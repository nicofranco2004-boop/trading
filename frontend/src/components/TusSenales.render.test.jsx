// Lo que DIBUJA «Tus señales» (pieza 15) con una respuesta de GET /api/tus-senales
// armada como la del servidor (backend/senales_semana.py): las tres tarjetas, el
// filtro, la lista por día, la frase de posibilidad de «cayó muy rápido» y lo
// que se esconde con «Ocultar saldos».
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { TusSenalesVista } from './TusSenales'
import {
  filtrar, porDia, tarjetas, deQuien, pesoTxt, diaLargo, semanaPasadaTxt, rutaDeFicha, boton,
} from '../utils/tusSenales'

const POSIBILIDAD = 'En la medición de Rendi (70 activos, 2 años), después de caídas así el precio rebotó algo más seguido que lo que siguió cayendo. Es una posibilidad, no una certeza.'

const DATOS = {
  desde: '2026-10-17', hasta: '2026-10-24',
  alcista: { pct: 54, semana_pasada: { semana: '2026-10-17', pct: 61 } },
  tenes: { activos: 7, con_cambios: 3 },
  watchlist: 4,
  canal: 'no',
  senales: [
    { asset: 'MELI', local: false, ficha: 'MELI', tenes: true, watchlist: false, peso: 0.12, tesis: null,
      tipo: 'rsi_bajo_30', fecha: '2026-10-23', sentido: 'abajo', etiqueta: 'Cayó muy rápido', tono: 'rsi',
      texto: 'tiene la fuerza (RSI) en 28: una semana de mercado antes estaba en 52.', extra: POSIBILIDAD },
    { asset: 'YPFD', local: true, ficha: 'YPFD', tenes: true, watchlist: false, peso: 0.14, tesis: null,
      tipo: 'maximo_12m', fecha: '2026-10-23', sentido: 'arriba', etiqueta: 'Máximo del año', tono: 'pos',
      texto: 'cerró en su precio más alto de los últimos 12 meses.', extra: null },
    { asset: 'AAPL', local: false, ficha: 'AAPL', tenes: true, watchlist: false, peso: 0.11, tesis: 'El recambio de iPhone.',
      tipo: 'media200', fecha: '2026-10-20', sentido: 'abajo', etiqueta: 'Tendencia de fondo', tono: 'neg',
      texto: 'quedó abajo de su promedio de 200 días: la tendencia de fondo se volvió bajista.', extra: null },
    { asset: 'PAMP', local: true, ficha: 'PAMP.BA', tenes: false, watchlist: true, peso: null, tesis: null,
      tipo: 'adx23', fecha: '2026-10-19', sentido: 'arriba', etiqueta: 'Fuerza de la tendencia', tono: 'adx',
      texto: 'tiene el ADX en 24: pasó 23, deja de ir de costado y marca dirección, para arriba.', extra: null },
  ],
}

const dibujar = (props) => renderToStaticMarkup(
  <TusSenalesVista datos={DATOS} hidden={false} filtro="todo" onFiltro={() => {}} onVer={() => {}}
    onCanal={() => {}} {...props} />,
)
const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ')

