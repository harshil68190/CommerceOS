/**
 * Build a URL query string from an object of params, skipping empty values.
 * Shared by the API modules so query-string construction stays DRY.
 */
export function toQueryString(params: object = {}): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      usp.append(k, String(v))
    }
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}
