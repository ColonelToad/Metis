#!/usr/bin/env python3
"""
R2 Auto-Backup for Daily Ingestion
Uploads database, cache, processed data, and ML features to CloudFlare R2.
Runs after successful ingestion to maintain cloud backup.

USAGE:
  python r2_auto_backup.py
  python r2_auto_backup.py --dry-run     # Preview without uploading
  python r2_auto_backup.py --db-only     # Backup only database
  python r2_auto_backup.py --force-full  # Re-upload everything, ignoring unchanged-state

INCREMENTAL BEHAVIOR:
  Before uploading, the script lists every object already in the bucket
  (one paginated list_objects_v2 pass) and skips local files whose size
  and mtime match the remote copy. Only new/changed files and the
  timestamped DB snapshot are transferred each run.
"""

import logging
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Fix SSL certificate issues on Windows
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()

import argparse

from dotenv import load_dotenv

try:
    import boto3
except ImportError:
    print("✗ boto3 not installed. Install with: pip install boto3")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

load_dotenv()

# R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "metis")
R2_REGION = os.getenv("R2_REGION", "auto")

# Local data paths
# Ingesters resolve DB_URL (and features/cache dirs) relative to the repo root,
# so all paths here are anchored to the repo root, not to this file's location.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RESEARCH_DATA_DIR = REPO_ROOT / "research" / "data"
PROCESSED_DIR = RESEARCH_DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"
FEATURES_DIR = DATA_DIR / "features"
LANCE_DIR = DATA_DIR / "lance"
RAG_DIR = DATA_DIR / "rag_context"

# Transient / re-downloadable caches that must NOT be backed up (huge, ephemeral)
R2_EXCLUDE_DIRS = {"gdelt_gkg", "lbnl", "cme_browser", ".tmp"}

MAX_DB_AGE_HOURS = 48


def resolve_db_path() -> Optional[Path]:
    """Resolve the SQLite DB path from DB_URL, falling back to <repo>/data/metis.db."""
    db_url = os.getenv("DB_URL", "").strip()
    if not db_url.lower().startswith("sqlite"):
        return None
    if ":memory:" in db_url or "mode=memory" in db_url:
        return None
    prefix = "sqlite:///" if db_url.startswith("sqlite:///") else "sqlite://"
    raw = db_url[len(prefix) :].split("?", 1)[0]
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


DB_PATH = resolve_db_path() or (DATA_DIR / "metis.db")


