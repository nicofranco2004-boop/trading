// useRecalculoDeCartera — el estado del aviso "Recalculando tu cartera"
// (components/RecalculoDeCartera.jsx). Uno solo para Cartera de escritorio y de
// celular (R6), y para el Dashboard.
//
//   · `anotar(cobro, recargar)`: un cobro anotado EN esta pantalla (la bandeja de
//     dividendos, un cupón de bono). Muestra "Recalculando…" mientras `recargar`
//     viaja y la página no terminó de cargar; después, el total nuevo.
//   · Al entrar, si en Movimientos se borró algo (un depósito, un dividendo,
//     una venta), lo toma de utils/cambioDeMovimiento y muestra el recálculo
//     desde el último total que se vio EN ESTA pantalla (`pantalla`).
//   · Va recordando el total que se muestra, para la próxima vez.
//
// `listo`: la página tiene posiciones Y precios (el total que se ve es el de
// verdad). Mientras no lo esté, el aviso sigue en "Recalculando…".

import { useCallback, useEffect, useState } from 'react'
import { recordarTotalVisto, tomarCambioPendiente } from '../utils/cambioDeMovimiento'

export function useRecalculoDeCartera({ total, moneda, listo, pantalla = 'cartera' }) {
  const [cobro, setCobro] = useState(null)
  const [enCurso, setEnCurso] = useState(false)

  // Lo que quedó anotado en otra pantalla. En un efecto y no al crear el estado:
  // tomarlo lo borra, y en desarrollo React crea el estado dos veces.
  useEffect(() => {
    const p = tomarCambioPendiente(moneda, pantalla)
    if (p) setCobro({ ...p, sinAntes: p.antes == null, id: `pendiente-${Date.now()}` })
    // sólo al entrar
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const recalculando = enCurso || (!!cobro && !listo)

  useEffect(() => {
    if (listo && !recalculando) recordarTotalVisto(total, moneda, pantalla)
  }, [total, moneda, listo, recalculando, pantalla])

  const anotar = useCallback(async (info, recargar) => {
    setCobro({ ...info, id: `${Date.now()}-${Math.random()}` })
    setEnCurso(true)
    try { await recargar?.() } finally { setEnCurso(false) }
  }, [])

  return { cobro, recalculando, anotar }
}
