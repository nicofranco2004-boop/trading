// TusSenales — la pestaña «Señales de la semana» de Análisis técnico (pieza
// 15, se mudó de Novedades el 28/10): «Qué cambió esta semana en lo tuyo».
// ════════════════════════════════════════════════════════════════════════════
// Desde el 30/10 se ve como Novedades → Eventos (lienzo «4 · Señales de la
// semana», aprobado por Nico):
//   · la franja de 3 números: cambios de la semana (en tu cartera / en tu
//     watchlist), a favor · en contra con su barrita, y el % de tu cartera en
//     tendencia alcista de largo plazo con el cambio contra la semana pasada;
//   · las barras por día (una por día, coloreadas por tipo, con el cartelito
//     de qué pasó ese día), como la «Distribución» de Eventos;
//   · los filtros Todo / Tu cartera / Watchlist y la agenda: el día a la
//     izquierda, una línea vertical y cada cambio como tarjeta (como
//     `EventAgenda`/`AgendaCard` de pages/Events.jsx), con «Ver el gráfico»,
//     la campanita «Avisame» y «hace 2 días»;
//   · al costado, el resumen del sábado y «¿Querés enterarte en el momento?».
//
// Una sola pieza para compu y celular (R6): en compu lo del costado va en una
// columna; en celular, abajo de la agenda. Los datos y las palabras vienen
// armados de GET /api/tus-senales (backend/senales_semana.py, la misma cuenta
// que el mail); utils/tusSenales.js sólo filtra, ordena y agrupa. El servidor
// manda los últimos 7 días: las barras dibujan esos 7.
//
// Con «Ocultar saldos» no se muestran el % ni el peso de cada tenencia, y el
// orden de cada día no es por peso (`enOrden`).

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mail } from 'lucide-react'
import AssetLogo from './AssetLogo'
import { api } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import { clicNormal } from '../utils/clicNormal'
import { usePushNotifications } from '../hooks/usePushNotifications'
import AvisoNotificaciones from './AvisoNotificaciones'
import { BotonAvisame, senalDelCambio } from './alerts/AvisameTecnico'
import {
  FILTROS, CANALES, NO_ES_RECOMENDACION, filtrar, porDia, franja, deQuien, boton, rutaDeFicha,
  TITULO_CAMBIOS, QUE_ES_ESTA_SEMANA, enOrden, diasDeLasBarras, colorDelCambio, ETIQUETA_CORTA,
  hace, detalleDe, quienCorto, textoDelResumen,
} from '../utils/tusSenales'

export const PASTILLA = {
  pos: 'text-rendi-pos bg-rendi-pos/10',
  neg: 'text-rendi-neg bg-rendi-neg/10',
  rsi: 'text-rendi-warn bg-rendi-warn/10',
  adx: 'text-data-blue bg-data-blue/10',
}

function Chip({ activo, onClick, children, disabled }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-pressed={activo}
      className={`inline-flex items-center text-[13px] font-medium px-3.5 py-1.5 min-h-[34px] rounded-full border transition disabled:opacity-60 ${
        activo
          ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
          : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0'
      }`}>
      {children}
    </button>
  )
}

/** Un cambio, como en la lista de la semana. Lo usa también el Panorama, que
 *  le pasa `avisos` (useAvisosTecnicos) para la campanita «Avisame» de cada
 *  renglón; sin `avisos`, sólo «Ver el gráfico». */
