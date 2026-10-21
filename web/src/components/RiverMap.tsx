import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useMemo, useState } from 'react'
import Map, { Layer, Popup, Source, type MapLayerMouseEvent } from 'react-map-gl/maplibre'

// MapLibre 6 ships its worker as a separate module that Vite won't find on its own.
setWorkerUrl(workerUrl)
import { formatPct, formatQ } from '../format'
import { ALERT_LEVELS, levelColor, usePalette } from '../theme'
import type { AlertLevel, Basins, Forecast, Network, Streams } from '../types'
import { AlertBadge, AlertIcon } from './AlertBadge'

const BASEMAP = {
  light: 'https://tiles.openfreemap.org/styles/positron',
  dark: 'https://tiles.openfreemap.org/styles/dark',
}

// HydroBASINS extent of the two basins.
const BOUNDS: [[number, number], [number, number]] = [
  [35.6, -7.8],
  [39.0, -5.05],
]

interface Props {
  network: Network
  basins: Basins
  streams?: Streams
  forecast: Forecast
  selectedId: string
  onSelect: (id: string) => void
}

export function RiverMap({ network, basins, streams, forecast, selectedId, onSelect }: Props) {
  const { palette, dark } = usePalette()
  const [hover, setHover] = useState<{ id: string; lng: number; lat: number } | null>(null)

  // Join the forecast summary onto the network so the layers can style by level.
  const { rivers, outlets } = useMemo(() => {
    const rivers = {
      ...network,
      features: network.features.map((f) => ({
        ...f,
        properties: { ...f.properties, level: forecast.reaches[f.properties.id].alert_level },
      })),
    }
    const outlets = {
      type: 'FeatureCollection' as const,
      features: rivers.features.map((f) => ({
        type: 'Feature' as const,
        properties: f.properties,
        geometry: { type: 'Point' as const, coordinates: f.properties.outlet },
      })),
    }
    return { rivers, outlets }
  }, [network, forecast])

  const levelExpr = [
    'match',
    ['get', 'level'],
    ...([0, 1, 2, 3] as AlertLevel[]).flatMap((l) => [l, levelColor(palette, l)]),
    palette.river,
  ] as unknown as string
  const widthExpr = [
    'interpolate', ['linear'], ['get', 'upstream_area_km2'],
    1000, 2, 20000, 3.5, 45000, 5,
  ] as unknown as number

  const onMove = (e: MapLayerMouseEvent) => {
    const f = e.features?.[0]
    setHover(f ? { id: f.properties.id, lng: e.lngLat.lng, lat: e.lngLat.lat } : null)
  }

  const hovered = hover && network.features.find((f) => f.properties.id === hover.id)?.properties
  const hoveredSummary = hover && forecast.reaches[hover.id]

  return (
    <div className="relative h-full min-h-[420px] overflow-hidden rounded-xl border border-line">
      <Map
        initialViewState={{ bounds: BOUNDS, fitBoundsOptions: { padding: 24 } }}
        mapStyle={dark ? BASEMAP.dark : BASEMAP.light}
        interactiveLayerIds={['river-hit', 'outlets']}
        cursor={hover ? 'pointer' : 'grab'}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => {
          const id = e.features?.[0]?.properties.id
          if (id) onSelect(id)
        }}
        attributionControl={{ compact: true, customAttribution: 'Rivers: derived from FABDEM · Basins: HydroSHEDS' }}
      >
        {/* Basins stay neutral so the alert colours on the rivers carry the signal. */}
        <Source id="basins" type="geojson" data={basins}>
          <Layer
            id="basin-fill"
            type="fill"
            filter={['==', ['get', 'kind'], 'basin']}
            paint={{ 'fill-color': palette['text-primary'], 'fill-opacity': 0.05 }}
          />
          <Layer
            id="subbasin-line"
            type="line"
            filter={['==', ['get', 'kind'], 'subbasin']}
            paint={{ 'line-color': palette['text-muted'], 'line-width': 0.6, 'line-opacity': 0.6 }}
          />
          <Layer
            id="basin-line"
            type="line"
            filter={['==', ['get', 'kind'], 'basin']}
            layout={{ 'line-join': 'round' }}
            paint={{ 'line-color': palette['text-secondary'], 'line-width': 1.5 }}
          />
        </Source>
        {streams && (
          <Source id="streams" type="geojson" data={streams}>
            <Layer
              id="streams"
              type="line"
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              paint={{
                'line-color': palette.river,
                'line-opacity': 0.55,
                'line-width': ['interpolate', ['linear'], ['get', 'uparea'], 100, 0.5, 2000, 1.2, 40000, 2.2] as unknown as number,
              }}
            />
          </Source>
        )}
        <Source id="rivers" type="geojson" data={rivers}>
          <Layer
            id="river-selected"
            type="line"
            filter={['==', ['get', 'id'], selectedId]}
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{ 'line-color': palette['series-1'], 'line-width': ['+', widthExpr, 10] as unknown as number, 'line-opacity': 0.25, 'line-blur': 2 }}
          />
          <Layer
            id="river-casing"
            type="line"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{ 'line-color': palette.surface, 'line-width': ['+', widthExpr, 2] as unknown as number }}
          />
          <Layer
            id="river"
            type="line"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{ 'line-color': levelExpr, 'line-width': widthExpr }}
          />
          {/* Wide invisible line: hit target bigger than the mark. */}
          <Layer id="river-hit" type="line" paint={{ 'line-color': '#000', 'line-opacity': 0, 'line-width': 14 }} />
        </Source>
        <Source id="outlets" type="geojson" data={outlets}>
          <Layer
            id="outlets"
            type="circle"
            paint={{
              'circle-radius': ['case', ['==', ['get', 'id'], selectedId], 7, 5] as unknown as number,
              'circle-color': levelExpr,
              'circle-stroke-color': palette.surface,
              'circle-stroke-width': 2,
            }}
          />
        </Source>

        {/* Labels drawn above the rivers so they are never hidden under a reach. */}
        <Source id="basin-labels" type="geojson" data={basins}>
          <Layer
            id="basin-label"
            type="symbol"
            filter={['==', ['get', 'kind'], 'label']}
            layout={{
              'text-field': ['concat', ['upcase', ['get', 'basin']], ' BASIN'],
              'text-font': ['Noto Sans Bold'],
              'text-size': 12,
              'text-letter-spacing': 0.15,
              'text-variable-anchor': ['center', 'top', 'bottom'],
            }}
            paint={{
              'text-color': palette['text-secondary'],
              'text-halo-color': palette.surface,
              'text-halo-width': 1.5,
            }}
          />
        </Source>

        {hover && hovered && hoveredSummary && (
          <Popup longitude={hover.lng} latitude={hover.lat} closeButton={false} offset={12} maxWidth="260px">
            <div className="font-medium">{hovered.name}</div>
            <div className="mb-1 text-ink-2">{hovered.basin} basin</div>
            <AlertBadge level={hoveredSummary.alert_level} />
            <div className="tabular mt-1 text-ink-2">
              Peak (median) {formatQ(hoveredSummary.peak_q50)} m³/s
              <br />
              P(&gt;5-yr) {formatPct(hoveredSummary.prob_exceed.rp5)}
            </div>
          </Popup>
        )}
      </Map>

      <div className="absolute bottom-9 left-3 hidden rounded-lg sm:block border border-line bg-surface/95 px-3 py-2 text-xs shadow-sm">
        <div className="mb-1 font-medium text-ink">Forecast exceedance</div>
        {([3, 2, 1, 0] as AlertLevel[]).map((l) => (
          <div key={l} className="flex items-center gap-1.5 py-0.5 text-ink-2">
            <AlertIcon level={l} size={12} />
            {ALERT_LEVELS[l].label}
          </div>
        ))}
        <div className="mt-1.5 border-t border-line pt-1.5">
          <div className="flex items-center gap-1.5 py-0.5 text-ink-2">
            <span className="inline-block h-0 w-3 border-t-[1.5px] border-[var(--text-secondary)]" />
            Basin boundary
          </div>
          <div className="flex items-center gap-1.5 py-0.5 text-ink-2">
            <span className="inline-block h-0 w-3 border-t border-[var(--text-muted)] opacity-60" />
            Sub-basin (HydroBASINS)
          </div>
          <div className="flex items-center gap-1.5 py-0.5 text-ink-2">
            <span className="inline-block h-0 w-3 border-t border-[var(--river)] opacity-70" />
            Model river network
          </div>
        </div>
      </div>
    </div>
  )
}
