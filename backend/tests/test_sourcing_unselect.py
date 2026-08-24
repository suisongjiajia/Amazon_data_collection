from services.sourcing_service import select_candidate, unselect_candidate


def test_unselect_candidate(monkeypatch):
    calls: list[tuple[int, str]] = []

    def fake_update(candidate_id: int, status: str):
        calls.append((candidate_id, status))
        return {"id": candidate_id, "status": status}

    monkeypatch.setattr("services.sourcing_service.update_supplier_candidate_status", fake_update)

    result = unselect_candidate(7)
    assert result["status"] == "candidate"
    assert calls == [(7, "candidate")]

    result = select_candidate(8)
    assert result["status"] == "selected"
    assert calls[-1] == (8, "selected")
