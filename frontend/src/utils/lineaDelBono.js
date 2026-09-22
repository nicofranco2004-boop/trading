// lineaDelBono.js — la línea chica bajo el ticker, cuando el activo es un bono.
// ════════════════════════════════════════════════════════════════════════════
// En la tabla de la cartera, debajo del nombre de cada activo hay un renglón
// chico de contexto: para una acción dice la fecha de compra. Para un bono eso
// no es lo que se quiere saber de un vistazo — se quiere saber cuándo vence y
// cuándo entra la próxima plata. Esta función devuelve ese renglón.
//
// Es el reemplazo de la zona "Renta Fija": el bono pasó a ser una fila normal
// de la tabla de su broker, así que lo que la zona mostraba en una card grande
// (vencimiento y próximo cobro) tiene que caber acá, en un renglón. El resto de
// la ficha del bono (cronograma completo, TIR, capital recuperado) sigue
// estando: se abre desplegando la fila (BondDetailRow).
//
// Devuelve null si el activo no es un bono con cronograma conocido; ahí la
// tabla sigue mostrando la fecha de compra, como con cualquier otro activo.
import { getBondMeta } from './bondMeta'
import { getNextPayment } from './bondSchedule'
import { hoyISO } from './fecha'

// "2027-01-09" → "09 ene 27". El slice MM-DD era ambiguo en es-AR.
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
export function fechaCorta(iso) {
  if (!iso || iso.length < 10) return iso || ''
  return `${iso.slice(8, 10)} ${MESES[+iso.slice(5, 7) - 1] || ''} ${iso.slice(2, 4)}`
}

// `compacta`: la lista de celular. El ancla de la fila mide 118 px y recorta
// con puntos suspensivos, así que el renglón de dos datos se veía "vence 09
// jul …" — el usuario perdía justo la mitad que le importa. En compacto va UN
// dato, y es el más accionable: cuándo entra la próxima plata; si ya no queda
// ninguna, el vencimiento.
export function lineaDelBono(p, hoy = hoyISO(), { compacta = false } = {}) {
  if (!p || p.is_cash) return null
  const meta = getBondMeta(p.asset)
  if (!meta?.maturity) return null
  // Sólo la FECHA del próximo pago. El MONTO no se puede poner acá: para un
  // bono CER depende de la serie del índice, que esta función no recibe — y un
  // monto calculado sin ella saldría con ajuste 1,00, es decir mal. La fecha no
  // depende del CER, así que es lo único que se puede afirmar sin la serie.
  let prox = null
  try { prox = getNextPayment(p.asset, hoy) } catch { prox = null }
  const vence = `vence ${fechaCorta(meta.maturity)}`
  // Cuando al bono le queda UN solo pago, ese pago ES el vencimiento: repetir
  // la misma fecha dos veces en el mismo renglón no agrega nada y se lee como
  // un error. Ahí queda sólo el vencimiento.
  if (!prox?.date || prox.date === meta.maturity) return vence
  if (compacta) return `cobrás ${fechaCorta(prox.date)}`
  return `${vence} · cobrás ${fechaCorta(prox.date)}`
}
