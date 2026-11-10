// ListaDelGrafico — tu lista al costado del gráfico, como en TradingView
// (pestaña «Gráfico» de Análisis técnico; Nico, 10/11; lienzo aprobado:
// https://claude.ai/artifact/3XbhPrhCWDdgYSUshPTgxQ).
//   · En la compu, un panel de 336 px a la derecha del gráfico, del alto que le
//     queda a la pantalla (llega hasta el borde de abajo de la ventana, como en
//     el lienzo) y que se queda a la vista si bajás a leer las tarjetas, y una
//     columnita al borde con el botón «Lista» que lo abre y lo cierra. No se
//     estira con la columna del gráfico: LecturaTecnica trae, debajo del
//     gráfico, las tarjetas de la lectura (medido: 2.074 px en total), y la
//     lista se estiraba hasta ahí con la ficha corta fuera de la pantalla.
//   · En el celular, la MISMA lista como una hoja que sube desde abajo y deja
//     ver el gráfico arriba (frontend/CLAUDE.md, R6: un solo componente; lo que
//     cambia entre uno y otro son las clases `lg:`). Tocar un activo lo abre en
//     el gráfico; mantenerlo apretado abre su menú (bandera, alerta, ficha,
//     sacarlo, moverlo).
//   · Tocar un renglón cambia el activo del gráfico (el mismo camino que el
//     buscador del activo: hooks/useActivoDelGrafico). Banderas, nombres y
//     orden se guardan en la cuenta (hooks/useListaDelGrafico); «Cómo se ve» y
//     si está abierta, en este navegador (utils/listaDelGrafico).
//   · «+» busca con el MISMO buscador del botón del activo
//     (utils/graficoTecnico.opcionesDelBuscador): «Apple» ofrece la acción en
//     dólares y el CEDEAR en pesos.
//   · Abajo, la ficha corta del que estás mirando (sólo en la compu: en el
//     celular el menú de cada renglón hace lo mismo).
// Pendiente: en la pantalla completa del gráfico (vive en LecturaTecnica) la
// lista no está.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, Bell, Check, ChevronDown, PanelRightClose, Pencil, Plus, Search, SlidersHorizontal, Trash2, X,
} from 'lucide-react'
import AssetLogo from './AssetLogo'
import { useAnchoMinimo } from '../hooks/useIsMobile'
import { usePrivacy } from '../contexts/PrivacyContext'
import { urlDeActivo, miradaSinTenencia } from '../utils/buscadorRapido'
import { opcionesDelBuscador, mismoGrafico } from '../utils/graficoTecnico'
import { lecturaDeSeguido, nombreDeActivo } from '../utils/listaTecnica'
import { clave } from '../utils/radiografia'
import {
  AGRUPAR, BANDERAS, ORDENAR, armarLista, banderaAlAgregar, colorDeBandera, enSuLugar, filaDelActivo, tipoDelLote,
  guardarVista, lecturaCorta, loTenes, mover, nombreDeBandera, numerosDe, textoDeLaRueda, textoLoTenes,
  tipoDeSimbolo, tipoInfo, vistaGuardada,
} from '../utils/listaDelGrafico'

const TOPE = 100   // main.WATCHLIST_TOPE
const TONO = { 1: 'text-rendi-pos', '-1': 'text-rendi-neg', 0: 'text-ink-2' }
const TONO_FONDO = { 1: 'bg-rendi-pos/15', '-1': 'bg-rendi-neg/15', 0: 'bg-bg-2' }
const MANTENER_MS = 500   // mantener apretado en el celular

// ─── Si está abierta y «Cómo se ve»: en este navegador ──────────────────────

// Desde dónde es «la compu»: el `lg` de Tailwind, el mismo de las clases de
// abajo. El ancho lo mide el dueño único (hooks/useIsMobile).
const ANCHO_COMPU = 1024

/** { vista, abierta, compu, cambiar }. La primera vez: abierta en la compu,
 *  cerrada en el celular (la hoja taparía el gráfico apenas entrás). */
export function useVistaDeLaLista() {
  const compu = useAnchoMinimo(ANCHO_COMPU)
  const [vista, setVista] = useState(() => vistaGuardada())
  const cambiar = (c) => setVista(v => { const n = { ...v, ...c }; guardarVista(n); return n })
  return { vista, abierta: vista.abierta ?? compu, compu, cambiar }
}

// Cuánto se deja libre abajo de la lista en la compu y el alto mínimo.
const MARGEN_PX = 12
const ALTO_MINIMO_PX = 480
// Dónde se pega arriba al bajar la página: debajo de la burbuja de Mervall-E,
// que flota arriba a la derecha (components/voz/RendiMate, en
// `--alto-barra-celular` + 8 px; medido en 1440 × 900: de 93 a 119 px). Más
// arriba, la burbuja tapaba los botones de la lista.
const PEGADA_ARRIBA = { top: 'calc(var(--alto-barra-celular, 80px) + 48px)' }

/** El alto de la lista en la compu: lo que le queda a la pantalla debajo de
 *  donde empieza (o, pegada arriba al bajar, la pantalla menos los márgenes).
 *  Se escribe en el elemento sin volver a dibujar la lista en cada movimiento
 *  de la rueda. En el celular el contenedor no ocupa lugar (`contents`) y no
 *  cambia nada. */
function useAltoHastaAbajo(ref, abierta) {
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof window === 'undefined' || !Number.isFinite(window.innerHeight)) return undefined
    const cuadro = window.requestAnimationFrame?.bind(window) || ((fn) => setTimeout(fn, 16))
    const soltar = window.cancelAnimationFrame?.bind(window) || clearTimeout
    let pendiente = 0
    const medir = () => {
      pendiente = 0
      const arriba = el.getBoundingClientRect?.().top
      if (!Number.isFinite(arriba)) return
      const pegada = parseFloat(window.getComputedStyle?.(el)?.top) || MARGEN_PX
      el.style.height = `${Math.max(ALTO_MINIMO_PX, Math.round(window.innerHeight - Math.max(arriba, pegada) - MARGEN_PX))}px`
    }
    const pedir = () => { if (!pendiente) pendiente = cuadro(medir) }
    medir()
    window.addEventListener('resize', pedir)
    window.addEventListener('scroll', pedir, { passive: true })
    return () => {
      if (pendiente) soltar(pendiente)
      window.removeEventListener('resize', pedir)
      window.removeEventListener('scroll', pedir)
    }
  }, [ref, abierta])
}

