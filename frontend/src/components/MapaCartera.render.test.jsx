// Lo que DIBUJA el Panorama de Análisis técnico (lienzo «1 · Panorama», 30/10)
// CON y SIN «Ocultar saldos», con los mismos datos. Lo que importa:
//   · sin ojito: el mapa con un cuadrito por activo, de tamaño según su peso,
//     con su % y su link a la ficha; el chip contra la semana pasada; los
//     cambios agrupados por día con su campanita;
//   · con ojito: NADA dice cuánto pesa cada cosa. Ni un %, ni el tamaño de los
//     cuadritos (todos iguales), ni el orden (alfabético, no de más a menos
//     plata), ni el de los nombres de la tarjeta grande.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

const privacidad = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', () => ({ usePrivacy: () => ({ hidden: privacidad.hidden, toggle: () => {} }) }))
vi.mock('../utils/api', () => ({ api: { get: vi.fn(async () => ({ items: [] })), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../hooks/usePlanFeatures', () => ({ usePlanFeatures: () => ({}) }))

import { Panorama } from '../pages/AnalisisTecnico'
import { hoyISO } from '../utils/fecha'

const HOY = hoyISO()
const haceSiete = new Date(Date.parse(HOY + 'T00:00:00Z') - 7 * 86400000).toISOString().slice(0, 10)
const fila = (nombre, peso, tendencia, extra = {}) => ({
  clave: `${nombre}|0`, nombre, ruta: nombre, tenes: true, peso, vigente: true, fondo: { id: tendencia },
  desdeMax: { pct: -5, enMaximo: false, anioCompleto: true }, ...extra,
})
// Pesos bien distintos (como en el lienzo) para que el tamaño se note.
const FILAS = [
  fila('GGAL', 40, 'alcista', { desdeMax: { pct: 0, enMaximo: true, anioCompleto: true } }),
  fila('MELI', 30, 'bajista'),
  fila('KO', 10, 'bajista'),
  fila('AL30', 5, 'sin'),
  { clave: 'TSLA|0', nombre: 'TSLA', ruta: 'TSLA', tenes: false, peso: 0, vigente: true, fondo: { id: 'alcista' } },
]
const CAMBIO = (asset, tipo, fecha, extra = {}) => ({
  asset, local: false, ficha: asset, tipo, fecha, sentido: 'arriba', etiqueta: 'Largo plazo', tono: 'pos',
  texto: 'superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista.', extra: null,
  tenes: true, watchlist: false, peso: 0.4, tesis: null, ...extra,
})
const SEMANA = {
  datos: {
    hasta: HOY, canal: 'mail', proximo_resumen: '2026-11-07',
    alcista: {
      pct: 40,
      grupos: {
        alcista: { pct: 40, fraccion: 0.4, nombres: ['GGAL'] },
        bajista: { pct: 40, fraccion: 0.4, nombres: ['MELI', 'KO'] },
        sin: { pct: 20, fraccion: 0.2, nombres: ['efectivo', 'AL30'] },
      },
      motivos: [{ porque: 'no_se_mide', nombres: ['efectivo', 'AL30'] }],
      semana_pasada: { semana: haceSiete, pct: 32 },
    },
    tenes: { activos: 3, con_cambios: 2 }, watchlist: 1,
    senales: [
      CAMBIO('GGAL', 'media200', HOY),
      CAMBIO('KO', 'rsi_bajo_30', HOY, { tono: 'rsi', etiqueta: 'Cayó muy rápido', texto: 'cayó muy rápido: su impulso (RSI) bajó de 30 y quedó en 28.', peso: 0.1 }),
      // Sin alerta para la fuerza de la tendencia (ADX): sin campanita.
      CAMBIO('MELI', 'adx23', haceSiete, { tono: 'adx', etiqueta: 'Toma dirección', texto: 'dejó de moverse de forma lateral y tomó una dirección.', peso: 0.3 }),
    ],
  },
  error: false,
}
// `sinMedir`: lo que manda POST /api/tecnico/lista junto con las filas (el
// mismo pedido): acá hay efectivo y no plazos fijos.
const LISTA = { cargando: false, error: null, sinMedir: { efectivo: 0.15, plazos_fijos: null } }

function dibujar(hidden) {
  privacidad.hidden = hidden
  return renderToStaticMarkup(
    <MemoryRouter>
      <Panorama lista={LISTA} filas={FILAS} semana={SEMANA} hidden={hidden} onVer={() => {}} onPestana={() => {}} />
    </MemoryRouter>)
}
const sinEtiquetas = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')
const elMapa = (html) => html.slice(html.indexOf('aria-label="Mapa de tu cartera"'), html.indexOf('aria-label="Lo que cambió esta semana"'))
/** [{ nombre, area }] de los cuadritos, en el orden en que se dibujan. */
function cuadritos(html) {
  const out = []
  const re = /<li class="absolute p-0.5" style="left:([\d.e-]+)%;top:([\d.e-]+)%;width:([\d.e-]+)%;height:([\d.e-]+)%"[^>]*>([\s\S]*?)<\/li>/g
  let m
  while ((m = re.exec(html))) {
    const nombre = (m[0].match(/aria-label="([^"·]+)/) || [])[1]?.trim()
    out.push({ nombre, area: (Number(m[3]) * Number(m[4])) / 10000 })
  }
  return out
}

describe('el Panorama, sin ocultar saldos', () => {
  it('el mapa: un cuadrito por activo que tenés, del tamaño de lo que pesa, con su % y su ficha', () => {
    const html = dibujar(false)
    const c = cuadritos(elMapa(html))
    // GGAL 40, MELI 30, el efectivo (100 − 85 = 15), KO 10, AL30 5. TSLA (sólo watchlist) no.
    expect(c.map(x => x.nombre)).toEqual(['GGAL', 'MELI', 'Efectivo', 'KO', 'AL30'])
    expect(c[0].area).toBeCloseTo(0.40, 3)
    expect(c[4].area).toBeCloseTo(0.05, 3)
    const t = sinEtiquetas(elMapa(html))
    expect(t).toContain('GGAL 40%')
    expect(elMapa(html)).toContain('href="/activo/GGAL"')
    expect(elMapa(html)).toContain('aria-label="GGAL · 40% de tu cartera · tendencia alcista"')
    expect(elMapa(html)).not.toContain('TSLA')
  })

  it('la tarjeta grande: el chip contra la semana pasada y qué lo movió', () => {
    const t = sinEtiquetas(dibujar(false))
    expect(t).toContain('40% de tu cartera está en activos con tendencia alcista de largo plazo')
    expect(t).toContain('▲ 8 puntos más que la semana pasada')
    expect(t).toMatch(/Qué lo movió: GGAL \(40% de tu cartera\) pasó a alcista el \S+ \d\d\/\d\d\./)
  })

  it('los cambios agrupados por día, con «Ver el gráfico» y la campanita (menos el ADX, que no tiene alerta)', () => {
    const html = dibujar(false)
    const cambios = html.slice(html.indexOf('aria-label="Lo que cambió esta semana"'), html.indexOf('aria-label="Tu lista de un vistazo"'))
    expect((cambios.match(/<h3 /g) || []).length).toBe(2)               // hoy y hace una semana
    expect((cambios.match(/Ver el gráfico/g) || []).length).toBe(3)
    expect(cambios).toContain('aria-label="Avisame cuando cruce su promedio de 200 días"')
    expect(cambios).toContain('aria-label="Avisame cuando su impulso (RSI) vuelva a superar 30"')
    expect((cambios.match(/aria-label="Avisame/g) || []).length).toBe(2)
  })

  it('tu lista de un vistazo, el resumen del sábado y un solo «no es una recomendación»', () => {
    const t = sinEtiquetas(dibujar(false))
    expect(t).toContain('5 activos')
    // GGAL y TSLA (Tu lista suma tu watchlist).
    expect(t).toContain('2 con tendencia alcista de largo plazo')
    expect(t).toContain('1 en su máximo del año')
    expect(t).toContain('El resumen de la semana te llega el sábado 07/11 a las 10:00, por mail.')
    expect(t).toContain('Cambiar cómo me llega')
    expect(t.match(/no es una recomendación/g)).toHaveLength(1)
    // Las tres tarjetas de abajo de antes (repetían las pestañas) ya no están.
    expect(t).not.toContain('Compará tus activos')
  })
})

describe('el Panorama, con «Ocultar saldos»', () => {
  it('ningún % en toda la pantalla (los que había sin ocultar, todos afuera)', () => {
    expect(sinEtiquetas(dibujar(false))).toMatch(/\d%/)
    const html = dibujar(true)
    expect(sinEtiquetas(html)).not.toMatch(/\d\s?%/)
    expect(html).not.toMatch(/aria-label="[^"]*\d%/)
    expect(sinEtiquetas(html)).not.toContain('puntos más')
  })

  it('el mapa: todos los cuadritos del mismo tamaño y en orden alfabético', () => {
    const c = cuadritos(elMapa(dibujar(true)))
    expect(c.map(x => x.nombre)).toEqual(['AL30', 'Efectivo', 'GGAL', 'KO', 'MELI'])
    for (const x of c) expect(x.area).toBeCloseTo(1 / 5, 6)
    expect(sinEtiquetas(elMapa(dibujar(true)))).toContain('Con los saldos ocultos, todos van del mismo tamaño.')
  })

  it('los nombres de la tarjeta grande, en orden alfabético (el servidor los manda de más a menos plata)', () => {
    const sin = sinEtiquetas(dibujar(false))
    expect(sin).toContain('bajista · MELI, KO')
    const con = sinEtiquetas(dibujar(true))
    expect(con).toContain('bajista · KO, MELI')
    expect(con).toContain('AL30, efectivo :')
  })

  it('la misma pantalla con y sin ojito: mismos activos, mismos cambios', () => {
    const a = cuadritos(elMapa(dibujar(false))).map(x => x.nombre).sort()
    const b = cuadritos(elMapa(dibujar(true))).map(x => x.nombre).sort()
    expect(b).toEqual(a)
    expect((dibujar(true).match(/Ver el gráfico/g) || []).length).toBe(3)
  })
})
