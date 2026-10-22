import { describe, it, expect } from 'vitest'
import { tarjetas, veredictoRsi, textoCruceRsi, lineaPromedio, marcas, indiceDeFecha, recortar, tendenciasDistintas } from './tecnico'

const L = {
  ruedas: 760, fecha: '2026-10-21', precio: 228.97,
  media50: 241.49, dist_media50: -5.18, media200: 250.08, dist_media200: -8.44,
  pendiente_media200: -1.2, rsi: 37.8, maximo_12m: 274.63, dist_maximo_12m: -16.63,
  anio_completo: true,
}

describe('tarjetas', () => {
  it('dice bajista con la media que baja, en palabras', () => {
    const t = tarjetas(L)
    const fondo = t.find(x => x.id === 'fondo')
    expect(fondo.veredicto).toBe('Bajista')
    expect(fondo.tono).toBe('neg')
    expect(fondo.texto).toBe('Está 8,4% abajo de su media de 200 días, y esa media viene bajando.')
    expect(t.find(x => x.id === 'corto').veredicto).toBe('Débil')
    expect(t.find(x => x.id === 'rsi').veredicto).toBe('Pesan más las bajas')
    expect(t.find(x => x.id === 'rsi').texto).toContain('38 de 100. Mide si en las últimas 14 ruedas pesaron más las subas o las bajas')
    expect(t.find(x => x.id === 'maximo').veredicto).toBe('16,6% abajo')
  })

  it('con pocas ruedas dice que faltan datos en vez de inventar la media', () => {
    const t = tarjetas({ ruedas: 120, media200: null, dist_media200: null, media50: 10, dist_media50: 2, rsi: 50, dist_maximo_12m: -3, anio_completo: false })
    const fondo = t.find(x => x.id === 'fondo')
    expect(fondo.veredicto).toBe('Faltan datos')
    expect(fondo.texto).toContain('hay 120')
    expect(t.find(x => x.id === 'maximo').titulo).toBe('Máximo del período')
  })

  it('sin lectura no hay tarjetas', () => {
    expect(tarjetas(null)).toEqual([])
    expect(tarjetas({ ruedas: 0 })).toEqual([])
  })
})

describe('veredictoRsi', () => {
  it('dice quién viene ganando, con los cortes de 30 y 70', () => {
    expect(veredictoRsi(25)).toBe('Bajó muy fuerte y rápido')
    expect(veredictoRsi(30)).toBe('Pesan más las bajas')
    expect(veredictoRsi(50)).toBe('Parejo')
    expect(veredictoRsi(70)).toBe('Pesan más las subas')
    expect(veredictoRsi(71)).toBe('Subió muy fuerte y rápido')
  })

  it('cuenta cuándo volvió a pasar 30 para arriba o bajó de 70', () => {
    expect(textoCruceRsi({ tipo: 'salio_de_abajo', hace: 3 }))
      .toBe('Hace 3 ruedas volvió a pasar 30 para arriba: muchos lo leen como que vuelve a tomar fuerza.')
    expect(textoCruceRsi({ tipo: 'salio_de_arriba', hace: 0 }))
      .toBe('En la última rueda bajó de 70: muchos lo leen como que pierde fuerza.')
    expect(textoCruceRsi(null)).toBeNull()
  })
})

describe('lineaPromedio', () => {
  const pts = [{ c: 100 }, { c: 120 }]
  it('la distancia al precio es exactamente tu resultado', () => {
    // Ganás 20 %: tu precio en este gráfico es 120 / 1,2 = 100.
    expect(lineaPromedio(pts, 0.2)).toBeCloseTo(100, 10)
    expect(lineaPromedio(pts, -0.25)).toBeCloseTo(160, 10)
  })
  it('sin resultado (no tenés el activo) no hay línea', () => {
    expect(lineaPromedio(pts, null)).toBeNull()
    expect(lineaPromedio([], 0.1)).toBeNull()
    expect(lineaPromedio(pts, -1)).toBeNull()
  })
})

describe('marcas', () => {
  it('compras de los lotes y de las cerradas, ventas de las cerradas, sin cobros ni conversiones', () => {
    const lotes = [{ entry_date: '2026-03-02', quantity: 5 }, { is_cash: true, entry_date: '2026-01-01' }]
    const ops = [
      { op_type: 'Venta', entry_date: '2025-11-14', date: '2026-04-28', pnl_usd: -3 },
      { op_type: 'Dividendo', date: '2026-05-10', pnl_usd: 12 },
      { op_type: 'Conversión ARS→USD', date: '2026-06-01', pnl_usd: 0 },
    ]
    expect(marcas(lotes, ops)).toEqual([
      { fecha: '2025-11-14', tipo: 'compra' },
      { fecha: '2026-03-02', tipo: 'compra' },
      { fecha: '2026-04-28', tipo: 'venta' },
    ])
  })
})