export function Cambio({ s, hidden, onVer, avisos = null }) {
  const aviso = avisos ? senalDelCambio(s) : null
  return (
    // Celular: la pastilla arriba y el botón al costado del texto; compu: en fila.
    <li className="grid grid-cols-[1fr_auto] sm:grid-cols-[150px_1fr_auto] gap-x-3 sm:gap-x-3.5 gap-y-1.5 items-start py-3 border-t border-line/60 first:border-t-0">
      <span className={`col-span-2 sm:col-span-1 justify-self-start sm:justify-self-stretch text-[12px] font-medium rounded-full px-2.5 py-1 whitespace-nowrap sm:text-center ${PASTILLA[s.tono] || PASTILLA.adx}`}>
        {s.etiqueta}
      </span>
      <div className="min-w-0 flex flex-col gap-1">
        <p className="text-[14px] leading-snug text-ink-0">
          <b className="font-semibold">{s.asset}</b> {s.texto}
        </p>
        {s.extra && <p className="text-[13px] leading-snug text-ink-1">{s.extra}</p>}
        {s.tesis && <p className="text-[13px] leading-snug text-ink-1">Tu tesis: «{s.tesis}»</p>}
        <p className={`text-[12px] ${s.tenes ? 'text-data-violet' : 'text-ink-2'}`}>{deQuien(s, hidden)}</p>
      </div>
      {/* Con la campanita, en el celular los dos botones van abajo del texto:
          al costado le dejaban al texto media pantalla. */}
      <div className={`sm:self-start flex items-center gap-1.5 ${aviso ? 'col-span-2 sm:col-span-1 justify-self-start' : 'self-end'}`}>
        {/* Un link de verdad: se puede abrir en otra pestaña (D12). */}
        <a href={rutaDeFicha(s)} onClick={(e) => { if (clicNormal(e)) { e.preventDefault(); onVer(s) } }}
          className="text-[13px] font-medium text-ink-1 bg-bg-2/60 border border-line rounded-full px-3.5 py-1.5 min-h-[34px] inline-flex items-center whitespace-nowrap hover:text-ink-0 hover:border-rendi-accent/40 transition">
          {boton(s)}
        </a>
        {aviso && (
          <BotonAvisame soloIcono avisos={avisos} asset={s.asset} accionLocal={!!s.local} moneda="usd" {...aviso} />
        )}
      </div>
    </li>
  )
}

/** El resumen del sábado: cómo te llega, como opciones de radio (lienzo).
 *  Elegir notificación pide el permiso del navegador en el mismo toque (como
 *  el formulario de Alertas). */
function Preferencia({ canal, proximo, onCambiar, guardando }) {
  const push = usePushNotifications()
  const conPush = canal === 'push' || canal === 'ambos'
  const elegir = (c) => {
    if (c === canal) return
    if ((c === 'push' || c === 'ambos') && push && !push.subscribed && !push.motivo) {
      push.subscribe()?.catch(() => {})
    }
    onCambiar(c)
  }
  return (
    <section aria-labelledby="senales-resumen-titulo" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-2.5">
      <div className="flex items-center gap-2.5">
        <span className="w-9 h-9 rounded-lg bg-data-violet/12 text-data-violet grid place-items-center flex-none">
          <Mail size={17} strokeWidth={2} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h2 id="senales-resumen-titulo" className="text-[15px] font-semibold text-ink-0">El resumen del sábado</h2>
          <p className="text-[12px] text-ink-2 leading-snug">Un mail o una notificación con lo de esta pantalla.</p>
        </div>
      </div>
      <div className="flex flex-col gap-1.5" role="radiogroup" aria-labelledby="senales-resumen-titulo">
        {CANALES.map(c => {
          const on = canal === c.id
          return (
            <button key={c.id} type="button" role="radio" aria-checked={on} disabled={guardando} onClick={() => elegir(c.id)}
              className={`flex items-center gap-2.5 text-left text-[13.5px] px-3 py-2.5 min-h-[40px] rounded-lg border transition disabled:opacity-60 ${
                on ? 'border-data-violet bg-data-violet/10 text-ink-0' : 'border-line bg-bg-1 text-ink-1 hover:text-ink-0'}`}>
              <span aria-hidden="true" className={`w-3.5 h-3.5 rounded-full flex-none box-border ${on ? 'border-4 border-data-violet' : 'border border-ink-3'}`} />
              {c.label}
            </button>
          )
        })}
      </div>
      <p className="text-[13px] text-ink-1 leading-snug">
        {textoDelResumen(canal, proximo)} Si en la semana no cambió nada, no te mandamos nada.
      </p>
      {conPush && push?.motivo && (
        <AvisoNotificaciones motivo={push.motivo} plataforma={push.plataforma} origen="tus-senales" />
      )}
    </section>
  )
}

