from services.product_edit_service import delete_edit


def test_delete_edit_rejects_approved_status(monkeypatch):
    monkeypatch.setattr(
        "db.ozon_workflow.get_product_edit",
        lambda _id: {"id": 1, "status": "approved"},
    )

    try:
        delete_edit(1)
        assert False, "should raise"
    except ValueError as exc:
        assert "不能取消" in str(exc)


def test_delete_edit_allows_draft(monkeypatch):
    calls: list[tuple[str, tuple]] = []

    monkeypatch.setattr(
        "db.ozon_workflow.get_product_edit",
        lambda _id: {"id": 2, "status": "draft"},
    )

    class FakeCursor:
        def execute(self, query, params=()):
            calls.append((query, params))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("db.ozon_workflow.get_connection", lambda: FakeConnection())

    result = delete_edit(2)
    assert result["deleted"] is True
    assert calls
