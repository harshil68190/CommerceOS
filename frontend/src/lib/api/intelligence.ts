import { apiClient } from '@/lib/api/client'
import { toQueryString } from '@/lib/queryString'
import type {
  ForecastHorizon,
  IntelligenceDashboard,
  ProductIntelligence,
  SimulationPayload,
  SimulationResult,
} from '@/types/api'

export interface IntelligenceParams {
  horizon_days: ForecastHorizon
  lead_time_days: number
}

export const intelligenceApi = {
  async dashboard(params: IntelligenceParams): Promise<IntelligenceDashboard> {
    const { data } = await apiClient.get<IntelligenceDashboard>(
      `/intelligence/dashboard${toQueryString({ ...params })}`,
    )
    return data
  },

  async product(
    productId: string,
    params: IntelligenceParams,
  ): Promise<ProductIntelligence> {
    const { data } = await apiClient.get<ProductIntelligence>(
      `/intelligence/products/${productId}${toQueryString({ ...params })}`,
    )
    return data
  },

  async simulate(payload: SimulationPayload): Promise<SimulationResult> {
    const { data } = await apiClient.post<SimulationResult>(
      '/intelligence/simulate',
      payload,
    )
    return data
  },
}
