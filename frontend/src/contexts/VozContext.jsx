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
import { loadChatSession, saveChatSession, clearChatSession, sendWindow, MAX_STORED } from '../utils/chatSession'
import { traducirErrorDeChat, esCancelacion } from '../utils/errorChat'

const LS_ON = 'rendi:voz:on'
const LS_RATE = 'rendi:voz:rate'

// 1,25× por defecto: a la velocidad natural el resumen de 3 oraciones dura 24
// segundos y se hace largo. Las tres marcas son las del mockup; acelerar más
// allá de 1,4 empieza a sonar a ardilla aunque se conserve el tono.
export const RATES = [1, 1.25, 1.4]
const DEFAULT_RATE = 1.25

// Cuántos mensajes guarda LA conversación. Es el mismo tope que usaba el chat
// grande, y ahora es el único: antes la isla guardaba 8 y /ai 40, así que al
// pasar de una a otra la conversación se acortaba sola.
//
// La isla sigue siendo un acompañante y no una segunda pantalla de chat: eso
// se resuelve mostrando el FINAL en una tarjeta chica, no guardando menos.
// Guardar menos era perder mensajes de verdad.
const MAX_THREAD = MAX_STORED

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

// ─── Pedir permiso para sonar ANTES de tener qué decir ──────────────────────
// 🔴 EL PROBLEMA: Rendi pide sonar ~15 SEGUNDOS DESPUÉS del toque del usuario.
//
// Los navegadores sólo dejan que un sonido arranque solo si viene de la mano de
// algo que el usuario tocó. Nosotros tocamos "enviar", esperamos a que el
// modelo escriba la respuesta —diez, quince, veinte segundos— y recién ahí
// pedimos reproducir. Para ese momento el navegador ya no ve ningún gesto:
// lo rechaza, y al usuario le aparece un botón de play sin ninguna explicación.
// Reportado por Nico EN LAS DOS pantallas, celular y escritorio.
//
// La salida es pedir el permiso cuando el permiso existe: en el toque mismo.
// Se reproduce este clip MUDO de 54 bytes apenas el usuario manda la pregunta
// —dura un parpadeo y no se oye— y con eso el navegador marca al reproductor
// como "habilitado por el usuario". Cuando la respuesta llega quince segundos
// después, ya tiene permiso.
//
// Es la misma idea que dejar la puerta trabada antes de salir con las manos
// llenas: el momento de hacerlo no es cuando ya no te queda mano libre.
const SILENCIO = 'data:audio/wav;base64,UklGRi4AAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoAAACAgICAgICAgICA'

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
  const rateRef = useRef(rate)
  rateRef.current = rate

  // ── El reproductor ───────────────────────────────────────────────────────
  // 'idle' · 'preparing' (pidiendo el audio) · 'playing' · 'paused'
  // 'blocked' (el navegador no deja sonar sin que toquen algo — iPhone la
  // primera vez) · 'error' · 'quota' (se acabaron las fichas)
  const [status, setStatus] = useState('idle')
  const [progress, setProgress] = useState({ t: 0, d: 0 })
  // El resumen hablado en curso: { text, sig, url }
  const [current, setCurrent] = useState(null)

  // ── LA conversación con Rendi ────────────────────────────────────────────
  // UNA sola, no una por pantalla. La isla flotante y el chat grande de /ai
  // son dos ventanas a lo MISMO.
  //
  // Antes eran dos hilos separados que se copiaban al final: el chat grande
  // le "publicaba" su respuesta a la isla cuando terminaba. Tres agujeros, los
  // tres reportados:
  //   · Preguntabas en la isla, ibas a /ai y no estaba: la copia iba en un
  //     solo sentido.
  //   · Recargabas y la isla arrancaba vacía aunque /ai tuviera todo: sólo el
  //     chat grande guardaba.
  //   · Y el peor: preguntabas en /ai, te ibas a otra sección en el medio y la
  //     respuesta NO se copiaba tarde — se CANCELABA (`abortRef` al
  //     desmontar). Perdías la respuesta y la ficha igual se cobraba.
  //
  // Por qué el dueño es ESTE archivo y no el chat: el proveedor está montado
  // arriba de todo y no se desmonta al navegar. Es exactamente la misma razón
  // por la que el audio no se corta al cambiar de pantalla.
  const [open, setOpen] = useState(false)
  const [thread, setThread] = useState(() => loadChatSession())
  const [sending, setSending] = useState(false)
  // Qué está haciendo Rendi ahora mismo ("Buscando los precios de hoy"). Lo
  // manda el backend cuando sale a buscar datos; sirve para que la espera no
  // sea un "pensando" mudo de 15 segundos.
  const [paso, setPaso] = useState(null)
  const [askError, setAskError] = useState(null)
  // `loading` NO es lo mismo que `sending`: sending dura todo el turno, loading
  // se apaga en cuanto llega la primera letra. Es lo que decide si se ven los
  // puntitos o la respuesta escribiéndose.
  const [loading, setLoading] = useState(false)
  // El payload de "pasate a Pro" cuando el backend lo manda con un 429 o un
  // 403. Con esto la UI dibuja la card promocional en vez del cartel rojo.
  const [upgradeInfo, setUpgradeInfo] = useState(null)
  // La cuota que viene pegada al error, para refrescar el pie sin otro viaje.
  const [usageDelError, setUsageDelError] = useState(null)
  // Se acabó el cupo de escuchas: { message, upgrade }. Se dibuja como aviso
  // con su atajo a Planes, no como error.
  const [sinCupo, setSinCupo] = useState(null)
  // 🔴 POR QUÉ NO ARRANCÓ SOLA. Hasta acá, los CINCO motivos por los que Rendi
  // puede no ponerse a hablar se veían exactamente igual: un botón de play, sin
  // una palabra. El usuario no tenía cómo saber si el que decidió fue él (la
  // tiene callada), su plan, su navegador, o si Rendi directamente no escribió
  // nada para leer.
  //
  // Esto costó dos arreglos a ciegas —uno para el celular y otro para el
  // permiso del navegador— y el problema seguía. La salida no era una tercera
  // corazonada: era que el programa dijera qué estaba pasando.
  const [motivoSinVoz, setMotivoSinVoz] = useState(null)

  // Snapshot de la cartera para poder repreguntar desde cualquier pantalla.
  // Perezoso: recién se pide cuando hace falta, y se refresca si el chat
  // registró una operación.
  const snapRef = useRef(null)
  const sendingRef = useRef(false)
  // 🔴 DE QUÉ CONVERSACIÓN ES LO QUE ESTÁ LLEGANDO.
  //
  // Nada cancela el pedido en vuelo, y es a propósito: cancelar al desmontar
  // era el bug que se arregló —preguntabas en /ai, te ibas al panel y perdías
  // la respuesta con la ficha ya cobrada—. Pero quedó el caso de al lado sin
  // cubrir: tocar "Nueva conversación" mientras Rendi escribe. El hilo se
  // vacía, la respuesta sigue viajando, y al llegar se dibuja igual — sola, en
  // el chat vacío, contestando una pregunta que ya no se ve.
  //
  // La diferencia entre los dos casos es de QUIÉN es la respuesta, no de dónde
  // está el usuario. Así que en vez de cortar el pedido se le pone número al
  // turno: navegar no lo cambia (la respuesta sigue siendo tuya), vaciar sí
  // (esa conversación ya no existe) y lo que llegue tarde se descarta.
  const turnoRef = useRef(0)

  // Se guarda en cada cambio, incluidos los pedacitos del streaming. Escribir
  // en sessionStorage es SINCRÓNICO —bloquea la pantalla— así que la duda era
  // si 200 escrituras por respuesta se notan. MEDIDO en el navegador con el
  // hilo lleno (40 mensajes con tarjetas y audio firmado, 22 KB): 0,056 ms
  // cada una, 11 ms las 200 juntas, repartidos en los diez segundos que tarda
  // la respuesta. No se nota. Y es lo que hace que la conversación siga ahí
  // después de un F5.
  useEffect(() => { saveChatSession(thread) }, [thread])

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
  // Se hace UNA sola vez por carga de página: alcanza para el resto de la
  // sesión. Y va con bandera propia para que los avisos del reproductor no
  // muestren "hablando" por el parpadeo del clip mudo.
  const desbloqueadoRef = useRef(false)
  const desbloqueandoRef = useRef(false)
  const desbloquearElSonido = useCallback(() => {
    const a = audioRef.current
    if (!a || desbloqueadoRef.current) return
    desbloqueadoRef.current = true
    desbloqueandoRef.current = true
    const listo = () => { try { a.pause() } catch { /* ya parado */ } desbloqueandoRef.current = false }
    const fallo = () => { desbloqueadoRef.current = false; desbloqueandoRef.current = false }
    try {
      a.src = SILENCIO
      const p = a.play()
      if (p && p.then) p.then(listo, fallo)
      else listo()
    } catch { fallo() }
  }, [])

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
      // 🔴 ARRANCA SIEMPRE A VELOCIDAD NORMAL, aunque el usuario haya elegido
      // más rápido. Reportado por Nico: con 1,25× no arrancaba —se quedaba en
      // 0:02— y tocando 1× salía sola, sin apretar play.
      //
      // El motivo: el audio llega EN VIVO, generándose mientras suena. Pedirle
      // ir 25% más rápido antes de que haya bajado un solo byte hace que se
      // coma lo poco que tiene y se quede esperando lo que falta. A 1× lo
      // consume al ritmo que llega.
      //
      // La velocidad que eligió el usuario se aplica abajo, cuando el navegador
      // avisa que ya tiene con qué llegar hasta el final.
      aplicarRate(a, 1)
      await a.play()
      setStatus('playing')
    } catch (e) {
      if (e?.name === 'NotAllowedError') {
        // El navegador exige que el usuario toque algo antes del primer
        // sonido (iPhone, sobre todo). No es un error: mostramos el botón de
        // play y con ese toque queda habilitado para el resto de la sesión.
        setStatus('blocked')
        setMotivoSinVoz('Tu navegador no la deja arrancar sola: tocá una vez y queda habilitada')
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
   * PREGUNTARLE A RENDI. Es la ÚNICA forma — la usan las dos pantallas.
   *
   * Antes había dos: ésta y `send()` adentro del chat grande, cada una con su
   * propio hilo, su propio acumulador de texto y su propia traducción de
   * errores. Eran la misma función escrita dos veces, y por eso se
   * desincronizaban. Ahora el chat grande es una VISTA de esto.
   *
   * Vive en el proveedor —que está montado arriba de todo y no se desmonta al
   * navegar— y ésa es la parte que importa: si preguntás en /ai y te vas al
   * Dashboard en el medio, la respuesta sigue llegando. Antes se cancelaba.
   *
   * `analisis` = { screen, params }: el turno lo disparó el botón ✦ de una
   * pantalla. Cambia tres cosas: la pregunta la escribe el servidor, se
   * descuenta del cupo de análisis y no del de consultas, y llega de yapa el
   * dato calculado de esa pantalla.
   * `snapshot`: sólo para el modo LIBRO del asesor, donde la foto la arma la
   * página. En el uso normal se resuelve solo.
   */
  const ask = useCallback(async (texto, { analisis, snapshot: snapDeAfuera } = {}) => {
    const content = (texto || '').trim()
    if ((!content && !analisis) || sendingRef.current) return
    // 🔴 LO PRIMERO, Y SIN `await` ANTES. Estamos adentro del toque del usuario
    // —esto lo llama el botón de enviar, un chip o el ✦— y ese es el único
    // momento en que el navegador concede el permiso para sonar. Una sola
    // línea de espera acá arriba y el gesto ya no cuenta.
    if (enabled) desbloquearElSonido()
    sendingRef.current = true
    setSending(true)
    setLoading(true)
    setPaso(null)
    setAskError(null)
    setUpgradeInfo(null)
    setMotivoSinVoz(null)
    const miTurno = turnoRef.current
    // ¿Esta conversación sigue siendo la que está en pantalla?
    const vigente = () => turnoRef.current === miTurno
    const previos = thread
    // Con el botón ✦ todavía no sabemos qué se preguntó: la pregunta la
    // escribe el servidor y llega en el primer frame, antes que la respuesta.
    // Se espera ese pestañeo en vez de pintar una burbuja inventada que
    // después habría que corregir en pantalla.
    let preguntaPuesta = !analisis
    if (!analisis) setThread(t => [...t, { role: 'user', content }].slice(-MAX_THREAD))
    const onPregunta = (q) => {
      if (!vigente()) return
      preguntaPuesta = true
      setThread(t => [...t, { role: 'user', content: q }].slice(-MAX_THREAD))
    }
    try {
      if (snapDeAfuera) snapRef.current = snapDeAfuera
      else if (!snapRef.current) snapRef.current = await fetchAiSnapshot()
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
      const pintar = (texto) => { if (!vigente()) return; setThread(t => {
        const copia = t.slice()
        if (agregado && copia.length && copia[copia.length - 1].role === 'assistant') {
          copia[copia.length - 1] = { ...copia[copia.length - 1], content: texto }
          return copia
        }
        agregado = true
        return [...copia, { role: 'assistant', content: texto }].slice(-MAX_THREAD)
      }) }
      const onDelta = (c) => {
        acc += c
        setLoading(false)          // ya hay texto: se apagan los puntitos
        // Se pinta la PROSA, no el texto crudo: así el bloque de datos del
        // final no aparece medio escrito en pantalla mientras llega.
        const { prose } = parseStructured(stripMarkdown(acc))
        if (prose) pintar(prose)
      }
      // 🔴 EL AUDIO NO ESPERA A LAS TARJETAS.
      //
      // Antes se arrancaba recién con el frame final, o sea cuando el modelo
      // había terminado de escribir TODO —incluidas las tarjetas, que el
      // usuario ya no necesita oír—. Medido: 4,7 · 4,9 · 5,3 segundos de
      // silencio con la respuesta entera escrita en pantalla, y recién ahí
      // empezaba el pedido del audio, que suma el suyo.
      //
      // Ahora el servidor manda el resumen hablado apenas lo termina de
      // escribir (frame `voz`), y esto lo agarra al vuelo. Se dispara una sola
      // vez por turno: si además viniera en el frame final, `yaSono` lo frena.
      let yaSono = false
      const arrancarAudio = async (v) => {
        if (yaSono || !v || !vigente()) return
        yaSono = true
        setCurrent(v)
        if (!enabled) { setMotivoSinVoz('La tenés silenciada'); return }
        // Con el parlante prendido arranca solo, salvo que el plan pague con
        // cupo propio de escuchas (Free) — ahí siempre lo tiene que tocar él.
        // La cuota se pregunta ACÁ y no antes del turno: el turno ya descontó
        // su ficha y con una sola de saldo la respuesta cambia.
        const u = await api.get('/ai/usage').catch(() => null)
        if (!puedeArrancarSolo(u)) {
          setMotivoSinVoz(u?.listens_limit != null
            ? 'Tu plan tiene un audio por semana: lo arrancás vos'
            : 'Te quedaste sin consultas por esta semana')
          return
        }
        speak(v)
      }

      // El turno terminó en una herramienta: lo que se escribió era el
      // preámbulo ("dejame ver los precios…"), no la respuesta. Se borra y
      // vuelve el "pensando" hasta que llegue la de verdad.
      const onReset = () => {
        if (!vigente()) return
        acc = ''
        setLoading(true)
        if (agregado) { setThread(t => t.slice(0, -1)); agregado = false }
        // 🔴 Y EL AUDIO TAMBIÉN SE BORRA, no sólo el texto.
        //
        // Si el preámbulo traía su resumen hablado, Rendi ya está diciendo en
        // voz alta "dejame ver los precios" — algo que acaba de desaparecer de
        // la pantalla. Peor: `yaSono` quedaba en true, así que cuando llegaba
        // la respuesta DE VERDAD el audio no arrancaba nunca. El usuario
        // escuchaba el preámbulo, se quedaba esperando el resto, y la escucha
        // ya estaba gastada.
        //
        // El servidor también limpia su copia (frame `reset` en utils/api.js);
        // eso solo no alcanzaba, porque acá ya habíamos empezado a hablar.
        if (yaSono) {
          stop()
          setCurrent(null)
          yaSono = false
        }
      }
      const res = await api.chatStream(
        // `voz: enabled` — si el parlante está apagado, el servidor le pide al
        // modelo que NO escriba el resumen hablado. Son ~130 tokens de salida
        // por respuesta que se pagaban aunque nadie los fuera a escuchar.
        { messages, snapshot: snapRef.current, voz: enabled,
          ...(analisis ? { analisis } : {}) },
        { onDelta, onReset, onPaso: setPaso, onPregunta, onVoz: arrancarAudio },
      )
      const { prose, meta } = parseStructured(stripMarkdown(acc))
      if (!vigente()) return          // vaciaron el chat mientras llegaba
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
      // Red de seguridad: si el resumen hablado no vino adelantado (un turno
      // donde el modelo lo escribió último igual, o el respaldo que lo saca
      // del titular), acá está el que viaja en el frame final. Si ya sonó,
      // esto no hace nada.
      await arrancarAudio(res?.voz)
      if (!res?.voz && !yaSono && vigente() && enabled) {
        setMotivoSinVoz('Esta respuesta no trajo resumen para escuchar')
      }
    } catch (e) {
      // Cancelar no es fallar: tocó "Nueva conversación" y ya se limpió todo.
      if (esCancelacion(e) || !vigente()) return
      const { mensaje, usage, upgrade } = traducirErrorDeChat(e)
      setAskError(mensaje)
      if (usage) setUsageDelError(usage)
      if (upgrade) setUpgradeInfo(upgrade)
      // Sacar del hilo lo que falló, para que se pueda reintentar: la burbuja
      // a medio escribir si la hubo, y la pregunta. Con el botón ✦ un 429
      // revienta ANTES del frame con la pregunta: ahí no hay burbuja que sacar
      // y este recorte se llevaría la respuesta anterior.
      setThread(t => {
        const sinParcial = agregado ? t.slice(0, -1) : t
        return preguntaPuesta ? sinParcial.slice(0, -1) : sinParcial
      })
    } finally {
      // SÓLO si este turno sigue siendo el de la pantalla. Si vaciaron el chat
      // y ya se preguntó otra cosa, soltar acá le sacaría el lugar al turno
      // nuevo y se podrían encimar dos.
      if (vigente()) {
        sendingRef.current = false
        setSending(false)
        setLoading(false)
        setPaso(null)
      }
    }
  }, [thread, enabled, speak, stop, desbloquearElSonido])

  /** Empezar de cero. Lo toca "Nueva conversación" en /ai. */
  const limpiar = useCallback(() => {
    // Lo que venga del turno anterior ya no es de nadie.
    turnoRef.current += 1
    // Y la pantalla queda libre AHORA. Sin esto el chat recién vaciado se
    // quedaba diciendo "pensando…" por la respuesta vieja, y no dejaba
    // preguntar hasta que ésa terminara — hasta veinte segundos mirando un
    // chat vacío que dice que está pensando algo que ya se descartó.
    sendingRef.current = false
    setSending(false)
    setLoading(false)
    setPaso(null)
    clearChatSession()
    setThread([])
    setAskError(null)
    setUpgradeInfo(null)
    setUsageDelError(null)
  }, [])

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
    // El clip mudo del desbloqueo pasa por acá igual que un audio de verdad.
    // Sin esta guarda, mandar una pregunta mostraba "Rendi está hablando" por
    // un parpadeo, sin que hubiera nada que oír.
    const mudo = () => desbloqueandoRef.current
    const onTime = () => { if (!mudo()) setProgress({ t: a.currentTime || 0, d: a.duration || 0 }) }
    const onEnd = () => { if (!mudo()) { setStatus('idle'); setProgress(p => ({ ...p, t: 0 })) } }
    const onErr = () => { if (!mudo()) setStatus('error') }
    const onPlay = () => { if (!mudo()) setStatus('playing') }
    const onPause = () => { if (!mudo()) setStatus(s => (s === 'playing' ? 'paused' : s)) }
    // LA VELOCIDAD SUBE CUANDO HAY CON QUÉ, Y BAJA SI SE QUEDA SIN.
    //
    // `canplaythrough` es el navegador diciendo "ya puedo llegar al final sin
    // frenar": recién ahí tiene sentido correr más rápido. Y `waiting` es lo
    // contrario —se quedó sin audio— así que se vuelve a 1 hasta que haya.
    // Si nunca alcanza para más, se escucha a velocidad normal, que es
    // exactamente lo que hay que hacer: sonar despacio es mejor que no sonar.
    const onPuedeLlegar = () => { if (rateRef.current !== 1) aplicarRate(a, rateRef.current) }
    const onSeQuedoSinAudio = () => { try { a.playbackRate = 1 } catch { /* sin soporte */ } }
    a.addEventListener('canplaythrough', onPuedeLlegar)
    a.addEventListener('waiting', onSeQuedoSinAudio)
    a.addEventListener('timeupdate', onTime)
    a.addEventListener('loadedmetadata', onTime)
    a.addEventListener('ended', onEnd)
    a.addEventListener('error', onErr)
    a.addEventListener('play', onPlay)
    a.addEventListener('pause', onPause)
    return () => {
      a.removeEventListener('canplaythrough', onPuedeLlegar)
      a.removeEventListener('waiting', onSeQuedoSinAudio)
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
    thread, sending, loading, paso, askError, upgradeInfo, usageDelError, motivoSinVoz,
    sinCupo, ask, analizar, limpiar,
  }), [enabled, setEnabled, rate, setRate, status, progress, current,
       speak, escuchar, toggle, stop, open, thread, sending, loading, paso, askError,
       upgradeInfo, usageDelError, sinCupo, motivoSinVoz, ask, analizar, limpiar])

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
  thread: [], sending: false, paso: null, askError: null, sinCupo: null, loading: false, upgradeInfo: null, usageDelError: null, motivoSinVoz: null,
  ask: () => {}, analizar: () => {}, limpiar: () => {},
}

export const useVoz = () => useContext(VozContext) || INERTE
