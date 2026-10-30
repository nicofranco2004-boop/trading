// TarjetasPorTema — las tarjetas del análisis técnico, debajo del gráfico.
// ════════════════════════════════════════════════════════════════════════════
// En la ficha del activo van en cinco pestañas (lienzo «3a · Ficha en línea»):
// Tendencia · Impulso y fuerza · Niveles · Tu posición (sólo si lo tenés) ·
// Cuánto se mueve. Cada pestaña lleva un puntito de color: verde si sus
// tarjetas dicen «a favor de la suba», rojo «en contra», gris neutro y
// amarillo para «Cuánto se mueve», que mide el tamaño y no la dirección
// (utils/lecturaDeHoy.js). La pestaña elegida se recuerda en este navegador.
// Los paneles están todos en la página y se ocultan los que no se eligieron:
// cambiar de pestaña no vuelve a armar nada (ni los «Avisame»).
//
// Las tarjetas son las de siempre, con su texto y su «Avisame»; las de
// Bollinger, Fibonacci y Elliott aparecen sólo con su capa prendida en el
// gráfico. Largo y mediano plazo suman un dibujito con el precio contra su
// promedio de los últimos meses (y el día en que lo cruzó); el máximo del año,
// una regla del mínimo al máximo con dónde está hoy.
//
// En la pestaña «Gráfico» de Análisis técnico (`enPestanas` false) van como
// antes: todas en una grilla y «Cuánto se mueve» abajo.
//
// Ocultar saldos (el ojito): «En tu cartera» no dice la plata ni qué parte de
// tu cartera es, y «Contra lo que pagaste» no dice cuánto ganás o perdés.

import { useState } from 'react'
import { BotonAvisame, senalDeTarjeta } from '../alerts/AvisameTecnico'
import { TarjetaFibonacci } from './CapaFibonacci'
import { TarjetaElliott } from './CapaElliott'
import { usePrivacy } from '../../contexts/PrivacyContext'
import { tarjetaBandas } from '../../utils/tecnico'
import { tarjetasMovimiento } from '../../utils/cuantoSeMueve'
import {
  TEMAS, guardarTema, lugarEnElAnio, miniPromedio, temaDe, temaGuardado, tonoDelTema, trazo, ultimoCruce,
} from '../../utils/lecturaDeHoy'

const v = (t) => `rgb(var(--${t}))`
const OCULTO = '••••••'
const PUNTO = { pos: 'bg-rendi-pos', neg: 'bg-rendi-neg', neutro: 'bg-ink-3', aviso: 'bg-rendi-warn' }

/** «Contra lo que pagaste»: en dólares, el MISMO resultado de arriba de la
 *  ficha; en pesos, el de lo que pagaste en pesos. null si no lo tenés. */
function tarjetaTuya(r, { moneda, lineaSinTc, oculto }) {
  if (r == null) return null
  return {
    id: 'tuyo', titulo: 'Contra lo que pagaste', tono: oculto ? 'neutro' : r >= 0 ? 'pos' : 'neg',
    veredicto: oculto ? OCULTO
      : `${r >= 0 ? 'Ganás' : 'Perdés'} ${Math.abs(r * 100).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`,
    texto: moneda === 'usd'
      ? (lineaSinTc
        ? 'Es el mismo resultado de arriba. La línea de tu precio promedio no se dibuja porque a alguna compra le falta el dólar de ese día.'
        : 'Es el mismo resultado de arriba. La línea punteada es tu precio promedio, con el dólar del día de cada compra.')
      : 'Lo que vale hoy contra lo que pagaste, todo en pesos.',
  }
}

