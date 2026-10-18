import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { useMemo } from 'react'
import { formatDay, formatQ, formatValid } from '../format'
import { type Palette, usePalette } from '../theme'
import type { ReachDetail, Thresholds } from '../types'

const THRESHOLD_LINES: { key: keyof Thresholds; label: string; role: keyof Palette }[] = [
  { key: 'rp2', label: '2-yr', role: 'status-warning' },
  { key: 'rp5', label: '5-yr', role: 'status-serious' },
  { key: 'rp20', label: '20-yr', role: 'status-critical' },
  { key: 'rp50', label: '50-yr', role: 'status-critical' },
]

// Shared horizontal frame so rainfall bars sit exactly above the hydrograph.
const GRID = { left: 56, right: 64 }

function niceCeil(x: number): number {
  const mag = 10 ** Math.floor(Math.log10(x))
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => s * mag >= x) ?? 10
  return step * mag
}

function baseAxes(p: Palette, min: number, max: number) {
  return {
    xAxis: {
      type: 'time' as const,
      min,
      max,
      axisLine: { lineStyle: { color: p.axis } },
      axisTick: { show: false },
      axisLabel: { color: p['text-muted'], formatter: '{dd} {MMM}', hideOverlap: true },
      splitLine: { show: false },
    },
    yAxisStyle: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: p['text-muted'] },
      splitLine: { lineStyle: { color: p.grid, width: 1, type: 'solid' as const } },
      nameTextStyle: { color: p['text-muted'], align: 'left' as const, padding: [0, 0, 0, -40] },
    },
  }
}

// Axis-trigger tooltip params carry the hovered x value; the echarts types omit it.
const axisValue = (params: unknown) =>
  (Array.isArray(params) ? params[0] : params as { axisValue: number }).axisValue as number

const tooltipBox = (p: Palette) => ({
  backgroundColor: p.surface,
  borderColor: p.grid,
  textStyle: { color: p['text-primary'], fontSize: 12 },
  extraCssText: 'border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.12);',
})

/** Axis range follows the data; return periods well above it are named in a caption instead. */
export function yRange(d: ReachDetail, showMembers: boolean) {
  const fc = d.forecast
  const dataMax = Math.max(...(showMembers ? fc.members.flat() : fc.p95), ...d.history.q, 1)
  // Bring the 2-year line into view once flows get within reach of it.
  const target = dataMax >= 0.4 * d.thresholds.rp2 ? Math.max(dataMax, d.thresholds.rp2) : dataMax
  const yMax = niceCeil(target * 1.15)
  const hidden = THRESHOLD_LINES.filter((l) => d.thresholds[l.key] > yMax)
  return { yMax, hidden }
}

function hydrographOption(d: ReachDetail, p: Palette, showMembers: boolean): EChartsOption {
  const t = (s: string) => new Date(s).getTime()
  const fc = d.forecast
  const ft = fc.times.map(t)
  const pair = (vals: number[]) => vals.map((v, i) => [ft[i], v])
  const diff = (hi: number[], lo: number[]) => hi.map((v, i) => [ft[i], +(v - lo[i]).toFixed(1)])

  const min = t(d.history.times[0])
  const max = ft[ft.length - 1]
  const { yMax } = yRange(d, showMembers)
  const { xAxis, yAxisStyle } = baseAxes(p, min, max)

  const index = new Map(ft.map((v, i) => [v, i]))
  const histIndex = new Map(d.history.times.map((s, i) => [t(s), i]))
  const band = { type: 'line' as const, symbol: 'none', lineStyle: { opacity: 0 }, silent: true, color: p['series-1'] }

  return {
    animation: false,
    // The legend wraps to two rows on narrow screens.
    grid: { ...GRID, top: window.innerWidth < 640 ? 60 : 36, bottom: 28 },
    legend: {
      top: 0,
      left: GRID.left - 8,
      itemWidth: 16,
      itemHeight: 8,
      textStyle: { color: p['text-secondary'], fontSize: 12 },
      data: [
        'Simulated (past)',
        'Ensemble median',
        { name: '50% range', icon: 'roundRect', itemStyle: { opacity: 0.45 } },
        { name: '90% range', icon: 'roundRect', itemStyle: { opacity: 0.2 } },
        ...(showMembers ? [{ name: 'Members', itemStyle: { opacity: 0.4 } }] : []),
      ],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: p.axis } },
      ...tooltipBox(p),
      formatter: (params) => {
        const x = axisValue(params)
        const head = `<div style="margin-bottom:4px;color:${p['text-secondary']}">${formatValid(new Date(x).toISOString())}</div>`
        const i = index.get(x)
        const h = histIndex.get(x)
        const row = (k: string, v: string) => `<div style="display:flex;justify-content:space-between;gap:16px"><span>${k}</span><b style="font-variant-numeric:tabular-nums">${v}</b></div>`
        if (i !== undefined && i > 0) {
          return head + row('Median', `${formatQ(fc.p50[i])} m³/s`)
            + row('50% range', `${formatQ(fc.p25[i])}–${formatQ(fc.p75[i])}`)
            + row('90% range', `${formatQ(fc.p05[i])}–${formatQ(fc.p95[i])}`)
        }
        if (h !== undefined) return head + row('Simulated', `${formatQ(d.history.q[h])} m³/s`)
        return head
      },
    },
    xAxis,
    yAxis: { type: 'value', name: 'm³/s', min: 0, max: yMax, ...yAxisStyle },
    series: [
      // Bands as stacked areas: invisible lower bound + visible width.
      { ...band, name: '90% range', stack: 'b90', data: pair(fc.p05) },
      { ...band, name: '90% range', stack: 'b90', data: diff(fc.p95, fc.p05), areaStyle: { color: p['series-1'], opacity: 0.12 } },
      { ...band, name: '50% range', stack: 'b50', data: pair(fc.p25) },
      { ...band, name: '50% range', stack: 'b50', data: diff(fc.p75, fc.p25), areaStyle: { color: p['series-1'], opacity: 0.24 } },
      ...(showMembers
        ? fc.members.map((m) => ({
            type: 'line' as const,
            name: 'Members',
            data: pair(m),
            symbol: 'none',
            silent: true,
            color: p['series-1'],
            lineStyle: { width: 1, opacity: 0.18 },
            z: 1,
          }))
        : []),
      {
        type: 'line',
        name: 'Simulated (past)',
        data: d.history.q.map((v, i) => [t(d.history.times[i]), v]),
        symbol: 'none',
        color: p.history,
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        z: 3,
      },
      {
        type: 'line',
        name: 'Ensemble median',
        data: pair(fc.p50),
        symbol: 'none',
        color: p['series-1'],
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        z: 4,
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              xAxis: ft[0],
              lineStyle: { color: p['text-muted'], width: 1, type: 'solid' },
              label: { formatter: 'Issued', position: 'end', color: p['text-muted'], fontSize: 11 },
            },
            ...THRESHOLD_LINES.filter((l) => d.thresholds[l.key] <= yMax).map((l) => ({
              yAxis: d.thresholds[l.key],
              lineStyle: { color: p[l.role], width: 1.5, type: 'solid' as const },
              label: { formatter: l.label, position: 'end' as const, color: p['text-secondary'], fontSize: 11 },
            })),
          ],
        },
      },
    ],
  }
}