/** El botón «Tu lista» del celular, en el renglón del activo. */
export function BotonDeLaLista({ abierta, onAlternar }) {
  return (
    <button type="button" onClick={onAlternar} aria-pressed={abierta} aria-controls="lista-del-grafico"
      className={`ml-auto inline-flex min-h-11 items-center gap-1.5 rounded-lg border px-3 text-[13.5px] font-semibold text-ink-0 lg:hidden ${
        abierta ? 'border-line-3 bg-bg-3' : 'border-line bg-bg-2'}`}>
      <IconoLista />
      Tu lista
    </button>
  )
}

function IconoLista({ size = 17 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M9 6h12M9 12h12M9 18h12" />
      <circle cx="4.5" cy="6" r="1.2" fill="currentColor" /><circle cx="4.5" cy="12" r="1.2" fill="currentColor" /><circle cx="4.5" cy="18" r="1.2" fill="currentColor" />
    </svg>
  )
}

/** La banderita: rellena con su color, o el contorno gris sin bandera. La usa
 *  también «Tu lista» (pages/TuLista.jsx). */
export function IconoBandera({ id, size = 13 }) {
  const color = colorDeBandera(id)
  const trazo = color || 'rgb(var(--ink-3))'
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="shrink-0">
      <path d="M6 21V3" stroke={trazo} strokeWidth="2.2" strokeLinecap="round" fill="none" />
      <path d="M6 4h12l-3 4.5 3 4.5H6z" fill={color || 'none'} stroke={trazo} strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  )
}

// ─── La lista ───────────────────────────────────────────────────────────────

/**
 * `datos`: lo de useListaDelGrafico. `activo`: el del gráfico; `onElegir(s)`
 * lo cambia. `deLaFicha`: lo que sabe la ficha del activo abierto
 * (useFichaDelActivo: `agg`, `accionLocal`), para «Lo tenés» y la lectura.
 * `vista`: lo de useVistaDeLaLista. `cliente`: un asesor adentro de la cuenta
 * de un cliente (no es «tu» lista). `recientes`: los últimos que miraste.
 */
