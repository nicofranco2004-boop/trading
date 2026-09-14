import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

// El proveedor es el dueño de la conversación y del audio. No se puede montar
// acá (el frontend corre sus tests sin navegador), así que estos son guards de
// fuente sobre decisiones que ya se rompieron una vez.
const fuente = readFileSync(new URL('./VozContext.jsx', import.meta.url), 'utf8')

describe('cuando el turno se reinicia, el audio también', () => {
  it('el reset calla lo que se haya empezado a decir', () => {
    // Un turno que usa una herramienta escribe primero un preámbulo ("dejame
    // ver los precios") que después se borra de la pantalla. Si ese preámbulo
    // traía su resumen hablado, Rendi ya estaba diciéndolo en voz alta.
    const reset = fuente.slice(fuente.indexOf('const onReset = () => {'))
    expect(reset.slice(0, 900)).toMatch(/stop\(\)/)
  })

  it('y vuelve a permitir que suene la respuesta de verdad', () => {
    // Éste era el daño grande: `yaSono` quedaba en true, así que la respuesta
    // real no arrancaba NUNCA. El usuario escuchaba el preámbulo, se quedaba
    // esperando el resto, y la escucha ya estaba gastada.
    const reset = fuente.slice(fuente.indexOf('const onReset = () => {'))
    expect(reset.slice(0, 900)).toMatch(/yaSono = false/)
  })

  it('la traba de "ya sonó" se declara ANTES del reset', () => {
    // Si se declarara después, el reset no la vería y el arreglo sería mudo.
    expect(fuente.indexOf('let yaSono = false'))
      .toBeLessThan(fuente.indexOf('const onReset = () => {'))
  })
})
