import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, Trash2, Pencil, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
import { RoleGate } from '@/components/layout/RoleGate'
import { ProductFormDialog } from '@/features/products/ProductFormDialog'
import { useAdminProducts, useArchiveProduct, useDeleteProduct, useProducts } from '@/features/products/hooks'
import { useAuth } from '@/lib/auth/useAuth'
import { queryKeys } from '@/lib/query/queryKeys'
import { toast } from '@/stores/toastStore'
import { formatCurrency } from '@/lib/utils'
import type { Product } from '@/types/api'

export default function ProductsPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Product | null>(null)

  const archiveMutation = useArchiveProduct()
  const deleteMutation = useDeleteProduct()

  const canManageCatalog = user?.role === 'admin' || user?.role === 'seller'
  const filters = {
    page,
    page_size: 20,
    q: search || undefined,
    status: !canManageCatalog || statusFilter === 'all' ? undefined : statusFilter,
    sort: 'newest',
  }
  const customerProducts = useProducts(filters, !canManageCatalog)
  const adminProducts = useAdminProducts(filters, canManageCatalog)
  const { data, isLoading, error, refetch } = canManageCatalog ? adminProducts : customerProducts

  const products = data?.items ?? []
  const pages = data?.pages ?? 1
  const total = data?.total ?? 0

  async function handleArchive(product: Product) {
    if (!window.confirm(`Archive "${product.name}"? This cannot be undone.`)) return
    try {
      await archiveMutation.mutateAsync(product.id)
      toast({ title: 'Product archived', variant: 'success' })
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    } catch {
      toast({ title: 'Error archiving product', variant: 'destructive' })
    }
  }

  async function handleDelete(product: Product) {
    if (!window.confirm(`Permanently delete "${product.name}"?`)) return
    try {
      await deleteMutation.mutateAsync(product.id)
      toast({ title: 'Product deleted', variant: 'success' })
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    } catch {
      toast({ title: 'Error deleting product', variant: 'destructive' })
    }
  }

  const columns: Column<Product>[] = [
    {
      key: 'name',
      header: 'Product',
      cell: (p: Product) => (
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-muted text-xs font-semibold text-muted-foreground">
            {p.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div className="font-medium">{p.name}</div>
            <div className="text-xs text-muted-foreground">{p.sku}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      cell: (p) => <span className="text-sm text-muted-foreground">{p.category || '—'}</span>,
    },
    {
      key: 'brand',
      header: 'Brand',
      cell: (p) => <span className="text-sm text-muted-foreground">{p.brand || '—'}</span>,
    },
    {
      key: 'price',
      header: 'Price',
      cell: (p) => <span className="font-medium">{formatCurrency(p.price, p.currency)}</span>,
    },
    {
      key: 'status',
      header: 'Status',
      cell: (p) => <StatusBadge status={p.status} />,
    },
    ...(canManageCatalog ? [{
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      cell: (p: Product) => (
        <div className="flex justify-end gap-1">
          <RoleGate roles={['admin', 'seller']}>
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation()
                setEditing(p)
                setFormOpen(true)
              }}
            >
              <Pencil className="h-4 w-4" />
            </Button>
          </RoleGate>
          <RoleGate roles={['admin', 'seller']}>
            {p.status !== 'archived' && (
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => {
                  e.stopPropagation()
                  handleArchive(p)
                }}
              >
                <Archive className="h-4 w-4" />
              </Button>
            )}
          </RoleGate>
          <RoleGate roles={['admin']}>
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive"
              onClick={(e) => {
                e.stopPropagation()
                handleDelete(p)
              }}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </RoleGate>
        </div>
      ),
    }] : []),
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Products</h1>
          <p className="text-sm text-muted-foreground">{canManageCatalog ? 'Manage the merchandising catalog' : 'Browse the active catalog'}</p>
        </div>
        <RoleGate roles={['admin', 'seller']}>
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" />
            New Product
          </Button>
        </RoleGate>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <CardTitle>All Products</CardTitle>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="relative w-full sm:w-64">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search products..."
                  className="pl-8"
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                />
              </div>
              {canManageCatalog && <div className="w-full sm:w-40">
                <Select
                  value={statusFilter}
                  onValueChange={(value) => { setStatusFilter(value); setPage(1) }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All statuses</SelectItem>
                    <SelectItem value="active">Active</SelectItem>
                    <SelectItem value="draft">Draft</SelectItem>
                    <SelectItem value="archived">Archived</SelectItem>
                    <SelectItem value="out_of_stock">Out of stock</SelectItem>
                  </SelectContent>
                </Select>
              </div>}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex items-center justify-between text-sm text-muted-foreground">
            <span>{total} products</span>
            {search && <span>Filtered by “{search}”</span>}
          </div>
          <DataTable<Product>
            columns={columns}
            data={products}
            loading={isLoading}
            error={error}
            onRetry={refetch}
            rowKey={(p) => p.id}
            onRowClick={(p) => navigate(`/products/${p.id}`)}
            page={page}
            pages={pages}
            total={total}
            onPageChange={setPage}
            emptyMessage={search || statusFilter !== 'all' ? 'No products match the current filters.' : 'No products found.'}
          />
        </CardContent>
      </Card>

      {canManageCatalog && <ProductFormDialog open={formOpen} onOpenChange={setFormOpen} product={editing} />}
    </div>
  )
}
