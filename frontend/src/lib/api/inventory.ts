import { apiClient } from '@/lib/api/client'
import { toQueryString } from '@/lib/queryString'
import type {
  AdjustStockPayload,
  Inventory,
  InventoryTransaction,
  LowStockReportResponse,
  Paginated,
  ProductStockSummary,
  RemoveStockPayload,
  StockMovementPayload,
  StockMovementResponse,
  TransferPayload,
  Warehouse,
  WarehouseCreatePayload,
  WarehouseUpdatePayload,
} from '@/types/api'

export const inventoryApi = {
  // --- Warehouses ---
  async listWarehouses(
    params: Record<string, unknown> = {},
  ): Promise<Paginated<Warehouse>> {
    const { data } = await apiClient.get<Paginated<Warehouse>>(
      `/inventory/warehouses${toQueryString(params)}`,
    )
    return data
  },

  async getWarehouse(id: string): Promise<Warehouse> {
    const { data } = await apiClient.get<Warehouse>(`/inventory/warehouses/${id}`)
    return data
  },

  async createWarehouse(payload: WarehouseCreatePayload): Promise<Warehouse> {
    const { data } = await apiClient.post<Warehouse>(
      '/inventory/warehouses',
      payload,
    )
    return data
  },

  async updateWarehouse(
    id: string,
    payload: WarehouseUpdatePayload,
  ): Promise<Warehouse> {
    const { data } = await apiClient.put<Warehouse>(
      `/inventory/warehouses/${id}`,
      payload,
    )
    return data
  },

  async deactivateWarehouse(id: string): Promise<void> {
    await apiClient.delete(`/inventory/warehouses/${id}`)
  },

  async reactivateWarehouse(id: string): Promise<Warehouse> {
    const { data } = await apiClient.patch<Warehouse>(
      `/inventory/warehouses/${id}/reactivate`,
    )
    return data
  },

  // --- Inventory ---
  async list(params: Record<string, unknown> = {}): Promise<Paginated<Inventory>> {
    const { data } = await apiClient.get<Paginated<Inventory>>(
      `/inventory${toQueryString(params)}`,
    )
    return data
  },

  async getProductSummary(productId: string): Promise<ProductStockSummary> {
    const { data } = await apiClient.get<ProductStockSummary>(
      `/inventory/products/${productId}`,
    )
    return data
  },

  // --- Stock movements ---
  async addStock(payload: StockMovementPayload): Promise<StockMovementResponse> {
    const { data } = await apiClient.post<StockMovementResponse>(
      '/inventory/stock/add',
      payload,
    )
    return data
  },

  async removeStock(payload: RemoveStockPayload): Promise<StockMovementResponse> {
    const { data } = await apiClient.post<StockMovementResponse>(
      '/inventory/stock/remove',
      payload,
    )
    return data
  },

  async adjustStock(payload: AdjustStockPayload): Promise<StockMovementResponse> {
    const { data } = await apiClient.post<StockMovementResponse>(
      '/inventory/stock/adjust',
      payload,
    )
    return data
  },

  async transfer(payload: TransferPayload): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/inventory/transfers', payload)
    return data
  },

  // --- Transactions ---
  async listTransactions(
    params: Record<string, unknown> = {},
  ): Promise<Paginated<InventoryTransaction>> {
    const { data } = await apiClient.get<Paginated<InventoryTransaction>>(
      `/inventory/transactions${toQueryString(params)}`,
    )
    return data
  },

  // --- Reports ---
  async lowStockReport(
    statusFilter = 'low_stock',
  ): Promise<LowStockReportResponse> {
    const { data } = await apiClient.get<LowStockReportResponse>(
      `/inventory/reports/low-stock?status_filter=${statusFilter}`,
    )
    return data
  },
}
