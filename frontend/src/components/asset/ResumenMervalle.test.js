// «✦ Analizar con Mervall-E» montado dentro de la ficha de verdad
// (testing/navegadorMinimo.js), con el servidor simulado en la frontera
// (utils/api) y el chat espiado (useVoz). Lo que se prueba es lo que ve la persona:
//   · el botón está en «La lectura de hoy» (mockup aprobado por Nico, 30/10);
//   · si el resumen ya existe, se muestra solo, sin pedir nada, y se puede cerrar;
//   · si no, al tocar el botón aparece el texto y el resto de la ficha sigue;
//   · el tope y las fallas se dicen con calma, y la ficha no se rompe;
//   · las preguntas para seguir abren el chat con la pregunta del servidor;
//   · sin IA (null), no hay ni botón.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic } from '../../testing/navegadorMinimo'

function puntos(n, f) {
  return Array.from({ length: n }, (_, i) => ({
    d: new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10),
    c: f(i), s50: f(i) * 1.02, s200: f(i) * 1.05, rsi: 40,
  }))
}
const BASE = {
  disponible: true, moneda: 'usd', ticker: 'NVDA', convertida: null,
  puntos: puntos(504, i => 250 - i * 0.03),
  lectura: { ruedas: 760, fecha: '2026-10-21', precio: 235, media50: 241, dist_media50: -2.5,
    media200: 250, dist_media200: -6, pendiente_media200: -1, rsi: 38, dist_maximo_12m: -14, anio_completo: true },
}
const TEXTO = 'En un año subió 23 %. Desde el 6 de octubre bajó de 243 a 213 dólares, y el 21 de octubre cerró en 222.'

let respuestas, alPost
// Lo real de utils/api (getClientContext: de quién es la copia de los dibujos)
// con `api` simulado.
vi.mock('../../utils/api', async (original) => ({
  ...(await original()),
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      return Promise.resolve(clave ? respuestas[clave] : [])
    }),
    post: vi.fn((ruta) => alPost(ruta)),
  },
}))

// El chat: el ✦ de las preguntas para seguir (lo demás de VozContext, real).
const voz = { analizar: vi.fn(), setOpen: vi.fn() }
vi.mock('../../contexts/VozContext', async (original) => ({
  ...(await original()),
  useVoz: () => ({ ...(original.useVoz?.() || {}), ...voz }),
}))

let LecturaTecnica, api
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
  ;({ api } = await import('../../utils/api'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  api.post.mockClear()
  voz.analizar.mockClear()
  voz.setOpen.mockClear()
})

