import { z } from 'zod'

const slugRegex = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

// Mirrors backend CreateProductRequest (app/schemas/product.py).
// All fields are required in the object shape (no .default()) so z.infer === z.input,
// keeping the RHF form type and the zodResolver in sync.
export const productSchema = z.object({
  sku: z.string().min(1, 'SKU is required.').max(64),
  slug: z
    .string()
    .min(1, 'Slug is required.')
    .max(255)
    .regex(slugRegex, 'Lowercase letters, numbers, and hyphens only.'),
  name: z.string().min(1, 'Name is required.').max(255),
  description: z.string().optional(),
  short_description: z.string().optional(),
  brand: z.string().optional(),
  category: z.string().optional(),
  price: z
    .string()
    .min(1, 'Price is required.')
    .regex(/^\d+(\.\d{1,2})?$/, 'Price must be a valid amount (max 2 decimals).'),
  compare_at_price: z.string().optional(),
  currency: z.string().length(3, '3-letter currency code.'),
  weight: z.string().optional(),
  status: z.enum(['active', 'draft']),
  is_featured: z.boolean(),
  track_inventory: z.boolean(),
})

export type ProductFormValues = z.infer<typeof productSchema>

// Mirrors backend WarehouseCreateRequest.
export const warehouseSchema = z.object({
  name: z.string().min(1, 'Name is required.').max(255),
  code: z
    .string()
    .min(1, 'Code is required.')
    .max(50)
    .regex(/^[A-Z0-9]+(?:[-_][A-Z0-9]+)*$/, 'Uppercase letters, numbers, hyphens, underscores.'),
  address: z.string().max(500).optional().or(z.literal('')),
  city: z.string().max(100).optional().or(z.literal('')),
  state: z.string().max(100).optional().or(z.literal('')),
  country: z.string().max(100).optional().or(z.literal('')),
  postal_code: z.string().max(20).optional().or(z.literal('')),
  contact_number: z.string().max(20).optional().or(z.literal('')),
  email: z.string().email('Invalid email.').optional().or(z.literal('')),
})

export type WarehouseFormValues = z.infer<typeof warehouseSchema>

// Stock movement forms.
export const stockMovementSchema = z
  .object({
    product_id: z.string().min(1, 'Product is required.'),
    warehouse_id: z.string().min(1, 'Warehouse is required.'),
    quantity: z.coerce.number().int().positive('Quantity must be positive.'),
    reason: z.enum(['damage', 'expired', 'adjustment', 'other']).default('adjustment'),
    new_quantity: z.coerce.number().int().min(0, 'Quantity cannot be negative.'),
    reference_number: z.string().max(255).optional().or(z.literal('')),
    notes: z.string().max(500).optional().or(z.literal('')),
  })
  .partial()

export type StockMovementFormValues = z.infer<typeof stockMovementSchema>

// Transfer form.
export const transferSchema = z.object({
  product_id: z.string().min(1, 'Product is required.'),
  from_warehouse_id: z.string().min(1, 'Source warehouse is required.'),
  to_warehouse_id: z.string().min(1, 'Destination warehouse is required.'),
  quantity: z.coerce.number().int().positive('Quantity must be positive.'),
  reference_number: z.string().max(255).optional().or(z.literal('')),
  notes: z.string().max(500).optional().or(z.literal('')),
}).refine((d) => d.from_warehouse_id !== d.to_warehouse_id, {
  message: 'Source and destination must be different.',
  path: ['to_warehouse_id'],
})

export type TransferFormValues = z.infer<typeof transferSchema>
