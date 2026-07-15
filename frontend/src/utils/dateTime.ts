const EXPLICIT_TIME_ZONE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/
const DATE_TIME_WITHOUT_ZONE = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/

/**
 * API timestamps are stored in UTC. SQLite returns them without an offset,
 * while PostgreSQL includes one, so normalise only the offset-less form.
 */
export function parseApiDateTime(value: string): Date {
  const source = value.trim()
  const normalized = DATE_TIME_WITHOUT_ZONE.test(source) && !EXPLICIT_TIME_ZONE.test(source)
    ? `${source.replace(' ', 'T')}Z`
    : source
  return new Date(normalized)
}

export function formatApiDateTime(
  value: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' },
): string {
  const parsed = parseApiDateTime(value)
  if (Number.isNaN(parsed.getTime())) return '時間格式錯誤'
  // No timeZone override: Intl intentionally follows the user's computer setting.
  return new Intl.DateTimeFormat('zh-TW', options).format(parsed)
}

export function toLocalDateTimeInput(value: string): string {
  const parsed = parseApiDateTime(value)
  if (Number.isNaN(parsed.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
}

export function localDateKey(value = new Date()): string {
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
}
