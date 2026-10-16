import { useEffect, useState } from 'react'
import type { AlertLevel } from './types'

// Alert levels use the reserved status palette and always ship with an
// icon + label (see AlertBadge), never colour alone.
export const ALERT_LEVELS: Record<AlertLevel, { label: string; short: string; cssVar: string }> = {
  0: { label: 'Below 2-year flow', short: 'None', cssVar: '--river' },
  1: { label: '2-year flow likely', short: '2-yr', cssVar: '--status-warning' },
  2: { label: '5-year flow likely', short: '5-yr', cssVar: '--status-serious' },
  3: { label: '20-year flow likely', short: '20-yr', cssVar: '--status-critical' },
}

const ROLES = [
  'surface',
  'text-primary',
  'text-secondary',
  'text-muted',
  'grid',
  'axis',
  'series-1',
  'river',
  'history',
  'status-warning',
  'status-serious',
  'status-critical',
] as const

export type Palette = Record<(typeof ROLES)[number], string>

function readPalette(): Palette {
  const css = getComputedStyle(document.documentElement)
  return Object.fromEntries(ROLES.map((r) => [r, css.getPropertyValue(`--${r}`).trim()])) as Palette
}

const darkQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

/** Resolved colour roles, re-read when the OS switches light/dark. */
export function usePalette(): { palette: Palette; dark: boolean } {
  const [state, setState] = useState(() => ({ palette: readPalette(), dark: darkQuery().matches }))
  useEffect(() => {
    const mq = darkQuery()
    const update = () => setState({ palette: readPalette(), dark: mq.matches })
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [])
  return state
}

export function levelColor(palette: Palette, level: AlertLevel): string {
  return palette[ALERT_LEVELS[level].cssVar.slice(2) as keyof Palette]
}
