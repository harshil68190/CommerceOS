"""
modules/intelligence/constants.py

Responsibility
--------------
Every tunable number and enum used by CommerceOS Intelligence lives here,
so the whole decision policy can be read (and defended) in one place.
Nothing in this module touches the database.

Policy summary (see README "CommerceOS Intelligence" for the full write-up):

* Demand      = units on CONFIRMED / SHIPPED / DELIVERED orders, per
                product x warehouse x calendar day (UTC).
* Forecast    = weighted blend of 7/14/30-day moving averages.
* Safety      = z * sigma_daily * sqrt(lead_time).
* Risk        = days of cover compared against multiples of lead time.
* Reorder     = order-up-to level minus available stock, capped by max_stock.
"""

import enum

from app.modules.orders.constants import OrderStatus


class RiskLevel(str, enum.Enum):
    """Stockout risk classification, ordered from safest to most urgent."""

    HEALTHY = "healthy"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Numeric rank so risk levels can be compared / sorted / max()-ed.
RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.HEALTHY: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
}


class ForecastConfidence(str, enum.Enum):
    """How much observed history backs a forecast."""

    NONE = "none"      # no demand observed in the lookback window
    LOW = "low"        # fewer than LOW_CONFIDENCE_MAX_DAYS of history
    MEDIUM = "medium"  # fewer than a full 30-day window
    HIGH = "high"      # a full 30-day window of history


# --- Demand definition --------------------------------------------------
# Orders in these statuses represent real, committed demand. PENDING is not
# counted (payment not confirmed; its units are already reflected in
# `reserved_quantity`), and CANCELLED / RETURNED / REFUNDED are not demand.
VALID_DEMAND_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.CONFIRMED, OrderStatus.SHIPPED, OrderStatus.DELIVERED}
)

# How many completed days of order history the repository loads. Must cover
# the backtest window plus the longest moving-average window.
LOOKBACK_DAYS = 60

# --- Forecast ------------------------------------------------------------
# Daily rate = 0.5 * MA7 + 0.3 * MA14 + 0.2 * MA30  (weights sum to 1).
# Recent behaviour dominates, longer windows damp noise.
FORECAST_WINDOWS: tuple[int, ...] = (7, 14, 30)
FORECAST_WEIGHTS: tuple[float, ...] = (0.5, 0.3, 0.2)
SIGMA_WINDOW_DAYS = 30        # window for demand standard deviation
BACKTEST_DAYS = 14            # days of forecast-vs-actual shown in the UI



class Horizon(enum.IntEnum):
    """Supported forecast horizons in days. An IntEnum (rather than
    Literal[7, 14, 30]) so FastAPI also accepts them as query strings
    ("?horizon_days=14") while still rejecting any other value."""

    D7 = 7
    D14 = 14
    D30 = 30


ALLOWED_HORIZONS: tuple[int, ...] = tuple(h.value for h in Horizon)
DEFAULT_HORIZON_DAYS = Horizon.D30

# --- Confidence ----------------------------------------------------------
LOW_CONFIDENCE_MAX_DAYS = 14   # < 14 days of history  -> LOW
FULL_HISTORY_DAYS = 30         # >= 30 days of history -> HIGH

# --- Risk ----------------------------------------------------------------
# days_of_cover <= 1.0 x lead time  -> HIGH   (stock gone before a PO lands)
# days_of_cover <= 2.0 x lead time  -> MEDIUM
# days_of_cover <= 4.0 x lead time  -> LOW
# otherwise                         -> HEALTHY
# Boundaries are inclusive on the riskier side (cover == threshold -> riskier).
RISK_HIGH_LEAD_TIME_MULTIPLE = 1.0
RISK_MEDIUM_LEAD_TIME_MULTIPLE = 2.0
RISK_LOW_LEAD_TIME_MULTIPLE = 4.0

# --- Reorder -------------------------------------------------------------
DEFAULT_LEAD_TIME_DAYS = 7     # no supplier lead-time data exists in the schema
MIN_LEAD_TIME_DAYS = 1
MAX_LEAD_TIME_DAYS = 90
SERVICE_LEVEL_Z = 1.65         # ~95% cycle service level (one-sided normal)

# --- Simulation ----------------------------------------------------------
MIN_DEMAND_CHANGE_PERCENT = -100.0   # -100% == demand disappears
MAX_DEMAND_CHANGE_PERCENT = 1000.0

# --- Dashboard list sizes ------------------------------------------------
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
