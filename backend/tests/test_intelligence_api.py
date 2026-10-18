"""
tests/test_intelligence_api.py

Integration tests for CommerceOS Intelligence against the real test
database: RBAC, empty / no-history cases, which orders and stock
positions count, per-warehouse separation, the dashboard, the product
drill-down, and the what-if simulation.

The clock is pinned with a dependency override so every expected date and
quantity below is deterministic and can be derived by hand. Throughout:

    FIXED_TODAY = 2026-03-15, "history" = the 60 completed days before it,
    lead time L = 7, horizon H = 30 unless a test says otherwise.

A position that sells 10/day for the last 30 days with 50 units available
therefore has: rate 10, cover 5 days (HIGH), stockout on 2026-03-19
(day 5 -> FIXED_TODAY + 4), reorder point 70, target 10 x (7 + 30) = 370
and a recommended order of 370 - 50 = 320.
"""

from datetime import date, datetime, time, timedelta
from typing import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.product import ProductStatus
from app.models.user import UserRole
from app.modules.intelligence.dependencies import get_today
from app.modules.inventory.models import Inventory
from app.modules.orders.constants import OrderStatus
from app.modules.orders.models import Order

FIXED_TODAY = date(2026, 3, 15)
BASE = "/api/v1/intelligence"


def _at(day: date) -> datetime:
    return datetime.combine(day, time(12, 0))


def _days_ago(n: int) -> date:
    return FIXED_TODAY - timedelta(days=n)


def _assert_error(response, *, status_code: int, error_code: str):
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def api(authenticated_admin_client: TestClient) -> TestClient:
    """Admin client with the intelligence clock pinned to FIXED_TODAY."""
    authenticated_admin_client.app.dependency_overrides[get_today] = lambda: FIXED_TODAY
    return authenticated_admin_client


@pytest.fixture
def seed(product_factory, warehouse_factory, inventory_factory, order_factory):
    """Small DSL for building real products, stock and order history."""

    class Seed:
        def position(
            self, *, available=100, reserved=0, reorder_level=0, max_stock=0,
            product=None, warehouse=None, created_days_ago=90, **product_kw,
        ):
            product = product or product_factory(**product_kw)
            warehouse = warehouse or warehouse_factory()
            inventory = inventory_factory(
                product=product, warehouse=warehouse,
                quantity=available + reserved, reserved_quantity=reserved,
                reorder_level=reorder_level, max_stock=max_stock,
                created_at=_at(_days_ago(created_days_ago)),
            )
            return product, warehouse, inventory

        def sell(
            self, product, warehouse, per_day, *, days=30, first_day=1,
            status=OrderStatus.CONFIRMED,
        ):
            """`per_day` units per day on `days` consecutive past days,
            starting `first_day` days before FIXED_TODAY."""
            for offset in range(first_day, first_day + days):
                order_factory(
                    product=product, warehouse=warehouse, quantity=per_day,
                    status=status, created_at=_at(_days_ago(offset)),
                )

        def order_on(self, product, warehouse, quantity, days_ago, status):
            order_factory(
                product=product, warehouse=warehouse, quantity=quantity,
                status=status, created_at=_at(_days_ago(days_ago)),
            )

    return Seed()


@pytest.fixture
def client_for_role(
    client_factory: Callable[..., TestClient], user_factory, access_token_factory
) -> Callable[[UserRole], TestClient]:
    def _make(role: UserRole) -> TestClient:
        user = user_factory(role=role)
        token = access_token_factory(user)
        client = client_factory(access_token=token)
        client.app.dependency_overrides[get_today] = lambda: FIXED_TODAY
        return client

    return _make


def _position_for(body: dict, warehouse_id) -> dict:
    return next(p for p in body["positions"] if p["warehouse_id"] == str(warehouse_id))


# =========================================================================
# Permissions
# =========================================================================


class TestPermissions:
    def _calls(self, product_id):
        return [
            ("GET", f"{BASE}/dashboard", None),
            ("GET", f"{BASE}/products/{product_id}", None),
            ("POST", f"{BASE}/simulate", {"demand_change_percent": 20}),
        ]

    def test_anonymous_gets_401_everywhere(self, client, product_factory):
        product = product_factory()
        for method, url, body in self._calls(product.id):
            response = client.request(method, url, json=body)
            _assert_error(response, status_code=401, error_code="UNAUTHORIZED")

    @pytest.mark.parametrize(
        "role", [UserRole.CUSTOMER, UserRole.SELLER, UserRole.INVENTORY_MANAGER]
    )
    def test_non_admin_roles_get_403_everywhere(self, role, client_for_role, product_factory):
        product = product_factory()
        client = client_for_role(role)
        for method, url, body in self._calls(product.id):
            response = client.request(method, url, json=body)
            _assert_error(response, status_code=403, error_code="FORBIDDEN")

    def test_admin_is_allowed_everywhere(self, api, product_factory):
        product = product_factory()
        for method, url, body in self._calls(product.id):
            response = api.request(method, url, json=body)
            assert response.status_code == 200, (url, response.text)

    def test_invalid_token_is_rejected(self, client_factory):
        client = client_factory(access_token="not-a-real-token")
        _assert_error(
            client.get(f"{BASE}/dashboard"), status_code=401, error_code="UNAUTHORIZED"
        )

    def test_simulation_is_not_exposed_to_customers_even_with_valid_body(
        self, client_for_role
    ):
        response = client_for_role(UserRole.CUSTOMER).post(
            f"{BASE}/simulate", json={"demand_change_percent": 0}
        )
        assert response.status_code == 403


