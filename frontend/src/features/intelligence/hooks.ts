import { useMutation, useQuery } from '@tanstack/react-query'
import { intelligenceApi, type IntelligenceParams } from '@/lib/api/intelligence'
import { queryKeys } from '@/lib/query/queryKeys'
import type { SimulationPayload } from '@/types/api'

export function useIntelligenceDashboard(params: IntelligenceParams) {
  return useQuery({
    queryKey: queryKeys.intelligence.dashboard(params),
    queryFn: () => intelligenceApi.dashboard(params),
    placeholderData: (prev) => prev,
  })
}

export function useProductIntelligence(
  productId: string | undefined,
  params: IntelligenceParams,
) {
  return useQuery({
    queryKey: queryKeys.intelligence.product(productId ?? '', params),
    queryFn: () => intelligenceApi.product(productId as string, params),
    enabled: Boolean(productId),
    placeholderData: (prev) => prev,
  })
}

/** Simulation is a read-only POST, so it is modelled as a mutation. */
export function useSimulation() {
  return useMutation({
    mutationFn: (payload: SimulationPayload) => intelligenceApi.simulate(payload),
  })
}
