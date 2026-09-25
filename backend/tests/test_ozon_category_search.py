from services.ozon_category_tree import _tokenize_query, search_types_by_query


def test_tokenize_query_chinese():
    tokens = _tokenize_query("宠物隧道玩具 85厘米")
    assert "宠物" in tokens or "隧道" in tokens
    assert "玩具" in tokens or any("玩" in t for t in tokens)


def test_search_types_by_query_scores(monkeypatch):
    import services.ozon_category_tree as tree

    monkeypatch.setattr(
        tree,
        "load_type_category_index",
        lambda force=False: {1: 10, 2: 20},
    )
    tree._TYPE_TO_NAME.clear()
    tree._TYPE_TO_CATEGORY.clear()
    tree._TYPE_TO_NAME.update(
        {
            1: "宠物隧道玩具",
            2: "汽车脚垫",
            3: "宠物屋",
        }
    )
    tree._TYPE_TO_CATEGORY.update({1: 100, 2: 200, 3: 300})
    tree._TREE_LOADED = True

    hits = search_types_by_query("灰色宠物隧道 85cm", limit=5)
    assert hits
    assert hits[0]["type_id"] == 1
    assert hits[0]["description_category_id"] == 100
