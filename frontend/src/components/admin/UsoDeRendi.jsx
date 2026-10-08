// UsoDeRendi — el panel "Uso de Rendi" de /admin.
// ═══════════════════════════════════════════════════════════════════════════
// Todo sale de UN pedido (GET /api/admin/uso) para el período elegido:
//   · tira de números: usaron la app, iniciaron sesión, primera vez, volvieron,
//     usaron la IA, importaron;
//   · barras por día;
//   · pestañas: Usuarios (quién, cuánto entró, qué tiene cargado), Lo más
//     tocado (botones y pantallas, utils/usoCatalogo.js) y Cartera de los que
//     usan (posiciones de los activos contra los que no entraron).
//
// Dos medidas distintas, y se muestran las dos a propósito:
//   · "Iniciaron sesión" tiene historia desde mayo 2026, pero NO cuenta a quien
//     entra con la sesión todavía abierta (dura 7 días).
//   · "Usaron la app" sí lo cuenta, pero existe desde el día que se publicó la
//     medición. Antes de esa fecha el panel lo dice en vez de mostrar 0.
//
// Se pide aparte de la carga de /admin (ver el comentario de `load` en
// Admin.jsx): un agregado lento no puede dejar la página en blanco.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Users, Search } from 'lucide-react'
import { api } from '../../utils/api'
import { fechaISO, hoyISO } from '../../utils/fecha'
import { pctTxt } from '../../utils/format'
import { nombreDeUso } from '../../utils/usoCatalogo'
import DateInput from '../DateInput'

// Los rangos se arman en días calendario del navegador (que en Argentina ES la
// hora argentina, ver utils/fecha.js) y el backend corta cada día en hora
// argentina: "Hoy" a las 22:00 no se mete en mañana.
export function rangoDe(clave, hoy = new Date()) {
  const hace = n => { const d = new Date(hoy); d.setDate(d.getDate() - n); return fechaISO(d) }
  const hoyIso = fechaISO(hoy)
  switch (clave) {
    case 'hoy': return { desde: hoyIso, hasta: hoyIso }
    case '7d': return { desde: hace(6), hasta: hoyIso }
    case '30d': return { desde: hace(29), hasta: hoyIso }
    case '90d': return { desde: hace(89), hasta: hoyIso }
    case 'mes': return { desde: fechaISO(new Date(hoy.getFullYear(), hoy.getMonth(), 1)), hasta: hoyIso }
    case 'mes_pasado': return {
      desde: fechaISO(new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1)),
      hasta: fechaISO(new Date(hoy.getFullYear(), hoy.getMonth(), 0)),
    }
    default: return null
  }
}

const PERIODOS = [
  { clave: 'hoy', label: 'Hoy' },
  { clave: '7d', label: '7 días' },
  { clave: '30d', label: '30 días' },
  { clave: '90d', label: '90 días' },
  { clave: 'mes', label: 'Este mes' },
  { clave: 'mes_pasado', label: 'Mes pasado' },
  { clave: 'elegir', label: 'Elegir fechas' },
]

const PLAN = { free: 'Free', plus: 'Plus', pro: 'Pro', advisor: 'Asesor', admin: 'Admin' }

const ddmm = iso => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '')
const entero = n => Number(n || 0).toLocaleString('es-AR')

// Contra HOY, no contra el fin del período: en "Mes pasado", alguien visto el
// 30/09 no es "hoy". Más de una semana atrás se muestra la fecha.
function haceDias(iso, hoy = hoyISO()) {
  if (!iso) return '—'
  const d = Math.round((new Date(hoy + 'T12:00:00') - new Date(iso + 'T12:00:00')) / 864e5)
  if (d > 7) return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
  return d <= 0 ? 'hoy' : d === 1 ? 'ayer' : `hace ${d} d`
}

const desdeHasta = (a, b) => (a === b ? ddmm(a).slice(0, 5) : `${ddmm(a).slice(0, 5)} al ${ddmm(b).slice(0, 5)}`)

