// useCurrencyChoice — la elección de moneda de la app, en un solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// El `CurrencyContext` guarda DOS ejes independientes (`currency` USD/ARS y
// `valuationDollar` mep/ccl) pero para el usuario es UNA sola decisión de tres
// opciones: USD MEP · USD CCL · Pesos. Ese mapeo vivía adentro del CurrencyRail
// (el control ancho de /config). Cuando el selector pasó a ser global —fijo en
// el shell, disponible en todas las páginas— hubo que montarlo en dos lugares
// más, así que el mapeo se extrajo acá: si hay dos copias, se desincronizan y
// el mismo click hace cosas distintas según desde dónde lo toques.
//
// No renderiza nada — sólo el modelo (opciones + activa + pick + cotizaciones).
// Consumidores: components/CurrencyRail.jsx (Config) y
// components/CurrencySwitcher.jsx (sidebar desktop + barra superior mobile).

import { useCurrency } from '../contexts/CurrencyContext'

// Las 3 opciones, en orden de riel. `symbol` + `tag` son las piezas cortas que
// usa el control global: juntas en la pastilla de la barra mobile ("US$ MEP") y
// apiladas en la sidebar colapsada, donde el ancho útil son 40px.
export const CURRENCY_CHOICES = [
  { key: 'mep', label: 'USD MEP', symbol: 'US$', tag: 'MEP', hint: 'Dólar local (default)' },
  { key: 'ccl', label: 'USD CCL', symbol: 'US$', tag: 'CCL', hint: 'El dólar implícito del CEDEAR' },
  { key: 'ars', label: 'Pesos',   symbol: '$',   tag: 'ARS', hint: 'Todos tus valores en pesos' },
]

/**
 * fmtRate — cotización ARS/USD para el subtítulo de una opción ("$1.424").
 * Devuelve null si todavía no llegó /dolar (el caller deja el espacio vacío).
 */
export function fmtRate(v) {
  const n = Number(v)
  if (v == null || !Number.isFinite(n) || n <= 0) return null
  return '$' + n.toLocaleString('es-AR', { maximumFractionDigits: 0 })
}

/**
 * activeChoiceKey — de los dos ejes del contexto a la opción visible.
 * Pura: se testea sin montar React.
 */
export function activeChoiceKey(currency, valuationDollar) {
  if (currency === 'ARS') return 'ars'
  return valuationDollar === 'ccl' ? 'ccl' : 'mep'
}

export function useCurrencyChoice() {
  const { currency, valuationDollar, setCurrency, setValuationDollar, dolar } = useCurrency()
  const active = activeChoiceKey(currency, valuationDollar)

  // Se muestra el MEDIO — el mismo dólar con el que se valúa la cartera (no la
  // punta de venta), para que la tasa del selector coincida con el total.
  const rates = {
    mep: fmtRate(dolar?.mep?.medio ?? dolar?.mep?.venta),
    ccl: fmtRate(dolar?.ccl?.medio ?? dolar?.ccl?.venta),
    ars: 'ARS',
  }

  // Al elegir "Pesos" NO se pisa valuationDollar: se conserva para que al
  // volver a USD el user recupere su elección MEP/CCL (round-trip).
  function pick(key) {
    if (key === 'ars') {
      setCurrency('ARS')
    } else {
      setCurrency('USD')
      setValuationDollar(key)
    }
  }

  const activeOption = CURRENCY_CHOICES.find(o => o.key === active) || CURRENCY_CHOICES[0]

  return { options: CURRENCY_CHOICES, active, activeOption, rates, pick }
}