/**
 * Lo que trae GET /api/tus-senales y cómo se cambia el canal del resumen de los
 * sábados. Lo usan esta pestaña y el Panorama de Análisis técnico: la página lo
 * pide una vez y se lo pasa a los dos. → { datos, error, cambiarCanal,
 * guardando, errorCanal }
 */
export function useTusSenales({ pedir = true } = {}) {
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [errorCanal, setErrorCanal] = useState(null)

  useEffect(() => {
    if (!pedir) return undefined
    let vivo = true
    api.get('/tus-senales')
      .then(r => { if (vivo) setDatos(r) })
      .catch(() => { if (vivo) setError(true) })
    return () => { vivo = false }
  }, [pedir])

  const cambiarCanal = (canal) => {
    const antes = datos?.canal
    setDatos(d => ({ ...d, canal }))
    setGuardando(true)
    setErrorCanal(null)
    api.put('/tus-senales/canal', { canal })
      .catch(() => { setDatos(d => ({ ...d, canal: antes })); setErrorCanal('No pudimos guardar el cambio. Probá de nuevo.') })
      .finally(() => setGuardando(false))
  }
  return { datos, error, cambiarCanal, guardando, errorCanal }
}

/** La pestaña con sus propios datos (`senales`: lo de useTusSenales, si la
 *  página ya lo pidió). */
export default function TusSenales({ senales = null }) {
  const propios = useTusSenales({ pedir: !senales })
  const s = senales || propios
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  const [filtro, setFiltro] = useState('todo')
  return (
    <TusSenalesVista datos={s.datos} error={s.error} hidden={hidden} filtro={filtro} onFiltro={setFiltro}
      onVer={(x) => navigate(rutaDeFicha(x))} onCanal={s.cambiarCanal} guardando={s.guardando} errorCanal={s.errorCanal} />
  )
}

// El color de cada tipo: la barra, el cuadradito del cartel y la etiqueta.
const COLOR = {
  pos: { barra: 'bg-rendi-pos', pastilla: 'text-rendi-pos bg-rendi-pos/10' },
  neg: { barra: 'bg-rendi-neg', pastilla: 'text-rendi-neg bg-rendi-neg/10' },
  azul: { barra: 'bg-data-blue', pastilla: 'text-data-blue bg-data-blue/10' },
}
const LEYENDA = [['pos', 'a favor'], ['neg', 'en contra'], ['azul', 'máximo / fuerza']]
const DIA_CORTO = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']
const DIA_LARGO = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const fechaUTC = (iso) => new Date(`${iso}T00:00:00Z`)

/** Un número de la franja de arriba. */
function Numero({ titulo, valor, tonoValor = 'text-ink-0', children, borde }) {
  return (
    <div className={`px-4 sm:px-[18px] py-3.5 flex flex-col gap-0.5 min-w-0 ${borde ? 'border-b sm:border-b-0 sm:border-r border-line' : ''}`}>
      <span className="text-[12px] text-ink-2 font-medium">{titulo}</span>
      <span className={`text-[24px] font-semibold tabular leading-tight ${tonoValor}`}>{valor}</span>
      {children}
    </div>
  )
}

