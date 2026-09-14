import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

// El acompañante flota en una posición FIJA (arriba a la derecha, 88px desde
// el borde). Eso funciona mientras flote sobre el CONTENIDO de una página; en
// /ai la página tiene su propia barra justo ahí y se pisan. Medido a 375px:
// la burbuja de y=93 a 117, el título de /ai en y=107, y los dos botones de
// esa barra debajo.
//
// No hay forma de renderizar esto acá (el frontend corre sus tests sin
// navegador), así que se mira la fuente. Alcanza: lo que puede volver a
// romperse es que alguien borre las dos líneas.
const fuente = readFileSync(new URL('./RendiMate.jsx', import.meta.url), 'utf8')

describe('en /ai el acompañante no se dibuja', () => {
  it('sale sin dibujar nada, no sólo cerrado', () => {
    // `setOpen(false)` dejaba la BURBUJA, que es la que se pisaba con la barra
    // de la página. Y en esa pantalla no aporta ningún control: el parlante
    // está arriba y cada respuesta tiene su "Escuchar/Pausar".
    expect(fuente).toMatch(/if \(enElChatGrande\) return null/)
  })

  it('la salida va DESPUÉS de los avisos, no antes', () => {
    // Si el `return null` se sube arriba del efecto que mira la ruta, salir de
    // /ai con Rendi hablando deja de abrir la isla — que es justo el momento
    // para el que existe. Se esconde el dibujo; el componente sigue vivo.
    const efecto = fuente.indexOf('rutaPrevia.current = loc.pathname')
    const salida = fuente.indexOf('if (enElChatGrande) return null')
    expect(efecto).toBeGreaterThan(0)
    expect(salida).toBeGreaterThan(efecto)
  })
})
