from services.xingyuan_freight import calc_xingyuan_economy_freight_cny, select_russia_economy_channel
from services.ozon_pricing_service import calc_suggested_price_rub, variant_prices_from_collected


def test_select_channel_by_weight():
    assert select_russia_economy_channel(200).code == "xy_economy_extra_small"
    assert select_russia_economy_channel(800).code == "xy_economy_small"
    assert select_russia_economy_channel(3000).code == "xy_economy_big"


def test_calc_xingyuan_economy_freight():
    result = calc_xingyuan_economy_freight_cny(200)
    assert result["channel_code"] == "xy_economy_extra_small"
    assert result["freight_cny"] == round(3.37 + 0.0281 * 200, 2)


def test_pricing_formula_a(monkeypatch):
    # (60+40)*1.3/0.8 = 162.5 CNY；×12 = 1950 RUB
    monkeypatch.setenv("OZON_CURRENCY_CODE", "CNY")
    result = calc_suggested_price_rub(
        supplier_price_cny=60,
        freight_cny=40,
        commission_rate=0.20,
        profit_markup=1.30,
        rub_per_cny=12,
    )
    assert result["price_cny_int"] == 162
    assert result["price_rub"] == 1950
    assert result["list_price"] == 162
    assert result["currency_code"] == "CNY"
    assert result["stock_qty"] == 99 or result["stock_qty"] > 0

    monkeypatch.setenv("OZON_CURRENCY_CODE", "RUB")
    rub = calc_suggested_price_rub(
        supplier_price_cny=60,
        freight_cny=40,
        commission_rate=0.20,
        profit_markup=1.30,
        rub_per_cny=12,
    )
    assert rub["list_price"] == 1950
    assert rub["currency_code"] == "RUB"


def test_variant_prices_follow_collected_ozon_prices():
    prices = variant_prices_from_collected(
        58,
        [
            {"external_id": "4246785373", "price_text": "1326 ₽"},
            {"external_id": "4246785076", "price_text": "1147 ₽"},
            {"external_id": "4246785230", "price_text": "680 ₽"},
            {"external_id": "4246785481", "price_text": "1235 ₽"},
        ],
        anchor_external_id="4246785373",
    )
    assert prices[0] == 58
    assert prices[1] == 50
    assert prices[2] == 30
    assert prices[3] == 54
    assert len(set(prices)) > 1
