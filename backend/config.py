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
    return int(get_env("PORT", "3001"))


def get_cors_origins() -> list[str]:
    raw_value = get_env("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_db_config() -> dict[str, str | int]:
    return {
        "host": get_env("DB_HOST", "localhost"),
        "port": int(get_env("DB_PORT", "3306")),
        "user": get_env("DB_USER"),
        "password": get_env("DB_PASSWORD"),
        "database": get_env("DB_NAME"),
        "charset": "utf8mb4",
    }


def get_ozon_cookie() -> str:
    """
    统一浏览器 Cookie：
    - 优先 OZON_COOKIE
    - 若为空则回退 OZON_SELLER_COOKIE（兼容旧配置）
    采集与卖家后台类目解析默认共用，避免重复粘贴。
    """
    primary = (os.getenv("OZON_COOKIE") or "").strip()
    if primary:
        return primary
    return (os.getenv("OZON_SELLER_COOKIE") or "").strip()


def get_ozon_seller_ui_cookie() -> str:
    """卖家后台 UI Cookie：有 OZON_SELLER_COOKIE 覆盖则用覆盖，否则复用 OZON_COOKIE。"""
    override = (os.getenv("OZON_SELLER_COOKIE") or "").strip()
    if override:
        return override
    return (os.getenv("OZON_COOKIE") or "").strip()


def ozon_cookie_configured() -> bool:
    return bool(get_ozon_cookie())


def ozon_browser_enabled() -> bool:
    return os.getenv("OZON_BROWSER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def ozon_browser_headless() -> bool:
    return os.getenv("OZON_BROWSER_HEADLESS", "true").strip().lower() not in ("0", "false", "no", "off")

