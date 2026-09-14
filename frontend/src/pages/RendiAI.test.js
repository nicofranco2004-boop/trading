import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

const fuente = readFileSync(new URL('./RendiAI.jsx', import.meta.url), 'utf8')

// ─── "Nueva conversación" tiene que borrar la conversación ───────────────────
// Parece obvio y estuvo roto: el botón más usado de la pantalla no hacía nada.
//
// Fue una víctima del cambio que convirtió a AICoach en una VISTA. Antes la
// conversación vivía adentro de AICoach, así que volver a montarlo la tiraba;
// desde que vive en VozContext, montar de nuevo la vista no toca el hilo. Y el
// `clearChatSession()` que lo acompañaba borraba el guardado que el contexto
// volvía a escribir en el cambio siguiente.
//
// MEDIDO en pantalla antes del arreglo: la burbuja del usuario seguía ahí y lo
// guardado pasaba de 1.826 a 1.925 bytes — crecía en vez de vaciarse.
describe('el botón de nueva conversación', () => {
  it('le pide al DUEÑO del hilo que lo borre', () => {
    expect(fuente).toMatch(/limpiar: limpiarConversacion/)
    expect(fuente).toMatch(/limpiarConversacion\(\)/)
  })

  it('no vuelve a intentar borrar por su cuenta', () => {
    // Borrar el guardado sin avisarle al contexto es lo que no funcionaba: el
    // contexto lo reescribe. Quien tiene el hilo tiene que enterarse.
    // Mirando CÓDIGO, no comentarios: el de arriba nombra la función al
    // explicar por qué no está, y eso hacía fallar al guard contra sí mismo.
    const codigo = fuente.split('\n').filter(l => !l.trim().startsWith('//')).join('\n')
    expect(codigo).not.toMatch(/clearChatSession\(\)/)
  })

  it('el botón está cableado al handler y no a un cuerpo suelto', () => {
    expect(fuente).toMatch(/onClick=\{nuevaConversacion\}/)
  })
})
