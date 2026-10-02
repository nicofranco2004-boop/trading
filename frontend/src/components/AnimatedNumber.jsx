// AnimatedNumber — renderiza un número que "cuenta" hacia su valor con count-up.
// ════════════════════════════════════════════════════════════════════════════
// Encapsula useCountUp en un componente para que el hook viva siempre dentro
// (cero riesgo de rules-of-hooks en el call-site, que puede tener early returns)
// y para componerlo limpio con <FlashValue>.
//
// Uso:
//   <AnimatedNumber value={portfolioTotalUsd} format={fmt} />
//   <AnimatedNumber value={x} format={(n) => `$${fmtNumber(n)}`} />
//   <AnimatedNumber value={x} format={fmt} visto={visto} />   ← cuenta al verse

import { useCountUp } from '../hooks/useCountUp'

// Sin número (null, undefined, NaN) muestra "—" y NO anima: useCountUp convierte
// lo que no es número en 0 (`Number(null)` es 0), así que una cotización que no
// llegó salía escrita "0,00%" — un número inventado, con flecha verde y todo.
// Antes de animar, la watchlist mostraba "—" en ese caso; eso vuelve a ser así.
//
// `visto` (de useAlVerse): el número cuenta desde 0 recién cuando su sección
// entra en pantalla. MIENTRAS NO SE VIO, el número está escondido (.por-entrar)
// y escrito con su valor FINAL. Antes cada pantalla pasaba `visto ? x : 0`, y
// ese 0 se veía: con la tarjeta asomada al pie de la pantalla, sin llegar a la
// porción que dispara `visto`, se leía "Tu cartera coincide con tu perfil en
// 0 de 8" o "Win rate 0 %" (medido en Chrome, 2026-10-02) — y un lector de
// pantalla lo leía siempre. Escondido, no se lee nada falso; escrito con el
// valor final, el lector de pantalla dice el número de verdad.
export default function AnimatedNumber({ value, format = (n) => n, duration, visto = true }) {
  const animated = useCountUp(visto ? value : 0, duration ? { duration } : undefined)
  const hayNumero = value != null && value !== '' && Number.isFinite(Number(value))
  if (!hayNumero) return <>—</>
  if (!visto) return <span className="por-entrar">{format(Number(value))}</span>
  return <>{format(animated)}</>
}
