// La lectura técnica montada de verdad (testing/navegadorMinimo.js), con los
// pedidos al servidor simulados en la frontera (utils/api). Lo que se prueba es
// el ARMADO que las cuentas (utils/tecnico.test.js) no ven:
//   · con velas: las tarjetas, la leyenda y "contra tu precio" con el resultado
//     de la ficha;
//   · en pesos, el aviso de que el dólar cambia la lectura;
//   · sin velas (o si el pedido falla): el gráfico de 30 días de siempre.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscar, buscarBoton, clic, enActo } from '../../testing/navegadorMinimo'

function puntos(n, f) {
  return Array.from({ length: n }, (_, i) => ({
    d: new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10),
    c: f(i), s50: f(i) * 1.02, s200: f(i) * 1.05, rsi: 40,
  }))
}
const USD = {
  disponible: true, moneda: 'usd', ticker: 'AAPL', convertida: null,
  puntos: puntos(504, i => 250 - i * 0.03),
  lectura: { ruedas: 760, fecha: '2026-10-21', precio: 235, media50: 241, dist_media50: -2.5,
    media200: 250, dist_media200: -6, pendiente_media200: -1, rsi: 38, dist_maximo_12m: -14, anio_completo: true },
}
const ARS = {
  ...USD, moneda: 'ars', ticker: 'AAPL.BA',
  lectura: { ...USD.lectura, dist_media200: 24, pendiente_media200: 3 },
}

let respuestas
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      const r = clave ? respuestas[clave] : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r)
    }),
  },
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

