"""兴远 rFBS 俄罗斯 Economy 运费（2026-07-17 计算器）。

选档规则（中档路径 Extra Small → Small → Big）：
1. 先按包装尺寸命中能装下的最小渠道；
2. 再把计费重量抬到该渠道下限（尺寸优先、重量其次）；
3. 若重量超出当前档上限，再升档。
"""
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
    max_side_cm: int
    max_sum_cm: int
    use_volumetric: bool = False
    notes: str = ""


# 兴远 rFBS 俄罗斯渠道 — Economy（到取货点），2026-07-17 版
# Small 下限取 551g：尺寸装不下 Extra Small 时，重量至少提到该档才能走对应物流
RUSSIA_ECONOMY_CHANNELS: tuple[XingyuanEconomyChannel, ...] = (
    XingyuanEconomyChannel(
        code="xy_economy_extra_small",
        name="XY Economy Extra Small",
        category="Extra Small",
        register_fee_cny=3.37,
        unit_price_per_gram_cny=0.0281,
        weight_min_g=1,
        weight_max_g=550,
        max_side_cm=60,
        max_sum_cm=90,
        notes="标准超级轻小件；单边≤60cm；三边和≤90cm",
    ),
    XingyuanEconomyChannel(
        code="xy_economy_small",
        name="XY Economy Small",
        category="Small",
        register_fee_cny=17.97,
        unit_price_per_gram_cny=0.0281,
        weight_min_g=551,
        weight_max_g=2200,
        max_side_cm=60,
        max_sum_cm=150,
        notes="标准小件；单边≤60cm；三边和≤150cm",
    ),
    XingyuanEconomyChannel(
        code="xy_economy_big",
        name="XY Economy Big",
        category="Big",
        register_fee_cny=40.44,
        unit_price_per_gram_cny=0.0191,
        weight_min_g=2201,
        weight_max_g=30000,
        max_side_cm=150,
        max_sum_cm=310,
        use_volumetric=True,
        notes="标准大件；单边≤150cm；三边和≤310cm；实重与体积重取大",
    ),
)


class FreightError(ValueError):
    pass


def mm_to_cm_sides(depth_mm: int, width_mm: int, height_mm: int) -> tuple[int, int, int]:
    sides = sorted(
        (
            max(1, int(round(float(depth_mm) / 10.0))),
            max(1, int(round(float(width_mm) / 10.0))),
            max(1, int(round(float(height_mm) / 10.0))),
        ),
        reverse=True,
    )
    return sides[0], sides[1], sides[2]


def volumetric_weight_g(depth_mm: int, width_mm: int, height_mm: int) -> int:
    """兴远大件体积重：长×宽×高(cm) / 12000 → kg，再换算克。"""
    a, b, c = mm_to_cm_sides(depth_mm, width_mm, height_mm)
    kg = (a * b * c) / 12000.0
    return max(1, int(round(kg * 1000)))


def channel_fits_size(channel: XingyuanEconomyChannel, *, max_side_cm: int, sum_cm: int) -> bool:
    return max_side_cm <= channel.max_side_cm and sum_cm <= channel.max_sum_cm


def select_russia_economy_channel(weight_g: float) -> XingyuanEconomyChannel:
    """仅按重量选档（兼容旧调用）。优先使用 select_channel_for_package。"""
    if weight_g is None or weight_g <= 0:
        raise FreightError("重量必须大于 0 克，才能计算兴远运费")
    weight = int(round(float(weight_g)))
    for channel in RUSSIA_ECONOMY_CHANNELS:
        if channel.weight_min_g <= weight <= channel.weight_max_g:
            return channel
    if weight < RUSSIA_ECONOMY_CHANNELS[0].weight_min_g:
        return RUSSIA_ECONOMY_CHANNELS[0]
    raise FreightError(f"重量 {weight}g 超出兴远 Economy 服务范围（最大 30kg）")


