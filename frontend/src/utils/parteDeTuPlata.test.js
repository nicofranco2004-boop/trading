// D12 (auditoría D, 29/10): YPFD decía «Es el 0 % de tu cartera» en la ficha
// mientras Tu lista decía «menos de 1 %», y Señales «menos del 1%». Cuatro
// pantallas escribían «qué parte de tu cartera es» cada una a su manera. Ahora
// una sola función (parteDeTuPlata) y las cuatro la usan.
import { describe, it, expect } from 'vitest'
import { parteDeTuPlata } from './parteDeTuPlata'
import { tarjetasMovimiento } from './cuantoSeMueve'
import { pesoTxt } from './tusSenales'
import fuenteLista from '../pages/TuLista.jsx?raw'
import fuenteRadiografia from '../components/RadiografiaTecnica.jsx?raw'

describe('qué parte de tu cartera es: una sola manera de decirlo', () => {
  it('menos de 1 % no es «0 %»', () => {
    expect(parteDeTuPlata(0.4)).toBe('menos de 1%')
    expect(parteDeTuPlata(0)).toBe('0%')
    expect(parteDeTuPlata(12.4)).toBe('12%')
    expect(parteDeTuPlata(null)).toBeNull()
  })

  it('la ficha (YPFD, 0,4 %): «Es menos de 1% de tu cartera»', () => {
    const m = { disponible: true, hasta: '2026-10-28', peor_caida: null, desde_el_maximo: null,
      dia_normal: { desvio_pct: 2, dias: 500, dias_malos: 40 } }
    const c = tarjetasMovimiento(m, { tenencia: { valor: 10 }, peso: 0.004 }).find(x => x.id === 'cartera')
    expect(c.texto).toContain('Es menos de 1% de tu cartera')
    expect(c.texto).not.toMatch(/\b0\s?% de tu cartera/)
  })

  it('Señales dice lo mismo', () => {
    expect(pesoTxt(0.004, false)).toBe('menos de 1% de tu cartera')
    expect(pesoTxt(0.12, false)).toBe('12% de tu cartera')
  })

  it('Tu lista y el Panorama usan la misma función', () => {
    // Tu lista va por pesoVisible / deTuCartera (parteDeTuPlata + el ojito).
    expect(fuenteLista).toMatch(/\b(parteDeTuPlata|pesoVisible|deTuCartera)\(/)
    expect(fuenteRadiografia).toContain('parteDeTuPlata(')
    expect(fuenteLista).not.toContain("'menos de 1%'")
    expect(fuenteRadiografia).not.toContain("'menos de 1%'")
  })
})
