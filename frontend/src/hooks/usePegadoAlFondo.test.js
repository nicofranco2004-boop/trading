import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

const fuente = readFileSync(new URL('./usePegadoAlFondo.js', import.meta.url), 'utf8')
const isla = readFileSync(new URL('../components/voz/RendiMate.jsx', import.meta.url), 'utf8')
const chat = readFileSync(new URL('../components/AICoach.jsx', import.meta.url), 'utf8')

// ─── No adivinar el gesto: mirar la posición ────────────────────────────────
// La versión anterior se enteraba de que el usuario se había movido por dos
// avisos del navegador: la rueda y el dedo arrastrando. Hay muchas formas de
// scrollear que no disparan ninguno —la barra, el teclado, y sobre todo LA
// INERCIA del dedo en el celular, que sigue corriendo cuando el dedo ya no
// está—. En esos casos el único aviso llega un cuadro tarde, y en ese cuadro
// entra una palabra nueva que dispara el auto-scroll.
//
// MEDIDO en la isla con Rendi escribiendo: subir a cero sin rueda ni dedo daba
// 0 → 1031 → 1167 (el fondo) en menos de un segundo. Con el arreglo, catorce
// muestras seguidas en cero. Y quedándose abajo, sigue siguiendo.
describe('seguir la respuesta sin arrastrar al que está leyendo', () => {
  it('decide comparando con la posición que dejó ÉL, no por el gesto', () => {
    expect(fuente).toMatch(/ultimoAutoRef/)
    expect(fuente).toMatch(/Math\.abs\(el\.scrollTop - ultimoAutoRef\.current\) > TOLERANCIA/)
  })

  it('anota dónde dejó la barra cada vez que la mueve', () => {
    // Sin esto la comparación de arriba no tiene contra qué comparar y todo
    // movimiento parece del usuario.
    expect(fuente).toMatch(/el\.scrollTop = el\.scrollHeight\s*\n\s*ultimoAutoRef\.current = el\.scrollTop/)
  })

  it('corre antes de que se pinte, para que el salto no se vea', () => {
    expect(fuente).toMatch(/useLayoutEffect/)
  })

  it('las DOS pantallas usan el mismo, sin copia propia', () => {
    for (const [nombre, src] of [['la isla', isla], ['el chat grande', chat]]) {
      expect(src, nombre).toMatch(/usePegadoAlFondo\(\)/)
      // Los restos de la versión copiada: si vuelve alguno, volvieron las dos
      // copias que se desincronizan.
      expect(src, nombre).not.toMatch(/onWheel=/)
      expect(src, nombre).not.toMatch(/onTouchMove=/)
      expect(src, nombre).not.toMatch(/tomoElControl/)
    }
  })
})
