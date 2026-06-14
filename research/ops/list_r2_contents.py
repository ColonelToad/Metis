#!/usr/bin/env python3
"""Verify uploaded files in R2"""
import os
from dotenv import load_dotenv
import boto3

load_dotenv()

s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name="auto",
)

print("\n" + "=" * 70)
print(f"Files in R2 bucket: {os.getenv('R2_BUCKET_NAME')}")
print("=" * 70 + "\n")

paginator = s3.get_paginator('list_objects_v2')
pages = paginator.paginate(Bucket=os.getenv('R2_BUCKET_NAME'))

total_size = 0
file_count = 0

for page in pages:
    if 'Contents' in page:
        for obj in page['Contents']:
            size_mb = obj['Size'] / (1024 * 1024)
            print(f"  {obj['Key']:<50} {size_mb:>8.2f} MB")
            total_size += obj['Size']
            file_count += 1

print(f"\n{'TOTAL:':<50} {total_size / (1024 * 1024):>8.2f} MB ({file_count} files)")
print("=" * 70)
