"""
tests/conftest.py

Shared test infrastructure for integration tests:
- forces the test environment file before app imports,
- applies migrations against the dedicated test database,
- wraps each test in a rollbacked transaction,
- uses a dedicated Redis logical DB and flushes it per test,
- injects both dependencies into the FastAPI app under test.
"""

import os
from pathlib import Path
from decimal import Decimal
from itertools import count
from typing import Any, Callable, Generator
from uuid import uuid4

import pytest
import redis
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

# Must be set before importing app modules that read settings at import time.
os.environ["COMMERCEOS_ENV_FILE"] = ".env.test"

from app.core.security import hash_password
from app.core.config import get_settings
from app.db.redis_client import get_redis
from app.db.session import SessionLocal, engine, get_db
from app.main import create_app
from app.models.product import Product, ProductStatus
from app.models.user import User, UserRole
from app.modules.inventory.models import Inventory, Warehouse
from app.modules.orders.constants import OrderStatus, PaymentStatus
from app.modules.orders.models import Order, OrderItem

DEFAULT_TEST_PASSWORD = "Str0ng!Pass1"


@pytest.fixture(scope="session", autouse=True)
def _validate_test_environment() -> None:
    settings = get_settings()
    if settings.ENVIRONMENT != "test":
        raise RuntimeError(
            "Pytest must run with ENVIRONMENT=test. "
            "Check COMMERCEOS_ENV_FILE and .env.test."
        )
    database_name = make_url(settings.DATABASE_URL).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            f"Refusing to run tests against non-test database '{database_name}'."
        )
    if "CHANGE_ME" in settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL in .env.test still contains placeholder credentials. "
            "Update .env.test with real test-database credentials."
        )


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_database(_validate_test_environment: None) -> None:
    project_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(project_root / "alembic.ini"))
    command.upgrade(alembic_config, "head")


