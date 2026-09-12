// RendiMate — el acompañante: la conversación con Rendi, chiquita, flotando
// sobre la pantalla que el usuario esté mirando.
// ═══════════════════════════════════════════════════════════════════════════
// NO es un reproductor de audio. Es el chat, compacto, con su caja de texto
// adentro, para poder repreguntar sin volver a /ai. El reproductor es una
// franja más, y aparece sólo cuando hay algo que escuchar.
//
// Cerrado es una burbujita; abierto, una tarjeta arriba a la derecha. Cerrar
// NO calla el audio: colapsa a la burbuja y Rendi sigue hablando (para callarla
// está el parlante). El estado y el <audio> viven en VozContext, que está
// montado en el shell — por eso esto sobrevive a cambiar de sección.
//
// LOS DOS BOTONES NO SE CONFUNDEN (y en esta etapa hay uno solo):
//   · el parlante, arriba → si Rendi te LEE la respuesta o te la deja escrita.
//   · el micrófono, abajo → cómo le hablás vos. Es de la etapa 2; no está acá.

import { useEffect, useRef, useState } from 'react'
import { Volume2, VolumeX, X, Play, Pause, Send, Loader2, ArrowUpRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { useVoz, RATES } from '../../contexts/VozContext'

// Preguntas de arranque: dos, cortas, y de las que ya están en la whitelist
// del backend (si no, Free y Plus se comen un 403 al tocarlas).
const SUGERIDAS = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
]

