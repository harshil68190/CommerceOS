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
from app.modules.products.repository import ProductFilters, ProductRepository
from app.schemas.product import CreateProductRequest, StockAdjustmentRequest, UpdateProductRequest

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
    reading, searching, and adjusting stock for catalog products."""

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
            stock_quantity=payload.stock_quantity,
            reserved_quantity=0,  # a brand-new product can't already have
            # reservations against it — this is only ever advanced by the
            # dedicated stock-reservation flow after creation.
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

        # A status change (or, in principle, any update) could leave the
        # active/out-of-stock flag out of sync with actual available
        # stock — e.g. an admin manually reactivating a product that
        # still has zero available units. Re-deriving it here keeps the
        # invariant correct after every write, not just after stock
        # operations.
        self._sync_status_with_stock(updated)

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

    def adjust_stock(
        self, product_id: uuid.UUID, payload: StockAdjustmentRequest, current_user: User
    ) -> Product:
        """
        Dispatches a single stock-adjustment request to the appropriate
        dedicated operation. This is the method `router.py`'s
        `PATCH /products/{id}/stock` endpoint calls — kept as a thin
        dispatcher so each individual operation (increase/decrease/
        reserve/release) stays independently callable, documented, and
        testable, per this milestone's explicit method list.
        """
        operation_map = {
            "increase": self.increase_stock,
            "decrease": self.decrease_stock,
            "reserve": self.reserve_stock,
            "release": self.release_reservation,
        }
        return operation_map[payload.operation](product_id, payload.quantity, current_user)

    def increase_stock(
        self, product_id: uuid.UUID, quantity: int, current_user: User
    ) -> Product:
        """
        Increases on-hand stock (e.g. a new shipment/restock arrived).

        Business reasoning: increasing stock can only ever *relax* the
        reserved-vs-available invariant (more stock means more headroom
        for existing reservations), so no ceiling check is needed here —
        unlike `decrease_stock`, which must guard against dropping below
        already-reserved quantity.
        """
        product = self._get_modifiable_product_or_404(product_id)
        self._validate_tracks_inventory(product)
        self._validate_positive_quantity(quantity)

        new_quantity = product.stock_quantity + quantity
        updated = self.repository.update(
            product, stock_quantity=new_quantity, updated_by=current_user.id
        )
        self._sync_status_with_stock(updated)
        self.db.commit()
        return updated

    def decrease_stock(
        self, product_id: uuid.UUID, quantity: int, current_user: User
    ) -> Product:
        """
        Decreases on-hand stock directly (e.g. damage, loss, manual
        correction) — distinct from `reserve_stock`, which earmarks
        stock for a pending sale without physically removing it yet.

        Business reasoning: the result must never leave
        `stock_quantity < reserved_quantity` — the database's own CHECK
        constraint (`ck_products_reserved_within_stock`) would reject
        this at the SQL level regardless, but validating here first
        means the client gets a specific, actionable `ValidationError`
        instead of a raw database constraint-violation error.
        """
        product = self._get_modifiable_product_or_404(product_id)
        self._validate_tracks_inventory(product)
        self._validate_positive_quantity(quantity)

        new_quantity = product.stock_quantity - quantity
        if new_quantity < 0:
            raise ValidationError(
                f"Cannot decrease stock by {quantity}: only "
                f"{product.stock_quantity} units are on hand."
            )
        if new_quantity < product.reserved_quantity:
            raise ValidationError(
                f"Cannot decrease stock by {quantity}: {product.reserved_quantity} "
                f"units are already reserved and cannot exceed on-hand stock."
            )

        updated = self.repository.update(
            product, stock_quantity=new_quantity, updated_by=current_user.id
        )
        self._sync_status_with_stock(updated)
        self.db.commit()
        return updated

    def reserve_stock(
        self, product_id: uuid.UUID, quantity: int, current_user: User
    ) -> Product:
        """
        Earmarks stock for a pending sale (e.g. an item added to an
        in-progress checkout) without physically removing it from
        on-hand inventory — this is the operation a future Orders module
        would call during checkout, mirroring the architecture doc's
        "Request Lifecycle" section on stock reservation at order time.

        Business reasoning: raises `ConflictError` (409, not 422) when
        there isn't enough *available* stock (`stock_quantity -
        reserved_quantity`) — this is a conflict with the product's
        current state (someone else may have just reserved the remaining
        units), the same category of error as two users racing to claim
        the last unit, not a malformed request.
        """
        product = self._get_modifiable_product_or_404(product_id)
        self._validate_tracks_inventory(product)
        self._validate_positive_quantity(quantity)

        if quantity > product.available_quantity:
            raise ConflictError(
                f"Cannot reserve {quantity} units: only "
                f"{product.available_quantity} are currently available."
            )

        updated = self.repository.update(
            product,
            reserved_quantity=product.reserved_quantity + quantity,
            updated_by=current_user.id,
        )
        self._sync_status_with_stock(updated)
        self.db.commit()
        return updated

    def release_reservation(
        self, product_id: uuid.UUID, quantity: int, current_user: User
    ) -> Product:
        """
        Releases a previously reserved quantity back to available stock
        (e.g. a cart expired, or checkout/payment failed) — the
        counterpart to `reserve_stock`.

        Business reasoning: releasing more than is currently reserved
        would drive `reserved_quantity` negative, which is nonsensical
        (you can't un-reserve stock that was never reserved) and would
        violate the same CHECK constraint that guards
        `reserved_quantity >= 0`.
        """
        product = self._get_modifiable_product_or_404(product_id)
        self._validate_tracks_inventory(product)
        self._validate_positive_quantity(quantity)

        if quantity > product.reserved_quantity:
            raise ValidationError(
                f"Cannot release {quantity} units: only "
                f"{product.reserved_quantity} are currently reserved."
            )

        updated = self.repository.update(
            product,
            reserved_quantity=product.reserved_quantity - quantity,
            updated_by=current_user.id,
        )
        self._sync_status_with_stock(updated)
        self.db.commit()
        return updated

    # --- Internal helpers ---------------------------------------------------

    def _get_product_or_404(self, product_id: uuid.UUID) -> Product:
        """Shared existence check used by every admin-facing operation
        (update/archive/delete/stock) — these all operate by id and
        should surface a uniform 404 for an unknown product."""
        product = self.repository.get_by_id(product_id)
        if product is None:
            raise NotFoundError(f"No product found with id '{product_id}'.")
        return product

    def _get_modifiable_product_or_404(self, product_id: uuid.UUID) -> Product:
        """Like `_get_product_or_404`, but additionally enforces "archived
        products cannot be modified" — shared by all four stock
        operations, since a stock change is exactly the kind of
        modification that rule is meant to block."""
        product = self._get_product_or_404(product_id)
        if product.status == ProductStatus.ARCHIVED:
            raise ConflictError(
                "This product is archived and its stock can no longer be adjusted."
            )
        return product

    @staticmethod
    def _validate_positive_quantity(quantity: int) -> None:
        """Defensive guard shared by all four stock operations. The
        `StockAdjustmentRequest` schema already enforces `quantity > 0`
        for requests arriving through the HTTP layer, but these service
        methods are public and may be called directly by other modules
        (e.g. a future Orders service) that bypass that schema entirely."""
        if quantity <= 0:
            raise ValidationError("Quantity must be a positive integer.")

    @staticmethod
    def _validate_tracks_inventory(product: Product) -> None:
        """Products with `track_inventory=False` (e.g. digital goods,
        made-to-order items) opt out of the stock system entirely — any
        stock operation attempted against one is a validation error, not
        something that should be silently ignored or silently applied to
        numbers that don't mean anything for that product."""
        if not product.track_inventory:
            raise ValidationError(
                "This product does not track inventory; stock adjustments are not applicable."
            )

    @staticmethod
    def _sync_status_with_stock(product: Product) -> None:
        """
        Keeps `status` consistent with actual available stock for
        products currently ACTIVE or OUT_OF_STOCK, mutating the
        already-persisted `product` in place (the caller is responsible
        for committing).

        Business reasoning: this only ever moves a product between
        ACTIVE and OUT_OF_STOCK — it never touches DRAFT (a product
        being authored shouldn't "go active" just because someone
        stocked it) or ARCHIVED (a terminal state, and unreachable here
        anyway since every stock-mutating path already rejects archived
        products via `_get_modifiable_product_or_404`).
        """
        if not product.track_inventory:
            return
        if product.status == ProductStatus.ACTIVE and product.available_quantity <= 0:
            product.status = ProductStatus.OUT_OF_STOCK
        elif product.status == ProductStatus.OUT_OF_STOCK and product.available_quantity > 0:
            product.status = ProductStatus.ACTIVE
