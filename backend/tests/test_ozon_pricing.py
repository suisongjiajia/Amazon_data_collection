from services.xingyuan_freight import calc_xingyuan_economy_freight_cny, select_russia_economy_channel
from services.ozon_pricing_service import calc_suggested_price_rub


def test_select_channel_by_weight():
    assert select_russia_economy_channel(200).code == "xy_economy_extra_small"
    assert select_russia_economy_channel(800).code == "xy_economy_small"
    assert select_russia_economy_channel(3000).code == "xy_economy_big"


def test_calc_xingyuan_economy_freight():
    result = calc_xingyuan_economy_freight_cny(200)
    assert result["channel_code"] == "xy_economy_extra_small"
    assert result["freight_cny"] == round(3.37 + 0.0281 * 200, 2)


def test_pricing_formula_a():
    # (60+40)*1.3/0.8 * 12 = 100*1.625*12 = 1950
    result = calc_suggested_price_rub(
        supplier_price_cny=60,
        freight_cny=40,
        commission_rate=0.20,
        profit_markup=1.30,
        rub_per_cny=12,
    )
    assert result["price_rub"] == 1950
    assert result["stock_qty"] == 99 or result["stock_qty"] > 0
