// AnalisisTecnico — «Análisis técnico» (menú → Análisis de mercado): cómo se
// mueven los precios de lo que tenés y de lo que seguís, en pestañas
// (recuadro 21 del tablero, aprobado por Nico el 28/10):
//   · Panorama (de entrada): el % de tu plata en tendencia de fondo alcista,
//     los 3 cambios más nuevos de la semana y por dónde seguir;
//   · Tu lista (?tab=lista): la tabla de pages/TuLista.jsx;
//   · Señales de la semana (?tab=senales): «Tus señales» de la pieza 15
//     (components/TusSenales.jsx), que vivía en Novedades;
//   · Comparar y Mercado: «Próximamente», no se pueden tocar.
// «Panorama» y no «Resumen»: Resumen es la primera pantalla del mismo grupo.
// ════════════════════════════════════════════════════════════════════════════
// Una sola pantalla para compu y celular (R6): en el celular las pestañas se
// deslizan de costado, con nombres cortos («Señales», «Pronto»).
//
// Nada se calcula acá. La página pide UNA vez lo de tu lista
// (useListaTecnica: tu cartera valuada como en la Cartera + POST
// /api/tecnico/lista) y lo de la semana (useTusSenales: GET /api/tus-senales,
// cambios_desde + texto_del_cambio, la misma cuenta que el mail de los
// sábados), y cada pestaña dibuja su parte.

import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import TuLista, { useListaTecnica } from './TuLista'
import { TusSenalesVista, useTusSenales, Cambio } from '../components/TusSenales'
import { TarjetaPlata } from '../components/RadiografiaTecnica'
import { usePrivacy } from '../contexts/PrivacyContext'
import { filasDeLaLista, contarFilas } from '../utils/listaTecnica'
import { tarjetas as tarjetasDeLaSemana, rutaDeFicha, NO_ES_RECOMENDACION } from '../utils/tusSenales'

// Las pestañas, en orden. `corto`: el nombre en el celular. `pronto`: todavía
// no está (se ve, no se toca).
export const PESTANAS = [
  { id: 'panorama', label: 'Panorama' },
  { id: 'lista', label: 'Tu lista' },
  { id: 'senales', label: 'Señales de la semana', corto: 'Señales' },
  { id: 'comparar', label: 'Comparar', pronto: true },
  { id: 'mercado', label: 'Mercado', pronto: true },
]

/** La pestaña de la dirección (?tab=…). Sin tab, una que no existe o una que
 *  todavía no está: Panorama. */
export function pestanaDe(searchParams) {
  const t = searchParams.get('tab')
  const p = PESTANAS.find(x => x.id === t && !x.pronto)
  return p ? p.id : 'panorama'
}

/** La dirección de una pestaña (Panorama va sin ?tab, es la de entrada). */
export const urlDePestana = (id) => (id === 'panorama' ? '/analisis-tecnico' : `/analisis-tecnico?tab=${id}`)

