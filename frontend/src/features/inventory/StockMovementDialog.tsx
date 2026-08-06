import { useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
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
import { useAddStock, useRemoveStock, useAdjustStock } from '@/features/inventory/hooks'
import { stockMovementSchema, type StockMovementFormValues } from '@/lib/validators/product.schema'
import { toast } from '@/stores/toastStore'
import { ApiClientError } from '@/lib/api/client'
import type { Inventory, Warehouse } from '@/types/api'

type Mode = 'add' | 'remove' | 'adjust'

interface StockMovementDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode: Mode
  inventory: Inventory | null
  warehouses: Warehouse[]
}

export function StockMovementDialog({
  open,
  onOpenChange,
  mode,
  inventory,
  warehouses,
}: StockMovementDialogProps) {
  const addMutation = useAddStock()
  const removeMutation = useRemoveStock()
  const adjustMutation = useAdjustStock()

  const [productId, setProductId] = useState<string>('')
  const [warehouseId, setWarehouseId] = useState<string>('')

  const form = useForm<StockMovementFormValues>({
    resolver: zodResolver(stockMovementSchema),
    defaultValues: {
      product_id: inventory?.product_id ?? '',
      warehouse_id: inventory?.warehouse_id ?? '',
      quantity: 1,
      new_quantity: inventory?.quantity ?? 0,
      reason: 'adjustment',
      reference_number: '',
      notes: '',
    },
  })

  const title =
    mode === 'add' ? 'Add Stock' : mode === 'remove' ? 'Remove Stock' : 'Adjust Stock'

  async function onSubmit(values: StockMovementFormValues) {
    const pid = inventory?.product_id ?? productId
    const wid = inventory?.warehouse_id ?? values.warehouse_id ?? warehouseId
    if (!pid || !wid) {
      toast({ title: 'Please select a product and warehouse', variant: 'destructive' })
      return
    }
    try {
      if (mode === 'add') {
        await addMutation.mutateAsync({
          product_id: pid,
          warehouse_id: wid,
          quantity: values.quantity ?? 1,
          reference_number: values.reference_number || null,
          notes: values.notes || null,
        })
        toast({ title: 'Stock added', variant: 'success' })
      } else if (mode === 'remove') {
        await removeMutation.mutateAsync({
          product_id: pid,
          warehouse_id: wid,
          quantity: values.quantity ?? 1,
          reason: values.reason ?? 'adjustment',
          reference_number: values.reference_number || null,
          notes: values.notes || null,
        })
        toast({ title: 'Stock removed', variant: 'success' })
      } else {
        await adjustMutation.mutateAsync({
          product_id: pid,
          warehouse_id: wid,
          new_quantity: values.new_quantity ?? 0,
          reference_number: values.reference_number || null,
          notes: values.notes || null,
        })
        toast({ title: 'Stock adjusted', variant: 'success' })
      }
      onOpenChange(false)
    } catch (err) {
      if (err instanceof ApiClientError) {
        toast({ title: 'Error', description: err.message, variant: 'destructive' })
      }
    }
  }

  const saving =
    addMutation.isPending || removeMutation.isPending || adjustMutation.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === 'add'
              ? 'Increase stock for a product in a warehouse.'
              : mode === 'remove'
                ? 'Remove stock (damage, expired, adjustment).'
                : 'Set the exact stock quantity (cycle count).'}
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {!inventory && (
              <>
                <FormField
                  control={form.control}
                  name="product_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Product ID</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="product-uuid"
                          {...field}
                          value={productId}
                          onChange={(e) => { setProductId(e.target.value); field.onChange(e.target.value) }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="warehouse_id"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Warehouse</FormLabel>
                      <Select
                        onValueChange={(v) => { setWarehouseId(v); field.onChange(v) }}
                        value={field.value}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Select warehouse" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {warehouses.map((w) => (
                            <SelectItem key={w.id} value={w.id}>
                              {w.name} ({w.code})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            )}

            {mode === 'add' || mode === 'remove' ? (
              <FormField
                control={form.control}
                name="quantity"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Quantity</FormLabel>
                    <FormControl>
                      <Input type="number" min={1} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              <FormField
                control={form.control}
                name="new_quantity"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>New Quantity</FormLabel>
                    <FormControl>
                      <Input type="number" min={0} {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {mode === 'remove' && (
              <FormField
                control={form.control}
                name="reason"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Reason</FormLabel>
                    <Select onValueChange={field.onChange} defaultValue={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select reason" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="damage">Damage</SelectItem>
                        <SelectItem value="expired">Expired</SelectItem>
                        <SelectItem value="adjustment">Adjustment</SelectItem>
                        <SelectItem value="other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="reference_number"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Reference (optional)</FormLabel>
                  <FormControl>
                    <Input placeholder="PO-12345" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="notes"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Notes (optional)</FormLabel>
                  <FormControl>
                    <Input placeholder="Notes" {...field} />
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
                {title}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
