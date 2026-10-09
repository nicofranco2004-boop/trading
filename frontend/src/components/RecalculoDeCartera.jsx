// RecalculoDeCartera — después de anotar un cobro (un dividendo, un cupón de
// bono) o de borrar un movimiento (en Movimientos: un depósito, un dividendo,
// una venta), muestra que el total se recalculó. Lo usan Cartera y Dashboard.
// ════════════════════════════════════════════════════════════════════════════
// Por qué existe (pedido de Nico, 2026-10-09): el total de Cartera ya cuenta y
// destella cuando cambia, pero al confirmar un cobro el usuario está mirando la
// tarjeta, más abajo, y el total queda fuera de la pantalla. Además el total
// destella con cada actualización de precios, así que ese destello no dice
// "entró tu plata". Este aviso sí: aparece arriba, a la vista, en dos tiempos:
//
//   1. "Recalculando tu cartera…" — MIENTRAS el pedido real viaja (la recarga
//      de posiciones y precios que hace la página). Sin pedido, no hay barrido.
//   2. "Tu cartera  US$ 7.969 → US$ 7.972" — el total de ANTES (el que había al
//      confirmar) cuenta hasta el que devolvió el servidor, con el monto cobrado
//      abajo. Los dos números son el total de la página, no una cuenta aparte:
//      si en el medio se movió algún precio, se ve.
//
// Con "reducir movimiento" no cuenta ni barre: muestra el resultado directo.

import { useEffect, useRef, useState } from 'react'
import { Check, X } from 'lucide-react'

const sinMovimiento = () => typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const VISIBLE_MS = 6000

/**
 * @param {Object|null} cobro        { id, texto: 'dividendo de SPY', articulo?: 'el'|'la', monto: '+US$ 2,65', deshecho? }
 *                                   — cada cambio trae id nuevo; `deshecho`: se BORRÓ (un cobro, un depósito,
 *                                   una venta) en vez de sumarse; `monto` entonces va sin signo.
 * @param {boolean}     recalculando la página está recargando posiciones y precios
 * @param {number}      total        el total de Cartera, en la moneda que se está mostrando
 * @param {Function}    formato      cómo se escribe ese total
 * @param {boolean}     oculto       modo privacidad: no se muestran montos
 */
