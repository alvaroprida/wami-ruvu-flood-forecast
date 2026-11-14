import { useEffect, useState } from 'react'
import { formatDay, formatTime } from '../format'
import type { Forecast, IbfManifest, IbfSummary, Network } from '../types'
import { AlertBadge } from './AlertBadge'
import { ImpactMap, type ImpactLayers } from './ImpactMap'
import { InflowChart } from './InflowChart'

const DATA = `${import.meta.env.BASE_URL}data`

async function getJSON<T>(url: string): Promise<T | undefined> {
  const res = await fetch(url)
  if (!res.ok) return undefined
  try {
    return (await res.json()) as T
  } catch {
    return undefined // a missing file can come back as the SPA's HTML page
  }
}

const round = (n: number, to = 10) => (Math.round(n / to) * to).toLocaleString('en-GB')

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="tabular text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {sub && <div className="text-xs text-ink-3">{sub}</div>}
    </div>
  )
}

/** One impact view: the demo event or the live forecast, depending on `mode`. */
export function ImpactView({ mode }: { mode: 'demo' | 'live' }) {
  const [manifest, setManifest] = useState<IbfManifest | null>()
  const [forecast, setForecast] = useState<Forecast>()
  const [network, setNetwork] = useState<Network>()
  const [scenario, setScenario] = useState<string>()
  const [summary, setSummary] = useState<IbfSummary>()
  const [corners, setCorners] = useState<{ corners: [[number, number], [number, number], [number, number], [number, number]] }>()
  const [layers, setLayers] = useState<ImpactLayers>({ depth: true, population: false, buildings: true })

  useEffect(() => {
    setManifest(undefined)
    setSummary(undefined)
    getJSON<IbfManifest>(`${DATA}/ibf/${mode}/manifest.json`).then((m) => {
      setManifest(m ?? null)
      setScenario(m?.scenarios[0]?.id)
    })
    if (mode === 'live') {
      getJSON<Forecast>(`${DATA}/latest/forecast.json`).then(setForecast)
      getJSON<Network>(`${DATA}/network.geojson`).then(setNetwork)
    }
  }, [mode])

  const sc = manifest?.scenarios.find((s) => s.id === scenario)
  const base = sc ? `${DATA}/ibf/${mode}/${sc.dir}/` : undefined
  useEffect(() => {
    setSummary(undefined)
    if (!base) return
    getJSON<IbfSummary>(`${base}summary.json`).then(setSummary)
    getJSON<typeof corners>(`${base}depth.json`).then(setCorners)
  }, [base])

  if (manifest === undefined) return <div className="p-8 text-ink-3">Loading…</div>

  const names = Object.fromEntries((network?.features ?? []).map((f) => [f.properties.id, f.properties.name]))
  const triggered = forecast
    ? Object.entries(forecast.reaches).filter(([, r]) => r.alert_level > 0).sort(([, a], [, b]) => b.alert_level - a.alert_level)
    : []

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {mode === 'demo' ? (manifest?.title ?? 'Demo event') : 'Live impact forecast'}
          </h1>
          <p className="text-sm text-ink-2">
            {mode === 'demo'
              ? (manifest?.description ?? 'Past event run through the whole impact chain.')
              : 'Latest hazard forecast run through SFINCS, exposure and vulnerability'}
          </p>
        </div>
        {mode === 'live' && forecast && (
          <div className="text-sm sm:text-right">
            <div className="text-ink-3">Hazard forecast issued</div>
            <div className="font-medium text-ink">{formatTime(manifest?.issued ?? forecast.issued)}</div>
          </div>
        )}
        {mode === 'demo' && manifest?.period && (
          <div className="text-sm sm:text-right">
            <div className="text-ink-3">Simulated period</div>
            <div className="font-medium text-ink">{formatDay(manifest.period[0])} – {formatDay(manifest.period[1])}</div>
          </div>
        )}
      </header>

      <div role="note" className="rounded-lg bg-banner px-4 py-2 text-sm text-ink">
        <strong>Experimental research prototype, not an official warning service.</strong>{' '}
        {mode === 'demo'
          ? 'Reconstruction with an uncalibrated hydrological model and a 100 m hydraulic model: treat numbers as order-of-magnitude.'
          : 'Impacts are scenarios of the model chain, not observed or validated flooding.'}
      </div>

      {mode === 'live' && (
        <section className="rounded-xl border border-line bg-surface p-5 text-sm">
          <h2 className="mb-1 text-base font-semibold text-ink">Alerts that trigger a hydraulic run</h2>
          <p className="mb-3 text-ink-3">Reaches at alert level 1 or above in the latest hazard forecast.</p>
          {!forecast ? (
            <p className="text-ink-3">Loading…</p>
          ) : triggered.length === 0 ? (
            <p className="text-ink-2">No alert in the current forecast: no hydraulic simulation is run.</p>
          ) : (
            <ul className="divide-y divide-line">
              {triggered.map(([id, r]) => (
                <li key={id} className="flex flex-wrap items-center gap-3 py-2">
                  <AlertBadge level={r.alert_level} />
                  <span className="font-medium text-ink">{names[id] ?? id}</span>
                  <span className="tabular ml-auto text-ink-2">peak {formatTime(r.peak_time)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {(!manifest || manifest.status !== 'ok' || !sc) && (
        <section className="rounded-xl border border-line bg-surface p-5 text-sm text-ink-2">
          {!manifest
            ? 'No impact products have been published for this view yet.'
            : manifest.status === 'not_triggered'
              ? 'No domain was triggered by the latest forecast, so there is no impact to show.'
              : (manifest.note ?? 'The latest impact run is not available.')}
        </section>
      )}

      {manifest && manifest.status === 'ok' && sc && (
        <>
          {manifest.scenarios.length > 1 && (
            <div className="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Scenario">
              <span className="text-ink-3">Scenario</span>
              {manifest.scenarios.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setScenario(s.id)}
                  aria-pressed={s.id === scenario}
                  className={`rounded-full border px-3 py-1 ${s.id === scenario ? 'border-accent bg-accent text-white' : 'border-line text-ink-2 hover:text-ink'}`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="People affected" value={summary ? `~${round(summary.people_affected)}` : '…'} sub={summary && `in cells flooded ≥ ${summary.flood_depth_threshold_m} m`} />
            <Kpi label="Buildings affected" value={summary ? `~${round(summary.buildings_affected, 10)}` : '…'} sub={summary && `of ${summary.buildings_in_domain.toLocaleString('en-GB')} in the domain`} />
            <Kpi label="Flooded area" value={summary ? `${summary.flooded_area_km2.toFixed(0)} km²` : '…'} sub={summary && `max depth ${summary.max_depth_m.toFixed(1)} m`} />
            <Kpi
              label="Building damage"
              value={summary ? `${Math.round(summary.mean_damage_factor * 100)}%` : '…'}
              sub={summary && `mean of value; ≈ ${round(summary.building_loss_equivalents, 10)} buildings lost`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="flex flex-col gap-2 lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:max-h-[780px]">
              <div className="flex flex-wrap gap-3 text-sm text-ink-2">
                {(
                  [
                    ['depth', 'Flood depth'],
                    ['population', 'Population in flooded area'],
                    ['buildings', 'Affected buildings'],
                  ] as const
                ).map(([k, label]) => (
                  <label key={k} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} />
                    {label}
                  </label>
                ))}
              </div>
              <div className="min-h-0 flex-1">
                {base && corners && <ImpactMap bbox={manifest.domain.bbox} base={base} corners={corners.corners} layers={layers} />}
              </div>
            </div>

            <div className="space-y-4">
              {sc.hydrograph && (
                <section className="rounded-xl border border-line bg-surface p-5 text-sm">
                  <h2 className="mb-1 text-base font-semibold text-ink">Inflow to the hydraulic model</h2>
                  <InflowChart times={sc.hydrograph.times} series={sc.hydrograph.series} names={names} />
                </section>
              )}
              {summary && (
                <section className="rounded-xl border border-line bg-surface p-5 text-sm">
                  <h2 className="mb-2 text-base font-semibold text-ink">Impact by flood depth</h2>
                  <table className="tabular w-full">
                    <thead>
                      <tr className="text-left text-ink-3">
                        <th className="py-1 font-normal">Depth</th>
                        <th className="py-1 text-right font-normal">People</th>
                        <th className="py-1 text-right font-normal">Buildings</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {Object.entries(summary.by_depth_class).map(([k, v]) => (
                        <tr key={k}>
                          <td className="py-1.5 text-ink">{k}</td>
                          <td className="py-1.5 text-right text-ink-2">{round(v.people)}</td>
                          <td className="py-1.5 text-right text-ink-2">{round(v.buildings)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-3 text-ink-3">
                    Depth-damage: {summary.vulnerability.source}, class {summary.vulnerability.class} (non-engineered / informal buildings), applied to every
                    building. {summary.population_note} Numbers are rounded.
                  </p>
                </section>
              )}
              <section className="rounded-xl border border-line bg-surface p-5 text-sm text-ink-2">
                <h2 className="mb-2 text-base font-semibold text-ink">How this was computed</h2>
                <ol className="list-decimal space-y-1 pl-5">
                  <li>Wflow discharge at the reaches entering the domain ({mode === 'demo' ? 'CHIRPS rainfall' : 'ECMWF ensemble, median and 95th percentile'}).</li>
                  <li>SFINCS hydraulic model, 100 m grid with 30 m FABDEM subgrid, maximum depth downscaled to 30 m.</li>
                  <li>Exposure: WorldPop 2025 population and Overture Maps buildings.</li>
                  <li>Englhardt et al. (2019) stage-damage curve for non-engineered buildings.</li>
                </ol>
              </section>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
