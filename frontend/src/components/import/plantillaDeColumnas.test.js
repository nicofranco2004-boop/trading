/**
 * El mapeo de columnas que se manda es el que la pantalla muestra.
 *
 * Una plantilla del importador guarda qué columna es qué, y también el broker fijo
 * que había al guardarla. Al cargarla reemplazaba al mapeo entero, y el paso de
 * mapeo dibuja todo con listas desplegables que sólo muestran lo que tienen entre
 * sus opciones:
 *
 *  · En "todo a un broker" (el modo por defecto) el cartel seguía diciendo
 *    "Importando todo a: B" y el archivo iba al broker A de la plantilla. La fila
 *    Broker ni se muestra en ese modo: no había forma de verlo.
 *  · En "varios brokers", si el broker de la plantilla ya no existía, la lista
 *    mostraba "— valor fijo —", se mandaba igual y el importador volvía a crear un
 *    broker con ese nombre (medido el 2026-10-10 contra el servidor: dos brokers
 *    donde había uno).
 *  · Una columna de la plantilla que el archivo no tiene se veía "— sin columna —"
 *    y el servidor rechazaba el archivo por una columna que nadie había elegido.
 *
 * Nadie lo veía porque las plantillas no cargaban nunca (pedirlas contestaba 404
 * desde el 2026-05-08). Al arreglar eso, todo esto quedaba a un click.
 *
 * Tres capas:
 *  1. La DECISIÓN (`mapeoQueSeVe`) y los avisos, como funciones.
 *  2. El DIBUJO: se dibuja el paso de mapeo de verdad (`MapStep`) con lo que la
 *     decisión devuelve, y se compara lo que quedó elegido en pantalla con lo que
 *     se mandaría. Tienen que ser lo mismo, valor por valor.
 *  3. El CABLEADO: que el asistente dibuje, mande y guarde pasando por esa decisión
 *     con el estado de pantalla. LÍMITE: este repo no tiene con qué hacerle click al
 *     asistente (no hay jsdom ni testing-library), así que esta capa lee el código.
 *     Ve nombres, no valores: tapar `brokers` con otra variable del mismo nombre no
 *     lo detecta. Se probó además a mano en el navegador (2026-10-11).
 */
import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { MapStep, avisosDePlantilla, brokersAlLlegarLaLista, mapeoQueSeVe } from './ImportWizard.jsx'

const leer = relativo => readFileSync(fileURLToPath(new URL(relativo, import.meta.url)), 'utf8')

// Los datos de Rendi tal cual los manda el servidor en `/imports/inspect`: se leen de
// su fuente (backend/importing/mapper.py) para que este test no use una copia vieja.
const CAMPOS = [...leer('../../../../backend/importing/mapper.py').matchAll(
  /\{"id":\s*"(\w+)",\s*"label":\s*"([^"]+)",\s*"required":\s*(True|False),\s*"allow_default":\s*(True|False)\}/g,
)].map(([, id, label, required, allow]) => ({ id, label, required: required === 'True', allow_default: allow === 'True' }))

const BROKERS = [{ id: 1, name: 'Balanz' }, { id: 2, name: 'Cocos' }, { id: 3, name: 'Cocos · USD' },
                 { id: 4, name: 'Zorzal Ñandú' }]
const TITULOS = ['Dia', 'Mov', 'Cuenta', 'Total']

// Como la guarda el asistente en "todo a un broker": sin columna de broker y con
// el broker de ese momento como valor fijo.
const guardado = (broker, columnasExtra = {}, fijosExtra = {}) => ({
  columns: { fecha: 'Dia', tipo: 'Mov', ...columnasExtra },
  defaults: { ...(broker ? { broker } : {}), moneda: 'ARS', ...fijosExtra },
})
const aUno = (broker = 'Cocos') => ({ importMode: 'single', singleBroker: broker, brokers: BROKERS, headers: TITULOS, campos: CAMPOS })
const aVarios = { importMode: 'general', singleBroker: 'Cocos', brokers: BROKERS, headers: TITULOS, campos: CAMPOS }
const sinBrokers = { importMode: 'general', singleBroker: '', brokers: [], headers: TITULOS, campos: CAMPOS }

describe('los datos de Rendi que usa este test', () => {
  it('son los 12 del servidor, y broker, tipo y moneda son los que tienen valor fijo', () => {
    expect(CAMPOS).toHaveLength(12)
    expect(CAMPOS.filter(c => c.allow_default).map(c => c.id).sort()).toEqual(['broker', 'moneda', 'tipo'])
  })
})

