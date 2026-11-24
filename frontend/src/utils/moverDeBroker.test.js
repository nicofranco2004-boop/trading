// «Mover a otro broker»: la lógica pura de la pantalla (spec E.3 / E.10).
//
// Qué fija:
//   · a qué cuentas se ofrece pasar (sin la misma cuenta —tampoco su pata en
//     dólares—, sin otra familia y sin Wallbit), con la misma regla de familia
//     que el servidor (C.1);
//   · que el pedido se lee con el único parser de números («1.000,5» = mil y medio);
//   · los textos de la vista previa, incluido «cierre del viernes 20/11».
import { describe, it, expect } from 'vitest'
import {
  destinosPosibles, familiaDeCuenta, puedeMoverse, cuerpoDeMover, textoDeFuente,
  lineaDeLote, lineaDelPuente, lineaDelValor, formateadorDeMontos, diaDeLaSemana,
  lineaDeFilaDePase, avisoDeFilaDePase, preguntaDeDeshacer, tituloDeLotePase,
  textoDeImportCambiaUnPase, faltaPrecio, esFilaDePase,
} from './moverDeBroker'
import { OCULTO } from './ocultarSaldos'

const BROKERS = [
  { id: 1, name: 'Balanz', currency: 'ARS' },
  { id: 2, name: 'Balanz · USD', currency: 'USDT', parent_broker_id: 1 },
  { id: 3, name: 'Cocos', currency: 'ARS' },
  { id: 4, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 3 },
  { id: 5, name: 'IOL', currency: 'ARS' },
  { id: 6, name: 'Schwab', currency: 'USD' },
  { id: 7, name: 'IBKR', currency: 'USD' },
  { id: 8, name: 'Binance', currency: 'USDT', is_exchange: 1 },
  { id: 9, name: 'Wallbit', currency: 'USD' },
  { id: 10, name: 'Ripio', currency: 'USDT', is_exchange: 1 },
]
const nombres = (lista) => lista.map(b => b.name)
const opcion = (o) => ({ asset: 'NVDA', cuenta: 'Cocos', moneda: 'ARS', broker: 'Cocos', dosMonedas: true, lots: [], ...o })

describe('destinosPosibles', () => {
  it('desde una cuenta argentina: las otras argentinas, sin la misma ni su pata en dólares', () => {
    expect(nombres(destinosPosibles(opcion(), BROKERS))).toEqual(['Balanz', 'IOL'])
  })

  it('una opción en dólares (vive en «Cocos · USD») tampoco puede ir a Cocos', () => {
    const o = opcion({ moneda: 'USD', broker: 'Cocos · USD' })
    expect(nombres(destinosPosibles(o, BROKERS))).toEqual(['Balanz', 'IOL'])
  })

  it('desde un broker de afuera: los de afuera, sin Wallbit', () => {
    const o = opcion({ cuenta: 'Schwab', broker: 'Schwab', moneda: 'USD', dosMonedas: false })
    expect(nombres(destinosPosibles(o, BROKERS))).toEqual(['IBKR'])
  })

  it('desde un exchange: sólo otros exchanges', () => {
    const o = opcion({ asset: 'BTC', cuenta: 'Binance', broker: 'Binance', moneda: 'USD', dosMonedas: false })
    expect(nombres(destinosPosibles(o, BROKERS))).toEqual(['Ripio'])
  })

  it('sin otro broker de la misma familia: vacío (la pantalla ofrece crear uno)', () => {
    const solo = [{ id: 1, name: 'Cocos', currency: 'ARS' }, { id: 2, name: 'Schwab', currency: 'USD' }]
    expect(destinosPosibles(opcion(), solo)).toEqual([])
    expect(destinosPosibles(null, BROKERS)).toEqual([])
  })

  it('la familia es la del servidor: pesos = AR, «X · USD» suelto = AR, is_exchange = exchange', () => {
    expect(familiaDeCuenta('Cocos · USD', BROKERS)).toBe('AR')
    expect(familiaDeCuenta('Viejo · USD', [{ id: 1, name: 'Viejo · USD', currency: 'USD' }])).toBe('AR')
    // El sufijo sin distinguir mayúsculas, como el servidor (`_is_ar_usd_subbroker`
    // pasa el nombre a minúsculas): datos viejos escritos «· usd».
    expect(familiaDeCuenta('Viejo · usd', [{ id: 1, name: 'Viejo · usd', currency: 'USD' }])).toBe('AR')
    expect(familiaDeCuenta('Binance', BROKERS)).toBe('EXCHANGE')
    expect(familiaDeCuenta('Schwab', BROKERS)).toBe('EXTERIOR')
    expect(familiaDeCuenta('No existe', BROKERS)).toBe(null)
  })
})

