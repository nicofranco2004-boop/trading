// SimularCartera — «Una cartera», el segundo modo de la pestaña «Backtesting» de
// Análisis técnico (?tab=backtesting&modo=cartera).
// ═══════════════════════════════════════════════════════════════════════════
// Nico, 05/11/2026; boceto aprobado (opción A, dentro de Backtesting):
// https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5.
// Arrancás con tu cartera de hoy o de cero, ponés cada activo y cuánto de la
// cartera va en él (sobre 100) y la torta se arma mientras escribís. Con 100 %
// repartido se ve qué habría pasado con US$ 100 comprados así el primer día y
// sin tocar, al lado del S&P 500 y del Nasdaq: las tarjetas, qué quiere decir,
// el gráfico y qué hizo cada activo.
//
// LA CUENTA LA HACE EL SERVIDOR (GET /api/backtest/cartera → backend/
// cartera_simulada.py), y «Mi cartera de hoy» también (GET /api/backtest/
// cartera/hoy: LA regla de qué tiene precio de todos los días, y nunca plata).
// Las palabras: utils/carteraSimulada.js, que nunca promete. La torta es LA de
// la cartera (components/CompositionDonut), sólo con porcentajes. El pedido, con
// sus reintentos, es el mismo de «Una regla» (`usePedidoDePrueba`).
//
// LA DIRECCIÓN lleva la cartera SÓLO si la armaste de cero (?origen=cero
// &activos=AAPL,GGAL&pesos=60,40&local=GGAL&anios=2): recargar o mandar el link
// abre la misma cartera. «Mi cartera de hoy» NUNCA va en la dirección, tampoco
// cambiada: dice qué tenés y cuánto pesa cada cosa, y la dirección se ve con el
// ojito prendido, queda en el historial, viaja en cada link y se les manda a
// Google y a Meta al cargar la página (auditorías del 05/11: A2, A3 y seguridad
// 1). Con origen=hoy, recargar la vuelve a pedir; quien abre el link ve la suya.
// «Ocultar saldos»: tu cartera de hoy no se trae con el ojito prendido (los
// porcentajes dicen qué tenés); una armada de cero se ve igual.
//
// Lo que sumás con el buscador lleva LA marca de la ficha (`marcaLocal`: si lo
// tenés, tus lotes; si no, el ticker y el tipo que dice el buscador): GGAL es la
// acción de BYMA en dólares MEP y AGRO es Agrometal, no Adecoagro (auditoría
// 05/11, H1). «GGAL.BA» es GGAL: no entra dos veces.
//
// Una sola pantalla para compu y celular (R6).

import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import CompositionDonut from '../components/CompositionDonut'
import Segmento from '../components/asset/Segmento'
import Skeleton from '../components/Skeleton'
import TickerSearch from '../components/fundamentals/TickerSearch'
import { Aviso, Dato, GraficoDeCien, PUNTEADO, Punto, Trazo, usePedidoDePrueba, v } from '../components/backtest/piezas'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { usePrivacy } from '../contexts/PrivacyContext'
import { useLotesDeLaCuenta } from '../hooks/useLotesDeLaCuenta'
import { api } from '../utils/api'
import { PERIODOS, aniosDe, colorDe, enQueTermino, porcentaje } from '../utils/backtesting'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_CADA_ACTIVO, QUE_SE_SIMULA, aLaDireccion, carteraDe, consultaDe,
  errorDeHoy, estadoDeLaCartera, filasDeHoy, lecturaCartera, limpiar, loQueFalta, motivoCartera, notaDeHoy,
  notaDeLosQueSobran, notaHoy, notaOjito, notaSinActivos, origenDe, origenes, pesoTxt, porcionesDeLaTorta,
  repartirIgual, sobranDe, textoDe, trayendoHoy,
} from '../utils/carteraSimulada'
import { marcaLocal } from '../utils/comparadorPrecio'
import { fechaCorta } from '../utils/cuantoSeMueve'
import { nombreDelCliente } from '../utils/navegacion'
import { track } from '../utils/track'

// La cartera en el violeta de la marca; los índices son la vara: tonos quietos
// y punteados, distintos entre sí por el trazo y por lo claro.
const COLOR_CARTERA = v('data-violet')
const VARA = { sp500: { color: v('ink-1'), dash: PUNTEADO }, nasdaq: { color: v('ink-2'), dash: '2 3' } }
// Mientras se escribe un porcentaje no se pide en cada tecla: se espera esto quieto.
const PAUSA_MS = 400
// Lo que dice la dirección de una cartera armada.
const DE_LA_CARTERA = ['activos', 'pesos', 'local']
// «GGAL.BA» y «GGAL» son el mismo papel en la cartera: la marca dice la serie.
const sinBA = (s) => s.replace(/\.BA$/, '')

