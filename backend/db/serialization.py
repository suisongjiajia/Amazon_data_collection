from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from db.connection import get_connection
from db.schema import JSON_FIELDS


def fetch_one(query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
    if row is None:
        return None
    return normalize_row(row)


def fetch_all(query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    return [normalize_row(row) for row in rows]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key, value in list(normalized.items()):
        if key in JSON_FIELDS and value is not None:
            normalized[key] = from_json(value)
        elif isinstance(value, datetime):
            normalized[key] = value.isoformat()
        elif isinstance(value, Decimal):
            normalized[key] = float(value)
    return normalized


def to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def from_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
