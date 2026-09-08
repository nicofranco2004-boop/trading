// El SellModal tiene que recibir las cotizaciones históricas en TODOS lados.
//
// POR QUÉ ESTE TEST
// ─────────────────
// `SellModal` vive en Positions.jsx y lo renderizan DOS pantallas: desktop
// (Positions.jsx) y mobile (PositionsMobile.jsx, que lo importa). Desktop le
// pasaba `fxHist`; mobile no.
//
// Sin esa prop, `tcForDate` degrada en silencio al MEP de HOY. Una venta con
// fecha pasada hecha desde el celular se registraba con el dólar equivocado —y
// eso NO es un número mal mostrado: queda escrito en `operations`, con su
// `pnl_usd` y su `fx_to_usd`, para siempre. La auditoría lo midió como hasta un
// 68 % menos de P&L realizado (hallazgo A-8, tanda 1A).
//
// El bug no fue que alguien escribiera mal el fix: el fix estaba bien escrito, en
// un solo call site de dos. Es la causa raíz más frecuente de este repo (28+
// hallazgos auditados) y la razón de la regla de propagación de CLAUDE.md.
//
// CÓMO FUNCIONA
// ─────────────
// No hay jsdom en este proyecto, así que no se puede montar el componente. Se
// verifica sobre el CÓDIGO FUENTE: se buscan todos los `<SellModal` del árbol y
// se exige que cada uno pase `fxHist`. Un renderer nuevo que la olvide falla acá
// aunque nadie se acuerde de este archivo — que es exactamente el caso a cazar.

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

function archivosJsx(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivosJsx(p)
    return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
  })
}

/** Cada `<SellModal ... />` del árbol, con su archivo y su bloque de props. */
function renders() {
  const out = []
  for (const f of archivosJsx(SRC)) {
    const src = readFileSync(f, 'utf8')
    let i = src.indexOf('<SellModal')
    while (i !== -1) {
      // El bloque de props va hasta el cierre de la etiqueta de apertura.
      const fin = src.indexOf('/>', i) === -1
        ? src.indexOf('>', i)
        : Math.min(src.indexOf('/>', i), src.indexOf('>', i) === -1 ? Infinity : src.indexOf('>', i))
      out.push({ archivo: f.slice(SRC.length + 1), props: src.slice(i, fin === -1 ? i + 800 : fin) })
      i = src.indexOf('<SellModal', i + 1)
    }
  }
  return out
}

describe('SellModal — contrato de props', () => {
  it('lo renderiza más de una pantalla (si no, este test sobra)', () => {
    expect(renders().length).toBeGreaterThan(1)
  })

  it('TODOS los renderers pasan fxHist', () => {
    const sinFxHist = renders().filter(r => !/\bfxHist\s*=/.test(r.props))
    expect(sinFxHist.map(r => r.archivo)).toEqual([])
  })

  it('TODOS los renderers pasan tcValuacion', () => {
    const sinTc = renders().filter(r => !/\btcValuacion\s*=/.test(r.props))
    expect(sinTc.map(r => r.archivo)).toEqual([])
  })
})
