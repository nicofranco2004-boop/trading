import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// Todo lo que GUARDA un valor calculado con precios (la foto diaria, el P&L
// no realizado del mes) tiene que pasar por la misma regla de cobertura
// (coberturaDePrecios ≥ COBERTURA_MINIMA, utils/valuation). El resumen mensual
// guardaba P&L 0 con /prices caído mientras el Dashboard, el otro escritor del
// mismo campo, sí lo chequeaba: ganaba el último que guardara (2026-10-02).
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const ESCRITURAS = [/['"`]\/monthly\/sync-unrealized['"`]/, /api\.post\(\s*['"`]\/snapshots['"`]/]

function archivos(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.jsx?$/.test(n) && !/\.test\./.test(n) && n !== 'demo.js' ? [p] : []
  })
}

describe('quien guarda valores con precios chequea la cobertura', () => {
  const escritores = archivos(SRC).filter((f) => ESCRITURAS.some((re) => re.test(readFileSync(f, 'utf8'))))
  it('hay escritores (si no, el guard no mira nada)', () => {
    expect(escritores.length).toBeGreaterThanOrEqual(2)
  })
  it('cada uno usa coberturaDePrecios y COBERTURA_MINIMA', () => {
    const sinGuard = escritores
      .filter((f) => { const t = readFileSync(f, 'utf8'); return !/coberturaDePrecios\(/.test(t) || !/COBERTURA_MINIMA/.test(t) })
      .map((f) => f.slice(SRC.length + 1))
    expect(sinGuard).toEqual([])
  })
})
