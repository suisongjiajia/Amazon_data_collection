from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# 阿里牛顿「以图搜货」业务首页（根路径 air.1688.com 会 404）
ALIBABA_1688_HOME_URL = (
    "https://air.1688.com/app/1688-lp/landing-page/home/inventory/products.html"
    "?bizType=browser&customerId=AIBUY"
)

_COOKIE_DOMAIN_HINTS = (
    "1688.com",
    "taobao.com",
    "tmall.com",
    "alibaba.com",
    "alicdn.com",
    "mmstat.com",
)


def alibaba_cdp_enabled() -> bool:
    return os.getenv("1688_USE_CDP", "true").strip().lower() in ("1", "true", "yes", "on")


def _cdp_url() -> str:
    return (
        (os.getenv("1688_BROWSER_CDP_URL") or "").strip()
        or (os.getenv("OZON_BROWSER_CDP_URL") or "").strip()
        or "http://127.0.0.1:9222"
    )


def _cookie_header(cookies: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for item in cookies:
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        domain = str(item.get("domain") or "").lower()
        if not name or name in seen:
            continue
        if not any(hint in domain for hint in _COOKIE_DOMAIN_HINTS):
            continue
        seen.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def _pick_1688_page(context: Any) -> Any:
    for candidate in context.pages:
        try:
            host = urlparse(candidate.url or "").hostname or ""
            if "1688.com" in host:
                return candidate
        except Exception:
            continue
    if context.pages:
        return context.pages[0]
    return context.new_page()


def pull_1688_cookie_from_cdp(*, refresh: bool = False, timeout_ms: int = 60_000) -> str:
    """
    从本机已打开的调试 Chrome 读取 1688 登录 Cookie。
    refresh=True 时会打开/刷新图搜首页，促使 _m_h5_tk 更新。
    若 Chrome 仅有 token、缺少 cookie2/lid，会与 .env 的 1688_COOKIE 会话字段合并。
    """
    if not alibaba_cdp_enabled():
        return ""

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 playwright，无法从 Chrome 读取 1688 Cookie") from exc

    cdp = _cdp_url()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp)
        except Exception as exc:
            raise RuntimeError(
                f"无法接入 Chrome CDP（{cdp}）。请先运行 start-ozon-chrome.ps1，"
                f"并在该窗口登录 {ALIBABA_1688_HOME_URL}"
            ) from exc

        try:
            if not browser.contexts:
                raise RuntimeError("已连接 Chrome，但没有任何上下文")
            context = browser.contexts[0]
            page = _pick_1688_page(context)

            # 用 .env 会话 Cookie 补齐 Chrome（常见：页面只有 _m_h5_tk，缺 cookie2）
            env_cookie = (os.getenv("1688_COOKIE") or "").strip()
            if env_cookie:
                adds: list[dict[str, Any]] = []
                for part in env_cookie.split(";"):
                    part = part.strip()
                    if "=" not in part:
                        continue
                    name, value = part.split("=", 1)
                    name = name.strip()
                    value = value.strip()
                    if not name or name.startswith("_m_h5_tk"):
                        continue
                    adds.append({"name": name, "value": value, "domain": ".1688.com", "path": "/"})
                if adds:
                    try:
                        context.add_cookies(adds)
                    except Exception as exc:
                        logger.warning("inject 1688 env cookies failed: %s", exc)

            need_nav = refresh
            try:
                host = urlparse(page.url or "").hostname or ""
                path = urlparse(page.url or "").path or ""
                if "1688.com" not in host or "products.html" not in path:
                    need_nav = True
            except Exception:
                need_nav = True

            if need_nav:
                page.goto(ALIBABA_1688_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)

            cookies = context.cookies()
            header = _cookie_header(_prefer_fresh_h5_token(cookies))
            if "_m_h5_tk=" not in header:
                page.goto(ALIBABA_1688_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2500)
                header = _cookie_header(_prefer_fresh_h5_token(context.cookies()))

            if "_m_h5_tk=" not in header:
                raise RuntimeError(
                    "已接入 Chrome，但未读到 1688 登录态（缺少 _m_h5_tk）。"
                    f"请在调试 Chrome 窗口打开并登录：{ALIBABA_1688_HOME_URL}"
                )
            if "cookie2=" not in header and "unb=" not in header:
                raise RuntimeError(
                    "1688 会话不完整（缺少 cookie2/unb）。"
                    f"请在调试 Chrome 登录图搜首页，或更新 .env 的 1688_COOKIE：{ALIBABA_1688_HOME_URL}"
                )
            logger.info("1688 cookie pulled from CDP (%d chars)", len(header))
            return header
        finally:
            try:
                browser.close()
            except Exception:
                pass


def _prefer_fresh_h5_token(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一 name 多份 Cookie 时，优先 .1688.com，_m_h5_tk 取时间戳最新。"""
    by_name: dict[str, dict[str, Any]] = {}
    for item in cookies:
        name = str(item.get("name") or "")
        domain = str(item.get("domain") or "")
        if not name:
            continue
        if name == "_m_h5_tk":
            cur = by_name.get(name)
            if cur is None or _h5_token_ts(item.get("value")) > _h5_token_ts(cur.get("value")):
                by_name[name] = item
            continue
        cur = by_name.get(name)
        if cur is None:
            by_name[name] = item
        elif "1688.com" in domain and "1688.com" not in str(cur.get("domain") or ""):
            by_name[name] = item
    return list(by_name.values())


def _h5_token_ts(value: Any) -> int:
    text = str(value or "")
    if "_" not in text:
        return 0
    try:
        return int(text.rsplit("_", 1)[-1])
    except ValueError:
        return 0


def is_token_error(message: str) -> bool:
    text = (message or "").upper()
    markers = (
        "TOKEN_EXOIRED",
        "TOKEN_EXPIRED",
        "FAIL_SYS_TOKEN",
        "SESSION_EXPIRED",
        "FAIL_SYS_SESSION",
        "RGV587_ERROR",
        "FAIL_SYS_USER_VALIDATE",
        "USERMUSTLOGIN",
        "LOGIN",
        "_M_H5_TK",
    )
    return any(marker in text for marker in markers)
