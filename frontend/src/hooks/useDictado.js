// useDictado — grabar lo que el usuario dice y devolverlo como texto.
// ═══════════════════════════════════════════════════════════════════════════
// La mitad del navegador del micrófono. El motor del servidor es
// backend/ai/oido.py; acá sólo se graba, se mide el nivel para que se vea que
// está tomando, y se manda.
//
// 🔴 LA REGLA QUE DEFINE TODO: el texto NO SE MANDA SOLO. Este hook termina
// devolviendo el texto y nada más; ponerlo en el cuadro y decidir si se manda
// es de quien lo usa. Un número mal escuchado en "compré a sesenta y cinco
// mil" se carga en la cartera y queda; un toque de más es barato al lado.
//
// Los estados, que son los del mockup:
//   'reposo'         nada pasando
//   'pidiendo'       esperando que el usuario le dé permiso al navegador
//   'escuchando'     grabando
//   'transcribiendo' mandado, esperando el texto
//   'error'          con `error` cargado (ver LOS_ERRORES)
//
// No hay estado 'revisar': cuando llega el texto, este hook vuelve a 'reposo'
// y se lo entrega al que lo llamó. Revisar es de la pantalla, no del motor.

import { useCallback, useEffect, useRef, useState } from 'react'

// El mismo tope que el servidor (ai/oido.py MAX_SEGUNDOS). Acá corta antes de
// mandar; allá es la red por si el navegador miente.
export const MAX_SEGUNDOS = 30

// Cuántas barritas tiene el medidor de nivel. Es decoración funcional: lo
// único que prueba que el micrófono está tomando de verdad es verlas moverse
// con la voz. Un contador corriendo no lo prueba — corre igual con el
// micrófono mudo.
export const BARRITAS = 20

export const LOS_ERRORES = {
  permiso: {
    titulo: 'No me diste permiso al micrófono',
    texto: 'Sin permiso no puedo escucharte. Se habilita desde el candado de la barra de direcciones.',
  },
  sin_microfono: {
    titulo: 'No encontré un micrófono',
    texto: 'Puede estar desconectado, o en uso por otra aplicación.',
  },
  nada: {
    titulo: 'No se escuchó nada',
    texto: 'Puede ser el micrófono equivocado, o que hablaste muy bajo.',
  },
  no_soportado: {
    titulo: 'Este navegador no puede grabar',
    texto: 'Probá desde Chrome, Safari o Firefox actualizados.',
  },
  fallo: {
    titulo: 'No pude pasar tu audio a texto',
    texto: 'Probá de nuevo, o escribí la pregunta.',
  },
}

/** ¿Este navegador puede grabar? Sin esto, el botón ni se dibuja. */
export function sePuedeGrabar() {
  return !!(typeof window !== 'undefined'
    && window.MediaRecorder
    && navigator?.mediaDevices?.getUserMedia)
}

/**
 * El formato que sabe grabar ESTE navegador. Chrome y Firefox hacen webm,
 * Safari hace mp4. Se elige acá y se le dice al servidor en el Content-Type:
 * OpenAI decide cómo decodificar por la extensión del archivo, así que mandar
 * el sufijo equivocado hace que rechace un audio perfectamente válido.
 */
export function formatoQueGraba() {
  const candidatos = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
  for (const c of candidatos) {
    try { if (window.MediaRecorder?.isTypeSupported?.(c)) return c } catch { /* sigue */ }
  }
  return ''   // que el navegador elija; igual mandamos lo que diga el blob
}

/** El content-type limpio, sin los `;codecs=`, que es lo que espera el server. */
export function tipoBase(mime) {
  return String(mime || '').split(';')[0].trim() || 'audio/webm'
}

