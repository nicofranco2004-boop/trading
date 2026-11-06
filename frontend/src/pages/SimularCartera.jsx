// SimularCartera — «Una cartera», el segundo modo de la pestaña «Backtesting» de
// Análisis técnico (?tab=backtesting&modo=cartera).
// ═══════════════════════════════════════════════════════════════════════════
// Nico, 05/11/2026; boceto aprobado (opción A, dentro de Backtesting):
// https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5.
// Arrancás con tu cartera de hoy o de cero y ponés cada activo y cuánto de la
// cartera va en él (sobre 100); la barra de abajo de la tabla se llena mientras
// escribís. Con 100 % repartido se ve qué habría pasado con US$ 100 comprados así
// el primer día y sin tocar, al lado del S&P 500 y del Nasdaq, de 1 a 5 años.
//
// LA RESPUESTA VA AL LADO DE LA TABLA (Nico, 06/11: «primero las mejoras»; diseño
// 05/11, M1). En la compu, donde estaba la torta van qué habría pasado y los
// números de la cartera y de los dos índices, así se ve mientras escribís: estaba
// ~950 px abajo, afuera de la pantalla. En el celular va debajo de la tabla. Más
// abajo siguen el gráfico y «Cada activo». La torta pasó a ser una barra finita:
// repetía la tabla y sus colores cambiaban de activo mientras escribías (M3).
//
// LA CUENTA LA HACE EL SERVIDOR (GET /api/backtest/cartera → backend/
// cartera_simulada.py), y «Mi cartera de hoy» también (GET /api/backtest/
// cartera/hoy: LA regla de qué tiene precio de todos los días, y nunca plata).
// Las palabras: utils/carteraSimulada.js, que nunca promete. El pedido, con sus
// reintentos, es el mismo de «Una regla» (`usePedidoDePrueba`).
//
// LA DIRECCIÓN lleva la cartera SÓLO si la armaste de cero (?origen=cero
// &activos=AAPL,GGAL&pesos=60,40&local=GGAL&anios=2): recargar o mandar el link
// abre la misma cartera. «Mi cartera de hoy» NUNCA va en la dirección, tampoco
// cambiada: dice qué tenés y cuánto pesa cada cosa, y la dirección se ve con el
// ojito prendido, queda en el historial y viaja en cada link (auditorías del 05/11:
// A2, A3 y seguridad 1). A Google y a Meta, `activos`, `pesos` y `local` no se los
// mandamos nosotros (no están en la lista de permitidos, utils/rutasSensibles.js) y
// el píxel no sigue los cambios de dirección. PERO Google los lee solo si en Google
// Analytics está prendida «Cambios de página basados en eventos del historial del
// navegador»: la armada de cero cambia la dirección en cada tecla. Tiene que estar
// apagada, y lo está desde el 06/11. Se comprueba con el programa real de Google, no
// con una marca suelta: la que manda esas vistas es la etiqueta `__ccd_em_page_view`
// (con `vtp_historyEvents`) del gtag.js; `vtp_enableHistoryEvents` dice true aunque
// esté apagada (así lo medí mal el 06/11). El banco: audit/_scripts/fugas_a_terceros.
// Con origen=hoy, recargar la vuelve a pedir; quien abre el link ve la suya.
// «Ocultar saldos»: tu cartera de hoy no se trae con el ojito prendido (los
// porcentajes dicen qué tenés); una armada de cero se ve igual.
//
// Lo que sumás con el buscador lleva LA marca de la ficha (`marcaLocal`: si lo
// tenés, tus lotes; si no, el ticker y el tipo que dice el buscador): GGAL es la
// acción de BYMA en dólares MEP y AGRO es Agrometal, no Adecoagro (auditoría
// 05/11, H1). El buscador usa el catálogo de Tu lista (`catalogoDelBuscador`), el
// que tiene las acciones argentinas: con el de Análisis fundamental, AGRO sólo
// ofrecía Adecoagro (verificación 05/11, V2). «GGAL.BA» es GGAL: no entra dos veces.
//
// El resultado, en condicional y, con «Mi cartera de hoy», diciendo que no es lo
// que ganaste (producto y método 05/11). Mientras la suma no da 100, el último
// resultado queda tenue en vez de desaparecer (M2).
//
// Una sola pantalla para compu y celular (R6).

import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import Segmento from '../components/asset/Segmento'
import Skeleton from '../components/Skeleton'
import TickerSearch from '../components/fundamentals/TickerSearch'
import { Aviso, GraficoDeCien, PUNTEADO, QUE_ES_LA_PEOR_CAIDA, Trazo, usePedidoDePrueba, v } from '../components/backtest/piezas'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { usePrivacy } from '../contexts/PrivacyContext'
import { useLotesDeLaCuenta } from '../hooks/useLotesDeLaCuenta'
import { api } from '../utils/api'
import { PERIODOS_CARTERA, aniosDe, colorDe, porcentaje } from '../utils/backtesting'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_CADA_ACTIVO, QUE_SE_SIMULA, aLaDireccion, carteraDe, consultaDe,
  errorDeHoy, estadoDeLaCartera, filasDeHoy, lecturaAnioPorAnio, lecturaCartera, limpiar, loQueFalta, motivoCartera, notaDeHoy,
  notaDeLosQueSobran, notaDelResumen, notaHoy, notaOjito, notaSinActivos, origenDe, origenes, pesoTxt, repartirIgual,
  rotuloDelAnterior, sobranDe, textoDe, tramosDeLaBarra, trayendoHoy,
} from '../utils/carteraSimulada'
import { marcaLocal } from '../utils/comparadorPrecio'
import { fechaCorta } from '../utils/cuantoSeMueve'
import { nombreDelCliente } from '../utils/navegacion'
import { catalogoDelBuscador } from '../utils/tickers'
import { track } from '../utils/track'