function Pestanas({ activa, cuentas, onElegir }) {
  return (
    <div role="tablist" aria-label="Partes del análisis técnico"
      className="flex items-center gap-0.5 sm:gap-1 mb-5 border-b border-line overflow-x-auto overscroll-x-contain scrollbar-none -mx-4 px-4 sm:mx-0 sm:px-0">
      {PESTANAS.map(p => {
        const on = activa === p.id
        const n = cuentas[p.id]
        return (
          <button key={p.id} type="button" role="tab" aria-selected={on} disabled={p.pronto}
            aria-controls="analisis-tecnico-panel" id={`analisis-tecnico-tab-${p.id}`}
            onClick={() => !p.pronto && onElegir(p.id)}
            className={`flex items-center gap-1.5 px-2.5 sm:px-3.5 py-3 text-[14px] sm:text-[15px] whitespace-nowrap border-b-2 -mb-px transition-colors ${
              on ? 'border-rendi-accent text-ink-0 font-semibold'
                : p.pronto ? 'border-transparent text-ink-3 cursor-default'
                  : 'border-transparent text-ink-2 hover:text-ink-0 font-medium'}`}>
            {p.corto ? <><span className="sm:hidden">{p.corto}</span><span className="hidden sm:inline">{p.label}</span></> : p.label}
            {n != null && <span className="text-[12px] font-medium text-ink-2 tabular">{n}</span>}
            {p.pronto && (
              <span className="text-[11px] font-semibold text-rendi-warn bg-rendi-warn/10 rounded-full px-1.5 py-0.5">
                <span className="sm:hidden">Pronto</span><span className="hidden sm:inline">Próximamente</span>
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/** «El resumen de la semana te llega el sábado 31/10 a las 10:00, por mail».
 *  `hasta`: el día de hoy que manda el servidor. */
export function textoDelResumen(canal, hasta) {
  if (!canal || canal === 'no') return 'No te llega el resumen de los sábados.'
  const como = { mail: 'por mail', push: 'por notificación', ambos: 'por mail y notificación' }[canal]
  const [y, m, d] = String(hasta).split('-').map(Number)
  const hoy = new Date(Date.UTC(y, m - 1, d))
  const faltan = (6 - hoy.getUTCDay() + 7) % 7
  const sab = new Date(hoy.getTime() + faltan * 86400000)
  const dia = `${String(sab.getUTCDate()).padStart(2, '0')}/${String(sab.getUTCMonth() + 1).padStart(2, '0')}`
  return `El resumen de la semana te llega el sábado ${dia} a las 10:00, ${como}.`
}

function Tarjeta({ titulo, texto, ir, accion, pronto = false }) {
  const cuerpo = (
    <>
      <span className="text-[15px] font-semibold text-ink-0 flex items-center gap-2">
        {titulo}
        {pronto && <span className="text-[11px] font-semibold text-rendi-warn bg-rendi-warn/10 rounded-full px-1.5 py-0.5">Próximamente</span>}
      </span>
      <span className="text-[13px] text-ink-1 leading-snug">{texto}</span>
      <span className={`text-[13px] font-medium ${pronto ? 'text-ink-3' : 'text-data-violet'}`}>{accion}</span>
    </>
  )
  if (pronto) return <div className="bg-bg-1 border border-line rounded-xl px-4 py-3.5 flex flex-col gap-1.5 opacity-80">{cuerpo}</div>
  return <Link to={ir} className="bg-bg-1 border border-line rounded-xl px-4 py-3.5 flex flex-col gap-1.5 hover:border-rendi-accent/40 transition-colors">{cuerpo}</Link>
}

/**
 * La tarjeta grande del Panorama: el % de tu plata en tendencia de fondo
 * alcista, la barra, los grupos y «la semana pasada». El número viene de GET
 * /api/tus-senales (`alcista`: senales_semana.reparto, LA cuenta, la misma de la
 * Cartera, de la pestaña Señales y del mail). La frase de lo que se dio vuelta
 * es la de `tarjetas` de utils/tusSenales.js, sin palabras nuevas.
 */
function PanoramaPlata({ semana, hidden }) {
  const datos = semana.datos
  const plata = tarjetasDeLaSemana(datos, hidden).plata
  // Sin nada con lectura el servidor manda `alcista: null`: la tarjeta lo dice.
  const reparto = datos ? (datos.alcista || { pct: null, grupos: {}, motivos: [] }) : null
  return (
    <TarjetaPlata reparto={reparto} cargando={!datos && !semana.error} error={!!semana.error}
      titulo="Tu plata en tendencia de fondo alcista"
      nota={datos?.alcista && !hidden ? plata.texto : null} />
  )
}

/** El Panorama. `lista`: lo de useListaTecnica; `filas`: las de tu lista;
 *  `semana`: lo de useTusSenales. */
export function Panorama({ lista, filas, semana, hidden, onVer, onPestana }) {
  const datos = semana.datos
  const t = useMemo(() => tarjetasDeLaSemana(datos, hidden), [datos, hidden])
  const ultimos = (datos?.senales || []).slice(0, 3)
  const total = datos?.senales?.length || 0
  const c = contarFilas(filas)
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] gap-3.5">
        <PanoramaPlata semana={semana} hidden={hidden} />
        <section aria-label="Esta semana" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-3">
          <div className="text-[12px] text-ink-2 font-medium">Esta semana</div>
          {semana.error ? (
            <p className="text-[13.5px] text-ink-1">No pudimos traer los cambios de la semana. Probá recargar en un rato.</p>
          ) : !datos ? (
            <div className="h-20 rounded-lg bg-bg-2/40 esqueleto" aria-label="Cargando la semana" />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div><div className="text-[24px] font-semibold tabular text-ink-0">{t.tenes.valor}</div><div className="text-[13px] text-ink-1">en lo que tenés</div></div>
                <div><div className="text-[24px] font-semibold tabular text-ink-0">{t.watch.valor}</div><div className="text-[13px] text-ink-1">en tu watchlist</div></div>
              </div>
              <p className="text-[13px] text-ink-1 leading-snug border-t border-line pt-3">
                {textoDelResumen(datos.canal, datos.hasta)}{' '}
                <button type="button" onClick={() => onPestana('senales')} className="text-data-violet font-medium hover:underline">
                  {datos.canal && datos.canal !== 'no' ? 'Cambiar' : 'Elegir cómo te llega'}
                </button>
              </p>
            </>
          )}
        </section>
      </div>

      <section aria-label="Lo que cambió esta semana" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-1">
        <div className="flex items-baseline justify-between gap-3 pt-3 pb-1">
          <h2 className="text-[15px] font-semibold text-ink-0">Lo que cambió esta semana en lo tuyo</h2>
          {ultimos.length > 0 && <span className="text-[12px] text-ink-2">{ultimos.length === 1 ? 'el único' : `los ${ultimos.length} más nuevos`}</span>}
        </div>
        {!datos ? (
          semana.error ? null : <div className="h-28 my-2 rounded-lg bg-bg-2/40 esqueleto" />
        ) : ultimos.length === 0 ? (
          <p className="py-4 text-[14px] text-ink-1">Esta semana no cambió nada en lo tuyo ni en tu watchlist.</p>
        ) : (
          <ul>{ultimos.map((s, i) => <Cambio key={`${s.asset}-${s.tipo}-${i}`} s={s} hidden={hidden} onVer={onVer} />)}</ul>
        )}
        {total > 0 && (
          <button type="button" onClick={() => onPestana('senales')}
            className="w-full text-left text-[14px] font-medium text-data-violet border-t border-line/60 py-3 hover:underline inline-flex items-center gap-1.5">
            Ver {total === 1 ? 'la señal' : `las ${total} señales`} de la semana <ArrowRight size={14} aria-hidden="true" />
          </button>
        )}
      </section>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
        <Tarjeta titulo="Tu lista" ir={urlDePestana('lista')} accion="Abrir tu lista →"
          texto={lista.cargando || lista.error ? 'Lo que tenés y lo que seguís, con su tendencia, fuerza y último cambio.'
            : `${c.todo} ${c.todo === 1 ? 'activo' : 'activos'}: ${c.tenes} que tenés y ${c.watchlist} que seguís, con su tendencia, fuerza y último cambio.`} />
        <Tarjeta titulo="Señales de la semana" ir={urlDePestana('senales')} accion="Ver las señales →"
          texto={`${datos ? `${total === 1 ? 'El cambio' : `Los ${total} cambios`}` : 'Los cambios'}, día por día, y cómo te llega el resumen de los sábados.`} />
        <Tarjeta titulo="Comparar" pronto accion="Todavía no está"
          texto="¿Qué rindió más desde que compraste? Contra guardar dólares, la inflación y el S&P 500." />
      </div>
      <p className="text-[12px] text-ink-3 leading-relaxed">{NO_ES_RECOMENDACION}</p>
    </div>
  )
}

export default function AnalisisTecnico() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  const activa = pestanaDe(searchParams)
  const lista = useListaTecnica()
  const semana = useTusSenales()
  const [filtro, setFiltro] = useState('todo')
  const filas = useMemo(
    () => (lista.cargando || lista.error ? [] : filasDeLaLista(lista)),
    [lista.cargando, lista.error, lista.lotes, lista.seguidos, lista.valorDe, lista.extra, lista.indice])

  const elegir = (id) => {
    const next = new URLSearchParams(searchParams)
    if (id === 'panorama') next.delete('tab'); else next.set('tab', id)
    setSearchParams(next)
    window.scrollTo?.({ top: 0 })
  }
  const cuentas = {
    lista: lista.cargando || lista.error ? null : filas.length,
    senales: semana.datos ? semana.datos.senales?.length || 0 : null,
  }
  const ver = (x) => navigate(rutaDeFicha(x))

  return (
    <div className="page-shell-wide py-4">
      <PageHeader eyebrow="Análisis de mercado" title="Análisis técnico"
        subtitle="Cómo se están moviendo los precios de lo que tenés y de lo que seguís. Medido en dólares, al cierre del último día de mercado." />
      <Pestanas activa={activa} cuentas={cuentas} onElegir={elegir} />
      <div role="tabpanel" id="analisis-tecnico-panel" aria-labelledby={`analisis-tecnico-tab-${activa}`}>
        {activa === 'panorama' && <Panorama lista={lista} filas={filas} semana={semana} hidden={hidden} onVer={ver} onPestana={elegir} />}
        {activa === 'lista' && <TuLista datos={lista} filas={filas} />}
        {activa === 'senales' && (
          <div className="flex flex-col gap-3">
            <TusSenalesVista datos={semana.datos} error={semana.error} hidden={hidden} filtro={filtro} onFiltro={setFiltro}
              onVer={ver} onCanal={semana.cambiarCanal} guardando={semana.guardando} errorCanal={semana.errorCanal} />
            <p className="text-[13px] text-ink-2">
              ¿Querés que te avisemos cuando pase algo así?{' '}
              <Link to="/alertas?tab=crear" className="text-data-violet font-medium hover:underline">Crear una alerta técnica en Alertas →</Link>
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