function planDe(u) {
  if (u.estado === 'en_pausa') return 'En pausa'
  const base = PLAN[u.plan] || u.plan
  return u.days_remaining != null && u.plan !== 'admin' ? `${base} · ${u.days_remaining} d` : base
}

export default function UsoDeRendi({ onElegirUsuario }) {
  const [periodo, setPeriodo] = useState('7d')
  const [propio, setPropio] = useState(() => rangoDe('30d'))
  const [internos, setInternos] = useState(false)
  const [tab, setTab] = useState('usuarios')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(false)
  const seq = useRef(0)

  const rango = periodo === 'elegir' ? propio : rangoDe(periodo)
  const rangoOk = rango?.desde && rango?.hasta && rango.desde <= rango.hasta

  useEffect(() => {
    if (!rangoOk) return
    const n = ++seq.current
    setCargando(true)
    setError('')
    api.get(`/admin/uso?desde=${rango.desde}&hasta=${rango.hasta}&internos=${internos}`)
      .then(r => { if (n === seq.current) setData(r) })
      .catch(e => { if (n === seq.current) { setData(null); setError(e?.message || 'no respondió') } })
      .finally(() => { if (n === seq.current) setCargando(false) })
  }, [rango?.desde, rango?.hasta, rangoOk, internos])

  // Mientras llega la respuesta nueva, lo viejo queda atenuado en vez de
  // hacerse pasar por el período nuevo.
  const vigente = data && rangoOk && data.desde === rango.desde && data.hasta <= rango.hasta && data.internos === internos

  return (
    <div className="bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <Users size={16} className="text-ink-3" />
            <h2 className="font-semibold text-ink-0 whitespace-nowrap">Uso de Rendi</h2>
            {data && <span className="text-xs text-ink-3 tabular">del {ddmm(data.desde)} al {ddmm(data.hasta)}</span>}
          </div>
          <p className="text-xs text-ink-3 mt-1">
            {internos ? 'Todas las cuentas con el mail confirmado, admins y cuentas internas incluidos.' : 'Sin admins ni cuentas internas o de prueba.'}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink-2 cursor-pointer select-none">
          <input type="checkbox" id="uso-internos" checked={internos} onChange={e => setInternos(e.target.checked)} className="accent-data-violet" />
          Incluir admins y cuentas internas
        </label>
      </div>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Período">
        {PERIODOS.map(p => (
          <button key={p.clave} type="button" onClick={() => setPeriodo(p.clave)} aria-pressed={periodo === p.clave}
            className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
              periodo === p.clave ? 'bg-data-violet/15 border-data-violet/40 text-ink-0 font-medium' : 'bg-bg-1 border-line text-ink-2 hover:text-ink-0'}`}>
            {p.label}
          </button>
        ))}
      </div>

      {periodo === 'elegir' && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-ink-3">
            <span className="block mb-1">Desde</span>
            <DateInput value={propio.desde} max={propio.hasta || hoyISO()} onChange={v => setPropio(r => ({ ...r, desde: v }))} />
          </label>
          <label className="text-xs text-ink-3">
            <span className="block mb-1">Hasta</span>
            <DateInput value={propio.hasta} min={propio.desde} max={hoyISO()} onChange={v => setPropio(r => ({ ...r, hasta: v }))} />
          </label>
          {!rangoOk && <p className="text-xs text-rendi-neg pb-2">«Desde» tiene que ser anterior o igual a «Hasta».</p>}
        </div>
      )}

      {error ? (
        <p className="text-sm text-rendi-neg">No se pudo cargar: {error}</p>
      ) : !data ? (
        <p className="text-sm text-ink-3">{cargando ? 'Cargando…' : '—'}</p>
      ) : (
        <div className={`space-y-4 ${vigente && !cargando ? '' : 'opacity-50'}`}>
          <Avisos data={data} />
          <Resumen r={data.resumen} usoDesde={data.uso_desde} anterior={data.anterior} />
          <PorDia dias={data.por_dia} />
          <div className="flex gap-1 border-b border-line overflow-x-auto" role="tablist" aria-label="Detalle">
            {[['usuarios', `Usuarios (${entero(data.usuarios.length)})`], ['tocado', 'Lo más tocado'], ['cartera', 'Cartera de los que usan']].map(([k, l]) => (
              <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px ${tab === k ? 'border-data-violet text-ink-0 font-medium' : 'border-transparent text-ink-2 hover:text-ink-0'}`}>
                {l}
              </button>
            ))}
          </div>
          {tab === 'usuarios' && <ListaUsuarios usuarios={data.usuarios} onElegir={onElegirUsuario} />}
          {tab === 'tocado' && <LoMasTocado ranking={data.ranking} usoDesde={data.uso_desde} />}
          {tab === 'cartera' && <Cartera c={data.cartera} />}
        </div>
      )}
    </div>
  )
}

