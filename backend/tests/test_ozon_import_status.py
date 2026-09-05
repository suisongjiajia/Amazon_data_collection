from services.ozon_import_status import (
    aggregate_task_status,
    extract_import_task_id,
    format_ozon_item_errors,
    is_ozon_product_sellable,
    map_ozon_item_status,
    parse_import_info_items,
    resolve_publish_item_status,
    summarize_item_errors,
)


def test_extract_import_task_id():
    assert extract_import_task_id({"result": {"task_id": 778899}}) == 778899
    assert extract_import_task_id({"task_id": "123"}) == 123
    assert extract_import_task_id({}) is None


def test_parse_and_map_import_info():
    payload = {
        "result": {
            "items": [
                {
                    "offer_id": "OZON-1",
                    "product_id": 11,
                    "status": "imported",
                    "errors": [],
                },
                {
                    "offer_id": "OZON-2",
                    "product_id": 0,
                    "status": "failed",
                    "errors": [{"code": "ATTR", "message": "缺少必填属性"}],
                },
                {
                    "offer_id": "OZON-3",
                    "status": "pending",
                    "errors": [],
                },
            ]
        }
    }
    items = parse_import_info_items(payload)
    assert len(items) == 3
    assert map_ozon_item_status("imported") == "success"
    assert map_ozon_item_status("skipped") == "success"
    assert map_ozon_item_status("failed") == "failed"
    assert map_ozon_item_status("pending") == "processing"

    code, message = format_ozon_item_errors(items[1]["errors"])
    assert code == "ATTR"
    assert "缺少必填属性" in (message or "")


def test_resolve_publish_item_status_sellable():
    status, code, msg = resolve_publish_item_status(
        import_raw_status="imported",
        import_errors=[],
        product_info={
            "sku": 5646903305,
            "statuses": {"is_created": True, "status": "price_sent"},
            "visibility_details": {"has_stock": True},
            "stocks": {"has_stock": True},
        },
    )
    assert status == "listed"
    assert code is None

    status2, code2, _msg2 = resolve_publish_item_status(
        import_raw_status="imported",
        import_errors=[],
        product_info={
            "sku": 5646903305,
            "statuses": {"is_created": True, "status_name": "不出售"},
            "visibility_details": {"has_stock": False},
            "stocks": {"has_stock": False},
        },
    )
    assert status2 == "pushed"
    assert code2 == "NOT_SELLABLE_YET"


def test_is_ozon_product_sellable():
    assert is_ozon_product_sellable(None) is False
    assert (
        is_ozon_product_sellable(
            {
                "sku": 1,
                "statuses": {"is_created": True},
                "stocks": {"has_stock": True},
            }
        )
        is True
    )


def test_format_errors_with_field_and_summary():
    code, message = format_ozon_item_errors(
        [
            {
                "code": "currency_differs_from_contract",
                "field": "currency",
                "message": "currency mismatch",
                "description": "currency mismatch",
                "attribute_name": "",
            }
        ]
    )
    assert code == "currency_differs_from_contract"
    assert "currency" in (message or "")
    assert "mismatch" in (message or "")

    summary = summarize_item_errors(
        [
            {
                "seller_sku": "OZON-1",
                "status": "failed",
                "error_code": "currency_differs_from_contract",
                "error_message": "currency: currency mismatch",
            }
        ]
    )
    assert summary is not None
    assert "OZON_CURRENCY_CODE" in summary
    assert "CNY" in summary


def test_aggregate_task_status():
    assert aggregate_task_status(["awaiting_pull", "processing"]) == "awaiting_pull"
    assert aggregate_task_status(["submitted", "processing"]) == "awaiting_pull"
    assert aggregate_task_status(["listed", "listed"]) == "listed"
    assert aggregate_task_status(["failed"]) == "failed"
    assert aggregate_task_status(["listed", "pushed"]) == "pushed"
    assert aggregate_task_status(["success", "success"]) == "listed"
