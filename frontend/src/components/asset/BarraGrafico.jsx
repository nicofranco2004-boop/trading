// BarraGrafico — la barra de herramientas del gráfico técnico y la lista de
// indicadores, como en TradingView.
// ════════════════════════════════════════════════════════════════════════════
// Dos lugares, cada uno con lo suyo (Nico, 28/10: «quedó demasiado cargada la
// barra lateral… ponelo como aparece en TradingView»):
//   · BarraGrafico, al costado: las herramientas de ANÁLISIS — líneas de
//     tendencia y horizontales, Fibonacci y Elliott (UN botón cada uno, con un
//     menú: el automático o marcarlo a mano), medir y borrar tus dibujos.
//   · LeyendaIndicadores, arriba a la izquierda del gráfico: los INDICADORES
//     (volumen, promedios, RSI, fuerza de la tendencia, balances, lo tuyo), cada
//     uno con su ojito para mostrarlo u ocultarlo.
// Línea o velas van arriba a la derecha, con los otros selectores de la ficha.
//
// De fábrica, una VISTA LIMPIA (Nico, 29/10, en lugar del «todo prendido» del
// 24/10): el precio, el promedio de 200 días y el volumen; el resto a un toque
// desde «Indicadores» y los menús de Fibonacci y Elliott. Lo que cada uno prende
// o apaga se guarda en el navegador (`rendi_grafico_capas`, como el tipo de
// gráfico en `rendi_grafico_tipo`); «Volver a lo de fábrica» lo olvida.
//
// Una sola barra para compu y celular (R6): en compu va parada, pegada a la
// izquierda del gráfico, con el ícono solo y el nombre al pasar el mouse; en el
// celular es la MISMA fila acostada arriba del gráfico, que se desliza de costado,
// con botones de 44 × 44 px y también sólo el ícono (Nico, 29/10: con el nombre
// al lado era un renglón más antes del gráfico). El nombre queda para el lector
// de pantalla y, en los que abren un menú, como título del menú.
// El menú de Fibonacci y Elliott se abre al lado del botón (o debajo, si al lado
// no entra) y por encima de todo: adentro de la fila que se desliza quedaría cortado.
//
// Algo sin datos para este activo (sin volumen, sin conteo de Elliott, sin
// compras tuyas) no se esconde: queda gris y, al tocarlo, dice por qué.

import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { borrar as borrarDelAlmacen, guardar as guardarEnAlmacen, leer as leerDelAlmacen } from '../../utils/almacen'
import { CATALOGO } from '../../utils/catalogoDelAlmacen'

const CLAVE = 'rendi_grafico_capas'

/** Cómo viene el gráfico: la vista limpia (precio, promedio de 200 y volumen). */
export const CAPAS_DE_FABRICA = Object.freeze({
  vol: true, s200: true, s50: false, bb: false, fib: false, ell: false, rsi: false, fuerza: false,
  eventos: false, marcas: false, prom: false,
  globo: true,   // el cartel con los datos del día al pasar el mouse: no ensucia, aparece al pasar
})

/** Todo prendido: lo que las pruebas del gráfico dejan guardado para ver todas las capas. */
export const CAPAS_TODAS = Object.freeze(Object.fromEntries(Object.keys(CAPAS_DE_FABRICA).map(k => [k, true])))

/**
 * Lo que la persona dejó prendido y apagado la última vez. Lo que no está
 * guardado (nunca lo tocó, o es una capa nueva) viene de fábrica. El navegador
 * puede tener el almacenamiento bloqueado (modo privado) o un valor roto: de
 * fábrica.
 */
export function capasGuardadas() {
  const capas = { ...CAPAS_DE_FABRICA }
  try {
    const g = JSON.parse(leerDelAlmacen(CATALOGO.graficoCapas) || 'null')
    if (g && typeof g === 'object') {
      for (const k of Object.keys(capas)) if (typeof g[k] === 'boolean') capas[k] = g[k]
    }
  } catch { /* sin almacenamiento o valor roto: de fábrica */ }
  return capas
}

export function guardarCapas(capas) {
  try { guardarEnAlmacen(CATALOGO.graficoCapas, JSON.stringify(capas)) } catch { /* sin almacenamiento */ }
}

export function olvidarCapas() {
  try { borrarDelAlmacen(CATALOGO.graficoCapas) } catch { /* sin almacenamiento */ }
}

export const sonDeFabrica = (capas) => Object.keys(CAPAS_DE_FABRICA).every(k => capas[k] === CAPAS_DE_FABRICA[k])

