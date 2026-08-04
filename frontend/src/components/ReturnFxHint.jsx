import InfoTooltip from './InfoTooltip'
import { pctSigned } from '../utils/format'

/**
 * ReturnFxHint — el (?) al lado del P&L del TOTAL cuando el retorno en pesos y el
 * retorno en dólares no coinciden.
 *
 * POR QUÉ EXISTE: en la vista USD el costo está medido al dólar que pagaste; en la
 * vista ARS está en pesos nominales. Si el dólar se movió entre tus compras y hoy,
 * los dos porcentajes DEBEN diferir — y sin embargo parecen "el mismo número en
 * otra moneda", así que la lectura natural es que uno de los dos está mal.
 * Reportado así: "en dólares me aparece +49 y en pesos +580.000, tiene un error sí
 * o sí". No lo tenía: en pesos rendía 6,0% y en dólares 0,75%, y la diferencia era
 * que el dólar había subido 5,2%.
 *
 * La cuenta que cierra: (1 + retorno ARS) / (1 + retorno USD) − 1 = cuánto se movió
 * el dólar. De ahí sale el número que se muestra, sin necesidad de pasarle el TC.
 *
 * No se dibuja nada si los dos retornos dan casi igual (el dólar no se movió, o la
 * cartera es toda en dólares): ahí el ícono sería ruido.
 */
export default function ReturnFxHint({ pnlArs, invArs, pnlUsd, invUsd, isArsDisp }) {
  if (!(invArs > 0) || !(invUsd > 0)) return null
  const rArs = pnlArs / invArs
  const rUsd = pnlUsd / invUsd
  if (!isFinite(rArs) || !isFinite(rUsd)) return null
  // Menos de medio punto de brecha no merece un ícono.
  if (Math.abs(rArs - rUsd) < 0.005) return null

  const fx = (1 + rArs) / (1 + rUsd) - 1
  if (!isFinite(fx)) return null
  const subio = fx >= 0

  return (
    // side="top": esto vive en la fila TOTAL, la ÚLTIMA de la tabla, y la tabla
    // está dentro de un `overflow-x-auto` anidado en un `overflow-hidden`. Un
    // popover que abriera hacia abajo quedaría cortado por el borde de la card.
    <InfoTooltip label="Por qué difiere del otro" side="top">
      <p className="font-medium text-ink-0">
        En pesos {pctSigned(rArs)} · en dólares {pctSigned(rUsd)}
      </p>
      <p>
        No es un error: son dos preguntas distintas. En pesos comparás contra lo que
        pagaste en pesos; en dólares, contra los dólares que valía esa plata cuando
        compraste.
      </p>
      <p>
        El dólar {subio ? 'subió' : 'bajó'} <strong>{pctSigned(Math.abs(fx))}</strong>{' '}
        desde tus compras, y eso {subio ? 'se come parte de' : 'suma a'} la ganancia
        cuando la medís en dólares.
      </p>
      <p className="text-ink-3">
        Estás viendo la vista en {isArsDisp ? 'pesos' : 'dólares'}. El toggle de arriba
        cambia entre las dos.
      </p>
    </InfoTooltip>
  )
}