/** Los 3 números de arriba (como la franja de Eventos). */
function Franja({ f }) {
  const { cambios, lados, plata } = f
  const conLado = lados.favor + lados.contra
  return (
    <section aria-label="La semana en números" className="bg-bg-1 border border-line rounded-xl grid grid-cols-1 sm:grid-cols-3">
      <Numero titulo={cambios.titulo} valor={cambios.valor} borde>
        <span className="text-[12px] text-ink-2 leading-snug">{cambios.texto}</span>
      </Numero>
      <Numero titulo={lados.titulo} borde valor={
        <><span className="text-rendi-pos">{lados.favor}</span> <span className="text-ink-3" aria-hidden="true">·</span><span className="sr-only">a favor,</span> <span className="text-rendi-neg">{lados.contra}</span><span className="sr-only">en contra</span></>
      }>
        {conLado > 0 && (
          <span className="flex gap-0.5 mt-1 h-[5px]" aria-hidden="true">
            {lados.favor > 0 && <span className="rounded-xs bg-rendi-pos" style={{ flex: lados.favor }} />}
            {lados.contra > 0 && <span className="rounded-xs bg-rendi-neg" style={{ flex: lados.contra }} />}
          </span>
        )}
        <span className="text-[12px] text-ink-2 leading-snug mt-0.5">A favor: el precio subió. En contra: bajó.</span>
      </Numero>
      <Numero titulo={plata.titulo} valor={plata.valor}
        tonoValor={plata.cambio?.tono === 'pos' ? 'text-rendi-pos' : plata.cambio?.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-0'}>
        {plata.cambio && (
          <span className={`text-[12px] font-medium ${plata.cambio.tono === 'pos' ? 'text-rendi-pos' : plata.cambio.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-2'}`}>
            {plata.cambio.texto}
          </span>
        )}
        <span className="text-[12px] text-ink-2 leading-snug">{plata.texto}</span>
      </Numero>
    </section>
  )
}

/** Las barras por día, como la «Distribución» de Eventos: una por día, un
 *  pedacito por cambio con el color de su tipo, y el cartel de qué pasó al
 *  pasar el mouse o al tocarla. Con más de 7 días (cuando el servidor los
 *  mande), la semana actual va resaltada. */
function BarrasPorDia({ dias }) {
  const max = Math.max(2, ...dias.map(d => d.items.length))
  const largo = dias.length > 7
  const ultimo = dias.length - 1
  const etiqueta = (d) => `${d.dia}: ${d.items.length ? d.items.map(s => `${s.asset} ${s.corta || s.etiqueta}`).join('; ') : 'sin cambios'}`
  return (
    <section aria-label="Cambios por día" className="bg-bg-1 border border-line rounded-xl px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 mb-2.5">
        <h2 className="text-[12px] text-ink-2 font-medium">Cambios por día · últimos {dias.length} días</h2>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-ink-2">
          {LEYENDA.map(([c, t]) => (
            <li key={c} className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-xs ${COLOR[c].barra}`} aria-hidden="true" />{t}</li>
          ))}
        </ul>
      </div>
      <div className="relative">
        <ol className="flex items-end gap-[3px] h-16">
          {dias.map((d, i) => {
            const semana = !largo || i > ultimo - 7
            // El cartel no se sale de la tarjeta en las puntas.
            const lugar = i < 2 ? 'left-0' : i > ultimo - 2 ? 'right-0' : 'left-1/2 -translate-x-1/2'
            return (
              <li key={d.fecha} className="flex-1 min-w-0 h-full relative group">
                {/* Tocarla muestra el cartel (el celular no tiene «pasar el
                    mouse») y lleva al día en la agenda. */}
                <button type="button" aria-label={etiqueta(d)} disabled={!d.items.length}
                  onClick={() => document.getElementById(`senales-dia-${d.fecha}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })}
                  className={`w-full h-full mx-auto ${largo ? '' : 'max-w-[44px]'} flex flex-col justify-end gap-0.5 rounded-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-data-violet ${semana ? '' : 'opacity-55'}`}>
                  {d.items.length === 0
                    ? <span className="w-full h-[3px] rounded-xs bg-line" />
                    : d.items.map((s, k) => (
                      <span key={k} className={`w-full rounded-xs ${COLOR[colorDelCambio(s)].barra} opacity-85 group-hover:opacity-100`}
                        style={{ height: `${(100 / max) - 3}%` }} />
                    ))}
                </button>
                {d.items.length > 0 && (
                  <div aria-hidden="true" className={`pointer-events-none absolute bottom-full mb-1.5 ${lugar} hidden group-hover:block group-focus-within:block z-20 w-max max-w-[260px] bg-bg-3 border border-line-2 rounded-lg px-2.5 py-1.5 shadow-lg`}>
                    <div className="text-[11.5px] text-ink-2 mb-1">{DIA_LARGO[fechaUTC(d.fecha).getUTCDay()]} {d.dia.split(' ')[1]}</div>
                    <div className="flex flex-col gap-0.5">
                      {d.items.slice(0, 6).map((s, k) => (
                        <div key={k} className="flex items-start gap-1.5 text-[11.5px] leading-snug">
                          <span className={`mt-1 w-1.5 h-1.5 rounded-xs flex-none ${COLOR[colorDelCambio(s)].barra}`} />
                          <span><b className="font-semibold text-ink-0">{s.asset}</b> <span className="text-ink-2">{s.corta || s.etiqueta}</span></span>
                        </div>
                      ))}
                      {d.items.length > 6 && <div className="text-[11px] text-ink-2">y {d.items.length - 6} más</div>}
                    </div>
                  </div>
                )}
              </li>
            )
          })}
        </ol>
        {largo && (
          <div aria-hidden="true" className="pointer-events-none absolute right-0 -top-1 -bottom-1 border border-dashed border-data-violet/45 bg-data-violet/5 rounded"
            style={{ left: `calc(100% * ${dias.length - 7} / ${dias.length})` }} />
        )}
      </div>
      {/* Con los 7 días, el nombre de cada uno; con más, tres marcas como el lienzo. */}
      {largo ? (
        <div className="flex justify-between mt-1.5 text-[12px] text-ink-2 font-medium" aria-hidden="true">
          <span>hace {dias.length} días</span><span>hace {Math.round(dias.length / 2)} días</span><span className="text-data-violet">esta semana</span>
        </div>
      ) : (
        <div className="flex gap-[3px] mt-1.5 text-[11.5px] text-ink-2 font-medium" aria-hidden="true">
          {dias.map((d, i) => (
            <span key={d.fecha} className={`flex-1 min-w-0 text-center truncate ${i === ultimo ? 'text-data-violet' : ''}`}>
              {i === ultimo ? 'hoy' : DIA_CORTO[fechaUTC(d.fecha).getUTCDay()]}
            </span>
          ))}
        </div>
      )}
    </section>
  )
}

