from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any

from db.ozon_workflow import get_product_edit, reopen_product_edit, submit_product_edit_for_review
from db.shop_pipeline import find_pipeline_item_by_edit, update_pipeline_item
from integrations.deepseek.client import DeepSeekClient, DeepSeekError
from services import ozon_publish_service, product_edit_service
from services.ozon_listing_payload import preview_listing

logger = logging.getLogger(__name__)

_follow_lock = threading.Lock()
_active_follows: set[int] = set()

HEAL_SYSTEM_PROMPT = """你是 Ozon Seller API 上架排错专家。根据报错信息与当前 listing，输出修正后的商品编辑 JSON。

只输出 JSON，字段：
title, description, bullet_points, attributes, variants（含 sku/title/price/quantity）, images

硬性规则：
1. 保留 description_category_id、type_id、currency_code、fulfillment、brand_mode；不要删图片。
2. INCORRECT_DENSITY / «Неверные габариты или вес» / density：
   - 包裹长宽高用毫米；重量用克（Вес товара, г / weight）。
   - 体积大但重量过轻时：提高重量到合理下限，或把尺寸改成折叠后真实外包装尺寸。
   - 宠物梳子/粉剂等小件：典型重量数百克到 1kg+，不要用 20–50g 配很大盒子。
3. 字典属性错误（«все возможные значения собраны в виде списка» / Рецепт 等）：
   - 不要手填自由文本；改成该类目常见俄语字典选项，或删除该属性键让系统跳过。
   - 不确定时删除报错提到的属性键，不要瞎编。
4. 旧价 old_price 由系统按售价×1.2 生成，你只需保证 variants[].price > 0。
5. variants[].quantity 必须保持原值或使用较大正整数（如 99），禁止改成 0/1/2 等过小库存。
6. 标题/描述保持俄语；不要编造违法信息。
"""


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _content_score_min() -> float:
    return float(_env_int("CONTENT_SCORE_MIN", 57))


def _heal_max_attempts() -> int:
    return max(1, min(_env_int("PUBLISH_HEAL_MAX_ATTEMPTS", 5), 10))


