// Las notas de texto del gráfico y las banderitas de tu tesis (Nico, 30/10),
// montadas de verdad (testing/navegadorMinimo.js) con /api/tecnico simulado
// en la frontera y con clicks, toques y teclas como los manda el navegador:
//   · «Nota»: tocás un punto y escribís; sin texto no se guarda; hasta 280
//     letras (un emoji es una); se guarda en tu cuenta con los dibujos;
//   · la banderita se toca para leerla entera, corregirla, colorearla o
//     borrarla; se arrastra; deshacer/rehacer la incluyen;
//   · las que se pisarían se juntan en una con el número (también a 375 px);
//   · tu tesis aparece como banderita en el día en que la escribiste, en las
//     dos monedas, sin copiarse a tus dibujos; tocarla lleva a editarla.
// Que la imagen de «Compartir» no las lleve: CompartirGrafico.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, buscarBoton, escribir, tecla } from '../../testing/navegadorMinimo'
import { elegirEnLaVista } from '../../testing/menuGrafico'
import { margenDerecho } from '../../utils/tecnico'
import { banderitaEn } from './NotasGrafico'

const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 20 * Math.sin(i / 40) + i * 0.05
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZEV', convertida: null, puntos,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
}

const cuenta = { usd: [], ars: [], puts: 0, cliente: null, ultimoPut: null }
const monedaDe = (ruta) => (ruta.includes('moneda=ars') ? 'ars' : 'usd')
vi.mock('../../utils/api', () => ({
  // null: tu propia cuenta; { id }: un asesor mirando la de un cliente.
  getClientContext: () => cuenta.cliente,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    get: vi.fn((ruta) => Promise.resolve(ruta.includes('/dibujos') ? { dibujos: cuenta[monedaDe(ruta)] }
      : ruta.startsWith('/alerts') ? { items: [] }
        : ruta.includes('/eventos') ? { eventos: [] } : DATOS)),
    post: vi.fn(() => Promise.resolve({ ok: true })),
    patch: vi.fn(() => Promise.resolve({ ok: true })),
    put: vi.fn((ruta, body) => { cuenta.puts++; cuenta.ultimoPut = body; cuenta[monedaDe(ruta)] = body.dibujos; return Promise.resolve({ ok: true }) }),
  },
}))