class R2AutoBackup:
    """Handle R2 backups for daily ingestion."""

    def __init__(self, dry_run: bool = False, force_full: bool = False):
        self.s3_client = None
        self.dry_run = dry_run
        self.force_full = force_full
        # key -> (size, last_modified) for objects already in the bucket;
        # populated once per run so unchanged files can be skipped locally.
        self.remote_manifest = None
        self.stats = {"files": 0, "bytes": 0, "skipped": 0, "unchanged": 0}

    def connect(self) -> bool:
        """Initialize S3 client for R2."""
        if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
            logger.error("✗ Missing R2 credentials in .env file")
            return False

        try:
            from botocore.config import Config

            config = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=10,
            )

            endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

            self.s3_client = boto3.client(
                service_name="s3",
                endpoint_url=endpoint,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name=R2_REGION,
                config=config,
                verify=certifi.where(),
            )

            # Test connection
            self.s3_client.head_bucket(Bucket=R2_BUCKET_NAME)
            logger.info(f"✓ Connected to R2 bucket: {R2_BUCKET_NAME}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to R2: {e}")
            return False

    def load_remote_manifest(self) -> None:
        """List every object already in the bucket (sizes + timestamps)."""
        self.remote_manifest = {}
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
                for obj in page.get("Contents", []):
                    self.remote_manifest[obj["Key"]] = (obj["Size"], obj["LastModified"])
            logger.info(f"  Remote manifest: {len(self.remote_manifest)} objects already in R2")
        except Exception as e:
            logger.warning(f"  Could not list existing objects ({e}); will upload everything")
            self.remote_manifest = {}

    def _is_unchanged(self, local_path: Path, r2_key: str) -> bool:
        """True when the remote copy matches local size and is not older
        than the local file (5s clock-skew tolerance)."""
        if self.force_full or not self.remote_manifest:
            return False
        entry = self.remote_manifest.get(r2_key)
        if entry is None:
            return False
        remote_size, remote_last_modified = entry
        if local_path.stat().st_size != remote_size:
            return False
        local_mtime_utc = datetime.fromtimestamp(local_path.stat().st_mtime, tz=timezone.utc)
        return local_mtime_utc <= remote_last_modified + timedelta(seconds=5)

    def upload_file(self, local_path: Path, r2_key: str) -> bool:
        """Upload a single file to R2 unless the remote copy is identical."""
        if not local_path.exists():
            logger.warning(f"  ✗ File not found: {local_path}")
            self.stats["skipped"] += 1
            return False

        file_size = local_path.stat().st_size

        if self._is_unchanged(local_path, r2_key):
            if self.dry_run:
                logger.info(f"  ⏭  {local_path.name:40} unchanged - would skip")
            self.stats["unchanged"] += 1
            return True

        try:
            if self.dry_run:
                logger.info(
                    f"  [DRY] {local_path.name:40} → {r2_key} ({self._format_bytes(file_size)})"
                )
            else:
                logger.info(f"  ⬆  {local_path.name:40} ({self._format_bytes(file_size)})...")
                self.s3_client.upload_file(str(local_path), R2_BUCKET_NAME, r2_key)
                logger.info(f"      ✓ Uploaded to {r2_key}")

            self.stats["files"] += 1
            self.stats["bytes"] += file_size
            return True
        except Exception as e:
            logger.error(f"  ✗ Upload failed: {e}")
            self.stats["skipped"] += 1
            return False

    def upload_directory(self, local_dir: Path, r2_prefix: str) -> int:
        """Upload all files from a directory to R2 with a prefix."""
        if not local_dir.exists():
            logger.warning(f"  Directory not found: {local_dir}")
            return 0

        files_uploaded = 0
        for file_path in local_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(local_dir)
                # Skip transient caches (gdelt raw zips, lbnl xlsx, browser profiles)
                if local_dir == CACHE_DIR and rel_path.parts[0] in R2_EXCLUDE_DIRS:
                    continue
                r2_key = f"{r2_prefix}/{rel_path}".replace("\\", "/")

                if self.upload_file(file_path, r2_key):
                    files_uploaded += 1

        return files_uploaded

    def snapshot_database(self, src: Path, dest: Path) -> bool:
        """Create a consistent copy of the SQLite DB via the backup API."""
        try:
            import sqlite3

            src_conn = sqlite3.connect(f"{src.as_uri()}?mode=ro", uri=True)
            dest_conn = sqlite3.connect(dest)
            try:
                src_conn.backup(dest_conn)
            finally:
                src_conn.close()
                dest_conn.close()
            return True
        except Exception as e:
            logger.warning(f"  SQLite backup API failed ({e}); falling back to raw copy")
            try:
                shutil.copy2(src, dest)
                return True
            except Exception as copy_err:
                logger.error(f"  ✗ Snapshot failed: {copy_err}")
                return False

    def backup_database(self, timestamp: str) -> bool:
        """Snapshot and upload the database, refusing stale sources."""
        logger.info(f"  Source: {DB_PATH}")

        if not DB_PATH.exists():
            logger.error(f"  ✗ Database not found: {DB_PATH}")
            self.stats["skipped"] += 1
            return False

        age_hours = (
            datetime.now() - datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        ).total_seconds() / 3600
        if age_hours > MAX_DB_AGE_HOURS:
            logger.error(
                f"  ✗ Database is stale (last modified {age_hours:.1f}h ago, "
                f"threshold {MAX_DB_AGE_HOURS}h) - refusing to upload"
            )
            self.stats["skipped"] += 1
            return False

        temp_snapshot = Path(tempfile.gettempdir()) / f"metis_backup_{os.getpid()}_{timestamp}.db"
        try:
            if self.snapshot_database(DB_PATH, temp_snapshot):
                return self.upload_file(temp_snapshot, f"database/metis_{timestamp}.db")
            self.stats["skipped"] += 1
            return False
        finally:
            if temp_snapshot.exists():
                temp_snapshot.unlink()

    def backup_all(self) -> bool:
        """Run complete backup routine."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

        print(f"\n{'='*70}")
        print(f"R2 Auto Backup - {timestamp}")
        print(f"{'='*70}\n")

        if self.dry_run:
            print("[DRY RUN MODE] No files will be uploaded\n")

        logger.info(f"Repo root: {REPO_ROOT}")
        logger.info(f"Database:  {DB_PATH}")

        # 0. Build the remote manifest for incremental skipping
        if not self.force_full:
            logger.info("Listing existing R2 objects (incremental mode)...")
            self.load_remote_manifest()
        else:
            logger.info("Force-full mode: uploading everything")

        # 1. Database
        logger.info("Backing up database...")
        self.backup_database(timestamp)

        # 2. Processed data
        logger.info("Backing up processed data...")
        if PROCESSED_DIR.exists():
            self.upload_directory(PROCESSED_DIR, "processed")

        # 3. Cache (LMP data, etc.)
        logger.info("Backing up cache data...")
        if CACHE_DIR.exists():
            self.upload_directory(CACHE_DIR, "cache")

        # 4. Features
        logger.info("Backing up ML features...")
        if FEATURES_DIR.exists():
            self.upload_directory(FEATURES_DIR, "features")

        # 5. Lance (vector DB)
        logger.info("Backing up Lance indices...")
        if LANCE_DIR.exists():
            self.upload_directory(LANCE_DIR, "lance")

        # Print summary
        print(f"\n{'='*70}")
        print("BACKUP SUMMARY")
        print(f"{'='*70}")
        print(f"Files uploaded: {self.stats['files']}")
        print(f"Total size: {self._format_bytes(self.stats['bytes'])}")
        print(f"Unchanged (skipped): {self.stats['unchanged']}")
        print(f"Skipped (failed/missing): {self.stats['skipped']}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"{'='*70}\n")

        return self.stats["skipped"] == 0

    @staticmethod
    def _format_bytes(bytes_size: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f}{unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f}TB"


def main():
    parser = argparse.ArgumentParser(
        description="Backup Metis data to CloudFlare R2 after daily ingestion"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview uploads without uploading")
    parser.add_argument(
        "--force-full", action="store_true", help="Re-upload all files even if unchanged in R2"
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Upload only database (not implemented in simple mode, use full script)",
    )
    args = parser.parse_args()

    backup = R2AutoBackup(dry_run=args.dry_run, force_full=args.force_full)

    if not backup.connect():
        logger.error("Failed to connect to R2")
        return 1

    try:
        success = backup.backup_all()
        return 0 if success else 1
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
