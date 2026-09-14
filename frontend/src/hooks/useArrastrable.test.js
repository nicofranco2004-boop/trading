import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'

const fuente = readFileSync(new URL('./useArrastrable.js', import.meta.url), 'utf8')
const isla = readFileSync(new URL('../components/voz/RendiMate.jsx', import.meta.url), 'utf8')

// Arrastrar la isla. No se puede montar acá (el frontend corre sus tests sin
// navegador), así que esto guarda las decisiones que ya costaron una prueba
// fallida; el comportamiento se midió en el navegador, cerrada y abierta, en
// escritorio y en 375px.
describe('mover la isla con el dedo', () => {
  it('un toque sigue siendo un toque', () => {
    // El botón de abrir, el parlante y la X viven ADENTRO de la zona que
    // arrastra. Sin el umbral, mover la isla te la abría o te la cerraba al
    // soltar; con él, menos de 4px es un toque y el botón hace lo suyo.
    expect(fuente).toMatch(/UMBRAL = 4/)
    expect(fuente).toMatch(/if \(!arrastroRef\.current && Math\.abs\(mx\) \+ Math\.abs\(my\) < UMBRAL\) return/)
  })

  it('el clic que viene DESPUÉS de arrastrar se descarta', () => {
    expect(fuente).toMatch(/onClickCapture/)
    expect(fuente).toMatch(/if \(arrastroRef\.current\) \{\s*\n\s*e\.preventDefault\(\)/)
  })

  it('cada toque nuevo arranca limpio', () => {
    // Si el "vengo de arrastrar" sobreviviera al gesto, se comería el toque
    // siguiente y la isla no abriría hasta el segundo intento.
    const apretar = fuente.slice(fuente.indexOf('const alApretar'))
    expect(apretar.slice(0, 400)).toMatch(/arrastroRef\.current = false/)
  })

  it('no se puede ir de la pantalla, ni al soltar ni al cambiar de tamaño', () => {
    // Al abrirse crece y al rotar el teléfono la pantalla se da vuelta: sin
    // recortar en esos momentos, quedaba con el cuadro de escribir afuera y
    // sin forma de volver a agarrarla.
    expect(fuente).toMatch(/ResizeObserver/)
    expect(fuente).toMatch(/window\.addEventListener\('resize', acomodar\)/)
    expect(fuente).toMatch(/MARGEN = 8/)
  })

  it('el gesto no se lo queda el navegador para scrollear', () => {
    // Sin touchAction 'none' el arrastre no llega nunca en el celular.
    expect(fuente).toMatch(/touchAction: 'none'/)
  })

  it('la posición dura lo que dura la PESTAÑA', () => {
    // Pedido de Nico: al volver a entrar, la isla en su lugar de siempre. Uno
    // la corre porque le tapa la pantalla que está mirando AHORA.
    expect(fuente).toMatch(/sessionStorage\.getItem/)
    expect(fuente).toMatch(/sessionStorage\.setItem/)
    expect(fuente).not.toMatch(/localStorage\./)
  })

  it('la isla la usa cerrada Y abierta', () => {
    expect(isla).toMatch(/useArrastrable\('rendi:isla:pos'\)/)
    // Cerrada: toda la burbuja es la manija. Abierta: sólo la cabecera — el
    // hilo y el cuadro de escribir quedan afuera porque ahí se scrollea y se
    // selecciona texto.
    expect(isla).toMatch(/onPointerDown=\{manija\.onPointerDown\}/)
    expect(isla).toMatch(/<header\s*\n?\s*\{\.\.\.manija\}/)
  })
})
