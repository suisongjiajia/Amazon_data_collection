from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def get_env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def get_port() -> int:
    return int(get_env("PORT", "8000"))


def get_db_config() -> dict[str, str | int]:
    return {
        "host": get_env("DB_HOST", "localhost"),
        "port": int(get_env("DB_PORT", "3306")),
        "user": get_env("DB_USER"),
        "password": get_env("DB_PASSWORD"),
        "database": get_env("DB_NAME"),
        "charset": "utf8mb4",
    }
