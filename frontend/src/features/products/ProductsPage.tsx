import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight, Plus, Archive, Trash2, Pencil, Search, SlidersHorizontal, ShoppingCart, Minus } from 'lucide-react'
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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ProductFormDialog } from '@/features/products/ProductFormDialog'
import { useAdminProducts, useArchiveProduct, useDeleteProduct, useProducts } from '@/features/products/hooks'
import { useCreateOrder } from '@/features/orders/hooks'
import { useAuth } from '@/lib/auth/useAuth'
import { inventoryApi } from '@/lib/api/inventory'
import { queryKeys } from '@/lib/query/queryKeys'
import { toast } from '@/stores/toastStore'
import { formatCurrency } from '@/lib/utils'
import type { Product } from '@/types/api'

export default function ProductsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { user } = useAuth()
  const qc = useQueryClient()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '')
  const [statusFilter, setStatusFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [filterOpen, setFilterOpen] = useState(false)
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Product | null>(null)
  const [cart, setCart] = useState<Array<{ product: Product; quantity: number }>>([])
  const [cartOpen, setCartOpen] = useState(false)

  const archiveMutation = useArchiveProduct()
  const deleteMutation = useDeleteProduct()
  const createOrderMutation = useCreateOrder()

  const canManageCatalog = user?.role === 'admin' || user?.role === 'seller'
  const filters = {
    page,
    page_size: 20,
    q: search || undefined,
    category: categoryFilter === 'all' ? undefined : categoryFilter,
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

  function addToCart(product: Product) {
    setCart((current) => {
      const existing = current.find((item) => item.product.id === product.id)
      if (existing) {
        return current.map((item) => item.product.id === product.id ? { ...item, quantity: item.quantity + 1 } : item)
      }
      return [...current, { product, quantity: 1 }]
    })
    setSelectedProduct(null)
    toast({ title: 'Added to cart', description: `${product.name} is ready for checkout.`, variant: 'success' })
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

  if (!canManageCatalog) {
    return (
      <div className="space-y-6">
        <div className="relative overflow-hidden rounded-3xl bg-[#102a56] px-6 py-8 text-white sm:px-9 sm:py-10">
          <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-blue-400/20 blur-3xl" />
          <div className="relative max-w-xl"><p className="text-[11px] font-bold uppercase tracking-[.16em] text-blue-200">CommerceOS catalog</p><h1 className="mt-3 text-3xl font-bold tracking-[-.05em] sm:text-4xl">Source better products, simply.</h1><p className="mt-3 text-sm leading-6 text-blue-100/75">Browse the available collection and find the products that keep your business moving.</p></div>
          <div className="relative mt-7 flex max-w-xl gap-2"><div className="relative flex-1"><Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" /><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} className="h-10 border-0 bg-white pl-9 text-slate-800 shadow-lg shadow-blue-950/15" placeholder="Search the catalog" /></div><Button variant="secondary" onClick={() => setFilterOpen(true)} className="h-10 rounded-xl bg-white/15 px-3 text-white hover:bg-white/25" aria-label="Filter catalog"><SlidersHorizontal className="h-4 w-4" /></Button></div>
        </div>
        <div className="flex items-center justify-between gap-3"><div><p className="page-eyebrow">Available now</p><h2 className="mt-1 text-xl font-bold tracking-[-.03em]">Explore products</h2></div><Button variant="outline" className="shrink-0" onClick={() => setCartOpen(true)}><ShoppingCart className="mr-2 h-4 w-4" />Cart{cart.length > 0 && <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-[10px] text-white">{cart.reduce((sum, item) => sum + item.quantity, 0)}</span>}</Button></div>
        {isLoading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-72 animate-pulse rounded-2xl border bg-white" />)}</div> : error ? <DataTable columns={[]} data={[]} error={error} onRetry={refetch} rowKey={() => ''} /> : products.length === 0 ? <div className="rounded-2xl border border-dashed bg-white p-12 text-center text-sm text-muted-foreground">No products match your search. Try a different term.</div> : <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {products.map((product, index) => <article key={product.id} role="button" tabIndex={0} onClick={() => setSelectedProduct(product)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setSelectedProduct(product) }} className="surface-card group cursor-pointer overflow-hidden bg-white transition duration-200 hover:-translate-y-0.5 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2">
              <div className="flex h-32 items-end justify-between bg-gradient-to-br from-blue-50 via-slate-50 to-[#dce9ff] p-5"><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-sm font-bold text-primary shadow-sm">{product.name.slice(0, 2).toUpperCase()}</div><span className="text-[42px] font-bold tracking-[-.08em] text-primary/10">0{index + 1}</span></div>
              <div className="p-5"><div className="flex items-start justify-between gap-3"><div><p className="text-base font-bold tracking-[-.025em] text-slate-800">{product.name}</p><p className="mt-1 text-xs text-slate-500">{product.brand || 'CommerceOS'} · {product.category || 'General'}</p></div><StatusBadge status={product.status} /></div><p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">{product.short_description || product.description || 'Available to order through your CommerceOS workspace.'}</p><div className="mt-5 flex items-end justify-between border-t pt-4"><div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-slate-400">From</p><p className="mt-1 text-lg font-bold tracking-[-.03em] text-slate-800">{formatCurrency(product.price, product.currency)}</p></div><span className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200 transition group-hover:bg-primary group-hover:text-white"><ArrowUpRight className="h-4 w-4" /></span></div></div>
            </article>)}
          </div>
          {pages > 1 && <div className="flex items-center justify-between border-t pt-5"><p className="text-sm text-muted-foreground">Page {page} of {pages}</p><div className="flex gap-2"><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button><Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button></div></div>}
        </>}
        <Dialog open={filterOpen} onOpenChange={setFilterOpen}><DialogContent className="rounded-2xl"><DialogHeader><DialogTitle>Filter the catalog</DialogTitle><DialogDescription>Choose a product category to narrow the current collection.</DialogDescription></DialogHeader><div className="grid grid-cols-2 gap-2"><Button variant={categoryFilter === 'all' ? 'default' : 'outline'} onClick={() => { setCategoryFilter('all'); setPage(1); setFilterOpen(false) }}>All products</Button>{['Chargers', 'Monitors', 'Accessories', 'Electronics'].map((category) => <Button key={category} variant={categoryFilter === category ? 'default' : 'outline'} onClick={() => { setCategoryFilter(category); setPage(1); setFilterOpen(false) }}>{category}</Button>)}</div><DialogFooter><Button variant="ghost" onClick={() => setFilterOpen(false)}>Close</Button></DialogFooter></DialogContent></Dialog>
        <Dialog open={Boolean(selectedProduct)} onOpenChange={(open) => { if (!open) setSelectedProduct(null) }}><DialogContent className="rounded-2xl"><DialogHeader><p className="page-eyebrow">Product overview</p><DialogTitle className="mt-1 text-2xl">{selectedProduct?.name}</DialogTitle><DialogDescription>{selectedProduct?.brand || 'CommerceOS'} · {selectedProduct?.category || 'General'} · {selectedProduct?.sku}</DialogDescription></DialogHeader><div className="rounded-xl bg-slate-50 p-4 text-sm leading-6 text-slate-600">{selectedProduct?.description || selectedProduct?.short_description || 'Product information is available through CommerceOS.'}</div><div className="flex items-center justify-between rounded-xl border p-4"><span className="text-sm text-muted-foreground">Available price</span><span className="text-xl font-bold">{selectedProduct && formatCurrency(selectedProduct.price, selectedProduct.currency)}</span></div><DialogFooter><Button variant="outline" onClick={() => setSelectedProduct(null)}>Close</Button><Button onClick={() => selectedProduct && addToCart(selectedProduct)}><ShoppingCart className="mr-2 h-4 w-4" />Add to cart</Button></DialogFooter></DialogContent></Dialog>
        <Dialog open={cartOpen} onOpenChange={setCartOpen}><DialogContent className="rounded-2xl"><DialogHeader><DialogTitle>Your cart</DialogTitle><DialogDescription>Review your items before placing the order.</DialogDescription></DialogHeader>{cart.length === 0 ? <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">Your cart is empty. Add a product from the catalog to continue.</div> : <div className="space-y-3">{cart.map((item) => <div key={item.product.id} className="flex items-center justify-between gap-3 rounded-xl border p-3"><div className="min-w-0"><p className="truncate text-sm font-semibold">{item.product.name}</p><p className="text-xs text-muted-foreground">{formatCurrency(item.product.price, item.product.currency)} each</p></div><div className="flex items-center gap-2"><Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setCart((current) => current.flatMap((entry) => entry.product.id === item.product.id ? (entry.quantity > 1 ? [{ ...entry, quantity: entry.quantity - 1 }] : []) : [entry]))} aria-label={`Remove one ${item.product.name}`}><Minus className="h-3 w-3" /></Button><span className="w-5 text-center text-sm font-semibold">{item.quantity}</span><Button variant="outline" size="icon" className="h-7 w-7" onClick={() => setCart((current) => current.map((entry) => entry.product.id === item.product.id ? { ...entry, quantity: entry.quantity + 1 } : entry))} aria-label={`Add one ${item.product.name}`}><Plus className="h-3 w-3" /></Button></div></div>)}</div>}<DialogFooter><Button variant="outline" onClick={() => setCartOpen(false)}>Continue shopping</Button><Button disabled={cart.length === 0 || createOrderMutation.isPending} onClick={checkoutCart}>{createOrderMutation.isPending ? 'Placing order…' : 'Place order'}</Button></DialogFooter></DialogContent></Dialog>
      </div>
    )
  }

  async function checkoutCart() {
    if (cart.length === 0) return
    try {
      const items: Array<{ product_id: string; warehouse_id: string; quantity: number }> = []
      for (const item of cart) {
        const stock = await inventoryApi.getProductSummary(item.product.id)
        let remaining = item.quantity
        for (const warehouse of stock.warehouses) {
          const available = Number(warehouse.available ?? 0)
          if (typeof warehouse.warehouse_id !== 'string' || available <= 0) continue
          const quantity = Math.min(remaining, available)
          items.push({ product_id: item.product.id, warehouse_id: warehouse.warehouse_id, quantity })
          remaining -= quantity
          if (remaining === 0) break
        }
        if (remaining > 0) {
          toast({ title: `${item.product.name} is unavailable`, description: 'Remove it from your cart or reduce the quantity.', variant: 'destructive' })
          return
        }
      }
      const order = await createOrderMutation.mutateAsync({ items, notes: 'Customer checkout from catalog' })
      setCart([])
      setCartOpen(false)
      toast({ title: 'Order confirmed', description: `${order.order_number} is now pending in My Orders.`, variant: 'success' })
      navigate('/orders')
    } catch (error) {
      toast({ title: 'Checkout failed', description: error instanceof Error ? error.message : 'Please try again.', variant: 'destructive' })
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="page-eyebrow">Catalog control</p><h1 className="mt-1 text-3xl font-bold tracking-[-.04em]">Products</h1>
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
            onRowClick={(p) => navigate(`/products/${p.slug}`)}
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
