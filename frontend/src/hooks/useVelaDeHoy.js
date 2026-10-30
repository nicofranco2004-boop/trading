// useVelaDeHoy — la vela de HOY del gráfico de la ficha mientras la rueda se
// mueve (GET /tecnico/{activo}/hoy, tecnico.vela_de_hoy en el servidor).
//
// Las velas del gráfico se guardan una vez por noche: sin esto, con el mercado
// abierto la última vela que se ve es la de ayer. Se pide al abrir y después
// cada minuto con la pestaña a la vista (relojVisible: oculta, no pide). Un
// minuto porque el servidor guarda la vela 60 s: pedir más seguido trae lo
// mismo. Con la rueda cerrada (`en_rueda` false) no se vuelve a pedir: la vela
// de hoy ya no cambia hasta que la guarde la corrida de la noche.
//
// Devuelve { d, o, h, l, c, v, hoy: true, enCurso, actualizada, demora } o null.
// `enCurso`: la rueda sigue abierta (contando la demora de sus precios) y la
// vela se mueve; cerrada, es la de hoy completa que todavía no se guardó.
// `demora`: minutos que tardan en llegar los precios de esa bolsa (BYMA, 20). Un pedido que falla deja la última que
// llegó: no borra lo que se ve.

import { useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'
import { relojVisible } from '../utils/relojVisible'

export const VELA_DE_HOY_MS = 60 * 1000

export function useVelaDeHoy(asset, moneda, local, activo = true) {
  const [vela, setVela] = useState(null)
  const enRueda = useRef(true)
  useEffect(() => {
    setVela(null)
    enRueda.current = true
    if (!activo || !asset) return undefined
    let vivo = true
    const pedir = () => {
      if (!enRueda.current) return
      api.get(`/tecnico/${encodeURIComponent(asset)}/hoy?moneda=${moneda}${local ? '&local=1' : ''}`)
        .then(r => {
          if (!vivo) return
          enRueda.current = !!r?.en_rueda
          setVela(r?.vela ? { ...r.vela, hoy: true, enCurso: !!r.en_rueda, actualizada: r.actualizada || null,
            demora: r.demora_min || 0 } : null)
        })
        .catch(() => {})
    }
    pedir()
    const apagar = relojVisible(pedir, VELA_DE_HOY_MS)
    return () => { vivo = false; apagar() }
  }, [asset, moneda, local, activo])
  return vela
}
