import { useEffect, useState } from 'react'
import { AlertBadge } from '../components/AlertBadge'
import { formatTime } from '../format'
import type { Forecast, Network } from '../types'

const DATA = `${import.meta.env.BASE_URL}data`

type Status = 'planned' | 'in progress' | 'done'

const CHAIN: { title: string; text: string; status: Status }[] = [
  { title: 'Hazard trigger', text: 'The FEWS tab: Wflow + ECMWF ENS flags reaches at 2-, 5- or 20-year flow.', status: 'done' },
  { title: 'Hydraulic model', text: 'SFINCS is run only on the basins where an alert is triggered, forced with the forecast hydrographs (and rainfall).', status: 'planned' },
  { title: 'Flood maps', text: 'Maximum flood depth per forecast, per ensemble quantile (e.g. median and 90th percentile).', status: 'planned' },
  { title: 'Exposure', text: 'Population (WorldPop) and building footprints (Overture Maps) overlaid on the flood maps.', status: 'planned' },
  { title: 'Vulnerability', text: 'Depth-damage / depth-impact functions applied to buildings and population.', status: 'planned' },
  { title: 'Impact forecast', text: 'People affected and buildings affected per basin and per administrative unit, with ensemble uncertainty.', status: 'planned' },
]

const SOURCES = [
  ['Hydraulic model', 'SFINCS (Deltares)'],
  ['Population', 'WorldPop gridded population'],
  ['Buildings', 'Overture Maps building footprints'],
  ['Vulnerability', 'Depth-damage / depth-impact functions (to be selected)'],
]

const STATUS_STYLE: Record<Status, string> = {
  done: 'bg-accent text-white',
  'in progress': 'bg-banner text-ink',
  planned: 'border border-line text-ink-3',
}

export default function IbfView() {
  const [forecast, setForecast] = useState<Forecast>()
  const [network, setNetwork] = useState<Network>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    Promise.all([
      fetch(`${DATA}/latest/forecast.json`).then((r) => r.json() as Promise<Forecast>),
      fetch(`${DATA}/network.geojson`).then((r) => r.json() as Promise<Network>),
    ])
      .then(([f, n]) => {
        setForecast(f)
        setNetwork(n)
      })
      .catch((e) => setError(String(e)))
  }, [])

  if (error) return <div className="p-8 text-ink">Could not load forecast data: {error}</div>
  if (!forecast || !network) return <div className="p-8 text-ink-3">Loading…</div>

  const names = new Map(network.features.map((f) => [f.properties.id, f.properties]))
  const triggered = Object.entries(forecast.reaches)
    .filter(([, r]) => r.alert_level > 0)
    .sort(([, a], [, b]) => b.alert_level - a.alert_level)

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Impact-based Forecast</h1>
          <p className="text-sm text-ink-2">
            From forecast discharge to people and buildings affected · Wflow + SFINCS + exposure and vulnerability
          </p>
        </div>
        <div className="text-sm sm:text-right">
          <div className="text-ink-3">Hazard forecast issued</div>
          <div className="font-medium text-ink">{formatTime(forecast.issued)}</div>
        </div>
      </header>

      <div role="note" className="rounded-lg bg-banner px-4 py-2 text-sm text-ink">
        <strong>Under development.</strong> Impact estimates are not available yet; this page shows the planned chain and
        which basins the current hazard forecast would send to the hydraulic model.
      </div>

      <section className="rounded-xl border border-line bg-surface p-5 text-sm">
        <h2 className="mb-3 text-base font-semibold text-ink">Impact chain</h2>
        <ol className="grid gap-3 md:grid-cols-3">
          {CHAIN.map((s, i) => (
            <li key={s.title} className="rounded-lg border border-line p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="font-medium text-ink">{i + 1}. {s.title}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_STYLE[s.status]}`}>{s.status}</span>
              </div>
              <p className="text-ink-2">{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-xl border border-line bg-surface p-5 text-sm">
        <h2 className="mb-1 text-base font-semibold text-ink">Reaches that would trigger a SFINCS run</h2>
        <p className="mb-3 text-ink-3">Any reach at alert level 1 or above in the latest hazard forecast.</p>
        {triggered.length === 0 ? (
          <p className="text-ink-2">No alert in the current forecast: no hydraulic simulation would be run.</p>
        ) : (
          <ul className="divide-y divide-line">
            {triggered.map(([id, r]) => (
              <li key={id} className="flex flex-wrap items-center gap-3 py-2">
                <AlertBadge level={r.alert_level} />
                <span className="font-medium text-ink">{names.get(id)?.name ?? id}</span>
                <span className="text-ink-3">{names.get(id)?.basin} basin</span>
                <span className="tabular ml-auto text-ink-2">peak {formatTime(r.peak_time)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-line bg-surface p-5 text-sm">
        <h2 className="mb-2 text-base font-semibold text-ink">Planned data &amp; models</h2>
        <ul className="space-y-1 text-ink-2">
          {SOURCES.map(([k, v]) => (
            <li key={k}><span className="font-medium text-ink">{k}:</span> {v}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}
