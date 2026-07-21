// Time-range selector matching modern broker / fintech apps.
// Used in Dashboard portfolio evolution chart.

export const RANGES = [
  { id: '1D', label: '1D', days: 1 },
  { id: '1W', label: '1S', days: 7 },
  { id: '1M', label: '1M', days: 30 },
  { id: '6M', label: '6M', days: 180 },
  { id: '1Y', label: '1A', days: 365 },
  { id: 'MAX', label: 'MAX', days: null },
]

export default function RangeTabs({ value, onChange, ranges = RANGES, size = 'md' }) {
  const padY = size === 'sm' ? 'py-1' : 'py-1.5'
  const padX = size === 'sm' ? 'px-2.5' : 'px-3'
  const text = size === 'sm' ? 'text-[11px]' : 'text-xs'
  return (
    <div className="inline-flex bg-bg-2 dark:bg-bg-2/60 p-0.5 rounded-full">
      {ranges.map(r => {
        const active = value === r.id
        return (
          <button
            key={r.id}
            onClick={() => onChange(r.id)}
            className={`${padX} ${padY} ${text} rounded-full font-semibold tracking-wide transition-colors ${
              active
                ? 'bg-white dark:bg-bg-2 text-ink-0 shadow-sm'
                : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
            }`}
          >
            {r.label}
          </button>
        )
      })}
    </div>
  )
}
