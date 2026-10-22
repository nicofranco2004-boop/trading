// EtiquetaFila — las etiquetas chicas que acompañan el nombre de un activo en
// una fila: la moneda en que se compró, "Efectivo", "Bono" y "Falta TC".
// ════════════════════════════════════════════════════════════════════════════
// Pastilla redonda, sin borde, en sans y en minúscula (la opción B que eligió
// Nico el 2026-10-20). Antes eran cajitas con borde, en mayúsculas espaciadas y
// letra de máquina de escribir ("ARS", "CASH", "TC?"), escritas a mano en cada
// pantalla — y la moneda en pesos usaba el ÁMBAR de las advertencias, así que
// una fila en pesos con el dólar de compra faltante parecía tener dos alertas.
//
// Los colores dicen una sola cosa cada uno:
//   • la moneda es un DATO, no una alerta: fondo neutro + un puntito
//     (celeste = pesos, aqua = dólares; el verde queda para las ganancias,
//     regla de tailwind.config.js);
//   • el ámbar queda SÓLO para "Falta TC", que sí pide hacer algo.
//
// `corta`: para el celular, donde la columna del activo mide 118px.

import { Wallet, Coins, AlertCircle } from 'lucide-react'

const BASE = 'inline-flex items-center gap-1 rounded-full px-2 py-px leading-normal font-medium whitespace-nowrap flex-none'
const NEUTRA = 'bg-bg-2 text-ink-1'

const PUNTO = { ARS: 'bg-data-blue', USD: 'bg-data-cyan' }

function Punto({ moneda }) {
  return <span className={`w-1.5 h-1.5 rounded-full flex-none ${PUNTO[moneda]}`} aria-hidden="true" />
}

/** moneda: 'ARS' | 'USD' | 'AMBAS' (una fila que junta compras en las dos). */
export function EtiquetaMoneda({ moneda, corta = false, className = '', title }) {
  // Corta (celular): "$" / "US$", y las dos monedas sólo con los dos puntitos —
  // en los ~30px que le quedan al lado del nombre, "$ y US$" se cortaba.
  const textos = corta
    ? { ARS: '$', USD: 'US$', AMBAS: '' }
    : { ARS: 'Pesos', USD: 'Dólares', AMBAS: 'Pesos y dólares' }
  const nombres = { ARS: 'Pesos', USD: 'Dólares', AMBAS: 'Pesos y dólares' }
  const m = moneda === 'ARS' || moneda === 'USD' ? moneda : 'AMBAS'
  const base = corta ? BASE.replace('gap-1', 'gap-0.5').replace('px-2', 'px-1.5') : BASE
  return (
    <span className={`${base} ${NEUTRA} ${className}`} title={title || nombres[m]} aria-label={nombres[m]}>
      {m === 'AMBAS'
        ? <><Punto moneda="ARS" /><Punto moneda="USD" /></>
        : <Punto moneda={m} />}
      {textos[m]}
    </span>
  )
}

export function EtiquetaEfectivo({ className = '' }) {
  return (
    <span className={`${BASE} ${NEUTRA} text-ink-2 ${className}`}>
      <Wallet size={11} strokeWidth={1.75} aria-hidden="true" />
      Efectivo
    </span>
  )
}

export function EtiquetaBono({ className = '' }) {
  return (
    <span className={`${BASE} bg-rendi-accent/10 text-rendi-accent ${className}`} title="Bono / Obligación Negociable">
      <Coins size={11} strokeWidth={1.75} aria-hidden="true" />
      Bono
    </span>
  )
}

/** Con `onClick` es un botón (lleva a cargar el dato); sin él, sólo avisa. */
export function EtiquetaFaltaTc({ onClick, className = '', title }) {
  const cls = `${BASE} bg-rendi-warn/15 text-rendi-warn ${className}`
  const t = title || 'Sin tipo de cambio de compra registrado: este lote usa el dólar de hoy para el costo en USD.'
  const contenido = <><AlertCircle size={11} strokeWidth={1.75} aria-hidden="true" />Falta TC</>
  return onClick
    ? <button type="button" onClick={onClick} className={`${cls} hover:bg-rendi-warn/25 transition`} title={`${t} Tocá para cargarlo.`}>{contenido}</button>
    : <span className={`${cls} select-none`} title={t}>{contenido}</span>
}
