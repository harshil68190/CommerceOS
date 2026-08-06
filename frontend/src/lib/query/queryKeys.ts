/** Centralized React Query key factories for consistent invalidation. */
export const queryKeys = {
  auth: {
    me: ['auth', 'me'] as const,
  },
products: {
    all: ['products'] as const,
    list: (filters: object) => ['products', 'list', filters] as const,
    admin: (filters: object) => ['products', 'admin', filters] as const,
    detail: (id: string) => ['products', 'detail', id] as const,
    slug: (slug: string) => ['products', 'slug', slug] as const,
  },
  warehouses: {
    all: ['warehouses'] as const,
    list: (filters: object) => ['warehouses', 'list', filters] as const,
    detail: (id: string) => ['warehouses', 'detail', id] as const,
  },
  inventory: {
    all: ['inventory'] as const,
    list: (filters: object) => ['inventory', 'list', filters] as const,
    product: (id: string) => ['inventory', 'product', id] as const,
    transactions: (filters: object) =>
      ['inventory', 'transactions', filters] as const,
    lowStock: (status: string) => ['inventory', 'low-stock', status] as const,
  },
  orders: {
    all: ['orders'] as const,
    list: (filters: object) => ['orders', 'list', filters] as const,
    my: (filters: object) => ['orders', 'my', filters] as const,
    detail: (id: string) => ['orders', 'detail', id] as const,
  },
} as const