# =========================================================================
# Empty / no-history cases
# =========================================================================


class TestEmptyAndNoHistory:
    def test_dashboard_with_no_inventory_at_all(self, api):
        response = api.get(f"{BASE}/dashboard")
        assert response.status_code == 200
        body = response.json()
        assert body["kpis"]["total_positions"] == 0
        assert body["kpis"]["risk_counts"] == {"healthy": 0, "low": 0, "medium": 0, "high": 0}
        assert body["kpis"]["total_recommended_units"] == 0
        assert body["high_risk"] == []
        assert body["reorder_recommendations"] == []
        assert body["has_demand_history"] is False
        assert body["network_wape"] is None
        assert body["as_of_date"] == FIXED_TODAY.isoformat()
        # chart still renders: 14 history days + 30 forecast days of zeros
        assert len(body["demand_trend"]) == 14 + 30

    def test_stock_but_no_orders_is_healthy_with_no_forecast(self, api, seed):
        product, warehouse, _ = seed.position(available=25)
        body = api.get(f"{BASE}/dashboard").json()
        assert body["kpis"]["total_positions"] == 1
        assert body["kpis"]["risk_counts"]["healthy"] == 1
        assert body["kpis"]["projected_stockouts"] == 0
        assert body["kpis"]["total_recommended_units"] == 0
        assert body["has_demand_history"] is False

        detail = api.get(f"{BASE}/products/{product.id}").json()
        pos = _position_for(detail, warehouse.id)
        assert pos["forecast"]["confidence"] == "none"
        assert pos["forecast"]["daily_rate"] == 0
        assert pos["stockout_date"] is None
        assert pos["risk"]["level"] == "healthy"
        assert pos["risk"]["days_of_cover"] is None
        assert any("No confirmed" in line for line in pos["reasoning"])

    def test_zero_stock_and_no_history_is_not_flagged(self, api, seed):
        seed.position(available=0)
        body = api.get(f"{BASE}/dashboard").json()
        assert body["kpis"]["risk_counts"]["high"] == 0
        assert body["kpis"]["positions_needing_reorder"] == 0

    def test_product_without_inventory_returns_empty_positions(self, api, product_factory):
        product = product_factory()
        response = api.get(f"{BASE}/products/{product.id}")
        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["aggregate"]["total_available"] == 0
        assert body["aggregate"]["worst_risk"] == "healthy"
        assert body["aggregate"]["earliest_stockout_date"] is None

    def test_unknown_product_is_404(self, api):
        _assert_error(
            api.get(f"{BASE}/products/{uuid4()}"), status_code=404, error_code="NOT_FOUND"
        )

    def test_malformed_product_id_is_422(self, api):
        assert api.get(f"{BASE}/products/not-a-uuid").status_code == 422

    def test_simulation_with_no_data(self, api):
        body = api.post(f"{BASE}/simulate", json={"demand_change_percent": 50}).json()
        assert body["positions_analyzed"] == 0
        assert body["changed_positions"] == []
        assert body["additional_reorder_units"] == 0
        assert body["additional_projected_stockouts"] == 0

    def test_short_history_is_flagged_low_confidence_and_not_diluted(self, api, seed):
        # Position created 9 days ago, selling 5/day since then.
        product, warehouse, _ = seed.position(available=1000, created_days_ago=9)
        seed.sell(product, warehouse, 5, days=9)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["history_days"] == 9
        assert pos["forecast"]["confidence"] == "low"
        assert pos["forecast"]["daily_rate"] == pytest.approx(5.0)

    def test_medium_confidence_with_three_weeks_of_history(self, api, seed):
        product, warehouse, _ = seed.position(available=1000, created_days_ago=21)
        seed.sell(product, warehouse, 2, days=21)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["confidence"] == "medium"

    def test_old_demand_only_gives_no_forecast(self, api, seed):
        # Sold 100 units but 70 days ago, outside the 60-day window.
        product, warehouse, _ = seed.position(available=10)
        seed.order_on(product, warehouse, 100, 70, OrderStatus.CONFIRMED)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["total_units_in_history"] == 0
        assert pos["risk"]["level"] == "healthy"


# =========================================================================
# Which data counts
# =========================================================================


