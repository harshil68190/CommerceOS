import type { ReactNode } from 'react'
import { useAuth } from '@/lib/auth/useAuth'
import type { UserRole } from '@/types/api'

interface RoleGateProps {
  roles: UserRole[]
  children: ReactNode
  fallback?: ReactNode
}

/** Renders children only if the current user's role is permitted. */
export function RoleGate({ roles, children, fallback = null }: RoleGateProps) {
  const { user } = useAuth()
  if (!user) return <>{fallback}</>
  if (!roles.includes(user.role)) return <>{fallback}</>
  return <>{children}</>
}

/** Hook version for conditional logic. */
export function usePermission(roles: UserRole[]): boolean {
  const { user } = useAuth()
  if (!user) return false
  return roles.includes(user.role)
}
