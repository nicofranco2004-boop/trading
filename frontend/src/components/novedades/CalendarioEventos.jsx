// CalendarioEventos — "Ver calendario" de Eventos: los cobros (dividendos y
// cupones) y los balances de tu cartera, en un calendario por mes.
// ═══════════════════════════════════════════════════════════════════════════
// Sin datos propios: los eventos de las empresas los da /api/events/portfolio
// (lo mismo que "Para ti", mirando un año) y los de los bonos, el cronograma
// (`upcomingBondEvents`). El monto de cada cobro sale de `eventCobro`, la misma
// cuenta que la agenda de Eventos. Las cuentas del calendario (qué entra, en qué
// casillero, qué meses) viven en utils/calendarioEventos.js, con tests.
//
// Sistema visual (frontend/CLAUDE.md): el armazón es `Modal` —ventana en la
// compu, hoja desde abajo en el teléfono—, así que no hay gemelo *Mobile (R6).
// En el teléfono cada día muestra puntitos; en la compu, los tickers. Números en
// Geist con `tabular` (R1), radios de la escala (R5), colores del tema (R8).
//
// Colores de la marca (manual de Rendi): verde y rojo sólo para plata que
// entra o sale, cielo para información, violeta sólo para acciones. Por eso un
// cobro va en verde —como los dividendos en la lista de Movimientos—, el corte
// con borde verde (es el mismo dividendo, todavía no cobrado) y el balance en
// cielo (es un dato, no plata). El violeta queda para el botón que lo abre.

import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import Modal from '../Modal'
import { api } from '../../utils/api'
import { fmtMoney } from '../../utils/format'
import { usePrivacy, OCULTO } from '../../contexts/PrivacyContext'
import { hoyISO } from '../../utils/fecha'
import {
  upcomingBondEvents, normalizeBackendEvents, mergeEvents, eventCobro,
} from '../../utils/upcomingEvents'
import {
  FILTROS, DIAS_SEMANA, categoriaDe, rotuloDe, nombreDelMes,
  eventosDelCalendario, porDia, semanasDelMes, mesesDelCalendario,
} from '../../utils/calendarioEventos'

const PUNTO = {
  cobro: 'bg-rendi-pos-fill',
  corte: 'border border-rendi-pos-fill',
  balance: 'bg-rendi-accent',
}
const CHIP = {
  cobro: 'bg-rendi-pos-fill/15 text-rendi-pos',
  corte: 'border border-rendi-pos-fill/50 text-rendi-pos',
  balance: 'bg-rendi-accent/15 text-rendi-accent',
}

const DIA_CORTO = new Intl.DateTimeFormat('es-AR', { weekday: 'short', day: 'numeric', timeZone: 'UTC' })
function diaCorto(iso) {
  return DIA_CORTO.format(new Date(iso + 'T00:00:00Z')).replace('.', '')
}

