// AdvisorClients — home del Plan Asesor (/clientes).
// ═══════════════════════════════════════════════════════════════════════════
// F1: roster de clientes (cards con AUM del último snapshot) + agregar cliente
//     managed + drill-down a "el Rendi del cliente" (setea el contexto y navega
//     al Dashboard — TODAS las páginas existentes sirven la cuenta del cliente
//     vía el header X-Rendi-Client-Id, con visión Pro).
// F2: notas privadas por cliente + OPERACIÓN GRUPAL (block trade): una compra
//     asignada a N clientes con broker/cantidad/precio por fila + deshacer lote.
//
// Gate: tier 'advisor' (o admin para testeo). El resto de los tiers ni ve la
// ruta (el sidebar no la muestra y la página redirige a /).

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import {
  Users, Plus, Layers, StickyNote, MoreVertical, Trash2, ChevronRight,
  ArrowRight, ArrowLeft, AlertTriangle, Undo2, Briefcase, Wallet,
  TrendingUp, TrendingDown, PhoneCall, Landmark, Mail, CheckCircle2,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import Modal from '../components/Modal'
import { usd, fmtMoney } from '../utils/format'

// ─── Página ──────────────────────────────────────────────────────────────────

export default function AdvisorClients() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const toast = useToast()
  const { enterClient, exitClient, clientCtx } = useAdvisorContext()

  const [clients, setClients] = useState(null)   // null = cargando
  const [book, setBook] = useState(null)         // /advisor/book (hero + estrella + colas)
  const [bookError, setBookError] = useState(false)
  const [error, setError] = useState(null)
  const [addOpen, setAddOpen] = useState(false)
  const [notesFor, setNotesFor] = useState(null)  // cliente cuyo modal de notas está abierto
  const [groupOpOpen, setGroupOpOpen] = useState(false)
  const [inviteFor, setInviteFor] = useState(null) // cliente cuyo modal de invitar está abierto
  const [menuFor, setMenuFor] = useState(null)    // client_uid del menú ⋯ abierto

  // Gate por IDENTIDAD (useAuth), no por plan features: en contexto de
  // cliente /plan/features devuelve el lente 'pro' y un gate por tier
  // rebotaba al asesor a "/" justo cuando volvía al roster (race del review).
  const isAdvisor = user?.tier === 'advisor' || !!user?.is_admin

  const load = useCallback(async () => {
    try {
      const d = await api.get('/advisor/clients')
      setClients(d.clients || [])
      setError(null)
    } catch (e) {
      setError(e.message || 'No se pudo cargar el roster')
      // Si ya había un roster cargado, un error transitorio (ej. recarga en
      // segundo plano) no debe vaciarlo a "sin clientes" — mismo patrón que
      // ya usa el fetch de /advisor/book un poco más abajo.
      setClients(prev => (prev === null ? [] : prev))
    }
    // El libro (AUM + estrella + colas) carga aparte y no bloquea el roster
    try {
      setBook(await api.get('/advisor/book'))
      setBookError(false)
    } catch {
      // No pisar un libro ya mostrado con nada; avisar que está desactualizado
      setBookError(true)
    }
  }, [])

  useEffect(() => {
    if (isAdvisor) load()
  }, [isAdvisor, load])

  // Si el asesor llega al roster con un contexto de cliente colgado (ej. volvió
  // con el botón Back del browser), lo limpiamos: el roster ES "afuera".
  useEffect(() => {
    if (clientCtx) exitClient()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (user && !isAdvisor) return <Navigate to="/" replace />

  const openClient = (c) => {
    enterClient({ id: c.client_uid, label: c.label })
    navigate('/dashboard')
  }

  const revoke = async (c) => {
    if (!window.confirm(`¿Quitar a "${c.label}" de tu lista? Sus datos no se borran; solo dejás de verlo.`)) return
    try {
      await api.post(`/advisor/clients/${c.client_uid}/revoke`)
      toast.push('Cliente quitado de tu lista')
      load()
    } catch (e) {
      toast.push(e.message || 'No se pudo quitar', { type: 'error' })
    }
  }

  return (
    <div className="page-shell-wide" onClick={() => setMenuFor(null)}>
      <PageHeader
        eyebrow="Plan Asesor"
        title="Tus clientes"
        subtitle="Todas las carteras que administrás en un solo lugar — entrá a cada cliente con visión Pro."
        action={(
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setGroupOpOpen(true)}
              disabled={!clients?.length}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-1 hover:text-ink-0 bg-bg-1 hover:bg-bg-2 border border-line rounded-md px-3 py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Layers size={13} strokeWidth={1.75} />
              Operación grupal
            </button>
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className={btnPrimary}
            >
              <Plus size={13} strokeWidth={2} />
              Agregar cliente
            </button>
          </div>
        )}
      />

      {error && (
        <div className="mb-4 text-sm text-rendi-neg bg-rendi-neg/[0.06] border border-rendi-neg/30 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {bookError && (
        <div className="mb-4 text-[12px] text-ink-2 bg-bg-1 border border-line/60 rounded-md px-3 py-2">
          No pudimos calcular el resumen de tus clientes recién{book ? ' — estás viendo la última versión' : ''}. Recargá la página para reintentar.
        </div>
      )}
      {book && <BookHero book={book} />}
      {book?.queues?.length > 0 && (
        <CallQueue queues={book.queues} clients={clients || []} onOpen={openClient} />
      )}
      {(book?.star || book?.distribution) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-6">
          {book.star && <StarSection star={book.star} />}
          {book.distribution && <DistributionCard dist={book.distribution} />}
        </div>
      )}

      {clients?.length > 0 && (
        <h2 className="text-[13px] font-semibold text-ink-2 mb-3">Clientes</h2>
      )}

      {clients === null ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-36 rounded-xl" />)}
        </div>
      ) : clients.length === 0 ? (
        <EmptyRoster onAdd={() => setAddOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {clients.map((c) => (
            <ClientCard
              key={c.client_uid}
              c={c}
              menuOpen={menuFor === c.client_uid}
              onToggleMenu={(e) => { e.stopPropagation(); setMenuFor(menuFor === c.client_uid ? null : c.client_uid) }}
              onOpen={() => openClient(c)}
              onNotes={(e) => { e.stopPropagation(); setMenuFor(null); setNotesFor(c) }}
              onInvite={(e) => { e.stopPropagation(); setMenuFor(null); setInviteFor(c) }}
              onRevoke={(e) => { e.stopPropagation(); setMenuFor(null); revoke(c) }}
            />
          ))}
        </div>
      )}

      {addOpen && <AddClientModal onClose={() => setAddOpen(false)} onCreated={() => { setAddOpen(false); load() }} />}
      {notesFor && <NotesModal client={notesFor} onClose={() => setNotesFor(null)} onSaved={() => { setNotesFor(null); load() }} />}
      {inviteFor && <InviteModal client={inviteFor} onClose={() => setInviteFor(null)} onSent={() => { setInviteFor(null); load() }} />}
      {groupOpOpen && (
        <GroupOpModal
          onClose={() => setGroupOpOpen(false)}
          onApplied={() => load()}
        />
      )}
    </div>
  )
}

