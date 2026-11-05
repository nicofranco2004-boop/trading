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
// la cartera (components/CompositionDonut), sólo con porcentajes.
//
// La cartera y el período van en la dirección (?activos=AAPL,GGAL&pesos=60,40
// &local=GGAL&anios=2): recargar o mandar el link abre la misma cartera.
// «Ocultar saldos»: tu cartera de hoy no se trae con el ojito prendido (los
// porcentajes dicen qué tenés); una armada de cero se ve igual.
//
// Una sola pantalla para compu y celular (R6).

import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, X } from 'lucide-react'
import CompositionDonut from '../components/CompositionDonut'
import Segmento from '../components/asset/Segmento'
import TickerSearch from '../components/fundamentals/TickerSearch'
import {
  Aviso, Dato, ESPERA_MS, GraficoDeCien, PUNTEADO, Punto, REINTENTOS, Trazo, v,
} from '../components/backtest/piezas'
import { usePrivacy } from '../contexts/PrivacyContext'
import { api } from '../utils/api'
import { PERIODOS, aniosDe, colorDe, porcentaje } from '../utils/backtesting'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_HOY, NOTA_OJITO, NOTA_SIN_ACTIVOS, ORIGENES, QUE_SE_SIMULA,
  aLaDireccion, carteraDe, consultaDe, estadoDeLaCartera, filasDeHoy, lecturaCartera, limpiar, loQueFalta,
  motivoCartera, notaDeHoy, origenDe, pesoTxt, porcionesDeLaTorta, repartirIgual, textoDe,
} from '../utils/carteraSimulada'
import { fechaCorta } from '../utils/cuantoSeMueve'
import { track } from '../utils/track'

// La cartera en el violeta de la marca; los índices son la vara: tonos quietos
// y punteados, distintos entre sí por el trazo y por lo claro.
const COLOR_CARTERA = v('data-violet')
const VARA = { sp500: { color: v('ink-1'), dash: PUNTEADO }, nasdaq: { color: v('ink-2'), dash: '2 3' } }
// Mientras se escribe un porcentaje no se pide en cada tecla: se espera esto quieto.
const PAUSA_MS = 400

