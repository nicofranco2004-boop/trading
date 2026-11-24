// La vista previa de «Mover a otro broker», dibujada (spec E.2 / E.10).
//
// `VistaPreviaDelPase` es pura a propósito: `renderToStaticMarkup` no corre
// efectos, así que todo lo que se ve tiene que salir de sus props. Se arma con la
// forma de la respuesta de POST /api/positions/traspaso/vista-previa (B.2), la
// que fija backend/tests/test_mover_entre_brokers_contrato.py.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import VistaPreviaDelPase, { SelectorDeDestino, VistaTalCual, CREAR_BROKER } from './VistaPreviaDelPase'
import { OCULTO } from '../../utils/ocultarSaldos'

const PLAN = {
  ok: true,
  origen: { cuenta: 'Cocos', etiqueta: 'Cocos · en pesos' },
  destino: { cuenta: 'Balanz', brokers_a_crear: [] },
  asset: 'NVDA', moneda: 'ARS', fecha: '2026-11-20', cantidad: 10, cantidad_disponible: 25,
  lotes: [
    { lote_id: 123, a_mano: false, fecha_compra: '2024-03-10', cantidad: 4, de_un_lote_de: 4, costo: 120000, comisiones: 600, moneda: 'ARS', broker_origen: 'Cocos', broker_destino: 'Balanz' },
    { lote_id: 124, a_mano: true, fecha_compra: '2024-06-01', cantidad: 6, de_un_lote_de: 10, costo: 180000, comisiones: 0, moneda: 'ARS', broker_origen: 'Cocos', broker_destino: 'Balanz' },
  ],
  valuacion: { precio_unitario: 25000, moneda_precio: 'ARS', fuente: 'cierre_del_dia', fecha_precio: '2026-11-20', dolar: 1400 },
  valor_nativo: 250000, valor_ars: 250000, valor_usd: 178.57, costo_usd: 92.3, puente_usd: 86.27,
  gasto: null,
  // El texto real del servidor (`_monto`, money_fmt.fmt_money): el signo y la moneda
  // ADELANTE del número, así `taparMontos` lo tapa con el ojito.
  avisos: ['Con el gasto, la caja de Cocos queda en −$5.000.'],
  firma: '9f2c0011aabbccdd',
}

const dibujar = (props) => renderToStaticMarkup(<VistaPreviaDelPase {...props} />)
const lineas = (html) => (html.match(/<li[^>]*class="tabular text-ink-2"[^>]*>/g) || []).length

