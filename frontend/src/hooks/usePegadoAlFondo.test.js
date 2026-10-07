import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { seguir, volverASeguir } from './usePegadoAlFondo'

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

  it('con el chat vacío no se pega al fondo: la portada arranca ARRIBA (auditoría Mervall-E, ronda 2)', () => {
    // Pegada al fondo, una portada que no entra pierde lo de arriba: en un
    // iPhone con Safari no se veían ni la cara ni el título.
    expect(fuente).toMatch(/if \(!activo\) \{[\s\S]*?if \(activoAntesRef\.current\) el\.scrollTop = 0/)
    // …SÓLO al quedar vacío: un `el.scrollTop = 0` incondicional corre en cada
    // render (cada tecla) y no deja deslizar para leer la explicación.
    expect(fuente).not.toMatch(/if \(!activo\) \{\s*\n\s*el\.scrollTop = 0/)
    // …y queda lista para pegarse apenas haya conversación.
    expect(fuente).toMatch(/if \(!activo\) \{[\s\S]*?pegadoRef\.current = true/)
    // El chat le dice cuándo hay algo que seguir; la isla, que nunca muestra
    // portada, lo usa siempre activo.
    expect(chat).toMatch(/usePegadoAlFondo\(\{ activo: messages\.length > 0 \|\| loading \}\)/)
  })

  it('corre antes de que se pinte, para que el salto no se vea', () => {
    expect(fuente).toMatch(/useLayoutEffect/)
  })

  it('las DOS pantallas usan el mismo, sin copia propia', () => {
    for (const [nombre, src] of [['la isla', isla], ['el chat grande', chat]]) {
      // Con o sin opciones (el chat le pasa `{ activo }` para que la portada
      // vacía arranque arriba): lo que importa es que sea ESTE hook.
      expect(src, nombre).toMatch(/usePegadoAlFondo\((\{[^)]*\})?\)/)
      // Los restos de la versión copiada: si vuelve alguno, volvieron las dos
      // copias que se desincronizan.
      expect(src, nombre).not.toMatch(/onWheel=/)
      expect(src, nombre).not.toMatch(/onTouchMove=/)
      expect(src, nombre).not.toMatch(/tomoElControl/)
    }
  })
})

// ─── La segunda respuesta en el celular: Chrome también mueve la barra ──────
// Una caja que scrollea como la de Chrome, en lo que importa acá:
//   · la barra no pasa de cero ni del final: si el contenido se achica, baja
//     sola hasta donde se puede;
//   · EL ANCLA: antes de acomodar un dibujo, Chrome elige un elemento visible
//     de referencia y anota a qué altura de la pantalla está. Después de
//     acomodar, mueve la barra para dejarlo a esa misma altura. Si no le da el
//     lugar, sigue intentando en los dibujos siguientes, hasta que alguien
//     mueva la barra de verdad (ahí se olvida y elige otra referencia).
//     Con overflow-anchor: none no hace nada de esto.
//
// `dibujar(alto, referencia)` es lo que pasa entre que React escribe y que
// corre el efecto del hook: el contenido cambia de alto y Chrome lo acomoda.
// `referencia` = dónde estaba y dónde quedó, dentro del contenido, el
// elemento que Chrome usa de ancla.
// `pasaUnCuadro()`: el aviso de "la barra se movió" llega UN CUADRO TARDE —
// sólo ahí se entera quien lo escucha.
function cajaComoChrome({ alto, visible }) {
  let top = 0
  let ancla = null                 // a qué altura de la pantalla la quiere
  let avisado = 0                  // dónde estaba en el último aviso
  const oyentes = []
  const tope = () => Math.max(0, caja.scrollHeight - caja.clientHeight)
  const ajustar = (v) => Math.min(Math.max(0, v), tope())
  const anclaPrendida = () => caja.style.overflowAnchor !== 'none'
  const caja = {
    scrollHeight: alto,
    clientHeight: visible,
    style: {},
    get scrollTop() { return top },
    set scrollTop(v) {
      const nuevo = ajustar(v)
      if (nuevo !== top) { top = nuevo; ancla = null }
    },
    dibujar(nuevoAlto, referencia) {
      if (anclaPrendida() && !ancla && referencia) ancla = referencia.antes - top
      caja.scrollHeight = nuevoAlto
      if (!anclaPrendida()) ancla = null
      top = ajustar(ancla != null && referencia ? referencia.despues - ancla : top)
    },
    falta: () => caja.scrollHeight - caja.scrollTop - caja.clientHeight,
    addEventListener: (tipo, fn) => { if (tipo === 'scroll') oyentes.push(fn) },
    pasaUnCuadro() { if (top !== avisado) { avisado = top; oyentes.forEach(fn => fn()) } },
  }
  return caja
}

