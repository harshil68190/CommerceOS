import { Badge } from '@/components/ui/badge'
import { humanize } from '@/lib/utils'
import type { ForecastConfidence, RiskLevel } from '@/types/api'

const RISK_VARIANT: Record<RiskLevel, 'success' | 'secondary' | 'warning' | 'destructive'> = {
  healthy: 'success',
  low: 'secondary',
  medium: 'warning',
  high: 'destructive',
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  return <Badge variant={RISK_VARIANT[level]}>{humanize(level)}</Badge>
}

export function ConfidenceBadge({ confidence }: { confidence: ForecastConfidence }) {
  const variant = confidence === 'high' ? 'success' : confidence === 'none' ? 'muted' : 'warning'
  return <Badge variant={variant}>{humanize(confidence)} confidence</Badge>
}