/** Un cambio de la agenda, como la tarjeta de un evento de Novedades. */
function TarjetaCambio({ s, hidden, hasta, onVer, avisos }) {
  const aviso = avisos ? senalDelCambio(s) : null
  const c = COLOR[colorDelCambio(s)]
  const cuando = hace(s.fecha, hasta)
  return (
    <li className="bg-bg-1 border border-line rounded-xl px-3.5 sm:px-4 py-3 grid items-center gap-x-3 gap-y-2 grid-cols-[auto_minmax(0,1fr)] lg:grid-cols-[auto_minmax(0,1fr)_auto]">
      <AssetLogo asset={s.asset} size={36} className="self-start lg:self-center" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h4 className="text-[14px] font-semibold text-ink-0 leading-snug">{s.asset} {s.corta || s.etiqueta?.toLowerCase()}</h4>
          <span className={`text-[11px] font-semibold rounded px-1.5 py-0.5 whitespace-nowrap ${c.pastilla}`}>{ETIQUETA_CORTA[s.tipo] || s.etiqueta}</span>
          {/* En el celular «hace 2 días» va acá: abajo, con los dos botones, no entraba. */}
          {cuando && <span className="lg:hidden text-[11.5px] font-bold text-data-violet bg-data-violet/12 rounded-full px-2.5 py-0.5 whitespace-nowrap">{cuando}</span>}
        </div>
        <p className="text-[12.5px] text-ink-2 mt-1 leading-snug">
          {detalleDe(s)}{' '}
          <b className={`font-semibold ${s.tenes ? 'text-data-violet' : 'text-ink-2'}`}>· {quienCorto(s, hidden)}</b>
        </p>
        {s.extra && <p className="text-[12.5px] text-ink-1 mt-1 leading-snug">{s.extra}</p>}
        {s.tesis && <p className="text-[12.5px] text-ink-1 mt-1 leading-snug">Tu tesis: «{s.tesis}»</p>}
      </div>
      {/* Debajo de `lg`, los botones van en una segunda línea alineados con el
          texto (como AgendaCard): al costado le dejaban al título 0 px. */}
      <div className="col-start-2 lg:col-start-3 lg:row-start-1 flex flex-wrap items-center gap-2">
        {/* Un link de verdad: se puede abrir en otra pestaña (D12). */}
        <a href={rutaDeFicha(s)} onClick={(e) => { if (clicNormal(e)) { e.preventDefault(); onVer(s) } }}
          className="text-[12.5px] font-medium text-ink-1 bg-bg-2/60 border border-line rounded-full px-3 py-1.5 min-h-[34px] inline-flex items-center whitespace-nowrap hover:text-ink-0 hover:border-rendi-accent/40 transition">
          {boton(s)}
        </a>
        {aviso && <BotonAvisame soloIcono avisos={avisos} asset={s.asset} accionLocal={!!s.local} moneda="usd" {...aviso} />}
        {cuando && (
          <span className="hidden lg:inline text-[11.5px] font-bold text-data-violet bg-data-violet/12 rounded-full px-2.5 py-1 whitespace-nowrap">{cuando}</span>
        )}
      </div>
    </li>
  )
}

