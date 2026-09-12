import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { ArrowRight, Boxes, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { useAuth } from '@/lib/auth/useAuth'
import { registerSchema, type RegisterFormValues } from '@/lib/validators/auth.schema'
import { ApiClientError } from '@/lib/api/client'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const form = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      email: '',
      username: '',
      password: '',
      confirm_password: '',
      first_name: '',
      last_name: '',
      phone: '',
    },
  })

  async function onSubmit(values: RegisterFormValues) {
    setSubmitting(true)
    setServerError(null)
    try {
      await register({
        email: values.email,
        username: values.username,
        password: values.password,
        confirm_password: values.confirm_password,
        first_name: values.first_name,
        last_name: values.last_name,
        phone: values.phone || null,
      })
      navigate('/login', { replace: true })
    } catch (err) {
      if (err instanceof ApiClientError) {
        // Surface first validation error if present.
        const details = err.details as { errors?: Array<{ msg?: string; loc?: unknown[] }> }
        const firstError = details?.errors?.[0]
        setServerError(firstError?.msg ?? err.message)
      } else {
        setServerError('Registration failed. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#f5f7fb] p-4 lg:grid lg:grid-cols-[.85fr_1.15fr] lg:p-5">
      <section className="relative hidden overflow-hidden rounded-3xl bg-[#102a56] p-12 text-white lg:flex lg:flex-col"><div className="absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-blue-400/20 blur-3xl" /><div className="relative flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-primary"><Boxes className="h-5 w-5" /></div><span className="text-xl font-bold tracking-[-.04em]">CommerceOS</span></div><div className="relative my-auto"><p className="text-xs font-bold uppercase tracking-[.2em] text-blue-200">Customer portal</p><h1 className="mt-5 max-w-sm text-5xl font-bold leading-[1.07] tracking-[-.06em]">Your orders, with complete clarity.</h1><p className="mt-6 max-w-sm leading-7 text-blue-100/80">Create an account to browse the catalog and keep every order in view.</p></div><p className="relative text-xs text-blue-200/70">CommerceOS · Reliable commerce operations</p></section>
      <section className="flex min-h-[calc(100vh-2rem)] items-center justify-center p-4 sm:p-8"><Card className="w-full max-w-[510px] border-0 bg-transparent shadow-none">
        <CardHeader className="px-0 text-left"><div className="mb-6 flex items-center gap-2 lg:hidden"><div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-white"><Boxes className="h-5 w-5" /></div><span className="text-lg font-bold tracking-[-.04em]">CommerceOS</span></div><p className="page-eyebrow">Customer account</p><CardTitle className="mt-2 text-3xl tracking-[-.045em]">Create your account</CardTitle><CardDescription className="mt-2">Public registration creates a customer workspace.</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              {serverError && (
                <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {serverError}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="first_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>First name</FormLabel>
                      <FormControl>
                        <Input placeholder="Jane" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="last_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Last name</FormLabel>
                      <FormControl>
                        <Input placeholder="Doe" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input placeholder="you@example.com" type="email" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Username</FormLabel>
                    <FormControl>
                      <Input placeholder="jane_doe" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="phone"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phone (optional)</FormLabel>
                    <FormControl>
                      <Input placeholder="+1 555 123 4567" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Password</FormLabel>
                    <FormControl>
                      <Input placeholder="Min 8 chars, upper/lower/number/special" type="password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="confirm_password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Confirm password</FormLabel>
                    <FormControl>
                      <Input placeholder="Re-enter password" type="password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" className="h-11 w-full rounded-xl" disabled={submitting}>
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create Account <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </form>
          </Form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-primary hover:underline">
              Sign in
            </Link>
          </p>
        </CardContent>
      </Card></section>
    </div>
  )
}
