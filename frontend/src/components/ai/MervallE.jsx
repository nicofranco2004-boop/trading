// MervallE — el personaje de la IA de Rendi (Mervall-E AI).
// ═══════════════════════════════════════════════════════════════════════════
// Es la cara de la IA en todos los lugares donde la IA es "alguien": la
// cabecera de /ai, la portada del chat vacío (del tamaño que entra), el
// compañero al costado del cuadro de texto (compu, con conversación), el
// avatar de cada respuesta, la espera, la isla flotante, la landing y los
// accesos (barra lateral, barra del celular, Más, buscador, onboarding, guía).
// Quién se mueve en /ai lo decide mervalle/estadoDelChat.enEscena. Los botones chicos de "✦ Analizar" NO son él: son
// una función de la IA y se quedan con la estrellita.
//
// Este archivo es sólo el puente con React. El dibujo y el movimiento viven
// en mervalle/motor.js (DOM directo, un bucle para todos), la pintura en
// mervalle/mervalle.css (tokens --mv-* de index.css) y qué cara poner según
// el chat en mervalle/estadoDelChat.js.
//
// La forma sale del tamaño (`size`, ancho en px): hasta 20 el visor solo,
// hasta 48 la cabeza, hasta 110 el busto, más el cuerpo entero.
//
// Reglas de uso (propuesta aprobada 2026-10-03):
//   · Uno solo en movimiento por pantalla. Los avatares de mensajes viejos y
//     la cabecera mientras otro está en escena van `congelado`; los accesos
//     van `quieto`: no flotan, parpadean y miran al cursor SÓLO si pasa a
//     menos de 250 px (es el default de `quieto`; `radio` lo cambia).
//   · Al lado de un número, `quieto`: no flota.
//   · `tono` sólo cuando está diciendo un número con signo, y sólo se ve en
//     las formas con pecho (busto y cuerpo entero).
//
// Es decorativo (aria-hidden): el nombre "Mervall-E AI" lo dice el texto de
// al lado, que es lo que leen los lectores de pantalla.

import { useEffect, useRef } from 'react'
import { crearMervallE, formaPara, proporcion } from './mervalle/motor'
import './mervalle/mervalle.css'

/** Un acceso quieto mira al cursor sólo de cerca: con el radio infinito, en
 *  el celular cada toque en cualquier parte giraba las cabecitas. */
const RADIO_DE_ACCESO = 250

export default function MervallE({
  size = 24,
  forma,
  estado = 'reposo',
  tono = null,
  quieto = false,
  sigue = true,
  radio,
  congelado = false,
  escucha = false,
  recuadro = false,
  className = '',
}) {
  const host = useRef(null)
  const inst = useRef(null)
  const f = forma || formaPara(recuadro ? Math.round(size * 0.78) : size)

  // El personaje se crea una vez por forma. Cambiar de estado o de tono NO lo
  // recrea: se le avisa al que ya está (los efectos de abajo).
  useEffect(() => {
    const m = crearMervallE(host.current, {
      forma: f, state: estado, tone: tono, still: quieto, track: sigue,
      trackRadius: radio ?? (quieto ? RADIO_DE_ACCESO : undefined), frozen: congelado, escucha,
    })
    inst.current = m
    return () => { m.destroy(); inst.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f, quieto, sigue, radio, congelado, escucha])

  useEffect(() => { inst.current?.setState(estado) }, [estado])
  useEffect(() => { inst.current?.setTone(tono) }, [tono])

  // El lugar se reserva con la proporción de la forma, así no hay salto
  // cuando el dibujo aparece (el motor dibuja recién al montar).
  const dibujo = (
    <span
      ref={host}
      aria-hidden="true"
      className="block select-none"
      style={{ width: recuadro ? '78%' : size, aspectRatio: `1 / ${proporcion(f)}` }}
    />
  )
  // `align-middle`: un inline-flex se apoya en el renglón como una letra y deja
  // abajo el lugar de la "g" o la "p"; adentro de un botón la cara quedaba 3 px
  // corrida hacia arriba.
  if (!recuadro) return <span className={`inline-flex flex-none align-middle ${className}`} style={{ width: size }}>{dibujo}</span>
  // El recuadro lo ancla al resto de los íconos de la interfaz: el personaje
  // suelto al lado de un título se ve pegado con cinta.
  return (
    <span
      className={`inline-grid place-items-center flex-none align-middle rounded-xl bg-data-violet/10 border border-data-violet/20 ${className}`}
      style={{ width: size, height: size }}
    >
      {dibujo}
    </span>
  )
}

/**
 * Para los lugares que reciben un ícono como componente (`Icon={…}`) con el
 * tamaño de un ícono de lucide (14-18): lo dibuja un poco más grande, porque
 * una cara a 16 px no se reconoce y un ícono sí. Quieto: es un acceso, no el
 * personaje en escena. Mira al cursor sólo si pasa cerca.
 */
export function MervallEIcono({ size = 16, className = '' }) {
  return <MervallE size={Math.round(size * 1.6)} forma="head" quieto className={className} />
}
