// escalaPrecio.js — la regla con la que el gráfico técnico pone un precio a una altura.
// ════════════════════════════════════════════════════════════════════════════
// Dos escalas (pedido de un usuario, Nico 12/11):
// · 'lineal' (la de siempre): cada renglón del eje SUMA la misma plata (100, 200,
//   300). La altura es proporcional al precio.
// · 'log' (logarítmica): cada renglón MULTIPLICA (100, 200, 400). La altura es
//   proporcional al logaritmo del precio: una suba del 50 % mide lo mismo en
//   cualquier parte del gráfico. Sólo existe para precios mayores que cero.
//
// Todo lo que pasa de precio a altura o de altura a precio —el gráfico de la
// ficha, el precio bajo el mouse, arrastrar un dibujo o el eje, y la imagen de
// «Compartir» (utils/imagenGrafico.js)— pasa por acá. Antes la misma cuenta
// estaba copiada en cuatro lugares; con dos escalas, una copia que se quedara
// en lineal dibujaría cosas en otro lugar que las demás.
//
// La cuenta se hace en el «eje»: el precio mismo en lineal, su logaritmo en
// log. En el eje las dos escalas son rectas: márgenes, arrastres y rangos se
// calculan ahí y se vuelven a precio al final.
//
// Tus líneas de tendencia y canales recuerdan en qué escala los dibujaste
// (`escala` del dibujo, utils/dibujos.js; sin ella, lineal): una línea es recta
// en SU escala. `precioEnLaRecta` es esa cuenta, la misma que hace el servidor
// para los avisos (backend/tecnico.valor_de_linea).

export const ESCALA_DE_FABRICA = 'lineal'

/** El tope del ancho de un canal logarítmico: su paralela multiplica por
 *  e^ancho, y más de e^20 (500 millones de veces) no es un canal. El mismo que
 *  el servidor (backend/tecnico.ANCHO_LOG_MAXIMO). */
export const ANCHO_LOG_MAXIMO = 20

// Hasta dónde se va lo que no tiene altura (ver armarEscala): mil veces el alto.
const FUERA = 1000

/** ¿Es la logarítmica? Cualquier otra cosa (null, undefined, un valor viejo) es lineal. */
export const esLog = (escala) => escala === 'log'

/** La escala de un valor guardado: 'log' o 'lineal' (lo desconocido, lineal). */
export const escalaDe = (valor) => (esLog(valor) ? 'log' : 'lineal')

/** El precio en el eje: él mismo en lineal, su logaritmo en log. */
export function aEje(precio, escala) {
  return esLog(escala) ? Math.log(precio) : precio
}

/** Del eje al precio (la vuelta de `aEje`). */
export function deEje(u, escala) {
  return esLog(escala) ? Math.exp(u) : u
}

/** ¿Se puede poner este precio en esta escala? En log, sólo mayores que cero. */
export function cabeEnLaEscala(precio, escala) {
  return Number.isFinite(precio) && (!esLog(escala) || precio > 0)
}

/**
 * La escala de un gráfico de `alto` unidades que muestra de `lo` (abajo) a `hi`
 * (arriba): `y(precio)` es la distancia desde arriba (0 = arriba, `alto` =
 * abajo) y `precio(y)` la vuelta. `fraccion(precio)` es lo mismo de 0 a 1.
 */
export function armarEscala(lo, hi, alto, escala) {
  const a = aEje(lo, escala), b = aEje(hi, escala)
  const largo = b - a || 1
  // En log, un precio de cero o menos (una vela con el mínimo en 0, un nivel
  // de Fibonacci bajo cero, una línea de la escala de siempre que cruza el
  // cero) está infinitamente abajo: va muy por debajo del borde, nunca a un
  // «NaN» o un «Infinity» que el navegador no dibuja (y corta la línea entera).
  const fraccion = (precio) => {
    const f = 1 - (aEje(precio, escala) - a) / largo
    return Number.isFinite(f) || Number.isNaN(precio) ? f : f > 0 ? FUERA : -FUERA
  }
  return {
    escala: escalaDe(escala), lo, hi, alto,
    fraccion,
    y: (precio) => fraccion(precio) * alto,
    precio: (y) => deEje(a + (1 - y / alto) * largo, escala),
  }
}

/** Lo que mide el rango [lo, hi] en el eje (para pasar un arrastre de pantalla a eje). */
export function largoEnEje(lo, hi, escala) {
  return aEje(hi, escala) - aEje(lo, escala)
}

/** Un precio corrido `du` en el eje (un arrastre en pantalla): en lineal suma
 *  plata, en log multiplica. En lineal nunca llega a 0 (arrastrar una línea muy
 *  abajo la deja en el piso); en log no hace falta: nunca llega. */
