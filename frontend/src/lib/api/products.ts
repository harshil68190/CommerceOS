import { apiClient } from '@/lib/api/client'
import { toQueryString } from '@/lib/queryString'
import type {
  CreateProductPayload,
  Paginated,
  Product,
  ProductFilters,
  UpdateProductPayload,
} from '@/types/api'

export const productsApi = {
  /** Customer-facing list (active only). */
  async list(filters: ProductFilters = {}): Promise<Paginated<Product>> {
    const { data } = await apiClient.get<Paginated<Product>>(
      `/products${toQueryString(filters)}`,
    )
    return data
  },

  /** Admin list (all statuses). */
  async listAdmin(filters: ProductFilters = {}): Promise<Paginated<Product>> {
    const { data } = await apiClient.get<Paginated<Product>>(
      `/products/admin${toQueryString(filters)}`,
    )
    return data
  },

  async getBySlug(slug: string): Promise<Product> {
    const { data } = await apiClient.get<Product>(`/products/${slug}`)
    return data
  },

  async create(payload: CreateProductPayload): Promise<Product> {
    const { data } = await apiClient.post<Product>('/products', payload)
    return data
  },

  async update(id: string, payload: UpdateProductPayload): Promise<Product> {
    const { data } = await apiClient.put<Product>(`/products/${id}`, payload)
    return data
  },

  async remove(id: string): Promise<void> {
    await apiClient.delete(`/products/${id}`)
  },

  async archive(id: string): Promise<Product> {
    const { data } = await apiClient.patch<Product>(`/products/${id}/archive`)
    return data
  },
}
