import { describe, it, expect } from 'vitest'
import {
  duracion, medicion, pctConSigno, plata, primeraCompra, puntosDesde, tarjetasMovimiento,
  textoEvento, textoGrupo, textoMedicion, ultimaFotoApta,
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
  it('el % y los días de mercado, toque en cualquier orden', () => {
    const m = medicion(p, '2025-03-06', '2025-03-03')
    expect(m.desde).toBe('2025-03-03')
    expect(m.dias).toBe(3)
    expect(m.pct).toBeCloseTo(21, 9)
    expect(textoMedicion(m)).toBe('+21,0% en 3 días de mercado')
    expect(textoMedicion(medicion(p, '2025-03-04', '2025-03-05'))).toBe('−10,0% en 1 día de mercado')
  })
  it('sin los dos toques no hay medición', () => {
    expect(medicion(p, '2025-03-03', null)).toBeNull()
    expect(medicion(p, '2025-03-03', '2030-01-01')).toBeNull()
  })
})

describe('globos de balances y dividendos', () => {
  it('balance presentado con el mercado cerrado', () => {
    const t = textoEvento({ tipo: 'balance', fecha: '2025-07-31', momento: 'despues_del_cierre',
      reaccion: { pct: -4.21, cuando: 'al_otro_dia' } })
    expect(t.titulo).toBe('Balance del 31/07/25')
    expect(t.lineas).toEqual(['Lo presentó con el mercado ya cerrado.', 'Al otro día el precio: −4,2%'])
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
      'Por acción. Desde el día de corte, el que compra ya no cobra ese pago.'])
  })
  it('balances juntos dicen cuándo se midió cada uno; uno solo, el globo de siempre', () => {
    const t = textoGrupo([
      { tipo: 'balance', fecha: '2026-05-13', momento: 'despues_del_cierre', reaccion: { pct: -0.25 } },
      { tipo: 'balance', fecha: '2026-05-20', momento: 'antes_del_cierre', reaccion: { pct: 1.7 } },
    ])
    expect(t.lineas).toEqual(['13/05/26: al otro día −0,3%', '20/05/26: ese día +1,7%'])
    const e = { tipo: 'balance', fecha: '2026-05-13', momento: null, reaccion: { pct: 2 } }
    expect(textoGrupo([e])).toEqual(textoEvento(e))
  })
})

describe('cuánto se mueve este papel', () => {
  it('las cuatro tarjetas, como el mockup', () => {
    const t = tarjetasMovimiento(MOV, { precio, tenencia: { valor: 5300 }, peso: 0.11 })
    expect(t.map(x => x.id)).toEqual(['caida', 'desde_maximo', 'dia', 'cartera'])
    expect(t[0].veredicto).toBe('−33,9%')
    expect(t[0].texto).toBe('De US$ 274 el 10/02/25 a US$ 181 el 21/04/25. Desde ese piso tardó 7 meses (148 días de mercado) en volver a US$ 274.')
    expect(t[1].veredicto).toBe('−16,6%')
    expect(t[2].veredicto).toBe('±1,6%')
    expect(t[2].texto).toContain('este papel se mueve 1,8 veces lo que el S&P 500')
    expect(t[2].texto).toContain('1 de cada 6 días de mercado')
    // 5.300 × 1,6 % = 84,8 → −US$ 85; a la cartera: 11 % × 1,6 % = 0,18 %.
    expect(t[3].veredicto).toBe('−US$ 85')
    expect(t[3].texto).toContain('Es el 11% de tu cartera: a toda tu cartera ese día la mueve −0,2%.')
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

describe('ultimaFotoApta', () => {
  it('la última que sirve como medición', () => {
    const fotos = [{ date: '2026-10-20', apto: 1, total_value: 10 }, { date: '2026-10-21', apto: 1, total_value: 20 },
      { date: '2026-10-22', apto: 0, total_value: 30 }]
    expect(ultimaFotoApta(fotos).total_value).toBe(20)
    expect(ultimaFotoApta([...fotos].reverse()).total_value).toBe(20)   // el demo las manda al revés
    expect(ultimaFotoApta([])).toBeNull()
  })
})
