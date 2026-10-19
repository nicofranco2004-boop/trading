// RegistrosPorOrigen — el panel "Registros por origen" de /admin.
// ═══════════════════════════════════════════════════════════════════════════
// Qué post o campaña trajo a cada persona que se registró. El link de cada post
// lleva un código (`rendi.finance/?d=x-20261019`); el navegador lo anota al
// entrar (utils/origen.js), viaja con el registro y queda en la cuenta.
//
// Un pedido (GET /api/admin/origenes) trae las dos ventanas, 7 y 30 días
// argentinos contando hoy. Por cada código: cuántos se registraron, cuántos
// confirmaron el mail y cuántos cargaron su cartera.
//
// Se pide aparte de la carga de /admin, como UsoDeRendi: si este conteo falla,
// el resto de la página se ve igual.

import { useEffect, useState } from 'react'
import { Link2 } from 'lucide-react'
import { api } from '../../utils/api'
import { pctTxt } from '../../utils/format'

const VENTANAS = [
  { clave: '7d', label: '7 días' },
  { clave: '30d', label: '30 días' },
]

const entero = n => Number(n || 0).toLocaleString('es-AR')

function DeCuantos({ n, de }) {
  return (
    <>
      <span className="text-ink-0 font-medium">{entero(n)}</span>
      {de > 0 && <span className="text-ink-3"> · {pctTxt(Math.round((n / de) * 100))}</span>}
    </>
  )
}

export default function RegistrosPorOrigen() {
  const [ventana, setVentana] = useState('7d')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let vivo = true
    api.get('/admin/origenes')
      .then(r => { if (vivo) setData(r) })
      .catch(e => { if (vivo) setError(e?.message || 'no respondió') })
    return () => { vivo = false }
  }, [])

  const v = data?.[ventana]

  return (
    <div className="bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link2 size={16} className="text-ink-3" />
            <h2 className="font-semibold text-ink-0">Registros por origen</h2>
          </div>
          <p className="text-xs text-ink-3 mt-1">
            Qué post trajo a cada uno. Cuenta a todos los que crearon la cuenta, confirmaran el mail o no; sin admins ni cuentas internas o de prueba.
          </p>
        </div>
        <div className="flex gap-1.5" role="group" aria-label="Período">
          {VENTANAS.map(w => (
            <button key={w.clave} type="button" onClick={() => setVentana(w.clave)} aria-pressed={ventana === w.clave}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                ventana === w.clave ? 'bg-data-violet/15 border-data-violet/40 text-ink-0 font-medium' : 'bg-bg-1 border-line text-ink-2 hover:text-ink-0'}`}>
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-sm text-rendi-neg">No se pudo cargar: {error}</p>}
      {!data && !error && <p className="text-sm text-ink-3">Cargando…</p>}

      {v && (
        <>
          <p className="text-sm text-ink-1 tabular">
            <span className="text-ink-0 font-medium">{entero(v.registros)}</span> {v.registros === 1 ? 'registro' : 'registros'}
            {' · '}<span className="text-ink-0 font-medium">{entero(v.con_codigo)}</span> {v.con_codigo === 1 ? 'vino' : 'vinieron'} por un link con código
          </p>
          {v.origenes.length === 0 ? (
            <p className="text-sm text-ink-3">Nadie se registró en este período.</p>
          ) : (
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-ink-3 text-left">
                    <th className="font-medium px-1 py-1.5">Origen</th>
                    <th className="font-medium px-1 py-1.5 text-right">Registros</th>
                    <th className="font-medium px-1 py-1.5 text-right">Confirmaron</th>
                    <th className="font-medium px-1 py-1.5 text-right">Cargaron cartera</th>
                  </tr>
                </thead>
                <tbody>
                  {v.origenes.map(f => (
                    <tr key={f.origen || '—'} className="border-t border-line/60">
                      <td className="px-1 py-1.5 text-ink-0 break-all">
                        {f.origen || <span className="text-ink-3">Sin código</span>}
                      </td>
                      <td className="px-1 py-1.5 text-right tabular text-ink-0 font-medium">{entero(f.registros)}</td>
                      <td className="px-1 py-1.5 text-right tabular whitespace-nowrap"><DeCuantos n={f.confirmaron} de={f.registros} /></td>
                      <td className="px-1 py-1.5 text-right tabular whitespace-nowrap"><DeCuantos n={f.cargaron} de={f.registros} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-ink-3">
            Para que un post cuente, su link tiene que llevar el código: <span className="text-ink-1">rendi.finance/?d=x-20261019</span>. Si la misma persona entra por dos posts, cuenta el primero (vence a los 30 días).
          </p>
        </>
      )}
    </div>
  )
}
