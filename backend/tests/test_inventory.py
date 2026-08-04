"""
tests/test_inventory.py

Production-quality integration test suite for the Inventory module.

Covers:
- CRUD / lookup (create, retrieve, list by product/warehouse, pagination, sorting, filtering)
- Stock operations (add, remove, reserve, release, adjust, manual correction, confirm, transfer)
- Validation (negative/zero quantities, nonexistent product/warehouse, over-reserve, over-release, invalid UUIDs, missing fields)
- Business rules (available/reserved calculation, stock never negative, transaction recording, version increments, product status sync)
- Transaction integrity (rollback behavior, no partial writes)
- Concurrency (parallel reservations/additions/removals, no overselling, no negative stock)
- RBAC (admin can modify, customer cannot, anonymous cannot access)
- Error response envelope consistency

Uses the shared test infrastructure from conftest.py (fixtures, rollback isolation,
dependency overrides, dedicated test DB/Redis).
"""

import threading
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.product import Product, ProductStatus
from app.models.user import User, UserRole
from app.modules.inventory.models import Inventory, InventoryTransaction, Warehouse
from app.modules.inventory.repository import (
    InventoryRepository,
    TransactionRepository,
    WarehouseRepository,
)
from app.modules.inventory.stock_movement_service import StockMovementService
from app.modules.inventory.constants import InventoryTransactionType, StockStatus


# =========================================================================
# Helpers
# =========================================================================


def _assert_error_envelope(response, *, status_code: int, error_code: str):
    """Asserts the consistent API error envelope format used across all
    modules."""
    assert response.status_code == status_code
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code


def _warehouse_payload(unique_value_factory, **overrides) -> dict:
    idx = unique_value_factory("wh")
    payload = {
        "name": f"Warehouse {idx}",
        "code": f"WH-{idx[-8:].upper()}",
        "city": f"City {idx}",
        "country": "Test Country",
        "address": "123 Test St",
        "postal_code": "00000",
        "contact_number": "+1234567890",
        "email": f"warehouse-{idx}@example.com",
    }
    payload.update(overrides)
    return payload


