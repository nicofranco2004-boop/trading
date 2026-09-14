import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  sePuedeGrabar, formatoQueGraba, tipoBase, mandarAlServidor,
  MAX_SEGUNDOS, LOS_ERRORES,
} from './useDictado.js'

// El hook maneja MediaRecorder y getUserMedia, que no existen sin un navegador
// de verdad. Para la guarda de arriba alcanza con mirar la fuente: es un guard
// contra una regresión puntual, no un test del flujo (ése se hizo en el
// navegador, con un micrófono simulado).
const fuente = () => readFileSync(new URL('./useDictado.js', import.meta.url), 'utf8')

// El navegador de mentira. Sólo lo que el hook mira. `navigator` en node es
// de sólo lectura, así que va por vi.stubGlobal y no por asignación directa.
function conNavegador({ mediaRecorder = true, getUserMedia = true, soporta = () => true } = {}) {
  const MR = mediaRecorder
    ? Object.assign(function () {}, { isTypeSupported: soporta })
    : undefined
  vi.stubGlobal('window', globalThis)
  vi.stubGlobal('MediaRecorder', MR)
  vi.stubGlobal('navigator', getUserMedia ? { mediaDevices: { getUserMedia: () => {} } } : {})
}

afterEach(() => { vi.unstubAllGlobals() })

describe('sin soporte el micrófono ni se dibuja', () => {
  it('un navegador sin MediaRecorder', () => {
    conNavegador({ mediaRecorder: false })
    expect(sePuedeGrabar()).toBe(false)
  })

  it('un navegador sin permiso de dispositivos (http, no https)', () => {
    // getUserMedia no existe fuera de un origen seguro. Un botón que al
    // tocarlo sólo sabe decir "tu navegador no puede" es peor que no estar.
    conNavegador({ getUserMedia: false })
    expect(sePuedeGrabar()).toBe(false)
  })

  it('con las dos cosas, sí', () => {
    conNavegador()
    expect(sePuedeGrabar()).toBe(true)
  })
})

describe('el formato tiene que ser el que este navegador SABE grabar', () => {
  it('Chrome y Firefox: webm con opus', () => {
    conNavegador({ soporta: (t) => t.startsWith('audio/webm') })
    expect(formatoQueGraba()).toBe('audio/webm;codecs=opus')
  })

  it('Safari: mp4 — si esto se cae, el micrófono no anda en iPhone', () => {
    conNavegador({ soporta: (t) => t === 'audio/mp4' })
    expect(formatoQueGraba()).toBe('audio/mp4')
  })

  it('si no soporta ninguno, que elija el navegador', () => {
    conNavegador({ soporta: () => false })
    expect(formatoQueGraba()).toBe('')
  })

  it('el content-type que viaja va SIN los codecs', () => {
    // OpenAI decide cómo decodificar por la extensión del archivo, y el
    // servidor la saca del content-type. Mandar "audio/webm;codecs=opus"
    // hace que rechace un audio perfectamente válido.
    expect(tipoBase('audio/webm;codecs=opus')).toBe('audio/webm')
    expect(tipoBase('audio/mp4')).toBe('audio/mp4')
    expect(tipoBase('')).toBe('audio/webm')
    expect(tipoBase(null)).toBe('audio/webm')
  })
})

describe('lo que se manda al servidor', () => {
  beforeEach(() => { conNavegador() })

  it('va como formulario, con el audio y su tipo', async () => {
    const fetchFalso = vi.fn(async () => ({ ok: true, json: async () => ({ texto: 'hola' }) }))
    vi.stubGlobal('fetch', fetchFalso)
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' })
    const { texto } = await mandarAlServidor(blob, 'audio/webm')
    expect(texto).toBe('hola')
    const [url, opciones] = fetchFalso.mock.calls[0]
    expect(url).toBe('/api/ai/dictado')
    expect(opciones.method).toBe('POST')
    expect(opciones.body).toBeInstanceOf(FormData)
    expect(opciones.body.get('audio')).toBeInstanceOf(Blob)
    expect(opciones.body.get('audio').type).toBe('audio/webm')
    // El Content-Type del formulario lo pone el navegador: si lo ponemos
    // nosotros se pierde el separador y el servidor no puede leer el archivo.
    expect(opciones.headers?.['Content-Type']).toBeUndefined()
  })

  it('el texto vuelve sin espacios de sobra', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({ texto: '  ¿Cómo viene?  ' }) }))
    expect((await mandarAlServidor(new Blob(['x']), 'audio/webm')).texto).toBe('¿Cómo viene?')
  })

  it('sin texto devuelve vacío, no revienta', async () => {
    // Vacío = no se escuchó nada. Es una respuesta legítima del servidor, no
    // un error: el usuario tocó el micrófono y no habló.
    vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({}) }))
    expect((await mandarAlServidor(new Blob(['x']), 'audio/webm')).texto).toBe('')
  })

  it('un error del servidor sube con SU mensaje, no uno inventado', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: false, status: 503,
      json: async () => ({ detail: { message: 'El micrófono no está disponible.' } }),
    }))
    await expect(mandarAlServidor(new Blob(['x']), 'audio/webm'))
      .rejects.toMatchObject({ mensaje: 'El micrófono no está disponible.' })
  })

  it('un error sin cuerpo tampoco revienta', async () => {
    vi.stubGlobal('fetch', async () => ({
      ok: false, status: 500, json: async () => { throw new Error('no es json') },
    }))
    await expect(mandarAlServidor(new Blob(['x']), 'audio/webm')).rejects.toThrow()
  })
})

