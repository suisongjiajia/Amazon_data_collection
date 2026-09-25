from integrations.qwen_image.client import extract_image_urls


def test_extract_image_urls_from_nested_payload():
    payload = {
        "output": {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"image": "https://cdn.example.com/a.png"},
                            {"text": "ok"},
                        ]
                    }
                }
            ]
        },
        "request_id": "req-1",
    }
    urls = extract_image_urls(payload)
    assert urls == ["https://cdn.example.com/a.png"]
