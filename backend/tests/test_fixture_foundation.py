from fastapi.testclient import TestClient
from redis import Redis

from app.modules.inventory.models import Inventory
from app.modules.orders.models import Order


def test_authenticated_admin_client_returns_admin_profile(
    authenticated_admin_client: TestClient,
) -> None:
    response = authenticated_admin_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["is_active"] is True


def test_inventory_factory_creates_linked_inventory_record(
    inventory_factory,
) -> None:
    inventory: Inventory = inventory_factory(quantity=25, reserved_quantity=5)

    assert inventory.product_id is not None
    assert inventory.warehouse_id is not None
    assert inventory.quantity == 25
    assert inventory.reserved_quantity == 5
    assert inventory.available_quantity == 20


def test_order_factory_creates_order_with_snapshot_item(order_factory) -> None:
    order: Order = order_factory(quantity=3)

    assert order.order_number.startswith("ORD-")
    assert order.status.value == "pending"
    assert len(order.items) == 1
    assert order.items[0].quantity == 3
    assert order.items[0].line_total == order.subtotal


def test_transaction_rollback_isolation_first(user_factory) -> None:
    user = user_factory(
        email="rollback-check@example.com",
        username="rollback_check_user",
    )
    assert user.email == "rollback-check@example.com"


def test_transaction_rollback_isolation_second(user_factory) -> None:
    # This should pass because the previous test's inserted row was rolled back.
    user = user_factory(
        email="rollback-check@example.com",
        username="rollback_check_user",
    )
    assert user.username == "rollback_check_user"


def test_redis_cleanup_first(redis_client: Redis) -> None:
    redis_client.set("fixture-cleanup-key", "value")
    assert redis_client.get("fixture-cleanup-key") == "value"


def test_redis_cleanup_second(redis_client: Redis) -> None:
    # This should be empty because each test gets a freshly flushed Redis DB.
    assert redis_client.get("fixture-cleanup-key") is None
