import { describe, it, expect } from 'vitest'
import {
  duracion, medicion, pctConSigno, plata, primeraCompra, puntosDesde, tarjetasMovimiento,
  textoEvento, textoGananciaPorAccion, textoGrupo, textoMedicion,
} from './cuantoSeMueve'

const precio = (x) => `US$ ${x.toLocaleString('es-AR', { maximumFractionDigits: 2 })}`

const MOV = {
  disponible: true, desde: '2024-10-24', hasta: '2026-10-22',
  peor_caida: {
    pico: { fecha: '2025-02-10', precio: 274 }, piso: { fecha: '2025-04-21', precio: 181 },
    pct: -33.94, volvio: '2025-11-20', dias_para_volver: 148, dias_corridos_para_volver: 213,
  },
  dia_normal: { desvio_pct: 1.6, dias: 500, dias_malos: 80, sp500_desvio_pct: 0.9, veces_el_sp500: 1.78 },
  desde_el_maximo: { pct: -16.6, maximo: 260, anio_completo: true },
}

describe('formatos', () => {
  it('el signo de verdad y la coma', () => {
    expect(pctConSigno(10.06)).toBe('+10,1%')
    expect(pctConSigno(-4.2)).toBe('−4,2%')
    expect(plata(-85.4, 'usd')).toBe('−US$ 85')
    expect(plata(120000, 'ars')).toBe('$ 120.000')
  })
  it('la duración como se dice', () => {
    expect(duracion(12)).toBe('12 días')
    expect(duracion(213)).toBe('7 meses')
    expect(duracion(430)).toBe('1 año y 2 meses')
    expect(duracion(731)).toBe('2 años')
  })
})

describe('desde que lo tenés', () => {
  it('el lote abierto más viejo, sin efectivo ni lotes vacíos', () => {
    expect(primeraCompra([
      { entry_date: '2025-06-01', quantity: 3 },
      { entry_date: '2024-03-05T00:00:00', quantity: 1 },
      { entry_date: '2020-01-01', quantity: 0 },
      { entry_date: '2019-01-01', quantity: 100, is_cash: 1 },
    ])).toBe('2024-03-05')
    expect(primeraCompra([])).toBeNull()
  })
  it('cuántos puntos desde esa fecha', () => {
    const p = ['2025-01-02', '2025-01-03', '2025-01-06', '2025-01-07'].map(d => ({ d }))
    expect(puntosDesde(p, '2025-01-04')).toBe(2)
    expect(puntosDesde(p, '2025-01-03')).toBe(3)
    expect(puntosDesde(p, '2000-01-01')).toBe(4)
  })
})

describe('medir entre dos puntos', () => {
  const p = [100, 110, 99, 121].map((c, i) => ({ d: `2025-03-0${i + 3}`, c }))
  it('el % entre los PRECIOS tocados (no los cierres) y los días de mercado, en cualquier orden', () => {
    const m = medicion(p, { i: 3, precio: 130 }, { i: 0, precio: 104 })
    expect(m.desde).toBe('2025-03-03')
    expect(m.hasta).toBe('2025-03-06')
    expect(m.precioDesde).toBe(104)
    expect(m.diferencia).toBe(26)
    expect(m.dias).toBe(3)
    expect(m.pct).toBeCloseTo(25, 9)
    expect(textoMedicion(m)).toBe('+25,0% en 3 días de mercado')
    expect(textoMedicion(medicion(p, { i: 1, precio: 110 }, { i: 2, precio: 99 }))).toBe('−10,0% en 1 día de mercado')
  })
  it('hacia adelante: el espacio vacío de la derecha cuenta días de mercado que todavía no pasaron', () => {
    const m = medicion(p, { i: 3, precio: 121 }, { i: 23, precio: 145.2 })
    expect(m.hasta).toBeNull()
    expect(m.adelanteHasta).toBe(20)
    expect(m.adelanteDesde).toBe(0)
    expect(textoMedicion(m)).toBe('+20,0% en 20 días de mercado')
  })
  it('el mismo día, dos precios: también se mide (en vertical, como TradingView)', () => {
    expect(textoMedicion(medicion(p, { i: 1, precio: 100 }, { i: 1, precio: 105 }))).toBe('+5,0% en el mismo día')
    expect(textoMedicion(medicion(p, { i: 1, precio: 100 }, { i: 1, precio: 100 }))).toBe('Es el mismo punto: tocá otro.')
  })
  it('sin los dos toques no hay medición', () => {
    expect(medicion(p, { i: 0, precio: 100 }, null)).toBeNull()
    expect(medicion(p, { i: 0, precio: 0 }, { i: 1, precio: 100 })).toBeNull()
  })
})

