import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, AlertTriangle, ArrowRight, Package, PackageSearch, Search, ShoppingCart, TrendingUp, Warehouse } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Legend,
} from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { StatCard } from '@/components/widgets/StatCard'
import { ErrorState } from '@/components/feedback/ErrorState'
import { useAuth } from '@/lib/auth/useAuth'
import { productsApi } from '@/lib/api/products'
import { ordersApi } from '@/lib/api/orders'
import { inventoryApi } from '@/lib/api/inventory'
import { queryKeys } from '@/lib/query/queryKeys'
import { formatCurrency, formatDate } from '@/lib/utils'

const PIE_COLORS = ['#10b981', '#f59e0b', '#ef4444']

export default function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [customerSearch, setCustomerSearch] = useState('')
  const isCustomer = user?.role === 'customer'
  const canReadOrders = user?.role === 'admin' || user?.role === 'seller'
  const canReadInventory = user?.role === 'admin' || user?.role === 'inventory_manager'

  const productsQuery = useQuery({
    queryKey: queryKeys.products.list({ page: 1, page_size: 1 }),
    queryFn: () => productsApi.list({ page: 1, page_size: 1 }),
    enabled: !isCustomer,
  })

  const customerProductsQuery = useQuery({
    queryKey: queryKeys.products.list({ page: 1, page_size: 6, sort: 'newest', q: customerSearch || undefined }),
    queryFn: () => productsApi.list({ page: 1, page_size: 6, sort: 'newest', q: customerSearch || undefined }),
    enabled: isCustomer,
  })

  const ordersQuery = useQuery({
    queryKey: queryKeys.orders.list({ page: 1, page_size: 100, sort: 'newest' }),
    queryFn: () => ordersApi.list({ page: 1, page_size: 100, sort: 'newest' }),
    enabled: canReadOrders,
  })

  const customerOrdersQuery = useQuery({
    queryKey: queryKeys.orders.my({ page: 1, page_size: 5, sort: 'newest' }),
    queryFn: () => ordersApi.listMy({ page: 1, page_size: 5, sort: 'newest' }),
    enabled: isCustomer,
  })

  const inventoryQuery = useQuery({
    queryKey: queryKeys.inventory.list({ page: 1, page_size: 100, sort: 'newest' }),
    queryFn: () => inventoryApi.list({ page: 1, page_size: 100, sort: 'newest' }),
    enabled: canReadInventory,
  })

  const lowStockQuery = useQuery({
    queryKey: queryKeys.inventory.lowStock('low_stock'),
    queryFn: () => inventoryApi.lowStockReport('low_stock'),
    enabled: canReadInventory,
  })

  const outOfStockQuery = useQuery({
    queryKey: queryKeys.inventory.lowStock('out_of_stock'),
    queryFn: () => inventoryApi.lowStockReport('out_of_stock'),
    enabled: canReadInventory,
  })

  const warehousesQuery = useQuery({
    queryKey: queryKeys.warehouses.list({ page: 1, page_size: 100 }),
    queryFn: () => inventoryApi.listWarehouses({ page: 1, page_size: 100 }),
    enabled: canReadInventory,
  })

  const totalProducts = productsQuery.data?.total ?? 0
  const customerCatalogTotal = customerProductsQuery.data?.total ?? 0
  const customerOpenOrders = customerOrdersQuery.data?.items.filter((order) => ['pending', 'confirmed', 'shipped'].includes(order.status)).length ?? 0
  const totalOrders = ordersQuery.data?.total ?? 0
  const pendingOrders = ordersQuery.data?.items.filter((order) => order.status === 'pending').length ?? 0
  const lowStockCount = lowStockQuery.data?.total ?? 0
  const outOfStockCount = outOfStockQuery.data?.total ?? 0
  const warehouseCount = warehousesQuery.data?.total ?? 0

  const inventoryStatusCounts = useMemo(() => {
    const baseline = { in_stock: 0, low_stock: 0, out_of_stock: 0 }
    for (const item of inventoryQuery.data?.items ?? []) {
      if (item.stock_status === 'in_stock') baseline.in_stock += 1
      if (item.stock_status === 'low_stock') baseline.low_stock += 1
      if (item.stock_status === 'out_of_stock') baseline.out_of_stock += 1
    }
    return baseline
  }, [inventoryQuery.data])

  const orderStatusCounts = useMemo(() => {
    const baseline = { pending: 0, confirmed: 0, shipped: 0, delivered: 0 }
    for (const order of ordersQuery.data?.items ?? []) {
      if (order.status === 'pending') baseline.pending += 1
      if (order.status === 'confirmed') baseline.confirmed += 1
      if (order.status === 'shipped') baseline.shipped += 1
      if (order.status === 'delivered') baseline.delivered += 1
    }
    return baseline
  }, [ordersQuery.data])

  const stockAlerts = useMemo(() => {
    const map = new Map<string, { product_id: string; product_name: string; product_sku: string; warehouse_name: string; warehouse_code: string; available_quantity: number; reorder_level: number; stock_status: string }>()
    for (const item of lowStockQuery.data?.items ?? []) {
      map.set(`${item.product_id}-${item.warehouse_id}`, {
        product_id: item.product_id,
        product_name: item.product_name,
        product_sku: item.product_sku,
        warehouse_name: item.warehouse_name,
        warehouse_code: item.warehouse_code,
        available_quantity: item.available_quantity,
        reorder_level: item.reorder_level,
        stock_status: item.stock_status,
      })
    }
    for (const item of outOfStockQuery.data?.items ?? []) {
      map.set(`${item.product_id}-${item.warehouse_id}`, {
        product_id: item.product_id,
        product_name: item.product_name,
        product_sku: item.product_sku,
        warehouse_name: item.warehouse_name,
        warehouse_code: item.warehouse_code,
        available_quantity: item.available_quantity,
        reorder_level: item.reorder_level,
        stock_status: item.stock_status,
      })
    }
    return Array.from(map.values()).slice(0, 5)
  }, [lowStockQuery.data, outOfStockQuery.data])

  const recentOrders = ordersQuery.data?.items.slice(0, 5) ?? []

  const stockChartData = [
    { name: 'In stock', value: inventoryStatusCounts.in_stock },
    { name: 'Low stock', value: inventoryStatusCounts.low_stock },
    { name: 'Out of stock', value: inventoryStatusCounts.out_of_stock },
  ]

  const orderFlowData = [
    { name: 'Pending', value: orderStatusCounts.pending },
    { name: 'Confirmed', value: orderStatusCounts.confirmed },
    { name: 'Shipped', value: orderStatusCounts.shipped },
    { name: 'Delivered', value: orderStatusCounts.delivered },
  ]

  const hasError =
    isCustomer
      ? customerProductsQuery.isError || customerOrdersQuery.isError
      : productsQuery.isError || ordersQuery.isError || inventoryQuery.isError || lowStockQuery.isError || outOfStockQuery.isError || warehousesQuery.isError

  return (
    <div className="space-y-4">
      {isCustomer ? (
        <>
          <div className="space-y-1">
            <p className="text-sm font-medium uppercase tracking-[0.12em] text-muted-foreground">Customer overview</p>
            <h1 className="text-3xl font-bold tracking-tight">Catalog & orders</h1>
            <p className="text-sm text-muted-foreground">
              Browse products and review the latest status of your orders.
            </p>
          </div>

          {hasError ? (
            <ErrorState
              title="Failed to load your catalog"
              message="Your product catalog or recent orders could not be loaded."
              onRetry={() => {
                customerProductsQuery.refetch()
                customerOrdersQuery.refetch()
              }}
            />
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-3">
                <StatCard
                  title="Catalog Items"
                  value={customerCatalogTotal}
                  description="Active products"
                  icon={<PackageSearch className="h-4 w-4" />}
                  loading={customerProductsQuery.isLoading}
                />
                <StatCard
                  title="Open Orders"
                  value={customerOpenOrders}
                  description="In progress"
                  icon={<ShoppingCart className="h-4 w-4" />}
                  loading={customerOrdersQuery.isLoading}
                />
                <StatCard
                  title="Recent Spend"
                  value={
                    customerOrdersQuery.data?.items.reduce(
                      (sum, order) => sum + Number(order.total || 0),
                      0,
                    )
                      ? formatCurrency(
                          customerOrdersQuery.data?.items.reduce(
                            (sum, order) => sum + Number(order.total || 0),
                            0,
                          ) ?? 0,
                        )
                      : '—'
                  }
                  description="Latest purchases"
                  icon={<TrendingUp className="h-4 w-4" />}
                  loading={customerOrdersQuery.isLoading}
                />
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.45fr_0.9fr]">
                <Card>
                  <CardHeader className="flex flex-col gap-3 pb-3 md:flex-row md:items-center md:justify-between">
                    <CardTitle>Product catalog</CardTitle>
                    <div className="relative w-full md:max-w-xs">
                      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input
                        placeholder="Search products"
                        value={customerSearch}
                        onChange={(event) => setCustomerSearch(event.target.value)}
                        className="pl-8"
                      />
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="grid gap-3 md:grid-cols-2">
                      {(customerProductsQuery.data?.items ?? []).map((product) => (
                        <div key={product.id} className="rounded-lg border bg-muted/20 p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-lg font-semibold">{product.name}</p>
                              <p className="text-sm text-muted-foreground">{product.brand || 'General'} · {product.category || 'Catalog'}</p>
                            </div>
                            <StatusBadge status={product.status} />
                          </div>
                          <p className="mt-3 line-clamp-2 text-sm text-muted-foreground">
                            {product.short_description || product.description || 'No description provided.'}
                          </p>
                          <div className="mt-4 flex items-center justify-between gap-3">
                            <div>
                              <div className="text-lg font-semibold">{formatCurrency(product.price, product.currency)}</div>
                              <div className="text-xs text-muted-foreground">{product.sku}</div>
                            </div>
                            <Button variant="outline" size="sm" onClick={() => navigate('/products')}>
                              View catalog
                              <ArrowRight className="ml-2 h-4 w-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                    {(customerProductsQuery.data?.items ?? []).length === 0 && (
                      <div className="rounded-xl border border-dashed bg-muted/20 p-6 text-center text-sm text-muted-foreground">
                        No active products match your search.
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="flex items-center justify-between pb-3">
                    <CardTitle>Recent orders</CardTitle>
                    <Button variant="ghost" size="sm" onClick={() => navigate('/orders')}>
                      View all
                    </Button>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {(customerOrdersQuery.data?.items ?? []).length === 0 ? (
                      <div className="rounded-xl border border-dashed bg-muted/20 p-6 text-center text-sm text-muted-foreground">
                        No recent orders yet.
                      </div>
                    ) : (
                      customerOrdersQuery.data?.items.map((order) => (
                        <div key={order.id} className="rounded-lg border bg-muted/20 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="font-medium">{order.order_number}</div>
                              <div className="text-xs text-muted-foreground">{formatDate(order.created_at)}</div>
                            </div>
                            <StatusBadge status={order.status} />
                          </div>
                          <div className="mt-3 flex items-center justify-between text-sm">
                            <span className="text-muted-foreground">{order.items.length} items</span>
                            <span className="font-medium">{formatCurrency(order.total)}</span>
                          </div>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </>
      ) : (
        <>
          <div className="space-y-1">
            <p className="text-sm font-medium uppercase tracking-[0.12em] text-muted-foreground">Operations overview</p>
            <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
            <p className="text-sm text-muted-foreground">
              Inventory, orders, and fulfillment status across the network.
            </p>
          </div>

          {hasError ? (
            <ErrorState
              title="Failed to load dashboard"
              message="Some dashboard data could not be loaded."
              onRetry={() => {
                productsQuery.refetch()
                ordersQuery.refetch()
                inventoryQuery.refetch()
                lowStockQuery.refetch()
                outOfStockQuery.refetch()
                warehousesQuery.refetch()
              }}
            />
          ) : (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <StatCard
                  title="Total Products"
                  value={totalProducts}
                  description="Catalog coverage"
                  icon={<Package className="h-4 w-4" />}
                  loading={productsQuery.isLoading}
                />
                <StatCard
                  title="Pending Orders"
                  value={pendingOrders}
                  description="Awaiting action"
                  icon={<ShoppingCart className="h-4 w-4" />}
                  loading={ordersQuery.isLoading}
                />
                <StatCard
                  title="Low Stock"
                  value={lowStockCount + outOfStockCount}
                  description="Need replenishment"
                  icon={<AlertTriangle className="h-4 w-4" />}
                  loading={lowStockQuery.isLoading || outOfStockQuery.isLoading}
                />
                <StatCard
                  title="Active Warehouses"
                  value={warehouseCount}
                  description="Operational sites"
                  icon={<Warehouse className="h-4 w-4" />}
                  loading={warehousesQuery.isLoading}
                />
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.25fr_1.15fr]">
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between pb-3">
                    <CardTitle>Inventory Health</CardTitle>
                    <Activity className="h-4 w-4 text-muted-foreground" />
                  </CardHeader>
                  <CardContent>
                    <div className="h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={stockChartData}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            innerRadius={55}
                            outerRadius={92}
                            paddingAngle={3}
                          >
                            {stockChartData.map((entry, index) => (
                              <Cell key={entry.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                            ))}
                          </Pie>
                          <Tooltip />
                          <Legend />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle>Order Status</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-72">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={orderFlowData}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} />
                          <XAxis dataKey="name" tickLine={false} axisLine={false} />
                          <YAxis allowDecimals={false} tickLine={false} axisLine={false} />
                          <Tooltip />
                          <Bar dataKey="value" fill="#2563eb" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
                <Card>
                  <CardHeader className="flex flex-row items-center justify-between pb-3">
                    <CardTitle>Recent orders</CardTitle>
                    <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
                      {totalOrders} total
                    </span>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {recentOrders.length === 0 ? (
                      <div className="rounded-xl border border-dashed bg-muted/20 p-6 text-center text-sm text-muted-foreground">
                        No recent orders available.
                      </div>
                    ) : (
                      recentOrders.map((order) => (
                        <div key={order.id} className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 p-3">
                          <div>
                            <div className="font-medium">{order.order_number}</div>
                            <div className="text-xs text-muted-foreground">
                              {order.customer_id.slice(0, 8)} · {formatDate(order.created_at)}
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="font-medium">{formatCurrency(order.total)}</div>
                            <div className="mt-1"><StatusBadge status={order.status} /></div>
                          </div>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle>Low-stock products</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {stockAlerts.length === 0 ? (
                      <div className="rounded-xl border border-dashed bg-muted/20 p-6 text-center text-sm text-muted-foreground">
                        All products are within target stock levels.
                      </div>
                    ) : (
                      stockAlerts.map((item) => (
                        <div key={`${item.product_id}-${item.warehouse_name}`} className="rounded-lg border bg-muted/20 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="font-medium">{item.product_name}</div>
                              <div className="text-xs text-muted-foreground">{item.product_sku}</div>
                            </div>
                            <StatusBadge status={item.stock_status} />
                          </div>
                          <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                            <span>{item.warehouse_name}</span>
                            <span>{item.available_quantity} available</span>
                          </div>
                          <div className="mt-2 h-2 rounded-full bg-muted">
                            <div
                              className="h-2 rounded-full bg-amber-500"
                              style={{ width: `${Math.max(18, (item.available_quantity / Math.max(item.reorder_level, 1)) * 100)}%` }}
                            />
                          </div>
                        </div>
                      ))
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
