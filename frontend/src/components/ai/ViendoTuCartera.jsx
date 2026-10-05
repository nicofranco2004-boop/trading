// ViendoTuCartera — "Viendo tu cartera · 12 posiciones · 3 brokers".
// ═══════════════════════════════════════════════════════════════════════════
// Lo que Mervall-E va a leer cuando le preguntes. Lo dicen la cabecera de /ai
// y la isla, con el mismo texto y los mismos números (los saca
// utils/aiSnapshot.resumenDeCartera de la lectura que viaja con la pregunta).
//
// Los números CUENTAN sólo si la lectura llegó con esto a la vista: contar
// dice "recién lo leí". Si al aparecer ya estaba leída (abrís la isla por
// segunda vez), se escriben quietos. Si después se vuelve a leer porque cambió
// algo (guardaste una operación), cuentan otra vez: es una lectura nueva.

import { useRef } from 'react'
import AnimatedNumber from '../AnimatedNumber'

// "1 posición", "12 posiciones": el número y su palabra juntos, así también se
// leen bien MIENTRAS cuentan (antes la palabra salía del número final y,
// contando hacia 12, se leía "1 posiciones" por un instante).
const conPalabra = (uno, varios) => (n) => {
  const r = Math.round(n)
  return `${r} ${r === 1 ? uno : varios}`
}

export default function ViendoTuCartera({ resumen, sinLectura = null }) {
  // ¿La lectura llegó con esto a la vista? Sí si apareció sin lectura, o si
  // la lectura se fue (se está releyendo: "Leyendo tu cartera…") y volvió.
  const llegaALaVista = useRef(!resumen)
  const huboLectura = useRef(!!resumen)
  if (resumen && !huboLectura.current) llegaALaVista.current = true
  huboLectura.current = !!resumen
  if (!resumen) return sinLectura
  const { posiciones, brokers } = resumen
  const numero = (n, uno, varios) => {
    const formato = conPalabra(uno, varios)
    return llegaALaVista.current ? <AnimatedNumber value={n} format={formato} /> : formato(n)
  }
  return (
    <span className="truncate">
      Viendo tu cartera
      {posiciones != null && <> · <span className="tabular">{numero(posiciones, 'posición', 'posiciones')}</span></>}
      {brokers ? <> · <span className="tabular">{numero(brokers, 'broker', 'brokers')}</span></> : null}
    </span>
  )
}
