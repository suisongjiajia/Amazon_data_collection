from services.ozon_category_tree import (
    _walk_type_parents,
    correct_category_id_for_type,
    find_category_id_for_type,
    load_type_category_index,
)
import services.ozon_category_tree as tree_mod


def test_walk_type_parents_builds_index():
    tree_mod._TYPE_TO_CATEGORY.clear()
    tree_mod._TREE_LOADED = False
    nodes = [
        {
            "description_category_id": 17027495,
            "category_name": "Auto",
            "children": [
                {
                    "description_category_id": 83250454,
                    "category_name": "Garage",
                    "children": [
                        {
                            "type_id": 971107021,
                            "type_name": "Squeegee",
                            "disabled": False,
                            "children": [],
                        }
                    ],
                }
            ],
        }
    ]
    _walk_type_parents(nodes)
    assert tree_mod._TYPE_TO_CATEGORY[971107021] == 83250454


def test_correct_category_id_for_type(monkeypatch):
    monkeypatch.setattr(
        "services.ozon_category_tree.find_category_id_for_type",
        lambda type_id, force_reload=False: 83250454,
    )
    category, type_id, changed = correct_category_id_for_type(
        description_category_id="200001075",
        type_id="971107021",
    )
    assert category == "83250454"
    assert type_id == "971107021"
    assert changed is True

    category2, _, changed2 = correct_category_id_for_type(
        description_category_id="83250454",
        type_id="971107021",
    )
    assert category2 == "83250454"
    assert changed2 is False


def test_find_category_id_uses_cache(monkeypatch):
    tree_mod._TYPE_TO_CATEGORY.clear()
    tree_mod._TYPE_TO_CATEGORY[971107021] = 83250454
    tree_mod._TREE_LOADED = True
    assert find_category_id_for_type(971107021) == 83250454
    # 不应再打网络
    monkeypatch.setattr(
        "services.ozon_category_tree.load_type_category_index",
        lambda force=False: (_ for _ in ()).throw(AssertionError("should use cache")),
    )
    assert find_category_id_for_type("971107021") == 83250454