// La cartera en el violeta de la marca; los índices son la vara, punteados. El
// Nasdaq en el azul que la marca reserva para «comparación y referencia»: con dos
// grises había que adivinar cuál era cuál (diseño 05/11, M5).
const COLOR_CARTERA = v('data-violet')
const VARA = { sp500: { color: v('ink-1'), dash: PUNTEADO }, nasdaq: { color: v('rendi-accent'), dash: '2 3' } }
// Mientras se escribe un porcentaje no se pide en cada tecla: se espera esto quieto.
const PAUSA_MS = 400
// Lo que dice la dirección de una cartera armada.
const DE_LA_CARTERA = ['activos', 'pesos', 'local']
// «GGAL.BA» y «GGAL» son el mismo papel en la cartera: la marca dice la serie.
const sinBA = (s) => s.replace(/\.BA$/, '')

/** La cartera y cada índice, como se ven en la respuesta y en el gráfico. */
const lineasDe = (res) => [
  { clave: 'cartera', nombre: 'Esta cartera', color: COLOR_CARTERA, resumen: res.cartera },
  ...res.indices.map(i => ({ clave: i.clave, nombre: i.nombre, ...VARA[i.clave], resumen: i })),
]

export default function SimularCartera() {
  const [searchParams, setSearchParams] = useSearchParams()
  const origen = origenDe(searchParams.get('origen'), searchParams.has('activos'))
  const anios = aniosDe(searchParams.get('anios'), PERIODOS_CARTERA)
  const { hidden } = usePrivacy()
  const { clientCtx } = useAdvisorContext()
  const cliente = nombreDelCliente(clientCtx)
  const lotes = useLotesDeLaCuenta()
  const [filas, setFilas] = useState(() => (origen === 'cero' ? carteraDe(searchParams) : []))
  const [sobran] = useState(() => (origen === 'cero' ? sobranDe(searchParams) : []))
  const [hoy, setHoy] = useState({ estado: origen === 'hoy' ? 'trayendo' : 'listo', nota: null })
  const [cambiada, setCambiada] = useState(false)
  const [vueltaHoy, setVueltaHoy] = useState(0)
  const [sumando, setSumando] = useState(false)
  const [yaEsta, setYaEsta] = useState(null)
  const entradas = useRef({})
  const sumarBoton = useRef(null)
  const origenRef = useRef(null)
  const enfocar = useRef(null)

  // Sólo la armada de cero va en la dirección (ver arriba).
  const escribir = (nuevas) => setSearchParams(prev => {
    const next = new URLSearchParams(prev)
    const d = aLaDireccion(nuevas)
    next.set('origen', 'cero')
    // `activos` va aunque esté vacía: así no se vuelve a llenar con la de hoy al recargar.
    next.set('activos', d.activos)
    next.set('pesos', d.pesos)
    if (d.local) next.set('local', d.local)
    else next.delete('local')
    return next
  }, { replace: true })
  const cambiarFilas = (nuevas) => {
    setFilas(nuevas)
    setYaEsta(null)
    if (origen === 'cero') escribir(nuevas)
    else setCambiada(true)
  }

  // Un link viejo (o armado a mano) con origen=hoy y una cartera: la cartera se
  // saca de la dirección y se trae la de hoy de quien lo abre.
  useEffect(() => {
    if (origen !== 'hoy' || !DE_LA_CARTERA.some(k => searchParams.has(k))) return
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      for (const k of DE_LA_CARTERA) next.delete(k)
      return next
    }, { replace: true })
  }, [origen]) // eslint-disable-line react-hooks/exhaustive-deps

  // «Mi cartera de hoy»: la arma el servidor, y sólo sin el ojito prendido. Si
  // lo prendés con la cartera cargada, se saca de la pantalla.
  useEffect(() => {
    if (origen !== 'hoy') return undefined
    if (hidden) {
      setHoy({ estado: 'oculto', nota: null })
      setFilas([])
      return undefined
    }
    let vivo = true
    setHoy({ estado: 'trayendo', nota: null })
    api.get('/backtest/cartera/hoy')
      .then(r => {
        if (!vivo) return
        const nuevas = filasDeHoy(r)
        setHoy({ estado: nuevas.length ? 'listo' : 'vacia', nota: notaDeHoy(r, cliente) })
        setFilas(nuevas)
        setCambiada(false)
      })
      .catch(e => {
        // `estadoHttp`: con 429 (el freno) el servidor ya dice cuánto esperar.
        if (vivo) setHoy({ estado: 'error', nota: null, detalle: e?.message || 'sin respuesta', estadoHttp: e?.status ?? null })
      })
    return () => { vivo = false }
  }, [origen, hidden, vueltaHoy])

  const elegirOrigen = (o) => {
    // La opción ya elegida no hace nada: tocarla otra vez borraba lo armado, sin
    // aviso ni vuelta atrás (auditoría 05/11, M7).
    if (o === origen) return
    setYaEsta(null)
    setCambiada(false)
    setFilas([])
    if (o === 'cero') {
      setHoy({ estado: 'listo', nota: null })
      setSumando(true)
      escribir([])
      return
    }
    setSumando(false)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('origen', 'hoy')
      for (const k of DE_LA_CARTERA) next.delete(k)
      return next
    }, { replace: true })
  }
  const cambiarAnios = (a) => setSearchParams(prev => {
    const next = new URLSearchParams(prev)
    next.set('anios', String(a))
    return next
  }, { replace: true })

  // El teclado no se pierde: al sumar, va al porcentaje del nuevo; al sacar, al
  // del que quedó en su lugar (o a «Sumar activo» si no quedó ninguno).
  useEffect(() => {
    if (enfocar.current == null) return
    const cual = enfocar.current
    enfocar.current = null
    const el = typeof cual === 'string' ? entradas.current[cual] : null
    if (el) el.focus?.()
    else sumarBoton.current?.focus?.()
  }, [filas.length])

  const ponerPeso = (i, txt) => {
    // Más de 100 no se acepta: queda lo que estaba (`limpiar`).
    const limpio = limpiar(txt)
    if (limpio == null) return
    cambiarFilas(filas.map((f, k) => (k === i ? { ...f, txt: limpio } : f)))
  }
  const sacar = (i) => {
    enfocar.current = filas[i + 1]?.asset || filas[i - 1]?.asset || true
    cambiarFilas(filas.filter((_, k) => k !== i))
  }
  const sumar = (simbolo, opcion) => {
    const crudo = String(simbolo || '').trim().toUpperCase()
    const s = sinBA(crudo)
    setSumando(false)
    if (!s) return
    if (filas.some(f => f.asset === s)) {
      // Ya está: se dice, y el teclado va a su porcentaje (antes no pasaba nada
      // y el foco se perdía; auditoría 05/11, M5).
      setYaEsta(s)
      entradas.current[s]?.focus?.()
      return
    }
    if (filas.length >= MAX_ACTIVOS) return
    const local = marcaLocal(crudo, lotes?.posiciones || [], lotes?.operaciones || [], opcion?.type)
    enfocar.current = s
    cambiarFilas([...filas, { asset: s, local, txt: textoDe(loQueFalta(filas)) }])
  }
  const repartir = () => {
    const ps = repartirIgual(filas.length)
    cambiarFilas(filas.map((f, k) => ({ ...f, txt: String(ps[k]) })))
  }

  const estado = estadoDeLaCartera(filas)
  const lleno = filas.length >= MAX_ACTIVOS
  const trayendo = origen === 'hoy' && hoy.estado === 'trayendo'
  // Con el ojito prendido, tu cartera de hoy no se ve aunque ya estuviera
  // cargada: los porcentajes (y «pasó de 30 % a 20 %») dicen qué tenés.
  const tapada = hidden && origen === 'hoy'
  // Tapada no se pide nada, tampoco en el dibujo antes de que se vacíe la tabla.
  const sim = useSimulacion(tapada ? [] : filas, anios)
  const vista = loQueSeVe(sim)
  // Cambiada, ya no es «tu cartera de hoy»: lo que vale es lo del diario del lunes.
  const deDonde = origen === 'hoy' && !cambiada ? 'hoy' : 'cero'
  const yaEstaEnLaCartera = (t) => (filas.some(f => f.asset === sinBA(String(t?.symbol || '').toUpperCase())) ? 'Ya está' : null)

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby="sc-titulo" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-4">
        <div>
          <h2 id="sc-titulo" className="text-[15px] sm:text-[16px] font-semibold text-ink-0">Simulá una cartera con el pasado</h2>
          <p className="text-[13px] text-ink-2 mt-0.5">{QUE_SE_SIMULA}</p>
        </div>
        <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-end sm:justify-between gap-3">
          <div className="flex flex-col gap-1.5">
            {/* Lo enfoca el «Reintentar» de la cartera de hoy, que desaparece al tocarlo (V7). */}
            <span ref={origenRef} tabIndex={-1} className="text-[12px] font-medium text-ink-2 focus:outline-none">Con qué arranca</span>
            <div className="flex">
              <Segmento etiqueta="Con qué arranca" valor={origen} alElegir={elegirOrigen} opciones={origenes(cliente)} estirar />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-ink-2">Período</span>
            <div className="flex">
              <Segmento etiqueta="Período" valor={anios} alElegir={cambiarAnios} opciones={PERIODOS_CARTERA} estirar />
            </div>
          </div>
        </div>
        {/* Con el ojito prendido no hay tabla: la nota va acá, con su salida. Si no, va
            debajo de la tabla de activos, de la que habla (auditoría de pantalla 06/11,
            M1: arriba empujaba la respuesta hacia abajo del borde de la pantalla). */}
        {tapada && <NotaDeHoy hoy={{ estado: 'oculto' }} cliente={cliente} cambiada={cambiada}
          onReintentar={() => {}} onArmarDeCero={() => elegirOrigen('cero')} />}
        {origen === 'cero' && notaDeLosQueSobran(sobran) && (
          <p className="text-[12.5px] text-ink-2">{notaDeLosQueSobran(sobran)}</p>
        )}

        {!tapada && <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          <div className="flex flex-col min-w-0">
            <div className="grid grid-cols-[minmax(0,1fr)_auto_2.75rem] gap-2 pb-1.5 border-b border-line text-[12px] font-medium text-ink-2">
              <span>Activo</span>
              <span className="text-right">De la cartera</span>
              <span aria-hidden="true" />
            </div>
            {filas.map((f, i) => (
              <div key={f.asset} className="grid grid-cols-[minmax(0,1fr)_auto_2.75rem] items-center gap-2 py-1.5 border-b border-line/60">
                <span className="flex items-center gap-2 min-w-0">
                  <span className="text-[15px] font-semibold text-ink-0 truncate">{f.asset}</span>
                  {f.local && <span className="text-[12px] text-ink-2">BYMA</span>}
                </span>
                <span className="flex items-center gap-1">
                  {/* Al entrar, el número queda elegido: lo que se escribe lo reemplaza (con
                      el tope de 100, «100» más un 6 seguía en 100 y parecía trabado). */}
                  <input ref={el => { entradas.current[f.asset] = el }} type="text" inputMode="decimal" value={f.txt}
                    onChange={e => ponerPeso(i, e.target.value)} onFocus={e => e.target.select?.()}
                    placeholder="0" aria-label={`Porcentaje de ${f.asset} en la cartera`}
                    className="w-16 min-h-11 sm:min-h-10 rounded-lg border border-line-2 bg-bg-2 px-2.5 text-right tabular text-[15px] font-semibold text-ink-0" />
                  <span className="text-[14px] text-ink-2">%</span>
                </span>
                <button type="button" onClick={() => sacar(i)} aria-label={`Sacar ${f.asset}`}
                  className="inline-flex items-center justify-center min-h-11 min-w-11 sm:min-h-10 sm:min-w-10 rounded-lg text-ink-2 hover:text-ink-0 hover:bg-bg-2">
                  <X size={16} aria-hidden="true" />
                </button>
              </div>
            ))}
            {!filas.length && !trayendo && (
              <p className="py-3 text-[13px] text-ink-1">Todavía no hay activos. Sumá el primero y poné cuánto de la cartera va en él.</p>
            )}
            {/* La barra y, debajo, el total en su renglón: al lado de los botones,
                «Total 82% · Faltan 18%» no entraba y bajaba de renglón en cada tecla
                (auditoría de pantalla 06/11, M2). Sin activos no dice nada (en ámbar,
                «Faltan 100%» antes de escribir nada parecía un error); con 100, sólo eso
                (diseño 05/11, B12 y M10). */}
            {filas.length > 0 && (
              <div className="flex flex-col gap-1.5 pt-3">
                <BarraDelCien filas={filas} />
                <span role="status"
                  className={`self-end text-[14px] font-semibold tabular ${estado.listo ? 'text-rendi-pos' : 'text-data-amber'}`}>
                  {estado.listo ? estado.texto : `Total ${estado.totalTxt} · ${estado.texto}`}
                </span>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2 pt-3">
              {/* Mientras se trae tu cartera de hoy no se suma: lo sumado quedaba debajo
                  de «Trayendo…» para siempre (M6). Y espera tus lotes, que deciden la
                  marca de lo que tenés (H1). */}
              <button ref={sumarBoton} type="button" onClick={() => setSumando(s => !s)} aria-expanded={sumando}
                disabled={lleno || trayendo || !lotes}
                className="inline-flex items-center gap-1.5 min-h-11 sm:min-h-9 px-3.5 rounded-full border border-dashed border-line-3 text-[13px] font-medium text-ink-1 hover:text-ink-0 disabled:opacity-50 disabled:cursor-not-allowed">
                <Plus size={14} aria-hidden="true" />
                Sumar activo
              </button>
              {/* El único «Repartir»: el aviso de al lado tenía otro (pantalla 06/11, B5). */}
              {filas.length > 1 && (
                <button type="button" onClick={repartir}
                  className="inline-flex items-center min-h-11 sm:min-h-9 px-3.5 rounded-full border border-line text-[13px] font-medium text-ink-1 hover:text-ink-0">
                  Repartir en partes iguales
                </button>
              )}
            </div>
            {yaEsta && <p role="status" className="pt-2 text-[12.5px] text-ink-1">{yaEsta} ya está en la cartera: cambiá su porcentaje acá arriba.</p>}
            {lleno && <p className="pt-2 text-[12px] text-ink-2">Ya sumaste {MAX_ACTIVOS}, el máximo.</p>}
            {/* El buscador, recién con tus lotes: deciden la marca de lo que tenés (V8). */}
            {sumando && !lleno && (
              <div className="pt-3">
                {lotes ? (
                  <TickerSearch onSelect={sumar} autoFocus etiqueta="Buscar un activo para sumar a la cartera"
                    universo={catalogoDelBuscador} placeholder="Ticker o nombre: GGAL, Apple, bitcoin…" pista="para sumar"
                    marca={yaEstaEnLaCartera} />
                ) : <p role="status" className="text-[12.5px] text-ink-2">Un momento…</p>}
              </div>
            )}
            {origen === 'hoy' && (
              <div className="pt-3">
                <NotaDeHoy hoy={hoy} cliente={cliente} cambiada={cambiada}
                  onReintentar={() => { origenRef.current?.focus?.(); setVueltaHoy(x => x + 1) }}
                  onArmarDeCero={() => elegirOrigen('cero')} />
              </div>
            )}
          </div>
          <Respuesta sim={sim} vista={vista} filas={filas} estado={estado} trayendoHoy={trayendo} origen={deDonde}
            cliente={cliente} />
        </div>}
      </section>

      {!tapada && <Detalle sim={sim} vista={vista} />}
    </div>
  )
}

