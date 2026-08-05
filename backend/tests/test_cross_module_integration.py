"""
tests/test_cross_module_integration.py

Phase 8 — Cross-Module Integration Tests.

This suite verifies COMPLETE business workflows that span the auth,
products, inventory, and orders modules END-TO-END through the HTTP API.
In contrast to the per-module suites (which focus on individual CRUD /
unit-level behavior), every test here drives the full request path:

    register → create product → create warehouse → add stock
        → create order → reserve → confirm → ship → deliver / cancel

and then asserts the resulting DATABASE state (orders, order_items,
inventory), ORDER state, INVENTORY state, TRANSACTION integrity, API
response, and error-envelope consistency.

Workflows covered (one test class each):

  1. TestFullLifecycleE2E             — register → product → warehouse → stock
                                        → order → reserve → confirm → ship →
                                        deliver → inventory verified.
  2. TestCancelRestoresInventory      — create + cancel pending order restores
                                        reserved stock.
  3. TestLastUnitNoOversell           — two customers, one unit available;
                                        only one succeeds, no overselling.
  4. TestMultiItemCancelRestoresAll   — multi-item order reserves all,
                                        cancel restores every line.
  5. TestCreationFailureRollsBack     — one unavailable item fails the whole
                                        order atomically (no order / items /
                                        inventory changes).
  6. TestConfirmationFailureConsistent — failed payment confirmation leaves
                                        order PENDING and inventory untouched.
  7. TestArchiveProductKeepsOrders    — archived product referenced by an
                                        existing order stays valid; new
                                        orders for it are rejected.
  8. TestInactiveWarehouseRejected    — ordering against a deactivated
                                        warehouse is rejected.

Design notes
------------
- API-driven: every step goes through the TestClient (no direct service
  or repository calls for the primary flow). Repositories are used only
  to *inspect* the resulting persistence state (read-after-write).
- Reuses the shared fixtures from conftest.py (client_factory,
  authenticated_admin_client, db_session, unique_value_factory).
- A fresh customer is registered through POST /auth/register for each
  workflow, then authenticated via POST /auth/login, so the customer
  token is genuinely minted from a real registration.
- For the "no oversell" workflow we use the sequential, API-level
  invariant check (the true thread-level concurrency race is already
  covered by the service-level test in test_orders.py); we verify the
  business invariant: only one order succeeds and reserved <= quantity.
- Error-envelope consistency is asserted via the shared
  `_assert_error_envelope` helper (same shape as the module suites).
"""

import uuid
from decimal import Decimal
from typing import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory.models import Inventory
from app.modules.inventory.repository import InventoryRepository
from app.modules.orders.models import Order
from app.modules.orders.repository import OrderRepository

VALID_PASSWORD = "Str0ng!Pass1"


# =========================================================================
# Shared helpers
# =========================================================================


def _assert_error_envelope(response, *, status_code: int, error_code: str):
    """Asserts the consistent API error envelope used across all modules."""
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code


def _register_customer_tokens(
    client_factory: Callable[..., TestClient],
    unique_value_factory: Callable[[str], str],
):
    """
    Registers a brand-new customer via the public /auth/register endpoint,
    logs in, and returns a client authenticated with that customer's token,
    plus the customer's id.

    Returns (customer_client, customer_id).
    """
    idx = unique_value_factory("xcust")
    email = f"{idx}@example.com"
    username = idx.replace("-", "_")
    payload = {
        "email": email,
        "username": username,
        "password": VALID_PASSWORD,
        "confirm_password": VALID_PASSWORD,
        "first_name": "Cross",
        "last_name": "Customer",
        "phone": "+10000000000",
    }
    anon_client = client_factory()
    register_resp = anon_client.post("/api/v1/auth/register", json=payload)
    assert register_resp.status_code == 201, register_resp.text
    customer_id = register_resp.json()["id"]

    login_resp = anon_client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": VALID_PASSWORD},
    )
    assert login_resp.status_code == 200, login_resp.text
    access_token = login_resp.json()["access_token"]

    customer_client = client_factory(access_token=access_token)
    return customer_client, customer_id


