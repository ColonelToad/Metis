#!/usr/bin/env python3
"""
R2 Auto-Backup for Daily Ingestion
Uploads database, cache, processed data, and ML features to CloudFlare R2.
Runs after successful ingestion to maintain cloud backup.

USAGE:
  python r2_auto_backup.py
  python r2_auto_backup.py --dry-run     # Preview without uploading
  python r2_auto_backup.py --db-only     # Backup only database
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import logging
from typing import Optional, Dict, List

# Fix SSL certificate issues on Windows
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

from dotenv import load_dotenv
import argparse

try:
    import boto3
except ImportError:
    print("✗ boto3 not installed. Install with: pip install boto3")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

load_dotenv()

# R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "metis")
R2_REGION = os.getenv("R2_REGION", "auto")

# Local data paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"
FEATURES_DIR = DATA_DIR / "features"
LANCE_DIR = DATA_DIR / "lance"
RAG_DIR = DATA_DIR / "rag_context"


class R2AutoBackup:
    """Handle R2 backups for daily ingestion."""
    
    def __init__(self, dry_run: bool = False):
        self.s3_client = None
        self.dry_run = dry_run
        self.stats = {
            "files": 0,
            "bytes": 0,
            "skipped": 0
        }
    
    def connect(self) -> bool:
        """Initialize S3 client for R2."""
        if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
            logger.error("✗ Missing R2 credentials in .env file")
            return False
        
        try:
            from botocore.config import Config
            
            config = Config(
                retries={'max_attempts': 3, 'mode': 'standard'},
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
                verify=certifi.where()
            )
            
            # Test connection
            self.s3_client.head_bucket(Bucket=R2_BUCKET_NAME)
            logger.info(f"✓ Connected to R2 bucket: {R2_BUCKET_NAME}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to R2: {e}")
            return False
    
    def upload_file(self, local_path: Path, r2_key: str) -> bool:
        """Upload a single file to R2."""
        if not local_path.exists():
            logger.warning(f"  ✗ File not found: {local_path}")
            self.stats["skipped"] += 1
            return False
        
        file_size = local_path.stat().st_size
        
        try:
            if self.dry_run:
                logger.info(f"  [DRY] {local_path.name:40} → {r2_key} ({self._format_bytes(file_size)})")
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
                r2_key = f"{r2_prefix}/{rel_path}".replace("\\", "/")
                
                if self.upload_file(file_path, r2_key):
                    files_uploaded += 1
        
        return files_uploaded
    
    def backup_all(self) -> bool:
        """Run complete backup routine."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        
        print(f"\n{'='*70}")
        print(f"R2 Auto Backup - {timestamp}")
        print(f"{'='*70}\n")
        
        if self.dry_run:
            print("[DRY RUN MODE] No files will be uploaded\n")
        
        # 1. Database
        logger.info("Backing up database...")
        db_path = DATA_DIR / "metis.db"
        if db_path.exists():
            self.upload_file(db_path, f"database/metis_{timestamp}.db")
        
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
        print(f"Skipped: {self.stats['skipped']}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"{'='*70}\n")
        
        return self.stats["skipped"] == 0
    
    @staticmethod
    def _format_bytes(bytes_size: int) -> str:
        """Format bytes as human-readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024:
                return f"{bytes_size:.1f}{unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f}TB"


def main():
    parser = argparse.ArgumentParser(
        description="Backup Metis data to CloudFlare R2 after daily ingestion"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview uploads without uploading"
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="Upload only database (not implemented in simple mode, use full script)"
    )
    args = parser.parse_args()
    
    backup = R2AutoBackup(dry_run=args.dry_run)
    
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
