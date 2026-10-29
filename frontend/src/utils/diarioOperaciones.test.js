import { describe, it, expect } from 'vitest'
import {
  esDelDiario, diasTenida, rendimientoPorAnio, textoTiempo, pedidosDeTendencia,
  resumenDiario, fraseDeTusNumeros, tesisDeLaOperacion, tesisVigente, DIAS_MIN_POR_ANIO,
} from './diarioOperaciones'
import { setBrokersRegistry } from './valuation'
import { computeTradeStats } from './tradeStats'

const venta = (id, extra = {}) => ({
  id, asset: 'NVDA', broker: 'Schwab', op_type: 'Venta', currency: 'USD',
  entry_date: '2025-01-01', date: '2025-07-01', pnl_usd: 100, pnl_pct: 10, ...extra,
})

describe('qué entra en el diario', () => {
  it('ventas sí; compras, cobros, conversiones y la amortización de Balanz no', () => {
    expect(esDelDiario(venta(1))).toBe(true)
    expect(esDelDiario(venta(2, { op_type: 'Compra' }))).toBe(false)
    for (const t of ['Dividendo', 'Cupón', 'Amortización', 'Interés', 'Renta']) {
      expect(esDelDiario(venta(3, { op_type: t })), t).toBe(false)
    }
    expect(esDelDiario(venta(4, { op_type: 'Conversión ARS→USD' }))).toBe(false)
    expect(esDelDiario(venta(5, { amortizacion_importada: true }))).toBe(false)
    expect(esDelDiario(venta(6, { pnl_usd: null }))).toBe(false)
  })
  it('un cupón con resultado cuenta en el win rate de siempre, pero no en el diario', () => {
    const cupon = venta(7, { op_type: 'Cupón', entry_date: null })
    expect(computeTradeStats([cupon]).trades).toBe(1)   // la decisión pendiente de tradeStats
    expect(resumenDiario([cupon]).cerradas).toBe(0)
  })
})

describe('tiempo y por año', () => {
  it('días entre compra y venta (espejo de behavioral._holding_days)', () => {
    expect(diasTenida(venta(1))).toBe(181)
    expect(diasTenida(venta(1, { entry_date: null }))).toBeNull()
    expect(diasTenida(venta(1, { entry_date: '2025-08-01' }))).toBeNull()   // venta antes que compra
    expect(diasTenida(venta(1, { entry_date: '2025-07-01T10:00:00' }))).toBe(0)
  })
  it('anualiza el MISMO % de la columna P&L % con interés compuesto', () => {
    const op = venta(1, { entry_date: '2024-01-01', date: '2026-01-01', pnl_pct: 21 })   // 2 años, +21 %
    expect(rendimientoPorAnio(op)).toBeCloseTo(Math.pow(1.21, 365 / 731) - 1, 10)
    expect(rendimientoPorAnio(op)).toBeCloseTo(0.1, 2)
  })
  it('con menos de 3 meses no se anualiza (inflaría)', () => {
    const corto = venta(1, { entry_date: '2025-06-01', date: '2025-07-01', pnl_pct: 5 })
    expect(diasTenida(corto)).toBeLessThan(DIAS_MIN_POR_ANIO)
    expect(rendimientoPorAnio(corto)).toBeNull()
    const justo = venta(1, { entry_date: '2025-04-02', date: '2025-07-01', pnl_pct: 5 })
    expect(diasTenida(justo)).toBe(90)
    expect(rendimientoPorAnio(justo)).not.toBeNull()
  })
  it('perder todo es −100 % por año, no un número imaginario', () => {
    expect(rendimientoPorAnio(venta(1, { pnl_pct: -100 }))).toBe(-1)
  })
  it('textos de tiempo', () => {
    expect(textoTiempo(1)).toBe('1 día')
    expect(textoTiempo(12)).toBe('12 días')
    expect(textoTiempo(164)).toBe('5,4 meses')
    expect(textoTiempo(30.44 * 1.02)).toBe('1,0 mes')
    expect(textoTiempo(900)).toBe('2,5 años')
    expect(textoTiempo(null)).toBe('—')
  })
})

