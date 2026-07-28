"""
modules/products/repository.py

Responsibility
--------------
`ProductRepository` is the ONLY place in the codebase that writes
SQLAlchemy queries against the `products` table — the same Repository
Pattern applied to `UserRepository` in the auth module. `ProductService`
depends on this class's methods and never constructs its own
`select(...)` statement.

No business rules live here (no uniqueness enforcement, no stock
invariants, no status-transition rules) — only "how do I fetch/persist
this data as efficiently as the query needs to be." That line is
deliberate: `search()`/`list_paginated()` build dynamic `WHERE` clauses
from a filters dict, which is inherently a data-access concern (which
columns, which operators, how pagination/sorting are expressed in SQL),
not a business one.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductStatus


@dataclass
class ProductFilters:
    """
    Structured filter parameters accepted by `search()` and
    `list_paginated()`.

    A dataclass (rather than a loose `dict[str, Any]`) so the repository
    method signatures are self-documenting and a typo in a filter name
    fails at call-construction time, not silently inside a query that
    quietly ignores an unrecognized dict key.
    """

    category: str | None = None
    brand: str | None = None
    status: ProductStatus | None = None
    is_featured: bool | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    query: str | None = None  # free-text search term, used by search() only
    sort: str | None = None
    exclude_statuses: tuple[ProductStatus, ...] = field(default_factory=tuple)
    # ^ used by customer-facing endpoints to hard-exclude DRAFT/ARCHIVED/
    # OUT_OF_STOCK regardless of what the caller's other filters say —
    # see ProductService for where this is set.


# Recognized `sort` values and the (column, descending) they map to.
# Kept as a plain mapping here (a data-access-layer lookup table), not in
# the service, since "how a sort key becomes an ORDER BY clause" is a
# query-construction detail.
_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "price_asc": (Product.price, False),
    "price_desc": (Product.price, True),
    "name_asc": (Product.name, False),
    "name_desc": (Product.name, True),
    "newest": (Product.created_at, True),
    "oldest": (Product.created_at, False),
}
_DEFAULT_SORT = "newest"


class ProductRepository:
    """Data-access layer for `Product` records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes ---------------------------------------------------

    def create(self, product: Product) -> Product:
        """Persists a new `Product` row and returns it with its
        generated `id`/server-side defaults populated."""
        self.db.add(product)
        self.db.flush()
        self.db.refresh(product)
        return product

    def update(self, product: Product, **fields: Any) -> Product:
        """Applies field updates to an already-loaded `Product` and
        flushes them. Only the columns actually passed in `fields` are
        changed — see `ProductService.update_product` for how it
        distinguishes "not supplied" from "explicitly set to None"."""
        for field_name, value in fields.items():
            setattr(product, field_name, value)
        self.db.flush()
        self.db.refresh(product)
        return product

    def delete(self, product: Product) -> None:
        """Permanently removes a product row. Irreversible — this is
        why `ProductService.delete_product` exists as a separate,
        deliberate action from `archive_product`, not something a
        generic `update(status=...)` call could do by accident."""
        self.db.delete(product)
        self.db.flush()

    # --- Single-row reads ---------------------------------------------------

    def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        return self.db.get(Product, product_id)

    def get_by_slug(self, slug: str) -> Product | None:
        stmt = select(Product).where(Product.slug == slug)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_sku(self, sku: str) -> Product | None:
        stmt = select(Product).where(Product.sku == sku)
        return self.db.execute(stmt).scalar_one_or_none()

    # --- Uniqueness checks ---------------------------------------------------

    def exists_sku(self, sku: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        """Returns True if another product already uses this SKU.
        `exclude_id` lets a future caller check "is this SKU taken by
        someone other than the product I'm currently editing" — SKUs are
        immutable in this milestone (see schemas/product.py), but the
        parameter is included for the same defensive-symmetry reason
        `exists_slug` needs it today."""
        stmt = select(Product.id).where(Product.sku == sku)
        if exclude_id is not None:
            stmt = stmt.where(Product.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def exists_slug(self, slug: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        """Returns True if another product already uses this slug.
        `exclude_id` is required in practice when validating a slug
        change during an update — otherwise a product would always
        appear to conflict with its own current slug."""
        stmt = select(Product.id).where(Product.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Product.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    # --- Filtering / pagination ---------------------------------------------------

    def _build_filtered_statement(self, filters: ProductFilters) -> Select:
        """Shared WHERE-clause construction for `search()` and
        `list_paginated()` — the only difference between the two public
        methods is whether a free-text `query` term is applied, so the
        common filtering logic is written once here."""
        stmt = select(Product)

        if filters.category is not None:
            stmt = stmt.where(Product.category == filters.category)
        if filters.brand is not None:
            stmt = stmt.where(Product.brand == filters.brand)
        if filters.is_featured is not None:
            stmt = stmt.where(Product.is_featured == filters.is_featured)
        if filters.price_min is not None:
            stmt = stmt.where(Product.price >= filters.price_min)
        if filters.price_max is not None:
            stmt = stmt.where(Product.price <= filters.price_max)

        if filters.exclude_statuses:
            stmt = stmt.where(Product.status.notin_(filters.exclude_statuses))
        if filters.status is not None:
            stmt = stmt.where(Product.status == filters.status)

        if filters.query:
            # Case-insensitive partial match across the fields a shopper
            # or admin would plausibly search by. `func.lower(...)` on
            # both sides keeps this portable (works the same whether or
            # not the column has a case-insensitive collation configured).
            term = f"%{filters.query.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.name).like(term),
                    func.lower(Product.sku).like(term),
                    func.lower(func.coalesce(Product.short_description, "")).like(term),
                    func.lower(func.coalesce(Product.description, "")).like(term),
                )
            )

        sort_key = filters.sort if filters.sort in _SORT_OPTIONS else _DEFAULT_SORT
        column, descending = _SORT_OPTIONS[sort_key]
        stmt = stmt.order_by(column.desc() if descending else column.asc())

        return stmt

    def list_paginated(
        self, *, filters: ProductFilters, page: int, page_size: int
    ) -> tuple[list[Product], int]:
        """Returns `(items, total_count)` for a plain filtered/sorted
        catalog listing (no free-text search term applied, even if one
        happens to be set on `filters` — see `search()` for that)."""
        return self._paginate(filters, page=page, page_size=page_size)

    def search(
        self, *, filters: ProductFilters, page: int, page_size: int
    ) -> tuple[list[Product], int]:
        """Returns `(items, total_count)` for a filtered/sorted catalog
        search, applying `filters.query` as a free-text term in addition
        to every other filter. Implemented via the same shared statement
        builder as `list_paginated` — a search is simply a listing with
        one more predicate, not a fundamentally different query path."""
        return self._paginate(filters, page=page, page_size=page_size)

    def _paginate(
        self, filters: ProductFilters, *, page: int, page_size: int
    ) -> tuple[list[Product], int]:
        base_stmt = self._build_filtered_statement(filters)

        # Total count uses the same filtered statement (minus ORDER BY,
        # which is irrelevant to a COUNT) so the reported total always
        # matches exactly what the filters would return across all pages.
        count_stmt = select(func.count()).select_from(base_stmt.order_by(None).subquery())
        total = self.db.execute(count_stmt).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = base_stmt.offset(offset).limit(page_size)
        items = list(self.db.execute(page_stmt).scalars().all())

        return items, total
