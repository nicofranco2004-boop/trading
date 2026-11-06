// useLotesDeLaCuenta — tus lotes y tus operaciones, para decidir con LA regla de
// la ficha qué serie mira cada activo (`marcaLocal`, utils/comparadorPrecio.js:
// si lo tenés, tus lotes; si no, el ticker). Lo usan Comparar → Precio y «Una
// cartera» del Backtesting: eran dos copias del mismo pedido, y la segunda
// pantalla no lo hacía (sumaba todo como «de afuera»: GGAL con el ADR y AGRO con
// Adecoagro; auditoría de «Una cartera», 05/11, H1).
//
// La marca de un lote (`isBymaHolding`) mira la moneda de su broker: por eso se
// cargan también los brokers. Sólo para decidir la marca: nada de esto se dibuja.
// null mientras carga; si un pedido falla, ése va vacío.
import { useEffect, useState } from 'react'
import { api } from '../utils/api'
import { setBrokersRegistry } from '../utils/valuation'

export function useLotesDeLaCuenta() {
  const [lotes, setLotes] = useState(null)   // { posiciones, operaciones }
  useEffect(() => {
    let vivo = true
    Promise.all([
      api.get('/positions').catch(() => []),
      api.get('/operations').catch(() => []),
      api.get('/brokers').catch(() => []),
    ]).then(([pos, ops, bkrs]) => {
      if (!vivo) return
      setBrokersRegistry(bkrs || [])
      setLotes({ posiciones: Array.isArray(pos) ? pos : [], operaciones: Array.isArray(ops) ? ops : [] })
    })
    return () => { vivo = false }
  }, [])
  return lotes
}
