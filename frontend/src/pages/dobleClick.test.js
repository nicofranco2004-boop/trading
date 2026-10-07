import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo, clic, buscarBoton, texto } from '../testing/navegadorMinimo'

// 🔴 UN DOBLE CLICK EN UN ALTA CREABA DOS REGISTROS (2026-10-07).
//
// El servidor ya "reclama" antes de editar, cobrar, vender o borrar: un doble
// click ahí no duplica plata. En un alta no puede: dos "Guardar" de la misma
// compra son, para él, dos compras. El único que sabe que fue un doble click
// es la pantalla, y estos botones no tenían freno —o lo tenían escrito pero
// nadie lo prendía (`CashFlowModal` traía `disabled={saving}` y ninguna de las
// dos pantallas que lo abren le pasaba `saving`).
//
// Acá se montan los formularios DE VERDAD y se les hace click como el
// navegador (el evento entra por el escucha de React en la raíz, así que un
// botón apagado lo ignora igual que en pantalla). Dos clicks dentro del mismo
// `enActo` caen en el mismo turno: React todavía no redibujó, el `disabled`
// todavía no está, y lo único que puede frenar el segundo es el freno de
// hooks/useEnVuelo.

vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false, useAnchoMinimo: () => true, MOBILE_BREAKPOINT_PX: 768 }))