export default function SimularCartera() {
  const [searchParams, setSearchParams] = useSearchParams()
  const origen = origenDe(searchParams.get('origen'))
  const anios = aniosDe(searchParams.get('anios'))
  const { hidden } = usePrivacy()
  const [filas, setFilas] = useState(() => carteraDe(searchParams))
  const [hoy, setHoy] = useState({ estado: 'listo', nota: null })
  const [vueltaHoy, setVueltaHoy] = useState(0)
  const [sumando, setSumando] = useState(false)
  const entradas = useRef({})
  const sumarBoton = useRef(null)
  const enfocar = useRef(null)

  const escribir = (nuevas, extra = {}) => setSearchParams(prev => {
    const next = new URLSearchParams(prev)
    const d = aLaDireccion(nuevas)
    // `activos` va aunque esté vacío: así una cartera vaciada a mano no se vuelve
    // a llenar con la de hoy al recargar.
    next.set('activos', d.activos)
    next.set('pesos', d.pesos)
    if (d.local) next.set('local', d.local)
    else next.delete('local')
    for (const [k, val] of Object.entries(extra)) next.set(k, val)
    return next
  }, { replace: true })
  const cambiarFilas = (nuevas) => { setFilas(nuevas); escribir(nuevas) }

  // «Mi cartera de hoy»: la arma el servidor, y sólo sin el ojito prendido.
  const traerHoy = origen === 'hoy' && !searchParams.has('activos')
  useEffect(() => {
    if (!traerHoy) return undefined
    if (hidden) { setHoy({ estado: 'oculto', nota: null }); return undefined }
    let vivo = true
    setHoy({ estado: 'trayendo', nota: null })
    api.get('/backtest/cartera/hoy')
      .then(r => {
        if (!vivo) return
        const nuevas = filasDeHoy(r)
        setHoy({ estado: nuevas.length ? 'listo' : 'vacia', nota: notaDeHoy(r) })
        cambiarFilas(nuevas)
      })
      .catch(e => { if (vivo) setHoy({ estado: 'error', nota: null, detalle: e?.message || 'sin respuesta' }) })
    return () => { vivo = false }
  }, [traerHoy, hidden, vueltaHoy]) // eslint-disable-line react-hooks/exhaustive-deps

  const elegirOrigen = (o) => {
    setHoy({ estado: 'listo', nota: null })
    setFilas([])
    if (o === 'cero') {
      setSumando(true)
      escribir([], { origen: 'cero' })
      return
    }
    setSumando(false)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('origen', 'hoy')
      for (const k of ['activos', 'pesos', 'local']) next.delete(k)
      return next
    }, { replace: true })
    setVueltaHoy(x => x + 1)
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
  const sumar = (simbolo) => {
    const s = String(simbolo || '').trim().toUpperCase()
    setSumando(false)
    if (!s || filas.some(f => f.asset === s) || filas.length >= MAX_ACTIVOS) return
    enfocar.current = s
    cambiarFilas([...filas, { asset: s, local: false, txt: textoDe(loQueFalta(filas)) }])
  }
  const repartir = () => {
    const ps = repartirIgual(filas.length)
    cambiarFilas(filas.map((f, k) => ({ ...f, txt: String(ps[k]) })))
  }

  const estado = estadoDeLaCartera(filas)
  const porciones = porcionesDeLaTorta(filas)
  const colores = Object.fromEntries(porciones.map(p => [p.key, p.color]))
  const lleno = filas.length >= MAX_ACTIVOS
  // Con el ojito prendido, tu cartera de hoy no se ve aunque ya estuviera
  // cargada: los porcentajes (y «pasó de 30 % a 20 %») dicen qué tenés.
  const tapada = hidden && origen === 'hoy'

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
              <Segmento etiqueta="Con qué arranca" valor={origen} alElegir={elegirOrigen} opciones={ORIGENES} estirar />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-ink-2">Período</span>
            <div className="flex">
              <Segmento etiqueta="Período" valor={anios} alElegir={cambiarAnios} opciones={PERIODOS} estirar />
            </div>
          </div>
        </div>
        {origen === 'hoy' && <NotaDeHoy hoy={tapada ? { estado: 'oculto' } : hoy} onReintentar={() => setVueltaHoy(x => x + 1)} />}

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
            {!filas.length && hoy.estado !== 'trayendo' && (
              <p className="py-3 text-[13px] text-ink-1">Todavía no hay activos. Sumá el primero y poné cuánto de la cartera va en él.</p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-3">
              <div className="flex flex-wrap items-center gap-2">
                <button ref={sumarBoton} type="button" onClick={() => setSumando(s => !s)} aria-expanded={sumando} disabled={lleno}
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
              <span role="status" className={`text-[14px] font-semibold tabular ${estado.listo ? 'text-rendi-pos' : 'text-data-amber'}`}>
                Total {estado.totalTxt} · {estado.texto}
              </span>
            </div>
            {lleno && <p className="pt-2 text-[12px] text-ink-2">Ya sumaste {MAX_ACTIVOS}, el máximo.</p>}
            {sumando && !lleno && (
              <div className="pt-3">
                <TickerSearch onSelect={sumar} autoFocus etiqueta="Buscar un activo para sumar a la cartera"
                  placeholder="Ticker o nombre: GGAL, Apple, bitcoin…" pista="para sumar" />
              </div>
            )}
          </div>
          <CompositionDonut title="La torta" items={porciones} montos={false} maxSlices={MAX_ACTIVOS + 1} minSlicePct={0}
            emptyLabel="Sumá un activo y poné cuánto va: la torta se arma acá." />
        </div>}
      </section>

      {!tapada && <Simulacion filas={filas} anios={anios} estado={estado} colores={colores} onRepartir={repartir} />}
    </div>
  )
}

function NotaDeHoy({ hoy, onReintentar }) {
  if (hoy.estado === 'trayendo') return <p role="status" className="text-[12.5px] text-ink-2">Trayendo tu cartera de hoy…</p>
  if (hoy.estado === 'oculto') return <p className="text-[12.5px] text-ink-1">{NOTA_OJITO}</p>
  if (hoy.estado === 'vacia') return <p className="text-[12.5px] text-ink-1">{NOTA_SIN_ACTIVOS}</p>
  if (hoy.estado === 'error') {
    return <Aviso error detalle={hoy.detalle} onReintentar={onReintentar}>No pudimos traer tu cartera de hoy.</Aviso>
  }
  return <p className="text-[12.5px] text-ink-2">{NOTA_HOY}{hoy.nota ? ` ${hoy.nota}` : ''}</p>
}

