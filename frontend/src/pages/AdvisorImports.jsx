// Importar historiales de varios clientes por tanda (Plan Asesor).
//
// Una fila por cliente: de quién es, de qué broker viene, sus archivos. Al
// guardar, `utils/tandaImport.correrTanda` corre el importador que ya existe
// una fila por vez, cada pedido a nombre del cliente de esa fila. Esta página
// sólo arma la lista y dibuja lo que el orquestador le va contando.
//
// Tres momentos, en un solo archivo y sin fork por viewport (frontend/CLAUDE.md R6):
// armar → cargando → resultado. En mobile la fila se apila (grid → 1 columna).
//
// Sólo al nivel propio del asesor (`tier === 'advisor' && !clientCtx`). Adentro
// de un cliente, importar es /imports como para cualquier usuario.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import {
  Plus, X, FileUp, HelpCircle, ChevronDown, ChevronUp, CheckCircle2,
  AlertTriangle, XCircle, Loader2, ArrowRight, Info,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import { api, errorMessage } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { BROKER_GUIDES } from '../components/import/BrokerInstructions'
import { correrTanda, filaLista, faltante, ESTADO, resumen as resumir } from '../utils/tandaImport'

const btnPrimary = 'inline-flex items-center gap-1.5 text-xs font-medium text-white bg-data-violet hover:bg-data-violet/85 rounded px-3.5 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const btnGhost = 'inline-flex items-center gap-1.5 text-xs font-medium text-ink-1 border border-line hover:border-data-violet/50 hover:text-ink-0 rounded px-3 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const selectCls = 'w-full bg-bg-2 border border-line-2 rounded px-3 py-2 text-sm text-ink-0 disabled:opacity-60'

// Tope de filas por tanda. En F1 vive acá; en F2 lo hereda el backend con la tanda.
export const MAX_FILAS = 50

// La tanda no incluye el CSV genérico: exige mapear columnas a mano, que es
// justamente lo que una tanda no puede preguntar. Va al asistente por cliente.
const SIN_TANDA = new Set(['generic'])

let _seq = 0
const nuevaFila = () => ({ id: ++_seq, clientUid: null, esNuevo: false, nombre: '', platform: '', format: '', archivos: [], soloLectura: false, estado: ESTADO.PENDIENTE })

