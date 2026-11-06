"""
TTL-based caching utilities for expensive API calls.
Provides decorators to cache function results with time-based expiry.

Caches are keyed by the decorated function's arguments. The previous version
kept a single slot per cache name, so a second call with different arguments
(e.g. NYISO after CAISO) silently received the first caller's result. That is
how grid_lmp_multi_iso ended up storing CAISO prices under NYISO/ISO-NE labels.
"""

import functools
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional


def _cache_key(args: tuple, kwargs: Dict[str, Any]) -> str:
    """Stable key from positional and keyword arguments.

    repr() is used instead of hash() so datetime/list arguments work and so the
    key is stable across processes (hash() is salted per interpreter).
    """
    parts = [repr(arg) for arg in args]
    parts.extend(f"{name}={value!r}" for name, value in sorted(kwargs.items()))
    return "|".join(parts)


class TTLCache:
    """
    Simple in-memory cache with time-to-live (TTL) expiration, keyed by call
    arguments. Persists per-key timestamps to disk to survive process restarts.
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
        self.cache_data: Dict[str, Any] = {}
        self.cache_timestamps: Dict[str, float] = {}
        self.metadata_dir = Path(__file__).parent.parent / "data" / "cache_metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.metadata_dir / f"{cache_name}_metadata.json"

        self._load_metadata()

    def _load_metadata(self):
        """Load cache metadata from disk."""
        if not self.metadata_file.exists():
            return
        try:
            with open(self.metadata_file, "r") as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load cache metadata: {e}")
            return

        keys = metadata.get("keys")
        if isinstance(keys, dict):
            for key, timestamp in keys.items():
                try:
                    self.cache_timestamps[key] = float(timestamp)
                except (TypeError, ValueError):
                    continue
        # Legacy files stored one anonymous timestamp. Its argument key was
        # never recorded, so it cannot be addressed safely; ignore it and let
        # the next call repopulate.

    def _save_metadata(self):
        """Save cache metadata to disk."""
        try:
            metadata = {"keys": self.cache_timestamps, "ttl_seconds": self.ttl_seconds}
            with open(self.metadata_file, "w") as f:
                json.dump(metadata, f)
        except Exception as e:
            print(f"Warning: Failed to save cache metadata: {e}")

    def _is_valid(self, key: str) -> bool:
        """Check if the entry for ``key`` is still valid (not expired)."""
        timestamp = self.cache_timestamps.get(key)
        if timestamp is None:
            return False
        elapsed = time.time() - timestamp
        is_valid = elapsed < self.ttl_seconds
        if not is_valid:
            print(f"[{self.cache_name}] Cache expired: {elapsed:.1f}s > {self.ttl_seconds}s TTL")
        return is_valid

    def get(self, key: str) -> Optional[Any]:
        """Get cached data for ``key`` if valid, None otherwise."""
        if key in self.cache_data and self._is_valid(key):
            elapsed = time.time() - self.cache_timestamps[key]
            print(f"[{self.cache_name}] Cache hit ({elapsed:.1f}s old, TTL={self.ttl_seconds}s)")
            return self.cache_data[key]
        return None

    def set(self, key: str, data: Any):
        """Store data for ``key`` with the current timestamp."""
        self.cache_data[key] = data
        self.cache_timestamps[key] = time.time()
        self._save_metadata()
        print(f"[{self.cache_name}] Cache refreshed (TTL={self.ttl_seconds}s)")


def ttl_cache(ttl_seconds: int, cache_name: str) -> Callable:
    """
    Decorator to cache function results with time-based expiry.

    Results are cached per distinct argument tuple, so callers with different
    parameters never share an entry.

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
            key = _cache_key(args, kwargs)

            cached_result = cache.get(key)
            if cached_result is not None:
                return cached_result

            print(f"[{cache_name}] Cache miss, calling {func.__name__}...")
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        return wrapper

    return decorator
