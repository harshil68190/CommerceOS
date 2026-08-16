import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/lib/auth/useAuth'
import { FullScreenLoader } from '@/components/feedback/FullScreenLoader'

/**
 * Guards protected routes. Renders a full-screen loader while the auth
 * session is still hydrating, then redirects to /login if unauthenticated.
 */
export function ProtectedRoute() {
  const { isAuthenticated, isHydrated, user, accessToken, refreshToken, redirectReason } = useAuth()
  const location = useLocation()

  if (!isHydrated) {
    return <FullScreenLoader />
  }

  if (!isAuthenticated) {
    const hadAuthenticatedSession =
      !!user || !!accessToken || !!refreshToken || redirectReason === 'session_expired'

    return (
      <Navigate
        to="/login"
        state={hadAuthenticatedSession ? { from: location, reason: 'session_expired' } : { from: location }}
        replace
      />
    )
  }

  return <Outlet />
}
