// TesisPosiciones — «Tu tesis» de una posición abierta, en Movimientos ›
// Operaciones cerradas (pieza 11). Elegís cuál de las que tenés y escribís por
// qué la compraste. Lee /positions (lo que tenés hoy) y le pasa a
// TesisDelActivo la marca de acción argentina con la MISMA regla que la ficha
// (`esAccionLocal`).

import { useEffect, useMemo, useState } from 'react'
import Panel from '../Panel'
import { api } from '../../utils/api'
import { esAccionLocal } from '../../utils/accionLocal'
import { tesisVigente } from '../../utils/diarioOperaciones'
import TesisDelActivo from './TesisDelActivo'

/** Las posiciones abiertas por activo: {asset, lots, desde}. Sin efectivo. */
export function abiertasPorActivo(positions) {
  const por = new Map()
  for (const p of (positions || [])) {
    if (p.is_cash || !(Number(p.quantity) > 0) || !p.asset) continue
    const g = por.get(p.asset) || { asset: p.asset, lots: [], desde: null }
    g.lots.push(p)
    const d = p.entry_date ? String(p.entry_date).slice(0, 10) : null
    if (d && (!g.desde || d < g.desde)) g.desde = d
    por.set(p.asset, g)
  }
  return [...por.values()].sort((a, b) => a.asset.localeCompare(b.asset))
}

function desdeTexto(iso) {
  if (!iso) return null
  const [a, m] = iso.split('-').map(Number)
  // «desde noviembre de 2025»: el mes lo nombra el navegador, en castellano.
  return `desde ${new Date(Date.UTC(a, m - 1, 15)).toLocaleDateString('es-AR', { month: 'long', year: 'numeric', timeZone: 'UTC' })}`
}

export default function TesisPosiciones({ tesis, className = '' }) {
  const [positions, setPositions] = useState(null)
  useEffect(() => {
    let vivo = true
    api.get('/positions').then(r => { if (vivo) setPositions(Array.isArray(r) ? r : []) })
      .catch(() => { if (vivo) setPositions([]) })
    return () => { vivo = false }
  }, [])
  const abiertas = useMemo(() => abiertasPorActivo(positions), [positions])
  // Arranca en la primera SIN tesis (es la que falta escribir) y se QUEDA ahí:
  // si se recalculara en cada render, al guardar la tesis de YPFD el cuadro
  // saltaba solo a otra posición (medido en la copia de prueba, 23/10).
  const [elegido, setElegido] = useState(null)
  const listo = positions != null && tesis?.estado === 'listo'
  useEffect(() => {
    if (elegido != null || !listo || !abiertas.length) return
    setElegido((abiertas.find(g => !tesisVigente(tesis.items, g.asset)) || abiertas[0]).asset)
  }, [listo, abiertas, elegido, tesis?.items])
  const actual = abiertas.find(g => g.asset === elegido) || abiertas[0]

  if (tesis?.estado === 'error' || !abiertas.length) return null
  const conTesis = abiertas.filter(g => tesisVigente(tesis?.items, g.asset)).length

  return (
    <Panel padding="md" className={className} as="section" aria-label="Tu tesis de una posición abierta">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-3">
        <div>
          <div className="text-[12.5px] text-ink-2 font-medium">Posición abierta · tu tesis</div>
          <div className="text-[12px] text-ink-3">Escribiste {conTesis} de {abiertas.length}</div>
        </div>
        <label className="sr-only" htmlFor="tesis-activo">Elegí la posición</label>
        <select
          id="tesis-activo"
          value={actual?.asset || ''}
          onChange={e => setElegido(e.target.value)}
          className="bg-bg-2 border border-line rounded px-2 py-1.5 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
        >
          {abiertas.map(g => (
            <option key={g.asset} value={g.asset}>
              {g.asset}{tesisVigente(tesis?.items, g.asset) ? ' ✓' : ''}
            </option>
          ))}
        </select>
      </div>
      {actual && (
        <TesisDelActivo
          key={actual.asset}
          asset={actual.asset}
          local={esAccionLocal(actual.asset, actual.lots)}
          desde={desdeTexto(actual.desde)}
          tesis={tesis}
        />
      )}
      <p className="mt-3 text-[12px] text-ink-3">Tu tesis aparece también en la ficha del activo, en las ventas que la tenían y en el aviso del recordatorio.</p>
    </Panel>
  )
}
