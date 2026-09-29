// MarketTicker — la cinta de cotizaciones de arriba de todo: S&P, Nasdaq,
// Merval, Bitcoin, Ethereum y Oro, cada una con su precio y la variación del
// día con flecha. Va en los DOS shells de App.jsx: adentro de la barra fija del
// celular (MobileTopBar) y arriba del contenido en la compu. Es un solo
// componente para los dos (R6 del contrato de frontend/CLAUDE.md): lo que
// cambia entre uno y otro es el tamaño de letra, por variante `md:`.
//
// Corre de derecha a izquierda, como las cintas de bolsa: los datos entran por
// la derecha. Se frena con el mouse encima (`:hover` de `.ticker-scroll`) o
// con el dedo apoyado.
//
// Cómo da la vuelta sin salto: la pista tiene DOS mitades idénticas y la
// animación la corre exactamente media pista (`ticker-scroll` de index.css, la
// misma que usa la cinta de brokers de la landing). Al terminar, la segunda
// mitad quedó donde arrancó la primera y el reinicio no se ve. Cada mitad
// repite la lista las veces que haga falta para cubrir el ancho visible: en la
// compu la lista sola es más angosta que la ventana, y con una sola copia por
// mitad se vería un hueco vacío antes de volver a empezar.
//
// La velocidad es fija en píxeles por segundo, no en duración: con duración
// fija, una pantalla ancha (más copias por mitad) correría más rápido que un
// celular.
//
// Movimiento reducido (la preferencia de accesibilidad del sistema): no corre.
// Queda UNA copia de la lista que se desliza con el dedo, como la barra de
// antes. Lo resuelve index.css (`.ticker-caja` / `.ticker-copia`), sin JS.

import { useEffect, useRef, useState } from 'react'
import { useMarketIndices, conDato } from '../hooks/useMarketIndices'
import { pctVar, pctVarSign, fmtIndexPrice } from '../utils/format'

const PX_POR_SEGUNDO = 36

// Cuántas copias de la lista necesita cada mitad para no dejar hueco.
export function copiasPorMitad(anchoVisible, anchoLista) {
  if (!(anchoVisible > 0) || !(anchoLista > 0)) return 1
  return Math.max(1, Math.ceil(anchoVisible / anchoLista))
}

function Cotizacion({ it }) {
  const dir = pctVarSign(it.change_pct)
  const tono = dir > 0 ? 'text-rendi-pos' : dir < 0 ? 'text-rendi-neg' : 'text-ink-2'
  return (
    <li className="flex items-center whitespace-nowrap">
      <span aria-hidden="true" className="h-3 w-px bg-line" />
      <span className="flex items-baseline gap-1.5 px-3.5 md:px-4">
        <span className="text-ink-2 font-medium">{it.label}</span>
        <span className="text-ink-0 tabular">{fmtIndexPrice(it.price, it.kind)}</span>
        <span className={`font-semibold tabular ${tono}`}>
          {dir !== 0 && (
            <span aria-hidden="true" className="mr-0.5 text-[0.7em]">{dir > 0 ? '▲' : '▼'}</span>
          )}
          {pctVar(it.change_pct)}
        </span>
      </span>
    </li>
  )
}

export default function MarketTicker({ className = '' }) {
  const { items, loading } = useMarketIndices()
  const lista = conDato(items)
  const cajaRef = useRef(null)
  const copiaRef = useRef(null)
  const [medida, setMedida] = useState({ copias: 1, anchoLista: 0 })
  const [apretado, setApretado] = useState(false)

  useEffect(() => {
    const caja = cajaRef.current
    const copia = copiaRef.current
    if (!caja || !copia) return
    const medir = () => {
      const anchoLista = copia.getBoundingClientRect().width
      const copias = copiasPorMitad(caja.clientWidth, anchoLista)
      setMedida(m => (m.copias === copias && m.anchoLista === anchoLista ? m : { copias, anchoLista }))
    }
    medir()
    if (typeof ResizeObserver === 'undefined') return
    // Observa las dos: la caja cambia con la ventana; la lista, cuando carga la
    // tipografía o llega un precio con más cifras.
    const ro = new ResizeObserver(medir)
    ro.observe(caja)
    ro.observe(copia)
    return () => ro.disconnect()
  }, [lista.length])

  // Mientras llega el primer dato se reserva el alto: si la cinta apareciera de
  // golpe, empujaría todo el contenido para abajo.
  if (lista.length === 0) {
    if (!loading) return null
    return (
      <div aria-hidden="true" className={`h-7 md:h-8 flex items-center gap-6 px-4 overflow-hidden ${className}`}>
        {[0, 1, 2, 3].map(i => <span key={i} className="h-2 w-24 shrink-0 rounded-sm bg-bg-3 animate-pulse" />)}
      </div>
    )
  }

  const duracion = medida.anchoLista > 0
    ? (medida.anchoLista * medida.copias) / PX_POR_SEGUNDO
    : 30
  const total = medida.copias * 2

  return (
    <div
      ref={cajaRef}
      className={`ticker-caja relative h-7 md:h-8 overflow-hidden text-[11px] md:text-[12px] leading-none select-none ${className}`}
      onPointerDown={() => setApretado(true)}
      onPointerUp={() => setApretado(false)}
      onPointerCancel={() => setApretado(false)}
      onPointerLeave={() => setApretado(false)}
    >
      <div
        className="ticker-scroll flex h-full w-max items-center"
        style={{ animationDuration: `${duracion.toFixed(1)}s`, animationPlayState: apretado ? 'paused' : undefined }}
      >
        {Array.from({ length: total }, (_, i) => (
          <ul
            key={i}
            ref={i === 0 ? copiaRef : undefined}
            aria-label={i === 0 ? 'Cotizaciones de mercado' : undefined}
            aria-hidden={i > 0 ? 'true' : undefined}
            className="ticker-copia flex shrink-0 items-center"
          >
            {lista.map(it => <Cotizacion key={it.symbol} it={it} />)}
          </ul>
        ))}
      </div>
      {/* Los bordes se desvanecen: la cinta entra y sale en vez de cortarse. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 w-6 md:w-12 bg-gradient-to-r from-bg-0 to-transparent" />
      <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 w-6 md:w-12 bg-gradient-to-l from-bg-0 to-transparent" />
    </div>
  )
}
