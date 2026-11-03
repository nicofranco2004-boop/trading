// La «Var. día» de un lote cuyo precio la Cartera DESCARTA (trustMktValue: un
// bono con el costo cargado en otra escala que el precio). La fila lo muestra al
// costo; la columna de al lado publicaba igual el movimiento de ese precio
// (sesión del mapa de calor, 30/10: AL30 «valía» USD 89 al costo y «se movía»
// −USD 217). El celular ya lo cortaba (`priceTrusted`). Se monta la Cartera
// entera con la cuenta del demo más un GD30 a 100.000 (cerró ayer en 102.000:
// −1,96 %) con un costo de $890.
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { prepararApp, dibujar } from '../testing/pantallaConOjito'

vi.mock('../utils/demo', async (io) => {
  const orig = await io()
  const BONO = { id: 9102, broker: 'Cocos', asset: 'GD30', asset_type: 'BOND', is_cash: 0, buy_price: 89,
    quantity: 10, invested: 890, entry_date: '2025-01-02', commissions: 0, tc_compra: 1100, price_override: null }
  const HOY = { 'GD30.BA': 100000 }
  const AYER = { 'GD30.BA': 102000 }
  const pedidos = (p) => decodeURIComponent((p.split('?')[1] || '').match(/symbols=([^&]+)/)?.[1] || '').split(',')
  const agregar = (r, p, tabla) => ({ ...r, ...Object.fromEntries(pedidos(p).filter(s => s in tabla).map(s => [s, tabla[s]])) })
  return {
    ...orig,
    handleDemoRequest: (m, p, b) => {
      const r = orig.handleDemoRequest(m, p, b)
      if (m !== 'GET') return r
      const base = p.split('?')[0]
      if (base === '/positions') return [...r, BONO]
      if (base === '/prices') return agregar(r, p, HOY)
      if (base === '/prices/prev-close') return agregar(r, p, AYER)
      return r
    },
  }
})
vi.mock('../components/ai/mervalle/motor', async (io) => ({
  ...(await io()), crearMervallE: () => new Proxy({}, { get: () => () => {} }),
}))

const filaDe = (t, activo) => {
  const i = t.indexOf(` ${activo} `)
  return i < 0 ? '' : t.slice(i, i + 420)
}

describe('Var. día de un precio que la Cartera descarta', () => {
  for (const [ancho, moneda] of [[1280, 'ARS'], [1280, 'USD'], [375, 'ARS']]) {
    describe(`${ancho} px, en ${moneda}`, () => {
      beforeAll(async () => { await prepararApp({ ancho }) }, 120000)
      it('la fila al costo no publica el movimiento de ese precio (−1,96 %)', async () => {
        let fila = ''
        for (let i = 0; i < 3 && !fila; i++) {
          fila = filaDe(await dibujar('/posiciones', { ojito: false, local: { rendi_display_currency: moneda } }), 'GD30')
        }
        expect(fila, 'no encontré la fila de GD30').not.toBe('')
        expect(fila).not.toMatch(/1,96|2,0\s?%|2\.000|20\.000|14,0|13,9/)
      }, 60000)
    })
  }
})
