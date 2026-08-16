import type { ReactNode } from 'react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/feedback/LoadingState'
import { ErrorState } from '@/components/feedback/ErrorState'
import { cn } from '@/lib/utils'

export interface Column<T> {
  key: string
  header: string
  cell: (row: T) => ReactNode
  className?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  emptyMessage?: string
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  page?: number
  pages?: number
  total?: number
  onPageChange?: (page: number) => void
}

/** Generic paginated data table with loading/error/empty states. */
export function DataTable<T>({
  columns,
  data,
  loading = false,
  error,
  onRetry,
  emptyMessage = 'No records found.',
  rowKey,
  onRowClick,
  page,
  pages,
  total,
  onPageChange,
}: DataTableProps<T>) {
  if (loading) {
    return <LoadingState rows={6} />
  }

  if (error) {
    return (
      <ErrorState
        title="Failed to load data"
        message={error instanceof Error ? error.message : undefined}
        onRetry={onRetry}
      />
    )
  }

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-dashed bg-muted/20 p-8 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    )
  }

  return (
    <div>
      <div className="overflow-hidden rounded-xl border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30 hover:bg-muted/30">
              {columns.map((col) => (
                <TableHead key={col.key} className={cn('text-xs uppercase tracking-[0.12em] text-muted-foreground', col.className)}>
                  {col.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((row) => (
              <TableRow
                key={rowKey(row)}
                className={cn('align-middle transition-colors', onRowClick && 'cursor-pointer hover:bg-muted/30')}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((col) => (
                  <TableCell key={col.key} className={cn('py-3 text-sm', col.className)}>
                    {col.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {page !== undefined && pages !== undefined && onPageChange && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            Page {page} of {pages || 1}
            {total !== undefined && ` · ${total} total`}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= (pages || 1)}
              onClick={() => onPageChange(page + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