/**
 * `grupos`: listas de botones, separadas por una rayita. Cada botón:
 *   { id, nombre, icono, onClick,
 *     activo     — prendido (true) / apagado (false); undefined = no es un
 *                  interruptor (hace algo), se ve neutro,
 *     herramienta — se prende para usarla (medir, dibujar): apagada se ve como
 *                  un botón común,
 *     menu       — en vez de onClick, las opciones que abre (Fibonacci y
 *                  Elliott: automático o a mano): [{ id, nombre, detalle,
 *                  activo, interruptor, sinDatos, onClick }],
 *     estado     — el texto del globo,
 *     sinDatos   — por qué no se puede usar en este activo (deshabilitado) }
 * `onAviso(texto)`: al tocar algo sin datos, la explicación (en el celular no
 * hay globo al pasar el mouse); null al tocar cualquier otra cosa.
 */
export default function BarraGrafico({ grupos, onAviso }) {
  return (
    <div role="toolbar" aria-label="Herramientas del gráfico" data-tour="grafico-herramientas"
      className="flex sm:flex-col gap-1.5 sm:gap-1 -mx-3 px-3 sm:mx-0 sm:px-0 pb-1.5 sm:pb-0 overflow-x-auto sm:overflow-visible shrink-0 sm:self-start">
      {grupos.filter(g => g.length).map((g, k) => (
        <div key={k} className={`flex sm:flex-col gap-1.5 sm:gap-1 shrink-0 ${k > 0 ? 'border-l sm:border-l-0 sm:border-t border-line/70 pl-1.5 sm:pl-0 sm:pt-1' : ''}`}>
          {g.map(b => (b.menu ? <BotonConMenu key={b.id} b={b} onAviso={onAviso} /> : <Boton key={b.id} b={b} onAviso={onAviso} />))}
        </div>
      ))}
    </div>
  )
}

function Boton({ b, onAviso, refBoton, abierto }) {
  const interruptor = typeof b.activo === 'boolean'
  const estado = b.sinDatos || b.estado || ''
  const clase = b.sinDatos
    ? 'border-dashed border-line text-ink-3 opacity-55 cursor-not-allowed'
    : b.activo ? 'border-rendi-accent/55 bg-rendi-accent/15 text-ink-0 hover:border-rendi-accent'
      : 'border-line-2 bg-bg-2 text-ink-1 hover:text-ink-0 hover:border-ink-3'
  return (
    <button type="button" data-capa={b.id} ref={refBoton}
      aria-pressed={interruptor && !b.sinDatos && !b.menu ? b.activo : undefined}
      aria-haspopup={b.menu ? 'menu' : undefined} aria-expanded={b.menu ? !!abierto : undefined}
      aria-disabled={b.sinDatos ? true : undefined}
      onClick={() => {
        if (b.sinDatos) { onAviso?.(`${b.nombre}: ${b.sinDatos}`); return }
        onAviso?.(null)
        b.onClick()
      }}
      className={`group relative shrink-0 inline-flex items-center justify-center h-11 w-11 sm:h-9 sm:w-9 rounded-lg border text-[12.5px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-rendi-accent ${clase}`}>
      <span aria-hidden="true" className={`relative inline-flex items-center justify-center w-5 h-5 ${b.sinDatos ? 'opacity-45 grayscale' : ''}`}>
        {b.icono}
      </span>
      <span className="sr-only">{b.nombre}</span>
      {/* La marquita de «tiene opciones» en la esquina (como TradingView). */}
      {b.menu && <span aria-hidden="true" className="absolute right-0.5 bottom-0.5 w-0 h-0 border-l-4 border-l-transparent border-b-4 border-b-ink-3" />}
      {b.sinDatos && <span className="sr-only">{`: ${b.sinDatos}`}</span>}
      {/* El globo con el nombre, al pasar el mouse o con el foco (sólo compu). */}
      {!abierto && (
        <span aria-hidden="true"
          className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 z-30 hidden sm:group-hover:block sm:group-focus-visible:block w-max max-w-[16rem] rounded border border-line-2 bg-bg-raised px-2 py-1 text-left text-[11.5px] leading-snug shadow-sm">
          <span className="block font-semibold text-ink-0">{b.nombre}</span>
          {estado && <span className="block text-ink-2">{estado}</span>}
        </span>
      )}
    </button>
  )
}