export default function AdvisorImports() {
  const { user } = useAuth()
  const { clientCtx, enterClient } = useAdvisorContext()
  const navigate = useNavigate()
  const isAdvisor = user?.tier === 'advisor'

  const [roster, setRoster] = useState(null)      // null = cargando
  const [grupos, setGrupos] = useState([])        // parsers agrupados por plataforma
  const [errorCarga, setErrorCarga] = useState(null)
  const [filas, setFilas] = useState(() => [nuevaFila()])
  const [momento, setMomento] = useState('armar')  // armar | cargando | resultado
  const [inicio, setInicio] = useState(null)
  const [fin, setFin] = useState(null)
  const abortRef = useRef(null)

  const cargar = useCallback(async () => {
    setErrorCarga(null)
    try {
      const [r, g] = await Promise.all([api.get('/advisor/clients'), api.get('/imports/parsers/grouped')])
      setRoster(r.clients || [])
      setGrupos((Array.isArray(g) ? g : []).filter(p => !SIN_TANDA.has(p.platform) && (p.exports || []).some(e => e.supported)))
    } catch (e) {
      setErrorCarga(errorMessage(e))
      setRoster([])
    }
  }, [])
  useEffect(() => { if (isAdvisor && !clientCtx) cargar() }, [isAdvisor, clientCtx, cargar])

  // Cortar la tanda si la página se desmonta: nunca a mitad de un confirm
  // (es atómico del lado del servidor), sí antes de la fila siguiente.
  useEffect(() => () => abortRef.current?.abort(), [])

  if (user && !isAdvisor) return <Navigate to="/" replace />
  if (clientCtx) return <Navigate to="/imports" replace />

  const patch = (id, p) => setFilas(fs => fs.map(f => (f.id === id ? { ...f, ...(typeof p === 'function' ? p(f) : p) } : f)))
  const quitar = (id) => setFilas(fs => fs.filter(f => f.id !== id))
  const agregar = () => setFilas(fs => (fs.length >= MAX_FILAS ? fs : [...fs, nuevaFila()]))

  const listas = filas.filter(filaLista)
  const nArchivos = filas.reduce((a, f) => a + f.archivos.length, 0)
  const nNuevos = filas.filter(f => f.esNuevo && (f.nombre || '').trim()).length

  async function guardar() {
    if (listas.length === 0) return
    // Las filas incompletas no viajan: se quedan en la lista, no entorpecen.
    const aCorrer = filas.filter(filaLista)
    setFilas(aCorrer.map(f => ({ ...f, estado: ESTADO.PENDIENTE, paso: null, detalle: null })))
    setMomento('cargando')
    setInicio(Date.now())
    setFin(null)
    const ac = new AbortController()
    abortRef.current = ac
    await correrTanda(aCorrer, { api, signal: ac.signal, onUpdate: patch })
    setFin(Date.now())
    setMomento('resultado')
    // El roster puede tener clientes nuevos → para la próxima tanda.
    api.get('/advisor/clients').then(r => setRoster(r.clients || [])).catch(() => {})
  }

  function nuevaTanda() {
    setFilas([nuevaFila()])
    setMomento('armar')
    setInicio(null); setFin(null)
  }

  const irACliente = (fila, ruta) => {
    const c = roster?.find(x => x.client_uid === fila.clientUid)
    enterClient({ id: fila.clientUid, label: c?.label || fila.nombre || `Cliente ${fila.clientUid}` })
    navigate(ruta)
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
      {momento === 'armar' && (
        <>
          <PageHeader
            eyebrow="Plan Asesor"
            title="Importar historiales de varios clientes"
            subtitle="Una fila por cliente: elegís de quién es, de qué broker viene y soltás sus archivos. Al guardar, Rendi carga los historiales uno detrás de otro y te avisa lo que necesite tu revisión."
          />
          {errorCarga && (
            <div className="mb-4 flex items-start gap-2 text-xs text-rendi-neg border border-rendi-neg/30 bg-rendi-neg/5 rounded-xl px-3 py-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>{errorCarga} <button type="button" className="underline" onClick={cargar}>Reintentar</button></span>
            </div>
          )}
          {roster === null ? (
            <div className="space-y-3"><Skeleton className="h-14 rounded-xl" /><Skeleton className="h-14 rounded-xl" /></div>
          ) : (
            <>
              <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
                <div className="hidden md:grid grid-cols-[1.1fr_.8fr_1.6fr_150px_36px] gap-3.5 items-center px-4 py-3 text-xs text-ink-2 bg-bg-2 border-b border-line">
                  <div>Cliente</div><div>Broker</div><div>Archivos del historial</div><div>Estado</div><div />
                </div>
                {filas.map(f => (
                  <Fila key={f.id} fila={f} roster={roster} grupos={grupos}
                    onChange={p => patch(f.id, p)} onQuitar={() => quitar(f.id)} />
                ))}
                <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-t border-line bg-bg-2">
                  <button type="button" className={btnGhost} onClick={agregar} disabled={filas.length >= MAX_FILAS}>
                    <Plus size={14} aria-hidden="true" /> Agregar cliente
                  </button>
                  <span className="text-xs text-ink-3">
                    {filas.length >= MAX_FILAS ? `Hasta ${MAX_FILAS} filas por tanda.` : 'Podés repetir un cliente si tiene más de un broker.'}
                  </span>
                </div>
              </div>

              <div className="mt-3.5 flex flex-wrap items-center justify-between gap-4 bg-bg-1 border border-line rounded-xl px-4 py-3.5">
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-1 tabular">
                  <span><b className="font-semibold text-ink-0">{filas.length}</b> {filas.length === 1 ? 'cliente' : 'clientes'}</span>
                  <span><b className="font-semibold text-ink-0">{nArchivos}</b> {nArchivos === 1 ? 'archivo' : 'archivos'}</span>
                  <span><b className="font-semibold text-ink-0">{nNuevos}</b> {nNuevos === 1 ? 'cuenta nueva se crea' : 'cuentas nuevas se crean'} al guardar</span>
                </div>
                <div className="flex items-center gap-3">
                  {listas.length > 0 && (
                    <span className="text-xs text-ink-3 tabular">Listas para cargar: {listas.length} de {filas.length}</span>
                  )}
                  <button type="button" className={btnPrimary} onClick={guardar} disabled={listas.length === 0}>
                    Guardar y cargar
                  </button>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {momento === 'cargando' && (
        <>
          <PageHeader
            eyebrow="Plan Asesor"
            title="Cargando historiales"
            subtitle="Van de a uno, en orden. Lo que ya se cargó queda cargado aunque cierres esta pestaña; lo que falta no arranca hasta que vuelvas a guardar."
          />
          <Progreso filas={filas} inicio={inicio} />
          <div className="mt-3.5 flex items-start gap-2.5 rounded-xl bg-data-violet/10 px-3.5 py-3 text-xs text-ink-0">
            <Info size={14} className="mt-0.5 shrink-0 text-data-violet" aria-hidden="true" />
            <p><span className="font-semibold">La tanda no se frena a preguntar.</span> Las filas repetidas se omiten solas y las que tengan error se informan al final. Lo que necesite una decisión tuya, como completar posiciones previas al archivo, queda marcado para revisar cliente por cliente.</p>
          </div>
        </>
      )}

      {momento === 'resultado' && (
        <Resultado filas={filas} inicio={inicio} fin={fin} onNueva={nuevaTanda} irACliente={irACliente}
          onReintentar={(fila) => { setFilas([{ ...fila, estado: ESTADO.PENDIENTE, paso: null, detalle: null, archivos: [] }]); setMomento('armar') }} />
      )}
    </div>
  )
}

// ─── Fila (momento "armar") ──────────────────────────────────────────────────

function Fila({ fila, roster, grupos, onChange, onQuitar }) {
  const [guiaAbierta, setGuiaAbierta] = useState(false)
  const inputRef = useRef(null)
  const falta = faltante(fila)

  const elegirCliente = (v) => {
    if (v === '__new') { onChange({ esNuevo: true, clientUid: null, label: '', soloLectura: false }); return }
    const uid = Number(v)
    const c = roster.find(x => x.client_uid === uid)
    onChange({ esNuevo: false, clientUid: Number.isInteger(uid) && c ? uid : null, nombre: '', label: c?.label || '', soloLectura: !!c && c.permission !== 'read_write' })
  }
  const elegirPlataforma = (platform) => {
    const g = grupos.find(x => x.platform === platform)
    const exp = g ? (g.exports || []).find(e => e.supported) : null
    onChange({ platform, format: exp?.id || '' })
    if (!g) setGuiaAbierta(false)
  }
  const agregarArchivos = (list) => {
    const nuevos = Array.from(list || [])
    if (!nuevos.length) return
    onChange(f => {
      const vistos = new Set(f.archivos.map(a => `${a.name}:${a.size}`))
      return { archivos: [...f.archivos, ...nuevos.filter(a => !vistos.has(`${a.name}:${a.size}`))] }
    })
  }
  const quitarArchivo = (i) => onChange(f => ({ archivos: f.archivos.filter((_, j) => j !== i) }))
  const guia = BROKER_GUIDES.find(g => g.id === fila.platform)
  const grupo = grupos.find(g => g.platform === fila.platform)

  return (
    <div className="border-b border-line last:border-b-0">
      <div className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1.6fr_150px_36px] gap-2.5 md:gap-3.5 items-start px-4 py-3">
        {/* Cliente */}
        <div className="flex flex-col gap-1.5">
          <label className="md:hidden text-[11px] text-ink-2">Cliente</label>
          <select className={selectCls} aria-label="Cliente"
            value={fila.esNuevo ? '__new' : (fila.clientUid ?? '')}
            onChange={e => elegirCliente(e.target.value)}>
            <option value="">Elegí un cliente…</option>
            {roster.map(c => (
              <option key={c.client_uid} value={c.client_uid}>
                {c.label}{c.permission !== 'read_write' ? ' — sólo lectura' : ''}
              </option>
            ))}
            <option value="__new">+ Cliente nuevo (se crea al guardar)</option>
          </select>
          {fila.esNuevo && (
            <input className={selectCls} placeholder="Nombre del cliente nuevo" aria-label="Nombre del cliente nuevo"
              value={fila.nombre} maxLength={80} onChange={e => onChange({ nombre: e.target.value })} />
          )}
        </div>

        {/* Broker + guía */}
        <div className="flex flex-col gap-1.5 min-w-0">
          <label className="md:hidden text-[11px] text-ink-2">Broker</label>
          <select className={selectCls} aria-label="Broker" value={fila.platform} onChange={e => elegirPlataforma(e.target.value)}>
            <option value="">Broker…</option>
            {grupos.map(g => <option key={g.platform} value={g.platform}>{g.platform_label}</option>)}
          </select>
          <button type="button"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-data-violet hover:underline disabled:text-ink-3 disabled:no-underline w-max"
            disabled={!guia} aria-expanded={guiaAbierta}
            onClick={() => setGuiaAbierta(v => !v)}>
            <HelpCircle size={12} aria-hidden="true" />
            ¿Cómo lo descargo?
            {guia && (guiaAbierta ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />)}
          </button>
        </div>

        {/* Archivos */}
        <div className="min-w-0">
          <label className="md:hidden text-[11px] text-ink-2">Archivos del historial</label>
          <div
            role="button" tabIndex={0}
            className="min-h-[38px] flex flex-wrap items-center gap-1.5 border border-dashed border-line-3 hover:border-data-violet rounded px-2 py-1.5 text-xs text-ink-3 cursor-pointer"
            onClick={() => inputRef.current?.click()}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inputRef.current?.click() } }}
            onDragOver={e => e.preventDefault()}
            onDrop={e => { e.preventDefault(); agregarArchivos(e.dataTransfer?.files) }}
            aria-label="Soltá los archivos del broker o hacé click para elegirlos">
            {fila.archivos.map((a, i) => (
              <span key={`${a.name}:${a.size}`} className="inline-flex items-center gap-1.5 bg-bg-2 border border-line rounded px-2 py-0.5 text-[11px] text-ink-1 max-w-full">
                <span className="truncate text-ink-0">{a.name}</span>
                <button type="button" className="text-ink-3 hover:text-rendi-neg" aria-label={`Quitar ${a.name}`}
                  onClick={e => { e.stopPropagation(); quitarArchivo(i) }}><X size={11} aria-hidden="true" /></button>
              </span>
            ))}
            <span className="inline-flex items-center gap-1">
              <FileUp size={12} aria-hidden="true" />
              {fila.archivos.length ? 'agregar' : 'Soltá los CSV o Excel del broker'}
            </span>
          </div>
          <input ref={inputRef} type="file" multiple hidden accept=".csv,.xlsx,.xls,.txt"
            onChange={e => { agregarArchivos(e.target.files); e.target.value = '' }} />
        </div>

        {/* Estado */}
        <div className="flex items-center gap-2 text-xs text-ink-2 md:pt-2">
          <span className={`w-2 h-2 rounded-full shrink-0 ${falta ? (fila.soloLectura ? 'bg-rendi-neg' : 'bg-line-3') : 'bg-rendi-pos'}`} aria-hidden="true" />
          {falta || (fila.esNuevo ? 'Se crea y se carga' : 'Lista')}
        </div>

        {/* Quitar */}
        <div className="flex md:justify-end md:pt-1.5">
          <button type="button" className="text-ink-3 hover:text-rendi-neg p-1 rounded" aria-label="Sacar fila" onClick={onQuitar}>
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {guiaAbierta && guia && (
        <div className="mx-4 mb-3 rounded-xl bg-bg-2 border border-line px-4 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <h4 className="text-sm font-semibold text-ink-0">Cómo descargar el historial de {grupo?.platform_label || guia.label}</h4>
            <button type="button" className="text-ink-3 hover:text-ink-0" aria-label="Cerrar la guía" onClick={() => setGuiaAbierta(false)}><X size={14} aria-hidden="true" /></button>
          </div>
          <ol className="mt-2 pl-5 list-decimal space-y-1.5 text-[13px] text-ink-1 max-w-[78ch]">
            {guia.steps.map((s, i) => (
              <li key={i}>
                {s}
                {esPasoDeFoto(s) && (
                  <span className="ml-1.5 inline-block align-middle text-[10px] font-medium text-rendi-warn bg-rendi-warn/10 rounded px-1.5 py-0.5">
                    la foto va después, desde su cuenta
                  </span>
                )}
              </li>
            ))}
          </ol>
          <p className="mt-2.5 text-[11px] text-ink-3">En la tanda se cargan los archivos de <b>movimientos</b>. La foto de tenencia se sube después desde la cuenta de cada cliente, porque exige aprobar qué se cierra y qué se crea.</p>
        </div>
      )}
    </div>
  )
}

