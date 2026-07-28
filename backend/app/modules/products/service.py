"""
modules/products/service.py

Responsibility
--------------
Every business rule for the product catalog: uniqueness enforcement,
price/stock validation, status-transition rules (draft -> active ->
archived, and the automatic active <-> out_of_stock toggle driven by
available inventory), and the four distinct stock-movement operations.
`router.py` calls exactly one method per endpoint and does nothing else.

No SQL lives here — every persistence operation goes through
`ProductRepository`. Every raised error is a domain exception from
`core/exceptions.py`; `router.py`/the global exception handler are the
only places that know these turn into HTTP status codes.
"""

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.product import Product, ProductStatus
from app.models.user import User
from app.modules.inventory.product_inventory_service import ProductInventoryService
from app.modules.products.repository import ProductFilters, ProductRepository
from app.schemas.product import CreateProductRequest, UpdateProductRequest

# Statuses a customer-facing listing/search/detail lookup is allowed to
# surface. Per this milestone's business rule ("Only ACTIVE products
# appear in customer listing" / "Draft products are invisible to
# customers"), this is a single-element tuple today, but expressed as a
# named constant (not a magic `ProductStatus.ACTIVE` scattered through
# the method bodies below) so the rule is easy to find and change in one
# place if it's ever relaxed (e.g. to also show OUT_OF_STOCK for
# transparency).
_CUSTOMER_VISIBLE_STATUSES = (ProductStatus.ACTIVE,)


