import { ALERT_LEVELS } from '../theme'
import type { AlertLevel } from '../types'

/** Distinct shape per level so the level never relies on colour alone. */
export function AlertIcon({ level, size = 14 }: { level: AlertLevel; size?: number }) {
  const fill = `var(${ALERT_LEVELS[level].cssVar})`
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      {level === 0 && <circle cx="8" cy="8" r="5.5" fill="none" stroke={fill} strokeWidth="2.5" />}
      {level === 1 && <path d="M8 1.5 15 14H1z" fill={fill} />}
      {level === 2 && <path d="M8 1 15 8 8 15 1 8z" fill={fill} />}
      {level === 3 && (
        <>
          <path d="M5 1h6l4 4v6l-4 4H5l-4-4V5z" fill={fill} />
          <path d="M8 4v5M8 11.2v.6" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </>
      )}
    </svg>
  )
}

export function AlertBadge({ level, compact = false }: { level: AlertLevel; compact?: boolean }) {
  const meta = ALERT_LEVELS[level]
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-ink">
      <AlertIcon level={level} />
      <span className={compact ? 'text-sm' : 'text-sm font-medium'}>{compact ? meta.short : meta.label}</span>
    </span>
  )
}
