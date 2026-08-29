from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class XingyuanEconomyChannel:
    code: str
    name: str
    category: str
    register_fee_cny: float
    unit_price_per_gram_cny: float
    weight_min_g: int
    weight_max_g: int
    notes: str = ""


# 兴远 rFBS 俄罗斯渠道 — Economy（到取货点），2026-07-17 版
# 按重量自动选档（中档路径：Extra Small → Small → Big，不含 Budget/Premium）
RUSSIA_ECONOMY_CHANNELS: tuple[XingyuanEconomyChannel, ...] = (
    XingyuanEconomyChannel(
        code="xy_economy_extra_small",
        name="XY Economy Extra Small",
        category="Extra Small",
        register_fee_cny=3.37,
        unit_price_per_gram_cny=0.0281,
        weight_min_g=1,
        weight_max_g=550,
        notes="标准超级轻小件",
    ),
    XingyuanEconomyChannel(
        code="xy_economy_small",
        name="XY Economy Small",
        category="Small",
        register_fee_cny=17.97,
        unit_price_per_gram_cny=0.0281,
        weight_min_g=551,
        weight_max_g=2200,
        notes="标准小件",
    ),
    XingyuanEconomyChannel(
        code="xy_economy_big",
        name="XY Economy Big",
        category="Big",
        register_fee_cny=40.44,
        unit_price_per_gram_cny=0.0191,
        weight_min_g=2201,
        weight_max_g=30000,
        notes="标准大件",
    ),
)


class FreightError(ValueError):
    pass


def select_russia_economy_channel(weight_g: float) -> XingyuanEconomyChannel:
    if weight_g is None or weight_g <= 0:
        raise FreightError("重量必须大于 0 克，才能计算兴远运费")
    weight = int(round(float(weight_g)))
    for channel in RUSSIA_ECONOMY_CHANNELS:
        if channel.weight_min_g <= weight <= channel.weight_max_g:
            return channel
    if weight < RUSSIA_ECONOMY_CHANNELS[0].weight_min_g:
        return RUSSIA_ECONOMY_CHANNELS[0]
    raise FreightError(f"重量 {weight}g 超出兴远 Economy 服务范围（最大 30kg）")


def calc_xingyuan_economy_freight_cny(weight_g: float) -> dict[str, Any]:
    channel = select_russia_economy_channel(weight_g)
    weight = max(1, int(round(float(weight_g))))
    freight = channel.register_fee_cny + channel.unit_price_per_gram_cny * weight
    freight = round(freight, 2)
    return {
        "channel_code": channel.code,
        "channel_name": channel.name,
        "category": channel.category,
        "transport": "Economy",
        "weight_g": weight,
        "register_fee_cny": channel.register_fee_cny,
        "unit_price_per_gram_cny": channel.unit_price_per_gram_cny,
        "freight_cny": freight,
        "notes": channel.notes,
        "formula": (
            f"{channel.register_fee_cny} + {channel.unit_price_per_gram_cny}×{weight}g"
            f" = {freight} CNY"
        ),
    }
