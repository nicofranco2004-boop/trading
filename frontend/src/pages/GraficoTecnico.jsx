// GraficoTecnico — la pestaña «Gráfico» de Análisis técnico (?tab=grafico):
// SÓLO el gráfico, para hacer tus análisis, como en TradingView (Nico, 30/10;
// propuesta aprobada: https://claude.ai/artifact/4Yr7u5rXnHZW4ADuYizC8t).
//   · Arriba a la izquierda, el activo: un botón que abre el buscador (los
//     últimos que miraste, tu cartera, tu lista y lo demás de la app).
//   · Se acuerda en qué activo lo dejaste (utils/graficoTecnico.js, en este
//     navegador) y lo pone en la dirección (?activo=GGAL), así recargar o
//     mandar el link abre el mismo.
//   · Cambiar de activo no borra nada: tus dibujos se guardan solos en tu
//     cuenta, por activo y por moneda (utils/dibujos.js).
// ════════════════════════════════════════════════════════════════════════════
// El gráfico es EL de la ficha (LecturaTecnica, sin tocarlo) con lo que le pasa
// la ficha, armado por la MISMA cuenta (hooks/useFichaDelActivo.js): tu precio,
// tus compras y «Desde que lo tenés» salen igual que en /activo/:ticker. El
// botón del activo va en su propio renglón, arriba de los botones del gráfico,
// y no en el lugar de su título: el gráfico no dibuja ese renglón mientras
// carga la primera vez ni con un activo sin historia de precios (un bono, uno
// que el servidor no pudo traer), y el botón desaparecía — sin él no había cómo
// cambiar de activo. En pantalla completa no está: se achica y se cambia.
//
// Una sola pantalla para compu y celular (R6): en el celular el buscador ocupa
// el ancho de la pantalla.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, Search, X } from 'lucide-react'
import LecturaTecnica from '../components/asset/LecturaTecnica'
import AssetTypeBadge from '../components/AssetTypeBadge'
import Skeleton from '../components/Skeleton'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { useFichaDelActivo } from '../hooks/useFichaDelActivo'
import { api } from '../utils/api'
import { claveDeActivos, urlDeActivo } from '../utils/buscadorRapido'
import { nombreDelCliente } from '../utils/navegacion'
import {
  FILTROS, activoDeEntrada, activoValido, guardado, opcionesDelBuscador, recordar,
} from '../utils/graficoTecnico'

// Cuántos de los últimos que miraste van al lado del botón (el resto, en el buscador).
const CHIPS = 3

export default function GraficoTecnico() {
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const persona = claveDeActivos(user, clientCtx)
  const cliente = nombreDelCliente(clientCtx)
  const [searchParams, setSearchParams] = useSearchParams()
  const deLaDireccion = activoValido(searchParams.get('activo'))
  // El activo abierto, con el nombre con que lo pediste (el de tu lista, el
  // del catálogo, el de tus lotes). null mientras se decide (sin dirección ni
  // nada guardado, hace falta saber qué tenés).
  const [activo, setActivo] = useState(() => deLaDireccion || guardado(persona).activo)
  const [recientes, setRecientes] = useState(() => guardado(persona).recientes)
  // Elegiste con el buscador o un atajo: el renglón del activo se arma de nuevo
  // y el teclado tiene que seguir en su botón, no volver al principio.
  const [enfocar, setEnfocar] = useState(false)

  // Sin nada guardado: el primero de tu cartera con gráfico, o el S&P 500.
  useEffect(() => {
    if (activo) return
    let vivo = true
    api.get('/positions').catch(() => []).then(pos => {
      if (vivo) setActivo(a => a || activoDeEntrada({ deLaDireccion: null, persona, posiciones: pos || [] }))
    })
    return () => { vivo = false }
  }, [activo, persona])

  // Un link a otro activo con la pestaña ya abierta (?activo=…): ése.
  useEffect(() => {
    if (deLaDireccion && deLaDireccion !== activo) setActivo(deLaDireccion)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deLaDireccion])

  // Se guarda y va a la dirección recién cuando el gráfico ABRIÓ ese activo:
  // pedido con otro nombre (GGAL.BA y tu lote es GGAL), queda el tuyo y no
  // los dos. Sin sumar un paso al «atrás» del navegador por cada activo.
  const abierto = (a) => {
    setRecientes(recordar(persona, a).recientes)
    setSearchParams(prev => {
      if (prev.get('activo') === a) return prev
      const next = new URLSearchParams(prev)
      next.set('activo', a)
      return next
    }, { replace: true })
  }
  const elegir = (s) => { const a = activoValido(s); if (a) { setEnfocar(true); setActivo(a) } }

  if (!activo) return <Cargando />
  return <GraficoDe key={activo} activo={activo} recientes={recientes} cliente={cliente} enfocar={enfocar}
    onElegir={elegir} onTuyo={(s) => setActivo(s)} onAbierto={abierto} />
}