function rainfallOption(d: ReachDetail, p: Palette): EChartsOption {
  const t = (s: string) => new Date(s).getTime()
  const r = d.rainfall
  // Daily totals plotted at mid-day so each bar covers its own day.
  const mid = r.days.map((s) => t(s) + 12 * 3_600_000)
  const { xAxis, yAxisStyle } = baseAxes(p, t(d.history.times[0]), t(d.forecast.times[d.forecast.times.length - 1]))

  return {
    animation: false,
    grid: { ...GRID, top: 24, bottom: 8 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: p.grid, opacity: 0.5 } },
      ...tooltipBox(p),
      formatter: (params) => {
        const i = mid.indexOf(axisValue(params))
        if (i < 0) return ''
        return `<div style="margin-bottom:4px;color:${p['text-secondary']}">${formatDay(r.days[i])}</div>`
          + `<div>Median <b style="font-variant-numeric:tabular-nums">${r.p50[i]} mm</b></div>`
          + `<div style="color:${p['text-secondary']}">10–90%: ${r.p10[i]}–${r.p90[i]} mm</div>`
      },
    },
    xAxis: { ...xAxis, axisLabel: { show: false }, axisLine: { lineStyle: { color: p.axis } } },
    yAxis: { type: 'value', name: 'mm/day', min: 0, splitNumber: 2, ...yAxisStyle },
    series: [
      {
        type: 'bar',
        name: 'Rainfall (median)',
        data: r.p50.map((v, i) => [mid[i], v]),
        barMaxWidth: 16,
        color: p['series-1'],
        itemStyle: { borderRadius: [4, 4, 0, 0] },
      },
      {
        // 10–90% whiskers.
        type: 'custom',
        name: 'Rainfall range',
        silent: true,
        data: r.p10.map((lo, i) => [mid[i], lo, r.p90[i]]),
        renderItem: (_params, api) => {
          const top = api.coord([api.value(0), api.value(2)])
          const bottom = api.coord([api.value(0), api.value(1)])
          return {
            type: 'line',
            shape: { x1: top[0], y1: top[1], x2: bottom[0], y2: bottom[1] },
            style: { stroke: p['text-secondary'], lineWidth: 1 },
          }
        },
        z: 3,
      },
    ],
  }
}

export function ForecastCharts({ detail, showMembers }: { detail: ReachDetail; showMembers: boolean }) {
  const { palette } = usePalette()
  const hydro = useMemo(() => hydrographOption(detail, palette, showMembers), [detail, palette, showMembers])
  const rain = useMemo(() => rainfallOption(detail, palette), [detail, palette])
  const { hidden } = yRange(detail, showMembers)

  return (
    <div>
      <h3 className="text-sm font-medium text-ink">Catchment rainfall forecast</h3>
      <p className="text-xs text-ink-3">Daily ensemble median, whiskers show the 10–90% range</p>
      <ReactECharts option={rain} notMerge style={{ height: 120 }} />
      <h3 className="mt-3 text-sm font-medium text-ink">River discharge at reach outlet</h3>
      <p className="text-xs text-ink-3">Past 10 days simulated from observed rainfall, then the {detail.forecast.members.length}-member forecast</p>
      <ReactECharts option={hydro} notMerge style={{ height: 300 }} />
      {hidden.length > 0 && (
        <p className="text-xs text-ink-3">
          Above this range: {hidden.map((l) => `${l.label} flow ${formatQ(detail.thresholds[l.key])} m³/s`).join(' · ')}
        </p>
      )}
    </div>
  )
}
