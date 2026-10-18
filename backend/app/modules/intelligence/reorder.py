"""
modules/intelligence/reorder.py

Responsibility
--------------
Reorder-quantity recommendation. Pure function with a fully itemised
breakdown so the UI can show every intermediate number.

Formulas (L = lead time days, H = planning horizon days, z = 1.65):

    lead_time_demand   = rate * L
    safety_stock       = z * sigma_daily * sqrt(L)
    reorder_point      = lead_time_demand + safety_stock
    effective_ROP      = max(reorder_point, configured reorder_level)
    target_stock       = max(rate * (L + H) + safety_stock, reorder_level)
                         capped at max_stock when max_stock > 0
    reorder_needed     = available <= effective_ROP
    recommended_qty    = ceil(max(0, target_stock - available))  if needed else 0

Notes
-----
* `available` is quantity - reserved_quantity (Inventory.available_quantity).
* The schema has no purchase orders / inbound shipments, so stock already
  on order is NOT netted off. This is stated in the UI and README.
* max_stock == 0 means "no cap configured".
"""

from dataclasses import dataclass, field
from math import ceil, sqrt

from app.modules.intelligence.constants import SERVICE_LEVEL_Z


@dataclass(frozen=True)
class ReorderRecommendation:
    available: int
    lead_time_days: int
    horizon_days: int
    lead_time_demand: float
    safety_stock: float
    computed_reorder_point: float
    configured_reorder_level: int
    effective_reorder_point: int
    target_stock: int
    max_stock: int
    capped_by_max_stock: bool
    reorder_needed: bool
    recommended_quantity: int
    reasons: list[str] = field(default_factory=list)


def _ceil(value: float) -> int:
    # round() first so 12.000000000000002 does not become 13
    return int(ceil(round(value, 9)))


def recommend_reorder(
    *,
    available: int,
    daily_rate: float,
    sigma_daily: float,
    lead_time_days: int,
    horizon_days: int,
    reorder_level: int,
    max_stock: int,
) -> ReorderRecommendation:
    avail = max(0, available)

    lead_time_demand = daily_rate * lead_time_days
    safety_stock = SERVICE_LEVEL_Z * sigma_daily * sqrt(lead_time_days)
    computed_rop = lead_time_demand + safety_stock
    effective_rop = max(_ceil(computed_rop), reorder_level)

    uncapped_target = max(
        _ceil(daily_rate * (lead_time_days + horizon_days) + safety_stock),
        reorder_level,
    )
    target = uncapped_target
    capped = False
    if max_stock > 0 and target > max_stock:
        target = max_stock
        capped = True

    needed = avail <= effective_rop
    quantity = _ceil(max(0.0, target - avail)) if needed else 0

    reasons: list[str] = []
    reasons.append(
        f"Lead-time demand = {daily_rate:.2f}/day x {lead_time_days} days = "
        f"{lead_time_demand:.1f} units."
    )
    reasons.append(
        f"Safety stock = {SERVICE_LEVEL_Z} x {sigma_daily:.2f} x sqrt({lead_time_days}) "
        f"= {safety_stock:.1f} units (~95% service level)."
    )
    reasons.append(
        f"Reorder point = max({computed_rop:.1f}, configured level "
        f"{reorder_level}) = {effective_rop} units."
    )
    reasons.append(
        f"Order-up-to level = {daily_rate:.2f}/day x ({lead_time_days} + "
        f"{horizon_days}) days + safety stock = {uncapped_target} units."
    )
    if capped:
        reasons.append(
            f"Target limited to the configured max_stock of {max_stock} units."
        )
    if max_stock > 0 and effective_rop > max_stock:
        reasons.append(
            f"Warning: reorder point ({effective_rop}) exceeds max_stock "
            f"({max_stock}); review these inventory settings."
        )

    if needed and quantity > 0:
        reasons.append(
            f"Available stock ({avail}) is at or below the reorder point "
            f"({effective_rop}): order {quantity} units to reach {target}."
        )
    elif needed:
        reasons.append(
            f"Available stock ({avail}) is at or below the reorder point "
            f"({effective_rop}), but the target ({target}) leaves nothing to order."
        )
    else:
        reasons.append(
            f"Available stock ({avail}) is above the reorder point "
            f"({effective_rop}): no reorder needed."
        )

    return ReorderRecommendation(
        available=avail,
        lead_time_days=lead_time_days,
        horizon_days=horizon_days,
        lead_time_demand=lead_time_demand,
        safety_stock=safety_stock,
        computed_reorder_point=computed_rop,
        configured_reorder_level=reorder_level,
        effective_reorder_point=effective_rop,
        target_stock=target,
        max_stock=max_stock,
        capped_by_max_stock=capped,
        reorder_needed=needed,
        recommended_quantity=quantity,
        reasons=reasons,
    )