function Leyenda() {
  const item = (cat, txt) => (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${PUNTO[cat]}`} />{txt}
    </span>
  )
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
      {item('cobro', 'Cobro')}
      {item('corte', 'Corte del dividendo')}
      {item('balance', 'Presenta balance')}
    </div>
  )
}

export default function CalendarioEventos({ positions = [], cerSeries, cobroCtx, eventosDelAnio = null, onClose, onVerActivo }) {
  // «Ocultar saldos»: lo que cobrarías se tapa, como en la agenda de Eventos
  // (pages/Events.jsx). Re-test A3, 29/10: sólo se había tapado la agenda.
  const { hidden: oculto } = usePrivacy()
  const hoy = hoyISO()
  // `eventosDelAnio`: los eventos que Eventos ya trajo, cuando su ventana es de
  // un año (1Y). Entonces son exactamente los mismos y no se vuelven a pedir
  // (cada pedido puede salir a buscar a Yahoo los tickers vencidos).
  const [pedidos, setPedidos] = useState(null)
  const backend = eventosDelAnio || pedidos
  const [error, setError] = useState(false)
  const [filtro, setFiltro] = useState('todo')
  const [idxMes, setIdxMes] = useState(0)
  const [diaElegido, setDiaElegido] = useState(null)

  useEffect(() => {
    if (eventosDelAnio) return undefined
    let vivo = true
    api.get('/events/portfolio?days=365')
      .then(r => { if (vivo) setPedidos(r?.events || []) })
      .catch(() => { if (vivo) { setPedidos([]); setError(true) } })
    return () => { vivo = false }
  }, [eventosDelAnio])

  const todos = useMemo(() => {
    if (backend == null) return []
    const bonos = upcomingBondEvents(positions, { windowDays: 365, cerSeries })
    return mergeEvents(bonos, normalizeBackendEvents(backend))
  }, [backend, positions, cerSeries])

  const eventos = useMemo(() => eventosDelCalendario(todos, { hoy, filtro }), [todos, hoy, filtro])
  // Los meses salen de TODOS los eventos, no de los filtrados: cambiar el filtro
  // no te saca del mes en que estás.
  const meses = useMemo(() => mesesDelCalendario(hoy, eventosDelCalendario(todos, { hoy })), [todos, hoy])
  const { anio, mes } = meses[Math.min(idxMes, meses.length - 1)]
  const semanas = useMemo(() => semanasDelMes(anio, mes), [anio, mes])
  const dias = useMemo(() => porDia(eventos), [eventos])
  const prefijo = `${anio}-${String(mes).padStart(2, '0')}`
  const lista = diaElegido
    ? (dias.get(diaElegido) || [])
    : eventos.filter(e => e.eventDate.startsWith(prefijo))

  // El corte de un dividendo lleva monto sólo si de esa empresa no se conoce
  // todavía la fecha de pago: si no, el mismo dividendo aparecería dos veces.
  const conPago = useMemo(() => new Set(todos.filter(e => e.eventType === 'payment_date').map(e => e.ticker)), [todos])
  function monto(ev) {
    const cat = categoriaDe(ev.eventType)
    if (cat === 'balance' || (cat === 'corte' && conPago.has(ev.ticker))) return null
    const c = eventCobro(ev, cobroCtx)
    return c?.amount > 0 ? c : null
  }

  function irAMes(i) {
    setIdxMes(i)
    setDiaElegido(null)
  }

  return (
    <Modal title="Calendario de tu cartera" onClose={onClose} wide>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1">
            <button
              onClick={() => irAMes(idxMes - 1)}
              disabled={idxMes === 0}
              aria-label="Mes anterior"
              className="p-1.5 rounded text-ink-2 hover:text-ink-0 hover:bg-bg-2 disabled:opacity-30 disabled:hover:bg-transparent"
            ><ChevronLeft size={16} /></button>
            <p className="text-sm font-semibold text-ink-0 w-36 text-center tabular">{nombreDelMes(anio, mes)}</p>
            <button
              onClick={() => irAMes(idxMes + 1)}
              disabled={idxMes >= meses.length - 1}
              aria-label="Mes siguiente"
              className="p-1.5 rounded text-ink-2 hover:text-ink-0 hover:bg-bg-2 disabled:opacity-30 disabled:hover:bg-transparent"
            ><ChevronRight size={16} /></button>
          </div>
          <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Qué mostrar">
            {FILTROS.map(f => (
              <button
                key={f.id}
                role="tab"
                aria-selected={filtro === f.id}
                onClick={() => { setFiltro(f.id); setDiaElegido(null) }}
                className={`text-xs px-3 py-1.5 rounded-full border transition ${
                  filtro === f.id
                    ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40 font-semibold'
                    : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3'
                }`}
              >{f.label}</button>
            ))}
          </div>
        </div>

        <Leyenda />

        {/* El ALTO de todo lo que sigue es fijo —seis semanas y una lista de alto
            fijo con su propia barra—, también mientras carga: si cambiara de un
            mes a otro, la ventana se volvería a centrar y la flecha de "mes
            siguiente" se correría de debajo del mouse. */}
        <div className="flex flex-col gap-1">
            <div className="grid grid-cols-7 gap-1">
              {DIAS_SEMANA.map((d, i) => (
                <div key={i} className="text-center text-xs text-ink-3 font-medium">{d}</div>
              ))}
            </div>
            {semanas.map((sem, i) => (
              <div key={i} className="grid grid-cols-7 gap-1">
                {sem.map((dia, j) => {
                  if (!dia) return <div key={j} className="min-h-12 sm:min-h-20" />
                  const del = dias.get(dia) || []
                  const pasado = dia < hoy
                  const elegido = diaElegido === dia
                  return (
                    <button
                      key={j}
                      onClick={() => setDiaElegido(elegido ? null : dia)}
                      disabled={!del.length}
                      aria-label={`${dia}: ${del.length ? del.map(e => `${e.ticker} ${rotuloDe(e.eventType)}`).join(', ') : 'sin eventos'}`}
                      className={`min-h-12 sm:min-h-20 rounded border p-1 flex flex-col items-stretch gap-0.5 text-left transition-colors ${
                        elegido ? 'bg-bg-3 border-line-3' : 'border-line'
                      } ${del.length ? 'hover:bg-bg-2 cursor-pointer' : 'cursor-default'} ${pasado ? 'opacity-40' : ''}`}
                    >
                      <span className={`text-xs tabular ${dia === hoy ? 'text-ink-0 font-semibold underline underline-offset-2' : 'text-ink-2'}`}>
                        {Number(dia.slice(8))}
                      </span>
                      {/* Teléfono: un puntito por evento. */}
                      <span className="flex sm:hidden flex-wrap gap-0.5">
                        {del.slice(0, 4).map((e, k) => (
                          <span key={k} className={`w-1.5 h-1.5 rounded-full ${PUNTO[categoriaDe(e.eventType)]}`} />
                        ))}
                      </span>
                      {/* Compu: el ticker. */}
                      <span className="hidden sm:flex flex-col gap-0.5 min-w-0">
                        {del.slice(0, 2).map((e, k) => (
                          <span key={k} className={`text-[10px] leading-tight px-1 py-0.5 rounded-sm truncate ${CHIP[categoriaDe(e.eventType)]}`}>
                            {e.ticker}
                          </span>
                        ))}
                        {del.length > 2 && <span className="text-[10px] text-ink-2">+{del.length - 2} más</span>}
                      </span>
                    </button>
                  )
                })}
              </div>
            ))}
        </div>

        <div className="flex flex-col">
            <div className="flex items-center justify-between gap-2 pb-2">
              <p className="text-sm font-semibold text-ink-0">
                {diaElegido ? `El ${diaCorto(diaElegido)}` : `En ${nombreDelMes(anio, mes).split(' ')[0].toLowerCase()}`}
              </p>
              {diaElegido && (
                <button onClick={() => setDiaElegido(null)} className="text-xs text-rendi-accent hover:underline">
                  Ver todo el mes
                </button>
              )}
            </div>
            <div className="h-40 sm:h-44 overflow-y-auto flex flex-col">
            {backend == null && <p className="text-sm text-ink-2 py-2">Buscando las fechas de tu cartera…</p>}
            {backend != null && !lista.length && (
              <p className="text-sm text-ink-2 py-2">
                {error ? 'No pudimos traer las fechas de tus empresas. Probá de nuevo en un rato.'
                  : 'No hay fechas conocidas este mes.'}
              </p>
            )}
            {lista.map(ev => {
              const m = monto(ev)
              const aConfirmar = ev.eventType === 'earnings' && !ev.confirmed
              return (
                <button
                  key={`${ev.ticker}-${ev.eventType}-${ev.eventDate}`}
                  onClick={() => onVerActivo?.(ev.ticker)}
                  className="grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-center gap-3 py-2 border-t border-line text-left hover:bg-bg-2 rounded-sm px-1"
                >
                  <span className="text-xs text-ink-2 tabular">{diaCorto(ev.eventDate)}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${PUNTO[categoriaDe(ev.eventType)]}`} />
                      <span className="text-sm font-semibold text-ink-0">{ev.ticker}</span>
                    </span>
                    <span className="block text-xs text-ink-2 truncate">
                      {rotuloDe(ev.eventType)}
                      {aConfirmar && ' · fecha estimada'}
                      {categoriaDe(ev.eventType) === 'corte' && ' · tenelo antes de este día para cobrarlo'}
                    </span>
                  </span>
                  <span className="text-right">
                    {m && (
                      <>
                        <span className="block text-sm font-semibold text-ink-0 tabular">
                          {oculto ? OCULTO : fmtMoney(m.amount, m.currency || 'USD', { decimals: (m.currency || 'USD') === 'ARS' ? 0 : 2 })}
                        </span>
                        <span className="block text-[10px] text-ink-2">
                          {ev.eventType.startsWith('bond_') ? 'según cronograma' : 'antes de impuestos'}
                        </span>
                      </>
                    )}
                  </span>
                </button>
              )
            })}
            </div>
        </div>

        <p className="text-xs text-ink-2 leading-relaxed">
          Están sólo las fechas que ya se conocen: las empresas anuncian su próximo balance y su próximo dividendo unas semanas antes, así que más adelante el calendario se va llenando. Los cupones de los bonos salen de su cronograma.
        </p>
      </div>
    </Modal>
  )
}
