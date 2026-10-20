// Dónde poner el ✦ «Preguntarle a Mervall-E» sin tapar nada de la tarjeta.
// ═══════════════════════════════════════════════════════════════════════════
// El ✦ iba fijo arriba a la derecha de cada tarjeta. En 17 de las 59 del demo
// (2026-10-20) esa esquina ya estaba ocupada: las etiquetas «Media»/«Saludable»
// de Comportamiento, el «MAX» del gráfico, «Ver todos», «Ir a Cartera»… El ✦
// las tapaba y, peor, se quedaba con el clic del botón de abajo. Le pasaba al
// visitante nuevo (el ✦ se ve siempre), en el celular (también), y a todos en
// la compu al pasar el mouse.
//
// Como son 30+ tarjetas armadas cada una a su manera, no se arregla tarjeta por
// tarjeta: el ✦ mira lo que hay en su franja de arriba y se corre al primer
// hueco libre hacia la izquierda (queda al lado de la etiqueta o del botón). Si
// la franja está llena, se apoya sobre el borde de arriba de la tarjeta.

const MARGEN = 8       // = top-2 / right-2, la esquina de siempre
const SEPARACION = 6   // aire entre el ✦ y lo que esquiva

function seTocan(a, b) {
  return Math.min(a.right, b.right) - Math.max(a.left, b.left) > 0
    && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0
}

/**
 * elegirLugar — la parte de la cuenta, sin DOM (así se puede probar).
 * @param {number} ancho  ancho de la tarjeta
 * @param {{w:number,h:number}} boton  tamaño del ✦
 * @param {Array<{left,right,top,bottom}>} obstaculos  relativos a la esquina de arriba a la izquierda de la tarjeta
 * @param {{w:number,h:number}} [compacto]  tamaño del ✦ solo, si el botón es la pastilla con texto
 * @returns {{top:number,right:number,compacto?:true}}  distancias desde arriba y desde la derecha
 */
export function elegirLugar(ancho, boton, obstaculos, compacto) {
  const l = buscarLugar(ancho, boton, obstaculos)
  if (l.top >= 0 || !compacto || compacto.w >= boton.w) return l
  // En el celular el ✦ es una pastilla «✦ Analizar»: si no entra en la fila de
  // arriba, antes de salirse de la tarjeta prueba achicarse al ✦ solo.
  const c = buscarLugar(ancho, compacto, obstaculos)
  return c.top >= 0 ? { ...c, compacto: true } : l
}

function buscarLugar(ancho, boton, obstaculos) {
  // Primero a 8 px del borde (como siempre); si la fila de arriba es más baja
  // que el botón (un título con un link al lado), pegado arriba de todo.
  for (const top of [MARGEN, 0]) {
    let right = MARGEN
    for (let i = 0; i < 12; i++) {
      const caja = { left: ancho - right - boton.w, right: ancho - right, top, bottom: top + boton.h }
      if (caja.left < MARGEN) break
      const choca = obstaculos.filter(o => seTocan(caja, o))
      if (!choca.length) return { top, right }
      right = ancho - Math.min(...choca.map(o => o.left)) + SEPARACION
    }
  }
  // Sin hueco en la franja: montado sobre el borde de arriba (la mitad queda
  // afuera de la tarjeta, donde no hay nada de ella que tapar). Si lo de abajo
  // arranca muy arriba, sube lo que haga falta para no tocarlo.
  const right = MARGEN + 4
  const columna = { left: ancho - right - boton.w, right: ancho - right }
  const debajo = obstaculos.filter(o => Math.min(columna.right, o.right) - Math.max(columna.left, o.left) > 0)
  const techo = debajo.length ? Math.min(...debajo.map(o => o.top)) : Infinity
  return { top: Math.min(-Math.round(boton.h / 2), Math.floor(techo - 2 - boton.h)), right }
}

const transparente = (c) => !c || c === 'transparent' || /rgba?\([^)]*,\s*0\)$/.test(c.replace(/\s*\/\s*0\)$/, ', 0)'))
// Pastillas chicas y tarjetas de adentro (las de Brokers): el ✦ no se apoya
// sobre ninguna. La tarjeta que lo contiene (arranca arriba de todo) no cuenta.
function tieneCajaBarato(el, r, base, b) {
  const chica = r.height <= 2 * b.height && r.width < base.width * 0.6
  const tarjetaDeAdentro = r.top - base.top > MARGEN
  return (chica || tarjetaDeAdentro) && tieneCaja(el)
}
function tieneCaja(el) {
  const cs = getComputedStyle(el)
  return !transparente(cs.backgroundColor) || parseFloat(cs.borderTopWidth) > 0 || parseFloat(cs.borderLeftWidth) > 0
}

const QUE_ESQUIVA = new Set(['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA', 'IMG', 'CANVAS', 'svg'])

/**
 * lugarDelBoton — junta lo que hay en la franja de arriba de la tarjeta y
 * elige dónde va el ✦. `anchoLleno` = ancho de la pastilla con texto (celular),
 * por si ahora se está viendo achicada. Mide el TEXTO (no la caja del párrafo, que ocupa todo el
 * ancho aunque la palabra sea corta) y los botones, links e íconos.
 */
export function lugarDelBoton(tarjeta, boton, anchoLleno) {
  const base = tarjeta.getBoundingClientRect()
  const b = boton.getBoundingClientRect()
  if (!base.width || !b.width) return null
  const franja = MARGEN + b.height + SEPARACION
  const obstaculos = []
  const sumar = (r) => {
    if (!r.width || !r.height) return
    const o = { left: r.left - base.left, right: r.right - base.left, top: r.top - base.top, bottom: r.bottom - base.top }
    if (o.top < franja && o.bottom > 0) obstaculos.push(o)
  }
  const rango = document.createRange()
  const caminante = document.createTreeWalker(tarjeta, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      if (n === boton) return NodeFilter.FILTER_REJECT
      if (n.nodeType === 1) {
        const r = n.getBoundingClientRect()
        // Lo que empieza debajo de la franja no puede chocar: ni se recorre.
        if (r.height && r.top - base.top >= franja) return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    },
  })
  for (let n = caminante.nextNode(); n; n = caminante.nextNode()) {
    if (n.nodeType === 3) {
      if (!n.textContent.trim()) continue
      rango.selectNodeContents(n)
      for (const r of rango.getClientRects()) sumar(r)
    } else if (QUE_ESQUIVA.has(n.tagName)) {
      // Un botón o un link que envuelve la tarjeta entera (en Comportamiento cada
      // tarjeta ES un botón) no es un obstáculo: se esquiva lo que tiene adentro.
      // Igual un gráfico grande: se esquivan sus rótulos, no el lienzo entero.
      const r = n.getBoundingClientRect()
      if (r.height <= 2 * b.height) sumar(r)
    } else {
      // Una pastilla («Media», «Saludable», un chip): no alcanza con esquivar la
      // palabra, también su fondo, su borde y el puntito de color.
      const r = n.getBoundingClientRect()
      if (!r.height || !tieneCajaBarato(n, r, base, b)) continue
      sumar(r)
    }
  }
  return elegirLugar(base.width, { w: anchoLleno || b.width, h: b.height }, obstaculos, { w: b.height, h: b.height })
}
