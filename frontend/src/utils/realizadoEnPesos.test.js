import { describe, it, expect } from 'vitest'
import { realizadoEnPesos, notaDelRealizado } from './realizadoEnPesos'
import { crearPesosDelPeriodo } from './periodoEnPesos'

// GGAL comprada a $4.500 con el dólar a 1.000 y vendida a $6.900 con el dólar a 1.500:
// +$240.000 en pesos (lo que dice el broker) y +US$10 en dólares. US$10 × 1.500 son $15.000.
const GGAL = { usd: 10, ars: 240000, cubreUsd: 10, fx: 1500 }

describe('realizadoEnPesos', () => {
  it('la venta en pesos da los pesos del broker, no los dólares × el dólar', () => {
    const r = realizadoEnPesos(GGAL)
    expect(r.monto).toBe(240000)
    expect(r.restoUsd).toBe(0)
  })

  it('sólo lo que no tiene pesos se convierte al dólar del período', () => {
    // US$ 10 de la venta + US$ 20 de un dividendo en dólares (no tiene pesos de verdad)
    const r = realizadoEnPesos({ ...GGAL, usd: 30 })
    expect(r.monto).toBe(240000 + 20 * 1500)
    expect(r.restoUsd).toBe(20)
  })

  it('sin la cuenta del servidor (versión anterior) convierte todo, como antes', () => {
    const r = realizadoEnPesos({ usd: 10, fx: 1500 })
    expect(r.monto).toBe(15000)
    expect(r.restoUsd).toBe(10)
  })

  it('un mes sin ventas ni cobros no inventa nada', () => {
    expect(realizadoEnPesos({ usd: 0, ars: 0, cubreUsd: 0, fx: 1500 }).monto).toBe(0)
  })

  it('una pérdida en pesos con ganancia en dólares conserva su signo', () => {
    // vendida $4.000 lo comprado a $4.500 con el dólar subiendo no puede dar positivo en pesos
    const r = realizadoEnPesos({ usd: -1, ars: -50000, cubreUsd: -1, fx: 1500 })
    expect(r.monto).toBe(-50000)
  })

  it('sin dólar con el que convertir el resto, no se inventa el número', () => {
    expect(realizadoEnPesos({ usd: 30, ars: 240000, cubreUsd: 10, fx: null }).monto).toBeNull()
    // …pero si no hay resto, los pesos exactos no necesitan dólar
    expect(realizadoEnPesos({ ...GGAL, fx: null }).monto).toBe(240000)
  })
})

describe('notaDelRealizado', () => {
  it('todo exacto: sin aclaración', () => {
    expect(notaDelRealizado({ restoUsd: 0, valuado: false })).toBeNull()
    expect(notaDelRealizado({ restoUsd: 0.4 })).toBeNull()
  })
  it('dice qué parte es convertida', () => {
    expect(notaDelRealizado({ restoUsd: 20 })).toMatch(/incluye US\$ 20 convertidos al dólar del cierre/)
  })
  it('dice si hubo ventas en dólares', () => {
    expect(notaDelRealizado({ restoUsd: 0, valuado: true })).toMatch(/ventas en dólares valuadas/)
  })
})

describe('Reportes en Pesos (periodoEnPesos.enVista)', () => {
  const crear = (moneda) => crearPesosDelPeriodo({
    moneda, tcHoy: 1500, tcEnFecha: () => 1500, dolarMes: {}, monthly: [], brokers: [],
  })
  const periodo = {
    period_type: 'month', period_start: '2024-06-01', period_end: '2024-06-30', is_current: false,
    metrics: { realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10, realized_ars_valuado: false,
               unrealized_pnl: 0, delta_usd: 10 },
  }

  it('en Pesos el realizado es el de las ventas en pesos', () => {
    const v = crear('ARS').enVista(periodo)
    expect(v.realizado).toBe(240000)
    expect(v.realizadoNota).toBeNull()
  })
  it('en Dólares no cambia: el realizado en dólares', () => {
    const v = crear('USD').enVista(periodo)
    expect(v.realizado).toBe(10)
    expect(v.realizadoNota).toBeNull()
  })
  it('con dividendos en dólares los convierte y lo dice', () => {
    const v = crear('ARS').enVista({ ...periodo, metrics: { ...periodo.metrics, realized_pnl: 30 } })
    expect(v.realizado).toBe(240000 + 20 * 1500)
    expect(v.realizadoNota).toMatch(/US\$ 20/)
  })
  it('un período de una versión anterior (sin los campos nuevos) se convierte entero', () => {
    const v = crear('ARS').enVista({ ...periodo, metrics: { realized_pnl: 10, unrealized_pnl: 0, delta_usd: 10 } })
    expect(v.realizado).toBe(15000)
  })
})