describe('"todo a un broker": manda el broker de pantalla', () => {
  it('el broker de la plantilla no le gana al elegido, y se avisa cuál era', () => {
    const r = mapeoQueSeVe(guardado('Balanz'), aUno('Cocos'))
    expect(r.mapping.defaults.broker).toBe('Cocos')
    expect(r.brokerReemplazado).toBe('Balanz')
    expect(r.brokerQueYaNoExiste).toBeNull()
    expect(r.columnaDeBrokerIgnorada).toBeNull()
  })

  it('si la plantilla se guardó con ese mismo broker, no hay nada que avisar', () => {
    expect(mapeoQueSeVe(guardado('Cocos'), aUno('Cocos')).brokerReemplazado).toBeNull()
    expect(mapeoQueSeVe(guardado(' cocos '), aUno('Cocos')).brokerReemplazado).toBeNull()
    expect(mapeoQueSeVe(guardado(' cocos '), aUno('Cocos')).mapping.defaults.broker).toBe('Cocos')
  })

  it('conserva todo lo demás de la plantilla', () => {
    const { mapping } = mapeoQueSeVe(guardado('Balanz', {}, { tipo: 'COMPRA' }), aUno())
    expect(mapping.columns).toEqual({ fecha: 'Dia', tipo: 'Mov' })
    expect(mapping.defaults).toEqual({ broker: 'Cocos', moneda: 'ARS', tipo: 'COMPRA' })
  })

  it('una plantilla que repartía por una columna de broker: la columna no se usa, y se dice', () => {
    const r = mapeoQueSeVe({ columns: { fecha: 'Dia', broker: 'Cuenta' }, defaults: {} }, aUno())
    expect('broker' in r.mapping.columns).toBe(false)
    expect(r.mapping.defaults.broker).toBe('Cocos')
    expect(r.columnaDeBrokerIgnorada).toBe('Cuenta')
  })

  it('la columna de broker ignorada no sale además como "columna que el archivo no tiene"', () => {
    // La fila Broker no se dibuja en este modo: mandar a revisarla no tiene sentido.
    const r = mapeoQueSeVe({ columns: { fecha: 'Dia', broker: 'Agente' }, defaults: {} }, aUno())
    expect(r.columnaDeBrokerIgnorada).toBe('Agente')
    expect(r.columnasQueNoEstan).toEqual([])
  })

  it('un broker de la plantilla que ya no existe se reemplaza igual', () => {
    const r = mapeoQueSeVe(guardado('Uno que se borró'), aUno())
    expect(r.mapping.defaults.broker).toBe('Cocos')
    expect(r.brokerQueYaNoExiste).toBeNull()
    expect(r.brokerReemplazado).toBe('Uno que se borró')
  })

  it('un mapeo sin broker fijo queda con el de pantalla, sin aviso', () => {
    const r = mapeoQueSeVe(guardado(null), aUno())
    expect(r.mapping.defaults.broker).toBe('Cocos')
    expect(r.brokerReemplazado).toBeNull()
  })

  it('sin broker elegido no puede salir NINGÚN broker: la pantalla no muestra ninguno', () => {
    // No se llega al mapeo así (el botón de seguir lo exige), pero si se llegara,
    // ni uno que existe ni uno que no: tiene que saltar "Falta mapear: Broker".
    for (const broker of ['Balanz', 'Uno que se borró']) {
      const { mapping } = mapeoQueSeVe(guardado(broker, { broker: 'Cuenta' }), aUno(''))
      expect('broker' in mapping.defaults).toBe(false)
      expect('broker' in mapping.columns).toBe(false)
    }
  })
})

