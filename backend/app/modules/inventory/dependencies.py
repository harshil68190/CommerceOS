"""
modules/inventory/dependencies.py

Responsibility
--------------
FastAPI dependency providers for the inventory module, following the same
pattern as `modules/auth/service.py`'s `get_auth_service`.

Assembles fully-wired service instances for the router. The exact same
chain can be overridden wholesale in tests via
`app.dependency_overrides[get_inventory_service] = ...`.
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
from app.modules.inventory.warehouse_service import WarehouseService


# --- Repository providers ---------------------------------------------------


def get_warehouse_repository(db: Session = Depends(get_db)) -> WarehouseRepository:
    """FastAPI dependency: builds a `WarehouseRepository` bound to the
    current request's DB session."""
    return WarehouseRepository(db)


def get_inventory_repository(db: Session = Depends(get_db)) -> InventoryRepository:
    """FastAPI dependency: builds an `InventoryRepository` bound to the
    current request's DB session."""
    return InventoryRepository(db)


def get_transaction_repository(db: Session = Depends(get_db)) -> TransactionRepository:
    """FastAPI dependency: builds a `TransactionRepository` bound to the
    current request's DB session."""
    return TransactionRepository(db)


# --- Service providers ---------------------------------------------------


def get_warehouse_service(
    db: Session = Depends(get_db),
    warehouse_repo: WarehouseRepository = Depends(get_warehouse_repository),
    inventory_repo: InventoryRepository = Depends(get_inventory_repository),
) -> WarehouseService:
    """FastAPI dependency: builds a fully-wired `WarehouseService`."""
    return WarehouseService(
        db=db, warehouse_repo=warehouse_repo, inventory_repo=inventory_repo
    )


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

