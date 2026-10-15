// FueraDeHorario — las piezas visuales del pre y post mercado.
//
// La marca es una sola en toda la app:
//   · Sol ámbar (rendi-warn) = pre-mercado; luna azul (rendi-accent) = post.
//   · BORDE PUNTEADO = «todavía no cuenta»: el monto no está sumado al total.
//   · El número va en verde o rojo como cualquier ganancia de Rendi.
// Las cuentas salen de utils/fueraDeHorario.js; acá no se calcula nada.

import { Sun, Moon } from 'lucide-react'
import { usd, ars, pctVar, pctColor, colorClass } from '../utils/format'
import { nombreDeSesion, nombreCorto, rotuloVia, estadoDeSesion } from '../utils/fueraDeHorario'

const esPre = (sesion) => sesion === 'pre'

export function tonoDeSesion(sesion) {
  return esPre(sesion)
    ? { texto: 'text-rendi-warn', borde: 'border-rendi-warn/50', fondo: 'bg-rendi-warn/10' }
    : { texto: 'text-rendi-accent', borde: 'border-rendi-accent/50', fondo: 'bg-rendi-accent/10' }
}

export function IconoSesion({ sesion, size = 13 }) {
  const Icono = esPre(sesion) ? Sun : Moon
  return <Icono size={size} strokeWidth={2} aria-hidden="true" />
}

/** «+USD 31,32» · «−ARS 3.384». */
export function montoFdh(n, moneda) {
  if (n == null || !Number.isFinite(n)) return '—'
  const signo = n > 0.0000001 ? '+' : n < -0.0000001 ? '−' : ''
  const abs = Math.abs(n)
  return moneda === 'ARS' ? `${signo}ARS ${ars(abs)}` : `${signo}USD ${usd(abs)}`
}

/** El cartel de estado: «☀ Pre-mercado abierto · cierra 10:30». */
export function EstadoSesion({ datos, className = '' }) {
  if (!datos?.sesion) return null
  const t = tonoDeSesion(datos.sesion)
  const texto = datos.sesion === 'post_cerrado'
    ? 'Post-mercado cerrado'
    : `${nombreDeSesion(datos.sesion)} abierto${datos.cierra ? ` · cierra ${datos.cierra}` : ''}`
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-medium ${t.fondo} ${t.texto} ${className}`}
      title="Wall Street opera fuera de la rueda. Lo que se mueve ahora es un anticipo: no se suma a tu cartera hasta que abra el mercado.">
      <IconoSesion sesion={datos.sesion} size={12} />
      {texto}
    </span>
  )
}

/**
 * El chip punteado del total: «☀ Pre-mercado −USD 122,53 −0,29 %».
 * `pctFraccion` es la fracción del valor (0,0029), como el resto de los
 * porcentajes de cartera.
 */
export function ChipFueraDeHorario({ sesion, monto, pctFraccion, moneda, oculto = false, className = '' }) {
  if (!sesion) return null
  const t = tonoDeSesion(sesion)
  const pctPuntos = pctFraccion != null ? pctFraccion * 100 : null
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] border border-dashed ${t.borde} ${t.texto} tabular ${className}`}
      title="Lo que se está moviendo tu cartera fuera de la rueda. No está sumado al total: se suma recién cuando abre el mercado.">
      <IconoSesion sesion={sesion} />
      <span>{nombreDeSesion(sesion)}</span>
      {oculto
        ? <span className="text-ink-2">••••</span>
        : <span className={`font-semibold ${colorClass(monto)}`}>{montoFdh(monto, moneda)}</span>}
      {pctPuntos != null && <span className={pctColor(pctPuntos)}>{pctVar(pctPuntos)}</span>}
    </span>
  )
}

/** «Todavía no está en el total. Si el mercado abriera así, tu cartera quedaría en …». */
export function SiAbrieraAsi({ sesion, total, moneda, oculto = false, className = '' }) {
  if (!sesion || oculto || total == null) return null
  const valor = moneda === 'ARS' ? `ARS ${ars(total)}` : `USD ${usd(total)}`
  return (
    <p className={`text-[12px] text-ink-2 tabular ${className}`}>
      Todavía no está en el total. Si el mercado abriera así, tu cartera quedaría en{' '}
      <span className="text-ink-1">{valor}</span>.
    </p>
  )
}

/** La línea de una tarjeta de broker: «Pre EE.UU. +ARS 35.505 · +0,46 %». */
export function LineaBroker({ sesion, monto, pctFraccion, moneda, via = '', oculto = false }) {
  if (!sesion) return null
  const t = tonoDeSesion(sesion)
  const pctPuntos = pctFraccion != null ? pctFraccion * 100 : null
  return (
    <div className={`mt-1.5 pt-1.5 border-t border-dashed ${t.borde} text-[11.5px] tabular flex items-center gap-1 ${t.texto}`}>
      <IconoSesion sesion={sesion} size={11} />
      <span>{nombreCorto(sesion)}{via ? ` ${via}` : ''}</span>
      {oculto ? <span className="text-ink-2">••••</span> : (
        <span className={colorClass(monto)}>
          {montoFdh(monto, moneda)}{pctPuntos != null ? ` · ${pctVar(pctPuntos)}` : ''}
        </span>
      )}
    </div>
  )
}

/** El encabezado de la columna: «☀ Pre-mercado». */
export function EncabezadoColumna({ sesion }) {
  const t = tonoDeSesion(sesion)
  return (
    <span className={`inline-flex items-center gap-1 ${t.texto}`}
      title="Lo que se mueve cada activo fuera de la rueda. No está sumado al valor ni a la ganancia.">
      <IconoSesion sesion={sesion} size={11} />
      {sesion === 'post_cerrado' ? 'Post (cerró)' : nombreDeSesion(sesion)}
    </span>
  )
}

/** La celda de una fila: monto arriba, % y de dónde sale abajo. `r` = sumarTenencias(...). */
export function CeldaFueraDeHorario({ r, moneda, oculto = false, soloMonto = false }) {
  if (!r) return <span className="text-ink-3">—</span>
  if (soloMonto) {
    const total = moneda === 'ARS' ? r.ars : r.usd
    return <span className={colorClass(total)}>{oculto ? '••••••' : montoFdh(total, moneda)}</span>
  }
  if (r.pct == null) {
    return <span className="text-ink-3" title="Todavía no operó fuera de la rueda.">sin operar</span>
  }
  const monto = moneda === 'ARS' ? r.ars : r.usd
  const via = rotuloVia(r.via)
  return (
    <div className="leading-tight"
      title={via ? `Lo que se mueve la acción en Nueva York (${via}). Anticipa al papel de acá, sin contar lo que haga el dólar CCL.` : undefined}>
      <div className={`font-medium ${colorClass(monto)}`}>{oculto ? '••••••' : montoFdh(monto, moneda)}</div>
      <div className={`text-[10px] ${pctColor(r.pct)}`}>
        {pctVar(r.pct)}{via && <span className="text-ink-3"> {via}</span>}
      </div>
    </div>
  )
}

export { estadoDeSesion }