export default function SimularCartera() {
  const [searchParams, setSearchParams] = useSearchParams()
  const origen = origenDe(searchParams.get('origen'), searchParams.has('activos'))
  const anios = aniosDe(searchParams.get('anios'))
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
  const totalRef = useRef(null)
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
        setHoy({ estado: nuevas.length ? 'listo' : 'vacia', nota: notaDeHoy(r) })
        setFilas(nuevas)
        setCambiada(false)
      })
      .catch(e => { if (vivo) setHoy({ estado: 'error', nota: null, detalle: e?.message || 'sin respuesta' }) })
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

  const ponerPeso = (i, txt) => cambiarFilas(filas.map((f, k) => (k === i ? { ...f, txt: limpiar(txt) } : f)))
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
  const porciones = porcionesDeLaTorta(filas)
  const colores = Object.fromEntries(porciones.map(p => [p.key, p.color]))
  const lleno = filas.length >= MAX_ACTIVOS
  const trayendo = origen === 'hoy' && hoy.estado === 'trayendo'
  // Con el ojito prendido, tu cartera de hoy no se ve aunque ya estuviera
  // cargada: los porcentajes (y «pasó de 30 % a 20 %») dicen qué tenés.
  const tapada = hidden && origen === 'hoy'
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
            <span className="text-[12px] font-medium text-ink-2">Con qué arranca</span>
            <div className="flex">
              <Segmento etiqueta="Con qué arranca" valor={origen} alElegir={elegirOrigen} opciones={origenes(cliente)} estirar />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-ink-2">Período</span>
            <div className="flex">
              <Segmento etiqueta="Período" valor={anios} alElegir={cambiarAnios} opciones={PERIODOS} estirar />
            </div>
          </div>
        </div>
        {origen === 'hoy' && (
          <NotaDeHoy hoy={tapada ? { estado: 'oculto' } : hoy} cliente={cliente} cambiada={cambiada}
            onReintentar={() => setVueltaHoy(x => x + 1)} />
        )}
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
                  <Punto color={colores[f.asset] || 'rgb(var(--bg-3))'} />
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
            <div className="flex flex-wrap items-center justify-between gap-2 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                {/* Mientras se trae tu cartera de hoy no se suma: lo sumado quedaba debajo
                    de «Trayendo…» para siempre (M6). Y espera tus lotes, que deciden la
                    marca de lo que tenés (H1). */}
                <button ref={sumarBoton} type="button" onClick={() => setSumando(s => !s)} aria-expanded={sumando}
                  disabled={lleno || trayendo || !lotes}
                  className="inline-flex items-center gap-1.5 min-h-11 sm:min-h-9 px-3.5 rounded-full border border-dashed border-line-3 text-[13px] font-medium text-ink-1 hover:text-ink-0 disabled:opacity-50 disabled:cursor-not-allowed">
                  <Plus size={14} aria-hidden="true" />
                  Sumar activo
                </button>
                {filas.length > 1 && (
                  <button type="button" onClick={repartir}
                    className="inline-flex items-center min-h-11 sm:min-h-9 px-3.5 rounded-full border border-line text-[13px] font-medium text-ink-1 hover:text-ink-0">
                    Repartir en partes iguales
                  </button>
                )}
              </div>
              {/* Lo enfoca «Repartir» del aviso de abajo, que desaparece al tocarlo. */}
              <span ref={totalRef} tabIndex={-1} role="status"
                className={`text-[14px] font-semibold tabular focus:outline-none ${estado.listo ? 'text-rendi-pos' : 'text-data-amber'} ${trayendo ? 'invisible' : ''}`}>
                {trayendo ? '' : `Total ${estado.totalTxt} · ${estado.texto}`}
              </span>
            </div>
            {yaEsta && <p role="status" className="pt-2 text-[12.5px] text-ink-1">{yaEsta} ya está en la cartera: cambiá su porcentaje acá arriba.</p>}
            {lleno && <p className="pt-2 text-[12px] text-ink-2">Ya sumaste {MAX_ACTIVOS}, el máximo.</p>}
            {sumando && !lleno && (
              <div className="pt-3">
                <TickerSearch onSelect={sumar} autoFocus etiqueta="Buscar un activo para sumar a la cartera"
                  placeholder="Ticker o nombre: GGAL, Apple, bitcoin…" pista="para sumar" marca={yaEstaEnLaCartera} />
              </div>
            )}
          </div>
          <CompositionDonut title="La torta" items={porciones} montos={false} maxSlices={MAX_ACTIVOS + 1} minSlicePct={0}
            emptyLabel="Sumá un activo y poné cuánto va: la torta se arma acá." />
        </div>}
      </section>

      {!tapada && (
        <Simulacion filas={filas} anios={anios} estado={estado} colores={colores}
          onRepartir={() => { totalRef.current?.focus?.(); repartir() }} />
      )}
    </div>
  )
}