let api, CashFlowModal, SellModal, ConvertModal, PositionFormModal, OpFormModal, PlazosFijosGroup, ToastProvider
beforeAll(async () => {
  instalarNavegadorMinimo()
  vi.stubGlobal('confirm', () => true)
  api = (await import('../utils/api')).api
  CashFlowModal = (await import('../components/cash/CashFlowModal')).default
  ;({ SellModal, ConvertModal, PositionFormModal } = await import('./Positions'))
  ;({ OpFormModal } = await import('./Operations'))
  PlazosFijosGroup = (await import('../components/PlazosFijosGroup')).default
  ;({ ToastProvider } = await import('../components/Toast'))
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

/** Un pedido que no vuelve hasta que la prueba lo suelta. */
function pedidoColgado() {
  let soltar
  const fn = vi.fn(() => new Promise(r => { soltar = r }))
  return { fn, soltar: () => soltar() }
}

const HOY = '2026-10-07'
const nada = () => {}

/**
 * Doble click (dos clicks en el mismo turno) sobre el botón `rotulo` del
 * formulario montado; después, un tercero ya con el botón apagado; al final
 * suelta el pedido y comprueba que el botón vuelve.
 */
async function probarFreno(elemento, rotulo, pedido) {
  const m = await montar(elemento)
  const boton = buscarBoton(m.contenedor, rotulo)
  expect(boton, `no encontré el botón «${rotulo}»`).toBeTruthy()
  expect(boton.hasAttribute('disabled')).toBe(false)

  await enActo(() => { clic(m.contenedor, boton); clic(m.contenedor, boton) })
  expect(pedido.fn).toHaveBeenCalledTimes(1)
  expect(boton.hasAttribute('disabled')).toBe(true)
  expect(texto(boton)).toContain('Guardando…')

  await enActo(() => clic(m.contenedor, boton))
  expect(pedido.fn).toHaveBeenCalledTimes(1)

  await enActo(async () => { pedido.soltar(); await Promise.resolve() })
  expect(boton.hasAttribute('disabled')).toBe(false)
  expect(texto(boton)).toContain(rotulo)
  await m.desmontar()
}

describe('un doble click manda UN pedido', () => {
  it('Depositar (CashFlowModal, compu y celular)', async () => {
    const pedido = pedidoColgado()
    await probarFreno(h(CashFlowModal, {
      form: { broker: 'IOL', currency: 'USD', direction: 'deposit', amount: '100', available: 0, date: HOY },
      setForm: nada, tcValuacion: 1400, fxHist: null, onClose: nada, onConfirm: pedido.fn,
    }), 'Confirmar depósito', pedido)
  })

  it('Vender (SellModal, compu y celular)', async () => {
    const pedido = pedidoColgado()
    await probarFreno(h(SellModal, {
      form: { broker: 'IBKR', asset: 'AAPL', currency: 'USD', quantity: '1', exit_price: '200', tc_venta: '', date: HOY, commissions: '' },
      setForm: nada,
      positions: [{ id: 1, broker: 'IBKR', asset: 'AAPL', quantity: 5, invested: 750, buy_price: 150, entry_date: '2026-01-02' }],
      tcValuacion: 1400, fxHist: null, onClose: nada, onConfirm: pedido.fn,
    }), 'Confirmar venta', pedido)
  })

  it('Comprar USD (ConvertModal, compu y celular)', async () => {
    const pedido = pedidoColgado()
    await probarFreno(h(ConvertModal, {
      form: { direction: 'ars_to_usd', from_broker: 'IOL', available: 1e7, tc_compra_avg: null, kind: 'MEP', ars_amount: '140000', usd_amount: '100', tc: '1400', date: HOY },
      setForm: nada, tcValuacion: 1400, onClose: nada, onConfirm: pedido.fn,
    }), 'Confirmar conversión', pedido)
  })

  it('Agregar posición (PositionFormModal, compu y celular)', async () => {
    const pedido = pedidoColgado()
    await probarFreno(h(PositionFormModal, {
      mode: 'add',
      form: { broker: 'IBKR', asset: 'AAPL', is_cash: false, buy_price: '150', quantity: '2', invested: '300', tc_compra: '', commissions: '', notes: '', price_override: '', entry_date: HOY, asset_type: 'STOCK', currency: '' },
      setForm: nada, brokers: [{ name: 'IBKR', currency: 'USD' }], selectedBrokerCurrency: 'USD', tcValuacion: 1400,
      onClose: nada, onSave: pedido.fn,
    }), 'Guardar', pedido)
  })

  it('Guardar operación (OpFormModal de Movimientos)', async () => {
    const pedido = pedidoColgado()
    await probarFreno(h(OpFormModal, {
      mode: 'add',
      form: { date: HOY, broker: 'IBKR', asset: 'AAPL', op_type: 'Venta', entry_price: '150', exit_price: '200', quantity: '1', pnl_usd: '50', pnl_pct: '', commissions: '', mueve_efectivo: false },
      setForm: nada, brokers: [{ name: 'IBKR', currency: 'USD' }], onSave: pedido.fn, onClose: nada,
    }), 'Guardar', pedido)
  })
})

describe('Plazo fijo vencido: cobrar dos veces manda UN cobro', () => {
  const PF = {
    id: 9, banco: 'Galicia', capital: 100000, moneda: 'ARS', tasa: 0.3, rate_type: 'TNA',
    fecha_inicio: '2026-08-01', plazo_dias: 30, fecha_vencimiento: '2026-08-31',
    modalidad: 'al_vencimiento', renovacion_auto: false,
  }
  const montarPf = () => montar(h(ToastProvider, null, h(PlazosFijosGroup, {
    reloadKey: 0, brokers: [{ id: 1, name: 'IOL', currency: 'ARS' }], onChange: nada,
  })))

  it('el doble click en «IOL» (acreditar en el broker) sale una sola vez, y apaga también «Retirar»', async () => {
    const cobro = pedidoColgado()
    vi.spyOn(api, 'get').mockResolvedValue([PF])
    const post = vi.spyOn(api, 'post').mockImplementation(cobro.fn)
    const m = await montarPf()
    await enActo(() => clic(m.contenedor, buscarBoton(m.contenedor, 'Cobrar')))

    const enIol = buscarBoton(m.contenedor, 'IOL')
    await enActo(() => { clic(m.contenedor, enIol); clic(m.contenedor, enIol) })
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/plazos-fijos/9/cobrar', { broker: 'IOL' })

    // Con el cobro viajando, «Retirar» del MISMO plazo fijo tampoco sale.
    const retirar = buscarBoton(m.contenedor, 'Retirar')
    expect(retirar.hasAttribute('disabled')).toBe(true)
    await enActo(() => clic(m.contenedor, retirar))
    expect(post).toHaveBeenCalledTimes(1)

    await enActo(async () => { cobro.soltar({ monto: 102000 }); await Promise.resolve() })
    await m.desmontar()
    vi.restoreAllMocks()
  })
})
