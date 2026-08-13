// AdvisorNote — bloque "Si sos asesor" dentro de una sección compartida del manual.
//
// Por qué existe: el asesor y el usuario comparten SEIS de las siete secciones (cargar
// posiciones, vender, marcar depósitos: el asesor hace todo eso, solo que adentro de
// cada cliente). Duplicar las seis páginas sería mantener dos manuales que se van a
// desincronizar. Pero dejarlas TAL CUAL le habla a la persona equivocada — y en tres
// casos le dice cosas que en su cuenta son FALSAS (planes Free/Plus/Pro, alertas de
// precio a su nivel, la IA de la cartera propia).
//
// Solución: una página, dos lecturas. El cuerpo sigue siendo el del usuario y este
// bloque, que solo ve una cuenta de asesor, corrige y reencuadra arriba de todo.
//
// La condición es la MISMA que usan Sidebar/Dashboard/Guia para conmutar el modo
// asesor (`user?.tier === 'advisor'`), no una nueva.

import { Users } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'

export default function AdvisorNote({ children }) {
  const { user } = useAuth()
  if (user?.tier !== 'advisor') return null

  return (
    <div className="not-prose my-6 rounded-xl border border-data-violet/30 bg-data-violet/[0.06] px-4 py-4 sm:px-5">
      <div className="flex items-center gap-2 mb-2.5">
        <Users size={15} strokeWidth={1.75} className="text-data-violet flex-shrink-0" aria-hidden="true" />
        <span className="text-[12.5px] font-semibold tracking-wide uppercase text-data-violet">
          Si sos asesor
        </span>
      </div>
      <div className="advisor-note text-[14.5px] leading-relaxed text-ink-1 space-y-2.5">
        {children}
      </div>
    </div>
  )
}
