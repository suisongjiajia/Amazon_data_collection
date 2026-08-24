from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


class DeepSeekError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.api_key = (api_key or os.getenv("DEEPSEEK_API_KEY") or "").strip()
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.model = (model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat").strip()
        self.timeout_seconds = timeout_seconds or int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120"))

    def ensure_configured(self) -> None:
        if not self.api_key:
            raise DeepSeekError("未配置 DEEPSEEK_API_KEY，请在 .env 中设置")

    def chat_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> str:
        self.ensure_configured()
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise DeepSeekError(f"DeepSeek 请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise DeepSeekError(f"DeepSeek API 错误 {response.status_code}: {response.text[:500]}")

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekError("DeepSeek 响应格式异常") from exc

    def chat_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        raw = self.chat_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
        )
        return parse_json_response(raw)


def parse_json_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(f"AI 返回的不是合法 JSON: {text[:300]}") from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError("AI 返回的 JSON 必须是对象")
    return parsed
