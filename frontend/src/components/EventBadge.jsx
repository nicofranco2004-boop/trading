// EventBadge — badge tipo Delta para clasificar visualmente un evento.
// ════════════════════════════════════════════════════════════════════════════
// Color según categoría del evento:
//   🟣 EARNINGS  → purple
//   🔵 DIVIDENDO → blue
//   🟠 BONO      → amber
//   🟢 ECONÓMICO → green (macro events, futuro)
//   ⚪ otro      → gray
//
// Inspirado en Delta (eToro). Uppercase + tracking-wide + border sutil para
// que sea legible sin saturar visualmente.

import { eventCategoryColor, eventCategoryLabel } from '../utils/upcomingEvents'

// Mapping color → clases Tailwind. Definidas explícitamente para que el
// purge de Tailwind no las borre (no podemos usar template strings dinámicos).
const COLOR_CLASSES = {
  purple: 'bg-purple-500/15 text-purple-500 dark:text-purple-400 border-purple-500/40',
  blue:   'bg-blue-500/15 text-blue-500 dark:text-blue-400 border-blue-500/40',
  amber:  'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/40',
  green:  'bg-rendi-pos/15 text-rendi-pos border-rendi-pos/40',
  gray:   'bg-bg-3 text-ink-2 border-line',
}

export default function EventBadge({ eventType, size = 'sm' }) {
  const color = eventCategoryColor(eventType)
  const label = eventCategoryLabel(eventType)
  const classes = COLOR_CLASSES[color] || COLOR_CLASSES.gray
  const sizeClasses = size === 'lg'
    ? 'text-[10px] px-2 py-0.5'
    : 'text-[9px] px-1.5 py-0.5'
  return (
    <span className={`tracking-[0.12em] rounded-sm border inline-flex items-center gap-1 ${sizeClasses} ${classes} font-medium`}>
      {label}
    </span>
  )
}
