import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User } from '@/types/api'

interface AuthState {
  user: User | null
  accessToken: string | null
  redirectReason: 'session_expired' | null
  isHydrated: boolean
  setAuth: (user: User, accessToken: string) => void
  setAccessToken: (token: string) => void
  setUser: (user: User) => void
  setRedirectReason: (reason: 'session_expired' | null) => void
  clearAuth: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      redirectReason: null,
      isHydrated: false,
      setAuth: (user, accessToken) =>
        set({ user, accessToken, redirectReason: null, isHydrated: true }),
      setAccessToken: (token) => set({ accessToken: token }),
      setUser: (user) => set({ user }),
      setRedirectReason: (reason) => set({ redirectReason: reason }),
      clearAuth: () =>
        set({
          user: null,
          accessToken: null,
          isHydrated: true,
        }),
    }),
    {
      name: 'commerceos.auth',
      version: 1,
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
      }),
      // Remove refresh tokens persisted by releases before cookie-only auth.
      migrate: (persistedState) => {
        const { refreshToken: _refreshToken, ...state } = persistedState as AuthState & {
          refreshToken?: unknown
        }
        return state
      },
      onRehydrateStorage: () => (state) => {
        if (state) state.isHydrated = true
      },
    },
  ),
)
