// useFueraDeHorario — pide el pre/post mercado (GET /fuera-de-horario) para
// estos símbolos de EE.UU. y lo repide cada minuto mientras la pestaña se vea.
//
// `simbolos` sale de utils/fueraDeHorario `simbolosFueraDeHorario` (cada CEDEAR
// ya traducido a su acción de EE.UU., cada acción argentina a su ADR). Sin
// símbolos y sin `listas` no se pide nada: no hay qué mostrar. Las pantallas
// con cartera usan `useFueraDeHorarioDe(positions, brokers)`, que arma los dos
// pedidos (símbolos y `byma`) de una.
//
// Si un refresco falla se QUEDAN los datos que había: un corte de red de un
// segundo no puede hacer desaparecer el chip.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { useRelojVisible } from './useRelojVisible'
import { FUERA_DE_HORARIO_MS, simbolosFueraDeHorario, simbolosDesdeByma } from '../utils/fueraDeHorario'

/** La dirección del pedido, o null si no hay nada que pedir. `byma`: cuáles
 *  de `simbolos` siguen a un CEDEAR o a una acción argentina
 *  (`simbolosDesdeByma`); el servidor les manda también el % desde el cierre
 *  de BYMA. */
export function urlFueraDeHorario(simbolos = [], { listas = false, byma = [] } = {}) {
  if (!simbolos.length && !listas) return null
  const q = new URLSearchParams()
  if (simbolos.length) q.set('symbols', simbolos.join(','))
  if (byma.length) q.set('byma', byma.join(','))
  if (listas) q.set('listas', '1')
  return `/fuera-de-horario?${q.toString()}`
}

/**
 * Lo mismo que `useFueraDeHorario`, y además `respondio`: ya volvió (o falló)
 * el pedido de la dirección de AHORA. Una pantalla que muestra el fuera de
 * horario ARRIBA lo espera antes de dibujarse (con tope: hooks/useEsperaConTope):
 * si se dibujaba antes, el chip y la sección aparecían después y empujaban todo
 * (CLS 0,36 en el inicio del celular, 0,175 en el Dashboard, 17/11/2026). Y eso
 * pasa casi todo el día: hay sesión en pre, en post y en «post cerrado» (de las
 * 22 hasta el pre siguiente, y el fin de semana); sólo en la rueda no hay nada.
 * Sin nada que pedir (`url` null), `respondio` es true: no hay qué esperar.
 */
export function useFueraDeHorarioConEstado(simbolos = [], { listas = false, byma = [] } = {}) {
  const [datos, setDatos] = useState(null)
  // La dirección de la última respuesta (o falla). Comparar con la de ahora,
  // y no un «ya contestó alguna vez»: cuando llega la cartera la dirección
  // cambia (suma los símbolos), y la respuesta vieja no trae lo tuyo.
  const [respondida, setRespondida] = useState(null)
  const url = urlFueraDeHorario(simbolos, { listas, byma })

  const pedir = useCallback(async () => {
    if (!url) { setDatos(null); return }
    try {
      setDatos(await api.get(url))
    } catch {
      // se quedan los que había
    } finally {
      setRespondida(url)
    }
  }, [url])

  useEffect(() => { pedir() }, [pedir])
  useRelojVisible(pedir, FUERA_DE_HORARIO_MS)
  return { datos, respondio: !url || respondida === url }
}

export function useFueraDeHorario(simbolos = [], opciones = {}) {
  return useFueraDeHorarioConEstado(simbolos, opciones).datos
}

/** El pre/post de estas tenencias: los símbolos de EE.UU. que siguen y cuáles
 *  se miden desde el cierre de BYMA. Lo usan todas las pantallas con cartera. */
export function useFueraDeHorarioDeConEstado(positions, brokers, { listas = false } = {}) {
  const simbolos = useMemo(() => simbolosFueraDeHorario(positions || [], brokers || []), [positions, brokers])
  const byma = useMemo(() => simbolosDesdeByma(positions || [], brokers || []), [positions, brokers])
  return useFueraDeHorarioConEstado(simbolos, { listas, byma })
}

export function useFueraDeHorarioDe(positions, brokers, opciones = {}) {
  return useFueraDeHorarioDeConEstado(positions, brokers, opciones).datos
}