class TestDemandDefinition:
    def test_only_valid_statuses_in_completed_days_count(self, api, seed):
        product, warehouse, _ = seed.position(available=1000)
        seed.sell(product, warehouse, 4, days=10)                             # 40
        seed.order_on(product, warehouse, 3, 3, OrderStatus.SHIPPED)          # +3
        seed.order_on(product, warehouse, 2, 4, OrderStatus.DELIVERED)        # +2
        # none of these are demand:
        seed.order_on(product, warehouse, 100, 2, OrderStatus.PENDING)
        seed.order_on(product, warehouse, 100, 2, OrderStatus.CANCELLED)
        seed.order_on(product, warehouse, 100, 2, OrderStatus.RETURNED)
        seed.order_on(product, warehouse, 100, 2, OrderStatus.REFUNDED)
        seed.order_on(product, warehouse, 100, 0, OrderStatus.CONFIRMED)      # today: incomplete day
        seed.order_on(product, warehouse, 100, 70, OrderStatus.CONFIRMED)     # older than window

        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["total_units_in_history"] == 45

    def test_multiple_orders_on_one_day_are_summed(self, api, seed):
        product, warehouse, _ = seed.position(available=1000, created_days_ago=3)
        for qty in (2, 3, 5):
            seed.order_on(product, warehouse, qty, 1, OrderStatus.CONFIRMED)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["total_units_in_history"] == 10
        yesterday = _days_ago(1).isoformat()
        point = next(d for d in pos["demand_history"] if d["day"] == yesterday and d["actual"] is not None)
        assert point["actual"] == 10

    def test_demand_is_kept_separate_per_warehouse(self, api, seed, warehouse_factory):
        product, wh_a, _ = seed.position(available=50)
        wh_b = warehouse_factory()
        seed.position(product=product, warehouse=wh_b, available=500)
        seed.sell(product, wh_a, 10)

        body = api.get(f"{BASE}/products/{product.id}").json()
        a, b = _position_for(body, wh_a.id), _position_for(body, wh_b.id)
        assert a["risk"]["level"] == "high"
        assert b["risk"]["level"] == "healthy"
        assert b["forecast"]["daily_rate"] == 0
        assert body["aggregate"]["total_available"] == 550
        assert body["aggregate"]["worst_risk"] == "high"
        assert body["aggregate"]["projected_stockouts"] == 1
        assert body["aggregate"]["total_recommended_quantity"] == 320
        assert body["aggregate"]["earliest_stockout_date"] == "2026-03-19"
        assert body["positions"][0]["warehouse_id"] == str(wh_a.id)   # worst first

    def test_reserved_stock_reduces_available(self, api, seed):
        product, warehouse, _ = seed.position(available=60, reserved=40)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["quantity"] == 100
        assert pos["reserved_quantity"] == 40
        assert pos["available"] == 60

    def test_out_of_scope_positions_are_excluded(self, api, seed, warehouse_factory):
        seed.position(available=10)                                           # counted
        seed.position(available=10, status=ProductStatus.ARCHIVED)
        seed.position(available=10, status=ProductStatus.DRAFT)
        seed.position(available=10, track_inventory=False)
        seed.position(available=10, warehouse=warehouse_factory(is_active=False))
        body = api.get(f"{BASE}/dashboard").json()
        assert body["kpis"]["total_positions"] == 1

    def test_out_of_stock_products_are_still_analysed(self, api, seed):
        product, warehouse, _ = seed.position(available=0, status=ProductStatus.OUT_OF_STOCK)
        seed.sell(product, warehouse, 2)
        body = api.get(f"{BASE}/dashboard").json()
        assert body["kpis"]["risk_counts"]["high"] == 1
        assert body["high_risk"][0]["product_id"] == str(product.id)


# =========================================================================
# Dashboard
# =========================================================================


@pytest.fixture
def portfolio(seed):
    """A: high risk. B: healthy. C: no history. D: out of stock w/ demand."""
    a, wa, _ = seed.position(available=50, name="Alpha Widget")
    seed.sell(a, wa, 10)
    b, wb, _ = seed.position(available=500, name="Bravo Gadget")
    seed.sell(b, wb, 1)
    c, wc, _ = seed.position(available=10, name="Charlie Gizmo")
    d, wd, _ = seed.position(available=0, status=ProductStatus.OUT_OF_STOCK, name="Delta Doohickey")
    seed.sell(d, wd, 2)
    return {"A": (a, wa), "B": (b, wb), "C": (c, wc), "D": (d, wd)}


