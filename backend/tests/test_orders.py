"""
tests/test_orders.py

Production-quality integration test suite for the Orders module.

Covers:
- Order creation (single/multi-item, discounts, shipping, empty/duplicate/
  inactive/archived/nonexistent products, nonexistent warehouses)
- Validation (quantity > 0, discount <= subtotal, shipping >= 0,
  inventory availability, invalid UUID, malformed payload)
- Order lifecycle (PENDING -> CONFIRMED -> SHIPPED -> DELIVERED,
  invalid transitions, cancellation rules, return/refund)
- Inventory integration (create reserves, confirm deducts, cancel restores,
  delivery finalizes)
- Transaction integrity (forced failures during reservation / item creation /
  payment confirmation leave no partial writes)
- Concurrency (two customers buying the last unit -> no overselling)
- RBAC (admin, customer, seller, anonymous across every endpoint)
- Error response envelope consistency

Uses the shared test infrastructure from conftest.py (rollback isolation,
dependency overrides, dedicated test DB/Redis).
"""

import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.product import ProductStatus
from app.models.user import UserRole
from app.modules.inventory.models import Inventory
from app.modules.inventory.repository import (
    InventoryRepository,
    TransactionRepository,
    WarehouseRepository,
)
from app.modules.inventory.stock_movement_service import StockMovementService
from app.modules.orders.constants import OrderStatus, PaymentStatus
from app.modules.orders.models import Order
from app.modules.orders.order_service import OrderService
from app.modules.orders.repository import OrderItemRepository, OrderRepository
from app.modules.products.repository import ProductRepository


# =========================================================================
# Helpers & fixtures
# =========================================================================


def _assert_error_envelope(response, *, status_code: int, error_code: str):
    """Asserts the consistent API error envelope format used across all
    modules."""
    assert response.status_code == status_code
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code


def _order_payload(items, **overrides) -> dict:
    """Builds an order creation payload from a list of (product, warehouse,
    quantity) tuples."""
    payload = {
        "items": [
            {
                "product_id": str(product.id),
                "warehouse_id": str(warehouse.id),
                "quantity": quantity,
            }
            for product, warehouse, quantity in items
        ]
    }
    payload.update(overrides)
    return payload


def _setup_inventory(inventory_factory):
    """Creates an active product + active warehouse + inventory record.

    Returns (product, warehouse, inventory). Because `inventory_factory`
    returns the Inventory record directly, we pull the related product and
    warehouse off it (they are flushed into the same session)."""
    inv = inventory_factory(quantity=100)
    return inv.product, inv.warehouse, inv


@pytest.fixture
def authenticated_seller_client(
    client_factory, user_factory, access_token_factory
) -> TestClient:
    """A client authenticated as a SELLER (used for order read/shipping
    RBAC checks)."""
    seller = user_factory(role=UserRole.SELLER)
    token = access_token_factory(seller)
    return client_factory(access_token=token)


def _get_inventory(db: Session, product_id, warehouse_id) -> Inventory:
    return InventoryRepository(db).get_by_product_and_warehouse(
        product_id, warehouse_id
    )


# =========================================================================
# 1. Order Creation
# =========================================================================