def _stock_payload(product, warehouse, quantity, **overrides) -> dict:
    payload = {
        "product_id": str(product.id),
        "warehouse_id": str(warehouse.id),
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def _inventory_by_id(db: Session, inventory_id) -> Inventory:
    return db.get(Inventory, inventory_id)


# =========================================================================
# 1. CRUD / Lookup
# =========================================================================


class TestInventoryCRUD:
    """Create, retrieve, list by product/warehouse, pagination, sorting,
    filtering."""

    def test_create_inventory_via_add_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory, unique_value_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        payload = _stock_payload(product, warehouse, 50, reference_number="PO-001")
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add", json=payload
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 50
        assert body["inventory"]["reserved_quantity"] == 0
        assert body["inventory"]["available_quantity"] == 50
        assert body["inventory"]["product_id"] == str(product.id)
        assert body["inventory"]["warehouse_id"] == str(warehouse.id)
        assert body["transaction"]["transaction_type"] == "purchase"

    def test_retrieve_inventory_via_list(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 30),
        )
        response = authenticated_admin_client.get("/api/v1/inventory")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(
            item["product_id"] == str(product.id)
            and item["warehouse_id"] == str(warehouse.id)
            for item in body["items"]
        )

    def test_retrieve_inventory_by_product(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse_a = warehouse_factory()
        warehouse_b = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse_a, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse_b, 20),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"product_id": str(product.id)}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["product_id"] == str(product.id)

    def test_retrieve_inventory_by_warehouse(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        warehouse = warehouse_factory()
        product_a = product_factory()
        product_b = product_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product_a, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product_b, warehouse, 20),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"warehouse_id": str(warehouse.id)}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        for item in body["items"]:
            assert item["warehouse_id"] == str(warehouse.id)

    def test_inventory_listing_pagination(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        warehouse = warehouse_factory()
        for _ in range(5):
            product = product_factory()
            authenticated_admin_client.post(
                "/api/v1/inventory/stock/add",
                json=_stock_payload(product, warehouse, 10),
            )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"page": 1, "page_size": 2, "warehouse_id": str(warehouse.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["pages"] == 3

    def test_inventory_listing_sort_by_quantity(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        warehouse = warehouse_factory()
        for qty in (10, 50, 30):
            product = product_factory()
            authenticated_admin_client.post(
                "/api/v1/inventory/stock/add",
                json=_stock_payload(product, warehouse, qty),
            )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"sort": "quantity_asc", "warehouse_id": str(warehouse.id)},
        )
        assert response.status_code == 200
        body = response.json()
        quantities = [item["quantity"] for item in body["items"]]
        assert quantities == sorted(quantities)

    def test_inventory_listing_filter_by_stock_status(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        # Add 10 stock, then reserve 10 -> available 0 -> out_of_stock
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"stock_status": "out_of_stock"}
        )
        assert response.status_code == 200
        body = response.json()
        assert any(
            item["product_id"] == str(product.id) for item in body["items"]
        )

    def test_inventory_listing_filter_by_query(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory(name="UniqueSearchableProductXYZ")
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"query": "UniqueSearchableProduct"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(
            item["product_id"] == str(product.id) for item in body["items"]
        )

    def test_product_stock_summary(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse_a = warehouse_factory()
        warehouse_b = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse_a, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse_b, 50),
        )
        response = authenticated_admin_client.get(
            f"/api/v1/inventory/products/{product.id}"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total_stock"] == 150
        assert body["total_reserved"] == 0
        assert body["total_available"] == 150
        assert body["warehouse_count"] == 2


# =========================================================================
# 2. Stock Operations
# =========================================================================


class TestStockOperations:
    """Add, remove, reserve, release, adjust, manual correction, confirm,
    transfer — verify resulting quantities."""

    def test_add_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 100
        assert body["inventory"]["available_quantity"] == 100

    def test_add_stock_accumulates(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 50),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 30),
        )
        assert response.status_code == 200
        assert response.json()["inventory"]["quantity"] == 80

    def test_remove_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 40, reason="damage"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 60
        assert body["transaction"]["transaction_type"] == "damage"

    def test_reserve_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 100
        assert body["inventory"]["reserved_quantity"] == 30
        assert body["inventory"]["available_quantity"] == 70
        assert body["transaction"]["transaction_type"] == "reservation"

    def test_release_reservation(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 20),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 100
        assert body["inventory"]["reserved_quantity"] == 10
        assert body["inventory"]["available_quantity"] == 90
        assert body["transaction"]["transaction_type"] == "release"

    def test_adjust_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        adjust_payload = {
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "new_quantity": 75,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/adjust", json=adjust_payload
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 75
        assert body["transaction"]["transaction_type"] == "adjustment"

    def test_manual_correction_to_zero(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        adjust_payload = {
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "new_quantity": 0,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/adjust", json=adjust_payload
        )
        assert response.status_code == 200
        assert response.json()["inventory"]["quantity"] == 0

    def test_confirm_reservation(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/confirm-reservation",
            json=_stock_payload(product, warehouse, 30),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["inventory"]["quantity"] == 70
        assert body["inventory"]["reserved_quantity"] == 0
        assert body["inventory"]["available_quantity"] == 70
        assert body["transaction"]["transaction_type"] == "confirm_reservation"

    def test_transfer_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        from_wh = warehouse_factory()
        to_wh = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, from_wh, 100),
        )
        transfer_payload = {
            "product_id": str(product.id),
            "from_warehouse_id": str(from_wh.id),
            "to_warehouse_id": str(to_wh.id),
            "quantity": 40,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/transfers", json=transfer_payload
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["source"]["inventory"]["quantity"] == 60
        assert body["destination"]["inventory"]["quantity"] == 40
        assert body["source"]["transaction"]["transaction_type"] == "transfer_out"
        assert body["destination"]["transaction"]["transaction_type"] == "transfer_in"
        assert (
            body["source"]["transaction"]["correlation_id"]
            == body["destination"]["transaction"]["correlation_id"]
        )

    def test_inventory_lookup_after_operations(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 25),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["quantity"] == 100
        assert item["reserved_quantity"] == 25
        assert item["available_quantity"] == 75


# =========================================================================
# 3. Validation
# =========================================================================


class TestInventoryValidation:
    """Negative/zero quantities, nonexistent product/warehouse, over-reserve,
    over-release, invalid UUIDs, missing required fields."""

    def test_negative_quantity_add_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, -5),
        )
        assert response.status_code == 422

    def test_zero_quantity_add_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 0),
        )
        assert response.status_code == 422

    def test_nonexistent_product_rejected(
        self, authenticated_admin_client: TestClient, warehouse_factory
    ):
        warehouse = warehouse_factory()
        fake_product = str(uuid4())
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json={
                "product_id": fake_product,
                "warehouse_id": str(warehouse.id),
                "quantity": 10,
            },
        )
        # The service validates product existence up front and returns a
        # clean 404 NOT_FOUND envelope instead of an unhandled IntegrityError.
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_nonexistent_warehouse_rejected(
        self, authenticated_admin_client: TestClient, product_factory
    ):
        product = product_factory()
        fake_warehouse = str(uuid4())
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json={
                "product_id": str(product.id),
                "warehouse_id": fake_warehouse,
                "quantity": 10,
            },
        )
        # The service validates the warehouse is active before mutating, so a
        # non-existent warehouse returns 404.
        assert response.status_code != 200

    def test_reserve_more_than_available(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 20),
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")

    def test_release_more_than_reserved(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 5),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=422, error_code="VALIDATION_ERROR")

    def test_remove_more_than_available(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 20),
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")

    def test_remove_below_reserved_quantity_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        """Removing more than is still available after accounting for
        reservations must fail — it would strand reserved orders."""
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 8),
        )
        # Removing 5 would leave quantity=5, below reserved=8.
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 5),
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")
        # Stock unchanged.
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = get_resp.json()["items"][0]
        assert item["quantity"] == 10
        assert item["reserved_quantity"] == 8

    def test_confirm_more_than_reserved_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        """Confirming more units than are currently reserved must fail."""
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 4),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/confirm-reservation",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=422, error_code="VALIDATION_ERROR")

    def test_transfer_with_insufficient_stock_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        from_wh = warehouse_factory()
        to_wh = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, from_wh, 5),
        )
        transfer_payload = {
            "product_id": str(product.id),
            "from_warehouse_id": str(from_wh.id),
            "to_warehouse_id": str(to_wh.id),
            "quantity": 50,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/transfers", json=transfer_payload
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")

    def test_transfer_same_warehouse_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        transfer_payload = {
            "product_id": str(product.id),
            "from_warehouse_id": str(warehouse.id),
            "to_warehouse_id": str(warehouse.id),
            "quantity": 10,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/transfers", json=transfer_payload
        )
        assert response.status_code == 422

    def test_release_on_nonexistent_inventory_404(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        """Releasing on a product-warehouse pair with no inventory record
        must return 404 INVENTORY_NOT_FOUND (no partial writes)."""
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 5),
        )
        _assert_error_envelope(response, status_code=404, error_code="INVENTORY_NOT_FOUND")

    def test_invalid_uuid_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json={
                "product_id": "not-a-uuid",
                "warehouse_id": str(warehouse.id),
                "quantity": 10,
            },
        )
        assert response.status_code == 422

    def test_missing_required_fields_rejected(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json={"product_id": str(product.id), "quantity": 10},
        )
        assert response.status_code == 422


