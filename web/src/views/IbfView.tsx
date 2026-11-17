import { useEffect, useState } from 'react'
import { ForecastImpactView } from '../components/ForecastImpactView'
import { ImpactView } from '../components/ImpactView'

const SUBTABS = [
  { id: 'forecast', label: 'Demo forecast (15 Jan 2024)', hint: 'A past ensemble forecast, impacts for every lead day' },
  { id: 'demo', label: 'Event reconstruction', hint: 'The same flood rebuilt from observed (CHIRPS) rainfall' },
  { id: 'live', label: 'Live', hint: 'Impact of the latest hazard forecast' },
] as const
type SubId = (typeof SUBTABS)[number]['id']

const fromHash = (): SubId =>
  location.hash === '#ibf/live' ? 'live' : location.hash === '#ibf/demo' ? 'demo' : 'forecast'

export default function IbfView() {
  const [sub, setSub] = useState<SubId>(fromHash)

  useEffect(() => {
    const onHash = () => setSub(fromHash())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <div role="tablist" aria-label="Impact-based forecast" className="mx-auto flex max-w-[1400px] gap-2 px-4 pt-4 md:px-6">
        {SUBTABS.map((t) => (
          <a
            key={t.id}
            href={`#ibf/${t.id}`}
            role="tab"
            aria-selected={sub === t.id}
            title={t.hint}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium ${
              sub === t.id ? 'border-accent bg-accent text-white' : 'border-line text-ink-2 hover:text-ink'
            }`}
          >
            {t.label}
          </a>
        ))}
      </div>
      {sub === 'forecast' ? <ForecastImpactView /> : <ImpactView key={sub} mode={sub} />}
    </>
  )
}