export default function ListaDelGrafico({ datos, activo, onElegir, deLaFicha = null, vista: v, cliente = null, recientes = [] }) {
  const { vista, abierta, compu, cambiar } = v
  const { hidden } = usePrivacy()
  const [buscando, setBuscando] = useState(false)
  const [opciones, setOpciones] = useState(false)
  // El menú de un renglón: { simbolo, conAcciones } (con acciones: lo abrió
  // mantener apretado o el botón derecho; si no, la banderita).
  const [menu, setMenu] = useState(null)
  const [arrastrando, setArrastrando] = useState(null)   // símbolo
  const [soltar, setSoltar] = useState(null)             // { simbolo, despues }
  const seccion = useRef(null)
  const caja = useRef(null)
  useAltoHastaAbajo(caja, abierta)
  const titulo = cliente ? `Lista de ${cliente}` : 'Tu lista'

  const { filtro, chips, secciones } = useMemo(
    () => armarLista({ filas: datos.filas, agrupar: vista.agrupar, filtro: vista.filtro, orden: vista.orden, nombres: datos.nombres }),
    [datos.filas, datos.nombres, vista.agrupar, vista.filtro, vista.orden])
  // Lo que tenés del activo abierto (tus lotes, la cuenta de la ficha): el
  // gráfico es el de tu lote, y el renglón y la ficha corta lo siguen.
  const tipoTenido = deLaFicha?.activo === activo && deLaFicha.agg?.lots?.length ? tipoDelLote(deLaFicha.agg.lots[0]) : null
  const actual = filaDelActivo(datos.filas, activo, tipoTenido)
  const plegadas = new Set(vista.plegadas)
  const puedeMover = vista.orden === 'tuyo'

  // Esc cierra lo que haya abierto adentro (el menú, «Cómo se ve», el buscador)
  // y, en el celular, la hoja.
  useEffect(() => {
    if (!abierta) return undefined
    const tecla = (e) => {
      if (e.key !== 'Escape') return
      if (menu) setMenu(null)
      else if (opciones) setOpciones(false)
      else if (buscando) setBuscando(false)
      else if (!compu) cambiar({ abierta: false })
    }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [abierta, menu, opciones, buscando, compu]) // eslint-disable-line react-hooks/exhaustive-deps

  const cerrar = () => { setMenu(null); setOpciones(false); setBuscando(false); cambiar({ abierta: false }) }
  const elegir = (s) => { setMenu(null); onElegir(s) }

  // «Como los acomodás»: el renglón `de` va antes (o después) de `a`.
  function moverA(de, a, despues) {
    const lista = enSuLugar(datos.filas).map(f => f.simbolo)
    const nueva = mover(lista, de, a, { despues })
    if (nueva !== lista) datos.ordenar(nueva)
  }
  // Uno para arriba o para abajo, adentro de su sección (teclado y menú).
  function moverUno(simbolo, paso) {
    const sec = secciones.find(s => s.filas.some(f => f.simbolo === simbolo))
    if (!sec) return
    const i = sec.filas.findIndex(f => f.simbolo === simbolo)
    const otro = sec.filas[i + paso]
    if (otro) moverA(simbolo, otro.simbolo, paso > 0)
  }

  return (
    <>
      <div ref={caja} style={PEGADA_ARRIBA} className={abierta ? 'contents lg:sticky lg:block lg:w-[336px] lg:shrink-0 lg:self-start' : 'hidden'}>
        <section id="lista-del-grafico" ref={seccion} aria-label={titulo}
          className="fixed inset-x-0 bottom-0 z-[60] flex h-[55vh] flex-col overflow-hidden rounded-t-xl border-t border-line-3 bg-bg-1 text-ink-0 shadow-2xl lg:absolute lg:inset-0 lg:z-auto lg:h-auto lg:rounded-xl lg:border lg:border-line lg:shadow-none">
          {/* La manija de la hoja, en el celular. */}
          <div aria-hidden="true" className="flex justify-center pb-0.5 pt-2 lg:hidden"><span className="h-1 w-10 rounded-full bg-line-3" /></div>

          {buscando ? (
            <Buscar datos={datos} vista={vista} filtro={filtro} recientes={recientes} cliente={cliente}
              onCerrar={() => setBuscando(false)} onElegir={elegir} />
          ) : (
            <>
              <div className="flex h-12 shrink-0 items-center gap-1 pl-4 pr-1 lg:h-[46px] lg:pl-3.5 lg:pr-1.5">
                <h2 className="text-[17px] font-semibold lg:text-[15px]">{titulo}</h2>
                <span className="tabular ml-1 text-[14px] text-ink-2 lg:text-[13px]">{datos.filas.length}</span>
                <span className="flex-1" />
                <BotonIcono etiqueta="Buscar y agregar un activo" onClick={() => { setBuscando(true); setOpciones(false); setMenu(null) }}>
                  <Plus size={19} aria-hidden="true" />
                </BotonIcono>
                <BotonIcono etiqueta="Cómo se ve la lista" expandido={opciones} activo={opciones}
                  onClick={() => { setOpciones(o => !o); setMenu(null) }}>
                  <SlidersHorizontal size={18} aria-hidden="true" />
                </BotonIcono>
                <BotonIcono etiqueta="Cerrar la lista" onClick={cerrar}>
                  <X size={19} aria-hidden="true" className="lg:hidden" />
                  <PanelRightClose size={18} aria-hidden="true" className="hidden lg:block" />
                </BotonIcono>
              </div>

              {chips.length > 1 && (
                <div role="group" aria-label="Qué mostrar" className="flex shrink-0 gap-1.5 overflow-x-auto px-3 pb-2.5 scrollbar-none">
                  {chips.map(c => (
                    <button key={c.id} type="button" aria-pressed={filtro === c.id} onClick={() => cambiar({ filtro: c.id })}
                      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3 text-[13px] font-medium transition-colors lg:min-h-7 lg:px-2.5 lg:text-[12px] ${
                        filtro === c.id ? 'border-data-violet bg-data-violet/15 text-ink-0' : 'border-line text-ink-1 hover:text-ink-0'}`}>
                      {c.bandera && <IconoBandera id={c.bandera} size={12} />}
                      <span className={c.conNombre ? '' : 'italic'}>{c.texto}</span>
                      <span className="tabular text-ink-2">{c.n}</span>
                    </button>
                  ))}
                </div>
              )}

              {/* Los títulos de las columnas, en la compu. */}
              <div aria-hidden="true" className="hidden h-[26px] shrink-0 grid-cols-[28px_minmax(0,1fr)] items-center border-y border-line pr-2.5 text-[11.5px] text-ink-2 lg:grid">
                <span />
                <div className={`grid items-center gap-1.5 ${vista.verVar ? 'grid-cols-[minmax(0,1fr)_70px_56px_60px]' : 'grid-cols-[minmax(0,1fr)_82px_64px]'}`}>
                  <span>Activo</span>
                  <span className="text-right">Último</span>
                  {vista.verVar && <span className="text-right">Var.</span>}
                  <span className="text-right">Var. %</span>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain border-t border-line lg:border-t-0">
                {datos.cargando ? <CargandoLista />
                  : datos.error ? (
                    <p className="px-4 py-4 text-[13px] text-ink-1">
                      No pudimos traer tu lista.{' '}
                      <button type="button" onClick={datos.reintentar} className="font-medium text-data-violet hover:underline">Probar de nuevo</button>
                    </p>
                  ) : !datos.filas.length ? (
                    <div className="px-4 py-5 text-[13px] text-ink-1">
                      <p>Tu lista está vacía. Sumá los activos que querés seguir de cerca: los ves acá al lado del gráfico, con su precio y cuánto se movieron hoy.</p>
                      <button type="button" onClick={() => setBuscando(true)}
                        className="mt-3 inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-data-violet/50 bg-data-violet/15 px-3 text-[13px] font-medium text-ink-0">
                        <Plus size={14} aria-hidden="true" />Agregar un activo
                      </button>
                    </div>
                  ) : secciones.map(sec => {
                    const plegada = plegadas.has(sec.id)
                    return (
                      <div key={sec.id} role="group" aria-label={sec.titulo || titulo}>
                        {sec.titulo && (
                          <button type="button" aria-expanded={!plegada}
                            onClick={() => cambiar({ plegadas: plegada ? vista.plegadas.filter(x => x !== sec.id) : [...vista.plegadas, sec.id] })}
                            className="flex h-[34px] w-full items-center gap-2 border-b border-line bg-bg-0 pl-3 pr-4 text-left text-[12.5px] font-semibold text-ink-1 lg:h-[30px] lg:border-b-0 lg:border-t lg:pl-2 lg:pr-3 lg:text-[12px]">
                            <ChevronDown size={13} aria-hidden="true" className={`shrink-0 text-ink-2 transition-transform ${plegada ? '-rotate-90' : ''}`} />
                            {sec.bandera && <IconoBandera id={sec.bandera} size={12} />}
                            <span className={`truncate ${sec.conNombre ? '' : 'italic'}`}>{sec.titulo}</span>
                            {sec.sub && <span className="shrink-0 font-normal text-ink-2">· {sec.sub}</span>}
                            <span className="flex-1" />
                            <span className="tabular font-medium text-ink-2">{sec.n}</span>
                          </button>
                        )}
                        {!plegada && sec.filas.map(f => (
                          <Renglon key={f.simbolo} f={f} sec={sec} actual={actual?.simbolo === f.simbolo} verVar={vista.verVar}
                            tenes={loTenes(f, datos.tenencias)} nombres={datos.nombres}
                            puedeMover={puedeMover} arrastrar={puedeMover && compu} arrastrando={arrastrando} soltar={soltar}
                            onElegir={() => elegir(f.simbolo)}
                            onBandera={() => { setMenu(m => (m?.simbolo === f.simbolo && !m.conAcciones ? null : { simbolo: f.simbolo, conAcciones: false })); setOpciones(false) }}
                            onMenu={() => { setMenu({ simbolo: f.simbolo, conAcciones: true }); setOpciones(false) }}
                            onMoverUno={(paso) => moverUno(f.simbolo, paso)}
                            onArrastrar={setArrastrando} onSoltarSobre={setSoltar}
                            onSoltar={(destino, despues) => { moverA(arrastrando, destino, despues); setArrastrando(null); setSoltar(null) }} />
                        ))}
                      </div>
                    )
                  })}
                {!datos.cargando && !datos.error && datos.filas.length > 0 && (
                  <p className="px-4 pb-6 pt-3.5 text-[12.5px] leading-snug text-ink-2 lg:hidden">
                    Tocá un activo para verlo en el gráfico. Mantenelo apretado para ponerle bandera, crear una alerta o sacarlo.
                  </p>
                )}
              </div>

              {datos.aviso && (
                <div role="status" className="flex shrink-0 items-start gap-2 border-t border-line px-3.5 py-2 text-[12.5px] text-rendi-neg">
                  <span className="flex-1">{datos.aviso.texto}</span>
                  <button type="button" onClick={datos.cerrarAviso} aria-label="Cerrar el aviso" className="shrink-0 text-ink-2 hover:text-ink-0"><X size={14} aria-hidden="true" /></button>
                </div>
              )}

              {vista.verFicha && !datos.cargando && !datos.error && (
                <FichaCorta activo={activo} fila={actual} datos={datos} deLaFicha={deLaFicha} oculto={hidden} tipoTenido={tipoTenido}
                  destino={banderaAlAgregar({ agrupar: vista.agrupar, filtro })}
                  onBandera={() => actual && setMenu({ simbolo: actual.simbolo, conAcciones: false })} />
              )}
            </>
          )}

          {menu && !buscando && datos.filas.some(f => f.simbolo === menu.simbolo) && (
            <MenuDeBandera fila={datos.filas.find(f => f.simbolo === menu.simbolo)} conAcciones={menu.conAcciones}
              nombres={datos.nombres} puedeMover={puedeMover}
              onCerrar={() => setMenu(null)}
              onElegir={(b) => { datos.ponerBandera(menu.simbolo, b); setMenu(null) }}
              onNombrar={datos.nombrarBandera}
              onMover={(paso) => moverUno(menu.simbolo, paso)}
              onSacar={() => { datos.sacar(menu.simbolo); setMenu(null) }} />
          )}

          {opciones && !buscando && (
            <ComoSeVe vista={vista} onCambiar={(c) => cambiar(c)} onCerrar={() => setOpciones(false)} />
          )}
        </section>
      </div>

      {/* La columnita del borde, en la compu: abre y cierra la lista. */}
      <div className="hidden w-12 shrink-0 flex-col items-center border-l border-line pt-1 lg:flex">
        <button type="button" style={PEGADA_ARRIBA} onClick={() => (abierta ? cerrar() : cambiar({ abierta: true }))} aria-pressed={abierta}
          aria-controls="lista-del-grafico" aria-label={abierta ? `Cerrar ${titulo.toLowerCase()}` : `Abrir ${titulo.toLowerCase()}`}
          className={`sticky inline-flex h-12 w-[42px] flex-col items-center justify-center gap-0.5 rounded-lg border transition-colors ${
            abierta ? 'border-line-3 bg-bg-3 text-ink-0' : 'border-line text-ink-2 hover:text-ink-0'}`}>
          <IconoLista size={18} />
          <span className="text-[10px] font-semibold">Lista</span>
        </button>
      </div>
    </>
  )
}

function BotonIcono({ etiqueta, onClick, expandido, activo = false, children }) {
  return (
    <button type="button" onClick={onClick} aria-label={etiqueta} aria-expanded={expandido}
      className={`inline-flex h-11 w-11 items-center justify-center rounded-lg text-ink-1 hover:text-ink-0 lg:h-[34px] lg:w-[34px] ${activo ? 'bg-bg-3' : ''}`}>
      {children}
    </button>
  )
}

function CargandoLista() {
  return (
    <div className="space-y-2 px-3.5 py-3" aria-label="Cargando tu lista">
      {Array.from({ length: 6 }).map((_, i) => <div key={i} className="esqueleto h-7 rounded bg-bg-2" />)}
    </div>
  )
}

// ─── Un renglón ─────────────────────────────────────────────────────────────

function Renglon({ f, sec, actual, verVar, tenes, nombres, puedeMover, arrastrar, arrastrando, soltar, onElegir, onBandera, onMenu, onMoverUno, onArrastrar, onSoltarSobre, onSoltar }) {
  const n = numerosDe(f)
  const t = tipoInfo(f.tipo)
  const nb = nombreDeBandera(f.bandera, nombres)
  const { local } = lecturaDeSeguido(f.simbolo, f.assetType)
  const nombre = nombreDeActivo(f.ticker, local)
  const moneda = f.pesos ? '$' : 'US$'
  // Mantener apretado (celular): abre el menú y el toque de después no elige.
  const reloj = useRef(null)
  const abrioElMenu = useRef(false)
  const soltarAca = soltar?.simbolo === f.simbolo && arrastrando && arrastrando !== f.simbolo
  const cortar = () => { clearTimeout(reloj.current); reloj.current = null }
  useEffect(() => cortar, [])

  return (
    // Arrastrar, sólo con el mouse (en el celular, mantener apretado abre el menú).
    <div data-simbolo={f.simbolo}
      draggable={arrastrar}
      onDragStart={(e) => { if (!arrastrar) return; e.dataTransfer?.setData?.('text/plain', f.simbolo); onArrastrar(f.simbolo) }}
      onDragOver={(e) => {
        if (!arrastrando || arrastrando === f.simbolo || !sec.filas.some(x => x.simbolo === arrastrando)) return
        e.preventDefault()
        const r = e.currentTarget.getBoundingClientRect?.()
        onSoltarSobre({ simbolo: f.simbolo, despues: r ? e.clientY > r.top + r.height / 2 : false })
      }}
      onDrop={(e) => { if (soltarAca) { e.preventDefault(); onSoltar(f.simbolo, soltar.despues) } }}
      onDragEnd={() => { onArrastrar(null); onSoltarSobre(null) }}
      className={`relative flex items-center border-b border-bg-2 lg:grid lg:grid-cols-[28px_minmax(0,1fr)] lg:border-b-0 lg:pr-2.5 ${
        actual ? 'bg-bg-2' : 'hover:bg-bg-2/60'} ${arrastrando === f.simbolo ? 'opacity-50' : ''}`}
      style={actual ? { boxShadow: 'inset 2px 0 0 rgb(var(--data-violet))' } : undefined}>
      {soltarAca && <span aria-hidden="true" className={`pointer-events-none absolute inset-x-0 h-0.5 bg-data-violet ${soltar.despues ? 'bottom-0' : 'top-0'}`} />}
      <button type="button" onClick={onBandera} aria-haspopup="menu"
        aria-label={`Bandera de ${f.ticker}${t.tag ? ` (${t.corto})` : ''}: ${f.bandera ? nb.texto : 'ninguna'}`}
        className="hidden h-9 w-7 items-center justify-center lg:inline-flex">
        <IconoBandera id={f.bandera} />
      </button>
      <button type="button" aria-current={actual ? 'true' : undefined}
        aria-label={`${f.ticker}${nombre ? `, ${nombre}` : ''}, ${t.corto}: ${f.precio == null ? 'sin precio' : `${moneda} ${n.precio}, ${n.pct} hoy`}${tenes ? ', lo tenés' : ''}. Ver en el gráfico`}
        onClick={() => { if (abrioElMenu.current) { abrioElMenu.current = false; return } onElegir() }}
        onContextMenu={(e) => { e.preventDefault(); cortar(); onMenu() }}
        onPointerDown={(e) => {
          if (e.pointerType !== 'touch') return
          abrioElMenu.current = false
          cortar()
          reloj.current = setTimeout(() => { abrioElMenu.current = true; onMenu() }, MANTENER_MS)
        }}
        onPointerUp={cortar} onPointerCancel={cortar} onPointerMove={(e) => { if (e.pointerType === 'touch' && (Math.abs(e.movementX) > 4 || Math.abs(e.movementY) > 4)) cortar() }}
        onKeyDown={(e) => {
          if (!puedeMover || !e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
          e.preventDefault(); onMoverUno(e.key === 'ArrowUp' ? -1 : 1)
        }}
        className={`flex min-h-14 min-w-0 flex-1 select-none items-center gap-3 pl-4 pr-3.5 text-left lg:grid lg:h-9 lg:min-h-0 lg:gap-1.5 lg:p-0 ${
          verVar ? 'lg:grid-cols-[minmax(0,1fr)_70px_56px_60px]' : 'lg:grid-cols-[minmax(0,1fr)_82px_64px]'}`}>
        <span className="flex min-w-0 flex-1 items-center gap-2.5 lg:gap-[7px]">
          <AssetLogo asset={f.ticker} size={32} className="lg:hidden" />
          <AssetLogo asset={f.ticker} size={20} className="hidden lg:flex" />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="whitespace-nowrap text-[15px] font-semibold lg:text-[13.5px]">{f.ticker}</span>
              {sec.mixta && t.tag && <span className="rounded-sm border border-line-2 px-1 text-[10px] font-semibold text-ink-1">{t.tag}</span>}
              {tenes && <span title="Lo tenés en tu cartera" className="h-1.5 w-1.5 shrink-0 rounded-full bg-data-violet" />}
            </span>
            {nombre && <span className="block truncate text-[12.5px] text-ink-2 lg:hidden">{nombre}</span>}
          </span>
        </span>
        {f.pendiente ? (
          <span className="esqueleto ml-auto h-3 w-16 rounded-sm bg-bg-2 lg:col-span-3" aria-label="Cargando el precio" />
        ) : (
          <>
            <span className="tabular hidden text-right text-[13px] lg:block">{n.precio}</span>
            {verVar && <span className={`tabular hidden text-right text-[13px] lg:block ${TONO[n.tono]}`}>{n.cambio}</span>}
            <span className={`tabular hidden text-right text-[13px] font-medium lg:block ${TONO[n.tono]}`}>{n.pct}</span>
            <span className="flex flex-col items-end gap-0.5 lg:hidden">
              <span className="tabular text-[15px]">{n.precio}</span>
              <span className={`tabular rounded px-1.5 py-px text-[12.5px] font-semibold ${TONO[n.tono]} ${TONO_FONDO[n.tono]}`}>{n.pct}</span>
            </span>
          </>
        )}
      </button>
    </div>
  )
}

// ─── El menú de la bandera (y, mantenido apretado, el del renglón) ─────────

function MenuDeBandera({ fila, conAcciones, nombres, puedeMover, onCerrar, onElegir, onNombrar, onMover, onSacar }) {
  const [editando, setEditando] = useState(null)   // id de la bandera
  const [valor, setValor] = useState('')
  const t = tipoInfo(fila.tipo)
  const caja = useRef(null)
  useEffect(() => { caja.current?.querySelector?.('[aria-checked="true"]')?.focus?.() }, [])

  const editar = (id) => { setEditando(id); setValor(nombres[id] || '') }
  const listo = () => { if (editando) onNombrar(editando, valor); setEditando(null) }

  return (
    <div ref={caja} role="menu" aria-label={`Bandera de ${fila.ticker}`}
      className="absolute inset-x-2.5 bottom-3 z-10 max-h-[calc(100%-24px)] overflow-y-auto rounded-xl border border-line-3 bg-bg-raised pb-2 pt-1.5 shadow-2xl lg:bottom-auto lg:top-[110px]">
      <div className="flex items-center gap-2 pb-2 pl-3.5 pr-1.5 pt-1.5">
        <span className="text-[13px] font-semibold">Bandera de {fila.ticker}</span>
        {t.tag && <span className="rounded-sm border border-line-2 px-1 text-[10px] font-semibold text-ink-1">{t.tag}</span>}
        <span className="flex-1" />
        <button type="button" onClick={onCerrar} aria-label="Cerrar el menú"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-ink-2 hover:text-ink-0 lg:h-[30px] lg:w-[30px]">
          <X size={14} aria-hidden="true" />
        </button>
      </div>
      {BANDERAS.map(b => {
        const n = nombreDeBandera(b.id, nombres)
        const es = fila.bandera === b.id
        return (
          <div key={b.id} className={`flex items-center gap-0.5 px-1.5 ${es ? 'bg-bg-3' : ''}`}>
            {editando === b.id ? (
              <>
                <span className="inline-flex w-[30px] shrink-0 justify-center"><IconoBandera id={b.id} size={14} /></span>
                <input autoFocus value={valor} onChange={e => setValor(e.target.value)} maxLength={30}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); listo() } if (e.key === 'Escape') { e.stopPropagation(); e.nativeEvent?.stopImmediatePropagation?.(); setEditando(null) } }}
                  aria-label={`Nombre de la bandera ${b.color.toLowerCase()}`} placeholder="Ponele un nombre: Vigilar, Dividendos…"
                  className="h-10 min-w-0 flex-1 rounded-lg border border-data-violet bg-bg-1 px-2 text-[16px] text-ink-0 outline-none lg:h-[30px] lg:text-[13px]" />
                <button type="button" onClick={listo}
                  className="ml-1 h-10 shrink-0 rounded-lg bg-data-violet px-2.5 text-[12px] font-semibold text-bg-0 lg:h-[30px]">Listo</button>
              </>
            ) : (
              <>
                <button type="button" role="menuitemradio" aria-checked={es} onClick={() => onElegir(b.id)}
                  className={`flex h-11 min-w-0 flex-1 items-center gap-2.5 px-2 text-left text-[13px] lg:h-9 ${es ? 'font-semibold' : ''} ${n.conNombre ? 'text-ink-0' : 'italic text-ink-2'}`}>
                  <IconoBandera id={b.id} size={14} />
                  <span className="flex-1 truncate">{n.texto}</span>
                  {es && <Check size={15} aria-hidden="true" className="text-data-violet" />}
                </button>
                <button type="button" onClick={() => editar(b.id)} aria-label={`Cambiarle el nombre a la bandera ${b.color.toLowerCase()}`}
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-ink-2 hover:text-ink-0 lg:h-8 lg:w-8">
                  <Pencil size={14} aria-hidden="true" />
                </button>
              </>
            )}
          </div>
        )
      })}
      <div className="my-1.5 h-px bg-line-2" />
      <div className="px-1.5">
        <button type="button" role="menuitemradio" aria-checked={!fila.bandera} onClick={() => onElegir(null)}
          className="flex h-11 w-full items-center gap-2.5 px-2 text-left text-[13px] text-ink-1 lg:h-[34px]">
          <IconoBandera id={null} size={14} />
          Sin bandera
        </button>
      </div>
      {conAcciones && (
        <>
          <div className="my-1.5 h-px bg-line-2" />
          <div className="px-1.5">
            <Link to={`/alertas?new=${encodeURIComponent(miradaSinTenencia(fila.simbolo, fila.assetType).simboloPrecio)}`} role="menuitem"
              className="flex h-11 w-full items-center gap-2.5 px-2 text-[13px] text-ink-0 lg:h-[34px]">
              <Bell size={14} aria-hidden="true" className="text-ink-2" />Crear alerta
            </Link>
            <Link to={urlDeActivo(fila.simbolo)} role="menuitem"
              className="flex h-11 w-full items-center gap-2.5 px-2 text-[13px] text-ink-0 lg:h-[34px]">
              <Search size={14} aria-hidden="true" className="text-ink-2" />Ver ficha
            </Link>
            {puedeMover && (
              <>
                <button type="button" role="menuitem" onClick={() => onMover(-1)}
                  className="flex h-11 w-full items-center gap-2.5 px-2 text-left text-[13px] text-ink-0 lg:h-[34px]">
                  <ArrowUp size={14} aria-hidden="true" className="text-ink-2" />Subirlo
                </button>
                <button type="button" role="menuitem" onClick={() => onMover(1)}
                  className="flex h-11 w-full items-center gap-2.5 px-2 text-left text-[13px] text-ink-0 lg:h-[34px]">
                  <ArrowDown size={14} aria-hidden="true" className="text-ink-2" />Bajarlo
                </button>
              </>
            )}
            <button type="button" role="menuitem" onClick={onSacar}
              className="flex h-11 w-full items-center gap-2.5 px-2 text-left text-[13px] text-rendi-neg lg:h-[34px]">
              <Trash2 size={14} aria-hidden="true" />Sacar de tu lista
            </button>
          </div>
        </>
      )}
      <p className="mx-3.5 mt-1 text-[11.5px] leading-snug text-ink-2">Una bandera por activo. Los nombres son tuyos y se ven igual en la compu y en el celular.</p>
    </div>
  )
}

// ─── «Cómo se ve» ───────────────────────────────────────────────────────────

function ComoSeVe({ vista, onCambiar, onCerrar }) {
  // Funciones y no componentes: un componente definido acá adentro se arma de
  // nuevo en cada cambio y el botón tocado pierde el foco.
  const opcion = (grupo, o) => {
    const elegida = vista[grupo] === o.id
    return (
      <button key={o.id} type="button" aria-pressed={elegida}
        onClick={() => onCambiar(grupo === 'agrupar' ? { agrupar: o.id, filtro: 'todas' } : { [grupo]: o.id })}
        className={`flex min-h-[44px] w-full items-center gap-2.5 px-3.5 py-1 text-left ${elegida ? 'bg-bg-3' : ''}`}>
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] font-medium text-ink-0">{o.titulo}</span>
          <span className="block text-[11.5px] text-ink-2">{o.detalle}</span>
        </span>
        <Check size={15} aria-hidden="true" className={elegida ? 'text-data-violet' : 'invisible'} />
      </button>
    )
  }
  const interruptor = (titulo, on, cambio) => (
    <button type="button" role="switch" aria-checked={on} onClick={() => onCambiar(cambio)}
      className="flex min-h-[40px] w-full items-center gap-2.5 px-3.5 text-left text-[13px] font-medium text-ink-0">
      <span className="flex-1">{titulo}</span>
      <span aria-hidden="true" className={`relative h-[18px] w-[30px] rounded-full transition-colors ${on ? 'bg-data-violet' : 'bg-line-3'}`}>
        <span className={`absolute top-0.5 h-3.5 w-3.5 rounded-full bg-bg-1 transition-all dark:bg-ink-0 ${on ? 'left-[14px]' : 'left-0.5'}`} />
      </span>
    </button>
  )
  return (
    <div role="dialog" aria-label="Cómo se ve la lista"
      className="absolute inset-x-2.5 bottom-3 z-10 max-h-[calc(100%-24px)] overflow-y-auto rounded-xl border border-line-3 bg-bg-raised pb-2.5 pt-1.5 shadow-2xl lg:inset-x-auto lg:bottom-auto lg:right-2 lg:top-11 lg:w-[292px]">
      <div className="flex items-center pl-3.5 pr-1.5">
        <span className="flex-1 pt-1.5 text-[11.5px] font-semibold text-ink-2">Agrupar</span>
        <button type="button" onClick={onCerrar} aria-label="Cerrar «Cómo se ve»"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-ink-2 hover:text-ink-0 lg:h-[30px] lg:w-[30px]">
          <X size={14} aria-hidden="true" />
        </button>
      </div>
      {AGRUPAR.map(o => opcion('agrupar', o))}
      <div className="my-1.5 h-px bg-line-2" />
      <div className="px-3.5 pb-1 pt-1 text-[11.5px] font-semibold text-ink-2">Ordenar adentro de cada grupo</div>
      {ORDENAR.map(o => opcion('orden', o))}
      <div className="my-1.5 h-px bg-line-2" />
      <div className="px-3.5 pb-1 pt-1 text-[11.5px] font-semibold text-ink-2">Mostrar</div>
      {interruptor('Variación en plata (Var.)', vista.verVar, { verVar: !vista.verVar })}
      <span className="hidden lg:block">
        {interruptor('La ficha de abajo', vista.verFicha, { verFicha: !vista.verFicha })}
      </span>
    </div>
  )
}

// ─── Buscar y agregar ───────────────────────────────────────────────────────

function Buscar({ datos, vista, filtro, recientes, cliente, onCerrar, onElegir }) {
  const [consulta, setConsulta] = useState('')
  const campo = useRef(null)
  useEffect(() => { campo.current?.focus?.() }, [])
  const destino = banderaAlAgregar({ agrupar: vista.agrupar, filtro })
  const seguidos = useMemo(() => datos.filas.map(f => ({ symbol: f.simbolo, asset_type: f.assetType })), [datos.filas])
  const resultados = useMemo(() => {
    if (!consulta.trim()) return []
    return opcionesDelBuscador({ consulta, recientes, cliente, lista: seguidos })
      .flatMap(s => s.filas)
      .filter(r => r.origen !== 'escrito')
      .slice(0, 20)
  }, [consulta, recientes, cliente, seguidos])
  const yaEsta = (s) => datos.filas.some(f => f.simbolo === s || mismoGrafico(f.simbolo, s))
  const nb = destino ? nombreDeBandera(destino, datos.nombres) : null

  return (
    <>
      <div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-line pl-3 pr-1.5">
        <Search size={17} aria-hidden="true" className="shrink-0 text-ink-1" />
        <label htmlFor="lista-buscar" className="sr-only">Buscar un activo para agregar</label>
        <input id="lista-buscar" ref={campo} value={consulta} onChange={e => setConsulta(e.target.value)}
          placeholder="Ticker o nombre: GGAL, Apple, bitcoin…" autoComplete="off" spellCheck="false"
          className="h-10 min-w-0 flex-1 rounded-lg border border-line-3 bg-bg-2 px-2.5 text-[16px] text-ink-0 outline-none placeholder:text-ink-3 lg:h-9 lg:text-[14px]" />
        <BotonIcono etiqueta="Cerrar el buscador" onClick={onCerrar}><X size={16} aria-hidden="true" /></BotonIcono>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1.5">
        {!consulta.trim() && (
          <p className="px-3.5 py-3.5 text-[13px] text-ink-1">Escribí el ticker o el nombre. Te mostramos las dos versiones cuando existen: la acción en dólares y el CEDEAR en pesos.</p>
        )}
        {consulta.trim() && !resultados.length && (
          <p className="px-3.5 py-3.5 text-[13px] text-ink-1">No encontramos ese activo. Probá con el ticker (GGAL, AAPL, BTC).</p>
        )}
        {resultados.map(r => {
          // Lo que se guarda: con el nombre con que se mira (una acción argentina,
          // con .BA: su precio de BYMA en pesos; la misma regla de la ficha).
          const simbolo = miradaSinTenencia(r.simbolo).simboloPrecio
          const esta = yaEsta(r.simbolo) || yaEsta(simbolo)
          const tipo = tipoInfo(tipoDeSimbolo(simbolo))
          const ticker = lecturaDeSeguido(simbolo).asset || simbolo
          const pesos = simbolo.endsWith('.BA')
          return (
            <div key={`${r.origen}:${r.simbolo}`} className="flex min-h-12 items-center gap-2.5 py-1 pl-3.5 pr-2.5">
              <AssetLogo asset={ticker} size={26} />
              <button type="button" onClick={() => onElegir(simbolo)} aria-label={`Ver ${ticker} (${tipo.corto}) en el gráfico`}
                className="min-w-0 flex-1 text-left">
                <span className="flex items-baseline gap-1.5">
                  <span className="text-[14px] font-semibold text-ink-0">{ticker}</span>
                  <span className="truncate text-[12.5px] text-ink-1">{(r.nombre || '').replace(/ \(CEDEAR\)$/, '')}</span>
                </span>
                <span className="block text-[11.5px] text-ink-2">{tipo.corto} · {pesos ? 'en pesos' : 'en dólares'}</span>
              </button>
              {esta ? (
                <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-[12px] text-ink-2">
                  <Check size={13} aria-hidden="true" className="text-rendi-pos" />En tu lista
                </span>
              ) : (
                <button type="button" onClick={() => datos.agregar(simbolo, destino)} aria-label={`Agregar ${ticker} (${tipo.corto}) a tu lista`}
                  disabled={datos.filas.length >= TOPE}
                  className="inline-flex min-h-9 shrink-0 items-center gap-1 whitespace-nowrap rounded-lg border border-data-violet/50 bg-data-violet/15 px-2.5 text-[12.5px] font-medium text-ink-0 disabled:opacity-40 lg:min-h-[30px]">
                  <Plus size={13} aria-hidden="true" />Agregar
                </button>
              )}
            </div>
          )
        })}
      </div>
      {datos.aviso && <p role="status" className="shrink-0 border-t border-line px-3.5 py-2 text-[12.5px] text-rendi-neg">{datos.aviso.texto}</p>}
      <p className="shrink-0 border-t border-line px-3.5 pb-3 pt-2.5 text-[12px] leading-snug text-ink-2">
        {nb ? <>Lo que agregues entra con la bandera «<span className={nb.conNombre ? '' : 'italic'}>{nb.texto}</span>», la que estás mirando.</>
          : 'Lo que agregues entra sin bandera: se la ponés tocando la banderita de su renglón.'}
        {' '}Tenés <span className="tabular">{datos.filas.length}</span> de {TOPE}.
      </p>
    </>
  )
}

// ─── La ficha corta del que estás mirando (en la compu) ────────────────────

/** Con qué nombre se guarda en tu lista lo que estás mirando: { simbolo,
 *  assetType }. Una acción argentina en BYMA, con .BA (su precio en pesos, el de la
 *  ficha); la MISMA acción que tenés en Nueva York (tu GGAL de Schwab), sin .BA
 *  y con tipo STOCK: es la regla de la lista para saber que es la de afuera
 *  (listaTecnica.lecturaDeSeguido: «AGRO» STOCK es Adecoagro). */
function paraGuardar(simbolo, local) {
  const s = String(simbolo || '').toUpperCase()
  if (local) return { simbolo: s.endsWith('.BA') ? s : `${s}.BA`, assetType: null }
  return { simbolo: s, assetType: tipoDeSimbolo(s) === 'arg' ? 'STOCK' : null }
}

function FichaCorta({ activo, fila, datos, deLaFicha, oculto, destino, tipoTenido, onBandera }) {
  const sym = fila?.simbolo || String(activo || '').toUpperCase()
  const { asset, local: localDeLaLista } = lecturaDeSeguido(sym, fila?.assetType)
  const ticker = fila?.ticker || asset || sym
  const tipo = fila?.tipo || tipoTenido || tipoDeSimbolo(sym)
  const t = tipoInfo(tipo)
  // Si es de BYMA lo dice la ficha del activo abierto (tus lotes); si no, la regla de lo que no tenés.
  const local = deLaFicha && deLaFicha.activo === activo ? !!deLaFicha.accionLocal : localDeLaLista
  const lectura = lecturaCorta(datos.indice?.get(clave(asset, local)) || null)
  const agg = deLaFicha && deLaFicha.activo === activo ? deLaFicha.agg : null
  const tenes = agg?.lots?.length ? textoLoTenes({ qty: agg.qty, pnlPct: agg.pnlPct, tipo, ticker, oculto }) : null
  const nombre = nombreDeActivo(ticker, local)
  const nb = fila ? nombreDeBandera(fila.bandera, datos.nombres) : null
  const n = fila ? numerosDe(fila) : null
  const rueda = textoDeLaRueda(fila)
  const pesos = fila ? fila.pesos : sym.endsWith('.BA')
  const alerta = `/alertas?new=${encodeURIComponent(fila ? miradaSinTenencia(sym, fila.assetType).simboloPrecio : paraGuardar(sym, local).simbolo)}`

  return (
    <div className="hidden shrink-0 flex-col gap-2 border-t border-line px-3.5 py-3 lg:flex" aria-label={`${ticker}, el que estás mirando`} role="group">
      <div className="flex items-center gap-2.5">
        <AssetLogo asset={ticker} size={30} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[15px] font-semibold">{ticker}</span>
            {nombre && <span className="truncate text-[13px] text-ink-1">{nombre}</span>}
          </div>
          <div className="text-[11.5px] text-ink-2">{t.corto} · {pesos ? 'en pesos' : 'en dólares'}</div>
        </div>
        {fila && (
          <button type="button" onClick={onBandera} aria-haspopup="menu" aria-label={`Cambiar la bandera de ${ticker}`}
            className="inline-flex h-7 max-w-[120px] shrink-0 items-center gap-1.5 rounded-full border border-line-2 bg-bg-2 px-2.5 text-[12px] font-medium">
            <IconoBandera id={fila.bandera} size={12} />
            <span className={`truncate ${fila.bandera && !nb.conNombre ? 'italic' : ''}`}>{fila.bandera ? nb.texto : 'Sin bandera'}</span>
          </button>
        )}
      </div>
      {n && fila.precio != null && (
        <div className="flex items-baseline gap-2">
          <span className="tabular text-[22px] font-semibold tracking-tight">{pesos ? '$' : 'US$'} {n.precio}</span>
          <span className={`tabular text-[13.5px] font-medium ${TONO[n.tono]}`}>{n.cambio}</span>
          <span className={`tabular text-[13.5px] font-medium ${TONO[n.tono]}`}>{n.pct}</span>
        </div>
      )}
      {rueda && (
        <div className="flex items-center gap-1.5 text-[12px] text-ink-1">
          <span aria-hidden="true" className={`h-[7px] w-[7px] rounded-full ${rueda.abierto ? 'bg-rendi-pos' : 'bg-ink-3'}`} />{rueda.texto}
        </div>
      )}
      {lectura && (
        <div className="flex flex-wrap gap-1.5">
          <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-line bg-bg-2 px-2 text-[11.5px] text-ink-1">
            <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${lectura.largo.id === 'alcista' ? 'bg-rendi-pos' : lectura.largo.id === 'bajista' ? 'bg-rendi-neg' : 'bg-ink-3'}`} />
            {lectura.largo.texto}
          </span>
          {lectura.impulso && (
            <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-line bg-bg-2 px-2 text-[11.5px] text-ink-1">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-data-amber" />{lectura.impulso.texto}
            </span>
          )}
        </div>
      )}
      {tenes && <div className="tabular text-[12.5px] text-ink-1"><span className="font-semibold text-data-violet">Lo tenés:</span> {tenes}</div>}
      <div className="flex items-center gap-1.5">
        <Link to={alerta} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-2 bg-bg-2 px-2.5 text-[12.5px] font-medium text-ink-0 hover:border-ink-3">
          <Bell size={14} aria-hidden="true" />Crear alerta
        </Link>
        <Link to={urlDeActivo(sym)} className="inline-flex h-8 items-center px-2 text-[12.5px] font-medium text-data-violet hover:underline">Ver ficha →</Link>
        <span className="flex-1" />
        {fila ? (
          <button type="button" onClick={() => datos.sacar(fila.simbolo)} aria-label={`Sacar ${ticker} de tu lista`}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 hover:text-rendi-neg">
            <X size={15} aria-hidden="true" />
          </button>
        ) : (
          <button type="button" onClick={() => { const g = paraGuardar(sym, local); datos.agregar(g.simbolo, destino, g.assetType) }} disabled={datos.filas.length >= TOPE}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-data-violet/50 bg-data-violet/15 px-2.5 text-[12.5px] font-medium text-ink-0 disabled:opacity-40">
            <Plus size={13} aria-hidden="true" />Agregar a tu lista
          </button>
        )}
      </div>
    </div>
  )
}