describe('puedeMoverse', () => {
  it('una acción o CEDEAR sí; efectivo, bono, letra, FCI y Wallbit no', () => {
    expect(puedeMoverse({ asset: 'NVDA', broker: 'Cocos' })).toBe(true)
    expect(puedeMoverse({ asset: 'ARS', broker: 'Cocos', is_cash: 1 })).toBe(false)
    expect(puedeMoverse({ asset: 'USD', broker: 'Cocos' })).toBe(false)
    expect(puedeMoverse({ asset: 'AL30', broker: 'Cocos' })).toBe(false)
    expect(puedeMoverse({ asset: 'XYZ', broker: 'Cocos', asset_type: 'BOND' })).toBe(false)
    expect(puedeMoverse({ asset: 'NVDA', broker: 'Cocos' }, { isBond: true })).toBe(false)
    expect(puedeMoverse({ asset: 'FCI:Balanz Ahorro', broker: 'Balanz' })).toBe(false)
    expect(puedeMoverse({ asset: 'X', broker: 'Balanz', asset_type: 'FUND' })).toBe(false)
    expect(puedeMoverse({ asset: 'VOO', broker: 'wallbit' })).toBe(false)
  })

  it('la fila agregada mira sus lotes', () => {
    expect(puedeMoverse({ asset: 'XYZ', broker: 'Cocos', _lots: [{ asset: 'XYZ', asset_type: 'BOND' }] })).toBe(false)
    expect(puedeMoverse({ asset: 'NVDA', broker: null, _lots: [{ asset: 'NVDA', broker: 'Cocos' }] })).toBe(true)
  })
})

describe('cuerpoDeMover', () => {
  const form = (o) => ({ destino: 'Balanz', fecha: '2026-11-20', cantidad: '', ...o })

  it('lee «1.000,5» como mil y medio, con el único parser', () => {
    const { body } = cuerpoDeMover(form({ cantidad: '1.000,5' }), opcion())
    expect(body).toEqual({
      broker_origen: 'Cocos', asset: 'NVDA', moneda: 'ARS', broker_destino: 'Balanz',
      fecha: '2026-11-20', cantidad: 1000.5,
    })
  })

  it('la cantidad vacía es «todo»: no viaja', () => {
    expect(cuerpoDeMover(form(), opcion()).body).not.toHaveProperty('cantidad')
  })

  it('precio a mano y gasto del trámite, cada uno con su moneda', () => {
    const { body } = cuerpoDeMover(form({ precioManual: '25.000', gastoMonto: '5.000', gastoMoneda: 'ARS' }), opcion())
    expect(body.precio_manual).toBe(25000)
    expect(body.gasto).toEqual({ monto: 5000, moneda: 'ARS' })
    expect(cuerpoDeMover(form({ gastoMonto: '3,5', gastoMoneda: 'USD' }), opcion()).body.gasto).toEqual({ monto: 3.5, moneda: 'USD' })
  })

  it('la opción en dólares manda la pata en dólares y moneda USD', () => {
    const { body } = cuerpoDeMover(form(), opcion({ moneda: 'USD', broker: 'Cocos · USD' }))
    expect(body.broker_origen).toBe('Cocos · USD')
    expect(body.moneda).toBe('USD')
  })

  it('sin fecha, sin destino o con números que no son números: el error, no un pedido', () => {
    expect(cuerpoDeMover(form({ fecha: '' }), opcion())).toEqual({ error: 'Elegí la fecha del pase.' })
    expect(cuerpoDeMover(form({ destino: '' }), opcion()).error).toBeTruthy()
    expect(cuerpoDeMover(form({ cantidad: '1,2,3' }), opcion()).error).toBeTruthy()
    expect(cuerpoDeMover(form({ cantidad: '0' }), opcion()).error).toBeTruthy()
    expect(cuerpoDeMover(form({ gastoMonto: 'abc' }), opcion()).error).toBeTruthy()
    expect(cuerpoDeMover(form(), null).error).toBeTruthy()
  })
})

describe('textoDeFuente', () => {
  it('cada fuente con sus palabras', () => {
    expect(textoDeFuente('cierre_del_dia', '2026-11-20', '2026-11-20')).toBe('cierre de ese día')
    expect(textoDeFuente('ultimo_precio', '2026-11-23', '2026-11-23')).toBe('último precio que tenemos')
    expect(textoDeFuente('precio_a_mano', null, '2026-11-20')).toBe('precio que escribiste')
    expect(textoDeFuente('precio_cargado', '2026-11-23', '2026-11-23')).toBe('precio que cargaste a mano')
  })

  it('una vela de otro día dice cuál: «cierre del viernes 20/11»', () => {
    expect(textoDeFuente('ultimo_precio', '2026-11-20', '2026-11-22')).toBe('cierre del viernes 20/11')
    expect(diaDeLaSemana('2026-11-23')).toBe('lunes 23/11')
  })
})

