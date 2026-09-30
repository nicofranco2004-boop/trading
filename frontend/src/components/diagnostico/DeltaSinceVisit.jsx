import { pctVar } from '../../utils/format'
import { useAlVerse, entrada } from '../../hooks/useAlVerse'
import AnimatedNumber from '../AnimatedNumber'
// DeltaSinceVisit — chips "Desde tu última visita".
// ═══════════════════════════════════════════════════════════════════════════
// Renderiza SOLO el body: el shell (título "Desde tu última visita" + badge con
// sinceLabel) lo pone el padre. Recibe el `delta` de useLastVisit. Primera
// visita o sin datos → null (el padre decide qué mostrar en ese caso).
// El <b> del porcentaje queda en ink-0 (no semántico) para mantenerlo calmo.
//
// Movimiento (2026-09-30): cuando el bloque entra en pantalla, el porcentaje
// cuenta desde 0 —cómo estaba tu cartera la última vez— hasta el cambio de hoy,
// y los chips entran de a uno. Es el movimiento que cuenta literalmente lo que
// pasó mientras no estabas.

function Chip({ dot, children }) {
  return (
    <span className="inline-flex items-center gap-1.5 bg-bg-2 border border-line rounded-full px-3 py-1.5 text-xs text-ink-1">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} aria-hidden="true" />
      {children}
    </span>
  )
}

export default function DeltaSinceVisit({ delta }) {
  // El hook va antes del return de "primera visita" (reglas de los hooks).
  const [ref, visto] = useAlVerse()
  if (!delta || delta.isFirstVisit) return null

  const { valueDeltaPct, newFindingIds = [], resolvedCount = 0 } = delta
  const nNew = newFindingIds.length
  // inline-block: en un <span> común el desplazamiento de la entrada no se
  // aplica (los elementos en línea no se pueden mover con transform).
  const entra = i => entrada(visto, i, 'inline-block')

  return (
    <div ref={ref} className="flex flex-wrap gap-2">
      {valueDeltaPct != null && (
        <span {...entra(0)}>
          <Chip dot="bg-data-violet">
            Tu cartera:{' '}
            <b className="text-ink-0 tabular">
              <AnimatedNumber value={visto ? valueDeltaPct : 0} format={n => pctVar(n, 1)} duration={900} />
            </b>
          </Chip>
        </span>
      )}

      {nNew > 0 && (
        <span {...entra(1)}>
          <Chip dot="bg-data-violet">
            {nNew} {nNew === 1 ? 'hallazgo nuevo' : 'hallazgos nuevos'}
          </Chip>
        </span>
      )}

      {resolvedCount > 0 && (
        <span {...entra(2)}>
          <Chip dot="bg-rendi-pos">
            {resolvedCount} {resolvedCount === 1 ? 'resuelto' : 'resueltos'}
          </Chip>
        </span>
      )}

      {nNew === 0 && resolvedCount === 0 && (
        <span {...entra(1)}>
          <Chip dot="bg-ink-3">Sin cambios en tus hallazgos</Chip>
        </span>
      )}
    </div>
  )
}
