import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { inventoryApi } from '@/lib/api/inventory'
import { queryKeys } from '@/lib/query/queryKeys'
import type {
  AdjustStockPayload,
  RemoveStockPayload,
  StockMovementPayload,
  WarehouseCreatePayload,
  WarehouseUpdatePayload,
} from '@/types/api'

// --- Warehouses ---
export function useWarehouses(filters: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: queryKeys.warehouses.list(filters),
    queryFn: () => inventoryApi.listWarehouses(filters),
    placeholderData: (prev) => prev,
  })
}

export function useCreateWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: WarehouseCreatePayload) => inventoryApi.createWarehouse(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.warehouses.all }),
  })
}

export function useUpdateWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: WarehouseUpdatePayload }) =>
      inventoryApi.updateWarehouse(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.warehouses.all }),
  })
}

export function useDeactivateWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => inventoryApi.deactivateWarehouse(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.warehouses.all }),
  })
}

export function useReactivateWarehouse() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => inventoryApi.reactivateWarehouse(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.warehouses.all }),
  })
}

// --- Inventory ---
export function useInventory(filters: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: queryKeys.inventory.list(filters),
    queryFn: () => inventoryApi.list(filters),
    placeholderData: (prev) => prev,
  })
}

export function useLowStockReport(status = 'low_stock') {
  return useQuery({
    queryKey: queryKeys.inventory.lowStock(status),
    queryFn: () => inventoryApi.lowStockReport(status),
  })
}

export function useTransactions(filters: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: queryKeys.inventory.transactions(filters),
    queryFn: () => inventoryApi.listTransactions(filters),
    placeholderData: (prev) => prev,
  })
}

// --- Stock mutations ---
function invalidateInventory(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: queryKeys.inventory.all })
  qc.invalidateQueries({ queryKey: queryKeys.products.all })
}

export function useAddStock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: StockMovementPayload) => inventoryApi.addStock(payload),
    onSuccess: () => invalidateInventory(qc),
  })
}

export function useRemoveStock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: RemoveStockPayload) => inventoryApi.removeStock(payload),
    onSuccess: () => invalidateInventory(qc),
  })
}

export function useAdjustStock() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AdjustStockPayload) => inventoryApi.adjustStock(payload),
    onSuccess: () => invalidateInventory(qc),
  })
}