def _create_product(
    admin_client: TestClient,
    unique_value_factory: Callable[[str], str],
    **overrides,
) -> dict:
    """Creates an ACTIVE product via the admin API and returns the response body."""
    idx = unique_value_factory("xcpro")
    payload = {
        "sku": f"XSKU-{idx[-8:].upper()}",
        "slug": f"xslug-{idx}",
        "name": f"Cross Product {idx}",
        "description": "Cross-module integration product",
        "short_description": "Integration product",
        "brand": "CrossBrand",
        "category": "CrossCat",
        "price": "29.99",
        "compare_at_price": "34.99",
        "currency": "USD",
        "weight": "1.000",
        "status": "active",
        "is_featured": False,
        "track_inventory": True,
    }
    payload.update(overrides)
    resp = admin_client.post("/api/v1/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_warehouse(
    admin_client: TestClient,
    unique_value_factory: Callable[[str], str],
    **overrides,
) -> dict:
    """Creates an active warehouse via the admin API and returns the response body."""
    idx = unique_value_factory("xcwh")
    payload = {
        "name": f"Cross Warehouse {idx}",
        "code": f"XWH-{idx[-8:].upper()}",
        "address": "1 Cross St",
        "city": "CrossCity",
        "state": "CS",
        "country": "Crossland",
        "postal_code": "00000",
        "contact_number": "+1234567890",
        "email": f"wh-{idx}@example.com",
    }
    payload.update(overrides)
    resp = admin_client.post("/api/v1/inventory/warehouses", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_stock(
    admin_client: TestClient, product_id, warehouse_id, quantity: int
) -> dict:
    """Adds stock via the admin API and returns the StockMovementResponse body."""
    payload = {
        "product_id": str(product_id),
        "warehouse_id": str(warehouse_id),
        "quantity": quantity,
        "reference_number": f"PO-{uuid.uuid4().hex[:8].upper()}",
        "notes": "Cross-module integration stock",
    }
    resp = admin_client.post("/api/v1/inventory/stock/add", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_inventory(db: Session, product_id, warehouse_id) -> Inventory:
    """Reads the persisted inventory record for inspection."""
    return InventoryRepository(db).get_by_product_and_warehouse(
        product_id, warehouse_id
    )


def _order_payload(items, **overrides) -> dict:
    """Builds an order creation payload from (product, warehouse, quantity) tuples."""
    payload = {
        "items": [
            {
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
                "quantity": quantity,
            }
            for product_id, warehouse_id, quantity in items
        ]
    }
    payload.update(overrides)
    return payload


def _count_orders(db: Session) -> int:
    """Counts orders in the persisted session (used for rollback assertions)."""
    return len(db.execute(select(Order)).scalars().all())


def _count_order_items(db: Session) -> int:
    """Counts order items in the persisted session."""
    from app.modules.orders.models import OrderItem

    return len(db.execute(select(OrderItem)).scalars().all())


# =========================================================================
# 1. Full End-to-End Lifecycle
# =========================================================================


class TestFullLifecycleE2E:
    """Customer registers → admin creates product → admin adds inventory →
    customer creates order → inventory reserved → payment confirmed →
    order shipped → order delivered → inventory verified."""

    def test_full_lifecycle(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        # -- Customer registers (real /auth/register) --------------------
        customer_client, customer_id = _register_customer_tokens(
            client_factory, unique_value_factory
        )

        # -- Admin creates product + warehouse + stock -------------------
        product = _create_product(authenticated_admin_client, unique_value_factory)
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, product["id"], warehouse["id"], 100)

        # -- Customer creates order (reserves 10) ------------------------
        order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 10)]),
        )
        assert order_resp.status_code == 201, order_resp.text
        order = order_resp.json()
        order_id = order["id"]
        assert order["status"] == "pending"
        assert order["payment_status"] == "unpaid"
        assert order["customer_id"] == customer_id
        assert len(order["items"]) == 1
        assert order["items"][0]["product_id"] == product["id"]
        # subtotal = 10 * 29.99 = 299.90
        assert Decimal(order["subtotal"]) == Decimal("299.90")

        # -- Inventory reserved (quantity unchanged, reserved=10) ---------
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv is not None
        assert inv.quantity == 100
        assert inv.reserved_quantity == 10
        assert inv.available_quantity == 90

        # -- Payment confirmed (admin) -> deducts stock ------------------
        confirm_resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/confirm-payment"
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        assert confirm_resp.json()["status"] == "confirmed"
        assert confirm_resp.json()["payment_status"] == "paid"

        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv.quantity == 90
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 90

        # -- Order shipped -------------------------------------------------
        ship_resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/ship"
        )
        assert ship_resp.status_code == 200, ship_resp.text
        assert ship_resp.json()["status"] == "shipped"

        # -- Order delivered ------------------------------------------------
        deliver_resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/deliver"
        )
        assert deliver_resp.status_code == 200, deliver_resp.text
        assert deliver_resp.json()["status"] == "delivered"

        # -- Final inventory verified (stock deducted once, no reservation) --
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv.quantity == 90
        assert inv.reserved_quantity == 0

        # -- Persisted order state final + consistent ----------------------
        stored = OrderRepository(db_session).get_by_id(order_id)
        assert stored is not None
        assert stored.status.value == "delivered"
        assert stored.payment_status.value == "paid"
        assert len(stored.items) == 1
        # Snapshot preserved.
        assert stored.items[0].product_name == product["name"]
        assert stored.items[0].product_sku == product["sku"]
        assert stored.items[0].quantity == 10


