// El botón «Ondas de Elliott» de la lectura técnica, montado de verdad
// (testing/navegadorMinimo.js) con /api/tecnico simulado en la frontera:
//   · prendido de entrada (Nico, 24/10: todo prendido y cada uno apaga lo que
//     no quiere): las etiquetas 1 a 5 sobre los puntos, la raya que invalida y
//     la tarjeta en castellano (qué es, dónde estaría hoy, qué lo invalida, la
//     confianza, otra lectura y la aclaración); el botón de la barra lo apaga;
//   · convive con el Fibonacci: los dos prendidos a la vez;
//   · sin conteo claro: lo dice, no dibuja nada y el botón queda deshabilitado.
// Y las palabras de cada estado (utils/elliott.js).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic } from '../../testing/navegadorMinimo'
import { tarjetaElliott, dondeHoy, veredictoElliott, textoInvalida } from '../../utils/elliott'

const puntos = Array.from({ length: 252 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 30 * Math.sin(i / 20)
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const onda = (o, i, precio, tipo) => ({ onda: o, fecha: puntos[i].d, precio, tipo })
const PRINCIPAL = {
  tipo: 'impulso', dir: 'suba', ahora: 'onda_5', confianza: 'alta',
  ondas: [onda('0', 120, 100, 'pozo'), onda('1', 140, 120, 'pico'), onda('2', 150, 108, 'pozo'),
    onda('3', 180, 140, 'pico'), onda('4', 200, 128, 'pozo')],
  invalida: { precio: 120, lado: 'debajo', por: 'final_1' },
  pautas: [{ id: 'onda2', valor: 0.6, cumple: true }, { id: 'onda3', valor: 1.6, cumple: true },
    { id: 'onda4', valor: 0.375, cumple: true }, { id: 'alternancia', valor: null, cumple: false }],
}
const ALTERNATIVO = { ...PRINCIPAL, ahora: 'onda_4', confianza: 'media', ondas: PRINCIPAL.ondas.slice(0, 4) }
const ELL = { disponible: true, n_pivote: 3, principal: PRINCIPAL, alternativo: ALTERNATIVO }
const FIB = { disponible: false, motivo: 'tramos_chicos', n_pivote: 3, ruedas: 252, en_curso: null }
const DATOS = (elliott) => ({
  disponible: true, moneda: 'usd', ticker: 'ZZEL', convertida: null, puntos, fibonacci: FIB, elliott,
  lectura: { ruedas: 252, fecha: puntos[251].d, precio: puntos[251].c, rsi: 50 },
})

let respuesta
vi.mock('../../utils/api', () => ({
  getClientContext: () => null,   // mirando tu propia cuenta (no la de un cliente)
  api: { get: vi.fn(() => Promise.resolve(respuesta)) },
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
// De fábrica el gráfico viene limpio (precio, promedio de 200 y volumen). Estas
// pruebas miran las demás capas: arrancan con todas prendidas, como quien las
// prende desde «Indicadores» (lo que se prende queda guardado así).
beforeEach(() => { try { localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS)) } catch { /* sin almacenamiento */ } })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})

const el = () => h(LecturaTecnica, { asset: 'ZZEL' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

// Un botón por su `data-capa` (la barra, su menú o el ojito de la lista).
function porCapa(id) {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
// Fibonacci y Elliott: el automático y el «a mano» viven en el menú de su botón.
async function enElMenu(menu, opcion) {
  await clic(montado.contenedor, porCapa(menu))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  const b = porCapa(opcion)
  return b
}
async function tocar(nombre) {
  // El automático se prende y se apaga desde el menú del botón «Ondas de Elliott».
  await clic(montado.contenedor, nombre === 'Ondas de Elliott' ? await enElMenu('menu-elliott', 'ell') : buscarBoton(montado.contenedor, nombre))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Ondas de Elliott en la ficha', () => {
  it('prendido de entrada: etiquetas, raya y tarjeta; el botón lo apaga', async () => {
    respuesta = DATOS(ELL)
    const t = await dibujar()
    expect((await enElMenu('menu-elliott', 'ell')).getAttribute('aria-checked')).toBe('true')
    await clic(montado.contenedor, porCapa('menu-elliott'))   // lo cierra
    expect(t).toContain('Un conteo posible: onda 5')
    expect(t).toContain('La teoría de Elliott dice que el precio suele avanzar en 5 ondas')
    expect(t).toContain('Según un conteo posible, el precio podría estar en la onda 5, que en la teoría es la última de la suba.')
    expect(t).toContain('Si el precio baja de US$ 120,00 (donde terminó la onda 1), este conteo dejaría de tener sentido')
    expect(t).toContain('Confianza alta: cumple 3 de 4 proporciones que suelen darse.')
    expect(t).toContain('La onda 2 devolvió el 60 % de la 1')
    expect(t).toContain('Otra lectura posible: el precio podría estar en la onda 4')
    expect(t).toContain('Es una de varias lecturas posibles')
    expect(t).toContain('no es una recomendación')
    expect(t).toContain('El conteo dejaría de valer · US$ 120,00')
    for (const n of ['1', '2', '3', '4']) expect(t).toContain(n)
    // Apagarlo lo saca, y volverlo a prender lo trae.
    const despues = await tocar('Ondas de Elliott')
    expect(despues).not.toContain('Un conteo posible')
    expect(despues).not.toContain('El conteo dejaría de valer')
    expect((await enElMenu('menu-elliott', 'ell')).getAttribute('aria-checked')).toBe('false')
    await clic(montado.contenedor, porCapa('menu-elliott'))
    expect(await tocar('Ondas de Elliott')).toContain('El conteo dejaría de valer · US$ 120,00')
  })

  it('convive con el Fibonacci: los dos prendidos', async () => {
    // Los dos arrancan prendidos (24/10).
    respuesta = DATOS(ELL)
    const t = await dibujar()
    expect(t).toContain('Sin tramo claro')               // la tarjeta del Fibonacci
    expect(t).toContain('Un conteo posible: onda 5')
  })

  it('sin conteo claro: lo dice y no dibuja nada', async () => {
    respuesta = DATOS({ disponible: false, motivo: 'sin_conteo', n_pivote: 3, ruedas: 252 })
    const t = await dibujar()
    expect(t).toContain('Sin conteo claro')
    expect(t).not.toContain('El conteo dejaría de valer')
    // El botón queda, deshabilitado; tocarlo dice por qué (en el celular no hay globo).
    const opcion = await enElMenu('menu-elliott', 'ell')
    expect(opcion.getAttribute('aria-disabled')).toBe('true')
    expect(opcion.getAttribute('aria-checked')).toBeNull()
    await clic(montado.contenedor, opcion)
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    const aviso = texto(montado.contenedor)
    expect(aviso).toContain('Ondas de Elliott (automático): Con los picos y pozos de este activo no aparece ningún conteo')
    expect(aviso).not.toContain('El conteo dejaría de valer')
  })

  it('una respuesta vieja sin el campo: el botón deshabilitado y nada dibujado', async () => {
    respuesta = DATOS(undefined)
    const t = await dibujar()
    expect((await enElMenu('menu-elliott', 'ell')).getAttribute('aria-disabled')).toBe('true')
    expect(t).not.toContain('Un conteo posible')
  })
})

describe('las palabras de cada estado', () => {
  const fecha = (d) => d
  const precio = (x) => `$ ${x}`
  const con = (extra) => ({ ...PRINCIPAL, ...extra })

  it('dónde estaría hoy', () => {
    expect(dondeHoy(con({ ahora: 'onda_3' }), fecha)).toBe('el precio podría estar en la onda 3 de la suba, que en la teoría suele ser la más larga')
    expect(dondeHoy(con({ ahora: 'onda_3', dir: 'bajada' }), fecha)).toContain('onda 3 de la bajada')
    const cinco = con({ ahora: 'correccion', ondas: [...PRINCIPAL.ondas, onda('5', 220, 150, 'pico')] })
    expect(dondeHoy(cinco, fecha)).toBe(`las 5 ondas de la suba podrían haber terminado el ${puntos[220].d}, y el precio podría estar en la corrección que en la teoría suele venir después`)
    const abc = { tipo: 'correccion', dir: 'bajada', ahora: 'fin_abc', ondas: [onda('0', 1, 120), onda('A', 2, 100), onda('B', 3, 110), onda('C', 4, 90)] }
    expect(dondeHoy(abc, fecha)).toBe(`la corrección a la baja, después de una suba (A, B y C) podría haber terminado el ${puntos[4].d}`)
    expect(dondeHoy({ ...abc, ahora: 'onda_C' }, fecha)).toBe('el precio podría estar en la onda C de la corrección a la baja, después de una suba, que en la teoría es su último tramo')
    expect(veredictoElliott(abc)).toBe('Un conteo posible: fin de una corrección A-B-C')
    expect(veredictoElliott(null)).toBe('Sin conteo claro')
  })

  it('qué lo invalida, en los dos sentidos', () => {
    expect(textoInvalida(con({ invalida: { precio: 100, lado: 'debajo', por: 'arranque_1' } }), precio))
      .toBe('Si el precio baja de $ 100 (donde arrancó la onda 1), este conteo dejaría de tener sentido: en la teoría, la onda 2 no va más allá de ese punto.')
    expect(textoInvalida(con({ invalida: { precio: 150, lado: 'encima', por: 'final_5' } }), precio))
      .toContain('Si el precio sube de $ 150 (el final de la onda 5), esta lectura dejaría de tener sentido')
  })

  it('el segundo nivel que también lo corta, del otro lado', () => {
    const c = con({ ahora: 'correccion', invalida: { precio: 150, lado: 'encima', por: 'final_5',
      otro: { precio: 100, lado: 'debajo', por: 'arranque_1' } } })
    expect(textoInvalida(c, precio)).toContain('Y también si baja de $ 100 (donde arrancó la onda 1): sería devolver todo el movimiento de 5 ondas.')
    const tope = con({ invalida: { precio: 120, lado: 'debajo', por: 'final_1', otro: { precio: 155, lado: 'encima', por: 'tope_3_corta' } } })
    expect(textoInvalida(tope, precio)).toContain('También dejaría de tener sentido si sube de $ 155')
  })

  it('lo que puede pasar se dice como posibilidad, en todos los estados (Nico, 23/10)', () => {
    // Si vuelve alguna de estas, el texto está hablando como si supiera qué va a pasar.
    const CERTEZA = /\b(va a|van a|se invalida|terminaron|termina en|suele terminar|seguro|seguramente|sin duda|se da por|ya hizo|Terminó una)\b/i
    const otros = {
      onda_5: { precio: 155, lado: 'encima', por: 'tope_3_corta' }, correccion: { precio: 100, lado: 'debajo', por: 'arranque_1' },
      onda_B: { precio: 100, lado: 'debajo', por: 'arranque_1' }, onda_C: { precio: 90, lado: 'debajo', por: 'borro_lo_corregido' },
      fin_abc: { precio: 120, lado: 'encima', por: 'arranque_A' },
    }
    const por = { onda_3: 'arranque_1', onda_4: 'final_1', onda_5: 'final_1', correccion: 'final_5', onda_B: 'arranque_A', onda_C: 'arranque_A', fin_abc: 'final_C' }
    const ondas = [...PRINCIPAL.ondas, onda('5', 220, 150, 'pico'), onda('A', 230, 130, 'pozo'), onda('B', 240, 140, 'pico'), onda('C', 250, 120, 'pozo')]
    for (const ahora of Object.keys(por)) {
      for (const tipo of ['impulso_y_correccion', 'correccion']) {
        const c = { ...PRINCIPAL, tipo, ahora, ondas, invalida: { precio: 110, lado: 'debajo', por: por[ahora], otro: otros[ahora] || null } }
        const t = tarjetaElliott({ disponible: true, principal: c, alternativo: c }, precio, fecha)
        for (const parte of [t.veredicto, t.texto, t.invalida, t.alternativo]) {
          expect(parte, `${ahora}/${tipo}: ${parte}`).not.toMatch(CERTEZA)
        }
      }
    }
  })

  it('nunca recomienda ni promete', () => {
    const t = tarjetaElliott(ELL, precio, fecha)
    // Todo menos la aclaración del pie (que dice justamente «no es una recomendación de compra»).
    const todo = [t.texto, t.invalida, t.confianza, t.alternativo, ...t.pautas.map(p => p.texto)].join(' ')
    expect(todo).not.toMatch(/\b(compr[áa]|vend[ée]|va a (subir|bajar)|seguro)\b/i)
    expect(t.pie).toContain('No dice qué va a pasar')
  })
})

describe('la zona de fin de onda se sacó (23/10: acertaba menos que una franja al azar)', () => {
  const precio = (x) => `US$ ${x}`
  // Un servidor viejo podría todavía mandarla: la pantalla no la dibuja ni la dice.
  const conZona = { ...ELL, principal: { ...PRINCIPAL, zona: { desde: 150, hasta: 160, aciertos: 30, casos: 60, tonta: 20, activos: 42 } } }

  it('ni en la tarjeta ni en el gráfico, aunque llegue', async () => {
    const t = tarjetaElliott(conZona, precio, (d) => d)
    expect(t.zona).toBeUndefined()
    expect(Object.values(t).join(' ')).not.toMatch(/terminar acá|podría terminar entre|franja/)
    respuesta = DATOS(conZona)
    const vis = await dibujar()
    expect(vis).toContain('Un conteo posible: onda 5')            // el conteo sigue
    expect(vis).toContain('El conteo dejaría de valer · US$ 120,00')
    expect(vis).not.toMatch(/terminar acá|acertó/)
  })

  it('tampoco estira la escala del gráfico', async () => {
    const { preciosDelConteo } = await import('./CapaElliott')
    expect(preciosDelConteo(conZona, puntos)).not.toContain(160)
    expect(preciosDelConteo(conZona, puntos)).toContain(120)
  })
})