describe('indiceDeFecha', () => {
  const pts = [{ d: '2026-10-16' }, { d: '2026-10-19' }, { d: '2026-10-20' }]
  it('un fin de semana cae en el viernes', () => {
    expect(indiceDeFecha(pts, '2026-10-18')).toBe(0)
    expect(indiceDeFecha(pts, '2026-10-20')).toBe(2)
    expect(indiceDeFecha(pts, '2026-10-01')).toBeNull()
  })
})

describe('recortar y tendenciasDistintas', () => {
  it('recorta las últimas ruedas', () => {
    expect(recortar([1, 2, 3, 4], 2)).toEqual([3, 4])
    expect(recortar([1, 2], 10)).toEqual([1, 2])
  })
  it('avisa cuando en pesos parece alcista y en dólares no', () => {
    expect(tendenciasDistintas({ dist_media200: -8 }, { dist_media200: 24 })).toBe(true)
    expect(tendenciasDistintas({ dist_media200: 3 }, { dist_media200: 24 })).toBe(false)
    expect(tendenciasDistintas(null, { dist_media200: 24 })).toBe(false)
  })
})

describe('velas', () => {
  it('completa una vela rota con lo que hay, sin inventar mecha', async () => {
    const { velaCompleta } = await import('./tecnico')
    expect(velaCompleta({ o: 10, h: 12, l: 9, c: 11 }, 9.5)).toEqual({ o: 10, h: 12, l: 9, c: 11 })
    // Sin apertura ni máximo/mínimo: abre en el cierre anterior y la mecha es el cuerpo.
    expect(velaCompleta({ o: null, h: null, l: null, c: 11 }, 10)).toEqual({ o: 10, h: 11, l: 10, c: 11 })
    // Un máximo menor que el cierre (dato roto) se corrige al cierre.
    expect(velaCompleta({ o: 10, h: 10.5, l: 9, c: 11 }, null).h).toBe(11)
  })

  it('agrupa por semana: apertura del lunes, máximo y mínimo de la semana, cierre del viernes', async () => {
    const { velasSemanales } = await import('./tecnico')
    const dias = [
      { d: '2026-10-12', o: 10, h: 11, l: 9.5, c: 10.5, s200: 1, rsi: 40 },   // lunes
      { d: '2026-10-14', o: 10.5, h: 13, l: 10, c: 12, s200: 2, rsi: 50 },
      { d: '2026-10-16', o: 12, h: 12.5, l: 8, c: 9, s200: 3, rsi: 45 },       // viernes
      { d: '2026-10-19', o: 9, h: 10, l: 8.5, c: 9.8, s200: 4, rsi: 47 },      // otra semana
    ]
    const s = velasSemanales(dias)
    expect(s).toHaveLength(2)
    expect(s[0]).toMatchObject({ d: '2026-10-12', o: 10, h: 13, l: 8, c: 9, s200: 3, rsi: 45, semana: true })
    expect(s[1]).toMatchObject({ d: '2026-10-19', o: 9, c: 9.8 })
  })
})

describe('zoom y arrastre', () => {
  it('la ruedita acerca dejando quieto el día bajo el mouse', async () => {
    const { zoomVentana } = await import('./tecnico')
    // Se ven las ruedas 252..503 y el mouse está en el medio (rueda 378).
    const v = zoomVentana({ n: 252, fin: 504, total: 504 }, 0.5, 0.5)
    expect(v).toEqual({ n: 126, fin: 441 })
    expect(v.fin - v.n + 0.5 * v.n).toBe(378)
  })
  it('no se pasa de los bordes ni baja de 20 ruedas', async () => {
    const { zoomVentana } = await import('./tecnico')
    expect(zoomVentana({ n: 500, fin: 504, total: 504 }, 1.5, 0.5)).toEqual({ n: 504, fin: 504 })
    expect(zoomVentana({ n: 504, fin: 504, total: 504 }, 1.5, 0.5)).toBeNull()
    expect(zoomVentana({ n: 21, fin: 504, total: 504 }, 0.1, 1)).toEqual({ n: 20, fin: 504 })
  })
  it('arrastrar a la derecha va para atrás en el tiempo, sin salirse', async () => {
    const { moverVentana } = await import('./tecnico')
    expect(moverVentana({ n: 100, fin: 504, total: 504 }, 0.25)).toEqual({ n: 100, fin: 479 })
    expect(moverVentana({ n: 100, fin: 504, total: 504 }, -0.25)).toBeNull()
    expect(moverVentana({ n: 100, fin: 110, total: 504 }, 0.5)).toEqual({ n: 100, fin: 100 })
  })
})
