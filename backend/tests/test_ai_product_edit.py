import json

import pytest

from integrations.deepseek.client import parse_json_response
from services.ai_product_edit_service import _normalize_ai_result, generate_product_edit


def test_parse_json_response_strips_markdown_fence():
    raw = '```json\n{"title": "Test"}\n```'
    assert parse_json_response(raw)["title"] == "Test"


def test_normalize_ai_result_builds_variants_and_attributes():
    context = {
        "ozon_product": {
            "external_id": "1002277569",
            "title": "Zekkert",
            "price_text": "1614 ₽",
            "images": ["https://example.com/1.jpg"],
            "main_image_url": "https://example.com/main.jpg",
        }
    }
    raw = {
        "title": "Стойки стабилизатора Zekkert",
        "description": "Комплект для Ford Focus",
        "bullet_points": ["2 шт", "Сталь"],
        "attributes": {"Тип": "стабилизатор", "Длина, мм": "298"},
        "search_keywords": ["ford", "focus"],
        "category_hint": "Авто / Запчасти",
        "variants": [{"title": "Стойки 2 шт", "price": 1599, "quantity": 20}],
        "listing_notes": "定价略低于竞品",
    }
    result = _normalize_ai_result(raw, context)
    assert result["title"].startswith("Стойки")
    assert len(result["bullet_points"]) == 2
    assert result["attributes"]["category_hint"] == "Авто / Запчасти"
    assert result["variants"][0]["sku"] == "OZON-1002277569"
    assert result["variants"][0]["price"] is None
    assert result["variants"][0]["quantity"] == 99


def test_generate_product_edit_with_mocked_client(monkeypatch):
    family = {
        "id": 3,
        "external_id": "1002277569",
        "title": "Zekkert",
        "main_image_url": "https://example.com/main.jpg",
        "variants": [{"id": 1, "price_text": "1614 ₽", "variant_attributes": {}}],
        "raw_payload": {"rawPayload": {"details": {"description": "desc", "attributes": {"Тип": "x"}}}},
    }

    class FakeClient:
        def chat_json(self, **kwargs):
            return {
                "title": "AI Title",
                "description": "AI Desc",
                "bullet_points": ["a"],
                "attributes": {"Brand": "Zekkert"},
                "variants": [{"title": "AI Title"}],
            }

    monkeypatch.setattr("services.ai_product_edit_service.get_ozon_product_family", lambda _id: family)
    monkeypatch.setattr("services.ai_product_edit_service.list_supplier_candidates", lambda _id, limit=20: [])
    monkeypatch.setattr("services.ai_product_edit_service.DeepSeekClient", lambda: FakeClient())
    monkeypatch.setattr(
        "services.ai_product_edit_service._apply_pricing_and_images",
        lambda family_id, suggestion, rehost_images=True: {
            "suggestion": {
                **suggestion,
                "variants": [
                    {
                        **suggestion["variants"][0],
                        "price": 1500,
                        "quantity": 99,
                    }
                ],
            },
            "pricing": None,
            "image_rehost": None,
        },
    )

    result = generate_product_edit(3, rehost_images=False)
    assert result["suggestion"]["title"] == "AI Title"
    assert result["suggestion"]["variants"][0]["price"] == 1500
    assert result["suggestion"]["variants"][0]["quantity"] == 99
