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
// El tope: si la lista no contesta en TOPE_ESPERA_LISTA_MS desde que la pantalla
// tiene lo suyo (`desde`), la pantalla se muestra igual. Una lista trabada no
// puede dejar a nadie mirando un esqueleto; en ese caso raro la lista vuelve a
// aparecer tarde, que es lo que pasaba siempre antes.

import { useCallback, useEffect, useState } from 'react'

export const TOPE_ESPERA_LISTA_MS = 1500

/**
 * @param {boolean} desde  la pantalla ya tiene sus propios datos: desde acá corre el tope
 * @returns {{ lista: boolean, alDecidirse: Function }}
 *   `lista`: se puede mostrar el contenido (la lista se decidió o venció el tope).
 *   `alDecidirse`: va al `onDecidida` de OnboardingChecklist.
 */
export function useEsperaDeLaLista({ desde = true } = {}) {
  const [decidida, setDecidida] = useState(false)
  const [vencida, setVencida] = useState(false)

  useEffect(() => {
    if (!desde || decidida) return undefined
    const t = setTimeout(() => setVencida(true), TOPE_ESPERA_LISTA_MS)
    return () => clearTimeout(t)
  }, [desde, decidida])

  const alDecidirse = useCallback(() => setDecidida(true), [])
  return { lista: decidida || vencida, alDecidirse }
}
