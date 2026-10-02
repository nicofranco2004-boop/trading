import { describe, it, expect, vi } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sePuedeGuardar, guardarPnlNoRealizado } from './guardarValuacion'

// Todo lo que GUARDA un valor calculado con precios (la foto diaria, el P&L no
// realizado del mes) pasa por la misma regla de cobertura de precios
// (utils/guardarValuacion) y vive al MEP. El resumen mensual guardaba P&L 0 con /prices caído
// y el Dashboard guardaba P&L al CCL: dos escritores del mismo campo con dos
// reglas, y ganaba el último que guardara (2026-10-02).
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

function archivos(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.jsx?$/.test(n) && !/\.test\./.test(n) && n !== 'demo.js' ? [p] : []
  })
}
const corto = (f) => f.slice(SRC.length + 1)

describe('la regla de lo que se guarda con precios', () => {
  it('con ≥ 95 % del costo con precio; si no, no', () => {
    expect(sePuedeGuardar({ cobertura: 1 })).toBe(true)
    expect(sePuedeGuardar({ cobertura: 0.95 })).toBe(true)
    expect(sePuedeGuardar({ cobertura: 0.94 })).toBe(false)
    expect(sePuedeGuardar({ cobertura: NaN })).toBe(false)
  })
  it('guardarPnlNoRealizado escribe cada fila sólo si se puede, y nunca un número roto', async () => {
    const post = vi.fn(() => Promise.resolve({}))
    const filas = [{ broker: 'Cocos', pnl: 12.345678 }, { broker: 'Roto', pnl: NaN }, { broker: 'global', pnl: 12.345678 }]
    expect(await guardarPnlNoRealizado(post, filas, { cobertura: 0.5 })).toBe(false)
    expect(post).not.toHaveBeenCalled()
    expect(await guardarPnlNoRealizado(post, filas, { cobertura: 1 })).toBe(true)
    expect(post).toHaveBeenCalledWith('/monthly/sync-unrealized', { broker: 'global', pnl_unrealized_usd: 12.3457 })
    expect(post).toHaveBeenCalledTimes(2)   // la fila NaN no se guarda (antes: un 0)
  })
})

describe('nadie guarda por fuera de la regla', () => {
  const todos = archivos(SRC)
  it('el P&L no realizado se escribe SÓLO por guardarPnlNoRealizado', () => {
    const escriben = todos.filter((f) => /['"`]\/monthly\/sync-unrealized['"`]/.test(readFileSync(f, 'utf8'))).map(corto)
    expect(escriben).toEqual(['utils/guardarValuacion.js'])
  })
  it('y sus llamadores son los dos de siempre (si aparece otro, que use la función)', () => {
    const llaman = todos.filter((f) => /guardarPnlNoRealizado\(/.test(readFileSync(f, 'utf8'))).map(corto).filter((f) => f !== 'utils/guardarValuacion.js').sort()
    expect(llaman).toEqual(['components/MonthlySummary.jsx', 'pages/Dashboard.jsx'])
  })
  it('la foto diaria (POST /snapshots) sale sólo al MEP y con sePuedeGuardar', () => {
    const fotos = todos.filter((f) => /api\.post\(\s*['"`]\/snapshots['"`]/.test(readFileSync(f, 'utf8')))
    expect(fotos.map(corto)).toEqual(['pages/Dashboard.jsx'])
    for (const f of fotos) {
      const t = readFileSync(f, 'utf8')
      const post = t.search(/api\.post\(\s*['"`]\/snapshots['"`]/)
      // La regla, en el mismo efecto y antes del POST (a menos de 30 líneas).
      const antes = t.slice(0, post).split('\n').slice(-30).join('\n')
      expect(antes).toMatch(/sePuedeGuardar\(/)
      expect(antes).toMatch(/valuationDollar !== 'mep'/)
    }
  })
})

import { coberturaDePrecios } from './valuation'

describe('los dos escritores pesan la cobertura al MEP', () => {
  it('Dashboard y resumen mensual: coberturaDePrecios con el TC del MEP (en CCL podían discrepar en el 95 %)', () => {
    const dash = readFileSync(join(SRC, 'pages/Dashboard.jsx'), 'utf8')
    const mensual = readFileSync(join(SRC, 'components/MonthlySummary.jsx'), 'utf8')
    expect(dash).toMatch(/coberturaDePrecios\([^)]*tcValuacion: tcMep, tcCedear: tcMep/)
    expect(mensual).toMatch(/coberturaDePrecios\([^)]*tcValuacion: tcMep, tcCedear: tcMep/)
  })
  it('el caso del límite: al MEP no alcanza aunque al CCL sí', () => {
    const brokers = [{ name: 'Cocos', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }]
    const pos = [{ asset: 'GGAL', broker: 'Cocos', invested: 64000 }, { asset: 'AAPL', broker: 'Schwab', invested: 1000 }]
    const precios = { AAPL: 230 }
    expect(coberturaDePrecios(pos, precios, brokers, { tcValuacion: 1200 })).toBeLessThan(0.95)
    expect(coberturaDePrecios(pos, precios, brokers, { tcValuacion: 1240 })).toBeGreaterThan(0.95)
  })
})