/** La agenda: el día a la izquierda, una línea vertical y las tarjetas (como
 *  `EventAgenda` de Novedades). El día más nuevo va en violeta. */
function Agenda({ dias, hidden, hasta, onVer, avisos }) {
  return (
    <div>
      {dias.map((g, gi) => {
        const f = fechaUTC(g.fecha)
        return (
          // minmax(0, 1fr): con `1fr` la columna medía lo que su texto más largo
          // y en el celular se salía de la pantalla (lo mismo que en Eventos).
          <section key={g.fecha} id={`senales-dia-${g.fecha}`} aria-label={g.dia} className="scroll-mt-20 grid gap-2.5 sm:gap-4 grid-cols-[40px_minmax(0,1fr)] sm:grid-cols-[76px_minmax(0,1fr)]">
            <div className="text-right pt-3.5" aria-hidden="true">
              {/* En el celular el día corto («MIÉ», como Eventos): el largo le comía lugar a la tarjeta. */}
              <div className={`text-[12px] font-bold uppercase ${gi === 0 ? 'text-data-violet' : 'text-ink-0'}`}>
                <span className="sm:hidden">{DIA_CORTO[f.getUTCDay()]}</span><span className="hidden sm:inline">{DIA_LARGO[f.getUTCDay()]}</span>
              </div>
              <div className="text-[11.5px] text-ink-2 tabular">{f.getUTCDate()} {MESES[f.getUTCMonth()]}</div>
            </div>
            <div className="relative border-l-2 border-line pl-3 sm:pl-4 pt-2 pb-5">
              <span aria-hidden="true" className={`absolute -left-[6px] top-[17px] w-2.5 h-2.5 rounded-full bg-bg-0 border-2 ${gi === 0 ? 'border-data-violet' : 'border-ink-2'}`} />
              <h3 className="sr-only">{g.dia}</h3>
              <ul className="flex flex-col gap-2.5">
                {g.items.map((s, i) => (
                  <TarjetaCambio key={`${s.asset}-${s.local}-${s.tipo}-${i}`} s={s} hidden={hidden} hasta={hasta} onVer={onVer} avisos={avisos} />
                ))}
              </ul>
            </div>
          </section>
        )
      })}
    </div>
  )
}

/** Lo que se dibuja, sin pedidos: así lo prueba TusSenales.render.test.jsx.
 *  `avisos`: lo de useAvisosTecnicos (la página lo pide), para las campanitas. */
