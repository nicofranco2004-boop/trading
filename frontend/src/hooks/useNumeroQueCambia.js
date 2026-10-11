// useNumeroQueCambia — una métrica que muestra CÓMO CAMBIÓ después de que el
// usuario hizo algo (cobró, vendió, depositó, borró). Pedido de Nico, 2026-10-10.
//
// Qué hace:
//   · Al aparecer: si la cartera cambió desde la última vez que este número se
//     vio (utils/valoresVistos) y el valor es otro, arranca en el valor VIEJO
//     y, cuando entra en pantalla (useAlVerse) y los datos están listos, cuenta
//     hasta el nuevo. Devuelve `cambio` (la diferencia) durante unos segundos y
//     `destello` ('up' | 'down') para pintarlo.
//   · Mientras está a la vista: si el valor cambia justo después de una
//     escritura (el usuario hizo algo en ESTA pantalla), lo mismo. Si cambia
//     solo —los precios, cada 90 s— cuenta y destella como cualquier número
//     vivo de la app, pero sin la etiqueta de la diferencia: eso no es "tu
//     cambio".
//   · Si no hubo ningún cambio del usuario, se ve como siempre.
//
// La cuenta es la de useCountUp (una sola en la app): de ahí salen la garantía
// de llegada —el número TERMINA en su valor aunque la pestaña esté de fondo— y
// el respeto por "reducir movimiento".
//
// `listo`: el valor ya es el de verdad (llegaron posiciones y precios). Antes
// de eso no se anuncia ni se recuerda nada: se recordaría un total a medias.
// `desdeCero`: sin cambio pendiente, la primera vez cuenta desde 0 (los números
// que ya lo hacían: el total, los de Movimientos). Sin esto, aparece escrito.

import { useEffect, useRef, useState } from 'react'
import { useAlVerse } from './useAlVerse'
import { useCountUp } from './useCountUp'
import { EVENTO_ESCRITURA } from '../utils/api'
import { recordarValor, valorAntesDelCambio } from '../utils/valoresVistos'

const DURA_MS = 900
const CAMBIO_VISIBLE_MS = 6000
// Un cambio "en esta pantalla" es el que llega poco después de una escritura.
const VENTANA_TRAS_ESCRIBIR_MS = 20000
// Tope de espera en el valor viejo si los datos no terminan de llegar: un
// número de plata no se queda mostrando lo de antes para siempre.
const ESPERA_MAX_MS = 12000
// Apenas asoma: con el margen de las entradas animadas (15 % y −40 px) un
// número al pie de la pantalla se leía en su valor VIEJO sin empezar a contar.
const AL_VERSE = { threshold: 0.01, rootMargin: '0px' }