# =========================================================================
# 2. Cancel Restores Inventory
# =========================================================================


class TestCancelRestoresInventory:
    """Customer creates order → order cancelled → reserved inventory
    restored."""

    def test_cancel_restores_reserved_inventory(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )
        product = _create_product(authenticated_admin_client, unique_value_factory)
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, product["id"], warehouse["id"], 50)

        # Create order (reserves 8).
        order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 8)]),
        )
        assert order_resp.status_code == 201, order_resp.text
        order_id = order_resp.json()["id"]

        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv.reserved_quantity == 8
        assert inv.available_quantity == 42

        # Cancel the order (customer). The cancel endpoint binds
        # CancelOrderRequest via Depends(), so the reason is a query
        # parameter rather than a JSON body.
        cancel_resp = customer_client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            params={"reason": "Changed my mind"},
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        body = cancel_resp.json()
        assert body["status"] == "cancelled"

        # Reserved inventory fully restored.
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv.quantity == 50
        assert inv.reserved_quantity == 0
        assert inv.available_quantity == 50

        # Persisted order state consistent.
        stored = OrderRepository(db_session).get_by_id(order_id)
        assert stored is not None
        assert stored.status.value == "cancelled"
        assert stored.cancel_reason == "Changed my mind"


# =========================================================================
# 3. Two Customers, Last Unit, No Overselling
# =========================================================================


class TestLastUnitNoOversell:
    """Two customers attempt to purchase the last available inventory →
    only one succeeds → no overselling."""

    def test_only_one_customer_buys_last_unit(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        # Register two distinct customers through the real API.
        customer_a_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )
        customer_b_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )

        product = _create_product(authenticated_admin_client, unique_value_factory)
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)
        # Only 1 unit is available.
        _add_stock(authenticated_admin_client, product["id"], warehouse["id"], 1)

        # Customer A places an order for the single unit -> succeeds.
        resp_a = customer_a_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 1)]),
        )
        assert resp_a.status_code == 201, resp_a.text

        # Customer B tries to buy the same (now sole) unit -> must fail.
        resp_b = customer_b_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 1)]),
        )
        _assert_error_envelope(resp_b, status_code=409, error_code="INSUFFICIENT_STOCK")

        # No overselling invariant.
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv is not None
        assert inv.reserved_quantity <= inv.quantity
        assert inv.reserved_quantity == 1
        assert inv.available_quantity == 0

        # Exactly one order exists.
        assert _count_orders(db_session) == 1


# =========================================================================
# 4. Multi-Item Order, Cancel Restores All
# =========================================================================


