from __future__ import annotations

import os
from typing import Any

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

    cookie_ok = bool(cookie)
    checks.append(
        {
            "key": "ozon_cookie",
            "label": "Ozon Cookie",
            "ok": cookie_ok,
            "required": True,
            "message": (
                "已配置（采集 + 自动解析类目共用）"
                if cookie_ok
                else "未配置 OZON_COOKIE：采集与自动获取 type_id 都会失败"
            ),
            "hint": "登录 seller.ozon.ru 或 ozon.ru 后 F12 复制 Cookie，只填 OZON_COOKIE 即可",
            "detail": _mask(cookie, 8) if cookie_ok else None,
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
        "checks": checks,
        "failed_required": [item["key"] for item in required_failed],
        "summary": (
            "配置正常，可进行采集/上架"
            if not required_failed
            else "关键配置缺失：" + "；".join(item["message"] for item in required_failed)
        ),
    }
