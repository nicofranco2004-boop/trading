// El aviso «no es una recomendación» (y sus parientes: los pies de Fibonacci y
// Elliott, la aclaración del diario) se lee: va en `text-ink-2`, el gris de los
// rótulos (≈ 6,8 a 1 en claro), no en `text-ink-3`, el de «pistas, deshabilitado»
// (index.css), que con letra de 12 px daba 4,0 a 1 en claro (el mínimo es 4,5).
//
// POR QUÉ ESTE TEST (auditoría D12 y su re-test, 29/10)
// ─────────────────────────────────────────────────────
// La primera versión miraba una LISTA de seis archivos y se arregló aviso por
// aviso: el del Resumen del mercado (ResumenMercado.jsx) y la aclaración del
// diario quedaron con el gris viejo. Ahora recorre TODA la app: cualquier
// renglón con el aviso (o sus constantes), y los dos renglones de arriba (donde
// suele estar la etiqueta con la clase), no pueden usar `text-ink-3`.
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { P } from '../pages/ReportPublic'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
// Ronda 2 del re-test D: la frase literal no alcanzaba; «no es asesoramiento
// financiero» (el chat de Mervall-E) y «recomendación de inversión» (el informe)
// son el mismo aviso con otras palabras.
const AVISO = /no es una recomendaci[oó]n|no es asesoramiento|recomendaci[oó]n de inversi[oó]n|\{NO_ES_RECOMENDACION\}|\{ACLARACION_DIARIO\}|\{t\.pie\}/

function archivos(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const r = path.join(dir, e.name)
    if (e.isDirectory()) return ['__guards__', 'testing'].includes(e.name) ? [] : archivos(r)
    return /\.jsx$/.test(e.name) && !/\.test\./.test(e.name) ? [r] : []
  })
}

describe('el aviso «no es una recomendación» se lee, en toda la app', () => {
  const avisos = archivos(SRC).flatMap((r) => {
    const l = fs.readFileSync(r, 'utf8').split('\n')
    return l.flatMap((x, i) => (AVISO.test(x) && !/^\s*(\/\/|\*|\{\/\*)/.test(x)
      ? [{ donde: `${path.relative(SRC, r)}:${i + 1}`, bloque: l.slice(Math.max(0, i - 2), i + 1).join('\n') }] : []))
  })

  it('el recorrido encuentra los avisos conocidos (contra el falso verde)', () => {
    const donde = avisos.map((a) => a.donde.split(':')[0])
    for (const f of ['pages/AnalisisTecnico.jsx', 'components/TusSenales.jsx', 'pages/ResumenMercado.jsx',
      'components/asset/CapaFibonacci.jsx', 'components/operations/DiarioResumen.jsx']) {
      expect(donde, f).toContain(f)
    }
  })

  it('ninguno está en el gris de «pistas, deshabilitado»', () => {
    const grises = avisos.filter((a) => /text-ink-3/.test(a.bloque)).map((a) => a.donde)
    expect(grises, 'usá text-ink-2').toEqual([])
  })

  it('el informe (papel claro fijo, ReportPublic / ReporteCartera): su gris chico llega a 4,5 a 1', () => {
    // Sus avisos usan P.ink3 por estilo, no por clase: se mide el color.
    const lum = (h) => {
      const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
        .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    }
    const contraste = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05)
    for (const fondo of [P.paper, P.paper2]) expect(contraste(P.ink3, fondo), fondo).toBeGreaterThanOrEqual(4.5)
  })
})