async function dibujar(props) {
  const el = () => h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', ...props })
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('LecturaTecnica', () => {
  it('con velas: tarjetas en castellano, leyenda y contra tu precio', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: -0.081, lotes: [{ entry_date: '2025-03-01', quantity: 5 }] })
    expect(t).toContain('Largo plazo')
    expect(t).toContain('Bajista')
    expect(t).toContain('Promedio 200 días')
    expect(t).toContain('Tu precio promedio')
    expect(t).toContain('Contra lo que pagaste')
    expect(t).toContain('Perdés 8,1%')
    expect(t).toContain('no es una recomendación')
    expect(t).not.toContain('En pesos la tendencia es otra')
  })

  it('en pesos avisa que el dólar cambia la lectura', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pesos'))
    // Pesos se piden recién ahora: que vuelva el pedido.
    for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    const t = texto(montado.contenedor)
    expect(t).toContain('En pesos la tendencia es otra que en dólares')
    expect(t).toContain('Alcista')
  })

  it('sin velas todavía: el gráfico de 30 días de siempre', async () => {
    respuestas = { '/tecnico/': { disponible: false }, '/prices/history': { points: [] } }
    const t = await dibujar({})
    expect(t).toContain('últimos 30 días')
    expect(t).not.toContain('Análisis técnico')
  })

  it('si el pedido falla lo dice y deja reintentar (no muestra otro gráfico)', async () => {
    respuestas = { '/tecnico/': new Error('caído'), '/prices/history': { points: [] } }
    const t = await dibujar({})
    expect(t).toContain('No se pudo cargar el gráfico')
    expect(t).not.toContain('últimos 30 días')
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Reintentar'))
    for (let i = 0; i < 3; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA' }))
    expect(texto(montado.contenedor)).toContain('Largo plazo')
  })

  it('la línea de tu precio usa el dólar de compra; sin ese dato no se dibuja y lo dice', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    let t = await dibujar({ pnlPctUsd: 0.4, pnlPctLinea: 0.1 })
    expect(t).toContain('Tu precio promedio')
    expect(t).toContain('Ganás 40,0%')            // la tarjeta: el mismo resultado de arriba
    await montado.desmontar(); montado = null
    t = await dibujar({ pnlPctUsd: 0.4, pnlPctLinea: null, lineaSinTc: true })
    expect(t).not.toContain('Tu precio promedio')
    expect(t).toContain('le falta el dólar de ese día')
  })

  it('compras y ventas en la leyenda sólo si hay alguna en el rango', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    let t = await dibujar({ pnlPctUsd: 0.1 })
    expect(t).not.toContain('Tus compras y ventas')
    await montado.desmontar(); montado = null
    const ultimo = USD.puntos[USD.puntos.length - 10].d
    t = await dibujar({ pnlPctUsd: 0.1, lotes: [{ entry_date: ultimo, quantity: 1 }] })
    expect(t).toContain('Tus compras y ventas')
  })

  it('pide pesos recién al tocarlos, y una acción argentina pide su precio local', async () => {
    const { api } = await import('../../utils/api')
    api.get.mockClear()
    respuestas = { '/tecnico/GGAL?moneda=usd&local=1': USD, '/tecnico/GGAL?moneda=ars&local=1': ARS }
    const el = () => h(LecturaTecnica, { asset: 'GGAL', accionLocal: true })
    montado = await montar(el())
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    const todos = () => api.get.mock.calls.map(c => c[0]).filter(r => r.startsWith('/tecnico'))
    const pedidos = () => todos().filter(r => !r.includes('/eventos'))
    expect(pedidos()).toEqual(['/tecnico/GGAL?moneda=usd&local=1'])
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pesos'))
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    expect(pedidos()).toEqual(['/tecnico/GGAL?moneda=usd&local=1', '/tecnico/GGAL?moneda=ars&local=1'])
    // Los balances y dividendos, también por moneda y con la acción local.
    expect(todos().filter(r => r.includes('/eventos'))).toEqual(
      ['/tecnico/GGAL/eventos?moneda=usd&local=1', '/tecnico/GGAL/eventos?moneda=ars&local=1'])
  })

  it('en pesos, tu precio sale de lo que pagaste en pesos (con comisiones)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    // Último cierre en pesos: 250 − 503 × 0,03 = 234,91. 10 unidades valen
    // 2.349,10; pagaste 2.000 + 100 de comisión → +11,9 %.
    await dibujar({ pnlPctUsd: 0.5, costoPesos: { invertido: 2100, cantidad: 10 } })
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pesos'))
    for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.5, costoPesos: { invertido: 2100, cantidad: 10 } }))
    expect(texto(montado.contenedor)).toContain('Ganás 11,9%')
  })

  it('con el botón Velas dibuja velas diarias, y semanales sólo si se eligen', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Velas'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(texto(montado.contenedor)).toContain('Velas: subió · bajó')
    expect(texto(montado.contenedor)).not.toContain('Cada vela es una semana')
    // En 2 años siguen siendo diarias; las semanales se eligen.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '2A'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(texto(montado.contenedor)).toContain('Cada vela es un día')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Semanales'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(texto(montado.contenedor)).toContain('Cada vela es una semana')
  })

  it('Agrandar pone el gráfico a pantalla completa; Achicar y Esc lo devuelven', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    const otra = () => montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    const seccion = () => buscar(montado.contenedor, 'section')
    expect(seccion().getAttribute('role')).toBeNull()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agrandar'))
    await otra()
    expect(seccion().getAttribute('role')).toBe('dialog')
    expect(seccion().getAttribute('class')).toContain('fixed')
    expect(document.body.style.overflow).toBe('hidden')   // la página de atrás no se mueve
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Achicar'))
    await otra()
    expect(seccion().getAttribute('role')).toBeNull()
    expect(document.body.style.overflow).not.toBe('hidden')
    // Esc también achica.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agrandar'))
    await otra()
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) })
    await otra()
    expect(seccion().getAttribute('role')).toBeNull()
  })

  it('el volumen: barras abajo del precio y un botón para apagarlas; sin datos, no aparece', async () => {
    const conVolumen = { ...USD, puntos: USD.puntos.map((p, i) => ({ ...p, v: 1000 + i })) }
    respuestas = { '/tecnico/AAPL?moneda=usd': conVolumen, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: 0.1 })
    expect(t).toContain('Volumen')
    const barras = () => {
      let n = 0
      const pila = [montado.contenedor]
      while (pila.length) {
        const x = pila.shift()
        if (x.nodeName === 'RECT' && x.getAttribute?.('fill-opacity') === '0.28') n++
        pila.push(...(x.childNodes || []))
      }
      return n
    }
    expect(barras()).toBeGreaterThan(200)          // un año de ruedas, una barra por día
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Volumen'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(barras()).toBe(0)
  })

  it('sin volumen en los datos no hay botón de volumen', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    expect(await dibujar({ pnlPctUsd: 0.1 })).not.toContain('Volumen')
  })

  it('sin tenencia no dibuja tu precio', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: null })
    expect(t).not.toContain('Contra lo que pagaste')
    expect(t).not.toContain('Tu precio promedio')
  })
})
