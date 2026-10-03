// PreciosPendientes — ¿la pantalla todavía no tiene las cotizaciones de hoy?
//
// Métricas y Perfil de inversor (pages/Insights.jsx) salen sin precios cuando
// tardan más de 8 s (utils/cargaDiagnostico) o cuando el pedido falla. En ese
// lapso la cartera está valuada al costo, y un "Analizar" o un ✦ le mandaba a
// Mervall-E AI esos números: gastaba un análisis del cupo en una cartera que no es
// la tuya, y la respuesta quedaba guardada 24 h (revisión del 2026-10-02).
//
// La pantalla lo declara UNA vez (Provider) y los dos botones de la IA
// (AnalyzeButton, AskAIAbout) lo leen: se deshabilitan y dicen por qué. Fuera
// de esa pantalla el valor es false y nada cambia.

import { createContext, useContext } from 'react'

export const PreciosPendientes = createContext(false)

export const usePreciosPendientes = () => useContext(PreciosPendientes)

export const TEXTO_PRECIOS_PENDIENTES =
  'Faltan las cotizaciones de hoy: sin ellas, Mervall-E AI leería tu cartera al costo.'