export function useDictado({ onTexto, onAntesDeGrabar } = {}) {
  const [estado, setEstado] = useState('reposo')
  const [error, setError] = useState(null)
  const [segundos, setSegundos] = useState(0)
  const [niveles, setNiveles] = useState(() => new Array(BARRITAS).fill(0))
  // { pregunta, parecido, dicho } — sólo en Free y Plus, cuando lo dictado se
  // parece a una de las doce preguntas que esos planes pueden mandar.
  const [sugerida, setSugerida] = useState(null)

  const recRef = useRef(null)
  const streamRef = useRef(null)
  const audioCtxRef = useRef(null)
  const rafRef = useRef(null)
  const timerRef = useRef(null)
  const canceladoRef = useRef(false)
  const pedazosRef = useRef([])

  // Soltar TODO. Se llama al terminar, al cancelar, al fallar y al desmontar.
  // Si el stream no se cierra, el navegador deja prendida la lucecita del
  // micrófono — y el usuario, con razón, cree que lo seguimos escuchando.
  const soltar = useCallback(() => {
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = null }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    try { streamRef.current?.getTracks().forEach(t => t.stop()) } catch { /* ya cerrado */ }
    streamRef.current = null
    try { audioCtxRef.current?.close() } catch { /* ya cerrado */ }
    audioCtxRef.current = null
    recRef.current = null
    setNiveles(new Array(BARRITAS).fill(0))
  }, [])

  useEffect(() => soltar, [soltar])

  const cancelar = useCallback(() => {
    canceladoRef.current = true
    try { recRef.current?.stop() } catch { /* ya parado */ }
    soltar()
    setEstado('reposo')
    setSegundos(0)
  }, [soltar])

  const terminar = useCallback(() => {
    // `stop()` dispara el onstop del grabador, que es donde se manda.
    try { recRef.current?.stop() } catch { soltar(); setEstado('reposo') }
  }, [soltar])

  const grabar = useCallback(async () => {
    // Se puede arrancar desde 'reposo' Y desde 'error': reintentar es lo
    // natural después de que algo salió mal, y el botón sigue viéndose
    // activo. Cuando esto sólo salía de 'reposo', tras cualquier error el
    // micrófono quedaba MUERTO —se tocaba y no pasaba nada— hasta tocar
    // "Escribirla a mano". Visto en el navegador, no deducido.
    if (estado !== 'reposo' && estado !== 'error') return
    if (!sePuedeGrabar()) { setError(LOS_ERRORES.no_soportado); setEstado('error'); return }

    setError(null)
    canceladoRef.current = false
    pedazosRef.current = []
    setEstado('pidiendo')

    // Que Rendi se calle ANTES de abrir el micrófono: si sigue hablando, el
    // micrófono la escucha a ella y la transcripción sale mezclada.
    try { onAntesDeGrabar?.() } catch { /* que no frene la grabación */ }

    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      const n = e?.name || ''
      setError(n === 'NotFoundError' || n === 'DevicesNotFoundError'
        ? LOS_ERRORES.sin_microfono : LOS_ERRORES.permiso)
      setEstado('error')
      return
    }
    streamRef.current = stream

    // El medidor de nivel. Es lo único que prueba que el micrófono toma: un
    // contador de segundos corre igual con el micrófono mudo, y el usuario se
    // entera de que no lo escuchó recién cuando vuelve el texto vacío.
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext
      const ctx = new Ctx()
      audioCtxRef.current = ctx
      const analizador = ctx.createAnalyser()
      analizador.fftSize = 256
      ctx.createMediaStreamSource(stream).connect(analizador)
      const datos = new Uint8Array(analizador.frequencyBinCount)
      const mirar = () => {
        analizador.getByteTimeDomainData(datos)
        let pico = 0
        for (let i = 0; i < datos.length; i++) {
          const v = Math.abs(datos[i] - 128) / 128
          if (v > pico) pico = v
        }
        setNiveles(prev => [...prev.slice(1), Math.min(1, pico * 2.2)])
        rafRef.current = requestAnimationFrame(mirar)
      }
      rafRef.current = requestAnimationFrame(mirar)
    } catch {
      // Sin medidor se puede grabar igual; se pierde la señal visual, no la
      // función. No es motivo para dejar al usuario sin micrófono.
    }

    let rec
    try {
      const mime = formatoQueGraba()
      rec = new window.MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    } catch {
      soltar(); setError(LOS_ERRORES.no_soportado); setEstado('error'); return
    }
    recRef.current = rec

    rec.ondataavailable = (e) => { if (e.data?.size) pedazosRef.current.push(e.data) }
    rec.onstop = async () => {
      const pedazos = pedazosRef.current
      pedazosRef.current = []
      const mime = rec.mimeType || formatoQueGraba() || 'audio/webm'
      soltar()
      setSegundos(0)
      if (canceladoRef.current) { setEstado('reposo'); return }

      const blob = new Blob(pedazos, { type: mime })
      if (!blob.size) { setError(LOS_ERRORES.nada); setEstado('error'); return }

      setEstado('transcribiendo')
      try {
        const { texto, sugerida } = await mandarAlServidor(blob, tipoBase(mime))
        setEstado('reposo')
        // Texto vacío = no se escuchó nada. NO es un error del servidor: es la
        // respuesta correcta a un micrófono que no tomó nada, y el usuario
        // tiene que poder reintentar sin un cartel rojo.
        if (!texto) { setError(LOS_ERRORES.nada); setEstado('error'); return }
        // En Free y Plus el servidor devuelve con qué pregunta de las doce se
        // parece lo dictado. Se muestra para CONFIRMAR en vez de tirar el
        // texto al cuadro: si lo mandara tal cual, el chat se lo rechazaría.
        if (sugerida) { setSugerida({ ...sugerida, dicho: texto }); return }
        onTexto?.(texto)
      } catch (e) {
        setError({ ...LOS_ERRORES.fallo, ...(e?.mensaje ? { texto: e.mensaje } : {}) })
        setEstado('error')
      }
    }

    try {
      rec.start()
    } catch {
      soltar(); setError(LOS_ERRORES.no_soportado); setEstado('error'); return
    }
    setEstado('escuchando')
    setSegundos(0)
    timerRef.current = setInterval(() => {
      setSegundos(s => {
        const n = s + 1
        // El tope corta SOLO, no avisa y deja seguir: pasado eso transcribe
        // peor y cuesta más. Lo grabado hasta acá se manda igual — cortar y
        // tirar lo que dijo sería lo peor de los dos mundos.
        if (n >= MAX_SEGUNDOS) { try { rec.stop() } catch { /* ya parado */ } }
        return n
      })
    }, 1000)
  }, [estado, onAntesDeGrabar, onTexto, soltar])

  return {
    estado, error, segundos, niveles, sugerida,
    grabando: estado === 'escuchando',
    ocupado: estado !== 'reposo' && estado !== 'error',
    grabar, terminar, cancelar,
    limpiarError: () => { setError(null); setEstado('reposo') },
    // Confirmar la sugerencia manda la pregunta EXACTA de la lista, no lo que
    // se dictó: es lo que hace que el candado de las doce siga cerrado.
    aceptarSugerida: () => { const q = sugerida?.pregunta; setSugerida(null); if (q) onTexto?.(q) },
    descartarSugerida: () => setSugerida(null),
  }
}

/** Manda el audio y devuelve el texto. Separado para poder probarlo suelto. */
export async function mandarAlServidor(blob, contentType) {
  const fd = new FormData()
  // El Content-Type del FORMULARIO lo pone el navegador solo (necesita poner
  // su propio separador). El del AUDIO viaja en el blob, y por eso el blob se
  // rearma con su mime: sin eso el servidor no sabe cómo decodificarlo y
  // rechaza un audio perfectamente válido.
  fd.append('audio', new Blob([blob], { type: contentType }), 'dictado')
  const res = await fetch('/api/ai/dictado', {
    method: 'POST',
    credentials: 'include',
    body: fd,
  })
  if (!res.ok) {
    let mensaje = ''
    try { mensaje = (await res.json())?.detail?.message || '' } catch { /* sin cuerpo */ }
    const err = new Error(mensaje || 'dictado_fallo')
    err.mensaje = mensaje
    throw err
  }
  const data = await res.json()
  return { texto: (data?.texto || '').trim(), sugerida: data?.sugerida || null }
}
