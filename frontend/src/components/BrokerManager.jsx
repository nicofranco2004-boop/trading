// BrokerManager — chips de brokers conectados + botón "+" para agregar.
// ═══════════════════════════════════════════════════════════════════════════
// Reemplazó la tabla de brokers en Config. Ahora vive en Positions porque
// es donde el user manipula sus brokers (y los ve activos).
//
// UX:
//   • Cada broker es un chip con nombre + currency pill + acciones hover
//     (editar, eliminar)
//   • Chip "+" al final abre modal de agregar
//   • Free user que intenta agregar broker n°2 → backend 403 → UpgradeModal
//   • Eliminar pide confirmación
//
// Props:
//   brokers     — array de {id, name, currency, parent_broker_id}
//   onChange()  — callback para recargar la lista (post add/edit/delete)

import { useState } from 'react'
import { Plus, Pencil, Trash2, X } from 'lucide-react'
import { api } from '../utils/api'
import { track } from '../utils/track'
import Modal from './Modal'
import Pill from './Pill'
import UpgradeModal from './plan/UpgradeModal'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'

function currencyTone(c) {
  switch (c) {
    case 'USDT': return 'info'
    case 'USD':  return 'neutral'
    case 'ARS':  return 'warn'
    default:     return 'default'
  }
}

export default function BrokerManager({ brokers, onChange }) {
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(null)
  const [brokerUpgrade, setBrokerUpgrade] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })

  async function addBroker(e) {
    e.preventDefault()
    if (!newBroker.name.trim()) return
    try {
      await api.post('/brokers', { name: newBroker.name.trim(), currency: newBroker.currency })
      setNewBroker({ name: '', currency: 'USDT' })
      setShowAdd(false)
      onChange?.()
      refreshPlanFeatures()
    } catch (ex) {
      if (ex?.status === 403 && ex?.payload?.detail?.upgrade) {
        const detail = ex.payload.detail
        track('feature_blocked_clicked', { feature: 'brokers.create', source: 'positions_broker_manager' })
        setBrokerUpgrade({
          message: detail.error || 'El plan Free permite 1 broker.',
          benefits: detail.upgrade?.benefits,
        })
        return
      }
      alert('No pudimos agregar el broker. Probá de nuevo.')
    }
  }

  async function saveEdit(e) {
    e.preventDefault()
    if (!editing.name.trim()) return
    await api.put(`/brokers/${editing.id}`, { name: editing.name.trim(), currency: editing.currency })
    setEditing(null)
    onChange?.()
  }

  async function deleteBroker(b) {
    if (!confirm(`¿Eliminar el broker "${b.name}"? Las posiciones asociadas quedarán huérfanas y deberás reasignarlas manualmente.`)) return
    await api.delete(`/brokers/${b.id}`)
    onChange?.()
    refreshPlanFeatures()
  }

  return (
    <section className="mb-6">
      <header className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <div>
          <p className="eyebrow mb-0.5">Brokers</p>
          <h3 className="text-sm font-medium text-ink-1">
            {brokers.length} {brokers.length === 1 ? 'cuenta conectada' : 'cuentas conectadas'}
          </h3>
        </div>
      </header>

      <div className="flex flex-wrap gap-2">
        {brokers.map(b => (
          <BrokerChip
            key={b.id}
            broker={b}
            onEdit={() => setEditing({ ...b })}
            onDelete={() => deleteBroker(b)}
          />
        ))}
        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-dashed border-data-violet/40 hover:border-data-violet/60 rounded-sm px-3 py-2 transition-colors"
        >
          <Plus size={13} strokeWidth={2} /> Agregar broker
        </button>
      </div>

      {/* Modal: agregar */}
      {showAdd && (
        <Modal title="Agregar broker" onClose={() => setShowAdd(false)}>
          <form onSubmit={addBroker} className="space-y-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Nombre del broker</label>
              <input
                value={newBroker.name}
                onChange={e => setNewBroker(b => ({ ...b, name: e.target.value }))}
                placeholder="Ej.: Binance, Cocos, IOL, IBKR…"
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tipo de moneda</label>
              <select
                value={newBroker.currency}
                onChange={e => setNewBroker(b => ({ ...b, currency: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
              >
                <option value="USDT">USDT — Exchange crypto (Binance, Bybit, etc.)</option>
                <option value="USD">USD — Broker en dólares (IBKR, Schwab, etc.)</option>
                <option value="ARS">ARS — Broker en pesos (Cocos, IOL, Balanz)</option>
              </select>
              <p className="text-[10px] text-ink-3 mt-1 leading-relaxed">
                Brokers ARS se convierten al blue para el valor total en USD.
              </p>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowAdd(false)}
                className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-4 py-2 rounded-sm transition-colors"
              >
                <Plus size={12} strokeWidth={2} /> Agregar
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: editar */}
      {editing && (
        <Modal title={`Editar "${editing.name}"`} onClose={() => setEditing(null)}>
          <form onSubmit={saveEdit} className="space-y-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Nombre del broker</label>
              <input
                value={editing.name}
                onChange={e => setEditing(eb => ({ ...eb, name: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
                autoFocus
              />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tipo de moneda</label>
              <select
                value={editing.currency}
                onChange={e => setEditing(eb => ({ ...eb, currency: e.target.value }))}
                className="w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2"
              >
                <option value="USDT">USDT</option>
                <option value="USD">USD</option>
                <option value="ARS">ARS</option>
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                className="text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-4 py-2 rounded-sm transition-colors"
              >
                Guardar
              </button>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal de upgrade cuando intenta agregar broker n°2 en Free */}
      {brokerUpgrade && (
        <UpgradeModal
          title="Pasate a Rendi Pro para más brokers"
          message={brokerUpgrade.message}
          feature="brokers.create"
          source="positions_broker_manager"
          benefits={brokerUpgrade.benefits}
          onClose={() => setBrokerUpgrade(null)}
        />
      )}
    </section>
  )
}

// ─── BrokerChip ─────────────────────────────────────────────────────────────

function BrokerChip({ broker, onEdit, onDelete }) {
  return (
    <div className="group inline-flex items-center gap-2 bg-bg-1 border border-line/60 hover:border-line rounded-sm px-3 py-2 transition-colors">
      <span className="text-sm font-medium text-ink-0">{broker.name}</span>
      <Pill tone={currencyTone(broker.currency)}>{broker.currency}</Pill>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onEdit}
          className="p-1 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
          title={`Editar ${broker.name}`}
          aria-label={`Editar ${broker.name}`}
        >
          <Pencil size={11} strokeWidth={1.75} />
        </button>
        <button
          onClick={onDelete}
          className="p-1 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-2 transition-colors"
          title={`Eliminar ${broker.name}`}
          aria-label={`Eliminar ${broker.name}`}
        >
          <Trash2 size={11} strokeWidth={1.75} />
        </button>
      </div>
    </div>
  )
}
