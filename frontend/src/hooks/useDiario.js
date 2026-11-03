// useDiario — lo que el diario de Movimientos le pide al servidor además de
// las operaciones: la tendencia del día de cada compra (/api/tecnico/en-fechas)
// y tus tesis (/api/tesis). Lo llama UNA vez Operations.jsx (el dueño de los
// datos de la pantalla) y lo pasa por prop a la tabla y a las tarjetas: nunca
// por fila.
//
// Si un pedido falla (o es el demo, que no los simula), el diario sigue sin esa
// parte: sin tendencias la columna dice «sin dato»; sin tesis, «—». La pantalla
// de operaciones no se cae por esto.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { pedidosDeTendencia } from '../utils/diarioOperaciones'

export function useTesis() {
  const [tesis, setTesis] = useState({ items: [], hoy: {} })
  const [estado, setEstado] = useState('cargando')   // 'cargando' | 'listo' | 'error'
  const recargar = useCallback(async () => {
    try {
      const r = await api.get('/tesis')
      setTesis({ items: r?.items || [], hoy: r?.hoy || {} })
      setEstado('listo')
    } catch {
      setEstado(e => (e === 'listo' ? e : 'error'))
    }
  }, [])
  useEffect(() => { recargar() }, [recargar])
  return { ...tesis, estado, recargar }
}

export function useDiario(ops) {
  const pedidos = useMemo(() => pedidosDeTendencia(ops), [ops])
  // La clave de lo pedido: recargar la lista sin cambios no vuelve a pedir.
  const clave = useMemo(() => pedidos.map(p => `${p.id}|${p.asset}|${p.local ? 1 : 0}|${p.fecha}`).join(','), [pedidos])
  const [tendencias, setTendencias] = useState({})
  const [estadoTendencias, setEstadoTendencias] = useState('cargando')
  useEffect(() => {
    if (!pedidos.length) { setTendencias({}); setEstadoTendencias('listo'); return }
    let vivo = true
    setEstadoTendencias('cargando')
    api.post('/tecnico/en-fechas', { items: pedidos })
      .then(r => { if (vivo) { setTendencias(r?.resultados || {}); setEstadoTendencias('listo') } })
      .catch(() => { if (vivo) setEstadoTendencias('error') })
    return () => { vivo = false }
  }, [clave]) // eslint-disable-line react-hooks/exhaustive-deps
  const tesis = useTesis()
  return { tendencias, estadoTendencias, tesis }
}
