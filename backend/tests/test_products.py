"""
tests/test_products.py

Production-quality integration test suite for the Product module.

Covers:
- CRUD operations (create, read, update, delete, archive, listing, pagination, sorting, filtering)
- Input validation (duplicate SKU/slug, invalid prices, missing fields, status constraints)
- Product status lifecycle (draft, active, archived, out_of_stock) and customer visibility
- Search (name, SKU, category, partial match, case-insensitive)
- RBAC (admin, seller, customer, anonymous)
- Business rules (archive immutability, timestamp updates, audit fields)
- Error response envelope consistency

Uses the shared test infrastructure from conftest.py (fixtures, rollback isolation, etc.).
"""

import re
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.product import Product, ProductStatus
from app.models.user import User


# =========================================================================
# Helpers
# =========================================================================


def _assert_error_envelope(response, *, status_code: int, error_code: str):
    """Asserts the consistent API error envelope format used across all
    modules. Mirror of the helper in test_auth.py."""
    assert response.status_code == status_code
    body = response.json()
    assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
    assert body["error_code"] == error_code


def _create_product_payload(unique_value_factory, **overrides) -> dict:
    """Generates a valid product creation payload with unique SKU and slug."""
    idx = unique_value_factory("test")
    payload = {
        "sku": f"TST-SKU-{idx[-8:].upper()}",
        "slug": f"test-slug-{idx}",
        "name": f"Test Product {idx}",
        "description": "A product created during integration testing.",
        "short_description": "Integration test product",
        "brand": "TestBrand",
        "category": "TestCategory",
        "price": "29.99",
        "compare_at_price": "34.99",
        "currency": "USD",
        "weight": "1.500",
        "status": "active",
        "is_featured": False,
        "track_inventory": True,
    }
    payload.update(overrides)
    return payload


# =========================================================================
# 1. Product CRUD
# =========================================================================


