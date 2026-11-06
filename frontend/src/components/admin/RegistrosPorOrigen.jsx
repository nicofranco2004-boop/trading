// RegistrosPorOrigen — el panel "Registros por origen" de /admin.
// ═══════════════════════════════════════════════════════════════════════════
// De dónde vino cada persona que se registró: qué post, qué red, qué IA. El
// link de cada post lleva un código (`rendi.finance/?d=x-20261019`); si no
// trae, el navegador anota el sitio de donde venía o la marca que la red le
// agrega al link (utils/origen.js). Viaja con el registro y queda en la cuenta.
//
// Un pedido (GET /api/admin/origenes) trae las dos ventanas, 7 y 30 días
// argentinos contando hoy. Arriba, el resumen por canal (IA, X, Meta…); abajo,
// el detalle por código o sitio. En los dos: cuántos se registraron, cuántos
// confirmaron el mail y cuántos cargaron su cartera. Qué canal es cada origen,
// y cómo se llama y qué entra en cada canal, lo manda el servidor
// (backend/canal_de_origen.py): acá no se decide ni se repite.
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

const COLUMNAS = ['Registros', 'Confirmaron', 'Cargaron cartera']

const entero = n => Number(n || 0).toLocaleString('es-AR')

function DeCuantos({ n, de }) {
  return (
    <>
      <span className="text-ink-0 font-medium">{entero(n)}</span>
      {de > 0 && <span className="text-ink-3"> · {pctTxt(Math.round((n / de) * 100))}</span>}
    </>
  )
}

function Tabla({ primera, children }) {
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-ink-3 text-left">
            <th className="font-medium px-1 py-1.5">{primera}</th>
            {COLUMNAS.map(c => <th key={c} className="font-medium px-1 py-1.5 text-right">{c}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

function Cuentas({ f }) {
  return (
    <>
      <td className="px-1 py-1.5 text-right tabular text-ink-0 font-medium align-top">{entero(f.registros)}</td>
      <td className="px-1 py-1.5 text-right tabular whitespace-nowrap align-top"><DeCuantos n={f.confirmaron} de={f.registros} /></td>
      <td className="px-1 py-1.5 text-right tabular whitespace-nowrap align-top"><DeCuantos n={f.cargaron} de={f.registros} /></td>
    </>
  )
}

/** Una ventana (7 o 30 días) de GET /api/admin/origenes, tal como llega. */
export function VentanaDeOrigenes({ v }) {
  const canales = v.canales || []
  const nombreDe = Object.fromEntries(canales.map(c => [c.canal, c.nombre]))
  return (
    <>
      <p className="text-sm text-ink-1 tabular">
        <span className="text-ink-0 font-medium">{entero(v.registros)}</span> {v.registros === 1 ? 'registro' : 'registros'}
        {v.con_dato != null && v.registros > 0 && (
          <>
            {' · '}de <span className="text-ink-0 font-medium">{entero(v.con_dato)}</span> se sabe de dónde {v.con_dato === 1 ? 'vino' : 'vinieron'}
          </>
        )}
      </p>
      {v.origenes.length === 0 ? (
        <p className="text-sm text-ink-3">Nadie se registró en este período.</p>
      ) : (
        <>
          {canales.length > 0 && (
            <Tabla primera="Canal">
              {canales.map(c => (
                <tr key={c.canal} className={`border-t border-line/60 ${c.registros ? '' : 'opacity-60'}`}>
                  <td className="px-1 py-1.5">
                    <div className="text-ink-0 font-medium">{c.nombre}</div>
                    <div className="text-xs text-ink-3">{c.explica}</div>
                  </td>
                  <Cuentas f={c} />
                </tr>
              ))}
            </Tabla>
          )}
          <Tabla primera="Código o sitio">
            {v.origenes.map(f => {
              const canal = nombreDe[f.canal]
              const detalle = [f.fuente !== canal ? f.fuente : null, canal].filter(Boolean).join(' · ')
              return (
                <tr key={f.origen || '—'} className="border-t border-line/60">
                  <td className="px-1 py-1.5">
                    <div className="text-ink-0 break-all">{f.origen || <span className="text-ink-3">Sin dato</span>}</div>
                    {f.origen && detalle && <div className="text-xs text-ink-3">{detalle}</div>}
                  </td>
                  <Cuentas f={f} />
                </tr>
              )
            })}
          </Tabla>
        </>
      )}
      <div className="text-xs text-ink-3 space-y-1.5">
        <p>
          Cómo se sabe: si el link trae código, cuenta el código (<span className="text-ink-1">rendi.finance/?d=x-20261019</span>). Si no trae, Rendi mira la marca que Facebook, Instagram, X y Google le agregan al link, o el sitio de donde venía la persona; de un sitio que no conoce no guarda el nombre (figura como <span className="text-ink-1">sitio/otro</span>). Si la misma persona entra varias veces, cuenta el primer link con código y, si no hubo ninguno, lo primero que se reconoció (vence a los 30 días).
        </p>
        <p>
          Para separar los anuncios de Meta del resto, el link del anuncio tiene que llevar el código. En el Administrador de anuncios → Seguimiento → Parámetros de URL: <span className="text-ink-1 break-all">{'utm_source=meta-anuncios&utm_campaign={{campaign.name}}'}</span>
        </p>
        <p>
          «Sin dato»: escribió la dirección, usó un link guardado, o la app (a veces Instagram, Facebook o X) abrió el link sin decir de dónde venía. Las cuentas de antes de que Rendi reconociera el sitio solo, si no traían código, también quedan acá.
        </p>
      </div>
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
            De dónde vino cada uno: qué IA, qué red, qué post. Cuenta a todos los que crearon la cuenta, confirmaran el mail o no; sin admins ni cuentas internas o de prueba.
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

      {v && <VentanaDeOrigenes v={v} />}
    </div>
  )
}