export function precioCorrido(precio, du, escala) {
  if (esLog(escala)) return precio * Math.exp(du)
  return Math.max(precio + du, precio * 0.02)
}

/** [lo, hi] con aire: un `margen` (fracción del rango) arriba y abajo, y
 *  `abajo` más abajo (el lugar del volumen), todo en el eje. */
export function rangoConAire(lo, hi, escala, margen = 0.08, abajo = 0) {
  let a = aEje(lo, escala), b = aEje(hi, escala)
  // Sin rango (un solo precio): un poquito alrededor.
  const m = (b - a) * margen || (esLog(escala) ? 0.02 : Math.abs(b) * 0.02) || 1
  a -= m; b += m
  if (abajo) a -= (b - a) * abajo
  return [deEje(a, escala), deEje(b, escala)]
}

/** ¿`precio` está lejos de [lo, hi]? Más de `tolerancia` (fracción del rango,
 *  medida en el eje) por debajo: 'abajo'; por arriba: 'arriba'; si no, null. */
export function ladoDeAfuera(precio, lo, hi, escala, tolerancia) {
  if (!cabeEnLaEscala(precio, escala)) return 'abajo'
  const a = aEje(lo, escala), b = aEje(hi, escala), p = aEje(precio, escala)
  const rango = b - a || Math.abs(b) * 0.1 || 1
  if (p < a - rango * tolerancia) return 'abajo'
  if (p > b + rango * tolerancia) return 'arriba'
  return null
}

/**
 * El precio de una recta que pasa por `a` y `b` ({ k, precio }: el lugar y el
 * precio) en el lugar `k`, recta en `escala`: en lineal sube la misma plata
 * por lugar; en log, el mismo porcentaje. Con a y b en el mismo lugar, el de a.
 */
export function precioEnLaRecta(a, b, k, escala) {
  if (b.k === a.k) return a.precio
  const ua = aEje(a.precio, escala), ub = aEje(b.precio, escala)
  return deEje(ua + ((ub - ua) * (k - a.k)) / (b.k - a.k), escala)
}

/** Un precio corrido una distancia `ancho` en el eje de `escala` (la paralela
 *  de un canal): en lineal, `ancho` es plata; en log, el logaritmo de cuánto
 *  multiplica. */
export function precioMasAncho(precio, ancho, escala) {
  return deEje(aEje(precio, escala) + ancho, escala)
}

// ─── Los rótulos del eje en logarítmica ──────────────────────────────────────
// Números redondos que se reparten multiplicando (1, 2, 5, 10, 20, 50…). Se
// elige el juego más tupido que deja al menos `cadaPx` entre dos rótulos. Con
// un rango angosto (acercado a unas semanas) ningún juego de esos deja más de
// uno o dos: ahí la logarítmica casi no se distingue de la lineal, y van los
// precios redondos parejos de siempre, sin los que quedarían pisados.

const JUEGOS_LOG = [[1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8], [1, 1.5, 2, 3, 4, 5, 7], [1, 2, 3, 5, 7], [1, 2, 5], [1, 3], [1]]

/** Los precios redondos para la columna en logarítmica, entre `lo` y `hi`, en un
 *  gráfico de `altoPx`. `parejos(lo, hi, altoPx)`: los rótulos de la lineal. */
export function marcasLog(lo, hi, altoPx, parejos, cadaPx = 40) {
  if (!(hi > lo) || !(lo > 0) || !(altoPx > 0)) return []
  const esc = armarEscala(lo, hi, altoPx, 'log')
  const separadas = (lista) => lista.every((v, i) => i === 0 || esc.y(lista[i - 1]) - esc.y(v) >= cadaPx)
  const minimo = Math.max(3, Math.floor(altoPx / (cadaPx * 3)))
  for (const juego of JUEGOS_LOG) {
    const out = []
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)) && out.length < 80; e++) {
      for (const m of juego) {
        const v = Number((m * Math.pow(10, e)).toPrecision(6))
        if (v >= lo && v <= hi) out.push(v)
      }
    }
    if (out.length >= 2 && separadas(out)) {
      if (out.length >= minimo) return out
      break
    }
  }
  // Rango angosto: los parejos, sacando los que quedarían pisados (de abajo hacia arriba).
  const out = []
  for (const v of parejos(lo, hi, altoPx)) {
    if (!(v > 0)) continue
    if (!out.length || esc.y(out[out.length - 1]) - esc.y(v) >= cadaPx * 0.75) out.push(v)
  }
  return out
}
