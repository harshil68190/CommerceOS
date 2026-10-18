export function formatDay(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(`${value}T00:00:00`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Stockout projections can be years beyond the selected horizon. Keep the
 * year visible so an October forecast in 2301 cannot look like a past date. */
export function formatStockoutDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(`${value}T00:00:00`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Four significant digits reveal small scenario changes without noisy
 * trailing decimals for ordinary and large daily rates. */
export function formatDemandRate(rate: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 }).format(rate)
}

export function formatCover(days: number | null | undefined): string {
  if (days === null || days === undefined) return 'No demand'
  return `${days.toFixed(1)} d`
}

export const HORIZONS = [7, 14, 30] as const