/** Lo que dice el servidor de la cartera armada: se pide sólo cuando suma 100. */
function Simulacion({ filas, anios, estado, colores, onRepartir }) {
  const consulta = consultaDe(filas, anios)
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState(null)
  const [vuelta, setVuelta] = useState(0)
  const primera = useRef(true)
  const contado = useRef(null)

  useEffect(() => {
    if (!consulta) { setRes(null); setError(null); setCargando(false); return undefined }
    let vivo = true
    let intento = 0
    let espera = null
    const pedir = () => {
      setCargando(true)
      setError(null)
      api.get(`/backtest/cartera?${consulta}`)
        .then(r => {
          if (!vivo) return
          if (r?.motivo === 'bajando' && intento < REINTENTOS) {
            intento += 1
            espera = setTimeout(pedir, ESPERA_MS)
            return
          }
          setRes(r)
          setCargando(false)
          if (r?.disponible && contado.current !== consulta) {
            contado.current = consulta
            track('cartera_simulada', { activos: filas.length, anios })
          }
        })
        .catch(e => {
          if (!vivo) return
          setRes(null)
          setError(e?.message || 'sin respuesta')
          setCargando(false)
        })
    }
    espera = setTimeout(pedir, primera.current ? 0 : PAUSA_MS)
    primera.current = false
    return () => { vivo = false; if (espera) clearTimeout(espera) }
  }, [consulta, vuelta]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!consulta) {
    if (!estado.aviso) return null
    return (
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
  if (error) {
    return <Aviso error detalle={error} onReintentar={() => setVuelta(x => x + 1)}>No se pudo simular la cartera.</Aviso>
  }
  if (!res) return <p role="status" className="text-[12.5px] text-ink-2">Simulando…</p>
  if (!res.disponible) {
    return <Aviso onReintentar={res.motivo === 'bajando' ? () => setVuelta(x => x + 1) : null}>{motivoCartera(res)}</Aviso>
  }
  return <Resultado res={res} cargando={cargando} colores={colores} />
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
        <div className={`grid grid-cols-1 ${tarjetas.length === 3 ? 'sm:grid-cols-3' : tarjetas.length === 2 ? 'sm:grid-cols-2' : ''} gap-4`}>
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
                <Dato etiqueta="US$ 100 quedaron en">
                  <span className="text-[16px] font-semibold tabular text-ink-0">US$ {Math.round(t.resumen.final).toLocaleString('es-AR')}</span>
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
  return (
    <section aria-labelledby="sc-cada" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col">
      <h3 id="sc-cada" className="text-[15px] font-semibold text-ink-0 mb-1.5">Cada activo</h3>
      <div className="hidden sm:grid grid-cols-[minmax(0,1.4fr)_repeat(4,minmax(0,1fr))] gap-3 pb-1.5 border-b border-line text-[12px] font-medium text-ink-2">
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
              <span className="sm:hidden">{pesoTxt(a.peso)} → {pesoTxt(a.peso_final)}</span>
              <span className="hidden sm:inline">{pesoTxt(a.peso)}</span>
            </span>
            <span className="hidden sm:block text-right text-ink-0">{pesoTxt(a.peso_final)}</span>
            <span className={`text-right font-semibold ${colorDe(a.resultado)}`}>
              <span className="sm:hidden text-[12px] font-normal text-ink-2">el activo </span>{porcentaje(a.resultado)}
            </span>
            <span className={`text-right ${colorDe(a.aporte)}`}>
              <span className="sm:hidden text-[12px] text-ink-2">aportó </span>{porcentaje(a.aporte).replace('%', ' p.')}
            </span>
          </li>
        ))}
      </ul>
      <p className="pt-2 text-[12px] text-ink-2 leading-relaxed">
        Sin tocar la cartera, el que sube pesa cada vez más y el que baja, cada vez menos. «Aportó»: cuántos puntos del
        resultado de la cartera vienen de ese activo.
      </p>
    </section>
  )
}
