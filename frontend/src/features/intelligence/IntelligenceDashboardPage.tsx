import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, BarChart3, ClipboardList, FlaskConical, ShieldAlert, Sparkles, TrendingDown } from 'lucide-react'
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatCard } from '@/components/widgets/StatCard'
import { DataTable, type Column } from '@/components/data/DataTable'
import { ErrorState } from '@/components/feedback/ErrorState'
import { LoadingState } from '@/components/feedback/LoadingState'
import { cn } from '@/lib/utils'
import type { ForecastHorizon, PositionSummary } from '@/types/api'
import { useIntelligenceDashboard } from './hooks'
import { ConfidenceBadge, RiskBadge } from './shared'
import { HORIZONS, formatCover, formatDay, formatStockoutDate } from './format'

export default function IntelligenceDashboardPage() {
  const navigate = useNavigate()
  const [horizon, setHorizon] = useState<ForecastHorizon>(30)
  const { data, isLoading, isError, error, refetch, isFetching } = useIntelligenceDashboard({
    horizon_days: horizon,
    lead_time_days: 7,
  })

  const openProduct = (row: PositionSummary) => navigate(`/intelligence/products/${row.product_id}`)

  const riskColumns: Column<PositionSummary>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.product_name}</p>
          <p className="text-xs text-muted-foreground">{r.product_sku} · {r.warehouse_code}</p>
        </div>
      ),
    },
    { key: 'risk', header: 'Risk', cell: (r) => <RiskBadge level={r.risk_level} /> },
    { key: 'available', header: 'Available', cell: (r) => r.available },
    { key: 'rate', header: 'Forecast/day', cell: (r) => r.daily_rate.toFixed(1) },
    { key: 'cover', header: 'Cover', cell: (r) => formatCover(r.days_of_cover) },
    { key: 'stockout', header: 'Stockout', cell: (r) => formatStockoutDate(r.stockout_date) },
    { key: 'conf', header: 'Confidence', cell: (r) => <ConfidenceBadge confidence={r.confidence} /> },
  ]

  const reorderColumns: Column<PositionSummary>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.product_name}</p>
          <p className="text-xs text-muted-foreground">{r.warehouse_name} ({r.warehouse_code})</p>
        </div>
      ),
    },
    { key: 'risk', header: 'Risk', cell: (r) => <RiskBadge level={r.risk_level} /> },
    { key: 'available', header: 'Available', cell: (r) => r.available },
    { key: 'qty', header: 'Order qty', cell: (r) => <span className="font-semibold">{r.recommended_quantity}</span> },
    { key: 'stockout', header: 'Stockout', cell: (r) => formatStockoutDate(r.stockout_date) },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="space-y-1">
          <p className="page-eyebrow">Inventory decision engine</p>
          <h1 className="page-title">CommerceOS Intelligence</h1>
          <p className="text-sm text-muted-foreground">
            Demand forecasts, stockout risk and reorder guidance from your live orders and inventory.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border bg-background p-0.5" role="group" aria-label="Forecast horizon">
            {HORIZONS.map((h) => (
              <button
                key={h}
                type="button"
                onClick={() => setHorizon(h)}
                aria-pressed={horizon === h}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-semibold transition',
                  horizon === h ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {h} days
              </button>
            ))}
          </div>
          <Button asChild>
            <Link to="/intelligence/simulate"><FlaskConical className="mr-2 h-4 w-4" />What-if simulation</Link>
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4" aria-busy="true" aria-label="Loading intelligence">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <StatCard key={i} title="Loading" value="" loading />
            ))}
          </div>
          <LoadingState rows={6} />
        </div>
      ) : isError || !data ? (
        <ErrorState
          title="Failed to load intelligence"
          message={error instanceof Error ? error.message : 'The intelligence data could not be loaded.'}
          onRetry={() => refetch()}
        />
      ) : data.kpis.total_positions === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <Sparkles className="h-8 w-8 text-muted-foreground" />
            <p className="font-medium">No stock positions to analyse yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Intelligence reads your inventory and order history. Add stock to a warehouse and it will appear here.
            </p>
            <Button variant="outline" onClick={() => navigate('/inventory')}>Go to inventory</Button>
          </CardContent>
        </Card>
      ) : (
        <div className={cn('space-y-4 transition-opacity', isFetching && 'opacity-70')}>
          {!data.has_demand_history && (
            <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                No confirmed, shipped or delivered orders were found in the last {data.assumptions.history_window_days} days,
                so demand is forecast at zero and nothing can be flagged. Forecasts appear as orders are fulfilled.
              </p>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              title="High risk"
              value={data.kpis.risk_counts.high}
              description={`${data.kpis.risk_counts.medium} medium · ${data.kpis.risk_counts.low} low · ${data.kpis.risk_counts.healthy} healthy`}
              icon={<ShieldAlert className="h-4 w-4" />}
            />
            <StatCard
              title={`Stockouts in ${horizon} days`}
              value={data.kpis.projected_stockouts}
              description={`${data.kpis.total_unserved_demand.toFixed(0)} units of unserved demand`}
              icon={<TrendingDown className="h-4 w-4" />}
            />
            <StatCard
              title="Need reorder"
              value={data.kpis.positions_needing_reorder}
              description={`${data.kpis.total_recommended_units} units recommended`}
              icon={<ClipboardList className="h-4 w-4" />}
            />
            <StatCard
              title="Forecast error (WAPE)"
              value={data.network_wape === null ? '—' : `${(data.network_wape * 100).toFixed(0)}%`}
              description={
                data.network_wape === null
                  ? 'No demand in the last 14 days'
                  : 'Lower is better. From the rolling 14-day backtest'
              }
              icon={<BarChart3 className="h-4 w-4" />}
            />
          </div>

          <Card>
            <CardHeader><CardTitle>Network demand: actual vs forecast (units/day)</CardTitle></CardHeader>
            <CardContent>
              <div className="h-72" role="img" aria-label="Line chart of actual and forecast daily demand">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.demand_trend} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="day" tickFormatter={formatDay} minTickGap={24} fontSize={11} />
                    <YAxis fontSize={11} allowDecimals={false} />
                    <Tooltip labelFormatter={(l) => formatDay(String(l))} />
                    <Legend />
                    <ReferenceLine x={data.as_of_date} stroke="#94a3b8" strokeDasharray="4 4" label={{ value: 'Today', fontSize: 11 }} />
                    <Line type="monotone" dataKey="actual" name="Actual" stroke="#0f172a" strokeWidth={2} dot={false} connectNulls={false} />
                    <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#2563eb" strokeWidth={2} strokeDasharray="5 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                History shows one-step-ahead forecasts (each day predicted only from earlier days), so accuracy is honest.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>High-risk products</CardTitle></CardHeader>
            <CardContent>
              <DataTable<PositionSummary>
                columns={riskColumns}
                data={data.high_risk}
                rowKey={(r) => `${r.product_id}-${r.warehouse_id}`}
                onRowClick={openProduct}
                emptyMessage="No high-risk positions. Stock covers demand beyond the supplier lead time."
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Reorder recommendations</CardTitle></CardHeader>
            <CardContent>
              <DataTable<PositionSummary>
                columns={reorderColumns}
                data={data.reorder_recommendations}
                rowKey={(r) => `${r.product_id}-${r.warehouse_id}`}
                onRowClick={openProduct}
                emptyMessage="Nothing to reorder right now."
              />
              <p className="mt-3 text-xs text-muted-foreground">
                Assumes a {data.assumptions.lead_time_days}-day supplier lead time. Select a row to see the full reasoning.
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
