// useDemora — true recién cuando `activo` lleva `ms` encendido sin apagarse.
//
// Para lo que sólo tiene sentido mostrar si algo TARDA (el cargador de
// Novedades): si los datos llegan antes, no aparece nunca — un cargador que
// se prende y se apaga en un parpadeo es ruido. Se apaga junto con `activo`.

import { useEffect, useState } from 'react'
import { DEMORA_CARGADOR_MS } from '../utils/cargaPorPasos'

export function useDemora(activo, ms = DEMORA_CARGADOR_MS) {
  const [cumplida, setCumplida] = useState(false)
  useEffect(() => {
    if (!activo) { setCumplida(false); return undefined }
    const t = setTimeout(() => setCumplida(true), ms)
    return () => clearTimeout(t)
  }, [activo, ms])
  return activo && cumplida
}