class TestDashboard:
    def test_kpis_match_hand_calculation(self, api, portfolio):
        k = api.get(f"{BASE}/dashboard").json()["kpis"]
        assert k["total_positions"] == 4
        assert k["positions_with_demand"] == 3
        assert k["risk_counts"] == {"healthy": 2, "low": 0, "medium": 0, "high": 2}
        assert k["projected_stockouts"] == 2
        assert k["positions_needing_reorder"] == 2
        assert k["total_recommended_units"] == 320 + 74
        assert k["total_unserved_demand"] == pytest.approx(250 + 60)

    def test_high_risk_list_is_ordered_most_urgent_first(self, api, portfolio):
        body = api.get(f"{BASE}/dashboard").json()
        names = [r["product_name"] for r in body["high_risk"]]
        assert names == ["Delta Doohickey", "Alpha Widget"]
        alpha = body["high_risk"][1]
        assert alpha["available"] == 50
        assert alpha["daily_rate"] == pytest.approx(10.0)
        assert alpha["days_of_cover"] == pytest.approx(5.0)
        assert alpha["stockout_date"] == "2026-03-19"
        assert alpha["risk_level"] == "high"
        assert alpha["confidence"] == "high"
        assert alpha["recommended_quantity"] == 320

    def test_reorder_recommendations(self, api, portfolio):
        recs = api.get(f"{BASE}/dashboard").json()["reorder_recommendations"]
        assert [(r["product_name"], r["recommended_quantity"]) for r in recs] == [
            ("Delta Doohickey", 74), ("Alpha Widget", 320),
        ]
        assert all(r["reorder_needed"] for r in recs)

    def test_forecast_versus_actual_trend(self, api, portfolio):
        body = api.get(f"{BASE}/dashboard").json()
        trend = body["demand_trend"]
        assert len(trend) == 14 + 30
        history, future = trend[:14], trend[14:]
        assert history[-1]["day"] == _days_ago(1).isoformat()
        assert all(p["actual"] == 13 for p in history)      # 10 + 1 + 0 + 2 per day
        assert all(p["actual"] is None for p in future)
        assert future[0]["day"] == FIXED_TODAY.isoformat()
        assert all(p["forecast"] == pytest.approx(13.0) for p in future)
        assert body["network_wape"] is not None and body["network_wape"] >= 0

    def test_horizon_changes_projected_stockouts_and_trend_length(self, api, seed):
        product, warehouse, _ = seed.position(available=100)
        seed.sell(product, warehouse, 10)           # stockout on day 10
        h7 = api.get(f"{BASE}/dashboard", params={"horizon_days": 7}).json()
        h14 = api.get(f"{BASE}/dashboard", params={"horizon_days": 14}).json()
        assert h7["kpis"]["projected_stockouts"] == 0
        assert h14["kpis"]["projected_stockouts"] == 1
        assert len(h7["demand_trend"]) == 14 + 7
        assert h14["assumptions"]["horizon_days"] == 14

    def test_lead_time_changes_risk_classification(self, api, portfolio):
        a = portfolio["A"][0]
        default = api.get(f"{BASE}/dashboard").json()
        assert default["assumptions"]["lead_time_days"] == 7
        short = api.get(f"{BASE}/dashboard", params={"lead_time_days": 3}).json()
        # cover 5 days: > 3-day lead time => medium instead of high
        assert short["kpis"]["risk_counts"]["high"] == 1       # only the already-out item
        assert str(a.id) not in {r["product_id"] for r in short["high_risk"]}
        assert short["assumptions"]["risk_thresholds_days"] == {
            "high": 3.0, "medium": 6.0, "low": 12.0,
        }

    def test_limit_truncates_lists_but_not_kpis(self, api, portfolio):
        body = api.get(f"{BASE}/dashboard", params={"limit": 1}).json()
        assert len(body["high_risk"]) == 1
        assert len(body["reorder_recommendations"]) == 1
        assert body["kpis"]["risk_counts"]["high"] == 2

    def test_assumptions_are_published(self, api, portfolio):
        a = api.get(f"{BASE}/dashboard").json()["assumptions"]
        assert a["forecast_weights"] == {"ma_7": 0.5, "ma_14": 0.3, "ma_30": 0.2}
        assert a["service_level_z"] == 1.65
        assert a["demand_statuses"] == ["confirmed", "delivered", "shipped"]
        assert a["notes"]

    @pytest.mark.parametrize(
        "params",
        [{"horizon_days": 15}, {"horizon_days": 0}, {"lead_time_days": 0},
         {"lead_time_days": 91}, {"limit": 0}, {"limit": 101}],
    )
    def test_invalid_query_params_are_rejected(self, api, params):
        _assert_error(
            api.get(f"{BASE}/dashboard", params=params),
            status_code=422, error_code="REQUEST_VALIDATION_ERROR",
        )

    def test_dashboard_is_deterministic(self, api, portfolio):
        first = api.get(f"{BASE}/dashboard").json()
        second = api.get(f"{BASE}/dashboard").json()
        first.pop("generated_at"), second.pop("generated_at")
        assert first == second

    def test_dashboard_does_not_modify_data(self, api, portfolio, db_session):
        before = sorted(
            (str(i.id), i.quantity, i.reserved_quantity, i.version)
            for i in db_session.query(Inventory).all()
        )
        api.get(f"{BASE}/dashboard")
        after = sorted(
            (str(i.id), i.quantity, i.reserved_quantity, i.version)
            for i in db_session.query(Inventory).all()
        )
        assert before == after


