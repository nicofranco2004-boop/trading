// useLastVisit — "¿qué cambió desde tu última visita?" por user.
// ═══════════════════════════════════════════════════════════════════════════
// Persiste una huella (valor de cartera + ids de hallazgos) en localStorage y,
// al volver, computa el delta contra lo guardado la vez anterior.
//
// Contrato pensado para las Rules of Hooks: el hook se llama SIEMPRE arriba del
// componente (antes de cualquier early-return, sin snapshot). Cuando la data
// está lista, el render llama `record(snapshot)` — función común, NO un hook —
// que devuelve el `delta` contra la visita previa y AGENDA la persistencia
// (nunca escribe durante el render). Así trackeamos valor + hallazgos sin
// depender de que el snapshot exista antes del guard de loading.
//
//   const lastVisit = useLastVisit('diagnostico')                    // arriba
//   const { delta } = lastVisit.record({ valueUsd, findingIds })     // en el render
//
// DE QUIÉN ES: de la persona Y de la cuenta (utils/duenoDeLaPestana), y lo pone
// el hook, no quien lo llama. Antes la clave la armaba la pantalla con el email:
// el asesor que miraba el cliente 2 y después el 3 veía el «cambió X % desde tu
// última visita» del 3 calculado contra la cartera del 2 (re-test a ciegas,
// 30/10). Sin nadie logueado no se guarda ni se lee nada.
//
// delta = { isFirstVisit } en la primera visita; si no:
//   { isFirstVisit:false, valueDeltaPct, newFindingIds, resolvedCount, sinceLabel }
//
// ROBUSTEZ: todo localStorage en try/catch (tira en modo privado). Nunca throw.

import { useEffect, useRef } from 'react'
import { useDuenoDeLaPestana } from '../utils/duenoDeLaPestana'

const LS_PREFIX = 'rendi_lastvisit_'

function readStored(key) {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

// sinceLabel — Date es válido acá: código de app en el browser (no un script
// de workflow). Usa Date.now() y el ts guardado.
function elapsedLabel(ts) {
  if (!ts || typeof ts !== 'number') return null
  const days = Math.floor((Date.now() - ts) / 86400000)
  if (days <= 0) return 'hoy'
  if (days === 1) return 'ayer'
  if (days < 7) return `hace ${days} días`
  const weeks = Math.floor(days / 7)
  if (weeks === 1) return 'hace 1 semana'
  if (weeks < 5) return `hace ${weeks} semanas`
  const months = Math.floor(days / 30)
  return months <= 1 ? 'hace 1 mes' : `hace ${months} meses`
}

export function useLastVisit(seccion) {
  const dueno = useDuenoDeLaPestana()
  const key = dueno ? `${seccion}:${dueno}` : null
  // La visita anterior se lee UNA sola vez por dueño (al montar, o cuando el
  // asesor cambia de cliente). No cambia dentro de la sesión: queremos comparar
  // contra lo de la última vez, no contra lo que acabamos de escribir.
  const previas = useRef({})
  if (key && !(key in previas.current)) previas.current[key] = readStored(key)
  const prev = key ? previas.current[key] : null
  const pendingRef = useRef(null)   // snapshot a persistir después del render
  const writtenRef = useRef(null)   // huella ya persistida (evita reescribir por render)
  const keyRef = useRef(key)
  keyRef.current = key

  useEffect(() => {
    const snap = pendingRef.current
    if (!snap || !keyRef.current) return
    // Solo persistimos cuando la huella real cambió — el effect corre en cada
    // commit y InsightsDesktop re-renderiza seguido; sin esto escribiríamos
    // localStorage en cada render (idempotente pero desperdiciado).
    const fp = keyRef.current + '|' + Math.round(snap.valueUsd || 0) + '|' +
      [...(snap.findingIds || [])].sort().join(',')
    if (writtenRef.current === fp) return
    writtenRef.current = fp
    try {
      localStorage.setItem(
        LS_PREFIX + keyRef.current,
        JSON.stringify({ ...snap, ts: Date.now() }),
      )
    } catch {
      /* modo privado / storage lleno → ignoramos, no rompemos la vista */
    }
  })

  function record(snapshot) {
    if (!snapshot || snapshot.valueUsd == null) return { delta: null }
    const findingIds = Array.isArray(snapshot.findingIds) ? snapshot.findingIds : []
    // Agendamos persistir el estado actual (el effect lo escribe post-render).
    pendingRef.current = { valueUsd: Number(snapshot.valueUsd) || 0, findingIds }

    if (!prev) return { delta: { isFirstVisit: true } }

    const prevVal = Number(prev.valueUsd)
    const valueDeltaPct = prevVal > 0
      ? Math.round(((pendingRef.current.valueUsd - prevVal) / prevVal) * 1000) / 10
      : null
    const prevIds = new Set(Array.isArray(prev.findingIds) ? prev.findingIds : [])
    const currIds = new Set(findingIds)
    const newFindingIds = [...currIds].filter((id) => !prevIds.has(id))
    const resolvedCount = [...prevIds].filter((id) => !currIds.has(id)).length

    return {
      delta: {
        isFirstVisit: false,
        valueDeltaPct,
        newFindingIds,
        resolvedCount,
        sinceLabel: elapsedLabel(prev.ts),
      },
    }
  }

  return { record }
}
