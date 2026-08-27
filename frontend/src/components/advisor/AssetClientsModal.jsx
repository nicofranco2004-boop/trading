// AssetClientsModal — quién tiene ESTE activo, y cómo le fue a cada uno.
// ═══════════════════════════════════════════════════════════════════════════
// Existe por un problema de lectura concreto, reportado por el dueño mirando
// la pantalla: la fila de MU decía "+1,0%" y debajo "2 de 6 clientes en rojo",
// y las dos cosas juntas parecían contradecirse.
//
// No se contradicen. El "+1,0%" es un promedio PONDERADO POR PLATA — lo manda
// quien más tiene — y el "2 de 6" cuenta GENTE. En el libro demo, Diego tiene
// US$79.277 de MU al −8,6% y otros cinco tienen US$44.000 entre todos con
// ganancias: el grandote en rojo se come a los cinco chicos en verde y el neto
// queda apenas positivo.
//
// Intentar explicar eso en una línea de 10px no funcionó (se intentó dos
// veces). La salida es dejar de explicarlo y mostrarlo: se abre, se ven los
// seis ordenados de peor a mejor, y la aritmética se vuelve obvia sin que
// nadie tenga que leer una definición.
//
// Los datos NO vienen en /composition: per-cliente per-activo son ~32.000
// filas para un libro de 500 clientes, que es justo lo que ese endpoint evita
// mandar. Se piden a /advisor/book/asset-clients al abrir, donde el tope
// natural es la cantidad de clientes que tienen ese activo.

import { useEffect, useState } from 'react'
import Modal from '../Modal'
import Skeleton from '../Skeleton'
import { api } from '../../utils/api'
import { fciLabel } from '../../utils/valuation'

const signed = (v) => (v >= 0 ? '+' : '−')
const toneOf = (v) => (v >= 0 ? 'text-rendi-pos' : 'text-rendi-neg')

export default function AssetClientsModal({ asset, market, label, fmt, onClose }) {
  const [data, setData] = useState(null)   // null = cargando
  const [error, setError] = useState(false)

  useEffect(() => {
    let alive = true
    const q = new URLSearchParams({ asset })
    // Sin `market` el backend junta los dos mercados; se manda cuando la torta
    // lo tiene resuelto, para que el detalle describa la MISMA porción.
    if (market != null) q.set('is_ar_market', String(market))
    api.get(`/advisor/book/asset-clients?${q}`)
      .then(r => { if (alive) { setData(r.clients || []); setError(false) } })
      .catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [asset, market])

  const titulo = label || fciLabel(asset)
  const conTasa = (data || []).filter(c => c.pct != null)
  const enRojo = conTasa.filter(c => c.pct < 0)
  const total = (data || []).reduce((s, c) => s + (c.value_usd || 0), 0)

  return (
    <Modal title={`${titulo} en tu libro`} onClose={onClose}>
      {error ? (
        <p className="text-[12px] text-ink-2">
          No pudimos cargar el detalle recién. Cerrá y volvé a intentar.
        </p>
      ) : data === null ? (
        <div className="space-y-2">
          <Skeleton className="h-4 rounded" />
          <Skeleton className="h-4 rounded" />
          <Skeleton className="h-4 rounded" />
        </div>
      ) : data.length === 0 ? (
        <p className="text-[12px] text-ink-2">Ningún cliente tiene este activo.</p>
      ) : (
        <>
          <p className="text-[11.5px] text-ink-2 leading-snug mb-3">
            {data.length} {data.length === 1 ? 'cliente tiene' : 'clientes tienen'} {titulo}
            {enRojo.length > 0 && (
              <>, {enRojo.length} en rojo</>
            )}
            . El porcentaje de la torta es el promedio{' '}
            <strong className="text-ink-1">ponderado por plata</strong>: pesa más
            el cliente que más tiene, así que puede dar positivo aunque algunos
            estén perdiendo.
          </p>

          <div className="border border-line/60 rounded-md overflow-hidden">
            <div className="flex items-center gap-3 px-3 py-1.5 bg-bg-2/50 text-[10.5px] text-ink-3 uppercase tracking-wide">
              <span className="flex-1">Cliente</span>
              <span className="w-24 text-right">Tiene</span>
              <span className="w-20 text-right">Le fue</span>
            </div>
            {/* Peor primero: el que abre esto quiere saber a quién llamar. */}
            {data.map(c => (
              <div
                key={c.client_uid}
                className="flex items-center gap-3 px-3 py-2 text-[12px] border-t border-line/40"
              >
                <span className="flex-1 text-ink-1 truncate">{c.label}</span>
                <span className="w-24 text-right text-ink-2 tabular">{fmt(c.value_usd)}</span>
                <span className={`w-20 text-right tabular font-medium ${
                  c.pct == null ? 'text-ink-3' : toneOf(c.pct)
                }`}>
                  {c.pct == null
                    ? '—'
                    : `${signed(c.pct)}${Math.abs(c.pct).toFixed(1)}%`}
                </span>
              </div>
            ))}
          </div>

          <p className="text-[10.5px] text-ink-3 mt-2.5 leading-snug">
            En total, {fmt(total)} del libro está en {titulo}.
            {conTasa.length < data.length && (
              <>
                {' '}A {data.length - conTasa.length}{' '}
                {data.length - conTasa.length === 1 ? 'cliente' : 'clientes'} no
                se le puede calcular la tasa: el capital que generó su resultado
                ya no está en la posición.
              </>
            )}
          </p>
        </>
      )}
    </Modal>
  )
}