const mmss = (s) => {
  if (!isFinite(s) || s < 0) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

/** El puntito que late mientras Rendi habla. */
function Pulso({ hablando }) {
  return (
    <span
      className={`w-6 h-6 rounded-lg grid place-items-center flex-none ${hablando ? 'animate-pulse' : ''}`}
      style={{ background: 'linear-gradient(135deg, #9d8cff, #4bd0e8)' }}
      aria-hidden="true"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-bg-0/60" />
    </span>
  )
}

export default function RendiMate() {
  const {
    enabled, setEnabled, rate, setRate,
    status, progress, current,
    escuchar, toggle,
    open, setOpen,
    thread, sending, askError, sinCupo, ask,
  } = useVoz()
  const [texto, setTexto] = useState('')
  const hiloRef = useRef(null)

  const hablando = status === 'playing'
  const preparando = status === 'preparing'
  // El reproductor aparece cuando hay algo que escuchar, y SE QUEDA cuando
  // termina. La primera versión lo escondía al terminar (status 'idle') y así
  // no había forma de volver a escuchar: el botón desaparecía justo cuando el
  // usuario podía querer usarlo. Y re-escuchar es la parte que sale gratis
  // —el audio ya está en el cache del server—, o sea lo último que hay que
  // esconder. Visto en pantalla, no deducido.
  const hayAudio = !!(current && (current.url || preparando))

  useEffect(() => {
    if (hiloRef.current) hiloRef.current.scrollTop = hiloRef.current.scrollHeight
  }, [thread, hayAudio, askError])

  // ESTE es el momento del acompañante: te fuiste a otra sección y Rendi
  // sigue hablando. Ahí se abre solo, para que tengas dónde pausarla y
  // repreguntar sin volver. En la pantalla donde preguntaste no se abre: ahí
  // ya estás leyendo la respuesta entera.
  const loc = useLocation()
  const rutaPrevia = useRef(loc.pathname)
  useEffect(() => {
    if (loc.pathname !== rutaPrevia.current && (status === 'playing' || status === 'preparing')) {
      setOpen(true)
    }
    rutaPrevia.current = loc.pathname
  }, [loc.pathname, status, setOpen])

  if (!open) {
    // LA BURBUJA CERRADA. Antes decía sólo "Rendi" y no se entendía: ni que se
    // podía apretar, ni qué iba a pasar, ni que ahí adentro estaba el control
    // del audio. Ahora dice en qué estado está y, si Rendi está hablando, trae
    // el botón de pausa ENCIMA — no hay que abrir nada para callarla.
    return (
      <div className="fixed top-[88px] right-4 z-40 flex items-center gap-1 rounded-full
                      bg-bg-2 border border-line-3 shadow-lg pl-2 pr-1 py-1">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 pr-1.5 text-[12.5px] text-ink-1 hover:text-ink-0 transition-colors"
          aria-label={hablando ? 'Rendi está hablando — abrir la conversación'
                    : preparando ? 'Preparando el audio — abrir la conversación'
                    : 'Abrir la conversación con Rendi'}
        >
          <Pulso hablando={hablando} />
          {hablando ? 'Rendi está hablando' : preparando ? 'Preparando…' : 'Preguntale a Rendi'}
        </button>
        {hayAudio && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); toggle() }}
            aria-label={hablando ? 'Pausar' : 'Reproducir'}
            title={hablando ? 'Pausar' : 'Reproducir'}
            className="w-6 h-6 rounded-full grid place-items-center flex-none bg-ink-0 text-bg-0"
          >
            {hablando ? <Pause size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" />}
          </button>
        )}
      </div>
    )
  }

  const ultimo = [...thread].reverse().find(m => m.role === 'assistant')
  const pills = (ultimo?.meta?.stats || []).slice(0, 2)
  const estado = preparando ? 'preparando el audio…'
    : hablando ? 'hablando'
    : sending ? 'pensando…'
    : ''

  return (
    <section
      className="fixed z-40 flex flex-col overflow-hidden rounded-xl border border-line-3
                 bg-bg-2 shadow-2xl
                 top-[88px] left-3 right-3 sm:left-auto sm:right-4 sm:w-[340px]"
      aria-label="Rendi, tu acompañante"
    >
      {/* ── Cabecera ─────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-2 px-3 py-2 border-b border-line-2">
        <Pulso hablando={hablando} />
        <span className="flex-1 min-w-0 text-[12.5px] font-semibold text-ink-0 leading-tight">
          Rendi
          {estado && <span className="block font-normal text-[11px] text-ink-3">{estado}</span>}
        </span>

        {/* EL PARLANTE. Decide una sola cosa: si te lee la respuesta en voz
            alta o te la deja sólo escrita. Apagado, el backend NI SIQUIERA
            genera el audio — el costo se paga al generar, no al reproducir. */}
        <button
          type="button"
          onClick={() => setEnabled(!enabled)}
          aria-pressed={enabled}
          title={enabled ? 'Te lee las respuestas en voz alta' : 'Te deja las respuestas sólo escritas'}
          aria-label={enabled ? 'Te lee las respuestas en voz alta' : 'Te deja las respuestas sólo escritas'}
          className={`p-1.5 rounded-lg transition-colors flex-none ${
            enabled ? 'text-data-violet bg-data-violet/[0.12] hover:bg-data-violet/20'
                    : 'text-ink-3 hover:text-ink-1 hover:bg-bg-3'
          }`}
        >
          {enabled ? <Volume2 size={15} strokeWidth={2} /> : <VolumeX size={15} strokeWidth={2} />}
        </button>

        <button
          type="button"
          onClick={() => setOpen(false)}
          title="Cerrar — si está hablando, sigue"
          aria-label="Cerrar"
          className="p-1.5 rounded-lg text-ink-3 hover:text-ink-0 hover:bg-bg-3 transition-colors flex-none"
        >
          <X size={15} strokeWidth={2} />
        </button>
      </header>

      {/* ── El hilo ──────────────────────────────────────────────────────── */}
      <div ref={hiloRef} className="flex flex-col gap-2.5 px-3 py-3 max-h-[260px] overflow-y-auto">
        {thread.length === 0 && (
          <p className="text-[13px] text-ink-2 m-0">
            Preguntame lo que quieras mientras mirás otra pantalla. Te sigo hablando.
          </p>
        )}

        {thread.map((m, i) => (
          m.role === 'user' ? (
            <p key={i} className="self-end max-w-[85%] m-0 rounded-xl rounded-br-sm bg-bg-3 px-3 py-1.5 text-[12.5px] text-ink-0">
              {m.content}
            </p>
          ) : (
            <p key={i} className="m-0 text-[13px] text-ink-1 whitespace-pre-wrap">{m.content}</p>
          )
        ))}

        {sending && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-3">
            <Loader2 size={12} className="animate-spin" aria-hidden="true" /> Mirando tu cartera…
          </span>
        )}

        {/* Los números, en dos píldoras. A propósito son DOS: con más, esto
            deja de ser un acompañante y se vuelve una segunda pantalla de
            chat — la respuesta completa, con sus tarjetas, vive en /ai. */}
        {pills.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {pills.map((s, k) => (
              <span key={k} className="rounded-lg border border-line-2 bg-bg-1 px-2 py-1 text-[11.5px] text-ink-2">
                {s.l}{' '}
                <b className={`font-semibold tabular ${
                  s.t === 'pos' ? 'text-rendi-pos' : s.t === 'neg' ? 'text-rendi-neg'
                  : s.t === 'warn' ? 'text-rendi-warn' : 'text-ink-0'
                }`}>{s.v}</b>
              </span>
            ))}
          </div>
        )}

        {ultimo && (
          <Link to="/ai" onClick={() => setOpen(false)}
            className="self-start inline-flex items-center gap-1 text-[12px] text-rendi-accent hover:underline underline-offset-2">
            Ver la respuesta entera <ArrowUpRight size={12} aria-hidden="true" />
          </Link>
        )}

        {askError && (
          <p className="m-0 text-[12px] text-rendi-neg">{askError}</p>
        )}

        {/* Se acabó el cupo de escuchas. NO va en rojo: no hizo nada mal, usó
            lo que tenía. Dice cuándo se le renueva (el backend lo arma con la
            fecha real de la ventana móvil) y ofrece el atajo — pero la
            respuesta escrita la sigue teniendo arriba, intacta. */}
        {sinCupo && (
          <div className="rounded-lg border border-rendi-accent/30 bg-rendi-accent/[0.07] px-3 py-2">
            <p className="m-0 text-[12px] text-ink-1 leading-snug">{sinCupo.message}</p>
            {sinCupo.upgrade?.available && (
              <Link to="/planes" onClick={() => setOpen(false)}
                className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-rendi-accent hover:underline underline-offset-2">
                Escuchar todas las que quieras <ArrowUpRight size={12} aria-hidden="true" />
              </Link>
            )}
          </div>
        )}
      </div>

      {/* ── El reproductor ───────────────────────────────────────────────── */}
      {hayAudio && (
        <div className="flex items-center gap-2 px-3 pb-2.5">
          <button
            type="button"
            onClick={(status === 'blocked' || !current?.url) ? () => escuchar(current) : toggle}
            disabled={preparando}
            aria-label={hablando ? 'Pausar' : 'Reproducir'}
            className="w-7 h-7 rounded-full grid place-items-center flex-none bg-ink-0 text-bg-0
                       disabled:opacity-50 disabled:cursor-default"
          >
            {preparando ? <Loader2 size={12} className="animate-spin" />
              : hablando ? <Pause size={12} fill="currentColor" />
              : <Play size={12} fill="currentColor" />}
          </button>

          <span className="flex-1 h-1 rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
            <i className="block h-full rounded-full bg-rendi-accent transition-[width] duration-200"
              style={{ width: progress.d ? `${Math.min(100, (progress.t / progress.d) * 100)}%` : '0%' }} />
          </span>
          <span className="text-[11px] text-ink-3 tabular min-w-[30px] text-right">{mmss(progress.t)}</span>

          {/* La velocidad se controla ACÁ y no pidiéndole al modelo que hable
              más rápido: se midió y no hace nada (24,2 s vs 24,4 s con el
              mismo texto). Acelerarlo a mano en el servidor suena metálico;
              el navegador lo hace bien y sin cambiarle el tono. */}
          <div className="flex rounded-lg border border-line bg-bg-1 p-0.5" role="group" aria-label="Velocidad">
            {RATES.map(r => (
              <button
                key={r}
                type="button"
                onClick={() => setRate(r)}
                aria-pressed={rate === r}
                className={`rounded px-1.5 py-0.5 text-[11px] font-medium tabular transition-colors ${
                  rate === r ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-1'
                }`}
              >
                {String(r).replace('.', ',')}×
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Sugeridas ────────────────────────────────────────────────────── */}
      {thread.length === 0 && !sending && (
        <div className="flex flex-wrap gap-1.5 px-3 pb-2.5">
          {SUGERIDAS.map(q => (
            <button key={q} type="button" onClick={() => ask(q)}
              className="rounded-full border border-line-2 px-2.5 py-1 text-[11.5px] text-ink-2
                         hover:text-ink-0 hover:border-ink-3 transition-colors">
              {q}
            </button>
          ))}
        </div>
      )}

      {/* ── Repreguntar ──────────────────────────────────────────────────── */}
      <form
        onSubmit={(e) => { e.preventDefault(); const t = texto.trim(); if (!t) return; setTexto(''); ask(t) }}
        className="flex items-center gap-2 border-t border-line-2 px-2.5 py-2"
      >
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Escribile a Rendi…"
          aria-label="Escribile a Rendi"
          autoComplete="off"
          className="flex-1 min-w-0 rounded-full border border-line-2 bg-bg-1 px-3 py-1.5
                     text-[12.5px] text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-3"
        />
        <button
          type="submit"
          disabled={!texto.trim() || sending}
          aria-label="Enviar"
          className="w-7 h-7 rounded-full grid place-items-center flex-none bg-rendi-accent text-bg-0
                     disabled:bg-bg-3 disabled:text-ink-3 transition-colors"
        >
          <Send size={13} strokeWidth={2.2} />
        </button>
      </form>
    </section>
  )
}
