// Un número que dice «hoy» tiene que traer la fecha de la medición (regla del
// repo desde el 15/09: cuatro mails decían «hoy» con el cierre del lunes).
//
// POR QUÉ ESTE TEST
// ─────────────────
// Auditoría D5 (29/10): en la ficha de AAPL, el Fibonacci decía «Hoy está en
// US$ 343,83» (el cierre del 28/10) y, más abajo, el fundamental «hoy $349,25»
// (el precio en vivo): dos «hoy» distintos en la misma página. Lo mismo «Caída
// desde el máximo · Hoy, contra el máximo del año» y la tesis «Hoy está 5,5 %
// arriba». Las tres lecturas salen del último CIERRE guardado, que viaja con su
// fecha (`fecha_hoy` del Fibonacci, `hasta` de «Cuánto se mueve», `fecha` de la
// tendencia de la tesis), pero el texto escribía «hoy» a mano.
//
// Lo que se prueba: (1) cada texto dice la fecha del cierre; (2) ningún texto
// del análisis técnico vuelve a escribir «Hoy está / Hoy cerró / Hoy, contra».
// Los «hoy» del precio EN VIVO (la ficha arriba, «Lo que vale hoy contra lo que
// pagaste») son de hoy de verdad y no entran.
import { describe, it, expect } from 'vitest'
import { ENTRE, archivosConTexto, hallazgos, relativa } from '../../scripts/texto-visible.mjs'
import { tarjetaFibonacci } from '../utils/fibonacci'
import { tarjetasMovimiento } from '../utils/cuantoSeMueve'
import { lineaDeTendencias } from '../components/tesis/TesisDelActivo'

const precio = (x) => `US$ ${x.toLocaleString('es-AR')}`
const fecha = (iso) => iso.split('-').reverse().join('/')

describe('D5 · lo que sale del último cierre dice de qué día es', () => {
  it('Fibonacci: «Al cierre del 28/10/2026 estaba en…»', () => {
    const t = tarjetaFibonacci({
      disponible: true, n_pivote: 3, dir: 'suba',
      desde: { fecha: '2026-05-13', precio: 1495 }, hasta: { fecha: '2026-09-03', precio: 2066 },
      ruptura: { fecha: '2026-09-09', cierre: 1876.33, nivel: 1900, nivel_fecha: '2026-09-01' },
      niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 2066 - n * 571 })),
      precio_hoy: 1854.88, fecha_hoy: '2026-10-28', retroceso_hoy: 0.3697, retroceso_maximo: null, entre: [0.236, 0.382],
    }, precio, fecha)
    expect(t.texto).toContain('Al cierre del 28/10/2026 estaba en US$ 1.854,88')
    expect(t.texto).not.toMatch(/\bHoy\b/)
  })

  it('«Caída desde el máximo»: la fecha del último cierre', () => {
    const m = { disponible: true, hasta: '2026-10-28', peor_caida: null, dia_normal: null,
      desde_el_maximo: { pct: -1.3, maximo: 348.22, anio_completo: true } }
    const c = tarjetasMovimiento(m, { precio }).find(x => x.id === 'desde_maximo')
    // Al juntar con Arreglos A (A5): la caída se mide contra el CIERRE más alto
    // (Fibonacci usa el pico de adentro del día), y lo dice así.
    expect(c.texto).toBe('Al cierre del 28/10/26, contra el cierre más alto del año (US$ 348,22).')
    const enMax = tarjetasMovimiento({ ...m, desde_el_maximo: { pct: 0, maximo: 1, anio_completo: true } }, { precio })
      .find(x => x.id === 'desde_maximo')
    // Al juntar A5 («el cierre más alto») con D5 («El 28/10/26 cerró en…») salía
    // «cerró en el cierre más alto»: la frase dice lo mismo sin repetirse.
    expect(enMax.texto).toBe('El 28/10/26 tuvo el cierre más alto del año.')
    const sinFecha = (x) => tarjetasMovimiento({ ...m, hasta: null, desde_el_maximo: x }, { precio })
      .find(c => c.id === 'desde_maximo').texto
    expect(sinFecha({ pct: 0, maximo: 1, anio_completo: true })).toBe('Su último cierre fue el más alto del año.')
    expect(sinFecha({ pct: 0, maximo: 1, anio_completo: false })).toBe('Su último cierre fue el más alto del período.')
    for (const x of [enMax.texto, sinFecha({ pct: 0, maximo: 1, anio_completo: true })]) {
      expect(x).not.toMatch(/cierr\w* .*cierre más alto/)
    }
  })

  it('la tesis: «Al cierre del 28/10/26 estaba 8,1 % abajo»', () => {
    const t = lineaDeTendencias({ tendencia: 'alcista' }, { tendencia: 'bajista', dist: -8.1, fecha: '2026-10-28' })
    expect(t).toContain('Al cierre del 28/10/26 estaba 8,1 % abajo de su promedio de 200 días: bajista.')
    expect(t).not.toMatch(/\bHoy\b/)
  })

  it('ningún texto del análisis técnico escribe «Hoy está», «Hoy cerró» ni «Hoy, contra»', () => {
    const NO = [new RegExp(String.raw`\bhoy,?${ENTRE}(?:est[aá]|cerr[oó]|contra)(?![\wáéíóú])`, 'gi')]
    const TECNICO = /^src\/(utils\/(fibonacci|cuantoSeMueve|elliott|tecnico|listaTecnica|tusSenales|radiografia\w*)\.js|components\/(asset|tesis)\/|components\/(TusSenales|RadiografiaTecnica)\.jsx|pages\/(AnalisisTecnico|TuLista)\.jsx)/
    const archivos = archivosConTexto().filter(r => TECNICO.test(relativa(r)))
    expect(archivos.length).toBeGreaterThan(10)
    const vistos = archivos.flatMap(r => hallazgos(r, NO))
      // «Lo que vale hoy contra lo que pagaste»: el precio en vivo, es de hoy.
      .filter(h => !h.startsWith('src/components/asset/LecturaTecnica.jsx') || !/«hoy contra»/.test(h))
    expect(vistos).toEqual([])
  })
})