// `format` (opcional): cómo se escribe el número. Con él, un cambio se anuncia
// sólo si SE VE: visto en la app el 2026-10-10, en Movimientos (montos sin
// centavos) borrar un dividendo con US$ 0,01 de cargo anunciaba "−US$0
// respecto de antes" en Comisiones.
export function useNumeroQueCambia({ clave, value, moneda = 'USD', listo = true, umbral = 0.005, desdeCero = false, format }) {
  const valido = Number.isFinite(value)
  const [refVisto, visto] = useAlVerse(AL_VERSE)
  // El valor viejo, leído en el PRIMER dibujo: así el número no arranca en el
  // nuevo para saltar al viejo y recién después contar.
  const [pendiente, setPendiente] = useState(() => (clave ? valorAntesDelCambio(clave, moneda) : null))
  const [cambio, setCambio] = useState(null)       // { delta } mientras se muestra
  const [destello, setDestello] = useState(null)   // { dir, n } — n cambia para re-disparar el CSS
  const asentado = useRef(false)                   // ya se mostró el valor de verdad al menos una vez
  const anterior = useRef(null)                    // el último valor de verdad que se mostró
  const identidad = `${clave}|${moneda}`
  const identidadAnterior = useRef(identidad)
  const ultimaEscritura = useRef(0)
  const timerCambio = useRef(null)

  // Mientras espera (datos o entrar en pantalla) se queda en el valor viejo.
  const enEspera = pendiente != null && !(listo && visto && valido)
  const inicio = useRef(pendiente != null ? pendiente : (desdeCero || !valido ? 0 : value))
  const contado = useCountUp(enEspera ? pendiente : (valido ? value : 0), { duration: DURA_MS, desde: inicio.current })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return undefined
    const anotar = () => { ultimaEscritura.current = Date.now() }
    window.addEventListener(EVENTO_ESCRITURA, anotar)
    window.addEventListener('rendi:portfolio-changed', anotar)
    return () => {
      window.removeEventListener(EVENTO_ESCRITURA, anotar)
      window.removeEventListener('rendi:portfolio-changed', anotar)
    }
  }, [])

  useEffect(() => () => clearTimeout(timerCambio.current), [])

  useEffect(() => {
    if (pendiente == null || listo) return undefined
    const t = setTimeout(() => setPendiente(null), ESPERA_MAX_MS)
    return () => clearTimeout(t)
  }, [pendiente, listo])

  // ¿El cambio se llega a leer? Mayor que el umbral y, escrito, distinto.
  const seNota = (antes, ahora) => {
    if (Math.abs(ahora - antes) <= umbral) return false
    if (typeof format !== 'function') return true
    try {
      return format(antes) !== format(ahora) && format(Math.abs(ahora - antes)) !== format(0)
    } catch { return true }
  }
  const destellar = (delta) => setDestello(d => ({ dir: delta >= 0 ? 'up' : 'down', n: (d?.n || 0) + 1 }))
  const anunciar = (delta) => {
    setCambio({ delta })
    destellar(delta)
    clearTimeout(timerCambio.current)
    timerCambio.current = setTimeout(() => setCambio(null), CAMBIO_VISIBLE_MS)
  }

  useEffect(() => {
    if (!valido || !listo) return
    const recordar = () => { if (clave && visto) recordarValor(clave, value, moneda) }

    // Pasó a ser OTRO número (otra moneda, otro filtro: la `clave` cambia con
    // lo que se está mirando): el valor es distinto y la cartera no cambió. No
    // se anuncia nada; el filtro de Movimientos puesto justo después de borrar
    // salía como "−US$ 5.000 respecto de antes".
    if (identidadAnterior.current !== identidad) {
      identidadAnterior.current = identidad
      asentado.current = true
      anterior.current = value
      if (pendiente != null) setPendiente(null)
      recordar()
      return
    }

    // 1) Primera vez con el valor de verdad.
    if (!asentado.current) {
      if (pendiente != null && seNota(pendiente, value)) {
        if (!visto) return                                  // espera a entrar en pantalla, en el valor viejo
        anunciar(value - pendiente)
      }
      asentado.current = true
      anterior.current = value
      if (pendiente != null) setPendiente(null)
      recordar()
      return
    }

    // 2) El valor cambió con el número ya asentado.
    const desde = anterior.current
    anterior.current = value
    const delta = value - desde
    if (Math.abs(delta) > umbral) {
      const porElUsuario = Date.now() - ultimaEscritura.current <= VENTANA_TRAS_ESCRIBIR_MS
      if (porElUsuario && !visto && seNota(desde, value)) {
        // Cambió fuera de la vista: queda en el valor viejo hasta que se vea.
        asentado.current = false
        setPendiente(desde)
        return
      }
      if (porElUsuario && seNota(desde, value)) { ultimaEscritura.current = 0; anunciar(delta) }   // este cambio ya se mostró
      else destellar(delta)
    }
    recordar()
    // `pendiente` no va: se lee del render en que corre.
  }, [value, listo, visto, valido, identidad])  // eslint-disable-line react-hooks/exhaustive-deps

  return { ref: refVisto, mostrado: valido ? contado : value, cambio, destello, enEspera }
}
