import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '@/lib/query/queryClient'
import { AppLayout } from '@/components/layout/AppLayout'
import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { RequireRole } from '@/components/layout/RoleGate'
import { Toaster } from '@/components/ui/toaster'
const LoginPage = lazy(() => import('@/features/auth/LoginPage'))
const RegisterPage = lazy(() => import('@/features/auth/RegisterPage'))
const DashboardPage = lazy(() => import('@/features/dashboard/DashboardPage'))
const ProductsPage = lazy(() => import('@/features/products/ProductsPage'))
const ProductDetailPage = lazy(() => import('@/features/products/ProductDetailPage'))
const WarehousesPage = lazy(() => import('@/features/inventory/WarehousesPage'))
const InventoryPage = lazy(() => import('@/features/inventory/InventoryPage'))
const OrdersPage = lazy(() => import('@/features/orders/OrdersPage'))
const OrderDetailPage = lazy(() => import('@/features/orders/OrderDetailPage'))
const ProfilePage = lazy(() => import('@/features/profile/ProfilePage'))
const IntelligenceDashboardPage = lazy(
  () => import('@/features/intelligence/IntelligenceDashboardPage'),
)
const ProductIntelligencePage = lazy(
  () => import('@/features/intelligence/ProductIntelligencePage'),
)
const SimulationPage = lazy(() => import('@/features/intelligence/SimulationPage'))
const NotFoundPage = lazy(() => import('@/features/NotFoundPage'))

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
      <Suspense
          fallback={
            <div className="grid min-h-[40vh] place-items-center text-sm text-muted-foreground">
              Loading page…
            </div>
          }
        >
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/admin/login" element={<LoginPage mode="admin" />} />
            <Route path="/register" element={<RegisterPage />} />

            <Route element={<ProtectedRoute />}>
              <Route element={<AppLayout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/products" element={<ProductsPage />} />
                <Route path="/products/:slug" element={<ProductDetailPage />} />
                <Route path="/orders" element={<OrdersPage />} />
                <Route path="/orders/:orderId" element={<OrderDetailPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route
                  path="/warehouses"
                  element={
                    <RequireRole roles={['admin', 'inventory_manager']}>
                      <WarehousesPage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/inventory"
                  element={
                    <RequireRole roles={['admin', 'inventory_manager']}>
                      <InventoryPage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/intelligence"
                  element={
                    <RequireRole roles={['admin']}>
                      <IntelligenceDashboardPage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/intelligence/products/:productId"
                  element={
                    <RequireRole roles={['admin']}>
                      <ProductIntelligencePage />
                    </RequireRole>
                  }
                />
                <Route
                  path="/intelligence/simulate"
                  element={
                    <RequireRole roles={['admin']}>
                      <SimulationPage />
                    </RequireRole>
                  }
                />
              </Route>
            </Route>

            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
