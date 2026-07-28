"""create inventory module: warehouses, inventory, transactions

Revision ID: e7a8b9c0d1e2
Revises: 95f59149cdee
Create Date: 2026-07-30 10:30:00.000000+00:00

This migration:
1. Creates the `warehouses` table (soft-delete, with unique code).
2. Creates the `inventory` table (single source of truth for stock).
3. Creates the `inventory_transactions` table (immutable audit log).
4. Removes `stock_quantity` and `reserved_quantity` columns from
   `products` (inventory is now managed by the inventory module).
5. Removes CHECK constraints related to the removed stock columns.
6. Adds the `inventory_manager` value to the `user_role` enum.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import quoted_name

# revision identifiers, used by Alembic.
revision: str = 'e7a8b9c0d1e2'
down_revision: Union[str, None] = '95f59149cdee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Create warehouses table -------------------------------------------
    op.create_table('warehouses',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('postal_code', sa.String(length=20), nullable=True),
        sa.Column('contact_number', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_warehouses')),
        sa.UniqueConstraint('code', name=op.f('uq_warehouses_code')),
    )
    op.create_index(op.f('ix_warehouses_name'), 'warehouses', ['name'], unique=False)
    op.create_index(op.f('ix_warehouses_code'), 'warehouses', ['code'], unique=True)
    op.create_index(op.f('ix_warehouses_city'), 'warehouses', ['city'], unique=False)
    op.create_index(op.f('ix_warehouses_is_active'), 'warehouses', ['is_active'], unique=False)

    # --- 2. Create inventory table -------------------------------------------
    op.create_table('inventory',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('warehouse_id', sa.Uuid(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('reserved_quantity', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('reorder_level', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_stock', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('last_stock_update', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity >= 0', name=op.f('ck_inventory_quantity_non_negative')),
        sa.CheckConstraint('reserved_quantity >= 0', name=op.f('ck_inventory_reserved_non_negative')),
        sa.CheckConstraint('reserved_quantity <= quantity', name=op.f('ck_inventory_reserved_within_quantity')),
        sa.CheckConstraint('reorder_level >= 0', name=op.f('ck_inventory_reorder_level_non_negative')),
        sa.CheckConstraint('max_stock >= 0', name=op.f('ck_inventory_max_stock_non_negative')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'],
            name=op.f('fk_inventory_product_id_products'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'],
            name=op.f('fk_inventory_warehouse_id_warehouses'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory')),
        sa.UniqueConstraint('product_id', 'warehouse_id',
            name=op.f('uq_inventory_product_warehouse')),
    )
    op.create_index(op.f('ix_inventory_product_id'), 'inventory', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_warehouse_id'), 'inventory', ['warehouse_id'], unique=False)

    # --- 3. Create inventory_transactions table -------------------------------
    op.create_table('inventory_transactions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('warehouse_id', sa.Uuid(), nullable=False),
        sa.Column('transaction_type',
            sa.Enum('purchase', 'sale', 'return', 'adjustment',
                    'transfer_in', 'transfer_out', 'damage', 'expired',
                    'reservation', 'release', 'confirm_reservation',
                    name='inventory_transaction_type'),
            nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('previous_quantity', sa.Integer(), nullable=False),
        sa.Column('new_quantity', sa.Integer(), nullable=False),
        sa.Column('previous_reserved_quantity', sa.Integer(), nullable=False),
        sa.Column('new_reserved_quantity', sa.Integer(), nullable=False),
        sa.Column('reference_number', sa.String(length=255), nullable=True),
        sa.Column('correlation_id', sa.String(length=64), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('quantity >= 0', name=op.f('ck_inventory_transactions_quantity_non_negative')),
        sa.CheckConstraint('previous_quantity >= 0', name=op.f('ck_inventory_transactions_prev_qty_non_negative')),
        sa.CheckConstraint('new_quantity >= 0', name=op.f('ck_inventory_transactions_new_qty_non_negative')),
        sa.CheckConstraint('previous_reserved_quantity >= 0', name=op.f('ck_inventory_transactions_prev_reserved_non_negative')),
        sa.CheckConstraint('new_reserved_quantity >= 0', name=op.f('ck_inventory_transactions_new_reserved_non_negative')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'],
            name=op.f('fk_inventory_transactions_product_id_products')),
        sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'],
            name=op.f('fk_inventory_transactions_warehouse_id_warehouses')),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
            name=op.f('fk_inventory_transactions_created_by_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_transactions')),
    )
    op.create_index(op.f('ix_inventory_transactions_product_id'),
                     'inventory_transactions', ['product_id'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_warehouse_id'),
                     'inventory_transactions', ['warehouse_id'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_transaction_type'),
                     'inventory_transactions', ['transaction_type'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_created_at'),
                     'inventory_transactions', ['created_at'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_reference_number'),
                     'inventory_transactions', ['reference_number'], unique=False)
    op.create_index(op.f('ix_inventory_transactions_correlation_id'),
                     'inventory_transactions', ['correlation_id'], unique=False)

    # --- 4. Remove stock columns from products --------------------------------
    # Drop CHECK constraints that reference the removed columns first.

    op.execute("""
    ALTER TABLE products
    DROP CONSTRAINT IF EXISTS ck_products_stock_non_negative;
    """)

    op.execute("""
    ALTER TABLE products
    DROP CONSTRAINT IF EXISTS ck_products_reserved_within_stock;
    """)

    # Drop the columns.c
    op.drop_column('products', 'stock_quantity')
    op.drop_column('products', 'reserved_quantity')

    # --- 5. Add inventory_manager to user_role enum ---------------------------
    # PostgreSQL ALTER TYPE ... ADD VALUE cannot run inside a transaction block
    # in older PostgreSQL versions. We use a raw execute to handle this.
    op.execute("ALTER TYPE user_role ADD VALUE 'inventory_manager'")


def downgrade() -> None:
    # --- 1. Restore stock columns on products ---------------------------------
    op.add_column('products',
        sa.Column('stock_quantity', sa.Integer(), nullable=False, server_default=sa.text('0'))
    )
    op.add_column('products',
        sa.Column('reserved_quantity', sa.Integer(), nullable=False, server_default=sa.text('0'))
    )

    # Re-add CHECK constraints.
    op.create_check_constraint(
        'ck_products_stock_non_negative',
        'products',
        sa.text('stock_quantity >= 0'),
    )
    op.create_check_constraint(
        'ck_products_reserved_within_stock',
        'products',
        sa.text('reserved_quantity >= 0 AND reserved_quantity <= stock_quantity'),
    )

    # --- 2. Drop inventory_transactions table ---------------------------------
    op.drop_index(op.f('ix_inventory_transactions_correlation_id'),
                   table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_reference_number'),
                   table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_created_at'),
                   table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_transaction_type'),
                   table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_warehouse_id'),
                   table_name='inventory_transactions')
    op.drop_index(op.f('ix_inventory_transactions_product_id'),
                   table_name='inventory_transactions')
    op.drop_table('inventory_transactions')
    op.execute('DROP TYPE IF EXISTS inventory_transaction_type')

    # --- 3. Drop inventory table ----------------------------------------------
    op.drop_index(op.f('ix_inventory_warehouse_id'), table_name='inventory')
    op.drop_index(op.f('ix_inventory_product_id'), table_name='inventory')
    op.drop_table('inventory')

    # --- 4. Drop warehouses table ---------------------------------------------
    op.drop_index(op.f('ix_warehouses_is_active'), table_name='warehouses')
    op.drop_index(op.f('ix_warehouses_city'), table_name='warehouses')
    op.drop_index(op.f('ix_warehouses_code'), table_name='warehouses')
    op.drop_index(op.f('ix_warehouses_name'), table_name='warehouses')
    op.drop_table('warehouses')

    # --- 5. Remove inventory_manager from user_role enum ----------------------
    # Note: PostgreSQL does not support removing values from enums directly.
    # A full enum recreation would be needed in production. This is a best-effort
    # downgrade for development purposes.
    # We leave the enum value in place since removing it is complex.
    pass