describe('los avisos de cuando sale mal', () => {
  it('los cinco dicen qué pasó y en castellano', () => {
    for (const [clave, e] of Object.entries(LOS_ERRORES)) {
      expect(e.titulo, clave).toBeTruthy()
      expect(e.texto, clave).toBeTruthy()
      // Nada de jerga del navegador en la cara del usuario.
      expect(e.titulo + e.texto).not.toMatch(/NotAllowedError|getUserMedia|MediaRecorder|undefined/)
    }
  })

  it('el de permiso dice DÓNDE se arregla', () => {
    // Rechazar el permiso una vez cuesta caro: volver a habilitarlo hay que
    // ir a la configuración del navegador, y nadie sabe dónde está.
    expect(LOS_ERRORES.permiso.texto).toMatch(/candado|barra de direcciones/i)
  })
})

describe('Free y Plus: la sugerencia viaja', () => {
  beforeEach(() => { conNavegador() })

  it('la sugerencia del servidor llega al que la va a mostrar', async () => {
    // Sin esto, un Free dicta, el texto cae en el cuadro, lo manda y el chat
    // se lo rechaza con "el chat libre es solo Pro". Medido: la pregunta
    // exacta de un chip salió "porfolio" y rebotó por una letra.
    vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({
      texto: 'cómo viene mi cartera',
      sugerida: { pregunta: '¿Cómo está mi portfolio en general?', parecido: 1 },
    }) }))
    const r = await mandarAlServidor(new Blob(['x']), 'audio/webm')
    expect(r.texto).toBe('cómo viene mi cartera')
    expect(r.sugerida.pregunta).toBe('¿Cómo está mi portfolio en general?')
  })

  it('en Pro no viene ninguna y eso no rompe nada', async () => {
    vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({ texto: 'lo que sea' }) }))
    expect((await mandarAlServidor(new Blob(['x']), 'audio/webm')).sugerida).toBeNull()
  })
})

describe('reintentar después de un error', () => {
  it('el botón NO queda muerto tras un error', () => {
    // Visto en el navegador: tras "no se escuchó nada" el botón seguía
    // viéndose activo pero `grabar()` no hacía nada, porque sólo salía de
    // 'reposo'. El usuario lo tocaba y no pasaba nada.
    const src = fuente()
    expect(src).toMatch(/estado !== 'reposo' && estado !== 'error'/)
  })
})

describe('en el celular se tiene que poder tocar', () => {
  // MEDIDO en 375px: el círculo del micrófono daba 30px y los botones del
  // panel 36 de alto. El mínimo para un dedo son 44. No es un detalle de
  // estética: el micrófono en el teléfono es EL caso de uso —caminando,
  // manejando— y un blanco de 30px se falla.
  const boton = () => readFileSync(
    new URL('../components/voz/BotonMicrofono.jsx', import.meta.url), 'utf8')

  it('el micrófono tiene área de toque aunque el círculo sea chico', () => {
    // Agrandar el círculo lo dejaba desparejo al lado del de enviar (28px),
    // así que crece el ÁREA y no el dibujo.
    expect(boton()).toMatch(/after:-inset-2/)
  })

  it('los botones del panel miden 44 en celular', () => {
    const src = boton()
    // h-11 = 44px en celular, h-9 = 36 de sm: para arriba, donde hay mouse.
    expect(src).toMatch(/h-11 sm:h-9/)
    expect(src).not.toMatch(/className="flex-1 h-9 /)
  })

  it('el medidor ocupa el ancho y no queda amontonado', () => {
    // Con ancho fijo daba 108px de los 303 disponibles: se leía como puntitos
    // y no como un medidor, que es justo lo único que prueba que toma audio.
    expect(boton()).toMatch(/flex-1 min-w-\[2px\]/)
  })
})

describe('el tope de grabación', () => {
  it('son 30 segundos, los mismos que el servidor', () => {
    // Si los dos números se separan, el navegador manda algo que el servidor
    // rechaza — y el usuario pierde lo que dijo sin entender por qué.
    expect(MAX_SEGUNDOS).toBe(30)
  })
})
