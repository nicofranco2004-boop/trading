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
// El resultado (y el progreso a medio camino) se guarda en sessionStorage:
// entrar a un cliente desde "Ver cartera" y volver con Atrás no lo destruye, y
// si la tanda se cortó (cerró la pestaña, navegó) al volver se ve qué quedó
// hecho y qué no. Sólo por pestaña; la Fase 2 lo persiste en el servidor.
//
// Sólo al nivel propio del asesor (`tier === 'advisor' && !clientCtx`). Adentro
// de un cliente, importar es /imports como para cualquier usuario.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import {
  Plus, X, FileUp, HelpCircle, ChevronDown, ChevronUp, CheckCircle2,
  AlertTriangle, XCircle, Loader2, ArrowRight, Info, History, Undo2, Camera,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import { api, errorMessage } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { BROKER_GUIDES, pasosPara } from '../components/import/BrokerInstructions'
import { ReconcileStep, decisionesPendientes, tickersAprobados } from '../components/import/ImportWizard'
import {
  correrTanda, filaLista, faltante, archivoAceptado, plural, ESTADO, EXTENSIONES, fusionarFotosLocales,
  resumen as resumir, filaAlServidor, filaDelServidor, fechaServidor, marcarInterrumpidas,
  aplicarFoto, omitirFoto,
} from '../utils/tandaImport'

const btnBase = 'inline-flex items-center gap-1.5 text-xs font-medium rounded px-3.5 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const btnPrimary = `${btnBase} text-white bg-data-violet hover:bg-data-violet/85`
const btnDanger = `${btnBase} text-white bg-rendi-neg hover:bg-rendi-neg/85`
const btnGhost = 'inline-flex items-center gap-1.5 text-xs font-medium text-ink-1 border border-line hover:border-data-violet/50 hover:text-ink-0 rounded px-3 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const selectCls = 'w-full bg-bg-2 border border-line-2 rounded px-3 py-2 text-sm text-ink-0 disabled:opacity-60'

// Tope de filas por tanda. La verdad vive en backend/advisor_tandas.MAX_FILAS;
// esta es la copia del front. Si cambia una, cambia la otra.
export const MAX_FILAS = 50

// La tanda no incluye el CSV genérico: exige mapear columnas a mano, que es
// justamente lo que una tanda no puede preguntar. Va al asistente por cliente.
const SIN_TANDA = new Set(['generic'])

const STORAGE_KEY = 'rendi_tanda_ultima'

const FINALES = new Set([ESTADO.COMPLETO, ESTADO.REVISAR, ESTADO.ERROR, ESTADO.FOTO_PENDIENTE])

let _seq = 0
const nuevaFila = () => ({ id: ++_seq, clientUid: null, esNuevo: false, nombre: '', label: '', platform: '', platformLabel: '', format: '', archivos: [], soloLectura: false, estado: ESTADO.PENDIENTE })

// Lo que se guarda por pestaña: sin los File (no se serializan), sólo nombres.
function serializar(filas, momento, inicio, fin, tandaId = null) {
  return {
    momento, inicio, fin, tandaId, ts: Date.now(),
    filas: filas.map(f => ({ ...f, archivos: (f.archivos || []).map(a => ({ name: a.name, size: a.size })) })),
  }
}
function guardarLocal(x) { try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(x)) } catch {} }
function leerLocal() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    const x = raw ? JSON.parse(raw) : null
    if (!x || !Array.isArray(x.filas)) return null
    // Las filas que quedaron "cargando"/"pendiente" en una tanda cortada no
    // corrieron o no sabemos cómo terminaron: se marcan como interrumpidas.
    const cortada = x.momento === 'cargando'
    if (cortada) x.filas = marcarInterrumpidas(x.filas)
    x.filas.forEach(f => { _seq = Math.max(_seq, Number(f.id) || 0) })
    return { ...x, cortada }
  } catch { return null }
}

