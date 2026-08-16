import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api/auth'
import { useAuthStore } from '@/lib/auth/useAuthStore'
import { tokenStorage } from '@/lib/auth/tokenStorage'

/**
 * Custom hook that exposes the auth session + login/logout actions.
 * The user profile is fetched once via GET /auth/me on mount if a token
 * is present, and refreshed whenever the token changes.
 */
export function useAuth() {
  const {
    user,
    accessToken,
    refreshToken,
    redirectReason,
    isHydrated,
    setAuth,
    setUser,
    setRedirectReason,
    clearAuth,
  } = useAuthStore()

  const { refetch: refetchMe } = useQuery({
    queryKey: ['auth', 'me', accessToken],
    queryFn: authApi.me,
    enabled: !!accessToken && !user,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  async function login(email: string, password: string) {
    setRedirectReason(null)
    const tokens = await authApi.login({ email, password })
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token)
    const me = await authApi.me()
    setAuth(me, tokens.access_token, tokens.refresh_token)
    return me
  }

  async function register(payload: Parameters<typeof authApi.register>[0]) {
    const user = await authApi.register(payload)
    return user
  }

  async function logout() {
    setRedirectReason(null)
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken)
      } catch {
        // Best-effort; ignore errors on logout.
      }
    }
    tokenStorage.clear()
    clearAuth()
  }

  return {
    user,
    accessToken,
    refreshToken,
    redirectReason,
    isAuthenticated: !!user && !!accessToken,
    isHydrated,
    login,
    register,
    logout,
    setUser,
    setRedirectReason,
    refetchMe,
  }
}
