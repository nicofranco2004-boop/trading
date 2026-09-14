// RendiAI — página de chat con la IA (/ai).
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza al drawer lateral (AICoachDrawer): tocar "Rendi AI" en el sidebar
// navega acá. Chat a pantalla completa estilo conversación centrada: topbar con
// la marca + chip de contexto + "Nueva conversación", mensajes con aire, input
// abajo. La lógica del chat (tiers, cuota, streaming, registrar operaciones)
// vive intacta en <AICoach fullHeight> — esta página solo arma el snapshot
// (mismo mecanismo que tenía el drawer) y pone el chrome.
//
// La pregunta inicial (✦ botones / onboarding) llega vía CoachDrawerContext:
// open(question) ahora navega acá y deja la pregunta en el contexto; la
// consumimos una sola vez y AICoach la auto-envía (autoAsk).

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Loader2, AlertCircle, Plus, Volume2, VolumeX } from 'lucide-react'
import AICoach from '../components/AICoach'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { clearChatSession } from '../utils/chatSession'
import { fetchAiSnapshot } from '../utils/aiSnapshot'
import { useVoz } from '../contexts/VozContext'

// Book-mode: AICoach exige un snapshot truthy para habilitar el envío; el
// backend lo IGNORA en este modo (arma el libro server-side). Ref estable
// para no re-disparar effects por identidad.
const BOOK_SNAPSHOT = {}