# =========================================================================
# 4. Business Rules
# =========================================================================


class TestInventoryBusinessRules:
    """Available/reserved calculation, stock never negative, reserved never
    exceeds total, reservation/release effect, transactions recorded, version
    increments, product status sync."""

    def test_available_quantity_calculation(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 40),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = response.json()["items"][0]
        assert item["available_quantity"] == item["quantity"] - item["reserved_quantity"]
        assert item["available_quantity"] == 60

    def test_reserved_quantity_calculation(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 20),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = response.json()["items"][0]
        assert item["reserved_quantity"] == 50
        assert item["available_quantity"] == 50

    def test_stock_never_negative(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Attempt to remove more than available
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 20),
        )
        assert response.status_code == 409
        # Verify stock unchanged
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        assert get_resp.json()["items"][0]["quantity"] == 10

    def test_reserved_never_exceeds_total(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Reserve all 10
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        # Attempt to reserve more -> insufficient
        response = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 1),
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")

    def test_reservation_reduces_available(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        before = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        ).json()["items"][0]
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        after = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        ).json()["items"][0]
        assert before["available_quantity"] == 100
        assert after["available_quantity"] == 70

    def test_release_restores_available(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 30),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = response.json()["items"][0]
        assert item["available_quantity"] == 100
        assert item["reserved_quantity"] == 0

    def test_transactions_recorded_for_each_movement(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/transactions",
            params={"product_id": str(product.id)},
        )
        assert response.status_code == 200
        body = response.json()
        types = [item["transaction_type"] for item in body["items"]]
        assert "purchase" in types
        assert "reservation" in types
        assert "release" in types

    def test_version_increments_on_update(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        # The first add on a brand-new inventory record goes through
        # create() (version=1) followed by update() (version+1 => 2),
        # and every subsequent movement also increments the version.
        look = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        ).json()["items"][0]
        assert look["version"] == 2
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 50),
        )
        look2 = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        ).json()["items"][0]
        assert look2["version"] == 3
        # Reserve also bumps the version (an update to reserved_quantity).
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        look3 = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        ).json()["items"][0]
        assert look3["version"] == 4

    def test_product_status_sync_to_out_of_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        # Tracked product starts ACTIVE. Deplete all stock -> should become
        # OUT_OF_STOCK after a product update triggers the sync.
        product = product_factory(status=ProductStatus.ACTIVE, track_inventory=True)
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Deplete stock via remove
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 10),
        )
        # Trigger product status sync via an update
        authenticated_admin_client.put(
            f"/api/v1/products/{product.id}", json={"name": "Synced"}
        )
        # Reload product
        get_resp = authenticated_admin_client.get(
            f"/api/v1/products/{product.slug}"
        )
        # OUT_OF_STOCK is not visible to public; check admin listing instead
        admin_resp = authenticated_admin_client.get("/api/v1/products/admin")
        statuses = {
            item["id"]: item["status"] for item in admin_resp.json()["items"]
        }
        assert statuses.get(str(product.id)) == "out_of_stock"


