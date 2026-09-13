// VozContext — la voz de Rendi y el acompañante que la sostiene.
// ═══════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO VIVE EN EL SHELL Y NO ADENTRO DE UNA PANTALLA
// ---------------------------------------------------------------------------
// Es LA decisión de la etapa, y de ella depende todo lo demás. El pedido fue
// "que me siga hablando mientras miro otra cosa". Si el <audio> se montara
// dentro de una página, al navegar React la desmonta, el elemento se destruye
// y el sonido se corta a mitad de frase — justo lo que se pidió que no pasara.
//
// Acá el <audio> lo renderiza el provider, que es hermano de <Layout/> y vive
// arriba del router: cambiar de sección no lo toca. Es el mismo patrón que ya
// usa el selector de moneda del sidebar, que sobrevive a la navegación.
//
// QUÉ HAY ADENTRO
//   · el parlante  — si Rendi LEE las respuestas o las deja sólo escritas.
//                    Es lo único que decide ese botón (no tiene nada que ver
//                    con el micrófono, que es de otra etapa).
//   · el reproductor — un solo <audio>, su estado y la perilla de velocidad.
//   · el acompañante — el hilo corto y la caja de texto que flotan sobre la
//                    pantalla que el usuario esté mirando.
//
// LO QUE NO HACE: no elige QUÉ se dice. El texto hablado lo escribe Claude en
// el mismo turno del chat y viene FIRMADO por el backend; acá se reenvía tal
// cual. Cambiarle un espacio rompe la firma y el servidor lo rechaza.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../utils/api'
import { fetchAiSnapshot } from '../utils/aiSnapshot'
import { stripMarkdown } from '../utils/stripMarkdown'
import { parseStructured } from '../utils/aiStructured'
import { sendWindow } from '../utils/chatSession'

const LS_ON = 'rendi:voz:on'
const LS_RATE = 'rendi:voz:rate'

// 1,25× por defecto: a la velocidad natural el resumen de 3 oraciones dura 24
// segundos y se hace largo. Las tres marcas son las del mockup; acelerar más
// allá de 1,4 empieza a sonar a ardilla aunque se conserve el tono.
export const RATES = [1, 1.25, 1.4]
const DEFAULT_RATE = 1.25

// Cuántos mensajes guarda el hilo del acompañante. Es un acompañante, no una
// segunda pantalla de chat: la conversación entera vive en /ai.
const MAX_THREAD = 8

/**
 * ¿El audio puede arrancar SOLO, sin que el usuario lo pida?
 *
 * Para Free la respuesta es SIEMPRE no. Free tiene UN escuche por semana (cupo
 * propio, aparte de su consulta escrita — ver ai/quota.py). Gastárselo sin que
 * lo haya pedido es peor que no dárselo: se quedaría sin el único de la semana
 * mirando una pantalla que ni sabía que iba a hablar. Lo tiene que tocar él.
 *
 * Se reconoce por `listens_limit`: si viene un número, ese tier paga con cupo
 * propio; si viene null, paga con fichas de chat y ahí sí arranca solo, mientras
 * le queden.
 */
export function puedeArrancarSolo(usage) {
  if (!usage) return true                       // sin dato, el comportamiento de antes
  if (usage.listens_limit != null) return false // Free: siempre a pedido
  return (usage.chat_remaining ?? 1) > 0
}

const VozContext = createContext(null)

function leerBool(k, def) {
  try {
    const v = localStorage.getItem(k)
    return v == null ? def : v === '1'
  } catch { return def }
}
function leerRate() {
  try {
    const v = parseFloat(localStorage.getItem(LS_RATE))
    return RATES.includes(v) ? v : DEFAULT_RATE
  } catch { return DEFAULT_RATE }
}
function guardar(k, v) {
  try { localStorage.setItem(k, v) } catch { /* modo privado: no es crítico */ }
}

