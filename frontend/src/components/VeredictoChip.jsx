// Veredicto — "vs el S&P 500 +1,5 pp" / "vs la inflación −0,8 pp".
// ═══════════════════════════════════════════════════════════════════════════
// La pastilla del veredicto contra un benchmark, UNA para las dos pantallas que
// lo muestran: la tarjeta "Este año" del inicio (`YearReturnLine`) y el año por
// año de Reportes (`PerformanceCalendar`). Cada una tenía la suya: la del inicio
// pintaba en verde un empate ("+0,0 pp") y escribía "−0,0 pp" en rojo lo que acá
// es "−0,04 pp".
//
// El artículo viaja aparte del nombre: la pastilla dice "vs el S&P 500" y el
// globo "Por encima DEL S&P 500". Con el artículo pegado al nombre salía "de el
// S&P 500".
//
// ⚠️ EL VACÍO HABLA. Si hay número pero el veredicto no se pudo medir (el IPC es
// mensual y el tramo arranca a mitad de mes, el INDEC no publicó, falta el
// dólar), la pastilla aparece igual, sin número y con el motivo en el globo
// (`motivo`, que manda el servidor). Un "vs el S&P" solo, sin "vs la inflación"
// al lado, es lo que se leyó como un error de la app.

import { pctVarSign, ppVarFino, decimalesFinos } from '../utils/format'

const CLASE = 'inline-flex items-center gap-1.5 text-[11px] text-ink-2 bg-bg-2 border border-line-2 rounded-full px-2.5 py-1 tabular whitespace-nowrap'

export function Veredicto({ nombre, articulo, pp, detalle, motivo }) {
  if (pp == null) {
    if (!motivo) return null
    return (
      <span className={CLASE} title={motivo}>
        vs {articulo} {nombre}
        <b className="font-semibold text-ink-3">sin medir</b>
      </span>
    )
  }
  // El veredicto, el del número que se ve: 0,0 pp es un empate (neutro), no
  // "por encima" en verde.
  const signo = pctVarSign(pp, decimalesFinos(pp, 1))
  const gana = signo > 0
  const de = articulo === 'el' ? 'del' : 'de la'
  return (
    <span
      className={CLASE}
      // La aclaración (`detalle`) va en los TRES casos: sin los paréntesis el
      // `+` se pegaba sólo al "por encima/por debajo" y el empate la perdía.
      title={(signo === 0 ? `Igual que ${articulo} ${nombre}`
        : `${gana ? 'Por encima' : 'Por debajo'} ${de} ${nombre} por ${ppVarFino(Math.abs(pp), 1).replace(/^\+/, '').replace(' pp', '')} puntos porcentuales`)
             + (detalle ? `. ${detalle}` : '')}
    >
      vs {articulo} {nombre}
      <b className={`font-semibold ${signo > 0 ? 'text-rendi-pos' : signo < 0 ? 'text-rendi-neg' : 'text-ink-1'}`}>
        {/* ppVarFino: −0,04 se escribe "−0,04 pp", no "−0,0 pp" en rojo. */}
        {ppVarFino(pp, 1)}
      </b>
    </span>
  )
}

export default Veredicto
