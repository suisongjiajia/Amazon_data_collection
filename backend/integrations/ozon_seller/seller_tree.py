from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import requests

from config import get_ozon_seller_ui_cookie
from integrations.ozon_seller.cdp_seller import (
    SELLER_HOME_URL,
    pull_seller_cookie_from_cdp,
    resolve_by_sku_via_cdp,
    seller_cdp_enabled,
)

logger = logging.getLogger(__name__)


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
        self._cookie_override = (cookie or "").strip() if cookie is not None else None
        self.company_id = (
            company_id if company_id is not None else os.getenv("OZON_SELLER_CLIENT_ID", "")
        ).strip()
        self.base_url = (
            base_url or os.getenv("OZON_SELLER_UI_BASE_URL") or "https://seller.ozon.ru"
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("OZON_SELLER_TIMEOUT_SECONDS", "60")
        )
        self.cookie = ""

    def is_configured(self) -> bool:
        if not self.company_id:
            return False
        if self._cookie_override is not None:
            return bool(self._cookie_override)
        if seller_cdp_enabled():
            return True
        return bool(get_ozon_seller_ui_cookie())

    def resolve_by_sku(self, sku: str | int) -> ResolvedCategory:
        if not self.company_id:
            raise OzonSellerTreeError(
                "缺少 OZON_SELLER_CLIENT_ID，无法自动解析 type_id / description_category_id"
            )

        sku_text = str(sku).strip()
        if not sku_text.isdigit():
            raise OzonSellerTreeError(f"无效的 Ozon SKU: {sku}")

        # 1) 优先：调试 Chrome 同源 fetch（最稳，免手贴 Cookie）
        if seller_cdp_enabled() and self._cookie_override is None:
            try:
                payload = resolve_by_sku_via_cdp(sku_text, timeout_ms=self.timeout_seconds * 1000)
                resolved = parse_resolved_categories_payload(payload, sku_text)
                if resolved is not None:
                    return resolved
                raise OzonSellerTreeError(f"未能解析 SKU {sku_text} 的类目/类型（CDP）")
            except Exception as exc:
                logger.warning("seller-tree CDP resolve failed, fallback to cookie HTTP: %s", exc)
                cdp_error = str(exc)
                # 未登录 / 反爬时直接提示，避免再用过期 Cookie 打一次
                lower = cdp_error.lower()
                if (
                    "challenge" in lower
                    or "反爬" in cdp_error
                    or "未登录" in cdp_error
                    or "人机验证" in cdp_error
                    or "unauthenticated" in lower
                    or "401" in cdp_error
                ):
                    raise OzonSellerTreeError(cdp_error) from exc
        else:
            cdp_error = ""

        # 2) Cookie HTTP：CDP Cookie > 显式传入 > .env
        self.cookie = self._resolve_cookie()
        if not self.cookie:
            hint = cdp_error or (
                f"请运行 start-ozon-chrome.ps1，在调试 Chrome 登录 {SELLER_HOME_URL}，"
                "或配置 OZON_COOKIE"
            )
            raise OzonSellerTreeError(f"无法获取卖家后台登录态。{hint}")

        return self._resolve_by_sku_http(sku_text)

    def _resolve_cookie(self) -> str:
        if self._cookie_override is not None:
            return self._cookie_override
        if seller_cdp_enabled():
            try:
                header = pull_seller_cookie_from_cdp(refresh=False)
                if header:
                    return header
            except Exception as exc:
                logger.warning("pull seller cookie from CDP failed: %s", exc)
        return get_ozon_seller_ui_cookie()

    def _resolve_by_sku_http(self, sku_text: str) -> ResolvedCategory:
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
                message = str(data.get("message") or data.get("error") or data)
                if data.get("challengeURL") or data.get("incidentId"):
                    raise OzonSellerTreeError(
                        "seller-tree 被反爬拦截。"
                        f"请在调试 Chrome 打开并完成验证：{SELLER_HOME_URL}"
                    )
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
