import { useState } from 'react'
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

  const warehouses = data?.items ?? []
  const pages = data?.pages ?? 1
  const total = data?.total ?? 0

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
      header: 'Name',
      cell: (w) => (
        <div>
          <div className="font-medium">{w.name}</div>
          <div className="text-xs text-muted-foreground">{w.code}</div>
        </div>
      ),
    },
    { key: 'city', header: 'City', cell: (w) => w.city || '—' },
    { key: 'country', header: 'Country', cell: (w) => w.country || '—' },
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Warehouses</h1>
          <p className="text-sm text-muted-foreground">Manage warehouse locations</p>
        </div>
        <RoleGate roles={['admin']}>
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" />
            New Warehouse
          </Button>
        </RoleGate>
      </div>

      <Card>
        <CardHeader>
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
