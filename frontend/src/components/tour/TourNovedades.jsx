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
import { useVoz } from '../../contexts/VozContext'

// Cuánto aire se deja alrededor de lo iluminado.
const AIRE = 8
// Cuánto se espera a que aparezca el blanco antes de darlo por perdido. La
// pantalla de Rendi AI pide la foto de la cartera antes de dibujar el chat.
const ESPERA_MAX = 2500
const REINTENTO = 120
// Lo que mide el cartel en pantalla grande.
const ANCHO_CARTEL = 360

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

  // El asesor en su propio nivel ve EL MISMO tutorial; sólo cambia el texto de
  // los pasos donde lo que puede hacer es otra cosa (ver `libro` en pasos.js).
  const { modoLibro } = useVoz()
  const crudo = activo ? PASOS[i] : null
  const paso = crudo && modoLibro && crudo.libro ? { ...crudo, ...crudo.libro } : crudo

  // Llevar al usuario a donde vive el paso.
  useEffect(() => {
    if (paso?.ruta && pathname !== paso.ruta) navigate(paso.ruta)
  }, [paso, pathname, navigate])

  // Buscar el blanco y SEGUIRLO. Si no aparece, se saltea el paso.
  //
  // 🔴 ANTES ESTO MEDÍA UNA VEZ y escuchaba `resize` y `scroll`. Falla, y se vio
  // en la pantalla de Nico: el paso de "Nueva alerta" iluminaba un rectángulo
  // vacío a 160px del botón. Medido al achicar la ventana a 1000x560 — con el
  // botón en x=845, el recuadro se quedó en x=677 y el evento de resize no lo
  // corrigió.
  //
  // El problema de fondo no es ese listener puntual: es que escuchar eventos
  // obliga a ACERTAR POR QUÉ SE MOVIÓ. Y el blanco se mueve por cosas que no
  // emiten ni `resize` ni `scroll`: una tarjeta de arriba que se abre o se
  // cierra, contenido que llega del servidor y empuja la lista, el sidebar que
  // colapsa, una tipografía que termina de cargar. Cada causa nueva es otro
  // listener que alguien se va a olvidar de agregar.
  //
  // Así que no se escucha nada: se MIRA. Un chequeo por frame mientras el paso
  // está activo, que sólo toca el estado si la posición cambió de verdad. Es
  // barato (una lectura de geometría por frame, y el tutorial dura segundos) y
  // no hay forma de que el blanco se mueva sin que lo siga.
  useLayoutEffect(() => {
    if (!paso) return
    let vivo = true
    let esperado = 0
    let pedido = 0
    let ultima = null

    const iguales = (a, b) => a && b
      && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5
      && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5

    const mirar = () => {
      if (!vivo) return
      const el = buscar(paso.marca)
      if (el) {
        const r = el.getBoundingClientRect()
        const nueva = {
          x: Math.max(0, r.left - AIRE), y: Math.max(0, r.top - AIRE),
          w: r.width + AIRE * 2, h: r.height + AIRE * 2,
        }
        // Sólo se re-renderiza cuando de verdad se movió.
        if (!iguales(nueva, ultima)) { ultima = nueva; setCaja(nueva) }
        pedido = requestAnimationFrame(mirar)
        return
      }
      esperado += REINTENTO
      if (esperado >= ESPERA_MAX) { setCaja(null); avanzar() }
      else setTimeout(mirar, REINTENTO)
    }
    mirar()
    return () => { vivo = false; cancelAnimationFrame(pedido) }
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
  const ancho = typeof window !== 'undefined' ? window.innerWidth : 1200
  const debajo = caja.y + caja.h < alto * 0.55
  const ultimo = i === PASOS.length - 1
  // Dónde va el cartel a lo ancho. En el celular ocupa todo lo que hay; en
  // pantalla grande se centra debajo de lo resaltado, sin pasarse de los bordes.
  const cartel = ancho < 640
    ? { left: 12, right: 12 }
    : { width: ANCHO_CARTEL,
        left: Math.min(Math.max(12, caja.x + caja.w / 2 - ANCHO_CARTEL / 2),
                       ancho - ANCHO_CARTEL - 12) }

  // LA PUNTA, y por qué hace falta. Centrar el cartel bajo lo resaltado sólo
  // funciona cuando hay lugar: si lo resaltado está pegado a un borde —el
  // interruptor del resumen del mercado vive en el extremo derecho— centrarlo
  // lo dejaría fuera de la pantalla, así que el recorte de arriba lo empuja
  // hacia adentro. Medido: el cartel terminaba 131px a la izquierda del
  // interruptor, y se leía como un cartel suelto que no apunta a nada.
  // Moverlo no es opción (no hay lugar); lo que faltaba era CONECTARLO.
  // La punta se clava en el centro de lo resaltado y se limita para no salirse
  // por las esquinas redondeadas del propio cartel.
  const cartelIzq = ancho < 640 ? 12 : cartel.left
  const cartelAncho = ancho < 640 ? ancho - 24 : ANCHO_CARTEL
  const puntaX = Math.min(Math.max(20, caja.x + caja.w / 2 - cartelIzq - 6),
                          cartelAncho - 32)

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
          outline: '2px solid rgb(var(--data-violet) / 0.9)',
        }}
      />

      {/* 🔴 EL CARTEL VA AL LADO DE LO QUE EXPLICA. Parece obvio y salió mal:
          en pantalla grande no le puse posición horizontal, así que se pegaba
          al borde izquierdo mientras lo resaltado estaba a la derecha. Visto
          en la pantalla de Nico: la burbuja iluminada arriba a la derecha y el
          cartel allá lejos, sin forma de saber de qué hablaba.
          Ahora se centra bajo lo resaltado y se recorta contra los bordes. En
          el celular ocupa el ancho, que es lo único que entra. Y cuando el
          recorte lo corre —lo resaltado pegado a un borde—, LA PUNTA de abajo
          mantiene la conexión: ver el comentario de `puntaX`. */}
      <div
        className="absolute rounded-xl border border-line-3 bg-bg-raised shadow-2xl p-4"
        style={{ ...cartel, ...(debajo
          ? { top: Math.min(alto - 210, caja.y + caja.h + 12) }
          : { bottom: Math.max(12, alto - caja.y + 12) }) }}
      >
        {/* La punta que apunta a lo resaltado. Es un cuadrado girado 45° con el
            mismo fondo y borde que el cartel: se ve como un triángulo pegado al
            borde, y las dos caras que quedan adentro las tapa el cartel. */}
        <div
          aria-hidden="true"
          className="absolute w-3 h-3 bg-bg-2 border-line-3 rotate-45"
          style={{ left: puntaX, ...(debajo
            ? { top: -7, borderLeftWidth: 1, borderTopWidth: 1 }
            : { bottom: -7, borderRightWidth: 1, borderBottomWidth: 1 }) }}
        />
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