export default function RendiAI() {
  const { initialQuestion, consumeInitialQuestion } = useCoachDrawer()
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const { enabled: vozEnabled, setEnabled: setVozEnabled, status: vozStatus } = useVoz()
  const vozHablando = vozStatus === 'playing' || vozStatus === 'preparing'
  // Book-mode: el asesor en su propio nivel chatea sobre EL LIBRO — el
  // backend arma el contexto server-side e IGNORA el snapshot personal.
  // Acá: no fetcheamos la cartera (vacía) ni bloqueamos el chat si esos
  // fetches fallan, y el chrome habla del libro, no de "tu cartera" (audit:
  // decía "Viendo tu cartera · 0 posiciones" en la superficie estrella).
  const bookMode = user?.tier === 'advisor' && !clientCtx
  const [snapshot, setSnapshot] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const snapshotRef = useRef(null)
  const [refreshTick, setRefreshTick] = useState(0)
  // Remount de AICoach = conversación nueva. La conversación PERSISTE al
  // navegar (sessionStorage, ver utils/chatSession) — por eso acá, además del
  // remount, hay que BORRAR la persistida (sin eso el remount la restaura).
  const [convKey, setConvKey] = useState(0)
  // La pregunta inicial se consume UNA vez (sino un remount la re-enviaría).
  const autoAskRef = useRef(null)
  if (initialQuestion && autoAskRef.current == null) {
    autoAskRef.current = initialQuestion
    consumeInitialQuestion?.()
  }

  // Snapshot vivo de la cartera — mismo criterio que el drawer: primer fetch
  // con loader, refreshes en background sin tirar el chat.
  useEffect(() => {
    let cancelled = false
    if (bookMode) { setLoading(false); setError(null); return }
    if (!snapshotRef.current) setLoading(true)
    setError(null)
    fetchAiSnapshot()
      .then(snap => {
        if (cancelled) return
        snapshotRef.current = snap
        setSnapshot(snap)
        setLoading(false)
      })
      .catch(err => {
        if (cancelled) return
        if (!snapshotRef.current) setError(err?.message || 'No pudimos cargar el contexto de tu cartera.')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [refreshTick, bookMode])

  // El chat registró/deshizo una operación → refrescar snapshot en background.
  useEffect(() => {
    const onPortfolioChanged = () => setRefreshTick(t => t + 1)
    window.addEventListener('rendi:portfolio-changed', onPortfolioChanged)
    return () => window.removeEventListener('rendi:portfolio-changed', onPortfolioChanged)
  }, [])

  // 🔴 EL ALTO DE ESTA PÁGINA SE MIDE, NO SE ESCRIBE.
  //
  // Antes decía `h-dvh`: el alto ENTERO de la pantalla. Pero la página no
  // arranca arriba de todo — arriba hay una barra fija con el logo y, debajo,
  // la tira de cotizaciones. Medido en 375px: la página empezaba en y=93 y
  // medía 812, o sea terminaba en 905 sobre una pantalla de 812. El pie del
  // chat quedaba 29 px abajo del borde y tapado por la barra de navegación,
  // con el botón de enviar y el del micrófono a medio tapar.
  //
  // No se puede poner un número fijo porque ese alto CAMBIA: la tira de
  // cotizaciones, el aviso del free trial, la barra de contexto de cliente y
  // el cartel del modo demo aparecen o no según quién mire. Un `calc(100dvh -
  // 93px)` andaría para una combinación y mentiría para las otras cinco.
  //
  // Así que se mide dónde arranca la página de verdad y se le da lo que queda.
  // Se vuelve a medir al rotar el teléfono y al aparecer el teclado (los dos
  // disparan `resize`).
  const cajaRef = useRef(null)
  const [alto, setAlto] = useState('100dvh')
  useLayoutEffect(() => {
    const medir = () => {
      const el = cajaRef.current
      if (!el) return
      // ⚠️ `getBoundingClientRect().top` A SECAS NO SIRVE: es relativo a lo
      // que se ve, así que con la página corrida da cero o negativo y el alto
      // sale igual de grande que antes. Medido: daba "calc(100dvh + 0px)".
      // Lo que hace falta es CUÁNTO OCUPA LO DE ARRIBA, que no se mueve con el
      // scroll — o sea la posición dentro del documento.
      const arriba = el.getBoundingClientRect().top + window.scrollY
      setAlto(`calc(100dvh - ${Math.max(0, Math.round(arriba))}px)`)
    }
    medir()
    window.addEventListener('resize', medir)
    // Los avisos de arriba (trial, demo, contexto de cliente) aparecen después
    // de montar: sin volver a medir, el alto queda calculado con lo que había
    // en el primer cuadro y la página vuelve a pasarse de largo.
    const obs = new ResizeObserver(medir)
    if (document.body) obs.observe(document.body)
    return () => { window.removeEventListener('resize', medir); obs.disconnect() }
  }, [])

  const nPos = snapshot?.summary?.open_positions_count
  const nBrokers = snapshot?.brokers?.length

  return (
    <div ref={cajaRef} style={{ height: alto }} className="flex flex-col pb-16 sm:pb-0">
      {/* Topbar de la página */}
      <div className="flex items-center justify-between gap-3 px-4 sm:px-7 py-3.5 border-b border-line/60 flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded-xl grid place-items-center text-white text-[15px] flex-none"
            style={{ background: 'linear-gradient(135deg, #9d8cff, #4bd0e8)' }}>✦</div>
          {/* QUÉ ESTÁ MIRANDO RENDI — va acá abajo del título y no como chip
              suelto a la derecha.
              El chip decía `hidden md:inline-flex`: aparecía según el ancho de
              la VENTANA, pero el lugar donde tenía que entrar es la ventana
              MENOS el sidebar. Con el sidebar abierto y la ventana grande,
              aparecía en un espacio que no le daba y se montaba encima del
              título — visto en pantalla, no deducido.
              Como subtítulo no puede pasar: es la misma línea que ya estaba
              ahí, y encima dice algo más útil que la frase fija de antes. */}
          <div className="min-w-0">
            <div className="text-[15.5px] font-semibold text-ink-0 leading-tight">Rendi AI</div>
            <div className="flex items-center gap-1.5 text-[12px] text-ink-3 truncate">
              {(bookMode || snapshot) && (
                <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos flex-none" aria-hidden />
              )}
              <span className="truncate">
                {bookMode
                  ? 'Viendo tu libro · todas las carteras de tus clientes'
                  : snapshot
                    ? `Viendo tu cartera${nPos != null ? ` · ${nPos} posiciones` : ''}${nBrokers ? ` · ${nBrokers} brokers` : ''}`
                    : 'Conoce tu cartera en tiempo real'}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2.5 flex-shrink-0">
          {/* SILENCIAR / DES-SILENCIAR, acá arriba del chat. El mismo
              interruptor está en la cabecera del acompañante flotante, pero
              esta es la pantalla donde el usuario pregunta: tener que
              descubrir la burbujita para poder callarla es pedirle demasiado.
              Los dos botones mueven el MISMO estado (VozContext), así que no
              se pueden contradecir. */}
          <button
            type="button"
            onClick={() => setVozEnabled(!vozEnabled)}
            aria-pressed={vozEnabled}
            title={vozEnabled ? 'Rendi te lee las respuestas en voz alta' : 'Rendi te deja las respuestas sólo escritas'}
            className={`inline-flex items-center gap-1.5 text-[12.5px] font-semibold rounded-lg px-3 py-1.5
              border transition-colors ${(vozEnabled || vozHablando)
                ? 'text-data-violet border-data-violet/45 bg-data-violet/[0.12] hover:bg-data-violet/[0.18]'
                : 'text-ink-3 border-line/60 hover:text-ink-1 hover:border-line'}`}
          >
            {/* "Hablando…" gana sobre todo lo demás: si SUENA, el chip lo dice.
                Antes mostraba "Silenciado" mientras la respuesta se escuchaba
                —la pantalla contradecía a los parlantes— porque el chip miraba
                sólo el interruptor y no si había audio. */}
            {/* En celular va SÓLO el ícono. Medido a 375px: con las dos
                etiquetas, los botones de la derecha sumaban 320 de 375 y
                aplastaban el título a ancho CERO — "Rendi AI" quedaba
                escrito encima de este botón. El estado igual se entiende: el
                ícono cambia y late cuando está hablando. */}
            {vozHablando
              ? <><Volume2 size={13} strokeWidth={2.2} aria-hidden="true" className="animate-pulse" /> <span className="hidden sm:inline">Hablando…</span></>
              : vozEnabled
                ? <><Volume2 size={13} strokeWidth={2.2} aria-hidden="true" /> <span className="hidden sm:inline">Te lee en voz alta</span></>
                : <><VolumeX size={13} strokeWidth={2} aria-hidden="true" /> <span className="hidden sm:inline">Silenciado</span></>}
          </button>
          <button
            type="button"
            onClick={() => { clearChatSession(); setConvKey(k => k + 1) }}
            title="Nueva conversación"
            aria-label="Nueva conversación"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink-2 hover:text-ink-0 border border-line hover:border-ink-3 rounded-lg px-3 py-1.5 transition-colors"
          >
            <Plus size={13} strokeWidth={2} aria-hidden="true" />
            <span className="hidden sm:inline">Nueva conversación</span>
          </button>
        </div>
      </div>

      {/* Cuerpo — conversación centrada */}
      <div className="flex-1 min-h-0 w-full max-w-3xl mx-auto flex flex-col px-2 sm:px-4">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-ink-3 py-16 justify-center">
            <Loader2 size={15} className="animate-spin" aria-hidden="true" />
            Cargando el contexto de tu cartera…
          </div>
        )}

        {error && !loading && (
          <div className="flex items-start gap-2 mx-4 mt-8 px-4 py-3 rounded-xl bg-rendi-neg/[0.08] border border-rendi-neg/25 text-rendi-neg text-sm">
            <AlertCircle size={15} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {bookMode ? (
          <AICoach key={convKey} snapshot={BOOK_SNAPSHOT} autoAsk={autoAskRef.current} fullHeight />
        ) : snapshot && !loading && !error && (
          <AICoach key={convKey} snapshot={snapshot} autoAsk={autoAskRef.current} fullHeight />
        )}
      </div>
    </div>
  )
}

