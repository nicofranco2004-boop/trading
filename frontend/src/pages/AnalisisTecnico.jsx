// AnalisisTecnico — «Análisis técnico» (menú → Análisis de mercado): cómo se
// mueven los precios de lo que tenés y de lo que seguís, en pestañas
// (recuadro 21 del tablero, aprobado por Nico el 28/10):
//   · Panorama (?tab=panorama), como la pantalla «1 · Panorama» del lienzo que
//     aprobó Nico el 30/10: el % de tu cartera en tendencia alcista de largo
//     plazo con el cambio contra la semana pasada, el mapa de tu cartera, los 3
//     cambios más nuevos de la semana por día (con «Avisame»), tu lista de un
//     vistazo y el resumen de los sábados (fue la de entrada hasta el 30/10);
//   · Tu lista (?tab=lista): la tabla de pages/TuLista.jsx;
//   · Señales de la semana (?tab=senales): «Tus señales» de la pieza 15
//     (components/TusSenales.jsx), que vivía en Novedades; desde el 30/10 se
//     ve como Novedades (lienzo «4 · Señales de la semana»): los 3 números,
//     las barras por día, la agenda con el día a la izquierda y, al costado,
//     el resumen del sábado y «¿Querés enterarte en el momento?»;
//   · Gráfico (de entrada, sin ?tab; ?activo=GGAL), la primera de la fila
//     (Nico, 30/10): sólo el gráfico, con el activo arriba a la izquierda como
//     en TradingView (pages/GraficoTecnico.jsx);
//   · Backtesting (?tab=backtesting; ?activo=GGAL&regla=rsi&anios=2): qué
//     habría pasado con US$ 100 siguiendo una regla técnica, al lado de comprar
//     y mantener (pages/Backtesting.jsx; Nico, 04/11). Va antes de Comparar
//     porque Comparar lleva a otra pantalla, y el tutorial termina en ella;
//   · Comparar: lleva a LA pantalla de comparar (Análisis fundamental →
//     Comparar → Precio, pieza 16) con tus 4 activos que más pesan ya cargados.
//     No hay un segundo «Comparar» acá adentro (decisión de Nico);
//   · Mercado: todavía no está; un «Pronto: Mercado» a la derecha de la fila,
//     no una pestaña gris que no se puede tocar (lienzo «1 · Panorama»).
// El título lleva «Beta» si el menú lo dice (utils/navegacion.js, esBeta).
// «Panorama» y no «Resumen»: Resumen es la primera pantalla del mismo grupo.
// ════════════════════════════════════════════════════════════════════════════
// Una sola pantalla para compu y celular (R6): en el celular las pestañas se
// deslizan de costado, con nombres cortos («Señales»), y el «Pronto» no va.
//
// Nada se calcula acá. La página pide UNA vez lo de tu lista
// (useListaTecnica: POST /api/tecnico/lista, con lo que tenés y cuánto pesa
// según el servidor) y lo de la semana (useTusSenales: GET /api/tus-senales,
// cambios_desde + texto_del_cambio, la misma cuenta que el mail de los
// sábados), y cada pestaña dibuja su parte.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, HelpCircle } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import TuLista, { useListaTecnica } from './TuLista'
import GraficoTecnico from './GraficoTecnico'
import Backtesting from './Backtesting'
import { TusSenalesVista, useTusSenales, Cambio } from '../components/TusSenales'
import { TarjetaPlata } from '../components/RadiografiaTecnica'
import MapaCartera from '../components/MapaCartera'
import { sinLecturaDe } from '../utils/mapaCartera'
import { useAvisosTecnicos } from '../components/alerts/AvisameTecnico'
import { usePrivacy } from '../contexts/PrivacyContext'
import { clicNormal } from '../utils/clicNormal'
import { filasDeLaLista, contarFilas } from '../utils/listaTecnica'
import {
  porDia, enOrden, rutaDeFicha, cambioContraAntes, queLoMovio, textoDelResumen,
  NO_ES_RECOMENDACION, TITULO_PLATA_ALCISTA, TITULO_CAMBIOS, QUE_ES_ESTA_SEMANA,
} from '../utils/tusSenales'
import { urlDeComparar } from '../utils/comparadorPrecio'
import { ordenConElOjito } from '../utils/parteDeTuPlata'
import { esBeta } from '../utils/navegacion'
import { EtiquetaBeta } from '../components/EtiquetaMenu'
import { pedirTour } from '../components/tour/recorrido'
import { ID_TOUR_TECNICO } from '../components/tour/TourTecnico'