/** El pedido de la simulación, sólo con 100 % repartido (el mismo de «Una regla»,
 *  `usePedidoDePrueba`), y el último resultado que se pudo simular: queda tenue
 *  mientras la suma no da 100 o mientras llega el nuevo (M2). */
function useSimulacion(filas, anios) {
  const consulta = consultaDe(filas, anios)
  const pedido = usePedidoDePrueba(consulta ? `/backtest/cartera?${consulta}` : null, { pausa: PAUSA_MS })
  const ultimo = useRef(null)
  if (pedido.res?.disponible) ultimo.current = pedido.res
  if (!filas.length) ultimo.current = null
  // «Simuló una cartera» se cuenta una vez por cartera y período, no en cada reintento.
  const contado = useRef(null)
  useEffect(() => {
    if (pedido.res?.disponible && consulta && contado.current !== consulta) {
      contado.current = consulta
      track('cartera_simulada', { activos: filas.length, anios })
    }
  }, [pedido.res]) // eslint-disable-line react-hooks/exhaustive-deps
  return { ...pedido, consulta, ultimo: ultimo.current }
}

/** El resultado que se ve, el MISMO al lado de la tabla y abajo: {res, tenue,
 *  cargando}, o null si no hay ninguno (falta repartir, un error, un aviso). */
