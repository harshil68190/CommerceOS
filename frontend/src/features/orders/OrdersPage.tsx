import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { DataTable, type Column } from '@/components/data/DataTable'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { useOrders, useMyOrders } from '@/features/orders/hooks'
import { useAuth } from '@/lib/auth/useAuth'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { Order } from '@/types/api'

export default function OrdersPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string>('')

  const isCustomer = user?.role === 'customer'
  const adminFilters = { page, page_size: 20, sort: 'newest', status: status || undefined }
  const customerOrders = useMyOrders({ page, page_size: 20, sort: 'newest' }, isCustomer)
  const adminOrders = useOrders(adminFilters, !isCustomer)
  const { data, isLoading, error, refetch } = isCustomer ? customerOrders : adminOrders

  const orders = useMemo(() => data?.items ?? [], [data?.items])
  const pages = data?.pages ?? 1
  const total = data?.total ?? 0

  const summary = useMemo(() => {
    const counts = { pending: 0, confirmed: 0, shipped: 0, delivered: 0 }
    for (const order of orders) {
      if (order.status in counts) counts[order.status as keyof typeof counts] += 1
    }
    return counts
  }, [orders])

  const columns: Column<Order>[] = [
    {
      key: 'order_number',
      header: 'Order',
      cell: (o) => (
        <div>
          <div className="font-medium">{o.order_number}</div>
          <div className="text-xs text-muted-foreground">{formatDate(o.created_at)}</div>
        </div>
      ),
    },
    {
      key: 'customer',
      header: 'Customer',
      cell: (o) => (
        <div>
          <div className="font-medium">{o.customer_id.slice(0, 8)}</div>
          <div className="text-xs text-muted-foreground">{o.items.length} items</div>
        </div>
      ),
    },
    { key: 'total', header: 'Total', cell: (o) => <span className="font-medium">{formatCurrency(o.total)}</span> },
    { key: 'status', header: 'Status', cell: (o) => <StatusBadge status={o.status} /> },
    { key: 'payment', header: 'Payment', cell: (o) => <StatusBadge status={o.payment_status} /> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Orders</h1>
          <p className="text-sm text-muted-foreground">
            {isCustomer ? 'Your orders' : 'Manage all orders'}
          </p>
        </div>
        {!isCustomer && (
          <div className="w-full max-w-52">
            <Select value={status} onValueChange={(v) => { setStatus(v === 'all' ? '' : v); setPage(1) }}>
              <SelectTrigger>
                <SelectValue placeholder="Filter by status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="confirmed">Confirmed</SelectItem>
                <SelectItem value="shipped">Shipped</SelectItem>
                <SelectItem value="delivered">Delivered</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
                <SelectItem value="returned">Returned</SelectItem>
                <SelectItem value="refunded">Refunded</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {!isCustomer && (
        <div className="grid gap-3 md:grid-cols-4">
          {[
            { label: 'Pending', value: summary.pending },
            { label: 'Confirmed', value: summary.confirmed },
            { label: 'Shipped', value: summary.shipped },
            { label: 'Delivered', value: summary.delivered },
          ].map((item) => (
            <Card key={item.label} className="border-0 bg-muted/30 shadow-sm">
              <CardContent className="flex items-center justify-between p-4">
                <div>
                  <div className="text-sm text-muted-foreground">{item.label}</div>
                  <div className="text-2xl font-semibold">{item.value}</div>
                </div>
                <StatusBadge status={item.label.toLowerCase()} />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>{isCustomer ? 'My Orders' : 'All Orders'}</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable<Order>
            columns={columns}
            data={orders}
            loading={isLoading}
            error={error}
            onRetry={refetch}
            rowKey={(o) => o.id}
            onRowClick={isCustomer ? undefined : (o) => navigate(`/orders/${o.id}`)}
            page={page}
            pages={pages}
            total={total}
            onPageChange={setPage}
            emptyMessage="No orders found."
          />
        </CardContent>
      </Card>
    </div>
  )
}
