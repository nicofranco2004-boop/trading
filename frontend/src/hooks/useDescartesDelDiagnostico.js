// useDescartesDelDiagnostico — el «No me interesa» de las tarjetas del
// Diagnóstico (Análisis), guardado en el navegador. Dos cosas:
//   (1) `dismissed`: el Set de ids que la persona marcó (la lista de las que no
//       se vuelven a ofrecer al elegir reemplazos);
//   (2) `slots`: las ids VISIBLES por grupo, en orden — así al descartar UNA
//       tarjeta se reemplaza sólo ESA y en un refresh se ven las mismas.
//
// DE QUIÉN ES: de la persona Y de la cuenta (utils/duenoDeLaPestana), y lo pone
// el hook. Antes la clave era sólo del email: el asesor que descartaba una
// tarjeta en el cliente 2 dejaba de verla en el 3 (re-test a ciegas, 30/10).
// Sin nadie logueado vive en memoria y no se guarda.
//
//   const [state, setState, guardar] = useDescartesDelDiagnostico()
//   state = { dismissed: Set, slots: { [grupo]: [ids] } }
//   guardar(dismissed, slots) → lo escribe para el dueño de ahora

import { useState } from 'react'
import { useDuenoDeLaPestana } from '../utils/duenoDeLaPestana'

const PREFIJO = 'rendi_diag_dismissed_diag:'
const VACIO = () => ({ dismissed: new Set(), slots: {} })

function leer(dueno) {
  if (!dueno) return VACIO()
  try {
    const raw = localStorage.getItem(PREFIJO + dueno)
    if (!raw) return VACIO()
    const parsed = JSON.parse(raw)
    // Formato viejo: array plano de ids descartadas (sin slots).
    if (Array.isArray(parsed)) return { dismissed: new Set(parsed), slots: {} }
    return { dismissed: new Set(parsed.dismissed || []), slots: parsed.slots || {} }
  } catch { return VACIO() }
}

function escribir(dueno, dismissed, slots) {
  if (!dueno) return
  try {
    localStorage.setItem(PREFIJO + dueno, JSON.stringify({ dismissed: [...dismissed], slots }))
  } catch { /* modo privado */ }
}

export function useDescartesDelDiagnostico() {
  const dueno = useDuenoDeLaPestana()
  // Por dueño: si el asesor cambia de cliente con la pantalla abierta, se leen
  // los del cliente nuevo en vez de seguir con los del anterior.
  const [porDueno, setPorDueno] = useState({})
  const state = porDueno[dueno] ?? leer(dueno)
  const setState = (f) => setPorDueno(x => {
    const antes = x[dueno] ?? leer(dueno)
    return { ...x, [dueno]: typeof f === 'function' ? f(antes) : f }
  })
  const guardar = (dismissed, slots) => escribir(dueno, dismissed, slots)
  return [state, setState, guardar]
}
