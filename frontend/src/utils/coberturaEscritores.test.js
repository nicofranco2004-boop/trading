import { describe, it, expect, vi } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { sePuedeGuardar, guardarPnlNoRealizado } from './guardarValuacion'

// Todo lo que GUARDA un valor calculado con precios (la foto diaria, el P&L no
// realizado del mes) pasa por la misma regla: al MEP y con cobertura de precios
// (utils/guardarValuacion). El resumen mensual guardaba P&L 0 con /prices caído
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
  it('al MEP y con ≥ 95 % del costo con precio; si no, no', () => {
    expect(sePuedeGuardar({ cobertura: 1, valuationDollar: 'mep' })).toBe(true)
    expect(sePuedeGuardar({ cobertura: 0.95, valuationDollar: 'mep' })).toBe(true)
    expect(sePuedeGuardar({ cobertura: 0.94, valuationDollar: 'mep' })).toBe(false)
    expect(sePuedeGuardar({ cobertura: 1, valuationDollar: 'ccl' })).toBe(false)
    expect(sePuedeGuardar({ cobertura: NaN, valuationDollar: 'mep' })).toBe(false)
  })
  it('guardarPnlNoRealizado escribe cada fila sólo si se puede', async () => {
    const post = vi.fn(() => Promise.resolve({}))
    const filas = [{ broker: 'Cocos', pnl: 12.345678 }, { broker: 'global', pnl: 12.345678 }]
    expect(await guardarPnlNoRealizado(post, filas, { cobertura: 0.5, valuationDollar: 'mep' })).toBe(false)
    expect(await guardarPnlNoRealizado(post, filas, { cobertura: 1, valuationDollar: 'ccl' })).toBe(false)
    expect(post).not.toHaveBeenCalled()
    expect(await guardarPnlNoRealizado(post, filas, { cobertura: 1, valuationDollar: 'mep' })).toBe(true)
    expect(post).toHaveBeenCalledWith('/monthly/sync-unrealized', { broker: 'global', pnl_unrealized_usd: 12.3457 })
    expect(post).toHaveBeenCalledTimes(2)
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
  it('la foto diaria (POST /snapshots) sale sólo con sePuedeGuardar', () => {
    const fotos = todos.filter((f) => /api\.post\(\s*['"`]\/snapshots['"`]/.test(readFileSync(f, 'utf8')))
    expect(fotos.map(corto)).toEqual(['pages/Dashboard.jsx'])
    for (const f of fotos) {
      const t = readFileSync(f, 'utf8')
      const post = t.search(/api\.post\(\s*['"`]\/snapshots['"`]/)
      // La regla, en el mismo efecto y antes del POST (a menos de 30 líneas).
      const antes = t.slice(0, post).split('\n').slice(-30).join('\n')
      expect(antes).toMatch(/sePuedeGuardar\(/)
    }
  })
})
