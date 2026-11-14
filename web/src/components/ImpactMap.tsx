import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useState } from 'react'
import Map, { Layer, Popup, Source, type MapLayerMouseEvent } from 'react-map-gl/maplibre'
import { usePalette } from '../theme'

setWorkerUrl(workerUrl)

const BASEMAP = {
  light: 'https://tiles.openfreemap.org/styles/positron',
  dark: 'https://tiles.openfreemap.org/styles/dark',
}

export const DEPTH_COLORS = ['#a6cee3', '#4292c6', '#2166ac', '#08306b']
export const POP_COLORS = ['#fed976', '#fd8d3c', '#e31a1c', '#800026']

export interface ImpactLayers {
  depth: boolean
  population: boolean
  buildings: boolean
}

type Corners = [[number, number], [number, number], [number, number], [number, number]]

interface Props {
  bbox: [number, number, number, number]
  base: string // URL of the scenario directory, with trailing slash
  corners: Corners
  layers: ImpactLayers
}

interface Hover {
  lng: number
  lat: number
  depth: number
  damage: number
  pop: number
}

export function ImpactMap({ bbox, base, corners, layers }: Props) {
  const { dark } = usePalette()
  const [hover, setHover] = useState<Hover | null>(null)
  const onMove = (e: MapLayerMouseEvent) => {
    const f = e.features?.[0]
    setHover(f ? { lng: e.lngLat.lng, lat: e.lngLat.lat, depth: f.properties.depth, damage: f.properties.damage, pop: f.properties.pop } : null)
  }
  const vis = (on: boolean) => ({ visibility: on ? ('visible' as const) : ('none' as const) })
  return (
    <div className="relative h-full min-h-[460px] overflow-hidden rounded-xl border border-line">
      <Map
        key={base}
        initialViewState={{ bounds: [[bbox[0], bbox[1]], [bbox[2], bbox[3]]], fitBoundsOptions: { padding: 16 } }}
        mapStyle={dark ? BASEMAP.dark : BASEMAP.light}
        interactiveLayerIds={['buildings']}
        cursor={hover ? 'pointer' : 'grab'}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        attributionControl={{ compact: true, customAttribution: 'Flood model: SFINCS · Buildings: Overture Maps · Population: WorldPop' }}
      >
        <Source id="depth" type="image" url={`${base}depth.png`} coordinates={corners}>
          <Layer id="depth" type="raster" layout={vis(layers.depth)} paint={{ 'raster-opacity': 0.85, 'raster-resampling': 'nearest' }} />
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
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 12, 2, 15, 4] as unknown as number,
              'circle-color': ['interpolate', ['linear'], ['get', 'damage'], 0, '#ffd166', 0.5, '#ef476f', 1, '#7b1e3a'] as unknown as string,
              'circle-opacity': 0.85,
            }}
          />
        </Source>
        {hover && (
          <Popup longitude={hover.lng} latitude={hover.lat} closeButton={false} offset={10} maxWidth="240px">
            <div className="font-medium">Affected building</div>
            <div className="tabular text-ink-2">
              Flood depth {Number(hover.depth).toFixed(2)} m
              <br />
              Damage {Math.round(Number(hover.damage) * 100)}% of value
              <br />~{Number(hover.pop).toFixed(1)} people
            </div>
          </Popup>
        )}
      </Map>

      <div className="absolute bottom-9 left-3 hidden rounded-lg border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm sm:block">
        <Legend title="Max flood depth" colors={DEPTH_COLORS} labels={['0.1', '0.5', '1', '2+ m']} />
        <Legend title="People in flooded area" colors={POP_COLORS} labels={['1', '5', '15', '40+ /ha']} />
        <div className="mt-1 flex items-center gap-1.5 text-ink-2">
          <span className="inline-block h-2 w-8 rounded-full" style={{ background: 'linear-gradient(90deg,#ffd166,#ef476f,#7b1e3a)' }} />
          Building damage (0–100%)
        </div>
      </div>
    </div>
  )
}

function Legend({ title, colors, labels }: { title: string; colors: string[]; labels: string[] }) {
  return (
    <div className="mb-1.5">
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