export function TusSenalesVista({ datos, error, hidden, filtro, onFiltro, onVer, onCanal, guardando, errorCanal, avisos = null }) {
  const ordenadas = useMemo(() => enOrden(datos?.senales || [], hidden), [datos, hidden])
  const dias = useMemo(() => porDia(filtrar(ordenadas, filtro)), [ordenadas, filtro])
  const barras = useMemo(() => diasDeLasBarras(ordenadas, datos?.desde, datos?.hasta), [ordenadas, datos])
  const f = useMemo(() => franja(datos, hidden), [datos, hidden])
  const cuantos = useMemo(() => Object.fromEntries(FILTROS.map(x => [x.id, filtrar(ordenadas, x.id).length])), [ordenadas])

  if (error) {
    return (
      <div className="bg-bg-1 border border-line rounded-xl px-4 py-4 text-[14px] text-ink-1">
        No pudimos traer tus señales ahora. Probá recargar la página en un rato.
      </div>
    )
  }
  if (!datos) {
    return (
      <div className="flex flex-col gap-3" aria-label="Cargando tus señales">
        <div className="h-24 rounded-xl bg-bg-2/40 border border-line esqueleto" />
        <div className="h-28 rounded-xl bg-bg-2/40 border border-line esqueleto" />
        <div className="h-64 rounded-xl bg-bg-2/40 border border-line esqueleto" />
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col lg:flex-row lg:items-start gap-4 lg:gap-5">
        <div className="flex-1 min-w-0 flex flex-col gap-3.5">
          <Franja f={f} />
          {barras.length > 0 && <BarrasPorDia dias={barras} />}

          <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2 mt-1">
            <div className="min-w-0">
              <h2 className="text-[17px] sm:text-[18px] font-semibold text-ink-0">{TITULO_CAMBIOS}</h2>
              <p className="text-[13px] text-ink-2 mt-0.5">{QUE_ES_ESTA_SEMANA} Medido en dólares.</p>
            </div>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Qué mostrar">
              {FILTROS.map(x => (
                <Chip key={x.id} activo={filtro === x.id} onClick={() => onFiltro(x.id)}>
                  {x.label} <span className="tabular ml-1 opacity-80">· {cuantos[x.id]}</span>
                </Chip>
              ))}
            </div>
          </div>

          {dias.length === 0 ? (
            <p className="bg-bg-1 border border-line rounded-xl px-4 py-4 text-[14px] text-ink-1">
              {filtro === 'watchlist' ? 'Esta semana no cambió nada en tu watchlist.'
                : filtro === 'tenes' ? 'Esta semana no cambió nada en tu cartera.'
                  : 'Esta semana no cambió nada en tu cartera ni en tu watchlist.'}
            </p>
          ) : (
            <Agenda dias={dias} hidden={hidden} hasta={datos.hasta} onVer={onVer} avisos={avisos} />
          )}
        </div>

        <aside className="lg:w-[320px] lg:flex-none flex flex-col gap-3.5">
          <Preferencia canal={datos.canal} proximo={datos.proximo_resumen} onCambiar={onCanal} guardando={guardando} />
          {errorCanal && <p role="alert" className="text-[13px] text-rendi-neg">{errorCanal}</p>}
          <section aria-labelledby="senales-momento-titulo" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-2">
            <h2 id="senales-momento-titulo" className="text-[15px] font-semibold text-ink-0">¿Querés enterarte en el momento?</h2>
            <p className="text-[13px] text-ink-1 leading-relaxed">
              Una alerta técnica te avisa el mismo día en que pasa algo así, sin esperar al sábado.
            </p>
            <Link to="/alertas?tab=crear"
              className="self-start text-[13px] font-medium text-ink-1 bg-bg-2/60 border border-line rounded-full px-3.5 py-1.5 min-h-[34px] inline-flex items-center hover:text-ink-0 hover:border-rendi-accent/40 transition">
              Crear una alerta técnica
            </Link>
          </section>
        </aside>
      </div>
      <p className="text-[12px] text-ink-2 leading-relaxed">{NO_ES_RECOMENDACION}</p>
    </div>
  )
}
