// Las palabras y las cuentas chicas de «Una cartera» (utils/carteraSimulada.js).
// Lo que importa:
//   · el máximo de activos y la tolerancia del 100 son los del servidor
//     (backend/cartera_simulada.py): uno distinto daría un 400;
//   · lo que se dice sale de la respuesta REAL del servidor
//     (backend/tests/fixtures/cartera_simulada.json, que test_cartera_simulada.py
//     compara contra cartera_simulada.simular), no de un caso armado a mano;
//   · cada porcentaje acepta coma, hasta 100; cuánto falta o sobra se dice;
//   · la torta va de la porción más grande a la más chica, con la rampa de las
//     tortas de composición, y lo que falta para 100 al final;
//   · nunca promete ni dice cuál cartera es «mejor».
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import {
  COMO_SE_SIMULA_CARTERA, MAX_ACTIVOS, NOTA_HOY, NOTA_OJITO, NOTA_SIN_ACTIVOS, QUE_SE_SIMULA, TOLERANCIA,
  aLaDireccion, carteraDe, consultaDe, estadoDeLaCartera, filasDeHoy, lecturaCartera, limpiar, loQueFalta,
  modoDe, motivoCartera, notaDeHoy, numeroDe, origenDe, porcionesDeLaTorta, repartirIgual, textoDe, totalDe,
} from './carteraSimulada'
import { porcionColor } from './chartTheme'

const AQUI = dirname(fileURLToPath(import.meta.url))
const CASOS = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/cartera_simulada.json'), 'utf8'))
const PY = readFileSync(resolve(AQUI, '../../../backend/cartera_simulada.py'), 'utf8')
const fila = (asset, txt, local = false) => ({ asset, local, txt })

describe('lo que se acepta es lo del servidor', () => {
  it('el máximo de activos y la tolerancia del 100', () => {
    expect(MAX_ACTIVOS).toBe(Number(PY.match(/^MAX_ACTIVOS = (\d+)/m)[1]))
    expect(TOLERANCIA).toBe(Number(PY.match(/^TOLERANCIA = ([\d.]+)/m)[1]))
  })

  it('el modo y con qué arranca, de la dirección', () => {
    expect([modoDe('cartera'), modoDe('otra'), modoDe(null)]).toEqual(['cartera', 'regla', 'regla'])
    expect([origenDe('cero'), origenDe('hoy'), origenDe(undefined)]).toEqual(['cero', 'hoy', 'hoy'])
  })
})

describe('cada porcentaje', () => {
  it('con coma o punto, y lo vacío es 0', () => {
    expect([numeroDe('33,3'), numeroDe('33.3'), numeroDe(''), numeroDe('x'), numeroDe('-5')]).toEqual([33.3, 33.3, 0, 0, 0])
    expect([textoDe(40), textoDe(33.3), textoDe(33.333), textoDe(0)]).toEqual(['40', '33,3', '33,33', ''])
  })

  it('mientras se escribe: dígitos y una coma, hasta 2 decimales y no más de 100', () => {
    expect(['30', '33,3', '33.3', '33,333', '3,3,3', 'a5', '150', ',5', '007', '100,5'].map(limpiar))
      .toEqual(['30', '33,3', '33,3', '33,33', '3,33', '5', '100', '0,5', '7', '100'])
  })

  it('cuánto falta, cuánto sobra, y que cada uno tenga el suyo', () => {
    expect(estadoDeLaCartera([])).toMatchObject({ listo: false, texto: 'Faltan 100%', aviso: null })
    expect(estadoDeLaCartera([fila('A', '60'), fila('B', '25')])).toMatchObject({
      listo: false, total: 85, totalTxt: '85%', texto: 'Faltan 15%',
      aviso: 'Para ver cómo le habría ido, los porcentajes tienen que sumar 100%: falta repartir 15%.',
    })
    expect(estadoDeLaCartera([fila('A', '60'), fila('B', '45,5')])).toMatchObject({ listo: false, texto: 'Sobran 5,5%' })
    expect(estadoDeLaCartera([fila('A', '33,33'), fila('B', '33,33'), fila('C', '33,34')])).toMatchObject({ listo: true, texto: 'Suma 100%' })
    expect(estadoDeLaCartera([fila('A', '100'), fila('B', '')])).toMatchObject({
      listo: false, aviso: 'B no tiene porcentaje: poné cuánto va, o sacalo.',
    })
    expect(totalDe([fila('A', '33,3'), fila('B', '33,3'), fila('C', '33,4')])).toBe(100)
  })

  it('repartir en partes iguales suma 100, y el que se suma toma lo que falta', () => {
    expect(repartirIgual(3)).toEqual([34, 33, 33])
    for (const n of [1, 2, 6, 7, 10]) expect(repartirIgual(n).reduce((a, b) => a + b, 0)).toBe(100)
    expect(loQueFalta([fila('A', '60')])).toBe(40)
    expect(loQueFalta([fila('A', '60'), fila('B', '50')])).toBe(0)
  })
})