let ANCHO = 1000
let LecturaTecnica, MemoryRouter
beforeAll(async () => {
  // Antes de cargar React (el router lo trae): si no, React cree que este
  // navegador no tiene el evento `input` y escribir en el campo no le llega.
  instalarNavegadorMinimo()
  medidas(() => ({ left: 0, top: 0, width: ANCHO, height: 250, right: ANCHO, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
  ;({ MemoryRouter } = await import('react-router-dom'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado, props
beforeEach(() => {
  localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
  // Ana logueada en su cuenta: los dibujos del navegador son a su nombre (utils/dibujos.js).
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@prueba.test' }))
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  ANCHO = 1000
  localStorage.clear()
  Object.assign(cuenta, { usd: [], ars: [], puts: 0, cliente: null, ultimoPut: null })
})
const el = () => h(MemoryRouter, null, h(LecturaTecnica, { asset: 'ZZEV', ...props }))
async function dibujar(p = {}) {
  props = p
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}
async function redibujar() { for (let i = 0; i < 2; i++) await montado.redibujar(el()) }

function todos(nodo, ok) {
  const out = [], pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (ok(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
async function evento(tipo, nodo, datos = {}) {
  await enActo(async () => {
    const ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true }, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
}
const grafico = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'img' && n.getAttribute('aria-label')?.startsWith('Precio con su promedio'))[0]
async function clickEn(x, y = 100) {
  await evento('mousedown', grafico(), { clientX: x, clientY: y })
  await evento('mouseup', grafico(), { clientX: x, clientY: y })
  await redibujar()
}
async function toqueEn(x, y) {
  const t = { touches: [{ clientX: x, clientY: y }], changedTouches: [{ clientX: x, clientY: y }] }
  await evento('touchstart', grafico(), t)
  await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: x, clientY: y }] })
  await redibujar()
}
async function deslizar(x0, y0, x1, y1) {
  const t = (x, y) => ({ touches: [{ clientX: x, clientY: y }], changedTouches: [{ clientX: x, clientY: y }] })
  await evento('touchstart', grafico(), t(x0, y0))
  await evento('touchmove', grafico(), t((x0 + x1) / 2, (y0 + y1) / 2))
  await evento('touchmove', grafico(), t(x1, y1))
  await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: x1, clientY: y1 }] })
  await redibujar()
}
async function arrastrar(x0, y0, x1, y1) {
  await evento('mousedown', grafico(), { clientX: x0, clientY: y0 })
  await evento('mousemove', grafico(), { clientX: (x0 + x1) / 2, clientY: (y0 + y1) / 2 })
  await evento('mousemove', grafico(), { clientX: x1, clientY: y1 })
  await evento('mouseup', grafico(), { clientX: x1, clientY: y1 })
  await redibujar()
}
const teclaVentana = (key, extra = {}) => enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key, ...extra })) })
const LUGARES = 700 + margenDerecho(700)
const bajo = (x) => Math.round((x / 1000) * (LUGARES - 1))
const boton = (id) => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id)[0]
const banderitas = () => todos(montado.contenedor, n => n.getAttribute?.('data-banderita') != null)
const cartel = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'group' && /^Tu nota/.test(n.getAttribute('aria-label') || ''))[0]
const campo = () => todos(montado.contenedor, n => n.nodeName === 'TEXTAREA')[0]
const status = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'status').map(n => texto(n)).join(' ')
const guardar = (parte = 'Guardar') => buscarBoton(cartel(), parte)
// La banderita va arriba de su punto: su cuadradito, 20 px más arriba.
const ARRIBA = 20

// Una nota en (x, y): la herramienta, el toque y el texto.
async function anotar(x, y, txt) {
  await clic(montado.contenedor, boton('nota')); await redibujar()
  await clickEn(x, y)
  await escribir(campo(), txt); await redibujar()
  await clic(montado.contenedor, guardar()); await redibujar()
}