const el = () => h(LecturaTecnica, { asset: 'NVDA', symbolMiniChart: 'NVDA' })
async function dibujar(resumen, extra = {}) {
  respuestas = { '/tecnico/NVDA?moneda=usd': { ...BASE, ...extra, resumen } }
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
async function tocar(parte) {
  await clic(montado.contenedor, buscarBoton(montado.contenedor, parte))
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

const BOTON = 'Analizar con Mervall-E'
// La tarjeta «La lectura de hoy» (su región, por el nombre que le da a lectores de pantalla).
function lecturaDeHoy() {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('aria-label') === 'La lectura de hoy') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe('Analizar con Mervall-E en la ficha', () => {
  it('el botón está en «La lectura de hoy»', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    expect(buscarBoton(lecturaDeHoy(), BOTON)).toBeTruthy()
    // Uno solo en toda la ficha: no compite con otro botón de Mervall-E.
    expect(texto(montado.contenedor).split(BOTON).length - 1).toBe(1)
  })

  it('si ya existe se muestra solo, sin pedir nada, y se puede cerrar', async () => {
    const t = await dibujar({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    expect(texto(lecturaDeHoy())).toContain(TEXTO)
    expect(t).toContain('al cierre del 21/10')
    expect(t).toContain('No es una recomendación')
    expect(t).toContain('¿Está en tendencia?')
    expect(api.post).not.toHaveBeenCalled()
    expect(await tocar(BOTON)).not.toContain(TEXTO)
    expect(await tocar(BOTON)).toContain(TEXTO)
    expect(api.post).not.toHaveBeenCalled()
  })

  it('si no existe: al tocar el botón aparece el texto y la ficha sigue igual', async () => {
    let t = await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    expect(t).not.toContain(TEXTO)
    expect(t).toContain('Largo plazo')
    alPost = () => Promise.resolve({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    t = await tocar(BOTON)
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls[0][0]).toBe('/tecnico/NVDA/resumen?moneda=usd')
    expect(texto(lecturaDeHoy())).toContain(TEXTO)
    expect(t).toContain('Largo plazo')
  })

  it('mientras escribe, la ficha se ve igual y el botón lo dice', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => new Promise(() => {})                 // no contesta nunca
    const t = await tocar(BOTON)
    expect(t).toContain('Mervall-E está escribiendo')
    expect(t).toContain('Largo plazo')
  })

  it('con el tope lleno lo dice con calma, sin «Probar de nuevo»', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => Promise.resolve({ estado: 'tope' })
    const t = await tocar(BOTON)
    expect(t).toContain('Mañana vuelve a estar')
    expect(buscarBoton(montado.contenedor, 'Probar de nuevo')).toBeFalsy()
    expect(t).toContain('Largo plazo')
  })

  it('si falla lo dice, deja probar de nuevo y la ficha no se rompe', async () => {
    await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
    alPost = () => Promise.reject(new Error('500'))
    let t = await tocar(BOTON)
    expect(t).toContain('no se pudo escribir el análisis')
    expect(t).toContain('Largo plazo')
    alPost = () => Promise.resolve({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
    t = await tocar('Probar de nuevo')
    expect(t).toContain(TEXTO)
  })

  it('si otro lo está escribiendo («generando»), vuelve a preguntar solo hasta que está', async () => {
    // Auditoría final E2 (31/10): el servidor ya no espera al otro pedido;
    // contesta «generando» al instante y la pantalla vuelve a preguntar.
    const { REINTENTO } = await import('./ResumenMervalle')
    const antes = { ...REINTENTO }
    Object.assign(REINTENTO, { ms: 0 })
    try {
      await dibujar({ estado: 'generando', fecha: '2026-10-21' })
      let n = 0
      alPost = () => Promise.resolve(++n < 3 ? { estado: 'generando', fecha: '2026-10-21' }
        : { estado: 'listo', texto: TEXTO, fecha: '2026-10-21' })
      await tocar(BOTON)
      for (let i = 0; i < 8; i++) await montado.redibujar(el())
      expect(api.post).toHaveBeenCalledTimes(3)
      expect(texto(lecturaDeHoy())).toContain(TEXTO)
      // Si nunca termina, después de unas vueltas lo dice y deja probar de nuevo.
      await montado.desmontar()
      api.post.mockClear()
      Object.assign(REINTENTO, { veces: 3 })
      await dibujar({ estado: 'no_hay', fecha: '2026-10-21' })
      alPost = () => Promise.resolve({ estado: 'generando', fecha: '2026-10-21' })
      await tocar(BOTON)
      for (let i = 0; i < 8; i++) await montado.redibujar(el())
      expect(api.post).toHaveBeenCalledTimes(3)
      expect(texto(montado.contenedor)).toContain('se está terminando de escribir')
      expect(buscarBoton(montado.contenedor, 'Probar de nuevo')).toBeTruthy()
    } finally {
      Object.assign(REINTENTO, antes)
    }
  })

  it('las preguntas para seguir abren el chat con la pregunta que escribe el servidor', async () => {
    await dibujar({ estado: 'listo', texto: TEXTO, fecha: '2026-10-21' },
      { fibonacci: { disponible: false, en_curso: { dir: 'bajada' } } })
    const esperado = { asset: 'NVDA', moneda: 'usd', local: '' }
    await tocar('¿Está en tendencia?')
    expect(voz.analizar).toHaveBeenLastCalledWith({ screen: 'tecnico.tendencia', params: esperado })
    await tocar('¿Tiene fuerza esta bajada?')
    expect(voz.analizar).toHaveBeenLastCalledWith({ screen: 'tecnico.fuerza', params: esperado })
    await tocar('¿Qué se mira de acá en adelante?')
    expect(voz.analizar).toHaveBeenLastCalledWith({ screen: 'tecnico.que_se_mira', params: esperado })
    await tocar('Preguntar otra cosa')
    expect(voz.setOpen).toHaveBeenCalledWith(true)
    expect(api.post).not.toHaveBeenCalled()
  })

  it('sin IA (o sin datos) no hay ni botón', async () => {
    const t = await dibujar(null)
    expect(t).not.toContain(BOTON)
    expect(t).toContain('Largo plazo')
  })
})
