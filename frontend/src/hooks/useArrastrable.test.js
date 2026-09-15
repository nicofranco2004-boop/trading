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

  it('al ABRIRSE se vuelve a recortar, porque es otro elemento', () => {
    // Cerrada es una burbujita y abierta es una tarjeta del ancho entero: React
    // desmonta una y monta la otra. MEDIDO: arrastrar la burbuja 140px a la
    // izquierda y abrirla dejaba la tarjeta en x = -128, afuera de la pantalla.
    //
    // El efecto va SIN lista de dependencias —corre en cada dibujo— porque es
    // lo único que se entera de que el elemento cambió.
    const i = fuente.indexOf('const vigiaRef')
    const bloque = fuente.slice(i, fuente.indexOf('// Rotar el teléfono'))
    expect(bloque).toMatch(/useLayoutEffect\(\(\) => \{/)
    expect(bloque).not.toMatch(/\}, \[/)          // sin dependencias
    expect(bloque).toMatch(/acomodar\(\)/)
  })

  it('pero NO cambia el estado en cada dibujo', () => {
    // 🔴 Eso es un bucle esperando a pasar: recortar cambia la posición,
    // cambiar la posición redibuja, y redibujar vuelve a recortar. Mientras
    // nada se mueva React corta solo; pero con el alto de la pantalla cambiando
    // cuadro a cuadro —el teclado del celular abriéndose— cada vuelta da un
    // número distinto y no corta nunca. Nico reportó las dos caras: "Se rompió
    // esta pantalla" al abrir la isla, y la isla desapareciendo sola al tocar
    // el cuadro para escribir.
    //
    // La guarda: primero se pregunta si el elemento cambió y se sale si no.
    const i = fuente.indexOf('const vigiaRef')
    const bloque = fuente.slice(i, fuente.indexOf('// Rotar el teléfono'))
    const cuerpo = bloque.slice(bloque.indexOf('useLayoutEffect'))
    const salida = cuerpo.indexOf('if (vigiaRef.current.nodo === nodo) return')
    const trabajo = cuerpo.indexOf('acomodar()')
    expect(salida).toBeGreaterThan(0)
    expect(trabajo).toBeGreaterThan(salida)   // recorta DESPUÉS de la guarda
  })

  it('el vigilante se re-engancha al elemento nuevo', () => {
    expect(fuente).toMatch(/if \(vigiaRef\.current\.nodo === nodo\) return/)
    expect(fuente).toMatch(/vigiaRef\.current\.obs\?\.disconnect\(\)/)
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