def select_channel_for_package(
    *,
    depth_mm: int,
    width_mm: int,
    height_mm: int,
    weight_g: float,
) -> tuple[XingyuanEconomyChannel, int]:
    """
    尺寸优先选档，再抬高计费重量到渠道下限。
    返回 (渠道, 计费重量克)。
    """
    if min(int(depth_mm), int(width_mm), int(height_mm)) <= 0:
        raise FreightError("包装长宽高必须大于 0")
    actual = max(1, int(round(float(weight_g or 0))))
    max_side, mid_side, min_side = mm_to_cm_sides(depth_mm, width_mm, height_mm)
    sum_cm = max_side + mid_side + min_side

    size_ok = [ch for ch in RUSSIA_ECONOMY_CHANNELS if channel_fits_size(ch, max_side_cm=max_side, sum_cm=sum_cm)]
    if not size_ok:
        raise FreightError(
            f"包装尺寸 {max_side}×{mid_side}×{min_side} cm（三边和 {sum_cm}cm）超出兴远 Economy 范围"
        )

    # 从能装下的最小档开始；重量超上限则升到下一档（仍须尺寸允许）
    chosen = size_ok[0]
    for channel in size_ok:
        chargeable = actual
        if channel.use_volumetric:
            chargeable = max(chargeable, volumetric_weight_g(depth_mm, width_mm, height_mm))
        # 尺寸命中该档后，重量至少提到渠道下限（例：Small 至少 551g）
        chargeable = max(chargeable, channel.weight_min_g)
        if chargeable <= channel.weight_max_g:
            return channel, chargeable
        chosen = channel

    # 尺寸只够当前最大可装档，但重量仍超上限
    chargeable = max(actual, chosen.weight_min_g)
    if chosen.use_volumetric:
        chargeable = max(chargeable, volumetric_weight_g(depth_mm, width_mm, height_mm))
    if chargeable > chosen.weight_max_g:
        raise FreightError(
            f"计费重量 {chargeable}g 超出渠道 {chosen.name} 上限 {chosen.weight_max_g}g"
        )
    return chosen, chargeable


def normalize_package_for_shipping(
    depth_mm: int,
    width_mm: int,
    height_mm: int,
    weight_g: float,
) -> dict[str, Any]:
    """按兴远规则校正计费重量，尺寸保持不变。"""
    channel, chargeable = select_channel_for_package(
        depth_mm=int(depth_mm),
        width_mm=int(width_mm),
        height_mm=int(height_mm),
        weight_g=weight_g,
    )
    actual = max(1, int(round(float(weight_g or 0))))
    freight = channel.register_fee_cny + channel.unit_price_per_gram_cny * chargeable
    freight = round(freight, 2)
    max_side, mid_side, min_side = mm_to_cm_sides(depth_mm, width_mm, height_mm)
    return {
        "depth_mm": int(depth_mm),
        "width_mm": int(width_mm),
        "height_mm": int(height_mm),
        "actual_weight_g": actual,
        "weight_g": chargeable,
        "weight_raised": chargeable > actual,
        "max_side_cm": max_side,
        "sum_cm": max_side + mid_side + min_side,
        "channel_code": channel.code,
        "channel_name": channel.name,
        "category": channel.category,
        "transport": "Economy",
        "register_fee_cny": channel.register_fee_cny,
        "unit_price_per_gram_cny": channel.unit_price_per_gram_cny,
        "freight_cny": freight,
        "volumetric_weight_g": volumetric_weight_g(depth_mm, width_mm, height_mm)
        if channel.use_volumetric
        else None,
        "notes": channel.notes,
        "formula": (
            f"{channel.register_fee_cny} + {channel.unit_price_per_gram_cny}×{chargeable}g"
            f" = {freight} CNY"
        ),
    }


def calc_xingyuan_economy_freight_cny(
    weight_g: float,
    *,
    depth_mm: int | None = None,
    width_mm: int | None = None,
    height_mm: int | None = None,
) -> dict[str, Any]:
    """有尺寸时走尺寸优先；否则退回纯重量选档。"""
    if depth_mm and width_mm and height_mm:
        return normalize_package_for_shipping(int(depth_mm), int(width_mm), int(height_mm), weight_g)

    channel = select_russia_economy_channel(weight_g)
    weight = max(1, int(round(float(weight_g))))
    weight = max(weight, channel.weight_min_g)
    freight = round(channel.register_fee_cny + channel.unit_price_per_gram_cny * weight, 2)
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