describe('VistaPreviaDelPase', () => {
  it('una línea por lote, primero los más viejos, con lo que corresponde a cada uno', () => {
    const html = dibujar({ plan: PLAN })
    expect(html).toContain('Se mueven estos lotes (primero los más viejos):')
    expect(lineas(html)).toBe(2)
    expect(html).toContain('4 NVDA · comprados el 10/03/2024 · costo $120.000 ARS')
    expect(html).toContain('6 NVDA · comprados el 01/06/2024 · costo $180.000 ARS · parte de un lote de 10 · cargado a mano')
    expect(html).toContain('Valían $250.000 ARS (USD 178,57) el 20/11/2026 · cierre de ese día')
    expect(html).toContain('Te costaron USD 92,30.')
    expect(html).toContain('No es una venta: no cuenta en tus operaciones cerradas ni en los impuestos.')
  })

  it('con el ojito, los montos se tapan y las cantidades y fechas quedan a la vista', () => {
    const html = dibujar({ plan: PLAN, hidden: true })
    for (const monto of ['120.000', '180.000', '250.000', '178,57', '92,30', '86,27', '5.000']) {
      expect(html).not.toContain(monto)
    }
    expect(html).toContain(OCULTO)
    expect(html).toContain('4 NVDA · comprados el 10/03/2024')
    expect(html).toContain('parte de un lote de 10')
    expect(html).toContain('el 20/11/2026')
  })

  it('el texto del puente según el signo: ganancia o pérdida en A, y lo que arranca valiendo en B', () => {
    expect(dibujar({ plan: PLAN })).toContain(
      'En Cocos va a figurar una ganancia de USD 86,27 hasta el pase, y en Balanz arrancan valiendo USD 178,57.')
    const pierde = dibujar({ plan: { ...PLAN, valor_usd: 80, puente_usd: -12.3 } })
    expect(pierde).toContain('En Cocos va a figurar una pérdida de USD 12,30 hasta el pase, y en Balanz arrancan valiendo USD 80,00.')
    expect(pierde).not.toContain('ganancia')
  })

  it('los avisos van uno por renglón, en el color de aviso', () => {
    const html = dibujar({ plan: PLAN })
    expect(html).toMatch(/class="text-rendi-warn tabular"[^>]*>Con el gasto, la caja de Cocos queda en −\$5\.000\./)
  })

  it('el error se ve, en rojo, aunque no haya vista previa', () => {
    const html = dibujar({ plan: null, error: 'La fecha del pase no puede ser posterior a hoy.' })
    expect(html).toContain('role="alert"')
    expect(html).toContain('text-rendi-neg')
    expect(html).toContain('La fecha del pase no puede ser posterior a hoy.')
    expect(html).not.toContain('Se mueven estos lotes')
  })

  // Revisión E12, problema 7: el gasto del bloque plegable viajaba aunque el
  // bloque estuviera cerrado, y la vista previa no lo mostraba. Ahora se ve lo que
  // entendió el servidor (`plan.gasto`), tapado con el ojito.
  it('el gasto del trámite se ve en la vista previa (y se tapa con el ojito)', () => {
    const conGasto = { ...PLAN, gasto: { monto: 5000, moneda: 'ARS', broker: 'Cocos', caja_queda_negativa: false } }
    expect(dibujar({ plan: conGasto })).toContain('Gasto del trámite: $5.000 ARS de la caja de Cocos.')
    const oculto = dibujar({ plan: conGasto, hidden: true })
    expect(oculto).toContain(`Gasto del trámite: ${OCULTO} de la caja de Cocos.`)
    expect(oculto).not.toContain('5.000 ARS')
    expect(dibujar({ plan: PLAN })).not.toContain('Gasto del trámite:')
  })

  it('sin plan ni error no dibuja nada que confunda', () => {
    expect(dibujar({ plan: null })).toBe('<div class="space-y-3"></div>')
  })
})

describe('SelectorDeDestino', () => {
  it('ofrece los destinos y, al final, crear un broker nuevo', () => {
    const html = renderToStaticMarkup(
      <SelectorDeDestino destinos={[{ id: 2, name: 'Balanz' }, { id: 5, name: 'IOL' }]} valor="" onCambio={() => {}} />)
    expect(html).toContain('Elegí un broker')
    expect(html).toContain('>Balanz</option>')
    expect(html).toContain('>IOL</option>')
    expect(html).toContain(`value="${CREAR_BROKER}"`)
    expect(html.indexOf('+ Crear un broker nuevo')).toBeGreaterThan(html.indexOf('>IOL<'))
  })
})