describe('la dirección y el pedido', () => {
  it('ida y vuelta, sin repetir y hasta el máximo', () => {
    const filas = [fila('AAPL', '60'), fila('GGAL', '33,5', true), fila('BTC', '6,5')]
    const d = aLaDireccion(filas)
    expect(d).toEqual({ activos: 'AAPL,GGAL,BTC', pesos: '60,33.5,6.5', local: 'GGAL' })
    expect(carteraDe(new URLSearchParams(d))).toEqual(filas)
    const muchos = Array.from({ length: 12 }, (_, i) => `T${i}`)
    expect(carteraDe(new URLSearchParams({ activos: [...muchos, 'T0'].join(','), pesos: '' }))).toHaveLength(MAX_ACTIVOS)
    expect(carteraDe(new URLSearchParams({ activos: 'aapl, aapl ,ko', pesos: '50,50,50' })))
      .toEqual([fila('AAPL', '50'), fila('KO', '50')])
  })

  it('se pide sólo cuando suma 100 y cada uno tiene el suyo', () => {
    expect(consultaDe([fila('AAPL', '60'), fila('GGAL', '40', true)], 2)).toBe('activos=AAPL,GGAL&pesos=60,40&local=GGAL&anios=2')
    expect(consultaDe([fila('AAPL', '100')], 1)).toBe('activos=AAPL&pesos=100&anios=1')
    expect(consultaDe([fila('AAPL', '60')], 2)).toBeNull()
    expect(consultaDe([], 2)).toBeNull()
  })
})

describe('la torta', () => {
  it('de la más grande a la más chica, con la rampa de composición, y lo que falta al final', () => {
    const p = porcionesDeLaTorta([fila('KO', '10'), fila('AAPL', '50'), fila('GGAL', '25'), fila('X', '')])
    expect(p.map(x => [x.key, x.value, x.pct, x.color])).toEqual([
      ['AAPL', 50, 50, porcionColor(0)], ['GGAL', 25, 25, porcionColor(1)], ['KO', 10, 10, porcionColor(2)],
      ['sin_dato', 15, 15, 'rgb(var(--bg-3))'],
    ])
    expect(p.at(-1).label).toBe('Falta repartir')
  })

  it('pasada de 100, cada porción es su parte del total y no hay hueco', () => {
    const p = porcionesDeLaTorta([fila('A', '80'), fila('B', '40')])
    expect(p.map(x => x.key)).toEqual(['A', 'B'])
    expect(p.map(x => Math.round(x.pct * 100) / 100)).toEqual([66.67, 33.33])
  })
})

describe('mi cartera de hoy', () => {
  it('como filas para editar, y qué quedó afuera', () => {
    const r = { activos: [{ asset: 'AAPL', local: false, peso: 66.7, tipo: 'STOCK' }, { asset: 'GGAL', local: true, peso: 33.3, tipo: 'ACCION' }],
      afuera: [{ asset: 'AL30', tipo: 'BOND', motivo: 'sin_serie' }, { asset: 'FCI:AHORRO', tipo: 'FCI', motivo: 'sin_serie' },
        { asset: 'T11', tipo: 'STOCK', motivo: 'tope' }] }
    expect(filasDeHoy(r)).toEqual([fila('AAPL', '66,7'), fila('GGAL', '33,3', true)])
    expect(notaDeHoy(r)).toBe('Quedaron afuera AL30 y AHORRO: no tienen precio de todos los días. Entran hasta 10 '
      + 'activos: quedó afuera el que menos pesa. El resto se repartió sobre 100%.')
    expect(notaDeHoy({ activos: [], afuera: [] })).toBeNull()
  })
})