describe('"varios brokers": el broker fijo tiene que estar en la lista', () => {
  it('si existe, queda', () => {
    const r = mapeoQueSeVe(guardado('Balanz'), aVarios)
    expect(r.mapping.defaults.broker).toBe('Balanz')
    expect(r.brokerQueYaNoExiste).toBeNull()
    expect(r.brokerReemplazado).toBeNull()
  })

  it('el "· USD" de un broker también existe', () => {
    expect(mapeoQueSeVe(guardado('Cocos · USD'), aVarios).mapping.defaults.broker).toBe('Cocos · USD')
  })

  it('si ya no existe, se saca y se avisa cuál era', () => {
    const r = mapeoQueSeVe(guardado('Hornero Ágil'), aVarios)
    expect('broker' in r.mapping.defaults).toBe(false)
    expect(r.brokerQueYaNoExiste).toBe('Hornero Ágil')
    expect(r.mapping.defaults.moneda).toBe('ARS')
  })

  it('escrito con otras mayúsculas o un espacio de más ES el mismo broker (como en el servidor): queda con el nombre de la lista', () => {
    for (const escrito of ['balanz', 'BALANZ', ' Balanz ']) {
      const r = mapeoQueSeVe(guardado(escrito), aVarios)
      expect(r.mapping.defaults.broker).toBe('Balanz')
      expect(r.brokerQueYaNoExiste).toBeNull()
    }
    // Con tilde y eñe: se bajan igual que en el servidor.
    expect(mapeoQueSeVe(guardado('ZORZAL ÑANDÚ'), aVarios).mapping.defaults.broker).toBe('Zorzal Ñandú')
  })

  it('con dos brokers que sólo difieren en mayúsculas, el elegido es el que dice el mapeo', () => {
    // Gana el nombre EXACTO. (Sin esto, elegir "balanz" en la lista dejaba elegido "Balanz".)
    const gemelos = { ...aVarios, brokers: [{ id: 1, name: 'Balanz' }, { id: 2, name: 'balanz' }] }
    expect(mapeoQueSeVe(guardado('balanz'), gemelos).mapping.defaults.broker).toBe('balanz')
    expect(mapeoQueSeVe(guardado('Balanz'), gemelos).mapping.defaults.broker).toBe('Balanz')
    const alReves = { ...aVarios, brokers: [{ id: 2, name: 'balanz' }, { id: 1, name: 'Balanz' }] }
    expect(mapeoQueSeVe(guardado('Balanz'), alReves).mapping.defaults.broker).toBe('Balanz')
    expect(mapeoQueSeVe(guardado('BALANZ'), gemelos).brokerQueYaNoExiste).toBeNull()   // alguno de los dos
  })

  it('la columna de broker del mapeo se respeta', () => {
    const r = mapeoQueSeVe(guardado('Balanz', { broker: 'Cuenta' }), aVarios)
    expect(r.mapping.columns.broker).toBe('Cuenta')
    expect(r.columnaDeBrokerIgnorada).toBeNull()
  })

  it('con columna de broker Y broker fijo que ya no existe: queda la columna, se saca el fijo', () => {
    const r = mapeoQueSeVe(guardado('Hornero Ágil', { broker: 'Cuenta' }), aVarios)
    expect(r.mapping.columns.broker).toBe('Cuenta')
    expect('broker' in r.mapping.defaults).toBe(false)
    expect(r.brokerQueYaNoExiste).toBe('Hornero Ágil')
  })

  it('sin ningún broker cargado el campo es un texto libre que SÍ muestra el valor: queda', () => {
    const r = mapeoQueSeVe(guardado('IBKR'), sinBrokers)
    expect(r.mapping.defaults.broker).toBe('IBKR')
    expect(r.brokerQueYaNoExiste).toBeNull()
  })

  it('un broker fijo en blanco no es un broker: se saca sin aviso', () => {
    for (const ctx of [aVarios, sinBrokers]) {
      const r = mapeoQueSeVe(guardado('   '), ctx)
      expect('broker' in r.mapping.defaults).toBe(false)
      expect(r.brokerQueYaNoExiste).toBeNull()
    }
  })

  it('un mapeo sin broker fijo no avisa nada', () => {
    const r = mapeoQueSeVe(guardado(null), aVarios)
    expect('broker' in r.mapping.defaults).toBe(false)
    expect(r.brokerQueYaNoExiste).toBeNull()
  })
})

describe('las columnas que el archivo no tiene', () => {
  it('se sacan y se dice cuáles eran y de qué dato', () => {
    const r = mapeoQueSeVe(guardado('Balanz', { activo: 'Papel', comisiones: 'Gastos' }), aVarios)
    expect(r.mapping.columns).toEqual({ fecha: 'Dia', tipo: 'Mov' })
    expect(r.columnasQueNoEstan).toEqual([{ campo: 'activo', titulo: 'Papel' }, { campo: 'comisiones', titulo: 'Gastos' }])
  })

  it('el título tiene que ser EXACTO: es lo único que la lista y el servidor reconocen', () => {
    const r = mapeoQueSeVe({ columns: { fecha: 'dia', tipo: 'Mov ' }, defaults: {} }, aVarios)
    expect(r.mapping.columns).toEqual({})
    expect(r.columnasQueNoEstan.map(c => c.titulo)).toEqual(['dia', 'Mov '])
  })

  it('en "todo a un broker" también', () => {
    const r = mapeoQueSeVe(guardado('Balanz', { precio: 'Px' }), aUno())
    expect('precio' in r.mapping.columns).toBe(false)
    expect(r.columnasQueNoEstan).toEqual([{ campo: 'precio', titulo: 'Px' }])
  })

  it('en "varios brokers", la columna de broker que el archivo no tiene es una más', () => {
    const r = mapeoQueSeVe(guardado('Balanz', { broker: 'Agente' }), aVarios)
    expect('broker' in r.mapping.columns).toBe(false)
    expect(r.columnasQueNoEstan).toEqual([{ campo: 'broker', titulo: 'Agente' }])
  })

  it('sin los títulos del archivo a mano no se saca ninguna', () => {
    const r = mapeoQueSeVe(guardado('Balanz', { activo: 'Papel' }), { ...aVarios, headers: undefined })
    expect(r.mapping.columns.activo).toBe('Papel')
    expect(r.columnasQueNoEstan).toEqual([])
  })
})