function loQueSeVe({ consulta, res, error, cargando, trayendo, ultimo }) {
  if (!consulta) return ultimo ? { res: ultimo, tenue: true, cargando: false } : null
  if (error || (trayendo && !res?.disponible)) return null
  if (!res || (cargando && !res.disponible)) return ultimo ? { res: ultimo, tenue: true, cargando: true } : null
  if (!res.disponible) return null
  return { res, tenue: cargando, cargando }
}

function NotaDeHoy({ hoy, cliente, cambiada, onReintentar, onArmarDeCero }) {
  if (hoy.estado === 'trayendo') return <p role="status" className="text-[12.5px] text-ink-2">{trayendoHoy(cliente)}</p>
  if (hoy.estado === 'oculto') {
    // La salida, tocable: antes estaba escrita y no se podía tocar (diseño 05/11, B5).
    return (
      <p className="text-[12.5px] text-ink-1">
        {notaOjito(cliente)}
        <button type="button" onClick={onArmarDeCero}
          className="ml-1.5 inline-flex items-center min-h-11 sm:min-h-0 font-medium text-data-violet hover:underline">
          Armar de cero
        </button>
      </p>
    )
  }
  if (hoy.estado === 'vacia') return <p className="text-[12.5px] text-ink-1">{notaSinActivos(cliente)}</p>
  if (hoy.estado === 'error') {
    // Con el freno (429), sin «Reintentar» al lado de «Esperá un minuto»: lo mismo que
    // la simulación desde el 05/11 (B2), que no había llegado acá (código 06/11).
    return (
      <Aviso error detalle={hoy.detalle} onReintentar={hoy.estadoHttp === 429 ? null : onReintentar}>
        {errorDeHoy(cliente)}
      </Aviso>
    )
  }
  const nota = notaHoy(cliente, cambiada)
  return <p className="text-[12.5px] text-ink-2">{nota}{hoy.nota && !cambiada ? ` ${hoy.nota}` : ''}</p>
}

