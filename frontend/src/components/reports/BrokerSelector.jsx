// BrokerSelector — dropdown para filtrar la timeline por broker.
//
// Reemplaza las tabs horizontales del diseño viejo. Escala mejor con N brokers.
// Default option es "Portfolio Global" (consolidado).

import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { api } from '../../utils/api'

export default function BrokerSelector({ value = 'global', onChange }) {
  const [brokers, setBrokers] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/brokers')
      .then(data => { if (!cancelled) setBrokers(data || []) })
      .catch(() => { if (!cancelled) setBrokers([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="relative inline-block">
      <select
        value={value}
        onChange={e => onChange?.(e.target.value)}
        disabled={loading}
        className="appearance-none bg-bg-2 border border-line text-ink-1 text-sm rounded-sm px-3 py-2 pr-8 cursor-pointer hover:bg-bg-3 transition-colors disabled:opacity-50 focus:outline-none focus:border-ink-2"
      >
        <option value="global">Cartera global</option>
        {brokers.map(b => (
          <option key={b.id || b.name} value={b.name}>
            {b.name}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        strokeWidth={1.75}
        className="absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none text-ink-3"
        aria-hidden="true"
      />
    </div>
  )
}
