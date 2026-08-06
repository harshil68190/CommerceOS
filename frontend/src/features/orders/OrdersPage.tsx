import { useState } from 'react'
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
  const { data, isLoading, error, refetch } = isCustomer
    ? useMyOrders({ page, page_size: 20, sort: 'newest' })
    : useOrders(adminFilters)

  const orders = data?.items ?? []
  const pages = data?.pages ?? 1
  const total = data?.total ?? 0

  const columns: Column<Order>[] = [
    { key: 'order_number', header: 'Order', cell: (o) => <span className="font-medium">{o.order_number}</span> },
    { key: 'customer', header: 'Customer', cell: (o) => o.customer_id.slice(0, 8) },
    { key: 'total', header: 'Total', cell: (o) => formatCurrency(o.total) },
    { key: 'status', header: 'Status', cell: (o) => <StatusBadge status={o.status} /> },
    { key: 'payment', header: 'Payment', cell: (o) => <StatusBadge status={o.payment_status} /> },
    { key: 'created', header: 'Created', cell: (o) => formatDate(o.created_at) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Orders</h1>
          <p className="text-sm text-muted-foreground">
            {isCustomer ? 'Your orders' : 'Manage all orders'}
          </p>
        </div>
        {!isCustomer && (
          <div className="w-48">
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

      <Card>
        <CardHeader>
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
            onRowClick={(o) => navigate(`/orders/${o.id}`)}
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
