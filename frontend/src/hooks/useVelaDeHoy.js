// useVelaDeHoy — las ruedas que la noche todavía no guardó, con la de HOY
// mientras se mueve, del gráfico de la ficha (GET /tecnico/{activo}/hoy,
// tecnico.vela_de_hoy en el servidor).
//
// Las velas del gráfico se guardan una vez por noche: sin esto, con el mercado
// abierto la última vela que se ve es la de ayer. Se pide al abrir y después
// cada minuto con la pestaña a la vista (relojVisible: oculta, no pide). Un
// minuto porque el servidor guarda la vela 60 s: pedir más seguido trae lo
// mismo. Con la rueda cerrada (`en_rueda` false) se espacia a la próxima media
// hora (la regla de las secciones de mercado, msHastaProximaMediaHora): así la
// vela de mañana aparece sola con la ficha abierta de un día para el otro. Antes
// dejaba de pedir para siempre, y una respuesta sin vela antes de la apertura la
// apagaba todo el día (auditoría 30/10).
//
// Devuelve null o { velas, base, enRueda, mercado, contra } donde cada vela es
// { d, o, h, l, c, v, vivo: true, hoy, enCurso, actualizada, demora }:
//   · `hoy`: es la rueda de hoy; las otras son días cerrados sin guardar todavía;
//   · `enCurso`: es la de hoy y la rueda sigue mandando precios (con su demora);
//   · `demora`: minutos que tardan en llegar los precios de esa bolsa (BYMA, 20);
//   · `base`: la vela guardada que siguen (el gráfico las dibuja sólo si es la suya);
//   · `mercado`: 'us', 'byma' o 'cripto';
//   · `contra`: qué lectura de las tarjetas da vuelta lo que todavía no se guardó, en curso o ya cerrado
//     (`contra_el_cierre`, tecnico.hoy_contra_el_cierre; utils/tecnico.js
//     `avisosDeHoy` lo pone en palabras).
// Un pedido que falla, o que con la rueda abierta vuelve sin velas (Yahoo no
// contestó), deja las últimas que llegaron: no borra lo que se ve.

import { useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'
import { MARGEN_APERTURA_MS, msHastaProximaMediaHora, relojVisible } from '../utils/relojVisible'

export const VELA_DE_HOY_MS = 60 * 1000

export function useVelaDeHoy(asset, moneda, local, activo = true) {
  const clave = `${asset}|${moneda}|${local ? 1 : 0}`
  const [estado, setEstado] = useState(null)
  const proximo = useRef(0)
  useEffect(() => {
    proximo.current = 0
    if (!activo || !asset) return undefined
    let vivo = true
    const pedir = () => {
      if (Date.now() < proximo.current) return
      api.get(`/tecnico/${encodeURIComponent(asset)}/hoy?moneda=${moneda}${local ? '&local=1' : ''}`)
        .then(r => {
          if (!vivo || !r) return
          const enRueda = !!r.en_rueda
          proximo.current = enRueda ? 0 : Date.now() + msHastaProximaMediaHora() + MARGEN_APERTURA_MS
          const velas = (r.velas || []).map(x => ({
            ...x, vivo: true, hoy: !!x.hoy, enCurso: !!x.hoy && enRueda,
            actualizada: r.actualizada || null, demora: r.demora_min || 0,
          }))
          setEstado(prev => (!velas.length && enRueda && prev?.clave === clave
            ? { ...prev, enRueda }
            : { clave, velas, base: r.ultima_guardada || null, enRueda, mercado: r.mercado || null,
                contra: r.contra_el_cierre || [] }))
        })
        .catch(() => {})
    }
    pedir()
    const apagar = relojVisible(pedir, VELA_DE_HOY_MS)
    return () => { vivo = false; apagar() }
  }, [asset, moneda, local, activo, clave])
  // La de otra moneda u otro activo (el pedido nuevo todavía no volvió) no se
  // dibuja ni un instante: estaría en otra escala.
  return estado?.clave === clave && estado.velas.length ? estado : null
}
