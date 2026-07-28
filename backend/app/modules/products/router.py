"""
modules/products/router.py

Responsibility
--------------
HTTP layer only for the product catalog: request/query parameter
binding, status codes, and authorization wiring. Every actual business
decision is made in `ProductService`; this file calls exactly one
service method per endpoint.

Route ordering note: `GET /products/search` is declared BEFORE
`GET /products/{slug}` on purpose. Both are GET routes under `/products`,
and Starlette matches path-parameter routes in declaration order — if
`{slug}` were declared first, a request to `/products/search` would be
(incorrectly) routed there with `slug="search"` instead of reaching the
dedicated search endpoint.
"""

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.modules.products.dependencies import require_catalog_manager
from app.modules.products.repository import ProductFilters, ProductRepository
from app.modules.products.service import ProductService
from app.schemas.product import (
    CreateProductRequest,
    ProductListResponse,
    ProductResponse,
    UpdateProductRequest,
)

router = APIRouter(prefix="/products", tags=["products"])

SortOption = Literal["price_asc", "price_desc", "name_asc", "name_desc", "newest", "oldest"]


def get_product_service(db: Session = Depends(get_db)) -> ProductService:
    """FastAPI dependency: assembles a fully-wired `ProductService` for
    the current request, mirroring `get_auth_service` in the auth
    module's `service.py`. Routers depend on this, never on
    `ProductRepository`/`ProductService` constructed inline."""
    repository = ProductRepository(db)
    return ProductService(repository=repository, db=db)


# --- Admin / catalog-manager routes ---------------------------------------------------


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new product",
)
def create_product(
    payload: CreateProductRequest,
    current_user: User = Depends(require_catalog_manager),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Creates a new catalog product. Restricted to admins/catalog
    managers — see `modules/products/dependencies.py`."""
    product = service.create_product(payload, current_user)
    return ProductResponse.model_validate(product)


@router.put(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing product",
)
def update_product(
    product_id: uuid.UUID,
    payload: UpdateProductRequest,
    current_user: User = Depends(require_catalog_manager),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Partially updates a product. Rejected with 409 if the product is
    archived (archived products are immutable)."""
    product = service.update_product(product_id, payload, current_user)
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete a product",
)
def delete_product(
    product_id: uuid.UUID,
    current_user: User = Depends(require_catalog_manager),
    service: ProductService = Depends(get_product_service),
) -> None:
    """Permanently removes a product. See `ProductService.delete_product`
    for why this is allowed regardless of status, unlike editing."""
    service.delete_product(product_id, current_user)


@router.patch(
    "/{product_id}/archive",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a product",
)
def archive_product(
    product_id: uuid.UUID,
    current_user: User = Depends(require_catalog_manager),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Moves a product to ARCHIVED — a one-way, terminal transition."""
    product = service.archive_product(product_id, current_user)
    return ProductResponse.model_validate(product)


# --- Customer-facing routes ---------------------------------------------------


@router.get(
    "",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="List active products (customer-facing catalog)",
)
def list_products(
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    featured: bool | None = Query(default=None),
    price_min: Decimal | None = Query(default=None, ge=0),
    price_max: Decimal | None = Query(default=None, ge=0),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: ProductService = Depends(get_product_service),
) -> ProductListResponse:
    """
    Lists products visible to customers.

    No `status` query parameter is exposed here at all — per this
    milestone's business rule, customers only ever see ACTIVE products,
    and that's enforced unconditionally inside
    `ProductService.list_products_for_customer`, not by trusting the
    router to pass the "right" filter value.
    """
    filters = ProductFilters(
        category=category,
        brand=brand,
        is_featured=featured,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
    )
    items, total = service.list_products_for_customer(
        filters=filters, page=page, page_size=page_size
    )
    return ProductListResponse.build(
        items=[ProductResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/search",
    response_model=ProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="Search active products by keyword (customer-facing)",
)
def search_products(
    q: str = Query(min_length=1, description="Free-text search term (name, SKU, description)"),
    category: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    featured: bool | None = Query(default=None),
    price_min: Decimal | None = Query(default=None, ge=0),
    price_max: Decimal | None = Query(default=None, ge=0),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: ProductService = Depends(get_product_service),
) -> ProductListResponse:
    """Free-text search across name/SKU/description, restricted to
    ACTIVE products for the same reason as `list_products` above."""
    filters = ProductFilters(
        category=category,
        brand=brand,
        is_featured=featured,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        query=q,
    )
    items, total = service.search_products_for_customer(
        filters=filters, page=page, page_size=page_size
    )
    return ProductListResponse.build(
        items=[ProductResponse.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{slug}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single active product by slug (customer-facing)",
)
def get_product_by_slug(
    slug: str,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    """Returns a single ACTIVE product by its slug. Returns 404 (never
    403) for a product that exists but isn't ACTIVE — see
    `ProductService.get_product_by_slug_for_customer` for why."""
    product = service.get_product_by_slug_for_customer(slug)
    return ProductResponse.model_validate(product)
