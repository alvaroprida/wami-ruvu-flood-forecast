import type { EChartsOption } from 'echarts'
import ReactECharts from 'echarts-for-react'
import { useMemo } from 'react'
import { formatDay } from '../format'
import { usePalette } from '../theme'

const SERIES_ROLES = ['series-1', 'status-serious', 'history'] as const

/** Discharge entering the hydraulic model, one line per inflow reach. */
export function InflowChart({ times, series, names }: { times: string[]; series: Record<string, number[]>; names: Record<string, string> }) {
  const { palette: p } = usePalette()
  const option = useMemo<EChartsOption>(
    () => ({
      animation: false,
      grid: { left: 52, right: 16, top: 52, bottom: 28 },
      legend: { top: 0, left: 0, icon: 'roundRect', itemHeight: 3, itemWidth: 14, textStyle: { color: p['text-secondary'], fontSize: 12 } },
      tooltip: {
        trigger: 'axis',
        backgroundColor: p.surface,
        borderColor: p.grid,
        textStyle: { color: p['text-primary'], fontSize: 12 },
        valueFormatter: (v) => `${Math.round(Number(v)).toLocaleString('en-GB')} m³/s`,
      },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: p.axis } },
        axisTick: { show: false },
        axisLabel: { color: p['text-muted'], formatter: '{dd} {MMM}', hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        name: 'm³/s',
        nameTextStyle: { color: p['text-muted'], align: 'left', padding: [0, 0, 6, -40] },
        axisLabel: { color: p['text-muted'] },
        splitLine: { lineStyle: { color: p.grid } },
      },
      series: Object.entries(series).map(([reach, values], i) => ({
        name: names[reach] ?? reach,
        type: 'line',
        showSymbol: false,
        lineStyle: { width: 2, color: p[SERIES_ROLES[i % SERIES_ROLES.length]] },
        itemStyle: { color: p[SERIES_ROLES[i % SERIES_ROLES.length]] },
        data: times.map((t, k) => [t, values[k]]),
      })),
    }),
    [times, series, names, p],
  )
  const span = times.length ? `${formatDay(times[0])} – ${formatDay(times[times.length - 1])}` : ''
  return (
    <div>
      <div className="mb-1 text-xs text-ink-3">{span}</div>
      <ReactECharts option={option} style={{ height: 200 }} notMerge />
    </div>
  )
}
