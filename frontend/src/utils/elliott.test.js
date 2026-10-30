// D3 (auditoría D, 29/10): «✓ La onda 2 devolvió el 68 % de la 1 (lo habitual:
// entre 50 % y 61,8 %)». El ✓ lo decide el servidor con su rango (40–72 %,
// backend/elliott.py) y el texto escribía otro, a mano. Ahora cada pauta llega
// con `desde`/`hasta` y el texto escribe ESE rango: lo que se muestra y lo que
// se cuenta son lo mismo. La prueba lee los números del TEXTO, como la persona.
import { describe, it, expect } from 'vitest'
import { textoPauta } from './elliott'

// Los rangos del servidor (backend/elliott.py: P_ONDA2…P_ONDA_C).
const RANGOS = {
  onda2: [0.40, 0.72], onda3: [1.38, 1.90], onda4: [0.24, 0.50],
  onda5: [0.75, 1.33], ondaB: [0.40, 0.79], ondaC: [0.75, 1.33],
}
const num = (s) => Number(s.replace(/\./g, '').replace(',', '.'))
// «… el 68 % de la 1 (lo habitual, con margen: entre 40 % y 72 %)» → [68, 40, 72]
function leer(t) {
  const m = t.match(/(?:el|midió) (\d+(?:,\d+)?).*entre (\d+(?:,\d+)?)(?: %)? y (\d+(?:,\d+)?)/)
  return m ? [num(m[1]), num(m[2]), num(m[3])] : []
}

describe('D3 · Elliott: el ✓ y el rango escrito son el mismo', () => {
  it('el caso de AAPL: 68 % con ✓ escribe un rango que contiene el 68', () => {
    const t = textoPauta({ id: 'onda2', valor: 0.68, cumple: true, desde: 0.40, hasta: 0.72 })
    expect(t).toContain('entre 40 % y 72 %')
    expect(t).not.toContain('61,8')
  })

  it('para cada pauta y valores de punta a punta: ✓ ⇔ el número escrito cae en el rango escrito', () => {
    for (const [id, [desde, hasta]] of Object.entries(RANGOS)) {
      for (let v = desde - 0.3; v <= hasta + 0.3; v += 0.01) {
        const valor = Math.round(v * 100) / 100   // como lo manda el servidor
        if (valor <= 0) continue
        const cumple = desde <= valor && valor <= hasta
        const t = textoPauta({ id, valor, cumple, desde, hasta })
        const [x, a, b] = leer(t)
        expect(a <= x && x <= b, `${t} (✓=${cumple})`).toBe(cumple)
      }
    }
  })

  it('un servidor viejo sin rango: no se inventa uno', () => {
    const t = textoPauta({ id: 'onda2', valor: 0.68, cumple: true })
    expect(t).toBe('La onda 2 devolvió el 68 % de la 1.')
  })

  it('la alternancia no tiene rango y sigue igual', () => {
    expect(textoPauta({ id: 'alternancia', valor: null, cumple: false })).toContain('lo habitual es que sean distintas')
  })
})
