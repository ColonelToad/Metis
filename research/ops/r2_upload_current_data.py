"""
R2 Data Backfill Utility - Full Version
Uploads existing local data to Cloudflare R2 for backup and cloud access.

PREREQUISITES:
  - .env file configured with R2 credentials
  - R2 bucket created in CloudFlare dashboard
  - boto3 installed (pip install boto3)
  - SSL certificate validation working

SETUP STEPS IF SSL FAILS:
  1. Verify R2 credentials in CloudFlare dashboard are correct
  2. Try from a different machine/network if available
  3. On Windows, check certificate store (Control Panel > Internet Options > Content)
  4. Try: pip install --upgrade certifi
  5. Restart Python/kernel to load new certificates

USAGE:
  python r2_upload_current_data.py [OPTIONS]
  
OPTIONS:
  --dry-run              Simulate uploads without uploading
  --all                  Upload all data (default if no options)
  --processed-only       Upload only processed data
  --cache-only          Upload only cache data
  --db-only             Upload only database backup
  --list-only           List files that would be uploaded (no upload)
""" 

import os
import sys
from pathlib import Path
from datetime import datetime
import json
import logging
from typing import List, Dict, Optional, Tuple

# Fix SSL certificate issues on Windows
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

# Suppress urllib3 SSL warnings for testing
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except:
    pass

from dotenv import load_dotenv
import pandas as pd

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

# Validate credentials
if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
    logger.error("✗ Missing R2 credentials in .env file:")
    logger.error("  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY required")
    sys.exit(1)

R2_ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

# Local data paths
DATA_DIR = Path(__file__).parent.parent / "data"
PROCESSED_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"


