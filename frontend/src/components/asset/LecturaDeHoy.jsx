// LecturaDeHoy — la tarjeta de arriba del gráfico técnico en la ficha del
// activo (lienzo «3a · Ficha en línea»): una frase con la conclusión y cuatro
// casilleros dibujados — largo plazo (200 días), mediano plazo (50 días),
// impulso (RSI, un velocímetro de 0 a 100) y fuerza de la tendencia (ADX,
// cinco barritas).
// ════════════════════════════════════════════════════════════════════════════
// No hace cuentas: las palabras y los colores son los de las tarjetas de
// utils/tecnico.js (`tarjetas()`) y los números, los de la lectura del
// servidor (`actual.lectura`). Lo que arma la frase y lee «desde cuándo» vive
// en utils/lecturaDeHoy.js. Sin datos (poca historia), cada casillero dice por
// qué, como las tarjetas.
//
// Una sola pantalla para compu y celular (R6): en la compu los cuatro
// casilleros van en fila; en el celular se deslizan de costado. Colores sólo
// por variables del tema (R8); números en Geist `tabular` (R1).
// La pestaña «Gráfico» de Análisis técnico no la muestra (`soloGrafico` de
// LecturaTecnica).
//
// `boton` y `panel`: «✦ Analizar con Mervall-E» (ResumenMervalle.jsx, mockup
// aprobado por Nico el 30/10). El botón va en la cabecera, al lado del día de
// cierre; lo que abre, abajo de los casilleros, dentro de la misma tarjeta.

import { useId } from 'react'
import { RSI_CASTIGADO, RSI_ESTIRADO, fmtAdx } from '../../utils/tecnico'
import { fraseDeHoy, ladoDelRsi, ultimoCruce } from '../../utils/lecturaDeHoy'

const v = (t) => `rgb(var(--${t}))`
const TEXTO_TONO = { pos: 'text-rendi-pos', neg: 'text-rendi-neg', neutro: 'text-ink-0' }
const PUNTO_TONO = { pos: 'bg-rendi-pos', neg: 'bg-rendi-neg', neutro: 'bg-ink-3' }
const FONDO_TONO = { pos: 'from-rendi-pos/10', neg: 'from-rendi-neg/10', neutro: 'from-bg-2/60' }

const pct1 = (x) => `${Math.abs(x).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`
const conSigno = (x) => `${x >= 0 ? '+' : '−'}${pct1(x)}`