// Lo que hacen las pantallas, con la MISMA función que corre el hook después
// de cada dibujo (el test de abajo vigila que el hook no haga otra cosa).
function pantalla(caja) {
  const pegado = { current: true }
  const ultimo = { current: -1 }
  const vista = { current: null }
  return {
    pegado,
    // `otra`: la caja nueva cuando la pantalla la vuelve a armar (la isla).
    render: (otra = caja) => seguir(otra, pegado, ultimo, vista),
    preguntar: () => volverASeguir(pegado, ultimo),   // send() → alFondo()
  }
}

// Los números son los MEDIDOS en Chrome a 390×664 (celular, modo demo,
// origin/main fca238e8): la caja de mensajes mide 168px de alto; la fila
// "Basado en… datos de la demo" de la respuesta 1 —la referencia que eligió
// Chrome— estaba en 1078 y quedó en 1055 al irse la línea "Esta respuesta no
// trajo resumen para escuchar" (23px) que tenía arriba.
function conversacionEnElCelular() {
  const caja = cajaComoChrome({ alto: 168, visible: 168 })
  const c = pantalla(caja)
  c.render()                                   // pregunta 1 + puntitos
  caja.dibujar(1234)                           // llega la respuesta 1
  c.render()
  const trasLaPrimera = caja.scrollTop         // 1066: el fondo
  c.preguntar()                                // toca "¿Qué riesgos detectás…?"
  caja.dibujar(1192, { antes: 1078, despues: 1055 })
  c.render()
  const esperando = caja.scrollTop             // 1024: el fondo (se achicó)
  caja.dibujar(1766, { antes: 1055, despues: 1055 })   // llega la respuesta 2
  const alLlegar = caja.scrollTop              // lo que encuentra el hook
  c.render()
  return { caja, c, trasLaPrimera, esperando, alLlegar }
}

