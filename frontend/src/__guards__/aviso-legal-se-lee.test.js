// D12 (auditoría D, 29/10): el aviso «Muestra cómo se movieron los precios: no
// es una recomendación…» del final de Análisis técnico daba 4,0 a 1 de
// contraste en modo claro con letra de 12 px (el mínimo para letra chica es
// 4,5): estaba en `text-ink-3`, el color de «pistas, deshabilitado» (index.css).
// El aviso legal no es una pista: va en `text-ink-2` (rótulos, ~6,8 a 1 en
// claro). Lo mismo los pies de Fibonacci y Elliott, que dicen lo mismo.
import { describe, it, expect } from 'vitest'
import panorama from '../pages/AnalisisTecnico.jsx?raw'
import senales from '../components/TusSenales.jsx?raw'
import radiografia from '../components/RadiografiaTecnica.jsx?raw'
import ficha from '../components/asset/LecturaTecnica.jsx?raw'
import fibonacci from '../components/asset/CapaFibonacci.jsx?raw'
import elliott from '../components/asset/CapaElliott.jsx?raw'

// El renglón del aviso y el anterior (donde suele estar la etiqueta con la clase).
function clasesDelAviso(fuente, marca) {
  const l = fuente.split('\n')
  return l.flatMap((x, i) => (x.includes(marca) ? [`${l[i - 1] || ''}\n${x}`] : []))
}

describe('el aviso «no es una recomendación» se lee', () => {
  const casos = [
    ['Panorama', panorama, '{NO_ES_RECOMENDACION}'], ['Señales', senales, '{NO_ES_RECOMENDACION}'],
    ['Cartera/Panorama', radiografia, 'no es una recomendación'], ['Ficha', ficha, 'no es una recomendación para comprar'],
    ['Fibonacci', fibonacci, '{t.pie}'], ['Elliott', elliott, '{t.pie}'],
  ]
  for (const [nombre, fuente, marca] of casos) {
    it(nombre, () => {
      const avisos = clasesDelAviso(fuente, marca)
      expect(avisos.length, nombre).toBeGreaterThan(0)
      for (const a of avisos) expect(a, nombre).not.toMatch(/text-ink-3/)
    })
  }
})
