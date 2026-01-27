"""
Configuration settings for Metis research environment.
Load from .env file or environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
RESULTS_DIR = PROJECT_ROOT / "results"

# Create directories if they don't exist
for dir_path in [DATA_DIR, MODELS_DIR, RESULTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Database configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "metis")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# API Keys (keep these secret!)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
FRED_API_KEY = os.getenv("FRED_API_KEY")
CME_API_KEY = os.getenv("CME_API_KEY")
DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY")

# Rust execution engine connection
EXECUTION_ENGINE_HOST = os.getenv("EXECUTION_ENGINE_HOST", "localhost")
EXECUTION_ENGINE_PORT = int(os.getenv("EXECUTION_ENGINE_PORT", 8080))

# Model configuration
MODEL_VERSION = "v1.0"
LSTM_HIDDEN_SIZE = 128
LSTM_NUM_LAYERS = 2
SEQUENCE_LENGTH = 24  # hours
FORECAST_HORIZON = 1  # hours

# Trading configuration
TARGET_INSTRUMENT = "NG:CME"  # Henry Hub Natural Gas
CONTRACT_SIZE = 10000  # MMBtu per contract
TICK_SIZE = 0.001  # $0.001 per MMBtu
COMMISSION_PER_SIDE = 1.50  # USD

# Feature engineering
WEATHER_REGIONS = ["PERMIAN", "MARCELLUS", "HAYNESVILLE"]
GRID_NODES = ["PJM", "ERCOT", "CAISO"]

# Backtest settings
INITIAL_CAPITAL = 100000.0
MAX_POSITION_SIZE = 10  # contracts
RISK_PER_TRADE = 0.02  # 2% of capital

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = PROJECT_ROOT / "logs" / "metis.log"