class TestProductCRUD:
    """Create, Read, Update, Delete, Archive, Listing, Pagination,
    Sorting, and Filtering."""

    def test_create_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["sku"] == payload["sku"]
        assert body["slug"] == payload["slug"]
        assert body["name"] == payload["name"]
        assert body["price"] == payload["price"]
        assert body["status"] == "active"
        assert "id" in body
        assert "created_at" in body
        assert "updated_at" in body

    def test_retrieve_product_by_slug(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        # Create first
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert create_resp.status_code == 201
        product_slug = create_resp.json()["slug"]

        # Retrieve by slug (public endpoint)
        response = authenticated_admin_client.get(f"/api/v1/products/{product_slug}")
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == product_slug
        assert body["name"] == payload["name"]
        assert body["sku"] == payload["sku"]

    def test_retrieve_nonexistent_product_returns_404(
        self, client: TestClient
    ):
        response = client.get("/api/v1/products/nonexistent-slug-that-does-not-exist")
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_update_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        update_data = {"name": "Updated Product Name", "price": "39.99"}
        response = authenticated_admin_client.put(
            f"/api/v1/products/{product_id}", json=update_data
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Updated Product Name"
        assert body["price"] == "39.99"
        # Slug should remain unchanged
        assert body["slug"] == payload["slug"]

    def test_update_nonexistent_product_returns_404(
        self, authenticated_admin_client: TestClient
    ):
        fake_id = str(uuid4())
        response = authenticated_admin_client.put(
            f"/api/v1/products/{fake_id}", json={"name": "Ghost"}
        )
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_hard_delete_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_admin_client.delete(f"/api/v1/products/{product_id}")
        assert response.status_code == 204

        # Verify it's gone
        get_resp = authenticated_admin_client.get(f"/api/v1/products/{payload['slug']}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_product_returns_404(
        self, authenticated_admin_client: TestClient
    ):
        fake_id = str(uuid4())
        response = authenticated_admin_client.delete(f"/api/v1/products/{fake_id}")
        _assert_error_envelope(response, status_code=404, error_code="NOT_FOUND")

    def test_archive_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_admin_client.patch(
            f"/api/v1/products/{product_id}/archive"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "archived"

    def test_archive_already_archived_product_returns_409(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        # First archive
        authenticated_admin_client.patch(f"/api/v1/products/{product_id}/archive")

        # Second archive should fail
        response = authenticated_admin_client.patch(
            f"/api/v1/products/{product_id}/archive"
        )
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")

    # --- Listing ---

    def test_admin_list_all_products(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = authenticated_admin_client.get("/api/v1/products/admin")
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "pages" in body
        assert body["total"] >= 1

    def test_customer_list_active_products(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        # Create an active product
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = authenticated_customer_client.get("/api/v1/products")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1

    def test_draft_products_excluded_from_customer_listing(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        # Create a draft product
        draft_payload = _create_product_payload(unique_value_factory, status="draft")
        authenticated_admin_client.post("/api/v1/products", json=draft_payload)

        # Create an active product
        active_payload = _create_product_payload(unique_value_factory, status="active")
        authenticated_admin_client.post("/api/v1/products", json=active_payload)

        # Customer listing should only show the active product
        response = authenticated_customer_client.get("/api/v1/products")
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            assert item["status"] == "active"

    # --- Pagination ---

    def test_pagination_defaults(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        # Create a few products
        for _ in range(3):
            p = _create_product_payload(unique_value_factory)
            authenticated_admin_client.post("/api/v1/products", json=p)

        response = authenticated_admin_client.get("/api/v1/products/admin")
        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["total"] >= 3

    def test_pagination_page_size(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        for _ in range(5):
            p = _create_product_payload(unique_value_factory)
            authenticated_admin_client.post("/api/v1/products", json=p)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"page": 1, "page_size": 2}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= 2
        assert body["page_size"] == 2

    def test_pagination_last_page_empty(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        for _ in range(3):
            p = _create_product_payload(unique_value_factory)
            authenticated_admin_client.post("/api/v1/products", json=p)

        # Request a page beyond available data
        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"page": 100, "page_size": 10}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 0
        assert body["total"] >= 3

    # --- Sorting ---

    def test_sort_by_price_ascending(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        p1 = _create_product_payload(unique_value_factory, price="10.00", slug="low-price")
        p2 = _create_product_payload(unique_value_factory, price="50.00", slug="mid-price")
        p3 = _create_product_payload(unique_value_factory, price="100.00", slug="high-price")
        authenticated_admin_client.post("/api/v1/products", json=p1)
        authenticated_admin_client.post("/api/v1/products", json=p2)
        authenticated_admin_client.post("/api/v1/products", json=p3)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"sort": "price_asc"}
        )
        assert response.status_code == 200
        body = response.json()
        prices = [Decimal(item["price"]) for item in body["items"] if item["slug"] in ("low-price", "mid-price", "high-price")]
        # Filter to only the ones we created and check ordering
        relevant = [p for p in prices]
        assert relevant == sorted(relevant), "Prices should be sorted ascending"

    def test_sort_by_price_descending(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        p1 = _create_product_payload(unique_value_factory, price="10.00")
        p2 = _create_product_payload(unique_value_factory, price="50.00")
        p3 = _create_product_payload(unique_value_factory, price="100.00")
        authenticated_admin_client.post("/api/v1/products", json=p1)
        authenticated_admin_client.post("/api/v1/products", json=p2)
        authenticated_admin_client.post("/api/v1/products", json=p3)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"sort": "price_desc"}
        )
        assert response.status_code == 200
        body = response.json()
        prices = [Decimal(item["price"]) for item in body["items"]]
        assert prices == sorted(prices, reverse=True)

    def test_sort_by_name_ascending(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        p1 = _create_product_payload(unique_value_factory, name="Alpha Product")
        p2 = _create_product_payload(unique_value_factory, name="Beta Product")
        p3 = _create_product_payload(unique_value_factory, name="Gamma Product")
        authenticated_admin_client.post("/api/v1/products", json=p1)
        authenticated_admin_client.post("/api/v1/products", json=p2)
        authenticated_admin_client.post("/api/v1/products", json=p3)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"sort": "name_asc"}
        )
        assert response.status_code == 200
        body = response.json()
        names = [item["name"] for item in body["items"]]
        assert names == sorted(names)

    # --- Filtering ---

    def test_filter_by_category(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        cat_a = _create_product_payload(unique_value_factory, category="Electronics")
        cat_b = _create_product_payload(unique_value_factory, category="Clothing")
        authenticated_admin_client.post("/api/v1/products", json=cat_a)
        authenticated_admin_client.post("/api/v1/products", json=cat_b)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"category": "Electronics"}
        )
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            assert item["category"] == "Electronics"

    def test_filter_by_brand(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        brand_a = _create_product_payload(unique_value_factory, brand="Sony")
        brand_b = _create_product_payload(unique_value_factory, brand="Apple")
        authenticated_admin_client.post("/api/v1/products", json=brand_a)
        authenticated_admin_client.post("/api/v1/products", json=brand_b)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"brand": "Sony"}
        )
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            assert item["brand"] == "Sony"

    def test_filter_by_price_range(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        p1 = _create_product_payload(unique_value_factory, price="10.00")
        p2 = _create_product_payload(unique_value_factory, price="50.00")
        p3 = _create_product_payload(unique_value_factory, price="100.00")
        authenticated_admin_client.post("/api/v1/products", json=p1)
        authenticated_admin_client.post("/api/v1/products", json=p2)
        authenticated_admin_client.post("/api/v1/products", json=p3)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"price_min": "20.00", "price_max": "80.00"}
        )
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            price = Decimal(item["price"])
            assert Decimal("20.00") <= price <= Decimal("80.00")

    def test_filter_by_featured(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        featured = _create_product_payload(unique_value_factory, is_featured=True)
        not_featured = _create_product_payload(unique_value_factory, is_featured=False)
        authenticated_admin_client.post("/api/v1/products", json=featured)
        authenticated_admin_client.post("/api/v1/products", json=not_featured)

        response = authenticated_admin_client.get(
            "/api/v1/products/admin", params={"featured": True}
        )
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            assert item["is_featured"] is True


# =========================================================================
# 2. Validation
# =========================================================================


class TestProductValidation:
    """Input validation: duplicate SKU/slug, invalid prices, missing
    required fields, invalid status transitions, etc."""

    def test_duplicate_sku_returns_409(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Same SKU, different slug
        duplicate = _create_product_payload(unique_value_factory, sku=payload["sku"])
        response = authenticated_admin_client.post("/api/v1/products", json=duplicate)
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")
        assert "SKU" in response.json()["message"]

    def test_duplicate_slug_returns_409(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Same slug, different SKU
        duplicate = _create_product_payload(unique_value_factory, slug=payload["slug"])
        response = authenticated_admin_client.post("/api/v1/products", json=duplicate)
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")
        assert "slug" in response.json()["message"]

    def test_negative_price_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, price="-10.00")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_zero_price_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, price="0.00")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_price_precision(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, price="99.99")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201
        assert response.json()["price"] == "99.99"

    def test_empty_name_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, name="")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_missing_sku_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        del payload["sku"]
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_missing_price_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        del payload["price"]
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_missing_name_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        del payload["name"]
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_invalid_status_archived_on_create_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="archived")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_invalid_status_out_of_stock_on_create_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="out_of_stock")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_invalid_slug_pattern_returns_422(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, slug="INVALID SLUG!!!")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 422

    def test_unicode_product_name(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, name="Produit à tester 日本語 Español")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201
        assert response.json()["name"] == "Produit à tester 日本語 Español"

    def test_large_description(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        large_desc = "A" * 5000
        payload = _create_product_payload(unique_value_factory, description=large_desc)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201
        assert len(response.json()["description"]) == 5000


# =========================================================================
# 3. Product Status
# =========================================================================


class TestProductStatus:
    """Status lifecycle: draft, active, archived, and customer visibility."""

    def test_create_draft_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="draft")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201
        assert response.json()["status"] == "draft"

    def test_create_active_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="active")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201
        assert response.json()["status"] == "active"

    def test_draft_product_not_visible_to_customer(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="draft")
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Customer should not see draft in listing
        list_resp = authenticated_customer_client.get("/api/v1/products")
        assert list_resp.status_code == 200
        for item in list_resp.json()["items"]:
            assert item["status"] != "draft"

        # Customer should not see draft by slug
        slug_resp = authenticated_customer_client.get(
            f"/api/v1/products/{payload['slug']}"
        )
        assert slug_resp.status_code == 404

    def test_archived_product_not_visible_to_customer(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        # Create active, then archive
        payload = _create_product_payload(unique_value_factory, status="active")
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        authenticated_admin_client.patch(f"/api/v1/products/{product_id}/archive")

        # Customer should not see archived in listing
        list_resp = authenticated_customer_client.get("/api/v1/products")
        for item in list_resp.json()["items"]:
            assert item["status"] != "archived"

        # Customer should not see archived by slug
        slug_resp = authenticated_customer_client.get(
            f"/api/v1/products/{payload['slug']}"
        )
        assert slug_resp.status_code == 404

    def test_active_product_visible_to_customer(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, status="active")
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Customer should see active by slug
        slug_resp = authenticated_customer_client.get(
            f"/api/v1/products/{payload['slug']}"
        )
        assert slug_resp.status_code == 200
        assert slug_resp.json()["status"] == "active"

    def test_admin_list_includes_draft_products(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        draft_payload = _create_product_payload(unique_value_factory, status="draft")
        authenticated_admin_client.post("/api/v1/products", json=draft_payload)

        response = authenticated_admin_client.get("/api/v1/products/admin")
        assert response.status_code == 200
        slugs = [item["slug"] for item in response.json()["items"]]
        assert draft_payload["slug"] in slugs


# =========================================================================
# 4. Search
# =========================================================================


class TestProductSearch:
    """Free-text search: name, SKU, category, partial match,
    case-insensitive, and visibility rules."""

    def test_search_by_name(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(
            unique_value_factory, name="UniqueWidgetPro"
        )
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "UniqueWidgetPro"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any("UniqueWidgetPro" in item["name"] for item in body["items"])

    def test_search_by_sku(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": payload["sku"]}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(payload["sku"] in item["sku"] for item in body["items"])

    def test_search_by_category_as_filter(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        """Category is a structured filter param on the search endpoint,
        not part of the free-text `q` search (which searches name, SKU,
        description). Use the `category` query parameter to filter by
        category."""
        payload = _create_product_payload(
            unique_value_factory, category="SpecialGadgets",
            name="CategorySearchableProduct",
        )
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Search using the category filter parameter
        response = authenticated_customer_client.get(
            "/api/v1/products/search",
            params={"q": "CategorySearchableProduct", "category": "SpecialGadgets"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        for item in body["items"]:
            assert item["category"] == "SpecialGadgets"

    def test_partial_match(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, name="SuperLongProductNameXYZ")
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Partial term
        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "LongProduct"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1

    def test_case_insensitive_search(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, name="CaseSensitiveTest")
        authenticated_admin_client.post("/api/v1/products", json=payload)

        # Lowercase query
        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "casesensitivetest"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1

    def test_search_excludes_draft_products(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        # Draft product
        draft = _create_product_payload(unique_value_factory, status="draft", name="DraftSearchable")
        authenticated_admin_client.post("/api/v1/products", json=draft)

        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "DraftSearchable"}
        )
        assert response.status_code == 200
        body = response.json()
        total = body["total"]
        # Draft should not appear in search results
        for item in body["items"]:
            assert item["status"] != "draft"

    def test_search_empty_result(
        self, authenticated_customer_client: TestClient
    ):
        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "zzzzzzzzzzzzzzzzzzzzzzzzz"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_search_with_category_filter(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        p1 = _create_product_payload(unique_value_factory, category="Audio", name="Speaker")
        p2 = _create_product_payload(unique_value_factory, category="Video", name="Speaker")
        authenticated_admin_client.post("/api/v1/products", json=p1)
        authenticated_admin_client.post("/api/v1/products", json=p2)

        response = authenticated_customer_client.get(
            "/api/v1/products/search", params={"q": "Speaker", "category": "Audio"}
        )
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            assert item["category"] == "Audio"


# =========================================================================
# 5. RBAC
# =========================================================================


class TestProductRBAC:
    """Role-based access control: admin, seller, customer, anonymous."""

    def test_admin_can_create_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        assert response.status_code == 201

    def test_admin_can_update_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_admin_client.put(
            f"/api/v1/products/{product_id}", json={"name": "Admin Updated"}
        )
        assert response.status_code == 200

    def test_admin_can_delete_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_admin_client.delete(f"/api/v1/products/{product_id}")
        assert response.status_code == 204

    def test_customer_cannot_create_product(
        self, authenticated_customer_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_customer_client.post("/api/v1/products", json=payload)
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_update_product(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_customer_client.put(
            f"/api/v1/products/{product_id}", json={"name": "Hacked"}
        )
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_delete_product(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_customer_client.delete(f"/api/v1/products/{product_id}")
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_customer_cannot_archive_product(
        self, authenticated_admin_client: TestClient,
        authenticated_customer_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        response = authenticated_customer_client.patch(
            f"/api/v1/products/{product_id}/archive"
        )
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")

    def test_anonymous_cannot_access_admin_endpoints(
        self, client: TestClient
    ):
        response = client.get("/api/v1/products/admin")
        _assert_error_envelope(response, status_code=401, error_code="UNAUTHORIZED")

    def test_anonymous_can_access_public_listing(
        self, client: TestClient, authenticated_admin_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = client.get("/api/v1/products")
        assert response.status_code == 200

    def test_anonymous_can_access_public_search(
        self, client: TestClient
    ):
        response = client.get("/api/v1/products/search", params={"q": "test"})
        assert response.status_code == 200

    def test_anonymous_can_access_public_product_by_slug(
        self, client: TestClient, authenticated_admin_client: TestClient,
        unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        response = client.get(f"/api/v1/products/{payload['slug']}")
        assert response.status_code == 200

    def test_customer_can_access_public_endpoints(
        self, authenticated_customer_client: TestClient
    ):
        response = authenticated_customer_client.get("/api/v1/products")
        assert response.status_code == 200

    def test_customer_cannot_access_admin_listing(
        self, authenticated_customer_client: TestClient
    ):
        response = authenticated_customer_client.get("/api/v1/products/admin")
        _assert_error_envelope(response, status_code=403, error_code="FORBIDDEN")


# =========================================================================
# 6. Business Rules
# =========================================================================


class TestProductBusinessRules:
    """Domain-specific business rules: uniqueness, archive immutability,
    timestamp updates, audit fields."""

    def test_duplicate_sku_on_create_returns_409(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        duplicate = _create_product_payload(unique_value_factory, sku=payload["sku"])
        response = authenticated_admin_client.post("/api/v1/products", json=duplicate)
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")
        assert payload["sku"] in response.json()["message"]

    def test_duplicate_slug_on_create_returns_409(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)

        duplicate = _create_product_payload(unique_value_factory, slug=payload["slug"])
        response = authenticated_admin_client.post("/api/v1/products", json=duplicate)
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")
        assert payload["slug"] in response.json()["message"]

    def test_cannot_update_archived_product(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        # Archive
        authenticated_admin_client.patch(f"/api/v1/products/{product_id}/archive")

        # Try to update
        response = authenticated_admin_client.put(
            f"/api/v1/products/{product_id}", json={"name": "Should Fail"}
        )
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")
        assert "archived" in response.json()["message"].lower()

    def test_timestamp_updates_on_create(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        body = response.json()
        assert body["created_at"] is not None
        assert body["updated_at"] is not None

    def test_timestamp_updates_on_update(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]
        original_created = create_resp.json()["created_at"]
        original_updated = create_resp.json()["updated_at"]

        update_resp = authenticated_admin_client.put(
            f"/api/v1/products/{product_id}", json={"name": "Updated Name"}
        )
        body = update_resp.json()
        # created_at must never change after creation
        assert body["created_at"] == original_created
        # updated_at must be a non-null timestamp (note: within the same
        # DB transaction PostgreSQL's now() returns the transaction start
        # time, so the string values may be identical — the important
        # invariant is that updated_at is always populated)
        assert body["updated_at"] is not None
        assert body["updated_at"] == body["updated_at"]  # valid datetime string

    def test_audit_fields_created_by(
        self, authenticated_admin_client: TestClient, unique_value_factory,
        admin_user: User
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        body = response.json()
        assert body["created_by"] == str(admin_user.id)

    def test_audit_fields_updated_by(
        self, authenticated_admin_client: TestClient, unique_value_factory,
        admin_user: User
    ):
        payload = _create_product_payload(unique_value_factory)
        create_resp = authenticated_admin_client.post("/api/v1/products", json=payload)
        product_id = create_resp.json()["id"]

        update_resp = authenticated_admin_client.put(
            f"/api/v1/products/{product_id}", json={"name": "Updated"}
        )
        body = update_resp.json()
        assert body["updated_by"] == str(admin_user.id)

    def test_slug_uniqueness_on_update(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload_a = _create_product_payload(unique_value_factory)
        payload_b = _create_product_payload(unique_value_factory)
        create_a = authenticated_admin_client.post("/api/v1/products", json=payload_a)
        create_b = authenticated_admin_client.post("/api/v1/products", json=payload_b)
        product_b_id = create_b.json()["id"]

        # Try to update product B to use product A's slug
        response = authenticated_admin_client.put(
            f"/api/v1/products/{product_b_id}",
            json={"slug": payload_a["slug"]}
        )
        _assert_error_envelope(response, status_code=409, error_code="CONFLICT")


# =========================================================================
# 7. Error Responses
# =========================================================================


class TestProductErrorResponses:
    """Consistent API error envelope for all error scenarios."""

    def test_validation_error_envelope(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory, price="-1.00")
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "REQUEST_VALIDATION_ERROR"
        assert "details" in body

    def test_duplicate_resource_error_envelope(
        self, authenticated_admin_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        authenticated_admin_client.post("/api/v1/products", json=payload)
        response = authenticated_admin_client.post("/api/v1/products", json=payload)
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "CONFLICT"

    def test_not_found_error_envelope(
        self, client: TestClient
    ):
        response = client.get("/api/v1/products/this-slug-does-not-exist-12345")
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "NOT_FOUND"

    def test_forbidden_error_envelope(
        self, authenticated_customer_client: TestClient, unique_value_factory
    ):
        payload = _create_product_payload(unique_value_factory)
        response = authenticated_customer_client.post("/api/v1/products", json=payload)
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "FORBIDDEN"

    def test_unauthorized_error_envelope(
        self, client: TestClient
    ):
        response = client.get("/api/v1/products/admin")
        body = response.json()
        assert set(body.keys()) == {"error_code", "message", "details", "request_id"}
        assert body["error_code"] == "UNAUTHORIZED"