// «jueves 29/10» (las fechas del servidor son días, sin hora: se leen en UTC).
function diaDeCierre(iso) {
  if (!iso) return ''
  const f = new Date(`${iso}T12:00:00Z`)
  const dia = f.toLocaleDateString('es-AR', { weekday: 'long', timeZone: 'UTC' })
  return `${dia} ${iso.slice(8, 10)}/${iso.slice(5, 7)}`
}
// 29/10, o 29/10/25 si es de otro año que el cierre.
function fechaDelCruce(iso, cierre) {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}${iso.slice(0, 4) !== (cierre || '').slice(0, 4) ? `/${iso.slice(2, 4)}` : ''}`
}

export default function LecturaDeHoy({ lectura, lista, puntos = [], adxTope = 50, boton = null, panel = null }) {
  if (!lectura?.ruedas || !lista?.length) return null
  const de = (id) => lista.find(t => t.id === id)
  const frase = fraseDeHoy(lista)
  // Las dos barritas de plazo en la misma escala, así se comparan a ojo.
  const dists = [lectura.dist_media200, lectura.dist_media50].filter(x => x != null).map(Math.abs)
  const escala = Math.max(10, Math.ceil(Math.max(0, ...dists) / 5) * 5)
  const tono = frase?.tono || 'neutro'
  return (
    // Un `div` con rol de región y no un <section>: la ficha busca su sección
    // del gráfico (la de «Pantalla completa») como la primera de la página.
    <div role="region" aria-label="La lectura de hoy" className="mb-4 overflow-hidden rounded-xl border border-line/60 bg-bg-1">
      <div className={`flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line/60 bg-gradient-to-r ${FONDO_TONO[tono]} to-transparent px-4 py-3`}>
        <p className="flex min-w-0 items-start gap-2.5 text-[14px] leading-snug">
          <span aria-hidden="true" className={`mt-1.5 h-2 w-2 flex-none rounded-full ${PUNTO_TONO[tono]}`} />
          <span><b className="font-semibold text-ink-0">La lectura de hoy:</b>{' '}
            <span className="text-ink-1">{frase?.texto || 'todavía no hay historia para leer la tendencia.'}</span></span>
        </p>
        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 sm:w-auto">
          <span className="text-[12px] font-medium text-ink-2">cierre del {diaDeCierre(lectura.fecha)}</span>
          {boton}
        </div>
      </div>
      <div className="flex snap-x snap-mandatory overflow-x-auto scrollbar-none lg:grid lg:grid-cols-4 lg:overflow-visible">
        <CasilleroPlazo t={de('fondo')} dias={200} dist={lectura.dist_media200} escala={escala} color={v('rendi-accent')}
          cruce={ultimoCruce(puntos, 's200')} cierre={lectura.fecha} ruedas={lectura.ruedas} />
        <CasilleroPlazo t={de('corto')} dias={50} dist={lectura.dist_media50} escala={escala} color={v('cat-orange')}
          cruce={ultimoCruce(puntos, 's50')} cierre={lectura.fecha} ruedas={lectura.ruedas} />
        <CasilleroRsi t={de('rsi')} ruedas={lectura.ruedas} />
        <CasilleroAdx t={de('fuerza')} adxTope={adxTope} />
      </div>
      {panel}
    </div>
  )
}

// El nombre de cada casillero es su rótulo (`aria-labelledby`): un
// `aria-label` propio repetía el de los paneles del gráfico («Fuerza de la
// tendencia (ADX)…»), que la ficha busca por ese nombre.
function Casillero({ id, children, fila = false }) {
  return (
    <div role="group" aria-labelledby={id}
      className={`flex w-[78%] flex-none snap-start border-r border-line/60 px-4 py-3.5 last:border-r-0 sm:w-[46%] lg:w-auto lg:min-w-0 ${fila ? 'flex-row items-center gap-3.5' : 'flex-col gap-1.5'}`}>
      {children}
    </div>
  )
}
const Rotulo = ({ id, children }) => <span id={id} className="text-[12px] font-medium text-ink-2">{children}</span>
const PorQue = ({ children }) => <span className="text-[12px] leading-snug text-ink-2">{children}</span>

// Largo o mediano plazo: la palabra de la tarjeta y una barrita con el precio
// contra su promedio (la raya del medio, del color de esa línea en el gráfico).
function CasilleroPlazo({ t, dias, dist, escala, color, cruce, cierre, ruedas }) {
  const id = useId()
  const etiqueta = `${dias === 200 ? 'Largo plazo' : 'Mediano plazo'} · ${dias} días`
  if (!t || dist == null || (t.tono !== 'pos' && t.tono !== 'neg')) {
    return (
      <Casillero id={id}>
        <Rotulo id={id}>{etiqueta}</Rotulo>
        <span className="text-[17px] font-semibold text-ink-0">{t?.veredicto || 'Faltan datos'}</span>
        <PorQue>{t?.texto || `Para calcularlo hacen falta ${dias} días de mercado y este activo tiene ${ruedas}.`}</PorQue>
      </Casillero>
    )
  }
  const arriba = dist >= 0
  const x = 100 + (Math.max(-escala, Math.min(escala, dist)) / escala) * 92
  const desde = cruce && cruce.arriba === arriba ? ` · desde el ${fechaDelCruce(cruce.fecha, cierre)}` : ''
  const relleno = v(arriba ? 'rendi-pos-fill' : 'rendi-neg-fill')
  return (
    <Casillero id={id}>
      <Rotulo id={id}>{etiqueta}</Rotulo>
      <span className={`text-[17px] font-semibold ${TEXTO_TONO[t.tono]}`}>{t.veredicto}</span>
      <svg viewBox="0 0 200 26" width="100%" height="26" aria-hidden="true" preserveAspectRatio="none">
        <line x1="4" y1="13" x2="196" y2="13" stroke={v('bg-3')} strokeWidth="4" strokeLinecap="round" />
        <line x1="100" y1="13" x2={x} y2="13" stroke={relleno} strokeWidth="4" strokeLinecap="round" />
        <line x1="100" y1="3" x2="100" y2="23" stroke={color} strokeWidth="2" />
        <circle cx={x} cy="13" r="5" fill={v('ink-0')} />
      </svg>
      <span className="text-[12px] text-ink-2 tabular">
        <b className="font-semibold text-ink-0">{conSigno(dist)}</b> {arriba ? 'arriba' : 'abajo'} de su promedio{desde}
      </span>
    </Casillero>
  )
}

// Un punto del velocímetro: 0 a la izquierda, 100 a la derecha, por arriba.
function enArco(valor, r = 40) {
  const a = Math.PI * (1 - Math.min(100, Math.max(0, valor)) / 100)
  return [50 + r * Math.cos(a), 50 - r * Math.sin(a)]
}
const arco = (de, a) => {
  const [x1, y1] = enArco(de), [x2, y2] = enArco(a)
  return `M${x1.toFixed(1)} ${y1.toFixed(1)} A40 40 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)}`
}

// El impulso (RSI): un velocímetro de 0 a 100 con las zonas de 30 y 70 (los
// cortes de la tarjeta), el número y su veredicto.
function CasilleroRsi({ t, ruedas }) {
  const id = useId()
  const etiqueta = 'Impulso (RSI)'
  if (!t || t.rsi == null) {
    return (
      <Casillero id={id}>
        <Rotulo id={id}>{etiqueta}</Rotulo>
        <span className="text-[17px] font-semibold text-ink-0">Faltan datos</span>
        <PorQue>{`Todavía no hay historia para calcularlo: este activo tiene ${ruedas} días de mercado.`}</PorQue>
      </Casillero>
    )
  }
  const lado = ladoDelRsi(t.rsi)
  const [ax, ay] = enArco(t.rsi, 34)
  return (
    <Casillero id={id} fila>
      <svg width="86" height="52" viewBox="0 0 100 58" aria-hidden="true" className="flex-none">
        <path d={arco(0, 100)} fill="none" stroke={v('bg-3')} strokeWidth="9" strokeLinecap="round" />
        <path d={arco(0, RSI_CASTIGADO)} fill="none" stroke={v('rendi-neg-fill')} strokeOpacity="0.6" strokeWidth="9" strokeLinecap="round" />
        <path d={arco(RSI_ESTIRADO, 100)} fill="none" stroke={v('rendi-pos-fill')} strokeOpacity="0.6" strokeWidth="9" strokeLinecap="round" />
        <line x1="50" y1="50" x2={ax.toFixed(1)} y2={ay.toFixed(1)} stroke={v('ink-0')} strokeWidth="3" strokeLinecap="round" />
        <circle cx="50" cy="50" r="4.5" fill={v('ink-0')} />
      </svg>
      <div className="flex min-w-0 flex-col gap-0.5">
        <Rotulo id={id}>{etiqueta}</Rotulo>
        <span className="text-[17px] font-semibold text-ink-0 tabular">{Math.round(t.rsi)}</span>
        <span className={`text-[12px] ${lado > 0 ? 'text-rendi-pos' : lado < 0 ? 'text-rendi-neg' : 'text-ink-1'}`}>{t.veredicto}</span>
      </div>
    </Casillero>
  )
}

// La fuerza de la tendencia (ADX): cinco barritas que crecen, de 0 a 50 (la
// escala del panel del ADX del gráfico), con su número y el veredicto de la
// tarjeta. Sin ADX, el rótulo no lo nombra: dice por qué no hay.
function CasilleroAdx({ t, adxTope }) {
  const id = useId()
  if (!t || t.adx == null) {
    const etiqueta = 'Fuerza de la tendencia'
    return (
      <Casillero id={id}>
        <Rotulo id={id}>{etiqueta}</Rotulo>
        <span className="text-[17px] font-semibold text-ink-0">{t?.veredicto || 'Faltan datos'}</span>
        {t?.texto && <PorQue>{t.texto}</PorQue>}
      </Casillero>
    )
  }
  const etiqueta = 'Fuerza de la tendencia (ADX)'
  const prendidas = Math.min(5, Math.max(t.adx > 0 ? 1 : 0, Math.ceil(t.adx / (adxTope / 5))))
  const color = v(t.tono === 'pos' ? 'rendi-pos-fill' : t.tono === 'neg' ? 'rendi-neg-fill' : 'rendi-accent')
  return (
    <Casillero id={id}>
      <Rotulo id={id}>{etiqueta}</Rotulo>
      <span className="text-[17px] font-semibold text-ink-0 tabular">
        {fmtAdx(t.adx)}
      </span>
      <span aria-hidden="true" className="flex h-[22px] items-end gap-1">
        {[8, 11, 14, 18, 22].map((alto, k) => (
          <span key={alto} className="w-4 rounded-xs" style={{ height: alto, background: k < prendidas ? color : v('bg-3') }} />
        ))}
      </span>
      <span className={`text-[12px] ${TEXTO_TONO[t.tono] === 'text-ink-0' ? 'text-ink-1' : TEXTO_TONO[t.tono]}`}>{t.veredicto}</span>
    </Casillero>
  )
}