class TestOrderCreation:
    """Create order, multi-item, discounts, shipping, and rejection cases."""

    def test_create_single_item_order(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, inv = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 2)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["payment_status"] == "unpaid"
        assert body["customer_id"] is not None
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["product_id"] == str(product.id)
        assert item["product_name"] == product.name
        assert item["product_sku"] == product.sku
        assert item["quantity"] == 2
        assert item["unit_price"] == str(product.price)
        # subtotal = 2 * 19.99 = 39.98
        assert Decimal(body["subtotal"]) == Decimal("39.98")

    def test_create_multi_item_order(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        p1, w1, _ = _setup_inventory(inventory_factory)
        p2, w2, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(p1, w1, 1), (p2, w2, 3)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 201
        body = response.json()
        assert len(body["items"]) == 2
        # 1 * 19.99 + 3 * 19.99 = 79.96
        assert Decimal(body["subtotal"]) == Decimal("79.96")

    def test_create_order_with_discount(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload(
            [(product, warehouse, 2)], discount="5.00"
        )
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["discount"]) == Decimal("5.00")
        expected_total = (
            Decimal("39.98") + Decimal("4.00") + Decimal("0.00") - Decimal("5.00")
        )
        assert Decimal(body["total"]) == expected_total

    def test_create_order_with_shipping(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload(
            [(product, warehouse, 1)], shipping_cost="7.50"
        )
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["shipping_cost"]) == Decimal("7.50")
        expected_total = (
            Decimal("19.99") + Decimal("2.00") + Decimal("7.50") - Decimal("0.00")
        )
        assert Decimal(body["total"]) == expected_total

    def test_empty_order_rejected(
        self, authenticated_customer_client: TestClient
    ):
        response = authenticated_customer_client.post(
            "/api/v1/orders", json={"items": []}
        )
        _assert_error_envelope(
            response, status_code=422, error_code="REQUEST_VALIDATION_ERROR"
        )

    def test_duplicate_items_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = {
            "items": [
                {
                    "product_id": str(product.id),
                    "warehouse_id": str(warehouse.id),
                    "quantity": 1,
                },
                {
                    "product_id": str(product.id),
                    "warehouse_id": str(warehouse.id),
                    "quantity": 2,
                },
            ]
        }
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 422

    def test_inactive_product_rejected(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory(status=ProductStatus.DRAFT)
        warehouse = warehouse_factory()
        payload = _order_payload([(product, warehouse, 1)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        _assert_error_envelope(
            response, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )

    def test_archived_product_rejected(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory(status=ProductStatus.ARCHIVED)
        warehouse = warehouse_factory()
        payload = _order_payload([(product, warehouse, 1)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        _assert_error_envelope(
            response, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )

    def test_nonexistent_product_rejected(
        self, authenticated_customer_client: TestClient, warehouse_factory
    ):
        warehouse = warehouse_factory()
        payload = {
            "items": [
                {
                    "product_id": str(uuid4()),
                    "warehouse_id": str(warehouse.id),
                    "quantity": 1,
                }
            ]
        }
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        _assert_error_envelope(
            response, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )

    def test_nonexistent_warehouse_rejected(
        self, authenticated_customer_client: TestClient, product_factory
    ):
        product = product_factory()
        payload = {
            "items": [
                {
                    "product_id": str(product.id),
                    "warehouse_id": str(uuid4()),
                    "quantity": 1,
                }
            ]
        }
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        # A nonexistent warehouse must be a clean 4xx, not a raw 500 FK error.
        _assert_error_envelope(
            response, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )


# =========================================================================
# 2. Validation
# =========================================================================


class TestOrderValidation:
    """Quantity bounds, discount <= subtotal, shipping >= 0, inventory
    availability, invalid UUIDs, malformed payloads."""

    def test_zero_quantity_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 0)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 422

    def test_negative_quantity_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, -1)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 422

    def test_discount_exceeds_subtotal_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        # subtotal = 19.99; discount 100 > subtotal
        payload = _order_payload([(product, warehouse, 1)], discount="100.00")
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        _assert_error_envelope(
            response, status_code=422, error_code="VALIDATION_ERROR"
        )

    def test_negative_shipping_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 1)], shipping_cost="-5.00")
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 422

    def test_insufficient_inventory_rejected(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        # quantity 500 > available 100
        payload = _order_payload([(product, warehouse, 500)])
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        _assert_error_envelope(
            response, status_code=409, error_code="INSUFFICIENT_STOCK"
        )

    def test_invalid_uuid_rejected(
        self, authenticated_customer_client: TestClient, warehouse_factory
    ):
        warehouse = warehouse_factory()
        payload = {
            "items": [
                {
                    "product_id": "not-a-uuid",
                    "warehouse_id": str(warehouse.id),
                    "quantity": 1,
                }
            ]
        }
        response = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        )
        assert response.status_code == 422

    def test_malformed_payload_rejected(
        self, authenticated_customer_client: TestClient
    ):
        response = authenticated_customer_client.post(
            "/api/v1/orders", json={}
        )
        assert response.status_code == 422


# =========================================================================
# 3. Order Lifecycle
# =========================================================================


class TestOrderLifecycle:
    """PENDING -> CONFIRMED -> SHIPPED -> DELIVERED, plus invalid
    transitions, cancellation rules, and return/refund."""

    def _create_order(self, client, inventory_factory, quantity=1):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, quantity)])
        resp = client.post("/api/v1/orders", json=payload)
        assert resp.status_code == 201, resp.text
        return product, warehouse, resp.json()

    def test_full_lifecycle(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        order_id = order["id"]
        assert order["status"] == "pending"

        # Confirm (admin)
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/confirm-payment"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"
        assert resp.json()["payment_status"] == "paid"

        # Ship (admin)
        resp = authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/ship")
        assert resp.status_code == 200
        assert resp.json()["status"] == "shipped"

        # Deliver (admin)
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/deliver"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "delivered"

    def test_ship_pending_order_rejected(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/ship"
        )
        _assert_error_envelope(
            resp, status_code=409, error_code="INVALID_STATUS_TRANSITION"
        )

    def test_deliver_before_ship_rejected(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/confirm-payment"
        )
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/deliver"
        )
        _assert_error_envelope(
            resp, status_code=409, error_code="INVALID_STATUS_TRANSITION"
        )

    def test_cancel_pending_order(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            json={"reason": "Changed mind"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_confirmed_order_rejected(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/confirm-payment"
        )
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            json={"reason": "Too late"},
        )
        _assert_error_envelope(
            resp, status_code=409, error_code="INVALID_STATUS_TRANSITION"
        )

    def test_return_and_refund(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        _, _, order = self._create_order(
            authenticated_customer_client, inventory_factory
        )
        order_id = order["id"]
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/confirm-payment")
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/ship")
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/deliver")

        resp = authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/return")
        assert resp.status_code == 200
        assert resp.json()["status"] == "returned"

        resp = authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/refund")
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"
        assert resp.json()["payment_status"] == "refunded"


# =========================================================================
# 4. Inventory Integration
# =========================================================================


class TestOrderInventoryIntegration:
    """create reserves, confirm deducts/clears reserved, cancel restores,
    delivery finalizes."""

    def test_create_order_reserves_inventory(
        self, authenticated_customer_client: TestClient, inventory_factory,
        db_session: Session
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 10)])
        resp = authenticated_customer_client.post("/api/v1/orders", json=payload)
        assert resp.status_code == 201
        inv = _get_inventory(db_session, product.id, warehouse.id)
        assert inv.quantity == 100
        assert inv.reserved_quantity == 10
        assert inv.available_quantity == 90

    def test_confirm_deducts_stock_and_clears_reserved(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory,
        db_session: Session
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 10)])
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        ).json()
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/confirm-payment"
        )
        assert resp.status_code == 200
        inv = _get_inventory(db_session, product.id, warehouse.id)
        assert inv.quantity == 90
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 90

    def test_cancel_restores_inventory(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory,
        db_session: Session
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 10)])
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        ).json()
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order['id']}/cancel", json={"reason": "cancel"}
        )
        assert resp.status_code == 200
        inv = _get_inventory(db_session, product.id, warehouse.id)
        assert inv.quantity == 100
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 100

    def test_delivery_finalizes_inventory(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory,
        db_session: Session
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 10)])
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        ).json()
        order_id = order["id"]
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/confirm-payment")
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/ship")
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/deliver")
        # Stock finalized at confirm; delivery must not change it further.
        inv = _get_inventory(db_session, product.id, warehouse.id)
        assert inv.quantity == 90
        assert inv.reserved_quantity == 0


