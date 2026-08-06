import { z } from 'zod'

const orderItemSchema = z.object({
  product_id: z.string().min(1, 'Product is required.'),
  warehouse_id: z.string().min(1, 'Warehouse is required.'),
  quantity: z.coerce.number().int().positive('Quantity must be positive.'),
})

// Mirrors backend OrderCreateRequest.
export const orderCreateSchema = z
  .object({
    items: z
      .array(orderItemSchema)
      .min(1, 'At least one item is required.'),
    notes: z.string().max(2000).optional().or(z.literal('')),
    shipping_cost: z
      .string()
      .regex(/^\d+(\.\d{1,2})?$/, 'Invalid amount.')
      .optional()
      .or(z.literal('')),
    discount: z
      .string()
      .regex(/^\d+(\.\d{1,2})?$/, 'Invalid amount.')
      .optional()
      .or(z.literal('')),
    // Form-only fields for building line items.
    _product_id: z.string().optional(),
    _warehouse_id: z.string().optional(),
    _quantity: z.coerce.number().int().positive().optional(),
  })
  .refine(
    (d) => {
      const keys = d.items.map((i) => `${i.product_id}:${i.warehouse_id}`)
      return new Set(keys).size === keys.length
    },
    { message: 'Duplicate product-warehouse combinations are not allowed.', path: ['items'] },
  )

export type OrderCreateFormValues = z.infer<typeof orderCreateSchema>

// Order update (partial).
export const orderUpdateSchema = z.object({
  notes: z.string().max(2000).optional().or(z.literal('')),
  shipping_cost: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, 'Invalid amount.')
    .optional()
    .or(z.literal('')),
  discount: z
    .string()
    .regex(/^\d+(\.\d{1,2})?$/, 'Invalid amount.')
    .optional()
    .or(z.literal('')),
})

export type OrderUpdateFormValues = z.infer<typeof orderUpdateSchema>

// Cancel order.
export const cancelOrderSchema = z.object({
  reason: z.string().max(1000).optional().or(z.literal('')),
})

export type CancelOrderFormValues = z.infer<typeof cancelOrderSchema>
