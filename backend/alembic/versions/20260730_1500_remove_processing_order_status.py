"""remove the obsolete processing order status

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-30 15:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing in-flight orders take the closest remaining pre-shipment state.
    op.execute("UPDATE orders SET status = 'confirmed' WHERE status = 'processing'")
    op.execute("ALTER TYPE order_status RENAME TO order_status_old")
    op.execute(
        "CREATE TYPE order_status AS ENUM "
        "('pending', 'confirmed', 'shipped', 'delivered', 'cancelled', 'returned', 'refunded')"
    )
    # PostgreSQL cannot automatically cast an existing enum-typed default
    # when the column switches to the replacement enum type.
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE order_status "
        "USING status::text::order_status"
    )
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute("DROP TYPE order_status_old")


def downgrade() -> None:
    op.execute("ALTER TYPE order_status RENAME TO order_status_new")
    op.execute(
        "CREATE TYPE order_status AS ENUM "
        "('pending', 'confirmed', 'processing', 'shipped', 'delivered', 'cancelled', 'returned', 'refunded')"
    )
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE orders ALTER COLUMN status TYPE order_status "
        "USING status::text::order_status"
    )
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute("DROP TYPE order_status_new")
