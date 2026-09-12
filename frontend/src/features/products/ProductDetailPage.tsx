import { ArrowLeft, Pencil } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatusBadge } from '@/components/widgets/StatusBadge'
import { RoleGate } from '@/components/layout/RoleGate'
import { LoadingState } from '@/components/feedback/LoadingState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { productsApi } from '@/lib/api/products'
import { useAuth } from '@/lib/auth/useAuth'
import { formatCurrency, formatDate } from '@/lib/utils'

export default function ProductDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const query = useQuery({
    queryKey: ['products', 'detail', slug],
    queryFn: () => productsApi.getBySlug(slug || ''),
    enabled: Boolean(slug),
  })

  if (query.isLoading) return <LoadingState rows={5} />
  if (query.isError || !query.data) return <ErrorState title="Failed to load product" onRetry={query.refetch} />

  const product = query.data
  const canEdit = user?.role === 'admin' || user?.role === 'seller'

  return (
    <div className="space-y-4">
      <Button variant="ghost" onClick={() => navigate('/products')}><ArrowLeft className="mr-2 h-4 w-4" />Back to Products</Button>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div><p className="page-eyebrow">Product detail</p><h1 className="mt-1 text-3xl font-bold tracking-[-.04em]">{product.name}</h1><p className="text-sm text-muted-foreground">{product.brand || 'CommerceOS'} · {product.category || 'General'} · {product.sku}</p></div>
        {canEdit && <RoleGate roles={['admin', 'seller']}><Button variant="outline" onClick={() => navigate('/products')}><Pencil className="mr-2 h-4 w-4" />Edit in catalog</Button></RoleGate>}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2"><CardHeader><CardTitle>Overview</CardTitle></CardHeader><CardContent className="space-y-5"><div className="rounded-2xl bg-gradient-to-br from-blue-50 to-slate-50 p-8 text-center text-5xl font-bold text-primary/20">{product.name.slice(0, 2).toUpperCase()}</div><p className="leading-7 text-muted-foreground">{product.description || product.short_description || 'No description provided.'}</p><div className="grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">Status</p><StatusBadge status={product.status} /></div><div><p className="text-xs text-muted-foreground">Price</p><p className="font-semibold">{formatCurrency(product.price, product.currency)}</p></div><div><p className="text-xs text-muted-foreground">Created</p><p className="font-semibold">{formatDate(product.created_at)}</p></div></div></CardContent></Card>
        <Card><CardHeader><CardTitle>Catalog metadata</CardTitle></CardHeader><CardContent className="space-y-4 text-sm"><div className="flex justify-between gap-3"><span className="text-muted-foreground">SKU</span><span className="font-medium">{product.sku}</span></div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Slug</span><span className="font-medium">{product.slug}</span></div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Featured</span><span className="font-medium">{product.is_featured ? 'Yes' : 'No'}</span></div><div className="flex justify-between gap-3"><span className="text-muted-foreground">Inventory tracking</span><span className="font-medium">{product.track_inventory ? 'Enabled' : 'Disabled'}</span></div></CardContent></Card>
      </div>
    </div>
  )
}