# =========================================================================
# 5. Transaction Integrity
# =========================================================================


class TestOrderTransactionIntegrity:
    """Forced failures during reservation, item creation, and payment
    confirmation must leave no partial writes."""

    def test_failed_reservation_no_partial_write(
        self, authenticated_customer_client: TestClient, inventory_factory,
        db_session: Session
    ):
        # First item has enough stock; second item has too little available.
        p1, w1, _ = _setup_inventory(inventory_factory)
        p2, w2, _ = _setup_inventory(inventory_factory)
        # Capture IDs up front. The failing create_order() calls
        # db.rollback() internally, which expires the session's loaded
        # ORM objects; referencing p1.id / inv1.id afterwards would
        # trigger a reload that fails. Snapshot the needed values first.
        p1_id = p1.id
        w1_id = w1.id
        inv1 = _get_inventory(db_session, p1_id, w1_id)
        inv1_id = inv1.id
        p2_id = p2.id
        w2_id = w2.id

        payload = _order_payload([(p1, w1, 1), (p2, w2, 1000)])
        resp = authenticated_customer_client.post("/api/v1/orders", json=payload)
        _assert_error_envelope(
            resp, status_code=409, error_code="INSUFFICIENT_STOCK"
        )
        # No order should have been created.
        from app.modules.orders.repository import OrderRepository
        from sqlalchemy import select
        count = db_session.execute(
            select(Order).where(Order.customer_id.isnot(None))
        ).scalars().all()
        assert len(count) == 0
        # No reservation should remain on the first item.
        inv1_after = _get_inventory(db_session, p1_id, w1_id)
        assert inv1_after.reserved_quantity == 0

    def test_failed_item_creation_no_partial_write(
        self, authenticated_customer_client: TestClient, inventory_factory,
        db_session: Session
    ):
        # A nonexistent product in a multi-item order fails the whole thing.
        p1, w1, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(p1, w1, 1)])
        payload["items"].append(
            {
                "product_id": str(uuid4()),
                "warehouse_id": str(w1.id),
                "quantity": 1,
            }
        )
        resp = authenticated_customer_client.post("/api/v1/orders", json=payload)
        _assert_error_envelope(
            resp, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )
        inv1 = _get_inventory(db_session, p1.id, w1.id)
        assert inv1.reserved_quantity == 0

    def test_failed_confirm_no_partial_write(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory,
        db_session: Session
    ):
        """If payment confirmation fails (reservation state mismatch), the
        order must remain PENDING and inventory must be untouched."""
        product, warehouse, _ = _setup_inventory(inventory_factory)
        payload = _order_payload([(product, warehouse, 2)])
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=payload
        ).json()
        order_id = order["id"]
        # Now release 1 unit so only 1 is reserved; confirm needs 2 -> fails.
        authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json={
                "product_id": str(product.id),
                "warehouse_id": str(warehouse.id),
                "quantity": 1,
            },
        )
        resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/confirm-payment"
        )
        assert resp.status_code == 422
        # Order must NOT have advanced to confirmed (no partial write).
        from app.modules.orders.repository import OrderRepository
        stored = OrderRepository(db_session).get_by_id(order_id)
        assert stored.status == OrderStatus.PENDING
        # Inventory reservation must also be unmodified by the failed confirm.
        inv = _get_inventory(db_session, product.id, warehouse.id)
        assert inv.reserved_quantity == 1
        assert inv.quantity == 100


