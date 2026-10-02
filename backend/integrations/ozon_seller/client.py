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
            message = ""
            if isinstance(data, dict):
                message = str(
                    data.get("message")
                    or data.get("error")
                    or data.get("detail")
                    or ""
                ).strip()
                if not message and isinstance(data.get("result"), dict):
                    message = str(data["result"].get("message") or "").strip()
            raise OzonSellerError(
                f"Ozon Seller API 错误 {response.status_code}: {message or response.text[:500]}"
            )

        return data if isinstance(data, dict) else {"result": data}

    def import_products(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        # v3 要求 description_category_id + type_id
        return self.request("POST", "/v3/product/import", {"items": items})

    def import_prices(self, prices: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request("POST", "/v1/product/import/prices", {"prices": prices})

    def get_import_info(self, task_id: int) -> dict[str, Any]:
        return self.request("POST", "/v1/product/import/info", {"task_id": task_id})

    def get_description_category_attributes(
        self,
        *,
        description_category_id: int,
        type_id: int,
        language: str = "DEFAULT",
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/description-category/attribute",
            {
                "description_category_id": description_category_id,
                "type_id": type_id,
                "language": language,
            },
        )

    def get_attribute_values(
        self,
        *,
        attribute_id: int,
        description_category_id: int,
        type_id: int,
        language: str = "DEFAULT",
        limit: int = 100,
        last_value_id: int = 0,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/v1/description-category/attribute/values",
            {
                "attribute_id": attribute_id,
                "description_category_id": description_category_id,
                "type_id": type_id,
                "language": language,
                "limit": max(1, min(int(limit), 100)),
                "last_value_id": int(last_value_id or 0),
            },
        )

    def search_attribute_values(
        self,
        *,
        attribute_id: int,
        description_category_id: int,
        type_id: int,
        value: str,
        limit: int = 30,
    ) -> dict[str, Any]:
        query = str(value or "").strip()
        if len(query) < 2:
            raise OzonSellerError("attribute/values/search 需要至少 2 个字符")
        return self.request(
            "POST",
            "/v1/description-category/attribute/values/search",
            {
                "attribute_id": attribute_id,
                "description_category_id": description_category_id,
                "type_id": type_id,
                "value": query,
                "limit": max(1, min(int(limit), 100)),
            },
        )

    def update_stocks(self, stocks: list[dict[str, Any]]) -> dict[str, Any]:
        return self.request("POST", "/v2/products/stocks", {"stocks": stocks})

    def archive_products(self, product_ids: list[int | str]) -> dict[str, Any]:
        """将商品移入归档。单次最多 1000 个 product_id。"""
        ids: list[int] = []
        for pid in product_ids:
            text = str(pid).strip()
            if not text:
                continue
            try:
                ids.append(int(text))
            except (TypeError, ValueError) as exc:
                raise OzonSellerError(f"archive_products 非法 product_id: {pid!r}") from exc
        if not ids:
            raise OzonSellerError("archive_products 需要至少一个 product_id")
        return self.request("POST", "/v1/product/archive", {"product_id": ids[:1000]})

    def generate_barcodes(self, product_ids: list[int | str]) -> dict[str, Any]:
        ids = [str(pid).strip() for pid in product_ids if str(pid).strip()]
        if not ids:
            raise OzonSellerError("generate_barcodes 需要至少一个 product_id")
        return self.request("POST", "/v1/barcode/generate", {"product_ids": ids[:100]})

    def get_product_info_list(
        self,
        *,
        offer_ids: list[str] | None = None,
        product_ids: list[int | str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if offer_ids:
            payload["offer_id"] = [str(x).strip() for x in offer_ids if str(x).strip()]
        if product_ids:
            payload["product_id"] = [str(x).strip() for x in product_ids if str(x).strip()]
        if not payload:
            raise OzonSellerError("get_product_info_list 需要 offer_id 或 product_id")
        return self.request("POST", "/v3/product/info/list", payload)

    def list_products(
        self,
        *,
        visibility: str = "ALL",
        last_id: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        """分页列出商品。visibility 对应卖家后台筛选，如 READY_TO_SUPPLY / STATE_FAILED。"""
        return self.request(
            "POST",
            "/v3/product/list",
            {
                "filter": {"visibility": str(visibility or "ALL").strip() or "ALL"},
                "last_id": str(last_id or ""),
                "limit": max(1, min(int(limit), 1000)),
            },
        )

    def iter_product_ids(
        self,
        *,
        visibility: str,
        max_items: int = 500,
    ) -> list[dict[str, Any]]:
        """拉取某 visibility 下的 product_id / offer_id 列表（最多 max_items）。"""
        collected: list[dict[str, Any]] = []
        last_id = ""
        while len(collected) < max_items:
            page_limit = min(100, max_items - len(collected))
            data = self.list_products(visibility=visibility, last_id=last_id, limit=page_limit)
            result = data.get("result") if isinstance(data.get("result"), dict) else data
            items = result.get("items") if isinstance(result, dict) else None
            if not isinstance(items, list) or not items:
                break
            for row in items:
                if not isinstance(row, dict):
                    continue
                collected.append(
                    {
                        "product_id": row.get("product_id") or row.get("id"),
                        "offer_id": str(row.get("offer_id") or "").strip(),
                    }
                )
                if len(collected) >= max_items:
                    break
            next_id = str((result or {}).get("last_id") or "").strip()
            if not next_id or next_id == last_id:
                break
            last_id = next_id
        return collected