function Avisos({ data }) {
  const out = []
  if (data.datos_desde && data.desde < data.datos_desde) {
    out.push(`Hay registro de inicios de sesión desde el ${ddmm(data.datos_desde)}: lo anterior no se puede contar.`)
  }
  if (!data.uso_desde || data.uso_desde > data.desde) {
    out.push(data.uso_desde
      ? `La medición de uso (qué se toca y quién abre la app) empezó el ${ddmm(data.uso_desde)}: antes de esa fecha no hay datos de uso.`
      : 'La medición de uso (qué se toca y quién abre la app) todavía no registró nada: empieza a contar desde que se publicó.')
  }
  if (!out.length) return null
  return (
    <div className="space-y-1">
      {out.map(t => <p key={t} className="text-xs text-amber-600 dark:text-amber-400 bg-amber-500/10 rounded-lg px-3 py-2">{t}</p>)}
    </div>
  )
}

function Kpi({ label, value, sub, extra }) {
  return (
    <div className="px-4 py-3 min-w-0 border-line border-t sm:border-t-0 sm:border-l first:border-0">
      <p className="text-xs text-ink-2">{label}</p>
      <p className="text-2xl font-semibold text-ink-0 tabular">{value}</p>
      {sub && <p className="text-xs text-ink-3">{sub}</p>}
      {extra}
    </div>
  )
}

function Resumen({ r, usoDesde, anterior }) {
  const delta = r.usuarios_antes == null ? null : r.usuarios - r.usuarios_antes
  const sinMedir = usoDesde ? `se mide desde ${ddmm(usoDesde)}` : 'se mide desde que se publicó'
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 bg-bg-1 border border-line rounded-xl overflow-hidden">
      <Kpi label="Activos" value={entero(r.activos)}
        sub={r.base > 0 ? `${pctTxt((r.activos / r.base) * 100, 0)} de ${entero(r.base)} · usaron la app o iniciaron sesión` : 'usaron la app o iniciaron sesión'} />
      <Kpi label="Usaron la app" value={r.usaron_app == null ? '—' : entero(r.usaron_app)}
        sub={r.usaron_app == null ? sinMedir : 'abrieron Rendi y la tocaron, con o sin login'} />
      <Kpi label="Iniciaron sesión" value={entero(r.usuarios)}
        sub={`${entero(r.ingresos)} inicios en total`}
        extra={delta == null ? null : <p className={`text-xs tabular ${delta > 0 ? 'text-rendi-pos' : delta < 0 ? 'text-rendi-neg' : 'text-ink-3'}`}>
          {delta > 0 ? '+' : ''}{entero(delta)} vs. {desdeHasta(anterior.desde, anterior.hasta)}</p>} />
      <Kpi label="Primera vez" value={entero(r.primera_vez)} sub="activos que crearon la cuenta en el período" />
      <Kpi label="Volvieron" value={entero(r.volvieron)} sub="activos que ya tenían cuenta" />
      <Kpi label="Usaron la IA" value={r.usaron_ia == null ? '—' : entero(r.usaron_ia)}
        sub={r.usaron_ia == null ? sinMedir : 'le escribieron a Mervall-E o pidieron un análisis'} />
      <Kpi label="Importaron" value={entero(r.importaron)} sub="confirmaron al menos un archivo" />
    </div>
  )
}

