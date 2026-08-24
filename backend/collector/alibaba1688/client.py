from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import time
from typing import Any
from urllib.parse import quote, urlencode

try:
    from curl_cffi import requests as http_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as http_requests  # type: ignore[no-redef]
    HAS_CURL_CFFI = False

from collector.alibaba1688.parser import parse_supplier_candidates

H5_API_BASE = "https://h5api.m.1688.com/h5"
APP_KEY = "12574478"
JSV = "2.7.5"
CUSTOMER_ID = "AIBUY"
BIZ_TYPE = "browser"

UPLOAD_API = "mtop.com.alibaba.global.select.aibuy.image.upload"
SEARCH_API = "mtop.com.alibaba.cbu.crossBorder.lp.imageSearch"


class Alibaba1688Client:
    def __init__(
        self,
        cookie: str | None = None,
        *,
        impersonate: str = "edge101",
        timeout: int = 60,
        max_results: int = 5,
    ) -> None:
        self.cookie = (cookie or os.getenv("1688_COOKIE", "")).strip()
        self.impersonate = os.getenv("1688_IMPERSONATE", impersonate).strip() or "edge101"
        self.timeout = int(os.getenv("1688_TIMEOUT_SECONDS", str(timeout)))
        self.max_results = int(os.getenv("1688_MAX_RESULTS", str(max_results)))
        self.session = self._build_session()

    def search_suppliers_by_image_url(self, image_url: str) -> list[dict[str, Any]]:
        if not self.cookie:
            raise ValueError("未配置 1688_COOKIE，请在 .env 中填入阿里牛顿登录 Cookie")

        normalized_url = self._normalize_image_url(image_url)
        upload_result = self._upload_image(normalized_url)
        alicdn_url = upload_result.get("imageUrl")
        region = upload_result.get("currentRegion")
        if not alicdn_url:
            raise RuntimeError("1688 图片上传未返回 imageUrl")
        if not region:
            region = upload_result.get("_fallbackRegion") or "0,0,800,800"

        search_page = self._image_search(alicdn_url, region)
        offers = search_page.get("data") or []
        if not isinstance(offers, list):
            offers = []
        candidates = parse_supplier_candidates(offers, limit=self.max_results)
        if not candidates:
            total = search_page.get("totalRecords") or "0"
            raise RuntimeError(
                "1688 图搜未返回供应商结果"
                f"（totalRecords={total}）。"
                "请确认 1688_COOKIE 未过期，或更换商品主图后重试"
            )
        return candidates

    @staticmethod
    def _normalize_image_url(image_url: str) -> str:
        url = image_url.strip()
        if "ozonstatic.cn" not in url or re.search(r"/wc\d+/", url, re.I):
            return url

        match = re.match(
            r"^(https?://[^/]+/s3/multimedia-[^/]+)/(?!wc\d+/)([^/?#]+\.(?:jpg|jpeg|png|webp))(?:\?.*)?$",
            url,
            re.I,
        )
        if match:
            return f"{match.group(1)}/wc500/{match.group(2)}"
        return url

    def _build_session(self) -> Any:
        if HAS_CURL_CFFI:
            return http_requests.Session(impersonate=self.impersonate)
        session = http_requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36 Edg/151.0.0.0"
                ),
            }
        )
        return session

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://air.1688.com",
            "Referer": "https://air.1688.com/",
            "Cookie": self.cookie,
        }

    def _upload_image(self, image_url: str) -> dict[str, Any]:
        image_bytes = self._download_image(image_url)
        encoded = base64.b64encode(image_bytes).decode("ascii")
        data_obj = {"bizType": BIZ_TYPE, "customerId": CUSTOMER_ID, "imageBase64": encoded}
        payload = self._mtop_post(UPLOAD_API, data_obj)
        result = (payload.get("data") or {}).get("result") or {}
        if not isinstance(result, dict) or not result.get("imageUrl"):
            raise RuntimeError(f"1688 图片上传响应异常: {payload}")
        if not result.get("currentRegion"):
            width, height = self._image_size(image_bytes)
            result["_fallbackRegion"] = f"0,0,{width},{height}"
        return result

    @staticmethod
    def _image_size(image_bytes: bytes) -> tuple[int, int]:
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(image_bytes) >= 24:
            width, height = struct.unpack(">II", image_bytes[16:24])
            if width > 0 and height > 0:
                return width, height

        if image_bytes[:2] == b"\xff\xd8":
            index = 2
            while index + 9 < len(image_bytes):
                if image_bytes[index] != 0xFF:
                    break
                marker = image_bytes[index + 1]
                if marker in {
                    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
                }:
                    height, width = struct.unpack(">HH", image_bytes[index + 5 : index + 9])
                    if width > 0 and height > 0:
                        return width, height
                segment_length = struct.unpack(">H", image_bytes[index + 2 : index + 4])[0]
                index += 2 + segment_length

        return 800, 800

    def _image_search(self, image_address: str, image_region: str) -> dict[str, Any]:
        search_param = json.dumps(
            {
                "imageAddress": image_address,
                "imageRegion": image_region,
                "beginPage": 1,
                "pageSize": self.max_results,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        data_obj = {
            "bizType": BIZ_TYPE,
            "customerId": CUSTOMER_ID,
            "language": "zh",
            "currency": "CNY",
            "searchParam": search_param,
        }
        payload = self._mtop_get(
            SEARCH_API,
            data_obj,
            path_segment="mtop.com.alibaba.cbu.crossborder.lp.imagesearch",
        )
        result = (payload.get("data") or {}).get("result") or {}
        if not isinstance(result, dict):
            raise RuntimeError(f"1688 图搜响应异常: {payload}")
        return result

    def _download_image(self, image_url: str) -> bytes:
        response = self.session.get(image_url, timeout=self.timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"下载商品主图失败: HTTP {response.status_code}")
        content = response.content
        if not content:
            raise RuntimeError("下载商品主图失败: 空内容")
        return content

    def _mtop_post(self, api: str, data_obj: dict[str, Any]) -> dict[str, Any]:
        data_str = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
        t = str(int(time.time() * 1000))
        sign = self._build_sign(t, data_str)
        query = urlencode(
            {
                "jsv": JSV,
                "appKey": APP_KEY,
                "t": t,
                "sign": sign,
                "ecode": "1",
                "type": "json",
                "valueType": "string",
                "api": api,
                "v": "1.0",
                "dataType": "json",
            }
        )
        url = f"{H5_API_BASE}/{api}/1.0/?{query}"
        response = self.session.post(
            url,
            data=f"data={quote(data_str)}",
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _mtop_get(
        self,
        api: str,
        data_obj: dict[str, Any],
        *,
        path_segment: str,
    ) -> dict[str, Any]:
        data_str = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
        t = str(int(time.time() * 1000))
        sign = self._build_sign(t, data_str)
        query = urlencode(
            {
                "jsv": JSV,
                "appKey": APP_KEY,
                "t": t,
                "sign": sign,
                "api": api,
                "v": "1.0",
                "H5Request": "true",
                "type": "json",
                "dataType": "json",
                "data": data_str,
            }
        )
        url = f"{H5_API_BASE}/{path_segment}/1.0/?{query}"
        response = self.session.get(url, headers=self._headers(), timeout=self.timeout)
        return self._parse_response(response)

    def _build_sign(self, timestamp: str, data_str: str) -> str:
        token = self._h5_token()
        raw = f"{token}&{timestamp}&{APP_KEY}&{data_str}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _h5_token(self) -> str:
        match = re.search(r"_m_h5_tk=([^;]+)", self.cookie)
        if not match:
            raise ValueError("1688_COOKIE 缺少 _m_h5_tk，请从已登录的阿里牛顿页面重新复制 Cookie")
        token_part = match.group(1).split("_", 1)[0]
        if not token_part:
            raise ValueError("1688_COOKIE 中 _m_h5_tk 格式无效")
        return token_part

    def _parse_response(self, response: Any) -> dict[str, Any]:
        if response.status_code >= 400:
            raise RuntimeError(f"1688 请求失败: HTTP {response.status_code}")
        text = response.text.strip()
        if text.startswith("mtopjsonp") or re.match(r"mtopjsonp\d*\s*\(", text):
            text = text[text.index("(") + 1 : text.rindex(")")]
        payload = json.loads(text)
        ret = payload.get("ret") or []
        if ret and not any(str(item).startswith("SUCCESS") for item in ret):
            raise RuntimeError(f"1688 接口错误: {ret}")
        return payload