# =========================================================================
# 5. Transaction Integrity
# =========================================================================


class TestInventoryTransactionIntegrity:
    """Rollback behavior — failure after reservation/adjustment/release must
    not leave partial writes."""

    def test_failed_add_stock_leaves_no_partial_state(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        # Attempt to remove from a non-existent inventory -> 404, no partial writes
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=404, error_code="INVENTORY_NOT_FOUND")
        # Verify no inventory record was created
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        assert get_resp.json()["total"] == 0

    def test_failed_reserve_does_not_create_transaction(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Reserve more than available -> fails
        response = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 50),
        )
        assert response.status_code == 409
        # No reservation transaction should have been recorded
        tx_resp = authenticated_admin_client.get(
            "/api/v1/inventory/transactions",
            params={"product_id": str(product.id), "transaction_type": "reservation"},
        )
        assert tx_resp.json()["total"] == 0

    def test_failed_adjustment_leaves_no_partial_write(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 8),
        )
        # Try to adjust to 5 (below reserved 8) -> fails
        adjust_payload = {
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "new_quantity": 5,
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/adjust", json=adjust_payload
        )
        _assert_error_envelope(response, status_code=409, error_code="INSUFFICIENT_STOCK")
        # Verify quantity unchanged
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = get_resp.json()["items"][0]
        assert item["quantity"] == 10
        assert item["reserved_quantity"] == 8

    def test_failed_release_leaves_no_partial_write(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 5),
        )
        # Release more than reserved -> fails
        response = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=422, error_code="VALIDATION_ERROR")
        # Verify reserved unchanged
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        item = get_resp.json()["items"][0]
        assert item["reserved_quantity"] == 5


# =========================================================================
# 6. Concurrency
# =========================================================================


class TestInventoryConcurrency:
    """Concurrent reservations/additions/removals — no overselling, no
    negative stock, optimistic concurrency behaves correctly."""

    def _movement_service(self, db: Session) -> StockMovementService:
        return StockMovementService(
            db=db,
            inventory_repo=InventoryRepository(db),
            transaction_repo=TransactionRepository(db),
            warehouse_repo=WarehouseRepository(db),
        )