function NotaDeHoy({ hoy, cliente, cambiada, onReintentar }) {
  if (hoy.estado === 'trayendo') return <p role="status" className="text-[12.5px] text-ink-2">{trayendoHoy(cliente)}</p>
  if (hoy.estado === 'oculto') return <p className="text-[12.5px] text-ink-1">{notaOjito(cliente)}</p>
  if (hoy.estado === 'vacia') return <p className="text-[12.5px] text-ink-1">{notaSinActivos(cliente)}</p>
  if (hoy.estado === 'error') {
    return <Aviso error detalle={hoy.detalle} onReintentar={onReintentar}>{errorDeHoy(cliente)}</Aviso>
  }
  const nota = notaHoy(cliente, cambiada)
  return <p className="text-[12.5px] text-ink-2">{nota}{hoy.nota && !cambiada ? ` ${hoy.nota}` : ''}</p>
}

/** Lo que dice el servidor de la cartera armada: se pide sólo cuando suma 100. */
function Simulacion({ filas, anios, estado, colores, onRepartir }) {
  const consulta = consultaDe(filas, anios)
  const { res, error, cargando, trayendo, reintentar } = usePedidoDePrueba(
    consulta ? `/backtest/cartera?${consulta}` : null, { pausa: PAUSA_MS })
  // El teclado no se pierde cuando el botón que lo tenía desaparece: va acá.
  const zona = useRef(null)
  const otraVez = () => { zona.current?.focus?.(); reintentar() }
  // «Simuló una cartera» se cuenta una vez por cartera y período, no en cada reintento.
  const contado = useRef(null)
  useEffect(() => {
    if (res?.disponible && consulta && contado.current !== consulta) {
      contado.current = consulta
      track('cartera_simulada', { activos: filas.length, anios })
    }
  }, [res]) // eslint-disable-line react-hooks/exhaustive-deps

  let contenido = null
  if (!consulta) {
    if (estado.aviso) {
      contenido = (
        <Aviso>
          {estado.aviso}
          {filas.length > 1 && (
            <button type="button" onClick={onRepartir}
              className="ml-1.5 inline-flex items-center min-h-11 sm:min-h-0 font-medium text-data-violet hover:underline">
              Repartir en partes iguales
            </button>
          )}
        </Aviso>
      )
    }
  } else if (error) {
    contenido = <Aviso error detalle={error} onReintentar={otraVez}>No se pudo simular la cartera.</Aviso>
  } else if (trayendo && !res?.disponible) {
    // Otra persona está bajando esos precios y se vuelve a pedir solo: se dice, en
    // vez de 12 segundos de gris (como en «Una regla»; auditoría 05/11, M8).
    contenido = <Aviso>Estamos trayendo los precios de los activos nuevos: un momento…</Aviso>
  } else if (!res || (cargando && !res.disponible)) {
    // Un aviso de otra cartera no queda en pantalla mientras se pide la nueva (M8).
    contenido = (
      <div className="flex flex-col gap-4" aria-busy="true">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-36 w-full rounded-xl hidden xl:block" />
        </div>
        <Skeleton className="h-72 w-full rounded-xl" />
      </div>
    )
  } else if (!res.disponible) {
    contenido = (
      <Aviso onReintentar={res.motivo === 'bajando' || res.motivo === 'tope' ? otraVez : null}>
        {motivoCartera(res, filas.length)}
      </Aviso>
    )
  } else {
    contenido = <Resultado res={res} cargando={cargando} colores={colores} />
  }
  return <div ref={zona} tabIndex={-1} className="focus:outline-none empty:hidden">{contenido}</div>
}

