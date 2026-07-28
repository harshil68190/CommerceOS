"""
modules/inventory/product_inventory_service.py

Responsibility
--------------
Dedicated service for querying aggregated inventory data for products.

This exists specifically to avoid coupling the Product model to
Inventory queries — Product remains a pure domain entity and does NOT
have @property methods that hit the database. Instead, this service
loads inventory aggregates efficiently using SQL aggregation (SUM, COUNT).

The Product module's service layer calls into this service when it needs
stock data, NOT the other way around (inventory does not depend on
product).

Solves the N+1 problem: a single query can return total_stock,
available_stock, and warehouse_count for one or many products without
loading individual Inventory rows.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.modules.inventory.models import Inventory, Warehouse
from app.modules.inventory.schemas import ProductStockSummary


class ProductInventoryService:
    """
    Provides aggregated inventory data for the Product module.

    Methods use SQL aggregation (SUM, COUNT, GROUP BY) to load
    inventory information efficiently, avoiding N+1 queries.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_product_stock_summary(self, product_id: uuid.UUID) -> ProductStockSummary:
        """
        Returns aggregated stock information for a single product
        across all warehouses.

        Uses a single aggregation query to compute total_stock,
        total_reserved, total_available, and warehouse_count.

        Also returns a per-warehouse breakdown for detailed views.
        """
        # Aggregate query.
        stmt = (
            select(
                func.coalesce(func.sum(Inventory.quantity), 0).label("total_stock"),
                func.coalesce(func.sum(Inventory.reserved_quantity), 0).label(
                    "total_reserved"
                ),
                func.count(Inventory.id).label("warehouse_count"),
            )
            .where(Inventory.product_id == product_id)
        )
        row = self.db.execute(stmt).one()
        total_stock = int(row.total_stock)
        total_reserved = int(row.total_reserved)
        total_available = total_stock - total_reserved
        warehouse_count = int(row.warehouse_count)

        # Per-warehouse breakdown (separate query to avoid complex joins
        # when not needed — callers that don't need breakdown can skip).
        warehouse_stmt = (
            select(
                Inventory.warehouse_id,
                Warehouse.name.label("warehouse_name"),
                Inventory.quantity,
                Inventory.reserved_quantity,
            )
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .where(Inventory.product_id == product_id)
        )
        warehouse_rows = self.db.execute(warehouse_stmt).all()
        warehouses = [
            {
                "warehouse_id": str(row.warehouse_id),
                "warehouse_name": row.warehouse_name,
                "quantity": row.quantity,
                "reserved": row.reserved_quantity,
                "available": row.quantity - row.reserved_quantity,
            }
            for row in warehouse_rows
        ]

        return ProductStockSummary(
            product_id=product_id,
            total_stock=total_stock,
            total_reserved=total_reserved,
            total_available=total_available,
            warehouse_count=warehouse_count,
            warehouses=warehouses,
        )

    def get_bulk_stock_summary(
        self, product_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, ProductStockSummary]:
        """
        Returns aggregated stock information for multiple products
        in a single query.

        Returns a dict keyed by product_id for easy lookup.
        """
        if not product_ids:
            return {}

        stmt = (
            select(
                Inventory.product_id,
                func.coalesce(func.sum(Inventory.quantity), 0).label("total_stock"),
                func.coalesce(func.sum(Inventory.reserved_quantity), 0).label(
                    "total_reserved"
                ),
                func.count(Inventory.id).label("warehouse_count"),
            )
            .where(Inventory.product_id.in_(product_ids))
            .group_by(Inventory.product_id)
        )
        rows = self.db.execute(stmt).all()

        result: dict[uuid.UUID, ProductStockSummary] = {}
        for row in rows:
            total_stock = int(row.total_stock)
            total_reserved = int(row.total_reserved)
            result[row.product_id] = ProductStockSummary(
                product_id=row.product_id,
                total_stock=total_stock,
                total_reserved=total_reserved,
                total_available=total_stock - total_reserved,
                warehouse_count=int(row.warehouse_count),
                warehouses=[],  # Callers needing breakdown call separately
            )

        # Fill zero summaries for products with no inventory.
        for pid in product_ids:
            if pid not in result:
                result[pid] = ProductStockSummary(
                    product_id=pid,
                    total_stock=0,
                    total_reserved=0,
                    total_available=0,
                    warehouse_count=0,
                    warehouses=[],
                )

        return result

    def check_product_out_of_stock(self, product_id: uuid.UUID) -> bool:
        """Returns True if the product has zero available stock across
        all warehouses."""
        summary = self.get_product_stock_summary(product_id)
        return summary.total_available <= 0

    def get_products_with_stock_status(
        self, status: str = "low_stock"
    ) -> list[dict[str, Any]]:
        """
        Returns all products with a given stock status across all
        warehouses.

        Status can be: 'low_stock', 'out_of_stock', 'in_stock'.

        This is used by the Product module to determine which products
        should have their auto-status set to OUT_OF_STOCK.
        """
        condition = None
        if status == "out_of_stock":
            condition = Inventory.quantity - Inventory.reserved_quantity <= 0
        elif status == "low_stock":
            condition = (
                (Inventory.quantity - Inventory.reserved_quantity > 0)
                & (
                    Inventory.quantity - Inventory.reserved_quantity
                    <= Inventory.reorder_level
                )
            )
        elif status == "in_stock":
            condition = (
                Inventory.quantity - Inventory.reserved_quantity
                > Inventory.reorder_level
            )

        if condition is None:
            return []

        stmt = (
            select(Product.id, Product.name, Product.sku, Product.status)
            .distinct()
            .join(Inventory, Product.id == Inventory.product_id)
            .where(condition)
        )
        rows = self.db.execute(stmt).all()
        return [
            {"id": row.id, "name": row.name, "sku": row.sku, "status": row.status.value}
            for row in rows
        ]