class ProductService:
    """Business logic for creating, updating, archiving, deleting,
    reading, and searching catalog products.

    NOTE: Stock operations have been moved to the Inventory module
    (StockMovementService in modules/inventory/). Product-level
    stock aggregates are available via ProductInventoryService."""

    def __init__(self, repository: ProductRepository, db: Session) -> None:
        self.repository = repository
        self.db = db

    # --- Create ---------------------------------------------------

    def create_product(self, payload: CreateProductRequest, current_user: User) -> Product:
        """
        Creates a new catalog product.

        Business reasoning: SKU and slug uniqueness are checked
        proactively so the common case (an honest duplicate) gets a
        clear, specific 409 instead of a raw database integrity error —
        the database's own unique constraints remain the final safety
        net against a race between two concurrent creations with the
        same SKU/slug (see `models/product.py`).
        """
        if self.repository.exists_sku(payload.sku):
            raise ConflictError(f"A product with SKU '{payload.sku}' already exists.")
        if self.repository.exists_slug(payload.slug):
            raise ConflictError(f"A product with slug '{payload.slug}' already exists.")

        product = Product(
            sku=payload.sku,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            short_description=payload.short_description,
            brand=payload.brand,
            category=payload.category,
            price=payload.price,
            compare_at_price=payload.compare_at_price,
            currency=payload.currency,
            # NOTE: stock_quantity and reserved_quantity are no longer
            # stored on Product. Use the Inventory module
            # (POST /inventory/stock/add) for initial stock.
            weight=payload.weight,
            status=payload.status,
            is_featured=payload.is_featured,
            track_inventory=payload.track_inventory,
            created_by=current_user.id,
            updated_by=current_user.id,
        )

        created = self.repository.create(product)
        self.db.commit()
        return created

    # --- Update ---------------------------------------------------

    def update_product(
        self, product_id: uuid.UUID, payload: UpdateProductRequest, current_user: User
    ) -> Product:
        """
        Applies a partial update to an existing product.

        Business reasoning:
        - Archived products are immutable by design (this milestone's
          explicit business rule) — attempting to update one is a 409
          conflict with the resource's current state, not a 400/422,
          since the request itself may be perfectly well-formed; it's
          simply not allowed given *this particular* product's status.
        - Only fields the client actually supplied are changed
          (`model_dump(exclude_unset=True)`) — a partial update must not
          silently null out fields the client never mentioned.
        - `slug` uniqueness is re-checked only when it's actually being
          changed, and explicitly excludes the product's own current row
          from that check (otherwise every product would permanently
          conflict with its own slug).
        """
        product = self._get_product_or_404(product_id)

        if product.status == ProductStatus.ARCHIVED:
            raise ConflictError(
                "This product is archived and can no longer be modified."
            )

        updates = payload.model_dump(exclude_unset=True)

        if "slug" in updates and updates["slug"] != product.slug:
            if self.repository.exists_slug(updates["slug"], exclude_id=product.id):
                raise ConflictError(
                    f"A product with slug '{updates['slug']}' already exists."
                )

        updates["updated_by"] = current_user.id
        updated = self.repository.update(product, **updates)

        # Sync status with inventory data (available stock from
        # Inventory module determines OUT_OF_STOCK status).
        self._sync_product_status_from_inventory(product.id)

        self.db.commit()
        return updated

    # --- Archive ---------------------------------------------------

    def archive_product(self, product_id: uuid.UUID, current_user: User) -> Product:
        """
        Moves a product to ARCHIVED — a one-way, terminal transition.

        Business reasoning: archiving an already-archived product is
        itself a disallowed "modification" per this milestone's rule, so
        it raises the same `ConflictError` as any other attempted edit to
        an archived product, rather than silently succeeding as a no-op.
        This keeps "archived products cannot be modified" an absolute
        rule with no special-cased exception for archiving itself.
        """
        product = self._get_product_or_404(product_id)

        if product.status == ProductStatus.ARCHIVED:
            raise ConflictError("This product is already archived.")

        archived = self.repository.update(
            product, status=ProductStatus.ARCHIVED, updated_by=current_user.id
        )
        self.db.commit()
        return archived

    # --- Delete ---------------------------------------------------

    def delete_product(self, product_id: uuid.UUID, current_user: User) -> None:
        """
        Permanently removes a product.

        Business reasoning: unlike editing fields or adjusting stock,
        hard deletion is treated as a distinct, final administrative
        action available regardless of a product's current status
        (including ARCHIVED) — "archived products cannot be modified"
        governs edits to a product's content/state, not an admin's
        ability to permanently remove obsolete catalog data entirely.
        Once an Orders module exists and references products by id, this
        method is the natural place to instead enforce "cannot delete a
        product that appears on any order" — out of scope today since no
        such reference exists yet.
        """
        product = self._get_product_or_404(product_id)
        self.repository.delete(product)
        self.db.commit()

    # --- Reads ---------------------------------------------------

    def get_product_by_slug_for_customer(self, slug: str) -> Product:
        """
        Customer-facing single-product lookup by slug.

        Business reasoning: raises `NotFoundError` (404) for a product
        that exists but isn't ACTIVE (draft/archived/out-of-stock) —
        never a 403 — so an unauthenticated shopper cannot distinguish
        "this slug was never a product" from "this product exists but
        isn't visible to you." Leaking that distinction would let anyone
        probe for draft/upcoming product slugs before launch.
        """
        product = self.repository.get_by_slug(slug)
        if product is None or product.status not in _CUSTOMER_VISIBLE_STATUSES:
            raise NotFoundError(f"No product found with slug '{slug}'.")
        return product

    # --- Search / list ---------------------------------------------------

    def list_products_for_customer(
        self, *, filters: ProductFilters, page: int, page_size: int
    ) -> tuple[list[Product], int]:
        """
        Customer-facing catalog listing (GET /products).

        Business reasoning: forces `exclude_statuses` to hide everything
        except ACTIVE, regardless of any `status` value a caller might
        otherwise try to pass in `filters` — this is what makes "Only
        ACTIVE products appear in customer listing" an actual guarantee
        rather than a convention a router could accidentally bypass.
        """
        filters.status = None  # a customer can't ask to see a specific
        # non-active status — silently ignored rather than erroring,
        # since it's not something the public API surface even exposes
        # as a parameter (see router.py).
        filters.exclude_statuses = tuple(
            s for s in ProductStatus if s not in _CUSTOMER_VISIBLE_STATUSES
        )
        return self.repository.list_paginated(filters=filters, page=page, page_size=page_size)

    def search_products_for_customer(
        self, *, filters: ProductFilters, page: int, page_size: int
    ) -> tuple[list[Product], int]:
        """Customer-facing catalog search (GET /products/search) — same
        visibility rule as `list_products_for_customer`, plus a
        free-text `filters.query` term."""
        filters.status = None
        filters.exclude_statuses = tuple(
            s for s in ProductStatus if s not in _CUSTOMER_VISIBLE_STATUSES
        )
        return self.repository.search(filters=filters, page=page, page_size=page_size)

    # --- Stock operations ---------------------------------------------------
    #
    # NOTE: Stock management has been moved to the Inventory module.
    # All stock mutations (add, remove, adjust, reserve, release,
    # transfer) are handled by StockMovementService in
    # modules/inventory/stock_movement_service.py.
    #
    # The Product module no longer stores stock_quantity or
    # reserved_quantity. Product-level stock aggregates are available
    # via ProductInventoryService in modules/inventory/.
    #
    # To maintain backward compatibility for existing callers, this
    # section provides a delegation method. New code should call the
    # Inventory module directly.

    # --- Internal helpers ---------------------------------------------------

    def _get_product_or_404(self, product_id: uuid.UUID) -> Product:
        """Shared existence check used by every admin-facing operation
        (update/archive/delete/stock) — these all operate by id and
        should surface a uniform 404 for an unknown product."""
        product = self.repository.get_by_id(product_id)
        if product is None:
            raise NotFoundError(f"No product found with id '{product_id}'.")
        return product

    def _sync_product_status_from_inventory(
        self, product_id: uuid.UUID
    ) -> None:
        """
        Derives the product's status based on available stock from the
        Inventory module.

        If a product is ACTIVE but has zero available stock across all
        warehouses, it transitions to OUT_OF_STOCK. If OUT_OF_STOCK and
        stock becomes available, it transitions back to ACTIVE.

        Uses ProductInventoryService to check aggregate inventory.
        """
        product = self._get_product_or_404(product_id)
        if not product.track_inventory:
            return
        if product.status in (ProductStatus.DRAFT, ProductStatus.ARCHIVED):
            return

        inv_svc = ProductInventoryService(self.db)
        is_oos = inv_svc.check_product_out_of_stock(product_id)

        if product.status == ProductStatus.ACTIVE and is_oos:
            self.repository.update(product, status=ProductStatus.OUT_OF_STOCK)
        elif product.status == ProductStatus.OUT_OF_STOCK and not is_oos:
            self.repository.update(product, status=ProductStatus.ACTIVE)
