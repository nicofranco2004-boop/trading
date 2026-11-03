// Tour — el paseo guiado: oscurece la pantalla, deja iluminado lo que está
// explicando y pone un cartel al lado. "Siguiente" avanza; "Omitir" lo cierra
// para siempre.
// ═══════════════════════════════════════════════════════════════════════════
// Es UN mecanismo para todos los tutoriales; cada uno es una lista de pasos y
// su propia entrada de «ya lo vio» en utils/catalogoDelAlmacen.js:
//   · TourNovedades.jsx — la voz, el micrófono, la isla, Alertas y el tema;
//   · TourTecnico.jsx   — qué te dice cada pestaña de Análisis técnico.
// Nunca dos a la vez: el que arranca toma el turno (recorrido.js) y el otro espera.
//
// CUATRO DECISIONES QUE VALEN LA PENA CONTAR
//
// 1. SI NO ENCUENTRA QUÉ RESALTAR, SE SALTEA ESE PASO. Los blancos viven en
//    componentes que pueden tardar en aparecer (la isla se monta con la sesión,
//    el chat espera la foto de la cartera, el gráfico espera sus precios).
//    Antes que dejar al usuario mirando una pantalla oscura con un agujero en
//    la nada, el paso se salta solo. Si no queda ninguno, el tutorial no se
//    muestra. Un blanco que ESTÁ pero no se ve (el «Pronto» de Análisis
//    técnico, que en el celular no va) se saltea enseguida: no va a aparecer.
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
// 4. SI EL USUARIO SE VA DE DONDE VIVE EL TUTORIAL (`cuando`: el de Análisis
//    técnico vive en /analisis-tecnico; el de novedades, en casi toda la app),
//    se cierra sin darlo por visto: no lo terminó ni lo omitió, así que vuelve
//    a aparecer la próxima vez. Y no lo trae de vuelta: la revisión del 02/11
//    encontró que el «atrás» lo cerraba y, en el mismo instante, el paso lo
//    mandaba otra vez a la pantalla, donde el tutorial arrancaba de cero — el
//    «atrás» no servía. Dentro de donde vive, sí lo lleva de pantalla en
//    pantalla: el de novedades, del micrófono a Alertas.
//
// La navegación entre pantallas y pestañas la hace el tutorial (pedido de
// Nico): al pasar al micrófono lo lleva él mismo a Mervall-E AI, y en Análisis
// técnico cambia de pestaña solo (?tab=…).

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ATRIBUTO, yaLoVio, marcarVisto, destino, turnoLibre, tomarTurno, soltarTurno, hayPedido, tomarPedido,
  escucharTurno, presentarse,
} from './recorrido'
import { hay, almacenDe } from '../../utils/almacen'
import { useVoz } from '../../contexts/VozContext'

// Cuánto aire se deja alrededor de lo iluminado.
const AIRE = 8
// Cuánto se espera a que aparezca el blanco antes de darlo por perdido, si el
// tutorial no dice otra cosa (`espera`). La pantalla de Mervall-E AI pide la
// foto de la cartera antes de dibujar el chat.
const ESPERA_MAX = 2500
// Un blanco que está pero no se ve: un respiro por si está terminando de
// acomodarse, y se saltea.
const ESPERA_OCULTO = 400
const REINTENTO = 120
// Lo que mide el cartel en pantalla grande.
const ANCHO_CARTEL = 360
// Lo que se supone que mide de alto hasta poder medirlo (ver `altoCartel`).
const ALTO_CARTEL = 210

/** El primer elemento con la marca que SE VE; 'oculto' si los hay pero
 *  ninguno se ve (display:none, como el «Pronto» en el celular); null si no hay.
 *  El interruptor del tema tiene dos (menú lateral y «Más»): el que se ve. */
function buscar(marca) {
  const todos = document.querySelectorAll(`[${ATRIBUTO}="${marca}"]`)
  for (const el of todos) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) return { el, r }
  }
  return todos.length ? 'oculto' : null
}

