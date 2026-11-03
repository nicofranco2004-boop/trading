// useDescartesDelDiagnostico — el «No me interesa» de las tarjetas del
// Diagnóstico (Análisis), guardado en el navegador. Dos cosas:
//   (1) `dismissed`: el Set de ids que la persona marcó (la lista de las que no
//       se vuelven a ofrecer al elegir reemplazos);
//   (2) `slots`: las ids VISIBLES por grupo, en orden — así al descartar UNA
//       tarjeta se reemplaza sólo ESA y en un refresh se ven las mismas.
//
// DE QUIÉN ES: de la persona Y de la cuenta DE LOS DATOS (las tarjetas a la
// vista): useDuenoDeLosDatos, el dueño de cuando se montó la pantalla. Antes la
// clave era sólo del email: el asesor que descartaba una tarjeta en el cliente 2
// dejaba de verla en el 3 (re-test a ciegas, 30/10). Si la pestaña cambia de
// dueño con la pantalla abierta, las tarjetas a la vista siguen siendo del
// anterior: se siguen mostrando sus descartes y uno nuevo no se guarda (la
// puerta, utils/almacen.guardarDe, no guarda para un dueño que ya no es el de
// la pestaña). Sin nadie logueado vive en memoria y no se guarda.
//
//   const [state, setState, guardar] = useDescartesDelDiagnostico()
//   state = { dismissed: Set, slots: { [grupo]: [ids] } }
//   guardar(dismissed, slots) → lo escribe para el dueño de los datos

import { useState } from 'react'
import { useDuenoDeLosDatos } from '../utils/duenoDeLaPestana'
import { leerDe, guardarDe } from '../utils/almacen'
import { CATALOGO } from '../utils/catalogoDelAlmacen'

const VACIO = () => ({ dismissed: new Set(), slots: {} })

function leer(dueno) {
  if (!dueno) return VACIO()
  try {
    const raw = leerDe(CATALOGO.descartesDiagnostico, dueno)
    if (!raw) return VACIO()
    const parsed = JSON.parse(raw)
    // Formato viejo: array plano de ids descartadas (sin slots).
    if (Array.isArray(parsed)) return { dismissed: new Set(parsed), slots: {} }
    return { dismissed: new Set(parsed.dismissed || []), slots: parsed.slots || {} }
  } catch { return VACIO() }
}

function escribir(dueno, dismissed, slots) {
  try {
    guardarDe(CATALOGO.descartesDiagnostico, dueno, JSON.stringify({ dismissed: [...dismissed], slots }))
  } catch { /* modo privado */ }
}

export function useDescartesDelDiagnostico() {
  const dueno = useDuenoDeLosDatos()
  const [state, setState] = useState(() => leer(dueno))
  const guardar = (dismissed, slots) => escribir(dueno, dismissed, slots)
  return [state, setState, guardar]
}
