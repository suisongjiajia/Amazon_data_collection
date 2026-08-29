from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlparse

import requests


class OssError(RuntimeError):
    pass


class AliyunOssClient:
    """轻量 OSS 上传（SignV1），不依赖 oss2，避免安装超时。"""

    def __init__(
        self,
        *,
        access_key_id: str | None = None,
        access_key_secret: str | None = None,
        endpoint: str | None = None,
        bucket: str | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self.access_key_id = (access_key_id or os.getenv("OSS_ACCESS_KEY_ID") or "").strip()
        self.access_key_secret = (access_key_secret or os.getenv("OSS_ACCESS_KEY_SECRET") or "").strip()
        self.endpoint = (endpoint or os.getenv("OSS_ENDPOINT") or "").strip().rstrip("/")
        self.bucket = (bucket or os.getenv("OSS_BUCKET") or "").strip()
        self.public_base_url = (
            public_base_url or os.getenv("OSS_PUBLIC_BASE_URL") or ""
        ).strip().rstrip("/")

    def ensure_configured(self) -> None:
        missing = [
            name
            for name, value in (
                ("OSS_ACCESS_KEY_ID", self.access_key_id),
                ("OSS_ACCESS_KEY_SECRET", self.access_key_secret),
                ("OSS_ENDPOINT", self.endpoint),
                ("OSS_BUCKET", self.bucket),
            )
            if not value
        ]
        if missing:
            raise OssError(f"未配置 OSS：{', '.join(missing)}")

    def _host(self) -> str:
        endpoint = self.endpoint.replace("https://", "").replace("http://", "")
        return f"{self.bucket}.{endpoint}"

    def public_url_for_key(self, key: str) -> str:
        key = key.lstrip("/")
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return f"https://{self._host()}/{key}"

    def upload_bytes(self, *, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        self.ensure_configured()
        key = key.lstrip("/")
        date = format_datetime(datetime.now(timezone.utc), usegmt=True)
        content_md5 = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
        canonical = (
            f"PUT\n{content_md5}\n{content_type}\n{date}\n/{self.bucket}/{key}"
        )
        signature = base64.b64encode(
            hmac.new(
                self.access_key_secret.encode("utf-8"),
                canonical.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("ascii")
        url = f"https://{self._host()}/{key}"
        headers = {
            "Date": date,
            "Content-Type": content_type,
            "Content-MD5": content_md5,
            "Authorization": f"OSS {self.access_key_id}:{signature}",
        }
        response = requests.put(url, data=data, headers=headers, timeout=60)
        if response.status_code not in {200, 201}:
            raise OssError(f"OSS 上传失败 {response.status_code}: {response.text[:300]}")
        return self.public_url_for_key(key)


def _guess_extension(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    suffix = os.path.splitext(path)[1].lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed == ".jpe":
            return ".jpg"
        if guessed:
            return guessed
    return ".jpg"


def _safe_sku_segment(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return text[:64] or "item"


def rehost_image_urls(
    image_urls: list[str],
    *,
    sku: str = "item",
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    client = AliyunOssClient()
    client.ensure_configured()

    uploaded: list[str] = []
    errors: list[dict[str, str]] = []
    sku_part = _safe_sku_segment(sku)

    for index, url in enumerate(image_urls):
        source = str(url or "").strip()
        if not source:
            continue
        if client.public_base_url and source.startswith(client.public_base_url):
            uploaded.append(source)
            continue
        try:
            response = requests.get(
                source,
                timeout=timeout_seconds,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
            )
            if response.status_code >= 400:
                raise OssError(f"下载失败 HTTP {response.status_code}")
            content_type = response.headers.get("Content-Type") or "image/jpeg"
            if "image" not in content_type and not source.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp")
            ):
                raise OssError(f"不是图片内容: {content_type}")
            ext = _guess_extension(source, content_type)
            key = f"products/{sku_part}/{index + 1}-{uuid.uuid4().hex[:8]}{ext}"
            public_url = client.upload_bytes(
                key=key,
                data=response.content,
                content_type=content_type if content_type.startswith("image/") else "image/jpeg",
            )
            uploaded.append(public_url)
        except Exception as exc:
            errors.append({"url": source, "error": str(exc)})

    if not uploaded:
        raise OssError("没有成功转存任何图片：" + (errors[0]["error"] if errors else "空列表"))

    return {"images": uploaded, "errors": errors, "count": len(uploaded)}