describe('lo que se le pide al servidor', () => {
  it('una fila por venta, con la fecha de SU compra y la marca de acción argentina', () => {
    setBrokersRegistry([{ name: 'IOL', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }])
    const ops = [
      venta(1),
      venta(2, { asset: 'GGAL', broker: 'IOL', currency: 'ARS', entry_date: '2025-03-04T00:00:00' }),
      venta(3, { asset: 'AAPL', broker: 'IOL', currency: 'ARS' }),          // CEDEAR: no es local
      venta(4, { op_type: 'Dividendo' }),
      venta(5, { entry_date: null }),
    ]
    expect(pedidosDeTendencia(ops)).toEqual([
      { id: '1', asset: 'NVDA', local: false, fecha: '2025-01-01' },
      { id: '2', asset: 'GGAL', local: true, fecha: '2025-03-04' },
      { id: '3', asset: 'AAPL', local: false, fecha: '2025-01-01' },
    ])
  })
})

describe('tarjetas y frase', () => {
  const ops = [
    venta(1, { pnl_usd: 50, entry_date: '2024-01-01', date: '2024-12-31', pnl_pct: 30 }),   // 365 d
    venta(2, { pnl_usd: 20, entry_date: '2024-01-01', date: '2024-07-01', pnl_pct: 10 }),   // 182 d
    venta(3, { pnl_usd: -10, entry_date: '2024-05-01', date: '2024-06-01', pnl_pct: -5 }),  // 31 d
    venta(4, { pnl_usd: -30, entry_date: '2024-05-01', date: '2024-07-01', pnl_pct: -12 }), // 61 d
    venta(5, { pnl_usd: -5, entry_date: '2024-05-01', date: '2024-07-31', pnl_pct: -2 }),   // 91 d
    venta(6, { op_type: 'Dividendo', pnl_usd: 3 }),
  ]
  const tend = {
    1: { tendencia: 'alcista' }, 2: { tendencia: 'bajista' },
    3: { tendencia: 'bajista' }, 4: { tendencia: 'bajista' }, 5: { tendencia: null, motivo: 'sin_precio' },
  }
  it('los números', () => {
    const r = resumenDiario(ops, tend)
    expect([r.cerradas, r.ganadas, r.perdidas]).toEqual([5, 2, 3])
    expect(r.diasGanadoras).toBeCloseTo((365 + 182) / 2)
    expect(r.diasPerdedoras).toBeCloseTo((31 + 61 + 91) / 3)
    expect(r.nPorAnio).toBe(5)   // ponderado por plata y tiempo, entran todas (D7)
    expect([r.ganadorasConTendencia, r.ganadorasAFavor]).toEqual([2, 1])
    expect([r.perdedorasConTendencia, r.perdedorasEnContra]).toEqual([2, 2])
  })
  it('la frase: descriptiva, sin consejos, y dice de cuántas no hay precios', () => {
    const f = fraseDeTusNumeros(resumenDiario(ops, tend))
    expect(f).toEqual([
      'De las 3 que perdiste hay precios del día de compra de 2: 2 las compraste cuando el papel estaba debajo de su promedio de 200 días.',
      'Las ganadoras las tuviste 4,5 veces más tiempo que las perdedoras.',
    ])
    expect(f.join(' ')).not.toMatch(/deber[ií]as|conviene|recomend|vendé|comprá|mantené/i)
  })
  it('una sola perdida, y tiempos parecidos', () => {
    const dos = [
      venta(1, { pnl_usd: 5, entry_date: '2024-01-01', date: '2024-04-01' }),
      venta(2, { pnl_usd: 5, entry_date: '2024-01-01', date: '2024-04-10' }),
      venta(3, { pnl_usd: -5, entry_date: '2024-01-01', date: '2024-04-05' }),
    ]
    expect(fraseDeTusNumeros(resumenDiario(dos, { 3: { tendencia: 'alcista' } }))).toEqual([
      'La que perdiste la compraste cuando el papel estaba arriba de su promedio de 200 días.',
      'A las ganadoras y a las perdedoras las tuviste un tiempo parecido.',
    ])
  })
  it('con menos de 3 cerradas no hay frase', () => {
    expect(fraseDeTusNumeros(resumenDiario(ops.slice(0, 2), tend))).toEqual([])
  })
})

