// Bajar la plantilla de un formato de importación (GET /api/imports/template).
//
// Un solo lugar para las dos puertas que la ofrecen: el paso de subida del
// importador (ImportWizard, cualquier formato que tenga plantilla) y la
// bienvenida obligatoria, que a quien elige «Otro / mi broker no está» le da la
// planilla de Rendi ahí mismo, sin esperar a que abra el importador.
// Tira si el servidor no la da: cada pantalla decide cómo lo cuenta.

import { pedirAlServidor } from './api'

/** La planilla de Rendi: el formato propio, para un broker que Rendi no lee. */
export const PLANILLA_DE_RENDI = 'rendi_generic'

export async function descargarPlantilla(format = PLANILLA_DE_RENDI) {
  const res = await pedirAlServidor(`/imports/template?format=${encodeURIComponent(format)}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  // El nombre es lo que la persona ve en Descargas: la planilla propia se llama
  // como se la nombra en pantalla, no «rendi_template_rendi_generic».
  a.download = format === PLANILLA_DE_RENDI ? 'planilla-de-rendi.csv' : `rendi_template_${format}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
