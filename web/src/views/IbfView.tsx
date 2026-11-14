import { useEffect, useState } from 'react'
import { ImpactView } from '../components/ImpactView'

const SUBTABS = [
  { id: 'demo', label: 'Demo event', hint: 'A past flood run through the whole impact chain' },
  { id: 'live', label: 'Live', hint: 'Impact of the latest hazard forecast' },
] as const
type SubId = (typeof SUBTABS)[number]['id']

const fromHash = (): SubId => (location.hash === '#ibf/live' ? 'live' : 'demo')

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
      <ImpactView key={sub} mode={sub} />
    </>
  )
}
