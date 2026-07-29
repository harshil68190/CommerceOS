"""
modules/orders/dependencies.py

Responsibility
--------------
FastAPI dependency providers for the orders module, following the same
pattern as `modules/products/dependencies.py`.

Assembles fully-wired service instances for the router. The exact same
chain can be overridden wholesale in tests via
`app.dependency_overrides[get_order_service] = ...`.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.inventory.repository import (
    InventoryRepository,
    TransactionRepository,
    WarehouseRepository,
)
from app.modules.inventory.stock_movement_service import StockMovementService
from app.modules.orders.order_service import OrderService
from app.modules.orders.repository import OrderItemRepository, OrderRepository
from app.modules.products.repository import ProductRepository


# --- Repository providers ---------------------------------------------------


def get_order_repository(db: Session = Depends(get_db)) -> OrderRepository:
    """FastAPI dependency: builds an `OrderRepository` bound to the
    current request's DB session."""
    return OrderRepository(db)


def get_order_item_repository(db: Session = Depends(get_db)) -> OrderItemRepository:
    """FastAPI dependency: builds an `OrderItemRepository` bound to the
    current request's DB session."""
    return OrderItemRepository(db)


def get_product_repository(db: Session = Depends(get_db)) -> ProductRepository:
    """FastAPI dependency: builds a `ProductRepository` bound to the
    current request's DB session."""
    return ProductRepository(db)


def get_inventory_repository(db: Session = Depends(get_db)) -> InventoryRepository:
    """FastAPI dependency: builds an `InventoryRepository` bound to the
    current request's DB session."""
    return InventoryRepository(db)


def get_warehouse_repository(db: Session = Depends(get_db)) -> WarehouseRepository:
    """FastAPI dependency: builds a `WarehouseRepository` bound to the
    current request's DB session."""
    return WarehouseRepository(db)


def get_transaction_repository(db: Session = Depends(get_db)) -> TransactionRepository:
    """FastAPI dependency: builds a `TransactionRepository` bound to the
    current request's DB session."""
    return TransactionRepository(db)


# --- Service providers ---------------------------------------------------


def get_stock_movement_service(
    db: Session = Depends(get_db),
    inventory_repo: InventoryRepository = Depends(get_inventory_repository),
    transaction_repo: TransactionRepository = Depends(get_transaction_repository),
    warehouse_repo: WarehouseRepository = Depends(get_warehouse_repository),
) -> StockMovementService:
    """FastAPI dependency: builds a fully-wired `StockMovementService`."""
    return StockMovementService(
        db=db,
        inventory_repo=inventory_repo,
        transaction_repo=transaction_repo,
        warehouse_repo=warehouse_repo,
    )


def get_order_service(
    db: Session = Depends(get_db),
    order_repo: OrderRepository = Depends(get_order_repository),
    item_repo: OrderItemRepository = Depends(get_order_item_repository),
    product_repo: ProductRepository = Depends(get_product_repository),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
) -> OrderService:
    """FastAPI dependency: builds a fully-wired `OrderService` for the
    current request."""
    return OrderService(
        db=db,
        order_repo=order_repo,
        item_repo=item_repo,
        product_repo=product_repo,
        stock_service=stock_service,
    )
