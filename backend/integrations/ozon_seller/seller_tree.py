from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from config import get_ozon_seller_ui_cookie


class OzonSellerTreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedCategory:
    description_category_id: str
    type_id: str
    raw: dict[str, Any]


def _pick_description_category_id_for_api(entry: dict[str, Any]) -> str | None:
    """
    Seller API（attribute / import）需要的是「类型所属类目」，
    对应 resolve/by-sku 的 level_3；level_4 会报 category ... is not found。
    """
    for key in (
        "description_category_id_level_3",
        "descriptionCategoryIdLevel3",
        "description_category_id",
        "descriptionCategoryId",
        "description_category_id_level_4",
        "description_category_id_level_2",
    ):
        value = entry.get(key)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if text.isdigit():
            return text
    return None


def _pick_type_id(entry: dict[str, Any]) -> str | None:
    for key in ("description_type_id", "descriptionTypeId", "type_id", "typeId"):
        value = entry.get(key)
        if value is None or value == "":
            continue
        text = str(value).strip()
        if text.isdigit():
            return text
    return None


def parse_resolved_categories_payload(
    payload: dict[str, Any],
    sku: str,
) -> ResolvedCategory | None:
    block = payload.get("resolved_categories_by_sku")
    if not isinstance(block, dict):
        return None

    sku_key = str(sku).strip()
    entry: Any = block.get(sku_key)
    if entry is None:
        for key, value in block.items():
            if str(key).strip() == sku_key:
                entry = value
                break
    if isinstance(entry, list):
        entry = next((item for item in entry if isinstance(item, dict)), None)
    if not isinstance(entry, dict):
        return None

    category_id = _pick_description_category_id_for_api(entry)
    type_id = _pick_type_id(entry)
    if not category_id or not type_id:
        return None
    return ResolvedCategory(
        description_category_id=category_id,
        type_id=type_id,
        raw=entry,
    )


class OzonSellerTreeClient:
    """卖家后台 UI 接口：用 SKU 解析 description_category_id / type_id。"""

    def __init__(
        self,
        *,
        cookie: str | None = None,
        company_id: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.cookie = (cookie if cookie is not None else get_ozon_seller_ui_cookie()).strip()
        self.company_id = (
            company_id if company_id is not None else os.getenv("OZON_SELLER_CLIENT_ID", "")
        ).strip()
        self.base_url = (
            base_url or os.getenv("OZON_SELLER_UI_BASE_URL") or "https://seller.ozon.ru"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("OZON_SELLER_TIMEOUT_SECONDS", "60")
        )

    def is_configured(self) -> bool:
        return bool(self.cookie and self.company_id)

    def resolve_by_sku(self, sku: str | int) -> ResolvedCategory:
        if not self.is_configured():
            raise OzonSellerTreeError(
                "未配置 OZON_COOKIE（或 OZON_SELLER_CLIENT_ID），"
                "无法自动解析 type_id / description_category_id"
            )

        sku_text = str(sku).strip()
        if not sku_text.isdigit():
            raise OzonSellerTreeError(f"无效的 Ozon SKU: {sku}")

        url = f"{self.base_url}/api/v1/seller-tree/resolve/by-sku"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/app/products/add/general-info",
            "Cookie": self.cookie,
            "x-o3-app-name": "seller-ui",
            "x-o3-company-id": self.company_id,
            "x-o3-language": "zh-Hans",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
        }
        # 官方请求体：ResolveBySKURequest.Skus（必须 1~1000 个）
        body = {"skus": [int(sku_text)]}

        try:
            response = requests.post(
                url,
                headers=headers,
                json=body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OzonSellerTreeError(f"seller-tree 请求失败: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw": response.text}

        if response.status_code >= 400:
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "")
            raise OzonSellerTreeError(
                f"seller-tree 错误 {response.status_code}: {message or response.text[:300]}"
            )

        if not isinstance(data, dict):
            raise OzonSellerTreeError("seller-tree 返回格式异常")

        resolved = parse_resolved_categories_payload(data, sku_text)
        if resolved is None:
            raise OzonSellerTreeError(f"未能解析 SKU {sku_text} 的类目/类型")
        return resolved


def try_resolve_by_sku(sku: str | int) -> ResolvedCategory | None:
    """采集用：未配置或失败时返回 None，不打断主流程。"""
    client = OzonSellerTreeClient()
    if not client.is_configured():
        return None
    try:
        return client.resolve_by_sku(sku)
    except OzonSellerTreeError:
        return None