export default function AdvisorImports() {
  const { user } = useAuth()
  const { clientCtx, enterClient, exitClient } = useAdvisorContext()
  const navigate = useNavigate()
  const isAdvisor = user?.tier === 'advisor'

  const [roster, setRoster] = useState(null)      // null = cargando
  const [grupos, setGrupos] = useState([])        // parsers agrupados por plataforma
  const [errorCarga, setErrorCarga] = useState(null)
  const [ultima] = useState(() => leerLocal())    // resultado guardado en la pestaña
  const [filas, setFilas] = useState(() => (ultima && ultima.momento !== 'armar' ? ultima.filas : [nuevaFila()]))
  const [momento, setMomento] = useState(() => (ultima && ultima.momento !== 'armar' ? 'resultado' : 'armar'))
  const [inicio, setInicio] = useState(() => ultima?.inicio || null)
  const [fin, setFin] = useState(() => ultima?.fin || null)
  const [cortada, setCortada] = useState(() => !!ultima?.cortada)
  const [hayGuardada, setHayGuardada] = useState(() => !!ultima)
  const [tandaId, setTandaId] = useState(() => ultima?.tandaId || null)   // id en el servidor (F2)
  const [historial, setHistorial] = useState([])   // tandas anteriores (servidor)
  const [deshacer, setDeshacer] = useState(null)   // null | 'confirmar' | 'corriendo' | {resultado}
  const abortRef = useRef(null)
  const pendientesRef = useRef([])   // filas incompletas que no viajaron: vuelven en "Nueva tanda"
  const filasRef = useRef(filas)
  filasRef.current = filas

  // Con Atrás desde "Ver cartera"/"Revisar" se vuelve con el contexto del
  // cliente puesto. Si hay un resultado guardado, se sale del cliente y se
  // muestra; si no, esta pantalla no existe adentro de un cliente.
  const volviendo = !!clientCtx && !!ultima
  useEffect(() => { if (volviendo) exitClient() }, [volviendo, exitClient])

  const cargar = useCallback(async () => {
    setErrorCarga(null)
    try {
      const [r, g] = await Promise.all([api.get('/advisor/clients'), api.get('/imports/parsers/grouped')])
      setRoster(r.clients || [])
      // Tandas anteriores: si el servidor todavía no las tiene, la pantalla sigue.
      api.get('/advisor/tandas').then(t => setHistorial(t?.tandas || [])).catch(() => setHistorial([]))
      setGrupos((Array.isArray(g) ? g : []).filter(p => !SIN_TANDA.has(p.platform) && (p.exports || []).some(e => e.supported)))
    } catch (e) {
      setErrorCarga(errorMessage(e) || 'No se pudo cargar la lista de clientes.')
      setRoster([])
    }
  }, [])
  useEffect(() => { if (isAdvisor && !clientCtx) cargar() }, [isAdvisor, clientCtx, cargar])

  // Cortar la tanda si la página se desmonta: nunca a mitad de un confirm
  // (es atómico del lado del servidor), sí antes de la fila siguiente.
  useEffect(() => () => abortRef.current?.abort(), [])

  // Cerrar la pestaña mientras corre: el navegador pregunta.
  useEffect(() => {
    if (momento !== 'cargando') return undefined
    const h = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [momento])

  if (user && !isAdvisor) return <Navigate to="/" replace />
  if (clientCtx && !volviendo) return <Navigate to="/imports" replace />

  const persistir = (fs, mom, ini = inicio, f = fin, tid = tandaId) => { guardarLocal(serializar(fs, mom, ini, f, tid)); setHayGuardada(true) }

  const patch = (id, p) => setFilas(fs => fs.map(f => (f.id === id ? { ...f, ...(typeof p === 'function' ? p(f) : p) } : f)))
  const quitar = (id) => setFilas(fs => fs.filter(f => f.id !== id))
  const agregar = () => setFilas(fs => (fs.length >= MAX_FILAS ? fs : [...fs, nuevaFila()]))

  const listas = filas.filter(filaLista)
  const incompletas = filas.length - listas.length
  const nArchivos = filas.reduce((a, f) => a + f.archivos.length, 0)
  const nNuevos = new Set(filas.filter(f => f.esNuevo && (f.nombre || '').trim()).map(f => f.nombre.trim().toLowerCase())).size

  async function guardar() {
    if (listas.length === 0) return
    // Las filas incompletas no viajan: se guardan aparte y vuelven en "Nueva tanda".
    pendientesRef.current = filas.filter(f => !filaLista(f))
    const aCorrer = filas.filter(filaLista).map(f => ({ ...f, estado: ESTADO.PENDIENTE, paso: null, detalle: null }))
    const t0 = Date.now()
    setFilas(aCorrer)
    setMomento('cargando')
    setInicio(t0); setFin(null); setCortada(false); setDeshacer(null)
    // La tanda nace en el servidor ANTES de correr: así cada lote queda colgado
    // de ella y, si la pestaña se cierra, "Tandas anteriores" muestra hasta
    // dónde llegó. Si el servidor no puede, la tanda corre igual, suelta.
    let tid = null
    try { tid = (await api.post('/advisor/tandas', { rows: aCorrer.map(filaAlServidor) }))?.id || null } catch { tid = null }
    setTandaId(tid)
    persistir(aCorrer, 'cargando', t0, null, tid)
    const ac = new AbortController()
    abortRef.current = ac
    // `latest` es la copia propia de las filas: el estado de React se actualiza
    // en diferido, y persistir desde él justo al terminar guardaba la penúltima
    // versión (la última fila quedaba "Cargando" para siempre al volver).
    let latest = aCorrer
    // Los PATCH van EN COLA: uno detrás de otro, nunca en paralelo. Si no, el
    // de la fila 1 podía quedar esperando la llave de escritura detrás del
    // confirm de la fila 2 y aplicarse DESPUÉS, dejando en el servidor una fila
    // "cargando" para siempre (y el deshacer de la tanda sin ese lote).
    let cola = Promise.resolve()
    const sincronizar = (finished) => {
      if (!tid) return Promise.resolve()
      cola = cola.then(() => api.patch(`/advisor/tandas/${tid}`, { rows: latest.map(filaAlServidor), ...(finished ? { finished: true } : {}) }).catch(() => {}))
      return cola
    }
    await correrTanda(aCorrer, {
      api, signal: ac.signal, tandaId: tid,
      onUpdate: (id, p) => {
        latest = latest.map(f => (f.id === id ? { ...f, ...p } : f))
        guardarLocal(serializar(latest, 'cargando', t0, null, tid))
        setFilas(latest)
        // Al servidor sólo cuando una fila TERMINA (no en cada sub-paso).
        if (p.estado && FINALES.has(p.estado)) sincronizar(false)
      },
    })
    if (ac.signal.aborted) { sincronizar(false); return }   // desmontada: lo guardado ya dice hasta dónde llegó
    const t1 = Date.now()
    setFin(t1)
    setMomento('resultado')
    persistir(latest, 'resultado', t0, t1, tid)
    await sincronizar(true)
    api.get('/advisor/tandas').then(t => setHistorial(t?.tandas || [])).catch(() => {})
    // El roster puede tener clientes nuevos → para la próxima tanda.
    api.get('/advisor/clients').then(r => setRoster(r.clients || [])).catch(() => {})
  }

  function nuevaTanda(extra = []) {
    const base = [...extra, ...pendientesRef.current]
    pendientesRef.current = []
    setFilas(base.length ? base : [nuevaFila()])
    setMomento('armar')
    setInicio(null); setFin(null)
  }

  // Volver a intentar UNA fila: se arma una tanda nueva con esa fila (sin
  // archivos) y el resultado anterior sigue guardado ("Ver la última tanda").
  function reintentar(fila) {
    const f = { ...fila, estado: ESTADO.PENDIENTE, paso: null, detalle: null, archivos: [] }
    if (Number.isInteger(f.clientUid)) { f.esNuevo = false; f.label = f.label || f.nombre }
    nuevaTanda([f])
  }

  function verUltima() {
    const u = leerLocal()
    if (!u) return
    // Si la tanda existe en el servidor, manda el servidor (ahí está lo que
    // pasó después: un deshacer, un revert desde la cuenta del cliente).
    if (u.tandaId) { verTanda(u.tandaId); return }
    setFilas(u.filas); setInicio(u.inicio); setFin(u.fin); setCortada(!!u.cortada); setTandaId(u.tandaId || null); setDeshacer(null); setMomento('resultado')
  }

  // Una tanda anterior, desde el servidor.
  async function verTanda(id) {
    try {
      const d = await api.get(`/advisor/tandas/${id}`)
      const local = leerLocal()
      const filasSrv = fusionarFotosLocales((d.rows || []).map(filaDelServidor), local?.tandaId === d.id ? local.filas : [])
      const seCorto = !d.finished_at && (d.resumen?.en_curso || 0) > 0
      setFilas(seCorto ? marcarInterrumpidas(filasSrv) : filasSrv)
      setInicio(fechaServidor(d.created_at))
      setFin(fechaServidor(d.finished_at))
      setCortada(seCorto)
      setTandaId(d.id); setDeshacer(null); setMomento('resultado')
      persistir(filasSrv, 'resultado', fechaServidor(d.created_at), fechaServidor(d.finished_at), d.id)
    } catch (e) {
      setErrorCarga(errorMessage(e) || 'No se pudo abrir esa tanda.')
    }
  }

  // Deshacer toda la tanda: primero confirma, después revierte lote por lote
  // en el servidor y vuelve a leer la tanda para mostrar el estado real.
  async function deshacerTanda() {
    if (!tandaId) return
    setDeshacer('corriendo')
    try {
      const res = await api.post(`/advisor/tandas/${tandaId}/revert`, {})
      const d = await api.get(`/advisor/tandas/${tandaId}`)
      const filasSrv = (d.rows || []).map(filaDelServidor)
      setFilas(filasSrv)
      persistir(filasSrv, 'resultado', inicio, fin, tandaId)
      setDeshacer({ resultado: res })
      api.get('/advisor/tandas').then(t => setHistorial(t?.tandas || [])).catch(() => {})
    } catch (e) {
      setDeshacer({ error: errorMessage(e) || 'No se pudo deshacer la tanda.' })
    }
  }

  // F3: aprobar u omitir la foto de una fila. Se confirma a nombre del
  // cliente con los tickers aprobados (opt-in), y la fila vuelve al estado de
  // sus movimientos. Se sincroniza al servidor y a la pestaña.
  async function decidirFoto(fila, aprobados, omitir = false) {
    const patchFila = omitir ? omitirFoto(fila) : await aplicarFoto(api, fila, aprobados)
    setFilas(fs => {
      const next = fs.map(f => (f.id === fila.id ? { ...f, ...patchFila } : f))
      persistir(next, 'resultado', inicio, fin, tandaId)
      if (tandaId) api.patch(`/advisor/tandas/${tandaId}`, { rows: next.map(filaAlServidor) }).catch(() => {})
      return next
    })
  }

  const irACliente = (fila, ruta) => {
    const c = roster?.find(x => x.client_uid === fila.clientUid)
    enterClient({ id: fila.clientUid, label: c?.label || fila.label || fila.nombre || `Cliente ${fila.clientUid}` })
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
            action={hayGuardada ? (
              <button type="button" className={btnGhost} onClick={verUltima}>
                <History size={14} aria-hidden="true" /> Ver la última tanda
              </button>
            ) : undefined}
          />
          {errorCarga && (
            <div className="mb-4 flex items-start gap-2 text-xs text-rendi-neg border border-rendi-neg/30 bg-rendi-neg/5 rounded-xl px-3 py-2" role="alert">
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
                  <span className="text-xs text-ink-2">
                    {filas.length >= MAX_FILAS ? `Hasta ${MAX_FILAS} filas por tanda.` : 'Podés repetir un cliente si tiene más de un broker. Si los títulos pasaron de un broker a otro, la fila va a pedirte revisarla.'}
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
                    <span className="text-xs text-ink-2 tabular">
                      {incompletas > 0
                        ? `Se cargan ${listas.length} de ${filas.length}; ${plural(incompletas, 'fila incompleta queda', 'filas incompletas quedan')} para la próxima tanda`
                        : `Listas para cargar: ${listas.length} de ${filas.length}`}
                    </span>
                  )}
                  <button type="button" className={btnPrimary} onClick={guardar} disabled={listas.length === 0}>
                    Guardar y cargar
                  </button>
                </div>
              </div>

              {historial.length > 0 && (
                <section className="mt-6" aria-label="Tandas anteriores">
                  <h2 className="text-sm font-semibold text-ink-0 mb-2">Tandas anteriores</h2>
                  <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
                    {historial.slice(0, 8).map(t => (
                      <button type="button" key={t.id} onClick={() => verTanda(t.id)}
                        className="w-full text-left grid grid-cols-1 md:grid-cols-[170px_1fr_auto] gap-1 md:gap-3.5 items-center px-4 py-3 border-b border-line last:border-b-0 hover:bg-bg-2 transition-colors">
                        <span className="text-xs text-ink-1 tabular">{fechaCorta(t.created_at)}{!t.finished_at && t.resumen?.en_curso > 0 ? <span className="ml-2 text-[10px] font-medium text-rendi-warn bg-rendi-warn/10 rounded-full px-2 py-0.5">se cortó</span> : null}</span>
                        <span className="text-xs text-ink-2 truncate">{(t.clientes || []).filter(Boolean).join(', ')}</span>
                        <span className="text-xs text-ink-1 tabular">{resumenCorto(t.resumen)}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </>
      )}

      {momento === 'cargando' && (
        <>
          <PageHeader
            eyebrow="Plan Asesor"
            title="Cargando historiales"
            subtitle="Van de a uno, en orden. Si salís de esta pantalla, la fila que está corriendo termina y las siguientes no arrancan; al volver vas a ver hasta dónde llegó."
          />
          <Progreso filas={filas} inicio={inicio} />
          <div className="mt-3.5 flex items-start gap-2.5 rounded-xl bg-data-violet/10 px-3.5 py-3 text-xs text-ink-0">
            <Info size={14} className="mt-0.5 shrink-0 text-data-violet" aria-hidden="true" />
            <p><span className="font-semibold">La tanda no se frena a preguntar.</span> Las filas repetidas se omiten solas y las que tengan error se informan al final. Lo que necesite una decisión tuya, como completar posiciones previas al archivo o aprobar un traspaso entre brokers, queda marcado para revisar cliente por cliente.</p>
          </div>
        </>
      )}

      {momento === 'resultado' && (
        <Resultado filas={filas} inicio={inicio} fin={fin} cortada={cortada}
          tandaId={tandaId} deshacer={deshacer} onDeshacer={deshacerTanda} onPedirDeshacer={() => setDeshacer('confirmar')} onCancelarDeshacer={() => setDeshacer(null)}
          onNueva={() => nuevaTanda()} irACliente={irACliente} onReintentar={reintentar} onDecidirFoto={decidirFoto} />
      )}
    </div>
  )
}

// ─── Fila (momento "armar") ──────────────────────────────────────────────────

function Fila({ fila, roster, grupos, onChange, onQuitar }) {
  const [guiaAbierta, setGuiaAbierta] = useState(false)
  const [rechazados, setRechazados] = useState([])
  const inputRef = useRef(null)
  const falta = faltante(fila)
  const grupo = grupos.find(g => g.platform === fila.platform)
  const exportsSoportados = grupo ? (grupo.exports || []).filter(e => e.supported) : []
  const guia = BROKER_GUIDES.find(g => g.id === fila.platform)

  const elegirCliente = (v) => {
    if (v === '__new') { onChange({ esNuevo: true, clientUid: null, label: '', soloLectura: false }); return }
    const uid = Number(v)
    const c = roster.find(x => x.client_uid === uid)
    onChange({ esNuevo: false, clientUid: Number.isInteger(uid) && c ? uid : null, nombre: '', label: c?.label || '', soloLectura: !!c && c.permission !== 'read_write' })
  }
  const elegirPlataforma = (platform) => {
    const g = grupos.find(x => x.platform === platform)
    const exp = g ? (g.exports || []).find(e => e.supported) : null
    onChange({ platform, platformLabel: g?.platform_label || '', format: exp?.id || '' })
    if (!g) setGuiaAbierta(false)
  }
  const agregarArchivos = (list) => {
    const todos = Array.from(list || [])
    const malos = todos.filter(a => !archivoAceptado(a.name)).map(a => a.name)
    setRechazados(malos)
    const nuevos = todos.filter(a => archivoAceptado(a.name))
    if (!nuevos.length) return
    onChange(f => {
      const vistos = new Set(f.archivos.map(a => `${a.name}:${a.size}`))
      return { archivos: [...f.archivos, ...nuevos.filter(a => !vistos.has(`${a.name}:${a.size}`))] }
    })
  }
  const quitarArchivo = (i) => onChange(f => ({ archivos: f.archivos.filter((_, j) => j !== i) }))

  return (
    <div className={`border-b border-line last:border-b-0 ${fila.soloLectura ? 'opacity-70' : ''}`}>
      <div className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1.6fr_150px_36px] gap-2.5 md:gap-3.5 items-start px-4 py-3">
        {/* Cliente */}
        <div className="flex flex-col gap-1.5">
          <div className="md:hidden flex items-center justify-between">
            <span className="text-[11px] text-ink-2">Cliente</span>
            <button type="button" className="text-ink-2 hover:text-rendi-neg p-1 rounded" aria-label="Sacar fila" onClick={onQuitar}><X size={14} aria-hidden="true" /></button>
          </div>
          <select className={selectCls} aria-label="Cliente"
            value={fila.esNuevo ? '__new' : (fila.clientUid ?? '')}
            onChange={e => elegirCliente(e.target.value)}>
            <option value="">Elegí un cliente…</option>
            {roster.map(c => (
              <option key={c.client_uid} value={c.client_uid} disabled={c.permission !== 'read_write'}>
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

        {/* Broker + export + guía */}
        <div className="flex flex-col gap-1.5 min-w-0">
          <span className="md:hidden text-[11px] text-ink-2">Broker</span>
          <select className={selectCls} aria-label="Broker" value={fila.platform} onChange={e => elegirPlataforma(e.target.value)}>
            <option value="">Broker…</option>
            {grupos.map(g => <option key={g.platform} value={g.platform}>{g.platform_label}</option>)}
          </select>
          {exportsSoportados.length > 1 && (
            <select className={`${selectCls} text-xs py-1.5`} aria-label="Tipo de archivo" value={fila.format} onChange={e => onChange({ format: e.target.value })}>
              {exportsSoportados.map(e => <option key={e.id} value={e.id}>{e.label}</option>)}
            </select>
          )}
          <button type="button"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-data-violet hover:underline disabled:text-ink-2 disabled:no-underline w-max"
            disabled={!guia} aria-expanded={guiaAbierta}
            onClick={() => setGuiaAbierta(v => !v)}>
            <HelpCircle size={12} aria-hidden="true" />
            ¿Cómo lo descargo?
            {guia && (guiaAbierta ? <ChevronUp size={12} aria-hidden="true" /> : <ChevronDown size={12} aria-hidden="true" />)}
          </button>
        </div>

        {/* Archivos */}
        <div className="min-w-0">
          <span className="md:hidden block text-[11px] text-ink-2 mb-1.5">Archivos del historial</span>
          <div
            className="min-h-[38px] flex flex-wrap items-center gap-1.5 border border-dashed border-line-3 hover:border-data-violet rounded px-2 py-1.5 text-xs text-ink-2"
            onDragOver={e => e.preventDefault()}
            onDrop={e => { e.preventDefault(); agregarArchivos(e.dataTransfer?.files) }}>
            {fila.archivos.map((a, i) => (
              <span key={`${a.name}:${a.size}`} className="inline-flex items-center gap-1.5 bg-bg-2 border border-line rounded px-2 py-0.5 text-[11px] text-ink-1 max-w-full">
                <span className="truncate text-ink-0">{a.name}</span>
                {/\.pdf$/i.test(a.name || '') && <span className="text-[10px] font-medium text-data-violet bg-data-violet/10 rounded px-1">foto</span>}
                <button type="button" className="text-ink-2 hover:text-rendi-neg rounded" aria-label={`Quitar ${a.name}`} onClick={() => quitarArchivo(i)}>
                  <X size={11} aria-hidden="true" />
                </button>
              </span>
            ))}
            <button type="button" className="inline-flex items-center gap-1 text-data-violet hover:underline rounded" onClick={() => inputRef.current?.click()}>
              <FileUp size={12} aria-hidden="true" />
              {fila.archivos.length ? 'agregar' : 'Elegir o soltar los archivos del broker (movimientos y foto)'}
            </button>
          </div>
          <p className="mt-1 text-[11px] text-ink-2">Rendi reconoce cuál archivo es la foto al cargar; los PDF se marcan de antemano.</p>
          {rechazados.length > 0 && (
            <p className="mt-1 text-[11px] text-rendi-warn">
              {plural(rechazados.length, 'archivo no entra', 'archivos no entran')} en la tanda ({rechazados.slice(0, 2).join(', ')}{rechazados.length > 2 ? '…' : ''}): acá van los CSV, Excel o PDF que exporta el broker.
            </p>
          )}
          <input ref={inputRef} type="file" multiple hidden accept={EXTENSIONES.map(e => `.${e}`).join(',')}
            onChange={e => { agregarArchivos(e.target.files); e.target.value = '' }} />
        </div>

        {/* Estado */}
        <div className="flex items-start gap-2 text-xs text-ink-2 md:pt-2">
          <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${falta ? (fila.soloLectura ? 'bg-rendi-neg' : 'bg-line-3') : 'bg-rendi-pos'}`} aria-hidden="true" />
          <span>
            {falta || (fila.esNuevo ? 'Se crea y se carga' : 'Lista')}
            {fila.soloLectura && <span className="block text-[11px]">Pedile permiso de edición desde Clientes.</span>}
          </span>
        </div>

        {/* Quitar (desktop) */}
        <div className="hidden md:flex md:justify-end md:pt-1.5">
          <button type="button" className="text-ink-2 hover:text-rendi-neg p-1 rounded" aria-label="Sacar fila" onClick={onQuitar}>
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {guiaAbierta && guia && (
        <div className="mx-4 mb-3 rounded-xl bg-bg-2 border border-line px-4 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <h4 className="text-sm font-semibold text-ink-0">Cómo descargar el historial de {grupo?.platform_label || guia.label}</h4>
            <button type="button" className="text-ink-2 hover:text-ink-0" aria-label="Cerrar la guía" onClick={() => setGuiaAbierta(false)}><X size={14} aria-hidden="true" /></button>
          </div>
          <ol className="mt-2 pl-5 list-decimal space-y-1.5 text-[13px] text-ink-1 max-w-[78ch]">
            {pasosPara(guia, 'cliente').map((s, i) => (guia.pasosSoloAsistente || []).includes(i) ? null : (
              <li key={i}>
                {s}
                {(guia.pasosFoto || []).includes(i) && (
                  <span className="ml-1.5 inline-block align-middle text-[10px] font-medium text-data-violet bg-data-violet/10 rounded px-1.5 py-0.5">
                    la foto también va en la fila
                  </span>
                )}
              </li>
            ))}
            <li>Soltá {(guia.pasosFoto || []).length > 0 ? 'todos esos archivos juntos (movimientos y foto)' : 'el archivo de movimientos'} en esta fila.</li>
          </ol>
          <p className="mt-2.5 text-[11px] text-ink-2">Rendi separa solo la foto de los movimientos. Primero entra el historial; después compara contra la foto y, si hay algo que cerrar o crear, la fila queda en <b>"Aprobar foto"</b> para que lo decidas vos. Nada de eso se aplica sin tu aprobación.</p>
        </div>
      )}
    </div>
  )
}

// ─── Progreso (momento "cargando") ───────────────────────────────────────────

function Progreso({ filas, inicio }) {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [])
  const hechas = filas.filter(f => FINALES.has(f.estado)).length
  const actual = filas.find(f => f.estado === ESTADO.CARGANDO)
  const idx = actual ? filas.indexOf(actual) : hechas
  const seg = inicio ? Math.round((Date.now() - inicio) / 1000) : 0
  const pct = filas.length ? Math.round((hechas / filas.length) * 100) : 0
  return (
    <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-line">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-semibold text-ink-0 tabular">
            {actual ? `Cliente ${idx + 1} de ${filas.length} · ${nombreDe(actual)}` : (hechas === 0 ? 'Empezando…' : 'Terminando…')}
          </span>
          <span className="text-xs text-ink-2 tabular">Empezó hace {Math.floor(seg / 60)}:{String(seg % 60).padStart(2, '0')}</span>
        </div>
        <div className="mt-2.5 h-1.5 bg-bg-3 rounded-full overflow-hidden" role="progressbar" aria-label="Avance de la tanda" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <span className="block h-full bg-data-violet rounded-full transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${pct}%` }} />
        </div>
      </div>
      {filas.map(f => (
        <div key={f.id} className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1fr] gap-2 md:gap-3.5 items-center px-4 py-3 border-b border-line last:border-b-0">
          <div className="min-w-0"><div className="text-sm font-medium text-ink-0 truncate">{nombreDe(f)}</div><div className="text-[11px] text-ink-2">{f.platformLabel || f.platform}</div></div>
          <div><Pildora estado={f.estado} /></div>
          <div className="text-xs text-ink-1 tabular">
            {f.estado === ESTADO.CARGANDO ? `${f.paso || 'Cargando'}…`
              : f.estado === ESTADO.PENDIENTE ? 'En espera'
              : f.estado === ESTADO.ERROR ? f.detalle
              : [movs(f.cargados), f.detalle, ...(f.notas || [])].filter(Boolean).join(' · ')}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Resultado ───────────────────────────────────────────────────────────────

function Resultado({ filas, inicio, fin, cortada, tandaId, deshacer, onDeshacer, onPedirDeshacer, onCancelarDeshacer, onNueva, irACliente, onReintentar, onDecidirFoto }) {
  const r = useMemo(() => resumir(filas), [filas])
  const revertibles = filas.filter(f => f.batchId && [ESTADO.COMPLETO, ESTADO.REVISAR, ESTADO.FOTO_PENDIENTE].includes(f.estado)).length
  const revertidos = filas.filter(f => f.estado === 'revertido').length
  const seg = inicio && fin ? Math.max(1, Math.round((fin - inicio) / 1000)) : null
  const dur = seg == null ? '' : seg < 60 ? plural(seg, 'segundo', 'segundos') : `${plural(Math.floor(seg / 60), 'minuto', 'minutos')} ${plural(seg % 60, 'segundo', 'segundos')}`
  const frase = [
    r.completos ? `${r.completos} ${r.completos === 1 ? 'quedó completo' : 'quedaron completos'}` : null,
    (r.revisar - r.fotos) ? `${r.revisar - r.fotos} ${(r.revisar - r.fotos) === 1 ? 'necesita' : 'necesitan'} tu revisión` : null,
    r.fotos ? `${r.fotos} ${r.fotos === 1 ? 'espera' : 'esperan'} que apruebes la foto` : null,
    r.errores ? `${r.errores} no se ${r.errores === 1 ? 'pudo' : 'pudieron'} cargar` : null,
  ].filter(Boolean).join(', ')

  if (filas.length === 0) {
    return <EmptyState eyebrow="Plan Asesor" title="No había filas para cargar" action={<button type="button" className={btnPrimary} onClick={onNueva}>Nueva tanda</button>} />
  }

  return (
    <>
      <PageHeader
        eyebrow="Plan Asesor"
        title={cortada ? 'La tanda se cortó'
          : (r.noRevertidos > 0 && revertibles === 0) ? `No se pudo deshacer: ${plural(r.noRevertidos, 'importación sigue cargada', 'importaciones siguen cargadas')}`
          : (revertibles === 0 && revertidos > 0) ? 'Tanda revertida'
          : (r.fotos > 0) ? `Falta aprobar ${plural(r.fotos, 'foto', 'fotos')}`
          : (r.completos + r.revisar === 0) ? 'La tanda no cargó nada'
          : (r.errores > 0) ? 'Tanda terminada' : 'Tanda cargada'}
        subtitle={`${plural(r.clientes, 'cliente', 'clientes')}${r.total !== r.clientes ? ` en ${plural(r.total, 'fila', 'filas')}` : ''}${dur ? ` en ${dur}` : ''}.${frase ? ` ${frase}.` : ''}${revertidos > 0 ? ` ${plural(revertidos, 'importación revertida', 'importaciones revertidas')}.` : ''}${r.noRevertidos > 0 ? ` ${plural(r.noRevertidos, 'no se pudo deshacer', 'no se pudieron deshacer')}.` : ''}`}
      />
      {!tandaId && !cortada && (
        <div className="mb-3.5 flex items-start gap-2 text-xs text-ink-0 border border-line bg-bg-1 rounded-xl px-3 py-2">
          <Info size={14} className="mt-0.5 shrink-0 text-ink-2" aria-hidden="true" />
          <span>Esta tanda no quedó guardada en el historial (Rendi no pudo anotarla al empezar). Los historiales sí se cargaron; para revertir alguno, hacelo desde la cuenta de ese cliente.</span>
        </div>
      )}
      {cortada && (
        <div className="mb-3.5 flex items-start gap-2 text-xs text-ink-0 border border-rendi-warn/30 bg-rendi-warn/10 rounded-xl px-3 py-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-rendi-warn" aria-hidden="true" />
          <span>Se salió de la pantalla mientras corría. Lo que dice "Completo" quedó cargado; las filas marcadas como cortadas no arrancaron o no sabemos cómo terminaron: revisá la cuenta del cliente antes de repetirlas.</span>
        </div>
      )}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3.5 tabular">
        <Kpi label="Movimientos y posiciones cargados" valor={r.movimientos} sub={`en ${plural(r.clientesCargados, 'cliente', 'clientes')}${r.fotos === 0 && filas.some(f => f.fotoBatchId) ? ' · incluye lo que completó la foto' : ''}`} />
        <Kpi label="Líneas repetidas omitidas" valor={r.repetidos} sub={r.archivosIdenticos > 0 ? `+ ${plural(r.archivosIdenticos, 'archivo idéntico', 'archivos idénticos')} a uno anterior` : 'ya estaban cargadas de antes'} />
        <Kpi label="Líneas con error" valor={r.filasConError} sub={r.errores > 0 ? `+ ${plural(r.errores, 'fila que no se cargó', 'filas que no se cargaron')}` : 'se informan, no frenan'} warn={r.filasConError + r.errores > 0} />
        <Kpi label="Necesitan tu revisión" valor={r.revisar} sub={r.fotos > 0 ? `${plural(r.fotos, 'foto para aprobar', 'fotos para aprobar')}${(r.revisar - r.fotos) > 0 ? ` · ${r.revisar - r.fotos} por otros motivos` : ''}` : `de ${plural(r.total, 'cliente', 'clientes')}`} warn={r.revisar > 0} />
      </div>

      <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
        {filas.map(f => (
          <div key={f.id} className="border-b border-line last:border-b-0">
          <div className="grid grid-cols-1 md:grid-cols-[1.1fr_.8fr_1fr_150px] gap-2 md:gap-3.5 items-center px-4 py-3">
            <div className="min-w-0">
              <div className="text-sm font-medium text-ink-0 truncate flex items-center gap-2">
                {nombreDe(f)}
                {f.creado && <span className="text-[10px] font-medium text-ink-2 bg-bg-2 rounded-full px-2 py-0.5">cuenta nueva</span>}
              </div>
              <div className="text-[11px] text-ink-2 tabular">{f.platformLabel || f.platform} · {plural(f.archivos.length, 'archivo', 'archivos')}</div>
            </div>
            <div><Pildora estado={f.estado} /></div>
            <div className="text-xs text-ink-1 tabular">
              {f.estado === ESTADO.FOTO_PENDIENTE ? (
                <>
                  {plural(f.cargados ?? 0, 'movimiento cargado', 'movimientos cargados')}
                  <span className="block text-[11px] text-ink-2 mt-0.5">
                    {f.foto ? `La foto ${f.foto.nombre ? `(${f.foto.nombre}) ` : ''}tiene diferencias con lo importado: mirá abajo y decidí qué aplicar.` : 'La foto quedó sin aplicar y su borrador ya no está: subila desde su cuenta.'}
                  </span>
                </>
              ) : f.estado === 'revertido' ? (
                <>Se revirtió: su cuenta quedó como antes de esta importación.</>
              ) : f.estado === 'revert_fallo' ? (
                <>{f.detalle || 'No se pudo revertir.'}<span className="block text-[11px] text-ink-2 mt-0.5">Los movimientos siguen cargados en su cuenta.</span></>
              ) : f.estado === ESTADO.ERROR ? (
                <>
                  {f.detalle}
                  <span className="block text-[11px] text-ink-2 mt-0.5">
                    {f.incierto ? 'No sabemos si llegó a guardarse: revisá su cuenta antes de repetir.' : 'No se cargó ningún movimiento.'}
                    {f.creado ? ' La cuenta del cliente sí quedó creada.' : ''}
                  </span>
                </>
              ) : (
                <>
                  {plural(f.cargados ?? 0, 'movimiento cargado', 'movimientos cargados')}
                  {(f.detalle || f.notas?.length > 0 || f.creado) && (
                    <span className="block text-[11px] text-ink-2 mt-0.5">
                      {[f.detalle, ...(f.notas || []), f.creado ? 'Cuenta creada. Desde Clientes podés mandar la invitación cuando quieras.' : null].filter(Boolean).join(' · ')}
                    </span>
                  )}
                </>
              )}
            </div>
            <div className="flex md:justify-end">
              {f.estado === ESTADO.REVISAR && <button type="button" className={btnPrimary} onClick={() => irACliente(f, '/imports')}>Revisar <ArrowRight size={12} aria-hidden="true" /></button>}
              {f.estado === ESTADO.FOTO_PENDIENTE && !f.foto && Number.isInteger(f.clientUid) && <button type="button" className={btnGhost} onClick={() => irACliente(f, '/imports')}>Subir la foto desde su cuenta</button>}
              {f.estado === ESTADO.COMPLETO && Number.isInteger(f.clientUid) && <button type="button" className={btnGhost} onClick={() => irACliente(f, '/posiciones')}>Ver cartera</button>}
              {f.estado === ESTADO.ERROR && Number.isInteger(f.clientUid) && <button type="button" className={f.incierto ? btnPrimary : btnGhost} onClick={() => irACliente(f, '/imports')}>Ver su cuenta</button>}
              {f.estado === ESTADO.ERROR && <button type="button" className={btnGhost} onClick={() => onReintentar(f)}>Cambiar archivo</button>}
              {f.estado === 'revert_fallo' && Number.isInteger(f.clientUid) && <button type="button" className={btnGhost} onClick={() => irACliente(f, '/imports')}>Ver en su cuenta</button>}
            </div>
          </div>
          {f.estado === ESTADO.FOTO_PENDIENTE && f.foto && (
            <PanelFoto fila={f} onDecidir={onDecidirFoto} />
          )}
          </div>
        ))}
      </div>

      {deshacer && typeof deshacer === 'object' && (
        <div className={`mt-3.5 flex items-start gap-2 text-xs rounded-xl px-3 py-2 border ${deshacer.error ? 'text-rendi-neg border-rendi-neg/30 bg-rendi-neg/5' : 'text-ink-0 border-line bg-bg-1'}`}>
          <Undo2 size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            {deshacer.error ? deshacer.error : (
              <>
                Se {deshacer.resultado.revertidos === 1 ? 'revirtió' : 'revirtieron'} {plural(deshacer.resultado.revertidos, 'importación', 'importaciones')}.
                {deshacer.resultado.fallidos > 0 ? ` ${plural(deshacer.resultado.fallidos, 'no se pudo deshacer', 'no se pudieron deshacer')}: el motivo está en cada fila.` : (filas.some(f => f.creado) ? ' Los historiales se revirtieron; las cuentas que la tanda creó siguen existiendo, vacías.' : ' Las cuentas quedaron como antes de la tanda.')}
              </>
            )}
          </span>
        </div>
      )}

      <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 bg-bg-1 border border-line rounded-xl px-4 py-3.5">
        <p className="text-xs text-ink-2 max-w-[60ch]">
          Cada cliente quedó como una importación propia: desde su cuenta, en Importar, podés revertirla sola o usar "Editar y rehacer" para completarla.
          {tandaId && revertibles > 0 ? ' Este botón revierte todas las de esta tanda juntas.' : ''}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {tandaId && revertibles > 0 && deshacer !== 'confirmar' && deshacer !== 'corriendo' && (
            <button type="button" className={btnGhost} onClick={onPedirDeshacer}><Undo2 size={13} aria-hidden="true" /> Deshacer toda la tanda</button>
          )}
          {deshacer === 'confirmar' && (
            <span className="inline-flex flex-wrap items-center gap-2 text-xs text-ink-0">
              ¿Revertir {plural(revertibles, 'importación', 'importaciones')} de {plural(new Set(filas.filter(f => FINALES.has(f.estado) && f.batchId).map(f => f.clientUid)).size, 'cliente', 'clientes')}? Se puede volver a cargar después.
              <button type="button" className={btnDanger} onClick={onDeshacer}>Sí, deshacer</button>
              <button type="button" className={btnGhost} onClick={onCancelarDeshacer}>Cancelar</button>
            </span>
          )}
          {deshacer === 'corriendo' && <span className="inline-flex items-center gap-1.5 text-xs text-ink-2"><Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> Deshaciendo…</span>}
          {revertidos > 0 && revertibles === 0 && typeof deshacer !== 'object' && <span className="text-xs text-ink-2">Tanda revertida.</span>}
          <button type="button" className={btnPrimary} onClick={onNueva}>Nueva tanda</button>
        </div>
      </div>
    </>
  )
}

// F3: la foto de UNA fila, con el mismo paso de aprobación del asistente
// individual (ReconcileStep) y las mismas dos salidas: aplicar con lo aprobado,
// u omitir. Lo dudoso no entra si no se marca.
function PanelFoto({ fila, onDecidir }) {
  const [decisiones, setDecisiones] = useState(() => new Map())   // ticker → 'si' | 'no'
  // Sin el detalle guardado no hay nada que decidir ítem por ítem.
  const faltan = fila.foto?.sinDetalle ? 0 : decisionesPendientes(fila.foto, decisiones)
  const aprobados = tickersAprobados(decisiones)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const nombre = nombreDe(fila)
  const quien = `${nombre}${fila.platformLabel || fila.platform ? ` · ${fila.platformLabel || fila.platform}` : ''}`
  const tituloId = `foto-${fila.id}`
  const correr = async (omitir) => {
    setBusy(true); setError(null)
    try { await onDecidir(fila, aprobados, omitir) } catch (e) { setError(errorMessage(e) || 'No se pudo aplicar la foto.') } finally { setBusy(false) }
  }
  return (
    <section className="mx-4 mb-3 rounded-xl border border-data-violet/30 bg-bg-1 px-4 py-3.5" aria-labelledby={tituloId}>
      <h3 id={tituloId} className="text-sm font-semibold text-ink-0 mb-2">Foto de {quien}{fila.foto?.nombre ? <span className="font-normal text-ink-2"> · {fila.foto.nombre}</span> : null}</h3>
      {fila.foto?.sinDetalle ? (
        <p className="text-xs text-ink-1">
          La foto quedó comparada y pendiente de decidir, pero el detalle no se guardó al cerrar la pantalla.
          Podés aplicarla sin lo dudoso (sólo entra lo que no requiere aprobación) u omitirla y subirla de nuevo desde su cuenta para verla completa.
        </p>
      ) : (
        <ReconcileStep data={fila.foto} decisiones={decisiones} sujeto="cliente"
          onDecidir={(tk, v) => setDecisiones(prev => new Map(prev).set(tk, v))} />
      )}
      {error && <p className="mt-2 text-xs text-rendi-neg" role="alert">{error}</p>}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button type="button" className={btnGhost} disabled={busy} onClick={() => correr(true)} aria-label={`Omitir la foto de ${nombre}`}>Omitir la foto</button>
        {/* Trabado hasta que cada ítem dudoso tenga su sí o su no: una casilla
            sin tildar se leía como "no lo vi", y la foto se aplicaba dejando
            los activos vendidos en la cartera. */}
        <button type="button" className={btnPrimary} disabled={busy || faltan > 0} onClick={() => correr(false)}
                aria-label={`Aplicar la foto de ${nombre}`}
                title={faltan > 0 ? 'Contestá sí o no en cada ítem para poder aplicar la foto.' : undefined}>
          {busy && <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />}
          {faltan > 0 ? `Faltan ${plural(faltan, 'decisión', 'decisiones')}`
            : aprobados.length > 0 ? `Aplicar (con ${plural(aprobados.length, 'aprobado', 'aprobados')})` : 'Aplicar la foto'}
        </button>
      </div>
    </section>
  )
}

function Kpi({ label, valor, sub, warn }) {
  return (
    <div className="bg-bg-1 border border-line rounded-xl px-4 py-3.5">
      <div className="text-xs text-ink-2">{label}</div>
      <div className={`text-2xl font-semibold tracking-tight mt-0.5 ${warn ? 'text-rendi-warn' : 'text-ink-0'}`}>{valor}</div>
      <div className="text-[11px] text-ink-2 mt-0.5">{sub}</div>
    </div>
  )
}

const PILDORA = {
  [ESTADO.PENDIENTE]: { t: 'Pendiente', cls: 'text-ink-2 bg-bg-2', Icon: null },
  [ESTADO.CARGANDO]: { t: 'Cargando', cls: 'text-data-violet bg-data-violet/10', Icon: Loader2 },
  [ESTADO.COMPLETO]: { t: 'Completo', cls: 'text-rendi-pos bg-rendi-pos/10', Icon: CheckCircle2 },
  [ESTADO.REVISAR]: { t: 'Revisar', cls: 'text-rendi-warn bg-rendi-warn/10', Icon: AlertTriangle },
  [ESTADO.ERROR]: { t: 'No se cargó', cls: 'text-rendi-neg bg-rendi-neg/10', Icon: XCircle },
  [ESTADO.FOTO_PENDIENTE]: { t: 'Aprobar foto', cls: 'text-data-violet bg-data-violet/10', Icon: Camera },
  revertido: { t: 'Revertido', cls: 'text-ink-2 bg-bg-2', Icon: Undo2 },
  revert_fallo: { t: 'No se pudo revertir', cls: 'text-rendi-neg bg-rendi-neg/10', Icon: XCircle },
}
function Pildora({ estado }) {
  const p = PILDORA[estado] || PILDORA[ESTADO.PENDIENTE]
  const Icon = p.Icon
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium rounded-full px-2.5 py-0.5 ${p.cls}`}>
      {Icon && <Icon size={12} className={estado === ESTADO.CARGANDO ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />}
      {p.t}
    </span>
  )
}

const movs = (n) => plural(n ?? 0, 'movimiento', 'movimientos')

function fechaCorta(iso) {
  const t = fechaServidor(iso)
  if (t == null) return iso ? String(iso) : ''
  const d = new Date(t)
  const conAnio = d.getFullYear() !== new Date().getFullYear()
  return d.toLocaleString('es-AR', { day: '2-digit', month: 'short', ...(conAnio ? { year: '2-digit' } : {}), hour: '2-digit', minute: '2-digit' })
}
function resumenCorto(r) {
  if (!r) return ''
  const partes = []
  if (r.completos) partes.push(`${r.completos} completos`)
  if (r.revisar) partes.push(`${r.revisar} a revisar`)
  if (r.errores) partes.push(`${r.errores} sin cargar`)
  if (r.revertidos) partes.push(`${r.revertidos} revertidos`)
  if (r.no_revertidos) partes.push(`${r.no_revertidos} no se pudieron deshacer`)
  return `${plural(r.total, 'cliente', 'clientes')}${partes.length ? ' · ' + partes.join(' · ') : ''}`
}

function nombreDe(f) {
  return f.esNuevo ? (f.nombre || 'Cliente nuevo') : (f.label || (f.clientUid ? `Cliente ${f.clientUid}` : 'Sin cliente'))
}
