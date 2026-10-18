/**
 * Shared API types mirrored from the backend Pydantic schemas.
 * These are kept in sync with the backend. An OpenAPI-generated version
 * (src/types/api.generated.ts) can be produced via `npm run typegen` when
 * the backend is running.
 */

/** Uniform backend error envelope. */
export interface ApiError {
  error_code: string
  message: string
  details: Record<string, unknown>
  request_id: string
}

/** Uniform paginated envelope. */
export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

// --- Auth ---------------------------------------------------------------

export type UserRole = 'admin' | 'seller' | 'inventory_manager' | 'customer'

export interface User {
  id: string
  email: string
  username: string
  first_name: string
  last_name: string
  phone: string | null
  is_active: boolean
  is_verified: boolean
  role: UserRole
  created_at: string
  last_login: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface RegisterPayload {
  email: string
  username: string
  password: string
  confirm_password: string
  first_name: string
  last_name: string
  phone?: string | null
}

export interface LoginPayload {
  email: string
  password: string
}

export interface ProfileUpdatePayload {
  first_name: string
  last_name: string
  phone?: string | null
}

// --- Products -----------------------------------------------------------

export type ProductStatus = 'active' | 'draft' | 'archived' | 'out_of_stock'

export interface Product {
  id: string
  sku: string
  slug: string
  name: string
  description: string | null
  short_description: string | null
  brand: string | null
  category: string | null
  price: string
  compare_at_price: string | null
  currency: string
  weight: string | null
  status: ProductStatus
  is_featured: boolean
  track_inventory: boolean
  created_by: string
  updated_by: string | null
  created_at: string
  updated_at: string
}

export interface CreateProductPayload {
  sku: string
  slug: string
  name: string
  description?: string | null
  short_description?: string | null
  brand?: string | null
  category?: string | null
  price: string
  compare_at_price?: string | null
  currency?: string
  weight?: string | null
  status: 'active' | 'draft'
  is_featured?: boolean
  track_inventory?: boolean
}

export interface UpdateProductPayload {
  slug?: string
  name?: string
  description?: string | null
  short_description?: string | null
  brand?: string | null
  category?: string | null
  price?: string
  compare_at_price?: string | null
  currency?: string
  weight?: string | null
  status?: 'active' | 'draft'
  is_featured?: boolean
  track_inventory?: boolean
}

export interface ProductFilters {
  category?: string
  brand?: string
  status?: string
  featured?: boolean
  price_min?: number
  price_max?: number
  sort?: string
  page?: number
  page_size?: number
  q?: string
}

// --- Inventory ----------------------------------------------------------

export type StockStatus = 'in_stock' | 'low_stock' | 'out_of_stock'

export interface Warehouse {
  id: string
  name: string
  code: string
  address: string | null
  city: string | null
  state: string | null
  country: string | null
  postal_code: string | null
  contact_number: string | null
  email: string | null
  is_active: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface WarehouseCreatePayload {
  name: string
  code: string
  address?: string | null
  city?: string | null
  state?: string | null
  country?: string | null
  postal_code?: string | null
  contact_number?: string | null
  email?: string | null
}

export interface WarehouseUpdatePayload {
  name?: string
  code?: string
  address?: string | null
  city?: string | null
  state?: string | null
  country?: string | null
  postal_code?: string | null
  contact_number?: string | null
  email?: string | null
  is_active?: boolean
}

export interface Inventory {
  id: string
  product_id: string
  warehouse_id: string
  quantity: number
  reserved_quantity: number
  available_quantity: number
  reorder_level: number
  max_stock: number
  version: number
  stock_status: StockStatus
  last_stock_update: string | null
  created_at: string
  updated_at: string
}

export interface InventoryTransaction {
  id: string
  product_id: string
  warehouse_id: string
  transaction_type: string
  quantity: number
  previous_quantity: number
  new_quantity: number
  previous_reserved_quantity: number
  new_reserved_quantity: number
  reference_number: string | null
  correlation_id: string | null
  notes: string | null
  created_by: string
  created_at: string
}

export interface StockMovementResponse {
  inventory: Inventory
  transaction: InventoryTransaction
}

export interface LowStockItem {
  product_id: string
  product_name: string
  product_sku: string
  warehouse_id: string
  warehouse_name: string
  warehouse_code: string
  quantity: number
  reserved_quantity: number
  available_quantity: number
  reorder_level: number
  stock_status: StockStatus
}

export interface LowStockReportResponse {
  items: LowStockItem[]
  total: number
}

export interface ProductStockSummary {
  product_id: string
  total_stock: number
  total_reserved: number
  total_available: number
  warehouse_count: number
  warehouses: Array<Record<string, unknown>>
}

export interface StockMovementPayload {
  product_id: string
  warehouse_id: string
  quantity: number
  reference_number?: string | null
  notes?: string | null
}

export interface RemoveStockPayload extends StockMovementPayload {
  reason: string
}

export interface AdjustStockPayload {
  product_id: string
  warehouse_id: string
  new_quantity: number
  reference_number?: string | null
  notes?: string | null
}

export interface TransferPayload {
  product_id: string
  from_warehouse_id: string
  to_warehouse_id: string
  quantity: number
  reference_number?: string | null
  notes?: string | null
}

// --- Orders -------------------------------------------------------------

export type OrderStatus =
  | 'pending'
  | 'confirmed'
  | 'shipped'
  | 'delivered'
  | 'cancelled'
  | 'returned'
  | 'refunded'

export type PaymentStatus =
  | 'unpaid'
  | 'authorized'
  | 'paid'
  | 'failed'
  | 'refunded'

export interface OrderItem {
  id: string
  product_id: string
  product_name: string
  product_sku: string
  warehouse_id: string
  quantity: number
  unit_price: string
  line_total: string
  created_at: string
}

export interface Order {
  id: string
  order_number: string
  customer_id: string
  status: OrderStatus
  subtotal: string
  tax: string
  shipping_cost: string
  discount: string
  total: string
  payment_status: PaymentStatus
  notes: string | null
  reserved_until: string | null
  cancel_reason: string | null
  version: number
  created_by: string
  updated_by: string | null
  created_at: string
  updated_at: string
  items: OrderItem[]
}

export interface OrderCreatePayload {
  items: Array<{
    product_id: string
    warehouse_id: string
    quantity: number
  }>
  notes?: string | null
  shipping_cost?: string
  discount?: string
}

export interface OrderUpdatePayload {
  notes?: string | null
  shipping_cost?: string
  discount?: string
}

export interface OrderStatusTransitionResponse {
  id: string
  order_number: string
  status: OrderStatus
  payment_status: PaymentStatus
  version: number
  updated_at: string
  message?: string | null
}

export interface OrderFilters {
  status?: string
  payment_status?: string
  sort?: string
  page?: number
  page_size?: number
}

export interface DashboardSummary {
  totalProducts: number
  totalOrders: number
  orderValue: string
  lowStockCount: number
  outOfStockCount: number
  recentOrders: Order[]
  lowStockItems: LowStockItem[]
}

// --- CommerceOS Intelligence ----------------------------------------------

export type RiskLevel = 'healthy' | 'low' | 'medium' | 'high'
export type ForecastConfidence = 'none' | 'low' | 'medium' | 'high'
export type ForecastHorizon = 7 | 14 | 30

export interface IntelligenceAssumptions {
  horizon_days: number
  lead_time_days: number
  service_level_z: number
  forecast_weights: Record<string, number>
  risk_thresholds_days: { high: number; medium: number; low: number }
  demand_statuses: string[]
  history_window_days: number
  notes: string[]
}

export interface DemandPoint {
  day: string
  actual?: number | null
  forecast?: number | null
}

export interface RiskCounts {
  healthy: number
  low: number
  medium: number
  high: number
}

export interface IntelligenceKpis {
  total_positions: number
  positions_with_demand: number
  risk_counts: RiskCounts
  projected_stockouts: number
  positions_needing_reorder: number
  total_recommended_units: number
  total_unserved_demand: number
}

export interface PositionSummary {
  product_id: string
  product_name: string
  product_sku: string
  warehouse_id: string
  warehouse_name: string
  warehouse_code: string
  available: number
  daily_rate: number
  days_of_cover: number | null
  risk_level: RiskLevel
  stockout_date: string | null
  stocks_out_in_horizon: boolean
  confidence: ForecastConfidence
  recommended_quantity: number
  reorder_needed: boolean
}

export interface IntelligenceDashboard {
  generated_at: string
  as_of_date: string
  assumptions: IntelligenceAssumptions
  kpis: IntelligenceKpis
  high_risk: PositionSummary[]
  reorder_recommendations: PositionSummary[]
  demand_trend: DemandPoint[]
  network_wape: number | null
  has_demand_history: boolean
}

export interface PositionForecast {
  daily_rate: number
  ma_7: number
  ma_14: number
  ma_30: number
  sigma_daily: number
  history_days: number
  total_units_in_history: number
  confidence: ForecastConfidence
  forecast_demand_horizon: number
}

export interface PositionReorder {
  available: number
  lead_time_demand: number
  safety_stock: number
  computed_reorder_point: number
  configured_reorder_level: number
  effective_reorder_point: number
  target_stock: number
  max_stock: number
  capped_by_max_stock: boolean
  reorder_needed: boolean
  recommended_quantity: number
  reasons: string[]
}

export interface ProjectionPoint {
  day: string
  projected_stock: number
  cumulative_demand: number
}

export interface PositionIntelligence {
  product_id: string
  product_name: string
  product_sku: string
  warehouse_id: string
  warehouse_name: string
  warehouse_code: string
  quantity: number
  reserved_quantity: number
  available: number
  reorder_level: number
  max_stock: number
  forecast: PositionForecast
  risk: { level: RiskLevel; days_of_cover: number | null; reasons: string[] }
  stockout_date: string | null
  stocks_out_in_horizon: boolean
  unserved_demand: number
  reorder: PositionReorder
  reasoning: string[]
  wape: number | null
  projection: ProjectionPoint[]
  demand_history: DemandPoint[]
}

export interface ProductIntelligence {
  generated_at: string
  as_of_date: string
  product_id: string
  product_name: string
  product_sku: string
  assumptions: IntelligenceAssumptions
  aggregate: {
    total_available: number
    total_daily_rate: number
    total_recommended_quantity: number
    worst_risk: RiskLevel
    earliest_stockout_date: string | null
    projected_stockouts: number
  }
  positions: PositionIntelligence[]
  demand_trend: DemandPoint[]
}

export interface SimulationPayload {
  demand_change_percent: number
  horizon_days: ForecastHorizon
  lead_time_days?: number
  product_id?: string
  warehouse_id?: string
}

export interface ScenarioSummary {
  risk_counts: RiskCounts
  projected_stockouts: number
  positions_needing_reorder: number
  total_recommended_units: number
  total_unserved_demand: number
}

export interface SimulationDelta {
  product_id: string
  product_name: string
  product_sku: string
  warehouse_id: string
  warehouse_name: string
  warehouse_code: string
  available: number
  baseline_daily_rate: number
  scenario_daily_rate: number
  baseline_risk: RiskLevel
  scenario_risk: RiskLevel
  risk_changed: boolean
  baseline_stockout_date: string | null
  scenario_stockout_date: string | null
  baseline_stocks_out_in_horizon: boolean
  scenario_stocks_out_in_horizon: boolean
  newly_stocking_out: boolean
  baseline_recommended_quantity: number
  scenario_recommended_quantity: number
  additional_reorder_quantity: number
}

export interface SimulationResult {
  generated_at: string
  as_of_date: string
  demand_change_percent: number
  assumptions: IntelligenceAssumptions
  positions_analyzed: number
  changed_positions_count: number
  baseline: ScenarioSummary
  scenario: ScenarioSummary
  additional_projected_stockouts: number
  additional_reorder_units: number
  positions_with_risk_change: number
  positions_with_stockout_date_change: number
  newly_projected_stockouts: number
  changed_positions: SimulationDelta[]
}
