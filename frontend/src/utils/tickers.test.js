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
  ARG_LIDER, ARG_GENERAL, CEDEAR_SEARCH, CEDEAR_EN_EEUU, cedearEspecieBase,
  POPULAR_TICKERS, catalogoDelBuscador, universoDelBuscador,
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
    ['MUX', 'McEwen — pedido el 2026-08-11'],
  ])('%s está en CEDEARS_LIST (%s)', (sym) => {
    expect(simbolos.has(sym)).toBe(true)
  })
})

describe('cada CEDEAR tiene también su acción de EE.UU.', () => {
  // 2026-10-19: IREN estaba como CEDEAR y no como acción, igual que otros 42
  // del barrido de BYMA del 2026-08-11. Quien la tenía en un broker del
  // exterior no la encontraba. Los ETF van aparte (ETFS / "(CEDEAR)" en el nombre).
  const us = new Set([...STOCKS_US, ...ETFS].map(x => x.s))

  it('ningún CEDEAR de empresa queda sin su acción', () => {
    const faltan = CEDEARS_LIST
      .filter(x => !/\(CEDEAR\)/.test(x.n))
      .map(x => CEDEAR_EN_EEUU[cedearEspecieBase(x.s)] || cedearEspecieBase(x.s))
      .filter(s => !us.has(s))
    expect(faltan, 'agregalos a STOCKS_US (y a ai/trade_tickers.US_TICKERS)').toEqual([])
  })

  it('IREN está como acción (pedido del 2026-10-19)', () => {
    expect(us.has('IREN')).toBe(true)
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

describe('el catálogo de los buscadores que suman a la watchlist (inicio y «Tu lista»)', () => {
  const simbolos = (q) => catalogoDelBuscador(q).map(t => t.symbol)

  it('sin consulta, los populares', () => {
    expect(catalogoDelBuscador('')).toBe(POPULAR_TICKERS)
  })

  it('con consulta, también lo que no es popular: todo CEDEAR, acción argentina y de EE.UU.', () => {
    const fuera = (s) => !POPULAR_TICKERS.some(p => p.symbol === s)
    const cedear = CEDEAR_SEARCH.find(c => fuera(c.symbol))
    const ar = [...ARG_LIDER, ...ARG_GENERAL].find(x => fuera(x.s))
    const etf = ETFS.find(x => fuera(x.s))
    expect(simbolos(cedear.symbol)).toContain(cedear.symbol)
    expect(simbolos(ar.s)).toContain(ar.s)
    expect(simbolos(etf.s)).toContain(etf.s)
  })

  it('nadie más lo arma a mano', async () => {
    // Estaba copiado en el buscador del inicio y en la lupa del celular; el de
    // «Tu lista» habría sido la tercera copia.
    const { readdirSync, readFileSync, statSync } = await import('node:fs')
    const { join } = await import('node:path')
    const raiz = new URL('../', import.meta.url).pathname
    const fuera = []
    const recorrer = (d) => {
      for (const n of readdirSync(d)) {
        const p = join(d, n)
        if (statSync(p).isDirectory()) { recorrer(p); continue }
        if (!/\.(js|jsx)$/.test(n) || /\.test\./.test(n) || p.endsWith('utils/tickers.js')) continue
        if (/CEDEAR_SEARCH|AR_STOCK_SEARCH|US_SEARCH/.test(readFileSync(p, 'utf8'))) fuera.push(p.slice(raiz.length))
      }
    }
    recorrer(raiz)
    expect(fuera).toEqual([])
  })

  it('el ticker exacto va primero (Enter suma el primero)', () => {
    // «T» (AT&T) quedaba en el puesto 193 detrás de MSFT (revisión del 02/11).
    for (const t of ['T', 'V', 'MA', 'F', 'C', 'KO']) {
      if (!universoDelBuscador(true).some(x => x.symbol === t)) continue
      expect(simbolos(t)[0], t).toBe(t)
    }
    expect(simbolos('T')[0]).toBe('T')
  })

  it('por el nombre y sin repetir', () => {
    expect(simbolos('coca')).toContain('KO')
    const s = simbolos('A')
    expect(new Set(s).size).toBe(s.length)
  })
})
