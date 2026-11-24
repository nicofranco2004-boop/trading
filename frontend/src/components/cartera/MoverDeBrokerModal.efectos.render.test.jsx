// El formulario de «Mover a otro broker» MONTADO de verdad (testing/navegadorMinimo.js):
// corren los efectos, la espera de 400 ms y los pedidos, que `renderToStaticMarkup`
// no ve. El servidor está simulado en la frontera (utils/api) con las respuestas
// del contrato (spec B.2, B.3, B.6). Lo que fija:
//   · no se pide la vista previa sin fecha, y con fecha se pide UNA vez, 400 ms
//     después del último cambio;
//   · el error de una combinación no queda en rojo cuando la persona ya cambió el
//     formulario (revisión E12, problema 8);
//   · un precio escrito para una fecha no viaja con otra fecha (problema 8);
//   · confirmar manda el cuerpo de la vista vigente más `firma` y `valuacion`, y
//     ante un 409 («tu cartera cambió») muestra el porqué y vuelve a pedir la vista.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, buscarBoton, escribir, enActo } from '../../testing/navegadorMinimo'
import { PrivacyProvider } from '../../contexts/PrivacyContext'
import { hoyISO } from '../../utils/fecha'

const pedidos = []
let respuestas = {}
vi.mock('../../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn(() => Promise.resolve({})),
    post: vi.fn((ruta, body) => {
      pedidos.push({ ruta, body })
      const cola = respuestas[ruta] || []
      const r = cola.length > 1 ? cola.shift() : cola[0]
      return r ? r(body) : Promise.resolve({})
    }),
  },
}))

const PLAN = (body) => ({
  ok: true, origen: { cuenta: 'Cocos', etiqueta: 'Cocos · en pesos' }, destino: { cuenta: 'Balanz', brokers_a_crear: [] },
  asset: 'NVDA', moneda: 'ARS', fecha: body.fecha, cantidad: body.cantidad ?? 10, cantidad_disponible: 10,
  lotes: [{ lote_id: 1, a_mano: false, fecha_compra: '2024-03-10', cantidad: body.cantidad ?? 10, de_un_lote_de: 10,
    costo: 120000, comisiones: 0, moneda: 'ARS', broker_origen: 'Cocos', broker_destino: 'Balanz' }],
  valuacion: { precio_unitario: 25000, moneda_precio: 'ARS', fuente: body.precio_manual ? 'precio_a_mano' : 'cierre_del_dia',
    fecha_precio: body.fecha, dolar: 1400 },
  valor_nativo: 250000, valor_ars: 250000, valor_usd: 178.57, costo_usd: 92.3, puente_usd: 86.27,
  gasto: null, avisos: [], firma: 'firma0123456789ab',
})
const ok = (body) => Promise.resolve(PLAN(body))
const falla = (status, detail) => () => Promise.reject(Object.assign(new Error(typeof detail === 'string' ? detail : 'x'), { status, payload: { detail } }))
const VISTA = '/positions/traspaso/vista-previa'
const CONFIRMAR = '/positions/traspaso'

let MoverDeBrokerModal
beforeAll(async () => {
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: MoverDeBrokerModal } = await import('./MoverDeBrokerModal'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; pedidos.length = 0; respuestas = {}; localStorage.clear() })

const BROKERS = [{ id: 1, name: 'Cocos', currency: 'ARS' }, { id: 3, name: 'Balanz', currency: 'ARS' }]
const OPCION = { key: 'k', asset: 'NVDA', cuenta: 'Cocos', moneda: 'ARS', dosMonedas: true, broker: 'Cocos', lots: [], qty: 10 }
let hecho = null

// Las pruebas del pase abren en «En una fecha»; las de «tal cual», con lo que viene
// elegido de entrada.
async function abrir(modoInicial = 'pase') {
  hecho = null
  const el = () => h(PrivacyProvider, null, h(MoverDeBrokerModal, {
    opcion: OPCION, brokers: BROKERS, onClose: () => {}, onHecho: (res) => { hecho = res }, onCrearBroker: () => {},
    modoInicial,
  }))
  montado = await montar(el())
  return { leer: () => texto(montado.contenedor) }
}
const esperar = (ms) => enActo(() => new Promise((r) => setTimeout(r, ms)))
function campos() {
  const out = []
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'INPUT') out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const campoFecha = () => campos().find((c) => c.atributos.placeholder === 'dd/mm/aaaa')
const campoCantidad = () => campos().find((c) => String(c.atributos.placeholder || '').startsWith('Todo'))
// El del precio no tiene placeholder ni etiqueta de accesibilidad (los otros sí).
const campoPrecio = () => campos().find((c) => !c.atributos.placeholder && !c.atributos['aria-label'])
const vistas = () => pedidos.filter((p) => p.ruta === VISTA)