// ─── Card de cliente ─────────────────────────────────────────────────────────

const CLAIM_BADGE = {
  invited: { label: 'Invitado', cls: 'text-data-violet bg-data-violet/10' },
  claimed: { label: 'Su cuenta', cls: 'text-rendi-pos bg-rendi-pos/10' },
}

function ClientCard({ c, onOpen, onNotes, onInvite, onRevoke, menuOpen, onToggleMenu }) {
  const badge = CLAIM_BADGE[c.claim_status]
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) onOpen() }}
      className="relative text-left bg-bg-1 border border-line/60 hover:border-data-violet/50 rounded-xl p-4 cursor-pointer transition-colors group"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink-0 truncate">{c.label}</p>
          <p className="text-[11px] text-ink-3 mt-0.5 flex items-center gap-1.5 flex-wrap">
            <span>{c.link_type === 'managed' ? 'Cuenta administrada' : 'Vinculado'}{c.notes ? ' · 📝' : ''}</span>
            {badge && (
              <span className={`text-[10px] font-medium rounded px-1.5 py-0.5 ${badge.cls}`}>{badge.label}</span>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onToggleMenu}
          aria-label="Opciones del cliente"
          className="p-1.5 -m-1 rounded-md text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors flex-shrink-0"
        >
          <MoreVertical size={14} strokeWidth={1.75} />
        </button>
        {menuOpen && (
          <div className="absolute right-3 top-10 z-20 w-52 bg-bg-1 border border-line rounded-lg shadow-xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {c.claim_status !== 'claimed' && (
              <button type="button" onClick={onInvite}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-ink-1 hover:bg-bg-2 transition-colors text-left">
                <Mail size={12} strokeWidth={1.75} />
                {c.claim_status === 'invited' ? 'Reenviar invitación' : 'Invitar a esta cuenta'}
              </button>
            )}
            <button type="button" onClick={onNotes}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-ink-1 hover:bg-bg-2 transition-colors text-left border-t border-line/40">
              <StickyNote size={12} strokeWidth={1.75} /> Notas privadas
            </button>
            <button type="button" onClick={onRevoke}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs text-rendi-neg hover:bg-rendi-neg/[0.06] transition-colors text-left border-t border-line/40">
              <Trash2 size={12} strokeWidth={1.75} /> Quitar de mi lista
            </button>
          </div>
        )}
      </div>

      <div className="mt-3">
        {c.aum_usd != null ? (
          <>
            <p className="text-xl font-semibold text-ink-0 tabular-nums">{usd(c.aum_usd, 0)}</p>
            <p className="text-[11px] text-ink-3 mt-0.5">AUM · snapshot {c.aum_date}</p>
          </>
        ) : (
          <>
            <p className="text-xl font-semibold text-ink-3">—</p>
            <p className="text-[11px] text-ink-3 mt-0.5">
              {c.positions_count > 0 ? 'AUM se calcula esta noche' : 'Sin posiciones cargadas'}
            </p>
          </>
        )}
      </div>

      <div className="mt-3 flex items-center gap-3 text-[11px] text-ink-2">
        <span className="inline-flex items-center gap-1"><Wallet size={11} strokeWidth={1.75} />{c.brokers_count} broker{c.brokers_count === 1 ? '' : 's'}</span>
        <span className="inline-flex items-center gap-1"><Briefcase size={11} strokeWidth={1.75} />{c.positions_count} posicion{c.positions_count === 1 ? '' : 'es'}</span>
        <span className="ml-auto inline-flex items-center gap-0.5 text-data-violet opacity-0 group-hover:opacity-100 transition-opacity font-medium">
          Entrar <ChevronRight size={12} strokeWidth={2} />
        </span>
      </div>
    </div>
  )
}

