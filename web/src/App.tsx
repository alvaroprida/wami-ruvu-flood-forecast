import { lazy, Suspense, useEffect, useState } from 'react'
import FewsView from './views/FewsView'

const IbfView = lazy(() => import('./views/IbfView'))

const TABS = [
  { id: 'fews', label: 'FEWS', hint: 'Hazard forecast and discharge alerts' },
  { id: 'ibf', label: 'IbF', hint: 'Impact-based forecast' },
] as const
type TabId = (typeof TABS)[number]['id']

const fromHash = (): TabId => (location.hash === '#ibf' ? 'ibf' : 'fews')

export default function App() {
  const [tab, setTab] = useState<TabId>(fromHash)

  useEffect(() => {
    const onHash = () => setTab(fromHash())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  return (
    <>
      <nav className="border-b border-line bg-surface" aria-label="Sections">
        <div role="tablist" className="mx-auto flex max-w-[1400px] gap-1 px-4 md:px-6">
          {TABS.map((t) => (
            <a
              key={t.id}
              href={`#${t.id}`}
              role="tab"
              aria-selected={tab === t.id}
              title={t.hint}
              className={`border-b-2 px-4 py-2.5 text-sm font-medium ${
                tab === t.id ? 'border-accent text-ink' : 'border-transparent text-ink-3 hover:text-ink'
              }`}
            >
              {t.label}
            </a>
          ))}
        </div>
      </nav>
      {tab === 'fews' ? (
        <FewsView />
      ) : (
        <Suspense fallback={<div className="p-8 text-ink-3">Loading…</div>}>
          <IbfView />
        </Suspense>
      )}
    </>
  )
}
