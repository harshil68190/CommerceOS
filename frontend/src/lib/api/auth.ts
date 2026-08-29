import { apiClient } from '@/lib/api/client'
import type {
  LoginPayload,
  RegisterPayload,
  TokenResponse,
  User,
} from '@/types/api'

export const authApi = {
  async register(payload: RegisterPayload): Promise<User> {
    const { data } = await apiClient.post<User>('/auth/register', payload)
    return data
  },

  async login(payload: LoginPayload): Promise<TokenResponse> {
    // Backend uses OAuth2PasswordRequestForm: username=<email>, password.
    const form = new URLSearchParams()
    form.append('username', payload.email)
    form.append('password', payload.password)
    const { data } = await apiClient.post<TokenResponse>('/auth/login', form, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    return data
  },

  async refresh(): Promise<TokenResponse> {
    const { data } = await apiClient.post<TokenResponse>('/auth/refresh')
    return data
  },

  async logout(): Promise<void> {
    await apiClient.post('/auth/logout')
  },

  async me(): Promise<User> {
    const { data } = await apiClient.get<User>('/auth/me')
    return data
  },
}
