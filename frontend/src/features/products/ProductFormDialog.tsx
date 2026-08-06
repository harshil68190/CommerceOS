import { zodResolver } from '@hookform/resolvers/zod'
import { useForm, type Resolver } from 'react-hook-form'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { useCreateProduct, useUpdateProduct } from '@/features/products/hooks'
import { productSchema, type ProductFormValues } from '@/lib/validators/product.schema'
import { toast } from '@/stores/toastStore'
import { ApiClientError } from '@/lib/api/client'
import type { Product } from '@/types/api'

interface ProductFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  product?: Product | null
}

export function ProductFormDialog({ open, onOpenChange, product }: ProductFormDialogProps) {
  const isEdit = !!product

  const createMutation = useCreateProduct()
  const updateMutation = useUpdateProduct()

const form = useForm<ProductFormValues>({
    resolver: zodResolver(productSchema) as Resolver<ProductFormValues>,
    defaultValues: {
      sku: product?.sku ?? '',
      slug: product?.slug ?? '',
      name: product?.name ?? '',
      description: product?.description ?? '',
      short_description: product?.short_description ?? '',
      brand: product?.brand ?? '',
      category: product?.category ?? '',
      price: product?.price ?? '',
      compare_at_price: product?.compare_at_price ?? '',
      currency: product?.currency ?? 'USD',
      weight: product?.weight ?? '',
      status: (product?.status === 'active' || product?.status === 'draft' ? product.status : 'active') as 'active' | 'draft',
      is_featured: product?.is_featured ?? false,
      track_inventory: product?.track_inventory ?? true,
    },
  })

  async function onSubmit(values: ProductFormValues) {
    try {
      if (isEdit && product) {
        await updateMutation.mutateAsync({
          id: product.id,
          payload: {
            name: values.name,
            slug: values.slug,
            description: values.description || null,
            short_description: values.short_description || null,
            brand: values.brand || null,
            category: values.category || null,
            price: values.price,
            compare_at_price: values.compare_at_price || null,
            currency: values.currency,
            weight: values.weight || null,
            status: values.status,
            is_featured: values.is_featured,
            track_inventory: values.track_inventory,
          },
        })
        toast({ title: 'Product updated', variant: 'success' })
      } else {
        await createMutation.mutateAsync({
          sku: values.sku,
          slug: values.slug,
          name: values.name,
          description: values.description || null,
          short_description: values.short_description || null,
          brand: values.brand || null,
          category: values.category || null,
          price: values.price,
          compare_at_price: values.compare_at_price || null,
          currency: values.currency,
          weight: values.weight || null,
          status: values.status,
          is_featured: values.is_featured,
          track_inventory: values.track_inventory,
        })
        toast({ title: 'Product created', variant: 'success' })
      }
      onOpenChange(false)
    } catch (err) {
      if (err instanceof ApiClientError) {
        toast({ title: 'Error', description: err.message, variant: 'destructive' })
      }
    }
  }

  const saving = createMutation.isPending || updateMutation.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit Product' : 'Create Product'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'Update the product details below.'
              : 'Fill in the details for the new product.'}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="Product name" {...field} disabled={isEdit} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="sku"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>SKU</FormLabel>
                    <FormControl>
                      <Input placeholder="SKU-001" {...field} disabled={isEdit} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="slug"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Slug</FormLabel>
                    <FormControl>
                      <Input placeholder="product-name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <FormField
                control={form.control}
                name="brand"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Brand</FormLabel>
                    <FormControl>
                      <Input placeholder="Brand" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Category</FormLabel>
                    <FormControl>
                      <Input placeholder="Category" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <FormField
                control={form.control}
                name="price"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Price</FormLabel>
                    <FormControl>
                      <Input placeholder="19.99" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="compare_at_price"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Compare at</FormLabel>
                    <FormControl>
                      <Input placeholder="24.99" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="currency"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Currency</FormLabel>
                    <FormControl>
                      <Input placeholder="USD" maxLength={3} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Status</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select status" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="draft">Draft</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Description</FormLabel>
                  <FormControl>
                    <Textarea placeholder="Product description" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEdit ? 'Save Changes' : 'Create Product'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
