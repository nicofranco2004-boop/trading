// FueraDeHorario — las piezas visuales del pre y post mercado.
//
// La marca es una sola en toda la app:
//   · Sol ámbar (rendi-warn) = pre-mercado; luna azul (rendi-accent) = post.
//   · BORDE PUNTEADO = «todavía no cuenta»: el monto no está sumado al total.
//   · El número va en verde o rojo como cualquier ganancia de Rendi.
// Las cuentas salen de utils/fueraDeHorario.js; acá no se calcula nada.

import { useMemo } from 'react'
import { Sun, Moon } from 'lucide-react'
import { useCurrency } from '../contexts/CurrencyContext'
import { usePrivacy } from '../contexts/PrivacyContext'
import InfoTooltip from './InfoTooltip'
import { usd, ars, pctVar, pctColor, colorClass } from '../utils/format'
import {
  nombreDeSesion, nombreCorto, rotuloVia, estadoDeSesion,
  simbolosFueraDeHorario, impactoFueraDeHorario, sumarTenencias,
} from '../utils/fueraDeHorario'
import { useFueraDeHorario } from '../hooks/useFueraDeHorario'

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
export function ChipFueraDeHorario({ sesion, monto, pctFraccion, moneda, oculto = false, className = '', impacto = null, sinOperar = false }) {
  if (!sesion) return null
  const t = tonoDeSesion(sesion)
  const pctPuntos = pctFraccion != null && !sinOperar ? pctFraccion * 100 : null
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] border border-dashed ${t.borde} ${t.texto} tabular ${className}`}>
      <IconoSesion sesion={sesion} />
      <span>{nombreDeSesion(sesion)}</span>
      {sinOperar
        ? <span className="text-ink-3" title="Todavía no operó fuera de la rueda.">sin operar</span>
        : oculto
        ? <span className="text-ink-2">••••</span>
        : <span className={`font-semibold ${colorClass(monto)}`}>{montoFdh(monto, moneda)}</span>}
      {pctPuntos != null && <span className={pctColor(pctPuntos)}>{pctVar(pctPuntos)}</span>}
      {/* El (?) va PEGADO al número que explica: abajo, suelto, no se sabía a
          qué se refería. Sólo existe mientras hay pre o post (el chip también). */}
      {impacto && (
        // align 'left': el globo crece hacia la DERECHA del (?). Hacia la izquierda
        // (el default) quedaba tapado por el menú lateral cuando el chip cae cerca
        // de él (compu a 1024 px); si se pasa del borde derecho, InfoTooltip lo corre.
        <InfoTooltip label={`Cómo se calcula el ${sesion === 'pre' ? 'pre-mercado' : 'post-mercado'}`} size={13} ancho="w-80" align="left">
          <ComoSeCalcula sesion={sesion} impacto={impacto} moneda={moneda} oculto={oculto} />
        </InfoTooltip>
      )}
    </span>
  )
}

/**
 * El chip de la ficha de UN activo (AssetDetail en la compu, PositionDetailMobile
 * en el celular): la misma cuenta que la fila de Cartera, sobre los lotes de esa
 * ficha. En dólares, la moneda de la ficha. Nada si el activo no tiene pre/post
 * (bonos, fondos, acción argentina sin ADR…) o si no hay sesión.
 * `prices`, `tcValuacion`, `tcCedear` y `tcCripto` son los mismos que Cartera
 * le pasa a impactoFueraDeHorario. «sin operar» si la acción todavía no se movió.
 */
export function ChipDelActivo({ lotes, brokers, prices, tcValuacion, tcCedear, tcCripto = null, className = '' }) {
  const { hidden } = usePrivacy()
  const simbolos = useMemo(() => simbolosFueraDeHorario(lotes, brokers), [lotes, brokers])
  const datos = useFueraDeHorario(simbolos)
  const impacto = useMemo(
    () => impactoFueraDeHorario(lotes, brokers, { prices, tcValuacion, tcCedear, tcCripto }, datos),
    [lotes, brokers, prices, tcValuacion, tcCedear, tcCripto, datos])
  if (!impacto.aplica) return null
  const r = sumarTenencias((lotes || []).map(l => l.id), impacto)
  return (
    <ChipFueraDeHorario impacto={impacto} sesion={datos.sesion} moneda="USD" oculto={hidden}
      monto={impacto.total.usd} pctFraccion={impacto.total.pct} sinOperar={r?.pct == null}
      className={className} />
  )
}

const valorFdh = (n, moneda) => (moneda === 'ARS' ? `ARS ${ars(n)}` : `USD ${usd(n)}`)

/** «El pre-mercado no se suma a tu total: se suma cuando abre el mercado. Si
 *  abriera así, tu cartera quedaría en …». Nombra la franja a propósito: un
 *  «todavía no está en el total» suelto no decía QUÉ no estaba. */
export function SiAbrieraAsi({ sesion, total, moneda, oculto = false, className = '' }) {
  if (!sesion || oculto || total == null) return null
  const nombre = sesion === 'pre' ? 'pre-mercado' : 'post-mercado'
  return (
    <p className={`text-[12px] text-ink-2 tabular ${className}`}>
      <span className="text-ink-1">El {nombre} no se suma a tu total</span>: se suma cuando abre el mercado.
      Si abriera así, tu cartera quedaría en <span className="text-ink-1">{valorFdh(total, moneda)}</span>.
    </p>
  )
}

/** El detalle del cálculo: por tipo de tenencia, y por qué un CEDEAR puede abrir distinto. */
export function ComoSeCalcula({ sesion, impacto, moneda, oculto = false }) {
  const { valuationDollar } = useCurrency()
  const { exacto, anticipo } = impacto.porVia
  const m = (x) => (moneda === 'ARS' ? x.ars : x.usd)
  const nombre = sesion === 'pre' ? 'pre-mercado' : 'post-mercado'
  const cuando = sesion === 'pre' ? 'cuando abra BYMA a las 11' : 'cuando vuelva a abrir BYMA'
  // Con los saldos ocultos, la explicación sigue pero sin montos (auditoría
  // 2026-10-15: el (?) mostraba la plata con el ojito tachado).
  const plata = (n, m) => (oculto ? '••••' : montoFdh(n, m))
  const valor = (n, m) => (oculto ? '••••' : valorFdh(n, m))
  const Fila = ({ titulo, detalle, monto, fuerte = false }) => (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className={`text-ink-0 ${fuerte ? 'font-semibold' : ''}`}>{titulo}</div>
        {detalle && <div className="text-[11px] text-ink-3 leading-snug">{detalle}</div>}
      </div>
      <span className={`tabular whitespace-nowrap ${fuerte ? 'font-semibold' : ''} ${colorClass(monto)}`}>{plata(monto, moneda)}</span>
    </div>
  )
  return (
    <div className="flex flex-col gap-2 text-left normal-case">
      <p className="font-semibold text-ink-0">Cómo se calcula el {nombre}</p>
      <p>Cada activo: su valor al último cierre × lo que se mueve su acción en Nueva York ahora. Después se suma.</p>
      {exacto.valorUsd > 0 && (
        <Fila titulo="Acciones y ETFs de EE.UU." detalle="Exacto: es el precio de esa misma acción." monto={m(exacto)} />
      )}
      {anticipo.valorUsd > 0 && (
        <Fila titulo="CEDEARs y acciones argentinas" detalle="Anticipo: usa la acción (o su ADR) en Nueva York." monto={m(anticipo)} />
      )}
      <div className="border-t border-line pt-1.5">
        <Fila titulo="Total" monto={moneda === 'ARS' ? impacto.total.ars : impacto.total.usd} fuerte />
      </div>
      {anticipo.valorArs > 0 && (
        <div className="rounded bg-rendi-warn/10 p-2 flex flex-col gap-1">
          <div className="font-semibold text-rendi-warn">Puede haber diferencia {cuando}</div>
          <p>
            Un CEDEAR en pesos vale la acción de Nueva York <span className="text-ink-0">× el dólar CCL</span>, y
            este cálculo todavía no sabe qué va a hacer el CCL.
          </p>
          <p className="tabular">
            Cada <span className="text-ink-0">1 %</span> que se mueva el CCL, tus CEDEARs y acciones argentinas
            ({valor(anticipo.valorArs, 'ARS')}) se mueven unos{' '}
            <span className="text-ink-0">{valor(anticipo.valorArs * 0.01, 'ARS')}</span> más o menos.
          </p>
          {moneda !== 'ARS' && (
            <p className="text-ink-2">
              En dólares la diferencia es más chica: Rendi pasa esos pesos a dólares al{' '}
              {valuationDollar === 'ccl' ? 'CCL' : 'MEP'}, que se mueve parecido.
            </p>
          )}
        </div>
      )}
      <p className="text-ink-3">No se suma a tu total ni a tu ganancia hasta que abra el mercado.</p>
    </div>
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