describe('la herramienta «Nota»', () => {
  it('tocás un punto, escribís y queda una banderita en ese día y ese precio, guardada en tu cuenta', async () => {
    await dibujar()
    // En la barra, con los dibujos (al lado de «Líneas y pincel»).
    const barra = todos(montado.contenedor, n => n.getAttribute?.('role') === 'toolbar')[0]
    const ids = todos(barra, n => n.nodeName === 'BUTTON').map(n => n.getAttribute('data-capa'))
    expect(ids.indexOf('nota')).toBe(ids.indexOf('menu-lineas') + 1)
    await clic(montado.contenedor, boton('nota')); await redibujar()
    expect(boton('nota').getAttribute('aria-pressed')).toBe('true')
    expect(status()).toContain('Tocá el punto del gráfico donde va tu nota')
    await clickEn(400, 100)
    // La banderita provisoria, y el campo para escribir.
    expect(banderitas().map(b => b.getAttribute('data-banderita'))).toEqual(['__nota__'])
    expect(campo()).toBeTruthy()
    expect(guardar().getAttribute('disabled')).not.toBeNull()          // sin texto no se guarda
    // Tocar otro punto la cambia de lugar (todavía no se guardó nada).
    await clickEn(420, 100)
    expect(cuenta.puts).toBe(0)
    await escribir(campo(), 'compré acá por el balance'); await redibujar()
    expect(texto(cartel())).toContain('25 de 280 letras')
    await clic(montado.contenedor, guardar()); await redibujar()
    expect(cuenta.usd).toHaveLength(1)
    const [n] = cuenta.usd
    expect(n).toMatchObject({ tipo: 'nota', texto: 'compré acá por el balance', a: { d: puntos[bajo(420)].d, mas: 0 } })
    expect(n.a.precio).toBeGreaterThan(0)
    expect(banderitas().map(b => b.getAttribute('data-banderita'))).toEqual([n.id])
    expect(boton('nota').getAttribute('aria-pressed')).toBe('false')   // una nota por vez
    // Avisa que conoce las notas: sin eso, el servidor no las toca (una
    // pestaña vieja, que no sabe qué son, las borraría al guardar).
    expect(cuenta.ultimoPut.notas).toBe(true)
    // Otra visita: vuelve (está en tu cuenta).
    await montado.desmontar(); localStorage.removeItem('rendi_dibujos:ana@prueba.test|propia:ZZEV:usd')
    await dibujar()
    expect(banderitas().map(b => b.getAttribute('data-banderita'))).toEqual([n.id])
  })

  it('sin texto (o sólo espacios) no se guarda; Esc cancela', async () => {
    await dibujar()
    await clic(montado.contenedor, boton('nota')); await redibujar()
    await clickEn(400, 100)
    await escribir(campo(), '   \n  '); await redibujar()
    expect(guardar().getAttribute('disabled')).not.toBeNull()
    await clic(montado.contenedor, guardar()); await redibujar()
    expect(cuenta.puts).toBe(0)
    await tecla(campo(), 'Escape'); await redibujar()
    expect(campo()).toBeUndefined()
    expect(banderitas()).toHaveLength(0)
    expect(cuenta.puts).toBe(0)
  })

  it('hasta 280 letras, contando un emoji como una (sin partirlo); emojis, comillas, HTML y dos renglones vuelven tal cual', async () => {
    await dibujar()
    await clic(montado.contenedor, boton('nota')); await redibujar()
    await clickEn(400, 100)
    await escribir(campo(), '🚀'.repeat(300)); await redibujar()
    expect(texto(cartel())).toContain('280 de 280 letras')
    await clic(montado.contenedor, guardar()); await redibujar()
    expect(Array.from(cuenta.usd[0].texto)).toHaveLength(280)
    expect(cuenta.usd[0].texto).toBe('🚀'.repeat(280))
    const raro = 'Ojo 👨‍👩‍👧 «el balance» "dijo" <b>no</b> & \'ya\'\nsegundo renglón'
    await anotar(800, 200, raro)
    expect(cuenta.usd[1].texto).toBe(raro)
    // Al tocarla, se lee entera y como texto (el <b> no es negrita).
    await clickEn(800, 200 - ARRIBA)
    const p = todos(cartel(), n => n.getAttribute?.('data-texto-nota') === '')[0]
    expect(texto(p)).toBe(raro)
    expect(todos(p, n => n.nodeName === 'B')).toHaveLength(0)
    expect(p.getAttribute('class')).toContain('whitespace-pre-line')
    expect(p.getAttribute('class')).not.toContain('line-clamp')
  })
})

