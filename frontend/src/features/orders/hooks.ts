import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ordersApi } from '@/lib/api/orders'
import { queryKeys } from '@/lib/query/queryKeys'
import type { OrderCreatePayload, OrderFilters, OrderUpdatePayload } from '@/types/api'

export function useOrders(filters: OrderFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orders.list(filters),
    queryFn: () => ordersApi.list(filters),
    placeholderData: (prev) => prev,
    enabled,
  })
}

export function useMyOrders(filters: OrderFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.orders.my(filters),
    queryFn: () => ordersApi.listMy(filters),
    placeholderData: (prev) => prev,
    enabled,
  })
}

export function useOrder(id: string) {
  return useQuery({
    queryKey: queryKeys.orders.detail(id),
    queryFn: () => ordersApi.get(id),
    enabled: !!id,
  })
}

function invalidateOrders(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: queryKeys.orders.all })
  qc.invalidateQueries({ queryKey: queryKeys.inventory.all })
  qc.invalidateQueries({ queryKey: queryKeys.products.all })
}

export function useCreateOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: OrderCreatePayload) => ordersApi.create(payload),
    onSuccess: () => invalidateOrders(qc),
  })
}

export function useUpdateOrder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: OrderUpdatePayload }) =>
      ordersApi.update(id, payload),
    onSuccess: (_, { id }) => {
      void id
      invalidateOrders(qc)
    },
  })
}

export function useOrderTransition(action: keyof typeof ordersApi) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      (ordersApi[action] as (id: string) => Promise<unknown>)(id),
    onSuccess: () => invalidateOrders(qc),
  })
}