describe('MoverDeBrokerModal montado: la vista previa', () => {
  it('sin fecha no se pide nada; con fecha, un solo pedido 400 ms después del último cambio', async () => {
    respuestas = { [VISTA]: [ok] }
    await abrir()
    await escribir(campoCantidad(), '3')
    await esperar(500)
    expect(vistas()).toHaveLength(0)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Hoy'))
    await esperar(100)
    await escribir(campoCantidad(), '4')
    expect(vistas()).toHaveLength(0)
    await esperar(500)
    expect(vistas()).toHaveLength(1)
    expect(vistas()[0].body).toMatchObject({ broker_origen: 'Cocos', broker_destino: 'Balanz', asset: 'NVDA', moneda: 'ARS',
      fecha: hoyISO(), cantidad: 4 })
  }, 30000)

  it('el error de la combinación anterior se va apenas cambia el formulario (no queda en rojo esperando)', async () => {
    const ERROR = 'En Cocos tenés 2 NVDA en pesos que estaban ahí ese día. No podés pasar 9.'
    respuestas = { [VISTA]: [falla(400, ERROR), ok] }
    const v = await abrir()
    await escribir(campoCantidad(), '9')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Hoy'))
    await esperar(500)
    expect(v.leer()).toContain(ERROR)
    await escribir(campoCantidad(), '2')
    expect(v.leer(), 'el error viejo seguía a la vista con otra cantidad').not.toContain(ERROR)
    await esperar(500)
    expect(v.leer()).toContain('Se mueven estos lotes')
  }, 30000)

  it('un precio escrito es de ESA fecha: con otra fecha se borra y no viaja', async () => {
    const SIN_PRECIO = { codigo: 'sin_precio', moneda_precio: 'ARS',
      mensaje: 'No encontramos a cuánto cotizaba NVDA el 20/11/2026. Escribí el precio de ese día (en pesos) para calcular cuánto valía lo que pasaste.' }
    respuestas = { [VISTA]: [falla(409, SIN_PRECIO), ok, ok] }
    const v = await abrir()
    await escribir(campoFecha(), '20/11/2026')
    await esperar(500)
    expect(v.leer()).toContain('Precio de NVDA el 20/11/2026 (en pesos)')
    expect(v.leer()).toContain(SIN_PRECIO.mensaje)
    await escribir(campoPrecio(), '25.000')
    await esperar(500)
    expect(vistas().at(-1).body).toMatchObject({ fecha: '2026-11-20', precio_manual: 25000 })
    expect(v.leer()).toContain('precio que escribiste')

    await escribir(campoFecha(), '19/11/2026')
    expect(v.leer(), 'el campo del precio seguía con el de otra fecha').not.toContain('Precio de NVDA')
    await esperar(500)
    const ultimo = vistas().at(-1).body
    expect(ultimo.fecha).toBe('2026-11-19')
    expect(ultimo).not.toHaveProperty('precio_manual')
  }, 30000)
})

describe('MoverDeBrokerModal montado: confirmar', () => {
  it('manda lo que se vio más la firma y la valuación; un 409 muestra el porqué y vuelve a pedir la vista', async () => {
    const CAMBIO = 'Tu cartera cambió desde que armaste la vista previa. Revisala de nuevo antes de confirmar.'
    respuestas = { [VISTA]: [ok], [CONFIRMAR]: [falla(409, CAMBIO), () => Promise.resolve({ ok: true, traspaso_id: 't1', mensaje: 'Listo.' })] }
    const v = await abrir()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Hoy'))
    await esperar(500)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Mover 10 NVDA'))
    await esperar(50)
    const conf = pedidos.find((p) => p.ruta === CONFIRMAR)
    expect(conf.body).toEqual({ ...vistas()[0].body, firma: 'firma0123456789ab', valuacion: PLAN(vistas()[0].body).valuacion })
    expect(v.leer()).toContain(CAMBIO)
    expect(hecho).toBe(null)
    await esperar(500)
    expect(vistas(), 'después del 409 se vuelve a pedir la vista previa').toHaveLength(2)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Mover 10 NVDA'))
    await esperar(50)
    expect(hecho).toMatchObject({ traspaso_id: 't1' })
  }, 30000)
})

// «Tal cual» (24/11/2026): viene elegido; con el único destino posible ya puesto,
// la vista previa se pide sola, y el botón manda el mismo cuerpo, sin fecha.
describe('MoverDeBrokerModal montado: tal cual', () => {
  const VISTA_TC = '/positions/tal-cual/vista-previa'
  const PASAR_TC = '/positions/tal-cual'
  const TC = (freno = null) => () => Promise.resolve({
    origen: 'Cocos', destino: 'Balanz', asset: 'NVDA', moneda: 'ARS', cantidad: 10, freno,
    lotes: [{ fecha_compra: '2024-03-10', cantidad: 10, costo: 120000, moneda: 'ARS' }],
  })

  it('abre elegido, pide la vista previa y pasa con el mismo cuerpo', async () => {
    respuestas = { [VISTA_TC]: [TC()], [PASAR_TC]: [() => Promise.resolve({ ok: true, mensaje: 'Listo.' })] }
    const v = await abrir('tal_cual')
    await esperar(50)
    const pedido = { broker_origen: 'Cocos', broker_destino: 'Balanz', asset: 'NVDA', moneda: 'ARS' }
    expect(pedidos.filter((p) => p.ruta === VISTA_TC).map((p) => p.body)).toEqual([pedido])
    expect(v.leer()).toContain('10 NVDA · comprados el 10/03/2024')
    expect(v.leer()).not.toContain('¿Qué día llegaron')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pasar 10 NVDA a Balanz'))
    await esperar(50)
    expect(pedidos.find((p) => p.ruta === PASAR_TC).body).toEqual(pedido)
    expect(hecho).toMatchObject({ ok: true })
  }, 30000)

  it('con freno muestra el porqué y no deja pasar', async () => {
    const FRENO = 'Tus NVDA en Cocos vienen de un archivo de Cocos que importaste.'
    respuestas = { [VISTA_TC]: [TC(FRENO)] }
    const v = await abrir('tal_cual')
    await esperar(50)
    expect(v.leer()).toContain(FRENO)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pasar 10 NVDA a Balanz'))
    await esperar(50)
    expect(pedidos.some((p) => p.ruta === PASAR_TC)).toBe(false)
  }, 30000)

  it('«En una fecha» vuelve al formulario del pase', async () => {
    respuestas = { [VISTA_TC]: [TC()] }
    const v = await abrir('tal_cual')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'En una fecha'))
    expect(v.leer()).toContain('¿Qué día llegaron a Balanz?')
    expect(v.leer()).toContain('Gasto del trámite (opcional)')
  }, 30000)
})
