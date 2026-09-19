from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SELLER_HOME_URL = "https://seller.ozon.ru/app/dashboard/main"
RESOLVE_PATH = "/api/v1/seller-tree/resolve/by-sku"


def seller_cdp_enabled() -> bool:
    return os.getenv("OZON_SELLER_USE_CDP", "true").strip().lower() in ("1", "true", "yes", "on")


def _cdp_url() -> str:
    return (
        (os.getenv("OZON_SELLER_CDP_URL") or "").strip()
        or (os.getenv("OZON_BROWSER_CDP_URL") or "").strip()
        or "http://127.0.0.1:9222"
    )


def _company_id() -> str:
    return (os.getenv("OZON_SELLER_CLIENT_ID") or "").strip()


def _pick_seller_page(context: Any) -> Any:
    for candidate in context.pages:
        try:
            host = urlparse(candidate.url or "").hostname or ""
            if "seller.ozon.ru" in host:
                return candidate
        except Exception:
            continue
    if context.pages:
        return context.pages[0]
    return context.new_page()


def _looks_like_challenge(title: str, url: str, payload: dict[str, Any] | None = None) -> bool:
    blob = f"{title} {url}".lower()
    if "challenge" in blob or "antibot" in blob:
        return True
    if payload and payload.get("challengeURL") and not payload.get("resolved_categories_by_sku"):
        return True
    if payload and payload.get("incidentId") and not payload.get("resolved_categories_by_sku"):
        return True
    return False


def resolve_by_sku_via_cdp(sku: str | int, *, timeout_ms: int = 60_000) -> dict[str, Any]:
    """
    在已打开的调试 Chrome 中，于 seller.ozon.ru 同源执行 resolve/by-sku。
    复用你手动登录/过验证后的会话，避免手贴 Cookie。
    """
    if not seller_cdp_enabled():
        raise RuntimeError("OZON_SELLER_USE_CDP 已关闭")

    company_id = _company_id()
    if not company_id:
        raise RuntimeError("缺少 OZON_SELLER_CLIENT_ID（seller-tree 需要 x-o3-company-id）")

    sku_text = str(sku).strip()
    if not sku_text.isdigit():
        raise RuntimeError(f"无效的 Ozon SKU: {sku}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 playwright，无法通过 Chrome 解析类目") from exc

    cdp = _cdp_url()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp)
        except Exception as exc:
            raise RuntimeError(
                f"无法接入 Chrome CDP（{cdp}）。请先运行 start-ozon-chrome.ps1，"
                f"并在该窗口登录 {SELLER_HOME_URL}"
            ) from exc

        try:
            if not browser.contexts:
                raise RuntimeError("已连接 Chrome，但没有任何上下文")
            context = browser.contexts[0]
            page = _pick_seller_page(context)

            need_nav = True
            try:
                host = urlparse(page.url or "").hostname or ""
                if "seller.ozon.ru" in host and "challenge" not in (page.url or "").lower():
                    need_nav = False
            except Exception:
                need_nav = True

            if need_nav:
                page.goto(SELLER_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)

            title = ""
            url = ""
            try:
                title = page.title()
                url = page.url
            except Exception:
                pass
            if _looks_like_challenge(title, url):
                raise RuntimeError(
                    "seller.ozon.ru 仍在反爬验证页。"
                    f"请在调试 Chrome 中打开并完成验证：{SELLER_HOME_URL}"
                )

            result = page.evaluate(
                """async ({ path, sku, companyId, timeoutMs }) => {
                    const controller = new AbortController();
                    const timer = setTimeout(() => controller.abort(), timeoutMs);
                    try {
                        const response = await fetch(path, {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json, text/plain, */*',
                                'Content-Type': 'application/json',
                                'x-o3-app-name': 'seller-ui',
                                'x-o3-company-id': companyId,
                                'x-o3-language': 'zh-Hans',
                            },
                            body: JSON.stringify({ skus: [Number(sku)] }),
                            signal: controller.signal,
                        });
                        const text = await response.text();
                        let json = null;
                        try { json = JSON.parse(text); } catch (e) { json = null; }
                        return {
                            status: response.status,
                            text,
                            json,
                            title: document.title,
                            url: location.href,
                        };
                    } finally {
                        clearTimeout(timer);
                    }
                }""",
                {
                    "path": RESOLVE_PATH,
                    "sku": sku_text,
                    "companyId": company_id,
                    "timeoutMs": max(10_000, timeout_ms),
                },
            )
        finally:
            try:
                browser.close()
            except Exception:
                pass

    status = int((result or {}).get("status") or 0)
    payload = (result or {}).get("json")
    text = str((result or {}).get("text") or "")
    page_title = str((result or {}).get("title") or "")
    page_url = str((result or {}).get("url") or "")

    if status in (401, 403) or (
        isinstance(payload, dict) and _looks_like_challenge(page_title, page_url, payload)
    ):
        raise RuntimeError(
            "seller.ozon.ru 未登录或需人机验证。"
            f"请在调试 Chrome 打开并登录：{SELLER_HOME_URL}"
        )
    if status >= 400:
        snippet = text[:240] if text else json.dumps(payload, ensure_ascii=False)[:240]
        raise RuntimeError(f"seller-tree CDP 错误 {status}: {snippet}")
    if not isinstance(payload, dict):
        raise RuntimeError("seller-tree CDP 返回非 JSON")
    logger.info("seller-tree resolve via CDP ok for sku=%s", sku_text)
    return payload


def pull_seller_cookie_from_cdp(*, refresh: bool = False, timeout_ms: int = 60_000) -> str:
    """备用：从 CDP 读取 seller.ozon.ru Cookie，供 HTTP 回退。"""
    if not seller_cdp_enabled():
        return ""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ""

    cdp = _cdp_url()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(cdp)
        except Exception:
            return ""
        try:
            if not browser.contexts:
                return ""
            context = browser.contexts[0]
            page = _pick_seller_page(context)
            if refresh:
                page.goto(SELLER_HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
            cookies = context.cookies()
            parts: list[str] = []
            seen: set[str] = set()
            for item in cookies:
                domain = str(item.get("domain") or "").lower()
                name = str(item.get("name") or "").strip()
                if not name or name in seen:
                    continue
                if "ozon.ru" not in domain:
                    continue
                seen.add(name)
                parts.append(f"{name}={item.get('value')}")
            return "; ".join(parts)
        finally:
            try:
                browser.close()
            except Exception:
                pass
