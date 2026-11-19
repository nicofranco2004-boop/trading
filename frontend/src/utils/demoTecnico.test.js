/**
 * La cuenta de ejemplo que el demo le manda a la puerta del demo del servidor
 * (utils/demo.js `contextoTecnicoDelDemo`; backend/main.py `DemoContextoIn`).
 *
 * Lo que se fija:
 *   · GGAL e YPFD de Cocos van como acción argentina aunque el registro de
 *     brokers de utils/valuation esté vacío. Lo está al entrar al demo, hasta que
 *     la Cartera o el inicio lo llenan: entrando directo al técnico salían «de
 *     Nueva York» (revisión a ciegas, 19/11), y el servidor leía el ADR de GGAL
 *     sin estirar, con otro % de tu plata que después de pasar por el inicio;
 *   · la lista del gráfico (GET /watchlist/cartera) dice lo mismo: es la misma regla;
 *   · lo que se manda entra en lo que acepta el servidor (si no, 422 y el
 *     técnico del demo con un error): símbolos, cantidades y topes.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { contextoTecnicoDelDemo, handleDemoRequest } from './demo'
import { setBrokersRegistry } from './valuation'

const PY = readFileSync(join(__dirname, '../../../backend/main.py'), 'utf8')
const tope = (nombre) => Number(PY.match(new RegExp(`^${nombre} = (\\d+)`, 'm'))[1])
const SIMBOLO = new RegExp(PY.match(/^_SYMBOL_RE = re\.compile\(r'(.+)'\)$/m)[1])

describe('la cuenta de ejemplo del técnico del demo', () => {
  it('GGAL e YPFD son acción argentina con el registro de brokers vacío', () => {
    setBrokersRegistry([])
    const { tenencias } = contextoTecnicoDelDemo().cartera
    const local = Object.fromEntries(tenencias.map(t => [`${t.asset}|${t.local}`, true]))
    expect(local['GGAL|true']).toBe(true)
    expect(local['YPFD|true']).toBe(true)
    expect(local['NVDA|false']).toBe(true)
    // El CEDEAR de Cocos no es acción argentina: se lee por AAPL de afuera.
    expect(tenencias.filter(t => t.asset === 'AAPL').every(t => t.local === false)).toBe(true)
    const lista = handleDemoRequest('GET', '/watchlist/cartera')
    const ggal = (Array.isArray(lista) ? lista : lista.items || lista.cartera || []).find(x => x.symbol === 'GGAL')
    expect(ggal?.local).toBe(true)
  })

  it('entra en lo que acepta el servidor', () => {
    const c = contextoTecnicoDelDemo()
    expect(Object.keys(c.precios).length).toBeLessThanOrEqual(tope('DEMO_MAX_PRECIOS'))
    expect(c.cartera.tenencias.length).toBeLessThanOrEqual(tope('DEMO_MAX_TENENCIAS'))
    expect(c.watchlist.length).toBeLessThanOrEqual(tope('DEMO_MAX_SEGUIDOS'))
    for (const [s, p] of Object.entries(c.precios)) {
      expect(SIMBOLO.test(s), s).toBe(true)
      expect(p > 0 && p <= 1e9, s).toBe(true)
    }
    for (const t of c.cartera.tenencias) {
      expect(t.valor > 0 && t.valor <= 1e10, t.asset).toBe(true)
      expect(t.asset.length).toBeLessThanOrEqual(40)
    }
    expect(c.cartera.efectivo).toBeGreaterThan(0)
  })
})