// Las pestañas, en orden. `corto`: el nombre en el celular. `pronto`: todavía
// no está (se ve, no se toca). `afuera`: lleva a otra pantalla (no se queda acá).
export const PESTANAS = [
  // Gráfico, la primera de la fila y la de entrada (Nico, 30/10).
  { id: 'grafico', label: 'Gráfico' },
  { id: 'panorama', label: 'Panorama' },
  { id: 'lista', label: 'Tu lista' },
  { id: 'senales', label: 'Señales de la semana', corto: 'Señales' },
  // Anunciado como «Pronto» el 31/10; abierto el 04/11 (Nico).
  { id: 'backtesting', label: 'Backtesting' },
  { id: 'comparar', label: 'Comparar', afuera: true },
  { id: 'mercado', label: 'Mercado', pronto: true },
]

/** La que se abre al entrar (sin ?tab): Gráfico (Nico, 30/10). Un lugar solo
 *  para la regla: la dirección, los links y el cambio de pestaña la leen acá. */
export const DE_ENTRADA = 'grafico'

/** La pestaña de la dirección (?tab=…). Sin tab, una que no existe, una que
 *  todavía no está o una que lleva afuera: la de entrada. */
export function pestanaDe(searchParams) {
  const t = searchParams.get('tab')
  const p = PESTANAS.find(x => x.id === t && !x.pronto && !x.afuera)
  return p ? p.id : DE_ENTRADA
}

/** Comparar → Precio con tus 4 activos que más pesan (los de «Tu lista» que
 *  tenés, por su peso del servidor). Sin ninguno, abre vacío para elegir. Con
 *  «Ocultar saldos», cuáles van y en qué orden dirían cuáles pesan más: van
 *  los 4 primeros de la A a la Z (ordenConElOjito, auditoría D6, 31/10). */
export function urlDeCompararTuyos(filas = [], oculto = false) {
  return urlDeComparar(ordenConElOjito(filas.filter(f => f.tenes), oculto,
    { nombre: f => f.ruta, sinOjito: (a, b) => (b.peso || 0) - (a.peso || 0) }).map(f => f.ruta))
}

/** La dirección de una pestaña (la de entrada va sin ?tab). */
export const urlDePestana = (id) => (id === DE_ENTRADA ? '/analisis-tecnico' : `/analisis-tecnico?tab=${id}`)

