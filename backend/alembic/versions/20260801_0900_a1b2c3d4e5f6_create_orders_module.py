"""create orders module: orders, order_items

Revision ID: a1b2c3d4e5f6
Revises: e7a8b9c0d1e2
Create Date: 2026-08-01 09:00:00.000000+00:00

This migration:
1. Creates the `orders` table (core order entity with audit fields).
2. Creates the `order_items` table (line items with product snapshots).
3. Creates the `order_status` enum type.
4. Creates the `payment_status` enum type.
5. Adds appropriate CHECK constraints, indexes, and foreign keys.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


order_status = postgresql.ENUM(
    "pending",
    "confirmed",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
    "refunded",
    name="order_status",
)

payment_status = postgresql.ENUM(
    "unpaid",
    "authorized",
    "paid",
    "failed",
    "refunded",
    name="payment_status",
)


def upgrade() -> None:
    # --- 1. Create orders table -----------------------------------------------
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            order_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "subtotal",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "tax", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0.00")
        ),
        sa.Column(
            "shipping_cost",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "discount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "total",
            sa.Numeric(12, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "payment_status",
            payment_status,
            nullable=False,
            server_default=sa.text("'unpaid'"),
        ),
        sa.Column("reserved_until", sa.DateTime(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subtotal >= 0", name=op.f("ck_orders_order_subtotal_non_negative")
        ),
        sa.CheckConstraint(
            "tax >= 0", name=op.f("ck_orders_order_tax_non_negative")
        ),
        sa.CheckConstraint(
            "shipping_cost >= 0",
            name=op.f("ck_orders_order_shipping_non_negative"),
        ),
        sa.CheckConstraint(
            "discount >= 0", name=op.f("ck_orders_order_discount_non_negative")
        ),
        sa.CheckConstraint(
            "total >= 0", name=op.f("ck_orders_order_total_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_orders_customer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_orders_created_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_orders_updated_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("order_number", name=op.f("uq_orders_order_number")),
    )
    op.create_index(
        op.f("ix_orders_order_number"), "orders", ["order_number"], unique=True
    )
    op.create_index(
        op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False
    )
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index(
        op.f("ix_orders_payment_status"),
        "orders",
        ["payment_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_orders_created_at"), "orders", ["created_at"], unique=False
    )

    # --- 2. Create order_items table -----------------------------------------
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("product_sku", sa.String(length=64), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_order_items_order_item_quantity_positive"),
        ),
        sa.CheckConstraint(
            "unit_price >= 0",
            name=op.f("ck_order_items_order_item_unit_price_non_negative"),
        ),
        sa.CheckConstraint(
            "line_total >= 0",
            name=op.f("ck_order_items_order_item_line_total_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_order_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_order_items_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
    )
    op.create_index(
        op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False
    )
    op.create_index(
        op.f("ix_order_items_product_id"),
        "order_items",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_items_warehouse_id"),
        "order_items",
        ["warehouse_id"],
        unique=False,
    )


def downgrade() -> None:
    # --- 1. Drop order_items table -------------------------------------------
    op.drop_index(
        op.f("ix_order_items_warehouse_id"), table_name="order_items"
    )
    op.drop_index(
        op.f("ix_order_items_product_id"), table_name="order_items"
    )
    op.drop_index(
        op.f("ix_order_items_order_id"), table_name="order_items"
    )
    op.drop_table("order_items")

    # --- 2. Drop orders table ------------------------------------------------
    op.drop_index(op.f("ix_orders_created_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_payment_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_order_number"), table_name="orders")
    op.drop_table("orders")

    # --- 3. Drop ENUM types --------------------------------------------------
    op.execute("DROP TYPE IF EXISTS payment_status")
    op.execute("DROP TYPE IF EXISTS order_status")
