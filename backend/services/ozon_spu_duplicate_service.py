"""同账号 SPU 重复：归档多余卡片，保留在售 keeper，并清理本地变体。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from db.ozon_workflow import (
    delete_product_edit_variants_by_skus,
    find_product_edit_variants_by_skus,
    get_product_edit,
    remap_product_edit_variant_sku,
    update_product_edit,
)
from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError

logger = logging.getLogger(__name__)

SPU_CODE = "SPU_ALREADY_EXISTS_IN_ANOTHER_ACCOUNT"
_OFFER_RE = re.compile(r"A1688-\d+", re.I)


def _product_id(product: dict[str, Any]) -> int | None:
    for key in ("id", "product_id"):
        raw = product.get(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _offer_id(product: dict[str, Any]) -> str:
    return str(product.get("offer_id") or "").strip()


def _is_selling(product: dict[str, Any]) -> bool:
    statuses = product.get("statuses") if isinstance(product.get("statuses"), dict) else {}
    name = str(statuses.get("status_name") or "").strip().casefold()
    if name == "продается":
        return True
    try:
        sku = int(product.get("sku") or 0)
    except (TypeError, ValueError):
        sku = 0
    return sku > 0 and not bool(product.get("is_archived") or product.get("archived"))


def _keep_score(product: dict[str, Any]) -> tuple[int, int]:
    """分越高越该保留；同分取更小 product_id（更早创建）。"""
    score = 0
    if _is_selling(product):
        score += 1000
    try:
        sku = int(product.get("sku") or 0)
    except (TypeError, ValueError):
        sku = 0
    if sku > 0:
        score += 100
    if not bool(product.get("is_archived") or product.get("archived")):
        score += 10
    pid = _product_id(product) or 0
    return score, -pid


def _error_codes(product: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for err in product.get("errors") or []:
        if isinstance(err, dict) and err.get("code"):
            codes.append(str(err.get("code")))
    return codes


def _error_blob(product: dict[str, Any]) -> str:
    parts: list[str] = []
    for err in product.get("errors") or []:
        if not isinstance(err, dict):
            continue
        parts.append(str(err.get("code") or ""))
        texts = err.get("texts") if isinstance(err.get("texts"), dict) else {}
        parts.append(str(texts.get("message") or ""))
        parts.append(str(texts.get("description") or ""))
        parts.append(json.dumps(err, ensure_ascii=False))
    return "\n".join(parts)


def parse_duplicate_offer_ids(product: dict[str, Any]) -> list[str]:
    """从 SPU 报错里解析被指为「已存在」的 offer_id。"""
    found: list[str] = []
    seen: set[str] = set()
    blob = _error_blob(product)
    # 结构化 DUPLICATES
    for match in re.finditer(r'"OFFERID"\s*:\s*"([^"]+)"', blob, re.I):
        offer = match.group(1).strip()
        if offer and offer not in seen:
            seen.add(offer)
            found.append(offer)
    self_offer = _offer_id(product)
    for offer in _OFFER_RE.findall(blob):
        offer = offer.strip()
        if offer.casefold() == self_offer.casefold():
            continue
        if offer not in seen:
            seen.add(offer)
            found.append(offer)
    return found


def is_same_account_spu_duplicate(
    product: dict[str, Any],
    *,
    company_id: str | None = None,
    known_products: dict[str, dict[str, Any]] | None = None,
) -> bool:
    codes = _error_codes(product)
    if SPU_CODE not in codes and "SPU_ALREADY_EXISTS" not in " ".join(codes):
        blob = _error_blob(product).casefold()
        if "duplicates" not in blob and "повтор" not in blob and "дубл" not in blob:
            return False
    blob = _error_blob(product)
    if company_id and "COMPANYID" in blob.upper() and str(company_id) not in blob:
        return False
    refs = parse_duplicate_offer_ids(product)
    if not refs and SPU_CODE not in codes:
        return False
    # 若冲突对象全都已归档，视为陈旧报错，不再当活跃重复
    if known_products and refs:
        active_refs = []
        for ref in refs:
            other = known_products.get(ref)
            if other is None:
                active_refs.append(ref)
                continue
            if bool(other.get("is_archived") or other.get("archived")):
                continue
            active_refs.append(ref)
        if not active_refs:
            return False
    return True


def fetch_products_by_offers(client: OzonSellerClient, offer_ids: list[str]) -> list[dict[str, Any]]:
    cleaned = [str(x).strip() for x in offer_ids if str(x).strip()]
    out: list[dict[str, Any]] = []
    for i in range(0, len(cleaned), 50):
        payload = client.get_product_info_list(offer_ids=cleaned[i : i + 50])
        items = payload.get("items") or (payload.get("result") or {}).get("items") or []
        out.extend([p for p in items if isinstance(p, dict)])
    return out


def _union_find_parent(parent: dict[str, str], key: str) -> str:
    while parent[key] != key:
        parent[key] = parent[parent[key]]
        key = parent[key]
    return key


def choose_archive_targets(
    products: list[dict[str, Any]],
    *,
    company_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    返回 (待归档商品列表, 归档货号→优先保留的 keeper 货号)。
    规则：
    - 未在售/未创建 → 归档，keeper=报错里的已存在货号
    - 在售但撞的是批次外货号 → 归档自己（重复推送）
    - 批次内互相撞 → 每个连通分量只留分最高的一张
    """
    known_all = {_offer_id(p): p for p in products if _offer_id(p)}
    spu_products = [
        p
        for p in products
        if not bool(p.get("is_archived") or p.get("archived"))
        and is_same_account_spu_duplicate(p, company_id=company_id, known_products=known_all)
    ]
    by_offer = {_offer_id(p): p for p in spu_products if _offer_id(p)}
    if not by_offer:
        return [], {}

    parent = {offer: offer for offer in by_offer}
    archive_now: dict[str, dict[str, Any]] = {}
    keeper_of: dict[str, str] = {}

    def mark_archive(offer: str, keeper: str | None) -> None:
        product = by_offer.get(offer)
        if not product:
            return
        archive_now[offer] = product
        if keeper and keeper != offer:
            keeper_of[offer] = keeper

    for offer, product in list(by_offer.items()):
        refs = [r for r in parse_duplicate_offer_ids(product) if r != offer]
        # 已归档的冲突对象不算活跃外部 keeper
        live_refs = []
        for r in refs:
            other = known_all.get(r)
            if other is not None and bool(other.get("is_archived") or other.get("archived")):
                continue
            live_refs.append(r)
        external_refs = [r for r in live_refs if r not in by_offer]
        internal_refs = [r for r in live_refs if r in by_offer]

        if not live_refs:
            # 只剩已归档冲突，保留当前卡
            continue

        if not _is_selling(product):
            mark_archive(offer, (external_refs or internal_refs or [""])[0] or None)
            continue

        if external_refs:
            # 已有同账号在售卡，当前是重复推送
            mark_archive(offer, external_refs[0])
            continue

        for other in internal_refs:
            ra = _union_find_parent(parent, offer)
            rb = _union_find_parent(parent, other)
            if ra != rb:
                parent[rb] = ra

    # 连通分量：未直接标记归档的互相冲突在售卡
    components: dict[str, list[str]] = {}
    for offer in by_offer:
        if offer in archive_now:
            continue
        root = _union_find_parent(parent, offer)
        components.setdefault(root, []).append(offer)

    for members in components.values():
        if len(members) <= 1:
            continue
        ranked = sorted(members, key=lambda o: _keep_score(by_offer[o]), reverse=True)
        survivor = ranked[0]
        for offer in ranked[1:]:
            mark_archive(offer, survivor)

    archived_set = set(archive_now)
    for offer in list(keeper_of):
        seen: set[str] = set()
        cur = keeper_of[offer]
        while cur in archived_set and cur in keeper_of and cur not in seen:
            seen.add(cur)
            cur = keeper_of[cur]
        if cur and cur not in archived_set:
            keeper_of[offer] = cur
        else:
            # 尝试同分量里未归档的货号
            root = _union_find_parent(parent, offer) if offer in parent else offer
            survivors = [
                m for m in parent
                if m not in archived_set and _union_find_parent(parent, m) == root
            ]
            if survivors:
                keeper_of[offer] = sorted(survivors, key=lambda o: _keep_score(by_offer[o]), reverse=True)[0]
            else:
                keeper_of.pop(offer, None)

    return list(archive_now.values()), keeper_of


