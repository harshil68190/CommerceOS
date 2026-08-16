import { useMemo, useState } from 'react'
import { Plus, Pencil, Power, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { DataTable, type Column } from '@/components/data/DataTable'
import { RoleGate } from '@/components/layout/RoleGate'
import { WarehouseFormDialog } from '@/features/inventory/WarehouseFormDialog'
import {
  useWarehouses,
  useDeactivateWarehouse,
  useReactivateWarehouse,
  useInventory,
} from '@/features/inventory/hooks'
import { toast } from '@/stores/toastStore'
import type { Warehouse } from '@/types/api'

export default function WarehousesPage() {
  const [page, setPage] = useState(1)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Warehouse | null>(null)

  const deactivateMutation = useDeactivateWarehouse()
  const reactivateMutation = useReactivateWarehouse()

  const { data, isLoading, error, refetch } = useWarehouses({
    page,
    page_size: 20,
    sort: 'newest',
  })

  const { data: inventoryData } = useInventory({ page: 1, page_size: 200, sort: 'newest' })

  const warehouses = data?.items ?? []
  const pages = data?.pages ?? 1
  const total = data?.total ?? 0

  const inventoryByWarehouse = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const entry of inventoryData?.items ?? []) {
      counts[entry.warehouse_id] = (counts[entry.warehouse_id] ?? 0) + 1
    }
    return counts
  }, [inventoryData])

  const activeWarehouses = warehouses.filter((warehouse) => warehouse.is_active).length
  const inactiveWarehouses = warehouses.filter((warehouse) => !warehouse.is_active).length

  async function handleDeactivate(w: Warehouse) {
    if (!window.confirm(`Deactivate "${w.name}"?`)) return
    try {
      await deactivateMutation.mutateAsync(w.id)
      toast({ title: 'Warehouse deactivated', variant: 'success' })
    } catch {
      toast({ title: 'Error deactivating warehouse', variant: 'destructive' })
    }
  }

  async function handleReactivate(w: Warehouse) {
    try {
      await reactivateMutation.mutateAsync(w.id)
      toast({ title: 'Warehouse reactivated', variant: 'success' })
    } catch {
      toast({ title: 'Error reactivating warehouse', variant: 'destructive' })
    }
  }

  const columns: Column<Warehouse>[] = [
    {
      key: 'name',
      header: 'Warehouse',
      cell: (w) => (
        <div>
          <div className="font-medium">{w.name}</div>
          <div className="text-xs text-muted-foreground">{w.code}</div>
        </div>
      ),
    },
    {
      key: 'location',
      header: 'Location',
      cell: (w) => (
        <div className="text-sm text-muted-foreground">
          {w.city || '—'}{w.city && w.country ? ', ' : ''}{w.country || ''}
        </div>
      ),
    },
    {
      key: 'inventory',
      header: 'Inventory items',
      cell: (w) => <span className="font-medium">{inventoryByWarehouse[w.id] ?? 0}</span>,
    },
    {
      key: 'active',
      header: 'Status',
      cell: (w) =>
        w.is_active ? <Badge variant="success">Active</Badge> : <Badge variant="muted">Inactive</Badge>,
    },
    {
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      cell: (w) => (
        <div className="flex justify-end gap-1">
          <RoleGate roles={['admin']}>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation()
                setEditing(w)
                setFormOpen(true)
              }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
            {w.is_active ? (
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive"
                onClick={(e) => {
                  e.stopPropagation()
                  handleDeactivate(w)
                }}
              >
                <Power className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation()
                  handleReactivate(w)
                }}
              >
                <RotateCcw className="h-4 w-4" />
              </Button>
            )}
          </RoleGate>
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Warehouses</h1>
          <p className="text-sm text-muted-foreground">Network operations and fulfillment locations</p>
        </div>
        <RoleGate roles={['admin']}>
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" />
            New Warehouse
          </Button>
        </RoleGate>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <Card className="border-0 bg-muted/30 shadow-sm">
          <CardContent className="flex items-center justify-between p-4">
            <div>
              <div className="text-sm text-muted-foreground">Active</div>
              <div className="text-2xl font-semibold">{activeWarehouses}</div>
            </div>
            <Badge variant="success">Online</Badge>
          </CardContent>
        </Card>
        <Card className="border-0 bg-muted/30 shadow-sm">
          <CardContent className="flex items-center justify-between p-4">
            <div>
              <div className="text-sm text-muted-foreground">Inactive</div>
              <div className="text-2xl font-semibold">{inactiveWarehouses}</div>
            </div>
            <Badge variant="muted">Paused</Badge>
          </CardContent>
        </Card>
        <Card className="border-0 bg-muted/30 shadow-sm">
          <CardContent className="flex items-center justify-between p-4">
            <div>
              <div className="text-sm text-muted-foreground">Total</div>
              <div className="text-2xl font-semibold">{total}</div>
            </div>
            <Badge variant="outline">Locations</Badge>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle>All Warehouses</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable<Warehouse>
            columns={columns}
            data={warehouses}
            loading={isLoading}
            error={error}
            onRetry={refetch}
            rowKey={(w) => w.id}
            page={page}
            pages={pages}
            total={total}
            onPageChange={setPage}
            emptyMessage="No warehouses found."
          />
        </CardContent>
      </Card>

      <WarehouseFormDialog open={formOpen} onOpenChange={setFormOpen} warehouse={editing} />
    </div>
  )
}
