"""
modules/intelligence/repository.py

Responsibility
--------------
Read-only data access for CommerceOS Intelligence. Two queries do all the
work, both against the existing tables (no new tables, no mock data):

1. `list_stock_positions`  - Inventory x Product x Warehouse
2. `get_daily_demand`      - order_items x orders, grouped by
                             product x warehouse x calendar day

Returns plain dataclasses (not ORM entities) so the service and the pure
engine stay free of SQLAlchemy. No business rules live here.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductStatus
from app.modules.intelligence.constants import VALID_DEMAND_STATUSES
from app.modules.inventory.models import Inventory, Warehouse
from app.modules.orders.models import Order, OrderItem

# Products that can still sell. DRAFT and ARCHIVED products are not part
# of the replenishment problem. OUT_OF_STOCK stays in: it is exactly the
# state intelligence should be flagging.
ANALYZED_PRODUCT_STATUSES = (ProductStatus.ACTIVE, ProductStatus.OUT_OF_STOCK)


@dataclass(frozen=True)
class StockPositionRow:
    """One Inventory row joined to its product and warehouse."""

    product_id: uuid.UUID
    product_name: str
    product_sku: str
    product_status: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_code: str
    quantity: int
    reserved_quantity: int
    reorder_level: int
    max_stock: int
    inventory_created: date | None


@dataclass(frozen=True)
class DailyDemandRow:
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    day: date
    quantity: int


class IntelligenceRepository:
    """Read-only queries feeding the intelligence service."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_product(self, product_id: uuid.UUID) -> Product | None:
        return self.db.get(Product, product_id)

    def list_stock_positions(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[StockPositionRow]:
        stmt = (
            select(
                Inventory.product_id,
                Product.name,
                Product.sku,
                Product.status,
                Inventory.warehouse_id,
                Warehouse.name,
                Warehouse.code,
                Inventory.quantity,
                Inventory.reserved_quantity,
                Inventory.reorder_level,
                Inventory.max_stock,
                Inventory.created_at,
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .where(
                Warehouse.is_active.is_(True),
                Product.track_inventory.is_(True),
                Product.status.in_(ANALYZED_PRODUCT_STATUSES),
            )
            .order_by(Product.name, Warehouse.code)
        )
        if product_id is not None:
            stmt = stmt.where(Inventory.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(Inventory.warehouse_id == warehouse_id)

        rows = self.db.execute(stmt).all()
        return [
            StockPositionRow(
                product_id=r[0],
                product_name=r[1],
                product_sku=r[2],
                product_status=r[3].value if hasattr(r[3], "value") else str(r[3]),
                warehouse_id=r[4],
                warehouse_name=r[5],
                warehouse_code=r[6],
                quantity=r[7],
                reserved_quantity=r[8],
                reorder_level=r[9],
                max_stock=r[10],
                inventory_created=r[11].date() if r[11] is not None else None,
            )
            for r in rows
        ]

    def get_daily_demand(
        self,
        *,
        start: date,
        end: date,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[DailyDemandRow]:
        """Units sold per product x warehouse x day for valid orders whose
        `created_at` falls on a calendar day in [start, end] inclusive."""
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        day_col = func.date(Order.created_at).label("day")

        stmt = (
            select(
                OrderItem.product_id,
                OrderItem.warehouse_id,
                day_col,
                func.sum(OrderItem.quantity).label("units"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.status.in_(VALID_DEMAND_STATUSES),
                Order.created_at >= start_dt,
                Order.created_at < end_dt,
            )
            .group_by(OrderItem.product_id, OrderItem.warehouse_id, day_col)
        )
        if product_id is not None:
            stmt = stmt.where(OrderItem.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(OrderItem.warehouse_id == warehouse_id)

        return [
            DailyDemandRow(
                product_id=r[0], warehouse_id=r[1], day=r[2], quantity=int(r[3])
            )
            for r in self.db.execute(stmt).all()
        ]
