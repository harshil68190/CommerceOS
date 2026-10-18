"""
modules/intelligence/risk.py

Responsibility
--------------
Explainable stockout-risk classification. Pure function; every decision
comes with human-readable reasons so the UI can show *why*.

Rule (L = lead time in days, cover = available / forecast daily rate):

    no expected demand          -> HEALTHY
    available <= 0 (w/ demand)  -> HIGH      (already out)
    cover <= 1 x L              -> HIGH      (gone before a PO can arrive)
    cover <= 2 x L              -> MEDIUM
    cover <= 4 x L              -> LOW
    otherwise                   -> HEALTHY

    Floor: if available <= the configured `reorder_level` and demand is
    expected, risk is at least MEDIUM (the operator's own alarm).

Boundaries are inclusive on the riskier side: cover == 1 x L is HIGH.
"""

from dataclasses import dataclass, field
from math import isfinite

from app.modules.intelligence.constants import (
    RISK_HIGH_LEAD_TIME_MULTIPLE,
    RISK_LOW_LEAD_TIME_MULTIPLE,
    RISK_MEDIUM_LEAD_TIME_MULTIPLE,
    RISK_RANK,
    RiskLevel,
)
from app.modules.intelligence.projection import days_of_cover


@dataclass(frozen=True)
class RiskThresholds:
    """Concrete day thresholds derived from the lead time."""

    high_days: float
    medium_days: float
    low_days: float


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    days_of_cover: float | None
    thresholds: RiskThresholds
    reasons: list[str] = field(default_factory=list)


def risk_thresholds(lead_time_days: int) -> RiskThresholds:
    return RiskThresholds(
        high_days=RISK_HIGH_LEAD_TIME_MULTIPLE * lead_time_days,
        medium_days=RISK_MEDIUM_LEAD_TIME_MULTIPLE * lead_time_days,
        low_days=RISK_LOW_LEAD_TIME_MULTIPLE * lead_time_days,
    )


def max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    return a if RISK_RANK[a] >= RISK_RANK[b] else b


def assess_risk(
    *,
    available: int,
    daily_rate: float,
    lead_time_days: int,
    reorder_level: int,
) -> RiskAssessment:
    thresholds = risk_thresholds(lead_time_days)
    reasons: list[str] = []

    if not isfinite(daily_rate) or daily_rate <= 0:
        reasons.append("No demand is forecast, so no stockout is projected.")
        if available <= 0:
            reasons.append("Stock is zero, but no recent demand was observed.")
        return RiskAssessment(RiskLevel.HEALTHY, None, thresholds, reasons)

    cover = days_of_cover(available, daily_rate)
    if cover is None:
        # Positive rates too small to produce a finite cover imply no
        # representable stockout horizon; treat them as healthy.
        reasons.append("Demand is too small to project a finite stockout horizon.")
        return RiskAssessment(RiskLevel.HEALTHY, None, thresholds, reasons)

    if available <= 0:
        level = RiskLevel.HIGH
        reasons.append(
            f"Available stock is {max(available, 0)} while demand is forecast "
            f"at {daily_rate:.2f} units/day: already out of stock."
        )
    else:
        cmp_cover = round(cover, 6)
        if cmp_cover <= thresholds.high_days:
            level = RiskLevel.HIGH
            reasons.append(
                f"Stock covers {cover:.1f} days, which is within the "
                f"{lead_time_days}-day lead time: it will run out before a "
                f"replenishment can arrive."
            )
        elif cmp_cover <= thresholds.medium_days:
            level = RiskLevel.MEDIUM
            reasons.append(
                f"Stock covers {cover:.1f} days, within 2x the "
                f"{lead_time_days}-day lead time ({thresholds.medium_days:.0f} days)."
            )
        elif cmp_cover <= thresholds.low_days:
            level = RiskLevel.LOW
            reasons.append(
                f"Stock covers {cover:.1f} days, within 4x the "
                f"{lead_time_days}-day lead time ({thresholds.low_days:.0f} days)."
            )
        else:
            level = RiskLevel.HEALTHY
            reasons.append(
                f"Stock covers {cover:.1f} days, more than 4x the "
                f"{lead_time_days}-day lead time ({thresholds.low_days:.0f} days)."
            )

    if available <= reorder_level and reorder_level > 0:
        floored = max_risk(level, RiskLevel.MEDIUM)
        if floored != level:
            reasons.append(
                f"Available stock ({available}) is at or below the configured "
                f"reorder level ({reorder_level}), so risk is raised to at "
                f"least medium."
            )
            level = floored
        else:
            reasons.append(
                f"Available stock ({available}) is at or below the configured "
                f"reorder level ({reorder_level})."
            )

    return RiskAssessment(level, cover, thresholds, reasons)
