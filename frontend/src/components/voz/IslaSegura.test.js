import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

const red = readFileSync(new URL('./IslaSegura.jsx', import.meta.url), 'utf8')
const app = readFileSync(new URL('../../App.jsx', import.meta.url), 'utf8')

// 🔴 Nico abrió la isla en su iPhone y le apareció "Se rompió esta pantalla":
// el acompañante se llevó puesta la aplicación entera. Eso está mal más allá
// del bug que lo causó — la isla flota SOBRE la pantalla que el usuario está
// mirando, y esa pantalla no tiene nada que ver con ella. Que una burbujita de
// chat rota impida ver cuánta plata tenés es una desproporción.
//
// MEDIDO: con la isla rota a propósito, el Dashboard se dibuja entero.
describe('la isla puede fallar, la pantalla no', () => {
  it('la isla va adentro de su propia red', () => {
    expect(app).toMatch(/<IslaSegura[\s\S]{0,120}<RendiMate \/>/)
  })

  it('cuando falla no dibuja nada, en vez de tirar el error para arriba', () => {
    expect(red).toMatch(/static getDerivedStateFromError/)
    expect(red).toMatch(/if \(this\.state\.fallo\) return null/)
  })

  it('el error se sigue registrando: la red no lo tapa', () => {
    // Una red que se traga el error en silencio deja el bug invisible para
    // siempre. Acá se apaga la isla y se anota qué pasó.
    expect(red).toMatch(/componentDidCatch/)
    expect(red).toMatch(/console\.error/)
  })

  it('al cambiar de pantalla le da otra oportunidad', () => {
    // El fallo pudo depender de esa pantalla o de un dato que ya no está.
    expect(red).toMatch(/prevProps\.reintentarEn !== this\.props\.reintentarEn/)
    expect(app).toMatch(/reintentarEn=\{pathname\}/)
  })
})