function GraficoDe({ activo, recientes, cliente, enfocar, onElegir, onTuyo, onAbierto }) {
  // Lo tenés con otro nombre (pediste GGAL.BA y tu lote es GGAL de IOL; BTC y
  // tu lote es BTC-USD): el tuyo, con tu precio y tus compras. Lo decide la
  // ficha, que sabe en qué mercado está cada lote (tu GGAL de Schwab NO es
  // GGAL.BA). Sólo si ese nombre se puede abrir y es otro: si no («BRK B», con
  // un espacio), el gráfico sigue con lo pedido en vez de quedarse esperando.
  const ficha = useFichaDelActivo(activo, {
    conCotizacion: false,
    aceptaOtroNombre: (s) => { const a = activoValido(s); return !!a && a !== activo },
  })
  useEffect(() => {
    if (ficha.otroNombre) onTuyo(activoValido(ficha.otroNombre))
    else if (!ficha.loading) onAbierto(activo)
  }, [ficha.otroNombre, ficha.loading]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="flex flex-col gap-2">
      <Encabezado activo={activo} recientes={recientes} cliente={cliente} enfocar={enfocar} onElegir={onElegir} />
      {ficha.loading ? <Skeleton className="h-[420px] w-full rounded-xl" />
        : !ficha.grafico ? (
          <div className="bg-bg-1 border border-line rounded-xl px-4 py-6 text-[14px] text-ink-1">
            Los fondos comunes no tienen gráfico de precios: se valúan una vez por día, por el valor de la cuotaparte.
            Elegí otro activo arriba a la izquierda.
          </div>
        ) : <LecturaTecnica key={`${activo}|${ficha.accionLocal}`} titulo={null} {...ficha.grafico} />}
    </div>
  )
}

function Cargando() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-[420px] w-full rounded-xl" />
    </div>
  )
}

// Arriba del gráfico: el activo (abre el buscador), los últimos que miraste y
// la ficha completa.
function Encabezado({ activo, recientes, cliente, enfocar, onElegir }) {
  const [abierto, setAbierto] = useState(false)
  const caja = useRef(null)
  const boton = useRef(null)
  const otros = recientes.filter(s => s !== activo).slice(0, CHIPS)
  // Al cerrar el buscador, el teclado vuelve al botón (como el ⌘K).
  const cerrar = () => { setAbierto(false); boton.current?.focus?.() }
  return (
    <div ref={caja} className="relative flex flex-wrap items-center gap-2 text-ink-0">
      <button ref={boton} type="button" autoFocus={enfocar} onClick={() => setAbierto(a => !a)} aria-haspopup="dialog" aria-expanded={abierto}
        aria-label={`Cambiar de activo (ahora: ${activo})`} data-capa="activo"
        className="inline-flex items-center gap-2 min-h-11 sm:min-h-9 pl-2.5 pr-3 rounded-lg border border-line-3 bg-bg-2 hover:border-ink-3 transition-colors">
        <Search size={15} aria-hidden="true" className="text-ink-1" />
        <span className="text-[16px] font-semibold tracking-tight">{activo}</span>
        <ChevronDown size={14} aria-hidden="true" className={`text-ink-2 transition-transform ${abierto ? 'rotate-180' : ''}`} />
      </button>
      {otros.length > 0 && (
        <div className="flex items-center gap-1.5" role="group" aria-label="Últimos que miraste">
          {otros.map(s => (
            <button key={s} type="button" onClick={() => onElegir(s)}
              className="inline-flex items-center min-h-11 sm:min-h-8 px-2.5 rounded-full border border-line text-[13px] font-medium text-ink-1 hover:text-ink-0 hover:border-ink-3 transition-colors">
              {s}
            </button>
          ))}
        </div>
      )}
      <Link to={urlDeActivo(activo)} className="text-[13px] font-medium text-data-violet hover:underline px-1">Ver ficha →</Link>
      {abierto && (
        <Buscador activo={activo} recientes={recientes} cliente={cliente} caja={caja}
          onCerrar={cerrar}
          onElegir={(s) => { cerrar(); onElegir(s) }} />
      )}
    </div>
  )
}

