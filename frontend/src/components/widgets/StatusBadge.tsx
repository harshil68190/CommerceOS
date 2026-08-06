import { Badge } from '@/components/ui/badge'
import { humanize } from '@/lib/utils'

const STATUS_VARIANTS: Record<string, 'success' | 'warning' | 'destructive' | 'muted' | 'secondary' | 'default'> = {
  // Product
  active: 'success',
  draft: 'muted',
  archived: 'secondary',
  out_of_stock: 'destructive',
  // Inventory / stock
  in_stock: 'success',
  low_stock: 'warning',
  // Order
  pending: 'warning',
  confirmed: 'secondary',
  shipped: 'secondary',
  delivered: 'success',
  cancelled: 'destructive',
  returned: 'muted',
  refunded: 'muted',
  // Payment
  unpaid: 'warning',
  authorized: 'secondary',
  paid: 'success',
  failed: 'destructive',
  refunded_fallback: 'muted',
}

/** Renders a colored badge for a backend status enum value. */
export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge variant="outline">—</Badge>
  const variant = STATUS_VARIANTS[status] ?? 'secondary'
  return <Badge variant={variant}>{humanize(status)}</Badge>
}
