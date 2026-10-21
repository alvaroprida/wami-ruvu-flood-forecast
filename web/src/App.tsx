import { useEffect, useState } from 'react'
import { About } from './components/About'
import { AlertIcon } from './components/AlertBadge'
import { AlertTable } from './components/AlertTable'
import { ReachPanel } from './components/ReachPanel'
import { RiverMap } from './components/RiverMap'
import { formatTime, setDailyTimestep } from './format'
import { ALERT_LEVELS } from './theme'
import type { AlertLevel, Basins, Forecast, Network, ReachDetail, Streams } from './types'

const DATA = `${import.meta.env.BASE_URL}data`

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${DATA}/${path}`)
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return res.json()
}

export default function App() {
  const [network, setNetwork] = useState<Network>()
  const [basins, setBasins] = useState<Basins>()
  const [streams, setStreams] = useState<Streams>()
  const [forecast, setForecast] = useState<Forecast>()
  const [details, setDetails] = useState<Record<string, ReachDetail>>({})
  const [selectedId, setSelectedId] = useState<string>()
  const [error, setError] = useState<string>()

  useEffect(() => {
    Promise.all([
      getJSON<Network>('network.geojson'),
      getJSON<Forecast>('latest/forecast.json'),
      getJSON<Basins>('basins.geojson'),
    ])
      .then(([n, f, b]) => {
        setNetwork(n)
        setBasins(b)
        setDailyTimestep(f.timestep_hours >= 24)
        setForecast(f)
        // Open on the most severe reach.
        const top = Object.entries(f.reaches).sort(
          ([, a], [, b]) => b.alert_level - a.alert_level || b.prob_exceed.rp20 - a.prob_exceed.rp20,
        )[0]
        setSelectedId(top[0])
      })
      .catch((e) => setError(String(e)))
  }, [])

  // Background river network: large and not needed for first paint, so loaded separately.
  useEffect(() => {
    getJSON<Streams>('rivers.geojson').then(setStreams).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!selectedId || details[selectedId]) return
    getJSON<ReachDetail>(`latest/reaches/${selectedId}.json`)
      .then((d) => setDetails((prev) => ({ ...prev, [d.id]: d })))
      .catch((e) => setError(String(e)))
  }, [selectedId, details])

  if (error) return <div className="p-8 text-ink">Could not load forecast data: {error}</div>
  if (!network || !basins || !forecast || !selectedId) return <div className="p-8 text-ink-3">Loading…</div>

  const reach = network.features.find((f) => f.properties.id === selectedId)!.properties
  const counts = ([3, 2, 1] as AlertLevel[]).map((l) => ({
    level: l,
    n: Object.values(forecast.reaches).filter((r) => r.alert_level === l).length,
  }))

  return (
    <div className="mx-auto max-w-[1400px] space-y-4 p-4 md:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Wami–Ruvu Flood Forecast</h1>
          <p className="text-sm text-ink-2">
            Ensemble river flow forecasts for two basins in eastern Tanzania · Wflow + ECMWF ENS
          </p>
        </div>
        <div className="text-sm sm:text-right">
          <div className="text-ink-3">Forecast issued</div>
          <div className="font-medium text-ink">{formatTime(forecast.issued)}</div>
        </div>
      </header>

      <div role="note" className="rounded-lg bg-banner px-4 py-2 text-sm text-ink">
        <strong>Experimental research prototype, not an official warning service.</strong>{' '}
        {forecast.mock && 'The forecast shown is synthetic demo data while the model pipeline is being built.'}
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Reaches per alert level">
        {counts.map(({ level, n }) => (
          <div key={level} className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm">
            <AlertIcon level={level} />
            <span className="font-semibold text-ink">{n}</span>
            <span className="text-ink-2">{n === 1 ? 'reach' : 'reaches'} · {ALERT_LEVELS[level].label.toLowerCase()}</span>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:max-h-[860px]">
          <RiverMap network={network} basins={basins} streams={streams} forecast={forecast} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <ReachPanel
          reach={reach}
          summary={forecast.reaches[selectedId]}
          detail={details[selectedId]}
          issued={forecast.issued}
        />
      </div>

      <AlertTable network={network} forecast={forecast} selectedId={selectedId} onSelect={setSelectedId} />
      <About forecast={forecast} />
    </div>
  )
}