/**
 * `id`: el nombre del tutorial (para el turno y para abrirlo a mano con
 * `pedirTour(id)`). `pasos`: la lista. `entrada`: la del catálogo del almacén
 * donde se guarda que ya lo vio. `etiqueta`: lo que dice arriba del cartel.
 * `cuando(pathname)`: dónde puede mostrarse. `despuesDe`: entradas de otros
 * tutoriales que tienen que estar vistos antes de que este arranque solo.
 * `espera`: cuánto esperar a que aparezca cada blanco.
 */
export default function Tour({ id, pasos, entrada, etiqueta, cuando, despuesDe = [], espera = ESPERA_MAX }) {
  const [activo, setActivo] = useState(false)
  const [i, setI] = useState(0)
  const [caja, setCaja] = useState(null)
  // Cambia cada vez que se suelta el turno o alguien pide un tutorial a mano:
  // es lo que hace que el que esperaba vuelva a mirar si puede arrancar.
  const [vuelta, setVuelta] = useState(0)
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const cerradoRef = useRef(false)
  const cartelRef = useRef(null)
  const [altoCartel, setAltoCartel] = useState(ALTO_CARTEL)

  useEffect(() => escucharTurno(() => setVuelta(v => v + 1)), [])
  // Estar montado es lo que permite pedirlo a mano (ver `presentarse`).
  useEffect(() => presentarse(id), [id])
  // Si la pantalla que lo tiene se desarma a mitad de camino, que no se quede
  // con el turno y deje esperando al otro para siempre.
  useEffect(() => () => soltarTurno(id), [id])

  // ¿Arranca solo? Una sola vez por navegador, donde el tutorial dice, nunca
  // antes que los que tienen que ir primero ni encima de otro.
  useEffect(() => {
    if (activo || cerradoRef.current) return
    if (!hay()) return
    if (!cuando(pathname)) return
    if (yaLoVio(almacenDe(entrada), entrada.clave)) return
    if (despuesDe.some(e => !yaLoVio(almacenDe(e), e.clave))) return
    if (!turnoLibre(id)) return
    // Un respiro para que la pantalla termine de armarse antes de oscurecerla.
    const t = setTimeout(() => { if (tomarTurno(id)) setActivo(true) }, 900)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, vuelta, activo])

  // ¿Lo pidieron a mano? Arranca desde el primer paso, aunque ya lo haya visto.
  // Si otro tiene el turno (esperando que aparezca su primer blanco), el pedido
  // queda hasta que lo suelte; si la persona ya se fue de donde vive, se tira.
  useEffect(() => {
    if (!hayPedido(id)) return
    if (!cuando(pathname)) { tomarPedido(id); return }
    if (!tomarTurno(id)) return
    tomarPedido(id)
    cerradoRef.current = false
    setCaja(null)
    setI(0)
    setActivo(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vuelta, id, pathname])

  const cerrar = useCallback(() => {
    cerradoRef.current = true
    setActivo(false)
    setCaja(null)
    if (hay()) marcarVisto(almacenDe(entrada), entrada.clave)
    soltarTurno(id)
  }, [entrada, id])

  // Se fue de donde vive el tutorial: se cierra sin darlo por visto (ver 4).
  useEffect(() => {
    if (!activo || cuando(pathname)) return
    setActivo(false)
    setCaja(null)
    setI(0)
    soltarTurno(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activo, pathname])

  // El asesor en su propio nivel ve EL MISMO tutorial; sólo cambia el texto de
  // los pasos donde lo que puede hacer es otra cosa (ver `libro` en pasos.js).
  // Memorizado: un objeto nuevo en cada dibujo reiniciaba el seguimiento del
  // blanco (que depende de `paso`) en cada dibujo.
  const { modoLibro } = useVoz()
  const crudo = activo ? pasos[i] : null
  const paso = useMemo(
    () => (crudo && modoLibro && crudo.libro ? { ...crudo, ...crudo.libro } : crudo),
    [crudo, modoLibro])

  // Llevar al usuario a donde vive el paso (la ruta y, si hace falta, la
  // pestaña: ver `destino` en recorrido.js). Dentro de la misma pantalla reemplaza
  // la dirección en vez de sumar un paso al «atrás» por cada pestaña.
  // Sólo dentro de donde vive el tutorial: si se fue (el «atrás»), el efecto de
  // arriba lo cierra y éste no lo tiene que traer de vuelta (ver 4).
  useEffect(() => {
    if (!cuando(pathname)) return
    const d = destino(paso, pathname, search)
    if (d) navigate(d, { replace: pathname === paso.ruta })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso, pathname, search, navigate])

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
    let oculto = 0
    let pedido = 0
    let ultima = null
    let acomodado = false

    const iguales = (a, b) => a && b
      && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5
      && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5

    const mirar = () => {
      if (!vivo) return
      const hallado = buscar(paso.marca)
      if (hallado && hallado !== 'oculto') {
        // La primera vez, que se vea: en el celular las pestañas se deslizan de
        // costado y «Comparar» puede estar afuera de la pantalla.
        if (!acomodado) {
          acomodado = true
          hallado.el.scrollIntoView?.({ block: 'nearest', inline: 'center' })
        }
        const r = hallado.el.getBoundingClientRect()
        const nueva = {
          x: Math.max(0, r.left - AIRE), y: Math.max(0, r.top - AIRE),
          w: r.width + AIRE * 2, h: r.height + AIRE * 2,
        }
        // Sólo se re-renderiza cuando de verdad se movió.
        if (!iguales(nueva, ultima)) { ultima = nueva; setCaja(nueva) }
        pedido = requestAnimationFrame(mirar)
        return
      }
      if (hallado === 'oculto') oculto += REINTENTO
      esperado += REINTENTO
      if (oculto >= ESPERA_OCULTO) { setCaja(null); avanzar() }
      else if (esperado >= espera) { setCaja(null); avanzar({ conSuGrupo: true }) }
      else setTimeout(mirar, REINTENTO)
    }
    mirar()
    return () => { vivo = false; cancelAnimationFrame(pedido) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paso, pathname])

  // `conSuGrupo`: el blanco nunca apareció, y los pasos siguientes de su mismo
  // `grupo` viven en lo mismo (los botones del gráfico, cuando el activo no
  // tiene gráfico o el demo no trae precios): se saltean juntos en vez de
  // esperar uno por uno con la pantalla sin cartel.
  //
  // Se calcula con el `i` de este dibujo y NO dentro de `setI(n => …)`: cerrar
  // desde ahí adentro avisaba al otro tutorial en el medio de un cálculo de
  // React («Cannot update a component while rendering…»). El `i` está al día:
  // el seguimiento del blanco se vuelve a armar con cada paso.
  function avanzar({ conSuGrupo = false } = {}) {
    setCaja(null)
    let sig = i + 1
    const grupo = pasos[i]?.grupo
    if (conSuGrupo && grupo) while (sig < pasos.length && pasos[sig].grupo === grupo) sig += 1
    if (sig >= pasos.length) cerrar()
    else setI(sig)
  }

  // Lo que de verdad mide el cartel, para que abajo no se salga de la pantalla:
  // con un texto largo y el celular acostado, «Siguiente» quedaba afuera.
  useLayoutEffect(() => {
    const h = cartelRef.current?.offsetHeight
    if (h && Math.abs(h - altoCartel) > 1) setAltoCartel(h)
  })

  if (!paso || !caja) return null

  // El cartel va del lado donde hay lugar: abajo si el blanco está arriba.
  const alto = typeof window !== 'undefined' ? window.innerHeight : 800
  const ancho = typeof window !== 'undefined' ? window.innerWidth : 1200
  const debajo = caja.y + caja.h < alto * 0.55
  const ultimo = i === pasos.length - 1
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
         aria-label={`${etiqueta}: ${paso.titulo}`}>
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
        ref={cartelRef}
        className="absolute rounded-xl border border-line-3 bg-bg-raised shadow-2xl p-4"
        style={{ ...cartel, ...(debajo
          ? { top: Math.max(12, Math.min(alto - altoCartel - 12, caja.y + caja.h + 12)) }
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
          {etiqueta} · {i + 1} de {pasos.length}
        </div>
        <h2 className="mt-1 text-[15.5px] font-semibold text-ink-0 leading-tight">{paso.titulo}</h2>
        <p className="mt-1.5 text-[13px] leading-snug text-ink-2">{paso.texto}</p>

        <div className="flex items-center gap-2 mt-3.5">
          <button
            type="button"
            onClick={ultimo ? cerrar : () => avanzar()}
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
