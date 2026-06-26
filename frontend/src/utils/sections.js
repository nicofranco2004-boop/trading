// sections.js — clasificación de posiciones en SECCIONES de Renta Fija.
// Espejo de backend/importing/sections.py: misma lógica para que front y back
// coincidan. Una sección = (categoría, moneda): Bonos/Letras/FCI × USD/ARS.
// Renta variable (acciones/CEDEARs/cripto) → null.
import { getBondMeta } from './bondMeta'

// Renta fija conocida por catálogo: bono soberano/CER u ON corporativa. Excluye
// ETFs (TIP/GLD/etc. son renta variable aunque estén en BOND_META).
const _FIXED_META_TYPES = new Set(['sovereign', 'cer', 'corporate'])
export function isKnownArBond(symbol) {
  const m = getBondMeta(symbol)
  return !!m && _FIXED_META_TYPES.has(m.type)
}

export const CATEGORY_BONO = 'BONO'
export const CATEGORY_LETRA = 'LETRA'
export const CATEGORY_FCI = 'FCI'

const CATEGORY_LABEL = { BONO: 'Bonos', LETRA: 'Letras', FCI: 'FCI' }

// Patrón de ticker de letra/LECAP: letra inicial + día (1-2 díg) + código-mes + año
// (1 díg). Espeja maturity._LETRA_RX del backend (S28N5, T13F6, X23N3…).
const LETRA_RX = /^[A-Z]\d{1,2}[EFMAYJLGSOND]\d$/

export function isLetraTicker(symbol) {
  return LETRA_RX.test((symbol || '').trim().toUpperCase())
}

export function normCcy(currency) {
  const c = (currency || '').trim().toUpperCase()
  return (c === 'USD' || c === 'USDT') ? 'USD' : 'ARS'
}

// Devuelve {category, currency} si la posición es renta fija, o null si no.
export function positionSection(assetType, symbol, currency) {
  const at = (assetType || '').trim().toUpperCase()
  const sym = (symbol || '').trim().toUpperCase()
  const ccy = normCcy(currency)
  if (at === 'FUND') return { category: CATEGORY_FCI, currency: ccy }
  // Letra ANTES que bono (matchea el patrón aunque no esté en el catálogo).
  if (sym && isLetraTicker(sym)) return { category: CATEGORY_LETRA, currency: ccy }
  const FIXED = at === 'BOND' || at === 'BONO' || at === 'ON' || at === 'LETRA' || at === 'LECAP'
  if (FIXED || isKnownArBond(sym)) return { category: CATEGORY_BONO, currency: ccy }
  return null
}

export function isFixedIncome(p) {
  return positionSection(p.asset_type, p.asset, p.currency) != null
}

export function sectionKey(category, currency) {
  return `${category}|${normCcy(currency)}`
}

export function sectionLabel(category, currency) {
  return `${CATEGORY_LABEL[category] || category} ${normCcy(currency)}`
}

// Orden de presentación de las secciones.
const ORDER = ['BONO|USD', 'BONO|ARS', 'LETRA|USD', 'LETRA|ARS', 'FCI|USD', 'FCI|ARS']
export function sortSectionKeys(keys) {
  return [...keys].sort((a, b) => {
    const ia = ORDER.indexOf(a), ib = ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
}
