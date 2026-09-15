// TourNovedades — el paseo que presenta la voz, el micrófono y la isla.
// ═══════════════════════════════════════════════════════════════════════════
// Oscurece la pantalla, deja iluminado lo que está explicando y pone un cartel
// al lado. "Siguiente" avanza; "Omitir" lo cierra para siempre.
//
// TRES DECISIONES QUE VALEN LA PENA CONTAR
//
// 1. SI NO ENCUENTRA QUÉ RESALTAR, SE SALTEA ESE PASO. Los blancos viven en
//    componentes que pueden tardar en aparecer (la isla se monta con la sesión,
//    el chat espera la foto de la cartera). Antes que dejar al usuario mirando
//    una pantalla oscura con un agujero en la nada, el paso se salta solo. Si
//    no queda ninguno, el tutorial no se muestra.
//
// 2. EL AGUJERO SE HACE CON UNA SOMBRA GIGANTE, no recortando una imagen. Un
//    `box-shadow` de 9999px pinta TODO lo de afuera del recuadro y deja limpio
//    lo de adentro: una sola caja, sin capas que se desalineen al hacer scroll
//    ni máscaras que cada navegador dibuja distinto.
//
// 3. EL RESALTADO NO SE PUEDE TOCAR. La tentación es dejar que el usuario
//    apriete el botón iluminado, pero entonces se va del paseo a mitad de
//    camino —abre la isla, manda una pregunta— y el tutorial queda hablando de
//    algo que ya no está en pantalla. Acá se mira; tocar viene después.
//
// La navegación entre pantallas la hace el tutorial (pedido de Nico): empieza
// donde esté el usuario, y al pasar al micrófono lo lleva él mismo a Rendi AI.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { PASOS, ATRIBUTO, yaLoVio, marcarVisto } from './pasos'

// Cuánto aire se deja alrededor de lo iluminado.
const AIRE = 8
// Cuánto se espera a que aparezca el blanco antes de darlo por perdido. La
// pantalla de Rendi AI pide la foto de la cartera antes de dibujar el chat.
const ESPERA_MAX = 2500
const REINTENTO = 120

const buscar = (marca) => document.querySelector(`[${ATRIBUTO}="${marca}"]`)

export default function TourNovedades() {
  const [activo, setActivo] = useState(false)
  const [i, setI] = useState(0)
  const [caja, setCaja] = useState(null)
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const cerradoRef = useRef(false)

  // ¿Arranca? Una sola vez por usuario, y nunca en las pantallas que piden la
  // pantalla entera (login, alta de cuenta, la primera lectura).
  useEffect(() => {
    if (cerradoRef.current) return
    if (typeof localStorage === 'undefined') return
    if (yaLoVio(localStorage)) return
    if (/^\/(login|registro|onboarding|bienvenida|claim|verify-email|reset-password)/.test(pathname)) return
    // Un respiro para que la pantalla termine de armarse antes de oscurecerla.
    const t = setTimeout(() => setActivo(true), 900)
    return () => clearTimeout(t)
  }, [pathname])

  const cerrar = useCallback(() => {
    cerradoRef.current = true
    setActivo(false)
    if (typeof localStorage !== 'undefined') marcarVisto(localStorage)
  }, [])

  const paso = activo ? PASOS[i] : null

  // Llevar al usuario a donde vive el paso.
  useEffect(() => {
    if (paso?.ruta && pathname !== paso.ruta) navigate(paso.ruta)
  }, [paso, pathname, navigate])

  // Buscar el blanco y medirlo. Si no aparece, se saltea el paso.
  useLayoutEffect(() => {
    if (!paso) return
    let vivo = true
    let esperado = 0
    const medir = () => {
      if (!vivo) return
      const el = buscar(paso.marca)
      if (el) {
        const r = el.getBoundingClientRect()
        setCaja({
          x: Math.max(0, r.left - AIRE), y: Math.max(0, r.top - AIRE),
          w: r.width + AIRE * 2, h: r.height + AIRE * 2,
        })
        return
      }
      esperado += REINTENTO
      if (esperado >= ESPERA_MAX) { setCaja(null); avanzar() }
      else setTimeout(medir, REINTENTO)
    }
    medir()
    window.addEventListener('resize', medir)
    window.addEventListener('scroll', medir, true)
    return () => {
      vivo = false
      window.removeEventListener('resize', medir)
      window.removeEventListener('scroll', medir, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso, pathname])

  function avanzar() {
    setCaja(null)
    setI((n) => {
      if (n + 1 >= PASOS.length) { cerrar(); return n }
      return n + 1
    })
  }

  if (!paso || !caja) return null

  // El cartel va del lado donde hay lugar: abajo si el blanco está arriba.
  const alto = typeof window !== 'undefined' ? window.innerHeight : 800
  const debajo = caja.y + caja.h < alto * 0.55
  const ultimo = i === PASOS.length - 1

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true"
         aria-label={`Novedades: ${paso.titulo}`}>
      {/* EL RESALTADO. La sombra gigante pinta todo lo de afuera y deja limpio
          lo de adentro. `pointer-events-none` para que el botón iluminado no se
          pueda tocar: si el usuario lo aprieta se va del paseo a mitad. */}
      <div
        className="absolute rounded-xl pointer-events-none transition-all duration-200"
        style={{
          left: caja.x, top: caja.y, width: caja.w, height: caja.h,
          boxShadow: '0 0 0 9999px rgba(0,0,0,0.72)',
          outline: '2px solid rgba(139,125,255,0.9)',
        }}
      />

      <div
        className="absolute left-3 right-3 sm:left-auto sm:right-auto sm:w-[360px] rounded-xl
                   border border-line-3 bg-bg-2 shadow-2xl p-4"
        style={debajo
          ? { top: Math.min(alto - 200, caja.y + caja.h + 12) }
          : { bottom: Math.max(12, alto - caja.y + 12) }}
      >
        <div className="text-[11px] font-semibold tracking-wide text-data-violet">
          Novedades · {i + 1} de {PASOS.length}
        </div>
        <h2 className="mt-1 text-[15.5px] font-semibold text-ink-0 leading-tight">{paso.titulo}</h2>
        <p className="mt-1.5 text-[13px] leading-snug text-ink-2">{paso.texto}</p>

        <div className="flex items-center gap-2 mt-3.5">
          <button
            type="button"
            onClick={ultimo ? cerrar : avanzar}
            className="h-11 sm:h-9 px-4 rounded-full bg-data-violet text-bg-0 text-[13px] font-semibold"
          >
            {ultimo ? 'Listo' : 'Siguiente'}
          </button>
          <button
            type="button"
            onClick={cerrar}
            className="h-11 sm:h-9 px-3 rounded-full text-[13px] text-ink-3 hover:text-ink-1 transition-colors"
          >
            Omitir
          </button>
        </div>
      </div>
    </div>
  )
}
