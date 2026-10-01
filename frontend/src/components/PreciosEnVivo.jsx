// PreciosEnVivo — el cartel de los precios de una pantalla:
//
//   "● Precios de hace 40 s · se actualizan solos"   (Cartera)
//   "● Precios de hace 3 min"                         (Dashboard: no los repide)
//
// El punto late sólo si el último refresco movió algún precio (`seMueven`, ver
// utils/preciosEnVivo.js). El "hace…" se reescribe solo: cada segundo mientras
// dice segundos, y después cada 15 s (dice minutos: redibujar cada segundo no
// cambiaría nada). Un "hace 40 s" congelado sería lo contrario de lo que el
// cartel promete.
import { useEffect, useState } from 'react'
import { textoPreciosEnVivo, proximoTic } from '../utils/preciosEnVivo'

export default function PreciosEnVivo({ actualizado, actualizando = false, seActualizanSolos = false, seMueven = false, className = '' }) {
  const [ahora, setAhora] = useState(() => Date.now())
  useEffect(() => {
    const id = setTimeout(() => setAhora(Date.now()), proximoTic(actualizado, ahora))
    return () => clearTimeout(id)
  }, [ahora, actualizado])

  const texto = textoPreciosEnVivo({ actualizado, actualizando, seActualizanSolos }, ahora)
  if (!texto) return null
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12px] text-ink-2 font-medium whitespace-nowrap tabular ${className}`}>
      {seMueven
        ? <span className="live-dot" aria-hidden="true" />
        : <span className="inline-block w-1.5 h-1.5 rounded-full bg-ink-3" aria-hidden="true" />}
      {texto}
    </span>
  )
}