const PLAN = {
  ok: true,
  origen: { cuenta: 'Cocos', etiqueta: 'Cocos · en pesos' },
  destino: { cuenta: 'Balanz', brokers_a_crear: [] },
  asset: 'NVDA', moneda: 'ARS', fecha: '2026-11-20', cantidad: 10, cantidad_disponible: 25,
  lotes: [
    { lote_id: 1, a_mano: false, fecha_compra: '2024-03-10', cantidad: 4, de_un_lote_de: 4, costo: 120000, comisiones: 600, moneda: 'ARS' },
    { lote_id: 2, a_mano: true, fecha_compra: '2024-06-01', cantidad: 6, de_un_lote_de: 10, costo: 180000, comisiones: 0, moneda: 'ARS' },
  ],
  valuacion: { precio_unitario: 25000, moneda_precio: 'ARS', fuente: 'cierre_del_dia', fecha_precio: '2026-11-20', dolar: 1400 },
  valor_nativo: 250000, valor_ars: 250000, valor_usd: 178.57, costo_usd: 92.3, puente_usd: 86.27,
}

describe('los renglones de la vista previa', () => {
  it('un lote entero, uno partido y cargado a mano', () => {
    expect(lineaDeLote(PLAN.lotes[0], 'NVDA')).toBe('4 NVDA · comprados el 10/03/2024 · costo $120.000 ARS')
    expect(lineaDeLote(PLAN.lotes[1], 'NVDA')).toBe('6 NVDA · comprados el 01/06/2024 · costo $180.000 ARS · parte de un lote de 10 · cargado a mano')
  })

  it('con el ojito, los montos se tapan y la cantidad y la fecha quedan', () => {
    const t = lineaDeLote(PLAN.lotes[0], 'NVDA', formateadorDeMontos(true))
    expect(t).toBe(`4 NVDA · comprados el 10/03/2024 · costo ${OCULTO}`)
  })

  it('el valor del día, con su fuente', () => {
    expect(lineaDelValor(PLAN)).toBe('Valían $250.000 ARS (USD 178,57) el 20/11/2026 · cierre de ese día')
  })

  it('el puente: ganancia o pérdida según el signo, y siempre «no es una venta»', () => {
    const gana = lineaDelPuente(PLAN, 'Cocos', 'Balanz')
    expect(gana).toEqual([
      'Te costaron USD 92,30.',
      'En Cocos va a figurar una ganancia de USD 86,27 hasta el pase, y en Balanz arrancan valiendo USD 178,57.',
      'No es una venta: no cuenta en tus operaciones cerradas ni en los impuestos.',
    ])
    const pierde = lineaDelPuente({ ...PLAN, valor_usd: 80, costo_usd: 92.3, puente_usd: -12.3 }, 'Cocos', 'Balanz')
    expect(pierde[1]).toBe('En Cocos va a figurar una pérdida de USD 12,30 hasta el pase, y en Balanz arrancan valiendo USD 80,00.')
  })
})

describe('Movimientos e Importaciones', () => {
  const salida = { type: 'TRASPASO_SALIDA', asset: 'NVDA', quantity: 10, broker: 'Cocos', contraparte: 'Balanz', traspaso_id: 't1', estado: 'vivo' }
  const entrada = { ...salida, type: 'TRASPASO_ENTRADA', broker: 'Balanz', contraparte: 'Cocos' }

  it('la fila de un pase dice hacia dónde fue', () => {
    expect(esFilaDePase(salida)).toBe(true)
    expect(esFilaDePase({ type: 'BUY' })).toBe(false)
    expect(lineaDeFilaDePase(salida)).toBe('10 NVDA → Balanz')
    expect(lineaDeFilaDePase(entrada)).toBe('10 NVDA ← Cocos')
  })

  it('desfasado e incompleto tienen su renglón; vivo no', () => {
    expect(avisoDeFilaDePase(salida)).toBe(null)
    expect(avisoDeFilaDePase({ ...entrada, estado: 'desfasado' }))
      .toBe('Cambió la historia de Cocos y este pase quedó desactualizado: deshacelo y hacelo de nuevo.')
    expect(avisoDeFilaDePase({ ...salida, estado: 'incompleto' })).toBe('Balanz ya no existe.')
  })

  it('la pregunta de deshacer, según el estado y el lado que queda', () => {
    const t = { id: 't1', asset: 'NVDA', cantidad: 10, broker_origen: 'Cocos', broker_destino: 'Balanz', estado: 'vivo' }
    expect(preguntaDeDeshacer(t, salida)).toBe(
      '¿Deshacer el pase de 10 NVDA de Cocos a Balanz?\n\n' +
      'Los títulos vuelven a Cocos con su costo original, y si cargaste el gasto del trámite, vuelve a la caja.')
    expect(preguntaDeDeshacer({ ...t, estado: 'incompleto' }, entrada)).toMatch(
      /Cocos ya no existe: al deshacer el pase, los 10 NVDA salen de Balanz y no vuelven a ningún lado\.$/)
  })

  it('el lote de Importaciones que es un pase', () => {
    expect(tituloDeLotePase({ asset: 'NVDA', cantidad: 10, lado: 'salida', contraparte: 'Balanz' })).toBe('Pase de 10 NVDA a Balanz')
    expect(tituloDeLotePase({ asset: 'NVDA', cantidad: 10, lado: 'entrada', contraparte: 'Cocos' })).toBe('Pase de 10 NVDA desde Cocos')
  })

  it('el bloqueo del importador usa el texto del servidor si viene armado', () => {
    expect(textoDeImportCambiaUnPase({ mensaje: 'Texto del servidor.' })).toBe('Texto del servidor.')
    expect(textoDeImportCambiaUnPase({ asset: 'NVDA', broker: 'Cocos', op: 'BUY', fecha: '2026-11-20', contraparte: 'Balanz', lado: 'origen' }))
      .toMatch(/^Este archivo trae compras de NVDA en Cocos, anteriores a tu pase del 20\/11\/2026 a Balanz\./)
  })

  it('reconoce el 409 «sin precio» de la vista previa', () => {
    const e = { payload: { detail: { codigo: 'sin_precio', mensaje: 'No encontramos…', moneda_precio: 'ARS' } } }
    expect(faltaPrecio(e)?.moneda_precio).toBe('ARS')
    expect(faltaPrecio({ payload: { detail: 'otro error' } })).toBe(null)
  })
})