class R2Uploader:
    """Handle uploads to Cloudflare R2."""
    
    def __init__(self):
        self.s3_client = None
        self.stats = {
            "processed": {"files": 0, "bytes": 0},
            "cache": {"files": 0, "bytes": 0},
            "database": {"files": 0, "bytes": 0}
        }
        self.files_list: List[Dict] = []
    
    def connect(self) -> bool:
        """Initialize S3 client for R2."""
        try:
            from botocore.config import Config
            
            # Configure with explicit CA bundle and SSL bypass for testing
            config = Config(
                retries={'max_attempts': 3, 'mode': 'standard'},
                s3={'addressing_style': 'path'},
                connect_timeout=10,
                read_timeout=10,
                max_pool_connections=10,
            )
            
            self.s3_client = boto3.client(
                service_name="s3",
                endpoint_url=R2_ENDPOINT,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name=R2_REGION,
                config=config,
                verify=certifi.where()  # Explicitly pass CA bundle path
            )
            # Test connection
            self.s3_client.head_bucket(Bucket=R2_BUCKET_NAME)
            logger.info(f"✓ Connected to R2 bucket: {R2_BUCKET_NAME}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to R2: {e}")
            logger.error("\nIf you see SSL errors, this is a system-level certificate issue.")
            logger.error("See docstring at top of this script for troubleshooting steps.")
            return False
    
    def upload_file(
        self,
        local_path: Path,
        r2_key: str,
        dry_run: bool = False
    ) -> bool:
        """Upload a single file to R2."""
        if not local_path.exists():
            logger.warning(f"  ✗ File not found: {local_path}")
            return False
        
        file_size = local_path.stat().st_size
        file_size_str = self._format_size(file_size)
        
        if dry_run:
            logger.info(f"  [DRY] {local_path.name:40} → {r2_key:50} ({file_size_str})")
            self.files_list.append({
                "local": str(local_path),
                "r2_key": r2_key,
                "size": file_size
            })
            return True
        
        try:
            logger.info(f"  ⬆  {local_path.name:40} ({file_size_str})...")
            self.s3_client.upload_file(str(local_path), R2_BUCKET_NAME, r2_key)
            return True
        except Exception as e:
            logger.error(f"  ✗ Upload failed: {e}")
            return False
    
    def collect_processed_files(self, dry_run: bool = False) -> Dict:
        """Collect stats on processed data files."""
        if not PROCESSED_DIR.exists():
            logger.warning(f" Processed directory not found: {PROCESSED_DIR}")
            return {"success": 0, "failed": 0, "skipped": 0}
        
        files = list(PROCESSED_DIR.glob("*"))
        success, failed = 0, 0
        backup_date = datetime.now().strftime("%Y-%m-%d")
        
        if not files:
            logger.info("  ⊘ No processed data files found")
            return {"success": 0, "failed": 0, "skipped": len(files)}
        
        for file_path in files:
            if not file_path.is_file():
                continue
            r2_key = f"backup/{backup_date}/processed/{file_path.name}"
            if self.upload_file(file_path, r2_key, dry_run):
                success += 1
                self.stats["processed"]["files"] += 1
                self.stats["processed"]["bytes"] += file_path.stat().st_size
            else:
                failed += 1
        
        return {"success": success, "failed": failed, "skipped": 0}
    
    def collect_cache_files(self, dry_run: bool = False) -> Dict:
        """Collect stats on cache files."""
        if not CACHE_DIR.exists():
            logger.warning(f"  Cache directory not found: {CACHE_DIR}")
            return {"success": 0, "failed": 0, "skipped": 0}
        
        success, failed, total = 0, 0, 0
        
        for subdir in CACHE_DIR.iterdir():
            if not subdir.is_dir():
                continue
            collection_name = subdir.name
            
            for file_path in subdir.glob("*"):
                if not file_path.is_file():
                    continue
                total += 1
                r2_key = f"cache/{collection_name}/{file_path.name}"
                if self.upload_file(file_path, r2_key, dry_run):
                    success += 1
                    self.stats["cache"]["files"] += 1
                    self.stats["cache"]["bytes"] += file_path.stat().st_size
                else:
                    failed += 1
        
        if total == 0:
            logger.info("  ⊘ No cache files found")
        return {"success": success, "failed": failed, "skipped": 0}
    
    def backup_database(self, dry_run: bool = False) -> Dict:
        """Backup SQLite database to R2."""
        db_path = DATA_DIR / "metis.db"
        
        if not db_path.exists():
            logger.info("  ⊘ Database not found")
            return {"success": 0, "failed": 0, "skipped": 1}
        
        backup_timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        r2_key = f"database/metis_{backup_timestamp}.db"
        
        success = 1 if self.upload_file(db_path, r2_key, dry_run) else 0
        if success:
            self.stats["database"]["files"] += 1
            self.stats["database"]["bytes"] += db_path.stat().st_size
        
        return {"success": success, "failed": 1 - success, "skipped": 0}
    
    @staticmethod
    def _format_size(bytes_val: int) -> str:
        """Format bytes to human-readable size."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f}{unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f}TB"
    
    def print_summary(self, dry_run: bool = False, list_only: bool = False):
        """Print upload summary."""
        print(f"\n{'='*80}")
        print("UPLOAD SUMMARY")
        print(f"{'='*80}")
        
        if dry_run:
            print(f"Mode: DRY RUN (no files will be uploaded)")
        if list_only:
            print(f"Mode: LIST ONLY (enumeration only)")
        
        print(f"Bucket: {R2_BUCKET_NAME}")
        print(f"Endpoint: {R2_ENDPOINT}")
        print()
        
        total_files = sum(s["files"] for s in self.stats.values())
        total_bytes = sum(s["bytes"] for s in self.stats.values())
        
        print("Data Summary:")
        print(f"  Processed: {self.stats['processed']['files']:3} files ({self._format_size(self.stats['processed']['bytes'])})")
        print(f"  Cache:     {self.stats['cache']['files']:3} files ({self._format_size(self.stats['cache']['bytes'])})")
        print(f"  Database:  {self.stats['database']['files']:3} files ({self._format_size(self.stats['database']['bytes'])})")
        print()
        print(f"  TOTAL:     {total_files:3} files ({self._format_size(total_bytes)})")
        print(f"{'='*80}\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Upload Metis data to Cloudflare R2 bucket",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument("--dry-run", action="store_true", help="Simulate uploads")
    parser.add_argument("--list-only", action="store_true", help="List files only (no upload)")
    parser.add_argument("--all", action="store_true", help="Upload all data (default)")
    parser.add_argument("--processed-only", action="store_true", help="Processed data only")
    parser.add_argument("--cache-only", action="store_true", help="Cache data only")
    parser.add_argument("--db-only", action="store_true", help="Database backup only")
    
    args = parser.parse_args()
    
    # Defaults
    if not any([args.processed_only, args.cache_only, args.db_only]):
        args.all = True
    
    if args.all:
        args.processed_only = args.cache_only = args.db_only = True
    
    # Initialize uploader
    uploader = R2Uploader()
    
    # Only connect if not doing dry-run or list-only
    if not (args.dry_run or args.list_only):
        if not uploader.connect():
            sys.exit(1)
    
    print(f"\n{'='*80}")
    print(f"Metis Data Upload to R2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    if args.dry_run:
        print("[MODE] DRY RUN - No files will be uploaded\n")
    
    if args.list_only:
        print("[MODE] LIST ONLY - Enumerating files without connecting to R2\n")
    
    # Upload sections
    if args.processed_only:
        logger.info("[1/3] Processed Data")
        uploader.collect_processed_files(args.dry_run or args.list_only)
    
    if args.cache_only:
        logger.info("[2/3] Cache Data")
        uploader.collect_cache_files(args.dry_run or args.list_only)
    
    if args.db_only:
        logger.info("[3/3] Database")
        uploader.backup_database(args.dry_run or args.list_only)
    
    # Print summary and file list
    uploader.print_summary(args.dry_run, args.list_only)
    
    if args.list_only and uploader.files_list:
        print(f"\nFiles to upload ({len(uploader.files_list)} total):")
        print(f"{'='*80}")
        total_size = 0
        for item in uploader.files_list:
            print(f"  {item['r2_key']:60} ({uploader._format_size(item['size'])})")
            total_size += item['size']
        print(f"{'='*80}")
        print(f"Total: {uploader._format_size(total_size)}\n")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
