import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/tabs'
import { DataTable, type Column } from '@/components/data/DataTable'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { RoleGate } from '@/components/layout/RoleGate'
import { StockMovementDialog } from '@/features/inventory/StockMovementDialog'
import {
  useInventory,
  useTransactions,
  useLowStockReport,
  useWarehouses,
} from '@/features/inventory/hooks'
import { formatDate } from '@/lib/utils'
import type { Inventory, InventoryTransaction } from '@/types/api'

type MovementMode = 'add' | 'remove' | 'adjust'

export default function InventoryPage() {
  const [page, setPage] = useState(1)
  const [txPage, setTxPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('low_stock')
  const [movementOpen, setMovementOpen] = useState(false)
  const [movementMode, setMovementMode] = useState<MovementMode>('add')
  const [selectedItem, setSelectedItem] = useState<Inventory | null>(null)

  const { data: invData, isLoading: invLoading, isError: invError, refetch: invRefetch } =
    useInventory({ page, page_size: 20, sort: 'newest' })

  const { data: txData, isLoading: txLoading, isError: txError, refetch: txRefetch } =
    useTransactions({ page: txPage, page_size: 20, sort: 'newest' })

  const { data: lowStockData, isLoading: lowLoading, isError: lowError, refetch: lowRefetch } =
    useLowStockReport(statusFilter)

  const { data: warehouseData } = useWarehouses({ page_size: 100 })

  const inventory = invData?.items ?? []
  const invPages = invData?.pages ?? 1
  const invTotal = invData?.total ?? 0

  const transactions = txData?.items ?? []
  const txPages = txData?.pages ?? 1

  const lowStockItems = lowStockData?.items ?? []

  const warehouses = warehouseData?.items ?? []

  function openMovement(mode: MovementMode, item: Inventory | null) {
    setMovementMode(mode)
    setSelectedItem(item)
    setMovementOpen(true)
  }

  const invColumns: Column<Inventory>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (i) => (
        <div>
          <div className="font-medium">{i.product_id}</div>
          <div className="text-xs text-muted-foreground">Warehouse {i.warehouse_id}</div>
        </div>
      ),
    },
    { key: 'quantity', header: 'Quantity', cell: (i) => i.quantity },
    { key: 'reserved', header: 'Reserved', cell: (i) => i.reserved_quantity },
    { key: 'available', header: 'Available', cell: (i) => i.available_quantity },
    { key: 'reorder', header: 'Reorder Level', cell: (i) => i.reorder_level },
    {
      key: 'status',
      header: 'Status',
      cell: (i) => <StatusBadge status={i.stock_status} />,
    },
    {
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      cell: (i) => (
        <RoleGate roles={['admin', 'inventory_manager']}>
          <div className="flex justify-end gap-1">
            <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); openMovement('add', i) }}>
              Add
            </Button>
            <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); openMovement('remove', i) }}>
              Remove
            </Button>
            <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); openMovement('adjust', i) }}>
              Adjust
            </Button>
          </div>
        </RoleGate>
      ),
    },
  ]

  const txColumns: Column<InventoryTransaction>[] = [
    { key: 'type', header: 'Type', cell: (t) => <StatusBadge status={t.transaction_type} /> },
    { key: 'quantity', header: 'Qty', cell: (t) => t.quantity },
    {
      key: 'change',
      header: 'Change',
      cell: (t) => `${t.previous_quantity} → ${t.new_quantity}`,
    },
    { key: 'reference', header: 'Reference', cell: (t) => t.reference_number || '—' },
    { key: 'created', header: 'Date', cell: (t) => formatDate(t.created_at) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Inventory</h1>
          <p className="text-sm text-muted-foreground">Manage stock across warehouses</p>
        </div>
        <RoleGate roles={['admin', 'inventory_manager']}>
          <Button onClick={() => openMovement('add', null)}>
            <Plus className="mr-2 h-4 w-4" />
            Add Stock
          </Button>
        </RoleGate>
      </div>

      <Tabs defaultValue="inventory">
        <TabsList>
          <TabsTrigger value="inventory">Inventory</TabsTrigger>
          <TabsTrigger value="transactions">Transactions</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
        </TabsList>

        <TabsContent value="inventory">
          <Card>
            <CardHeader>
              <CardTitle>Inventory Records</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable<Inventory>
                columns={invColumns}
                data={inventory}
                loading={invLoading}
                error={invError}
                onRetry={invRefetch}
                rowKey={(i) => i.id}
                page={page}
                pages={invPages}
                total={invTotal}
                onPageChange={setPage}
                emptyMessage="No inventory records found."
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="transactions">
          <Card>
            <CardHeader>
              <CardTitle>Transaction History</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable<InventoryTransaction>
                columns={txColumns}
                data={transactions}
                loading={txLoading}
                error={txError}
                onRetry={txRefetch}
                rowKey={(t) => t.id}
                page={txPage}
                pages={txPages}
                onPageChange={setTxPage}
                emptyMessage="No transactions found."
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="reports">
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle>Stock Reports</CardTitle>
              <div className="flex gap-2">
                <Button
                  variant={statusFilter === 'low_stock' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setStatusFilter('low_stock')}
                >
                  Low Stock
                </Button>
                <Button
                  variant={statusFilter === 'out_of_stock' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setStatusFilter('out_of_stock')}
                >
                  Out of Stock
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <DataTable
                columns={[
                  { key: 'name', header: 'Product', cell: (i: { product_name: string; product_sku: string }) => (
                    <div>
                      <div className="font-medium">{i.product_name}</div>
                      <div className="text-xs text-muted-foreground">{i.product_sku}</div>
                    </div>
                  ) },
                  { key: 'warehouse', header: 'Warehouse', cell: (i: { warehouse_name: string; warehouse_code: string }) => (
                    <div>
                      <div>{i.warehouse_name}</div>
                      <div className="text-xs text-muted-foreground">{i.warehouse_code}</div>
                    </div>
                  ) },
                  { key: 'available', header: 'Available', cell: (i: { available_quantity: number }) => i.available_quantity },
                  { key: 'qty', header: 'Quantity', cell: (i: { quantity: number }) => i.quantity },
                  { key: 'reserved', header: 'Reserved', cell: (i: { reserved_quantity: number }) => i.reserved_quantity },
                  { key: 'reorder', header: 'Reorder Level', cell: (i: { reorder_level: number }) => i.reorder_level },
                  { key: 'status', header: 'Status', cell: (i: { stock_status: string }) => <StatusBadge status={i.stock_status} /> },
                ]}
                data={lowStockItems}
                loading={lowLoading}
                error={lowError}
                onRetry={lowRefetch}
                rowKey={(i) => `${i.product_id}-${i.warehouse_id}`}
                emptyMessage="No items in this report."
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <StockMovementDialog
        open={movementOpen}
        onOpenChange={setMovementOpen}
        mode={movementMode}
        inventory={selectedItem}
        warehouses={warehouses}
      />
    </div>
  )
}
