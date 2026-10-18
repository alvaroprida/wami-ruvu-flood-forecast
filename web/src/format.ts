const dateFmt = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Africa/Dar_es_Salaam',
})

const dayFmt = new Intl.DateTimeFormat('en-GB', {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  timeZone: 'Africa/Dar_es_Salaam',
})

/** ISO timestamps in the data are UTC; display in East Africa Time. */
export const formatTime = (iso: string) => `${dateFmt.format(new Date(iso))} EAT`
export const formatDay = (iso: string) => dayFmt.format(new Date(iso))

// Daily forecasts carry one value per UTC day: show the date, not a clock time.
let dailyTimestep = false
export const setDailyTimestep = (daily: boolean) => {
  dailyTimestep = daily
}
/** Time a forecast value is valid for. */
export const formatValid = (iso: string) => (dailyTimestep ? formatDay(iso) : formatTime(iso))

export const formatQ = (q: number) =>
  q >= 100 ? Math.round(q).toLocaleString('en-GB') : q.toLocaleString('en-GB', { maximumFractionDigits: 1 })

export const formatPct = (p: number) => `${Math.round(p * 100)}%`

export function leadText(issued: string, iso: string): string {
  const days = (new Date(iso).getTime() - new Date(issued).getTime()) / 86_400_000
  if (dailyTimestep) return days < 1 ? 'Day 1 (today)' : `Day ${Math.round(days) + 1}`
  if (days < 1) return `in ${Math.round(days * 24)} h`
  return `in ${days.toFixed(1)} days`
}
