// Shared definitions for the impact views: metrics, colour ramps, severity scale, small helpers.
import type { IbfArea, IbfSummary } from './types'

export type MetricId = 'people' | 'buildings' | 'share' | 'damage'

// Sequential ramp (light to dark = low to high impact). Class 0 is "no impact".
export const RAMP = ['#ffffb2', '#fed976', '#feb24c', '#fd8d3c', '#f03b20', '#bd0026']

export const METRICS: Record<MetricId, { label: string; unit: string; steps: number[]; value: (a: IbfArea) => number; format: (v: number) => string }> = {
  people: {
    label: 'People affected',
    unit: 'people',
    steps: [1, 100, 500, 1000, 5000, 10000],
    value: (a) => a.people,
    format: (v) => Math.round(v).toLocaleString('en-GB'),
  },
  buildings: {
    label: 'Buildings affected',
    unit: 'buildings',
    steps: [1, 25, 100, 300, 1000, 3000],
    value: (a) => a.buildings,
    format: (v) => Math.round(v).toLocaleString('en-GB'),
  },
  share: {
    label: 'Share of ward population',
    unit: '% of residents',
    steps: [0.1, 1, 5, 10, 25, 50],
    value: (a) => (a.pop_total > 0 ? (100 * a.people) / a.pop_total : 0),
    format: (v) => (v < 10 ? v.toFixed(1) : Math.round(v).toString()) + '%',
  },
  damage: {
    label: 'Mean building damage',
    unit: 'of building value',
    steps: [0.01, 0.2, 0.4, 0.6, 0.8, 0.95],
    value: (a) => a.damage,
    format: (v) => `${Math.round(v * 100)}%`,
  },
}

/** MapLibre `step` expression colouring a feature property by the metric's classes. */
export function stepExpression(prop: string, metric: MetricId): unknown[] {
  const { steps } = METRICS[metric]
  const expr: unknown[] = ['step', ['get', prop], 'rgba(0,0,0,0)']
  steps.forEach((s, i) => expr.push(s, RAMP[i]))
  return expr
}

export function legendClasses(metric: MetricId): { color: string; label: string }[] {
  const { steps, format } = METRICS[metric]
  return steps.map((s, i) => ({
    color: RAMP[i],
    label: i === steps.length - 1 ? `≥ ${format(s)}` : `${format(s)}–${format(steps[i + 1])}`,
  }))
}

/**
 * Indicative impact scale from people affected, for quick triage. The thresholds are illustrative
 * (not an official scale) and should be agreed with the users of the service.
 */
export const SEVERITY = [
  { level: 0, label: 'No impact', min: 0, color: 'var(--river)' },
  { level: 1, label: 'Minor', min: 1, color: 'var(--status-warning)' },
  { level: 2, label: 'Moderate', min: 1000, color: 'var(--status-serious)' },
  { level: 3, label: 'Severe', min: 10000, color: 'var(--status-critical)' },
  { level: 4, label: 'Extreme', min: 50000, color: 'var(--status-critical)' },
] as const

export function severityOf(people: number) {
  return [...SEVERITY].reverse().find((s) => people >= s.min) ?? SEVERITY[0]
}

export type BBox = [number, number, number, number]

/** Bounding box of a (Multi)Polygon geometry's coordinates. */
export function bboxOf(coords: unknown): BBox {
  let w = Infinity
  let s = Infinity
  let e = -Infinity
  let n = -Infinity
  const walk = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === 'number') {
      const [x, y] = c as number[]
      w = Math.min(w, x)
      e = Math.max(e, x)
      s = Math.min(s, y)
      n = Math.max(n, y)
    } else if (Array.isArray(c)) c.forEach(walk)
  }
  walk(coords)
  return [w, s, e, n]
}

export const round = (n: number, to = 10) => (Math.round(n / to) * to).toLocaleString('en-GB')

export function areasToCsv(areas: IbfArea[]): string {
  const head = ['district', 'ward', 'people_affected', 'population_total', 'buildings_affected', 'buildings_total', 'flooded_km2', 'max_depth_m', 'mean_damage_factor']
  const rows = areas.map((a) => [a.district, a.ward, a.people, a.pop_total, a.buildings, a.buildings_total, a.area_km2, a.max_depth, a.damage])
  const esc = (v: string | number) => (typeof v === 'string' && /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : String(v))
  return [head, ...rows].map((r) => r.map(esc).join(',')).join('\n')
}

export function situationText(title: string, scenario: string, s: IbfSummary): string {
  const sev = severityOf(s.people_affected)
  const top = (s.areas ?? []).slice(0, 5).map((a) => `${a.ward} (${a.district}): ~${round(a.people)} people, ~${round(a.buildings)} buildings`)
  return [
    `${title} - ${scenario}`,
    `Impact scale: ${sev.label}. Approx. ${round(s.people_affected)} people and ${round(s.buildings_affected)} buildings affected over ${s.flooded_area_km2.toFixed(0)} km2 (max depth ${s.max_depth_m.toFixed(1)} m).`,
    top.length ? `Most affected wards: ${top.join('; ')}.` : '',
    'Experimental model output (uncalibrated hydrology), not an official warning.',
  ]
    .filter(Boolean)
    .join('\n')
}