describe('la tesis de cada venta', () => {
  const tesis = [
    { id: 1, asset: 'NVDA', escrita_el: '2025-01-05', texto: 'v1' },
    { id: 2, asset: 'NVDA', escrita_el: '2025-09-01', texto: 'v2' },
    { id: 3, asset: 'GGAL', escrita_el: '2025-01-01', texto: 'g' },
  ]
  it('la última escrita hasta el día de la venta', () => {
    expect(tesisDeLaOperacion(tesis, venta(1, { date: '2025-07-01' })).texto).toBe('v1')
    expect(tesisDeLaOperacion(tesis, venta(1, { date: '2025-09-01' })).texto).toBe('v2')
    expect(tesisDeLaOperacion(tesis, venta(1, { date: '2025-01-04' }))).toBeNull()   // la escribió después
    expect(tesisVigente(tesis, 'NVDA').texto).toBe('v2')
    expect(tesisVigente(tesis, 'AAPL')).toBeNull()
  })
})


// D7 (auditoría D, 29/10): «P&L Realizado US$ 1.100» y, al lado, «Rendimiento por
// año −1,0 %». Era el promedio simple de los «por año» de cada venta: una
// pérdida chica y corta pesaba lo mismo que una ganancia grande y larga.
// Decisión de Nico: ponderar por la plata invertida y el tiempo que estuvo.
describe('D7 · rendimiento por año, ponderado por plata y tiempo', () => {
  // Las dos ventas de la auditoría, cargadas con «Nueva operación».
  const MSFT = { id: 1, asset: 'MSFT', op_type: 'Venta', currency: 'USD', entry_date: '2025-03-10', date: '2026-10-20',
    quantity: 10, entry_price: 380, exit_price: 520, pnl_usd: 1400, pnl_pct: 36.84 }
  const TSLA = { id: 2, asset: 'TSLA', op_type: 'Venta', currency: 'USD', entry_date: '2026-02-02', date: '2026-09-01',
    quantity: 5, entry_price: 420, exit_price: 360, pnl_usd: -300, pnl_pct: -14.29 }

  it('ganaste US$ 1.100: el por año da positivo (+15 %), no −1 %', () => {
    const r = resumenDiario([MSFT, TSLA])
    // 1.100 / (3.800 × 589 días + 2.100 × 211 días) × 365 = 14,97 % por año.
    expect(r.porAnio).toBeCloseTo(1100 / (3800 * 589 / 365 + 2100 * 211 / 365), 3)
    expect(r.porAnio).toBeGreaterThan(0)
    expect(r.nPorAnio).toBe(2)
  })

  it('una venta grande y larga pesa más que una chica y corta', () => {
    const chica = { ...TSLA, id: 3, quantity: 1, entry_date: '2026-08-01', pnl_usd: -60, pnl_pct: -14.29 }
    expect(resumenDiario([MSFT, chica]).porAnio).toBeGreaterThan(0.2)
  })

  it('una venta de un mes entra, pero con el peso de su mes (no infla)', () => {
    const corta = { ...MSFT, id: 4, entry_date: '2026-09-20', pnl_usd: 190, pnl_pct: 5 }
    const r = resumenDiario([corta])
    expect(r.porAnio).toBeCloseTo(190 / (3800 * 30 / 365), 3)   // como interés simple, sin componer
  })

  it('sin plata o sin fechas no inventa: «—»', () => {
    expect(resumenDiario([{ ...MSFT, entry_date: null }]).porAnio).toBeNull()
    expect(resumenDiario([]).porAnio).toBeNull()
  })
})
