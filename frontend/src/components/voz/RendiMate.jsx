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
import { useMicrofono } from './BotonMicrofono'
import { useVoz, RATES, esRecienLlegada, escribiendoEn } from '../../contexts/VozContext'
import CursorEscribiendo from '../ai/CursorEscribiendo'
import { entrada } from '../../hooks/useAlVerse'
import { usePegadoAlFondo } from '../../hooks/usePegadoAlFondo'
import { useArrastrable } from '../../hooks/useArrastrable'
import { paraLaIsla } from '../ai/preguntasSugeridas'
import MervallE from '../ai/MervallE'
import { avisarTipeo, avisarMicrofono } from '../ai/mervalle/motor'
import { useEstadoMervallE } from '../ai/mervalle/estadoDelChat'



const mmss = (s) => {
  if (!isFinite(s) || s < 0) return '0:00'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}


export default function RendiMate() {
  const {
    enabled, setEnabled, rate, setRate,
    status, progress, current,
    escuchar, toggle, stop,
    open, setOpen,
    thread, sending, loading, paso, askError, sinCupo, ask, motivoSinVoz, modoLibro,
  } = useVoz()
  const [texto, setTexto] = useState('')
  // La respuesta que se está escribiendo ahora lleva un cursor al final.
  const iEscribiendo = escribiendoEn(thread, sending, loading)

  const hablando = status === 'playing'
  const preparando = status === 'preparing'
  // El reproductor aparece cuando hay algo que escuchar, y SE QUEDA cuando
  // termina. La primera versión lo escondía al terminar (status 'idle') y así
  // no había forma de volver a escuchar: el botón desaparecía justo cuando el
  // usuario podía querer usarlo. Y re-escuchar es la parte que sale gratis
  // —el audio ya está en el cache del server—, o sea lo último que hay que
  // esconder. Visto en pantalla, no deducido.
  const hayAudio = !!(current && (current.url || preparando))

  // Seguir la respuesta mientras se escribe, sin arrastrar al que se fue para
  // arriba a leer. El cómo vive en hooks/usePegadoAlFondo.js: acá estaba
  // copiado igual que en el chat grande, y las dos copias fallaban igual.
  const { ref: hiloRef, alFondo } = usePegadoAlFondo()
  // ARRASTRAR LA ISLA. Flota siempre arriba a la derecha y ahí viven los
  // botones de varias pantallas; el usuario la corre adonde no le moleste y se
  // queda ahí. El cómo vive en hooks/useArrastrable.js.
  //
  // La misma posición para cerrada y abierta a propósito: uno la deja en un
  // lugar y la espera ahí, no en dos lugares distintos según el estado.
  const { ref: islaRef, estilo: islaEstilo, manija } = useArrastrable('rendi:isla:pos')
  // Pregunta nueva → volvemos a seguirla, esté donde esté el usuario.
  useEffect(() => { if (sending) alFondo() }, [sending, alFondo])

  // ESTE es el momento del acompañante: te fuiste a otra sección y Rendi
  // sigue hablando. Ahí se abre solo, para que tengas dónde pausarla y
  // repreguntar sin volver. En la pantalla donde preguntaste no se abre: ahí
  // ya estás leyendo la respuesta entera.
  //
  // Y en /ai NO SE DIBUJA NADA, ni abierta ni cerrada: la conversación es UNA
  // sola, así que la tarjeta muestra lo mismo que estás leyendo y encima lo
  // tapa. La burbuja cerrada tampoco agrega nada ahí —esa pantalla tiene su
  // propio parlante arriba y un "Escuchar/Pausar" en CADA respuesta— y sí
  // molesta: cae justo sobre la barra de la página (medido a 375px, la burbuja
  // de y=93 a 117 y el título de la página en y=107).
  //
  // Se esconde el DIBUJO, no el componente: los avisos de más arriba tienen
  // que seguir corriendo. Si dejáramos de montarlo en /ai, al salir de ahí
  // arrancaría de cero creyendo que /dashboard es la pantalla de siempre, y
  // justo el momento que esto existe para cubrir —preguntar en /ai, irse al
  // panel y que Rendi siga hablando— dejaría de abrir la isla.
  //
  // EL MICRÓFONO. Lo dictado cae EN EL CUADRO, editable — no se manda solo
  // (ver components/voz/BotonMicrofono.jsx). Y Rendi se calla antes de abrir
  // el micrófono: si sigue hablando, se escucha a sí misma.
  const inputRef = useRef(null)
  const mic = useMicrofono({
    deshabilitado: sending,
    onAntesDeGrabar: stop,
    onTexto: (t) => {
      setTexto(prev => (prev.trim() ? prev.trim() + ' ' + t : t))
      // El foco al final, para que corregir sea escribir y no buscar el cursor.
      setTimeout(() => {
        const el = inputRef.current
        if (!el) return
        el.focus()
        try { el.setSelectionRange(el.value.length, el.value.length) } catch { /* sin soporte */ }
      }, 0)
    },
  })

  const loc = useLocation()
  const enElChatGrande = loc.pathname === '/ai'
  const rutaPrevia = useRef(loc.pathname)
  useEffect(() => {
    if (enElChatGrande) { setOpen(false); rutaPrevia.current = loc.pathname; return }
    if (loc.pathname !== rutaPrevia.current && (status === 'playing' || status === 'preparing')) {
      setOpen(true)
    }
    rutaPrevia.current = loc.pathname
  }, [loc.pathname, enElChatGrande, status, setOpen])

  // EL GRABADOR NO PUEDE SEGUIR SI SU PANEL NO ESTÁ A LA VISTA.
  //
  // El panel de grabar vive adentro de la tarjeta abierta. Cuando la isla se
  // cierra sola —entrar a /ai la cierra— el panel desaparece y el grabador
  // sigue: la lucecita del micrófono queda prendida hasta que se cumplen los
  // 30 segundos, sin nada en pantalla que lo pare, y encima al terminar se
  // gasta una transcripción que nadie va a ver. Visto leyendo el código, no en
  // el navegador: acá el micrófono no se puede probar.
  const panelALaVista = open && !enElChatGrande
  const { grabando: micGrabando, cancelar: micCancelar } = mic
  useEffect(() => {
    if (!panelALaVista && micGrabando) micCancelar()
  }, [panelALaVista, micGrabando, micCancelar])

  // La cara de Mervall-E en la burbuja y en la cabecera de la tarjeta. Antes
  // era un cuadradito con un punto que latía mientras sonaba el audio; ahora
  // es él, con la cara de lo que esté pasando (piensa, habla, reacciona,
  // duerme sin cuota). Va ANTES de los return: es un hook.
  const mervalle = useEstadoMervallE()
  useEffect(() => {
    avisarMicrofono(micGrabando)
    return () => avisarMicrofono(false)
  }, [micGrabando])

  if (enElChatGrande) return null

  if (!open) {
    // LA BURBUJA CERRADA. Antes decía sólo "Rendi" y no se entendía: ni que se
    // podía apretar, ni qué iba a pasar, ni que ahí adentro estaba el control
    // del audio. Ahora dice en qué estado está y, si Rendi está hablando, trae
    // el botón de pausa ENCIMA — no hay que abrir nada para callarla.
    return (
      <div
        ref={islaRef}
        data-tour="isla"
        style={{ ...islaEstilo, ...manija.style }}
        onPointerDown={manija.onPointerDown}
        onPointerMove={manija.onPointerMove}
        onPointerUp={manija.onPointerUp}
        onPointerCancel={manija.onPointerCancel}
        onClickCapture={manija.onClickCapture}
        // En el celular arranca ABAJO A LA IZQUIERDA, sobre la barra de abajo
        // (80 px: la barra mide 56 y el "+" sobresale 16; a la derecha está
        // WhatsApp). Arriba a la derecha tapaba lo que se pega debajo de la
        // barra al bajar: el selector USD/Pesos de Cartera, el win rate de
        // Movimientos. En la compu sigue arriba a la derecha.
        className="fixed bottom-[calc(80px_+_env(safe-area-inset-bottom))] left-4 md:bottom-auto md:left-auto md:top-[calc(var(--alto-barra-celular,80px)_+_8px)] md:right-4 z-40 flex items-center gap-1 rounded-full
                   bg-bg-raised border border-line-3 shadow-lg pl-2 pr-1 py-1 cursor-grab active:cursor-grabbing">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-2 pr-1.5 text-[12.5px] text-ink-1 hover:text-ink-0 transition-colors"
          aria-label={hablando ? 'Mervall-E está hablando — abrir la conversación'
                    : preparando ? 'Preparando el audio — abrir la conversación'
                    : 'Abrir la conversación con Mervall-E'}
        >
          <MervallE size={26} escucha estado={mervalle.estado} />
          {hablando ? 'Mervall-E está hablando' : preparando ? 'Preparando…' : 'Preguntale a Mervall-E'}
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
    : iEscribiendo !== -1 ? 'escribiendo…'
    : sending ? (paso ? paso.toLowerCase() + '…' : 'pensando…')
    : ''

  return (
    <section
      className="fixed z-40 flex flex-col overflow-hidden rounded-xl border border-line-3
                 bg-bg-raised shadow-2xl
                 top-[calc(var(--alto-barra-celular,80px)_+_8px)] left-3 right-3 sm:left-auto sm:right-4 sm:w-[340px]"
      aria-label="Mervall-E AI, tu acompañante"
      ref={islaRef}
      style={islaEstilo}
    >
      {/* ── Cabecera ─────────────────────────────────────────────────────────
          Y la MANIJA para arrastrar: apretás acá y la movés. El hilo y el
          cuadro de escribir quedan afuera a propósito — ahí se selecciona
          texto y se scrollea, y si arrastraran no se podría hacer ninguna de
          las dos. */}
      <header
        {...manija}
        className="flex items-center gap-2 px-3 py-2 border-b border-line-2 cursor-grab active:cursor-grabbing">
        {/* Con la tarjeta abierta, "pensando" lo dice el visor barriendo de la
            línea de espera de abajo: la cabecera se queda en reposo mientras
            tanto, para que no haya dos caras animándose a la vez. */}
        <MervallE size={26} escucha estado={mervalle.estado === 'pensando' ? 'reposo' : mervalle.estado} />
        <span className="flex-1 min-w-0 text-[12.5px] font-semibold text-ink-0 leading-tight">
          Mervall-E AI
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
      <div
        ref={hiloRef}
        className="flex flex-col gap-2.5 px-3 py-3 max-h-[260px] overflow-y-auto"
      >
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
            <p key={i} className="m-0 text-[13px] text-ink-1 whitespace-pre-wrap">{m.content}{i === iEscribiendo && <CursorEscribiendo />}</p>
          )
        ))}

        {/* Qué está HACIENDO, no un "pensando" mudo. El backend manda la frase
            (ver _PASOS_HUMANOS en main.py) cuando sale a buscar datos. La misma
            espera se hace corta cuando se entiende en qué se está yendo. Se
            apaga cuando empieza a llegar el texto: desde ahí lo dice el cursor
            (antes seguía girando "pensando…" debajo de la respuesta escrita).
            Si lo que llega no tiene texto para mostrar todavía, sigue. */}
        {sending && iEscribiendo === -1 && (
          // key = el paso: cada paso nuevo que manda el servidor entra en vez de
          // reemplazar el texto de golpe.
          <span key={paso || 'mirando'} className="entra inline-flex items-center gap-1.5 text-[12px] text-ink-3">
            <MervallE size={20} forma="visor" estado="cargando" />
            {paso || 'Mirando tu cartera'}…
          </span>
        )}

        {/* Los números, en dos píldoras. A propósito son DOS: con más, esto
            deja de ser un acompañante y se vuelve una segunda pantalla de
            chat — la respuesta completa, con sus tarjetas, vive en /ai. */}
        {pills.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {pills.map((s, k) => (
              <span key={k} {...(esRecienLlegada(ultimo)
                ? entrada(true, k, 'rounded-lg border border-line-2 bg-bg-1 px-2 py-1 text-[11.5px] text-ink-2')
                : { className: 'rounded-lg border border-line-2 bg-bg-1 px-2 py-1 text-[11.5px] text-ink-2' })}>
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
            {/* "Escuchar todas las que quieras" prometía audio sin límite, y
                ningún plan lo da: en los pagos cada audio usa una consulta de
                la semana (quota.reserve_listen). Lo que da cada plan lo dice
                el cartel de /planes. */}
            {sinCupo.upgrade?.available && (
              <Link to="/planes" onClick={() => setOpen(false)}
                className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-rendi-accent hover:underline underline-offset-2">
                Escuchar más respuestas <ArrowUpRight size={12} aria-hidden="true" />
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

          {/* EL NAVEGADOR LO FRENÓ, Y HAY QUE DECIRLO. Cuando rechaza el
              sonido, antes sólo aparecía el play: se leía como si Rendi
              hubiera decidido no hablar, y el usuario no tenía forma de saber
              que el que decidió fue su navegador. Con esto, una vez que toca,
              queda habilitado para el resto de la sesión. */}
          {(status !== 'playing' && motivoSinVoz) ? (
            <span className="flex-1 text-[11px] leading-tight text-ink-3">{motivoSinVoz}</span>
          ) : (
            <>
              <span className="flex-1 h-1 rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
                <i className="block h-full rounded-full bg-rendi-accent transition-[width] duration-200"
                  style={{ width: progress.d ? `${Math.min(100, (progress.t / progress.d) * 100)}%` : '0%' }} />
              </span>
              <span className="text-[11px] text-ink-3 tabular min-w-[30px] text-right">{mmss(progress.t)}</span>
            </>
          )}

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
          {paraLaIsla(modoLibro).map(q => (
            <button key={q} type="button" onClick={() => ask(q)}
              className="rounded-full border border-line-2 px-2.5 py-1 text-[11.5px] text-ink-2
                         hover:text-ink-0 hover:border-ink-3 transition-colors">
              {q}
            </button>
          ))}
        </div>
      )}

      {/* ── Repreguntar, escribiendo o hablando ──────────────────────────── */}
      {mic.aviso && <div className="px-2.5 pb-1">{mic.aviso}</div>}
      <form
        onSubmit={(e) => { e.preventDefault(); const t = texto.trim(); if (!t) return; setTexto(''); ask(t) }}
        className="flex items-center gap-2 border-t border-line-2 px-2.5 py-2"
      >
        {mic.boton}
        {/* Mientras graba, el panel del micrófono OCUPA el pie: el cuadro de
            escribir se va. Tener las dos cosas a la vez invita a escribir
            mientras habla, y lo dictado le pisaría lo tipeado. */}
        {!mic.grabando && (
          <>
            <input
              ref={inputRef}
              value={texto}
              onChange={(e) => { setTexto(e.target.value); avisarTipeo() }}
              placeholder="Escribile a Mervall-E…"
              aria-label="Escribile a Mervall-E"
              autoComplete="off"
              className="flex-1 min-w-0 rounded-full border border-line-2 bg-bg-1 px-3 py-1.5
                         text-[12.5px] text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-3"
            />
            {/* EL ÁREA DE TOQUE ES MÁS GRANDE QUE EL BOTÓN, igual que el
                micrófono de al lado. El círculo dibuja 28px y el mínimo para un
                dedo son 44: el `after` invisible agrega 8 por lado y llega
                justo a 44. Crece el área y NO el dibujo porque al lado hay un
                micrófono de 30 — un botón de 44 ahí quedaría desparejo, y esa
                es la misma razón por la que el micrófono tampoco creció.
                De sm: para arriba se apaga: con mouse el blanco alcanza. */}
            <button
              type="submit"
              disabled={!texto.trim() || sending}
              aria-label="Enviar"
              className="w-7 h-7 relative rounded-full grid place-items-center flex-none bg-rendi-accent text-bg-0
                         after:absolute after:content-[''] after:-inset-2 sm:after:inset-0
                         disabled:bg-bg-3 disabled:text-ink-3 transition-colors"
            >
              <Send size={13} strokeWidth={2.2} />
            </button>
          </>
        )}
      </form>
    </section>
  )
}