describe('globos de balances y dividendos', () => {
  it('balance presentado con el mercado cerrado', () => {
    const t = textoEvento({ tipo: 'balance', fecha: '2025-07-31', momento: 'despues_del_cierre',
      reaccion: { pct: -4.21, cuando: 'al_otro_dia' } })
    expect(t.titulo).toBe('Balance del 31/07/25')
    expect(t.lineas).toEqual(['Presentó resultados después del cierre del mercado.', 'Al día siguiente, el precio: −4,2%'])
  })
  it('sin hora conocida: los dos días juntos', () => {
    const t = textoEvento({ tipo: 'balance', fecha: '2025-07-31', momento: null, reaccion: { pct: 3 } })
    expect(t.lineas).toEqual(['Entre ese día y el siguiente, el precio: +3,0%'])
  })
  it('dividendo con su monto y el día de corte explicado', () => {
    const t = textoEvento({ tipo: 'dividendo', fecha: '2025-08-11', monto: 0.26, moneda: 'usd',
      reaccion: { pct: -0.4 } })
    expect(t.titulo).toBe('Dividendo · día de corte 11/08/25')
    expect(t.lineas[0]).toBe('Pagó US$ 0,26 por acción.')
    expect(t.lineas[2]).toBe('Ese día el precio: −0,4%')
  })
})

describe('marcas juntas', () => {
  it('dividendos de todos los meses: un renglón por cada uno', () => {
    const t = textoGrupo([
      { tipo: 'dividendo', fecha: '2026-07-06', monto: 8.300841, moneda: 'ars', reaccion: { pct: 4.48 } },
      { tipo: 'dividendo', fecha: '2026-08-03', monto: 8.300841, moneda: 'ars', reaccion: null },
    ])
    expect(t.titulo).toBe('2 dividendos')
    expect(t.lineas).toEqual(['06/07/26: pagó $ 8,301 · ese día +4,5%', '03/08/26: pagó $ 8,301',
      'Por acción. Quien compra desde el día de corte ya no cobra este dividendo.'])
  })
  it('balances juntos dicen cuándo se midió cada uno; uno solo, el globo de siempre', () => {
    const t = textoGrupo([
      { tipo: 'balance', fecha: '2026-05-13', momento: 'despues_del_cierre', reaccion: { pct: -0.25 } },
      { tipo: 'balance', fecha: '2026-05-20', momento: 'antes_del_cierre', reaccion: { pct: 1.7 } },
    ])
    expect(t.lineas).toEqual(['13/05/26: al día siguiente −0,3%', '20/05/26: ese día +1,7%'])
    const e = { tipo: 'balance', fecha: '2026-05-13', momento: null, reaccion: { pct: 2 } }
    expect(textoGrupo([e])).toEqual(textoEvento(e))
  })
})

