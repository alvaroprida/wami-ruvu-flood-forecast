// Data contract shared with pipeline/: the files under public/data/.

export type AlertLevel = 0 | 1 | 2 | 3

export interface Thresholds {
  rp2: number
  rp5: number
  rp20: number
  rp50: number
}

export interface ReachSummary {
  alert_level: AlertLevel
  prob_exceed: Thresholds
  peak_q50: number
  peak_time: string
  thresholds: Thresholds
}

export interface Forecast {
  issued: string
  mock: boolean
  model: string
  forcing: string
  members: number
  timestep_hours: number
  lead_days: number
  alert_rule: { level: AlertLevel; return_period: number; min_probability: number }[]
  reaches: Record<string, ReachSummary>
}

export interface ReachDetail {
  id: string
  issued: string
  units: string
  history: { times: string[]; q: number[] }
  forecast: {
    times: string[]
    p05: number[]
    p25: number[]
    p50: number[]
    p75: number[]
    p95: number[]
    members: number[][]
  }
  thresholds: Thresholds
  rainfall: { days: string[]; p10: number[]; p50: number[]; p90: number[] }
}

export interface ReachProps {
  id: string
  name: string
  basin: 'Wami' | 'Ruvu'
  upstream_area_km2: number
  outlet: [number, number]
}

export interface Basins {
  type: 'FeatureCollection'
  features: {
    type: 'Feature'
    properties: { kind: 'basin' | 'subbasin' | 'label'; basin: 'Wami' | 'Ruvu'; HYBAS_ID: number | null; area_km2: number }
    geometry: { type: 'Polygon' | 'MultiPolygon' | 'Point'; coordinates: unknown }
  }[]
}

export interface Streams {
  type: 'FeatureCollection'
  features: { type: 'Feature'; properties: { uparea: number }; geometry: unknown }[]
}

export interface Network {
  type: 'FeatureCollection'
  features: {
    type: 'Feature'
    properties: ReachProps
    geometry: { type: 'MultiLineString'; coordinates: number[][][] }
  }[]
}