function EmptyRoster({ onAdd }) {
  return (
    <div className="border border-dashed border-line rounded-xl p-10 text-center">
      <Users size={28} strokeWidth={1.5} className="mx-auto text-ink-3 mb-3" />
      <h3 className="text-sm font-semibold text-ink-0 mb-1">Todavía no tenés clientes</h3>
      <p className="text-xs text-ink-2 max-w-sm mx-auto mb-4">
        Agregá tu primer cliente y cargale la foto de su cartera (posiciones actuales)
        desde adentro de su cuenta. El historial se construye solo, noche a noche.
      </p>
      <button
        type="button"
        onClick={onAdd}
        className={btnPrimary}
      >
        <Plus size={13} strokeWidth={2} /> Agregar cliente
      </button>
    </div>
  )
}

// Modal compartido (components/Modal): BottomSheet en mobile + prop `wide`.

const inputCls = 'w-full bg-bg-1 border border-line rounded-md px-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-data-violet focus:ring-2 focus:ring-data-violet/20 transition-colors'
const btnPrimary = 'inline-flex items-center gap-1.5 text-xs font-medium text-white bg-data-violet hover:bg-data-violet/85 rounded-md px-3.5 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

// ─── Agregar cliente ─────────────────────────────────────────────────────────

function AddClientModal({ onClose, onCreated }) {
  const toast = useToast()
  const [label, setLabel] = useState('')
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (!label.trim() || saving) return
    setSaving(true)
    setErr(null)
    try {
      await api.post('/advisor/clients', { label: label.trim(), name: name.trim() || null })
      toast.push(`Cliente "${label.trim()}" creado — entrá y cargale su cartera`)
      onCreated()
    } catch (ex) {
      setErr(ex.message || 'No se pudo crear el cliente')
      setSaving(false)
    }
  }

  return (
    <Modal title="Agregar cliente" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <label htmlFor="adv-label" className="block text-xs text-ink-2 mb-1">¿Cómo lo identificás? *</label>
          <input id="adv-label" autoFocus className={inputCls} value={label} maxLength={100}
                 onChange={(e) => setLabel(e.target.value)} placeholder='Ej: "Juan P — conservador"' />
        </div>
        <div>
          <label htmlFor="adv-name" className="block text-xs text-ink-2 mb-1">Nombre real (opcional)</label>
          <input id="adv-name" className={inputCls} value={name} maxLength={100}
                 onChange={(e) => setName(e.target.value)} placeholder="Juan Pérez" />
        </div>
        <p className="text-[11px] text-ink-3 leading-relaxed">
          Se crea una cuenta administrada por vos. Después entrás a su Rendi y le cargás
          la foto de su cartera (import del broker o carga manual). Tu cliente no recibe
          ningún email.
        </p>
        {err && <p className="text-xs text-rendi-neg">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="text-xs text-ink-2 hover:text-ink-0 px-3 py-2 transition-colors">Cancelar</button>
          <button type="submit" disabled={!label.trim() || saving}
                  className={btnPrimary}>
            {saving ? 'Creando…' : 'Crear cliente'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// ─── Notas privadas ──────────────────────────────────────────────────────────

function NotesModal({ client, onClose, onSaved }) {
  const toast = useToast()
  const [notes, setNotes] = useState(client.notes || '')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (saving) return
    setSaving(true)
    try {
      await api.patch(`/advisor/clients/${client.client_uid}`, { notes })
      toast.push('Notas guardadas')
      onSaved()
    } catch (e) {
      toast.push(e.message || 'No se pudo guardar', { type: 'error' })
      setSaving(false)
    }
  }

  return (
    <Modal title={`Notas privadas — ${client.label}`} onClose={onClose}>
      <textarea
        autoFocus
        rows={6}
        className={inputCls + ' resize-y'}
        value={notes}
        maxLength={2000}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Fee acordado, perfil, próxima llamada… Solo vos ves esto."
      />
      <div className="flex justify-end gap-2 pt-3">
        <button type="button" onClick={onClose} className="text-xs text-ink-2 hover:text-ink-0 px-3 py-2 transition-colors">Cancelar</button>
        <button type="button" onClick={save} disabled={saving}
                className={btnPrimary}>
          {saving ? 'Guardando…' : 'Guardar'}
        </button>
      </div>
    </Modal>
  )
}

// ─── Invitar a reclamar la cuenta (F4a) ──────────────────────────────────────
// El asesor pone el email REAL del cliente → le llega un link para poner
// contraseña y entrar a ver LO MISMO que el asesor le cargó (misma cuenta).

function InviteModal({ client, onClose, onSent }) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState(null)
  const alreadyInvited = client.claim_status === 'invited'

  const submit = async (e) => {
    e.preventDefault()
    if (!email.trim() || sending) return
    setSending(true)
    setErr(null)
    try {
      await api.post(`/advisor/clients/${client.client_uid}/invite`, { email: email.trim() })
      toast.push(`Invitación enviada a ${email.trim()}`)
      onSent()
    } catch (ex) {
      setErr(ex.message || 'No se pudo enviar la invitación')
      setSending(false)
    }
  }

  return (
    <Modal title={`Invitar a ${client.label}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <p className="text-xs text-ink-2 leading-relaxed">
          {alreadyInvited
            ? 'Ya le mandamos un link a este cliente. Si ingresás un email nuevo, se lo reenviamos ahí (el link anterior deja de servir).'
            : 'Le mandamos un email para que ponga su propia contraseña y entre a ver — con visión Free — la cartera que le cargaste. Es la MISMA cuenta: lo que vos edites, él lo ve; lo que él edite, vos lo ves.'}
        </p>
        <div>
          <label htmlFor="inv-email" className="block text-xs text-ink-2 mb-1">Email real del cliente *</label>
          <input id="inv-email" type="email" autoFocus className={inputCls} value={email}
                 maxLength={254} onChange={(e) => setEmail(e.target.value)}
                 placeholder="juan.perez@gmail.com" />
        </div>
        {err && <p className="text-xs text-rendi-neg">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="text-xs text-ink-2 hover:text-ink-0 px-3 py-2 transition-colors">Cancelar</button>
          <button type="submit" disabled={!email.trim() || sending} className={btnPrimary}>
            <Mail size={12} strokeWidth={1.75} />
            {sending ? 'Enviando…' : (alreadyInvited ? 'Reenviar' : 'Mandar invitación')}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// ─── Operación grupal (block trade) ─────────────────────────────────────────
// 3 pasos: (1) la operación común, (2) para quiénes, (3) tabla de asignación
// con broker/cantidad/precio POR FILA (las posiciones viven por broker: sin
// esto no se sabe a qué cuenta-broker entra la compra de cada cliente).

function GroupOpModal({ onClose, onApplied }) {
  const toast = useToast()
  const [step, setStep] = useState(1)
  // Paso 1 — operación común
  const [asset, setAsset] = useState('')
  const [price, setPrice] = useState('')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [currency, setCurrency] = useState('ARS')
  // Paso 2/3 — clientes + asignación
  const [prep, setPrep] = useState(null)         // respuesta de /prep
  const [selected, setSelected] = useState({})   // client_uid → bool
  const [rows, setRows] = useState({})           // client_uid → {broker, quantity, price}
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)     // respuesta del POST (para undo)

  const goStep2 = async () => {
    if (!asset.trim() || !price) return
    try {
      const d = await api.get(`/advisor/group-op/prep?asset=${encodeURIComponent(asset.trim().toUpperCase())}&currency=${encodeURIComponent(currency)}`)
      const clients = d.clients || []
      setPrep(clients)
      // Preselección: todos los que tienen algún broker
      const sel = {}
      clients.forEach((c) => { sel[c.client_uid] = c.brokers.length > 0 })
      setSelected(sel)
      setStep(2)
    } catch (e) {
      toast.push(e.message || 'No se pudo preparar la operación', { type: 'error' })
    }
  }

  const goStep3 = () => {
    const r = {}
    prep.filter((c) => selected[c.client_uid]).forEach((c) => {
      // Preservar lo ya tipeado si el asesor volvió al paso 2 y re-entra:
      // perder 15 cantidades/precios cargados era el bug del review.
      r[c.client_uid] = rows[c.client_uid] || {
        broker: c.suggested_broker || (c.brokers[0]?.name ?? ''),
        quantity: '',
        price: price,
      }
    })
    setRows(r)
    setStep(3)
  }

  const chosen = useMemo(() => (prep || []).filter((c) => selected[c.client_uid]), [prep, selected])
  const validRows = useMemo(() => chosen.filter((c) => {
    const r = rows[c.client_uid]
    return r && r.broker && Number(r.quantity) > 0 && Number(r.price) >= 0
  }), [chosen, rows])

  const submit = async () => {
    if (!validRows.length || submitting) return
    setSubmitting(true)
    try {
      const body = {
        asset: asset.trim().toUpperCase(),
        currency,
        entry_date: date || null,
        rows: validRows.map((c) => ({
          client_uid: c.client_uid,
          broker: rows[c.client_uid].broker,
          quantity: Number(rows[c.client_uid].quantity),
          buy_price: Number(rows[c.client_uid].price),
        })),
      }
      const d = await api.post('/advisor/group-op', body)
      setResult(d)
      onApplied()
    } catch (e) {
      toast.push(e.message || 'No se pudo aplicar la operación', { type: 'error' })
      setSubmitting(false)
    }
  }

  const undo = async () => {
    if (!result?.batch_id) return
    try {
      await api.post(`/advisor/group-op/${result.batch_id}/undo`)
      toast.push('Lote deshecho — posiciones borradas y cash re-acreditado')
      onApplied()
      onClose()
    } catch (e) {
      toast.push(e.message || 'No se pudo deshacer', { type: 'error' })
    }
  }

  // ── Resultado ──
  if (result) {
    return (
      <Modal title="Operación aplicada" onClose={onClose} wide>
        <div className="space-y-3">
          <p className="text-sm text-ink-1">
            <span className="font-semibold text-ink-0">{asset.trim().toUpperCase()}</span> registrada
            en <span className="font-semibold text-ink-0">{result.applied.length}</span> cuenta{result.applied.length === 1 ? '' : 's'}.
          </p>
          {result.skipped?.length > 0 && (
            <div className="text-xs text-ink-2 bg-bg-1 border border-line/60 rounded-md p-3 space-y-1">
              <p className="font-medium text-ink-1 flex items-center gap-1.5"><AlertTriangle size={12} className="text-rendi-warn" /> {result.skipped.length} fila{result.skipped.length === 1 ? '' : 's'} salteada{result.skipped.length === 1 ? '' : 's'}:</p>
              {result.skipped.map((s, i) => (
                <p key={i}>· Cliente {s.client_uid}: {s.reason}</p>
              ))}
            </div>
          )}
          <div className="flex justify-between items-center pt-2">
            <button type="button" onClick={undo}
                    className="inline-flex items-center gap-1.5 text-xs text-rendi-neg hover:bg-rendi-neg/[0.06] border border-rendi-neg/30 rounded-md px-3 py-2 transition-colors">
              <Undo2 size={12} strokeWidth={1.75} /> Deshacer lote completo
            </button>
            <button type="button" onClick={onClose}
                    className={btnPrimary}>
              Listo
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title={`Operación grupal — paso ${step} de 3`} onClose={onClose} wide={step === 3}>
      {step === 1 && (
        <div className="space-y-3">
          <div>
            <label htmlFor="gop-asset" className="block text-xs text-ink-2 mb-1">Activo (ticker) *</label>
            <input id="gop-asset" autoFocus className={inputCls} value={asset}
                   onChange={(e) => setAsset(e.target.value)} placeholder="AL30, GGAL, AAPL…" maxLength={100} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label htmlFor="gop-price" className="block text-xs text-ink-2 mb-1">Precio *</label>
              <input id="gop-price" type="number" min="0" step="any" className={inputCls} value={price}
                     onChange={(e) => setPrice(e.target.value)} placeholder="58.900" />
            </div>
            <div>
              <label htmlFor="gop-date" className="block text-xs text-ink-2 mb-1">Fecha</label>
              <input id="gop-date" type="date" className={inputCls} value={date}
                     onChange={(e) => setDate(e.target.value)} />
            </div>
            <div>
              <label htmlFor="gop-ccy" className="block text-xs text-ink-2 mb-1">Moneda</label>
              <select id="gop-ccy" className={inputCls} value={currency} onChange={(e) => setCurrency(e.target.value)}>
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>
          <p className="text-[11px] text-ink-3">El precio se precarga en todas las filas del paso 3 — después lo ajustás por cliente si los fills difirieron.</p>
          <div className="flex justify-end pt-1">
            <button type="button" onClick={goStep2} disabled={!asset.trim() || !price}
                    className={btnPrimary}>
              Elegir clientes <ArrowRight size={12} strokeWidth={2} />
            </button>
          </div>
        </div>
      )}

      {step === 2 && prep && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-ink-2">¿A quiénes les registrás la compra de <span className="font-semibold text-ink-0">{asset.trim().toUpperCase()}</span>?</p>
            <button type="button" className="text-[11px] text-data-violet hover:underline"
                    onClick={() => {
                      const all = prep.every((c) => selected[c.client_uid] || c.brokers.length === 0)
                      const sel = {}
                      prep.forEach((c) => { sel[c.client_uid] = !all && c.brokers.length > 0 })
                      setSelected(sel)
                    }}>
              Alternar todos
            </button>
          </div>
          <div className="border border-line/60 rounded-lg divide-y divide-line/40 max-h-72 overflow-y-auto">
            {prep.map((c) => (
              <label key={c.client_uid} className={`flex items-center gap-3 px-3 py-2.5 text-sm ${c.brokers.length === 0 ? 'opacity-45 cursor-not-allowed' : 'cursor-pointer hover:bg-bg-1'}`}>
                <input
                  type="checkbox"
                  className="accent-[#8B7DFF]"
                  disabled={c.brokers.length === 0}
                  checked={!!selected[c.client_uid]}
                  onChange={(e) => setSelected({ ...selected, [c.client_uid]: e.target.checked })}
                />
                <span className="flex-1 min-w-0 truncate text-ink-0">{c.label}</span>
                {c.has_asset && <span className="text-[10px] text-data-violet bg-data-violet/10 rounded px-1.5 py-0.5">ya lo tiene</span>}
                {c.brokers.length === 0 && <span className="text-[10px] text-ink-3">sin brokers</span>}
              </label>
            ))}
          </div>
          <div className="flex justify-between pt-1">
            <button type="button" onClick={() => setStep(1)} className="inline-flex items-center gap-1 text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">
              <ArrowLeft size={12} /> Volver
            </button>
            <button type="button" onClick={goStep3} disabled={!chosen.length}
                    className={btnPrimary}>
              Asignar cantidades ({chosen.length}) <ArrowRight size={12} strokeWidth={2} />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          <p className="text-xs text-ink-2">
            <span className="font-semibold text-ink-0">{asset.trim().toUpperCase()}</span> · {currency} · {date} — una fila por cliente. El broker sugerido es donde ya tiene el activo (o su único broker).
          </p>
          <div className="border border-line/60 rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10.5px] uppercase tracking-wide text-ink-3 border-b border-line/60">
                  <th className="text-left px-3 py-2 font-medium">Cliente</th>
                  <th className="text-left px-3 py-2 font-medium">Broker</th>
                  <th className="text-right px-3 py-2 font-medium">Cantidad</th>
                  <th className="text-right px-3 py-2 font-medium">Precio</th>
                  <th className="text-right px-3 py-2 font-medium">Monto</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/40">
                {chosen.map((c) => {
                  const r = rows[c.client_uid] || {}
                  const amount = Number(r.quantity) > 0 && Number(r.price) >= 0
                    ? Number(r.quantity) * Number(r.price) : null
                  const set = (patch) => setRows({ ...rows, [c.client_uid]: { ...r, ...patch } })
                  return (
                    <tr key={c.client_uid}>
                      <td className="px-3 py-2 text-ink-0 whitespace-nowrap max-w-[160px] truncate">{c.label}</td>
                      <td className="px-3 py-2">
                        <select
                          aria-label={`Broker de ${c.label}`}
                          className="bg-bg-1 border border-line rounded px-2 py-1 text-xs text-ink-0 focus:outline-none focus:border-data-violet"
                          value={r.broker || ''}
                          onChange={(e) => set({ broker: e.target.value })}
                        >
                          {c.brokers.map((b) => (
                            <option key={b.name} value={b.name}>{b.name} ({b.currency})</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <input type="number" min="0" step="any" aria-label={`Cantidad de ${c.label}`}
                               className="w-24 bg-bg-1 border border-line rounded px-2 py-1 text-xs text-right text-ink-0 focus:outline-none focus:border-data-violet"
                               value={r.quantity ?? ''} onChange={(e) => set({ quantity: e.target.value })} />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <input type="number" min="0" step="any" aria-label={`Precio de ${c.label}`}
                               className="w-24 bg-bg-1 border border-line rounded px-2 py-1 text-xs text-right text-ink-0 focus:outline-none focus:border-data-violet"
                               value={r.price ?? ''} onChange={(e) => set({ price: e.target.value })} />
                      </td>
                      <td className="px-3 py-2 text-right text-xs text-ink-1 tabular-nums whitespace-nowrap">
                        {amount != null ? fmtMoney(amount, currency) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="flex justify-between items-center pt-1">
            <button type="button" onClick={() => setStep(2)} className="inline-flex items-center gap-1 text-xs text-ink-2 hover:text-ink-0 px-2 py-2 transition-colors">
              <ArrowLeft size={12} /> Volver
            </button>
            <button type="button" onClick={submit} disabled={!validRows.length || submitting}
                    className={btnPrimary}>
              {submitting ? 'Aplicando…' : `Registrar en ${validRows.length} cuenta${validRows.length === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ─── F3: el libro (hero + colas + estrella + distribución) ──────────────────

// usd() formatea negativos con paréntesis — para deltas del libro queremos ±.
const signedUsd = (n) => (n >= 0 ? `+${usd(n, 0)}` : `−${usd(Math.abs(n), 0)}`)
const signedPct = (n) => (n >= 0 ? `+${n}%` : `${n}%`)

function BookHero({ book }) {
  const { aum, flows_month: flows } = book
  if (!aum || aum.clients === 0) return null
  const hasAum = aum.total_usd != null
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-5 mb-4">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
        <div>
          <p className="text-[11.5px] text-ink-3 mb-1">Total administrado</p>
          {hasAum ? (
            <>
              <p className="text-3xl font-semibold text-ink-0 tabular-nums leading-none">
                {usd(aum.total_usd, 0)}
              </p>
              <p className="text-[10.5px] text-ink-3 mt-1.5">
                La suma de las carteras de todos tus clientes
                {(() => {
                  // Si el snapshot más nuevo es viejo (cron caído), avisar en
                  // vez de mentir "+0" como si el mercado no se hubiera movido.
                  if (!aum.as_of) return null
                  const days = Math.floor((Date.now() - new Date(aum.as_of + 'T12:00:00').getTime()) / 86400000)
                  return days > 1 ? ` · datos al ${aum.as_of}` : null
                })()}
              </p>
            </>
          ) : (
            <p className="text-lg text-ink-3 leading-none">
              Se calcula esta noche
              <span className="block text-[11px] mt-1">cada noche sumamos el valor de las carteras cargadas</span>
            </p>
          )}
        </div>
        {aum.delta_7d_usd != null && (
          <div>
            <p className="text-[11.5px] text-ink-3 mb-1">Últimos 7 días</p>
            <p className={`text-sm font-medium tabular-nums ${aum.delta_7d_usd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {signedUsd(aum.delta_7d_usd)}
              {aum.delta_7d_pct != null && ` · ${signedPct(aum.delta_7d_pct)}`}
            </p>
          </div>
        )}
        {flows && (
          <div>
            <p className="text-[11.5px] text-ink-3 mb-1">Aportes − retiros (este mes)</p>
            <p className="text-sm font-medium text-ink-0 tabular-nums">
              {signedUsd(flows.net_deposited_usd)}
            </p>
            <p className="text-[10.5px] text-ink-3 mt-0.5 tabular-nums">
              Plata que entró/salió de las cuentas · el mercado {flows.market_effect_usd >= 0 ? 'sumó ' : 'restó '}
              {usd(Math.abs(flows.market_effect_usd), 0)}
            </p>
          </div>
        )}
        <div className="ml-auto text-right">
          <p className="text-[11.5px] text-ink-3 mb-1">Clientes</p>
          <p className="text-sm font-medium text-ink-0 tabular-nums">
            {aum.clients}
            {aum.with_data < aum.clients && (
              <span className="text-ink-3 font-normal"> · {aum.clients - aum.with_data} sin datos aún</span>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

function CallQueue({ queues, clients, onOpen }) {
  const byUid = Object.fromEntries((clients || []).map((c) => [c.client_uid, c]))
  const KIND_STYLE = {
    drawdown:    'text-rendi-neg bg-rendi-neg/10',
    cash_ocioso: 'text-rendi-warn bg-rendi-warn/10',
    inactivo:    'text-ink-2 bg-bg-2',
    sin_cargar:  'text-data-violet bg-data-violet/10',
  }
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-4 mb-4">
      <div className="mb-3">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0">
          <PhoneCall size={13} strokeWidth={1.75} className="text-data-violet" />
          Clientes que necesitan tu atención
          <span className="text-ink-3 font-normal">({queues.length})</span>
        </h2>
        <p className="text-[11px] text-ink-3 mt-0.5 ml-[21px]">
          Señales automáticas: caídas fuertes, plata sin invertir o cuentas frenadas — los candidatos a un llamado.
        </p>
      </div>
      <div className="divide-y divide-line/40">
        {queues.map((q) => (
          <div key={q.client_uid} className="flex items-center gap-3 py-2 flex-wrap">
            <span className="text-sm font-medium text-ink-0 min-w-[140px]">{q.label}</span>
            <div className="flex-1 flex flex-wrap gap-1.5">
              {q.reasons.map((r, i) => (
                <span key={i} className={`text-[11px] rounded px-2 py-0.5 ${KIND_STYLE[r.kind] || 'text-ink-2 bg-bg-2'}`}>
                  {r.detail}
                </span>
              ))}
            </div>
            {byUid[q.client_uid] && (
              <button
                type="button"
                onClick={() => onOpen(byUid[q.client_uid])}
                className="text-[11px] font-medium text-data-violet hover:bg-data-violet/10 border border-data-violet/30 rounded px-2 py-1 transition-colors flex-shrink-0"
              >
                Entrar →
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function StarSection({ star }) {
  const Row = ({ r, tone }) => {
    // Cada columna muestra SU plata (lo que pierden los que pierden / ganan
    // los que ganan) — el neto agregado contradecía el título cuando un
    // activo tenía clientes en ambos lados.
    const pnl = tone === 'red' ? (r.pnl_red_usd ?? r.pnl_usd) : (r.pnl_green_usd ?? r.pnl_usd)
    return (
      <div className="flex items-center gap-2 py-1.5">
        <span className="text-sm font-medium text-ink-0 w-20 truncate">{r.asset}</span>
        <span className="text-[11px] text-ink-2 flex-1">
          {tone === 'red'
            ? `${r.clients_red} de ${r.clients_total} cliente${r.clients_total === 1 ? '' : 's'} en rojo`
            : `${r.clients_green} de ${r.clients_total} cliente${r.clients_total === 1 ? '' : 's'} en verde`}
        </span>
        <span className={`text-xs font-medium tabular-nums ${pnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {signedUsd(pnl)}
        </span>
      </div>
    )
  }
  return (
    <div className="lg:col-span-2 bg-bg-1 border border-line/60 rounded-xl p-4">
      <h2 className="text-[13px] font-semibold text-ink-0 mb-3">Qué activos mueven a tus clientes</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        <div>
          <p className="flex items-center gap-1.5 text-[11px] text-rendi-neg font-medium mb-1">
            <TrendingDown size={11} strokeWidth={2} /> Le hace perder a más clientes
          </p>
          {star.losers.length
            ? star.losers.map((r) => <Row key={r.asset} r={r} tone="red" />)
            : <p className="text-[11.5px] text-ink-3 py-1.5">Ningún activo en rojo — bien ahí.</p>}
        </div>
        <div>
          <p className="flex items-center gap-1.5 text-[11px] text-rendi-pos font-medium mb-1">
            <TrendingUp size={11} strokeWidth={2} /> Le hace ganar a más clientes
          </p>
          {star.winners.length
            ? star.winners.map((r) => <Row key={r.asset} r={r} tone="green" />)
            : <p className="text-[11.5px] text-ink-3 py-1.5">Todavía nada en verde.</p>}
        </div>
      </div>
      {star.skipped_no_price > 0 && (
        <p className="text-[10.5px] text-ink-3 mt-2">
          {star.skipped_no_price} posición{star.skipped_no_price === 1 ? '' : 'es'} quedaron afuera del cálculo (sin precio conocido o con broker borrado).
        </p>
      )}
    </div>
  )
}

function DistributionCard({ dist }) {
  const total = dist.green + dist.red + dist.flat
  const pct = (n) => (total > 0 ? (n / total) * 100 : 0)
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-4">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0 mb-3">
        <Landmark size={13} strokeWidth={1.75} className="text-data-violet" />
        ¿Cómo vienen tus clientes?
      </h2>
      <div className="flex h-2 rounded-full overflow-hidden bg-bg-2 mb-2">
        {dist.green > 0 && <div className="bg-rendi-pos" style={{ width: `${pct(dist.green)}%` }} />}
        {dist.flat > 0 && <div className="bg-ink-3/40" style={{ width: `${pct(dist.flat)}%` }} />}
        {dist.red > 0 && <div className="bg-rendi-neg" style={{ width: `${pct(dist.red)}%` }} />}
      </div>
      <p className="text-[11.5px] text-ink-2 mb-3">
        <span className="text-rendi-pos font-medium">{dist.green} en verde</span>
        {' · '}
        <span className="text-rendi-neg font-medium">{dist.red} en rojo</span>
        {dist.flat > 0 && <> · {dist.flat} neutro{dist.flat === 1 ? '' : 's'}</>}
      </p>
      <div className="space-y-1 text-[11.5px]">
        {dist.best && (
          <p className="text-ink-2 truncate">
            Mejor: <span className="text-ink-0">{dist.best.label}</span>{' '}
            <span className={`tabular-nums ${dist.best.ret_pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{signedPct(dist.best.ret_pct)}</span>
          </p>
        )}
        {dist.worst && dist.worst.client_uid !== dist.best?.client_uid && (
          <p className="text-ink-2 truncate">
            Peor: <span className="text-ink-0">{dist.worst.label}</span>{' '}
            <span className={`tabular-nums ${dist.worst.ret_pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{signedPct(dist.worst.ret_pct)}</span>
          </p>
        )}
      </div>
      <p className="text-[10.5px] text-ink-3 mt-2">Retorno total vs. aportado, del último snapshot.</p>
    </div>
  )
}