describe('los valores fijos que la pantalla no tiene dónde mostrar', () => {
  it('un valor fijo de un dato sin casillero (Fecha, Activo, Notas…) no sale', () => {
    const r = mapeoQueSeVe(guardado('Balanz', {}, { fecha: '2026-01-01', activo: 'AAPL', notas: 'x' }), aVarios)
    expect(r.mapping.defaults).toEqual({ broker: 'Balanz', moneda: 'ARS' })
  })

  it('los de Tipo, Moneda y Broker (que sí tienen casillero) quedan', () => {
    const r = mapeoQueSeVe(guardado('Balanz', {}, { tipo: 'COMPRA' }), aVarios)
    expect(r.mapping.defaults).toEqual({ broker: 'Balanz', moneda: 'ARS', tipo: 'COMPRA' })
  })

  it('un valor que no es texto no sale, ni como columna ni como valor fijo', () => {
    // Sólo llega con una plantilla escrita por fuera del asistente; el servidor ya no las guarda.
    const raro = { columns: { fecha: 'Dia', tipo: 7, activo: null, precio: ['Px'] },
                   defaults: { broker: 7, moneda: { a: 1 }, tipo: 'COMPRA' } }
    const r = mapeoQueSeVe(raro, aVarios)
    expect(r.mapping).toEqual({ columns: { fecha: 'Dia' }, defaults: { tipo: 'COMPRA' } })
    expect(r.brokerQueYaNoExiste).toBeNull()
    expect(r.columnasQueNoEstan).toEqual([])
    expect(mapeoQueSeVe(raro, aUno('Cocos')).mapping.defaults).toEqual({ broker: 'Cocos', tipo: 'COMPRA' })
  })

  it('sin la lista de datos a mano no se saca ninguno', () => {
    const r = mapeoQueSeVe(guardado('Balanz', {}, { fecha: '2026-01-01' }), { ...aVarios, campos: undefined })
    expect(r.mapping.defaults.fecha).toBe('2026-01-01')
  })
})

describe('lo que no puede romper', () => {
  it('no modifica lo que recibe (la plantilla se puede volver a cargar)', () => {
    const m = guardado('Hornero Ágil', { broker: 'Cuenta', activo: 'Papel' }, { fecha: 'x' })
    const copia = JSON.parse(JSON.stringify(m))
    mapeoQueSeVe(m, aVarios)
    mapeoQueSeVe(m, aUno())
    expect(m).toEqual(copia)
  })

  it('aplicarla dos veces da lo mismo que una (lo que ya se ve no cambia al mandarlo)', () => {
    for (const ctx of [aVarios, aUno(), aUno(''), sinBrokers]) {
      const una = mapeoQueSeVe(guardado(' hornero ágil ', { broker: 'Cuenta', activo: 'Papel' }, { fecha: 'x' }), ctx).mapping
      const dos = mapeoQueSeVe(una, ctx)
      expect(dos.mapping).toEqual(una)
      expect(dos.brokerQueYaNoExiste).toBeNull()
      expect(dos.brokerReemplazado).toBeNull()
      expect(dos.columnaDeBrokerIgnorada).toBeNull()
      expect(dos.columnasQueNoEstan).toEqual([])
    }
  })

  it('un mapeo vacío o a medio guardar no revienta', () => {
    for (const m of [undefined, null, {}, { columns: null, defaults: null }]) {
      expect(mapeoQueSeVe(m, aVarios).mapping).toEqual({ columns: {}, defaults: {} })
      expect(mapeoQueSeVe(m, aUno()).mapping).toEqual({ columns: {}, defaults: { broker: 'Cocos' } })
    }
    expect(mapeoQueSeVe(guardado('Balanz')).mapping.defaults.broker).toBe('Balanz')   // sin contexto
  })
})

