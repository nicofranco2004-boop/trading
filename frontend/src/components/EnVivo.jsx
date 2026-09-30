// EnVivo — el estado de la rueda en el encabezado de una sección de mercado.
// Recibe `estado` tal cual lo manda el servidor (home.market.estado_de_rueda +
// `actualizado`) y dice una de cuatro cosas:
//
//   "● Abierto · actualizado hace 3m"          todos los números son de la rueda
//                                              de hoy y la rueda está en horario
//                                              (el punto late)
//   "● En rueda 1 de 3 · actualizado hace 3m"  lista mezclada: una cripto un
//                                              sábado al lado de acciones con el
//                                              porcentaje del viernes (late)
//   "● Esperando la rueda de hoy · rueda del 28/09"
//                                              en horario, pero los números
//                                              todavía son de la anterior (a
//                                              primera hora, o la barra `.BA`
//                                              que llega en NaN) — quieto
//   "● Cerrado · rueda del 26/09"              fuera de horario — quieto
//
// El punto late SÓLO al lado de números de la rueda de hoy. Un punto que late
// al lado de números de ayer es el "hoy" que mentía en las alertas del 15/09.
//
// El "hace 3m" se reescribe solo cada 30 s: sin eso quedaba congelado en lo
// que decía al cargar, justo lo contrario de lo que el indicador promete.

import { useEffect, useState } from 'react'
import { haceCuanto, diaMes } from '../utils/fecha'

export function textoDeRueda(estado, ahora = new Date()) {
  if (!estado || (estado.abierto == null && !estado.actualizado)) return null
  const hace = haceCuanto(estado.actualizado, ahora)
  const actualizado = hace ? `actualizado ${hace}` : ''
  const rueda = estado.rueda ? `rueda del ${diaMes(estado.rueda)}` : ''
  if (estado.abierto) return { late: true, titulo: 'Abierto', detalle: actualizado }
  if (estado.en_rueda > 0) {
    return { late: true, titulo: `En rueda ${estado.en_rueda} de ${estado.total}`, detalle: actualizado }
  }
  if (estado.en_horario) return { late: false, titulo: 'Esperando la rueda de hoy', detalle: rueda }
  return { late: false, titulo: 'Cerrado', detalle: rueda }
}

export default function EnVivo({ estado, className = '' }) {
  const [, setTic] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTic(t => t + 1), 30000)
    return () => clearInterval(id)
  }, [])

  const t = textoDeRueda(estado)
  if (!t) return null

  return (
    <span className={`inline-flex items-center gap-1.5 text-[12px] text-ink-2 whitespace-nowrap ${className}`}>
      {t.late
        ? <span className="live-dot" aria-hidden="true" />
        : <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-3" aria-hidden="true" />}
      <span className={t.late ? 'text-ink-1 font-medium' : ''}>{t.titulo}</span>
      {t.detalle && <span>· {t.detalle}</span>}
    </span>
  )
}
