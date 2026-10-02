// ResumenCoincidencias — "Tu cartera coincide con tu perfil en N de M", arriba
// del Tablero del perfil.
//
// Un tilde por cruce medido, en el MISMO orden que las tarjetas de abajo: verde
// si coincide con lo que declaraste en el test, ámbar si no. Cada tilde se pone
// cuando entra su tarjeta (mismo --i que la cascada del tablero) y el número
// sube con ellos. El veredicto de cada cruce sale de `veredicto` en
// utils/profileDashboard.js — la misma regla que pinta cada tarjeta.
//
// M son sólo los cruces que se pudieron medir: un cruce bloqueado (falta el
// test o la cartera) no suma ni resta.

import { Check, X } from 'lucide-react'
import AnimatedNumber from '../AnimatedNumber'

export default function ResumenCoincidencias({ modulos = [], titulos = {}, visto = true }) {
  const medidos = modulos.filter((m) => m.veredicto != null)
  if (!medidos.length) return null
  const coinciden = medidos.filter((m) => m.veredicto === 'coincide').length

  return (
    <section className="border border-line/70 dark:border-line rounded-lg bg-bg-1/40 p-4 mb-4">
      <p className="text-sm text-ink-1">
        Tu cartera coincide con tu perfil en{' '}
        <span className="text-xl font-semibold text-data-violet tabular-nums">
          <AnimatedNumber value={coinciden} visto={visto} format={(n) => Math.round(n)} />
        </span>{' '}
        de <span className="tabular-nums">{medidos.length}</span>
      </p>
      <ul className="flex flex-wrap gap-1.5 mt-3" aria-label="Cruce por cruce">
        {modulos.map((m, i) => {
          if (m.veredicto == null) return null
          const si = m.veredicto === 'coincide'
          // --i = el lugar de SU tarjeta en el tablero (cuenta también las que
          // no tienen veredicto): el tilde se pone cuando entra la tarjeta.
          return (
            <li
              key={m.id}
              style={{ '--i': i }}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[12px] font-medium ${
                visto ? 'tilde-entra' : 'por-entrar'
              } ${si
                ? 'bg-rendi-pos/10 border-rendi-pos/40 text-rendi-pos'
                : 'bg-rendi-warn/10 border-rendi-warn/40 text-rendi-warn'}`}
            >
              {si
                ? <Check size={12} strokeWidth={2.25} aria-hidden="true" />
                : <X size={12} strokeWidth={2.25} aria-hidden="true" />}
              {titulos[m.id] || m.id}
              <span className="sr-only">{si ? ': coincide' : ': no coincide'}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
