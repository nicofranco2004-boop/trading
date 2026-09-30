// AnimatedNumber — renderiza un número que "cuenta" hacia su valor con count-up.
// ════════════════════════════════════════════════════════════════════════════
// Encapsula useCountUp en un componente para que el hook viva siempre dentro
// (cero riesgo de rules-of-hooks en el call-site, que puede tener early returns)
// y para componerlo limpio con <FlashValue>.
//
// Uso:
//   <AnimatedNumber value={portfolioTotalUsd} format={fmt} />
//   <AnimatedNumber value={x} format={(n) => `$${fmtNumber(n)}`} />

import { useCountUp } from '../hooks/useCountUp'

// Sin número (null, undefined, NaN) muestra "—" y NO anima: useCountUp convierte
// lo que no es número en 0 (`Number(null)` es 0), así que una cotización que no
// llegó salía escrita "0,00%" — un número inventado, con flecha verde y todo.
// Antes de animar, la watchlist mostraba "—" en ese caso; eso vuelve a ser así.
export default function AnimatedNumber({ value, format = (n) => n, duration }) {
  const animated = useCountUp(value, duration ? { duration } : undefined)
  const hayNumero = value != null && value !== '' && Number.isFinite(Number(value))
  return <>{hayNumero ? format(animated) : '—'}</>
}