class TestMultiItemCancelRestoresAll:
    """Multi-item order → inventory reserved for all items → cancel order →
    inventory restored for all items."""

    def test_cancel_restores_all_items(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )

        # Two distinct products & warehouses.
        p1 = _create_product(authenticated_admin_client, unique_value_factory)
        w1 = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, p1["id"], w1["id"], 100)

        p2 = _create_product(authenticated_admin_client, unique_value_factory)
        w2 = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, p2["id"], w2["id"], 100)

        # Multi-item order: 5 of p1/w1, 3 of p2/w2.
        order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(p1["id"], w1["id"], 5), (p2["id"], w2["id"], 3)]),
        )
        assert order_resp.status_code == 201, order_resp.text
        order_id = order_resp.json()["id"]
        assert len(order_resp.json()["items"]) == 2

        # Both reservations applied.
        inv1 = _get_inventory(db_session, p1["id"], w1["id"])
        inv2 = _get_inventory(db_session, p2["id"], w2["id"])
        assert inv1.reserved_quantity == 5
        assert inv2.reserved_quantity == 3

        # Cancel -> both restored.
        cancel_resp = customer_client.patch(
            f"/api/v1/orders/{order_id}/cancel", json={"reason": "Cancel all"}
        )
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert cancel_resp.json()["status"] == "cancelled"

        inv1 = _get_inventory(db_session, p1["id"], w1["id"])
        inv2 = _get_inventory(db_session, p2["id"], w2["id"])
        assert inv1.quantity == 100 and inv1.reserved_quantity == 0
        assert inv2.quantity == 100 and inv2.reserved_quantity == 0
        assert inv1.available_quantity == 100
        assert inv2.available_quantity == 100


# =========================================================================
# 5. Order Creation Failure Rolls Back Everything
# =========================================================================


class TestCreationFailureRollsBack:
    """Order creation failure (one item unavailable) → entire transaction
    rolls back → no order, no order items, no inventory changes."""

    def test_unavailable_item_rolls_back_entire_order(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )

        # First item has enough stock; warehouse added but no stock for item 2.
        p1 = _create_product(authenticated_admin_client, unique_value_factory)
        w1 = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, p1["id"], w1["id"], 10)

        p2 = _create_product(authenticated_admin_client, unique_value_factory)
        w2 = _create_warehouse(authenticated_admin_client, unique_value_factory)
        # Add an inventory record for p2/w2 but with insufficient stock
        # (5 units) so order creation fails with 409 INSUFFICIENT_STOCK
        # rather than 404 (which would be "no inventory record at all").
        _add_stock(authenticated_admin_client, p2["id"], w2["id"], 5)

        # Snapshot IDs so the failed create_order()'s internal rollback
        # (which expires the session) can't break later reads.
        p1_id = p1["id"]
        w1_id = w1["id"]

        # Request 10 units of p2/w2 (only 5 are available) -> whole order fails.
        resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload(
                [(p1["id"], w1["id"], 1), (p2["id"], w2["id"], 10)]
            ),
        )
        _assert_error_envelope(resp, status_code=409, error_code="INSUFFICIENT_STOCK")

        # No order, no order items.
        assert _count_orders(db_session) == 0
        assert _count_order_items(db_session) == 0

        # No inventory changes on the first item (nothing was reserved).
        inv1 = _get_inventory(db_session, p1_id, w1_id)
        assert inv1 is not None
        assert inv1.quantity == 10
        assert inv1.reserved_quantity == 0
        assert inv1.available_quantity == 10

        # No inventory changes on the second item either (nothing reserved).
        inv2 = _get_inventory(db_session, p2["id"], w2["id"])
        assert inv2 is not None
        assert inv2.quantity == 5
        assert inv2.reserved_quantity == 0
        assert inv2.available_quantity == 5


# =========================================================================
# 6. Order Confirmation Failure Consistency
# =========================================================================


class TestConfirmationFailureConsistent:
    """Order confirmation failure → order status remains consistent →
    inventory remains consistent."""

    def test_failed_confirmation_leaves_order_and_inventory_consistent(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )
        product = _create_product(authenticated_admin_client, unique_value_factory)
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, product["id"], warehouse["id"], 100)

        # Create order reserving 2.
        order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 2)]),
        )
        assert order_resp.status_code == 201, order_resp.text
        order_id = order_resp.json()["id"]

        # Now release 1 unit via the inventory API so only 1 is reserved,
        # but the order still "thinks" it reserved 2. Confirmation must fail.
        release_resp = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json={
                "product_id": str(product["id"]),
                "warehouse_id": str(warehouse["id"]),
                "quantity": 1,
            },
        )
        assert release_resp.status_code == 200, release_resp.text

        confirm_resp = authenticated_admin_client.patch(
            f"/api/v1/orders/{order_id}/confirm-payment"
        )
        # Confirmation fails (reservation state mismatch) -> 422.
        assert confirm_resp.status_code == 422, confirm_resp.text

        # Order status remains PENDING (no partial write).
        stored = OrderRepository(db_session).get_by_id(order_id)
        assert stored is not None
        assert stored.status == "pending"
        assert stored.payment_status == "unpaid"

        # Inventory consistent: 1 reserved (the other was explicitly released).
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv is not None
        assert inv.quantity == 100
        assert inv.reserved_quantity == 1
        assert inv.available_quantity == 99