describe('cuánto se mueve este activo', () => {
  it('las cuatro tarjetas, como el mockup', () => {
    const t = tarjetasMovimiento(MOV, { precio, tenencia: { valor: 5300 }, peso: 0.11 })
    expect(t.map(x => x.id)).toEqual(['caida', 'desde_maximo', 'dia', 'cartera'])
    expect(t[0].veredicto).toBe('−33,9%')
    expect(t[0].texto).toBe('De US$ 274 el 10/02/25 a US$ 181 el 21/04/25. Desde ese piso tardó 7 meses (148 días de mercado) en volver a US$ 274.')
    expect(t[1].veredicto).toBe('−16,6%')
    expect(t[2].veredicto).toBe('±1,6%')
    expect(t[2].texto).toContain('este activo se mueve 1,8 veces lo que el S&P 500')
    expect(t[2].texto).toContain('1 de cada 6 días de mercado')
    // 5.300 × 1,6 % = 84,8 → −US$ 85; a la cartera: 11 % × 1,6 % = 0,18 %.
    expect(t[3].veredicto).toBe('−US$ 85')
    expect(t[3].texto).toContain('Es el 11% de tu cartera: ese día, tu cartera completa cambiaría −0,2%.')
  })
  it('todavía no volvió', () => {
    const t = tarjetasMovimiento({ ...MOV, peor_caida: { ...MOV.peor_caida, volvio: null, dias_para_volver: null } }, { precio })
    expect(t[0].texto).toMatch(/Todavía no volvió a US\$ 274\.$/)
  })
  it('sin tenencia no hay tarjeta de tu cartera; sin foto, sin el %', () => {
    expect(tarjetasMovimiento(MOV, { precio }).map(x => x.id)).not.toContain('cartera')
    const t = tarjetasMovimiento(MOV, { precio, tenencia: { valor: 1000 }, peso: null })
    expect(t.find(x => x.id === 'cartera').texto).not.toContain('de tu cartera')
  })
  it('en pesos el S&P se dice en pesos', () => {
    const t = tarjetasMovimiento(MOV, { moneda: 'ars', precio, tenencia: { valor: 1e6 } })
    expect(t[2].texto).toContain('se mueve ±0,9% en pesos')
    expect(t[3].veredicto).toBe('−$ 16.000')
  })
  it('sin datos, nada', () => {
    expect(tarjetasMovimiento({ disponible: false })).toEqual([])
    expect(tarjetasMovimiento(undefined)).toEqual([])
  })
})

describe('lo declarado contra lo esperado, y el detalle del dividendo (Nico, 29/10)', () => {
  it('la ganancia por acción en palabras: más, menos, igual, pérdida, o lo que se sepa', () => {
    const b = (x) => textoGananciaPorAccion({ moneda: 'usd', ...x })
    expect(b({ eps_esperado: 1.5, eps_declarado: 1.65, sorpresa_pct: 10 }))
      .toBe('Declaró una ganancia de US$ 1,65 por acción; se esperaba US$ 1,50: 10% más de lo esperado.')
    expect(b({ eps_esperado: 2, eps_declarado: 1.8, sorpresa_pct: -10 })).toContain('10% menos de lo esperado')
    expect(b({ eps_esperado: 2, eps_declarado: 2.004, sorpresa_pct: 0.2 })).toContain('lo mismo que se esperaba')
    expect(b({ eps_esperado: -0.1, eps_declarado: -0.12, sorpresa_pct: -20 }))
      .toBe('Declaró una pérdida de US$ 0,12 por acción; se esperaba US$ 0,10 de pérdida: 20% menos de lo esperado.')
    expect(b({ eps_esperado: 1.5 })).toBe('Se esperaba una ganancia de US$ 1,50 por acción.')
    expect(textoGananciaPorAccion({ moneda: 'ars', eps_declarado: 120 })).toBe('Declaró una ganancia de $ 120,00 por acción.')
    expect(b({})).toBeNull()
  })

  it('el dividendo: qué parte del precio fue y cómo se compara con el anterior', () => {
    const d = (x) => textoEvento({ tipo: 'dividendo', fecha: '2026-05-13', monto: 0.26, moneda: 'usd', ...x }).lineas
    expect(d({ rendimiento: 0.412, anterior: 0.24 })).toEqual([
      'Pagó US$ 0,26 por acción: el 0,41% de lo que valía la acción ese día.',
      'El anterior: US$ 0,24 (este es 8,3% más).',
      'Quien compra desde el día de corte ya no cobra este dividendo.',
    ])
    expect(d({ anterior: 0.26 })[1]).toBe('Igual que el anterior (US$ 0,26).')
    expect(d({})[0]).toBe('Pagó US$ 0,26 por acción.')            // sin precio en su moneda: no se mezcla
  })
})