function PorDia({ dias }) {
  if (!dias?.length) return null
  const W = 900, H = 140, L = 34, R = 6, T = 8, B = 20
  const max = Math.max(1, ...dias.map(d => d.activos))
  const top = Math.max(5, Math.ceil(max / 5) * 5)
  const iw = W - L - R, ih = H - T - B, bw = iw / dias.length
  const cada = dias.length <= 10 ? 1 : dias.length <= 35 ? 7 : dias.length <= 100 ? 15 : 30
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-2">
        <span>Usuarios distintos por día</span>
        <span className="flex gap-3">
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-data-violet/60 mr-1.5 align-[-1px]" />Activos</span>
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-ink-3/50 mr-1.5 align-[-1px]" />De esos, cuentas nuevas</span>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Usuarios activos por día">
        {[0, top / 2, top].map(t => {
          const y = T + ih - (t / top) * ih
          return (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y} y2={y} className="stroke-line" strokeWidth="1" />
              <text x={L - 6} y={y + 3} textAnchor="end" className="fill-ink-3 tabular" fontSize="10">{entero(t)}</text>
            </g>
          )
        })}
        {dias.map((d, i) => {
          const x = L + i * bw + bw * 0.15, w = Math.max(1, bw * 0.7)
          const h = (d.activos / top) * ih, hn = (d.primera_vez / top) * ih
          return (
            <g key={d.dia}>
              <rect x={x} y={T + ih - h} width={w} height={h} rx="2" className="fill-data-violet/60">
                <title>{`${ddmm(d.dia)}: ${d.activos} activos · ${d.ingresaron} iniciaron sesión · ${d.usaron_app} usaron la app · ${d.primera_vez} cuentas nuevas`}</title>
              </rect>
              <rect x={x} y={T + ih - hn} width={w} height={hn} rx="2" className="fill-ink-3/50" pointerEvents="none" />
              {(i % cada === 0 || i === dias.length - 1) && (
                <text x={x + w / 2} y={H - 5} textAnchor="middle" className="fill-ink-3 tabular" fontSize="10">{ddmm(d.dia).slice(0, 5)}</text>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

const COLUMNAS = [
  ['ingresos', 'Inicios de sesión'],
  ['dias_con_uso', 'Días con uso'],
  ['ultimo', 'Último'],
  ['posiciones', 'Posiciones'],
  ['operaciones', 'Operaciones'],
  ['ia', 'IA'],
  ['toques', 'Toques'],
]

function ListaUsuarios({ usuarios, onElegir }) {
  const [q, setQ] = useState('')
  const [orden, setOrden] = useState('ultimo')
  const filas = useMemo(() => {
    const f = q.trim().toLowerCase()
    const lista = usuarios.filter(u => !f || u.email.toLowerCase().includes(f) || (u.name || '').toLowerCase().includes(f))
    const val = u => orden === 'ultimo' ? (u.ultimo || '') : (u[orden] ?? -1)
    return [...lista].sort((a, b) => (val(a) < val(b) ? 1 : val(a) > val(b) ? -1 : a.email.localeCompare(b.email)))
  }, [usuarios, q, orden])
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-full sm:w-72">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
          <input id="uso-buscar" type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Buscar por mail o nombre"
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg bg-bg-1 border border-line text-ink-0 placeholder:text-ink-3" />
        </div>
        <span className="text-xs text-ink-3">Click en una fila → la busca en la tabla de usuarios de abajo</span>
      </div>
      <div className="overflow-x-auto border border-line rounded-xl bg-bg-1">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-ink-2 bg-bg-2/60">
              <th className="text-left font-medium px-3 py-2">Usuario</th>
              <th className="text-left font-medium px-3 py-2">Plan</th>
              {COLUMNAS.map(([k, l]) => (
                <th key={k} className="text-right font-medium px-3 py-2 whitespace-nowrap">
                  <button type="button" onClick={() => setOrden(k)} className={`hover:text-ink-0 ${orden === k ? 'text-ink-0' : ''}`}
                    aria-label={`Ordenar por ${l}`}>{l}{orden === k ? ' ↓' : ''}</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filas.length === 0 && (
              <tr><td colSpan={COLUMNAS.length + 2} className="px-3 py-6 text-center text-ink-3">Nadie en este período.</td></tr>
            )}
            {filas.map(u => (
              <tr key={u.id} onClick={() => onElegir?.(u.email)} className="border-t border-line hover:bg-bg-2/60 cursor-pointer">
                <td className="px-3 py-2">
                  <span className="text-ink-0 font-medium">{u.email}</span>
                  {u.primera_vez && <span className="ml-2 text-[11px] px-1.5 py-0.5 rounded-full bg-data-violet/15 text-data-violet">cuenta nueva</span>}
                  {u.name && <span className="block text-xs text-ink-3">{u.name}</span>}
                </td>
                <td className="px-3 py-2 text-ink-2 whitespace-nowrap">{planDe(u)}</td>
                <td className="px-3 py-2 text-right tabular">{entero(u.ingresos)}</td>
                <td className="px-3 py-2 text-right tabular">{entero(u.dias_con_uso)}</td>
                <td className="px-3 py-2 text-right tabular whitespace-nowrap">{haceDias(u.ultimo)}</td>
                <td className="px-3 py-2 text-right tabular">{entero(u.posiciones)}</td>
                <td className="px-3 py-2 text-right tabular">{entero(u.operaciones)}</td>
                <td className="px-3 py-2 text-right tabular">{u.ia == null ? '—' : entero(u.ia)}</td>
                <td className="px-3 py-2 text-right tabular">{u.toques == null ? '—' : entero(u.toques)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-ink-3">
        “Último” es el último día del período en que inició sesión o usó la app. “IA” son los pedidos a la IA (mensajes a Mervall-E,
        «Analizar», repreguntas). “Toques” son los botones medidos, sin pantallas ni lo que se muestra solo. “—” = sin datos de uso en el período.
        Posiciones = activos con tenencia por broker, sin efectivo; operaciones incluye cupones y amortizaciones.
      </p>
    </div>
  )
}

const GRUPOS = [['botones', 'Botones'], ['pantallas', 'Pantallas'], ['avisos', 'Avisos y resultados']]

function LoMasTocado({ ranking, usoDesde }) {
  const [modo, setModo] = useState('botones')
  const filas = ranking[modo] || []
  const max = Math.max(1, ...filas.map(f => f.personas))
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1.5" role="group" aria-label="Qué mostrar">
          {GRUPOS.map(([k, l]) => (
            <button key={k} type="button" onClick={() => setModo(k)} aria-pressed={modo === k}
              className={`px-3 py-1.5 rounded-lg text-xs border ${modo === k ? 'bg-data-violet/15 border-data-violet/40 text-ink-0 font-medium' : 'bg-bg-1 border-line text-ink-2 hover:text-ink-0'}`}>
              {l}
            </button>
          ))}
        </div>
        <span className="text-xs text-ink-3">Ordenado por personas distintas</span>
      </div>
      {filas.length === 0 ? (
        <p className="text-sm text-ink-3 py-4">
          {usoDesde ? 'Nadie tocó nada medido en este período.' : 'Todavía no hay datos: la medición arranca desde que se publicó y se llena sola con el uso.'}
        </p>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-[minmax(0,1fr)_64px_72px_64px] sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)_64px_72px_64px] gap-3 text-[11px] text-ink-3">
            <span>{modo === 'botones' ? 'Botón' : modo === 'pantallas' ? 'Pantalla' : 'Qué apareció'}</span>
            <span className="hidden sm:block" />
            <span className="text-right">Personas</span>
            <span className="text-right">{modo === 'botones' ? 'Toques' : 'Veces'}</span>
            <span className="text-right">vs. antes</span>
          </div>
          {filas.map(f => {
            const n = nombreDeUso(f.evento)
            const d = f.personas_antes == null ? null : f.personas - f.personas_antes
            return (
              <div key={f.evento} className="grid grid-cols-[minmax(0,1fr)_64px_72px_64px] sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)_64px_72px_64px] gap-3 items-center text-sm">
                <span className="min-w-0">
                  <span className="block text-ink-0 truncate" title={f.evento}>{n.label}</span>
                  <span className="block text-[11px] text-ink-3 truncate">{n.donde}</span>
                </span>
                <span className="hidden sm:block h-2.5 bg-bg-1 rounded overflow-hidden">
                  <span className="block h-full bg-data-violet/60 rounded" style={{ width: `${(f.personas / max) * 100}%` }} />
                </span>
                <span className="text-right tabular text-ink-0">{entero(f.personas)}</span>
                <span className="text-right tabular text-ink-2">{entero(f.cantidad)}</span>
                <span className={`text-right tabular text-xs ${d == null || f.personas_antes === 0 ? 'text-ink-3' : d > 0 ? 'text-rendi-pos' : d < 0 ? 'text-rendi-neg' : 'text-ink-3'}`}
                  title={d == null ? 'El período anterior no estaba medido' : undefined}>
                  {d == null ? '—' : f.personas_antes === 0 ? 'nuevo' : `${d > 0 ? '+' : ''}${entero(d)}`}
                </span>
              </div>
            )
          })}
        </div>
      )}
      {modo === 'avisos' && <p className="text-xs text-ink-3">Lo que se mostró o terminó solo, sin que nadie lo tocara: una pantalla que abrió, un análisis que llegó, un error, el muro de planes.</p>}
      <p className="text-xs text-ink-3">“vs. antes” compara personas con el período anterior del mismo largo, justo antes del elegido (“—” si ese período todavía no se medía). Se muestra en personas y no en porcentaje: con pocos usuarios, un “+200 %” puede ser pasar de 1 a 3.</p>
    </div>
  )
}

function Cartera({ c }) {
  const max = Math.max(1, ...c.tramos.flatMap(t => [t.activos, t.inactivos]))
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="space-y-3 min-w-0">
        <h3 className="text-sm font-semibold text-ink-0">Cuántas posiciones tiene cada usuario</h3>
        <div className="flex gap-3 text-xs text-ink-2">
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-data-violet/60 mr-1.5 align-[-1px]" />Usaron Rendi en el período</span>
          <span><i className="inline-block w-2.5 h-2.5 rounded-sm bg-ink-3/50 mr-1.5 align-[-1px]" />No entraron</span>
        </div>
        {c.tramos.map(t => (
          <div key={t.rango} className="grid grid-cols-[88px_minmax(0,1fr)_84px] gap-3 items-center text-sm">
            <span className="text-ink-1">{t.rango}</span>
            <span className="space-y-1">
              <span className="block h-2.5 bg-bg-1 rounded overflow-hidden"><span className="block h-full bg-data-violet/60 rounded" style={{ width: `${(t.activos / max) * 100}%` }} /></span>
              <span className="block h-2.5 bg-bg-1 rounded overflow-hidden"><span className="block h-full bg-ink-3/50 rounded" style={{ width: `${(t.inactivos / max) * 100}%` }} /></span>
            </span>
            <span className="text-right tabular text-xs text-ink-2">{entero(t.activos)} · {entero(t.inactivos)}</span>
          </div>
        ))}
      </div>
      <div className="space-y-3 min-w-0">
        <h3 className="text-sm font-semibold text-ink-0">El usuario típico de cada grupo</h3>
        <div className="grid grid-cols-2 gap-3">
          {[['Usaron Rendi', c.activos], ['No entraron', c.inactivos]].map(([l, g]) => (
            <div key={l} className="bg-bg-1 border border-line rounded-xl p-3">
              <p className="text-xs text-ink-2">{l} ({entero(g.cuantos)})</p>
              <p className="text-xl font-semibold text-ink-0 tabular">{entero(g.posiciones)}</p>
              <p className="text-xs text-ink-3 tabular">posiciones · {entero(g.operaciones)} operaciones</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-ink-3">
          “Típico” es la mediana: la mitad tiene más, la mitad menos. Se usa en vez del promedio porque una cuenta con miles de
          operaciones importadas arrastraría el promedio de todos. Posiciones y operaciones son lo que cada uno tiene cargado hoy.
        </p>
      </div>
    </div>
  )
}
