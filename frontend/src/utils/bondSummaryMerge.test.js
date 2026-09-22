// Las cobranzas del bono que vive en las DOS patas de una cuenta.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Medido en la app el 2026-09-22, con una cuenta unificada (pata pesos + pata
// dólar) y el MISMO bono en las dos, tres cupones ya cobrados y acreditados:
//   • unificada:  GD30  +USD 9.201,85
//   • separada:   GD30  +USD 6.572,31  y  +USD 3.927,81  →  +USD 10.500,12
// El mismo bono, el mismo día, a un click de distancia, con US$1.298 de
// diferencia: los cupones. La fila fusionada buscaba la clave "null:GD30"
// —porque `_buildAgg` le pone `broker: null` a propósito— no encontraba nada,
// y además afirmaba "Aún no registraste cobranzas" con la plata ya cobrada.
//
// Lo que se protege acá es que la fila de dos patas vea las cobranzas de las
// DOS, y que lo que se suma entre patas esté en la misma unidad.
import { describe, it, expect } from 'vitest'
import { mergeBondSummaries, bondSummaryDeLaFila } from './bondSummaryMerge.js'

const patar = (over = {}) => ({
  ops: [{ id: 1 }],
  coupons: 10, amortizations: 100, total: 110,
  couponsUsd: 10, amortizationsUsd: 100, totalUsd: 110,
  pnlContribution: 10, pnlContributionUsd: 10,
  usdByOpId: new Map([[1, 110]]),
  hasLegacyOps: false, currency: 'USD',
  ...over,
})

describe('una fila que junta las dos patas ve las cobranzas de las dos', () => {
  it('suma lo que está en USD, que es aditivo entre patas', () => {
    const m = mergeBondSummaries([patar(), patar({ ops: [{ id: 2 }], couponsUsd: 5, totalUsd: 55, amortizationsUsd: 50, pnlContributionUsd: 5, usdByOpId: new Map([[2, 55]]) })])
    expect(m.couponsUsd).toBe(15)
    expect(m.totalUsd).toBe(165)
    expect(m.pnlContributionUsd).toBe(15)   // ← los US$1.298 que se perdían
    expect(m.ops).toHaveLength(2)
    expect(m.usdByOpId.size).toBe(2)
  })

  it('NO suma pesos con dólares: el aporte nativo queda en null si las patas difieren', () => {
    const m = mergeBondSummaries([patar({ currency: 'ARS' }), patar({ currency: 'USD' })])
    expect(m.pnlContribution).toBeNull()
    expect(m.total).toBeNull()
    expect(m.currency).toBeNull()
    // el de USD sí, porque ahí las dos hablan la misma unidad
    expect(m.pnlContributionUsd).toBe(20)
  })

  it('con las dos patas en la misma moneda, el nativo también suma', () => {
    const m = mergeBondSummaries([patar({ currency: 'USD' }), patar({ currency: 'USD' })])
    expect(m.pnlContribution).toBe(20)
    expect(m.currency).toBe('USD')
  })

  it('marca la fila como de varias patas: registrar un cobro no sabría a cuál', () => {
    expect(mergeBondSummaries([patar(), patar()])._variasPatas).toBe(true)
    // Con una sola pata NO se marca: ahí el registro funciona como siempre.
    expect(mergeBondSummaries([patar()])._variasPatas).toBeUndefined()
  })

  it('sin ninguna cobranza en ninguna pata devuelve null, no un resumen en cero', () => {
    // Un resumen en cero haría que el panel diga "cobraste 0" en vez de
    // "todavía no registraste cobranzas".
    expect(mergeBondSummaries([undefined, undefined])).toBeNull()
    expect(mergeBondSummaries([])).toBeNull()
  })
})

describe('la fila pide su resumen por TODAS sus patas', () => {
  const porClave = new Map([
    ['Cocos:GD30', patar({ pnlContributionUsd: 26 })],
    ['Cocos · USD:GD30', patar({ pnlContributionUsd: 16 })],
  ])

  it('la fila fusionada suma las dos patas', () => {
    const fila = { asset: 'GD30', broker: null, _brokers: ['Cocos', 'Cocos · USD'] }
    expect(bondSummaryDeLaFila(fila, porClave).pnlContributionUsd).toBe(42)
  })

  it('la fila de una sola pata sigue viendo exactamente lo suyo', () => {
    const fila = { asset: 'GD30', broker: 'Cocos', _brokers: ['Cocos'] }
    expect(bondSummaryDeLaFila(fila, porClave).pnlContributionUsd).toBe(26)
  })

  it('una fila vieja sin `_brokers` cae a su broker, como antes', () => {
    const fila = { asset: 'GD30', broker: 'Cocos · USD' }
    expect(bondSummaryDeLaFila(fila, porClave).pnlContributionUsd).toBe(16)
  })

  it('la fila fusionada NUNCA busca la clave "null:activo"', () => {
    // Era exactamente el bug: `${p.broker}:${p.asset}` con broker null.
    const fila = { asset: 'GD30', broker: null, _brokers: ['Cocos', 'Cocos · USD'] }
    expect(bondSummaryDeLaFila(fila, porClave)).not.toBeNull()
    expect(porClave.has('null:GD30')).toBe(false)
  })
})

// ─── Vigilancia del código fuente ────────────────────────────────────────────
// La clave se arma dentro del JSX, así que no se puede importar y probar.
// Mismo patrón que cerBasisProps.test.js / tarjetaBroker.test.js.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('nadie vuelve a armar la clave del bono con un solo broker', () => {
  it('Positions.jsx no usa `${p.broker}:${p.asset}` para las cobranzas', () => {
    const src = readFileSync(join(SRC, 'pages/Positions.jsx'), 'utf8')
    // eslint-disable-next-line no-template-curly-in-string
    expect(src, 'volvió la clave de una sola pata: la fila unificada se come los cupones')
      .not.toMatch(/`\$\{p\.broker\}:\$\{p\.asset\}`/)
  })

  it('las dos tablas, el orden y el desplegable piden el resumen por todas las patas', () => {
    const src = readFileSync(join(SRC, 'pages/Positions.jsx'), 'utf8')
    // TRES: la tabla en pesos, la tabla en dólares… y la clave de ORDEN. El
    // tercero es el que casi se queda afuera: si ordena por un P&L sin cupones
    // mientras la celda muestra uno con cupones, la tabla queda ordenada por un
    // número que no está en la pantalla.
    expect((src.match(/bondSummaryDeLaFila\s*\(/g) || []).length).toBe(3)
    // …y las dos, más toggleBondExpand, arman la clave con todas las patas.
    expect((src.match(/_brokers \|\| \[p\.broker\]/g) || []).length).toBe(3)
  })

  it('el panel no ofrece registrar un cobro cuando la fila junta dos patas', () => {
    const src = readFileSync(join(SRC, 'components/BondDetail.jsx'), 'utf8')
    expect(src, 'volvieron los botones que mandaban broker:null al backend')
      .toMatch(/_variasPatas/)
  })
})
