import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Boxes, Loader2 } from 'lucide-react'
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
import { loginSchema, type LoginFormValues } from '@/lib/validators/auth.schema'
import { ApiClientError } from '@/lib/api/client'

interface LocationState {
  from?: { pathname: string }
  reason?: 'session_expired'
}

export default function LoginPage({
  mode = 'customer',
}: {
  mode?: 'customer' | 'admin'
}) {
  const { login, logout, setRedirectReason } = useAuth()
  const isAdminLogin = mode === 'admin'
  const navigate = useNavigate()
  const location = useLocation()
  const [serverError, setServerError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const sessionExpired = (location.state as LocationState | null)?.reason === 'session_expired'

  const form = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  const from = (location.state as LocationState | null)?.from?.pathname || '/'

  useEffect(() => {
    if (!sessionExpired) {
      setServerError(null)
      setRedirectReason(null)
    }
  }, [sessionExpired, setRedirectReason])

  async function onSubmit(values: LoginFormValues) {
    setSubmitting(true)
    setServerError(null)
    setRedirectReason(null)
    try {
      const user = await login(values.email, values.password)
      if (
        (isAdminLogin && user.role !== 'admin') ||
        (!isAdminLogin && user.role === 'admin')
      ) {
        await logout()
        setServerError(
          isAdminLogin
            ? 'This account does not have administrator access.'
            : 'Administrator accounts must sign in through the admin portal.',
        )
        return
      }
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof ApiClientError) {
        setServerError(err.message)
      } else {
        setServerError('Invalid email or password.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-background p-0 lg:grid lg:grid-cols-[1.08fr_.92fr] lg:p-4">
      <section aria-labelledby="login-product-heading" className="flex flex-col justify-center gap-9 bg-[#102a56] px-6 py-8 text-white sm:px-10 lg:min-h-[calc(100vh-2rem)] lg:justify-between lg:px-12 lg:py-9 xl:px-14">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-md bg-white text-primary"><Boxes className="h-5 w-5" aria-hidden="true" /></div><span className="text-xl font-semibold tracking-tight">CommerceOS</span></div>
        <div className="w-full max-w-[540px] self-center lg:py-10">
          <h1
            id="login-product-heading"
            className="max-w-[500px] text-[clamp(1.8rem,4vw,3.25rem)] font-semibold leading-[1.08] tracking-[-.04em]"
          >
            {isAdminLogin
              ? 'Run your commerce operations with confidence.'
              : 'Know what to restock before you run out.'}
          </h1>
          <p className="mt-4 max-w-lg text-sm leading-6 text-blue-100/85 sm:text-base">
            {isAdminLogin
              ? 'Manage your catalog, inventory, orders, and demand intelligence from one secure workspace.'
              : 'Inventory intelligence that forecasts demand and helps you plan your next reorder.'}
          </p>
        </div>
        <div aria-hidden="true" className="hidden lg:block" />
      </section>
      <section className="flex min-h-[440px] items-center justify-center border-x-0 border-b border-border px-5 py-10 sm:px-8 lg:min-h-[calc(100vh-2rem)] lg:border-b-0 lg:border-l lg:px-10">
      <Card className="w-full max-w-[400px] border-0 bg-transparent shadow-none">
        <CardHeader className="px-0 text-left">
          <CardTitle className="mt-2 text-[28px] font-semibold tracking-[-.035em]">
            {isAdminLogin ? 'Administrator sign in' : 'Sign in'}
          </CardTitle>
          <CardDescription className="mt-2">
            {isAdminLogin
              ? 'Use your administrator account to access the operations console.'
              : 'Enter your email and password to continue.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              {(serverError || sessionExpired) && (
                <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {sessionExpired ? 'Your session has expired. Please log in again.' : serverError}
                </div>
              )}
              <FormField
                control={form.control}
                name="email"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Email</FormLabel>
                    <FormControl>
                      <Input placeholder="you@example.com" type="email" autoComplete="email" {...field} />
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
                      <Input placeholder="••••••••" type="password" autoComplete="current-password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" className="mt-2 h-11 w-full rounded-md" disabled={submitting}>
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Sign In
              </Button>
            </form>
          </Form>
          {isAdminLogin ? (
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Customer account?{' '}
            <Link
              to="/login"
              className="font-medium text-primary hover:underline"
            >
              Sign in to the customer portal
            </Link>
          </p>
        ) : (
          <>
            <p className="mt-4 text-center text-sm text-muted-foreground">
              Don't have an account?{' '}
              <Link
                to="/register"
                className="font-medium text-primary hover:underline"
              >
                Register
              </Link>
            </p>
            <p className="mt-3 text-center text-sm text-muted-foreground">
              Administrator?{' '}
              <Link
                to="/admin/login"
                className="font-medium text-primary hover:underline"
              >
                Sign in to the admin portal
              </Link>
            </p>
          </>
        )}
        </CardContent>
      </Card>
      </section>
    </div>
  )
}
