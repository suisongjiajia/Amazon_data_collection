"""API 候选 + AI 白名单选择字典属性。"""

from services.ozon_ai_dict_pick import (
    CandidateBundle,
    DictAttrJob,
    _validate_pick,
    ai_select_from_candidates,
    resolve_dictionary_picks,
)


class _FakeClient:
    def __init__(self, *, values=None, searches=None):
        self.values = values or []
        self.searches = searches or {}

    def get_attribute_values(self, **kwargs):
        return {"result": self.values}

    def search_attribute_values(self, **kwargs):
        q = str(kwargs.get("value") or "")
        return {"result": self.searches.get(q, self.searches.get(q.lower(), []))}


def test_validate_pick_whitelist_only():
    bundle = CandidateBundle(
        attribute_id=100,
        name="Наполнитель",
        is_required=True,
        candidates=[
            {"id": 62081, "value": "Синтепон"},
            {"id": 2, "value": "Без наполнителя"},
        ],
        best=None,
        best_score=0,
    )
    assert _validate_pick(bundle, 62081)["dictionary_value_id"] == 62081
    assert _validate_pick(bundle, 999999) is None
    assert _validate_pick(bundle, None) is None


def test_high_score_skips_ai(monkeypatch):
    """高分匹配不调用 AI。"""
    called = {"ai": 0}

    def _boom(*_a, **_k):
        called["ai"] += 1
        raise AssertionError("should not call AI")

    monkeypatch.setattr("services.ozon_ai_dict_pick.ai_select_from_candidates", _boom)
    monkeypatch.setattr("services.ozon_ai_dict_pick.ai_dict_pick_enabled", lambda: True)

    client = _FakeClient(
        searches={
            "Синтепон": [{"id": 62081, "value": "Синтепон"}],
            "синтепон": [{"id": 62081, "value": "Синтепон"}],
        },
        values=[{"id": 2, "value": "Без наполнителя"}],
    )
    jobs = [
        DictAttrJob(
            attribute_id=100,
            name="Наполнитель лежака/домика для животных",
            is_required=True,
            queries=["Синтепон"],
            hint="Синтепон",
        )
    ]
    picks = resolve_dictionary_picks(
        client=client,
        jobs=jobs,
        description_category_id=1,
        type_id=95203,
        product_context={"title": "Лежак"},
    )
    assert called["ai"] == 0
    assert picks[100]["dictionary_value_id"] == 62081
    assert picks[100]["source"] in {"score", "type_id_match"}


def test_ai_whitelist_and_reject_hallucination(monkeypatch):
    monkeypatch.setattr("services.ozon_ai_dict_pick.ai_dict_pick_enabled", lambda: True)

    def fake_ai(*, bundles, product_context):
        # 合法 id + 幻觉 id
        return {
            bundles[0].attribute_id: {
                "dictionary_value_id": 62081,
                "value": "Синтепон",
                "source": "ai_whitelist",
            }
        }

    monkeypatch.setattr("services.ozon_ai_dict_pick.ai_select_from_candidates", fake_ai)

    # 低分：搜索词对不上，强制走 AI 分支
    client = _FakeClient(
        searches={"xxx": [{"id": 62081, "value": "Синтепон"}, {"id": 2, "value": "Без"}]},
        values=[{"id": 62081, "value": "Синтепон"}, {"id": 2, "value": "Без"}],
    )
    jobs = [
        DictAttrJob(
            attribute_id=100,
            name="Наполнитель лежака/домика для животных",
            is_required=True,
            queries=["xxx"],
            hint="хлопок мягкий",
        )
    ]
    picks = resolve_dictionary_picks(
        client=client,
        jobs=jobs,
        description_category_id=1,
        type_id=95203,
        product_context={"title": "Домик"},
    )
    assert picks[100]["dictionary_value_id"] == 62081
    assert picks[100]["source"] == "ai_whitelist"


def test_ai_select_rejects_unknown_id(monkeypatch):
    class FakeDS:
        def chat_json(self, **kwargs):
            return {"picks": {"100": 999001, "101": 62081}}

    monkeypatch.setattr(
        "integrations.deepseek.client.DeepSeekClient",
        lambda **kwargs: FakeDS(),
    )
    bundles = [
        CandidateBundle(
            attribute_id=100,
            name="A",
            is_required=True,
            candidates=[{"id": 1, "value": "One"}],
            best=None,
            best_score=0,
        ),
        CandidateBundle(
            attribute_id=101,
            name="B",
            is_required=True,
            candidates=[{"id": 62081, "value": "Синтепон"}],
            best=None,
            best_score=0,
        ),
    ]
    out = ai_select_from_candidates(
        bundles=bundles,
        product_context={"title": "t"},
    )
    assert out.get(100) is None  # 幻觉 id 被拒
    assert out[101]["dictionary_value_id"] == 62081


def test_type_attr_uses_type_id_no_ai(monkeypatch):
    monkeypatch.setattr(
        "services.ozon_ai_dict_pick.ai_select_from_candidates",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no ai")),
    )
    client = _FakeClient(
        values=[
            {"id": 1, "value": "Other"},
            {"id": 95203, "value": "Лежак"},
        ]
    )
    jobs = [
        DictAttrJob(
            attribute_id=8229,
            name="Тип",
            is_required=True,
            queries=["Лежак"],
            hint="Лежак",
        )
    ]
    picks = resolve_dictionary_picks(
        client=client,
        jobs=jobs,
        description_category_id=1,
        type_id=95203,
    )
    assert picks[8229]["dictionary_value_id"] == 95203
    assert picks[8229]["source"] == "type_id_match"