describe('tusSenales: cuentas', () => {
  it('agrupa por día, el más nuevo primero, con el nombre del día', () => {
    const d = porDia(DATOS.senales)
    expect(d.map(x => x.dia)).toEqual(['Viernes 23/10', 'Martes 20/10', 'Lunes 19/10'])
    expect(d[0].items.map(s => s.asset)).toEqual(['MELI', 'YPFD'])
    expect(diaLargo('2026-10-24')).toBe('Sábado 24/10')
  })

  it('filtra lo que tenés y la watchlist (un activo que tenés y seguís sale en los dos)', () => {
    expect(filtrar(DATOS.senales, 'tenes').map(s => s.asset)).toEqual(['MELI', 'YPFD', 'AAPL'])
    expect(filtrar(DATOS.senales, 'watchlist').map(s => s.asset)).toEqual(['PAMP'])
    const ambos = [{ ...DATOS.senales[0], watchlist: true }]
    expect(filtrar(ambos, 'tenes')).toHaveLength(1)
    expect(filtrar(ambos, 'watchlist')).toHaveLength(1)
  })

  it('las tres tarjetas', () => {
    const t = tarjetas(DATOS, false)
    expect([t.tenes.valor, t.tenes.texto]).toEqual(['3 cambios', 'en 3 de tus 7 activos con lectura'])
    expect([t.watch.valor, t.watch.texto]).toEqual(['1 cambio', 'PAMP'])
    expect([t.plata.valor, t.plata.antes, t.plata.tono]).toEqual(['54%', 'la semana pasada 61%', 'neg'])
    expect(t.plata.texto).toBe('AAPL pasó a bajista esta semana')
  })

  it('sin dato de la semana pasada, esa parte no aparece; uno que no es de hace 7 días lleva su fecha', () => {
    expect(tarjetas({ ...DATOS, alcista: { pct: 54, semana_pasada: null } }, false).plata.antes).toBeNull()
    expect(semanaPasadaTxt({ semana: '2026-10-17' }, '2026-10-21')).toBe('el sábado 17/10')
  })

  it('con «Ocultar saldos»: ni el %, ni el de la semana pasada, ni el peso', () => {
    const t = tarjetas(DATOS, true)
    expect(t.plata.valor).toBe('••')
    expect(t.plata.antes).toBeNull()
    expect(deQuien(DATOS.senales[0], true)).toBe('Lo tenés')
    expect(deQuien(DATOS.senales[0], false)).toBe('Lo tenés · 12% de tu plata')
    expect(pesoTxt(0.004, false)).toBe('menos del 1% de tu plata')
    expect(deQuien(DATOS.senales[3], false)).toBe('En tu watchlist')
  })

  it('el botón abre la ficha por el símbolo que dio el servidor; con tesis, «Revisar tu tesis»', () => {
    expect(rutaDeFicha(DATOS.senales[3])).toBe('/activo/PAMP.BA')
    expect(boton(DATOS.senales[2])).toBe('Revisar tu tesis')
    expect(boton(DATOS.senales[0])).toBe('Ver gráfico')
  })
})

describe('tusSenales: lo que se dibuja', () => {
  it('la pantalla del recuadro 15', () => {
    const t = texto(dibujar())
    expect(t).toContain('Qué cambió esta semana en lo tuyo y en tu watchlist')
    for (const x of ['En lo que tenés', 'En tu watchlist', 'Tu plata en tendencia alcista', '54%', 'la semana pasada 61%',
      'Todo', 'Lo que tenés', 'Watchlist', 'Viernes 23/10', 'Lunes 19/10', 'Ver gráfico',
      'MELI tiene la fuerza (RSI) en 28', 'Lo tenés · 12% de tu plata', 'En tu watchlist',
      'Tu tesis: «El recambio de iPhone.»', 'Revisar tu tesis',
      'Mail', 'Notificación', 'Las dos', 'No quiero', 'Sábados a las 10:00. Si en la semana no cambió nada, no te escribimos.',
      'no es una recomendación para comprar ni vender']) {
      expect(t).toContain(x)
    }
  })

  it('«cayó muy rápido» va con la frase de posibilidad, nunca como certeza', () => {
    const t = texto(dibujar())
    expect(t).toContain(POSIBILIDAD)
    expect(t.toLowerCase()).not.toMatch(/va a rebotar|comprá|vendé|oportunidad/)
  })

  it('con «Ocultar saldos» no aparece ningún porcentaje de la cartera', () => {
    const t = texto(dibujar({ hidden: true }))
    expect(t).not.toMatch(/\d+%/)
    expect(t).toContain('Oculto porque tenés prendido «Ocultar saldos».')
  })

  it('semana quieta y pedido fallido dicen cada uno lo suyo', () => {
    expect(texto(dibujar({ datos: { ...DATOS, senales: [] } }))).toContain('Esta semana no cambió nada en lo tuyo ni en tu watchlist.')
    expect(texto(dibujar({ filtro: 'watchlist', datos: { ...DATOS, senales: [DATOS.senales[0]] } })))
      .toContain('Esta semana no cambió nada en tu watchlist.')
    expect(texto(dibujar({ error: true }))).toContain('No pudimos traer tus señales ahora')
  })

  it('la preferencia marca lo elegido', () => {
    const html = dibujar({ datos: { ...DATOS, canal: 'ambos' } })
    expect(html).toMatch(/aria-pressed="true"[^>]*>Las dos</)
    expect(html).not.toMatch(/aria-pressed="true"[^>]*>No quiero</)
  })
})
