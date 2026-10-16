import { formatPct, formatQ, formatTime } from '../format'
import type { Forecast, Network } from '../types'
import { AlertBadge } from './AlertBadge'

interface Props {
  network: Network
  forecast: Forecast
  selectedId: string
  onSelect: (id: string) => void
}

export function AlertTable({ network, forecast, selectedId, onSelect }: Props) {
  const rows = network.features
    .map((f) => ({ ...f.properties, ...forecast.reaches[f.properties.id] }))
    .sort((a, b) => b.alert_level - a.alert_level || b.prob_exceed.rp5 - a.prob_exceed.rp5)

  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="text-base font-semibold text-ink">All forecast reaches</h2>
      <p className="mb-2 text-xs text-ink-3">Sorted by alert level. Select a row to open its forecast.</p>
      <div className="overflow-x-auto">
        <table className="tabular w-full min-w-[720px] text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr>
              <th className="py-2 font-normal">Reach</th>
              <th className="font-normal">Basin</th>
              <th className="font-normal">Level</th>
              <th className="text-right font-normal">P(&gt;2-yr)</th>
              <th className="text-right font-normal">P(&gt;5-yr)</th>
              <th className="text-right font-normal">P(&gt;20-yr)</th>
              <th className="text-right font-normal">Peak, m³/s</th>
              <th className="pl-4 font-normal">Peak time</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                onClick={() => onSelect(r.id)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(r.id)}
                tabIndex={0}
                aria-selected={r.id === selectedId}
                className={`cursor-pointer border-t border-line outline-none hover:bg-[var(--grid)]/40 focus-visible:bg-[var(--grid)]/60 ${
                  r.id === selectedId ? 'bg-[var(--grid)]/60' : ''
                }`}
              >
                <td className="py-2 font-medium text-ink">{r.name}</td>
                <td className="text-ink-2">{r.basin}</td>
                <td><AlertBadge level={r.alert_level} compact /></td>
                <td className="text-right">{formatPct(r.prob_exceed.rp2)}</td>
                <td className="text-right">{formatPct(r.prob_exceed.rp5)}</td>
                <td className="text-right">{formatPct(r.prob_exceed.rp20)}</td>
                <td className="text-right">{formatQ(r.peak_q50)}</td>
                <td className="pl-4 text-ink-2">{formatTime(r.peak_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
