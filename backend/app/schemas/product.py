"""
schemas/product.py

Responsibility
--------------
Every request/response shape the product catalog module's API exposes.
Kept separate from `models/product.py` for the same reason as the auth
module's schemas: the database shape and the wire format are allowed to
evolve independently.

Two deliberate design decisions worth calling out:

1. `sku` is NOT present on `UpdateProductRequest`. A SKU is a permanent
   identifier tying a catalog entry to external systems (barcodes,
   supplier records, past order line items once the orders module
   exists) — real commerce systems treat it as immutable after creation.
   `slug` IS updatable (renaming a product's URL slug for SEO reasons is
   a normal operation), and the service layer re-validates its
   uniqueness whenever it changes.

2. `status` on `UpdateProductRequest` only accepts `DRAFT`/`ACTIVE` —
   moving a product to `ARCHIVED` goes through the dedicated
   `PATCH /products/{id}/archive` endpoint (a one-way, deliberate action
   with its own business rules), and `OUT_OF_STOCK` is a status the
   service manages automatically based on available stock, never
   something a client sets directly.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from math import ceil
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.product import ProductStatus

# Only these two statuses are valid as a *creation-time* or general
# *update-time* value — see the module docstring above for why ARCHIVED
# and OUT_OF_STOCK are excluded here.
_EDITABLE_STATUSES = (ProductStatus.DRAFT, ProductStatus.ACTIVE)


class CreateProductRequest(BaseModel):
    """Request body for POST /products (admin/manager only)."""

    sku: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    short_description: str | None = Field(default=None, max_length=500)
    brand: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)

    price: Decimal = Field(gt=0, decimal_places=2)
    compare_at_price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)

    stock_quantity: int = Field(default=0, ge=0)
    weight: Decimal | None = Field(default=None, gt=0, decimal_places=3)

    status: ProductStatus = Field(default=ProductStatus.DRAFT)
    is_featured: bool = False
    track_inventory: bool = True

    @field_validator("status")
    @classmethod
    def _status_must_be_editable(cls, value: ProductStatus) -> ProductStatus:
        if value not in _EDITABLE_STATUSES:
            raise ValueError(
                "A product can only be created as 'draft' or 'active'; "
                "'archived' and 'out_of_stock' are not valid creation states."
            )
        return value

    @field_validator("currency")
    @classmethod
    def _currency_must_be_uppercase(cls, value: str) -> str:
        # Normalizes "usd" -> "USD" rather than rejecting it outright —
        # currency codes are conventionally uppercase, but there's no
        # ambiguity in what the client meant, so correcting is friendlier
        # than a 422 for something this trivial.
        return value.upper()


class UpdateProductRequest(BaseModel):
    """
    Request body for PUT /products/{id} (admin/manager only).

    Every field is optional — this is a partial update; only the fields
    actually supplied are changed (see `ProductService.update_product`
    for how unset fields are distinguished from fields explicitly set to
    `None`).
    """

    slug: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    short_description: str | None = Field(default=None, max_length=500)
    brand: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)

    price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    compare_at_price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    weight: Decimal | None = Field(default=None, gt=0, decimal_places=3)

    status: ProductStatus | None = None
    is_featured: bool | None = None
    track_inventory: bool | None = None

    @field_validator("status")
    @classmethod
    def _status_must_be_editable(cls, value: ProductStatus | None) -> ProductStatus | None:
        if value is not None and value not in _EDITABLE_STATUSES:
            raise ValueError(
                "This endpoint can only set status to 'draft' or 'active'. "
                "Use PATCH /products/{id}/archive to archive a product."
            )
        return value

    @field_validator("currency")
    @classmethod
    def _currency_must_be_uppercase(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class StockAdjustmentRequest(BaseModel):
    """
    Request body for PATCH /products/{id}/stock (admin/manager only).

    A single endpoint covers all four stock operations (increase,
    decrease, reserve, release), disambiguated by `operation` — this
    mirrors how `ProductService` exposes four distinct, individually
    documented methods rather than one ambiguous "set stock to N" call
    that would lose the business meaning of *why* the stock changed.
    """

    operation: Literal["increase", "decrease", "reserve", "release"]
    quantity: int = Field(gt=0)


class ProductResponse(BaseModel):
    """Full public representation of a product, returned by every
    catalog read/write endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    slug: str
    name: str
    description: str | None
    short_description: str | None
    brand: str | None
    category: str | None

    price: Decimal
    compare_at_price: Decimal | None
    currency: str

    stock_quantity: int
    reserved_quantity: int
    available_quantity: int  # computed property on the ORM model

    weight: Decimal | None

    status: ProductStatus
    is_featured: bool
    track_inventory: bool

    created_by: uuid.UUID
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    """
    Paginated envelope returned by GET /products and GET /products/search.

    Offset pagination (`page`/`page_size`) rather than cursor pagination
    — the right tradeoff for a catalog listing where "jump to page 7" and
    total-count display genuinely matter to shoppers/admins, unlike a
    high-write-throughput feed where cursor pagination's consistency
    guarantees would matter more.
    """

    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls, *, items: list[ProductResponse], total: int, page: int, page_size: int
    ) -> "ProductListResponse":
        """Convenience constructor that computes `pages` from
        `total`/`page_size` rather than making every caller repeat the
        `ceil` division themselves."""
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)