describe('avisosDePlantilla', () => {
  const avisos = (m, ctx) => avisosDePlantilla(mapeoQueSeVe(m, ctx), { singleBroker: ctx.singleBroker, campos: CAMPOS })

  it('nada que contar → lista vacía', () => {
    expect(avisos(guardado('Cocos'), aUno('Cocos'))).toEqual([])
    expect(avisos(guardado('Balanz'), aVarios)).toEqual([])
  })

  it('"todo a un broker" con otro broker: dice con cuál se guardó y a cuál va', () => {
    const [aviso, ...resto] = avisos(guardado('Balanz'), aUno('Cocos'))
    expect(resto).toEqual([])
    expect(aviso.texto).toContain('«Balanz»')
    expect(aviso.texto).toContain('«Cocos»')
    expect(aviso.campo).toBeNull()             // no se arregla en una fila: no se va al tocar el mapeo
  })

  it('"todo a un broker" con una plantilla que repartía por columna: dice la columna y cómo volver', () => {
    const [aviso, ...resto] = avisos({ columns: { fecha: 'Dia', broker: 'Cuenta' }, defaults: {} }, aUno('Cocos'))
    expect(resto).toEqual([])
    expect(aviso.texto).toContain('«Cuenta»')
    expect(aviso.texto).toContain('«Cocos»')
    expect(aviso.texto).toContain('mezcla varios brokers')
    expect(aviso.campo).toBeNull()
  })

  it('si repartía por columna y además tenía un broker fijo, se cuenta lo de la columna (un solo aviso)', () => {
    const lista = avisos({ columns: { fecha: 'Dia', broker: 'Cuenta' }, defaults: { broker: 'Balanz' } }, aUno('Cocos'))
    expect(lista.map(a => a.id)).toEqual(['columna-de-broker'])
  })

  it('broker fijo que ya no existe: lo nombra, manda a ELEGIR OTRO en la fila Broker', () => {
    const [aviso] = avisos(guardado('Hornero Ágil'), aVarios)
    expect(aviso.texto).toContain('«Hornero Ágil»')
    expect(aviso.texto).toContain('Elegí otro en la fila Broker')
    expect(aviso.campo).toBe('broker')
  })

  it('columnas que el archivo no tiene: un aviso por dato, con el nombre de la fila de Rendi', () => {
    const lista = avisos(guardado('Balanz', { activo: 'Papel', comisiones: 'Gastos' }), aVarios)
    expect(lista.map(a => a.campo)).toEqual(['activo', 'comisiones'])
    expect(lista[0].texto).toContain('«Papel»')
    expect(lista[0].texto).toContain('Activo')
    expect(lista[1].texto).toContain('«Gastos»')
    expect(lista[1].texto).toContain('Comisiones')
  })

  it('dos datos sobre la misma columna que falta: dos avisos distintos, no un título repetido', () => {
    const lista = avisos(guardado('Balanz', { monto: 'Importe', monto_usd: 'Importe' }), aVarios)
    expect(lista).toHaveLength(2)
    expect(new Set(lista.map(a => a.texto)).size).toBe(2)
  })

  it('los `id` no se repiten (se usan de `key` al dibujar)', () => {
    const lista = avisos(guardado('Hornero Ágil', { activo: 'Papel', precio: 'Px', broker: 'Agente' }), aVarios)
    expect(lista).toHaveLength(4)
    expect(new Set(lista.map(a => a.id)).size).toBe(4)
  })
})

describe('la lista de brokers que llega tarde', () => {
  it('conserva el broker que la persona ya creó desde el asistente, sin repetir ninguno', () => {
    const creado = { id: 9, name: 'Nuevo' }
    expect(brokersAlLlegarLaLista([creado], [BROKERS[0], BROKERS[1]])).toEqual([BROKERS[0], BROKERS[1], creado])
    expect(brokersAlLlegarLaLista([creado], [BROKERS[0], creado])).toEqual([BROKERS[0], creado])
    expect(brokersAlLlegarLaLista([], BROKERS)).toEqual(BROKERS)
    expect(brokersAlLlegarLaLista(BROKERS, [])).toEqual(BROKERS)
  })
})

// ─── El DIBUJO: lo elegido en pantalla es lo que se manda ─────────────────────
const sinEscapar = t => t.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>').replace(/&amp;/g, '&')

/** Todo lo que el paso muestra ELEGIDO: la opción marcada de cada lista y el texto de
 *  cada casillero. Sin los vacíos ("— sin columna —", casillero en blanco). */
