// CargaPorPasos — el cargador de Novedades (Eventos y Noticias).
//
// En vez de una rueda que gira sin decir nada: los pedidos REALES, cada uno con
// su tilde y lo que trajo cuando vuelve ("Tu cartera ✓ 12 activos"), y los
// chips de tus empresas barriendo en ola mientras se buscan sus eventos; cuando
// llega la respuesta, cada chip aterriza con cuántos encontró.
//
// Qué pasos hay, qué empresas son "tuyas" y cuándo aparece: utils/cargaPorPasos.js
// (el que lo monta lo muestra con useDemora: sólo si la carga tarda).
// Movimiento: .chip-escaneando / .chip-listo en index.css, y la tilde de cada
// paso entra con .entra. Con "reducir movimiento" nada se mueve.

import { Check, Loader2, AlertCircle } from 'lucide-react'

function IconoDePaso({ estado }) {
  if (estado === 'listo') return <Check size={14} strokeWidth={2.25} className="text-rendi-pos shrink-0" aria-hidden="true" />
  if (estado === 'error') return <AlertCircle size={14} strokeWidth={2} className="text-rendi-warn shrink-0" aria-hidden="true" />
  return <Loader2 size={14} strokeWidth={2} className="text-data-violet shrink-0 animate-spin motion-reduce:animate-none" aria-hidden="true" />
}

const ESTADO_EN_PALABRAS = { cargando: 'cargando', listo: 'listo', error: 'no respondió' }

export default function CargaPorPasos({ pasos = [], chips = [], titulo = 'Cargando' }) {
  return (
    <div role="status" aria-live="polite" aria-label={titulo}
      className="bg-bg-1 border border-line rounded-xl p-4 sm:p-5">
      <ul className="space-y-2.5">
        {pasos.map((p, i) => (
          <li key={p.id} className="flex items-center gap-2.5 text-[13px] entra" style={{ '--i': i }}>
            <IconoDePaso estado={p.estado} />
            <span className={p.estado === 'cargando' ? 'text-ink-0' : 'text-ink-2'}>
              {p.etiqueta}
              <span className="sr-only"> — {p.detalle || ESTADO_EN_PALABRAS[p.estado]}</span>
            </span>
            {p.detalle && (
              <span aria-hidden="true"
                className={`ml-auto shrink-0 tabular text-[12.5px] entra ${p.estado === 'error' ? 'text-rendi-warn' : 'text-ink-3'}`}>
                {p.detalle}
              </span>
            )}
          </li>
        ))}
      </ul>

      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3.5 pl-6" aria-hidden="true">
          {chips.map((c, i) => (
            <span
              key={`${c.simbolo}:${c.estado}`}
              style={{ '--i': i }}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11.5px] font-semibold ${
                c.estado === 'buscando'
                  ? 'chip-escaneando bg-bg-2 border-line text-ink-2'
                  : c.cuenta > 0
                    ? 'chip-listo bg-data-violet/10 border-data-violet/40 text-ink-0'
                    : 'chip-listo bg-bg-2 border-line text-ink-3'
              }`}
            >
              {c.simbolo}
              {c.estado === 'listo' && (
                <span className="tabular font-medium">{c.cuenta > 0 ? c.cuenta : '–'}</span>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