export function VozProvider({ children }) {
  const audioRef = useRef(null)

  // ── El parlante ──────────────────────────────────────────────────────────
  const [enabled, setEnabledState] = useState(() => leerBool(LS_ON, true))
  const [rate, setRateState] = useState(leerRate)

  // ── El reproductor ───────────────────────────────────────────────────────
  // 'idle' · 'preparing' (pidiendo el audio) · 'playing' · 'paused'
  // 'blocked' (el navegador no deja sonar sin que toquen algo — iPhone la
  // primera vez) · 'error' · 'quota' (se acabaron las fichas)
  const [status, setStatus] = useState('idle')
  const [progress, setProgress] = useState({ t: 0, d: 0 })
  // El resumen hablado en curso: { text, sig, url }
  const [current, setCurrent] = useState(null)

  // ── El acompañante ───────────────────────────────────────────────────────
  const [open, setOpen] = useState(false)
  const [thread, setThread] = useState([])
  const [sending, setSending] = useState(false)
  // Qué está haciendo Rendi ahora mismo ("Buscando los precios de hoy"). Lo
  // manda el backend cuando sale a buscar datos; sirve para que la espera no
  // sea un "pensando" mudo de 15 segundos.
  const [paso, setPaso] = useState(null)
  const [askError, setAskError] = useState(null)
  // Se acabó el cupo de escuchas: { message, upgrade }. Se dibuja como aviso
  // con su atajo a Planes, no como error.
  const [sinCupo, setSinCupo] = useState(null)

  // Snapshot de la cartera para poder repreguntar desde cualquier pantalla.
  // Perezoso: recién se pide cuando hace falta, y se refresca si el chat
  // registró una operación.
  const snapRef = useRef(null)
  const sendingRef = useRef(false)

  useEffect(() => {
    const invalidar = () => { snapRef.current = null }
    window.addEventListener('rendi:portfolio-changed', invalidar)
    return () => window.removeEventListener('rendi:portfolio-changed', invalidar)
  }, [])

  const setEnabled = useCallback((v) => {
    setEnabledState(v)
    guardar(LS_ON, v ? '1' : '0')
    // Apagar el parlante calla lo que esté sonando: el usuario tocó "no me
    // leas" y seguir hablando sería no haberle hecho caso.
    if (!v && audioRef.current) {
      audioRef.current.pause()
      setStatus(s => (s === 'playing' ? 'paused' : s))
    }
  }, [])

  // playbackRate SIN que la voz se ponga aguda: preservesPitch va ANTES de
  // tocar la velocidad, y con los tres prefijos porque cada navegador tardó
  // lo suyo en estandarizarlo.
  const aplicarRate = useCallback((a, r) => {
    if (!a) return
    a.preservesPitch = true
    a.mozPreservesPitch = true
    a.webkitPreservesPitch = true
    a.playbackRate = r
  }, [])

  const setRate = useCallback((r) => {
    const v = RATES.includes(r) ? r : DEFAULT_RATE
    setRateState(v)
    guardar(LS_RATE, String(v))
    aplicarRate(audioRef.current, v)
  }, [aplicarRate])

  /**
   * Reproduce un resumen hablado. `voz` es { text, sig } tal como lo devolvió
   * el backend — no lo re-armes ni lo recortes.
   *
   * Dos pasos a propósito: primero le preguntamos al servidor la dirección del
   * audio, y después se la damos al <audio> para que la baje ÉL. Así el sonido
   * arranca apenas llegan los primeros bytes (~1,5 s en vez de ~5) y el
   * celular puede seguir reproduciéndolo con la pantalla apagada — dos cosas
   * que se pierden si el audio se baja entero por JavaScript antes de sonar.
   */
  const speak = useCallback(async (voz) => {
    const a = audioRef.current
    if (!a || !voz?.text || !voz?.sig) return
    setStatus('preparing')
    setAskError(null)
    setSinCupo(null)
    try {
      const { url } = await api.post('/ai/voz', { text: voz.text, sig: voz.sig })
      if (!url) throw new Error('sin url')
      setCurrent({ ...voz, url })
      a.src = url
      aplicarRate(a, rate)
      await a.play()
      setStatus('playing')
    } catch (e) {
      if (e?.name === 'NotAllowedError') {
        // El navegador exige que el usuario toque algo antes del primer
        // sonido (iPhone, sobre todo). No es un error: mostramos el botón de
        // play y con ese toque queda habilitado para el resto de la sesión.
        setStatus('blocked')
        return
      }
      const detail = e?.payload?.detail
      if (e?.status === 429) {
        // No es un error del usuario: se le acabó el cupo. Se muestra como
        // aviso con la fecha en que se renueva, no como una falla en rojo.
        setStatus('quota')
        setSinCupo({
          message: detail?.message || 'Te quedaste sin escuchas por esta semana.',
          upgrade: detail?.upgrade || null,
        })
        return
      }
      setStatus('error')
      setAskError(detail?.message || 'No pudimos generar el audio.')
    }
  }, [aplicarRate, rate])

  /**
   * "Escuchar" — lo que pasa cuando el usuario PIDE oír una respuesta.
   *
   * Además de reproducirla, PRENDE el parlante. Dos motivos, y los dos salieron
   * de verlo en uso:
   *  1. Sin esto, tocabas Escuchar, la respuesta sonaba, y el interruptor de
   *     arriba seguía diciendo "Silenciado". La pantalla contradecía a los
   *     parlantes.
   *  2. Pedir que te lea una respuesta ES decir "quiero escuchar". Obligarte a
   *     pedirlo de nuevo en cada mensaje era justo lo que había que sacar: una
   *     conversación hablada se habla entera.
   * Para volver al silencio está el interruptor, que queda a la vista.
   */
  const escuchar = useCallback((voz) => {
    setEnabled(true)
    speak(voz)
  }, [setEnabled, speak])

  /** Play/pausa del audio ya cargado. */
  const toggle = useCallback(async () => {
    const a = audioRef.current
    if (!a || !a.src) return
    if (a.paused) {
      try {
        // Terminado → volver a empezar. Sale del cache del servidor, así que
        // re-escuchar no cuesta ni una ficha ni una llamada a OpenAI.
        if (a.ended || (a.duration && a.currentTime >= a.duration - 0.05)) a.currentTime = 0
        aplicarRate(a, rate)
        await a.play()
        setStatus('playing')
      } catch { setStatus('blocked') }
    } else {
      a.pause()
      setStatus('paused')
    }
  }, [aplicarRate, rate])

  const stop = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    a.pause()
    try { a.currentTime = 0 } catch { /* sin metadata todavía */ }
    setStatus('idle')
  }, [])

  /**
   * Lo que /ai (o el propio acompañante) le pasa al terminar un turno: la
   * pregunta, la respuesta y —si la hubo— la versión hablada.
   * Si el parlante está prendido y hay audio, arranca solo.
   */
  const publicar = useCallback(({ question, reply, voz, meta, autoplay = true }) => {
    setThread(t => {
      const next = [...t]
      if (question) next.push({ role: 'user', content: question })
      if (reply) next.push({ role: 'assistant', content: reply, voz: voz || null, meta: meta || null })
      return next.slice(-MAX_THREAD)
    })
    if (voz) {
      setCurrent(voz)
      // Arranca el audio pero NO abre el panel: el usuario está mirando la
      // respuesta completa en /ai y taparla sería estorbar. La burbuja pasa a
      // "Hablando…", y el panel se abre solo si se va a otra sección (ver
      // RendiMate: ahí es donde el acompañante tiene que hacerse ver).
      if (enabled && autoplay) speak(voz)
    }
  }, [enabled, speak])

  /** Repreguntar desde el acompañante, sin volver a /ai. */
  // `analisis` = { screen, params }: el turno lo disparó el botón ✦ de una
  // pantalla, no el usuario escribiendo. Cambia tres cosas y ninguna más — por
  // eso es un parámetro y no una segunda función: la pregunta la escribe el
  // servidor, se descuenta del cupo de análisis y no del de consultas, y el
  // acompañante recibe de yapa el dato calculado de esa pantalla. Todo lo
  // demás —el hilo, el audio, las tarjetas, poder repreguntar— es idéntico.
  const ask = useCallback(async (texto, { analisis } = {}) => {
    const content = (texto || '').trim()
    if ((!content && !analisis) || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    setPaso(null)
    setAskError(null)
    const previos = thread
    // Con el botón ✦ todavía no sabemos qué se preguntó: la pregunta la
    // escribe el servidor y llega en el primer frame, antes que la respuesta.
    // Se espera ese pestañeo en vez de pintar una burbuja inventada que
    // después habría que corregir en pantalla.
    let preguntaPuesta = !analisis
    if (!analisis) setThread(t => [...t, { role: 'user', content }].slice(-MAX_THREAD))
    const onPregunta = (q) => {
      preguntaPuesta = true
      setThread(t => [...t, { role: 'user', content: q }].slice(-MAX_THREAD))
    }
    try {
      if (!snapRef.current) snapRef.current = await fetchAiSnapshot()
      let acc = ''
      // Al modelo van SOLO role y content: el hilo de acá guarda además el
      // audio firmado y las tarjetas, que no son parte de la conversación.
      // En el turno del ✦ el último mensaje es un relleno que el servidor
      // pisa con la pregunta de verdad; la conversación previa viaja igual,
      // así Rendi sigue acordándose de lo que venían hablando.
      const messages = sendWindow([...previos, { role: 'user', content: content || '✦' }])
        .map(({ role, content: c }) => ({ role, content: c }))

      // 🔴 SE ESCRIBE EN VIVO, letra por letra, igual que en /ai.
      //
      // Antes acá sólo se acumulaba el texto y el mensaje se agregaba al hilo
      // RECIÉN al terminar. Como escribir la respuesta lleva 10-20 segundos
      // (medido: el 100% de la espera es el modelo redactando, buscar los datos
      // tarda 0,4 s), el acompañante se quedaba mudo todo ese rato y después
      // escupía el texto entero de golpe. Se sentía muchísimo más lento que el
      // chat grande aunque tardara lo mismo: la espera con algo pasando en
      // pantalla es corta, la espera mirando nada es eterna.
      let agregado = false
      const pintar = (texto) => setThread(t => {
        const copia = t.slice()
        if (agregado && copia.length && copia[copia.length - 1].role === 'assistant') {
          copia[copia.length - 1] = { ...copia[copia.length - 1], content: texto }
          return copia
        }
        agregado = true
        return [...copia, { role: 'assistant', content: texto }].slice(-MAX_THREAD)
      })
      const onDelta = (c) => {
        acc += c
        // Se pinta la PROSA, no el texto crudo: así el bloque de datos del
        // final no aparece medio escrito en pantalla mientras llega.
        const { prose } = parseStructured(stripMarkdown(acc))
        if (prose) pintar(prose)
      }
      // El turno terminó en una herramienta: lo que se escribió era el
      // preámbulo ("dejame ver los precios…"), no la respuesta. Se borra y
      // vuelve el "pensando" hasta que llegue la de verdad.
      const onReset = () => {
        acc = ''
        if (agregado) { setThread(t => t.slice(0, -1)); agregado = false }
      }
      const res = await api.chatStream(
        { messages, snapshot: snapRef.current, ...(analisis ? { analisis } : {}) },
        { onDelta, onReset, onPaso: setPaso, onPregunta },
      )
      const { prose, meta } = parseStructured(stripMarkdown(acc))
      setThread(t => {
        const copia = t.slice()
        const final = { role: 'assistant', content: prose || '…', voz: res?.voz || null, meta }
        if (agregado && copia.length && copia[copia.length - 1].role === 'assistant') {
          copia[copia.length - 1] = final
          return copia
        }
        return [...copia, final].slice(-MAX_THREAD)
      })
      if (res?.portfolioChanged) window.dispatchEvent(new Event('rendi:portfolio-changed'))
      if (res?.voz) {
        setCurrent(res.voz)
        // Mismo criterio que /ai: con el parlante prendido arranca solo, salvo
        // que el tier pague con cupo propio de escuchas (Free) — ahí siempre a
        // pedido. La cuota se consulta fresca porque la de antes del turno ya
        // quedó vieja.
        if (enabled) {
          const u = await api.get('/ai/usage').catch(() => null)
          if (puedeArrancarSolo(u)) speak(res.voz)
        }
      }
    } catch (e) {
      const detail = e?.payload?.detail
      setAskError(
        (detail && typeof detail === 'object' && detail.message)
          ? detail.message
          : 'No pudimos completar la consulta. Probá de nuevo.',
      )
      // Sacar la pregunta que falló — sólo si llegó a haber una. Un 429 del
      // botón ✦ revienta ANTES del frame con la pregunta: ahí no hay burbuja
      // que sacar y este slice se llevaría la respuesta anterior.
      if (preguntaPuesta) setThread(t => t.slice(0, -1))
    } finally {
      sendingRef.current = false
      setSending(false)
      setPaso(null)
    }
  }, [thread, enabled, speak])

  /**
   * Lo que hace el botón ✦ Analizar de cualquier pantalla: abre el
   * acompañante y le pregunta a Rendi por eso.
   *
   * Antes cada uno de estos botones abría un panel lateral con una respuesta
   * larga y un callejón sin salida — se leía y se cerraba. Ahora la respuesta
   * cae en la conversación: se puede escuchar, se puede repreguntar, y sigue
   * ahí cuando el usuario se va a otra sección.
   *
   * `screen` es cuál de los análisis (la lista vive en el servidor,
   * ai/preguntas.py) y `params` sobre qué — el activo, el mes, la categoría.
   * La pregunta en castellano NO se arma acá: la escribe el servidor. Ver el
   * comentario de ese archivo para el porqué.
   */
  const analizar = useCallback(({ screen, params } = {}) => {
    if (!screen) return
    setOpen(true)
    ask('', { analisis: { screen, params: params || {} } })
  }, [ask])

  // ── Cablear el <audio> ───────────────────────────────────────────────────
  useEffect(() => {
    const a = audioRef.current
    if (!a) return
    const onTime = () => setProgress({ t: a.currentTime || 0, d: a.duration || 0 })
    const onEnd = () => { setStatus('idle'); setProgress(p => ({ ...p, t: 0 })) }
    const onErr = () => setStatus('error')
    const onPlay = () => setStatus('playing')
    const onPause = () => setStatus(s => (s === 'playing' ? 'paused' : s))
    a.addEventListener('timeupdate', onTime)
    a.addEventListener('loadedmetadata', onTime)
    a.addEventListener('ended', onEnd)
    a.addEventListener('error', onErr)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    return () => {
      a.removeEventListener('timeupdate', onTime)
      a.removeEventListener('loadedmetadata', onTime)
      a.removeEventListener('ended', onEnd)
      a.removeEventListener('error', onErr)
      a.removeEventListener('play', onPlay)
      a.removeEventListener('pause', onPause)
    }
  }, [])

  // Controles del sistema (pantalla bloqueada, auriculares, barra del celu).
  // Best-effort: si el navegador no la tiene, no pasa nada.
  useEffect(() => {
    if (!('mediaSession' in navigator)) return
    try {
      navigator.mediaSession.setActionHandler('play', () => { audioRef.current?.play().catch(() => {}) })
      navigator.mediaSession.setActionHandler('pause', () => { audioRef.current?.pause() })
    } catch { /* navegador sin soporte parcial */ }
  }, [])

  useEffect(() => {
    if (!('mediaSession' in navigator) || !window.MediaMetadata || !current?.text) return
    try {
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: current.text.slice(0, 70),
        artist: 'Rendi',
      })
    } catch { /* idem */ }
  }, [current?.text])

  const value = useMemo(() => ({
    enabled, setEnabled,
    rate, setRate, rates: RATES,
    status, progress, current,
    speak, escuchar, toggle, stop,
    open, setOpen,
    thread, sending, paso, askError, sinCupo, ask, analizar, publicar,
  }), [enabled, setEnabled, rate, setRate, status, progress, current,
       speak, escuchar, toggle, stop, open, thread, sending, paso, askError, sinCupo,
       ask, analizar, publicar])

  return (
    <VozContext.Provider value={value}>
      {children}
      {/* EL elemento de audio de toda la app. Uno solo, acá arriba: es lo que
          hace que el sonido no se corte al cambiar de sección. */}
      <audio ref={audioRef} preload="auto" hidden />
    </VozContext.Provider>
  )
}

// Devuelve un objeto inerte si no hay provider (tests que montan un componente
// suelto, o el árbol sin sesión): así ningún caller tiene que preguntar.
const INERTE = {
  enabled: false, setEnabled: () => {},
  rate: DEFAULT_RATE, setRate: () => {}, rates: RATES,
  status: 'idle', progress: { t: 0, d: 0 }, current: null,
  speak: () => {}, escuchar: () => {}, toggle: () => {}, stop: () => {},
  open: false, setOpen: () => {},
  thread: [], sending: false, paso: null, askError: null, sinCupo: null, ask: () => {}, analizar: () => {}, publicar: () => {},
}

export const useVoz = () => useContext(VozContext) || INERTE
