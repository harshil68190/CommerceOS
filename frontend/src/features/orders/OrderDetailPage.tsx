import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { ErrorState } from '@/components/feedback/ErrorState'
import { LoadingState } from '@/components/feedback/LoadingState'
import { RoleGate } from '@/components/layout/RoleGate'
import { useOrder, useOrderTransition } from '@/features/orders/hooks'
import { useAuth } from '@/lib/auth/useAuth'
import { formatCurrency, formatDate } from '@/lib/utils'
import { toast } from '@/stores/toastStore'

export default function OrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()

  const { data: order, isLoading, isError, error, refetch } = useOrder(orderId || '')

  const cancelMutation = useOrderTransition('cancel')
  const confirmMutation = useOrderTransition('confirmPayment')
  const shipMutation = useOrderTransition('ship')
  const deliverMutation = useOrderTransition('deliver')
  const returnMutation = useOrderTransition('returnOrder')
  const refundMutation = useOrderTransition('refund')

  if (isLoading) return <LoadingState rows={6} />
  if (isError || !order) {
    return (
      <ErrorState
        title="Failed to load order"
        message={error instanceof Error ? error.message : undefined}
        onRetry={refetch}
      />
    )
  }

  const isOwner = user?.id === order.customer_id

async function runTransition(
    action: (id: string) => Promise<unknown>,
    label: string,
  ) {
    if (!order) return
    try {
      await action(order.id)
      toast({ title: label, variant: 'success' })
    } catch {
      toast({ title: `Failed to ${label.toLowerCase()}`, variant: 'destructive' })
    }
  }

  const mutating =
    cancelMutation.isPending ||
    confirmMutation.isPending ||
    shipMutation.isPending ||
    deliverMutation.isPending ||
    returnMutation.isPending ||
    refundMutation.isPending

  return (
    <div className="space-y-4">
      <Button variant="ghost" onClick={() => navigate('/orders')}>
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Orders
      </Button>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">{order.order_number}</h1>
          <p className="text-sm text-muted-foreground">
            Created {formatDate(order.created_at)}
          </p>
        </div>
        <Badge variant="outline">{order.status}</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Order Status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Status</span>
              <StatusBadge status={order.status} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Payment</span>
              <StatusBadge status={order.payment_status} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Version</span>
              <span>{order.version}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Totals</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Subtotal</span>
              <span>{formatCurrency(order.subtotal)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Shipping</span>
              <span>{order.shipping_cost ? formatCurrency(order.shipping_cost) : '—'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Discount</span>
              <span>{order.discount ? `-${formatCurrency(order.discount)}` : '—'}</span>
            </div>
            <Separator />
            <div className="flex items-center justify-between font-bold">
              <span>Total</span>
              <span>{formatCurrency(order.total)}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {order.status === 'pending' && (
              <>
                <RoleGate roles={['admin', 'seller']}>
                  <Button
                    className="w-full"
                    disabled={mutating}
                    onClick={() => runTransition(confirmMutation.mutateAsync, 'Payment confirmed')}
                  >
                    {confirmMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Confirm Payment
                  </Button>
                </RoleGate>
                {(isOwner || user?.role === 'admin') && (
                  <Button
                    variant="destructive"
                    className="w-full"
                    disabled={mutating}
                    onClick={() => runTransition(cancelMutation.mutateAsync, 'Order cancelled')}
                  >
                    {cancelMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Cancel Order
                  </Button>
                )}
              </>
            )}
            {order.status === 'confirmed' && (
              <RoleGate roles={['admin', 'seller']}>
                <Button
                  className="w-full"
                  disabled={mutating}
                  onClick={() => runTransition(shipMutation.mutateAsync, 'Order shipped')}
                >
                  {shipMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Ship Order
                </Button>
              </RoleGate>
            )}
            {order.status === 'shipped' && (
              <RoleGate roles={['admin', 'seller']}>
                <Button
                  className="w-full"
                  disabled={mutating}
                  onClick={() => runTransition(deliverMutation.mutateAsync, 'Order delivered')}
                >
                  {deliverMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Deliver Order
                </Button>
              </RoleGate>
            )}
            {order.status === 'delivered' && (
              <RoleGate roles={['admin', 'seller']}>
                <Button
                  className="w-full"
                  variant="outline"
                  disabled={mutating}
                  onClick={() => runTransition(returnMutation.mutateAsync, 'Return processed')}
                >
                  {returnMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Process Return
                </Button>
              </RoleGate>
            )}
            {order.status === 'returned' && (
              <RoleGate roles={['admin']}>
                <Button
                  className="w-full"
                  disabled={mutating}
                  onClick={() => runTransition(refundMutation.mutateAsync, 'Refund completed')}
                >
                  {refundMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Process Refund
                </Button>
              </RoleGate>
            )}
            {(order.status === 'cancelled' || order.status === 'refunded') && (
              <p className="text-sm text-muted-foreground">
                This order is in a terminal state.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Items</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="divide-y">
            {order.items.map((item) => (
              <div key={item.id} className="flex items-center justify-between py-3">
                <div>
                  <div className="font-medium">{item.product_name}</div>
                  <div className="text-xs text-muted-foreground">
                    {item.product_sku} · qty {item.quantity}
                  </div>
                </div>
                <div className="text-right">
                  <div className="font-medium">{formatCurrency(item.line_total)}</div>
                  <div className="text-xs text-muted-foreground">
                    {formatCurrency(item.unit_price)} each
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {order.notes && (
        <Card>
          <CardHeader>
            <CardTitle>Notes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{order.notes}</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
