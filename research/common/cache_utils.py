"""
TTL-based caching utilities for expensive API calls.
Provides decorators to cache function results with time-based expiry.
"""

import time
import functools
from typing import Callable, Any, Optional
from pathlib import Path
import json


class TTLCache:
    """
    Simple in-memory cache with time-to-live (TTL) expiration.
    Persists cache metadata to disk to survive process restarts.
    """

    def __init__(self, ttl_seconds: int, cache_name: str):
        """
        Initialize TTL cache.

        Args:
            ttl_seconds: Time-to-live in seconds
            cache_name: Name for cache metadata file (e.g., 'lmp_fetch')
        """
        self.ttl_seconds = ttl_seconds
        self.cache_name = cache_name
        self.cache_data = None
        self.cache_timestamp = None
        self.metadata_dir = Path(__file__).parent.parent / "data" / "cache_metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.metadata_dir / f"{cache_name}_metadata.json"

        self._load_metadata()

    def _load_metadata(self):
        """Load cache metadata from disk."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    metadata = json.load(f)
                    self.cache_timestamp = metadata.get("timestamp")
            except Exception as e:
                print(f"Warning: Failed to load cache metadata: {e}")
                self.cache_timestamp = None

    def _save_metadata(self):
        """Save cache metadata to disk."""
        try:
            metadata = {"timestamp": self.cache_timestamp, "ttl_seconds": self.ttl_seconds}
            with open(self.metadata_file, "w") as f:
                json.dump(metadata, f)
        except Exception as e:
            print(f"Warning: Failed to save cache metadata: {e}")

    def is_valid(self) -> bool:
        """Check if cache is still valid (not expired)."""
        if self.cache_timestamp is None:
            return False
        elapsed = time.time() - self.cache_timestamp
        is_valid = elapsed < self.ttl_seconds
        if not is_valid:
            print(
                f"[{self.cache_name}] Cache expired: {elapsed:.1f}s > {self.ttl_seconds}s TTL"
            )
        return is_valid

    def get(self) -> Optional[Any]:
        """Get cached data if valid, None if expired or not cached."""
        if self.cache_data is not None and self.is_valid():
            elapsed = time.time() - self.cache_timestamp
            print(f"[{self.cache_name}] Cache hit ({elapsed:.1f}s old, TTL={self.ttl_seconds}s)")
            return self.cache_data
        return None

    def set(self, data: Any):
        """Store data in cache with current timestamp."""
        self.cache_data = data
        self.cache_timestamp = time.time()
        self._save_metadata()
        print(f"[{self.cache_name}] Cache refreshed (TTL={self.ttl_seconds}s)")


def ttl_cache(ttl_seconds: int, cache_name: str) -> Callable:
    """
    Decorator to cache function results with time-based expiry.

    Args:
        ttl_seconds: Time-to-live in seconds (e.g., 3600 for 1 hour)
        cache_name: Name for this cache (used in logging and metadata)

    Example:
        @ttl_cache(ttl_seconds=3600, cache_name="lmp_fetch")
        def fetch_expensive_data(param1, param2):
            # ... expensive API call ...
            return result
    """

    cache = TTLCache(ttl_seconds, cache_name)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Try to get from cache
            cached_result = cache.get()
            if cached_result is not None:
                return cached_result

            # Cache miss or expired: call the function
            print(f"[{cache_name}] Cache miss, calling {func.__name__}...")
            result = func(*args, **kwargs)

            # Store in cache
            cache.set(result)
            return result

        return wrapper

    return decorator