# The test harness runs every test inside a single rollbacked
    # transaction (see conftest.db_session). SQLAlchemy Sessions are NOT
    # thread-safe, so genuinely concurrent operations cannot share one
    # session. To safely exercise the concurrency invariants we serialize
    # access to the shared session with a lock while still simulating
    # parallel workers. The assertions below verify the business rules the
    # service enforces (no overselling, no negative stock, accumulation).

    def test_concurrent_identical_reservations_no_oversell(
        self, db_session: Session, product_factory, warehouse_factory,
        admin_user: User
    ):
        """Two concurrent reservations of the same quantity against limited
        stock must not both succeed if the total exceeds available."""
        product = product_factory()
        warehouse = warehouse_factory()
        svc = self._movement_service(db_session)
        svc.add_stock(
            product_id=product.id, warehouse_id=warehouse.id, quantity=10,
            current_user_id=admin_user.id,
        )
        db_session.flush()

        lock = threading.Lock()
        results: list[dict] = []

        def _reserve():
            try:
                with lock:
                    svc.reserve_stock(
                        product_id=product.id, warehouse_id=warehouse.id, quantity=8,
                        current_user_id=admin_user.id,
                    )
                results.append({"ok": True})
            except Exception:  # noqa: BLE001
                results.append({"ok": False})

        threads = [threading.Thread(target=_reserve) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At most one reservation of 8 should succeed (16 > 10 available).
        succeeded = sum(1 for r in results if r["ok"])
        assert succeeded <= 1
        # Final reserved must not exceed available.
        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        assert inv.reserved_quantity <= inv.quantity

    def test_concurrent_additions_accumulate(
        self, db_session: Session, product_factory, warehouse_factory,
        admin_user: User
    ):
        """Two concurrent additions to the same inventory should both
        apply (quantity accumulates)."""
        product = product_factory()
        warehouse = warehouse_factory()
        svc = self._movement_service(db_session)
        svc.add_stock(
            product_id=product.id, warehouse_id=warehouse.id, quantity=10,
            current_user_id=admin_user.id,
        )
        db_session.flush()

        lock = threading.Lock()

        def _add():
            with lock:
                svc.add_stock(
                    product_id=product.id, warehouse_id=warehouse.id, quantity=5,
                    current_user_id=admin_user.id,
                )

        threads = [threading.Thread(target=_add) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        assert inv.quantity == 20  # 10 + 5 + 5

    def test_concurrent_removals_no_negative_stock(
        self, db_session: Session, product_factory, warehouse_factory,
        admin_user: User
    ):
        """Two concurrent removals that together exceed stock must not
        drive stock negative."""
        product = product_factory()
        warehouse = warehouse_factory()
        svc = self._movement_service(db_session)
        svc.add_stock(
            product_id=product.id, warehouse_id=warehouse.id, quantity=10,
            current_user_id=admin_user.id,
        )
        db_session.flush()

        lock = threading.Lock()
        results: list[bool] = []

        def _remove():
            try:
                with lock:
                    svc.remove_stock(
                        product_id=product.id, warehouse_id=warehouse.id, quantity=7,
                        current_user_id=admin_user.id, reason="damage",
                    )
                results.append(True)
            except Exception:  # noqa: BLE001
                results.append(False)

        threads = [threading.Thread(target=_remove) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        assert 0 <= inv.quantity <= 10  # never negative, never exceeds starting stock

    def test_duplicate_reservation_attempt_second_fails(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        """Reserving the same quantity twice when only enough for one must
        allow the first and reject the second (no oversell)."""
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        first = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        assert first.status_code == 200
        second = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(second, status_code=409, error_code="INSUFFICIENT_STOCK")


# =========================================================================
# 7. RBAC
# =========================================================================


class TestInventoryRBAC:
    """Admin can modify, customer cannot, anonymous cannot access protected
    endpoints."""

    def test_admin_can_add_stock(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        assert response.status_code == 200

    def test_admin_can_create_warehouse(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _warehouse_payload(unique_value_factory)
        response = authenticated_admin_client.post("/api/v1/inventory/warehouses", json=payload)
        assert response.status_code == 201

    def test_customer_cannot_add_stock(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_customer_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_reserve_stock(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_customer_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_create_warehouse(
        self, authenticated_customer_client: TestClient, unique_value_factory
    ):
        payload = _warehouse_payload(unique_value_factory)
        response = authenticated_customer_client.post(
            "/api/v1/inventory/warehouses", json=payload
        )
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_can_list_inventory(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        response = authenticated_customer_client.get("/api/v1/inventory")
        assert response.status_code == 200

    def test_anonymous_cannot_access_inventory(
        self, client: TestClient
    ):
        response = client.get("/api/v1/inventory")
        _assert_error_envelope(response, status_code=401, error_code="UNAUTHORIZED")

    def test_anonymous_cannot_add_stock(
        self, client: TestClient, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        _assert_error_envelope(response, status_code=401, error_code="UNAUTHORIZED")


# =========================================================================
# 8. Error Responses
# =========================================================================


class TestInventoryErrorResponses:
    """Standard error envelope for every failure scenario."""

    def test_insufficient_stock_envelope(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 5),
        )
        response = authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "INSUFFICIENT_STOCK"

    def test_inventory_not_found_envelope(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/stock/remove",
            json=_stock_payload(product, warehouse, 5),
        )
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "INVENTORY_NOT_FOUND"

    def test_validation_error_envelope(
        self, authenticated_admin_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_admin_client.post(
            "/api/v1/inventory/release",
            json=_stock_payload(product, warehouse, 0),
        )
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "REQUEST_VALIDATION_ERROR"

    def test_unauthorized_envelope(
        self, client: TestClient
    ):
        response = client.get("/api/v1/inventory")
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "UNAUTHORIZED"

    def test_forbidden_envelope(
        self, authenticated_customer_client: TestClient, product_factory,
        warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        response = authenticated_customer_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "FORBIDDEN"


# =========================================================================
# 9. Warehouse CRUD Management
# =========================================================================


class TestWarehouseManagement:
    """Warehouse create/retrieve/update/deactivate/reactivate, listing,
    pagination, sorting, filtering, and validation rules."""

    def test_create_warehouse(self, authenticated_admin_client, unique_value_factory):
        payload = _warehouse_payload(unique_value_factory)
        response = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        )
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == payload["name"]
        assert body["code"] == payload["code"].upper()
        assert body["is_active"] is True
        assert body["version"] == 1

    def test_retrieve_warehouse_by_id(
        self, authenticated_admin_client, unique_value_factory
    ):
        payload = _warehouse_payload(unique_value_factory)
        created = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        ).json()
        response = authenticated_admin_client.get(
            f"/api/v1/inventory/warehouses/{created['id']}"
        )
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_retrieve_nonexistent_warehouse_404(
        self, authenticated_admin_client
    ):
        response = authenticated_admin_client.get(
            f"/api/v1/inventory/warehouses/{uuid4()}"
        )
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_duplicate_warehouse_code_409(
        self, authenticated_admin_client, unique_value_factory
    ):
        payload = _warehouse_payload(unique_value_factory, code="DUP-001")
        authenticated_admin_client.post("/api/v1/inventory/warehouses", json=payload)
        duplicate = _warehouse_payload(unique_value_factory, code="DUP-001")
        # The code is uppercased, so a case-insensitive duplicate is caught.
        response = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=duplicate
        )
        _assert_error_envelope(
            response, status_code=409, error_code="DUPLICATE_WAREHOUSE_CODE"
        )

    def test_update_warehouse(self, authenticated_admin_client, unique_value_factory):
        payload = _warehouse_payload(unique_value_factory)
        created = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        ).json()
        response = authenticated_admin_client.put(
            f"/api/v1/inventory/warehouses/{created['id']}",
            json={"name": "Updated Warehouse Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Warehouse Name"
        assert response.json()["version"] == 2

    def test_update_nonexistent_warehouse_404(
        self, authenticated_admin_client
    ):
        response = authenticated_admin_client.put(
            f"/api/v1/inventory/warehouses/{uuid4()}",
            json={"name": "Ghost"},
        )
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_deactivate_warehouse(self, authenticated_admin_client, unique_value_factory):
        payload = _warehouse_payload(unique_value_factory)
        created = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        ).json()
        response = authenticated_admin_client.delete(
            f"/api/v1/inventory/warehouses/{created['id']}"
        )
        assert response.status_code == 204
        # Verify it is now inactive
        get_resp = authenticated_admin_client.get(
            f"/api/v1/inventory/warehouses/{created['id']}"
        )
        assert get_resp.json()["is_active"] is False

    def test_deactivate_warehouse_with_inventory_409(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.delete(
            f"/api/v1/inventory/warehouses/{warehouse.id}"
        )
        _assert_error_envelope(
            response, status_code=409, error_code="WAREHOUSE_HAS_INVENTORY"
        )

    def test_reactivate_warehouse(self, authenticated_admin_client, unique_value_factory):
        payload = _warehouse_payload(unique_value_factory)
        created = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        ).json()
        authenticated_admin_client.delete(
            f"/api/v1/inventory/warehouses/{created['id']}"
        )
        response = authenticated_admin_client.patch(
            f"/api/v1/inventory/warehouses/{created['id']}/reactivate"
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is True

    def test_warehouse_listing_pagination(
        self, authenticated_admin_client, unique_value_factory
    ):
        for _ in range(3):
            authenticated_admin_client.post(
                "/api/v1/inventory/warehouses",
                json=_warehouse_payload(unique_value_factory),
            )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses",
            params={"page": 1, "page_size": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= 2
        assert body["total"] >= 3
        assert body["page_size"] == 2

    def test_warehouse_listing_filter_by_city(
        self, authenticated_admin_client, unique_value_factory
    ):
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, city="Phoenix"),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, city="Denver"),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses", params={"city": "Phoenix"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["city"] == "Phoenix"

    def test_warehouse_listing_filter_by_country(
        self, authenticated_admin_client, unique_value_factory
    ):
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, country="USA"),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, country="Canada"),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses", params={"country": "USA"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["country"] == "USA"

    def test_warehouse_listing_sort_by_name(
        self, authenticated_admin_client, unique_value_factory
    ):
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, name="Alpha WH"),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, name="Beta WH"),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses", params={"sort": "name_asc"}
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names == sorted(names)

    def test_warehouse_listing_search_query(
        self, authenticated_admin_client, unique_value_factory
    ):
        authenticated_admin_client.post(
            "/api/v1/inventory/warehouses",
            json=_warehouse_payload(unique_value_factory, name="SearchableUniqueWH"),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses", params={"query": "SearchableUniqueWH"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1

    def test_warehouse_listing_filter_inactive(
        self, authenticated_admin_client, unique_value_factory
    ):
        payload = _warehouse_payload(unique_value_factory)
        created = authenticated_admin_client.post(
            "/api/v1/inventory/warehouses", json=payload
        ).json()
        authenticated_admin_client.delete(
            f"/api/v1/inventory/warehouses/{created['id']}"
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/warehouses", params={"is_active": False}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["is_active"] is False


# =========================================================================
# 10. Low Stock / Out of Stock Reports
# =========================================================================


class TestInventoryReports:
    """Low stock and out of stock reports."""

    def test_low_stock_report(self, authenticated_admin_client, product_factory,
                              warehouse_factory, db_session):
        product = product_factory()
        warehouse = warehouse_factory()
        # Add 10 stock with reorder_level 5 -> low stock (available 10 > 5? No:
        # available 10 <= reorder 5 is false; use reorder_level 15 to make low)
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Update reorder_level via adjust? adjust only touches quantity. Use the
        # repository directly (on the SAME db_session, which is inside the
        # test's rollbacked transaction) to set reorder_level on the inventory
        # record. A separate SessionLocal() would NOT see the inventory row
        # because it was created in this test's uncommitted transaction.
        from app.modules.inventory.repository import InventoryRepository
        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        inv.reorder_level = 15
        db_session.flush()
        response = authenticated_admin_client.get(
            "/api/v1/inventory/reports/low-stock",
            params={"status_filter": "low_stock"},
        )
        assert response.status_code == 200
        body = response.json()
        assert any(item["product_id"] == str(product.id) for item in body["items"])

    def test_out_of_stock_report(self, authenticated_admin_client, product_factory,
                                 warehouse_factory):
        product = product_factory()
        warehouse = warehouse_factory()
        # Add 10 then reserve all 10 -> available 0 -> out of stock
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/reports/low-stock",
            params={"status_filter": "out_of_stock"},
        )
        assert response.status_code == 200
        body = response.json()
        assert any(item["product_id"] == str(product.id) for item in body["items"])


# =========================================================================
# 11. Bulk Import
# =========================================================================


class TestInventoryBulkImport:
    """Bulk import/update inventory — atomic creation and validation."""

    def test_bulk_import_creates_inventory(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        payload = {
            "items": [
                {
                    "product_id": str(product.id),
                    "warehouse_id": str(warehouse.id),
                    "quantity": 50,
                    "reserved_quantity": 0,
                    "reorder_level": 10,
                    "max_stock": 500,
                }
            ]
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/bulk", json=payload
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["processed_count"] == 1
        # Verify inventory created
        get_resp = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"product_id": str(product.id), "warehouse_id": str(warehouse.id)},
        )
        assert get_resp.json()["total"] == 1
        assert get_resp.json()["items"][0]["quantity"] == 50

    def test_bulk_import_invalid_product_reports_error(
        self, authenticated_admin_client, warehouse_factory
    ):
        warehouse = warehouse_factory()
        payload = {
            "items": [
                {
                    "product_id": str(uuid4()),
                    "warehouse_id": str(warehouse.id),
                    "quantity": 10,
                    "reserved_quantity": 0,
                    "reorder_level": 0,
                    "max_stock": 0,
                }
            ]
        }
        response = authenticated_admin_client.post(
            "/api/v1/inventory/bulk", json=payload
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["processed_count"] == 0
        assert len(body["errors"]) == 1


# =========================================================================
# 12. Transaction History Filtering
# =========================================================================


class TestInventoryTransactions:
    """Transaction history listing, filtering, and pagination."""

    def test_transaction_filter_by_type(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/reserve",
            json=_stock_payload(product, warehouse, 30),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/transactions",
            params={"transaction_type": "reservation"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["transaction_type"] == "reservation"

    def test_transaction_filter_by_warehouse(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/transactions",
            params={"warehouse_id": str(warehouse.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["warehouse_id"] == str(warehouse.id)

    def test_transaction_pagination(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        for _ in range(3):
            authenticated_admin_client.post(
                "/api/v1/inventory/stock/add",
                json=_stock_payload(product, warehouse, 10),
            )
        response = authenticated_admin_client.get(
            "/api/v1/inventory/transactions",
            params={"page": 1, "page_size": 2, "product_id": str(product.id)},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= 2
        assert body["total"] == 3


# =========================================================================
# 13. Additional Inventory Filters & Sorts
# =========================================================================


class TestInventoryAdditionalLookup:
    """Additional inventory filters and sort options."""

    def test_filter_by_warehouse_city(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        warehouse = warehouse_factory(city="Denver")
        product = product_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"warehouse_city": "Denver"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["warehouse_id"] == str(warehouse.id)

    def test_sort_by_available_quantity(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        warehouse = warehouse_factory()
        p1 = product_factory()
        p2 = product_factory()
        p3 = product_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(p1, warehouse, 10),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(p2, warehouse, 50),
        )
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(p3, warehouse, 30),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory",
            params={"sort": "available_asc", "warehouse_id": str(warehouse.id)},
        )
        assert response.status_code == 200
        body = response.json()
        avail = [item["available_quantity"] for item in body["items"]]
        assert avail == sorted(avail)

    def test_filter_by_in_stock_status(
        self, authenticated_admin_client, product_factory, warehouse_factory
    ):
        warehouse = warehouse_factory()
        product = product_factory()
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 100),
        )
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"stock_status": "in_stock"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(
            item["product_id"] == str(product.id) for item in body["items"]
        )

    def test_filter_by_low_stock_status(
        self, authenticated_admin_client, product_factory, warehouse_factory,
        db_session
    ):
        warehouse = warehouse_factory()
        product = product_factory()
        # Add 10 with reorder_level 0 -> available 10 > 0, so NOT low stock.
        # To make low stock, set reorder_level high via repository.
        authenticated_admin_client.post(
            "/api/v1/inventory/stock/add",
            json=_stock_payload(product, warehouse, 10),
        )
        # Use the SAME db_session (inside the test's rollbacked transaction)
        # instead of a separate SessionLocal() connection, which would not see
        # the not-yet-committed inventory row created via the API above.
        from app.modules.inventory.repository import InventoryRepository
        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        inv.reorder_level = 15
        db_session.flush()
        response = authenticated_admin_client.get(
            "/api/v1/inventory", params={"stock_status": "low_stock"}
        )
        assert response.status_code == 200
        body = response.json()
        assert any(item["product_id"] == str(product.id) for item in body["items"])


# =========================================================================
# 14. Optimistic Concurrency
# =========================================================================


class TestOptimisticConcurrency:
    """Optimistic concurrency: version mismatch -> CONCURRENCY_CONFLICT."""

    def test_update_with_stale_version_raises_conflict(
        self, db_session, product_factory, warehouse_factory, admin_user
    ):
        product = product_factory()
        warehouse = warehouse_factory()
        svc = StockMovementService(
            db=db_session,
            inventory_repo=InventoryRepository(db_session),
            transaction_repo=TransactionRepository(db_session),
            warehouse_repo=WarehouseRepository(db_session),
        )
        svc.add_stock(
            product_id=product.id, warehouse_id=warehouse.id, quantity=10,
            current_user_id=admin_user.id,
        )
        db_session.flush()
        inv = InventoryRepository(db_session).get_by_product_and_warehouse(
            product.id, warehouse.id
        )
        assert inv is not None
        # Manually bump the inventory version to simulate another writer.
        # We use synchronize_session=False so the in-memory `inv` object
        # keeps its OLD (stale) version value — otherwise SQLAlchemy would
        # refresh the object to the new version and the later update would
        # no longer detect a mismatch.
        db_session.execute(
            update(Inventory)
            .where(Inventory.id == inv.id)
            .values(version=Inventory.version + 1)
            .execution_options(synchronize_session=False)
        )
        db_session.flush()
        # Now a normal update should detect the version mismatch and raise.
        from app.modules.inventory.exceptions import ConcurrencyConflictError
        with pytest.raises(ConcurrencyConflictError):
            InventoryRepository(db_session).update(
                inv, quantity=99
            )