# =========================================================================
# 7. Archived Product Keeps Existing Orders, Rejects New Orders
# =========================================================================


class TestArchiveProductKeepsOrders:
    """Product archived while referenced by orders → existing orders remain
    valid → new orders are rejected."""

    def test_archive_keeps_existing_orders_and_rejects_new(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )
        product = _create_product(authenticated_admin_client, unique_value_factory)
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)
        _add_stock(authenticated_admin_client, product["id"], warehouse["id"], 50)

        # Customer places an order BEFORE archiving.
        order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 3)]),
        )
        assert order_resp.status_code == 201, order_resp.text
        order_id = order_resp.json()["id"]

        # Admin archives the product.
        archive_resp = authenticated_admin_client.patch(
            f"/api/v1/products/{product['id']}/archive"
        )
        assert archive_resp.status_code == 200, archive_resp.text
        assert archive_resp.json()["status"] == "archived"

        # The archived product is no longer visible to customers.
        public_resp = authenticated_admin_client.get(
            f"/api/v1/products/{product['slug']}"
        )
        assert public_resp.status_code == 404

        # A NEW order for the archived product is rejected.
        new_order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 1)]),
        )
        _assert_error_envelope(
            new_order_resp, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )

        # Existing order remains valid: retrievable, snapshot intact,
        # reservation still held.
        stored = OrderRepository(db_session).get_by_id(order_id)
        assert stored is not None
        assert stored.status.value == "pending"
        assert len(stored.items) == 1
        assert stored.items[0].product_name == product["name"]
        assert stored.items[0].product_sku == product["sku"]
        assert str(stored.items[0].product_id) == product["id"]
        assert stored.items[0].quantity == 3

        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv is not None
        assert inv.reserved_quantity == 3


# =========================================================================
# 8. Inactive Warehouse Rejects New Orders
# =========================================================================


class TestInactiveWarehouseRejected:
    """Warehouse inactive → new orders using that warehouse are rejected."""

    def test_deactivated_warehouse_rejects_new_orders(
        self,
        client_factory: Callable[..., TestClient],
        authenticated_admin_client: TestClient,
        unique_value_factory: Callable[[str], str],
        db_session: Session,
    ):
        customer_client, _ = _register_customer_tokens(
            client_factory, unique_value_factory
        )
        product = _create_product(authenticated_admin_client, unique_value_factory)
        # NOTE: We deliberately do NOT add stock to this warehouse. A
        # warehouse with inventory cannot be deactivated (the service
        # raises WAREHOUSE_HAS_INVENTORY), and the order-rejection rule
        # is driven purely by the warehouse's inactive state (checked
        # before any stock availability). Creating a stock-less warehouse
        # lets us cleanly put it into the inactive state.
        warehouse = _create_warehouse(authenticated_admin_client, unique_value_factory)

        # Deactivate the warehouse via the admin API.
        deactivate_resp = authenticated_admin_client.delete(
            f"/api/v1/inventory/warehouses/{warehouse['id']}"
        )
        assert deactivate_resp.status_code == 204, deactivate_resp.text

        # Verify the warehouse is now inactive.
        get_wh = authenticated_admin_client.get(
            f"/api/v1/inventory/warehouses/{warehouse['id']}"
        )
        assert get_wh.status_code == 200
        assert get_wh.json()["is_active"] is False

        # A new order using the inactive warehouse is rejected.
        new_order_resp = customer_client.post(
            "/api/v1/orders",
            json=_order_payload([(product["id"], warehouse["id"], 1)]),
        )
        _assert_error_envelope(
            new_order_resp, status_code=422, error_code="ORDER_ITEM_VALIDATION_ERROR"
        )

        # No order was created.
        assert _count_orders(db_session) == 0

        # No inventory record was created by the rejected order.
        inv = _get_inventory(db_session, product["id"], warehouse["id"])
        assert inv is None

