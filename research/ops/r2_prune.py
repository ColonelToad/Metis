#!/usr/bin/env python3
"""
R2 retention pruner — keeps bucket under the 10 GB free tier.

Default policy (as discussed): keep the 5 most recent database snapshots
plus the first snapshot of each prior month. Everything else under
database/ is deleted. Other prefixes (lance, cache, features) are left
alone — lance is rebuildable but slow, cache/features are already
incrementally skipped and tiny.

USAGE:
  python r2_prune.py --dry-run          # preview what would be deleted
  python r2_prune.py                    # actually delete
  python r2_prune.py --keep-last 3      # tighter
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import certifi
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv("C:/Users/legot/Metis/.env")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_BUCKET = os.getenv("R2_BUCKET_NAME", "metis")

ENDPOINT = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
S3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
    config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    verify=certifi.where(),
)

# database/metis_2026-09-02_070038.db  -> 2026-09-02 07:00:38
DB_RE = re.compile(r"database/metis_(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})\.db")


def parse_db_key(key: str):
    m = DB_RE.match(key)
    if not m:
        return None
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    int(m.group(4)), int(m.group(5)), int(m.group(6)))


def list_db_objects():
    paginator = S3.get_paginator("list_objects_v2")
    objs = []
    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix="database/"):
        for obj in page.get("Contents", []):
            dt = parse_db_key(obj["Key"])
            if dt is None:
                continue
            objs.append((obj["Key"], obj["Size"], dt))
    objs.sort(key=lambda x: x[2], reverse=True)  # newest first
    return objs


def choose_keep(objs, keep_last: int):
    if not objs:
        return set()
    # 1) keep N most recent
    keep = set(k for k, _, _ in objs[:keep_last])
    # 2) keep first snapshot of each prior month not already kept
    #    (group by YYYY-MM, pick earliest in that month)
    by_month: dict[str, list] = defaultdict(list)
    for k, _, dt in objs:
        by_month[dt.strftime("%Y-%m")].append((dt, k))
    for month, pairs in by_month.items():
        pairs.sort(key=lambda x: x[0])  # earliest in month
        keep.add(pairs[0][1])
    return keep


def main():
    parser = argparse.ArgumentParser(description="Prune old database snapshots in R2")
    parser.add_argument("--keep-last", type=int, default=5, help="keep N most recent DB snapshots")
    parser.add_argument("--dry-run", action="store_true", help="preview without deleting")
    args = parser.parse_args()

    objs = list_db_objects()
    if not objs:
        print("No database objects found.")
        return 0

    total_bytes = sum(s for _, s, _ in objs)
    print(f"Found {len(objs)} database snapshots, {total_bytes / (1024**3):.2f} GB total")
    for k, s, dt in objs[:8]:
        print(f"  {dt:%Y-%m-%d %H:%M}  {s/(1024**2):7.1f} MB  {k}")
    if len(objs) > 8:
        print(f"  ... and {len(objs)-8} older")

    keep = choose_keep(objs, args.keep_last)
    delete = [(k, s) for k, s, _ in objs if k not in keep]
    keep_bytes = sum(s for k, s, _ in objs if k in keep)
    delete_bytes = sum(s for _, s in delete)

    print(f"\nPolicy: keep-last={args.keep_last} + first-per-month")
    print(f"Keep:   {len(keep):3d} files, {keep_bytes/(1024**3):.2f} GB")
    print(f"Delete: {len(delete):3d} files, {delete_bytes/(1024**3):.2f} GB")
    if delete:
        print(f"Bucket after: {(total_bytes - delete_bytes)/(1024**3):.2f} GB (database prefix)")

    if not delete:
        print("Nothing to delete.")
        return 0

    if args.dry_run:
        print("\n[DRY RUN] No files deleted. Re-run without --dry-run to execute.")
        for k, s in delete[:10]:
            print(f"  would delete {k} ({s/(1024**2):.1f} MB)")
        if len(delete) > 10:
            print(f"  ... and {len(delete)-10} more")
        return 0

    print(f"\nDeleting {len(delete)} files...")
    # Batch in groups of 1000 (S3 limit)
    for i in range(0, len(delete), 1000):
        batch = delete[i:i+1000]
        resp = S3.delete_objects(
            Bucket=R2_BUCKET,
            Delete={"Objects": [{"Key": k} for k, _ in batch], "Quiet": True},
        )
        errs = resp.get("Errors") or []
        if errs:
            for e in errs:
                print(f"  ERROR {e['Key']}: {e['Message']}", file=sys.stderr)
            return 1
        print(f"  deleted {len(batch)}")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
