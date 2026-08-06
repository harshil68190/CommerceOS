import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, Archive, Trash2, Pencil, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DataTable, type Column } from '@/components/data/DataTable'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { RoleGate } from '@/components/layout/RoleGate'
import { ProductFormDialog } from '@/features/products/ProductFormDialog'
import { useAdminProducts, useArchiveProduct, useDeleteProduct } from '@/features/products/hooks'
import { queryKeys } from '@/lib/query/queryKeys'
import { toast } from '@/stores/toastStore'
import { formatCurrency } from '@/lib/utils'
import type { Product } from '@/types/api'

export default function ProductsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Product | null>(null)

  const archiveMutation = useArchiveProduct()
  const deleteMutation = useDeleteProduct()

const { data, isLoading, error, refetch } = useAdminProducts({
    page,
    page_size: 20,
    q: search || undefined,
    sort: 'newest',
  })

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
      header: 'Name',
      cell: (p) => (
        <div>
          <div className="font-medium">{p.name}</div>
          <div className="text-xs text-muted-foreground">{p.sku}</div>
        </div>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      cell: (p) => p.category || '—',
    },
    {
      key: 'brand',
      header: 'Brand',
      cell: (p) => p.brand || '—',
    },
    {
      key: 'price',
      header: 'Price',
      cell: (p) => formatCurrency(p.price, p.currency),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (p) => <StatusBadge status={p.status} />,
    },
    {
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      cell: (p) => (
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
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Products</h1>
          <p className="text-sm text-muted-foreground">Manage your product catalog</p>
        </div>
        <RoleGate roles={['admin', 'seller']}>
          <Button onClick={() => { setEditing(null); setFormOpen(true) }}>
            <Plus className="mr-2 h-4 w-4" />
            New Product
          </Button>
        </RoleGate>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>All Products</CardTitle>
            <div className="relative w-64">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search products..."
                className="pl-8"
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
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
            emptyMessage="No products found."
          />
        </CardContent>
      </Card>

      <ProductFormDialog open={formOpen} onOpenChange={setFormOpen} product={editing} />
    </div>
  )
}
