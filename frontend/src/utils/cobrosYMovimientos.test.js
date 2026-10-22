// "Cobrado" de Movimientos == total del año de la pestaña Cobros, al centavo.
//
// Las dos pantallas arrancan de pedidos distintos —Movimientos de
// /api/movements, Cobros de /api/cobros— y tienen que contar lo mismo, con el
// cupón de los pagos de bonos que traen cupón y amortización juntos adentro.
// Las respuestas son las REALES: las arma y guarda la prueba del servidor
// (backend/tests/test_cobros.py · CobradoIgualEnLasDosPantallas), que importa
// un caso con los dos formatos de Balanz y falla si el servidor cambia lo que
// devuelve sin regenerar este archivo. Pedido de Nico, 2026-10-22.
import { describe, it, expect } from 'vitest'
import datos from './fixtures/cobrosYMovimientos.json'
import { computeMovementKpis } from '../pages/Operations.jsx'
import { resumirCobros, cobradoDe, cuponDelPago } from './cobros'

const { movements, cobros } = datos
const sumar = (filas, getUsd) => filas.reduce((s, f) => s + getUsd(f), 0)
// Lo que hace Movimientos con el filtro de año en 2026 (Operations.jsx · filtered).
const del2026 = movements.filter(m => (m.date || '').startsWith('2026'))
const kpi = (lista, label) => lista.find(k => k.label === label).num

describe('lo cobrado en las dos pantallas', () => {
  const resumen = resumirCobros(cobros)

  it('"Cobrado" de Movimientos y "Cobraste en 2026" de Cobros dan lo mismo, al centavo', () => {
    const cobrado = kpi(computeMovementKpis(del2026, 'all', { sumar, fmt: String }, 0, cobradoDe(del2026, sumar)), 'Cobrado')
    expect(Math.abs(cobrado - resumen.total_anio)).toBeLessThan(0.005)
  })

  it('los dos cuentan el cupón de los pagos mixtos, no el pago entero', () => {
    const mixtos = cobros.pagos_mixtos
    const cupones = mixtos.reduce((s, p) => s + cuponDelPago(p), 0)
    const enteros = cobros.cobros.filter(c => c.fecha.startsWith('2026')).reduce((s, c) => s + c.usd, 0)
    expect(cupones).toBeGreaterThan(0)
    expect(resumen.total_anio).toBeCloseTo(enteros + cupones, 6)
    // Ni el capital devuelto ni nada de afuera.
    expect(resumen.total_anio).toBeLessThan(enteros + mixtos.reduce((s, p) => s + p.usd, 0))
    expect(resumen.mixtos).toMatchObject({ separados: 2, sinSeparar: 0 })
  })

  it('el total del filtro Dividendos incluye el cupón de los pagos mixtos y lo dice', () => {
    const lista = computeMovementKpis(del2026.filter(m => m.type === 'DIVIDEND'), 'DIVIDEND', { sumar, fmt: String }, 0, cobradoDe(del2026, sumar))
    const total = kpi(lista, 'Total dividendos')
    const intereses = kpi(computeMovementKpis([], 'INTEREST', { sumar, fmt: String }, 0, cobradoDe(del2026, sumar)), 'Total intereses')
    expect(Math.abs(total + intereses - resumen.total_anio)).toBeLessThan(0.005)
    expect(lista[0].sub).toContain('incluye el cupón de 2 pagos de bonos con amortización')
  })
})