function Pestanas({ activa, cuentas, onElegir }) {
  const pronto = PESTANAS.filter(p => p.pronto)
  // En el celular la fila se desliza de costado y las últimas no entran: la
  // abierta se trae a la vista (con ?tab=backtesting quedaba afuera, 04/11).
  // Otra vez cuando llegan los números de Tu lista y Señales: ensanchan las de
  // antes y la empujaban de nuevo afuera.
  const abierta = useRef(null)
  useEffect(() => { abierta.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' }) },
    [activa, cuentas.lista, cuentas.senales])
  return (
    <div className="flex items-center gap-3 mb-5 border-b border-line -mx-4 px-4 sm:mx-0 sm:px-0">
      <div role="tablist" aria-label="Partes del análisis técnico"
        className="flex items-center gap-0.5 sm:gap-1 min-w-0 overflow-x-auto overscroll-x-contain scrollbar-none">
        {PESTANAS.filter(p => !p.pronto).map(p => {
          const on = activa === p.id
          const n = cuentas[p.id]
          return (
            <button key={p.id} ref={on ? abierta : undefined} type="button" role="tab" aria-selected={on}
              aria-controls="analisis-tecnico-panel" id={`analisis-tecnico-tab-${p.id}`}
              data-tour={`tab-${p.id}`}
              onClick={() => onElegir(p.id)}
              className={`flex items-center gap-1.5 px-2.5 sm:px-3.5 py-3 text-[14px] sm:text-[15px] whitespace-nowrap border-b-2 -mb-px transition-colors ${
                on ? 'border-rendi-accent text-ink-0 font-semibold' : 'border-transparent text-ink-2 hover:text-ink-0 font-medium'}`}>
              {p.corto ? <><span className="sm:hidden">{p.corto}</span><span className="hidden sm:inline">{p.label}</span></> : p.label}
              {n != null && <span className="text-[12px] font-medium text-ink-2 tabular">{n}</span>}
            </button>
          )
        })}
      </div>
      {/* Lo que todavía no está: un texto, no pestañas que no se pueden tocar. */}
      {pronto.length > 0 && (
        <span data-tour="pronto" className="hidden sm:inline ml-auto text-[12px] text-ink-2 whitespace-nowrap px-1">
          Pronto: <span className="text-rendi-warn font-medium">{pronto.map(p => p.label).join(' · ')}</span>
        </span>
      )}
    </div>
  )
}

// La frase de cuándo llega el resumen vive en utils/tusSenales.js: la dicen
// el Panorama y la pestaña Señales.
export { textoDelResumen }

/**
 * La tarjeta grande del Panorama: el % de tu cartera en tendencia alcista de
 * largo plazo, el cambio contra la semana pasada, la barra, los grupos y qué lo
 * movió. El número viene de GET /api/tus-senales (`alcista`:
 * senales_semana.reparto, LA cuenta, la misma de la Cartera, de la pestaña
 * Señales y del mail).
 */
function PanoramaPlata({ semana, hidden }) {
  const datos = semana.datos
  // Sin nada con lectura el servidor manda `alcista: null`: la tarjeta lo dice.
  const reparto = datos ? (datos.alcista || { pct: null, grupos: {}, motivos: [] }) : null
  return (
    <TarjetaPlata reparto={reparto} cargando={!datos && !semana.error} error={!!semana.error}
      titulo={TITULO_PLATA_ALCISTA}
      cambio={datos?.alcista ? cambioContraAntes(datos.alcista, datos.hasta, hidden) : null}
      queLoMovio={datos?.alcista ? queLoMovio(datos, hidden) : null} />
  )
}

/** Un número de «Tu lista de un vistazo». */
function Numero({ valor, texto, tono = '' }) {
  return (
    <div className="bg-bg-2/60 rounded-lg px-3 py-2.5 min-w-0">
      <div className={`text-[22px] font-semibold tabular leading-tight ${tono || 'text-ink-0'}`}>{valor}</div>
      <div className="text-[12px] text-ink-2 leading-snug">{texto}</div>
    </div>
  )
}

/** Un link que cambia de pestaña sin recargar (y se puede abrir en otra). */
function APestana({ id, onPestana, className, children }) {
  return (
    <a href={urlDePestana(id)} onClick={(e) => { if (clicNormal(e)) { e.preventDefault(); onPestana(id) } }} className={className}>
      {children}
    </a>
  )
}

const BOTON = 'text-[13px] font-medium text-ink-1 bg-bg-2/60 border border-line rounded-full px-3.5 py-1.5 min-h-[34px] inline-flex items-center hover:text-ink-0 hover:border-rendi-accent/40 transition'

/** El Panorama. `lista`: lo de useListaTecnica; `filas`: las de tu lista;
 *  `semana`: lo de useTusSenales. */
/** `diaDelMapa`: lo del día del mapa, fijo (sólo la prueba; ver MapaCartera). */
export function Panorama({ lista, filas, semana, hidden, onVer, onPestana, diaDelMapa = null }) {
  const datos = semana.datos
  // Las alertas de la cuenta, para que cada campanita sepa si ya hay una igual:
  // una vez por pantalla, no una por botón, y sólo si se abre el Panorama.
  const avisos = useAvisosTecnicos()
  // Con «Ocultar saldos», los 3 más nuevos no se eligen por peso (enOrden).
  const ultimos = useMemo(() => enOrden(datos?.senales || [], hidden).slice(0, 3), [datos, hidden])
  const dias = useMemo(() => porDia(ultimos), [ultimos])
  const total = datos?.senales?.length || 0
  const c = contarFilas(filas)
  const alcistas = filas.filter(f => f.fondo?.id === 'alcista').length
  const enMaximo = filas.filter(f => f.desdeMax?.enMaximo && f.desdeMax.anioCompleto).length
  // Efectivo / plazos fijos, del MISMO pedido que las filas del mapa.
  const sinLectura = useMemo(() => sinLecturaDe(lista.sinMedir), [lista.sinMedir])
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] gap-4">
        <PanoramaPlata semana={semana} hidden={hidden} />
        <MapaCartera conTusActivos filas={filas} cargando={lista.cargando} error={!!lista.error} hidden={hidden}
          sinLectura={sinLectura} rutaOtros={urlDePestana('lista')} dia={diaDelMapa} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] gap-4 items-start">
        <section aria-label="Lo que cambió esta semana" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-1 min-w-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 pt-3 pb-1">
            <div>
              <h2 className="text-[15px] sm:text-[16px] font-semibold text-ink-0">{TITULO_CAMBIOS}</h2>
              <p className="text-[12px] text-ink-2 mt-0.5">{QUE_ES_ESTA_SEMANA}</p>
            </div>
            {ultimos.length > 0 && (
              <span className="text-[12px] text-ink-2 font-medium">
                {total === 1 ? '1 cambio' : `${total} cambios`}{total > ultimos.length ? ` · los ${ultimos.length} más nuevos` : ''}
              </span>
            )}
          </div>
          {!datos ? (
            semana.error
              ? <p className="py-4 text-[13.5px] text-ink-1">No pudimos cargar los cambios de la semana. Probá recargar la página en unos minutos.</p>
              : <div className="h-28 my-2 rounded-lg bg-bg-2/40 esqueleto" aria-label="Cargando la semana" />
          ) : ultimos.length === 0 ? (
            <p className="py-4 text-[14px] text-ink-1">Esta semana no cambió nada en tu cartera ni en tu watchlist.</p>
          ) : dias.map(d => (
            <div key={d.fecha}>
              <h3 className="text-[12px] text-ink-2 font-semibold pt-3 pb-0.5">{d.dia}</h3>
              <ul>
                {d.items.map((s, i) => <Cambio key={`${s.asset}-${s.local}-${s.tipo}-${i}`} s={s} hidden={hidden} onVer={onVer} avisos={avisos} />)}
              </ul>
            </div>
          ))}
          {total > 0 && (
            <a href={urlDePestana('senales')} onClick={(e) => { if (clicNormal(e)) { e.preventDefault(); onPestana('senales') } }}
              className="w-full text-left text-[14px] font-medium text-data-violet border-t border-line/60 mt-1 py-3 hover:underline inline-flex items-center gap-1.5">
              Ver {total === 1 ? 'la señal' : `las ${total} señales`} de la semana <ArrowRight size={14} aria-hidden="true" />
            </a>
          )}
        </section>

        <div className="flex flex-col gap-4 min-w-0">
          {/* En el celular no va: la pestaña «Tu lista» ya dice cuántos son. */}
          <section aria-label="Tu lista de un vistazo" className="hidden sm:flex bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex-col gap-2.5">
            <h2 className="text-[15px] font-semibold text-ink-0">Tu lista de un vistazo</h2>
            {lista.error ? (
              <p className="text-[13.5px] text-ink-1">No pudimos cargar tu lista. Probá recargar la página en unos minutos.</p>
            ) : lista.cargando ? (
              <div className="h-16 rounded-lg bg-bg-2/40 esqueleto" aria-label="Cargando tu lista" />
            ) : (
              <div className="grid grid-cols-3 gap-2.5">
                <Numero valor={c.todo} texto={c.todo === 1 ? 'activo' : 'activos'} />
                <Numero valor={alcistas} texto="con tendencia alcista de largo plazo" tono={alcistas ? 'text-rendi-pos' : ''} />
                <Numero valor={enMaximo} texto="en su máximo del año" />
              </div>
            )}
            <APestana id="lista" onPestana={onPestana} className="text-[13.5px] font-medium text-data-violet hover:underline self-start">
              Abrir tu lista →
            </APestana>
          </section>

          <section aria-label="El resumen del sábado" className="bg-bg-1 border border-line rounded-xl px-4 sm:px-5 py-4 flex flex-col gap-2.5">
            <h2 className="text-[15px] font-semibold text-ink-0">El resumen del sábado</h2>
            {semana.error ? (
              <p className="text-[13.5px] text-ink-1">No pudimos cargar cómo te llega el resumen. Probá recargar la página en unos minutos.</p>
            ) : !datos ? (
              <div className="h-12 rounded-lg bg-bg-2/40 esqueleto" />
            ) : (
              <>
                <p className="text-[13.5px] text-ink-1 leading-relaxed">{textoDelResumen(datos.canal, datos.proximo_resumen)}</p>
                <div className="flex flex-wrap gap-2">
                  <APestana id="senales" onPestana={onPestana} className={BOTON}>
                    {datos.canal && datos.canal !== 'no' ? 'Cambiar cómo me llega' : 'Elegir cómo recibirlo'}
                  </APestana>
                  <Link to="/alertas?tab=crear" className={BOTON}>Crear una alerta técnica</Link>
                </div>
              </>
            )}
          </section>
        </div>
      </div>

      <p className="text-[12px] text-ink-2 leading-relaxed">{NO_ES_RECOMENDACION}</p>
    </div>
  )
}

