from __future__ import annotations

import os
from typing import Any

from collector.ozon.browser_session import get_ozon_browser_session, ozon_browser_enabled
from config import get_ozon_cookie, get_ozon_seller_ui_cookie, ozon_cookie_configured


def _mask(value: str, keep: int = 6) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "***"
    return f"{text[:keep]}…{text[-keep:]}"


def get_ozon_runtime_health() -> dict[str, Any]:
    """配置体检：让卖家一眼知道缺什么，而不是到处踩坑。"""
    cookie = get_ozon_cookie()
    seller_override = (os.getenv("OZON_SELLER_COOKIE") or "").strip()
    client_id = (os.getenv("OZON_SELLER_CLIENT_ID") or "").strip()
    api_key = (os.getenv("OZON_SELLER_API_KEY") or "").strip()
    warehouse = (os.getenv("OZON_WAREHOUSE_ID") or "").strip()
    oss_key = (os.getenv("OSS_ACCESS_KEY_ID") or "").strip()
    oss_secret = (os.getenv("OSS_ACCESS_KEY_SECRET") or "").strip()
    oss_bucket = (os.getenv("OSS_BUCKET") or "").strip()

    checks: list[dict[str, Any]] = []

    browser_on = ozon_browser_enabled()
    browser_status = get_ozon_browser_session().status()
    cdp_url = str(browser_status.get("cdp_url") or "http://127.0.0.1:9222")
    cdp_reachable = False
    try:
        import urllib.request

        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=1.5) as resp:
            cdp_reachable = resp.status == 200
    except Exception:
        cdp_reachable = False

    playwright_ok = True
    playwright_msg = ""
    if browser_on:
        try:
            import playwright  # noqa: F401
        except ImportError:
            playwright_ok = False
            playwright_msg = "未安装 playwright，请执行: pip install playwright && playwright install chromium"
        else:
            if cdp_reachable:
                playwright_msg = f"已检测到可接入 Chrome（{cdp_url}），将复用你的浏览器会话"
            elif browser_status.get("warmed"):
                playwright_msg = f"已接入浏览器（mode={browser_status.get('mode')}），可采集"
            else:
                playwright_ok = False
                playwright_msg = (
                    "未检测到带调试端口的 Chrome。请先运行 start-ozon-chrome.ps1，"
                    "在窗口打开 ozon.ru 完成验证后保持开着再采集"
                )
    else:
        playwright_msg = "已关闭（OZON_BROWSER_ENABLED=false），将回退 HTTP/Cookie"

    checks.append(
        {
            "key": "ozon_browser",
            "label": "本机 Chrome 采集（CDP）",
            "ok": (not browser_on) or (playwright_ok and (cdp_reachable or browser_status.get("warmed"))),
            "required": browser_on,
            "message": playwright_msg,
            "hint": "先运行 start-ozon-chrome.ps1；不要用后端另开的无痕浏览器",
            "detail": {**browser_status, "cdp_reachable": cdp_reachable},
        }
    )

    cookie_ok = bool(cookie)
    checks.append(
        {
            "key": "ozon_cookie",
            "label": "Ozon Cookie（可选兜底）",
            "ok": True,
            "required": False,
            "message": (
                "已配置：仅 HTTP 兜底；类目解析优先走调试 Chrome 的 seller.ozon.ru"
                if cookie_ok
                else "未配置：类目解析走调试 Chrome（推荐），无需手贴 Cookie"
            ),
            "hint": "调试 Chrome 登录 https://seller.ozon.ru ；OZON_COOKIE 仅作兜底",
            "detail": _mask(cookie, 8) if cookie_ok else None,
        }
    )

    seller_cdp_on = os.getenv("OZON_SELLER_USE_CDP", "true").strip().lower() in ("1", "true", "yes", "on")
    if seller_cdp_on and cdp_reachable:
        msg_seller_tree = "将通过调试 Chrome 访问 seller.ozon.ru 自动解析类目"
        ok_seller_tree = bool(client_id)
    elif cookie_ok and client_id:
        msg_seller_tree = "将使用 OZON_COOKIE 解析类目（易过期）"
        ok_seller_tree = True
    else:
        msg_seller_tree = "未就绪：请运行 start-ozon-chrome.ps1 并登录 seller.ozon.ru"
        ok_seller_tree = False
    checks.append(
        {
            "key": "seller_tree",
            "label": "自动获取类目",
            "ok": ok_seller_tree,
            "required": False,
            "message": msg_seller_tree,
            "hint": "同一调试 Chrome 打开并登录 https://seller.ozon.ru/app/dashboard/main",
            "detail": {"use_cdp": seller_cdp_on, "cdp_reachable": cdp_reachable},
        }
    )

    cookie_1688 = (os.getenv("1688_COOKIE") or "").strip()
    use_cdp_1688 = os.getenv("1688_USE_CDP", "true").strip().lower() in ("1", "true", "yes", "on")
    if use_cdp_1688 and cdp_reachable:
        msg_1688 = "将从调试 Chrome 实时读取 1688 图搜页登录态（推荐）"
        ok_1688 = True
    elif cookie_1688:
        msg_1688 = "已配置 1688_COOKIE（易过期，建议改用调试 Chrome 登录）"
        ok_1688 = True
    else:
        msg_1688 = "未就绪：请运行 start-ozon-chrome.ps1 并登录 1688 图搜页，或配置 1688_COOKIE"
        ok_1688 = False
    checks.append(
        {
            "key": "alibaba_1688",
            "label": "1688 以图搜货",
            "ok": ok_1688,
            "required": False,
            "message": msg_1688,
            "hint": (
                "同一调试 Chrome 打开并登录 "
                "https://air.1688.com/app/1688-lp/landing-page/home/inventory/products.html"
                "?bizType=browser&customerId=AIBUY"
            ),
            "detail": {
                "use_cdp": use_cdp_1688,
                "cdp_reachable": cdp_reachable,
                "env_cookie": bool(cookie_1688),
            },
        }
    )
    if seller_override and seller_override != cookie:
        checks.append(
            {
                "key": "ozon_seller_cookie_override",
                "label": "卖家 Cookie 覆盖",
                "ok": True,
                "required": False,
                "message": "已单独设置 OZON_SELLER_COOKIE（可选覆盖）",
                "hint": "一般不需要；清空后会自动复用 OZON_COOKIE",
            }
        )

    seller_api_ok = bool(client_id and api_key)
    checks.append(
        {
            "key": "seller_api",
            "label": "Seller API 密钥",
            "ok": seller_api_ok,
            "required": True,
            "message": (
                f"Client-Id={client_id}" if seller_api_ok else "缺少 OZON_SELLER_CLIENT_ID 或 OZON_SELLER_API_KEY"
            ),
            "hint": "seller.ozon.ru → 设置 → API 密钥",
        }
    )

    warehouse_ok = warehouse.isdigit()
    checks.append(
        {
            "key": "warehouse",
            "label": "rFBS 仓库",
            "ok": warehouse_ok,
            "required": True,
            "message": f"仓库 ID={warehouse}" if warehouse_ok else "未配置 OZON_WAREHOUSE_ID，发布后无法推库存",
            "hint": "卖家后台仓库列表中的数字 ID",
        }
    )

    oss_ok = bool(oss_key and oss_secret and oss_bucket)
    checks.append(
        {
            "key": "oss",
            "label": "图片 OSS",
            "ok": oss_ok,
            "required": False,
            "message": "已配置" if oss_ok else "未配置 OSS，图片转存不可用（可用原图试发）",
            "hint": "OSS_ACCESS_KEY_ID / SECRET / BUCKET；上传会设 public-read，若仍 AccessDenied 请在控制台开公共读或重转存",
        }
    )

    required_failed = [item for item in checks if item.get("required") and not item.get("ok")]
    return {
        "ok": not required_failed,
        "cookie_unified": True,
        "using_seller_cookie_override": bool(seller_override),
        "seller_ui_cookie_ready": bool(get_ozon_seller_ui_cookie()),
        "browser_cookie_ready": ozon_cookie_configured(),
        "browser_collect_enabled": browser_on,
        "checks": checks,
        "failed_required": [item["key"] for item in required_failed],
        "summary": (
            "配置正常，可进行采集/上架"
            if not required_failed
            else "关键配置缺失：" + "；".join(item["message"] for item in required_failed)
        ),
    }
