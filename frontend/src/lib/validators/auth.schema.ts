import { z } from 'zod'

// Mirrors backend RegisterRequest (app/schemas/auth.py).
export const registerSchema = z
  .object({
    email: z.string().email('Enter a valid email address.'),
    username: z
      .string()
      .min(3, 'Username must be at least 3 characters.')
      .max(50, 'Username must be at most 50 characters.')
      .regex(/^[a-zA-Z0-9_]+$/, 'Only letters, numbers, and underscores allowed.'),
    password: z
      .string()
      .min(8, 'Password must be at least 8 characters.')
      .regex(/[a-z]/, 'Must contain a lowercase letter.')
      .regex(/[A-Z]/, 'Must contain an uppercase letter.')
      .regex(/\d/, 'Must contain a digit.')
      .regex(/[^A-Za-z0-9]/, 'Must contain a special character.'),
    confirm_password: z.string(),
    first_name: z.string().min(1, 'First name is required.').max(100),
    last_name: z.string().min(1, 'Last name is required.').max(100),
    phone: z.string().max(20, 'Phone must be at most 20 characters.').optional().or(z.literal('')),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: 'Passwords do not match.',
    path: ['confirm_password'],
  })

export type RegisterFormValues = z.infer<typeof registerSchema>

// Mirrors backend LoginRequest.
export const loginSchema = z.object({
  email: z.string().email('Enter a valid email address.'),
  password: z.string().min(1, 'Password is required.'),
})

export type LoginFormValues = z.infer<typeof loginSchema>
