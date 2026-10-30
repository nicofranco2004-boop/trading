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

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const AVISO = /no es una recomendaci[oó]n|\{NO_ES_RECOMENDACION\}|\{ACLARACION_DIARIO\}|\{t\.pie\}/

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
})