describe('la banderita', () => {
  it('se toca para leerla, corregirla, cambiarle el color y borrarla; deshacer y rehacer la incluyen', async () => {
    await dibujar()
    await anotar(400, 100, 'compré acá')
    const id = cuenta.usd[0].id
    await clickEn(400, 100 - ARRIBA)
    expect(texto(cartel())).toContain('Tu nota')
    expect(texto(cartel())).toContain('compré acá')
    // Corregirla.
    await clic(montado.contenedor, buscarBoton(cartel(), 'Editar')); await redibujar()
    expect(campo().value).toBe('compré acá')
    await escribir(campo(), 'compré acá por el balance'); await redibujar()
    await clic(montado.contenedor, guardar('Guardar cambios')); await redibujar()
    expect(cuenta.usd[0]).toMatchObject({ id, texto: 'compré acá por el balance' })
    // El color.
    await clic(montado.contenedor, todos(cartel(), n => n.getAttribute?.('data-color') === 'rosa')[0]); await redibujar()
    expect(cuenta.usd[0].color).toBe('rosa')
    // Borrarla, y volverla con Cmd+Z: el color, después el texto de antes.
    await clic(montado.contenedor, buscarBoton(cartel(), 'Borrar esta nota')); await redibujar()
    expect(cuenta.usd).toEqual([])
    expect(banderitas()).toHaveLength(0)
    await teclaVentana('z', { metaKey: true }); await redibujar()
    expect(cuenta.usd[0]).toMatchObject({ id, texto: 'compré acá por el balance', color: 'rosa' })
    await teclaVentana('z', { metaKey: true }); await redibujar()
    expect(cuenta.usd[0].color).toBeUndefined()
    await teclaVentana('z', { metaKey: true }); await redibujar()
    expect(cuenta.usd[0].texto).toBe('compré acá')
    await teclaVentana('z', { metaKey: true }); await redibujar()
    expect(cuenta.usd).toEqual([])                                    // ni la nota
    await teclaVentana('z', { metaKey: true, shiftKey: true }); await redibujar()
    expect(cuenta.usd[0].texto).toBe('compré acá')
  })

  it('al corregirla, sin texto no se guarda y Esc deja la que estaba', async () => {
    await dibujar()
    await anotar(400, 100, 'mi idea')
    await clickEn(400, 100 - ARRIBA)
    await clic(montado.contenedor, buscarBoton(cartel(), 'Editar')); await redibujar()
    await escribir(campo(), '  '); await redibujar()
    expect(guardar('Guardar cambios').getAttribute('disabled')).not.toBeNull()
    await tecla(campo(), 'Escape'); await redibujar()
    expect(campo()).toBeUndefined()
    expect(cuenta.usd[0].texto).toBe('mi idea')
    expect(texto(cartel())).toContain('mi idea')                       // sigue elegida
  })

  it('se arrastra a otro día y otro precio, como los otros dibujos; deshacer la vuelve', async () => {
    await dibujar()
    await anotar(400, 100, 'mi idea')
    const antes = cuenta.usd[0].a
    await arrastrar(400, 100 - ARRIBA, 600, 150 - ARRIBA)
    const despues = cuenta.usd[0].a
    expect(despues.d).toBe(puntos[bajo(400) + Math.round((200 / 1000) * (LUGARES - 1))].d)
    expect(despues.precio).toBeLessThan(antes.precio)                 // más abajo, más barato
    expect(banderitas().map(b => b.getAttribute('data-banderita'))).toEqual([cuenta.usd[0].id])
    await teclaVentana('z', { ctrlKey: true }); await redibujar()
    expect(cuenta.usd[0].a).toEqual(antes)
  })

  it('con el dedo: tocarla la elige; recién elegida se arrastra (si no, deslizar la página la agarraría)', async () => {
    await dibujar()
    await anotar(400, 100, 'mi idea')
    const antes = cuenta.usd[0].a
    // Sin elegir: deslizar el dedo desde la banderita no la mueve.
    await deslizar(400, 100 - ARRIBA, 600, 100 - ARRIBA)
    expect(cuenta.usd[0].a).toEqual(antes)
    await toqueEn(405, 100 - ARRIBA + 6)                               // el dedo tiene más margen
    expect(texto(cartel())).toContain('mi idea')
    // Elegida, sí.
    await deslizar(405, 100 - ARRIBA, 605, 100 - ARRIBA)
    expect(cuenta.usd[0].a.d).toBe(puntos[bajo(400) + Math.round((200 / 1000) * (LUGARES - 1))].d)
  })

  it('las que se pisarían se juntan en una con el número; tocarla las lista y elegir una la saca del grupo', async () => {
    await dibujar()
    await anotar(400, 100, 'primera')
    await anotar(410, 105, 'segunda')                                  // 10 px al lado
    await anotar(800, 100, 'lejos')
    const b = banderitas()
    expect(b).toHaveLength(2)
    const grupo = b.find(x => x.getAttribute('data-tipo') === 'grupo')
    expect(texto(grupo)).toBe('2')
    await clickEn(400, 100 - ARRIBA)
    expect(texto(cartel())).toContain('Acá hay 2 banderitas juntas')
    expect(texto(cartel())).toContain('primera')
    expect(texto(cartel())).toContain('segunda')
    const segunda = cuenta.usd.find(n => n.texto === 'segunda')
    await clic(montado.contenedor, todos(cartel(), n => n.getAttribute?.('data-elegir') === segunda.id)[0]); await redibujar()
    expect(texto(cartel())).toContain('segunda')
    expect(banderitas().map(x => x.getAttribute('data-banderita')).sort()).toEqual(cuenta.usd.map(n => n.id).sort())
    // La tecla Suprimir con el GRUPO elegido no borra nada.
    await clickEn(100, 20)                                             // suelta
    await clickEn(400, 100 - ARRIBA)
    await teclaVentana('Delete'); await redibujar()
    expect(cuenta.usd).toHaveLength(3)
  })

  it('a 375 px (el celular) se juntan las que ahí se pisarían, aunque en la compu entren separadas', async () => {
    await dibujar()
    await anotar(400, 100, 'una')
    await anotar(440, 100, 'otra')                                     // 40 px: en la compu, separadas
    expect(banderitas()).toHaveLength(2)
    await montado.desmontar()
    ANCHO = 375
    await dibujar()
    // Al celular entra lo reciente: se acerca con «Todo» para tener el mismo período.
    await elegirEnLaVista(montado.contenedor, 'Todo'); await redibujar()
    const b = banderitas()
    expect(b).toHaveLength(1)
    expect(texto(b[0])).toBe('2')
  })

  it('en pesos no está la nota de dólares (son precios distintos), como los otros dibujos', async () => {
    await dibujar()
    await anotar(400, 100, 'en dólares')
    await elegirEnLaVista(montado.contenedor, 'Pesos'); await redibujar(); await redibujar()
    expect(banderitas()).toHaveLength(0)
    expect(cuenta.ars).toEqual([])
  })
})

