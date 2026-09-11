// useReportYears — el año por año desde `/api/reports/years`.
//
// ⚠️ UNA SOLA FUENTE PARA EL NÚMERO DEL AÑO. Antes convivían dos: la pestaña Año
// de Reportes pedía `/reports/period/year/{año}` con el año de hoy escrito a mano
// (o sea, un año solo), y el calendario componía por su cuenta los meses que la
// timeline hubiera traído — con los meses ausentes contados como +0%. Con una
// timeline de 12 meses, 2025 publicaba "+6,50%" donde el motor mide +32,95%: dos
// números del mismo año, en la misma pantalla, con 26 puntos de diferencia.
//
// Este hook trae el número del motor canónico para TODOS los años, con la ventana
// que cada número cubre y el veredicto contra el S&P (y contra la inflación cuando
// se mide en pesos).

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'

/**
 * @param {string} broker  'global' | nombre del broker
 * @param {string} modo    'certero' | 'estimado'
 * @param {string} moneda  'usd' | 'ars'
 * @returns {{ years, current, loading, refreshing, error }} — `loading` es sólo
 *   la PRIMERA carga; los cambios de modo/moneda levantan `refreshing` y dejan
 *   los datos anteriores en pantalla.
 */
export default function useReportYears(broker = 'global', modo = 'certero', moneda = 'usd') {
  const [years, setYears] = useState([])
  // ¿El plan incluye los años anteriores? Lo dice el backend, que es quien corta.
  const [historicos, setHistoricos] = useState(true)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  // Los años que ya se mostraron, para no vaciarlos mientras llega la respuesta
  // nueva. Es una ref y no estado: cambiarla no tiene que re-renderizar.
  const hayDatos = useRef(false)

  const load = useCallback(() => {
    let cancelled = false
    // ⚠️ AL CAMBIAR DE MODO NO SE VACÍA LA PANTALLA. Con `loading = true` en cada
    // recarga, el toggle Certero/Estimado desmontaba la card del año en el inicio
    // —que no se dibuja mientras carga— y todo lo de abajo saltaba hacia arriba y
    // volvía. Ese es el "efecto raro" del toggle: no es una animación, es la card
    // yéndose y volviendo. La primera carga sí muestra vacío, porque ahí
    // efectivamente no hay nada que conservar.
    if (hayDatos.current) setRefreshing(true)
    else setLoading(true)
    setError(null)
    api.get(`/reports/years?broker=${encodeURIComponent(broker)}`
            + `&modo=${encodeURIComponent(modo)}&moneda=${encodeURIComponent(moneda)}`)
      .then(d => {
        if (cancelled) return
        setYears(d?.years || [])
        setHistoricos(d?.historicos !== false)
        hayDatos.current = true
      })
      .catch(ex => {
        if (cancelled) return
        setError(ex?.message || 'No pudimos cargar el rendimiento por año.')
        setYears([])
        hayDatos.current = false
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
        setRefreshing(false)
      })
    return () => { cancelled = true }
  }, [broker, modo, moneda])

  // ⚠️ Y SE VUELVE A PEDIR CUANDO LOS DATOS CAMBIAN. El Dashboard se recarga solo
  // ante `rendi:portfolio-changed` —que emiten el importador, el chat que registra
  // operaciones, el ajuste de split y el aviso de trial— y al volver a la pestaña.
  // Este hook no escuchaba ninguna de las dos: importabas un archivo, todo el
  // Dashboard se actualizaba y la card del año se quedaba con el número anterior
  // hasta recargar la página a mano.
  useEffect(() => {
    let cancelar = load()
    function refrescar() {
      if (cancelar) cancelar()
      cancelar = load()
    }
    window.addEventListener('rendi:portfolio-changed', refrescar)
    window.addEventListener('focus', refrescar)
    return () => {
      if (cancelar) cancelar()
      window.removeEventListener('rendi:portfolio-changed', refrescar)
      window.removeEventListener('focus', refrescar)
    }
  }, [load])

  // El año en curso — el que muestra el inicio. El backend lo manda primero y
  // marcado, así que no se deduce de `new Date()`: el "hoy" de Rendi es el día
  // ARGENTINO y vive en el backend (ver `fechas.hoy_art`).
  const current = years.find(y => y.is_current) || null

  return { years, current, historicos, loading, refreshing, error }
}
