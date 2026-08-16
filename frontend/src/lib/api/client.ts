import axios, {
  AxiosError,
  AxiosInstance,
  InternalAxiosRequestConfig,
} from 'axios'
import { tokenStorage } from '@/lib/auth/tokenStorage'
import { useAuthStore } from '@/lib/auth/useAuthStore'
import type { ApiError, TokenResponse } from '@/types/api'

/** Normalized API error thrown by the client. */
export class ApiClientError extends Error {
  errorCode: string
  status: number | undefined
  details: Record<string, unknown>
  requestId: string

  constructor(error: ApiError, status?: number) {
    super(error.message || 'An unexpected error occurred.')
    this.name = 'ApiClientError'
    this.errorCode = error.error_code || 'UNKNOWN'
    this.details = error.details || {}
    this.requestId = error.request_id || '-'
    this.status = status
  }
}

const BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'

export const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

// Request interceptor: attach the bearer token.
apiClient.interceptors.request.use((config) => {
  const token = tokenStorage.getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// --- Refresh-once logic ------------------------------------------------
let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = tokenStorage.getRefreshToken()
  if (!refreshToken) return null
  try {
    const { data } = await axios.post<TokenResponse>(
      `${BASE_URL}/auth/refresh`,
      { refresh_token: refreshToken },
    )
    tokenStorage.setTokens(data.access_token, data.refresh_token)
    return data.access_token
  } catch {
    tokenStorage.clear()
  useAuthStore.getState().clearAuth()
  useAuthStore.getState().setRedirectReason('session_expired')
  return null
}
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retry?: boolean
}

// Response interceptor: unwrap errors + handle 401 refresh-once.
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    const original = error.config as RetriableConfig | undefined

    // No network / server unreachable.
    if (!error.response) {
      return Promise.reject(
        new ApiClientError(
          {
            error_code: 'NETWORK_ERROR',
            message: 'Cannot reach the server. Please check your connection.',
            details: {},
            request_id: '-',
          },
          0,
        ),
      )
    }

    const status = error.response.status

    // Attempt a single token refresh on 401, then retry once.
    if (status === 401 && original && !original._retry) {
      original._retry = true
      refreshPromise = refreshPromise ?? refreshAccessToken()
      const newToken = await refreshPromise
      refreshPromise = null
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }
      // Refresh failed -> force logout handled by caller via error.
      return Promise.reject(
        new ApiClientError(
          {
            error_code: 'UNAUTHORIZED',
            message: 'Your session has expired. Please log in again.',
            details: {},
            request_id: '-',
          },
          401,
        ),
      )
    }

    const envelope = error.response.data
    return Promise.reject(
      new ApiClientError(
        envelope || {
          error_code: 'HTTP_ERROR',
          message: `Request failed with status ${status}.`,
          details: {},
          request_id: '-',
        },
        status,
      ),
    )
  },
)
