"""1688 开放平台网关客户端（param2 + HMAC-SHA1）。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

try:
    from curl_cffi import requests as http_requests
except ImportError:
    import requests as http_requests  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

BASE_URL = "https://gw.open.1688.com/openapi"

# 进程内幂等：同一次运行不重复关注/铺货
_LOCK = threading.Lock()
_RELATED_IDS: set[str] = set()
_SYNCED_IDS: set[str] = set()


class AlibabaOpenApiError(RuntimeError):
    pass


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


def open_api_configured() -> bool:
    """具备签名所需凭证即可调用（token 可稍后 refresh）。"""
    app_key = _env("ALIBABA_1688_APP_KEY", "ALI1688_APP_KEY")
    app_secret = _env("ALIBABA_1688_APP_SECRET", "ALI1688_APP_SECRET")
    token = _env("ALIBABA_1688_ACCESS_TOKEN", "ALI1688_ACCESS_TOKEN")
    refresh = _env("ALIBABA_1688_REFRESH_TOKEN", "ALI1688_REFRESH_TOKEN")
    return bool(app_key and app_secret and (token or refresh))


def sign_request_hmac_sha1(url_path: str, params: dict[str, Any], app_secret: str) -> str:
    """url_path 从 param2 起；参数按 key 排序后 key+value 拼接。"""
    sorted_params = sorted((str(k), "" if v is None else str(v)) for k, v in params.items())
    param_str = "".join(f"{k}{v}" for k, v in sorted_params)
    sign_str = f"{url_path}{param_str}"
    return (
        hmac.new(app_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha1)
        .hexdigest()
        .upper()
    )


def _normalize_offer_id(value: str | int) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        raise AlibabaOpenApiError(f"非法 offerId/productId: {value!r}")
    return text


def _payload_text(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        return str(payload)


def is_success_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("success") is True:
        return True
    result = payload.get("result")
    if isinstance(result, dict) and result.get("success") is True:
        return True
    if isinstance(result, bool) and result is True:
        return True
    # 部分接口直接返回业务对象
    if any(k in payload for k in ("productInfo", "offerId", "subject")):
        return True
    return False


def is_idempotent_ok_payload(payload: dict[str, Any] | None) -> bool:
    """已关注/已铺货等重复调用视为成功。"""
    if is_success_payload(payload):
        return True
    blob = _payload_text(payload).lower()
    markers = (
        "已存在",
        "已经",
        "重复",
        "已关注",
        "已铺货",
        "已添加",
        "already",
        "exist",
        "duplicate",
        "relation exist",
    )
    return any(m in blob for m in markers)


def needs_relation_or_push(payload: dict[str, Any] | None) -> bool:
    """无铺货关系 / 无权限 / 品池不存在 → 需要走关注+铺货。"""
    blob = _payload_text(payload)
    lower = blob.lower()
    markers = (
        "没有该商品的查询权限",
        "没有查询权限",
        "未建立铺货",
        "铺货关系",
        "商品不存在",
        "不存在",
        "SP0056",
        "无权限",
        "not permission",
        "no permission",
        "not exist",
        "does not exist",
    )
    if any(m.lower() in lower for m in markers):
        return True
    # 商品[123]不存在
    if "商品" in blob and "不存在" in blob:
        return True
    return False


def _relation_cache_path() -> Path:
    raw = (os.getenv("ALIBABA_1688_RELATION_CACHE") or "").strip()
    if raw:
        return Path(raw)
    root = Path(__file__).resolve().parents[2]  # backend/
    return root / ".cache" / "1688_cross_relation.json"


def _load_persistent_sets() -> tuple[set[str], set[str]]:
    path = _relation_cache_path()
    if not path.exists():
        return set(), set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set(), set()
    related = {str(x) for x in (data.get("related") or []) if str(x).isdigit()}
    synced = {str(x) for x in (data.get("synced") or []) if str(x).isdigit()}
    return related, synced


def _save_persistent_sets(related: set[str], synced: set[str]) -> None:
    path = _relation_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "related": sorted(related),
            "synced": sorted(synced),
            "updated_at": int(time.time()),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("写入 1688 relation cache 失败: %s", exc)


def _ensure_memory_loaded() -> None:
    with _LOCK:
        if _RELATED_IDS or _SYNCED_IDS:
            return
        related, synced = _load_persistent_sets()
        _RELATED_IDS.update(related)
        _SYNCED_IDS.update(synced)


class AlibabaOpenApiClient:
    def __init__(
        self,
        *,
        app_key: str | None = None,
        app_secret: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.app_key = (app_key or _env("ALIBABA_1688_APP_KEY", "ALI1688_APP_KEY")).strip()
        self.app_secret = (app_secret or _env("ALIBABA_1688_APP_SECRET", "ALI1688_APP_SECRET")).strip()
        self._access_token = (
            access_token or _env("ALIBABA_1688_ACCESS_TOKEN", "ALI1688_ACCESS_TOKEN")
        ).strip()
        self._refresh_token = (
            refresh_token or _env("ALIBABA_1688_REFRESH_TOKEN", "ALI1688_REFRESH_TOKEN")
        ).strip()
        self.timeout = float(
            timeout
            if timeout is not None
            else _env("ALIBABA_1688_TIMEOUT_SECONDS", "1688_TIMEOUT_SECONDS", default="30") or 30
        )
        self.out_member_id = _env("ALIBABA_1688_OUT_MEMBER_ID", default="1")
        self.country = _env("ALIBABA_1688_COUNTRY", default="en") or "en"
        self.push_settle_seconds = float(_env("ALIBABA_1688_PUSH_SETTLE_SECONDS", default="1.5") or 1.5)
        if not self.app_key or not self.app_secret:
            raise AlibabaOpenApiError(
                "缺少 ALIBABA_1688_APP_KEY / ALIBABA_1688_APP_SECRET（开放平台应用密钥）"
            )
        if not self._access_token and not self._refresh_token:
            raise AlibabaOpenApiError(
                "缺少 ALIBABA_1688_ACCESS_TOKEN 或 ALIBABA_1688_REFRESH_TOKEN"
            )
        _ensure_memory_loaded()

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        if self._access_token and not force_refresh:
            return self._access_token
        if not self._refresh_token:
            raise AlibabaOpenApiError("access_token 无效且未配置 refresh_token")
        url = f"{BASE_URL}/param2/1/system.oauth2/getToken/{self.app_key}"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }
        resp = http_requests.post(url, data=data, timeout=self.timeout)
        payload = resp.json() if resp.content else {}
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise AlibabaOpenApiError(f"刷新 access_token 失败: {payload}")
        self._access_token = token
        new_refresh = str(payload.get("refresh_token") or "").strip()
        if new_refresh:
            self._refresh_token = new_refresh
        logger.info("1688 open api access_token refreshed")
        return token

    def call(
        self,
        namespace: str,
        api_name: str,
        params: dict[str, Any],
        *,
        retry_on_auth: bool = True,
    ) -> dict[str, Any]:
        token = self.get_access_token()
        body = {str(k): v for k, v in params.items()}
        body["access_token"] = token
        url_path = f"param2/1/{namespace}/{api_name}/{self.app_key}"
        body["_aop_signature"] = sign_request_hmac_sha1(url_path, body, self.app_secret)
        url = f"{BASE_URL}/{url_path}"
        resp = http_requests.post(url, data=body, timeout=self.timeout)
        try:
            payload = resp.json()
        except Exception as exc:
            raise AlibabaOpenApiError(
                f"开放平台响应非 JSON HTTP {resp.status_code}: {resp.text[:300]}"
            ) from exc
        if not isinstance(payload, dict):
            raise AlibabaOpenApiError(f"开放平台响应格式异常: {payload!r}")

        err = str(payload.get("error_message") or payload.get("error") or "").lower()
        code = str(payload.get("error_code") or payload.get("code") or "")
        if retry_on_auth and (
            "token" in err
            or code in {"401", "UNAUTHORIZED"}
            or "expired" in err
            or "invalid access_token" in err
        ):
            logger.warning("1688 open api auth error, refreshing token: %s", payload)
            self.get_access_token(force_refresh=True)
            return self.call(namespace, api_name, params, retry_on_auth=False)
        return payload

    def query_product_detail(self, offer_id: str | int, *, country: str | None = None) -> dict[str, Any]:
        """分销跨境：product.search.queryProductDetail。"""
        detail_params = {
            "offerId": int(_normalize_offer_id(offer_id)),
            "country": (country or self.country).strip() or "en",
            "outMemberId": self.out_member_id or "1",
        }
        return self.call(
            "com.alibaba.fenxiao.crossborder",
            "product.search.queryProductDetail",
            {"offerDetailParam": json.dumps(detail_params, separators=(",", ":"), ensure_ascii=False)},
        )

    def cross_product_info(self, product_id: str | int) -> dict[str, Any]:
        """跨境铺货详情：alibaba.cross.productInfo（需铺货关系）。"""
        return self.call(
            "com.alibaba.product",
            "alibaba.cross.productInfo",
            {"productId": _normalize_offer_id(product_id)},
        )

    def alibaba1688_cross_border_add_relation(self, offer_id: str | int) -> dict[str, Any]:
        """关注：product.kjdistribute.addRelation（幂等）。"""
        oid = _normalize_offer_id(offer_id)
        with _LOCK:
            if oid in _RELATED_IDS:
                return {"success": True, "idempotent": True, "offerId": oid, "skipped": "memory"}
        payload = self.call(
            "com.alibaba.fenxiao.crossborder",
            "product.kjdistribute.addRelation",
            {"offerId": oid},
        )
        if is_idempotent_ok_payload(payload):
            with _LOCK:
                _RELATED_IDS.add(oid)
                related = set(_RELATED_IDS)
                synced = set(_SYNCED_IDS)
            _save_persistent_sets(related, synced)
            return payload if isinstance(payload, dict) else {"success": True, "result": payload}
        raise AlibabaOpenApiError(f"addRelation 失败 offer={oid}: {payload}")

    def alibaba1688_cross_border_sync_product_list(
        self,
        product_ids: Iterable[str | int],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """铺货：alibaba.cross.syncProductListPushed（单次最多 20，幂等跳过已铺）。"""
        ids = [_normalize_offer_id(x) for x in product_ids]
        uniq: list[str] = []
        seen: set[str] = set()
        for oid in ids:
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(oid)
        if not uniq:
            return {"success": True, "synced": [], "skipped": [], "failed": []}

        to_sync: list[str] = []
        skipped: list[str] = []
        with _LOCK:
            for oid in uniq:
                if not force and oid in _SYNCED_IDS:
                    skipped.append(oid)
                else:
                    to_sync.append(oid)

        results: list[dict[str, Any]] = []
        failed: list[str] = []
        synced: list[str] = []
        for i in range(0, len(to_sync), 20):
            chunk = to_sync[i : i + 20]
            payload = self.call(
                "com.alibaba.product.push",
                "alibaba.cross.syncProductListPushed",
                {"productIdList": json.dumps([int(x) for x in chunk], separators=(",", ":"))},
            )
            ok = is_idempotent_ok_payload(payload) or (
                isinstance(payload.get("result"), dict) and payload["result"].get("success") is True
            )
            if ok:
                synced.extend(chunk)
                with _LOCK:
                    _SYNCED_IDS.update(chunk)
                    _RELATED_IDS.update(chunk)
                    related = set(_RELATED_IDS)
                    synced_set = set(_SYNCED_IDS)
                _save_persistent_sets(related, synced_set)
                results.append({"chunk": chunk, "payload": payload, "ok": True})
            else:
                failed.extend(chunk)
                results.append({"chunk": chunk, "payload": payload, "ok": False})
                logger.warning("syncProductListPushed 业务失败 ids=%s payload=%s", chunk, payload)
            if i + 20 < len(to_sync) and self.push_settle_seconds > 0:
                time.sleep(min(self.push_settle_seconds, 1.0))

        return {
            "success": not failed,
            "synced": synced,
            "skipped": skipped,
            "failed": failed,
            "batches": results,
        }

    def ensure_offer_relation_and_push(self, offer_id: str | int) -> dict[str, Any]:
        """幂等：关注 + 尝试铺货。铺货失败不抛死（部分货不可铺），由上层再查详情判定。"""
        oid = _normalize_offer_id(offer_id)
        related_payload = self.alibaba1688_cross_border_add_relation(oid)
        sync_payload = self.alibaba1688_cross_border_sync_product_list([oid])
        if self.push_settle_seconds > 0:
            time.sleep(self.push_settle_seconds)
        return {
            "offer_id": oid,
            "add_relation": related_payload,
            "sync": sync_payload,
            "push_ok": bool(sync_payload.get("success")) or oid in (sync_payload.get("skipped") or []),
        }