// Los pasos de las guías que hablan de la FOTO (PDF / Estado de Cuenta /
// Portafolio / Tenencia) se etiquetan: en F1 la tanda no la acepta.
function esPasoDeFoto(texto) {
  const t = String(texto || '').toLowerCase()
  return /\bpdf\b|estado de cuenta|resumen de cuenta|tenencia valorizada|portafolio\b|posición consolidada|descargar portfolio/.test(t)
    && !/movimientos:\s/.test(t)
}

// ─── Progreso (momento "cargando") ───────────────────────────────────────────

function Progreso({ filas, inicio }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const hechas = filas.filter(f => [ESTADO.COMPLETO, ESTADO.REVISAR, ESTADO.ERROR].includes(f.estado)).length
  const actual = filas.find(f => f.estado === ESTADO.CARGANDO)
  const idx = actual ? filas.indexOf(actual) : hechas
  const seg = inicio ? Math.round((Date.now() - inicio) / 1000) : 0
  const pct = filas.length ? Math.round((hechas / filas.length) * 100) : 0
  return (
    <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-line">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-semibold text-ink-0 tabular">
            {actual ? `Cliente ${idx + 1} de ${filas.length} · ${nombreDe(actual)}` : 'Terminando…'}
          </span>
          <span className="text-xs text-ink-3 tabular">Empezó hace {Math.floor(seg / 60)}:{String(seg % 60).padStart(2, '0')}</span>
        </div>
        <div className="mt-2.5 h-1.5 bg-bg-3 rounded-full overflow-hidden" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <span className="block h-full bg-data-violet rounded-full transition-[width] duration-500" style={{ width: `${pct}%` }} />
        </div>
      </div>
      {filas.map(f => (
        <div key={f.id} className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1fr] gap-2 md:gap-3.5 items-center px-4 py-3 border-b border-line last:border-b-0">
          <div className="min-w-0"><div className="text-sm font-medium text-ink-0 truncate">{nombreDe(f)}</div><div className="text-[11px] text-ink-3">{f.platform}</div></div>
          <div><Pildora estado={f.estado} /></div>
          <div className="text-xs text-ink-1 tabular">
            {f.estado === ESTADO.CARGANDO ? `${f.paso || 'Cargando'}…`
              : f.estado === ESTADO.PENDIENTE ? 'En espera'
              : f.detalle || (f.notas?.length ? f.notas.join(' · ') : movs(f.cargados))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Resultado ───────────────────────────────────────────────────────────────

function Resultado({ filas, inicio, fin, onNueva, irACliente, onReintentar }) {
  const r = useMemo(() => resumir(filas), [filas])
  const seg = inicio && fin ? Math.max(1, Math.round((fin - inicio) / 1000)) : null
  const dur = seg == null ? '' : seg < 60 ? `${seg} segundos` : `${Math.floor(seg / 60)} ${Math.floor(seg / 60) === 1 ? 'minuto' : 'minutos'} ${seg % 60} segundos`
  const frase = [
    r.completos ? `${r.completos} ${r.completos === 1 ? 'quedó completo' : 'quedaron completos'}` : null,
    r.revisar ? `${r.revisar} ${r.revisar === 1 ? 'necesita' : 'necesitan'} tu revisión` : null,
    r.errores ? `${r.errores} no se ${r.errores === 1 ? 'pudo' : 'pudieron'} cargar` : null,
  ].filter(Boolean).join(', ')

  if (filas.length === 0) {
    return <EmptyState eyebrow="Plan Asesor" title="No había filas para cargar" action={<button type="button" className={btnPrimary} onClick={onNueva}>Nueva tanda</button>} />
  }

  return (
    <>
      <PageHeader
        eyebrow="Plan Asesor"
        title="Tanda cargada"
        subtitle={`${r.total} ${r.total === 1 ? 'cliente' : 'clientes'}${dur ? ` en ${dur}` : ''}. ${frase}.`}
      />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3.5 tabular">
        <Kpi label="Movimientos cargados" valor={r.movimientos} sub={`en ${r.completos + r.revisar} ${r.completos + r.revisar === 1 ? 'cliente' : 'clientes'}`} />
        <Kpi label="Repetidos omitidos" valor={r.repetidos} sub="ya estaban cargados de antes" />
        <Kpi label="Filas con error" valor={r.filasConError} sub="se informan, no frenan" warn={r.filasConError > 0} />
        <Kpi label="Necesitan tu revisión" valor={r.revisar} sub={`de ${r.total} ${r.total === 1 ? 'cliente' : 'clientes'}`} warn={r.revisar > 0} />
      </div>

      <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
        {filas.map(f => (
          <div key={f.id} className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1fr_150px] gap-2 md:gap-3.5 items-center px-4 py-3 border-b border-line last:border-b-0">
            <div className="min-w-0">
              <div className="text-sm font-medium text-ink-0 truncate flex items-center gap-2">
                {nombreDe(f)}
                {f.creado && <span className="text-[10px] font-medium text-ink-2 bg-bg-2 rounded-full px-2 py-0.5">cuenta nueva</span>}
              </div>
              <div className="text-[11px] text-ink-3 tabular">{f.platform} · {f.archivos.length} {f.archivos.length === 1 ? 'archivo' : 'archivos'}</div>
            </div>
            <div><Pildora estado={f.estado} /></div>
            <div className="text-xs text-ink-1 tabular">
              {f.estado === ESTADO.ERROR ? (
                <>{f.detalle}<span className="block text-[11px] text-ink-3 mt-0.5">No se tocó nada en su cuenta.</span></>
              ) : (
                <>
                  {movs(f.cargados)} cargados
                  {(f.detalle || f.notas?.length > 0 || f.creado) && (
                    <span className="block text-[11px] text-ink-3 mt-0.5">
                      {[f.detalle, ...(f.notas || []), f.creado ? 'Cuenta creada. Podés invitarlo cuando quieras desde Clientes.' : null].filter(Boolean).join(' · ')}
                    </span>
                  )}
                </>
              )}
            </div>
            <div className="flex md:justify-end">
              {f.estado === ESTADO.REVISAR && <button type="button" className={btnPrimary} onClick={() => irACliente(f, '/imports')}>Completar <ArrowRight size={12} aria-hidden="true" /></button>}
              {f.estado === ESTADO.COMPLETO && <button type="button" className={btnGhost} onClick={() => irACliente(f, '/posiciones')}>Ver cartera</button>}
              {f.estado === ESTADO.ERROR && <button type="button" className={btnGhost} onClick={() => onReintentar(f)}>Cambiar archivo</button>}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 bg-bg-1 border border-line rounded-xl px-4 py-3.5">
        <p className="text-xs text-ink-3 max-w-[60ch]">Cada cliente quedó como una importación propia: desde su cuenta, en Importar, podés revertirla sola.</p>
        <button type="button" className={btnPrimary} onClick={onNueva}>Nueva tanda</button>
      </div>
    </>
  )
}

function Kpi({ label, valor, sub, warn }) {
  return (
    <div className="bg-bg-1 border border-line rounded-xl px-4 py-3.5">
      <div className="text-xs text-ink-2">{label}</div>
      <div className={`text-2xl font-semibold tracking-tight mt-0.5 ${warn ? 'text-rendi-warn' : 'text-ink-0'}`}>{valor}</div>
      <div className="text-[11px] text-ink-3 mt-0.5">{sub}</div>
    </div>
  )
}

const PILDORA = {
  [ESTADO.PENDIENTE]: { t: 'Pendiente', cls: 'text-ink-2 bg-bg-2', Icon: null },
  [ESTADO.CARGANDO]: { t: 'Cargando', cls: 'text-data-violet bg-data-violet/10', Icon: Loader2 },
  [ESTADO.COMPLETO]: { t: 'Completo', cls: 'text-rendi-pos bg-rendi-pos/10', Icon: CheckCircle2 },
  [ESTADO.REVISAR]: { t: 'Revisar', cls: 'text-rendi-warn bg-rendi-warn/10', Icon: AlertTriangle },
  [ESTADO.ERROR]: { t: 'No se cargó', cls: 'text-rendi-neg bg-rendi-neg/10', Icon: XCircle },
}
function Pildora({ estado }) {
  const p = PILDORA[estado] || PILDORA[ESTADO.PENDIENTE]
  const Icon = p.Icon
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium rounded-full px-2.5 py-0.5 ${p.cls}`}>
      {Icon && <Icon size={12} className={estado === ESTADO.CARGANDO ? 'animate-spin' : ''} aria-hidden="true" />}
      {p.t}
    </span>
  )
}

const movs = (n) => `${n ?? 0} ${n === 1 ? 'movimiento' : 'movimientos'}`

function nombreDe(f) {
  return f.esNuevo ? (f.nombre || 'Cliente nuevo') : (f.label || (f.clientUid ? `Cliente ${f.clientUid}` : 'Sin cliente'))
}