// Un botón que abre sus opciones (Fibonacci y Elliott: automático o a mano).
function BotonConMenu({ b, onAviso }) {
  const [lugar, setLugar] = useState(null)       // null = cerrado; si no, dónde va el menú
  const boton = useRef(null)
  const menu = useRef(null)
  useEffect(() => {
    if (!lugar) return
    const fuera = (e) => {
      if (menu.current?.contains?.(e.target) || boton.current?.contains?.(e.target)) return
      setLugar(null)
    }
    const tecla = (e) => { if (e.key === 'Escape') setLugar(null) }
    // Va fijo en la pantalla: si se desliza la página o la fila de botones, se
    // cierra (si no, quedaría flotando lejos de su botón).
    const cerrar = () => setLugar(null)
    window.addEventListener('pointerdown', fuera)
    window.addEventListener('keydown', tecla)
    window.addEventListener('scroll', cerrar, true)
    window.addEventListener('resize', cerrar)
    return () => {
      window.removeEventListener('pointerdown', fuera); window.removeEventListener('keydown', tecla)
      window.removeEventListener('scroll', cerrar, true); window.removeEventListener('resize', cerrar)
    }
  }, [lugar])
  const abrir = () => {
    if (lugar) { setLugar(null); return }
    const r = boton.current?.getBoundingClientRect?.() || { left: 0, right: 0, top: 0, bottom: 0 }
    const ancho = 256
    const vw = typeof window !== 'undefined' ? window.innerWidth || 1024 : 1024
    // Al lado del botón si entra (la barra parada de la compu); si no, debajo
    // (la fila del celular), sin salirse de la pantalla.
    setLugar(vw - r.right > ancho + 16
      ? { left: r.right + 8, top: r.top }
      : { left: Math.max(8, Math.min(r.left, vw - ancho - 8)), top: r.bottom + 6 })
  }
  return (
    <>
      <Boton b={{ ...b, onClick: abrir }} onAviso={onAviso} refBoton={boton} abierto={!!lugar} />
      {lugar && (
        <div ref={menu} role="menu" aria-label={b.nombre}
          className="fixed z-[60] w-64 rounded-lg border border-line-2 bg-bg-raised p-1 shadow-lg"
          style={{ left: lugar.left, top: lugar.top }}>
          <div className="px-2.5 pt-1.5 pb-1 text-[12px] font-semibold text-ink-0">{b.nombre}</div>
          {b.menu.map(o => (
            <button key={o.id} type="button" data-capa={o.id}
              role={o.interruptor ? 'menuitemcheckbox' : 'menuitem'}
              aria-checked={o.interruptor && !o.sinDatos ? !!o.activo : undefined}
              aria-disabled={o.sinDatos ? true : undefined}
              onClick={() => {
                setLugar(null)
                if (o.sinDatos) { onAviso?.(`${b.nombre} (${o.nombre.toLowerCase()}): ${o.sinDatos}`); return }
                onAviso?.(null)
                o.onClick()
              }}
              className={`w-full flex items-start gap-2 rounded px-2.5 py-2 min-h-11 sm:min-h-0 text-left hover:bg-bg-2 ${o.sinDatos ? 'opacity-55 cursor-not-allowed' : ''}`}>
              <span aria-hidden="true" className={`mt-0.5 inline-flex items-center justify-center w-4 h-4 rounded border text-[10px] font-bold ${o.activo && !o.sinDatos ? 'border-rendi-accent bg-rendi-accent text-bg-0' : 'border-line-2 text-transparent'}`}>✓</span>
              <span className="min-w-0">
                <span className="block text-[12.5px] text-ink-0">{o.nombre}</span>
                <span className="block text-[11.5px] text-ink-2 leading-snug">{o.sinDatos || o.detalle}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}

const CLAVE_LEYENDA = 'rendi_grafico_leyenda'
// Lo que la persona eligió la última vez: true (abierta), false (plegada) o
// null (nunca la tocó).
function leyendaGuardada() {
  try {
    const g = leerDelAlmacen(CATALOGO.graficoLeyenda)
    if (g === 'abierta' || g === 'cerrada') return g === 'abierta'
  } catch { /* sin almacenamiento */ }
  return null
}
// Sin elección guardada, se abre si el GRÁFICO (no la pantalla) es ancho: en uno
// angosto, como el del celular, la lista abierta taparía medio gráfico.
export const ANCHO_PARA_LEYENDA_ABIERTA = 420

/**
 * La lista de indicadores, arriba a la izquierda del gráfico, como en
 * TradingView: cada uno con su muestra de color, su nombre y un ojito para
 * mostrarlo u ocultarlo. Se pliega a un solo renglón («Indicadores · 6 de 8»)
 * y se acuerda de cómo la dejaste. `items`: { id, nombre, icono, activo,
 * sinDatos, onClick }; al pie, «Volver a lo de fábrica». `anchoDisponible`: el
 * ancho del gráfico en píxeles (lo pasa el gráfico, que lo mide).
 * `plegada`: hay una herramienta de dibujar o de medir prendida. Abierta, la
 * lista tapa la franja izquierda del gráfico (en la compu, 9 renglones = dos
 * tercios del alto) y ahí no se podía dibujar ni medir (auditoría D, 29/10):
 * mientras dure la herramienta se pliega sola, sin guardarlo como elección, y
 * con el botón se puede abrir igual.
 */
export function LeyendaIndicadores({ items, onAviso, deFabrica, onFabrica, anchoDisponible = 1000, plegada = false }) {
  const [elegida, setElegida] = useState(leyendaGuardada)
  const [abiertaIgual, setAbiertaIgual] = useState(false)
  useEffect(() => { setAbiertaIgual(false) }, [plegada])
  const abierta = plegada ? abiertaIgual : (elegida ?? anchoDisponible >= ANCHO_PARA_LEYENDA_ABIERTA)
  const setAbierta = (x) => {
    if (plegada) { setAbiertaIgual(x); return }
    setElegida(x); try { guardarEnAlmacen(CATALOGO.graficoLeyenda, x ? 'abierta' : 'cerrada') } catch { /* sin almacenamiento */ }
  }
  const usables = items.filter(i => !i.sinDatos)
  const prendidos = usables.filter(i => i.activo).length
  return (
    // `w-max`: del ancho de la lista, no del gráfico. Como bloque ocupaba todo
    // el ancho de arriba del gráfico (invisible) y se comía los clicks: no se
    // podía elegir el Fibonacci automático ni arrastrar una línea hacia arriba
    // (Nico, 29/10). Y por si la caja vuelve a crecer: los clicks los toma sólo
    // lo que se ve (el botón y la lista), nunca la caja que los envuelve.
    <div className="w-max max-w-[calc(100%-8px)] text-[11.5px] pointer-events-none" role="group" aria-label="Indicadores">
      <button type="button" onClick={() => setAbierta(!abierta)} aria-expanded={abierta}
        className="pointer-events-auto inline-flex items-center gap-1 min-h-8 sm:min-h-6 px-2 rounded border border-line/60 bg-bg-1/85 text-ink-1 hover:text-ink-0">
        Indicadores <span className="tabular text-ink-2">· {prendidos} de {usables.length}</span>
        <ChevronDown size={13} aria-hidden="true" className={`transition-transform ${abierta ? 'rotate-180' : ''}`} />
      </button>
      {abierta && (
        <ul className="pointer-events-auto mt-1 w-max max-w-full rounded-lg border border-line/60 bg-bg-1/85 p-0.5">
          {items.map(i => {
            const ve = i.activo && !i.sinDatos
            return (
              <li key={i.id} className="flex items-center gap-1.5 pl-1.5">
                <span aria-hidden="true" className={`inline-flex items-center justify-center w-4 h-4 ${ve ? '' : 'opacity-40 grayscale'}`}>{i.icono}</span>
                <span className={`flex-1 whitespace-nowrap ${ve ? 'text-ink-1' : 'text-ink-3'}`}>{i.nombre}</span>
                <button type="button" data-capa={i.id}
                  aria-pressed={i.sinDatos ? undefined : !!i.activo} aria-disabled={i.sinDatos ? true : undefined}
                  title={i.sinDatos || (i.activo ? 'Ocultar' : 'Mostrar')}
                  onClick={() => {
                    if (i.sinDatos) { onAviso?.(`${i.nombre}: ${i.sinDatos}`); return }
                    onAviso?.(null)
                    i.onClick()
                  }}
                  className={`inline-flex items-center justify-center w-9 h-9 sm:w-7 sm:h-7 rounded ${i.sinDatos ? 'text-ink-3 opacity-50 cursor-not-allowed' : ve ? 'text-ink-1 hover:text-ink-0 hover:bg-bg-2' : 'text-ink-3 hover:text-ink-1 hover:bg-bg-2'}`}>
                  {ve ? <Eye size={15} aria-hidden="true" /> : <EyeOff size={15} aria-hidden="true" />}
                  <span className="sr-only">{i.sinDatos ? `${i.nombre}: ${i.sinDatos}` : `${i.activo ? 'Ocultar' : 'Mostrar'} ${i.nombre}`}</span>
                </button>
              </li>
            )
          })}
          <li className="border-t border-line/60 mt-0.5 pt-0.5">
            <button type="button" data-capa="fabrica" onClick={onFabrica} disabled={deFabrica}
              title={deFabrica ? 'El gráfico ya está como al principio: todo visible y en línea' : 'Vuelve a mostrar todo y pasa el gráfico a línea'}
              className="w-full inline-flex items-center gap-1.5 min-h-9 sm:min-h-7 px-1.5 rounded text-ink-2 enabled:hover:text-ink-0 enabled:hover:bg-bg-2 disabled:opacity-50">
              <RotateCcw size={13} aria-hidden="true" />Volver a lo de fábrica
            </button>
          </li>
        </ul>
      )}
    </div>
  )
}
