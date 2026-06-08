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

export default function AnimatedNumber({ value, format = (n) => n, duration }) {
  const animated = useCountUp(value, duration ? { duration } : undefined)
  return <>{format(animated)}</>
}