/** La pestaña Señales, como Novedades (lienzo «4 · Señales de la semana», 30/10).
 *  Las alertas de la cuenta se piden acá, una vez, para las campanitas. */
function Senales({ semana, hidden, filtro, onFiltro, onVer }) {
  const avisos = useAvisosTecnicos()
  return (
    <TusSenalesVista datos={semana.datos} error={semana.error} hidden={hidden} filtro={filtro} onFiltro={onFiltro}
      onVer={onVer} onCanal={semana.cambiarCanal} guardando={semana.guardando} errorCanal={semana.errorCanal} avisos={avisos} />
  )
}

/** Vuelve a abrir el recorrido por las pestañas (components/tour/TourTecnico.jsx).
 *  Solo se muestra una vez; después, sólo con este botón. */
function ComoSeLee() {
  return (
    <button type="button" onClick={() => pedirTour(ID_TOUR_TECNICO)}
      className="inline-flex items-center gap-1.5 min-h-11 sm:min-h-8 px-3 rounded-full border border-line text-[13px] font-medium text-ink-1 hover:text-ink-0 hover:border-ink-3 transition-colors">
      <HelpCircle size={15} aria-hidden="true" />
      ¿Cómo se lee esto?
    </button>
  )
}

export default function AnalisisTecnico() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { hidden } = usePrivacy()
  const activa = pestanaDe(searchParams)
  // Sigue la watchlist: el buscador de «Tu lista» suma y el activo aparece.
  const lista = useListaTecnica({ seguirLaWatchlist: true })
  const semana = useTusSenales()
  const [filtro, setFiltro] = useState('todo')
  const filas = useMemo(
    () => (lista.cargando || lista.error ? [] : filasDeLaLista(lista)),
    [lista.cargando, lista.error, lista.tenencias, lista.seguidos, lista.indice])

  const elegir = (id) => {
    if (id === 'comparar') { navigate(urlDeCompararTuyos(filas, hidden)); return }
    const next = new URLSearchParams(searchParams)
    if (id === DE_ENTRADA) next.delete('tab'); else next.set('tab', id)
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
      <PageHeader eyebrow="Análisis de mercado"
        title={esBeta('/analisis-tecnico')
          ? <span className="inline-flex items-center gap-2.5">Análisis técnico{' '}<EtiquetaBeta className="tracking-normal" /></span>
          : 'Análisis técnico'}
        subtitle="Cómo se están moviendo los precios de tus activos y de los de tu watchlist. En dólares, con el precio de cierre del último día de mercado."
        action={<ComoSeLee />} />
      <Pestanas activa={activa} cuentas={cuentas} onElegir={elegir} />
      <div role="tabpanel" id="analisis-tecnico-panel" aria-labelledby={`analisis-tecnico-tab-${activa}`}>
        {activa === 'panorama' && <Panorama lista={lista} filas={filas} semana={semana} hidden={hidden} onVer={ver} onPestana={elegir} />}
        {activa === 'lista' && <TuLista datos={lista} filas={filas} />}
        {activa === 'grafico' && <GraficoTecnico />}
        {activa === 'backtesting' && <Backtesting />}
        {activa === 'senales' && (
          <Senales semana={semana} hidden={hidden} filtro={filtro} onFiltro={setFiltro} onVer={ver} />
        )}
      </div>
    </div>
  )
}