// El contenedor, en su primer dibujo (sin efectos: todavía no pidió nada). Lo que
// importa: la fecha NO viene puesta, está el «Hoy», un solo destino posible ya
// queda elegido, y el botón de mover está apagado sin vista previa.
describe('MoverDeBrokerModal — el formulario al abrir', () => {
  const BROKERS = [
    { id: 1, name: 'Cocos', currency: 'ARS' },
    { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 },
    { id: 3, name: 'Balanz', currency: 'ARS' },
    { id: 4, name: 'Schwab', currency: 'USD' },
  ]
  const OPCION = { key: 'k', asset: 'NVDA', cuenta: 'Cocos', moneda: 'ARS', dosMonedas: true, broker: 'Cocos', lots: [], qty: 10 }

  it('abre en «Tal cual»: sin fecha, sin cantidad, sin gasto, y el botón apagado', async () => {
    const { default: MoverDeBrokerModal } = await import('./MoverDeBrokerModal')
    const html = renderToStaticMarkup(
      <MoverDeBrokerModal opcion={OPCION} brokers={BROKERS} onClose={() => {}} onHecho={() => {}} onCrearBroker={() => {}} />)
    expect(html).toContain('Mover NVDA a otro broker')
    expect(html).toMatch(/aria-checked="true"[^>]*>.*?Tal cual/)
    expect(html).toContain('En una fecha')
    expect(html).toContain('Siempre estuvieron en el otro broker')
    expect(html).toMatch(/<option value="Balanz" selected="">Balanz<\/option>/)
    expect(html).not.toContain('¿Qué día llegaron')
    expect(html).not.toContain('Gasto del trámite')
    expect(html).toContain('Revisando tus compras…')
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>Pasar NVDA a Balanz<\/button>/)
  })

  it('«En una fecha»: título, bajada, destino, fecha sin valor y el botón apagado', async () => {
    const { default: MoverDeBrokerModal } = await import('./MoverDeBrokerModal')
    const html = renderToStaticMarkup(
      <MoverDeBrokerModal opcion={OPCION} brokers={BROKERS} onClose={() => {}} onHecho={() => {}} onCrearBroker={() => {}} modoInicial="pase" />)
    expect(html).toContain('Mover NVDA a otro broker')
    expect(html).toContain('Desde Cocos · en pesos')
    expect(html).toContain('¿A qué broker?')
    // Balanz es el único de la misma familia: queda elegido (Schwab es de afuera).
    expect(html).toMatch(/<option value="Balanz" selected="">Balanz<\/option>/)
    expect(html).not.toContain('>Schwab<')
    expect(html).toContain('¿Qué día llegaron a Balanz?')
    expect(html).toMatch(/placeholder="dd\/mm\/aaaa"[^>]*value=""|value=""[^>]*placeholder="dd\/mm\/aaaa"/)
    expect(html).toContain('>Hoy</button>')
    expect(html).toContain('Usá la fecha que figura en tu broker.')
    expect(html).toContain('Gasto del trámite (opcional)')
    expect(html).toMatch(/<button type="button" disabled=""[^>]*>Mover NVDA<\/button>/)
  })
})

// «Tal cual» (24/11/2026): la forma de POST /api/positions/tal-cual/vista-previa
// (la fija backend/tests/test_tal_cual.py).
describe('VistaTalCual', () => {
  const VISTA = {
    origen: 'Santander', destino: 'Galicia', asset: 'MSFT', moneda: 'ARS', cantidad: 20, freno: null,
    lotes: [{ fecha_compra: '2026-06-29', cantidad: 20, costo: 384000, moneda: 'ARS' }],
  }

  it('las compras con su fecha y su costo, y qué queda en cada broker', () => {
    const html = renderToStaticMarkup(<VistaTalCual vista={VISTA} />)
    expect(html).toContain('Se pasan estas compras a Galicia:')
    expect(html).toContain('20 MSFT · comprados el 29/06/2026 · costo $384.000 ARS')
    expect(html).toContain('Quedan en Galicia como si siempre hubieran estado ahí, con su fecha y su costo de compra. De Santander desaparecen: sin pérdida ni ganancia.')
    expect(html).not.toContain('Valían')
    expect(html).not.toContain('La plata con que las pagaste')
  })

  it('compras cargadas antes del 06/08/2026: avisa que su plata pasa con ellas', () => {
    const html = renderToStaticMarkup(<VistaTalCual vista={{ ...VISTA, plata_viaja: true }} />)
    expect(html).toContain('La plata con que las pagaste pasa con ellas: en Movimientos vas a ver que sale de Santander y entra en Galicia el día de cada compra.')
  })

  it('con el ojito, el costo se tapa y la cantidad y la fecha quedan', () => {
    const html = renderToStaticMarkup(<VistaTalCual vista={VISTA} hidden />)
    expect(html).toContain(`20 MSFT · comprados el 29/06/2026 · costo ${OCULTO}`)
    expect(html).not.toContain('384.000')
  })

  it('con freno: sólo el motivo, sin la lista', () => {
    const html = renderToStaticMarkup(<VistaTalCual vista={{ ...VISTA, freno: 'Tus MSFT en Santander vienen de un archivo.' }} />)
    expect(html).toContain('role="alert"')
    expect(html).toContain('Tus MSFT en Santander vienen de un archivo.')
    expect(html).not.toContain('Se pasan estas compras')
  })
})