/** La barra del 100 % (`tramosDeLaBarra`): un tramo violeta por activo, en el orden
 *  de la tabla y cortados por una rayita; lo que falta, en ámbar (como «Faltan
 *  10%»; al 30 % casi no se veía en claro, pantalla 06/11, B2); llena pero sin
 *  estar lista (sobra, o un activo sin porcentaje), toda en ámbar. Al pasar el
 *  mouse, cada tramo dice de quién es. Lo que dice ya lo dicen la tabla y el total:
 *  el lector de pantalla no la lee. */
function BarraDelCien({ filas }) {
  const { tramos, falta, ambar } = tramosDeLaBarra(filas)
  return (
    <div data-barra="" aria-hidden="true" className="flex gap-0.5 h-2 rounded-full overflow-hidden">
      {tramos.map(t => (
        <span key={t.asset} title={`${t.asset} ${pesoTxt(t.peso)}`} className={ambar ? 'bg-data-amber' : 'bg-data-violet'}
          style={{ flexGrow: t.peso, flexBasis: 0 }} />
      ))}
      {falta > 0 && (
        <span title={`Falta repartir ${pesoTxt(falta)}`} className="bg-data-amber/60" style={{ flexGrow: falta, flexBasis: 0 }} />
      )}
    </div>
  )
}

