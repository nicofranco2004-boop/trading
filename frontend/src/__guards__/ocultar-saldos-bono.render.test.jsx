// «Ocultar saldos» en el detalle de un bono (re-test de la auditoría A, 29/10):
// mostraba lo cobrado en cupones y amortizaciones y «De eso es ganancia real»
// con el ojito prendido. Se dibuja con los mismos props que le pasa la Cartera.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { PrivacyProvider } from '../contexts/PrivacyContext'
import { BondDetailBody } from '../components/BondDetail'

const props = {
  p: { asset: 'AL30', quantity: 1000, invested: 600, broker: 'IOL' },
  summary: { coupons: 12.34, amortizations: 43.21, total: 55.55, totalUsd: 55.55, pnlContribution: 12.34,
    couponsUsd: 12.34, amortizationsUsd: 43.21, pnlContributionUsd: 12.34 },
  isARS: false, currentPrice: 0.62, tcMep: 1500, cobros: [], brokers: [],
}
function ver(ojito) {
  globalThis.localStorage = { getItem: () => (ojito ? '1' : '0'), setItem() {}, removeItem() {} }
  return renderToStaticMarkup(<PrivacyProvider><BondDetailBody {...props} /></PrivacyProvider>).replace(/<[^>]+>/g, ' ')
}

describe('detalle de un bono con «Ocultar saldos»', () => {
  it('apagado se ve lo cobrado; prendido, no', () => {
    const apagado = ver(false)
    expect(apagado).toContain('55,55')
    expect(apagado).toContain('ganancia real')
    const prendido = ver(true)
    for (const m of ['55,55', '12,34', '43,21']) expect(prendido, m).not.toContain(m)
    expect(prendido).toContain('••••••')
  })
})
