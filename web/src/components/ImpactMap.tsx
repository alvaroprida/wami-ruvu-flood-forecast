import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import Map, { Layer, NavigationControl, Popup, ScaleControl, Source, type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre'
import { type BBox, legendClasses, METRICS, type MetricId, stepExpression } from '../impact'
import { usePalette } from '../theme'

setWorkerUrl(workerUrl)

export type Basemap = 'light' | 'streets' | 'satellite' | 'dark'

export const BASEMAPS: Record<Basemap, { label: string; style: string | object }> = {
  light: { label: 'Light', style: 'https://tiles.openfreemap.org/styles/positron' },
  streets: { label: 'Streets', style: 'https://tiles.openfreemap.org/styles/liberty' },
  satellite: {
    label: 'Satellite',
    style: {
      version: 8,
      glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
      sources: {
        imagery: {
          type: 'raster',
          tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
          tileSize: 256,
          maxzoom: 19,
          attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
        },
      },
      layers: [{ id: 'imagery', type: 'raster', source: 'imagery' }],
    },
  },
  dark: { label: 'Dark', style: 'https://tiles.openfreemap.org/styles/dark' },
}

export const DEPTH_COLORS = ['#a6cee3', '#4292c6', '#2166ac', '#08306b']
export const POP_COLORS = ['#fed976', '#fd8d3c', '#e31a1c', '#800026']

export interface ImpactLayers {
  depth: boolean
  wards: boolean
  buildings: boolean
  population: boolean
}

type Corners = [[number, number], [number, number], [number, number], [number, number]]
type Wards = { type: 'FeatureCollection'; features: { type: 'Feature'; properties: Record<string, string | number>; geometry: unknown }[] }

interface Props {
  bbox: BBox
  base: string // URL of the scenario directory, with trailing slash
  corners: Corners
  wards?: Wards
  layers: ImpactLayers
  metric: MetricId
  basemap: Basemap
  depthOpacity: number
  selectedWard?: number
  onSelectWard: (id: number | undefined) => void
  focus?: BBox // zoom here when it changes
}

type Hover =
  | { kind: 'ward'; lng: number; lat: number; props: Record<string, string | number> }
  | { kind: 'building'; lng: number; lat: number; props: Record<string, string | number> }

export function ImpactMap({ bbox, base, corners, wards, layers, metric, basemap, depthOpacity, selectedWard, onSelectWard, focus }: Props) {
  const { palette } = usePalette()
  const ref = useRef<MapRef>(null)
  const [hover, setHover] = useState<Hover | null>(null)

  useEffect(() => {
    if (focus) ref.current?.fitBounds([[focus[0], focus[1]], [focus[2], focus[3]]], { padding: 60, maxZoom: 13, duration: 700 })
  }, [focus])

  const onMove = (e: MapLayerMouseEvent) => {
    const b = e.features?.find((f) => f.layer.id === 'buildings')
    const w = e.features?.find((f) => f.layer.id === 'wards-fill')
    const f = b ?? w
    setHover(f ? { kind: b ? 'building' : 'ward', lng: e.lngLat.lng, lat: e.lngLat.lat, props: f.properties } : null)
  }
  const vis = (on: boolean) => ({ visibility: on ? ('visible' as const) : ('none' as const) })
  const lineColor = basemap === 'satellite' || basemap === 'dark' ? '#ffffff' : '#52514e'
  const prop = metric === 'share' ? 'share' : metric

  return (
    <div className="relative h-full min-h-[480px] overflow-hidden rounded-xl border border-line">
      <Map
        ref={ref}
        initialViewState={{ bounds: [[bbox[0], bbox[1]], [bbox[2], bbox[3]]], fitBoundsOptions: { padding: 16 } }}
        mapStyle={BASEMAPS[basemap].style as string}
        interactiveLayerIds={['wards-fill', 'buildings']}
        cursor={hover ? 'pointer' : 'grab'}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const w = e.features?.find((f) => f.layer.id === 'wards-fill')
          onSelectWard(w ? Number(w.properties.id) : undefined)
        }}
        attributionControl={{ compact: true, customAttribution: 'Flood model: SFINCS · Buildings: Overture Maps · Population: WorldPop · Wards: geoBoundaries' }}
      >
        <NavigationControl position="top-right" showCompass={false} />
        <ScaleControl position="bottom-right" />

        {wards && (
          <Source id="wards" type="geojson" data={wards as never}>
            <Layer
              id="wards-fill"
              type="fill"
              layout={vis(layers.wards)}
              paint={{ 'fill-color': stepExpression(prop, metric) as never, 'fill-opacity': 0.5 }}
            />
            <Layer id="wards-line" type="line" layout={vis(layers.wards)} paint={{ 'line-color': lineColor, 'line-width': 0.8, 'line-opacity': 0.7 }} />
            <Layer
              id="wards-selected"
              type="line"
              filter={['==', ['get', 'id'], selectedWard ?? -1]}
              paint={{ 'line-color': palette['series-1'], 'line-width': 3 }}
            />
            <Layer
              id="wards-label"
              type="symbol"
              minzoom={10}
              layout={{ ...vis(layers.wards), 'text-field': ['get', 'ward'], 'text-font': ['Noto Sans Regular'], 'text-size': 11 }}
              paint={{ 'text-color': basemap === 'satellite' || basemap === 'dark' ? '#ffffff' : '#222222', 'text-halo-color': basemap === 'satellite' || basemap === 'dark' ? '#000000' : '#ffffff', 'text-halo-width': 1.2 }}
            />
          </Source>
        )}

        <Source id="depth" type="image" url={`${base}depth.png`} coordinates={corners}>
          <Layer id="depth" type="raster" layout={vis(layers.depth)} paint={{ 'raster-opacity': depthOpacity, 'raster-resampling': 'nearest' }} />
        </Source>
        <Source id="population" type="image" url={`${base}population.png`} coordinates={corners}>
          <Layer id="population" type="raster" layout={vis(layers.population)} paint={{ 'raster-opacity': 0.9, 'raster-resampling': 'nearest' }} />
        </Source>
        <Source id="buildings" type="geojson" data={`${base}buildings.geojson`}>
          <Layer
            id="buildings"
            type="circle"
            layout={vis(layers.buildings)}
            paint={{
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 12, 2, 15, 4.5] as never,
              'circle-color': ['interpolate', ['linear'], ['get', 'damage'], 0, '#ffd166', 0.5, '#ef476f', 1, '#7b1e3a'] as never,
              'circle-stroke-color': '#ffffff',
              'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 11, 0, 15, 0.6] as never,
              'circle-opacity': 0.9,
            }}
          />
        </Source>

        {hover && (
          <Popup longitude={hover.lng} latitude={hover.lat} closeButton={false} offset={10} maxWidth="260px">
            {hover.kind === 'ward' ? (
              <>
                <div className="font-medium">{hover.props.ward}</div>
                <div className="mb-1 text-ink-2">{hover.props.district}</div>
                <div className="tabular text-ink-2">
                  {Number(hover.props.people).toLocaleString('en-GB')} people · {Number(hover.props.buildings).toLocaleString('en-GB')} buildings
                  <br />
                  max depth {Number(hover.props.max_depth).toFixed(1)} m
                </div>
              </>
            ) : (
              <>
                <div className="font-medium">Affected building</div>
                <div className="tabular text-ink-2">
                  Flood depth {Number(hover.props.depth).toFixed(2)} m
                  <br />
                  Damage {Math.round(Number(hover.props.damage) * 100)}% of value
                  <br />~{Number(hover.props.pop).toFixed(1)} people
                </div>
              </>
            )}
          </Popup>
        )}
      </Map>

      <div className="absolute bottom-9 left-3 max-w-[260px] rounded-lg border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm">
        {layers.wards && (
          <div className="mb-2">
            <div className="mb-1 font-medium text-ink">{METRICS[metric].label} by ward</div>
            <div className="flex flex-wrap gap-x-2 gap-y-1">
              {legendClasses(metric).map((c) => (
                <span key={c.label} className="flex items-center gap-1 text-ink-2">
                  <span className="inline-block h-3 w-3 rounded-sm border border-line" style={{ background: c.color }} />
                  {c.label}
                </span>
              ))}
            </div>
          </div>
        )}
        {layers.depth && <Legend title="Max flood depth" colors={DEPTH_COLORS} labels={['0.1', '0.5', '1', '2+ m']} />}
        {layers.population && <Legend title="People per ha (flooded)" colors={POP_COLORS} labels={['1', '5', '15', '40+']} />}
        {layers.buildings && (
          <div className="flex items-center gap-1.5 text-ink-2">
            <span className="inline-block h-2 w-8 rounded-full" style={{ background: 'linear-gradient(90deg,#ffd166,#ef476f,#7b1e3a)' }} />
            Building damage 0–100%
          </div>
        )}
      </div>
    </div>
  )
}

function Legend({ title, colors, labels }: { title: string; colors: string[]; labels: string[] }) {
  return (
    <div className="mb-2">
      <div className="font-medium text-ink">{title}</div>
      <div className="flex gap-1">
        {colors.map((c, i) => (
          <div key={c} className="text-center text-ink-3">
            <div className="h-2 w-9 rounded-sm" style={{ background: c }} />
            {labels[i]}
          </div>
        ))}
      </div>
    </div>
  )
}