/** Al lado de la tabla (en el celular, debajo): qué habría pasado, o por qué
 *  todavía no se ve. Mientras la cartera no está lista, el último resultado queda
 *  tenue EN SU LUGAR, con un renglón que dice que es el anterior: el aviso que iba
 *  arriba lo bajaba 68 px en cada tecla y lo volvía a subir (auditoría de pantalla
 *  06/11, M2, B4 y B5; diseño 05/11, M2). Por qué no está lista lo dice el total de
 *  la izquierda. */
function Respuesta({ sim, vista, filas, estado, trayendoHoy, origen, cliente }) {
  // El teclado no se pierde cuando el botón que lo tenía desaparece: va acá.
  const zona = useRef(null)
  const otraVez = () => { zona.current?.focus?.(); sim.reintentar() }
  const resumen = vista && (
    <Resumen res={vista.res} anterior={sim.consulta ? null : rotuloDelAnterior(estado)} cargando={vista.cargando}
      origen={origen} cliente={cliente} />
  )

  let contenido
  if (!sim.consulta) {
    if (trayendoHoy) contenido = <EsperandoLaRespuesta />
    else if (!filas.length) {
      contenido = (
        <p className="rounded-lg border border-dashed border-line-2 px-4 py-5 text-[13px] text-ink-2 leading-relaxed">
          Cuando los porcentajes sumen 100%, acá vas a ver cómo le habría ido a la cartera al lado del S&P 500 y del Nasdaq.
        </p>
      )
    } else if (resumen) {
      contenido = resumen
    } else {
      // Sin un resultado anterior, el aviso entero. No se lee solo: el total de la
      // izquierda ya se lee en cada tecla (pantalla 06/11, B11).
      contenido = <Aviso vivo={false}>{estado.aviso}</Aviso>
    }
  } else if (sim.error && sim.estadoHttp === 429) {
    // El freno: el servidor ya dice cuánto esperar; sin «Reintentar» que volvería a
    // frenar ni un «en unos segundos» que lo contradiga (diseño 05/11, B2).
    contenido = <Aviso error>{sim.error}</Aviso>
  } else if (sim.error) {
    contenido = <Aviso error detalle={sim.error} onReintentar={otraVez}>No pudimos simular la cartera.</Aviso>
  } else if (sim.trayendo && !sim.res?.disponible) {
    // Otra persona está bajando esos precios y se vuelve a pedir solo: se dice, en
    // vez de 12 segundos de gris (como en «Una regla»; auditoría 05/11, M8).
    contenido = <Aviso>Estamos trayendo los precios de los activos nuevos: un momento…</Aviso>
  } else if (sim.res && !sim.res.disponible && !sim.cargando) {
    contenido = (
      <Aviso onReintentar={sim.res.motivo === 'bajando' || sim.res.motivo === 'tope' ? otraVez : null}>
        {motivoCartera(sim.res, filas.length)}
      </Aviso>
    )
  } else {
    // Un aviso de otra cartera no queda en pantalla mientras se pide la nueva (M8).
    contenido = resumen || <EsperandoLaRespuesta />
  }
  // En la compu, la rayita que la separa de la tabla va de arriba abajo
  // (`self-stretch`): con 8 activos terminaba a la mitad de la tabla.
  return (
    <div ref={zona} tabIndex={-1}
      className="min-w-0 focus:outline-none border-t border-line pt-4 lg:self-stretch lg:border-t-0 lg:pt-0 lg:border-l lg:pl-5">
      {contenido}
    </div>
  )
}

function EsperandoLaRespuesta() {
  return (
    <div className="flex flex-col gap-3" aria-busy="true">
      <Skeleton className="h-6 w-4/5" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-28 w-full rounded-lg" />
    </div>
  )
}

/** Qué habría pasado, primero (diseño 05/11, M1); si arrancó más tarde o falta un
 *  índice, enseguida (pantalla 06/11, M3: iba último y afuera de la pantalla); los
 *  números de la cartera y de los índices en una tabla, pegada al título para que
 *  entre en la pantalla (M1); y después la aclaración y las notas. `anterior`: el
 *  renglón que dice que es el resultado de antes (y queda tenue). */
