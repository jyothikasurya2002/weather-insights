"""Environment configuration and project paths."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOG_FILE = DATA_DIR / "weather_log.csv"

load_dotenv(PROJECT_ROOT / "variables.env")


def get_api_key() -> str:
    """Return the OpenWeatherMap key from the environment.

    Read lazily (not at import time) so the tests and the Streamlit app
    can import the package without a key and show a friendly message
    instead of crashing.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if not api_key or api_key == "your_key_here":
        raise RuntimeError(
            "OPENWEATHER_API_KEY is not set. Copy variables.env.example to "
            "variables.env and fill in your own key."
        )
    return api_key
