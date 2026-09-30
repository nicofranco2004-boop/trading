// useRelojVisible — relojVisible (utils/relojVisible.js) atado a la vida de un
// componente: arranca al montar, se apaga al desmontar. `fn` puede cambiar
// entre renders sin reiniciar el reloj.

import { useEffect, useRef } from 'react'
import { relojVisible } from '../utils/relojVisible'

export function useRelojVisible(fn, ms) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => relojVisible(() => fnRef.current(), ms), [ms])
}
