"""
models/product.py

Responsibility
--------------
Defines the `Product` ORM model — the persisted catalog entry every
sellable item in CommerceOS is stored as — and the `ProductStatus` enum
that drives catalog visibility rules (draft/active/archived/out-of-stock).

Like `User` (see `models/user.py`), this is a pure persistence artifact:
uniqueness checks, price/stock validation, and status-transition rules
live in `modules/products/service.py`, not here. This file's only job is
describing what a product record looks like in the database — including
enforcing the handful of invariants that are cheap and correct to also
enforce at the database level as a final safety net (see the CHECK
constraints below).

Schema note (deliberate divergence from the original architecture doc):
the original CommerceOS architecture document modeled `category` and
`brand` as separate tables (`categories`, `brands`) with foreign keys.
This milestone's spec explicitly lists `category` and `brand` as plain
string fields directly on `Product`, so that's what's implemented here.
This keeps the milestone's literal field list intact; promoting these to
normalized reference tables (with a migration to backfill) is a natural,
separate follow-up once category/brand management needs its own CRUD.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductStatus(str, enum.Enum):
    """
    Catalog visibility/lifecycle states for a product.

    - DRAFT: being authored, not yet visible to customers.
    - ACTIVE: visible and purchasable in customer-facing listings.
    - OUT_OF_STOCK: visible in the sense of "exists", but NOT surfaced in
      customer listings per this milestone's business rule ("Only ACTIVE
      products appear in customer listing") — this status exists mainly
      so admins can distinguish "temporarily unavailable" from "actively
      selling" without treating it as a full archive. The service layer
      transitions a product into/out of this status automatically as
      available stock crosses zero (see `ProductService`).
    - ARCHIVED: permanently retired. Per this milestone's business rule,
      archived products cannot be modified again.

    Inherits from `str` for the same reason as `UserRole` in
    `models/user.py`: clean JSON serialization and simple equality
    comparisons against plain strings.
    """

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    OUT_OF_STOCK = "out_of_stock"


class Product(Base):
    """
    ORM model for a single catalog product.

    Notes on specific column choices:
    - `id` is a UUID, consistent with `User` and the architecture doc's
      decision to avoid sequential, enumerable public-facing IDs.
    - `sku` and `slug` each carry a unique index — the database
      constraint is the final source of truth against a race between two
      concurrent creations, even though the service layer also checks
      proactively (same defense-in-depth reasoning as `User.email`).
    - `price`/`compare_at_price` use `Numeric` (fixed-point), never
      `Float` — floating point cannot represent currency amounts exactly,
      and even small rounding drift is unacceptable for money.
    - Three CHECK constraints encode the cheapest, most fundamental
      invariants directly in the database schema, as a last line of
      defense beyond the service layer: price must be positive, stock
      can't go negative, and reserved stock can never exceed on-hand
      stock. A bug in application code (or a manual `UPDATE` run by an
      engineer during an incident) still cannot corrupt these invariants.
    - `created_by`/`updated_by` reference `users.id` without a
      `relationship()` back to `User` — a plain FK column is enough for
      this milestone's needs (attribution) and avoids adding any
      navigation property to the `User` model, which this milestone must
      not modify.
    """

    __tablename__ = "products"
    __table_args__ = (
        # Names passed here are the *unprefixed* constraint identifier —
        # `Base.metadata`'s naming convention (see `db/base.py`) already
        # applies the `ck_%(table_name)s_` prefix automatically. Passing
        # an already-prefixed name here would cause it to be prefixed
        # a second time (e.g. "ck_products_ck_products_price_positive"),
        # which is exactly the kind of naming inconsistency the shared
        # convention exists to prevent.
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("stock_quantity >= 0", name="stock_non_negative"),
        CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= stock_quantity",
            name="reserved_within_stock",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    brand: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), index=True, nullable=False)
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    stock_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(default=0, nullable=False)

    weight: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)

    status: Mapped[ProductStatus] = mapped_column(
        SAEnum(
            ProductStatus,
            name="product_status",
            native_enum=True,
            # Same reasoning as `User.role` in models/user.py: store the
            # enum's lowercase *value* in the database, not its uppercase
            # *member name*, so the raw DB representation matches what
            # the API/JSON responses use everywhere else.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ProductStatus.DRAFT,
        index=True,
        nullable=False,
    )

    is_featured: Mapped[bool] = mapped_column(default=False, nullable=False)
    track_inventory: Mapped[bool] = mapped_column(default=True, nullable=False)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_products_created_by_users"), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", name="fk_products_updated_by_users"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def available_quantity(self) -> int:
        """Stock actually available to sell right now (on-hand minus
        already-reserved). Exposed as a computed property rather than a
        stored column so it can never drift out of sync with
        `stock_quantity`/`reserved_quantity` — it's always derived, never
        independently persisted."""
        return self.stock_quantity - self.reserved_quantity

    def __repr__(self) -> str:
        return f"<Product id={self.id} sku={self.sku} status={self.status}>"
