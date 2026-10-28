// TusSenales — la pestaña «Tus señales» de Mercado → Novedades (pieza 15):
// «Qué cambió esta semana en lo tuyo».
// ════════════════════════════════════════════════════════════════════════════
// Tres tarjetas arriba (cambios en lo que tenés, en tu watchlist y el % de tu
// plata en tendencia alcista con el de la semana pasada), los filtros Todo /
// Lo que tenés / Watchlist, la lista agrupada por día con «Ver gráfico» (abre
// la ficha) y cómo te llega el resumen de los sábados.
//
// Una sola pieza para compu y celular (R6): en compu la preferencia va en una
// columna al costado; en celular, abajo de la lista. Los datos y las palabras
// vienen armados de GET /api/tus-senales (backend/senales_semana.py, la misma
// cuenta que el mail); utils/tusSenales.js sólo filtra y agrupa.
//
// Con «Ocultar saldos» no se muestran el % ni el peso de cada tenencia.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../utils/api'
import { usePrivacy } from '../contexts/PrivacyContext'
import { usePushNotifications } from '../hooks/usePushNotifications'
import AvisoNotificaciones from './AvisoNotificaciones'
import {
  FILTROS, CANALES, NO_ES_RECOMENDACION, filtrar, porDia, tarjetas, deQuien, boton, rutaDeFicha,
} from '../utils/tusSenales'

const PASTILLA = {
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

function Tarjeta({ t, children }) {
  return (
    <div className="bg-bg-1 border border-line rounded-xl px-4 py-3.5 flex flex-col gap-0.5 min-w-0">
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className="text-[22px] sm:text-[24px] font-semibold tabular text-ink-0 leading-tight flex flex-wrap items-baseline gap-x-2">
        <span>{t.valor}</span>
        {children}
      </div>
      <div className="text-[13px] text-ink-1 leading-snug">{t.texto}</div>
    </div>
  )
}

function Cambio({ s, hidden, onVer }) {
  return (
    <li className="flex flex-col sm:flex-row sm:items-start gap-2.5 sm:gap-3.5 py-3 border-t border-line/60 first:border-t-0">
      <span className={`self-start inline-block text-[12px] font-medium rounded-full px-2.5 py-1 whitespace-nowrap sm:min-w-[150px] sm:text-center ${PASTILLA[s.tono] || PASTILLA.adx}`}>
        {s.etiqueta}
      </span>
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        <p className="text-[14px] leading-snug text-ink-0">
          <b className="font-semibold">{s.asset}</b> {s.texto}
        </p>
        {s.extra && <p className="text-[13px] leading-snug text-ink-1">{s.extra}</p>}
        {s.tesis && <p className="text-[13px] leading-snug text-ink-1">Tu tesis: «{s.tesis}»</p>}
        <p className={`text-[12px] ${s.tenes ? 'text-data-violet' : 'text-ink-2'}`}>{deQuien(s, hidden)}</p>
      </div>
      <button type="button" onClick={() => onVer(s)}
        className="self-start flex-none text-[13px] font-medium text-ink-1 bg-bg-2/60 border border-line rounded-full px-3.5 py-1.5 min-h-[34px] hover:text-ink-0 hover:border-rendi-accent/40 transition">
        {boton(s)}
      </button>
    </li>
  )
}

/** ¿Cómo te llega el resumen de los sábados? Elegir notificación pide el
 *  permiso del navegador en el mismo toque (como el formulario de Alertas). */
function Preferencia({ canal, onCambiar, guardando }) {
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
    <section aria-label="El resumen de los sábados" className="bg-bg-1 border border-line rounded-xl px-4 py-3.5 flex flex-col gap-2.5">
      <div className="text-[12px] text-ink-2 font-medium">Lo mismo, los sábados, por mail o notificación</div>
      <div className="text-[14px] text-ink-0 font-medium">¿Cómo te llega?</div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Cómo te llega el resumen">
        {CANALES.map(c => (
          <Chip key={c.id} activo={canal === c.id} disabled={guardando} onClick={() => elegir(c.id)}>{c.label}</Chip>
        ))}
      </div>
      <p className="text-[13px] text-ink-1 leading-snug">
        Sábados a las 10:00. Si en la semana no cambió nada, no te escribimos.
      </p>
      {conPush && push?.motivo && (
        <AvisoNotificaciones motivo={push.motivo} plataforma={push.plataforma} origen="tus-senales" />
      )}
    </section>
  )
}

