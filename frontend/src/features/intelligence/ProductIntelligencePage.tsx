import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, FlaskConical } from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatCard } from '@/components/widgets/StatCard'
import { ErrorState } from '@/components/feedback/ErrorState'
import { LoadingState } from '@/components/feedback/LoadingState'
import { ApiClientError } from '@/lib/api/client'
import { cn } from '@/lib/utils'
import type { ForecastHorizon, PositionIntelligence } from '@/types/api'
import { useProductIntelligence } from './hooks'
import { ConfidenceBadge, RiskBadge } from './shared'
import { HORIZONS, formatCover, formatDay, formatStockoutDate } from './format'

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-1.5 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value}</span>
    </div>
  )
}

function PositionCard({ pos, productId }: { pos: PositionIntelligence; productId: string }) {
  const f = pos.forecast
  const r = pos.reorder
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>{pos.warehouse_name}</CardTitle>
          <p className="text-xs text-muted-foreground">{pos.warehouse_code}</p>
        </div>
        <div className="flex items-center gap-2">
          <ConfidenceBadge confidence={f.confidence} />
          <RiskBadge level={pos.risk.level} />
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <section aria-label="Why this risk level">
          <h3 className="mb-2 text-sm font-semibold">Why this recommendation</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {pos.reasoning.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
        </section>

        <div className="grid gap-6 lg:grid-cols-2">
          <section aria-label="Forecast">
            <h3 className="mb-1 text-sm font-semibold">Forecast</h3>
            <Row label="Weighted forecast" value={`${f.daily_rate.toFixed(2)} / day`} />
            <Row label="7-day average (×0.5)" value={f.ma_7.toFixed(2)} />
            <Row label="14-day average (×0.3)" value={f.ma_14.toFixed(2)} />
            <Row label="30-day average (×0.2)" value={f.ma_30.toFixed(2)} />
            <Row label="Daily std deviation" value={f.sigma_daily.toFixed(2)} />
            <Row label="History used" value={`${f.history_days} days · ${f.total_units_in_history} units`} />
            <Row label="Backtest error (WAPE)" value={pos.wape === null ? '—' : `${(pos.wape * 100).toFixed(0)}%`} />
          </section>
          <section aria-label="Stock position">
            <h3 className="mb-1 text-sm font-semibold">Stock & stockout</h3>
            <Row label="On hand" value={pos.quantity} />
            <Row label="Reserved" value={pos.reserved_quantity} />
            <Row label="Available" value={pos.available} />
            <Row label="Days of cover" value={formatCover(pos.risk.days_of_cover)} />
            <Row label="Stockout date" value={formatStockoutDate(pos.stockout_date)} />
            <Row label="Unserved demand in horizon" value={pos.unserved_demand.toFixed(0)} />
            <Row label="Configured reorder level / max" value={`${pos.reorder_level} / ${pos.max_stock || 'no cap'}`} />
          </section>
        </div>

        <section aria-label="Projected inventory">
          <h3 className="mb-2 text-sm font-semibold">Projected inventory</h3>
          <div className="h-56" role="img" aria-label="Projected stock over the forecast horizon">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={pos.projection} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tickFormatter={formatDay} minTickGap={24} fontSize={11} />
                <YAxis fontSize={11} allowDecimals={false} />
                <Tooltip labelFormatter={(l) => formatDay(String(l))} />
                {pos.reorder_level > 0 && (
                  <ReferenceLine y={pos.reorder_level} stroke="#f59e0b" strokeDasharray="4 4" label={{ value: 'Reorder level', fontSize: 11 }} />
                )}
                <Area type="monotone" dataKey="projected_stock" name="Projected stock" stroke="#2563eb" fill="#2563eb22" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section aria-label="Forecast versus actual">
          <h3 className="mb-2 text-sm font-semibold">Demand: forecast vs actual</h3>
          <div className="h-56" role="img" aria-label="Actual and forecast daily demand">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={pos.demand_history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" tickFormatter={formatDay} minTickGap={24} fontSize={11} />
                <YAxis fontSize={11} />
                <Tooltip labelFormatter={(l) => formatDay(String(l))} />
                <Legend />
                <Line type="monotone" dataKey="actual" name="Actual" stroke="#0f172a" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#2563eb" strokeDasharray="5 3" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section aria-label="Reorder recommendation" className="rounded-xl border bg-muted/20 p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Reorder recommendation</h3>
            <span className={cn('text-lg font-bold', r.recommended_quantity > 0 ? 'text-foreground' : 'text-muted-foreground')}>
              {r.recommended_quantity > 0 ? `Order ${r.recommended_quantity} units` : 'No reorder needed'}
            </span>
          </div>
          <div className="grid gap-x-8 sm:grid-cols-2">
            <Row label="Lead-time demand" value={r.lead_time_demand.toFixed(1)} />
            <Row label="Safety stock" value={r.safety_stock.toFixed(1)} />
            <Row label="Reorder point" value={r.effective_reorder_point} />
            <Row label="Order-up-to level" value={`${r.target_stock}${r.capped_by_max_stock ? ' (capped at max stock)' : ''}`} />
          </div>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            {r.reasons.map((line, i) => <li key={i}>{line}</li>)}
          </ul>
          <Button asChild variant="outline" size="sm" className="mt-4">
            <Link to={`/intelligence/simulate?product=${productId}`}>
              <FlaskConical className="mr-2 h-4 w-4" />Simulate demand change
            </Link>
          </Button>
        </section>
      </CardContent>
    </Card>
  )
}

export default function ProductIntelligencePage() {
  const { productId } = useParams<{ productId: string }>()
  const [horizon, setHorizon] = useState<ForecastHorizon>(30)
  const { data, isLoading, isError, error, refetch } = useProductIntelligence(productId, {
    horizon_days: horizon,
    lead_time_days: 7,
  })

  const notFound = error instanceof ApiClientError && error.status === 404

  return (
    <div className="space-y-4">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/intelligence"><ArrowLeft className="mr-2 h-4 w-4" />Intelligence</Link>
      </Button>

      {isLoading ? (
        <LoadingState rows={8} />
      ) : isError || !data ? (
        <ErrorState
          title={notFound ? 'Product not found' : 'Failed to load product intelligence'}
          message={error instanceof Error ? error.message : undefined}
          onRetry={notFound ? undefined : () => refetch()}
        />
      ) : (
        <>
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-1">
              <p className="page-eyebrow">Product risk</p>
              <h1 className="page-title">{data.product_name}</h1>
              <p className="text-sm text-muted-foreground">{data.product_sku}</p>
            </div>
            <div className="inline-flex rounded-lg border bg-background p-0.5" role="group" aria-label="Forecast horizon">
              {HORIZONS.map((h) => (
                <button
                  key={h}
                  type="button"
                  aria-pressed={horizon === h}
                  onClick={() => setHorizon(h)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-xs font-semibold transition',
                    horizon === h ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {h} days
                </button>
              ))}
            </div>
          </div>

          {data.positions.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-sm text-muted-foreground">
                This product has no tracked stock in any active warehouse, so there is nothing to forecast.
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard title="Worst risk" value={<RiskBadge level={data.aggregate.worst_risk} />} description={`${data.positions.length} warehouse position(s)`} />
                <StatCard title="Available" value={data.aggregate.total_available} description={`${data.aggregate.total_daily_rate.toFixed(1)} units/day forecast`} />
                <StatCard title="First stockout" value={formatStockoutDate(data.aggregate.earliest_stockout_date)} description={`${data.aggregate.projected_stockouts} within ${horizon} days`} />
                <StatCard title="Recommended order" value={data.aggregate.total_recommended_quantity} description="units across warehouses" />
              </div>
              {data.positions.map((pos) => (
                <PositionCard key={pos.warehouse_id} pos={pos} productId={data.product_id} />
              ))}
            </>
          )}
        </>
      )}
    </div>
  )
}
