// useCurrencyChoice — la elección de moneda de la app, en un solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// El `CurrencyContext` guarda DOS ejes independientes (`currency` USD/ARS y
// `valuationDollar` mep/ccl). El riel de Configuración los presenta como UNA
// decisión de tres opciones (USD MEP · USD CCL · Pesos); este módulo es ese
// mapeo, sacado del componente para poder testearlo sin DOM y para que
// `fmtRate` no quede duplicado en el selector global del shell.
//
// El reparto de responsabilidades entre los dos controles:
//   • CurrencySwitcher (shell, todas las páginas) → SÓLO la moneda: USD | Pesos.
//   • CurrencyRail (/config → Tipos de cambio)    → además, CON QUÉ DÓLAR se
//     valúa (MEP / CCL). Preferencia que se toca una vez, no todos los días.
//
// No renderiza nada — sólo el modelo (opciones + activa + pick + cotizaciones).

import { useCurrency } from '../contexts/CurrencyContext'

// Las 3 opciones, en orden de riel.
export const CURRENCY_CHOICES = [
  { key: 'mep', label: 'USD MEP', hint: 'Dólar local (default)' },
  { key: 'ccl', label: 'USD CCL', hint: 'El dólar implícito del CEDEAR' },
  { key: 'ars', label: 'Pesos',   hint: 'Todos tus valores en pesos' },
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