describe('lo que encontró la auditoría (30/10)', () => {
  it('escribiendo una nota con otra elegida: prender «Nota» la suelta, y Suprimir o Cmd+Z no tocan tus dibujos', async () => {
    await dibujar()
    await anotar(400, 100, 'la vieja')
    await clickEn(400, 100 - ARRIBA)                                   // elegida
    expect(texto(cartel())).toContain('la vieja')
    await clic(montado.contenedor, boton('nota')); await redibujar()
    await clickEn(700, 150)
    await escribir(campo(), 'la nueva a medias'); await redibujar()
    await clickEn(720, 150)                                            // la cambia de lugar: el foco sale del campo
    await teclaVentana('Delete'); await redibujar()
    await teclaVentana('z', { metaKey: true }); await redibujar()
    expect(cuenta.usd.map(n => n.texto)).toEqual(['la vieja'])
    expect(campo().value).toBe('la nueva a medias')                    // lo escrito sigue ahí
    await clic(montado.contenedor, guardar()); await redibujar()
    expect(cuenta.usd.map(n => n.texto)).toEqual(['la vieja', 'la nueva a medias'])
  })

  it('cambiar de moneda con una nota a medias no la pasa a la otra moneda', async () => {
    await dibujar()
    await clic(montado.contenedor, boton('nota')); await redibujar()
    await clickEn(400, 100)
    await escribir(campo(), 'en dólares'); await redibujar()
    await elegirEnLaVista(montado.contenedor, 'Pesos'); await redibujar(); await redibujar()
    await clickEn(400, 100)
    expect(campo().value).toBe('')
  })

  it('un asesor mirando la cuenta de un cliente no ve sus notas ni la herramienta (son suyas y no dicen de qué cliente)', async () => {
    const mia = { id: 'n1', tipo: 'nota', a: { d: puntos[400].d, mas: 0, precio: 110 }, texto: 'Juan compró acá' }
    const linea = { id: 'h1', tipo: 'horizontal', precio: 110 }
    localStorage.setItem('rendi_dibujos:ana@prueba.test|propia:ZZEV:usd', JSON.stringify({ pendiente: false, dibujos: [linea, mia] }))
    cuenta.cliente = { id: 5, label: 'María' }
    cuenta.usd = [linea]                                                // el servidor tampoco las manda ahí
    await dibujar()
    expect(banderitas()).toHaveLength(0)
    expect(boton('nota')).toBeUndefined()
    expect(texto(montado.contenedor)).not.toContain('Juan compró acá')
  })

  it('la elegida gana el toque aunque una vecina quede más cerca (si no, no se podía arrastrar)', () => {
    const grupos = [{ id: 'a', cx: 100, cy: 100, arriba: true, items: [] }, { id: 'b', cx: 108, cy: 100, arriba: true, items: [] }]
    expect(banderitaEn(grupos, 107, 100, 4)).toBe('b')
    expect(banderitaEn(grupos, 107, 100, 4, 'a')).toBe('a')
  })
})