// Movimientos: el filtro «Pases», su contador y el tacho (revisión E12, problemas 1 y 3).
describe('Movimientos · el filtro «Pases», su número y qué filas tienen tacho', () => {
  const FILAS = [
    { id: 's', type: 'TRASPASO_SALIDA', traspaso_id: 'abc', borrable: false },
    { id: 'e', type: 'TRASPASO_ENTRADA', traspaso_id: 'abc', borrable: false },
    { id: 'g', type: 'FEE', traspaso_id: 'abc', borrable: false },          // el gasto del trámite
    // La compra original de un lote cargado a mano que se pasó (D.9.2): sin traspaso_id.
    { id: 'trp-abc-0', type: 'BUY', source: 'traspaso', borrable: false },
    { id: 1, type: 'DEPOSIT' },
    { id: 2, type: 'FEE' },
    { id: 3, type: 'BUY' },
  ]

  it('el número del botón usa la MISMA regla que el filtro (antes «Pases» daba siempre 0 y no aparecía)', async () => {
    const { cuantosDelTipo, coincideConElTipo } = await import('../components/operations/shared')
    expect(cuantosDelTipo(FILAS, 'PASE')).toBe(3)
    expect(cuantosDelTipo(FILAS, 'PASE')).toBe(FILAS.filter(m => coincideConElTipo(m, 'PASE')).length)
    expect(cuantosDelTipo(FILAS, 'FEE')).toBe(2)
    expect(cuantosDelTipo(FILAS, 'all')).toBe(FILAS.length)
    expect(cuantosDelTipo(FILAS, 'DIVIDEND')).toBe(0)
  })

  it('nada de un pase tiene tacho: ni las patas, ni el gasto, ni la compra `trp-…` (borrable: false)', async () => {
    const { puedeBorrarMovimiento } = await import('../components/operations/shared')
    expect(FILAS.filter(puedeBorrarMovimiento).map(m => m.id)).toEqual([1, 2, 3])
    // Las conversiones con receta siguen con tacho; las viejas, sin.
    expect(puedeBorrarMovimiento({ type: 'FX_ARS_TO_USD', borrable: true })).toBe(true)
    expect(puedeBorrarMovimiento({ type: 'FX_ARS_TO_USD', borrable: false })).toBe(false)
  })
})

describe('el renglón del gasto del trámite en la vista previa', () => {
  it('lo que entendió el servidor, tapado con el ojito; vacío sin gasto', async () => {
    const { lineaDelGasto } = await import('./moverDeBroker')
    const plan = { gasto: { monto: 12.5, moneda: 'USD', broker: 'Cocos · USD' } }
    expect(lineaDelGasto(plan, 'Cocos')).toBe('Gasto del trámite: $12,50 USD de la caja de Cocos · USD.')
    expect(lineaDelGasto(plan, 'Cocos', formateadorDeMontos(true))).toBe(`Gasto del trámite: ${OCULTO} de la caja de Cocos · USD.`)
    expect(lineaDelGasto({ gasto: null }, 'Cocos')).toBe('')
    expect(lineaDelGasto(null, 'Cocos')).toBe('')
  })
})
