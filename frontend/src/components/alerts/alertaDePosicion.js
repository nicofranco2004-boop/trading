// alertaDePosicion — a dónde lleva «Crear alerta» desde el menú de una posición
// de Cartera (la de la compu y la del celular: antes cada una tenía su copia).
// ═══════════════════════════════════════════════════════════════════════════
// Abre /alertas con el ticker precargado en SU riel, espejo de la valuación
// (priceSymbol): '.BA' para CEDEARs y brokers AR·USD, pelado para el resto.
//   • Cripto: SIEMPRE su ticker pelado en dólares (BTC → BTC-USD), nunca '.BA'
//     — aunque se haya comprado en un broker argentino, donde priceSymbol daría
//     'BTC.BA', que no cotiza y dejaba la alerta muerta.
//   • Un CEDEAR comprado en dólares (AAPLD) abre en dólares: el aviso mira su
//     precio en dólares (ver alertasTexto.esCedearEnDolares). Si resulta que no
//     cotiza en dólares, el formulario lo pasa a pesos (monedasPosibles).
import { priceSymbol, costInPesos, isArUsdBroker } from '../../utils/valuation'
import { isCrypto } from '../../utils/crypto'

export function linkDeAlerta(p) {
  if (isCrypto(p.asset)) return `/alertas?new=${encodeURIComponent(p.asset)}&ccy=USD`
  const arsRail = costInPesos(p) || p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)
  const sym = priceSymbol(p.asset, arsRail, p.asset_type)
  const cedearEnDolares = sym.toUpperCase().endsWith('.BA') && p.asset_type === 'CEDEAR'
    && ['USD', 'USDT'].includes(String(p.currency || '').toUpperCase())
  const ccy = !arsRail || cedearEnDolares ? 'USD' : 'ARS'
  return `/alertas?new=${encodeURIComponent(sym)}&ccy=${ccy}`
}
