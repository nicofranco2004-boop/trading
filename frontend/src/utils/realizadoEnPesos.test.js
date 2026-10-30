import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { realizadoEnPesos, notaDelRealizado, realizadoDeLaFilaMensual, sumarRealizadoMeses } from './realizadoEnPesos'
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

  it('una pérdida en pesos con ganancia en dólares conserva el signo de los pesos', () => {
    // 100 u. compradas a $4.500 con el dólar a 1.500 (US$ 300) y vendidas a $4.400 con el dólar
    // a 1.000 (US$ 440): el peso se apreció, así que en dólares +US$ 140 y en pesos −$10.000.
    const r = realizadoEnPesos({ usd: 140, ars: -10000, cubreUsd: 140, fx: 1000 })
    expect(r.monto).toBe(-10000)
    expect(r.monto * 140).toBeLessThan(0)    // signos opuestos: dólares × dólar daría +$140.000
  })

  it('una pérdida sale negativa también en la cuenta (no sólo en valor absoluto)', () => {
    expect(realizadoEnPesos({ usd: -2, ars: -3000, cubreUsd: -2, fx: 1500 }).restoUsd).toBe(0)
    // el resto de una pérdida en dólares también conserva el signo
    expect(realizadoEnPesos({ usd: -22, ars: -3000, cubreUsd: -2, fx: 1500 }).restoUsd).toBe(-20)
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
  it('dice si hubo ventas o compras en dólares (la misma frase que Movimientos)', () => {
    expect(notaDelRealizado({ restoUsd: 0, valuado: true }))
      .toBe('ventas o compras en dólares valuadas al dólar de cada fecha')
  })
  it('el umbral es de un dólar convertido: 0,9 no avisa, 1 sí', () => {
    expect(notaDelRealizado({ restoUsd: 0.9 })).toBeNull()
    expect(notaDelRealizado({ restoUsd: 1 })).toMatch(/US\$ 1 convertidos/)
  })
  it('lo convertido avisa con cualquier signo', () => {
    expect(notaDelRealizado({ restoUsd: -20 })).toMatch(/US\$ 20 convertidos/)
  })
  it('junta las dos aclaraciones y nombra el dólar usado', () => {
    expect(notaDelRealizado({ restoUsd: 20, valuado: true, dolar: 'de cada mes' }))
      .toBe('ventas o compras en dólares valuadas al dólar de cada fecha · incluye US$ 20 convertidos al dólar de cada mes')
  })
  it('juntando meses se suma el valor absoluto: +500 y −500 no se cancelan', () => {
    // El que junta varios meses suma Math.abs de cada resto. Con signo daba 0 y el cartel
    // desaparecía aunque todo el monto fuera convertido.
    const meses = [{ usd: 500, ars: 0, cubreUsd: 0, fx: 1000 }, { usd: -500, ars: 0, cubreUsd: 0, fx: 1000 }]
    const restos = meses.map(m => realizadoEnPesos(m).restoUsd)
    expect(restos.reduce((a, b) => a + b, 0)).toBe(0)
    const abs = restos.reduce((a, b) => a + Math.abs(b), 0)
    expect(notaDelRealizado({ restoUsd: abs, dolar: 'de cada mes' })).toMatch(/US\$ 1\.?000 convertidos/)
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

  // El hallazgo de la auditoría: con el mismo dólar en todos lados, usar el equivocado pasaba.
  describe('cada resto va a SU dólar', () => {
    const tcEnFecha = (iso) => (String(iso).startsWith('2024-06') ? 1200 : String(iso).startsWith('2024-05') ? 1000 : 1500)
    const crear2 = () => crearPesosDelPeriodo({
      moneda: 'ARS', tcHoy: 1500, tcEnFecha, dolarMes: {}, monthly: [], brokers: [],
    })
    // US$ 10 de la venta + US$ 20 de un dividendo en dólares
    const conDividendo = { ...periodo, metrics: { ...periodo.metrics, realized_pnl: 30, delta_usd: 30 } }

    it('un mes cerrado convierte el resto al dólar de su cierre, no al de hoy', () => {
      const v = crear2().enVista(conDividendo)
      expect(v.fxCierre).toBe(1200)
      expect(v.realizado).toBe(240000 + 20 * 1200)
    })
    it('el mes en curso lo convierte al dólar de hoy', () => {
      const v = crear2().enVista({ ...conDividendo, is_current: true })
      expect(v.fxCierre).toBe(1500)
      expect(v.realizado).toBe(240000 + 20 * 1500)
    })
  })

  describe('el resultado contiene al realizado (si no, no cierra la tarjeta)', () => {
    const pesos = crear('ARS')
    it('un mes con una sola venta: resultado = realizado, sin posiciones abiertas', () => {
      const v = pesos.enVista(periodo)
      expect(v.resultado).toBe(240000)
      expect(v.noRealizado).toBe(0)
      expect(v.resultado).toBe(v.realizado + v.noRealizado)
    })
    it('con el dólar a favor del peso: ni el signo del resultado se da vuelta', () => {
      // En dólares −US$ 130 (delta y realizado), en pesos +$30.000: el resultado es el de los pesos.
      const v = pesos.enVista({ ...periodo, metrics: { realized_pnl: -130, realized_ars: 30000,
        realized_ars_cubre_usd: -130, unrealized_pnl: 0, delta_usd: -130 } })
      expect(v.realizado).toBe(30000)
      expect(v.resultado).toBe(30000)
    })
    it('una semana con ventas y posiciones abiertas: resultado = realizado + no realizado', () => {
      // delta −US$ 100 = realizado −US$ 130 + no realizado +US$ 30 (así lo arma el servidor)
      const v = pesos.enVista({ ...periodo, period_type: 'week', metrics: { realized_pnl: -130,
        realized_ars: 30000, realized_ars_cubre_usd: -130, unrealized_pnl: 30, delta_usd: -100 } })
      expect(v.noRealizado).toBe(30 * 1500)
      expect(v.resultado).toBe(v.realizado + v.noRealizado)
    })
    it('lo que no es ni vendido ni abierto (el efecto del dólar) queda en el resultado', () => {
      const v = pesos.enVista({ ...periodo, metrics: { ...periodo.metrics, delta_usd: 14 } })
      expect(v.resultado).toBe(240000 + 4 * 1500)
    })
    it('en dólares el resultado es el del servidor', () => {
      expect(crear('USD').enVista(periodo).resultado).toBe(10)
    })
    it('sin la cuenta del servidor (versión anterior) queda como antes: dólares × dólar', () => {
      const v = pesos.enVista({ ...periodo, metrics: { realized_pnl: 10, unrealized_pnl: 0, delta_usd: 10 } })
      expect(v.resultado).toBe(15000)
    })
  })

  describe('lo convertido y lo valuado se dicen', () => {
    it('la nota junta lo valuado y lo convertido', () => {
      const v = crear('ARS').enVista({ ...periodo, metrics: { ...periodo.metrics, realized_pnl: 30,
        delta_usd: 30, realized_ars_valuado: true } })
      expect(v.realizadoNota).toMatch(/ventas o compras en dólares valuadas/)
      expect(v.realizadoNota).toMatch(/incluye US\$ 20 convertidos/)
      expect(v.realizadoValuado).toBe(true)
      expect(v.realizadoRestoUsd).toBe(20)
    })
    it('el resto de una pérdida convertida se expone en valor absoluto, para sumar meses', () => {
      const v = crear('ARS').enVista({ ...periodo, metrics: { ...periodo.metrics, realized_pnl: -10,
        delta_usd: -10, realized_ars: 0, realized_ars_cubre_usd: 0 } })
      expect(v.realizadoRestoUsd).toBe(10)
    })
    it('en dólares no hay nada que avisar', () => {
      const v = crear('USD').enVista({ ...periodo, metrics: { ...periodo.metrics, realized_ars_valuado: true } })
      expect(v.realizadoNota).toBeNull()
      expect(v.realizadoRestoUsd).toBe(0)
      expect(v.realizadoValuado).toBe(false)
    })
  })
})

// Las filas de /api/monthly, como las manda el servidor (backend/main.py, get_monthly).
const fila = (year, month, usd, ars, cubre, extra = {}) => ({
  broker: 'global', year, month, pnl_realized: usd, realized_ars: ars, realized_ars_cubre_usd: cubre,
  realized_ars_valuado: false, ...extra,
})

describe('el Dashboard y el Resumen mensual leen el realizado de la fila de /api/monthly', () => {
  it('una fila con una venta en pesos: los pesos del broker, no dólares × dólar', () => {
    expect(realizadoDeLaFilaMensual(fila(2024, 6, 10, 240000, 10), 1500).monto).toBe(240000)
  })
  it('una fila de un servidor anterior (sin los campos nuevos) se convierte entera', () => {
    expect(realizadoDeLaFilaMensual({ pnl_realized: 10 }, 1500).monto).toBe(15000)
  })

  describe('sumarRealizadoMeses: convertir y después sumar, cada resto a SU dólar', () => {
    const dolar = { '2024-05': 1000, '2024-06': 1200 }
    const fx = (m) => dolar[`${m.year}-${String(m.month).padStart(2, '0')}`] ?? 1500
    it('cada mes convierte su resto con el dólar de ese mes', () => {
      const r = sumarRealizadoMeses([
        fila(2024, 5, 20, 0, 0),               // sólo un dividendo en dólares: US$ 20 × 1.000
        fila(2024, 6, 30, 240000, 10),         // la venta GGAL + US$ 20 de dividendo × 1.200
      ], fx)
      expect(r.monto).toBe(20 * 1000 + 240000 + 20 * 1200)
      expect(r.restoUsd).toBe(40)
    })
    it('los restos de signo opuesto no se cancelan: el cartel sigue', () => {
      const r = sumarRealizadoMeses([fila(2024, 5, 500, 0, 0), fila(2024, 6, -500, 0, 0)], fx)
      expect(r.monto).toBe(500 * 1000 - 500 * 1200)
      expect(r.restoUsd).toBe(1000)
      expect(notaDelRealizado({ restoUsd: r.restoUsd, dolar: 'de cada mes' })).toMatch(/convertidos/)
    })
    it('un mes valuado marca el total', () => {
      expect(sumarRealizadoMeses([fila(2024, 6, 10, 240000, 10, { realized_ars_valuado: true })], fx).valuado).toBe(true)
      expect(sumarRealizadoMeses([fila(2024, 6, 10, 240000, 10)], fx).valuado).toBe(false)
    })
    it('sin filas: cero', () => {
      expect(sumarRealizadoMeses([], fx)).toEqual({ monto: 0, restoUsd: 0, valuado: false })
      expect(sumarRealizadoMeses(null, fx).monto).toBe(0)
    })
  })

  // Guardia de texto (con sus puntos ciegos): las dos pantallas siguen usando la cuenta y no
  // volvieron a multiplicar `pnl_realized` por el dólar. Lo que prueba la cuenta son los tests de arriba.
  describe('las pantallas usan la cuenta', () => {
    const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
    it('Dashboard', () => {
      const t = leer('../pages/Dashboard.jsx')
      expect(t).toMatch(/sumarRealizadoMeses\(/)
      expect(t).toMatch(/realizadoDeLaFilaMensual\(/)
    })
    it('Resumen mensual', () => {
      expect(leer('../components/MonthlySummary.jsx')).toMatch(/realizadoDeLaFilaMensual\(/)
    })
  })
})
