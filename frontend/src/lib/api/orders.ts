import { apiClient } from '@/lib/api/client'
import { toQueryString } from '@/lib/queryString'
import type {
  Order,
  OrderCreatePayload,
  OrderFilters,
  OrderItem,
  OrderStatusTransitionResponse,
  OrderUpdatePayload,
  Paginated,
} from '@/types/api'

export interface OrderItemCreatePayload {
  product_id: string
  warehouse_id: string
  quantity: number
}

export const ordersApi = {
  /** Admin/seller list. */
  async list(filters: OrderFilters = {}): Promise<Paginated<Order>> {
    const { data } = await apiClient.get<Paginated<Order>>(
      `/orders${toQueryString(filters)}`,
    )
    return data
  },

/** Customer's own orders. */
  async listMy(filters: OrderFilters = {}): Promise<Paginated<Order>> {
    const { data } = await apiClient.get<Paginated<Order>>(
      `/orders/my${toQueryString(filters)}`,
    )
    return data
  },

  async get(id: string): Promise<Order> {
    const { data } = await apiClient.get<Order>(`/orders/${id}`)
    return data
  },

  async create(payload: OrderCreatePayload): Promise<Order> {
    const { data } = await apiClient.post<Order>('/orders', payload)
    return data
  },

  async update(id: string, payload: OrderUpdatePayload): Promise<Order> {
    const { data } = await apiClient.patch<Order>(`/orders/${id}`, payload)
    return data
  },

  async remove(id: string): Promise<void> {
    await apiClient.delete(`/orders/${id}`)
  },

  async cancel(id: string, reason?: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/cancel`,
      {},
      { params: reason ? { reason } : {} },
    )
    return data
  },

  async confirmPayment(id: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/confirm-payment`,
    )
    return data
  },

  async ship(id: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/ship`,
    )
    return data
  },

  async deliver(id: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/deliver`,
    )
    return data
  },

  async returnOrder(id: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/return`,
    )
    return data
  },

  async refund(id: string): Promise<OrderStatusTransitionResponse> {
    const { data } = await apiClient.patch<OrderStatusTransitionResponse>(
      `/orders/${id}/refund`,
    )
    return data
  },

  async addItem(
    orderId: string,
    payload: OrderItemCreatePayload,
  ): Promise<OrderItem> {
    const { data } = await apiClient.post<OrderItem>(
      `/orders/${orderId}/items`,
      payload,
    )
    return data
  },

  async updateItem(
    orderId: string,
    itemId: string,
    quantity: number,
  ): Promise<OrderItem> {
    const { data } = await apiClient.patch<OrderItem>(
      `/orders/${orderId}/items/${itemId}`,
      { quantity },
    )
    return data
  },

  async removeItem(orderId: string, itemId: string): Promise<void> {
    await apiClient.delete(`/orders/${orderId}/items/${itemId}`)
  },
}
