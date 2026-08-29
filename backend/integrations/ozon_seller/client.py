from __future__ import annotations

import json
import os
from typing import Any

import requests


class OzonSellerError(RuntimeError):
    pass


class OzonSellerClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.client_id = (client_id or os.getenv("OZON_SELLER_CLIENT_ID") or "").strip()
        self.api_key = (api_key or os.getenv("OZON_SELLER_API_KEY") or "").strip()
        self.base_url = (base_url or os.getenv("OZON_SELLER_BASE_URL") or "https://api-seller.ozon.ru").rstrip("/")
        self.timeout_seconds = timeout_seconds or int(os.getenv("OZON_SELLER_TIMEOUT_SECONDS", "60"))

    def ensure_configured(self) -> None:
        if not self.client_id or not self.api_key:
            raise OzonSellerError("未配置 OZON_SELLER_CLIENT_ID 或 OZON_SELLER_API_KEY")

    def _headers(self) -> dict[str, str]:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.ensure_configured()
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(),
                json=payload or {},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OzonSellerError(f"Ozon Seller API 请求失败: {exc}") from exc

        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw": response.text}

        if response.status_code >= 400:
            message = data.get("message") or data.get("error") or response.text[:500]
            raise OzonSellerError(f"Ozon Seller API 错误 {response.status_code}: {message}")

        return data if isinstance(data, dict) else {"result": data}

    def import_products(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        # v3 要求 description_category_id + type_id
        return self.request("POST", "/v3/product/import", {"items": items})

    def get_import_info(self, task_id: int) -> dict[str, Any]:
        return self.request("POST", "/v1/product/import/info", {"task_id": task_id})

    def update_stocks(self, stocks: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request("POST", "/v2/products/stocks", {"stocks": stocks})
