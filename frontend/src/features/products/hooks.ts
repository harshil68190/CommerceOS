import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { productsApi } from '@/lib/api/products'
import { queryKeys } from '@/lib/query/queryKeys'
import type {
  CreateProductPayload,
  ProductFilters,
  UpdateProductPayload,
} from '@/types/api'

export function useProducts(filters: ProductFilters, enabled = true) {
  return useQuery({
    queryKey: queryKeys.products.list(filters),
    queryFn: () => productsApi.list(filters),
    placeholderData: (prev) => prev,
    enabled,
  })
}

export function useAdminProducts(filters: ProductFilters, enabled = true) {
  return useQuery({
    queryKey: queryKeys.products.admin(filters),
    queryFn: () => productsApi.listAdmin(filters),
    placeholderData: (prev) => prev,
    enabled,
  })
}

export function useCreateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CreateProductPayload) => productsApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    },
  })
}

export function useUpdateProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: UpdateProductPayload }) =>
      productsApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    },
  })
}

export function useArchiveProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => productsApi.archive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    },
  })
}

export function useDeleteProduct() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => productsApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.products.all })
    },
  })
}
