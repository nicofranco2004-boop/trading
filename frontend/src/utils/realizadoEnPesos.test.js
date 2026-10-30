import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { realizadoEnPesos, notaDelRealizado, realizadoDeLaFilaMensual, sumarRealizadoMeses, realizadoGlobalDeLosMeses, realizadoGlobalDelMes } from './realizadoEnPesos'
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
    it('una semana de un broker filtrado: el delta del servidor ES lo realizado, el resultado también', () => {
      // Con un broker elegido el servidor pone delta = realizado y no realizado = 0 (no mide las
      // abiertas del broker). −US$ 130 en dólares, +$30.000 en pesos: el resultado es el de los pesos.
      const v = pesos.enVista({ ...periodo, period_type: 'week', metrics: { realized_pnl: -130,
        realized_ars: 30000, realized_ars_cubre_usd: -130, unrealized_pnl: 0, delta_usd: -130 } })
      expect(v.resultado).toBe(30000)
      expect(v.noRealizado).toBe(0)
      expect(v.resultado).toBe(v.realizado + v.noRealizado)
    })
    it('si el servidor midió el delta con otra medida y hay abiertas, no se le pegan pesos exactos encima', () => {
      // Sin las dos puntas no hay resta que repetir en pesos. Mezclar el realizado exacto con un
      // delta en dólares que ya trae lo latente era lo que inflaba el resultado: queda el delta.
      const v = pesos.enVista({ ...periodo, period_type: 'week', metrics: { realized_pnl: -130,
        realized_ars: 30000, realized_ars_cubre_usd: -130, unrealized_pnl: 30, delta_usd: -100 } })
      expect(v.resultado).toBe(-100 * 1500)
      expect(v.noRealizado).toBe(30 * 1500)
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

  // LA AUDITORÍA 2 (alta): vender algo que ya tenías al empezar el período. El delta en dólares trae
  // el vaciado de lo latente, y en pesos no hay latente: el resultado tiene que ser la resta de los
  // pesos de la propia tarjeta (cierre − inicio − flujos), no el delta con el realizado cambiado.
  describe('vender una posición que ya tenías al empezar el período', () => {
    // El dólar de mayo (la punta del inicio) es 1.000; el de junio (el cierre) y el de hoy, 1.500.
    const tcEnFecha = (iso) => (String(iso) < '2024-06' ? 1000 : 1500)
    const pesos = crearPesosDelPeriodo({
      moneda: 'ARS', tcHoy: 1500, tcEnFecha, dolarMes: {}, monthly: [], brokers: [],
    })
    const mes = (metrics) => ({ period_type: 'month', period_start: '2024-06-01', period_end: '2024-06-30',
      is_current: false, metrics: { realized_ars_valuado: false, deposits: 0, withdrawals: 0, ...metrics } })
    // La tarjeta cierra: valor de inicio + depósitos − retiros + resultado = valor de cierre.
    const cierra = (v) => expect(v.inicio + v.depositos - v.retiros + v.resultado).toBeCloseTo(v.cierre, 6)

    it('ganancia: GGAL comprada a $450.000 (dólar 500), valía $450.000 al arrancar y se vende a $690.000', () => {
      // En dólares: costo US$ 900, valía US$ 450 al arrancar (dólar 1.000) y se vende a US$ 460
      // (dólar 1.500). realizado −440, el latente que se vacía +450, delta +10. En pesos: +$240.000.
      const v = pesos.enVista(mes({ start_value: 450, end_value: 460, delta_usd: 10, realized_pnl: -440,
        realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 450 }))
      expect(v.inicio).toBe(450000)
      expect(v.cierre).toBe(690000)
      expect(v.realizado).toBe(240000)
      expect(v.resultado).toBe(240000)
      expect(v.noRealizado).toBe(0)
      cierra(v)
    })
    it('pérdida: ni el signo se da vuelta (−$10.000, no un número positivo)', () => {
      // Comprada a $100.000 con el dólar a 500 (US$ 200); valía US$ 100 al arrancar; se vende a
      // $90.000 con el dólar a 1.500 (US$ 60). realizado −140, latente +100, delta −40.
      const v = pesos.enVista(mes({ start_value: 100, end_value: 60, delta_usd: -40, realized_pnl: -140,
        realized_ars: -10000, realized_ars_cubre_usd: -140, unrealized_pnl: 100 }))
      expect(v.realizado).toBe(-10000)
      expect(v.resultado).toBe(-10000)
      expect(v.noRealizado).toBe(0)
      cierra(v)
    })
    it('una parte vendida y otra abierta: lo abierto es lo que sobra', () => {
      // La mitad de la posición del primer caso se vende y la otra mitad sigue (valía $225.000 al
      // arrancar, vale $345.000 ahora). Ganó $120.000 vendida + $120.000 abierta.
      const v = pesos.enVista(mes({ start_value: 450, end_value: 460, delta_usd: 10, realized_pnl: -220,
        realized_ars: 120000, realized_ars_cubre_usd: -220, unrealized_pnl: 230 }))
      expect(v.resultado).toBe(240000)
      expect(v.realizado).toBe(120000)
      expect(v.noRealizado).toBe(120000)
      expect(v.resultado).toBe(v.realizado + v.noRealizado)
      cierra(v)
    })
    it('los dividendos en dólares (lo que no es ni vendido ni abierto) van al dólar del cierre y no se pierden', () => {
      // realizado = venta (−440, de la cual 240.000 exactos) + dividendo US$ 20; delta = 10 + 20.
      const v = pesos.enVista(mes({ start_value: 450, end_value: 480, delta_usd: 30, realized_pnl: -420,
        realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 450 }))
      expect(v.realizado).toBe(240000 + 20 * 1500)
      expect(v.resultado).toBe(480 * 1500 - 450 * 1000)
      expect(v.noRealizado).toBe(0)
      cierra(v)
    })
    it('con depósitos: los flujos entran con la misma regla que muestra la fila «Depósitos»', () => {
      // Dólar quieto en 1.500 (cierre = inicio): 100 + 50 depositados, hoy 160 → ganó US$ 10 = $15.000.
      const quieto = crearPesosDelPeriodo({ moneda: 'ARS', tcHoy: 1500, tcEnFecha: () => 1500,
        dolarMes: {}, monthly: [], brokers: [] })
      const v = quieto.enVista({ ...mes({ start_value: 100, end_value: 160, delta_usd: 10, realized_pnl: 0,
        realized_ars: 0, realized_ars_cubre_usd: 0, unrealized_pnl: 10, deposits: 50 }), period_type: 'week' })
      expect(v.depositos).toBe(75000)
      expect(v.resultado).toBe(15000)
      cierra(v)
    })
    it('una cartera en dólares sin tocar: en pesos ganó lo que subió el dólar (es lo que ya dice el % de Pesos)', () => {
      // Antes mostraba +$0 al lado de un +50 % en pesos: el monto y el porcentaje se contradecían.
      const v = pesos.enVista(mes({ start_value: 100, end_value: 100, delta_usd: 0, realized_pnl: 0,
        realized_ars: 0, realized_ars_cubre_usd: 0, unrealized_pnl: 0 }))
      expect(v.resultado).toBe(100 * 1500 - 100 * 1000)
      cierra(v)
    })
    it('el delta del servidor no es la resta de las puntas (motor mensual): no se inventa la resta', () => {
      const v = pesos.enVista(mes({ start_value: 450, end_value: 460, delta_usd: 25, realized_pnl: 5,
        realized_ars: 0, realized_ars_cubre_usd: 0, unrealized_pnl: 20 }))
      expect(v.resultado).toBe(25 * 1500)
      expect(v.noRealizado).toBe(20 * 1500)
    })
    it('sin saldo en ninguna punta tampoco se repite la resta (no hay con qué)', () => {
      const v = pesos.enVista(mes({ start_value: 0, end_value: 0, delta_usd: 0, realized_pnl: 10,
        realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: 0 }))
      expect(v.inicio).toBe(0)
      expect(v.cierre).toBe(0)
      expect(v.realizado).toBe(240000)
      // Repetir la resta daría 0 − 0 − 0 = 0 aunque se haya vendido: el resultado no se queda en cero.
      expect(v.resultado).toBeGreaterThan(0)
    })
    it('lo que no es ni vendido ni abierto (con otros) sale del dólar del cierre y no rompe la suma', () => {
      // delta 30 = realizado −440 + abiertas +440 + otros +30 (p. ej. un dividendo ya contado aparte).
      const v = pesos.enVista(mes({ start_value: 450, end_value: 480, delta_usd: 30, realized_pnl: -440,
        realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 440 }))
      expect(v.resultado).toBe(480 * 1500 - 450 * 1000)
      expect(v.noRealizado).toBe(v.resultado - v.realizado - 30 * 1500)
      expect(v.resultado).toBe(v.realizado + v.noRealizado + 30 * 1500)
    })
    it('sin realizado en el período (no vendió nada) el no realizado es el de las abiertas al dólar del cierre', () => {
      const tres = crearPesosDelPeriodo({ moneda: 'ARS', tcHoy: 1500, dolarMes: {}, monthly: [], brokers: [],
        tcEnFecha: (iso) => (String(iso) < '2024-06' ? 1000 : 1200) })   // cierre 1.200 ≠ hoy 1.500
      const v = tres.enVista(mes({ start_value: 450, end_value: 460, delta_usd: 10, unrealized_pnl: 10 }))
      expect(v.realizado).toBeNull()
      expect(v.noRealizado).toBe(10 * 1200)
      expect(v.resultado).toBe(460 * 1200 - 450 * 1000)
    })
    // Tres dólares distintos —el del inicio (mayo 1.000), el del cierre (junio 1.200) y el de hoy
    // (1.500)—: con el mismo en todos lados, usar el equivocado pasaría igual.
    it('cada punta va a SU dólar: el inicio al de mayo, el cierre al de junio, no al de hoy', () => {
      const tres = crearPesosDelPeriodo({ moneda: 'ARS', tcHoy: 1500, dolarMes: {}, monthly: [], brokers: [],
        tcEnFecha: (iso) => (String(iso) < '2024-06' ? 1000 : 1200) })
      // GGAL vendida a $690.000 con el dólar a 1.200 (US$ 575; costó US$ 900) + un dividendo de US$ 20.
      const v = tres.enVista(mes({ start_value: 450, end_value: 595, delta_usd: 145, realized_pnl: -305,
        realized_ars: 240000, realized_ars_cubre_usd: -325, unrealized_pnl: 450 }))
      expect(v.fxInicio).toBe(1000)
      expect(v.fxCierre).toBe(1200)
      expect(v.inicio).toBe(450000)
      expect(v.cierre).toBe(595 * 1200)
      expect(v.realizado).toBe(240000 + 20 * 1200)      // el dividendo, al dólar del cierre
      expect(v.resultado).toBe(595 * 1200 - 450 * 1000) // 264.000
      expect(v.noRealizado).toBe(0)
      expect(v.resultado).toBe(v.realizado + v.noRealizado)
      cierra(v)
    })
    it('en el mes en curso el cierre es el dólar de hoy', () => {
      const tres = crearPesosDelPeriodo({ moneda: 'ARS', tcHoy: 1500, dolarMes: {}, monthly: [], brokers: [],
        tcEnFecha: (iso) => (String(iso) < '2024-06' ? 1000 : 1200) })
      const v = tres.enVista({ ...mes({ start_value: 450, end_value: 460, delta_usd: 10, realized_pnl: -440,
        realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 450 }), is_current: true })
      expect(v.fxCierre).toBe(1500)
      expect(v.cierre).toBe(460 * 1500)
      expect(v.resultado).toBe(460 * 1500 - 450 * 1000)
      cierra(v)
    })
    it('en dólares sigue todo como lo manda el servidor', () => {
      const d = crearPesosDelPeriodo({ moneda: 'USD', tcHoy: 1500, tcEnFecha, dolarMes: {}, monthly: [], brokers: [] })
      const v = d.enVista(mes({ start_value: 450, end_value: 460, delta_usd: 10, realized_pnl: -440,
        realized_ars: 240000, realized_ars_cubre_usd: -440, unrealized_pnl: 450 }))
      expect(v.resultado).toBe(10)
      expect(v.noRealizado).toBe(450)
      expect(v.realizado).toBe(-440)
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

  // El Dashboard lee estas dos funciones puras (no hay cuenta escrita en la pantalla): lo que se prueba
  // es el comportamiento, no que aparezca un nombre en el archivo.
  describe('realizadoGlobalDeLosMeses (KPI «P&L realizado» del Dashboard)', () => {
    const dolar = { '2024-05': 1000, '2024-06': 1200 }
    const fxDelMes = (m) => dolar[`${m.year}-${String(m.month).padStart(2, '0')}`] ?? 1500
    it('el caso GGAL: $240.000 de verdad, no los US$ 10 × el dólar', () => {
      const r = realizadoGlobalDeLosMeses([fila(2024, 6, 10, 240000, 10)], { moneda: 'ARS', fxDelMes })
      expect(r.monto).toBe(240000)
      expect(r.nota).toBeNull()
    })
    it('suma sólo el total (global): sumar también el de cada broker lo contaría dos veces', () => {
      const r = realizadoGlobalDeLosMeses([
        fila(2024, 6, 10, 240000, 10),
        fila(2024, 6, 10, 240000, 10, { broker: 'Cocos' }),
      ], { moneda: 'ARS', fxDelMes })
      expect(r.monto).toBe(240000)
    })
    it('cada mes convierte su resto con el dólar de ese mes, no el de hoy ni el del mes anterior', () => {
      const r = realizadoGlobalDeLosMeses([fila(2024, 5, 20, 0, 0), fila(2024, 6, 20, 0, 0)], { moneda: 'ARS', fxDelMes })
      expect(r.monto).toBe(20 * 1000 + 20 * 1200)
      expect(r.restoUsd).toBe(40)
      expect(r.nota).toMatch(/incluye US\$ 40 convertidos al dólar de cada mes/)
    })
    it('una venta en dólares valuada se dice', () => {
      const r = realizadoGlobalDeLosMeses([fila(2024, 6, 500, 1250000, 500, { realized_ars_valuado: true })], { moneda: 'ARS', fxDelMes })
      expect(r.valuado).toBe(true)
      expect(r.nota).toMatch(/valuadas/)
    })
    it('en dólares: la suma de siempre y ningún cartel', () => {
      const r = realizadoGlobalDeLosMeses([fila(2024, 5, 20, 0, 0), fila(2024, 6, 10, 240000, 10)], { moneda: 'USD', fxDelMes })
      expect(r).toEqual({ monto: 30, restoUsd: 0, valuado: false, nota: null })
    })
    it('sin filas: cero', () => {
      expect(realizadoGlobalDeLosMeses(null, { moneda: 'ARS', fxDelMes }).monto).toBe(0)
    })
  })

  describe('realizadoGlobalDelMes (nota «realizado» de «Este mes»)', () => {
    const meses = [fila(2024, 5, 99, 0, 0), fila(2024, 6, 10, 240000, 10), fila(2024, 6, 10, 240000, 10, { broker: 'Cocos' })]
    it('en pesos: el del mes pedido, del total, con los pesos de verdad', () => {
      expect(realizadoGlobalDelMes(meses, { year: 2024, month: 6, moneda: 'ARS', fx: 1500 })).toBe(240000)
    })
    it('el resto de ese mes va al dólar que se le pasa', () => {
      expect(realizadoGlobalDelMes([fila(2024, 6, 30, 240000, 10)], { year: 2024, month: 6, moneda: 'ARS', fx: 1200 }))
        .toBe(240000 + 20 * 1200)
    })
    it('en dólares: los dólares', () => {
      expect(realizadoGlobalDelMes(meses, { year: 2024, month: 6, moneda: 'USD', fx: 1500 })).toBe(10)
    })
    it('un mes sin fila: cero', () => {
      expect(realizadoGlobalDelMes(meses, { year: 2024, month: 7, moneda: 'ARS', fx: 1500 })).toBe(0)
    })
  })

  // Guardia de texto: SÓLO ve que el nombre aparece en el archivo, no que se lo llame bien (D3: llamar a
  // la función y descartar el resultado la pasa en verde). Lo que prueba la cuenta son los tests de arriba.
  describe('las pantallas usan la cuenta', () => {
    const leer = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
    it('Dashboard', () => {
      const t = leer('../pages/Dashboard.jsx')
      expect(t).toMatch(/realizadoGlobalDeLosMeses\(/)
      expect(t).toMatch(/realizadoGlobalDelMes\(/)
    })
    it('Resumen mensual', () => {
      const t = leer('../components/MonthlySummary.jsx')
      expect(t).toMatch(/realizadoDeLaFilaMensual\(/)
      expect(t).toMatch(/sumarRealizadoMeses\(/)
    })
  })
})