function Resumen({ res, cargando = false, anterior = null, origen, cliente }) {
  const lec = lecturaCartera(res, { origen, cliente })
  return (
    <div className="flex flex-col gap-3">
      {/* Un renglón fijo arriba: «Actualizando…», «Es el resultado anterior: …» o,
          para el lector de pantalla, el resultado nuevo. Antes «Actualizando…» empujaba
          todo (diseño 05/11, B3 y M9). */}
      <p role="status" className={`min-h-5 -mb-2 text-[12.5px] ${anterior ? 'font-medium text-data-amber' : 'text-ink-2'}`}>
        {anterior || (cargando ? 'Actualizando…' : <span className="sr-only">{`Listo: ${lec.titulo}.`}</span>)}
      </p>
      <div className={`flex flex-col gap-3 ${cargando || anterior ? 'opacity-60' : ''} transition-opacity`}>
        <h3 id="sc-respuesta" className="text-[16px] font-semibold text-ink-0 leading-snug">{lec.titulo}</h3>
        {lec.avisos.map(a => <p key={a} className="text-[13px] text-ink-0 leading-relaxed">{a}</p>)}
        {/* La tabla se llama como el título (pantalla 06/11, B12). */}
        <table aria-labelledby="sc-respuesta" className="w-full tabular">
          <thead>
            <tr className="border-b border-line text-[12px] text-ink-2">
              <th scope="col" className="pb-1.5 text-left font-medium"><span className="sr-only">Cartera o índice</span></th>
              <th scope="col" className="pb-1.5 text-right font-medium">Habría dado</th>
              <th scope="col" className="pb-1.5 pl-4 text-right font-medium">Peor caída</th>
            </tr>
          </thead>
          <tbody>
            {lineasDe(res).map(l => (
              <tr key={l.clave} className="border-b border-line/60">
                <th scope="row" className={`py-2 text-left text-[14px] ${l.clave === 'cartera' ? 'font-semibold text-ink-0' : 'font-medium text-ink-1'}`}>
                  <span className="inline-flex items-center gap-2"><Trazo color={l.color} dash={l.dash} />{l.nombre}</span>
                </th>
                <td className={`py-2 text-right text-[16px] font-semibold ${colorDe(l.resumen.resultado)}`}>
                  {porcentaje(l.resumen.resultado)}
                </td>
                <td className="py-2 pl-4 text-right text-[14px] text-ink-0">{porcentaje(l.resumen.peor_caida, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-[13px] text-ink-1 leading-relaxed">
          {lec.aclaracion}
          {origen === 'hoy' && (
            <Link to="/analisis" className="ml-1.5 font-medium text-data-violet hover:underline">Ver Métricas →</Link>
          )}
        </p>
        <p className="text-[12px] text-ink-2 leading-relaxed">{notaDelResumen(res)} {QUE_ES_LA_PEOR_CAIDA}</p>
      </div>
    </div>
  )
}

/** Debajo de la tarjeta: «Año por año», el gráfico, «Cada activo» y cómo se simula,
 *  del MISMO resultado que se ve al lado de la tabla (tenue si aquél lo está). */
function Detalle({ sim, vista }) {
  if (!vista) {
    // La primera vez, mientras llega: el lugar del gráfico.
    const esperando = sim.consulta && !sim.error && !sim.trayendo && (!sim.res || sim.cargando)
    return esperando ? <Skeleton className="h-72 w-full rounded-xl" /> : null
  }
  const { res } = vista
  return (
    <div className={`flex flex-col gap-4 ${vista.tenue ? 'opacity-60' : ''} transition-opacity`}>
      <AnioPorAnio res={res} />
      <GraficoDeCien curva={res.curva} desde={res.desde} hasta={res.hasta}
        lineas={lineasDe(res).map(l => ({ clave: l.clave, nombre: l.nombre, color: l.color, dash: l.dash, final: l.resumen.final }))} />
      <CadaActivo res={res} frases={lecturaCartera(res).deLosActivos} />
      <p className="text-[12px] text-ink-2 leading-relaxed">{COMO_SE_SIMULA_CARTERA}</p>
    </div>
  )
}

/** «Año por año» (Nico, 06/11): el total de la respuesta, abierto en años, y al final
 *  quién habría ganado más años. Va entre la respuesta y el gráfico: si fue parejo o si
 *  un año lo explica casi todo es la pregunta que deja el total. Con un solo año, nada. */
function AnioPorAnio({ res }) {
  const lec = lecturaAnioPorAnio(res)
  if (!lec) return null
  const lineas = lineasDe(res)
  const rotulo = (txt, fechas, fuerte = false) => (
    <th scope="row" className={`py-2 pr-2 text-left text-[14px] text-ink-0 ${fuerte ? 'font-semibold' : 'font-medium'}`}>
      {txt}{fechas && <span className="block text-[12px] font-normal text-ink-2">{fechas}</span>}
    </th>
  )
  const celda = (l, x, fuerte = false) => (
    <td key={l.clave} className={`py-2 pl-2 sm:pl-4 text-right text-[14px] ${fuerte || l.clave === 'cartera' ? 'font-semibold' : ''} ${colorDe(x)}`}>
      {porcentaje(x)}
    </td>
  )
  return (
    <section aria-labelledby="sc-anios" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-1.5">
      <h3 id="sc-anios" className="text-[15px] font-semibold text-ink-0">Año por año</h3>
      {lec.frase && <p className="text-[13.5px] text-ink-1 leading-relaxed">{lec.frase}</p>}
      <table aria-labelledby="sc-anios" className="w-full tabular mt-1">
        <thead>
          <tr className="border-b border-line text-[12px] text-ink-2">
            <th scope="col" className="pb-1.5 text-left font-medium">Período</th>
            {lineas.map(l => (
              <th key={l.clave} scope="col" className="pb-1.5 pl-2 sm:pl-4 text-right font-medium">
                {/* En el celular, la marca arriba del nombre: cuatro columnas entran en 375. */}
                <span className="inline-flex flex-col sm:flex-row items-end sm:items-center gap-1 sm:gap-2">
                  <Trazo color={l.color} dash={l.dash} />{l.nombre}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Primero el total, después cada año (Nico, 06/11). */}
          <tr className="border-b border-line">
            {rotulo(lec.total.rotulo, lec.total.fechas, true)}
            {lineas.map(l => celda(l, l.resumen.resultado, true))}
          </tr>
          {lec.filas.map(f => (
            <tr key={f.desde} className="border-b border-line/60">
              {rotulo(f.rotulo, f.fechas)}
              {lineas.map(l => celda(l, f[l.clave]))}
            </tr>
          ))}
          <tr>
            {rotulo('Por año, en promedio', null, true)}
            {lineas.map(l => celda(l, lec.promedio[l.clave], true))}
          </tr>
        </tbody>
      </table>
      {lec.veredicto.map(v => <p key={v} className="pt-1 text-[14px] font-semibold text-ink-0 leading-relaxed">{v}</p>)}
      <p className="pt-1 text-[12px] text-ink-2 leading-relaxed">{lec.nota}</p>
    </section>
  )
}

// Lo que aportó cada activo, en dólares de cada US$ 100: «+US$ 17,8» (diseño 05/11, M7).
function aporteEnDolares(x) {
  const r = Math.round(x * 10) / 10
  const signo = r > 0 ? '+' : r < 0 ? '−' : ''
  return `${signo}US$ ${Math.abs(r).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`
}

function CadaActivo({ res, frases }) {
  // Los rótulos de cada número también para el lector de pantalla en compu, donde
  // los de arriba son una fila aparte (M12). Sin puntos de color: el de la torta
  // decía cuánto pesa, no quién es, y cambiaba de dueño (diseño 05/11, M3).
  const lector = (txt) => <span className="sr-only">{txt} </span>
  return (
    <section aria-labelledby="sc-cada" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col">
      <h3 id="sc-cada" className="text-[15px] font-semibold text-ink-0 mb-1.5">Cada activo</h3>
      {/* Lo que dicen estos números, al lado de ellos (antes iba con la respuesta). */}
      {frases.map(f => <p key={f} className="pb-1.5 text-[13.5px] text-ink-1 leading-relaxed">{f}</p>)}
      <div aria-hidden="true" className="hidden sm:grid grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] gap-3 pt-1.5 pb-1.5 border-b border-line text-[12px] font-medium text-ink-2">
        <span>Activo</span><span className="text-right">Al principio</span><span className="text-right">Al final</span>
        <span className="text-right">Rindió</span><span className="text-right">Aportó</span>
      </div>
      <ul>
        {res.activos.map(a => (
          <li key={a.asset} className="grid grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] gap-x-3 gap-y-0.5 py-2.5 border-b border-line/60 tabular text-[14px] items-baseline">
            <span className="flex items-center gap-2 min-w-0">
              <span className="font-semibold text-ink-0">{a.asset}</span>
              {a.primera_vela > res.desde && <span className="text-[12px] text-ink-2">desde el {fechaCorta(a.primera_vela)}</span>}
            </span>
            <span className="text-right text-ink-1 sm:text-ink-0">
              <span className="sm:hidden">
                {lector('pesaba')}{pesoTxt(a.peso)}<span aria-hidden="true"> → </span>{lector(', terminó en')}{pesoTxt(a.peso_final)}
              </span>
              <span className="hidden sm:inline">{lector('al principio')}{pesoTxt(a.peso)}</span>
            </span>
            <span className="hidden sm:block text-right text-ink-0">{lector('al final')}{pesoTxt(a.peso_final)}</span>
            <span className={`text-right font-semibold ${colorDe(a.resultado)}`}>
              <span className="sm:hidden text-[12px] font-normal text-ink-2">rindió </span>
              <span className="hidden sm:inline">{lector('rindió')}</span>{porcentaje(a.resultado)}
            </span>
            <span className={`text-right ${colorDe(a.aporte)}`}>
              <span className="sm:hidden text-[12px] text-ink-2">aportó </span>
              <span className="hidden sm:inline">{lector('aportó')}</span>{aporteEnDolares(a.aporte)}
            </span>
          </li>
        ))}
      </ul>
      <p className="pt-2 text-[12px] text-ink-2 leading-relaxed">{NOTA_CADA_ACTIVO}</p>
    </section>
  )
}
