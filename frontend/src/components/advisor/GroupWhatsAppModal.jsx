// GroupWhatsAppModal — escribís el mensaje UNA vez y lo mandás al grupo.
//
// ⚠️ WhatsApp NO permite difusión desde un link: wa.me abre UN chat con UN
// número. No hay forma de mandarle a 12 personas de una sin la API de negocios.
// Entonces lo honesto es esto: escribís una vez, y la lista te va llevando de
// a uno con el texto ya cargado, marcando a quién ya le escribiste. El ahorro
// real es no re-tipear el mensaje 12 veces ni perder el hilo de por quién ibas.
import { useState } from 'react'
import { X, Check, ExternalLink } from 'lucide-react'
import { whatsappUrl } from '../../utils/support'

const firstName = (c) => String(c.name || c.label || '').trim().split(/\s+/)[0] || ''

export default function GroupWhatsAppModal({ group, clients, onClose }) {
  const [tpl, setTpl] = useState('Hola {nombre}! ¿Cómo va? Te escribo por tu cartera.')
  const [sent, setSent] = useState(() => new Set())

  const withPhone = clients.filter(c => c.phone)
  const without = clients.filter(c => !c.phone)
  const pending = withPhone.filter(c => !sent.has(c.client_uid))

  const msgFor = (c) => tpl.replace(/\{nombre\}/g, firstName(c))

  function open(c) {
    window.open(whatsappUrl(msgFor(c), c.phone), '_blank', 'noopener')
    setSent(prev => new Set(prev).add(c.client_uid))
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-bg-1 border border-line rounded-xl w-full max-w-lg max-h-[85vh] flex flex-col"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink-0 truncate">
              Escribirle a {group?.name || 'tus clientes'}
            </h3>
            <p className="text-[11px] text-ink-3 mt-0.5">
              {withPhone.length} con celular cargado
              {without.length > 0 ? ` · ${without.length} sin celular` : ''}
            </p>
          </div>
          <button onClick={onClose} aria-label="Cerrar" className="text-ink-3 hover:text-ink-0 shrink-0">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 space-y-4 overflow-y-auto">
          <div>
            <label htmlFor="wa-tpl" className="block text-xs text-ink-2 mb-1.5">
              El mensaje (escribilo una vez)
            </label>
            <textarea id="wa-tpl" value={tpl} onChange={e => setTpl(e.target.value)} rows={4}
              className="w-full text-sm bg-bg-2 border border-line rounded-md px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none resize-none" />
            <p className="text-[11px] text-ink-3 mt-1">
              Escribí <code className="text-ink-2">{'{nombre}'}</code> y lo reemplaza por el nombre de cada uno.
            </p>
          </div>

          <div className="rounded-md bg-bg-2/60 border border-line/60 px-3 py-2">
            <p className="text-[11px] text-ink-3">
              WhatsApp no deja mandar a varios de una sola vez: se abre un chat por
              persona con el texto ya escrito, y vos apretás enviar. Acá vas tildando
              a quién ya le escribiste para no perder la cuenta.
            </p>
          </div>

          <div className="border border-line rounded-md divide-y divide-line/40">
            {withPhone.map(c => {
              const done = sent.has(c.client_uid)
              return (
                <div key={c.client_uid} className="flex items-center gap-3 px-3 py-2.5">
                  <span className={`flex-1 min-w-0 truncate text-[13px] ${done ? 'text-ink-3 line-through' : 'text-ink-0'}`}>
                    {c.name || c.label}
                  </span>
                  {done && <Check size={14} className="text-emerald-400 shrink-0" />}
                  <button type="button" onClick={() => open(c)}
                    className={`shrink-0 inline-flex items-center gap-1.5 text-[11px] rounded-full px-3 py-1.5 border transition-colors ${
                      done ? 'border-line text-ink-3 hover:text-ink-1'
                           : 'border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10'}`}>
                    <ExternalLink size={12} /> {done ? 'Abrir de nuevo' : 'Abrir chat'}
                  </button>
                </div>
              )
            })}
            {withPhone.length === 0 && (
              <p className="text-xs text-ink-3 px-3 py-4 text-center">
                Ninguno de estos clientes tiene el celular cargado. Podés agregarlo
                desde “Notas privadas” en cada uno.
              </p>
            )}
          </div>

          {without.length > 0 && (
            <p className="text-[11px] text-ink-3">
              Sin celular: {without.map(c => c.name || c.label).join(', ')}.
            </p>
          )}
        </div>

        <div className="px-5 py-3 border-t border-line flex items-center justify-between">
          <span className="text-[11px] text-ink-3">
            {pending.length === 0 && withPhone.length > 0
              ? 'Les escribiste a todos.'
              : `Te faltan ${pending.length} de ${withPhone.length}.`}
          </span>
          <button type="button" onClick={onClose}
            className="text-xs text-ink-1 hover:text-ink-0 border border-line rounded-md px-3 py-1.5">
            Listo
          </button>
        </div>
      </div>
    </div>
  )
}