function Resultado({ res, cargando, colores }) {
  const lec = lecturaCartera(res)
  const tarjetas = [
    { clave: 'cartera', nombre: 'Esta cartera', color: COLOR_CARTERA, resumen: res.cartera },
    ...res.indices.map(i => ({ clave: i.clave, nombre: i.nombre, ...VARA[i.clave], resumen: i })),
  ]
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-[12.5px] text-ink-2 empty:hidden">{cargando ? 'Actualizando…' : ''}</p>
      <div className={`flex flex-col gap-4 ${cargando ? 'opacity-60' : ''} transition-opacity`}>
        {/* Tres columnas recién en xl: en una tablet, con el menú al costado, el
            número de 26 px no entraba en un tercio y pisaba el de al lado (M3). */}
        <div className={`grid grid-cols-1 ${tarjetas.length > 1 ? 'sm:grid-cols-2' : ''} ${tarjetas.length === 3 ? 'xl:grid-cols-3' : ''} gap-4`}>
          {tarjetas.map(t => (
            <section key={t.clave} aria-label={t.nombre} className={`bg-bg-1 border rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3 min-w-0 ${
              t.clave === 'cartera' ? 'border-data-violet/40' : 'border-line'}`}>
              <h3 className="flex items-center gap-2 text-[14px] font-semibold text-ink-0"><Trazo color={t.color} dash={t.dash} />{t.nombre}</h3>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-3">
                <Dato etiqueta="Resultado">
                  <span className={`text-[26px] leading-tight font-semibold tabular ${colorDe(t.resumen.resultado)}`}>
                    {porcentaje(t.resumen.resultado)}
                  </span>
                </Dato>
                <Dato etiqueta="Peor caída">
                  <span className="text-[18px] font-semibold tabular text-ink-0">{porcentaje(t.resumen.peor_caida, 0)}</span>
                </Dato>
                <Dato etiqueta="US$ 100 habrían quedado en">
                  <span className="text-[16px] font-semibold tabular text-ink-0">{enQueTermino(t.resumen.final)}</span>
                </Dato>
              </dl>
            </section>
          ))}
        </div>
        {lec && (
          <section aria-labelledby="sc-lectura" className="bg-bg-2/60 rounded-lg px-4 py-3 flex flex-col gap-1.5">
            <h3 id="sc-lectura" className="text-[14px] font-semibold text-ink-0">{lec.titulo}</h3>
            {lec.frases.map(f => <p key={f} className="text-[13.5px] text-ink-1 leading-relaxed">{f}</p>)}
          </section>
        )}
        <GraficoDeCien curva={res.curva} desde={res.desde} hasta={res.hasta}
          lineas={tarjetas.map(t => ({ clave: t.clave, nombre: t.nombre, color: t.color, dash: t.dash, final: t.resumen.final }))} />
        <CadaActivo res={res} colores={colores} />
        <p className="text-[12px] text-ink-2 leading-relaxed">{COMO_SE_SIMULA_CARTERA}</p>
      </div>
    </div>
  )
}

function CadaActivo({ res, colores }) {
  // Los rótulos de cada número también para el lector de pantalla en compu, donde
  // los de arriba son una fila aparte (M12).
  const lector = (txt) => <span className="sr-only">{txt} </span>
  return (
    <section aria-labelledby="sc-cada" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col">
      <h3 id="sc-cada" className="text-[15px] font-semibold text-ink-0 mb-1.5">Cada activo</h3>
      <div aria-hidden="true" className="hidden sm:grid grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] gap-3 pb-1.5 border-b border-line text-[12px] font-medium text-ink-2">
        <span>Activo</span><span className="text-right">Al principio</span><span className="text-right">Al final</span>
        <span className="text-right">El activo</span><span className="text-right">Aportó</span>
      </div>
      <ul>
        {res.activos.map(a => (
          <li key={a.asset} className="grid grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] gap-x-3 gap-y-0.5 py-2.5 border-b border-line/60 tabular text-[14px] items-baseline">
            <span className="flex items-center gap-2 min-w-0">
              <Punto color={colores[a.asset] || 'rgb(var(--bg-3))'} />
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
              <span className="sm:hidden text-[12px] font-normal text-ink-2">el activo </span>
              <span className="hidden sm:inline">{lector('el activo')}</span>{porcentaje(a.resultado)}
            </span>
            <span className={`text-right ${colorDe(a.aporte)}`}>
              <span className="sm:hidden text-[12px] text-ink-2">aportó </span>
              <span className="hidden sm:inline">{lector('aportó')}</span>{porcentaje(a.aporte).replace('%', ' puntos')}
            </span>
          </li>
        ))}
      </ul>
      <p className="pt-2 text-[12px] text-ink-2 leading-relaxed">{NOTA_CADA_ACTIVO}</p>
    </section>
  )
}
