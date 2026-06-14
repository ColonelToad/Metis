"""
Log Rotation & Retention Policy
Manages lifecycle of logs: live (20 days) → archive (10 days) → delete

Usage:
    rotate_logs()  # Call periodically (e.g., start of each run)
"""

import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def rotate_logs(logs_dir: Path = None, live_days: int = 20, archive_days: int = 10):
    """
    Rotate logs based on age:
    - Last 20 days: uncompressed in logs/
    - Days 20-30: compressed in logs/archive/
    - After 30 days: deleted
    
    Args:
        logs_dir: Path to logs directory (default: research/logs)
        live_days: Keep uncompressed logs for this many days
        archive_days: Keep archived logs for this many additional days
    """
    if logs_dir is None:
        logs_dir = Path(__file__).parent / "logs"
    
    archive_dir = logs_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    now = datetime.now()
    live_cutoff = now - timedelta(days=live_days)
    archive_cutoff = now - timedelta(days=live_days + archive_days)
    
    # Process uncompressed logs in main logs/ directory
    for log_file in logs_dir.glob("*.log"):
        if not log_file.stat().st_mtime / 1000 > live_cutoff.timestamp():
            # File is older than live period, move to archive and compress
            compress_and_move_to_archive(log_file, archive_dir)
    
    # Process archived logs
    for log_file in archive_dir.glob("*.log.gz"):
        # Get creation time from file
        file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
        if file_time < archive_cutoff:
            # Older than archive period, delete
            log_file.unlink()
            print(f"Deleted archived log: {log_file.name}")


def compress_and_move_to_archive(log_file: Path, archive_dir: Path):
    """Compress a log file and move to archive"""
    archive_path = archive_dir / f"{log_file.name}.gz"
    
    with open(log_file, 'rb') as f_in:
        with gzip.open(archive_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    log_file.unlink()
    print(f"Archived and compressed: {log_file.name} → {archive_path.name}")


if __name__ == "__main__":
    rotate_logs()
    print("Log rotation complete")
