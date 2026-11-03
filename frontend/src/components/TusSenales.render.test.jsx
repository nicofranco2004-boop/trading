// Lo que DIBUJA «Señales de la semana» (pieza 15, como Novedades desde el 30/10)
// con una respuesta de GET /api/tus-senales armada como la del servidor
// (backend/senales_semana.py): la franja de 3 números, las barras por día, el
// filtro, la agenda por día, la frase de posibilidad de «cayó muy rápido» y lo
// que se esconde con «Ocultar saldos» (también el orden por peso).
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { TusSenalesVista } from './TusSenales'
import {
  filtrar, porDia, franja, deQuien, pesoTxt, diaLargo, semanaPasadaTxt, rutaDeFicha, boton,
  lado, colorDelCambio, hace, enOrden, diasDeLasBarras, quienCorto, detalleDe, queLoMovio,
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
      corta: 'cayó muy rápido', texto: 'cayó muy rápido: el impulso (RSI) bajó de 30 y quedó en 28; una semana de mercado antes estaba en 52.',
      detalle: 'Su impulso (RSI) bajó de 30 y quedó en 28; una semana antes estaba en 52.', extra: POSIBILIDAD },
    { asset: 'YPFD', local: true, ficha: 'YPFD', tenes: true, watchlist: false, peso: 0.14, tesis: null,
      tipo: 'maximo_12m', fecha: '2026-10-23', sentido: 'arriba', etiqueta: 'Máximo del año', tono: 'pos',
      corta: 'empezó a marcar máximos del año', texto: 'empezó a marcar máximos del año (cerró en su precio más alto de los últimos 12 meses), después de un mes sin hacerlo.', extra: null },
    { asset: 'AAPL', local: false, ficha: 'AAPL', tenes: true, watchlist: false, peso: 0.11, tesis: 'El recambio de iPhone.',
      tipo: 'media200', fecha: '2026-10-20', sentido: 'abajo', etiqueta: 'Tendencia de largo plazo', tono: 'neg',
      texto: 'cayó por debajo de su promedio de 200 días: la tendencia de largo plazo pasó a ser bajista.', extra: null },
    { asset: 'PAMP', local: true, ficha: 'PAMP.BA', tenes: false, watchlist: true, peso: null, tesis: null,
      tipo: 'adx23', fecha: '2026-10-19', sentido: 'arriba', etiqueta: 'Fuerza de la tendencia', tono: 'adx',
      corta: 'dejó de moverse de forma lateral y tomó una dirección (al alza)', texto: 'dejó de moverse de forma lateral y tomó una dirección (al alza): la fuerza de la tendencia (ADX) superó 23 y quedó en 24.', extra: null },
  ],
}