describe('tu tesis en el gráfico', () => {
  const TESIS = [
    { id: 11, asset: 'ZZEV', texto: 'El recambio va a empujar las ventas', escrita_el: puntos[300].d },
    { id: 12, asset: 'ZZEV', texto: 'Sigo: subieron los márgenes', escrita_el: puntos[600].d },
  ]
  // Dónde cae una versión: su día, al cierre de ese día.
  const lugar = (i) => ({ x: (i / (LUGARES - 1)) * 100 })

  it('cada versión es una banderita en el día en que la escribiste, sin copiarse a tus dibujos', async () => {
    const ver = vi.fn()
    await dibujar({ tesis: TESIS, onVerTesis: ver })
    const b = banderitas().filter(x => x.getAttribute('data-tipo') === 'tesis')
    expect(b.map(x => x.getAttribute('data-banderita'))).toEqual(['tesis:11', 'tesis:12'])
    expect(parseFloat(b[0].style.left)).toBeCloseTo(lugar(300).x, 6)
    expect(cuenta.puts).toBe(0)                                        // no se guarda como dibujo
    // Tocarla: el texto entero y el botón que lleva a editarla.
    const x = (300 / (LUGARES - 1)) * 1000
    const y = (parseFloat(b[0].style.top) / 100) * 250
    await clickEn(x, y - ARRIBA)
    expect(texto(cartel())).toContain('Tu tesis, escrita el')
    expect(texto(cartel())).toContain('El recambio va a empujar las ventas')
    expect(texto(cartel())).toContain('después la cambiaste')          // hay una más nueva
    expect(buscarBoton(cartel(), 'Borrar')).toBeNull()                  // se borra donde se edita
    await teclaVentana('Delete'); await redibujar()
    expect(cuenta.puts).toBe(0)
    await clic(montado.contenedor, buscarBoton(cartel(), 'Ver o editar tu tesis')); await redibujar()
    await enActo(() => new Promise(r => setTimeout(r, 5)))
    expect(ver).toHaveBeenCalledTimes(1)
  })

  it('también en pesos (la tesis no es de una moneda)', async () => {
    await dibujar({ tesis: TESIS })
    await elegirEnLaVista(montado.contenedor, 'Pesos'); await redibujar(); await redibujar()
    expect(banderitas().map(x => x.getAttribute('data-banderita'))).toEqual(['tesis:11', 'tesis:12'])
  })

  it('una tesis escrita antes de lo que hay guardado no va (no hay ese día en el gráfico)', async () => {
    await dibujar({ tesis: [{ id: 9, asset: 'ZZEV', texto: 'vieja', escrita_el: '2020-01-02' }] })
    expect(banderitas()).toHaveLength(0)
  })
})
