# CommerceOS — System Architecture Design

**Status:** Architecture finalization phase — no implementation yet.
**Author:** Staff Engineering / System Architecture review
**Scope:** This document is the single source of truth for how CommerceOS is structured before any module is implemented.

---

## 1. High-Level System Architecture

CommerceOS is designed as a **modular monolith** — not microservices, not a naive CRUD app. This is the correct choice at this stage for three reasons an interviewer will want to hear:

1. A modular monolith gives you microservice-shaped boundaries (clear module ownership, no cross-module DB access, service-layer isolation) without the operational tax of distributed systems (network calls, distributed transactions, service discovery) that a small team can't yet justify.
2. It can be **decomposed into microservices later** module-by-module (e.g., Inventory or Notifications peeled off first) because the boundaries were designed correctly from day one.
3. It's what a real startup would actually run in production for its first 1–3 years.

### 1.1 Component Diagram (logical)

```
                                ┌───────────────────────────┐
                                │        Client Apps        │
                                │  React + TS + Vite (SPA)  │
                                └─────────────┬──────────────┘
                                              │ HTTPS / REST (JSON)
                                              ▼
                                ┌───────────────────────────┐
                                │        API Gateway        │
                                │   (Nginx / Traefik proxy) │
                                │  TLS termination, rate    │
                                │  limiting, routing        │
                                └─────────────┬──────────────┘
                                              ▼
                    ┌────────────────────────────────────────────────┐
                    │                FastAPI Application               │
                    │  ┌──────────────────────────────────────────┐  │
                    │  │  Middleware Layer                         │  │
                    │  │  - CORS, Request-ID, Logging, Auth Guard  │  │
                    │  │  - Rate limiting (Redis-backed)           │  │
                    │  └──────────────────────────────────────────┘  │
                    │  ┌──────────────────────────────────────────┐  │
                    │  │  Router Layer (API endpoints, versioned)   │  │
                    │  └──────────────────────────────────────────┘  │
                    │  ┌──────────────────────────────────────────┐  │
                    │  │  Service Layer (business logic, modules)   │  │
                    │  │  Auth │ Users │ Catalog │ Inventory │      │  │
                    │  │  Cart │ Orders │ Coupons │ Reviews │       │  │
                    │  │  Admin │ Analytics                        │  │
                    │  └──────────────────────────────────────────┘  │
                    │  ┌──────────────────────────────────────────┐  │
                    │  │  Repository Layer (data access, per model) │  │
                    │  └──────────────────────────────────────────┘  │
                    └───────┬───────────────────┬──────────────┬─────┘
                            ▼                   ▼              ▼
                  ┌──────────────┐    ┌──────────────┐  ┌──────────────┐
                  │  PostgreSQL  │    │     Redis     │  │  Background  │
                  │  (Primary DB)│    │ Cache/Session │  │  Workers     │
                  │              │    │ Rate-limit    │  │ (Celery/RQ)  │
                  │              │    │ Token blocklist│  └──────┬───────┘
                  └──────────────┘    └──────────────┘         ▼
                                                        ┌──────────────────┐
                                                        │ Async Job Queue    │
                                                        │ - Emails           │
                                                        │ - Invoice gen      │
                                                        │ - Low-stock alerts │
                                                        │ - Audit logging    │
                                                        └──────────────────┘

                External integrations (future-ready, called via Service Layer):
                Payment Gateway (Stripe/Razorpay) │ Email Provider (SES/SendGrid) │
                SMS/Push Notification Provider │ Object Storage (S3) for images
```

### 1.2 Communication Rules (the part that actually matters architecturally)

- **Client → API**: strictly over REST/JSON, versioned (`/api/v1/...`). No client ever talks to Postgres or Redis directly.
- **Router → Service → Repository → DB**: a strict, one-directional dependency chain.
  - Routers know nothing about SQLAlchemy.
  - Services know nothing about HTTP (no `Request`/`Response` objects leak into services).
  - Repositories know nothing about business rules — they only do persistence.