const dibujar = (props) => renderToStaticMarkup(
  <MemoryRouter>
    <TusSenalesVista datos={DATOS} hidden={false} filtro="todo" onFiltro={() => {}} onVer={() => {}}
      onCanal={() => {}} {...props} />
  </MemoryRouter>,
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

  it('la franja de 3 números', () => {
    const f = franja(DATOS, false)
    expect([f.cambios.valor, f.cambios.texto]).toEqual([4, '3 en tu cartera · 1 en tu watchlist'])
    // MELI cayó muy rápido (en contra), YPFD máximo (a favor), AAPL bajó del
    // promedio de 200 (en contra), PAMP tomó dirección al alza (sin `squeeze`
    // en el dato: no cuenta para ningún lado).
    expect([f.lados.favor, f.lados.contra, f.lados.sin]).toEqual([1, 2, 1])
    expect(f.lados.texto).toBe('Del lado del precio: a favor, subió; en contra, bajó. 1 cambio sin dirección.')
    expect([f.plata.valor, f.plata.cambio]).toEqual(['54%', { texto: '▼ 7 puntos menos que la semana pasada', tono: 'neg' }])
    // La misma frase que «Qué lo movió» del Panorama (queLoMovio), con el peso y el día.
    expect(f.plata.texto).toBe('AAPL (11% de tu cartera) pasó a bajista el martes 20/10.')
  })

  it('de qué lado y de qué color es cada cambio', () => {
    expect(lado({ tipo: 'media200', sentido: 'arriba' })).toBe('favor')
    expect(lado({ tipo: 'media50', sentido: 'abajo' })).toBe('contra')
    expect(lado({ tipo: 'rsi_bajo_30' })).toBe('contra')
    expect(lado({ tipo: 'rsi_sobre_70' })).toBe('favor')
    expect(lado({ tipo: 'maximo_12m' })).toBe('favor')
    expect([lado({ tipo: 'adx23', squeeze: 1 }), lado({ tipo: 'adx23', squeeze: -1 }), lado({ tipo: 'adx23', squeeze: 0 })]).toEqual(['favor', 'contra', null])
    // El color es el MISMO lado que cuenta la franja: el máximo (YPFD) es verde
    // en la barra porque suma «a favor» arriba; azul sólo lo que no tiene dirección.
    expect(DATOS.senales.map(colorDelCambio)).toEqual(['neg', 'pos', 'neg', 'azul'])
  })

  it('la franja cuenta igual que los filtros: lo que tenés Y seguís va en los dos', () => {
    const ko = { asset: 'KO', fecha: '2026-10-23', tenes: true, watchlist: true, peso: 0.1, tipo: 'media200', sentido: 'arriba', corta: 'superó su promedio de 200 días' }
    const datos = { ...DATOS, senales: [ko] }
    expect(franja(datos, false).cambios.texto).toBe('1 en tu cartera · 1 en tu watchlist')
    const t = texto(dibujar({ datos }))
    expect(t).toContain('Tu cartera · 1')
    expect(t).toContain('Watchlist · 1')
  })

  it('un día con 40 cambios: la barra se parte por color, sin alturas negativas', () => {
    const muchos = Array.from({ length: 40 }, (_, k) => ({ asset: `A${k}`, fecha: '2026-10-23', tenes: false, watchlist: true, peso: null,
      tipo: 'media200', sentido: k % 4 ? 'abajo' : 'arriba', corta: 'x' }))
    const html = dibujar({ datos: { ...DATOS, senales: muchos } })
    expect(html).not.toMatch(/height:\s*-/)
    const barra = html.slice(html.indexOf('aria-label="Viernes 23/10:'), html.indexOf('</button>', html.indexOf('aria-label="Viernes 23/10:')))
    // Dos pedazos (10 a favor, 30 en contra), cada uno del alto de lo suyo.
    expect(barra.match(/flex:\s*\d+/g)).toEqual(['flex:10', 'flex:30'])
    expect(barra).toContain('height:100%')
  })

  it('«hace 2 días» se cuenta desde el hoy del servidor', () => {
    expect([hace('2026-10-24', '2026-10-24'), hace('2026-10-23', '2026-10-24'), hace('2026-10-20', '2026-10-24')])
      .toEqual(['hoy', 'ayer', 'hace 4 días'])
    expect(hace('2026-10-25', '2026-10-24')).toBeNull()
  })

  it('las barras: un día por cada día del período, con lo que pasó ese día', () => {
    const d = diasDeLasBarras(DATOS.senales, DATOS.desde, DATOS.hasta)
    expect(d.map(x => x.fecha)).toEqual(['2026-10-18', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24'])
    expect(d.map(x => x.items.length)).toEqual([0, 1, 1, 0, 0, 2, 0])
  })

  it('«con lectura» quiere decir una sola cosa (re-test A2, 29/10)', () => {
    // La misma respuesta del servidor (la de la prueba A2): NVDA con 3 años y
    // NUEVA con 120 días. Señales dice lo que cuenta, precios al día.
    const resp = {
      senales: [], tenes: { activos: 2, con_cambios: 0 }, watchlist: 0,
      alcista: { pct: 50, semana_pasada: null, grupos: { alcista: { nombres: ['NVDA'] }, bajista: { nombres: [] }, sin: { nombres: ['NUEVA'] } } },
    }
    expect(franja(resp, false).cambios.texto).toBe('Nada cambió en tus 2 activos con precios al día.')
    expect(franja({ ...resp, watchlist: 3 }, false).cambios.texto).toBe('Nada cambió en tus 2 activos con precios al día ni en tu watchlist.')
    // Quien sólo sigue una watchlist (revisión 30/10): antes leía «no hay precios
    // guardados de ninguno de tus activos», con precios de sus 5 a la vista.
    expect(franja({ ...resp, tenes: { activos: 0 }, watchlist: 5 }, false).cambios.texto).toBe('Nada cambió en tu watchlist.')
    expect(franja({ ...resp, tenes: { activos: 0 }, watchlist: 0 }, false).cambios.texto).toBe('Todavía no hay precios guardados de tus activos ni de tu watchlist.')
  })

  it('sin dato de la semana pasada, no hay chip; uno que no es de hace 7 días lleva su fecha', () => {
    expect(franja({ ...DATOS, alcista: { pct: 54, semana_pasada: null } }, false).plata.cambio).toBeNull()
    expect(semanaPasadaTxt({ semana: '2026-10-17' }, '2026-10-21')).toBe('el sábado 17/10')
  })

  it('con «Ocultar saldos»: ni el %, ni el chip, ni el peso', () => {
    const f = franja(DATOS, true)
    expect(f.plata.valor).toBe('••')
    expect(f.plata.cambio).toBeNull()
    expect(quienCorto(DATOS.senales[0], true)).toBe('en tu cartera')
    expect(quienCorto(DATOS.senales[0], false)).toBe('12% de tu cartera')
    expect(quienCorto(DATOS.senales[3], false)).toBe('en tu watchlist')
    expect(deQuien(DATOS.senales[0], true)).toBe('En tu cartera')
    expect(deQuien(DATOS.senales[0], false)).toBe('En tu cartera · 12% de tu cartera')
    expect(pesoTxt(0.004, false)).toBe('menos de 1% de tu cartera')
  })

  it('con «Ocultar saldos», el orden de cada día no delata cuál pesa más', () => {
    // El servidor manda lo tuyo de más a menos peso: YPFD (14%) antes que MELI (12%).
    const dia = [
      { asset: 'YPFD', fecha: '2026-10-23', tenes: true, peso: 0.14, tipo: 'media200', sentido: 'arriba', corta: 'superó su promedio de 200 días' },
      { asset: 'MELI', fecha: '2026-10-23', tenes: true, peso: 0.12, tipo: 'media200', sentido: 'arriba', corta: 'superó su promedio de 200 días' },
      { asset: 'AAPL', fecha: '2026-10-23', tenes: false, watchlist: true, peso: null, tipo: 'maximo_12m' },
      { asset: 'ZZZ', fecha: '2026-10-20', tenes: true, peso: 0.5, tipo: 'media50' },
    ]
    expect(enOrden(dia, false).map(s => s.asset)).toEqual(['YPFD', 'MELI', 'AAPL', 'ZZZ'])
    expect(enOrden(dia, true).map(s => s.asset)).toEqual(['MELI', 'YPFD', 'AAPL', 'ZZZ'])
    // «Qué lo movió» tampoco nombra por peso con el ojito cerrado.
    expect(queLoMovio({ senales: dia }, true)).toBe('MELI pasó a alcista el viernes 23/10; YPFD pasó a alcista el viernes 23/10.')
    // Y la pantalla: MELI antes que YPFD en la agenda con el ojito.
    const datos = { ...DATOS, senales: dia }
    const conOjo = texto(dibujar({ datos, hidden: true }))
    expect(conOjo.indexOf('MELI superó')).toBeLessThan(conOjo.indexOf('YPFD superó'))
    // Las barras tampoco: su descripción nombra a MELI primero con el ojito, a YPFD sin él.
    expect(dibujar({ datos, hidden: true })).toContain('aria-label="Viernes 23/10: MELI superó su promedio de 200 días; YPFD superó')
    expect(dibujar({ datos, hidden: false })).toContain('aria-label="Viernes 23/10: YPFD superó su promedio de 200 días; MELI superó')
  })

  it('la segunda línea: `detalle` del servidor; uno de antes no repite el título', () => {
    expect(detalleDe(DATOS.senales[0])).toBe('Su impulso (RSI) bajó de 30 y quedó en 28; una semana antes estaba en 52.')
    expect(detalleDe(DATOS.senales[2])).toBeNull()
    expect(texto(dibujar())).not.toContain('cayó por debajo de su promedio de 200 días: la tendencia')
  })

  it('el botón abre la ficha por el símbolo que dio el servidor; con tesis, «Revisar tu tesis»', () => {
    expect(rutaDeFicha(DATOS.senales[3])).toBe('/activo/PAMP.BA')
    expect(boton(DATOS.senales[2])).toBe('Revisar tu tesis')
    expect(boton(DATOS.senales[0])).toBe('Ver el gráfico')
  })
})

describe('tusSenales: lo que se dibuja', () => {
  it('la pantalla del lienzo «4 · Señales de la semana»', () => {
    const t = texto(dibujar())
    for (const x of ['Cambios esta semana', '3 en tu cartera · 1 en tu watchlist', 'A favor · en contra',
      'Del lado del precio: a favor, subió; en contra, bajó.',
      'Tu cartera en tendencia alcista de largo plazo', '54%', '▼ 7 puntos menos que la semana pasada',
      'Cambios por día · últimos 7 días',
      'Qué cambió esta semana en tu cartera y en tu watchlist', 'Todo · 4', 'Tu cartera · 3', 'Watchlist · 1',
      'viernes', '23 oct', 'lunes', '19 oct',
      'MELI cayó muy rápido', 'Impulso', 'Su impulso (RSI) bajó de 30 y quedó en 28', '· 12% de tu cartera',
      'YPFD empezó a marcar máximos del año', 'Máximo', 'AAPL', 'Largo plazo', 'PAMP', 'Fuerza', '· en tu watchlist',
      'Ver el gráfico', 'ayer', 'hace 4 días', 'hace 5 días',
      'Tu tesis: «El recambio de iPhone.»', 'Revisar tu tesis',
      'El resumen del sábado', 'Mail', 'Notificación', 'Mail y notificación', 'No recibirlo',
      'No te llega el resumen de los sábados. Si en la semana no cambió nada, no te mandamos nada.',
      '¿Querés enterarte en el momento?', 'Una alerta técnica te avisa a la mañana siguiente de que pase algo así', 'Crear una alerta técnica',
      'no es una recomendación para comprar ni vender']) {
      expect(t).toContain(x)
    }
    // La leyenda de las barras: sus tres colores (PAMP no tiene dirección).
    const html = dibujar()
    const ul = html.slice(html.indexOf('aria-label="Colores"'), html.indexOf('</ul>', html.indexOf('aria-label="Colores"')))
    expect((ul.match(/<li[^>]*>.*?<\/li>/g) || []).map(x => texto(x).trim())).toEqual(['a favor', 'en contra', 'sin dirección'])
    expect(texto(dibujar({ datos: { ...DATOS, senales: DATOS.senales.slice(0, 3) } }))).not.toContain('sin dirección')
    // Un solo aviso de «no es una recomendación», al pie.
    expect(t.split('no es una recomendación').length - 1).toBe(1)
    // El cartel de cada barra dice qué pasó ese día; la del lector de pantalla, también.
    expect(dibujar()).toContain('aria-label="Viernes 23/10: MELI cayó muy rápido; YPFD empezó a marcar máximos del año"')
    expect(dibujar()).toMatch(/href="\/alertas\?tab=crear"/)
  })

  it('las palabras no prometen nada', () => {
    const t = texto(dibujar()).toLowerCase()
    expect(t).not.toMatch(/\bsuele|anticipa|va a (subir|bajar|rebotar)|comprá|vendé|oportunidad/)
  })

  it('«cayó muy rápido» va con la frase de posibilidad, nunca como certeza', () => {
    const t = texto(dibujar())
    expect(t).toContain(POSIBILIDAD)
    expect(t.toLowerCase()).not.toMatch(/va a rebotar|comprá|vendé|oportunidad/)
  })

  it('con «Ocultar saldos» no aparece ningún porcentaje de la cartera', () => {
    const t = texto(dibujar({ hidden: true }))
    expect(t).not.toMatch(/\d+%/)
    expect(t).toContain('Qué parte de tu cartera está en tendencia alcista de largo plazo: oculto porque tenés prendido «Ocultar saldos».')
  })

  it('semana quieta y pedido fallido dicen cada uno lo suyo', () => {
    expect(texto(dibujar({ datos: { ...DATOS, senales: [] } }))).toContain('Esta semana no cambió nada en tu cartera ni en tu watchlist.')
    expect(texto(dibujar({ filtro: 'watchlist', datos: { ...DATOS, senales: [DATOS.senales[0]] } })))
      .toContain('Esta semana no cambió nada en tu watchlist.')
    expect(texto(dibujar({ error: true }))).toContain('No pudimos traer tus señales ahora')
  })

  it('la preferencia marca lo elegido y dice cuándo llega', () => {
    const html = dibujar({ datos: { ...DATOS, canal: 'ambos', proximo_resumen: '2026-10-31' } })
    // Botones con aria-pressed, no un radiogroup: ése promete moverse con las
    // flechas y estos no (revisión 30/10). Mientras guarda, no se deshabilitan.
    expect(html).not.toContain('radiogroup')
    expect(html).toMatch(/aria-pressed="true"[^>]*>(<span[^>]*><\/span>)?Mail y notificación</)
    const resumen = html.slice(html.indexOf('id="senales-resumen-titulo"'))
    expect(resumen.slice(0, resumen.indexOf('</section>')).match(/aria-pressed="true"/g)).toHaveLength(1)
    expect(dibujar({ guardando: true })).not.toMatch(/<button[^>]*disabled=""[^>]*aria-pressed/)
    expect(texto(html)).toContain('El resumen de la semana te llega el sábado 31/10 a las 10:00, por mail y notificación.')
  })
})