# =========================================================================
# Product intelligence
# =========================================================================


class TestProductIntelligence:
    def test_full_breakdown_for_a_high_risk_position(self, api, seed):
        product, warehouse, _ = seed.position(available=50)
        seed.sell(product, warehouse, 10)
        body = api.get(f"{BASE}/products/{product.id}").json()
        assert body["product_name"] == product.name
        assert body["product_sku"] == product.sku

        pos = _position_for(body, warehouse.id)
        f, r, risk = pos["forecast"], pos["reorder"], pos["risk"]
        assert f["daily_rate"] == pytest.approx(10.0)
        assert f["ma_7"] == pytest.approx(10.0)
        assert f["ma_14"] == pytest.approx(10.0)
        assert f["ma_30"] == pytest.approx(10.0)
        assert f["sigma_daily"] == pytest.approx(0.0)
        assert f["forecast_demand_horizon"] == pytest.approx(300.0)
        assert risk["level"] == "high"
        assert risk["days_of_cover"] == pytest.approx(5.0)
        assert pos["stockout_date"] == "2026-03-19"
        assert pos["stocks_out_in_horizon"] is True
        assert pos["unserved_demand"] == pytest.approx(250.0)
        assert r["lead_time_demand"] == pytest.approx(70.0)
        assert r["safety_stock"] == pytest.approx(0.0)
        assert r["effective_reorder_point"] == 70
        assert r["target_stock"] == 370
        assert r["reorder_needed"] is True
        assert r["recommended_quantity"] == 320
        assert r["capped_by_max_stock"] is False
        assert pos["reasoning"] and risk["reasons"] and r["reasons"]

    def test_projection_series(self, api, seed):
        product, warehouse, _ = seed.position(available=50)
        seed.sell(product, warehouse, 10)
        pos = _position_for(
            api.get(f"{BASE}/products/{product.id}", params={"horizon_days": 7}).json(),
            warehouse.id,
        )
        proj = pos["projection"]
        assert [p["projected_stock"] for p in proj] == [40, 30, 20, 10, 0, 0, 0]
        assert [p["cumulative_demand"] for p in proj] == [10, 20, 30, 40, 50, 60, 70]
        assert proj[0]["day"] == FIXED_TODAY.isoformat()

    def test_demand_history_has_actuals_backtest_and_forward_forecast(self, api, seed):
        product, warehouse, _ = seed.position(available=50)
        seed.sell(product, warehouse, 10)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        history = pos["demand_history"]
        actual = [d for d in history if d["actual"] is not None]
        forward = [d for d in history if d["actual"] is None]
        assert len(actual) == 14 and len(forward) == 30
        assert all(d["actual"] == 10 for d in actual)
        assert all(d["forecast"] is not None for d in actual)
        assert all(d["forecast"] == pytest.approx(10.0) for d in forward)
        assert pos["wape"] is not None

    def test_variable_demand_adds_safety_stock(self, api, seed):
        product, warehouse, _ = seed.position(available=0)
        for offset in range(1, 31):
            seed.order_on(product, warehouse, 2 if offset % 2 else 18, offset, OrderStatus.CONFIRMED)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["forecast"]["sigma_daily"] > 0
        assert pos["reorder"]["safety_stock"] > 0
        assert pos["reorder"]["effective_reorder_point"] > pos["reorder"]["lead_time_demand"]

    def test_max_stock_caps_the_recommendation(self, api, seed):
        product, warehouse, _ = seed.position(available=50, max_stock=200)
        seed.sell(product, warehouse, 10)
        r = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)["reorder"]
        assert r["capped_by_max_stock"] is True
        assert r["target_stock"] == 200
        assert r["recommended_quantity"] == 150

    def test_configured_reorder_level_is_respected(self, api, seed):
        product, warehouse, _ = seed.position(available=90, reorder_level=100)
        seed.sell(product, warehouse, 1)           # 90 days of natural cover
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["risk"]["level"] == "medium"    # raised from healthy by reorder level
        assert pos["reorder"]["effective_reorder_point"] == 100
        assert pos["reorder"]["recommended_quantity"] == 10
        assert any("reorder level" in s for s in pos["risk"]["reasons"])

    def test_healthy_position_recommends_nothing(self, api, seed):
        product, warehouse, _ = seed.position(available=500)
        seed.sell(product, warehouse, 1)
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        assert pos["risk"]["level"] == "healthy"
        assert pos["reorder"]["reorder_needed"] is False
        assert pos["reorder"]["recommended_quantity"] == 0
        assert pos["stocks_out_in_horizon"] is False
        assert pos["unserved_demand"] == 0

    def test_risk_levels_across_the_boundaries(self, api, seed):
        """1 unit/day (history 30 days) so cover == available. L = 7."""
        expected = {7: "high", 8: "medium", 14: "medium", 15: "low", 28: "low", 29: "healthy"}
        for available, level in expected.items():
            product, warehouse, _ = seed.position(available=available)
            seed.sell(product, warehouse, 1)
            pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
            assert pos["risk"]["level"] == level, f"available={available}"

    def test_recent_surge_is_reflected_in_the_forecast(self, api, seed):
        product, warehouse, _ = seed.position(available=1000)
        seed.sell(product, warehouse, 2, days=23, first_day=8)      # older, calm
        seed.sell(product, warehouse, 20, days=7, first_day=1)      # last week, surge
        pos = _position_for(api.get(f"{BASE}/products/{product.id}").json(), warehouse.id)
        ma7, ma14, ma30 = 20.0, (20 * 7 + 2 * 7) / 14, (20 * 7 + 2 * 23) / 30
        assert pos["forecast"]["daily_rate"] == pytest.approx(0.5 * ma7 + 0.3 * ma14 + 0.2 * ma30, abs=1e-3)
        assert pos["forecast"]["daily_rate"] > ma30

    @pytest.mark.parametrize("params", [{"horizon_days": 10}, {"lead_time_days": 0}])
    def test_invalid_params_are_rejected(self, api, product_factory, params):
        product = product_factory()
        assert api.get(f"{BASE}/products/{product.id}", params=params).status_code == 422


