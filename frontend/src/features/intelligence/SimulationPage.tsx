import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, FlaskConical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { StatCard } from '@/components/widgets/StatCard'
import { DataTable, type Column } from '@/components/data/DataTable'
import { ErrorState } from '@/components/feedback/ErrorState'
import { cn } from '@/lib/utils'
import type { ForecastHorizon, SimulationDelta } from '@/types/api'
import { useSimulation } from './hooks'
import { RiskBadge } from './shared'
import { HORIZONS, formatDemandRate, formatStockoutDate } from './format'

const PRESETS = [-20, 10, 20, 50]
const MIN_PERCENT = -100
const MAX_PERCENT = 1000

function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n)
}

export default function SimulationPage() {
  const [params] = useSearchParams()
  const productId = params.get('product') ?? undefined
  const [percentText, setPercentText] = useState('20')
  const [horizon, setHorizon] = useState<ForecastHorizon>(30)
  const sim = useSimulation()

  const percent = Number(percentText)
  const valid = percentText.trim() !== '' && Number.isFinite(percent) && percent >= MIN_PERCENT && percent <= MAX_PERCENT

  const run = () => {
    if (!valid) return
    sim.mutate({ demand_change_percent: percent, horizon_days: horizon, product_id: productId })
  }

  const result = sim.data

  const columns: Column<SimulationDelta>[] = [
    {
      key: 'product',
      header: 'Product',
      cell: (d) => (
        <div>
          <p className="font-medium">{d.product_name}</p>
          <p className="text-xs text-muted-foreground">{d.product_sku} · {d.warehouse_code}</p>
        </div>
      ),
    },
    {
      key: 'risk',
      header: 'Risk',
      cell: (d) => (
        <div className="flex items-center gap-1.5">
          <RiskBadge level={d.baseline_risk} />
          {d.risk_changed && (<><ArrowRight className="h-3 w-3 text-muted-foreground" /><RiskBadge level={d.scenario_risk} /></>)}
        </div>
      ),
    },
    { key: 'rate', header: 'Demand/day', cell: (d) => `${formatDemandRate(d.baseline_daily_rate)} → ${formatDemandRate(d.scenario_daily_rate)}` },
    { key: 'stockout', header: 'Projected stockout', cell: (d) => `${formatStockoutDate(d.baseline_stockout_date)} → ${formatStockoutDate(d.scenario_stockout_date)}` },
    {
      key: 'extra',
      header: 'Extra reorder',
      cell: (d) => (
        <span className={cn('font-semibold', d.additional_reorder_quantity > 0 && 'text-amber-700')}>
          {signed(d.additional_reorder_quantity)}
        </span>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/intelligence"><ArrowLeft className="mr-2 h-4 w-4" />Intelligence</Link>
      </Button>
      <div className="space-y-1">
        <p className="page-eyebrow">What-if simulation</p>
        <h1 className="page-title">Demand scenario</h1>
        <p className="text-sm text-muted-foreground">
          Change demand by a percentage and see how stockout risk and reorder needs shift. Nothing is saved or modified.
          {productId && ' Limited to the selected product.'}
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6 md:flex-row md:items-end">
          <div className="space-y-2">
            <Label htmlFor="demand-change">Demand change (%)</Label>
            <Input
              id="demand-change"
              type="number"
              inputMode="decimal"
              min={MIN_PERCENT}
              max={MAX_PERCENT}
              step="any"
              value={percentText}
              onChange={(e) => setPercentText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') run() }}
              aria-invalid={!valid}
              aria-describedby="demand-change-help"
              className="w-40"
            />
            <div className="flex gap-1.5">
              {PRESETS.map((p) => (
                <Button key={p} type="button" size="sm" variant="outline" onClick={() => setPercentText(String(p))}>
                  {signed(p)}%
                </Button>
              ))}
            </div>
            <p id="demand-change-help" className={cn('text-xs', valid ? 'text-muted-foreground' : 'text-destructive')}>
              {valid ? 'Between −100% and +1000%.' : 'Enter a number between −100 and 1000.'}
            </p>
          </div>
          <div className="space-y-2">
            <Label>Horizon</Label>
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
          <Button onClick={run} disabled={!valid || sim.isPending}>
            <FlaskConical className="mr-2 h-4 w-4" />
            {sim.isPending ? 'Running…' : 'Run simulation'}
          </Button>
        </CardContent>
      </Card>

      {sim.isError ? (
        <ErrorState
          title="Simulation failed"
          message={sim.error instanceof Error ? sim.error.message : undefined}
          onRetry={run}
        />
      ) : !result ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            Choose a demand change and run the simulation to compare against the baseline forecast.
          </CardContent>
        </Card>
      ) : result.positions_analyzed === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            There are no stock positions to simulate.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4" aria-live="polite">
          <p className="text-xs text-muted-foreground">
            Reference date: {formatStockoutDate(result.as_of_date)}. Forecasts use this inventory snapshot and demand through the previous day.
          </p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              title="Positions analyzed"
              value={result.positions_analyzed}
              description={`${result.changed_positions_count} positions affected by this scenario`}
            />
            <StatCard
              title="Stockout dates changed"
              value={result.positions_with_stockout_date_change}
              description="Date differs between baseline and scenario"
            />
            <StatCard
              title="Risk levels changed"
              value={result.positions_with_risk_change}
              description={`of ${result.positions_analyzed} positions analyzed`}
            />
            <StatCard
              title="New projected stockouts"
              value={result.newly_projected_stockouts}
              description={`Scenario stockout within ${result.assumptions.horizon_days} days; not present at baseline`}
            />
            <StatCard
              title="Stockouts within horizon"
              value={`${result.baseline.projected_stockouts} → ${result.scenario.projected_stockouts}`}
              description={`${signed(result.additional_projected_stockouts)} net change within ${result.assumptions.horizon_days} days`}
            />
            <StatCard
              title="Additional reorder"
              value={`${signed(result.additional_reorder_units)}`}
              description={`${result.baseline.total_recommended_units} → ${result.scenario.total_recommended_units} units`}
            />
            <StatCard
              title="Unserved demand"
              value={`${result.baseline.total_unserved_demand.toFixed(0)} → ${result.scenario.total_unserved_demand.toFixed(0)}`}
              description="units over the horizon"
            />
          </div>
          <Card>
            <CardHeader><CardTitle>Positions affected ({signed(result.demand_change_percent)}% demand)</CardTitle></CardHeader>
            <CardContent>
              <DataTable<SimulationDelta>
                columns={columns}
                data={result.changed_positions}
                rowKey={(d) => `${d.product_id}-${d.warehouse_id}`}
                emptyMessage="This scenario changes no stockout dates, risk levels, horizon stockouts or reorder quantities."
              />
              {result.changed_positions_count > result.changed_positions.length && (
                <p className="mt-3 text-xs text-muted-foreground">
                  Showing {result.changed_positions.length} of {result.changed_positions_count} affected positions.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
