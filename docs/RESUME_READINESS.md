# CommerceOS — Resume & Interview Readiness

This document is your cheat sheet for talking about CommerceOS in a job
search: resume bullets, a 2-minute interview explanation, and 10 likely
interview questions with strong sample answers.

---

## Table of Contents

1. [Three Resume Bullet Points](#1-three-resume-bullet-points)
2. [Two-Minute Interview Explanation](#2-two-minute-interview-explanation)
3. [Ten Interview Questions with Sample Answers](#3-ten-interview-questions-with-sample-answers)

---

## 1. Three Resume Bullet Points

> Lead with **impact and engineering substance**, not just "built an app."
> Each bullet should demonstrate a real architecture/engineering decision.
> Replace the bracketed `[context]` with your situation (e.g., "as a solo
> project," "on a team of three").

**Bullet 1 — Architecture & scale thinking**
> "Designed and built **CommerceOS**, a production-oriented modular-monolith
> commerce platform (FastAPI + React), enforcing a strict Router → Service →
> Repository → DB layering with service-level cross-module boundaries that
> support future decomposition into microservices."

**Bullet 2 — Correctness & data integrity**
> "Engineered an **immutable inventory transaction ledger** with
> `SELECT ... FOR UPDATE` row locking and optimistic concurrency, eliminating
> overselling under concurrent order requests; every stock change is audited
> and atomic."

**Bullet 3 — Delivery & quality**
> "Delivered a **full-stack, tested** system: 200+ integration tests with an
> 80%+ coverage gate, Docker Compose for local dev, and a committed Render
> Blueprint for one-command production deployment — cutting setup from hours
> to minutes."

---

## 2. Two-Minute Interview Explanation

> Deliver this in about 90–120 seconds. Practice it out loud. The goal is to
> show you understand *why* the architecture is shaped the way it is, not just
> what it does.

**Opener (10s):**
"CommerceOS is a full-stack commerce platform I built to production
quality — a FastAPI and React application covering authentication,
product catalog, multi-warehouse inventory, and the complete order
lifecycle."

**The core idea — modular monolith (30s):**
"I made a deliberate architectural choice: a **modular monolith** rather
than microservices. Each domain — auth, products, inventory, orders — is its
own module with a router, a service, and a repository. Services only talk to
each other through interfaces. That gives me microservice-shaped boundaries
and clean ownership, but without the operational cost of distributed systems,
which doesn't make sense for a small team. And because the seams are correct,
I can peel modules into services later if the system needs to scale."

**The hardest part — data integrity (45s):**
"The hardest engineering problem was inventory correctness under concurrency.
Orders reserve stock, and two concurrent orders must never oversell the same
SKU. I solved that with three layers: **row locking** via `SELECT ... FOR
UPDATE`, **optimistic concurrency** via a version column, and an **immutable
transaction ledger** that records every stock movement. Order creation and
stock reservation happen in the same database transaction, so they're atomic —
if anything fails, nothing is left partially reserved. On the order side, I
modeled a strict state machine — pending, confirmed, shipped, delivered,
returned, refunded — so invalid transitions are impossible."

**Quality & delivery (20s):**
"To make it genuinely production-quality, I added centralized error handling
with request IDs, health and readiness probes, 200+ integration tests with an
80% coverage gate, and Docker Compose plus a Render Blueprint so it deploys
with one command. The frontend is a typed React SPA with TanStack Query and a
single-flight refresh-once auth interceptor."

**Closer (5s):**
"It's a showcase of applied architecture: real layering, real concurrency
control, real test coverage, and real deployment config."

---

## 3. Ten Interview Questions with Sample Answers

### Q1. Why did you choose a modular monolith over microservices?

**Sample answer:**
"A modular monolith is the right fit for this stage. Microservices add
real operational tax — network hops, distributed transactions, service
discovery, more deployment complexity — that a small team can't justify early
on. But I still wanted microservice-shaped boundaries, so I organized the code
into modules with strict, one-directional layering: routers validate HTTP,
services hold business logic, repositories persist. Cross-module calls go
through service interfaces, never direct model imports. That means if CommerceOS
were to grow, I could extract, say, the inventory module into its own service
just by turning that service interface into a network call — without rewriting
business logic."

### Q2. How do you prevent overselling when two orders hit the same SKU at the same time?

**Sample answer:**
"Three layers. First, every stock read-for-modification uses
`SELECT ... FOR UPDATE`, so a second transaction blocks until the first
commits. Second, I have optimistic concurrency with a `version` column as a
backup. Third, and most importantly, order creation and stock reservation happen
in the same database transaction — so they're atomic. If anything fails, the
whole transaction rolls back, and stock is never left partially reserved. On
top of that, the database has CHECK constraints so quantity can't go negative
and reserved can't exceed on-hand. That's defense in depth."

### Q3. Walk me through what happens when a customer places an order.

**Sample answer:**
"The create-order endpoint first validates every product exists and is active,
and checks the warehouse is active. It snapshots product name, SKU, and unit
price at order time so history stays immutable. Then, in a single database
transaction, it creates the order and the line items and calls the inventory
service to reserve stock. The order starts in `pending`. Later, when payment is
confirmed, we call `confirm_reservation`, which converts the reservation into a
real sale and deducts physical stock. If the order is cancelled before shipping,
we release the reservation. Every stock movement writes an immutable transaction
record for audit."

### Q4. Why an immutable inventory transaction ledger?

**Sample answer:**
"Because inventory is money, and you need to be able to answer 'why is stock
at this number?' The ledger is append-only — every add, remove, adjust, reserve,
release, confirm, and transfer writes a record with the previous and new
quantities, the actor, and a reference. If something goes wrong, you can
reconstruct exactly what happened. It also gives me a natural audit trail for
compliance and debugging. I never mutate inventory quantities directly; every
change has to go through the stock-movement service, which always writes the
transaction."

### Q5. How do you handle authentication and token revocation?

**Sample answer:**
"I use short-lived JWT access tokens plus longer-lived refresh tokens. Access
tokens are stateless — verified by signature only, no database hit — which is
fast. But JWTs can't be revoked, so I track refresh tokens in Redis with a TTL.
On refresh, I rotate: the old token is deleted and a new pair is issued, so a
stolen-and-replayed refresh token stops working immediately. Logout deletes the
Redis entry for instant revocation. I also made login constant-time by using a
dummy hash for non-existent emails, so an attacker can't enumerate accounts by
measuring response time."

### Q6. How do you handle errors consistently across the API?

**Sample answer:**
"There's a single centralized error handler. Business and data-access code
raises plain domain exceptions — they know nothing about HTTP. The handler maps
those to HTTP statuses and a consistent JSON envelope with `error_code`,
`message`, `details`, and `request_id`. Validation errors are reformatted into
the same shape, and unexpected exceptions return a generic 500 without leaking
stack traces. Every request also gets a request ID via middleware, so you can
correlate a client error with server logs."

### Q7. How did you ensure the order state machine can't be violated?

**Sample answer:**
"Order status transitions are not enforced ad hoc. I defined an explicit
transition map in the orders module — e.g. `pending` can go to `confirmed` or
`cancelled`, `shipped` can only go to `delivered`, `delivered` to `returned`,
`returned` to `refunded`, and `cancelled`/`refunded` are terminal. The service
layer validates every transition against that map before updating, and raises a
domain error for an invalid one. So an illegal move like `shipped` back to
`pending` is impossible, and the rules live in one place."

### Q8. How would you scale this beyond a single instance?

**Sample answer:**
"The architecture is already stateless — auth is JWT-based, so any instance can
serve any request. Early on I'd add Postgres read replicas for read-heavy
endpoints and Redis caching for hot catalog data. Because reads and writes are
separated at the repository layer, routing reads to a replica is a config
change. For the API layer, I'd scale horizontally behind a load balancer. The
database is still the bottleneck, so beyond that I'd move the inventory and order
append-only tables to a partitioned or dedicated store, and use a worker queue
for emails and invoice generation. The modular boundaries mean I can extract the
inventory module into its own service if it becomes the hotspot."

### Q9. How do you test this, and what has the coverage gate taught you?

**Sample answer:**
"I wrote 200+ integration tests with pytest and httpx, driving the real API
against a test PostgreSQL database and Redis. The cases cover auth, products,
inventory movements, the full order lifecycle, and cross-module flows like
order + inventory reservation. I set a CI gate at 80% coverage so the build
fails if coverage drops. The gate pushed me to write tests for edge cases I
might otherwise skip — like over-reservation, invalid transitions, and
authorization boundaries — which is exactly where bugs live in a commerce
system."

### Q10. What would you do differently or add next?

**Sample answer:**
"CommerceOS is feature complete for its scope, but I have a clear roadmap.
The most valuable next steps are integrating a real payment gateway with
webhooks, adding background workers for email and low-stock alerts, and
committing the GitHub Actions CI workflow that's currently documented but not
in the repo. I'd also add rate limiting. On the product side, a cart and
checkout flow, coupons, and reviews. Importantly, I'd keep the modular
boundaries intact so these additions don't break the layering — that's the
whole point of the architecture."

---

_See also: [GITHUB_READINESS.md](GITHUB_READINESS.md) and
[PORTFOLIO_READINESS.md](PORTFOLIO_READINESS.md)._
