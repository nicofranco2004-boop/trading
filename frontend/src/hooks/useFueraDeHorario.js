// useFueraDeHorario — pide el pre/post mercado (GET /fuera-de-horario) para
// estos símbolos de EE.UU. y lo repide cada minuto mientras la pestaña se vea.
//
// `simbolos` sale de utils/fueraDeHorario `simbolosFueraDeHorario` (cada CEDEAR
// ya traducido a su acción de EE.UU., cada acción argentina a su ADR). Sin
// símbolos y sin `listas` no se pide nada: no hay qué mostrar.
//
// Si un refresco falla se QUEDAN los datos que había: un corte de red de un
// segundo no puede hacer desaparecer el chip.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../utils/api'
import { useRelojVisible } from './useRelojVisible'
import { FUERA_DE_HORARIO_MS } from '../utils/fueraDeHorario'

export function useFueraDeHorario(simbolos = [], { listas = false } = {}) {
  const [datos, setDatos] = useState(null)
  const clave = simbolos.join(',')

  const pedir = useCallback(async () => {
    if (!clave && !listas) { setDatos(null); return }
    try {
      const q = new URLSearchParams()
      if (clave) q.set('symbols', clave)
      if (listas) q.set('listas', '1')
      setDatos(await api.get(`/fuera-de-horario?${q.toString()}`))
    } catch {
      // se quedan los que había
    }
  }, [clave, listas])

  useEffect(() => { pedir() }, [pedir])
  useRelojVisible(pedir, FUERA_DE_HORARIO_MS)
  return datos
}