def resolve_spu_duplicates(
    *,
    offer_ids: list[str] | None = None,
    products: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    client: OzonSellerClient | None = None,
) -> dict[str, Any]:
    """扫描并归档同账号 SPU 重复卡，同步清理/改写本地变体。"""
    client = client or OzonSellerClient()
    company_id = str(client.client_id or "").strip()

    if products is None:
        if not offer_ids:
            return {"ok": True, "archived": [], "kept": [], "dry_run": dry_run, "message": "无货号"}
        products = fetch_products_by_offers(client, offer_ids)

    targets, keeper_of = choose_archive_targets(products, company_id=company_id)
    archive_ids: list[int] = []
    archive_offers: list[str] = []
    for product in targets:
        pid = _product_id(product)
        offer = _offer_id(product)
        if pid and offer:
            archive_ids.append(pid)
            archive_offers.append(offer)

    # 去重保序
    seen_pid: set[int] = set()
    uniq_ids: list[int] = []
    uniq_offers: list[str] = []
    for pid, offer in zip(archive_ids, archive_offers):
        if pid in seen_pid:
            continue
        seen_pid.add(pid)
        uniq_ids.append(pid)
        uniq_offers.append(offer)

    known_for_count = {_offer_id(p): p for p in products if _offer_id(p)}
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "spu_count": sum(
            1
            for p in products
            if not bool(p.get("is_archived") or p.get("archived"))
            and is_same_account_spu_duplicate(
                p, company_id=company_id, known_products=known_for_count
            )
        ),
        "archive_count": len(uniq_offers),
        "archived": uniq_offers,
        "keepers": keeper_of,
        "api": None,
        "local_deleted_edits": [],
        "remapped": [],
        "message": "",
    }

    if not uniq_ids:
        result["message"] = "没有需要归档的同账号 SPU 重复卡"
        return result

    if dry_run:
        result["message"] = f"dry-run：将归档 {len(uniq_offers)} 张重复卡"
        return result

    # 1) 本地：能映射到 keeper 的先改货号，其余删除
    to_delete: list[str] = []
    for offer in uniq_offers:
        keeper = keeper_of.get(offer)
        if keeper:
            if remap_product_edit_variant_sku(offer, keeper):
                result["remapped"].append({"from": offer, "to": keeper})
            else:
                to_delete.append(offer)
        else:
            to_delete.append(offer)
    if to_delete:
        result["local_deleted_edits"] = delete_product_edit_variants_by_skus(to_delete)

    # 2) Ozon 归档
    api_results = []
    for i in range(0, len(uniq_ids), 100):
        chunk = uniq_ids[i : i + 100]
        try:
            api_results.append(client.archive_products(chunk))
        except OzonSellerError as exc:
            logger.exception("归档失败 product_ids=%s", chunk)
            result["ok"] = False
            result["message"] = f"归档 API 失败: {exc}"
            result["api"] = api_results
            return result
    result["api"] = api_results
    result["message"] = f"已归档 {len(uniq_offers)} 张同账号 SPU 重复卡"
    return result


