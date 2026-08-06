import { useQuery } from '@tanstack/react-query'
import {
  Package,
  ShoppingCart,
  Warehouse as WarehouseIcon,
  AlertTriangle,
  TrendingUp,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatCard } from '@/components/widgets/StatCard'
import { ErrorState } from '@/components/feedback/ErrorState'
import { useAuth } from '@/lib/auth/useAuth'
import { productsApi } from '@/lib/api/products'
import { ordersApi } from '@/lib/api/orders'
import { inventoryApi } from '@/lib/api/inventory'
import { queryKeys } from '@/lib/query/queryKeys'

const PIE_COLORS = ['#10b981', '#f59e0b', '#ef4444']

export default function DashboardPage() {
  const { user } = useAuth()

  const productsQuery = useQuery({
    queryKey: queryKeys.products.list({ page: 1, page_size: 1 }),
    queryFn: () => productsApi.list({ page: 1, page_size: 1 }),
  })

  const ordersQuery = useQuery({
    queryKey: queryKeys.orders.list({ page: 1, page_size: 1 }),
    queryFn: () => ordersApi.list({ page: 1, page_size: 1 }),
    enabled: user?.role !== 'customer',
  })

  const lowStockQuery = useQuery({
    queryKey: queryKeys.inventory.lowStock('low_stock'),
    queryFn: () => inventoryApi.lowStockReport('low_stock'),
    enabled: user?.role !== 'customer',
  })

  const outOfStockQuery = useQuery({
    queryKey: queryKeys.inventory.lowStock('out_of_stock'),
    queryFn: () => inventoryApi.lowStockReport('out_of_stock'),
    enabled: user?.role !== 'customer',
  })

  const warehousesQuery = useQuery({
    queryKey: queryKeys.warehouses.list({ page: 1, page_size: 100 }),
    queryFn: () => inventoryApi.listWarehouses({ page: 1, page_size: 100 }),
    enabled: user?.role !== 'customer',
  })

  const totalProducts = productsQuery.data?.total ?? 0
  const totalOrders = ordersQuery.data?.total ?? 0
  const lowStockCount = lowStockQuery.data?.total ?? 0
  const outOfStockCount = outOfStockQuery.data?.total ?? 0
  const warehouseCount = warehousesQuery.data?.total ?? 0

  const hasError =
    productsQuery.isError ||
    (user?.role !== 'customer' &&
      (ordersQuery.isError || lowStockQuery.isError || outOfStockQuery.isError || warehousesQuery.isError))

  const stockData = [
    { name: 'In Stock', value: 100 - lowStockCount - outOfStockCount },
    { name: 'Low Stock', value: lowStockCount },
    { name: 'Out of Stock', value: outOfStockCount },
  ]

  const orderStatusData = [
    { name: 'Total', value: totalOrders },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Welcome back{user ? `, ${user.first_name}` : ''}
        </p>
      </div>

      {hasError ? (
        <ErrorState
          title="Failed to load dashboard"
          message="Some dashboard data could not be loaded."
          onRetry={() => {
            productsQuery.refetch()
            ordersQuery.refetch()
            lowStockQuery.refetch()
            outOfStockQuery.refetch()
            warehousesQuery.refetch()
          }}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Total Products"
              value={totalProducts}
              icon={<Package className="h-5 w-5" />}
              loading={productsQuery.isLoading}
            />
            {user?.role !== 'customer' && (
              <StatCard
                title="Total Orders"
                value={totalOrders}
                icon={<ShoppingCart className="h-5 w-5" />}
                loading={ordersQuery.isLoading}
              />
            )}
            {user?.role !== 'customer' && (
              <StatCard
                title="Warehouses"
                value={warehouseCount}
                icon={<WarehouseIcon className="h-5 w-5" />}
                loading={warehousesQuery.isLoading}
              />
            )}
            {user?.role !== 'customer' && (
              <StatCard
                title="Low Stock"
                value={lowStockCount + outOfStockCount}
                icon={<AlertTriangle className="h-5 w-5" />}
                loading={lowStockQuery.isLoading}
              />
            )}
          </div>

          {user?.role !== 'customer' && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="flex-row items-center justify-between space-y-0">
                  <CardTitle>Stock Health</CardTitle>
                  <TrendingUp className="h-4 w-4 text-muted-foreground" />
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie
                        data={stockData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={90}
                        label
                      >
                        {stockData.map((entry, index) => (
                          <Cell key={entry.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip />
                      <Legend />
                    </PieChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Orders Overview</CardTitle>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={orderStatusData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" />
                      <YAxis allowDecimals={false} />
                      <Tooltip formatter={(value) => [`${value}`, 'Orders']} />
                      <Bar dataKey="value" fill="#10b981" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          )}

          {lowStockCount > 0 && user?.role !== 'customer' && (
            <Card>
              <CardHeader>
                <CardTitle>Low Stock Alerts</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  {lowStockCount} products are running low on stock. Visit the Inventory page to
                  manage stock levels.
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {user?.role === 'customer' && (
        <Card>
          <CardHeader>
            <CardTitle>Welcome</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Browse the product catalog and manage your orders from the sidebar.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