describe('lo que dicen los números', () => {
  it('la cartera de las pruebas, al lado del S&P 500 y del Nasdaq', () => {
    const l = lecturaCartera(CASOS.tres)
    expect(l.titulo).toBe('Le fue mejor que el S&P 500, pero no que el Nasdaq')
    expect(l.frases).toEqual([
      'En los últimos 2 años, US$ 100 en esta cartera habrían quedado en US$ 121; en el S&P 500, en US$ 121, y en el Nasdaq, en US$ 129.',
      'El que más sumó fue AAPL, +17,8 puntos, y el que más restó, GGAL, −6,0: entre todos, la cartera dio +21,4%.',
      'Sin tocarla, GGAL pasó de 30% a 19,7% de la cartera.',
      `Su peor caída fue de 20%, contra ${CAIDA(CASOS.tres.indices[0])} del S&P 500 y ${CAIDA(CASOS.tres.indices[1])} del Nasdaq.`,
    ])
  })

  it('sin el Nasdaq lo dice, y compara con el que hay', () => {
    const l = lecturaCartera(CASOS.sin_nasdaq)
    expect(l.titulo).toBe('Le fue mejor que el S&P 500')
    expect(l.frases[0]).toMatch(/habrían quedado en US\$ 121, y en el S&P 500, en US\$ 121\.$/)
    expect(l.frases.at(-1)).toBe('Todavía no tenemos la historia del Nasdaq para compararla.')
  })

  it('si un activo cotiza desde después, dice desde cuándo', () => {
    const l = lecturaCartera(CASOS.recortada)
    expect(l.frases[0]).toMatch(/^Desde el 26\/01\/26, US\$ 100 en esta cartera/)
    expect(l.frases).toContain('NUEVA cotiza desde el 26/01/26: la simulación arranca ese día.')
  })

  it('los títulos dicen contra qué índice, con los números como se ven', () => {
    const t = (c, s, n) => lecturaCartera({ ...CASOS.tres, cartera: { ...CASOS.tres.cartera, resultado: c },
      indices: [{ ...CASOS.tres.indices[0], resultado: s }, { ...CASOS.tres.indices[1], resultado: n }] }).titulo
    expect(t(30, 20, 25)).toBe('Le fue mejor que el S&P 500 y que el Nasdaq')
    expect(t(10, 20, 25)).toBe('El S&P 500 y el Nasdaq le ganaron')
    expect(t(21.41, 21.38, 25)).toBe('Dio casi lo mismo que el S&P 500, y el Nasdaq le ganó')
    expect(t(30, 30.04, 10)).toBe('Le fue mejor que el Nasdaq y dio casi lo mismo que el S&P 500')
    expect(t(20, 20, 20)).toBe('Dio casi lo mismo que el S&P 500 y el Nasdaq')
    const solo = lecturaCartera({ ...CASOS.tres, indices: [], faltan: [] })
    expect(solo.titulo).toBe('Así habría ido esta cartera')
    expect(lecturaCartera(CASOS.vieja)).toBeNull()
  })
})

describe('por qué no se pudo simular', () => {
  it('cada motivo, en una oración entera', () => {
    expect(motivoCartera(CASOS.vieja)).toBe('PARADA no tiene precios desde el 30/09/26: sacalo para simular el resto.')
    expect(motivoCartera({ motivo: 'sin_serie', faltan: [{ asset: 'AL30' }, { asset: 'ZZZ' }] }))
      .toBe('No tenemos los precios de cada día de AL30 y ZZZ: sacalos o cambialos por otro.')
    expect(motivoCartera({ motivo: 'poca_historia', recorte_por: 'NUEVITO', faltan: [] }))
      .toBe('NUEVITO cotiza hace muy poco: con él no alcanzan los días para simular. Sacalo para probar el resto.')
    expect(motivoCartera({ motivo: 'demo' })).toBe('En el modo demo no hay precios de todos los días para simular carteras.')
    expect(motivoCartera({ motivo: 'tope' })).toMatch(/probá de nuevo en un rato/)
  })
})

describe('en el modo demo', () => {
  it('la cartera de hoy se arma sin el bono, y simular dice que no hay precios', async () => {
    const { handleDemoRequest } = await import('./demo')
    const hoy = handleDemoRequest('GET', '/backtest/cartera/hoy')
    expect(hoy.activos.reduce((s, a) => s + a.peso, 0)).toBe(100)
    expect(hoy.activos.length).toBeLessThanOrEqual(MAX_ACTIVOS)
    expect(hoy.afuera).toEqual([{ asset: 'AL30', tipo: 'BOND', motivo: 'sin_serie' }])
    const r = handleDemoRequest('GET', '/backtest/cartera?activos=NVDA&pesos=100&anios=2')
    expect(r).toEqual({ disponible: false, motivo: 'demo' })
    expect(motivoCartera(r)).toBe('En el modo demo no hay precios de todos los días para simular carteras.')
  })
})

describe('nunca promete', () => {
  it('ni «suele», ni «conviene», ni «la mejor cartera», ni consejos', () => {
    const textos = [
      ...Object.values(CASOS).flatMap(r => { const l = lecturaCartera(r); return l ? [l.titulo, ...l.frases] : [motivoCartera(r)] }),
      QUE_SE_SIMULA, NOTA_HOY, NOTA_OJITO, NOTA_SIN_ACTIVOS, COMO_SE_SIMULA_CARTERA,
    ].join(' ')
    expect(textos).not.toMatch(/suele|se viene|comprá|vendé|va a subir|va a bajar|conviene|deber[íi]as|mejor cartera|la mejor\b|te recomend|ayuda|muchas veces|garantiz/i)
  })
})

function CAIDA(i) {
  return `${Math.abs(Math.round(i.peor_caida))}%`
}