def _auto_publish_simulate() -> bool:
    raw = (os.getenv("OZON_AUTO_PUBLISH_SIMULATE") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def extract_content_score(product_info: dict[str, Any] | None) -> float | None:
    """从 Ozon 商品详情中尽力提取内容评分。"""
    if not isinstance(product_info, dict):
        return None
    candidates: list[Any] = []
    for key, value in product_info.items():
        lower = str(key).lower()
        if any(token in lower for token in ("content_rating", "content_score", "description_score", "контент")):
            candidates.append(value)
        if lower in {"rating", "score"} and isinstance(value, (int, float)):
            candidates.append(value)
    nested = product_info.get("content_rating") or product_info.get("ratings")
    if isinstance(nested, dict):
        for value in nested.values():
            candidates.append(value)
    for value in candidates:
        score = _to_score(value)
        if score is not None:
            return score
    return None


def _to_score(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if 0 <= number <= 100 else None
    text = str(value).strip().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    return number if 0 <= number <= 100 else None


def approve_and_auto_publish(
    edit_id: int,
    *,
    note: str | None = None,
    reviewer: str | None = "owner",
) -> dict[str, Any]:
    """审核通过后立即真实推送，并后台拉取状态 / 低分重生 / 失败自愈。"""
    from services.review_service import approve as review_approve

    result = review_approve(edit_id, note=note, reviewer=reviewer)
    pipeline_item = find_pipeline_item_by_edit(edit_id)
    if pipeline_item:
        update_pipeline_item(int(pipeline_item["id"]), status="approved")

    try:
        publish_task = ozon_publish_service.publish_edit(
            edit_id,
            shop_name=None,
            simulate=_auto_publish_simulate(),
            auto_follow=True,
        )
    except Exception as exc:
        if pipeline_item:
            update_pipeline_item(
                int(pipeline_item["id"]),
                status="publish_failed",
                error_message=f"自动发布失败: {exc}",
            )
        raise

    if pipeline_item:
        update_pipeline_item(
            int(pipeline_item["id"]),
            status="publishing",
            publish_task_id=int(publish_task["id"]),
            clear_error=True,
        )

    return {
        **result,
        "publish_task": publish_task,
        "auto_publish": True,
        "simulate": _auto_publish_simulate(),
    }


def start_publish_follow(task_id: int, edit_id: int) -> None:
    """推送后启动后台跟进：拉状态 → 不可售则补库存/自愈重推 → 直到可售。"""
    task_id = int(task_id)
    edit_id = int(edit_id)
    with _follow_lock:
        if task_id in _active_follows:
            return
        _active_follows.add(task_id)

    def _runner() -> None:
        try:
            _follow_publish_lifecycle(task_id, edit_id)
        finally:
            with _follow_lock:
                _active_follows.discard(task_id)

    threading.Thread(
        target=_runner,
        name=f"publish-follow-{task_id}",
        daemon=True,
    ).start()


def _follow_publish_lifecycle(task_id: int, edit_id: int) -> None:
    try:
        _poll_and_handle(task_id, edit_id)
    except Exception:
        logger.exception("发布跟进失败 task_id=%s edit_id=%s", task_id, edit_id)


def _poll_and_handle(task_id: int, edit_id: int) -> None:
    max_rounds = 20
    pushed_rounds = 0
    for round_idx in range(max_rounds):
        time.sleep(8 if round_idx == 0 else 12)
        try:
            task = ozon_publish_service.refresh_import_status(task_id)
        except Exception as exc:
            logger.warning("拉取发布状态失败 task_id=%s: %s", task_id, exc)
            continue

        status = str(task.get("status") or "")
        pipeline_item = find_pipeline_item_by_edit(edit_id)

        if status == "failed":
            healed = _try_heal_and_republish(edit_id, task)
            if healed:
                return
            if pipeline_item:
                update_pipeline_item(
                    int(pipeline_item["id"]),
                    status="publish_failed",
                    error_message=task.get("error_message") or "发布失败且自愈耗尽",
                    publish_task_id=task_id,
                )
            _send_back_to_review(edit_id, reason=task.get("error_message") or "发布失败")
            return

        # 仅「可售/上架成功」才算完成；pushed = 已创建但仍不可售，必须继续跟进
        if status in {"listed", "success", "completed"}:
            score = _read_task_content_score(task)
            if pipeline_item and score is not None:
                update_pipeline_item(int(pipeline_item["id"]), content_score=score)
            if score is not None and score < _content_score_min():
                _regenerate_for_low_score(edit_id, score)
                if pipeline_item:
                    update_pipeline_item(
                        int(pipeline_item["id"]),
                        status="pending_review",
                        content_score=score,
                        error_message=f"内容评分 {score} < {_content_score_min()}，已重生并退回审核",
                    )
                return
            if pipeline_item:
                update_pipeline_item(
                    int(pipeline_item["id"]),
                    status="published",
                    publish_task_id=task_id,
                    clear_error=True,
                )
            return

        if status in {"pushed", "partial"}:
            pushed_rounds += 1
            if pipeline_item:
                update_pipeline_item(
                    int(pipeline_item["id"]),
                    status="publishing",
                    publish_task_id=task_id,
                    error_message=task.get("error_message") or "已推送但仍不可售，继续补库存/修复",
                )
            # 连续多轮仍不可售：先规则+AI 修 listing 再重推；库存类也会在 refresh 里反复推
            if pushed_rounds in {3, 6, 9}:
                logger.info(
                    "不可售持续跟进，触发自愈重推 edit_id=%s task_id=%s round=%s",
                    edit_id,
                    task_id,
                    pushed_rounds,
                )
                healed = _try_heal_and_republish(edit_id, task)
                if healed:
                    return
            continue

        # awaiting_pull / pending → 继续轮询

    # 超时仍未可售
    pipeline_item = find_pipeline_item_by_edit(edit_id)
    if pipeline_item:
        update_pipeline_item(
            int(pipeline_item["id"]),
            status="publish_failed",
            error_message="跟进超时：商品仍未变为可售，请检查库存仓库或回编辑修复",
            publish_task_id=task_id,
        )
    logger.warning("发布跟进超时仍未可售 task_id=%s edit_id=%s", task_id, edit_id)


def _read_task_content_score(task: dict[str, Any]) -> float | None:
    for item in task.get("items") or []:
        payload = item.get("response_payload") or {}
        if not isinstance(payload, dict):
            continue
        product = payload.get("product") or payload.get("product_info") or {}
        if isinstance(product, dict):
            score = extract_content_score(product)
            if score is not None:
                return score
        score = extract_content_score(payload)
        if score is not None:
            return score
    return None


def _try_heal_and_republish(edit_id: int, failed_task: dict[str, Any]) -> bool:
    try:
        result = heal_and_republish(edit_id, source_task=failed_task, auto_follow=True)
        return bool(result.get("ok"))
    except Exception as exc:
        logger.exception("AI 自愈失败 edit_id=%s: %s", edit_id, exc)
        return False


def heal_and_republish(
    edit_id: int,
    *,
    source_task: dict[str, Any] | None = None,
    auto_follow: bool = True,
) -> dict[str, Any]:
    """对发布失败的编辑做规则修复 + AI 修复，然后重新推送。"""
    from db.ozon_workflow import update_product_edit

    edit = get_product_edit(edit_id)
    pipeline_item = find_pipeline_item_by_edit(edit_id)
    attempts = int((pipeline_item or {}).get("heal_attempts") or 0)
    attrs = dict(edit.get("attributes") or {})
    attempts = max(attempts, int(attrs.get("heal_attempts") or 0))
    if attempts >= _heal_max_attempts():
        raise ValueError(f"AI 自愈已达上限（{_heal_max_attempts()} 次），请人工回编辑修复")

    if source_task is None:
        source_task = {
            "status": edit.get("status"),
            "error_message": attrs.get("publish_fail_reason") or "",
            "items": [],
        }
        # 尽量带上最近一次发布任务明细
        try:
            tasks = ozon_publish_service.list_tasks(limit=30)
            for task in tasks:
                if int(task.get("edit_id") or 0) == edit_id:
                    source_task = task
                    break
        except Exception:
            pass

    error_blob = {
        "task_status": source_task.get("status"),
        "error_message": source_task.get("error_message"),
        "items": [
            {
                "seller_sku": item.get("seller_sku"),
                "error_code": item.get("error_code"),
                "error_message": item.get("error_message"),
                "submission_payload": item.get("submission_payload"),
                "response_payload": item.get("response_payload"),
            }
            for item in (source_task.get("items") or [])
        ],
    }
    error_text = json.dumps(error_blob, ensure_ascii=False)

    # 1) 规则修复（密度 / 明显字典属性）
    edit = _apply_deterministic_fixes(edit, error_text)

    # 2) AI 修复
    preview = preview_listing(edit)
    qty_by_sku = {
        str(v.get("sku") or ""): v.get("quantity")
        for v in (edit.get("variants") or [])
        if v.get("sku")
    }
    fixed = _ai_heal_listing(edit, preview, error_blob)
    # 禁止 AI 把库存改成过小值
    from services.ozon_pricing_service import DEFAULT_STOCK_QTY

    default_qty = _env_int("OZON_DEFAULT_STOCK_QTY", DEFAULT_STOCK_QTY)
    for variant in fixed.get("variants") or []:
        sku = str(variant.get("sku") or "")
        try:
            qty = int(variant.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        original = qty_by_sku.get(sku)
        try:
            original_qty = int(original) if original is not None else 0
        except (TypeError, ValueError):
            original_qty = 0
        if qty < 10:
            variant["quantity"] = original_qty if original_qty >= 10 else default_qty
    reopen_product_edit(edit_id)
    product_edit_service.apply_ai_suggestion_to_edit(edit_id, fixed)

    # 3) 再跑一遍密度规则，避免 AI 仍给过轻重量
    edit = get_product_edit(edit_id)
    edit = _apply_deterministic_fixes(edit, error_text)
    attrs = dict(edit.get("attributes") or {})
    attrs["heal_attempts"] = str(attempts + 1)
    attrs["last_heal_errors"] = (source_task.get("error_message") or "")[:1000]
    update_product_edit(edit_id, attributes=attrs)

    built = product_edit_service.build_listing(edit_id)
    if not built.get("ok") or not built.get("saved"):
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (built.get("issues") or [])
            if issue.get("severity") == "error"
        )
        raise ValueError(f"自愈后 Listing 仍校验失败：{messages or built.get('build_error') or '未知'}")

    update_product_edit(edit_id, status="approved")
    new_task = ozon_publish_service.publish_edit(
        edit_id,
        simulate=_auto_publish_simulate(),
        auto_follow=auto_follow,
    )
    if pipeline_item:
        update_pipeline_item(
            int(pipeline_item["id"]),
            heal_attempts=attempts + 1,
            status="publishing",
            publish_task_id=int(new_task["id"]),
            error_message=f"第 {attempts + 1} 次 AI 自愈重推",
            clear_error=False,
        )

    return {
        "ok": True,
        "heal_attempt": attempts + 1,
        "publish_task": new_task,
        "message": f"已完成第 {attempts + 1} 次 AI 修复并重新推送（后台将继续拉取直到可售）",
    }


def _apply_deterministic_fixes(edit: dict[str, Any], error_text: str) -> dict[str, Any]:
    """针对 density / 字典属性做可预期的机械修复。"""
    from db.ozon_workflow import update_product_edit
    from services.ozon_listing_payload import read_package_metrics, read_variant_package_metrics

    edit_id = int(edit["id"])
    attrs = dict(edit.get("attributes") or {})
    lower = (error_text or "").lower()
    changed = False

    # 字典属性：报错点名 Рецепт 等时，删除自由文本，避免再次提交非法值
    dict_tokens = ("списка", "dictionary", "рецепт", "неверное значение атрибута")
    if any(token in lower for token in dict_tokens):
        for key in list(attrs.keys()):
            key_l = str(key).lower()
            if "рецепт" in key_l or "состав" in key_l:
                attrs.pop(key, None)
                changed = True
        # 也从报错文本里抠属性名
        for match in re.finditer(r"([А-Яа-яA-Za-z0-9 #/,\-]{2,80}):\s*Неверное значение", error_text or ""):
            name = match.group(1).strip()
            if name in attrs:
                attrs.pop(name, None)
                changed = True

    # 统一包裹尺寸：100×100×100 mm / 200g（覆盖密度自愈）
    from services.ozon_listing_payload import apply_fixed_package_attributes, force_package_metrics_enabled

    if force_package_metrics_enabled():
        attrs = apply_fixed_package_attributes(attrs)
        changed = True
    else:
        depth, width, height, weight = read_package_metrics(attrs)
        if depth and width and height:
            volume_cm3 = (depth * width * height) / 1000.0
            min_weight = max(80, int((volume_cm3 * 0.003) + 0.999))
            current_weight = int(weight or 0)
            if current_weight < min_weight:
                attrs["Вес товара, г"] = str(min_weight)
                attrs["weight"] = str(min_weight)
                attrs["weight_g"] = str(min_weight)
                changed = True

        for variant in edit.get("variants") or []:
            v_depth, v_width, v_height, v_weight = read_variant_package_metrics(attrs, variant)
            if not (v_depth and v_width and v_height):
                continue
            volume_cm3 = (v_depth * v_width * v_height) / 1000.0
            min_weight = max(80, int((volume_cm3 * 0.003) + 0.999))
            if int(v_weight or 0) < min_weight:
                attrs["Вес товара, г"] = str(min_weight)
                attrs["weight"] = str(min_weight)
                changed = True

    if changed:
        update_product_edit(edit_id, attributes=attrs)
        return get_product_edit(edit_id)
    return edit


def _ai_heal_listing(
    edit: dict[str, Any],
    preview: dict[str, Any],
    error_blob: dict[str, Any],
) -> dict[str, Any]:
    client = DeepSeekClient()
    user_prompt = (
        "请根据 Ozon 报错修复 listing。优先处理 density/尺寸重量 与 字典属性。"
        "不确定的字典属性请删除该键。当前数据：\n\n"
        + json.dumps(
            {
                "edit": {
                    "title": edit.get("title"),
                    "description": edit.get("description"),
                    "bullet_points": edit.get("bullet_points"),
                    "attributes": edit.get("attributes"),
                    "variants": edit.get("variants"),
                    "images": edit.get("images"),
                },
                "preview_issues": preview.get("issues"),
                "errors": error_blob,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    try:
        raw = client.chat_json(system_prompt=HEAL_SYSTEM_PROMPT, user_prompt=user_prompt, temperature=0.2)
    except DeepSeekError:
        raise
    if not isinstance(raw, dict) or not raw.get("title"):
        raise DeepSeekError("AI 自愈未返回有效标题")
    if not raw.get("images"):
        raw["images"] = edit.get("images") or []
    # 强制保留类目 ID
    attrs = dict(edit.get("attributes") or {})
    incoming = dict(raw.get("attributes") or {})
    for key in ("description_category_id", "type_id", "currency_code", "fulfillment", "brand_mode"):
        if attrs.get(key):
            incoming[key] = attrs[key]
    raw["attributes"] = incoming
    return raw


def _regenerate_for_low_score(edit_id: int, score: float) -> None:
    edit = get_product_edit(edit_id)
    family_id = int(edit["raw_product_family_id"])
    from services import ai_product_edit_service

    reopen_product_edit(edit_id)
    ai_result = ai_product_edit_service.generate_product_edit(family_id, rehost_images=False)
    suggestion = ai_result["suggestion"]
    attrs = dict(suggestion.get("attributes") or {})
    attrs["content_score_regen"] = str(score)
    attrs["regen_reason"] = f"内容评分 {score} < {_content_score_min()}"
    suggestion["attributes"] = attrs
    product_edit_service.apply_ai_suggestion_to_edit(edit_id, suggestion)
    built = product_edit_service.build_listing(edit_id)
    if built.get("ok") and built.get("saved"):
        submit_product_edit_for_review(edit_id)


def _send_back_to_review(edit_id: int, *, reason: str) -> None:
    try:
        reopen_product_edit(edit_id)
        edit = get_product_edit(edit_id)
        attrs = dict(edit.get("attributes") or {})
        attrs["publish_fail_reason"] = reason[:1000]
        from db.ozon_workflow import update_product_edit

        update_product_edit(edit_id, attributes=attrs, status="editing")
        built = product_edit_service.build_listing(edit_id)
        if built.get("ok") and built.get("saved"):
            submit_product_edit_for_review(edit_id)
    except Exception:
        logger.exception("退回审核失败 edit_id=%s", edit_id)
