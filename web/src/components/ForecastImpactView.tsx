import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { addProtocol, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { Protocol } from 'pmtiles'
import { useEffect, useMemo, useState } from 'react'
import Map, { Layer, NavigationControl, Popup, ScaleControl, Source, type MapLayerMouseEvent } from 'react-map-gl/maplibre'
import { formatDay } from '../format'
import { RAMP } from '../impact'
import { usePalette } from '../theme'
import { BASEMAPS, type Basemap, DEPTH_COLORS, POP_COLORS } from './ImpactMap'

setWorkerUrl(workerUrl)
const protocol = new Protocol()
addProtocol('pmtiles', protocol.tile)

const DATA = `${import.meta.env.BASE_URL}data/ibf/forecast`
const ABS = (p: string) => new URL(`${DATA}/${p}`, location.href).href
const SCEN_COLORS: Record<string, string> = { p50: '#2a78d6', p95: '#eb6834' }   // categorical slots 1-2

interface Total { day: number; people: number; buildings: number; loss_equiv: number; flooded_km2: number; max_depth_m: number }
interface Manifest {
  issued: string; title: string; description: string; days: string[]; rain_mm: number[]
  domain: { bbox: [number, number, number, number] }
  scenarios: { id: string; label: string; dir: string; hydrograph: Record<string, number[]> }[]
  corners: [number, number][]; totals: Record<string, Total[]>
  flood_depth_threshold_m: number; depth_legend_m: number[]; pop_legend_per_ha: number[]
  vulnerability: { source: string; class: string }; buildings_in_domain: number; population_in_domain: number
}
type Show = { depth: boolean; popHit: boolean; popAll: boolean; buildings: boolean; wards: boolean }
interface WardGeo {
  type: 'FeatureCollection'
  features: { type: 'Feature'; properties: Record<string, unknown>; geometry: unknown }[]
}
interface Ward { id: number; ward: string; district: string; pop_total: number; buildings_total: number }
interface WardRow { scenario: string; day: number; id: number; people: number; buildings: number; loss_equiv: number }
type Metric = 'people' | 'buildings' | 'loss_equiv'
const METRIC: Record<Metric, { label: string; steps: number[] }> = {
  people: { label: 'People affected', steps: [1, 100, 500, 1000, 5000, 10000] },
  buildings: { label: 'Buildings affected', steps: [1, 25, 100, 300, 1000, 3000] },
  loss_equiv: { label: 'Damage (building-loss equivalents)', steps: [0.1, 5, 25, 100, 300, 1000] },
}

const fmt = (v: number) => Math.round(v).toLocaleString('en-GB')
const pad = (d: number) => String(d).padStart(2, '0')

export function ForecastImpactView() {
  const { palette, dark } = usePalette()
  const [m, setM] = useState<Manifest>()
  const [wardData, setWardData] = useState<{ wards: Ward[]; rows: WardRow[] }>()
  const [admin, setAdmin] = useState<WardGeo>()
  const [scen, setScen] = useState('p50')
  const [day, setDay] = useState(1)
  const [metric, setMetric] = useState<Metric>('people')
  const [playing, setPlaying] = useState(false)
  const [basemap, setBasemap] = useState<Basemap>(dark ? 'dark' : 'light')
  const [show, setShow] = useState<Show>({ depth: true, popHit: true, popAll: true, buildings: true, wards: true })
  const [hover, setHover] = useState<{ lng: number; lat: number; kind: 'b' | 'w'; p: Record<string, unknown> } | null>(null)
  const [selWard, setSelWard] = useState<number | null>(null)

  useEffect(() => {
    fetch(`${DATA}/manifest.json`).then((r) => r.json()).then((x: Manifest) => {
      setM(x)
      // Open on the day with the largest median impact.
      const t = x.totals.p50 ?? Object.values(x.totals)[0]
      setDay(t.reduce((a, b) => (b.people > a.people ? b : a)).day)
    })
    fetch(`${DATA}/wards.json`).then((r) => r.json()).then(setWardData)
    fetch(`${DATA}/admin.geojson`).then((r) => r.json()).then(setAdmin)
  }, [])

  useEffect(() => {
    if (!playing || !m) return
    const t = setInterval(() => setDay((d) => (d >= m.days.length ? 1 : d + 1)), 1200)
    return () => clearInterval(t)
  }, [playing, m])

  // Ward values for the selected scenario/day, joined onto the polygons for the choropleth.
  const dayRows = useMemo(() => {
    const out: Record<number, WardRow> = {}
    wardData?.rows.filter((r) => r.scenario === scen && r.day === day).forEach((r) => (out[r.id] = r))
    return out
  }, [wardData, scen, day])
  const wardsGeo = useMemo(() => admin && {
    ...admin,
    features: admin.features.map((f) => {
      const r = dayRows[f.properties.id as number]
      return { ...f, properties: { ...f.properties, people: r?.people ?? 0, buildings: r?.buildings ?? 0, loss_equiv: r?.loss_equiv ?? 0 } }
    }),
  }, [admin, dayRows])

  if (!m || !wardData || !wardsGeo) return <div className="p-8 text-ink-3">Loading forecast impact…</div>

  const total = m.totals[scen][day - 1]
  const key = `${scen}_${day}`
  const dir = m.scenarios.find((s) => s.id === scen)!.dir
  const dateOf = (d: number) => formatDay(m.days[d - 1])
  const steps = METRIC[metric].steps
  const stepExpr = (prop: string) => ['step', ['get', prop], 'rgba(0,0,0,0)', ...steps.flatMap((s, i) => [s, RAMP[i]])] as unknown as string
  const depthExpr = ['step', ['coalesce', ['get', key], 0], DEPTH_COLORS[0], 50, DEPTH_COLORS[1], 100, DEPTH_COLORS[2], 200, DEPTH_COLORS[3]] as unknown as string
  const hitFilter = ['>=', ['coalesce', ['get', key], 0], Math.round(m.flood_depth_threshold_m * 100)] as unknown as boolean
  const [w, s, e, n] = m.domain.bbox

  const onMove = (ev: MapLayerMouseEvent) => {
    const f = ev.features?.[0]
    setHover(f ? { lng: ev.lngLat.lng, lat: ev.lngLat.lat, kind: f.layer.id === 'bld-hit' ? 'b' : 'w', p: f.properties } : null)
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{m.title}</h1>
        <p className="max-w-4xl text-sm text-ink-2">{m.description}</p>
      </header>
      <div role="note" className="rounded-lg bg-banner px-4 py-2 text-sm text-ink">
        <strong>Demonstration with an uncalibrated model.</strong> Flows, flood extents and impacts are overestimated; read the
        development over lead times and the relative pattern between wards, not the absolute numbers.
      </div>

      {/* Controls: scenario, lead day, metric */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-2" role="radiogroup" aria-label="Scenario">
          {m.scenarios.map((sc) => (
            <button key={sc.id} role="radio" aria-checked={scen === sc.id} onClick={() => setScen(sc.id)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ${scen === sc.id ? 'border-ink bg-ink text-surface' : 'border-line text-ink-2'}`}>
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: SCEN_COLORS[sc.id] }} />{sc.label}
            </button>
          ))}
        </div>
        <div className="flex min-w-[320px] flex-1 items-center gap-3">
          <button onClick={() => setPlaying((p) => !p)} className="rounded-full border border-line px-3 py-1 text-sm text-ink" aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? '❚❚' : '▶'}
          </button>
          <input type="range" min={1} max={m.days.length} value={day} onChange={(ev) => setDay(+ev.target.value)}
            className="flex-1 accent-[var(--series-1)]" aria-label="Lead day" />
          <div className="w-44 text-sm">
            <div className="font-medium text-ink">Lead day {day} of {m.days.length}</div>
            <div className="text-ink-3">{dateOf(day)} · issued {formatDay(m.issued)}</div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Wards by
          <select value={metric} onChange={(ev) => setMetric(ev.target.value as Metric)} className="rounded border border-line bg-surface px-2 py-1 text-ink">
            {(Object.keys(METRIC) as Metric[]).map((k) => <option key={k} value={k}>{METRIC[k].label}</option>)}
          </select>
        </label>
      </div>

      {/* Stat tiles for the selected day */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          ['People affected', fmt(total.people), `of ${fmt(m.population_in_domain)} in the domain`],
          ['Buildings affected', fmt(total.buildings), `of ${fmt(m.buildings_in_domain)} mapped`],
          ['Damage', `${fmt(total.loss_equiv)} bldg-equiv.`, 'sum of damage factors (Englhardt 2019)'],
          ['Flooded area', `${total.flooded_km2.toLocaleString('en-GB')} km²`, `max depth ${total.max_depth_m.toFixed(1)} m`],
        ].map(([label, value, sub]) => (
          <div key={label} className="rounded-lg border border-line bg-surface px-3 py-2">
            <div className="text-xs text-ink-3">{label} · day {day}</div>
            <div className="text-lg font-semibold text-ink">{value}</div>
            <div className="text-xs text-ink-2">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="relative h-[640px] overflow-hidden rounded-xl border border-line">
          <Map initialViewState={{ bounds: [[w, s], [e, n]], fitBoundsOptions: { padding: 20 } }} mapStyle={BASEMAPS[basemap].style as string}
            interactiveLayerIds={['bld-hit', 'ward-fill']} onMouseMove={onMove} onMouseLeave={() => setHover(null)}
            onClick={(ev) => { const f = ev.features?.find((x) => x.layer.id === 'ward-fill'); if (f) setSelWard(f.properties.id as number) }}
            attributionControl={{ compact: true, customAttribution: 'Buildings: Overture Maps · Population: WorldPop · Wards: geoBoundaries' }}>
            <NavigationControl position="top-right" />
            <ScaleControl position="bottom-right" />
            {/* Bottom to top: ward fill, all population, flood depth, flooded people, buildings, ward outlines. */}
            <Source id="wards" type="geojson" data={wardsGeo}>
              <Layer id="ward-fill" type="fill" layout={{ visibility: show.wards ? 'visible' : 'none' }}
                paint={{ 'fill-color': stepExpr(metric),
                  'fill-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.4, 13, 0.08] as unknown as number }} />
            </Source>
            {show.popAll && (
              <Source id="pop-all" type="image" url={`${DATA}/population.png`} coordinates={m.corners as never}>
                <Layer id="pop-all" type="raster" paint={{ 'raster-opacity': 0.3, 'raster-resampling': 'nearest' }} />
              </Source>
            )}
            {show.depth && (
              <Source id="depth" type="image" url={`${DATA}/${dir}/depth_d${pad(day)}.png`} coordinates={m.corners as never}>
                <Layer id="depth" type="raster" paint={{ 'raster-opacity': 0.8, 'raster-resampling': 'nearest' }} />
              </Source>
            )}
            {show.popHit && (
              <Source id="pop-hit" type="image" url={`${DATA}/${dir}/pop_d${pad(day)}.png`} coordinates={m.corners as never}>
                <Layer id="pop-hit" type="raster" paint={{ 'raster-opacity': 0.7, 'raster-resampling': 'nearest' }} />
              </Source>
            )}
            <Source id="buildings" type="vector" url={`pmtiles://${ABS('buildings.pmtiles')}`}>
              <Layer id="bld-all" type="fill" source-layer="buildings" minzoom={12} layout={{ visibility: show.buildings ? 'visible' : 'none' }}
                paint={{ 'fill-color': palette['text-muted'], 'fill-opacity': 0.55, 'fill-outline-color': palette['text-secondary'] }} />
              <Layer id="bld-hit" type="fill" source-layer="buildings" filter={hitFilter} layout={{ visibility: show.buildings ? 'visible' : 'none' }}
                paint={{ 'fill-color': depthExpr, 'fill-opacity': 1, 'fill-outline-color': '#08306b' }} />
            </Source>
            <Layer id="ward-line" type="line" source="wards"
              paint={{ 'line-color': palette['text-secondary'], 'line-width': ['case', ['==', ['get', 'id'], selWard ?? -1], 2.5, 0.8] as unknown as number }} />
            {hover && (
              <Popup longitude={hover.lng} latitude={hover.lat} closeButton={false} offset={10} maxWidth="240px">
                {hover.kind === 'b' ? (
                  <div className="text-sm">
                    <div className="font-medium">Flooded building · day {day}</div>
                    <div className="text-ink-2">depth {(Number(hover.p[key] ?? 0) / 100).toFixed(2)} m · ~{Number(hover.p.pop).toFixed(1)} people</div>
                  </div>
                ) : (
                  <div className="text-sm">
                    <div className="font-medium">{String(hover.p.ward)}</div>
                    <div className="text-ink-2">{String(hover.p.district)}</div>
                    <div className="tabular">{fmt(Number(hover.p.people))} people · {fmt(Number(hover.p.buildings))} buildings</div>
                  </div>
                )}
              </Popup>
            )}
          </Map>
          <MapLegend m={m} show={show} setShow={setShow} basemap={basemap} setBasemap={setBasemap} metric={metric} />
        </div>

        <div className="space-y-4">
          <ImpactOverTime m={m} day={day} onDay={setDay} palette={palette} />
          <InflowChart m={m} day={day} palette={palette} />
        </div>
      </div>

      <WardHeatmap m={m} rows={wardData.rows} wards={wardData.wards} scen={scen} metric={metric} day={day}
        onPick={(d, id) => { setDay(d); setSelWard(id) }} palette={palette} />
      <WardTable wards={wardData.wards} dayRows={dayRows} selWard={selWard} onSelect={setSelWard} day={day} />
    </div>
  )
}

function MapLegend({ m, show, setShow, basemap, setBasemap, metric }: {
  m: Manifest; show: Show; setShow: (f: (s: Show) => Show) => void
  basemap: Basemap; setBasemap: (b: Basemap) => void; metric: Metric
}) {
  const toggle = (k: keyof Show) => setShow((s) => ({ ...s, [k]: !s[k] }))
  const row = (k: keyof Show, label: string) => (
    <label key={k} className="flex cursor-pointer items-center gap-1.5 text-ink-2">
      <input type="checkbox" checked={show[k]} onChange={() => toggle(k)} className="accent-[var(--series-1)]" />{label}
    </label>
  )
  const ramp = (colors: string[], labels: string[]) => (
    <div className="flex items-center gap-1">
      {colors.map((c, i) => <span key={c} className="flex items-center gap-0.5"><i className="inline-block h-2.5 w-3 rounded-sm" style={{ background: c }} /><span className="text-[10px] text-ink-3">{labels[i]}</span></span>)}
    </div>
  )
  return (
    <div className="absolute bottom-8 left-3 max-w-[250px] space-y-1.5 rounded-lg border border-line bg-surface/95 p-2.5 text-xs shadow-sm">
      <div className="font-medium text-ink">Layers</div>
      {row('depth', 'Flood depth')}
      {ramp(DEPTH_COLORS, m.depth_legend_m.map((d) => `${d} m`))}
      {row('buildings', 'Buildings (flooded by depth, others grey)')}
      {row('popHit', 'People in flooded area (per ha)')}
      {ramp(POP_COLORS, m.pop_legend_per_ha.map(String))}
      {row('popAll', 'All population (grey, reference)')}
      {row('wards', `Wards: ${METRIC[metric].label.toLowerCase()}`)}
      <select value={basemap} onChange={(ev) => setBasemap(ev.target.value as Basemap)} className="mt-1 w-full rounded border border-line bg-surface px-1 py-0.5 text-ink">
        {(Object.keys(BASEMAPS) as Basemap[]).map((b) => <option key={b} value={b}>{BASEMAPS[b].label} basemap</option>)}
      </select>
    </div>
  )
}

type Pal = ReturnType<typeof usePalette>['palette']
const axisStyle = (p: Pal) => ({
  axisLine: { lineStyle: { color: p.axis } }, axisTick: { show: false }, axisLabel: { color: p['text-muted'] },
  splitLine: { lineStyle: { color: p.grid } },
})
const tip = (p: Pal) => ({ backgroundColor: p.surface, borderColor: p.grid, textStyle: { color: p['text-primary'], fontSize: 12 } })

function ImpactOverTime({ m, day, onDay, palette: p }: { m: Manifest; day: number; onDay: (d: number) => void; palette: Pal }) {
  const days = m.days.map((_, i) => i + 1)
  const chart = (field: 'people' | 'buildings', title: string): EChartsOption => ({
    animation: false,
    title: { text: title, left: 0, textStyle: { fontSize: 13, fontWeight: 500, color: p['text-primary'] } },
    grid: { left: 56, right: 12, top: 66, bottom: 24 },
    tooltip: { trigger: 'axis', ...tip(p) },
    legend: { left: 0, top: 30, textStyle: { color: p['text-secondary'], fontSize: 11 } },
    xAxis: { type: 'category', data: days, name: 'lead day', nameLocation: 'end', nameTextStyle: { color: p['text-muted'] }, ...axisStyle(p) },
    yAxis: { type: 'value', ...axisStyle(p), axisLine: { show: false } },
    series: m.scenarios.map((sc, i) => ({
      type: 'line', name: sc.label, data: m.totals[sc.id].map((t) => t[field]), symbolSize: 6, color: SCEN_COLORS[sc.id],
      lineStyle: { width: 2 },
      ...(i === 0 ? { markLine: { silent: true, symbol: 'none', data: [{ xAxis: day - 1 }], lineStyle: { color: p['text-muted'], type: 'solid' }, label: { show: false } } } : {}),
    })),
  })
  const onEvents = { click: (e: { dataIndex: number }) => onDay(e.dataIndex + 1) }
  return (
    <section className="space-y-2 rounded-xl border border-line bg-surface p-4">
      <ReactECharts option={chart('people', 'People affected per lead day')} style={{ height: 220 }} onEvents={onEvents} notMerge />
      <ReactECharts option={chart('buildings', 'Buildings affected per lead day')} style={{ height: 220 }} onEvents={onEvents} notMerge />
      <p className="text-xs text-ink-3">Daily maximum flood on each lead day. Click a point to jump to that day.</p>
    </section>
  )
}

function InflowChart({ m, day, palette: p }: { m: Manifest; day: number; palette: Pal }) {
  const days = m.days.map((d) => formatDay(d))
  const reaches = Object.keys(m.scenarios[0].hydrograph)
  const option: EChartsOption = {
    animation: false,
    title: { text: 'Forecast inflow to the floodplain (m³/s)', left: 0, textStyle: { fontSize: 13, fontWeight: 500, color: p['text-primary'] } },
    grid: { left: 56, right: 12, top: 66, bottom: 24 },
    tooltip: { trigger: 'axis', ...tip(p) },
    legend: { left: 0, top: 30, textStyle: { color: p['text-secondary'], fontSize: 11 } },
    xAxis: { type: 'category', data: days, ...axisStyle(p), axisLabel: { color: p['text-muted'], interval: 3 } },
    yAxis: { type: 'value', ...axisStyle(p), axisLine: { show: false } },
    series: m.scenarios.map((sc, i) => ({
      type: 'line', name: sc.label, symbol: 'none', color: SCEN_COLORS[sc.id], lineStyle: { width: 2 },
      data: days.map((_, k) => reaches.reduce((a, r) => a + sc.hydrograph[r][k], 0)),
      ...(i === 0 ? { markLine: { silent: true, symbol: 'none', data: [{ xAxis: day - 1 }], lineStyle: { color: p['text-muted'], type: 'solid' }, label: { show: false } } } : {}),
    })),
  }
  const rain: EChartsOption = {
    animation: false,
    title: { text: 'Basin rainfall forecast, ensemble median (mm/day)', left: 0, textStyle: { fontSize: 13, fontWeight: 500, color: p['text-primary'] } },
    grid: { left: 56, right: 12, top: 32, bottom: 24 },
    tooltip: { trigger: 'axis', ...tip(p) },
    xAxis: { type: 'category', data: days, ...axisStyle(p), axisLabel: { color: p['text-muted'], interval: 3 } },
    yAxis: { type: 'value', ...axisStyle(p), axisLine: { show: false } },
    series: [{ type: 'bar', data: m.rain_mm, barMaxWidth: 16, color: p['series-1'], itemStyle: { borderRadius: [4, 4, 0, 0] } }],
  }
  return (
    <section className="space-y-2 rounded-xl border border-line bg-surface p-4">
      <ReactECharts option={option} style={{ height: 210 }} notMerge />
      <ReactECharts option={rain} style={{ height: 140 }} notMerge />
      <p className="text-xs text-ink-3">Sum of the {reaches.join(' and ').replaceAll('_', ' ')} reaches, the inflows of the hydraulic model.</p>
    </section>
  )
}

function WardHeatmap({ m, rows, wards, scen, metric, day, onPick, palette: p }: {
  m: Manifest; rows: WardRow[]; wards: Ward[]; scen: string; metric: Metric; day: number
  onPick: (d: number, id: number) => void; palette: Pal
}) {
  const sel = rows.filter((r) => r.scenario === scen)
  const peak: Record<number, number> = {}
  sel.forEach((r) => (peak[r.id] = Math.max(peak[r.id] ?? 0, r[metric])))
  const top = Object.entries(peak).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([id]) => +id).reverse()
  const name = (id: number) => wards.find((w) => w.id === id)?.ward ?? String(id)
  // Colour on a log scale so small wards' development is visible next to the largest; value [2] stays raw.
  const data = sel.filter((r) => top.includes(r.id)).map((r) => [r.day - 1, top.indexOf(r.id), r[metric], Math.log10(1 + r[metric])])
  const vmax = Math.max(1, ...data.map((d) => d[2]))
  const option: EChartsOption = {
    animation: false,
    grid: { left: 140, right: 16, top: 8, bottom: 56 },
    tooltip: { ...tip(p), formatter: (x: unknown) => {
      const v = (x as { value: number[] }).value
      return `${name(top[v[1]])} · lead day ${v[0] + 1}<br/><b>${fmt(v[2])}</b> ${METRIC[metric].label.toLowerCase()}`
    } },
    xAxis: { type: 'category', data: m.days.map((_, i) => i + 1), name: 'lead day', nameLocation: 'middle', nameGap: 26,
      nameTextStyle: { color: p['text-muted'] }, ...axisStyle(p), splitLine: { show: false } },
    yAxis: { type: 'category', data: top.map(name), ...axisStyle(p), splitLine: { show: false } },
    visualMap: { type: 'continuous', dimension: 3, min: 0, max: Math.log10(1 + vmax), calculable: false,
      orient: 'horizontal', left: 140, bottom: 0, itemWidth: 10, itemHeight: 160, text: [fmt(vmax), '0 (log scale)'],
      textStyle: { color: p['text-secondary'], fontSize: 11 }, inRange: { color: RAMP } },
    series: [{ type: 'heatmap', data, itemStyle: { borderColor: p.surface, borderWidth: 2 },
      markLine: { silent: true, symbol: 'none', data: [{ xAxis: day - 1 }], lineStyle: { color: p['text-primary'], width: 1.5, type: 'solid' }, label: { show: false } } }],
  }
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="text-base font-semibold text-ink">How the impact develops, per ward</h2>
      <p className="mb-2 text-xs text-ink-3">
        {METRIC[metric].label}, {m.scenarios.find((s) => s.id === scen)!.label.toLowerCase()}, 15 most affected wards. Click a cell to show that day and ward on the map.
      </p>
      {top.length ? (
        <ReactECharts option={option} style={{ height: Math.max(220, 26 * top.length + 70) }} notMerge
          onEvents={{ click: (e: { value: number[] }) => onPick(e.value[0] + 1, top[e.value[1]]) }} />
      ) : <p className="text-sm text-ink-3">No ward is affected in this scenario.</p>}
    </section>
  )
}

function WardTable({ wards, dayRows, selWard, onSelect, day }: {
  wards: Ward[]; dayRows: Record<number, WardRow>; selWard: number | null; onSelect: (id: number) => void; day: number
}) {
  const rows = wards.map((w) => ({ ...w, ...(dayRows[w.id] ?? { people: 0, buildings: 0, loss_equiv: 0 }) }))
    .sort((a, b) => b.people - a.people || b.buildings - a.buildings)
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="text-base font-semibold text-ink">Wards on lead day {day}</h2>
      <div className="mt-2 max-h-[420px] overflow-auto">
        <table className="tabular w-full min-w-[720px] text-sm">
          <thead className="sticky top-0 bg-surface text-left text-xs text-ink-3">
            <tr><th className="py-2 font-normal">Ward</th><th className="font-normal">District</th>
              <th className="text-right font-normal">People affected</th><th className="text-right font-normal">% of residents</th>
              <th className="text-right font-normal">Buildings affected</th><th className="text-right font-normal">of mapped</th>
              <th className="text-right font-normal">Damage (bldg-equiv.)</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} onClick={() => onSelect(r.id)} aria-selected={selWard === r.id}
                className={`cursor-pointer border-t border-line ${selWard === r.id ? 'bg-[var(--grid)]/60' : ''} ${r.people + r.buildings === 0 ? 'text-ink-3' : 'text-ink'}`}>
                <td className="py-1.5 font-medium">{r.ward}</td><td className="text-ink-2">{r.district}</td>
                <td className="text-right">{fmt(r.people)}</td>
                <td className="text-right">{r.pop_total ? ((100 * r.people) / r.pop_total).toFixed(1) : '0.0'}%</td>
                <td className="text-right">{fmt(r.buildings)}</td><td className="text-right text-ink-3">{fmt(r.buildings_total)}</td>
                <td className="text-right">{r.loss_equiv.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
