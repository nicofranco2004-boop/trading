// NumeroQueCambia — un número que, después de que el usuario hizo algo (cobró un
// cupón o un dividendo, vendió con ganancia o pérdida, depositó, borró un
// movimiento), se ve cambiar: cuenta del valor que tenía la última vez que se
// vio al de ahora, destella (verde si subió, rojo si bajó) y muestra la
// diferencia unos segundos. Si no hubo ningún cambio del usuario, se ve como
// cualquier número: no agrega movimiento. Toda la lógica: hooks/useNumeroQueCambia.
//
//   <NumeroQueCambia clave="dashboard:aportado" value={usd} format={fmt}
//                    moneda="USD" listo={!cargando} />
//
//   clave    identifica la métrica (única en la app): es con lo que se recuerda
//            su último valor visto, por cuenta.
//   value    el NÚMERO crudo (no el texto): hace falta para saber cuánto cambió.
//   format   cómo se escribe. `formatDelta`: cómo se escribe la diferencia (sin
//            signo; por defecto, `format`).
//   moneda   en qué moneda está `value`: no se compara un valor en pesos con el
//            que se vio en dólares.
//   listo    el valor ya es el de verdad (hay precios). Antes no se cuenta.
//   oculto   modo privacidad.
//   conDiferencia  false: cuenta y destella, sin la etiqueta de la diferencia
//            (donde no hay lugar; ahí la diferencia la muestra quien lo usa).
//   desdeCero  sin cambio que mostrar, la primera vez cuenta desde 0 (los que
//            ya lo hacían: el total, los de Movimientos).
//
// Los números van en Geist con `tabular` (R1): la clase la pone quien lo monta.

import { useNumeroQueCambia } from '../hooks/useNumeroQueCambia'

/** "+US$ 10,33" / "−US$ 10,33": la diferencia con signo, sin duplicar el del formato. */
export function textoDeDiferencia(delta, format) {
  const limpio = String(format(Math.abs(delta))).replace(/^\s*[+−-]\s*/, '')
  return `${delta >= 0 ? '+' : '−'}${limpio}`
}

export function Diferencia({ delta, format, className = '' }) {
  return (
    <span title="Respecto de antes de tu último cambio"
      className={`entra inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-medium leading-none tabular whitespace-nowrap ${
      delta >= 0 ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'} ${className}`}>
      {textoDeDiferencia(delta, format)}
    </span>
  )
}

export default function NumeroQueCambia({
  clave, value, format = (n) => n, formatDelta, moneda = 'USD', listo = true,
  oculto = false, conDiferencia = true, desdeCero = false, className = '',
}) {
  const n = useNumeroQueCambia({ clave, value, moneda, listo, desdeCero, format: formatDelta || format })
  // Sin número (null, NaN: un dato que no llegó) se escribe "—", no un 0 inventado.
  if (!Number.isFinite(value)) return <span ref={n.ref} className={className}>—</span>
  if (oculto) {
    return <span ref={n.ref} className={className}>••••••</span>
  }
  return (
    // Un <span> común (en línea), no una caja flexible: así se puede montar
    // adentro de un texto que se corta con puntos suspensivos sin cambiarle nada.
    <span ref={n.ref} className={className}>
      <span key={n.destello?.n || 0} className={n.destello ? (n.destello.dir === 'up' ? 'flash-up' : 'flash-down') : ''}>
        {format(n.mostrado)}
      </span>
      {conDiferencia && n.cambio && <Diferencia delta={n.cambio.delta} format={formatDelta || format} className="ml-1.5 align-middle" />}
    </span>
  )
}
