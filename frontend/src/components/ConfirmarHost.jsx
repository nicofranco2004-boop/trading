// ConfirmarHost — dibuja el "¿Seguro?" de Rendi (ver utils/confirmar.js). Se
// monta UNA vez, en main.jsx; cualquier pantalla lo abre con `await confirmar(…)`.
//
// Un cartel a la vez: si llega otra pregunta con una abierta, la nueva se
// contesta "no" (un doble click no apila dos carteles ni acepta por la persona).
// Enter acepta —el foco arranca en el botón de aceptar, como en el cartel del
// navegador— y Escape o tocar afuera cancelan. Al cerrarse, el foco vuelve a
// donde estaba.
//
// Superficie de la generación nueva: `rounded-xl`, colores del tema. El mismo
// cartel en compu y en celular (R6: no se bifurca por pantalla).

import { useEffect, useRef, useState } from 'react'
import { registrarConfirmar } from '../utils/confirmar'

export default function ConfirmarHost() {
  const [pedido, setPedido] = useState(null)   // { titulo, detalle, opciones }
  const resolver = useRef(null)
  const botonSi = useRef(null)
  const focoAntes = useRef(null)

  useEffect(() => registrarConfirmar((texto, opciones) => new Promise((resolve) => {
    if (resolver.current) { resolve(false); return }
    const corte = texto.indexOf('\n\n')
    resolver.current = resolve
    focoAntes.current = typeof document !== 'undefined' ? document.activeElement : null
    setPedido({
      titulo: corte >= 0 ? texto.slice(0, corte) : texto,
      detalle: corte >= 0 ? texto.slice(corte + 2) : '',
      opciones: opciones || {},
    })
  })), [])

  // Si el cartel se desmonta con una pregunta abierta, se contesta "no".
  useEffect(() => () => { resolver.current?.(false); resolver.current = null }, [])

  function responder(si) {
    const r = resolver.current
    resolver.current = null
    setPedido(null)
    r?.(si)
    try { focoAntes.current?.focus?.() } catch { /* el elemento ya no está */ }
  }

  useEffect(() => {
    if (!pedido) return undefined
    botonSi.current?.focus?.()
    const alTeclear = (e) => { if (e.key === 'Escape') { e.preventDefault(); responder(false) } }
    document.addEventListener('keydown', alTeclear)
    return () => document.removeEventListener('keydown', alTeclear)
  }, [pedido])

  if (!pedido) return null
  const { titulo, detalle, opciones } = pedido
  return (
    <div
      className="fixed inset-0 z-[150] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onMouseDown={(e) => { if (e.target === e.currentTarget) responder(false) }}
    >
      <div
        role="alertdialog" aria-modal="true" aria-labelledby="confirmar-titulo"
        aria-describedby={detalle ? 'confirmar-detalle' : undefined}
        className="entra w-full max-w-md bg-bg-raised border border-line rounded-xl shadow-2xl p-5"
      >
        <h2 id="confirmar-titulo" className="text-[15px] font-semibold text-ink-0 leading-snug whitespace-pre-line">{titulo}</h2>
        {detalle && (
          <p id="confirmar-detalle" className="mt-2.5 text-[13px] text-ink-2 leading-relaxed whitespace-pre-line max-h-[50vh] overflow-y-auto">{detalle}</p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={() => responder(false)}
            className="px-3.5 py-2 text-[13px] font-medium rounded-lg bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition-colors">
            {opciones.no || 'Cancelar'}
          </button>
          <button type="button" ref={botonSi} onClick={() => responder(true)}
            className={`px-3.5 py-2 text-[13px] font-medium rounded-lg text-white transition-colors ${
              opciones.peligro ? 'bg-rendi-neg hover:bg-rendi-neg/90' : 'bg-data-violet hover:bg-data-violet/90'}`}>
            {opciones.si || 'Confirmar'}
          </button>
        </div>
      </div>
    </div>
  )
}
