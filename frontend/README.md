# CommerceOS — Frontend

The **React + TypeScript** single-page application for CommerceOS. It is a
role-aware admin/operations console for managing products, multi-warehouse
inventory, and the full order lifecycle — built with Vite, TanStack Query,
shadcn/ui, and Tailwind CSS.

> This is the frontend half of the CommerceOS monorepo. See the
> [root README](../README.md) for the full project, and
> [backend/README.md](../backend/README.md) for the API it consumes.

---

## Table of Contents

- [Stack](#stack)
- [Getting Started](#getting-started)
- [Dev Proxy](#dev-proxy)
- [Project Structure](#project-structure)
- [Key Design Decisions](#key-design-decisions)
- [Scripts](#scripts)
- [Environment Variables](#environment-variables)
- [Production Build](#production-build)

---

## Stack

| Concern | Technology |
|---------|-----------|
| Framework | React 18 + Vite 5 |
| Language | TypeScript 5.6 (strict) |
| Routing | React Router 6 |
| Server state | TanStack Query 5 |
| HTTP client | Axios (auth interceptor + refresh-once) |
| Forms / Validation | React Hook Form + Zod |
| Styling | Tailwind CSS 3 + shadcn/ui (Radix primitives) |
| Charts | Recharts |
| Client state | Zustand (theme, toasts) |
| Linting / Formatting | ESLint 9 |

---

## Getting Started

### Prerequisites

- Node.js 20+ and npm
- A running CommerceOS backend (see [backend/README.md](../backend/README.md))
  — either native or via Docker Compose.

### Install & run

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to the
backend at `http://localhost:8000` (configurable via `VITE_API_TARGET`).

Register a new account, then either use it as a **customer** or promote a user
to an admin/inventory-manager role in the database to access the full back-
office functionality.

---

## Dev Proxy

`vite.config.ts` proxies `/api` to the backend to avoid CORS issues in dev:

```ts
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: process.env.VITE_API_TARGET || 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

---

## Project Structure

```
frontend/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── package.json
└── src/
    ├── App.tsx                 # Router + providers wiring
    ├── main.tsx                # React entry
    ├── components/
    │   ├── data/               # DataTable
    │   ├── feedback/           # ErrorState, LoadingState, FullScreenLoader
    │   ├── layout/             # AppLayout, Sidebar, Topbar, ProtectedRoute, RoleGate
    │   ├── ui/                 # shadcn/ui primitives (button, dialog, table, ...)
    │   └── widgets/            # StatCard, StatusBadge
    ├── features/
    │   ├── auth/               # LoginPage, RegisterPage
    │   ├── dashboard/          # DashboardPage (KPI + charts)
    │   ├── products/           # ProductsPage, ProductFormDialog, hooks
    │   ├── inventory/          # InventoryPage, WarehousesPage, StockMovementDialog, ...
    │   ├── orders/             # OrdersPage, OrderDetailPage, hooks
    │   ├── profile/            # ProfilePage
    │   └── NotFoundPage.tsx
    ├── lib/
    │   ├── api/                # axios client + per-domain API modules
    │   ├── auth/               # token storage + useAuth hook/store
    │   ├── query/              # queryClient + queryKeys
    │   ├── validators/         # zod schemas mirroring backend
    │   └── utils.ts
    ├── stores/                 # zustand stores (theme, toast)
    └── types/                  # shared TS types (mirror backend schemas)
```

---

## Key Design Decisions

### Server state via TanStack Query
All data fetching is declarative with `useQuery`/`useMutation`, keyed through
`lib/query/queryKeys.ts` for consistent cache invalidation across pages.

### Axios client with refresh-once
`lib/api/client.ts` centralizes the HTTP layer:

- Attaches the bearer token on every request.
- On a **401**, a **single shared refresh Promise** obtains a new token pair
  (single-flight, so concurrent 401s don't each trigger a refresh), retries the
  original request once, and otherwise clears the session.
- Normalizes every error into an `ApiClientError` carrying `errorCode`,
  `status`, `details`, and `requestId` — matching the backend's centralized
  error envelope.

### Role-gated UI
`ProtectedRoute` guards authenticated routes; `RoleGate` conditionally renders
admin/seller/inventory-manager-only controls based on the current user's role.

### Feature-sliced pages
Each domain (`products`, `inventory`, `orders`) owns its pages, its
`hooks.ts` (TanStack Query hooks), and its dialogs, keeping related code
colocated.

### Zod schemas mirror the backend
`lib/validators/*` define the same request shapes the FastAPI Pydantic schemas
enforce, so invalid forms fail fast client-side.

---

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start the Vite dev server (port 5173, hot reload) |
| `npm run build` | Type-check (`tsc -b`) then produce a production build to `dist/` |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | Run ESLint over the source |
| `npm run typegen` | Generate TS types from the backend OpenAPI schema |

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_URL` | `/api/v1` | Base URL for the API (set to the deployed backend origin in production) |
| `VITE_API_TARGET` | `http://localhost:8000` | Dev-only: backend target for the Vite proxy |

Environment files: `.env.development` and `.env.production` are committed at
the frontend root.

---

## Production Build

```bash
npm run build   # outputs static files to dist/
npm run preview # serve the production build locally to verify
```

To deploy, serve the `dist/` directory from any static host (or a CDN) and set
`VITE_API_URL` to the deployed backend's origin. The SPA is configured for
client-side routing (BrowserRouter), so the host must rewrite unknown paths to
`index.html`.

> **Note:** A production Dockerfile for the frontend and its wiring into the
> deployment stack is a planned improvement (see the root
> [README](../README.md#future-improvements--roadmap)). Currently the frontend
> runs via `npm run dev` in development.
