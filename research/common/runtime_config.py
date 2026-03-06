"""
Runtime mode configuration
- Mode is controlled by METIS_MODE env var: DEV (default), PROD, or REAL
- DEV: no external API calls; use synthetic/generator data
- PROD or REAL: call APIs when keys available
"""
import os
from dotenv import load_dotenv

load_dotenv()

MODE = os.getenv("METIS_MODE", "DEV").upper()


def is_real_mode() -> bool:
    """Check if running in production mode (REAL or PROD)."""
    return MODE in ("REAL", "PROD")


def mode_label() -> str:
    return MODE


def get_db_url(default="postgresql://postgres:postgres@localhost:5432/metis") -> str:
    return os.getenv("DB_URL", default)


def log_mode(prefix: str = ""):
    label = mode_label()
    msg = f"[{prefix}] Running in {label} mode"
    print(msg)


def require_real_mode(feature: str):
    """Check if real mode is enabled; print skip message if not."""
    if not is_real_mode():
        mode_str = "PROD" if MODE == "PROD" else MODE
        print(f"Skipping {feature}: METIS_MODE={mode_str} ({MODE})")
        return False
    return True