export default function RecalculoDeCartera({ cobro, recalculando, total, formato, oculto = false }) {
  const [fase, setFase] = useState(null)          // null | 'recalculando' | 'listo'
  const [mostrado, setMostrado] = useState(total)
  const antes = useRef(total)
  const ultimoId = useRef(null)
  const ultimoTotal = useRef(total)

  // El total de ANTES es el que había cuando llegó el cobro (la recarga todavía
  // no volvió). Se guarda el último visto en cada dibujo, antes de que cambie.
  useEffect(() => { if (fase !== 'recalculando') ultimoTotal.current = total }, [total, fase])

  useEffect(() => {
    if (!cobro || cobro.id === ultimoId.current) return
    ultimoId.current = cobro.id
    // Un cambio hecho en OTRA pantalla (Movimientos) trae el total que el
    // usuario vio la última vez; uno de esta pantalla, el que hay ahora.
    // Si en esa pantalla no se llegó a ver ningún total, no hay "antes": se
    // muestra sólo el total nuevo, sin inventar de dónde partió.
    const desde = cobro.sinAntes ? null
      : Number.isFinite(cobro.antes) ? cobro.antes : ultimoTotal.current
    antes.current = desde
    setMostrado(desde ?? total)
    setFase('recalculando')
  }, [cobro])

  // Volvió la recarga → pasa a mostrar el resultado. (En un efecto aparte del
  // que cuenta: si fuera el mismo, el cambio de fase lo volvía a correr y la
  // limpieza cancelaba la cuenta recién empezada — el aviso quedaba diciendo
  // "US$ 7.997 → US$ 7.997" con el total ya bajado. Visto en la app 2026-10-09.)
  useEffect(() => {
    if (fase === 'recalculando' && !recalculando) setFase('listo')
  }, [fase, recalculando])

  // Mientras se ve el resultado, el número va hasta el total VIGENTE: si llega
  // otra actualización (los precios), sigue desde donde estaba hasta el nuevo.
  const mostradoRef = useRef(mostrado)
  useEffect(() => { mostradoRef.current = mostrado }, [mostrado])
  useEffect(() => {
    if (fase !== 'listo') return undefined
    const hasta = total
    const desde = Number.isFinite(mostradoRef.current) ? mostradoRef.current : hasta
    if (sinMovimiento() || !Number.isFinite(hasta) || desde === hasta) {
      setMostrado(hasta)
      return undefined
    }
    let raf
    const t0 = performance.now() + 150
    const paso = (ahora) => {
      const p = Math.min(1, Math.max(0, (ahora - t0) / 900))
      setMostrado(desde + (hasta - desde) * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(paso)
    }
    raf = requestAnimationFrame(paso)
    return () => cancelAnimationFrame(raf)
  }, [fase, total])

  useEffect(() => {
    if (fase !== 'listo') return undefined
    const t = setTimeout(() => setFase(null), VISIBLE_MS)
    return () => clearTimeout(t)
  }, [fase])

  if (!fase || !cobro) return null
  const monto = (v) => (oculto ? '••••••' : formato(v))

  return (
    <div className="fixed inset-x-0 top-[calc(var(--alto-barra-celular,80px)_+_8px)] z-[90] flex justify-center px-4 pointer-events-none">
      <div role="status" aria-live="polite"
        className="isla-despliega pointer-events-auto w-full max-w-sm overflow-hidden rounded-xl border border-line-2 bg-bg-1 shadow-lg">
        <div className="flex items-start gap-3 px-4 py-3">
          <span aria-hidden="true"
            className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full ${fase === 'listo' ? 'bg-rendi-pos/15 text-rendi-pos tilde-entra' : 'bg-data-violet/15 text-data-violet'}`}>
            {fase === 'listo'
              ? <Check size={14} strokeWidth={2.5} />
              : <span className="h-2 w-2 rounded-full bg-data-violet animate-pulse motion-reduce:animate-none" />}
          </span>
          <div className="min-w-0 flex-1">
            {fase === 'recalculando' ? (
              <>
                <p className="text-[13.5px] font-semibold text-ink-0">Recalculando tu cartera…</p>
                <p className="text-[12px] text-ink-3">{cobro.deshecho ? 'Sacando' : 'Sumando'} {cobro.articulo || 'el'} {cobro.texto}</p>
              </>
            ) : (
              <>
                <p className="text-[12px] text-ink-3">Tu cartera, {cobro.deshecho ? 'sin' : 'con'} {cobro.articulo || 'el'} {cobro.texto}</p>
                <p className="tabular text-[15px] font-semibold text-ink-0">
                  {antes.current != null && <span className="text-ink-3 font-normal">{monto(antes.current)} → </span>}
                  <span className={`rounded px-0.5 ${!oculto ? 'flash-up' : ''}`}>{monto(mostrado)}</span>
                </p>
                {cobro.monto && (
                  <p className={`tabular text-[12px] ${cobro.deshecho ? 'text-ink-2' : 'text-rendi-pos'}`}>
                    {oculto ? (cobro.deshecho ? 'Borrado' : 'Anotado')
                      : cobro.deshecho ? `Borrado: ${cobro.monto}` : `${cobro.monto} anotado`}
                  </p>
                )}
              </>
            )}
          </div>
          <button type="button" onClick={() => setFase(null)} aria-label="Cerrar"
            className="-mr-1 rounded p-1 text-ink-3 hover:bg-bg-2 hover:text-ink-0">
            <X size={14} />
          </button>
        </div>
        {fase === 'recalculando' && <div className="barrido-escaneo" aria-hidden="true" />}
      </div>
    </div>
  )
}