export default function TarjetasPorTema({
  enPestanas = true, Tarjeta, lista = [], lectura, puntos = [], ver = {}, fibonacci = null, elliott = null,
  moneda, precio, fecha, avisos, asset, accionLocal, resultado = null, lineaSinTc = false,
  movimiento, tenencia = null, peso = null, periodo = '', colores = {},
}) {
  const { hidden } = usePrivacy()
  const cuanto = tarjetasMovimiento(movimiento, { moneda, precio, tenencia, peso: hidden ? null : peso })
    .map(t => (t.id === 'cartera' && hidden ? { ...t, veredicto: OCULTO } : t))
  const tuya = tarjetaTuya(resultado, { moneda, lineaSinTc, oculto: hidden })
  const bandas = ver.bb ? tarjetaBandas(lectura) : null

  // Una tarjeta de tecnico.js con su «Avisame» (si tiene señal) y su dibujito.
  const conAvisame = (t) => {
    const s = senalDeTarjeta(t.id, lectura)
    const dibujo = !enPestanas ? null
      : t.id === 'fondo' ? <MiniPromedio puntos={puntos} clave="s200" color={colores.media200} tono={t.tono} fecha={fecha} />
        : t.id === 'corto' ? <MiniPromedio puntos={puntos} clave="s50" color={colores.media50} tono={t.tono} fecha={fecha} />
          : t.id === 'maximo' ? <ReglaDelAnio lectura={lectura} precio={precio} />
            : null
    return (
      <Tarjeta key={t.id} t={t} dibujo={dibujo} pie={s && (
        <BotonAvisame avisos={avisos} asset={asset} accionLocal={accionLocal} moneda={moneda} {...s} />
      )} />
    )
  }
  const fib = ver.fib && fibonacci ? <TarjetaFibonacci key="fibonacci" fib={fibonacci} precio={precio} fecha={fecha} /> : null
  const ell = ver.ell && elliott ? <TarjetaElliott key="elliott" elliott={elliott} precio={precio} fecha={fecha} /> : null
  const cuantoSeccion = cuanto.length > 0 && (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 mb-2">
        <h3 className="text-[14px] font-semibold text-ink-0">Cuánto se mueve este papel</h3>
        <span className="text-[12px] text-ink-2">{periodo}, en {moneda === 'usd' ? 'dólares' : 'pesos'}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
        {cuanto.map(t => <Tarjeta key={t.id} t={t} />)}
      </div>
      <p className="text-[11.5px] text-ink-2 mt-2 leading-relaxed">
        Es lo que pasó, de cierre a cierre: no dice cuánto se va a mover de acá en adelante.
      </p>
    </>
  )

  if (!enPestanas) {
    return (
      <>
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
          {fib}
          {ell}
          {bandas && <Tarjeta t={bandas} />}
          {lista.map(conAvisame)}
          {tuya && <Tarjeta t={tuya} />}
        </div>
        {cuantoSeccion && <section aria-label="Cuánto se mueve este papel" className="mt-5">{cuantoSeccion}</section>}
      </>
    )
  }

  return <EnPestanas lista={lista} bandas={bandas} fib={fib} ell={ell} tuya={tuya} cuanto={cuanto}
    conAvisame={conAvisame} Tarjeta={Tarjeta} cuantoSeccion={cuantoSeccion} />
}