@pytest.fixture(scope="session", autouse=True)
def _clean_test_database(_migrate_test_database: None) -> None:
    with engine.begin() as connection:
        table_names = connection.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public' AND tablename != 'alembic_version'
                """
            )
        ).scalars().all()
        if table_names:
            quoted = ", ".join(f'"{table}"' for table in table_names)
            connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = SessionLocal(bind=connection)

    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess: Session, transaction: Any) -> None:
        if transaction.nested and transaction.parent is not None and not transaction.parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", _restart_savepoint)
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture
def redis_client() -> Generator[redis.Redis, None, None]:
    client = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture
def client_factory(
    db_session: Session, redis_client: redis.Redis
) -> Generator[Callable[..., TestClient], None, None]:
    clients: list[tuple[TestClient, Any]] = []

    def _create(*, access_token: str | None = None) -> TestClient:
        app = create_app()

        def override_get_db() -> Generator[Session, None, None]:
            yield db_session

        def override_get_redis() -> Generator[redis.Redis, None, None]:
            yield redis_client

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_redis] = override_get_redis

        test_client = TestClient(app)
        if access_token:
            test_client.headers.update({"Authorization": f"Bearer {access_token}"})

        clients.append((test_client, app))
        return test_client

    yield _create

    for test_client, app in clients:
        test_client.close()
        app.dependency_overrides.clear()


@pytest.fixture
def client(client_factory: Callable[..., TestClient]) -> TestClient:
    return client_factory()


@pytest.fixture
def unique_value_factory() -> Callable[[str], str]:
    sequence = count(1)

    def _create(prefix: str) -> str:
        return f"{prefix}-{next(sequence)}-{uuid4().hex[:8]}"

    return _create


@pytest.fixture
def user_factory(
    db_session: Session, unique_value_factory: Callable[[str], str]
) -> Callable[..., User]:
    def _create(
        *,
        role: UserRole = UserRole.CUSTOMER,
        password: str = DEFAULT_TEST_PASSWORD,
        **overrides: Any,
    ) -> User:
        idx = unique_value_factory("user")
        defaults = {
            "email": f"{idx}@example.com",
            "username": idx.replace("-", "_"),
            "hashed_password": hash_password(password),
            "first_name": "Test",
            "last_name": "User",
            "phone": "+10000000000",
            "is_active": True,
            "is_verified": True,
            "role": role,
        }
        defaults.update(overrides)
        user = User(**defaults)
        db_session.add(user)
        db_session.flush()
        return user

    return _create


@pytest.fixture
def admin_user(user_factory: Callable[..., User]) -> User:
    return user_factory(role=UserRole.ADMIN)


@pytest.fixture
def customer_user(user_factory: Callable[..., User]) -> User:
    return user_factory(role=UserRole.CUSTOMER)


@pytest.fixture
def access_token_factory(client: TestClient) -> Callable[[User, str], str]:
    def _create(user: User, password: str = DEFAULT_TEST_PASSWORD) -> str:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": user.email, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _create


@pytest.fixture
def admin_token(admin_user: User, access_token_factory: Callable[[User, str], str]) -> str:
    return access_token_factory(admin_user)


@pytest.fixture
def customer_token(
    customer_user: User, access_token_factory: Callable[[User, str], str]
) -> str:
    return access_token_factory(customer_user)


@pytest.fixture
def authenticated_admin_client(
    client_factory: Callable[..., TestClient], admin_token: str
) -> TestClient:
    return client_factory(access_token=admin_token)


@pytest.fixture
def authenticated_customer_client(
    client_factory: Callable[..., TestClient], customer_token: str
) -> TestClient:
    return client_factory(access_token=customer_token)


@pytest.fixture
def warehouse_factory(
    db_session: Session, unique_value_factory: Callable[[str], str]
) -> Callable[..., Warehouse]:
    def _create(**overrides: Any) -> Warehouse:
        idx = unique_value_factory("wh")
        defaults = {
            "name": f"Warehouse {idx}",
            "code": f"WH-{idx[-8:].upper()}",
            "city": "Test City",
            "country": "Test Country",
            "is_active": True,
        }
        defaults.update(overrides)
        warehouse = Warehouse(**defaults)
        db_session.add(warehouse)
        db_session.flush()
        return warehouse

    return _create


@pytest.fixture
def product_factory(
    db_session: Session,
    unique_value_factory: Callable[[str], str],
    admin_user: User,
) -> Callable[..., Product]:
    def _create(**overrides: Any) -> Product:
        idx = unique_value_factory("product")
        defaults = {
            "sku": f"SKU-{idx[-8:].upper()}",
            "slug": f"slug-{idx}",
            "name": f"Product {idx}",
            "description": "Fixture-generated product",
            "short_description": "Fixture product",
            "brand": "FixtureBrand",
            "category": "FixtureCategory",
            "price": Decimal("19.99"),
            "compare_at_price": Decimal("24.99"),
            "currency": "USD",
            "weight": Decimal("0.500"),
            "status": ProductStatus.ACTIVE,
            "is_featured": False,
            "track_inventory": True,
            "created_by": admin_user.id,
            "updated_by": admin_user.id,
        }
        defaults.update(overrides)
        product = Product(**defaults)
        db_session.add(product)
        db_session.flush()
        return product

    return _create


@pytest.fixture
def inventory_factory(
    db_session: Session,
    product_factory: Callable[..., Product],
    warehouse_factory: Callable[..., Warehouse],
) -> Callable[..., Inventory]:
    def _create(
        *,
        product: Product | None = None,
        warehouse: Warehouse | None = None,
        **overrides: Any,
    ) -> Inventory:
        product = product or product_factory()
        warehouse = warehouse or warehouse_factory()

        defaults = {
            "product_id": product.id,
            "warehouse_id": warehouse.id,
            "quantity": 100,
            "reserved_quantity": 0,
            "reorder_level": 10,
            "max_stock": 1000,
        }
        defaults.update(overrides)
        inventory = Inventory(**defaults)
        db_session.add(inventory)
        db_session.flush()
        return inventory

    return _create


@pytest.fixture
def order_factory(
    db_session: Session,
    unique_value_factory: Callable[[str], str],
    customer_user: User,
    admin_user: User,
    product_factory: Callable[..., Product],
    warehouse_factory: Callable[..., Warehouse],
) -> Callable[..., Order]:
    def _create(
        *,
        customer: User | None = None,
        created_by: User | None = None,
        product: Product | None = None,
        warehouse: Warehouse | None = None,
        include_item: bool = True,
        quantity: int = 1,
        **overrides: Any,
    ) -> Order:
        customer = customer or customer_user
        created_by = created_by or admin_user

        defaults = {
            "order_number": f"ORD-{unique_value_factory('order')[-12:].upper()}",
            "customer_id": customer.id,
            "status": OrderStatus.PENDING,
            "subtotal": Decimal("0.00"),
            "tax": Decimal("0.00"),
            "shipping_cost": Decimal("0.00"),
            "discount": Decimal("0.00"),
            "total": Decimal("0.00"),
            "payment_status": PaymentStatus.UNPAID,
            "notes": "Fixture-generated order",
            "created_by": created_by.id,
            "updated_by": created_by.id,
        }
        defaults.update(overrides)
        order = Order(**defaults)
        db_session.add(order)
        db_session.flush()

        if include_item:
            product = product or product_factory(created_by=created_by.id, updated_by=created_by.id)
            warehouse = warehouse or warehouse_factory()
            line_total = product.price * quantity
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                product_sku=product.sku,
                warehouse_id=warehouse.id,
                quantity=quantity,
                unit_price=product.price,
                line_total=line_total,
            )
            db_session.add(item)
            db_session.flush()

            order.subtotal = line_total
            order.total = line_total + order.tax + order.shipping_cost - order.discount
            db_session.flush()

        return order

    return _create