function elegidoEnPantalla(html) {
  const listas = [...html.matchAll(/<select[^>]*>(.*?)<\/select>/gs)].map(([, opciones]) => {
    const marcada = opciones.match(/<option[^>]*\bselected=""[^>]*>/)
    return marcada ? sinEscapar(marcada[0].match(/\bvalue="([^"]*)"/)[1]) : ''
  })
  const casilleros = [...html.matchAll(/<input[^>]*type="text"[^>]*>/g)]
    .map(([input]) => sinEscapar((input.match(/\bvalue="([^"]*)"/) || [, ''])[1]))
  return [...listas, ...casilleros].filter(Boolean).sort()
}

function dibujar(mapping, ctx, extra = {}) {
  return renderToStaticMarkup(createElement(MapStep, {
    inspect: { headers: ctx.headers, rendi_fields: CAMPOS, sample_rows: [] },
    mapping, setMapping: () => {}, brokers: ctx.brokers, importMode: ctx.importMode,
    singleBroker: ctx.singleBroker, useCurrencyRouting: false, ...extra,
  }))
}

/** Lo que se mandaría, como lista de valores. En "todo a un broker" el broker no va
 *  en una fila: va en el cartel de arriba (se revisa aparte). */
function loQueSeManda(mapping, ctx) {
  const fijos = { ...mapping.defaults }
  if (ctx.importMode === 'single') delete fijos.broker
  return [...Object.values(mapping.columns), ...Object.values(fijos)].sort()
}

const MAPEOS_DIFICILES = {
  'guardada con un broker que existe': guardado('Balanz'),
  'broker que ya no existe': guardado('Hornero Ágil'),
  'broker con otras mayúsculas y espacios': guardado('  ZORZAL ÑANDÚ '),
  'broker en blanco': guardado('   '),
  'el sub-broker en dólares': guardado('Cocos · USD'),
  'columna de broker + broker fijo': guardado('Balanz', { broker: 'Cuenta' }),
  'columna de broker que el archivo no tiene': guardado('Balanz', { broker: 'Agente' }),
  'columnas de otro archivo': guardado('Balanz', { activo: 'Papel', precio: 'Px', monto: 'Total' }),
  'valores fijos en Tipo y Moneda': guardado('Balanz', {}, { tipo: 'COMPRA', moneda: 'USD' }),
  'valor fijo en un dato sin casillero': guardado('Balanz', {}, { fecha: '2026-01-01', notas: 'hola' }),
  'valores que no son texto': { columns: { fecha: 'Dia', tipo: 7 }, defaults: { broker: 7, moneda: 'ARS' } },
  'vacío': { columns: {}, defaults: {} },
}

describe('el paso de mapeo dibuja exactamente lo que se manda', () => {
  for (const [nombreCtx, ctx] of [['varios brokers', aVarios], ['varios brokers, cuenta sin brokers', sinBrokers],
                                   ['todo a un broker', aUno('Cocos')]]) {
    for (const [nombre, crudo] of Object.entries(MAPEOS_DIFICILES)) {
      it(`${nombreCtx} · ${nombre}`, () => {
        const { mapping } = mapeoQueSeVe(crudo, ctx)
        const html = dibujar(mapping, ctx)
        expect(elegidoEnPantalla(html)).toEqual(loQueSeManda(mapping, ctx))
        if (ctx.importMode === 'single') {
          expect(mapping.defaults.broker).toBe('Cocos')
          expect(html).toMatch(/Importando todo a:<\/span><span[^>]*>Cocos<\/span>/)
          expect(html).not.toMatch(/>Broker</)            // la fila Broker no se dibuja
        }
      })
    }
  }

  it('CONTROL: sin pasar por la decisión, la pantalla y lo que se manda NO coinciden', () => {
    // Si esto dejara de fallar, el test de arriba ya no estaría midiendo nada.
    for (const nombre of ['broker que ya no existe', 'columnas de otro archivo',
                          'valor fijo en un dato sin casillero', 'broker con otras mayúsculas y espacios']) {
      const crudo = MAPEOS_DIFICILES[nombre]
      expect(elegidoEnPantalla(dibujar(crudo, aVarios)), nombre).not.toEqual(loQueSeManda(crudo, aVarios))
    }
    const crudo = MAPEOS_DIFICILES['guardada con un broker que existe']      // Balanz, con Cocos en el cartel
    expect(dibujar(crudo, aUno('Cocos'))).not.toContain('Balanz')
  })

  it('los avisos se dibujan todos (uno solo también), y sin avisos no hay caja', () => {
    const lista = [{ id: 'a', texto: 'Primero de los avisos', campo: null },
                   { id: 'b', texto: 'Segundo de los avisos', campo: 'broker' }]
    const con = dibujar(guardado('Balanz'), aVarios, { avisos: lista })
    expect(con).toContain('Primero de los avisos')
    expect(con).toContain('Segundo de los avisos')
    expect(con).toContain('rendi-warn')
    const conUno = dibujar(guardado('Balanz'), aVarios, { avisos: lista.slice(0, 1) })
    expect(conUno).toContain('Primero de los avisos')
    expect(conUno).not.toContain('Segundo de los avisos')
    expect(dibujar(guardado('Balanz'), aVarios)).not.toContain('rendi-warn')
  })

  it('el broker fijo es una LISTA en cuanto la cuenta tiene un broker, y un texto libre si no tiene ninguno', () => {
    // De esto depende la regla: con lista, sólo se puede mostrar un broker que existe.
    const unSolo = { ...aVarios, brokers: [BROKERS[0]] }
    const conLista = dibujar(mapeoQueSeVe(guardado('Balanz'), unSolo).mapping, unSolo)
    expect(conLista).toMatch(/<option value="Balanz" selected="">Balanz<\/option>/)
    expect(conLista).toContain('— valor fijo (opcional) —</option>')
    const conTexto = dibujar(mapeoQueSeVe(guardado('IBKR'), sinBrokers).mapping, sinBrokers)
    expect(conTexto).not.toContain('— valor fijo (opcional) —</option>')
    expect(conTexto).toMatch(/<input[^>]*value="IBKR"/)
  })

  it('el nombre de una plantilla nueva no pasa del largo que el servidor acepta', () => {
    // El servidor rechaza más de 80 letras con un texto técnico; el casillero no deja escribirlas.
    const fuente = leer('./ImportWizard.jsx')
    const casillero = fuente.slice(fuente.indexOf('placeholder="Nombre (ej: IBKR template)"') - 600,
                                   fuente.indexOf('placeholder="Nombre (ej: IBKR template)"') + 200)
    expect(casillero).toContain('maxLength={80}')
    expect(leer('../../../../backend/main.py')).toMatch(
      /class ImportMappingIn\(BaseModel\):\s*name: str = Field\(\.\.\., min_length=1, max_length=80\)/)
  })

  it('con plantillas guardadas aparece el selector para cargarlas, con todas', () => {
    const html = dibujar(guardado('Balanz'), aVarios, { savedTemplates: [{ id: 1, name: 'mi banco' }, { id: 2, name: 'otro' }] })
    expect(html).toContain('— cargar guardada —')
    expect(html).toContain('>mi banco</option>')
    expect(html).toContain('>otro</option>')
    expect(dibujar(guardado('Balanz'), aVarios)).not.toContain('— cargar guardada —')
  })
})

// ─── El CABLEADO ──────────────────────────────────────────────────────────────
describe('el cableado: el asistente dibuja y manda pasando por esa decisión', () => {
  const fuente = leer('./ImportWizard.jsx')
  const cuerpoDe = firma => {
    const desde = fuente.indexOf(firma)
    expect(desde, `no encontré «${firma}» en ImportWizard.jsx`).toBeGreaterThan(-1)
    const hasta = fuente.indexOf('\n  }\n', desde)
    expect(hasta).toBeGreaterThan(desde)
    return fuente.slice(desde, hasta)
  }
  const desdeMapStep = fuente.indexOf('\nexport function MapStep(')

  it('hay UNA forma de armar lo que se ve, con el estado de pantalla', () => {
    expect(fuente).toMatch(/const loQueSeVe = \(m, archivo = inspect\) => mapeoQueSeVe\(m, \{\s*importMode, singleBroker, brokers, headers: archivo\?\.headers, campos: archivo\?\.rendi_fields,\s*\}\)/)
    // La definición y esa única llamada: nadie más arma el contexto por su cuenta.
    expect(fuente.match(/mapeoQueSeVe\(/g)).toHaveLength(2)
  })

  it('LA SALIDA: lo que se manda es lo que se ve, y la validación mira eso', () => {
    const cuerpo = cuerpoDe('  async function confirmMapping() {')
    expect(cuerpo).toContain('const { mapping: aEnviar } = loQueSeVe(mapping)')
    expect(cuerpo).toContain("fd.append('mapping', JSON.stringify(aEnviar))")
    expect(cuerpo.match(/JSON\.stringify\(/g)).toHaveLength(1)
    expect(cuerpo).not.toMatch(/mapping\.(columns|defaults)/)
    expect(cuerpo).toMatch(/aEnviar\.columns\?\.\[f\.id\]/)
    expect(cuerpo).toMatch(/aEnviar\.defaults\?\.\[f\.id\]/)
  })

  it('es el único lugar del asistente que manda un mapeo', () => {
    expect(fuente.match(/append\('mapping'/g)).toHaveLength(1)
  })

  it('EL DIBUJO: el paso recibe lo que se ve, con el mismo estado que la salida', () => {
    expect(fuente).toContain('mapping={loQueSeVe(mapping).mapping}')
    expect(fuente.match(/<MapStep\b/g)).toHaveLength(1)
    const montaje = fuente.slice(fuente.indexOf('<MapStep'), fuente.indexOf('/>', fuente.indexOf('<MapStep')))
    for (const prop of ['brokers={brokers}', 'importMode={importMode}', 'singleBroker={singleBroker}',
                        'inspect={inspect}', 'avisos={avisosPlantilla}', 'savedTemplates={savedTemplates}',
                        'onLoadTemplate={loadTemplate}']) {
      expect(montaje, prop).toContain(prop)
    }
    expect(montaje).toContain('onTocarMapeo={campo => setAvisosPlantilla(a => a.filter(x => x.campo !== campo))}')
  })

  it('GUARDAR una plantilla: se guarda lo que se ve, no el estado crudo', () => {
    const cuerpo = cuerpoDe('  async function saveTemplate(name) {')
    expect(cuerpo).toMatch(/api\.post\('\/imports\/mappings',\s*\{ name: name\.trim\(\), mapping: loQueSeVe\(mapping\)\.mapping \}\)/)
    expect(fuente.match(/api\.post\('\/imports\/mappings'/g)).toHaveLength(1)
  })

  it('cargar una plantilla: arma el mapeo con la decisión y muestra sus avisos', () => {
    const cuerpo = cuerpoDe('  function loadTemplate(template) {')
    expect(cuerpo).toContain('const cargado = loQueSeVe(template.mapping)')
    expect(cuerpo).toContain('setMapping(cargado.mapping)')
    expect(cuerpo).toContain('setAvisosPlantilla(avisosDePlantilla(cargado, { singleBroker, campos: inspect?.rendi_fields }))')
    expect(cuerpo.match(/template\./g)).toHaveLength(1)        // sólo como entrada de la decisión
  })

  it('leer el archivo: el mapeo sugerido pasa por la misma decisión, con los títulos de ESE archivo', () => {
    const cuerpo = cuerpoDe('  async function uploadAndInspect() {')
    expect(cuerpo).toContain('setMapping(loQueSeVe(initial, data).mapping)')
    expect(cuerpo).toContain('setAvisosPlantilla([])')          // los avisos eran de otro archivo
  })

  it('fuera del paso de mapeo, todo mapeo entero que se pone sale de la decisión (o es el vacío)', () => {
    const enteros = [...fuente.slice(0, desdeMapStep).matchAll(/setMapping\(([^\n]*)/g)].map(m => m[1].trim())
    expect(enteros.sort()).toEqual([
      'cargado.mapping)',
      'loQueSeVe(initial, data).mapping)',
      '{ columns: {}, defaults: {} })',
    ].sort())
  })

  it('adentro del paso de mapeo sólo se ajusta UN campo por vez, y eso apaga el aviso de ESA fila', () => {
    const paso = fuente.slice(desdeMapStep, fuente.indexOf('\nfunction ', desdeMapStep + 1))
    const ajustes = [...paso.matchAll(/setMapping\(([^\n]*)/g)].map(m => m[1].trim())
    expect(ajustes).toEqual(['m => {', 'm => {'])
    for (const nombre of ['setColumn', 'setDefault']) {
      const desde = paso.indexOf(`  function ${nombre}(`)
      expect(paso.slice(desde, paso.indexOf('\n  }\n', desde))).toContain('onTocarMapeo?.(fieldId)')
    }
  })

  it('al abrir: pide las plantillas, y la lista de brokers que llega no pisa lo que la persona ya hizo', () => {
    const desde = fuente.indexOf("api.get('/imports/parsers/grouped')")
    const efecto = fuente.slice(desde, fuente.indexOf('}, [])', desde))
    expect(efecto).toContain("api.get('/imports/mappings').then(setSavedTemplates)")
    expect(efecto).toContain('setBrokers(prev => brokersAlLlegarLaLista(prev, bs))')
    expect(efecto).toContain('setSingleBroker(prev => prev || bs[0].name)')
  })

  it('después de la vista previa: se apagan los avisos y se vuelve a pedir la lista de brokers', () => {
    const cuerpo = cuerpoDe('  async function confirmMapping() {')
    const trasLaVistaPrevia = cuerpo.slice(cuerpo.indexOf("api.upload('/imports/preview'"))
    expect(trasLaVistaPrevia).toContain('setAvisosPlantilla([])')
    expect(trasLaVistaPrevia).toContain("api.get('/brokers').then(setBrokers)")
  })
})
