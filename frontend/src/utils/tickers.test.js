// Las listas de tickers son un ALLOWLIST DURO: si un papel no está acá, no se
// puede cargar ni buscar. Por eso se tocan seguido, a mano, y por eso se
// ensucian.
//
// Lo que pasó el 2026-08-11: SNDK se agregó dos veces el mismo día —una en un
// commit suelto y otra en el barrido de BYMA— y quedó DUPLICADO en
// CEDEARS_LIST. El usuario lo vio en el buscador: la misma acción dos veces
// seguidas, con dos logos distintos. Nada lo frenó porque no había test.
//
// Estas guardas son baratas y cubren las tres formas de ensuciar una lista:
// duplicar, dejar un ticker sin nombre, y meter el símbolo con formato raro.
import { describe, it, expect } from 'vitest'
import {
  CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST,
  ARG_LIDER, ARG_GENERAL, CEDEAR_SEARCH,
} from './tickers'

const LISTAS = {
  CRYPTO, STOCKS_US, ETFS, INDICES, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL,
}

describe('listas de tickers — sin duplicados', () => {
  for (const [nombre, lista] of Object.entries(LISTAS)) {
    it(`${nombre} no repite ningún símbolo`, () => {
      const vistos = new Map()
      const repetidos = []
      for (const x of lista) {
        if (vistos.has(x.s)) repetidos.push(`${x.s} ("${vistos.get(x.s)}" y "${x.n}")`)
        else vistos.set(x.s, x.n)
      }
      expect(repetidos, `${nombre} tiene símbolos repetidos — se ven dos veces en el buscador`)
        .toEqual([])
    })
  }
})

describe('listas de tickers — entradas bien formadas', () => {
  for (const [nombre, lista] of Object.entries(LISTAS)) {
    it(`${nombre}: todas tienen símbolo y nombre`, () => {
      const rotas = lista.filter(x => !x?.s?.trim() || !x?.n?.trim())
      expect(rotas, `${nombre} tiene entradas sin s/n`).toEqual([])
    })

    it(`${nombre}: los símbolos vienen limpios (sin espacios ni minúsculas)`, () => {
      // Un símbolo con espacio o en minúscula no matchea contra el precio ni
      // contra lo que trae el importador, así que el activo queda mudo.
      const sucios = lista.map(x => x.s).filter(s => s !== s.trim().toUpperCase())
      expect(sucios).toEqual([])
    })
  }
})

describe('los CEDEARs que pidieron los usuarios están', () => {
  const simbolos = new Set(CEDEARS_LIST.map(x => x.s))

  // Cada uno acá es un reporte real. Si alguien los borra sin querer, el test
  // dice de quién era el pedido.
  it.each([
    ['CEG', 'no podía cargar una compra en Balanz'],
    ['SNDK', 'reportado el 2026-08-11'],
    ['NOW', 'ServiceNow — pedido el 2026-08-11'],
    ['ASML', 'ASML Holding — pedido el 2026-08-11, daba "Sin resultados"'],
  ])('%s está en CEDEARS_LIST (%s)', (sym) => {
    expect(simbolos.has(sym)).toBe(true)
  })
})

describe('CEDEAR_SEARCH — lo que alimenta el buscador', () => {
  it('deriva de CEDEARS_LIST sin perder ni duplicar nada', () => {
    expect(CEDEAR_SEARCH).toHaveLength(CEDEARS_LIST.length)
    const symbols = CEDEAR_SEARCH.map(x => x.symbol)
    expect(new Set(symbols).size).toBe(CEDEAR_SEARCH.length)
    // y con el sufijo .BA, que es como cotiza en BYMA
    expect(symbols.every(s => s.endsWith('.BA'))).toBe(true)
  })

  it('los CEDEARs recién agregados son buscables', () => {
    // El fix de julio: estar en CEDEARS_LIST no alcanzaba, el buscador tenía su
    // propia fuente. Esto verifica que sigan enganchados.
    const symbols = new Set(CEDEAR_SEARCH.map(x => x.symbol))
    for (const sym of ['NOW', 'ASML']) expect(symbols.has(`${sym}.BA`)).toBe(true)
  })
})
