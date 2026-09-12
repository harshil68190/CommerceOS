import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

interface StatCardProps {
  title: string
  value: ReactNode
  icon?: ReactNode
  description?: ReactNode
  className?: string
  loading?: boolean
  onClick?: () => void
}

/** KPI card used on the dashboard. */
export function StatCard({ title, value, icon, description, className, loading, onClick }: StatCardProps) {
  return (
    <Card
      className={cn(
        'surface-card overflow-hidden border-border/80 bg-white shadow-none',
        onClick && 'cursor-pointer transition hover:border-primary/40 hover:shadow-sm',
        className,
      )}
      onClick={onClick}
      onKeyDown={(event) => {
        if (onClick && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onClick()
        }
      }}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">{title}</CardTitle>
        {icon && (
          <div className="quiet-icon h-9 w-9">
            {icon}
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-2">
        {loading ? (
          <Skeleton className="h-7 w-20" />
        ) : (
          <div className="text-[28px] font-bold tracking-[-0.045em] text-slate-900">{value}</div>
        )}
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </CardContent>
    </Card>
  )
}