# =========================================================================
# What-if simulation
# =========================================================================


@pytest.fixture
def sim_position(seed):
    """80 available, 10/day: cover 8 days => MEDIUM at baseline."""
    product, warehouse, inventory = seed.position(available=80)
    seed.sell(product, warehouse, 10)
    return product, warehouse, inventory


class TestSimulation:
    def test_plus_20_percent_hand_calculated(self, api, sim_position):
        product, warehouse, _ = sim_position
        body = api.post(
            f"{BASE}/simulate", json={"demand_change_percent": 20, "horizon_days": 7}
        ).json()

        # baseline: rate 10, cover 8 (medium), d* = 8 > 7, ROP 70 < 80 => no order
        # scenario: rate 12, cover 6.67 (high), d* = 7 <= 7, ROP 84, target 12 x 14 = 168 => 88
        assert body["demand_change_percent"] == 20
        assert body["positions_analyzed"] == 1
        assert body["baseline"]["risk_counts"]["medium"] == 1
        assert body["scenario"]["risk_counts"]["high"] == 1
        assert body["baseline"]["projected_stockouts"] == 0
        assert body["scenario"]["projected_stockouts"] == 1
        assert body["additional_projected_stockouts"] == 1
        assert body["baseline"]["total_recommended_units"] == 0
        assert body["scenario"]["total_recommended_units"] == 88
        assert body["additional_reorder_units"] == 88
        assert body["positions_with_risk_change"] == 1
        assert body["positions_with_stockout_date_change"] == 1
        assert body["newly_projected_stockouts"] == 1
        assert body["changed_positions_count"] == len(body["changed_positions"]) == 1

        delta = body["changed_positions"][0]
        assert delta["product_id"] == str(product.id)
        assert delta["warehouse_id"] == str(warehouse.id)
        assert delta["baseline_risk"] == "medium"
        assert delta["scenario_risk"] == "high"
        assert delta["risk_changed"] is True
        assert delta["newly_stocking_out"] is True
        assert delta["baseline_daily_rate"] == pytest.approx(10.0)
        assert delta["scenario_daily_rate"] == pytest.approx(12.0)
        assert delta["additional_reorder_quantity"] == 88
        assert delta["baseline_stockout_date"] == "2026-03-22"     # day 8
        assert delta["scenario_stockout_date"] == "2026-03-21"     # day 7

    def test_zero_percent_changes_nothing(self, api, sim_position):
        body = api.post(f"{BASE}/simulate", json={"demand_change_percent": 0}).json()
        assert body["baseline"] == body["scenario"]
        assert body["changed_positions"] == []
        assert body["additional_reorder_units"] == 0
        assert body["additional_projected_stockouts"] == 0
        assert body["positions_with_risk_change"] == 0

    def test_stockout_date_shift_alone_is_reported_as_changed(self, api, seed):
        """Regression: a position whose stockout date moves, but whose risk
        level, reorder quantity and in-horizon status all stay the same,
        must still appear in changed_positions.

        1000 available at 10/day: stockout on day 100 (healthy, outside the
        30-day horizon, no reorder). At +20% (12/day) it is day ceil(83.3) =
        84: still healthy, still outside the horizon, still no reorder.
        """
        product, warehouse, _ = seed.position(available=1000)
        seed.sell(product, warehouse, 10)

        body = api.post(
            f"{BASE}/simulate",
            json={"demand_change_percent": 20, "horizon_days": 30},
        ).json()

        assert len(body["changed_positions"]) == 1
        delta = body["changed_positions"][0]
        assert delta["product_id"] == str(product.id)
        assert delta["warehouse_id"] == str(warehouse.id)

        # everything except the stockout date is unchanged...
        assert delta["baseline_risk"] == delta["scenario_risk"] == "healthy"
        assert delta["risk_changed"] is False
        assert delta["baseline_stocks_out_in_horizon"] is False
        assert delta["scenario_stocks_out_in_horizon"] is False
        assert delta["newly_stocking_out"] is False
        assert delta["baseline_recommended_quantity"] == 0
        assert delta["scenario_recommended_quantity"] == 0
        assert delta["additional_reorder_quantity"] == 0

        # ...but the date moved earlier, and that is what must be reported.
        assert delta["baseline_stockout_date"] == (FIXED_TODAY + timedelta(days=99)).isoformat()
        assert delta["scenario_stockout_date"] == (FIXED_TODAY + timedelta(days=83)).isoformat()
        assert delta["scenario_stockout_date"] < delta["baseline_stockout_date"]

        # aggregate counters are untouched by a pure date shift
        assert body["positions_with_risk_change"] == 0
        assert body["additional_projected_stockouts"] == 0
        assert body["additional_reorder_units"] == 0

    def test_demand_drop_improves_risk(self, api, sim_position):
        body = api.post(f"{BASE}/simulate", json={"demand_change_percent": -50}).json()
        delta = body["changed_positions"][0]          # rate 5 => cover 16 => low
        assert delta["baseline_risk"] == "medium"
        assert delta["scenario_risk"] == "low"
        assert delta["additional_reorder_quantity"] == 0
        assert body["scenario"]["risk_counts"]["low"] == 1

    def test_minus_100_percent_removes_all_risk(self, api, portfolio):
        body = api.post(f"{BASE}/simulate", json={"demand_change_percent": -100}).json()
        assert body["scenario"]["risk_counts"]["high"] == 0
        assert body["scenario"]["risk_counts"]["healthy"] == 4
        assert body["scenario"]["projected_stockouts"] == 0
        assert body["scenario"]["total_recommended_units"] == 0
        assert body["additional_reorder_units"] == -(320 + 74)
        assert all(d["scenario_stockout_date"] is None for d in body["changed_positions"])

    def test_plus_1000_percent_runs_the_full_scenario(self, api, sim_position):
        product, warehouse, _ = sim_position
        body = api.post(
            f"{BASE}/simulate", json={"demand_change_percent": 1000, "horizon_days": 30}
        ).json()

        assert body["positions_analyzed"] == 1
        assert body["baseline"]["risk_counts"]["medium"] == 1
        assert body["scenario"]["risk_counts"]["high"] == 1
        assert body["scenario"]["projected_stockouts"] == 1
        delta = body["changed_positions"][0]
        assert delta["product_id"] == str(product.id)
        assert delta["warehouse_id"] == str(warehouse.id)
        assert delta["baseline_daily_rate"] == pytest.approx(10.0)
        assert delta["scenario_daily_rate"] == pytest.approx(110.0)
        assert delta["baseline_stockout_date"] is not None
        assert delta["scenario_stockout_date"] is not None
        assert delta["scenario_recommended_quantity"] > delta["baseline_recommended_quantity"]

    def test_october_18_low_demand_and_plus_10_percent_summary_matches_rows(
        self, api, inventory_factory, product_factory, warehouse_factory,
        order_factory,
    ):
        reference_date = date(2026, 10, 18)
        api.app.dependency_overrides[get_today] = lambda: reference_date
        product = product_factory()
        warehouse = warehouse_factory()
        inventory = inventory_factory(
            product=product,
            warehouse=warehouse,
            quantity=1000,
            reorder_level=0,
            max_stock=0,
        )
        inventory.created_at = _at(reference_date - timedelta(days=30))
        order_factory(
            product=product,
            warehouse=warehouse,
            quantity=1,
            status=OrderStatus.CONFIRMED,
            created_at=_at(reference_date - timedelta(days=20)),
        )

        response = api.post(
            f"{BASE}/simulate",
            json={"demand_change_percent": 10, "horizon_days": 30},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["as_of_date"] == reference_date.isoformat()
        assert body["positions_analyzed"] == 1
        assert body["positions_with_risk_change"] == 0
        assert body["positions_with_stockout_date_change"] == 1
        assert body["newly_projected_stockouts"] == 0
        assert body["additional_projected_stockouts"] == 0
        assert body["changed_positions_count"] == len(body["changed_positions"]) == 1
        assert body["baseline"]["projected_stockouts"] == 0
        assert body["scenario"]["projected_stockouts"] == 0

        delta = body["changed_positions"][0]
        assert delta["baseline_daily_rate"] == pytest.approx(0.0067)
        assert delta["scenario_daily_rate"] == pytest.approx(0.0073)
        assert delta["baseline_risk"] == delta["scenario_risk"] == "healthy"
        assert delta["baseline_stockout_date"] > reference_date.isoformat()
        assert delta["scenario_stockout_date"] > reference_date.isoformat()

    def test_large_surge_across_a_portfolio(self, api, portfolio):
        body = api.post(f"{BASE}/simulate", json={"demand_change_percent": 100}).json()
        assert body["positions_analyzed"] == 4
        assert body["scenario"]["total_recommended_units"] > body["baseline"]["total_recommended_units"]
        assert body["additional_reorder_units"] > 0
        # no-history position cannot be affected by scaling zero demand
        names = {d["product_name"] for d in body["changed_positions"]}
        assert "Charlie Gizmo" not in names

    def test_scope_to_one_product(self, api, portfolio):
        a = portfolio["A"][0]
        body = api.post(
            f"{BASE}/simulate",
            json={"demand_change_percent": 50, "product_id": str(a.id)},
        ).json()
        assert body["positions_analyzed"] == 1
        assert all(d["product_id"] == str(a.id) for d in body["changed_positions"])

    def test_scope_to_one_warehouse(self, api, portfolio):
        wb = portfolio["B"][1]
        body = api.post(
            f"{BASE}/simulate",
            json={"demand_change_percent": 50, "warehouse_id": str(wb.id)},
        ).json()
        assert body["positions_analyzed"] == 1

    def test_unknown_product_scope_is_404(self, api):
        _assert_error(
            api.post(f"{BASE}/simulate",
                     json={"demand_change_percent": 10, "product_id": str(uuid4())}),
            status_code=404, error_code="NOT_FOUND",
        )

    def test_lead_time_override(self, api, sim_position):
        body = api.post(
            f"{BASE}/simulate",
            json={"demand_change_percent": 0, "lead_time_days": 3},
        ).json()
        assert body["assumptions"]["lead_time_days"] == 3
        assert body["baseline"]["risk_counts"]["low"] == 1   # cover 8 vs thresholds 3/6/12

    @pytest.mark.parametrize("percent", [-100, -99.5, 0, 0.5, 1000])
    def test_boundary_values_are_accepted(self, api, percent):
        assert api.post(f"{BASE}/simulate", json={"demand_change_percent": percent}).status_code == 200

    @pytest.mark.parametrize("percent", [-100.01, -250, 1000.01])
    def test_out_of_range_percent_is_rejected(self, api, percent):
        _assert_error(
            api.post(f"{BASE}/simulate", json={"demand_change_percent": percent}),
            status_code=422, error_code="REQUEST_VALIDATION_ERROR",
        )

    @pytest.mark.parametrize(
        "payload",
        [{}, {"demand_change_percent": "lots"}, {"demand_change_percent": 10, "horizon_days": 15},
         {"demand_change_percent": 10, "lead_time_days": 0},
         {"demand_change_percent": 10, "product_id": "nope"}],
    )
    def test_malformed_payloads_are_rejected(self, api, payload):
        assert api.post(f"{BASE}/simulate", json=payload).status_code == 422

    def test_simulation_persists_nothing(self, api, sim_position, db_session):
        _, _, inventory = sim_position
        before = (inventory.quantity, inventory.reserved_quantity, inventory.version)
        order_count = db_session.query(Order).count()
        api.post(f"{BASE}/simulate", json={"demand_change_percent": 300})
        db_session.refresh(inventory)
        assert (inventory.quantity, inventory.reserved_quantity, inventory.version) == before
        assert db_session.query(Order).count() == order_count

    def test_date_overflow_returns_null_dates_from_dashboard_and_simulation(
        self, api, db_session, product_factory, warehouse_factory, inventory_factory,
        order_factory,
    ):
        # Keep every plotted forecast date representable while making the
        # baseline stockout date exceed date.max.
        as_of = date.max - timedelta(days=30)
        api.app.dependency_overrides[get_today] = lambda: as_of
        product = product_factory()
        warehouse = warehouse_factory()
        inventory = inventory_factory(
            product=product,
            warehouse=warehouse,
            quantity=40,
            reorder_level=45,
            max_stock=0,
        )
        inventory.created_at = _at(as_of - timedelta(days=60))
        for offset in range(1, 31):
            order_factory(
                product=product,
                warehouse=warehouse,
                quantity=1,
                status=OrderStatus.CONFIRMED,
                created_at=_at(as_of - timedelta(days=offset)),
            )
        db_session.flush()

        dashboard = api.get(f"{BASE}/dashboard").json()
        summary = next(
            row for row in dashboard["reorder_recommendations"]
            if row["product_id"] == str(product.id)
        )
        assert summary["stockout_date"] is None

        simulation = api.post(
            f"{BASE}/simulate", json={"demand_change_percent": 1000}
        ).json()
        delta = next(
            row for row in simulation["changed_positions"]
            if row["product_id"] == str(product.id)
        )
        assert delta["baseline_stockout_date"] is None
        assert delta["scenario_stockout_date"] == (as_of + timedelta(days=3)).isoformat()

    def test_simulation_is_deterministic(self, api, portfolio):
        payload = {"demand_change_percent": 35}
        first = api.post(f"{BASE}/simulate", json=payload).json()
        second = api.post(f"{BASE}/simulate", json=payload).json()
        first.pop("generated_at"), second.pop("generated_at")
        assert first == second
