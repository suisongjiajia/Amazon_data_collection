from __future__ import annotations

from typing import Any

from db.connection import get_connection
from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import get_product_edit, update_product_edit
from integrations.ozon_seller.seller_tree import OzonSellerTreeClient, OzonSellerTreeError, ResolvedCategory
from services.ozon_category_tree import correct_category_id_for_type


def _source_sku_from_family(family: dict[str, Any]) -> str:
    external_id = str(family.get("external_id") or "").strip()
    if external_id.isdigit():
        return external_id
    raise ValueError(f"商品缺少有效的 Ozon SKU（external_id={family.get('external_id')!r}）")


def update_family_category_ids(
    family_id: int,
    *,
    description_category_id: str,
    type_id: str,
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE raw_product_family
                SET category_id = %s,
                    type_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (str(description_category_id), str(type_id), family_id),
            )


def _apply_tree_correction(
    *,
    description_category_id: str,
    type_id: str,
) -> tuple[str, str, bool]:
    category, type_text, changed = correct_category_id_for_type(
        description_category_id=description_category_id,
        type_id=type_id,
    )
    return (
        str(category or description_category_id),
        str(type_text or type_id),
        changed,
    )


def resolve_category_for_family(
    family_id: int,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    用源商品 SKU 调用卖家后台 resolve/by-sku，写入 family.category_id / type_id。
    再用官方类目树按 type_id 校正 description_category_id（Seller API 认父类目）。
    force=False 时若已有完整 ID，仍会做树校正。
    """
    family = get_ozon_product_family(family_id)
    existing_category = str(family.get("category_id") or "").strip()
    existing_type = str(family.get("type_id") or "").strip()
    source = "cached"
    raw: dict[str, Any] | None = None

    if force or not (existing_category.isdigit() and existing_type.isdigit()):
        sku = _source_sku_from_family(family)
        client = OzonSellerTreeClient()
        try:
            resolved: ResolvedCategory = client.resolve_by_sku(sku)
        except OzonSellerTreeError as exc:
            # Cookie 失效时：若已有 type_id，仍可用官方树校正类目
            if existing_type.isdigit():
                category_id, type_id, changed = _apply_tree_correction(
                    description_category_id=existing_category,
                    type_id=existing_type,
                )
                if changed or not existing_category.isdigit():
                    update_family_category_ids(
                        family_id,
                        description_category_id=category_id,
                        type_id=type_id,
                    )
                return {
                    "family_id": family_id,
                    "sku": family.get("external_id"),
                    "description_category_id": category_id,
                    "type_id": type_id,
                    "source": "tree_corrected_after_seller_tree_error",
                    "warning": str(exc),
                }
            raise RuntimeError(str(exc)) from exc

        existing_category = resolved.description_category_id
        existing_type = resolved.type_id
        source = "seller_tree"
        raw = resolved.raw
        sku_out = sku
    else:
        sku_out = family.get("external_id")

    category_id, type_id, changed = _apply_tree_correction(
        description_category_id=existing_category,
        type_id=existing_type,
    )
    if changed:
        source = f"{source}+tree_corrected"

    update_family_category_ids(
        family_id,
        description_category_id=category_id,
        type_id=type_id,
    )
    result = {
        "family_id": family_id,
        "sku": sku_out,
        "description_category_id": category_id,
        "type_id": type_id,
        "source": source,
    }
    if raw is not None:
        result["raw"] = raw
    return result


def ensure_edit_category_ids(edit_id: int, *, force: bool = False) -> dict[str, Any]:
    """确保 product_edit.attributes 含可用的 description_category_id / type_id。"""
    edit = get_product_edit(edit_id)
    attributes = dict(edit.get("attributes") or {})
    category_id = str(attributes.get("description_category_id") or attributes.get("category_id") or "").strip()
    type_id = str(attributes.get("type_id") or "").strip()

    # 已有 type 时先按官方树校正（修复误存的 level_4 / 错误 level_3）
    if type_id.isdigit():
        corrected_category, corrected_type, changed = _apply_tree_correction(
            description_category_id=category_id,
            type_id=type_id,
        )
        if changed:
            attributes["description_category_id"] = corrected_category
            attributes["type_id"] = corrected_type
            attributes.pop("category_resolve_error", None)
            updated = update_product_edit(edit_id, attributes=attributes)
            family_id = int(edit["raw_product_family_id"])
            update_family_category_ids(
                family_id,
                description_category_id=corrected_category,
                type_id=corrected_type,
            )
            if not force:
                return {
                    "edit_id": edit_id,
                    "description_category_id": corrected_category,
                    "type_id": corrected_type,
                    "source": "tree_corrected",
                    "edit": updated,
                }
            category_id = corrected_category
            type_id = corrected_type

    if not force and category_id.isdigit() and type_id.isdigit():
        return {
            "edit_id": edit_id,
            "description_category_id": category_id,
            "type_id": type_id,
            "source": "edit_attributes",
            "edit": edit,
        }

    family_id = int(edit["raw_product_family_id"])
    resolved = resolve_category_for_family(family_id, force=force)
    attributes["description_category_id"] = resolved["description_category_id"]
    attributes["type_id"] = resolved["type_id"]
    attributes.pop("category_resolve_error", None)

    updated = update_product_edit(edit_id, attributes=attributes)
    return {
        "edit_id": edit_id,
        "description_category_id": resolved["description_category_id"],
        "type_id": resolved["type_id"],
        "source": resolved.get("source"),
        "sku": resolved.get("sku"),
        "edit": updated,
    }


def apply_resolved_ids_to_attributes(
    attributes: dict[str, Any],
    *,
    description_category_id: str,
    type_id: str,
) -> dict[str, Any]:
    merged = dict(attributes or {})
    category, type_text, _changed = correct_category_id_for_type(
        description_category_id=description_category_id,
        type_id=type_id,
    )
    merged["description_category_id"] = str(category or description_category_id)
    merged["type_id"] = str(type_text or type_id)
    merged.pop("category_resolve_error", None)
    return merged


def mark_category_resolve_error(edit_id: int, message: str) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    attributes = dict(edit.get("attributes") or {})
    attributes["category_resolve_error"] = message
    return update_product_edit(edit_id, attributes=attributes)
