import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { cuerpoDeVenta, cuerpoDeConversion } from './formulariosCartera'
import fuenteEscritorio from '../pages/Positions.jsx?raw'
import fuenteCelular from '../pages/PositionsMobile.jsx?raw'

// El modal de venta se dibuja de verdad (el mismo que montan compu y celular) y
// se compara lo que MUESTRA con lo que se MANDARÍA. Antes de 2026-10-15 los dos
// salían de lecturas distintas: el modal entendía "10.820,00" y el envío no.
vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} })
const { SellModal } = await import('../pages/Positions')

const lote = { id: 1, broker: 'Cocos', asset: 'WMT', quantity: 20, invested: 182520, buy_price: 9126, entry_date: '2026-08-20' }
const venta = (extra) => ({
  broker: 'Cocos', asset: 'WMT', currency: 'ARS', quantity: '20', exit_price: '10820',
  tc_venta: 1536.9, date: '2026-10-15', commissions: '', ...extra,
})
const dibujar = (form) => renderToStaticMarkup(
  <SellModal form={form} setForm={() => {}} positions={[lote]} tcValuacion={1500} fxHist={null}
    onClose={() => {}} onConfirm={() => {}} />)
// "216.400,00 ARS" → 216400
const montoDe = (html, rotulo) => {
  const desde = html.indexOf(rotulo)
  const m = html.slice(desde).match(/>(−?[\d.]+,\d{2}) ARS</)
  return Number(m[1].replace('−', '').replace(/\./g, '').replace(',', '.'))
}

describe('venta: lo que se manda es lo que se ve', () => {
  // El caso de la captura del usuario y sus primos: todos se VEÍAN bien.
  const casos = [
    ['precio con miles y decimales', { exit_price: '10.820,00' }, { exit_price: 10820, quantity: 20 }],
    ['precio con punto de miles', { exit_price: '10.820' }, { exit_price: 10820, quantity: 20 }],
    ['precio con coma decimal', { exit_price: '10820,5' }, { exit_price: 10820.5, quantity: 20 }],
    ['cantidad con punto de miles', { quantity: '1.000', exit_price: '10' }, { exit_price: 10, quantity: 1000 }],
  ]
  for (const [nombre, cambio, esperado] of casos) {
    it(nombre, () => {
      const form = venta(cambio)
      const { body, error } = cuerpoDeVenta(form)
      expect(error).toBeUndefined()
      expect(body.exit_price).toBe(esperado.exit_price)
      expect(body.quantity).toBe(esperado.quantity)
      // El bruto que dibuja el modal es cantidad × precio de lo que se manda.
      expect(montoDe(dibujar(form), 'Bruto')).toBeCloseTo(body.quantity * body.exit_price, 2)
      // Y viaja como número, no como null.
      expect(JSON.parse(JSON.stringify(body)).exit_price).toBe(esperado.exit_price)
    })
  }

  it('la comisión escrita a la argentina se descuenta igual en pantalla y en el envío', () => {
    const form = venta({ commissions: '1.500,50' })
    const { body } = cuerpoDeVenta(form)
    expect(body.commissions).toBe(1500.5)
    expect(montoDe(dibujar(form), 'Neto recibido')).toBeCloseTo(216400 - 1500.5, 2)
  })

  it('el TC escrito con coma viaja; uno ilegible frena en vez de caer al de hoy', () => {
    expect(cuerpoDeVenta(venta({ tc_venta: '1.536,90' })).body.tc_venta).toBe(1536.9)
    expect(cuerpoDeVenta(venta({ tc_venta: '1,536.90' })).error).toMatch(/tipo de cambio/)
  })

  it('lo ilegible frena con un aviso, nunca viaja como null', () => {
    expect(cuerpoDeVenta(venta({ exit_price: '1.2.3' })).error).toMatch(/precio/)
    expect(cuerpoDeVenta(venta({ exit_price: '' })).error).toMatch(/precio/)
    expect(cuerpoDeVenta(venta({ quantity: 'abc' })).error).toMatch(/cantidad/)
    expect(cuerpoDeVenta(venta({ commissions: '1,2,3' })).error).toMatch(/comisión/)
  })

  it('comisión vacía = 0 y en dólares no se manda TC', () => {
    const { body } = cuerpoDeVenta(venta({ currency: 'USDT', tc_venta: '' }))
    expect(body.commissions).toBe(0)
    expect(body.currency).toBe('USD')
    expect('tc_venta' in body).toBe(false)
  })
})

describe('conversión: el campo espejo que escribe el sistema', () => {
  // ConvertModal escribe el lado calculado con separadores: 1.500.000 / 1.500 → "1.000".
  // Con `+campo` eso era US$ 1, sin error.
  it('"1.000" calculado por el modal viaja como mil', () => {
    const { body } = cuerpoDeConversion({
      from_broker: 'Cocos', direction: 'ars_to_usd', kind: 'MEP', date: '2026-10-15',
      ars_amount: '1500000', usd_amount: '1.000', tc: '1500',
    })
    expect(body.usd_amount).toBe(1000)
    expect(body.ars_amount).toBe(1500000)
  })
  it('montos con coma y TC con miles', () => {
    const { body } = cuerpoDeConversion({ ars_amount: '200.000,50', usd_amount: '133,33', tc: '1.500' })
    expect(body).toMatchObject({ ars_amount: 200000.5, usd_amount: 133.33, tc: 1500 })
  })
})

describe('guardia: ningún envío de cartera vuelve a leer con +campo', () => {
  // Los dos aparatos arman el cuerpo con cuerpoDeVenta / cuerpoDeConversion.
  for (const [nombre, fuente] of [['escritorio', fuenteEscritorio], ['celular', fuenteCelular]]) {
    it(nombre, () => {
      expect(fuente).not.toMatch(/[+]\s*(sellForm|convertForm)\.\w+/)
      expect(fuente).toMatch(/cuerpoDeVenta\(sellForm\)/)
      expect(fuente).toMatch(/cuerpoDeConversion\(convertForm\)/)
    })
  }
})