function EnPestanas({ lista, bandas, fib, ell, tuya, cuanto, conAvisame, Tarjeta, cuantoSeccion }) {
  const deTema = (id) => lista.filter(t => temaDe(t.id) === id)
  const temas = TEMAS.map(tema => {
    if (tema.id === 'niveles') return { ...tema, tarjetas: [bandas].filter(Boolean), extra: [fib, ell].filter(Boolean) }
    if (tema.id === 'tuyo') return { ...tema, tarjetas: tuya ? [tuya] : [] }
    if (tema.id === 'movimiento') return { ...tema, tarjetas: [...deTema('movimiento'), ...cuanto] }
    return { ...tema, tarjetas: deTema(tema.id) }
  }).filter(t => t.id === 'niveles' || t.tarjetas.length)
  const [elegido, setElegido] = useState(temaGuardado)
  const activo = temas.some(t => t.id === elegido) ? elegido : temas[0]?.id
  const elegir = (id) => { setElegido(id); guardarTema(id) }
  // Con las flechas del teclado se pasa de una pestaña a la otra.
  const teclas = (e, k) => {
    const paso = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!paso) return
    e.preventDefault()
    const sig = temas[(k + paso + temas.length) % temas.length]
    elegir(sig.id)
    e.currentTarget.parentElement?.querySelector(`#tema-tecnico-${sig.id}`)?.focus()
  }

  return (
    <section aria-label="Qué mirar del gráfico" className="mt-4 border-t border-line/60">
      <div role="tablist" aria-label="Qué mirar del gráfico" className="-mx-1 flex overflow-x-auto scrollbar-none border-b border-line/60">
        {temas.map((tema, k) => {
          const si = tema.id === activo
          return (
            <button key={tema.id} id={`tema-tecnico-${tema.id}`} type="button" role="tab" aria-selected={si}
              aria-controls={`panel-tecnico-${tema.id}`} tabIndex={si ? 0 : -1}
              onClick={() => elegir(tema.id)} onKeyDown={(e) => teclas(e, k)}
              className={`-mb-px inline-flex min-h-11 flex-none items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-[13.5px] transition-colors ${si ? 'border-rendi-accent font-semibold text-ink-0' : 'border-transparent font-medium text-ink-2 hover:text-ink-0'}`}>
              <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${PUNTO[tonoDelTema(tema.id, tema.tarjetas)]}`} />
              {tema.nombre}
            </button>
          )
        })}
      </div>
      {temas.map(tema => (
        <div key={tema.id} id={`panel-tecnico-${tema.id}`} role="tabpanel" aria-labelledby={`tema-tecnico-${tema.id}`}
          hidden={tema.id !== activo} className="pt-3">
          {tema.id === 'movimiento' ? (
            <>
              {deTemaMovimiento(tema.tarjetas).length > 0 && (
                <div className="mb-3 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                  {deTemaMovimiento(tema.tarjetas).map(conAvisame)}
                </div>
              )}
              {cuantoSeccion}
            </>
          ) : tema.id === 'niveles' ? (
            tema.tarjetas.length || tema.extra.length ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                {tema.extra}
                {tema.tarjetas.map(t => <Tarjeta key={t.id} t={t} />)}
              </div>
            ) : (
              <p className="text-[13px] text-ink-1 leading-relaxed">
                No hay ningún nivel prendido en el gráfico. Las Bandas de Bollinger se prenden desde «Indicadores», arriba a la
                izquierda del gráfico; el Fibonacci y las Ondas de Elliott, desde la barra de herramientas del costado.
              </p>
            )
          ) : tema.id === 'tuyo' ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
              {tema.tarjetas.map(t => <Tarjeta key={t.id} t={t} />)}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
              {tema.tarjetas.map(conAvisame)}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}

// La «Cuánto se mueve» de tecnico.js va arriba, con su «Avisame»; las de
// cuantoSeMueve, en su sección de siempre.
const deTemaMovimiento = (tarjetas) => tarjetas.filter(t => t.id === 'movimiento')

// El precio (del color de la tarjeta) contra su promedio (punteado, del color
// de esa línea en el gráfico) en los últimos ~6 meses, con un círculo el día en
// que lo cruzó si fue en ese tramo.
function MiniPromedio({ puntos, clave, color, tono, fecha }) {
  const m = miniPromedio(puntos, clave)
  if (!m) return null
  const c = m.cruce ? ultimoCruce(puntos, clave) : null
  return (
    <div className="mt-2">
      <svg viewBox="0 0 300 54" width="100%" height="54" preserveAspectRatio="none" aria-hidden="true" className="block overflow-visible">
        <path d={trazo(m.promedio)} fill="none" stroke={color} strokeWidth="1.6" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        <path d={trazo(m.precio)} fill="none" stroke={v(tono === 'neg' ? 'rendi-neg' : tono === 'pos' ? 'rendi-pos' : 'ink-1')} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {m.cruce && <circle cx={m.cruce[0]} cy={m.cruce[1]} r="5" fill="none" stroke={v('ink-0')} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />}
      </svg>
      <div className="mt-1 text-[11.5px] text-ink-2 tabular">
        Últimos 6 meses · punteado, el promedio{c ? ` · el círculo, el ${fecha(c.fecha)}, cuando lo cruzó hacia ${c.arriba ? 'arriba' : 'abajo'}` : ''}
      </div>
    </div>
  )
}

// Del mínimo al máximo de los últimos 12 meses (de cierre, los del servidor),
// con dónde está hoy el precio.
function ReglaDelAnio({ lectura, precio }) {
  const lugar = lugarEnElAnio(lectura)
  if (lugar == null) return null
  const pct = `${(lugar * 100).toFixed(1)}%`
  return (
    <div className="mt-2.5 mb-0.5" aria-hidden="true">
      <div className="relative h-2 rounded-full bg-bg-3">
        <span className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-rendi-accent/20 to-rendi-accent" style={{ width: pct }} />
        <span className="absolute -top-1 h-4 w-3 rounded bg-ink-0" style={{ left: `calc(${pct} - 6px)` }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-ink-2 tabular">
        <span>mínimo {precio(lectura.minimo_12m)}</span><span>máximo {precio(lectura.maximo_12m)}</span>
      </div>
    </div>
  )
}
