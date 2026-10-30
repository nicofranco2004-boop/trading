// La imagen del gráfico técnico para compartir: qué lleva (specDelGrafico) y
// qué pinta (shareCard.pintarGrafico, con un canvas de mentira que anota cada
// texto y cada raya). El botón montado está en components/asset/CompartirGrafico.test.js.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { archivoDelGrafico, specDelGrafico } from './imagenGrafico'
import { renderShareCard } from './shareCard'

const dia = (i) => new Date(Date.UTC(2026, 0, 1) + i * 86400000).toISOString().slice(0, 10)
function velas(n, f, extra = () => ({})) {
  return Array.from({ length: n }, (_, i) => {
    const c = f(i)
    return { d: dia(i), o: c * 0.99, h: c * 1.02, l: c * 0.97, c, v: 1000 + i, s50: c * 1.01, s200: c * 1.03,
      bb_arriba: c * 1.08, bb_abajo: c * 0.92, rsi: 50, ...extra(i) }
  })
}
const fmt = (x) => `US$ ${x.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const COLORES = {
  precio: 'rgb(var(--ink-0))', media200: 'rgb(var(--rendi-accent))', media50: 'rgb(var(--cat-orange))',
  bandas: 'rgb(var(--cat-olive))', fibonacci: 'rgb(var(--cat-magenta) / 1)', elliott: 'rgb(var(--cat-indigo) / 1)',
  sube: 'rgb(var(--rendi-pos-fill))', baja: 'rgb(var(--rendi-neg-fill))', positivo: 'rgb(var(--rendi-pos))',
  negativo: 'rgb(var(--rendi-neg))', grilla: 'rgb(var(--chart-grid))', balance: 'rgb(var(--data-violet))', dividendo: 'rgb(var(--cat-teal))',
}
const base = (extra = {}) => ({
  activo: 'aapl', moneda: 'usd', puntos: velas(60, i => 100 + i), huecos: 8, lo: 90, hi: 170,
  ver: { vol: true, s200: true }, tipo: 'linea', precio: fmt, colores: COLORES, now: new Date(2026, 9, 29), ...extra,
})

describe('specDelGrafico: qué lleva la imagen', () => {
  it('el activo, el período que se ve, la temporalidad, la moneda y el último precio', () => {
    const s = specDelGrafico(base())
    expect(s.kind).toBe('grafico')
    expect(s.activo).toBe('AAPL')
    expect(s.subtitulo).toBe('Línea · del 01/01/26 al 01/03/26 · en dólares')
    expect(s.precio.texto).toBe('US$ 159,00')
    expect(s.cambio.texto).toBe('+59,0 % en el período')
    expect(s.date).toBe('Hecho con Rendi el 29 de octubre de 2026')
    expect(specDelGrafico(base({ tipo: 'velas', semanales: true, moneda: 'ars' })).subtitulo)
      .toBe('Velas semanales · del 01/01/26 al 01/03/26 · en pesos')
    expect(specDelGrafico(base({ tipo: 'velas' })).subtitulo).toMatch(/^Velas diarias/)
  })

  it('usa la escala de la pantalla (también la estirada a mano) y los lugares vacíos de la derecha', () => {
    const s = specDelGrafico(base({ lo: 50, hi: 250 }))
    const ult = s.grafico.etiquetas.find(e => e.principal)
    // 159 en una escala de 50 a 250: el 54,5 % desde arriba.
    expect(ult.y).toBeCloseTo((1 - (159 - 50) / 200) * 100, 6)
    // 60 velas + 8 huecos: la última va en el lugar 59 de 67, no contra el borde.
    expect(s.grafico.area[0].at(-1)[0]).toBeCloseTo((59 / 67) * 100, 6)
    // Sin escala (no debería pasar) arma una con los cierres.
    const sin = specDelGrafico(base({ lo: undefined, hi: undefined }))
    expect(sin.grafico.etiquetas[0].y).toBeGreaterThan(0)
    expect(sin.grafico.etiquetas[0].y).toBeLessThan(100)
  })

  it('las capas: sólo las prendidas, cada una con su referencia', () => {
    const nombres = (ver) => specDelGrafico(base({ ver })).leyenda.map(l => l.nombre)
    expect(nombres({ vol: true, s200: true })).toEqual(['Volumen', 'Promedio 200 días'])
    expect(nombres({ s50: true, bb: true })).toEqual(['Bandas de Bollinger', 'Promedio 50 días'])
    const s = specDelGrafico(base({ ver: { s200: false, s50: false, vol: false, rsi: false, fuerza: false } }))
    expect(s.grafico.lineas).toEqual([])
    expect(s.grafico.volumen).toEqual([])
    expect(s.rsi).toBe(null)
    // El RSI se ve salvo que se apague (como en la pantalla).
    expect(specDelGrafico(base()).rsi.ultimo.texto).toBe('50')
  })

  it('velas: una por punto, verde si cerró arriba de la apertura', () => {
    const s = specDelGrafico(base({ tipo: 'velas' }))
    expect(s.grafico.velas).toHaveLength(60)
    expect(s.grafico.area).toBe(null)
    expect(s.grafico.velas.every(v => v.sube)).toBe(true)
  })

  it('tus dibujos, cada uno en su color: línea, horizontal, canal, pincel, Fibonacci y Elliott', () => {
    const p = (k, precio) => ({ k, precio })
    const dibujos = [
      { id: 't', tipo: 'tendencia', a: p(5, 105), b: p(40, 140), color: 'ambar' },
      { id: 'h', tipo: 'horizontal', precio: 130, color: 'rosa' },
      { id: 'c', tipo: 'canal', a: p(10, 100), b: p(50, 140), ancho: 12, color: 'verde' },
      { id: 'p', tipo: 'pincel', puntos: [p(1, 100), p(2, 104), p(3, 101)] },
      { id: 'f', tipo: 'fibonacci', a: p(10, 110), b: p(50, 150), color: 'violeta' },
      { id: 'e', tipo: 'elliott', forma: 'impulso', puntos: [p(5, 100), p(10, 120), p(15, 110), p(25, 150)], color: 'rojo' },
    ]
    const s = specDelGrafico(base({ dibujos }))
    const colores = new Set(s.grafico.trazos.map(t => t.color))
    for (const tok of ['data-amber', 'cat-pink', 'rendi-pos', 'data-cyan', 'data-violet', 'rendi-neg']) {
      expect(colores.has(`rgb(var(--${tok}))`)).toBe(true)
    }
    // La horizontal, con su precio en la columna, en su color.
    expect(s.grafico.etiquetas).toContainEqual(expect.objectContaining({ texto: '130,00', color: 'rgb(var(--cat-pink))' }))
    // La franja del canal.
    expect(s.grafico.poligonos.some(x => x.color === 'rgb(var(--rendi-pos))')).toBe(true)
    // Los niveles del Fibonacci con su precio, y los números de las ondas.
    const textos = s.grafico.rotulos.map(r => r.texto)
    expect(textos).toEqual(expect.arrayContaining(['Pico · US$ 150,00', '50 % · US$ 130,00', 'Arranque · US$ 110,00']))
    expect(textos).toEqual(expect.arrayContaining(['1', '2', '3']))
    expect(s.leyenda.map(l => l.nombre)).toContain('Tus dibujos')
  })

  it('con 60 dibujos van los 60; sin dibujos no dice «Tus dibujos»', () => {
    const muchos = Array.from({ length: 60 }, (_, k) => ({ id: `h${k}`, tipo: 'horizontal', precio: 95 + k }))
    const s = specDelGrafico(base({ dibujos: muchos }))
    expect(s.grafico.trazos.length).toBe(60)
    expect(specDelGrafico(base()).leyenda.map(l => l.nombre)).not.toContain('Tus dibujos')
  })

  it('una cripto de centavos: los precios del costado no dicen todos «0,00»', () => {
    const s = specDelGrafico(base({ puntos: velas(60, i => 0.0004 + i * 0.000002), lo: 0.00038, hi: 0.00054,
      precio: (x) => `US$ ${x.toLocaleString('es-AR', { maximumSignificantDigits: 3 })}` }))
    const textos = s.grafico.eje.map(t => t.texto)
    expect(textos.length).toBeGreaterThan(2)
    expect(new Set(textos).size).toBe(textos.length)
    expect(textos.every(t => t !== '0' && t !== '0,00')).toBe(true)
  })

  it('el Fibonacci y las ondas automáticas, sólo si están prendidos', () => {
    const fibonacci = { disponible: true, dir: 'suba', desde: { fecha: dia(10), precio: 110 }, hasta: { fecha: dia(50), precio: 150 },
      niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 150 - 40 * n })), entre: [0.236, 0.382],
      ruptura: { fecha: dia(52), cierre: 151 } }
    const apagado = specDelGrafico(base({ fibonacci }))
    expect(apagado.leyenda.map(l => l.nombre)).not.toContain('Fibonacci automático')
    const s = specDelGrafico(base({ fibonacci, ver: { fib: true } }))
    expect(s.leyenda.map(l => l.nombre)).toContain('Fibonacci automático')
    expect(s.grafico.trazos.filter(t => t.color === COLORES.fibonacci).length).toBe(8)   // 7 niveles + el tramo
  })

  it('balances y dividendos sólo prendidos, y los pegados en una marca', () => {
    const eventos = [{ tipo: 'balance', fecha: dia(10) }, { tipo: 'dividendo', fecha: dia(11) }, { tipo: 'dividendo', fecha: dia(40) }]
    expect(specDelGrafico(base({ eventos })).marcas).toEqual([])
    const m = specDelGrafico(base({ eventos, ver: { eventos: true } })).marcas
    expect(m.map(x => [x.letra, x.cuantos])).toEqual([['B·D', 2], ['D', 1]])
  })

  it('sin precios no hay imagen', () => {
    expect(specDelGrafico(base({ puntos: [] }))).toBe(null)
  })

  it('no tiene por dónde recibir nada de tu cartera', () => {
    // Aunque le pasaran tu precio o tus compras, no los mira: no hay
    // parámetro para eso.
    const s = specDelGrafico({ ...base(), promedio: 123.45, marcas: [{ fecha: dia(5), tipo: 'compra' }], pnlPct: 0.5 })
    const json = JSON.stringify(s)
    expect(json).not.toContain('Tu precio')
    expect(json).not.toContain('123,45')
    expect(json).not.toMatch(/"compra"|Compraste|marcas":\[\{/)
  })

  it('el nombre del archivo', () => {
    expect(archivoDelGrafico('GGAL.BA', new Date(2026, 9, 9))).toBe('ggal-ba-grafico-2026-10-09.png')
  })
})

// ── El canvas de mentira ──────────────────────────────────────────────────
// Anota cada texto (con dónde y con qué letra) y mide como una letra de ancho
// medio (0,55 del tamaño): alcanza para ver si algo se sale de la imagen.
function canvasDeMentira() {
  const textos = []
  const rayas = []
  let font = '10px sans'
  let align = 'left'
  const tam = () => Number((font.match(/(\d+)px/) || [])[1] || 10)
  const ctx = new Proxy({
    get font() { return font }, set font(f) { font = f },
    get textAlign() { return align }, set textAlign(a) { align = a },
    measureText: (t) => ({ width: String(t).length * tam() * 0.55 }),
    fillText: (t, x, y) => {
      const w = String(t).length * tam() * 0.55
      const izq = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x
      textos.push({ t: String(t), x0: izq, x1: izq + w, y, font })
    },
    moveTo: (x, y) => rayas.push([x, y]), lineTo: (x, y) => rayas.push([x, y]),
    createLinearGradient: () => ({ addColorStop() {} }), createRadialGradient: () => ({ addColorStop() {} }),
  }, { get: (o, k) => (k in o ? o[k] : () => {}), set: (o, k, v) => { o[k] = v; return true } })
  return { canvas: { width: 0, height: 0, getContext: () => ctx }, textos, rayas }
}

describe('pintarGrafico: lo que se ve en la imagen', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  async function pintar(spec) {
    const falso = canvasDeMentira()
    vi.stubGlobal('document', { createElement: () => falso.canvas })
    await renderShareCard(spec)
    return falso
  }

  it('el activo, el precio, el período, las fechas, el aviso de que no es una recomendación y la marca', async () => {
    const { textos } = await pintar(specDelGrafico(base({ fechaDatos: dia(59) })))
    const t = textos.map(x => x.t)
    expect(t).toEqual(expect.arrayContaining(['AAPL', 'US$ 159,00', 'Rendi', 'rendi.finance',
      'Línea · del 01/01/26 al 01/03/26 · en dólares', '+59,0 % en el período', 'Datos al cierre del 01/03/26.',
      'Muestra cómo se movió el precio: no es una recomendación para comprar ni vender.']))
    expect(t).toContain('159,00')                        // el último precio en la columna
    expect(t.some(x => /^(ene|feb|mar)$/.test(x))).toBe(true)   // las fechas de abajo
  })

  it('nada se sale de la imagen, ni con todo prendido y 60 dibujos en un celular angosto de precios largos', async () => {
    const muchos = Array.from({ length: 60 }, (_, k) => ({ id: `h${k}`, tipo: 'horizontal', precio: 1_000_000 + k * 9000, color: 'ambar' }))
    const spec = specDelGrafico(base({
      activo: 'BRK.A-SUPERLARGO', puntos: velas(300, i => 1_000_000 + i * 2000, i => ({ adx: 20 + (i % 10), squeeze: Math.sin(i), squeeze_color: 'verde_fuerte' })),
      lo: 950_000, hi: 1_700_000, dibujos: muchos, tipo: 'velas',
      ver: { vol: true, s200: true, s50: true, bb: true, rsi: true, fuerza: true, eventos: true },
      squeeze: { verde_fuerte: ['rgb(var(--rendi-pos-fill))', 1] },
      precio: (x) => `US$ ${Math.round(x).toLocaleString('es-AR')}`,
    }))
    const { textos } = await pintar(spec)
    for (const x of textos) {
      expect(x.x0, x.t).toBeGreaterThanOrEqual(0)
      expect(x.x1, x.t).toBeLessThanOrEqual(1080)
      expect(x.y, x.t).toBeLessThanOrEqual(1350)
    }
    expect(textos.map(x => x.t)).toEqual(expect.arrayContaining(['RSI', 'Fuerza de la tendencia (ADX)']))
    // Las etiquetas de la columna no se pisan: con 60 horizontales juntas, van
    // las que entran (el último precio siempre).
    const columna = textos.filter(x => x.x0 > 900 && x.font.startsWith('600 22px'))
    expect(columna.length).toBeGreaterThan(3)
    expect(columna.length).toBeLessThan(40)
    expect(columna.map(x => x.t)).toContain('1.598.000')
    const ys = columna.map(x => x.y).sort((a, b) => a - b)
    for (let k = 1; k < ys.length; k++) expect(ys[k] - ys[k - 1]).toBeGreaterThanOrEqual(34)
  })

  it('un activo en pesos de nueve cifras: la etiqueta del precio no se sale por la derecha', async () => {
    const pesos = (x) => `$ ${x.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    const spec = specDelGrafico(base({ moneda: 'ars', puntos: velas(60, i => 123_456_789 + i * 1_000_000), lo: 120_000_000, hi: 190_000_000, precio: pesos,
      dibujos: [{ id: 'h', tipo: 'horizontal', precio: 150_123_456.78 }] }))
    const { textos } = await pintar(spec)
    const columna = textos.filter(x => x.x0 > 880)
    expect(columna.length).toBeGreaterThan(2)
    for (const x of columna) expect(x.x1, x.t).toBeLessThanOrEqual(1080 - 8)
  })

  it('las letras de la imagen son de 18 px para arriba (se mira achicada en el celular), también los 70 y 30 del RSI', async () => {
    const { textos } = await pintar(specDelGrafico(base({ ver: { vol: true, s200: true, rsi: true, fuerza: true },
      puntos: velas(60, i => 100 + i, i => ({ adx: 30, squeeze: 1, squeeze_color: 'verde_fuerte' })) })))
    const t = textos.map(x => x.t)
    expect(t).toEqual(expect.arrayContaining(['70', '30', '50', '23']))
    for (const x of textos) expect(Number(x.font.match(/(\d+)px/)[1]), x.t).toBeGreaterThanOrEqual(18)
  })
})
