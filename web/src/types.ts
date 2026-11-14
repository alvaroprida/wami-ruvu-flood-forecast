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

// Impact-based forecast products: files under public/data/ibf/{demo,live}/ (see pipeline/ibf/).
export interface IbfScenario {
  id: string
  label: string
  dir: string
  hydrograph?: { times: string[]; series: Record<string, number[]> }
}

export interface IbfManifest {
  kind: 'demo' | 'live'
  title: string
  description: string
  issued?: string
  period?: [string, string]
  domain: { id: string; name: string; bbox: [number, number, number, number] }
  status: 'ok' | 'not_triggered' | 'unavailable'
  note?: string
  scenarios: IbfScenario[]
}

export interface IbfSummary {
  people_affected: number
  buildings_affected: number
  buildings_in_domain: number
  flooded_area_km2: number
  max_depth_m: number
  mean_damage_factor: number
  building_loss_equivalents: number
  by_depth_class: Record<string, { people: number; buildings: number }>
  flood_depth_threshold_m: number
  vulnerability: { source: string; class: string }
  population_note: string
  depth_legend_m: number[]
  areas?: IbfArea[]
  districts?: IbfDistrict[]
}

/** Impact in one ward (ADM3), as written by pipeline/ibf/products.py. */
export interface IbfArea {
  id: number
  ward: string
  district: string
  people: number
  buildings: number
  area_km2: number
  max_depth: number
  damage: number
  pop_total: number
  buildings_total: number
}

export interface IbfDistrict {
  district: string
  people: number
  buildings: number
  pop_total: number
  buildings_total: number
}
