// ocultarSaldos.js — cómo se ve un monto con «Ocultar saldos» prendido (el
// ojito de la Cartera, contexts/PrivacyContext.jsx). Vive en utils para que lo
// usen también las funciones que arman textos sin depender de React.

// Lo que va en lugar del monto. Uno solo para toda la app.
export const OCULTO = '••••••'
// La frase que lo explica, cuando un texto se queda sin su número. Una sola
// manera de decirlo (auditoría D, 29/10: había tres).
export const AVISO_OCULTO = 'Oculto porque tenés prendido «Ocultar saldos».'

// Un texto que arma el SERVIDOR con montos adentro («Aportaste US$ 2.000 este
// período», «la inflación le sacó ~US$ 84»): con el ojito prendido se tapa el
// monto y queda la frase. Sólo lo que lleva moneda adelante (US$, USD, ARS, $):
// los % y las cantidades no son plata y se ven, como en la Cartera.
const MONTO_EN_TEXTO = /[~+−-]?(?:US\$|U\$S|USD|ARS|\$)\s?[~+−-]?\d[\d.,]*\d|[~+−-]?(?:US\$|U\$S|USD|ARS|\$)\s?[~+−-]?\d/g
export function taparMontos(texto) {
  return typeof texto === 'string' ? texto.replace(MONTO_EN_TEXTO, OCULTO) : texto
}

/** `taparMontos` en cada texto de un objeto del servidor (una tarjeta, un período). */
export function taparMontosEnTodo(v) {
  if (typeof v === 'string') return taparMontos(v)
  if (Array.isArray(v)) return v.map(taparMontosEnTodo)
  if (v && typeof v === 'object') {
    const out = {}
    for (const [k, x] of Object.entries(v)) out[k] = taparMontosEnTodo(x)
    return out
  }
  return v
}
