"""通义千问图像生成（qwen-image），经 MaaS 兼容网关。"""

from __future__ import annotations

import os
import re
from typing import Any

import requests


class QwenImageError(RuntimeError):
    pass


class QwenImageClient:
    """
    调用示例网关：
    POST {base}/api/v1/services/aigc/multimodal-generation/generation
    model: qwen-image-3.0
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("QWEN_IMAGE_API_KEY")
            or ""
        ).strip()
        self.base_url = (
            base_url
            or os.getenv("QWEN_IMAGE_BASE_URL")
            or "https://maas.qianwenaiapi.com"
        ).rstrip("/")
        self.model = (model or os.getenv("QWEN_IMAGE_MODEL") or "qwen-image-3.0").strip()
        self.timeout_seconds = timeout_seconds or int(os.getenv("QWEN_IMAGE_TIMEOUT_SECONDS", "180"))

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise QwenImageError("未配置 DASHSCOPE_API_KEY（或 QWEN_IMAGE_API_KEY）")

    def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        prompt_extend: bool = False,
        size: str | None = None,
        negative_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        文生图：只传 prompt。
        图生图/编辑：再传 image_url（公网可访问的原图）。
        返回原始 JSON，并尽量解析出 images 列表。
        """
        self.ensure_configured()
        text = str(prompt or "").strip()
        if not text:
            raise QwenImageError("prompt 不能为空")

        content: list[dict[str, Any]] = []
        if image_url:
            content.append({"image": str(image_url).strip()})
        content.append({"text": text})

        parameters: dict[str, Any] = {
            "prompt_extend": bool(prompt_extend),
        }
        if size:
            parameters["size"] = size
        if negative_prompt:
            parameters["negative_prompt"] = negative_prompt

        payload = {
            "model": self.model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": parameters,
        }
        url = f"{self.base_url}/api/v1/services/aigc/multimodal-generation/generation"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise QwenImageError(f"Qwen Image 请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise QwenImageError(f"Qwen Image API 错误 {response.status_code}: {response.text[:800]}")

        try:
            data = response.json()
        except ValueError as exc:
            raise QwenImageError(f"Qwen Image 响应非 JSON: {response.text[:300]}") from exc

        images = extract_image_urls(data)
        return {
            "raw": data,
            "images": images,
            "request_id": (
                (data.get("request_id") if isinstance(data, dict) else None)
                or (data.get("requestId") if isinstance(data, dict) else None)
            ),
        }


def extract_image_urls(data: Any) -> list[str]:
    """从通义/MaaS 多种响应结构里抠出图片 URL。"""
    found: list[str] = []
    seen: set[str] = set()

    def _add(url: Any) -> None:
        text = str(url or "").strip()
        if not text.startswith(("http://", "https://")):
            return
        if text in seen:
            return
        seen.add(text)
        found.append(text)

    def _walk(node: Any, depth: int = 0) -> None:
        if depth > 12 or node is None:
            return
        if isinstance(node, str):
            if node.startswith("http") and re.search(r"\.(png|jpe?g|webp)(?:\?|$)", node, re.I):
                _add(node)
            elif node.startswith("http") and ("alicdn" in node or "oss" in node or "dashscope" in node):
                _add(node)
            return
        if isinstance(node, dict):
            for key in ("url", "image", "image_url", "imageUrl", "output_image_url"):
                if key in node:
                    _add(node.get(key))
            for value in node.values():
                _walk(value, depth + 1)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)

    _walk(data)
    return found
