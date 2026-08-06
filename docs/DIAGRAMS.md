# CommerceOS — Diagrams

This document contains the key architecture and lifecycle diagrams for
CommerceOS, rendered with **Mermaid** (renders on GitHub, GitLab, and VS Code
with the Mermaid extension, or at [mermaid.live](https://mermaid.live/)).

All diagrams reflect the **currently implemented** system. For context on
what is implemented vs. planned, see
[CommerceOS_Architecture.md](../CommerceOS_Architecture.md).

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Backend Request Flow](#2-backend-request-flow)
3. [Database ER Diagram](#3-database-er-diagram)
4. [Order Lifecycle](#4-order-lifecycle)
5. [Inventory Lifecycle](#5-inventory-lifecycle)

---

## 1. High-Level Architecture

```mermaid
flowchart TB
    subgraph Client["Client"]
        SPA["React + TypeScript SPA<br/>(Vite / TanStack Query / shadcn-ui)"]
    end

    subgraph Backend["FastAPI Application (modular monolith)"]
        direction TB
        MW["Middleware<br/>CORS, Request-ID, Centralized Error Handler"]
        RT["Routers<br/>auth | products | inventory | orders | health"]
        SV["Services (business logic)<br/>AuthService, ProductService,<br/>WarehouseService, StockMovementService,<br/>OrderService"]
        RP["Repositories (persistence)<br/>SQLAlchemy 2.x typed"]
        MD["Models / Schemas<br/>ORM ↔ Pydantic DTOs"]
    end

    subgraph Data["Data Layer"]
        PG[("PostgreSQL 16<br/>Primary DB")]
        RD[("Redis 7<br/>Refresh tokens / cache-ready")]
    end

    SPA -- "HTTPS / REST (JSON) /api/v1/*" --> MW
    MW --> RT
    RT --> SV
    SV --> RP
    RP --> MD
    MD --> PG
    SV --> RD
```

**Key point:** CommerceOS is a **modular monolith**. Each module owns its own
router, service, and repository; cross-module calls go through **service
interfaces** (e.g., `OrderService` → `StockMovementService`), never through
direct model imports across modules. This is the seam that allows future
decomposition into microservices.

---

## 2. Backend Request Flow

The strict, one-directional dependency chain enforced throughout the codebase:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client (React SPA)
    participant M as Middleware (Request-ID, CORS, Error Handler)
    participant R as Router (validates via Pydantic)
    participant S as Service (business logic)
    participant RE as Repository (data access)
    participant DB as PostgreSQL
    participant RD as Redis

    C->>M: HTTP request (JWT Bearer)
    M->>M: assign request_id, resolve current_user
    M->>R: forward request
    R->>R: validate request body / query (Pydantic schema)
    R->>S: call exactly one service method
    S->>RE: query/update via repository
    RE->>DB: SQL (SQLAlchemy)
    DB-->>RE: result
    RE-->>S: domain object
    S-->>R: result (or raise domain exception)
    R-->>M: HTTP response (DTO)
    M-->>C: JSON response
    Note over S,RD: AuthService tracks refresh tokens in Redis
```

**Layering rules** (enforced by convention):

- **Routers** know nothing about SQLAlchemy — they only parse/validate HTTP.
- **Services** know nothing about HTTP — no `Request`/`Response` leak in.
- **Repositories** know no business rules — they only persist.
- Business/validation errors are raised as domain exceptions and mapped to
  HTTP by the **centralized error handler** into a consistent envelope.

---

## 3. Database ER Diagram

```mermaid
erDiagram
    USERS ||--o{ PRODUCTS : "created_by"
    USERS ||--o{ ORDERS : "customer_id"
    USERS ||--o{ ORDERS : "created_by"
    USERS ||--o{ INVENTORY_TRANSACTIONS : "created_by"
    USERS ||--o{ WAREHOUSES : "created_by"

    PRODUCTS ||--o{ INVENTORY : "holds stock in"
    WAREHOUSES ||--o{ INVENTORY : "contains"
    PRODUCTS ||--o{ INVENTORY_TRANSACTIONS : "audited by"
    WAREHOUSES ||--o{ INVENTORY_TRANSACTIONS : "audited by"

    ORDERS ||--o{ ORDER_ITEMS : "contains"
    PRODUCTS ||--o{ ORDER_ITEMS : "references"
    WAREHOUSES ||--o{ ORDER_ITEMS : "fulfilled by"

    USERS {
        uuid id PK
        string email UK
        string username UK
        string hashed_password
        string role "admin|seller|inventory_manager|customer"
        boolean is_active
        boolean is_verified
        datetime created_at
        datetime updated_at
    }

    PRODUCTS {
        uuid id PK
        string sku UK
        string slug UK
        string name
        string description
        string brand
        string category
        decimal price
        decimal compare_at_price
        string currency
        string status "draft|active|archived|out_of_stock"
        boolean is_featured
        boolean track_inventory
        uuid created_by FK
        datetime created_at
    }

    WAREHOUSES {
        uuid id PK
        string name
        string code UK
        string address
        string city
        string country
        boolean is_active
        int version
        datetime created_at
    }

    INVENTORY {
        uuid id PK
        uuid product_id FK
        uuid warehouse_id FK
        int quantity
        int reserved_quantity
        int reorder_level
        int max_stock
        int version
        datetime created_at
    }

    INVENTORY_TRANSACTIONS {
        uuid id PK
        uuid product_id FK
        uuid warehouse_id FK
        string transaction_type "purchase|sale|adjustment|reservation|release|transfer_in|transfer_out|damage|expired|confirm_reservation"
        int quantity
        int previous_quantity
        int new_quantity
        int previous_reserved_quantity
        int new_reserved_quantity
        string reference_number
        string correlation_id
        string notes
        uuid created_by FK
        datetime created_at
    }

    ORDERS {
        uuid id PK
        string order_number UK
        uuid customer_id FK
        string status "pending|confirmed|shipped|delivered|cancelled|returned|refunded"
        string payment_status "unpaid|authorized|paid|failed|refunded"
        decimal subtotal
        decimal tax
        decimal shipping_cost
        decimal discount
        decimal total
        datetime reserved_until
        string cancel_reason
        int version
        uuid created_by FK
        datetime created_at
    }

    ORDER_ITEMS {
        uuid id PK
        uuid order_id FK
        uuid product_id FK
        uuid warehouse_id FK
        string product_name "snapshot"
        string product_sku "snapshot"
        int quantity
        decimal unit_price "snapshot"
        decimal line_total
        datetime created_at
    }
```

**Key invariants:**

- `INVENTORY` is the **single source of truth** for stock, with a unique
  `(product_id, warehouse_id)` pair.
- `INVENTORY_TRANSACTIONS` is an **immutable append-only audit ledger** — every
  stock change writes a record.
- `ORDER_ITEMS` **snapshots** product name / SKU / unit price at order time so
  history is immutable.
- All IDs are **UUIDs** (no enumerable public IDs); money is stored as
  fixed-point `Numeric`.

---

## 4. Order Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING : Order created (stock reserved)
    PENDING --> CONFIRMED : Payment confirmed (reservation → sale)
    PENDING --> CANCELLED : Cancelled (stock released)
    CONFIRMED --> SHIPPED : Carrier pickup
    SHIPPED --> DELIVERED : Delivered to customer
    DELIVERED --> RETURNED : Return initiated
    RETURNED --> REFUNDED : Refund completed
    CANCELLED --> [*]
    REFUNDED --> [*]
```

**Transition map** (enforced in `OrderService` via `ORDER_STATUS_TRANSITIONS`):

| From | Allowed To |
|------|-----------|
| `pending` | `confirmed`, `cancelled` |
| `confirmed` | `shipped` |
| `shipped` | `delivered` |
| `delivered` | `returned` |
| `returned` | `refunded` |
| `cancelled` | _(terminal)_ |
| `refunded` | _(terminal)_ |

**Inventory integration throughout:**

- **Create** → `reserve_stock` (stock reserved for the pending order).
- **Confirm payment** → `confirm_reservation` (reservation converted to a sale,
  physical stock deducted).
- **Cancel / delete** → `release_reservation` (reserved stock released).
- **Item qty change** → reserve or release the difference.

---

## 5. Inventory Lifecycle

```mermaid
stateDiagram-v2
    [*] --> IN_STOCK

    IN_STOCK --> LOW_STOCK : available ≤ reorder_level
    IN_STOCK --> OUT_OF_STOCK : available = 0

    LOW_STOCK --> IN_STOCK : restock (add / transfer in)
    LOW_STOCK --> OUT_OF_STOCK : sold / reserved to zero

    OUT_OF_STOCK --> IN_STOCK : restock (add / transfer in)
    OUT_OF_STOCK --> LOW_STOCK : partial restock

    IN_STOCK --> IN_STOCK : reserve / release / add / remove / transfer / adjust
    LOW_STOCK --> LOW_STOCK : reserve / release / add / remove / transfer / adjust
    OUT_OF_STOCK --> OUT_OF_STOCK : reserve / release / remove / transfer / adjust
```

**Stock movement model** — every transition above is driven by one of these
operations, each of which writes an immutable `InventoryTransaction`:

| Operation | Effect on `quantity` | Effect on `reserved_quantity` | Transaction type |
|-----------|----------------------|-------------------------------|------------------|
| **Add** | + | — | `purchase` / `return` |
| **Remove** | − | — | `damage` / `expired` / `adjustment` |
| **Adjust** | set to target | — | `adjustment` |
| **Reserve** | — | + | `reservation` |
| **Release** | — | − | `release` |
| **Confirm** | − | − | `confirm_reservation` + `sale` |
| **Transfer** | src − / dest + | — | `transfer_out` + `transfer_in` (shared `correlation_id`) |

**Concurrency & correctness:**

- All reads-for-modification use `SELECT ... FOR UPDATE` to prevent overselling.
- Optimistic concurrency (`version` field) is a second safety layer.
- DB `CHECK` constraints guarantee `quantity >= 0`, `reserved <= quantity`,
  and non-negative monetary fields.
- `available_quantity` is a **computed** property (`quantity − reserved`),
  never stored, so it cannot drift out of sync.

---

_See [CommerceOS_Architecture.md](../CommerceOS_Architecture.md) for the full
reference architecture and roadmapped future modules._
