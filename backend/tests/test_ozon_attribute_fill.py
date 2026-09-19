from services.ozon_attribute_fill import (
    _default_model_name,
    _score_dict_candidate,
    _tokenize_tokens,
    pick_dictionary_value,
)


class _FakeClient:
    def __init__(self, *, values=None, searches=None):
        self.values = values or []
        self.searches = searches or {}

    def get_attribute_values(self, **kwargs):
        return {"result": self.values}

    def search_attribute_values(self, **kwargs):
        q = str(kwargs.get("value") or "")
        return {"result": self.searches.get(q, [])}


def test_score_and_tokens():
    assert _score_dict_candidate("Ракель", "Ракель") == 1000
    assert _score_dict_candidate("ракел", "Ракель") >= 800
    tokens = _tokenize_tokens("Профессиональный ракель для тонировки")
    assert any("ракель" in t.lower() for t in tokens)


def test_pick_dictionary_by_type_id():
    client = _FakeClient(
        values=[
            {"id": 1, "value": "Other"},
            {"id": 971107021, "value": "Ракель"},
        ]
    )
    picked = pick_dictionary_value(
        client=client,
        attribute_id=8229,
        description_category_id=83250454,
        type_id=971107021,
        queries=["ракель"],
    )
    assert picked is not None
    assert picked["dictionary_value_id"] == 971107021
    assert picked["source"] == "type_id_match"


def test_pick_dictionary_by_search():
    client = _FakeClient(
        values=[{"id": 1, "value": "Other"}],
        searches={"ракель": [{"id": 971107021, "value": "Ракель"}]},
    )
    picked = pick_dictionary_value(
        client=client,
        attribute_id=8229,
        description_category_id=83250454,
        type_id=971107021,
        queries=["ракель"],
    )
    assert picked is not None
    assert picked["dictionary_value_id"] == 971107021


def test_skip_pdf_and_infer_color():
    from services.ozon_attribute_fill import (
        should_skip_attr_auto_fill,
        _find_source_value,
        infer_color_label,
    )

    assert should_skip_attr_auto_fill("Название файла PDF")
    assert should_skip_attr_auto_fill("Документ PDF")
    assert should_skip_attr_auto_fill("Озон.Видео: ссылка")
    assert not should_skip_attr_auto_fill("Название цвета")
    assert (
        _find_source_value(
            "Название файла PDF",
            {"название": "Домик для кошки", "названиецвета": "серый"},
        )
        is None
    )
    assert infer_color_label("https://ozon.ru/product/xxx-goluboy-5621185243/") == "голубой"
    assert infer_color_label("домик серый утепленный") == "серый"


def test_format_ozon_hashtags_and_boolean():
    from services.ozon_attribute_fill import format_ozon_hashtags, _coerce_filled_value

    tags = format_ozon_hashtags("домик для кошки уличный")
    assert "#домик" in tags
    assert "#кошки" in tags
    assert "#для" not in tags
    assert format_ozon_hashtags("#old money #k-pop") == "#old #money #k_pop"
    attr = {"name": "Нужен код маркировки", "type": "Boolean"}
    assert _coerce_filled_value(attr, "Нет") == "false"
    assert _coerce_filled_value(attr, "true") == "true"
    int_attr = {"name": "Количество", "type": "Integer"}
    assert _coerce_filled_value(int_attr, "3") == "3"
    tag_attr = {"name": "#Хештеги", "type": "String"}
    assert _coerce_filled_value(tag_attr, "cat house warm").startswith("#")


def test_default_model_name():
    assert (
        _default_model_name(
            edit_title="Профессиональный ракель / blue",
            edit_attributes={},
            variants=[{"sku": "OZON-1"}],
        )
        == "Профессиональный ракель"
    )
    assert (
        _default_model_name(
            edit_title="",
            edit_attributes={"型号": "X-100"},
            variants=[],
        )
        == "X-100"
    )