describe('la segunda respuesta en el celular se sigue hasta el final', () => {
  it('el hook corre exactamente esto después de cada dibujo, y alFondo es volverASeguir', () => {
    // Si el hook hiciera otra cosa, los tests de abajo certificarían una
    // función que en producción no corre. Lo único que hace antes es lo del
    // chat vacío (la portada arriba), que vigila su propio test.
    expect(fuente).toMatch(/activoAntesRef\.current = true\s*\n\s*seguir\(el, pegadoRef, ultimoAutoRef, cajaRef\)\s*\n\s*\}\)/)
    expect((fuente.match(/el\.scrollTop = el\.scrollHeight/g) || []).length).toBe(1)   // sólo en seguir()
    expect(fuente).toMatch(/const alFondo = useCallback\(\(\) => volverASeguir\(pegadoRef, ultimoAutoRef\), \[\]\)/)
  })

  it('la caja de prueba reproduce lo medido cuando Chrome ancla: 19px de deuda y 555 abajo', () => {
    // El hook de antes, tal cual (sin apagar el ancla y midiendo contra el
    // fondo nuevo). Si esto deja de dar 555, la caja ya no imita a Chrome y
    // los tests de abajo no prueban nada.
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const pegado = { current: true }, ultimo = { current: -1 }
    const deAntes = () => {
      const seMovio = ultimo.current >= 0 && Math.abs(caja.scrollTop - ultimo.current) > 2
      if (seMovio) pegado.current = (caja.scrollHeight - caja.scrollTop - caja.clientHeight) < 80
      if (pegado.current) { caja.scrollTop = caja.scrollHeight; ultimo.current = caja.scrollTop }
    }
    deAntes(); caja.dibujar(1234); deAntes()
    expect(caja.scrollTop).toBe(1066)
    pegado.current = true; ultimo.current = -1
    caja.dibujar(1192, { antes: 1078, despues: 1055 }); deAntes()
    expect(caja.scrollTop).toBe(1024)
    caja.dibujar(1766, { antes: 1055, despues: 1055 })
    expect(caja.scrollTop).toBe(1043)              // Chrome cobró los 19px
    deAntes()
    expect(pegado.current).toBe(false)
    expect(caja.falta()).toBe(555)                 // lo que se veía en el celular
  })

  it('mientras sigue, Chrome no ancla: no queda deuda y la respuesta 2 se ve entera', () => {
    const r = conversacionEnElCelular()
    expect(r.trasLaPrimera).toBe(1066)
    expect(r.esperando).toBe(1024)
    expect(r.alLlegar).toBe(1024)                  // nadie movió la barra
    expect(r.c.pegado.current).toBe(true)
    expect(r.caja.scrollTop).toBe(1598)
    expect(r.caja.falta()).toBe(0)
    expect(r.caja.style.overflowAnchor).toBe('none')
  })

  it('y si algo la empuja PARA ABAJO igual, no cuenta como "se fue"', () => {
    // La otra mitad: aunque Chrome (u otra cosa que todavía no se nos ocurrió)
    // mueva la barra, bajar no es irse a leer —eso es subir—. Es el empujón
    // medido, con la respuesta nueva ya adentro: antes daba "lejos" (555).
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()
    c.preguntar(); caja.dibujar(1192); c.render()
    caja.dibujar(1766)
    caja.scrollTop = caja.scrollTop + 19           // el empujón de 19px de Chrome
    c.render()
    expect(c.pegado.current).toBe(true)
    expect(caja.falta()).toBe(0)
  })

  it('el que empieza a SUBIR justo cuando entra un bloque grande queda suelto: no se lo pelea', () => {
    // Decisión de la auditoría. Una versión de este arreglo medía la subida
    // contra donde la dejamos (y no contra el fondo nuevo): con eso, a éste lo
    // volvía a bajar a la fuerza hasta que subiera 80px. Mejor perderse el
    // seguimiento de unas tarjetas que pelearle el dedo al que se va a leer.
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()     // al fondo: 1066
    caja.scrollTop = 1036                          // empieza a subir: 30px
    caja.dibujar(1634)                             // entran las tarjetas: +400
    c.render()
    expect(c.pegado.current).toBe(false)
    expect(caja.scrollTop).toBe(1036)              // donde él la dejó
  })
})

describe('el que se fue a leer sigue sin ser arrastrado', () => {
  it('se va arriba: no se lo baja mientras llega la respuesta, y vuelve a seguir cuando él vuelve', () => {
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()
    caja.scrollTop = 300                           // se fue a leer
    caja.dibujar(1300); c.render()
    expect(caja.scrollTop).toBe(300)
    expect(c.pegado.current).toBe(false)
    caja.dibujar(1500); c.render()
    expect(caja.scrollTop).toBe(300)
    caja.scrollTop = 1500 - 168                    // vuelve al fondo él solo
    caja.dibujar(1520); c.render()                 // y entra otro pedacito
    expect(c.pegado.current).toBe(true)
    expect(caja.falta()).toBe(0)
  })

  it('mientras lee, Chrome le vuelve a cuidar el lugar: si se borra el mensaje más viejo, el texto no le salta', () => {
    // Pasando los 40 mensajes se borra el más viejo, ARRIBA de lo que está
    // leyendo. Con el ancla apagada para siempre, el texto le saltaría 200px.
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()
    expect(caja.style.overflowAnchor).toBe('none')
    caja.scrollTop = 400                           // se fue a leer
    caja.dibujar(1300); c.render()
    expect(caja.style.overflowAnchor).toBe('')     // el ancla, de vuelta
    // Lo que está leyendo estaba en 450; se borran 200px de arriba → 250.
    caja.dibujar(1150, { antes: 450, despues: 250 }); c.render()
    expect(caja.scrollTop).toBe(200)               // 450−400 = 250−200: no saltó
    expect(c.pegado.current).toBe(false)
  })

  it('si el contenido se achica y la barra baja sola al fondo, sigue pegado', () => {
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()     // 1066
    caja.dibujar(1034); c.render()                 // −200: la barra topa en 866
    expect(c.pegado.current).toBe(true)
    expect(caja.falta()).toBe(0)
  })
})

