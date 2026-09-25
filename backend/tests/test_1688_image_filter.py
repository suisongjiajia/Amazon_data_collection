from collector.alibaba1688.image_filter import filter_1688_product_images, is_1688_product_image


def test_rejects_logo_icon_gif():
    assert not is_1688_product_image("https://cbu01.alicdn.com/img/logo.png")
    assert not is_1688_product_image("https://img.alicdn.com/icon/foo.jpg")
    assert not is_1688_product_image("https://cbu01.alicdn.com/img/ibank/x.gif")
    assert not is_1688_product_image("https://img.alicdn.com/imgextra/banner/x.jpg")


def test_keeps_ibank_product_photo():
    url = "https://cbu01.alicdn.com/img/ibank/O1CN01abc123_1234567890_!!0-0-cib.jpg"
    assert is_1688_product_image(url)


def test_filter_prefers_and_caps():
    prefer = ["https://cbu01.alicdn.com/img/ibank/prefer.jpg"]
    pool = [
        "https://img.alicdn.com/imgextra/i1/banner/x.jpg",
        "https://cbu01.alicdn.com/img/ibank/a.jpg",
        "https://cbu01.alicdn.com/img/ibank/b.jpg",
        "https://cbu01.alicdn.com/img/logo.png",
        *prefer,
    ]
    out = filter_1688_product_images(pool, max_count=2, prefer=prefer)
    assert out[0].endswith("prefer.jpg")
    assert len(out) == 2
    assert all("logo" not in u and "banner" not in u for u in out)