// El buscador. No dice cuántos dibujos hay en cada activo: la copia de los
// dibujos que guarda el navegador no es por persona (utils/dibujos.js), y en una
// compu compartida mostraba los de la persona anterior (auditoría 30/10).
function Buscador({ activo, recientes, cliente, caja, onCerrar, onElegir }) {
  const [consulta, setConsulta] = useState('')
  const [filtro, setFiltro] = useState('todo')
  const [marcado, setMarcado] = useState(0)
  const [datos, setDatos] = useState({ posiciones: [], lista: [] })
  const campo = useRef(null)

  // Tu cartera y tu lista: se piden al abrir (no al entrar a la pestaña).
  useEffect(() => {
    let vivo = true
    Promise.all([
      api.get('/positions').catch(() => []),
      api.get('/watchlist').catch(() => ({ items: [] })),
    ]).then(([posiciones, wl]) => { if (vivo) setDatos({ posiciones: posiciones || [], lista: wl?.items || [] }) })
    campo.current?.focus?.()
    return () => { vivo = false }
  }, [])

  // Tocar afuera cierra.
  useEffect(() => {
    const fuera = (e) => { if (!caja.current?.contains?.(e.target)) onCerrar() }
    document.addEventListener('pointerdown', fuera)
    return () => document.removeEventListener('pointerdown', fuera)
  }, [caja, onCerrar])

  const secciones = useMemo(
    () => opcionesDelBuscador({ consulta, filtro, recientes, cliente, ...datos }),
    [consulta, filtro, recientes, cliente, datos])
  const filas = secciones.flatMap(s => s.filas)
  useEffect(() => { setMarcado(0) }, [consulta, filtro])
  // La opción marcada con las flechas, siempre a la vista.
  const lista = useRef(null)
  useEffect(() => {
    lista.current?.querySelector?.(`#grafico-op-${marcado}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [marcado])

  // Esc cierra desde cualquier parte del buscador (el campo, un filtro, una
  // opción); las flechas y Enter, desde el campo.
  function teclaEnElBuscador(e) {
    if (e.key === 'Escape') { e.preventDefault(); onCerrar() }
  }
  function tecla(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault(); setMarcado(i => Math.min(filas.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); setMarcado(i => Math.max(0, i - 1))
    } else if (e.key === 'Enter' && filas[marcado]) {
      e.preventDefault(); onElegir(filas[marcado].simbolo)
    }
  }

  let n = -1
  return (
    // En la compu, colgado del botón. En el celular y en la tablet, a todo el
    // ancho (colgado del botón, en una tablet vertical con el menú abierto se
    // salía por la derecha), arriba de la página. En el celular, no más alto que
    // media pantalla: el teclado tapa la otra mitad (el alto de la pantalla no
    // se achica cuando aparece, ni en iPhone ni en Android).
    <div role="dialog" aria-label="Buscar un activo" onKeyDown={teclaEnElBuscador}
      className="fixed inset-x-3 top-[calc(var(--alto-barra-celular,80px)_+_8px)] z-[80] lg:absolute lg:inset-x-auto lg:left-0 lg:top-full lg:mt-1.5 lg:w-[34rem] max-h-[45vh] lg:max-h-[70vh] flex flex-col rounded-xl border border-line-2 bg-bg-raised shadow-lg overflow-hidden">
      <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-line">
        <Search size={17} aria-hidden="true" className="text-ink-1 shrink-0" />
        <label htmlFor="grafico-buscar" className="sr-only">Buscar un activo</label>
        <input id="grafico-buscar" ref={campo} value={consulta} onChange={e => setConsulta(e.target.value)} onKeyDown={tecla}
          placeholder="Ticker o nombre: GGAL, Apple, bitcoin…" autoComplete="off" spellCheck="false"
          role="combobox" aria-expanded="true" aria-controls="grafico-opciones"
          aria-activedescendant={filas[marcado] ? `grafico-op-${marcado}` : undefined}
          className="flex-1 min-w-0 bg-transparent outline-none text-[16px] text-ink-0 placeholder:text-ink-3" />
        <button type="button" onClick={onCerrar} aria-label="Cerrar el buscador"
          className="inline-flex items-center justify-center min-h-10 min-w-10 sm:min-h-8 sm:min-w-8 rounded text-ink-2 hover:text-ink-0">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="flex gap-1.5 px-3.5 py-2 border-b border-line overflow-x-auto scrollbar-none" role="group" aria-label="Qué mostrar">
        {FILTROS.map(f => (
          <button key={f.id} type="button" onClick={() => setFiltro(f.id)} aria-pressed={filtro === f.id}
            className={`shrink-0 min-h-9 sm:min-h-7 px-2.5 rounded-full border text-[12.5px] font-medium whitespace-nowrap transition-colors ${
              filtro === f.id ? 'border-rendi-accent bg-rendi-accent/15 text-ink-0' : 'border-line text-ink-1 hover:text-ink-0'}`}>
            {cliente && f.id === 'cartera' ? 'Cartera' : cliente && f.id === 'lista' ? 'Lista' : f.label}
          </button>
        ))}
      </div>
      <div id="grafico-opciones" ref={lista} role="listbox" aria-label="Activos" className="overflow-y-auto py-1">
        {secciones.length === 0 && (
          <p className="px-3.5 py-4 text-[13px] text-ink-2">
            {consulta.trim() ? 'No encontramos ese activo. Probá con el ticker (GGAL, AAPL, BTC).' : 'Escribí el ticker o el nombre de un activo.'}
          </p>
        )}
        {secciones.map(sec => (
          <div key={sec.titulo} role="group" aria-label={sec.titulo}>
            <div className="px-3.5 pt-2.5 pb-1 text-[11.5px] font-semibold text-ink-2">{sec.titulo}</div>
            {sec.filas.map(f => {
              n += 1
              const i = n
              return (
                <button key={`${sec.titulo}:${f.simbolo}`} id={`grafico-op-${i}`} type="button" role="option"
                  aria-selected={i === marcado} onMouseEnter={() => setMarcado(i)} onClick={() => onElegir(f.simbolo)}
                  className={`w-full flex items-center gap-3 min-h-11 px-3.5 py-1.5 text-left ${i === marcado ? 'bg-bg-2' : ''}`}>
                  <span className="w-20 shrink-0 text-[14.5px] font-semibold text-ink-0 truncate">{f.simbolo}</span>
                  <span className="flex-1 min-w-0 text-[13px] text-ink-1 truncate">
                    {f.origen === 'escrito' ? `Abrir «${f.simbolo}»` : f.nombre || ''}
                  </span>
                  {f.origen !== 'escrito' && <AssetTypeBadge type={f.tipo} />}
                  {f.simbolo === activo && <span className="shrink-0 text-[12px] text-ink-2">abierto</span>}
                </button>
              )
            })}
          </div>
        ))}
      </div>
      <p className="px-3.5 py-2 border-t border-line text-[12px] text-ink-2">
        Al cambiar de activo, tus dibujos del que estabas quedan guardados en él.
      </p>
    </div>
  )
}