// ─── Lo que encontró la auditoría ───────────────────────────────────────────
describe('auditoría: lo que el arreglo no podía empeorar', () => {
  it('la isla (pregunta ANTES de "volvé a seguir"): también se sigue la respuesta 2', () => {
    // La isla llama alFondo en un efecto que corre DESPUÉS del dibujo que
    // agrega la pregunta — al revés que el chat grande. Ese dibujo se juzga
    // con la barra que topó en 1024.
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()
    caja.dibujar(1192, { antes: 1078, despues: 1055 }); c.render()
    c.preguntar()
    caja.dibujar(1766, { antes: 1055, despues: 1055 }); c.render()
    expect(c.pegado.current).toBe(true)
    expect(caja.falta()).toBe(0)
  })

  it('el que sube a releer durante el "pensando…" no ve saltar el texto cuando se borra el mensaje más viejo', () => {
    // 40 mensajes: el primer pedazo de la respuesta entra abajo y, en el MISMO
    // dibujo, se borra el mensaje más viejo de arriba (200px). Si el ancla
    // volviera recién en ese dibujo, el texto le saltaba 200px.
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(2000); c.render()     // al fondo: 1832, sin ancla
    expect(caja.style.overflowAnchor).toBe('none')
    caja.scrollTop = 1500                          // sube a releer, sin dibujos
    caja.pasaUnCuadro()                            // llega el aviso de scroll
    expect(caja.style.overflowAnchor).toBe('')     // el ancla, de vuelta YA
    // Lo que está leyendo estaba en 1550; se borran 200px de arriba → 1350.
    caja.dibujar(1900, { antes: 1550, despues: 1350 }); c.render()
    expect(caja.scrollTop).toBe(1300)              // 1550−1500 = 1350−1300
    expect(c.pegado.current).toBe(false)
  })

  it('los movimientos propios y el tope no le devuelven el ancla mientras sigue', () => {
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()
    caja.pasaUnCuadro()                            // aviso de nuestra bajada
    c.preguntar(); caja.dibujar(1192); c.render()  // topa en 1024
    caja.pasaUnCuadro()                            // aviso del tope
    expect(caja.style.overflowAnchor).toBe('none')
  })

  it('el que BAJA a leer algo que creció sin redibujar no es tirado al fondo', () => {
    const caja = cajaComoChrome({ alto: 168, visible: 168 })
    const c = pantalla(caja)
    c.render(); caja.dibujar(1234); c.render()     // al fondo: 1066
    caja.dibujar(1834)                             // creció 600 sin redibujar
    caja.scrollTop = 1366                          // baja 300 a leerlo
    c.render()                                     // otro dibujo (el audio)
    expect(c.pegado.current).toBe(false)
    expect(caja.scrollTop).toBe(1366)
  })

  it('la isla cerrada y reabierta muestra lo último (en main mostraba lo más viejo)', () => {
    // Al cerrarse, la isla desarma la lista; al reabrir nace una caja nueva
    // con la barra en cero. MEDIDO en Chrome sobre main: 440px arriba del
    // último mensaje.
    const vieja = cajaComoChrome({ alto: 260, visible: 260 })
    const c = pantalla(vieja)
    c.render(); vieja.dibujar(700); c.render()     // abierta: al fondo, 440
    const nueva = cajaComoChrome({ alto: 700, visible: 260 })
    c.render(nueva)                                // reabierta
    expect(nueva.scrollTop).toBe(440)
    expect(nueva.style.overflowAnchor).toBe('none')
    expect(c.pegado.current).toBe(true)
  })
})
