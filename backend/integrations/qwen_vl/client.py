"""通义千问 VL：读图并产出作图提示词（OpenAI 兼容网关）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


class QwenVLError(RuntimeError):
    pass


class QwenVLClient:
    """
    POST {base}/compatible-mode/v1/chat/completions
    model: qwen-vl-max / qwen-vl-plus
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
            or os.getenv("QWEN_VL_API_KEY")
            or ""
        ).strip()
        self.base_url = (
            base_url
            or os.getenv("QWEN_VL_BASE_URL")
            or os.getenv("QWEN_IMAGE_BASE_URL")
            or "https://maas.qianwenaiapi.com"
        ).rstrip("/")
        self.model = (model or os.getenv("QWEN_VL_MODEL") or "qwen-vl-max").strip()
        self.timeout_seconds = timeout_seconds or int(os.getenv("QWEN_VL_TIMEOUT_SECONDS", "120"))

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise QwenVLError("未配置 DASHSCOPE_API_KEY（或 QWEN_VL_API_KEY）")

    def chat_vision(
        self,
        *,
        prompt: str,
        image_url: str,
        system_prompt: str | None = None,
        temperature: float = 0.4,
    ) -> str:
        self.ensure_configured()
        image_url = str(image_url or "").strip()
        text = str(prompt or "").strip()
        if not image_url or not text:
            raise QwenVLError("image_url 与 prompt 均不能为空")

        user_content: list[dict[str, Any]] = [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": text},
        ]
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        url = f"{self.base_url}/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise QwenVLError(f"Qwen VL 请求失败: {exc}") from exc
        if response.status_code >= 400:
            raise QwenVLError(f"Qwen VL API 错误 {response.status_code}: {response.text[:800]}")
        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise QwenVLError(f"Qwen VL 响应格式异常: {response.text[:400]}") from exc

    def chat_vision_json(
        self,
        *,
        prompt: str,
        image_url: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        raw = self.chat_vision(
            prompt=prompt,
            image_url=image_url,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        return _extract_json_object(raw)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise QwenVLError("VL 返回空内容")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise QwenVLError(f"VL 未返回 JSON: {raw[:300]}")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise QwenVLError("VL JSON 不是对象")
    return data