export default function TusSenales() {
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  const [datos, setDatos] = useState(null)
  const [error, setError] = useState(false)
  const [filtro, setFiltro] = useState('todo')
  const [guardando, setGuardando] = useState(false)
  const [errorCanal, setErrorCanal] = useState(null)

  useEffect(() => {
    let vivo = true
    api.get('/tus-senales')
      .then(r => { if (vivo) setDatos(r) })
      .catch(() => { if (vivo) setError(true) })
    return () => { vivo = false }
  }, [])

  const cambiarCanal = (canal) => {
    const antes = datos?.canal
    setDatos(d => ({ ...d, canal }))
    setGuardando(true)
    setErrorCanal(null)
    api.put('/tus-senales/canal', { canal })
      .catch(() => { setDatos(d => ({ ...d, canal: antes })); setErrorCanal('No pudimos guardarlo. Probá de nuevo.') })
      .finally(() => setGuardando(false))
  }

  return (
    <TusSenalesVista datos={datos} error={error} hidden={hidden} filtro={filtro} onFiltro={setFiltro}
      onVer={(x) => navigate(rutaDeFicha(x))} onCanal={cambiarCanal} guardando={guardando} errorCanal={errorCanal} />
  )
}

/** Lo que se dibuja, sin pedidos: así lo prueba TusSenales.render.test.jsx. */
export function TusSenalesVista({ datos, error, hidden, filtro, onFiltro, onVer, onCanal, guardando, errorCanal }) {
  const dias = useMemo(() => porDia(filtrar(datos?.senales, filtro)), [datos, filtro])
  const t = useMemo(() => tarjetas(datos, hidden), [datos, hidden])

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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[0, 1, 2].map(i => <div key={i} className="h-24 rounded-xl bg-bg-2/40 border border-line esqueleto" />)}
        </div>
        <div className="h-64 rounded-xl bg-bg-2/40 border border-line esqueleto" />
      </div>
    )
  }
  return (
    <div className="flex flex-col lg:flex-row gap-4 lg:gap-5">
      <div className="flex-1 min-w-0 flex flex-col gap-3">
        <div>
          <h2 className="text-[18px] sm:text-[20px] font-semibold text-ink-0">Qué cambió esta semana en lo tuyo</h2>
          <p className="text-[13px] text-ink-2 mt-0.5">Los últimos 7 días, contados desde hoy. Medido en dólares.</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Tarjeta t={t.tenes} />
          <Tarjeta t={t.watch} />
          <Tarjeta t={t.plata}>
            {t.plata.antes && (
              <span className={`text-[13px] font-medium ${t.plata.tono === 'pos' ? 'text-rendi-pos' : t.plata.tono === 'neg' ? 'text-rendi-neg' : 'text-ink-2'}`}>
                {t.plata.antes}
              </span>
            )}
          </Tarjeta>
        </div>

        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Qué mostrar">
          {FILTROS.map(f => <Chip key={f.id} activo={filtro === f.id} onClick={() => onFiltro(f.id)}>{f.label}</Chip>)}
        </div>

        <section aria-label="Cambios de la semana" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-1">
          {dias.length === 0 ? (
            <p className="py-5 text-[14px] text-ink-1">
              {filtro === 'watchlist' ? 'Esta semana no cambió nada en tu watchlist.'
                : filtro === 'tenes' ? 'Esta semana no cambió nada en lo que tenés.'
                  : 'Esta semana no cambió nada en lo tuyo ni en tu watchlist.'}
            </p>
          ) : dias.map(d => (
            <div key={d.fecha}>
              <h3 className="text-[12px] text-ink-2 font-semibold pt-3 pb-1">{d.dia}</h3>
              <ul>
                {d.items.map((s, i) => (
                  <Cambio key={`${s.asset}-${s.local}-${s.tipo}-${i}`} s={s} hidden={hidden} onVer={onVer} />
                ))}
              </ul>
            </div>
          ))}
        </section>
        <p className="text-[12px] text-ink-3 leading-relaxed">{NO_ES_RECOMENDACION}</p>
      </div>

      <aside className="lg:w-[340px] lg:flex-none flex flex-col gap-2">
        <Preferencia canal={datos.canal} onCambiar={onCanal} guardando={guardando} />
        {errorCanal && <p role="alert" className="text-[13px] text-rendi-neg">{errorCanal}</p>}
      </aside>
    </div>
  )
}
