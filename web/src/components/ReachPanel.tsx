import { useState } from 'react'
import { formatPct, formatQ, formatValid, leadText } from '../format'
import type { ReachDetail, ReachProps, ReachSummary, Thresholds } from '../types'
import { AlertBadge } from './AlertBadge'
import { ForecastCharts } from './ForecastCharts'

const METERS: { key: keyof Thresholds; label: string; cssVar: string }[] = [
  { key: 'rp2', label: '2-year', cssVar: '--status-warning' },
  { key: 'rp5', label: '5-year', cssVar: '--status-serious' },
  { key: 'rp20', label: '20-year', cssVar: '--status-critical' },
  { key: 'rp50', label: '50-year', cssVar: '--status-critical' },
]

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="text-lg font-semibold text-ink">{value}</div>
      {sub && <div className="text-xs text-ink-2">{sub}</div>}
    </div>
  )
}

interface Props {
  reach: ReachProps
  summary: ReachSummary
  detail: ReachDetail | undefined
  issued: string
}

export function ReachPanel({ reach, summary, detail, issued }: Props) {
  const [showMembers, setShowMembers] = useState(false)

  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold text-ink">{reach.name}</h2>
          <p className="text-sm text-ink-2">
            {reach.basin} basin · {reach.upstream_area_km2.toLocaleString('en-GB')} km² upstream
          </p>
        </div>
        <AlertBadge level={summary.alert_level} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <StatTile label="Forecast peak (median)" value={`${formatQ(summary.peak_q50)} m³/s`} />
        <StatTile label="Timing of peak" value={leadText(issued, summary.peak_time)} sub={formatValid(summary.peak_time)} />
      </div>

      <div className="mt-3">
        <div className="mb-1 text-xs text-ink-3">Chance of exceeding the return-period flow in the next 15 days</div>
        <div className="space-y-1">
          {METERS.map((m) => {
            const p = summary.prob_exceed[m.key]
            return (
              <div key={m.key} className="grid grid-cols-[4.5rem_1fr_3rem] items-center gap-2 text-sm">
                <span className="text-ink-2">{m.label}</span>
                <div className="h-2 overflow-hidden rounded-full" style={{ background: 'var(--grid)' }}>
                  <div className="h-full rounded-full" style={{ width: `${p * 100}%`, background: `var(${m.cssVar})` }} />
                </div>
                <span className="tabular text-right text-ink">{formatPct(p)}</span>
              </div>
            )
          })}
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-3">
        {detail ? (
          <>
            <ForecastCharts detail={detail} showMembers={showMembers} />
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-sm text-ink-2">
              <label className="inline-flex cursor-pointer items-center gap-2">
                <input type="checkbox" checked={showMembers} onChange={(e) => setShowMembers(e.target.checked)} className="accent-[var(--series-1)]" />
                Show all {detail.forecast.members.length} members
              </label>
            </div>
            <DataTable detail={detail} />
          </>
        ) : (
          <div className="flex h-[440px] items-center justify-center text-sm text-ink-3">Loading forecast…</div>
        )}
      </div>
    </section>
  )
}

function DataTable({ detail }: { detail: ReachDetail }) {
  const fc = detail.forecast
  // One row per day (00 UTC steps) keeps the table readable.
  const rows = fc.times.map((t, i) => ({ t, i })).filter(({ t }) => t.endsWith('T00:00Z'))
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer text-ink-2">Data table</summary>
      <table className="tabular mt-2 w-full text-right">
        <thead className="text-xs text-ink-3">
          <tr>
            <th className="py-1 text-left font-normal">Time</th>
            <th className="font-normal">5%</th>
            <th className="font-normal">Median</th>
            <th className="font-normal">95%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ t, i }) => (
            <tr key={t} className="border-t border-line">
              <td className="py-1 text-left text-ink-2">{formatValid(t)}</td>
              <td>{formatQ(fc.p05[i])}</td>
              <td className="font-medium">{formatQ(fc.p50[i])}</td>
              <td>{formatQ(fc.p95[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-ink-3">Discharge in m³/s.</p>
    </details>
  )
}
