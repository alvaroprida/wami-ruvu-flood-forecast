import { useEffect, useMemo, useState } from 'react'
import { formatDay, formatTime } from '../format'
import { areasToCsv, bboxOf, type BBox, METRICS, type MetricId, round, severityOf, situationText } from '../impact'
import type { Forecast, IbfArea, IbfManifest, IbfSummary, Network } from '../types'
import { AlertBadge } from './AlertBadge'
import { type Basemap, BASEMAPS, ImpactMap, type ImpactLayers } from './ImpactMap'
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

type Corners = [[number, number], [number, number], [number, number], [number, number]]
type WardCollection = { type: 'FeatureCollection'; features: { type: 'Feature'; properties: Record<string, string | number>; geometry: { coordinates: unknown } }[] }

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3" style={accent ? { borderLeft: `4px solid ${accent}` } : undefined}>
      <div className="text-xs text-ink-3">{label}</div>
      <div className="tabular text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {sub && <div className="text-xs text-ink-3">{sub}</div>}
    </div>
  )
}

function Panel({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-surface p-4 text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

const selectCls = 'rounded-md border border-line bg-surface px-2 py-1 text-sm text-ink'

/** One impact view: the demo event or the live forecast, depending on `mode`. */
export function ImpactView({ mode }: { mode: 'demo' | 'live' }) {
  const [manifest, setManifest] = useState<IbfManifest | null>()
  const [forecast, setForecast] = useState<Forecast>()
  const [network, setNetwork] = useState<Network>()
  const [scenario, setScenario] = useState<string>()
  const [summary, setSummary] = useState<IbfSummary>()
  const [corners, setCorners] = useState<{ corners: Corners }>()
  const [rawWards, setRawWards] = useState<WardCollection>()
  const [layers, setLayers] = useState<ImpactLayers>({ depth: true, wards: true, buildings: false, population: false })
  const [metric, setMetric] = useState<MetricId>('people')
  const [basemap, setBasemap] = useState<Basemap>('light')
  const [depthOpacity, setDepthOpacity] = useState(0.8)
  const [selected, setSelected] = useState<number>()
  const [focus, setFocus] = useState<BBox>()
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setManifest(undefined)
    setSummary(undefined)
    getJSON<IbfManifest>(`${DATA}/ibf/${mode}/manifest.json`).then((m) => {
      setManifest(m ?? null)
      setScenario(m?.scenarios[0]?.id)
    })
    getJSON<Network>(`${DATA}/network.geojson`).then(setNetwork)
    if (mode === 'live') getJSON<Forecast>(`${DATA}/latest/forecast.json`).then(setForecast)
  }, [mode])

  const sc = manifest?.scenarios.find((s) => s.id === scenario)
  const base = sc ? `${DATA}/ibf/${mode}/${sc.dir}/` : undefined
  useEffect(() => {
    setSummary(undefined)
    setRawWards(undefined)
    setSelected(undefined)
    if (!base) return
    getJSON<IbfSummary>(`${base}summary.json`).then(setSummary)
    getJSON<{ corners: Corners }>(`${base}depth.json`).then(setCorners)
    getJSON<WardCollection>(`${base}admin.geojson`).then(setRawWards)
  }, [base])

  // Wards with the derived "share" property the map colours by.
  const wards = useMemo(
    () =>
      rawWards && {
        ...rawWards,
        features: rawWards.features.map((f) => {
          const p = f.properties
          return { ...f, properties: { ...p, share: Number(p.pop_total) > 0 ? (100 * Number(p.people)) / Number(p.pop_total) : 0 } }
        }),
      },
    [rawWards],
  )
  const wardBox = useMemo(() => new Map((rawWards?.features ?? []).map((f) => [Number(f.properties.id), bboxOf(f.geometry.coordinates)])), [rawWards])

  const areas = useMemo<IbfArea[]>(() => {
    const a = [...(summary?.areas ?? [])]
    return a.sort((x, y) => METRICS[metric].value(y) - METRICS[metric].value(x))
  }, [summary, metric])
  const selectedArea = summary?.areas?.find((a) => a.id === selected)

  const select = (id: number | undefined) => {
    setSelected(id)
    const b = id !== undefined ? wardBox.get(id) : undefined
    if (b) setFocus([...b] as BBox)
  }

  if (manifest === undefined) return <div className="p-8 text-ink-3">Loading…</div>

  const names = Object.fromEntries((network?.features ?? []).map((f) => [f.properties.id, f.properties.name]))
  const triggered = forecast
    ? Object.entries(forecast.reaches).filter(([, r]) => r.alert_level > 0).sort(([, a], [, b]) => b.alert_level - a.alert_level)
    : []
  const sev = summary ? severityOf(summary.people_affected) : undefined
  const ok = manifest && manifest.status === 'ok' && sc
  const title = mode === 'demo' ? (manifest?.title ?? 'Demo event') : 'Live impact forecast'

  const download = () => {
    const blob = new Blob([areasToCsv(summary?.areas ?? [])], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `impact_${mode}_${sc?.id ?? 'scenario'}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  const copy = () => {
    if (!summary || !sc) return
    navigator.clipboard?.writeText(situationText(title, sc.label, summary)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
          <p className="text-sm text-ink-2">
            {mode === 'demo'
              ? (manifest?.description ?? 'Past event run through the whole impact chain.')
              : 'Latest hazard forecast run through SFINCS, exposure and vulnerability'}
          </p>
        </div>
        <div className="text-sm sm:text-right">
          {mode === 'live' && forecast && (
            <>
              <div className="text-ink-3">Hazard forecast issued</div>
              <div className="font-medium text-ink">{formatTime(manifest?.issued ?? forecast.issued)}</div>
            </>
          )}
          {mode === 'demo' && manifest?.period && (
            <>
              <div className="text-ink-3">Simulated period</div>
              <div className="font-medium text-ink">
                {formatDay(manifest.period[0])} – {formatDay(manifest.period[1])}
              </div>
            </>
          )}
        </div>
      </header>

      <div role="note" className="rounded-lg bg-banner px-4 py-2 text-sm text-ink">
        <strong>Experimental research prototype, not an official warning service.</strong>{' '}
        {mode === 'demo'
          ? 'Reconstruction with an uncalibrated hydrological model: flows, and so flooded areas and impacts, are overestimated. Use for demonstration and method testing.'
          : 'Impacts are scenarios of the model chain, not observed or validated flooding.'}
      </div>

      {mode === 'live' && (
        <Panel title="Hazard alerts that trigger a hydraulic run">
          {!forecast ? (
            <p className="text-ink-3">Loading…</p>
          ) : triggered.length === 0 ? (
            <p className="text-ink-2">No reach is at or above the 2-year flow in the latest forecast, so no hydraulic simulation is run.</p>
          ) : (
            <ul className="divide-y divide-line">
              {triggered.map(([id, r]) => (
                <li key={id} className="flex flex-wrap items-center gap-3 py-1.5">
                  <AlertBadge level={r.alert_level} />
                  <span className="font-medium text-ink">{names[id] ?? id}</span>
                  <span className="tabular ml-auto text-ink-2">peak {formatTime(r.peak_time)}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      {!ok && (
        <section className="rounded-xl border border-line bg-surface p-5 text-sm text-ink-2">
          {!manifest
            ? 'No impact products have been published for this view yet.'
            : manifest.status === 'not_triggered'
              ? 'No domain was triggered by the latest forecast, so there is no impact to show. This page updates when an alert is issued.'
              : (manifest.note ?? 'The latest impact run is not available.')}
        </section>
      )}

      {ok && (
        <>
          {/* Situation strip: scenario, severity, actions */}
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm">
            {sev && (
              <div className="flex items-center gap-2" title="Indicative scale from people affected: Minor ≥ 1, Moderate ≥ 1,000, Severe ≥ 10,000, Extreme ≥ 50,000. Illustrative, not an official scale.">
                <span className="inline-block h-3 w-3 rounded-full" style={{ background: sev.color }} aria-hidden="true" />
                <span className="text-ink-3">Impact scale</span>
                <span className="font-semibold text-ink">{sev.label}</span>
              </div>
            )}
            {manifest.scenarios.length > 1 && (
              <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Scenario">
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
            <div className="ml-auto flex flex-wrap gap-2">
              <button onClick={copy} disabled={!summary} className="rounded-md border border-line px-3 py-1 text-ink-2 hover:text-ink disabled:opacity-50">
                {copied ? 'Copied' : 'Copy situation summary'}
              </button>
              <button onClick={download} disabled={!summary} className="rounded-md border border-line px-3 py-1 text-ink-2 hover:text-ink disabled:opacity-50">
                Download CSV (by ward)
              </button>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="People affected" value={summary ? `~${round(summary.people_affected)}` : '…'} sub={summary && `in cells flooded ≥ ${summary.flood_depth_threshold_m} m`} accent={sev?.color} />
            <Kpi label="Buildings affected" value={summary ? `~${round(summary.buildings_affected)}` : '…'} sub={summary && `of ${summary.buildings_in_domain.toLocaleString('en-GB')} mapped in the domain`} accent={sev?.color} />
            <Kpi label="Flooded area" value={summary ? `${summary.flooded_area_km2.toFixed(0)} km²` : '…'} sub={summary && `max depth ${summary.max_depth_m.toFixed(1)} m`} />
            <Kpi label="Building damage" value={summary ? `${Math.round(summary.mean_damage_factor * 100)}%` : '…'} sub={summary && `mean of value · ≈ ${round(summary.building_loss_equivalents)} buildings lost`} />
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
            {/* Map and layer controls */}
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm text-ink-2">
                <label className="flex items-center gap-1.5">
                  Background
                  <select className={selectCls} value={basemap} onChange={(e) => setBasemap(e.target.value as Basemap)}>
                    {(Object.keys(BASEMAPS) as Basemap[]).map((k) => (
                      <option key={k} value={k}>{BASEMAPS[k].label}</option>
                    ))}
                  </select>
                </label>
                {(
                  [
                    ['depth', 'Max flood depth'],
                    ['wards', 'Impact by ward'],
                    ['buildings', 'Affected buildings'],
                    ['population', 'Population in flood'],
                  ] as const
                ).map(([k, label]) => (
                  <label key={k} className="flex items-center gap-1.5">
                    <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} />
                    {label}
                  </label>
                ))}
                <label className="flex items-center gap-1.5">
                  Ward colour
                  <select className={selectCls} value={metric} onChange={(e) => setMetric(e.target.value as MetricId)}>
                    {(Object.keys(METRICS) as MetricId[]).map((k) => (
                      <option key={k} value={k}>{METRICS[k].label}</option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-1.5">
                  Depth opacity
                  <input type="range" min={0.2} max={1} step={0.05} value={depthOpacity} onChange={(e) => setDepthOpacity(Number(e.target.value))} />
                </label>
              </div>
              <div className="h-[62vh] min-h-[480px] xl:sticky xl:top-3 xl:h-[calc(100vh-7rem)] xl:max-h-[820px]">
                {base && corners && (
                  <ImpactMap
                    bbox={manifest.domain.bbox}
                    base={base}
                    corners={corners.corners}
                    wards={wards}
                    layers={layers}
                    metric={metric}
                    basemap={basemap}
                    depthOpacity={depthOpacity}
                    selectedWard={selected}
                    onSelectWard={select}
                    focus={focus}
                  />
                )}
              </div>
            </div>

            {/* Operational side panel */}
            <div className="space-y-4">
              {selectedArea && (
                <Panel
                  title={`${selectedArea.ward}, ${selectedArea.district}`}
                  right={<button className="text-ink-3 hover:text-ink" onClick={() => select(undefined)} aria-label="Clear selection">✕</button>}
                >
                  <dl className="tabular grid grid-cols-2 gap-x-4 gap-y-1 text-ink-2">
                    <dt>People affected</dt>
                    <dd className="text-right text-ink">{round(selectedArea.people)} of {round(selectedArea.pop_total)}</dd>
                    <dt>Buildings affected</dt>
                    <dd className="text-right text-ink">{round(selectedArea.buildings)} of {round(selectedArea.buildings_total)}</dd>
                    <dt>Flooded area</dt>
                    <dd className="text-right text-ink">{selectedArea.area_km2.toFixed(1)} km²</dd>
                    <dt>Max depth</dt>
                    <dd className="text-right text-ink">{selectedArea.max_depth.toFixed(1)} m</dd>
                    <dt>Mean building damage</dt>
                    <dd className="text-right text-ink">{Math.round(selectedArea.damage * 100)}%</dd>
                  </dl>
                </Panel>
              )}

              <Panel
                title="Priority areas"
                right={
                  <select className={selectCls} value={metric} onChange={(e) => setMetric(e.target.value as MetricId)} aria-label="Rank by">
                    {(['people', 'buildings', 'share'] as MetricId[]).map((k) => (
                      <option key={k} value={k}>Rank by {METRICS[k].label.toLowerCase()}</option>
                    ))}
                  </select>
                }
              >
                {!summary ? (
                  <p className="text-ink-3">Loading…</p>
                ) : areas.length === 0 ? (
                  <p className="text-ink-2">No ward is affected in this scenario.</p>
                ) : (
                  <div className="max-h-[420px] overflow-auto">
                    <table className="tabular w-full">
                      <thead className="sticky top-0 bg-surface text-left text-ink-3">
                        <tr>
                          <th className="py-1 font-normal">Ward</th>
                          <th className="py-1 text-right font-normal">People</th>
                          <th className="py-1 text-right font-normal">Buildings</th>
                          <th className="py-1 text-right font-normal">% pop.</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {areas.map((a) => (
                          <tr
                            key={a.id}
                            onClick={() => select(a.id)}
                            className={`cursor-pointer hover:bg-page ${a.id === selected ? 'bg-page' : ''}`}
                          >
                            <td className="py-1.5 pr-2">
                              <div className="font-medium text-ink">{a.ward}</div>
                              <div className="text-xs text-ink-3">{a.district}</div>
                            </td>
                            <td className="py-1.5 text-right text-ink">{round(a.people)}</td>
                            <td className="py-1.5 text-right text-ink-2">{round(a.buildings)}</td>
                            <td className="py-1.5 text-right text-ink-2">{METRICS.share.format(METRICS.share.value(a))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>

              {summary?.districts && summary.districts.length > 0 && (
                <Panel title="By district">
                  <table className="tabular w-full">
                    <thead className="text-left text-ink-3">
                      <tr>
                        <th className="py-1 font-normal">District</th>
                        <th className="py-1 text-right font-normal">People</th>
                        <th className="py-1 text-right font-normal">Buildings</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {summary.districts.map((d) => (
                        <tr key={d.district}>
                          <td className="py-1.5 text-ink">{d.district}</td>
                          <td className="py-1.5 text-right text-ink">{round(d.people)}</td>
                          <td className="py-1.5 text-right text-ink-2">{round(d.buildings)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Panel>
              )}

              {sc.hydrograph && (
                <Panel title="Inflow to the hydraulic model">
                  <InflowChart times={sc.hydrograph.times} series={sc.hydrograph.series} names={names} />
                </Panel>
              )}

              {summary && (
                <Panel title="Impact by flood depth">
                  <table className="tabular w-full">
                    <thead className="text-left text-ink-3">
                      <tr>
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
                </Panel>
              )}

              <Panel title="How to read this">
                <ul className="list-disc space-y-1 pl-5 text-ink-2">
                  <li>Flood depth is the <strong>maximum</strong> reached during the simulation, not a snapshot in time.</li>
                  <li>People come from WorldPop 2025 (100 m) in flooded cells; buildings from Overture Maps, which is incomplete in rural areas, so building counts are lower bounds.</li>
                  <li>Damage uses the Englhardt et al. (2019) curve for non-engineered buildings, applied to every building.</li>
                  <li>Wards are geoBoundaries ADM3 (2015); names and limits may differ from current administrative units.</li>
                  <li>Numbers are rounded; treat them as orders of magnitude.</li>
                </ul>
              </Panel>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
