// DeltaSinceVisit — chips "Desde tu última visita".
// ═══════════════════════════════════════════════════════════════════════════
// Renderiza SOLO el body: el shell (título "Desde tu última visita" + badge con
// sinceLabel) lo pone el padre. Recibe el `delta` de useLastVisit. Primera
// visita o sin datos → null (el padre decide qué mostrar en ese caso).
// El <b> del porcentaje queda en ink-0 (no semántico) para mantenerlo calmo.

function Chip({ dot, children }) {
  return (
    <span className="inline-flex items-center gap-1.5 bg-bg-2 border border-line rounded-full px-3 py-1.5 text-xs text-ink-1">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} aria-hidden="true" />
      {children}
    </span>
  )
}

export default function DeltaSinceVisit({ delta }) {
  if (!delta || delta.isFirstVisit) return null

  const { valueDeltaPct, newFindingIds = [], resolvedCount = 0 } = delta
  const nNew = newFindingIds.length

  return (
    <div className="flex flex-wrap gap-2">
      {valueDeltaPct != null && (
        <Chip dot="bg-data-violet">
          Tu cartera:{' '}
          <b className="text-ink-0 tabular-nums">
            {valueDeltaPct > 0 ? '+' : ''}{valueDeltaPct}%
          </b>
        </Chip>
      )}

      {nNew > 0 && (
        <Chip dot="bg-data-violet">
          {nNew} {nNew === 1 ? 'hallazgo nuevo' : 'hallazgos nuevos'}
        </Chip>
      )}

      {resolvedCount > 0 && (
        <Chip dot="bg-rendi-pos">
          {resolvedCount} {resolvedCount === 1 ? 'resuelto' : 'resueltos'}
        </Chip>
      )}

      {nNew === 0 && resolvedCount === 0 && (
        <Chip dot="bg-ink-3">Sin cambios en tus hallazgos</Chip>
      )}
    </div>
  )
}
