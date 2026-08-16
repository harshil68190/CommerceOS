import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth/useAuth'
import type { UserRole } from '@/types/api'

interface RoleGateProps {
  roles: UserRole[]
  children: ReactNode
  fallback?: ReactNode
}

interface RequireRoleProps {
  roles: UserRole[]
  children: ReactNode
  fallbackPath?: string
}

/** Renders children only if the current user's role is permitted. */
export function RoleGate({ roles, children, fallback = null }: RoleGateProps) {
  const { user } = useAuth()
  if (!user) return <>{fallback}</>
  if (!roles.includes(user.role)) return <>{fallback}</>
  return <>{children}</>
}

/** Route-level role guard that redirects users away from forbidden pages. */
export function RequireRole({ roles, children, fallbackPath }: RequireRoleProps) {
  const { user } = useAuth()

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (!roles.includes(user.role)) {
    return <Navigate to={fallbackPath ?? (user.role === 'customer' ? '/products' : '/')} replace />
  }

  return <>{children}</>
}

/** Hook version for conditional logic. */
export function usePermission(roles: UserRole[]): boolean {
  const { user } = useAuth()
  if (!user) return false
  return roles.includes(user.role)
}
