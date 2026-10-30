// D12 (auditoría D, 29/10): lo mismo dicho de maneras distintas en Cartera,
// Panorama y Señales:
//   · con «Ocultar saldos», tres frases («Mirá cómo está repartida tu plata…»,
//     «Así está repartida tu plata…», «•• Oculto porque…»);
//   · «la semana pasada» con coma en dos y sin coma en la otra («el sábado 24/10 86%»);
//   · títulos: «Tu plata en tendencia de fondo alcista» / «Tu plata en tendencia
//     alcista»; «Lo que cambió esta semana en lo tuyo» con cosas de la watchlist;
//     «Esta semana» en un lado y «Los últimos 7 días, contados desde hoy» en otro.
// Ahora cada cosa sale de una constante o función de utils/tusSenales.js, y esta
// prueba exige que las pantallas las usen (y no vuelvan a escribirlas a mano).
import { describe, it, expect } from 'vitest'
import {
  TITULO_PLATA_ALCISTA, PLATA_ALCISTA_OCULTA, TITULO_CAMBIOS, QUE_ES_ESTA_SEMANA, antesConPct, tarjetas,
} from './tusSenales'
import fuenteRadiografia from '../components/RadiografiaTecnica.jsx?raw'
import fuentePanorama from '../pages/AnalisisTecnico.jsx?raw'
import fuenteSenales from '../components/TusSenales.jsx?raw'

describe('D12 · lo mismo, dicho igual en Cartera, Panorama y Señales', () => {
  it('las palabras', () => {
    expect(TITULO_PLATA_ALCISTA).toBe('Tu plata en tendencia de fondo alcista')
    expect(PLATA_ALCISTA_OCULTA).toContain('Ocultar saldos')
    expect(TITULO_CAMBIOS).toMatch(/lo que tenés y en tu watchlist/)
    expect(antesConPct({ semana: '2026-10-24', pct: 86.2 }, '2026-10-29')).toBe('el sábado 24/10, 86%')
  })

  it('Señales usa el mismo título, la misma frase oculta y la coma', () => {
    const datos = { hasta: '2026-10-29', senales: [], alcista: { pct: 54, semana_pasada: { semana: '2026-10-24', pct: 61 } } }
    expect(tarjetas(datos, false).plata.titulo).toBe(TITULO_PLATA_ALCISTA)
    expect(tarjetas(datos, false).plata.antes).toBe('el sábado 24/10, 61%')
    expect(tarjetas(datos, true).plata.texto).toBe(PLATA_ALCISTA_OCULTA)
  })

  it('las pantallas no escriben estas frases a mano', () => {
    for (const [nombre, f] of [['Radiografía', fuenteRadiografia], ['Panorama', fuentePanorama], ['Señales', fuenteSenales]]) {
      expect(f, nombre).not.toMatch(/Mirá cómo está repartida|Así está repartida/)
      expect(f, nombre).not.toMatch(/en lo tuyo<\/h2>|>Esta semana<\/div>/)
      expect(f, nombre).not.toContain('Los últimos 7 días, contados desde hoy')
    }
    expect(fuenteRadiografia).toContain('PLATA_ALCISTA_OCULTA')
    expect(fuentePanorama).toContain('TITULO_PLATA_ALCISTA')
    expect(fuentePanorama).toContain('TITULO_CAMBIOS')
    expect(fuenteSenales).toContain('TITULO_CAMBIOS')
    expect(fuenteSenales).toContain('QUE_ES_ESTA_SEMANA')
    expect(fuentePanorama).toContain('QUE_ES_ESTA_SEMANA')
  })
})