def resolve_spu_duplicates_for_edit(edit_id: int, *, dry_run: bool = False) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    offers = [str(v.get("sku") or "").strip() for v in (edit.get("variants") or []) if v.get("sku")]
    # 把报错里引用到的 keeper 也拉进来，便于连通判断
    client = OzonSellerClient()
    products = fetch_products_by_offers(client, offers) if offers else []
    extra_refs: list[str] = []
    for product in products:
        if is_same_account_spu_duplicate(product, company_id=client.client_id):
            extra_refs.extend(parse_duplicate_offer_ids(product))
    known = {_offer_id(p) for p in products}
    missing = [o for o in dict.fromkeys(extra_refs) if o not in known]
    if missing:
        products.extend(fetch_products_by_offers(client, missing))
    result = resolve_spu_duplicates(products=products, dry_run=dry_run, client=client)
    result["edit_id"] = edit_id
    if not dry_run and result.get("archive_count"):
        # 清掉失败痕迹，避免日修再对已归档货号烧 AI
        attrs = dict(get_product_edit(edit_id).get("attributes") or {})
        attrs["last_spu_archive"] = result.get("message") or ""
        attrs.pop("publish_fail_reason", None)
        update_product_edit(edit_id, attributes=attrs, clear_listing=True)
    return result


def error_blob_looks_like_same_account_spu(error_text: str, *, company_id: str | None = None) -> bool:
    text = str(error_text or "")
    if SPU_CODE not in text and "DUPLICATES" not in text.upper():
        return False
    if company_id and "COMPANYID" in text.upper():
        return str(company_id) in text
    return True


def offers_mentioned_in_error(error_text: str) -> list[str]:
    return list(dict.fromkeys(_OFFER_RE.findall(str(error_text or ""))))
