"""
Runtime mode configuration
- Mode is controlled by METIS_MODE env var: DEV (default) or REAL
- DEV: no external API calls; use synthetic/generator data
- REAL: call APIs when keys available
"""
import os
from dotenv import load_dotenv

load_dotenv()

MODE = os.getenv("METIS_MODE", "DEV").upper()


def is_real_mode() -> bool:
    return MODE == "REAL"


def mode_label() -> str:
    return MODE


def get_db_url(default="postgresql://postgres:postgres@localhost:5432/metis") -> str:
    return os.getenv("DB_URL", default)


def log_mode(prefix: str = ""):
    label = mode_label()
    msg = f"[{prefix}] Running in {label} mode"
    print(msg)


def require_real_mode(feature: str):
    if not is_real_mode():
        print(f"Skipping {feature}: METIS_MODE={MODE} (DEV)")
        return False
    return True
