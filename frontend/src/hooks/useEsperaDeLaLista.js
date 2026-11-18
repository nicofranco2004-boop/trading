// useEsperaDeLaLista — la pantalla que tiene arriba de todo la lista de primeros
// pasos (components/home/OnboardingChecklist) no muestra su contenido hasta saber
// si la lista va o no. Con tope.
// ═══════════════════════════════════════════════════════════════════════════
// Por qué (auditoría SEO 16/11/2026, CLS de Chrome con usuarios reales): la lista
// no sabe si se muestra hasta que vuelven sus tres pedidos (/imports,
// /auth/investor-profile, /primeros-pasos), y mientras tanto no dibuja nada.
// Cuando aparecía —con 968 px de alto en el demo— empujaba TODA la pantalla hacia
// abajo, justo cuando la persona iba a tocar algo: CLS 0,77 en el inicio del
// celular y 0,31 en el de la compu, en 4 de 4 cargas. Un lugar vacío reservado
// no alcanza, porque el alto final depende de la respuesta (0 px o casi un metro).
//
// Así que la pantalla espera: muestra su esqueleto (o nada) hasta que la lista
// avisa que se decidió (`alDecidirse`). La lista tiene que estar MONTADA desde el
// principio, escondida, para que sus pedidos viajen junto con los de la pantalla
// y no recién cuando la pantalla terminó (así era en el celular: la lista vivía
// sólo en la rama «terminada», arrancaba tarde y llegaba tarde siempre).
//
// El tope y la espera en sí viven en useEsperaConTope (también los usa el
// Dashboard). `ademas`: otra pieza de arriba que la pantalla también espera —
// el fuera de horario: en el inicio del celular su primera respuesta; en el de
// la compu, la sección entera (hooks/useFueraDeHorarioDelInicio).

import { useCallback, useState } from 'react'
import { useEsperaConTope, TOPE_ESPERA_MS } from './useEsperaConTope'

export const TOPE_ESPERA_LISTA_MS = TOPE_ESPERA_MS

/**
 * @param {boolean} desde   la pantalla ya tiene sus propios datos: desde acá corre el tope
 * @param {boolean} ademas  otra pieza de arriba que también tiene que estar lista
 * @returns {{ lista: boolean, alDecidirse: Function }}
 *   `lista`: se puede mostrar el contenido (todo lo de arriba se decidió o venció el tope).
 *   `alDecidirse`: va al `onDecidida` de OnboardingChecklist.
 */
export function useEsperaDeLaLista({ desde = true, ademas = true } = {}) {
  const [decidida, setDecidida] = useState(false)
  const lista = useEsperaConTope({ desde, listo: decidida && ademas })
  const alDecidirse = useCallback(() => setDecidida(true), [])
  return { lista, alDecidirse }
}
