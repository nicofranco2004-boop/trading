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

describe('el micrófono no se queda grabando a escondidas', () => {
  it('se corta cuando el panel deja de estar a la vista', () => {
    // El panel de grabar vive adentro de la tarjeta abierta. Al entrar a /ai la
    // isla se cierra sola: el panel desaparece y el grabador seguía tomando,
    // con la lucecita del micrófono prendida y sin nada que lo pare.
    expect(fuente).toMatch(/if \(!panelALaVista && micGrabando\) micCancelar\(\)/)
  })

  it('el hook del micrófono expone con qué pararlo', () => {
    // Sin esto no hay arreglo posible desde acá: el grabador es privado del
    // hook y quien esconde el panel no tiene cómo avisarle.
    const boton = readFileSync(new URL('./BotonMicrofono.jsx', import.meta.url), 'utf8')
    expect(boton).toMatch(/cancelar: d\.cancelar/)
  })
})

describe('en el celular los botones del pie se pueden tocar', () => {
  // El mínimo para un dedo son 44px. El de enviar dibujaba 28 y no tenía área
  // agrandada: el micrófono de al lado sí, y su propio comentario explicaba
  // que no crecía el dibujo "para no quedar desparejo al lado del de enviar,
  // que mide 28" — o sea que el de enviar era la referencia, y era el chico.
  //
  // MEDIDO después del arreglo: enviar 28 de dibujo y 44×44 de área; el
  // micrófono 30 y 46×46. Y las dos áreas quedan pegadas SIN pisarse ni
  // comerse el cuadro de escribir, que conserva sus 281px.
  it('el de enviar tiene área de toque aunque el círculo sea chico', () => {
    const boton = fuente.slice(fuente.indexOf('aria-label="Enviar"'))
    expect(boton.slice(0, 400)).toMatch(/after:-inset-2/)
  })

  it('crece el área y NO el dibujo', () => {
    // Un botón de 44 al lado de un micrófono de 30 queda desparejo, y es la
    // misma razón por la que el micrófono tampoco creció.
    const boton = fuente.slice(fuente.indexOf('aria-label="Enviar"'))
    expect(boton.slice(0, 400)).toMatch(/w-7 h-7/)
  })

  it('con mouse se apaga: ahí el blanco alcanza', () => {
    const boton = fuente.slice(fuente.indexOf('aria-label="Enviar"'))
    expect(boton.slice(0, 400)).toMatch(/sm:after:inset-0/)
  })
})