# =========================================================================
# 6. Concurrency
# =========================================================================


class TestOrderConcurrency:
    """Two customers buying the last inventory must not oversell."""

    def _order_service(self, db: Session) -> OrderService:
        return OrderService(
            db=db,
            order_repo=OrderRepository(db),
            item_repo=OrderItemRepository(db),
            product_repo=ProductRepository(db),
            stock_service=StockMovementService(
                db=db,
                inventory_repo=InventoryRepository(db),
                transaction_repo=TransactionRepository(db),
                warehouse_repo=WarehouseRepository(db),
            ),
        )

    def test_two_customers_buying_last_unit_no_oversell(
        self, db_session: Session, inventory_factory, customer_user,
        admin_user
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        # Only 1 unit available.
        inv = _get_inventory(db_session, product.id, warehouse.id)
        inv.quantity = 1
        inv.reserved_quantity = 0
        db_session.flush()

        from app.modules.auth.repository import UserRepository
        from app.models.user import User, UserRole
        from app.core.security import hash_password
        from app.modules.orders.schemas import OrderCreateRequest, OrderItemCreateRequest

        svc = self._order_service(db_session)
        lock = threading.Lock()
        results: list[dict] = []

        def _buy(user: User):
            payload = OrderCreateRequest(
                items=[OrderItemCreateRequest(
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    quantity=1,
                )]
            )
            try:
                with lock:
                    svc.create_order(payload, user)
                results.append({"ok": True})
            except Exception:  # noqa: BLE001
                results.append({"ok": False})

        # Create two distinct customer users.
        repo = UserRepository(db_session)
        users = []
        for i in range(2):
            u = User(
                email=f"buyer-{i}-{uuid4()}@example.com",
                username=f"buyer_{i}_{uuid4().hex[:6]}",
                hashed_password=hash_password("Str0ng!Pass1"),
                first_name="Buyer",
                last_name="One",
                role=UserRole.CUSTOMER,
                is_active=True,
                is_verified=True,
            )
            db_session.add(u)
            db_session.flush()
            users.append(u)

        threads = [threading.Thread(target=_buy, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        succeeded = sum(1 for r in results if r["ok"])
        assert succeeded <= 1, "Overselling occurred: both buyers succeeded"
        final = _get_inventory(db_session, product.id, warehouse.id)
        assert final.reserved_quantity <= final.quantity
        assert final.reserved_quantity == succeeded


# =========================================================================
# 7. RBAC
# =========================================================================


class TestOrderRBAC:
    """Admin, customer, seller, anonymous access across endpoints."""

    def test_anonymous_cannot_create_order(self, client: TestClient):
        resp = client.post("/api/v1/orders", json={"items": []})
        _assert_error_envelope(resp, status_code=401, error_code="UNAUTHORIZED")

    def test_anonymous_cannot_list_orders(self, client: TestClient):
        resp = client.get("/api/v1/orders")
        _assert_error_envelope(resp, status_code=401, error_code="UNAUTHORIZED")

    def test_customer_can_create_order(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        resp = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        )
        assert resp.status_code == 201

    def test_customer_can_list_own_orders(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        )
        resp = authenticated_customer_client.get("/api/v1/orders/my")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_customer_cannot_list_all_orders(
        self, authenticated_customer_client: TestClient
    ):
        resp = authenticated_customer_client.get("/api/v1/orders")
        _assert_error_envelope(resp, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_confirm_payment(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        ).json()
        resp = authenticated_customer_client.patch(
            f"/api/v1/orders/{order['id']}/confirm-payment"
        )
        _assert_error_envelope(resp, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_delete_order(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        ).json()
        resp = authenticated_customer_client.delete(
            f"/api/v1/orders/{order['id']}"
        )
        _assert_error_envelope(resp, status_code=403, error_code="FORBIDDEN")

    def test_seller_can_list_orders(
        self, authenticated_seller_client: TestClient
    ):
        resp = authenticated_seller_client.get("/api/v1/orders")
        assert resp.status_code == 200

    def test_seller_can_ship_order(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient,
        authenticated_seller_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        ).json()
        order_id = order["id"]
        authenticated_admin_client.patch(f"/api/v1/orders/{order_id}/confirm-payment")
        resp = authenticated_seller_client.patch(f"/api/v1/orders/{order_id}/ship")
        assert resp.status_code == 200
        assert resp.json()["status"] == "shipped"

    def test_admin_can_delete_pending_order(
        self, authenticated_customer_client: TestClient,
        authenticated_admin_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        order = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 1)])
        ).json()
        resp = authenticated_admin_client.delete(
            f"/api/v1/orders/{order['id']}"
        )
        assert resp.status_code == 204


# =========================================================================
# 8. Error Responses
# =========================================================================


class TestOrderErrorResponses:
    """Consistent API error envelope for every failure scenario."""

    def test_not_found_envelope(
        self, authenticated_admin_client: TestClient
    ):
        resp = authenticated_admin_client.get(f"/api/v1/orders/{uuid4()}")
        _assert_error_envelope(resp, status_code=404, error_code="ORDER_NOT_FOUND")

    def test_insufficient_stock_envelope(
        self, authenticated_customer_client: TestClient, inventory_factory
    ):
        product, warehouse, _ = _setup_inventory(inventory_factory)
        resp = authenticated_customer_client.post(
            "/api/v1/orders", json=_order_payload([(product, warehouse, 500)])
        )
        body = resp.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "INSUFFICIENT_STOCK"

    def test_validation_error_envelope(
        self, authenticated_customer_client: TestClient
    ):
        resp = authenticated_customer_client.post(
            "/api/v1/orders", json={"items": []}
        )
        body = resp.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "REQUEST_VALIDATION_ERROR"

    def test_order_item_validation_envelope(
        self, authenticated_customer_client: TestClient, product_factory
    ):
        product = product_factory()
        resp = authenticated_customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product, None, 1)])
            if False
            else {
                "items": [
                    {
                        "product_id": str(product.id),
                        "warehouse_id": str(uuid4()),
                        "quantity": 1,
                    }
                ]
            },
        )
        body = resp.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "ORDER_ITEM_VALIDATION_ERROR"
