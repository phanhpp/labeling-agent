"""Settings, read from the environment. For local runs, .env is loaded first."""

import os

from dotenv import load_dotenv

load_dotenv()  # never overrides a variable that is already set


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://labeler:labeler@localhost:5432/labeler")
