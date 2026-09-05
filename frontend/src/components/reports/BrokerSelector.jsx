// BrokerSelector — dropdown para filtrar la timeline por CUENTA.
//
// Reemplaza las tabs horizontales del diseño viejo. Escala mejor con N brokers.
// Default option es "Portfolio Global" (consolidado).
//
// ⚠️ UNA OPCIÓN POR CUENTA, NO POR FILA DE `brokers`. GET /api/brokers hace un
// `SELECT *` sin filtrar hijos, así que antes ofrecía "IOL" y "IOL · USD" como
// dos opciones sueltas. Eso era medio coherente mientras el backend filtraba
// `broker = ?` y cada opción traía su mitad; ahora que los lectores de reportes
// miran el PAR (`broker_pair`), las dos devuelven EXACTAMENTE el mismo reporte
// — dos filtros distintos con una sola respuesta, una pantalla que se
// contradice a sí misma.
//
// El agrupado sale de `groupBrokersIntoAccounts`, la MISMA función que usa
// Cartera: agrupa por `parent_broker_id` (nunca parseando el sufijo ' · USD',
// su docstring explica por qué), soporta N patas y re-emite los huérfanos como
// cuenta propia. Un tercer constructor del árbol padre→hijo es cómo se
// desincronizan dos criterios de identidad.

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { api } from '../../utils/api'
import { groupBrokersIntoAccounts, accountForBrokerName } from '../../utils/brokerAccounts'

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

  const accounts = useMemo(() => groupBrokersIntoAccounts(brokers), [brokers])

  // Un link viejo con `?broker=IOL · USD` sigue FUNCIONANDO (el backend lo
  // expande al mismo par), pero el nombre del sibling ya no es una opción del
  // select: sin esto el control quedaría en blanco sobre un reporte correcto.
  // Lo mapeamos al nombre del padre, que es el value que el dropdown ofrece.
  const selected = useMemo(() => {
    if (value === 'global') return 'global'
    const acc = accountForBrokerName(accounts, value)
    return acc ? acc.parent.name : value
  }, [accounts, value])

  return (
    <div className="relative inline-block">
      <select
        value={selected}
        onChange={e => onChange?.(e.target.value)}
        disabled={loading}
        className="appearance-none bg-bg-2 border border-line text-ink-1 text-sm rounded-sm px-3 py-2 pr-8 cursor-pointer hover:bg-bg-3 transition-colors disabled:opacity-50 focus:outline-none focus:border-ink-2"
      >
        <option value="global">Cartera global</option>
        {accounts.map(a => (
          // `value` = el nombre del PADRE, que es lo que el backend filtra y lo
          // que `broker_pair` expande al par entero.
          <option key={a.key} value={a.parent.name}>
            {a.label}
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