- **Cross-module calls happen through service interfaces, never through direct model imports across modules.** E.g., the Order service calls `InventoryService.reserve_stock(...)`, it never imports Inventory's SQLAlchemy models directly. This is the seam that makes future microservice extraction possible.
- **Redis** serves three distinct purposes (kept logically separate even though it's one instance at this scale): session/refresh-token store, rate-limiting counters, and read-through cache for hot data (product catalog, category trees).
- **Background workers** (Celery or RQ) handle anything that shouldn't block the request/response cycle: sending emails, generating PDF invoices, recalculating analytics aggregates, firing low-stock alerts. The API enqueues a job and returns immediately.
- **External providers** (payment, email, SMS) are never called directly from routers or repositories — always through a Service → Gateway/Adapter abstraction (see Section 9, Strategy/Adapter pattern), so swapping Stripe for Razorpay or SES for SendGrid is a config change, not a rewrite.

---

## 2. Folder Structure

```
commerceos/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app factory, startup/shutdown hooks
│   │   ├── core/
│   │   │   ├── config.py               # Pydantic Settings (env-driven config)
│   │   │   ├── security.py             # JWT encode/decode, password hashing
│   │   │   ├── logging.py              # Structured logging setup
│   │   │   ├── exceptions.py           # Custom exception hierarchy
│   │   │   └── constants.py
│   │   │
│   │   ├── db/
│   │   │   ├── base.py                 # SQLAlchemy Base + metadata
│   │   │   ├── session.py              # Engine + session factory, get_db dependency
│   │   │   └── mixins.py               # TimestampMixin, SoftDeleteMixin, UUIDMixin
│   │   │
│   │   ├── models/                     # SQLAlchemy ORM models, one file per domain
│   │   │   ├── user.py
│   │   │   ├── product.py
│   │   │   ├── inventory.py
│   │   │   ├── order.py
│   │   │   ├── cart.py
│   │   │   ├── coupon.py
│   │   │   ├── review.py
│   │   │   └── audit_log.py
│   │   │
│   │   ├── schemas/                    # Pydantic v2 request/response DTOs
│   │   │   ├── user.py
│   │   │   ├── product.py
│   │   │   ├── order.py
│   │   │   ├── inventory.py
│   │   │   ├── coupon.py
│   │   │   └── review.py
│   │   │
│   │   ├── modules/                    # Feature modules — the core of the app
│   │   │   ├── auth/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   ├── repository.py
│   │   │   │   └── dependencies.py     # get_current_user, role guards
│   │   │   ├── users/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   └── repository.py
│   │   │   ├── catalog/                # products, categories, brands, variants
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   ├── repository.py
│   │   │   │   └── search.py           # search/filter/sort query builder
│   │   │   ├── inventory/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   └── repository.py
│   │   │   ├── cart/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   └── repository.py
│   │   │   ├── orders/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   ├── repository.py
│   │   │   │   └── state_machine.py    # order status transitions
│   │   │   ├── coupons/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   ├── repository.py
│   │   │   │   └── strategies.py       # FlatDiscount / PercentageDiscount strategy
│   │   │   ├── reviews/
│   │   │   │   ├── router.py
│   │   │   │   ├── service.py
│   │   │   │   └── repository.py
│   │   │   ├── admin/
│   │   │   │   ├── router.py
│   │   │   │   └── service.py
│   │   │   └── analytics/
│   │   │       ├── router.py
│   │   │       └── service.py
│   │   │
│   │   ├── integrations/               # External provider adapters
│   │   │   ├── payments/
│   │   │   │   ├── base.py             # PaymentGateway interface
│   │   │   │   ├── stripe_gateway.py
│   │   │   │   └── razorpay_gateway.py
│   │   │   ├── email/
│   │   │   │   ├── base.py
│   │   │   │   └── ses_provider.py
│   │   │   ├── notifications/
│   │   │   │   └── push_provider.py
│   │   │   └── storage/
│   │   │       └── s3_client.py
│   │   │
│   │   ├── workers/                    # Celery/RQ tasks
│   │   │   ├── celery_app.py
│   │   │   ├── email_tasks.py
│   │   │   ├── invoice_tasks.py
│   │   │   └── alert_tasks.py
│   │   │
│   │   ├── middleware/
│   │   │   ├── request_id.py
│   │   │   ├── rate_limit.py
│   │   │   └── error_handler.py
│   │   │
│   │   └── api_router.py               # Aggregates all module routers, versioning
│   │
│   ├── alembic/
│   │   ├── versions/
│   │   └── env.py
│   │
│   ├── tests/
│   │   ├── unit/                       # service-layer tests, mocked repositories
│   │   ├── integration/                # repository + DB tests (test containers)
│   │   └── e2e/                        # full API flow tests
│   │
│   ├── scripts/                        # seed data, one-off admin scripts
│   ├── pyproject.toml / requirements.txt
│   ├── alembic.ini
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── api/                        # TanStack Query hooks per domain
│   │   ├── components/                 # shadcn/ui-based shared components
│   │   ├── features/                   # feature-sliced: catalog/, cart/, orders/, admin/
│   │   ├── pages/
│   │   ├── lib/                        # axios client, query client, utils
│   │   ├── store/                      # auth/session state
│   │   └── types/                      # shared TS types (mirrors backend schemas)
│   ├── Dockerfile
│   └── vite.config.ts
│
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
└── README.md
```

---

## 3. Database Design

Conventions used throughout: every table has a surrogate primary key `id` (UUID, recommended over auto-increment int for a public-facing commerce system — avoids enumeration attacks on order/user IDs and works cleanly if you shard later). Every table has `created_at`, `updated_at`; sensitive/deletable entities also get `deleted_at` (soft delete).

### 3.1 Identity & Access

**`users`**
- Purpose: core identity record for customers, sellers, and admins (single-table role model with a `role` enum, not separate tables — avoids join explosion for a property that's really just an attribute).
- Key columns: `id (PK)`, `email (unique)`, `password_hash`, `role (enum: customer|seller|admin)`, `is_email_verified`, `is_active`, `phone`, `created_at`.
- Relationships: 1—N with `addresses`, `orders`, `carts`, `wishlists`, `reviews`; 1—1 with `seller_profiles` (when role=seller).
- Indexes: unique index on `email`; index on `role`.

**`seller_profiles`**
- Purpose: extended attributes only relevant to seller accounts (store name, payout details, verification status).
- Key columns: `id (PK)`, `user_id (FK → users.id, unique)`, `store_name`, `verification_status`, `payout_account_ref`.
- Relationships: 1—1 with `users`; 1—N with `products`.

**`addresses`**
- Purpose: shipping/billing addresses, reusable across orders.
- Key columns: `id (PK)`, `user_id (FK → users.id)`, `line1`, `city`, `state`, `postal_code`, `country`, `is_default`, `type (shipping|billing)`.
- Indexes: index on `user_id`.

**`refresh_tokens`**
- Purpose: server-side record of issued refresh tokens to support revocation/rotation (JWTs alone can't be invalidated; this table plus Redis blocklist solves that).
- Key columns: `id (PK)`, `user_id (FK → users.id)`, `token_hash`, `expires_at`, `revoked_at`, `device_info`.
- Indexes: index on `user_id`, index on `token_hash`.

**`password_reset_tokens`**
- Purpose: single-use tokens for the forgot-password flow.
- Key columns: `id (PK)`, `user_id (FK)`, `token_hash`, `expires_at`, `used_at`.

**`email_verification_tokens`**
- Purpose: single-use tokens for confirming email ownership at signup.
- Key columns: `id (PK)`, `user_id (FK)`, `token_hash`, `expires_at`, `used_at`.

### 3.2 Catalog

**`categories`**
- Purpose: hierarchical product categorization.
- Key columns: `id (PK)`, `name`, `slug (unique)`, `parent_id (FK → categories.id, nullable, self-referential)`.
- Relationships: self-referential tree; 1—N with `products`.
- Indexes: index on `parent_id`, unique index on `slug`.

**`brands`**
- Purpose: brand/manufacturer entity.
- Key columns: `id (PK)`, `name (unique)`, `slug`, `logo_url`.

**`products`**
- Purpose: core sellable item (parent record; variants hold sellable SKUs).
- Key columns: `id (PK)`, `seller_id (FK → seller_profiles.id)`, `category_id (FK → categories.id)`, `brand_id (FK → brands.id)`, `title`, `description`, `base_price`, `status (draft|active|archived)`, `avg_rating (denormalized)`, `rating_count (denormalized)`.
- Relationships: N—1 to seller, category, brand; 1—N with `product_variants`, `product_images`, `reviews`.
- Indexes: index on `category_id`, `brand_id`, `seller_id`, `status`; full-text search index on `title`/`description` (Postgres `tsvector` GIN index).

**`product_variants`**
- Purpose: actual purchasable unit (size/color/etc. combination), each with its own SKU and price delta.
- Key columns: `id (PK)`, `product_id (FK → products.id)`, `sku (unique)`, `attributes (JSONB — e.g. {"size":"L","color":"red"})`, `price`, `is_active`.
- Relationships: 1—N with `stock_items`, `cart_items`, `order_items`.
- Indexes: unique index on `sku`, index on `product_id`, GIN index on `attributes` JSONB.

**`product_images`**
- Purpose: ordered images per product (or per variant).
- Key columns: `id (PK)`, `product_id (FK)`, `variant_id (FK, nullable)`, `url`, `sort_order`, `is_primary`.

### 3.3 Inventory

**`warehouses`**
- Purpose: physical/logical stock locations.
- Key columns: `id (PK)`, `name`, `address_id (FK → addresses.id)`, `is_active`.

**`stock_items`**
- Purpose: quantity of a specific variant at a specific warehouse — the actual inventory ledger's current-state table.
- Key columns: `id (PK)`, `variant_id (FK → product_variants.id)`, `warehouse_id (FK → warehouses.id)`, `quantity_on_hand`, `quantity_reserved`, `reorder_threshold`.
- Relationships: composite uniqueness on `(variant_id, warehouse_id)`.
- Indexes: unique composite index on `(variant_id, warehouse_id)`; index on `warehouse_id`.

**`inventory_transactions`**
- Purpose: append-only audit ledger of every stock change (received, reserved, released, sold, adjusted) — this is what lets you reconstruct "why is stock at this number" and is critical for any real inventory system.
- Key columns: `id (PK)`, `stock_item_id (FK → stock_items.id)`, `change_qty`, `reason (enum: purchase_order|order_placed|order_cancelled|manual_adjustment|return)`, `reference_id (order_id or PO id, polymorphic)`, `created_by (FK → users.id)`.
- Indexes: index on `stock_item_id`, index on `reference_id`.

**`low_stock_alerts`**
- Purpose: generated records when `quantity_on_hand` crosses `reorder_threshold`, consumed by notification worker.
- Key columns: `id (PK)`, `stock_item_id (FK)`, `triggered_at`, `resolved_at`, `notified_at`.

### 3.4 Shopping & Orders

**`carts`**
- Purpose: one active cart per user (or guest via session id).
- Key columns: `id (PK)`, `user_id (FK, nullable for guest)`, `session_token (nullable)`, `status (active|converted|abandoned)`.

**`cart_items`**
- Purpose: line items in a cart.
- Key columns: `id (PK)`, `cart_id (FK → carts.id)`, `variant_id (FK → product_variants.id)`, `quantity`, `price_snapshot`.
- Indexes: unique composite `(cart_id, variant_id)`.

**`wishlists`**
- Purpose: saved-for-later items.
- Key columns: `id (PK)`, `user_id (FK)`, `variant_id (FK)`, `added_at`.
- Indexes: unique composite `(user_id, variant_id)`.

**`orders`**
- Purpose: the order header — one per checkout.
- Key columns: `id (PK)`, `user_id (FK → users.id)`, `status (enum: pending|confirmed|processing|shipped|delivered|cancelled|refunded)`, `subtotal`, `discount_total`, `tax_total`, `shipping_total`, `grand_total`, `shipping_address_id (FK)`, `billing_address_id (FK)`, `coupon_id (FK, nullable)`, `placed_at`.
- Relationships: 1—N with `order_items`, `order_status_history`, `payments`, `invoices`.
- Indexes: index on `user_id`, index on `status`, index on `placed_at` (for reporting/analytics range queries).

**`order_items`**
- Purpose: line items, immutable snapshot of what was purchased (price at time of purchase, not live product price).
- Key columns: `id (PK)`, `order_id (FK → orders.id)`, `variant_id (FK → product_variants.id)`, `quantity`, `unit_price_snapshot`, `product_title_snapshot`.
- Indexes: index on `order_id`, index on `variant_id`.

**`order_status_history`**
- Purpose: audit trail of every status transition, powers order tracking UI.
- Key columns: `id (PK)`, `order_id (FK)`, `from_status`, `to_status`, `changed_by (FK → users.id, nullable for system)`, `note`, `created_at`.
- Indexes: index on `order_id`.

**`payments`**
- Purpose: payment attempts/records per order (supports partial/multiple attempts, retries).
- Key columns: `id (PK)`, `order_id (FK)`, `provider (enum: stripe|razorpay|cod)`, `provider_reference`, `amount`, `status (pending|succeeded|failed|refunded)`, `raw_response (JSONB)`.
- Indexes: index on `order_id`, index on `provider_reference`.

**`invoices`**
- Purpose: generated invoice documents per order.
- Key columns: `id (PK)`, `order_id (FK, unique)`, `invoice_number (unique)`, `pdf_url`, `issued_at`.

### 3.5 Coupons

**`coupons`**
- Purpose: discount definitions.
- Key columns: `id (PK)`, `code (unique)`, `type (enum: flat|percentage)`, `value`, `max_discount_amount (nullable, caps percentage coupons)`, `min_order_amount`, `starts_at`, `expires_at`, `usage_limit_total`, `usage_limit_per_user`, `is_active`.
- Indexes: unique index on `code`.

**`coupon_redemptions`**
- Purpose: tracks each use, enforces per-user and total usage limits.
- Key columns: `id (PK)`, `coupon_id (FK)`, `user_id (FK)`, `order_id (FK)`, `redeemed_at`.
- Indexes: composite index on `(coupon_id, user_id)`; unique composite `(coupon_id, order_id)`.

### 3.6 Reviews

**`reviews`**
- Purpose: customer ratings/comments on products.
- Key columns: `id (PK)`, `product_id (FK → products.id)`, `user_id (FK → users.id)`, `order_item_id (FK, nullable — presence proves verified purchase)`, `rating (1-5)`, `comment`, `is_verified_purchase`, `status (pending|published|flagged)`.
- Indexes: index on `product_id`, unique composite `(product_id, user_id)` if one-review-per-purchase policy is desired, index on `order_item_id`.

### 3.7 Cross-Cutting

**`audit_logs`**
- Purpose: system-wide record of sensitive actions (admin changes, role changes, price changes, refunds) for compliance and debugging.
- Key columns: `id (PK)`, `actor_id (FK → users.id, nullable)`, `action`, `entity_type`, `entity_id`, `before_state (JSONB)`, `after_state (JSONB)`, `ip_address`, `created_at`.
- Indexes: index on `(entity_type, entity_id)`, index on `actor_id`, index on `created_at`.

**`notifications`**
- Purpose: in-app/email/push notification records (order updates, low stock, price drops).
- Key columns: `id (PK)`, `user_id (FK)`, `type`, `payload (JSONB)`, `channel (email|push|in_app)`, `status (queued|sent|failed)`, `sent_at`.
- Indexes: index on `user_id`, index on `status`.

---

## 4. API Design

All routes are versioned under `/api/v1`. Auth requirements noted as `[public]`, `[auth]`, `[seller]`, `[admin]`.

### 4.1 Authentication
```
POST   /api/v1/auth/register                  [public]
POST   /api/v1/auth/login                      [public]
POST   /api/v1/auth/refresh                    [public]  (valid refresh token required)
POST   /api/v1/auth/logout                     [auth]
POST   /api/v1/auth/verify-email               [public]  (token in body)
POST   /api/v1/auth/resend-verification        [auth]
POST   /api/v1/auth/forgot-password            [public]
POST   /api/v1/auth/reset-password             [public]  (token + new password)
```

### 4.2 Users
```
GET    /api/v1/users/me                        [auth]
PATCH  /api/v1/users/me                        [auth]
GET    /api/v1/users/me/addresses               [auth]
POST   /api/v1/users/me/addresses               [auth]
PATCH  /api/v1/users/me/addresses/{id}          [auth]
DELETE /api/v1/users/me/addresses/{id}          [auth]
POST   /api/v1/users/me/become-seller           [auth]   (creates seller_profile, pending verification)
```

### 4.3 Products (Catalog)
```
GET    /api/v1/products                        [public]  ?q=&category=&brand=&min_price=&max_price=&sort=&page=&limit=
GET    /api/v1/products/{id}                    [public]
POST   /api/v1/products                        [seller]
PATCH  /api/v1/products/{id}                    [seller/admin]  (ownership enforced)
DELETE /api/v1/products/{id}                    [seller/admin]
POST   /api/v1/products/{id}/images             [seller]
DELETE /api/v1/products/{id}/images/{image_id}  [seller]
GET    /api/v1/products/{id}/variants           [public]
POST   /api/v1/products/{id}/variants           [seller]
PATCH  /api/v1/variants/{id}                    [seller]
GET    /api/v1/categories                       [public]
POST   /api/v1/categories                       [admin]
GET    /api/v1/brands                           [public]
POST   /api/v1/brands                           [admin]
```

### 4.4 Inventory
```
GET    /api/v1/inventory/warehouses             [admin]
POST   /api/v1/inventory/warehouses             [admin]
GET    /api/v1/inventory/stock                  [seller/admin]  ?variant_id=&warehouse_id=
POST   /api/v1/inventory/stock/adjust           [seller/admin]  (manual adjustment, writes inventory_transactions)
GET    /api/v1/inventory/stock/{variant_id}/history   [seller/admin]
GET    /api/v1/inventory/low-stock-alerts       [seller/admin]
```

### 4.5 Cart & Wishlist
```
GET    /api/v1/cart                             [auth]
POST   /api/v1/cart/items                       [auth]
PATCH  /api/v1/cart/items/{item_id}              [auth]
DELETE /api/v1/cart/items/{item_id}              [auth]
DELETE /api/v1/cart                             [auth]   (clear)
GET    /api/v1/wishlist                         [auth]
POST   /api/v1/wishlist                         [auth]
DELETE /api/v1/wishlist/{variant_id}             [auth]
```

### 4.6 Checkout & Orders
```
POST   /api/v1/checkout                         [auth]   (validates cart, stock, coupon → creates order + payment intent)
GET    /api/v1/orders                           [auth]   (own order history; admin can filter by user)
GET    /api/v1/orders/{id}                       [auth]   (ownership or admin)
POST   /api/v1/orders/{id}/cancel                [auth]   (ownership; only if cancellable status)
GET    /api/v1/orders/{id}/tracking              [auth]
GET    /api/v1/orders/{id}/invoice                [auth]   (returns signed PDF url)
POST   /api/v1/orders/{id}/status                [seller/admin]  (transition status, writes order_status_history)
```

### 4.7 Coupons
```
GET    /api/v1/coupons                          [admin]
POST   /api/v1/coupons                          [admin]
PATCH  /api/v1/coupons/{id}                      [admin]
DELETE /api/v1/coupons/{id}                      [admin]
POST   /api/v1/coupons/validate                  [auth]   (checks code against cart total, returns computed discount)
```

### 4.8 Reviews
```
GET    /api/v1/products/{id}/reviews             [public]  ?sort=&page=
POST   /api/v1/products/{id}/reviews             [auth]    (requires verified order_item)
PATCH  /api/v1/reviews/{id}                       [auth]    (own review only)
DELETE /api/v1/reviews/{id}                       [auth/admin]
POST   /api/v1/reviews/{id}/flag                  [auth]
POST   /api/v1/reviews/{id}/moderate              [admin]   (publish/reject)
```

### 4.9 Admin
```
GET    /api/v1/admin/users                       [admin]   ?role=&status=&page=
PATCH  /api/v1/admin/users/{id}/status            [admin]   (activate/deactivate/ban)
PATCH  /api/v1/admin/users/{id}/role              [admin]
GET    /api/v1/admin/sellers/pending              [admin]
POST   /api/v1/admin/sellers/{id}/approve         [admin]
GET    /api/v1/admin/orders                       [admin]   ?status=&date_from=&date_to=
GET    /api/v1/admin/audit-logs                   [admin]   ?entity_type=&actor_id=
```

### 4.10 Analytics
```
GET    /api/v1/analytics/sales-summary            [admin/seller]  ?period=daily|weekly|monthly
GET    /api/v1/analytics/top-products              [admin/seller]
GET    /api/v1/analytics/revenue-by-category       [admin]
GET    /api/v1/analytics/inventory-turnover        [admin/seller]
GET    /api/v1/analytics/customer-cohort           [admin]
```

---

## 5. Authentication Flow

### 5.1 Login Flow
1. Client `POST /auth/login` with email + password.
2. `AuthService` fetches user via `UserRepository`, verifies password hash (bcrypt/argon2) in constant time.
3. On success: generate an **access token** (JWT, short-lived, 15 min) and a **refresh token** (opaque random string, long-lived, 7–30 days).
4. Refresh token is hashed and stored in `refresh_tokens` table (never store the raw token — same principle as passwords). A copy is also cached in Redis for fast revocation checks.
5. Response returns access token in body (or httpOnly cookie, recommended for web client) and refresh token in a separate httpOnly, secure, SameSite=strict cookie.
6. Failed login attempts are rate-limited per email+IP via Redis counters to blunt brute force.

### 5.2 JWT Lifecycle
- **Access token claims**: `sub` (user id), `role`, `iat`, `exp`, `jti` (unique token id, enables targeted revocation).
- Access tokens are **stateless** and verified by signature only (no DB hit) on every request — this is the whole point of JWT for performance.
- A Redis-backed **blocklist** of `jti`s is checked only for explicitly revoked tokens (logout, forced password reset, admin ban) — this keeps the common path fast while still allowing revocation, which pure stateless JWT can't do alone.
- Access token expiry is short (15 min) specifically so that a compromised token has a small blast radius.

### 5.3 Refresh Token Flow
1. When the access token expires, client calls `POST /auth/refresh` with the refresh token cookie.
2. Server looks up the token hash in `refresh_tokens`, checks `revoked_at IS NULL` and `expires_at > now()`.
3. **Rotation**: on every refresh, the old refresh token is revoked and a brand-new one is issued and stored. This is critical — refresh token rotation means a stolen-and-reused old token immediately signals theft (the legitimate client's next refresh will fail, and this can trigger an alert/force-logout-all-sessions).
4. New access token is issued and returned.

### 5.4 Password Reset Flow
1. `POST /auth/forgot-password` with email — always returns a generic 200 response regardless of whether the email exists (prevents user enumeration).
2. If the user exists, a single-use token is generated, hashed, stored in `password_reset_tokens` with a short expiry (e.g. 30 min), and the raw token is emailed via the background worker.
3. `POST /auth/reset-password` with token + new password: service validates token hash, expiry, and `used_at IS NULL`, then updates `password_hash`, marks token used, and **revokes all existing refresh tokens for that user** (forces re-login everywhere — correct security behavior after a password reset).

### 5.5 Email Verification Flow
- Mirrors the password reset mechanism structurally (single-use hashed token, expiry) but only gates `is_email_verified`, and unverified accounts can be restricted from checkout/reviews depending on business policy.

---

## 6. Request Lifecycle — Placing an Order

This is the flow most likely to come up in an interview, so it's worth being explicit about every internal step for `POST /api/v1/checkout`:

1. **Middleware**: request hits rate-limiter, request-ID is assigned, JWT is verified (signature + blocklist check), `current_user` dependency resolves.
2. **Router**: `checkout_router` validates the request shape via Pydantic schema (shipping address id, optional coupon code, payment method) and delegates to `OrderService.checkout(...)`. The router contains no business logic.
3. **Service — cart validation**: `OrderService` calls `CartService.get_active_cart(user)`; if empty, raises a domain exception mapped to 400.
4. **Service — price & stock validation (critical, must be re-verified server-side, never trust client-sent prices)**:
   - For each cart item, fetch the live `product_variant` price — never trust any price the client might have cached.
   - Call `InventoryService.check_availability(variant_id, qty)` for every line item.
5. **Transaction boundary opens** (single DB transaction wraps the following steps — this must be atomic):
   a. `InventoryService.reserve_stock(...)` decrements `quantity_on_hand`/increments `quantity_reserved` per variant and writes an `inventory_transactions` row with reason `order_placed`. Uses row-level locking (`SELECT ... FOR UPDATE`) on `stock_items` to prevent race conditions from concurrent checkouts overselling the same SKU.
   b. If a coupon code was supplied: `CouponService.apply(code, user, cart_total)` validates expiry, usage limits (via `coupon_redemptions`), min order amount, and computes the discount using the appropriate **Strategy** (flat vs percentage — see Section 9).
   c. `OrderService` creates the `orders` row (status=`pending`) and one `order_items` row per line item, snapshotting price and product title (so future catalog changes never alter historical orders).
   d. `order_status_history` row is written for the initial `pending` state.
   e. Cart status is set to `converted`.
6. **Transaction commits.** If any step in 5 fails, the entire transaction rolls back — stock is never left "reserved" for a failed order.
7. **Payment initiation (outside the DB transaction, since external calls should never hold a DB lock)**: `PaymentService` calls the configured `PaymentGateway` adapter (Stripe/Razorpay) to create a payment intent, stores a `payments` row with status `pending`.
8. **Response returned to client** with order id and payment client-secret/redirect info.
9. **Asynchronously (via webhook + background worker)**: when the payment provider confirms payment, a webhook handler verifies the signature, updates the `payments` row to `succeeded`, transitions the order to `confirmed`, and enqueues background jobs: generate invoice PDF, send confirmation email, decrement `quantity_reserved` permanently (convert reservation into a real sale), and check whether the resulting stock crosses the low-stock threshold (enqueue `low_stock_alerts` if so).
10. **If payment fails or times out**: a scheduled worker job releases reserved stock back to `quantity_on_hand` and transitions the order to `cancelled`, writing the corresponding `inventory_transactions` and `order_status_history` rows.

The key architectural point here: **the checkout endpoint's DB transaction never waits on an external network call.** Reservation and order creation are atomic and fast; payment confirmation is decoupled via webhook + worker. This is the difference between a system that survives a slow payment provider and one that doesn't.

---

## 7. Folder Responsibilities

- **`core/`** — cross-cutting technical concerns with zero business logic: config loading, security primitives, logging, the exception hierarchy every module raises against. Exists so nothing in the codebase hardcodes secrets, log formats, or JWT logic in more than one place.
- **`db/`** — the single place that knows how to get a database session and what the ORM base class looks like. No module should construct its own engine or session.
- **`models/`** — SQLAlchemy ORM classes = the shape of persisted data. Deliberately separated from `schemas/` so that the database shape and the API contract are decoupled — you can change one without breaking the other.
- **`schemas/`** — Pydantic v2 DTOs for request validation and response serialization. This is the API's actual contract with the outside world.
- **`modules/`** — one folder per bounded context (auth, catalog, orders, etc.), each with its own `router.py` (HTTP layer), `service.py` (business logic), `repository.py` (persistence). This is the enforced separation that makes the codebase navigable at scale and testable in isolation — you can unit-test `service.py` with a fake repository and never touch a real DB.
- **`integrations/`** — adapters to the outside world (payment, email, storage). Isolated specifically so that "swap Stripe for Razorpay" or "swap SES for SendGrid" touches one file, not the entire order flow.
- **`workers/`** — anything that must run outside the request/response cycle. Exists so slow operations (sending email, PDF generation) never block an HTTP response.
- **`middleware/`** — request-scoped cross-cutting behavior (rate limiting, request ID propagation, centralized error formatting) applied uniformly regardless of which module handles the request.
- **`alembic/`** — schema migration history. Exists so schema changes are versioned, reviewable, and reversible, never applied by hand against production.
- **`tests/`** — split into unit (fast, mocked, run on every commit), integration (real DB via test containers, run in CI), and e2e (full API flow, run before deploy) — this tiering is itself a scalability decision about developer feedback loops.

---

## 8. SOLID Principles in This Architecture

- **Single Responsibility**: Routers only parse/validate HTTP and delegate. Services only hold business rules. Repositories only persist. A `Product` model doesn't know how to calculate a discount, and a `CouponService` doesn't know how to write SQL. Each class has exactly one reason to change.
- **Open/Closed**: New coupon types are added by writing a new `DiscountStrategy` implementation, not by editing an `if/elif` chain inside `CouponService`. New payment providers are added by writing a new `PaymentGateway` adapter, not by modifying `OrderService`. The core services are closed for modification, open for extension.
- **Liskov Substitution**: Any `PaymentGateway` implementation (Stripe, Razorpay, a test/mock gateway) must be fully substitutable behind the same interface — `OrderService` calls `gateway.create_payment_intent(...)` and must work identically regardless of which concrete adapter is injected. Same for `DiscountStrategy` implementations and for `NotificationChannel` implementations (email/push/SMS).
- **Interface Segregation**: Services depend on narrow repository interfaces scoped to what they actually need (e.g., `OrderService` depends on an `InventoryReader`/`InventoryWriter`-shaped interface, not a giant generic repository with every possible method), so a change to unrelated repository methods never forces a service to be touched or retested.
- **Dependency Inversion**: Services depend on repository **abstractions** (injected via FastAPI's `Depends()`), not concrete SQLAlchemy sessions directly instantiated inside business logic. This is what makes services unit-testable with in-memory fakes and what makes the eventual swap of Postgres details (or even a different persistence technology for one module) a contained change.

---

## 9. Design Patterns and Where They Apply

- **Repository Pattern** — one repository per aggregate root (`UserRepository`, `ProductRepository`, `OrderRepository`, etc.), wrapping all SQLAlchemy query logic. Services never write raw queries; they call `repository.get_by_id(...)`, `repository.list_with_filters(...)`. This is what makes services testable without a real database.
- **Service Layer Pattern** — all business logic (order placement rules, stock reservation, coupon validation, review eligibility) lives in `service.py` files, never in routers and never in models. This is the layer where cross-module orchestration happens (e.g. `OrderService` orchestrates `CartService`, `InventoryService`, `CouponService`, `PaymentService`).
- **Dependency Injection** — used pervasively via FastAPI's `Depends()`: DB sessions, current-user resolution, repository instances, and even service instances are all injected rather than constructed inline. This is what enables clean unit testing (swap real dependencies for fakes/mocks in tests) and centralizes lifecycle management (e.g., one DB session per request).
- **Factory Pattern** — used for constructing the correct `PaymentGateway` or `NotificationChannel` implementation at runtime based on config/provider name (`PaymentGatewayFactory.create("stripe")`), and for constructing the FastAPI `app` itself in `main.py` (app factory pattern, useful for testing with different configs).
- **Strategy Pattern** — the natural fit for **coupon discount calculation** (`FlatDiscountStrategy` vs `PercentageDiscountStrategy`, both implementing a common `DiscountStrategy.calculate(cart_total) -> discount_amount` interface) and for **product search/sort** (different `SortStrategy` implementations for price/rating/relevance/newest).
- **Adapter Pattern** — every external integration (`StripeGateway`, `RazorpayGateway`, `SESEmailProvider`) adapts a third-party SDK's specific interface to CommerceOS's own internal `PaymentGateway`/`EmailProvider` interface, so the rest of the app never depends on a vendor SDK's shape directly.
- **Builder Pattern** — useful for constructing complex, optional-heavy objects: the product search query (many optional filters: category, brand, price range, rating, in-stock, sort, pagination — a `ProductQueryBuilder` composes these into a single SQLAlchemy query incrementally) and for constructing an `Order` aggregate during checkout (accumulating line items, discounts, tax, shipping before final assembly).
- **State Machine (behavioral, order-specific)** — `order_status_history` plus an explicit `state_machine.py` in the orders module enforces which status transitions are legal (e.g., `shipped` cannot go directly to `pending`), preventing invalid transitions from ever reaching the database.
- **Observer/Pub-Sub (via background jobs)** — order status changes and stock threshold breaches "publish" jobs to the queue (email, alert) rather than the triggering code calling notification logic directly — this decouples the "what happened" from "who cares and what they do about it."

---

## 10. Scalability Path: 100 → 100,000 Users

**At 100 users (MVP / single small instance):**
- One FastAPI process (Uvicorn/Gunicorn with a few workers), one Postgres instance, one Redis instance, all via the existing Docker Compose setup. No caching strategy needed beyond Redis for sessions. Synchronous background jobs are fine even with a single Celery worker.

**At ~1,000–5,000 users:**
- Add read replicas for Postgres for read-heavy endpoints (product listing, search) — services already separate reads from writes at the repository layer, so routing read queries to a replica is a config change, not a refactor.
- Introduce Redis caching for hot, low-churn data: category trees, product detail pages (cache-aside pattern, invalidated on product update).
- Move image storage to S3/object storage (already abstracted via `integrations/storage/`) instead of local disk.
- Horizontal-scale the API layer behind a load balancer — this is trivial specifically because the API is stateless (JWT auth, no server-side session affinity needed).

**At ~10,000–50,000 users:**
- Introduce full-text/product search via a dedicated search engine (Elasticsearch/OpenSearch/Meilisearch) fed by a change-data-capture or event-driven sync from Postgres, rather than relying on Postgres `tsvector` alone — the `catalog/search.py` module is the seam where this swap happens without touching routers or other modules.
- Partition/scale Celery workers by queue type (emails vs invoice generation vs analytics) so a slow job type (PDF generation) never starves email delivery.
- Add a CDN in front of the frontend and static/product assets.
- Introduce database connection pooling tuning (PgBouncer) as concurrent connections grow beyond what a single Postgres instance's connection limit handles comfortably.

**At 100,000+ users:**
- This is the point where the modular monolith's boundaries pay off: peel off the highest-load, most independently-scalable modules into standalone services first — typically **Inventory** (needs strict consistency and high write throughput, good candidate for its own datastore/service) and **Notifications** (embarrassingly parallel, no shared-transaction needs) — communicating with the remaining monolith via an event bus (Kafka/RabbitMQ) rather than direct synchronous calls.
- Introduce database sharding or move very hot tables (e.g., `inventory_transactions`, `order_status_history`, `audit_logs` — all append-only, high-volume) to a time-partitioned strategy or a separate analytical store, so OLTP tables serving live traffic stay small and fast.
- Move analytics off the primary OLTP database entirely into a data warehouse (e.g., via CDC into BigQuery/Snowflake/ClickHouse) so heavy aggregate queries never compete with checkout traffic for Postgres resources — this is exactly why `analytics/service.py` was already isolated from `orders/service.py` from day one.
- Introduce multi-region deployment for the API layer with a global load balancer, keeping Postgres primary in one region with cross-region read replicas, since full multi-region write consistency is a much bigger and separate architectural decision (and usually not needed even at this scale for most commerce platforms).

The consistent theme: nothing above requires rewriting business logic. Every scaling step is possible specifically because routers/services/repositories/integrations were kept in strict, one-directional layers from the start.

---

## 11. Future Improvements

- **Payment Gateway Integration**: full Stripe/Razorpay webhook handling, saved payment methods, partial refunds, multi-currency support.
- **Notification Service**: proper multi-channel (email/SMS/push) preference center per user, templated notifications, delivery tracking/retries.
- **Recommendation Engine**: "customers also bought", personalized homepage, based on order history + browsing events.
- **Multi-vendor Marketplace Enhancements**: seller payout scheduling, commission/fee structures, seller-level analytics dashboards.
- **Fraud Detection**: rules-based or ML-based flagging on checkout (velocity checks, mismatched billing/shipping, device fingerprinting).
- **Internationalization**: multi-currency pricing, multi-language product content, region-specific tax rules.
- **Advanced Search**: faceted search, typo-tolerance, personalized ranking, synonym handling via a dedicated search engine.
- **Subscription/Recurring Orders**: for consumable goods, recurring billing integration.
- **Return/Refund Workflow**: a full RMA (Return Merchandise Authorization) module with its own state machine, distinct from cancellation.
- **GraphQL Gateway (optional)**: layered on top of existing services for clients needing flexible querying, without disturbing the REST contract.
- **Event Sourcing for Orders**: replacing `order_status_history` with a full event-sourced order aggregate if audit/replay requirements grow more demanding.
- **Feature Flags / A/B Testing Infrastructure**: for gradual rollout of catalog/checkout experiments.

---

**Next step (per your instruction):** this document is the frozen reference architecture. When you're ready, we implement one module at a time, starting wherever you'd like — I'd suggest `core/` + `db/` + the `auth` module first, since every other module depends on authentication and the DB session pattern being solid.
