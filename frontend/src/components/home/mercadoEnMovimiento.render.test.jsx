import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// Las secciones de mercado del inicio con movimiento: movers, indicador en
// vivo y barra de intensidad, dibujados de verdad.
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})) } }))

import { MoverList } from './MoversRail'
import EnVivo from '../EnVivo'
import BarraIntensidad, { anchoBarra, TOPE_BARRA_PCT } from '../BarraIntensidad'
import { TrendingUp } from 'lucide-react'
import { haceCuanto, diaMes } from '../../utils/fecha'
import AnimatedNumber from '../AnimatedNumber'
import { refrescoSegunRueda, REFRESCO_MERCADO_MS, MARGEN_APERTURA_MS, msHastaProximaMediaHora } from '../../utils/relojVisible'
import { _ruedaDemo, handleDemoRequest } from '../../utils/demo'
import { horaDelCable, urlsNuevas, Cable } from './NewsPreview'

const MOVERS = [
  { symbol: 'ORCL', name: 'Oracle', change_pct: 3.91 },
  { symbol: 'META', name: 'Meta', change_pct: 3.24 },
]

const dibujar = (visto) => renderToStaticMarkup(
  <MoverList items={MOVERS} tone="pos" icon={TrendingUp} label="Más suben" onSelect={() => {}} visto={visto} />,
)

describe('Movers del día con movimiento', () => {
  it('antes de verse: filas escondidas, barras en cero y números escondidos', () => {
    const html = dibujar(false)
    // 2 filas + los 2 números: el número espera escondido y escrito con su
    // valor final (lo que lee un lector de pantalla), nunca con un 0 a la vista.
    expect((html.match(/por-entrar/g) || []).length).toBe(4)
    expect(html).not.toMatch(/class="[^"]*\bentra\b/)
    expect(html).toContain('width:0%')
    expect(html).toMatch(/<span class="por-entrar">\+3,91%<\/span>/)
    expect(html).not.toMatch(/>\+?0,00%</)
  })

  it('al verse: entran de a una (el orden en --i), la barra crece y el número llega a su valor', () => {
    const html = dibujar(true)
    expect((html.match(/\bentra\b/g) || []).length).toBe(2)
    expect(html).toContain('--i:0')
    expect(html).toContain('--i:1')
    // En el navegador el número cuenta desde 0; en el render a texto sale en
    // su valor final (useCountUp). Lo que importa acá es la barra con su ancho.
    expect(html).toContain(`width:${(3.91 / TOPE_BARRA_PCT) * 55}%`)
  })

  it('los porcentajes no van en mono (R1); el ticker sí puede (R3)', () => {
    const html = dibujar(true)
    // Las celdas de números son las que llevan `num` (DataRow.Cell tabular).
    const celdasNum = html.match(/<div class="[^"]*\bnum\b[^"]*"/g) || []
    expect(celdasNum.length).toBe(2)
    celdasNum.forEach(c => expect(c).not.toContain('font-mono'))
    expect(html).toMatch(/font-mono[^>]*><span[^>]*>ORCL/)
  })
})

describe('BarraIntensidad — escala fija, no relativa al más movido', () => {
  it('un día tranquilo se ve tranquilo', () => {
    expect(anchoBarra(0.8)).toBeCloseTo(0.16)
    expect(anchoBarra(-2.5)).toBe(0.5)
  })
  it('arriba del tope la barra queda llena', () => {
    expect(anchoBarra(12)).toBe(1)
  })
  it('sin movimiento o sin dato, no hay barra', () => {
    expect(renderToStaticMarkup(<BarraIntensidad pct={0} />)).toBe('')
    expect(renderToStaticMarkup(<BarraIntensidad pct={null} />)).toBe('')
    expect(renderToStaticMarkup(<BarraIntensidad pct={-0.001} />)).toBe('')
  })
  it('verde si subió, roja si bajó, y detrás del texto', () => {
    expect(renderToStaticMarkup(<BarraIntensidad pct={2} />)).toMatch(/bg-rendi-pos\/10.*-z-10|-z-10.*bg-rendi-pos\/10/)
    expect(renderToStaticMarkup(<BarraIntensidad pct={-2} />)).toContain('bg-rendi-neg/10')
  })
})

describe('EnVivo — el punto late sólo al lado de números de la rueda de hoy', () => {
  const hace3 = () => new Date(Date.now() - 3 * 60000).toISOString()
  const base = { en_rueda: 0, total: 3, en_horario: false, rueda: '2026-09-25', actualizado: new Date().toISOString() }

  it('todos en rueda: "Abierto", punto que late y cuándo se actualizó', () => {
    const html = renderToStaticMarkup(<EnVivo estado={{ ...base, abierto: true, en_rueda: 3, en_horario: true, actualizado: hace3() }} />)
    expect(html).toContain('live-dot')
    expect(html).toContain('Abierto')
    expect(html).toContain('actualizado hace 3m')
  })
  it('lista mezclada (una cripto un sábado): NO dice "Abierto", dice cuántos', () => {
    const html = renderToStaticMarkup(<EnVivo estado={{ ...base, abierto: false, en_rueda: 1, total: 3 }} />)
    expect(html).toContain('En rueda 1 de 3')
    expect(html).not.toContain('Abierto')
  })
  it('en horario con números de ayer: esperando, quieto y con la fecha', () => {
    const html = renderToStaticMarkup(<EnVivo estado={{ ...base, abierto: false, en_horario: true, rueda: '2026-09-28' }} />)
    expect(html).toContain('Esperando la rueda de hoy')
    expect(html).toContain('rueda del 28/09')
    expect(html).not.toContain('live-dot')
    expect(html).not.toContain('Cerrado')
  })
  it('fuera de horario: cerrado, quieto y DE CUÁNDO son los números', () => {
    const html = renderToStaticMarkup(<EnVivo estado={{ ...base, abierto: false }} />)
    expect(html).not.toContain('live-dot')
    expect(html).toContain('Cerrado')
    expect(html).toContain('rueda del 25/09')
  })
  it('sin datos del servidor, no dice nada', () => {
    expect(renderToStaticMarkup(<EnVivo />)).toBe('')
    expect(renderToStaticMarkup(<EnVivo estado={{}} />)).toBe('')
  })
})

describe('sin cotización no se inventa un número', () => {
  it('el mover sin dato muestra "—" en gris, no "0,00%" en verde', () => {
    const html = renderToStaticMarkup(
      <MoverList items={[{ symbol: 'XYZ', name: 'Sin dato', change_pct: null }]} tone="pos" icon={TrendingUp} label="Más suben" onSelect={() => {}} visto />,
    )
    expect(html).not.toContain('0,00%')
    expect(html).toContain('—')
    expect(html).toContain('text-ink-3')
    expect(html).not.toContain('text-rendi-pos font-medium')
  })
  it('AnimatedNumber con null, undefined o NaN escribe "—" sin llamar al formato', () => {
    for (const v of [null, undefined, NaN]) {
      expect(renderToStaticMarkup(<AnimatedNumber value={v} format={() => 'NO'} />)).toBe('—')
    }
    expect(renderToStaticMarkup(<AnimatedNumber value={0} format={n => `v${n}`} />)).toBe('v0')
  })
})

describe('refrescoSegunRueda — con todo cerrado, a la próxima media hora en punto', () => {
  it('algo vivo o en horario: cada 5 min; todo cerrado: cuando puede abrir', () => {
    expect(refrescoSegunRueda({ abierto: true })).toBe(REFRESCO_MERCADO_MS)
    expect(refrescoSegunRueda({ abierto: false, en_rueda: 1 })).toBe(REFRESCO_MERCADO_MS)
    expect(refrescoSegunRueda({ abierto: false, en_rueda: 0, en_horario: true })).toBe(REFRESCO_MERCADO_MS)
    // Todo cerrado: a la próxima media hora en punto + el margen (NY abre 9:30,
    // BYMA 11:00): a las 10:12 ART el próximo pedido es a las 10:31:30.
    const a = new Date('2026-09-29T13:12:00Z')
    expect(refrescoSegunRueda({ abierto: false, en_rueda: 0, en_horario: false }, a))
      .toBe(18 * 60000 + MARGEN_APERTURA_MS)
    expect(msHastaProximaMediaHora(new Date('2026-09-29T13:30:00Z'))).toBe(30 * 60000)
    expect(refrescoSegunRueda(null)).toBe(REFRESCO_MERCADO_MS)
  })
})

describe('haceCuanto / diaMes', () => {
  const ahora = new Date('2026-09-29T20:00:00Z')
  it('escribe cuánto pasó', () => {
    expect(haceCuanto('2026-09-29T19:59:40Z', ahora)).toBe('ahora')
    expect(haceCuanto('2026-09-29T19:55:00Z', ahora)).toBe('hace 5m')
    expect(haceCuanto('2026-09-29T17:00:00Z', ahora)).toBe('hace 3h')
    expect(haceCuanto('2026-09-26T20:00:00Z', ahora)).toBe('hace 3d')
    expect(haceCuanto(null, ahora)).toBe('')
    expect(haceCuanto('basura', ahora)).toBe('')
  })
  it('la fecha corta de una rueda', () => {
    expect(diaMes('2026-09-25')).toBe('25/09')
    expect(diaMes(null)).toBe('')
  })
})

describe('el demo se comporta como producción', () => {
  it('abierto en horario de Nueva York un día hábil', () => {
    expect(_ruedaDemo(new Date('2026-09-29T15:00:00Z')).abierto).toBe(true)   // martes 11:00 NY
  })
  it('cerrado el fin de semana, con la rueda del viernes', () => {
    const r = _ruedaDemo(new Date('2026-10-03T15:00:00Z'))                   // sábado
    expect(r.abierto).toBe(false)
    expect(r.rueda).toBe('2026-10-02')
  })
  it('antes de la campana, la última rueda es la del día anterior', () => {
    const r = _ruedaDemo(new Date('2026-09-29T12:00:00Z'))                   // martes 08:00 NY
    expect(r.abierto).toBe(false)
    expect(r.rueda).toBe('2026-09-28')
  })
  it('los movers del demo traen el nombre y vienen ordenados, como los del servidor', () => {
    const { gainers, losers } = handleDemoRequest('GET', '/home/movers?market=sp500')
    expect(gainers[0]).toHaveProperty('name')
    expect(gainers[0]).not.toHaveProperty('label')
    const g = gainers.map(x => x.change_pct)
    const l = losers.map(x => x.change_pct)
    expect(g).toEqual([...g].sort((a, b) => b - a))
    expect(l).toEqual([...l].sort((a, b) => a - b))
  })
  it('movers y watchlist del demo traen el estado con la forma del servidor', () => {
    for (const ruta of ['/home/movers?market=sp500', '/watchlist']) {
      const r = handleDemoRequest('GET', ruta)
      for (const k of ['abierto', 'en_rueda', 'total', 'en_horario', 'rueda', 'actualizado']) {
        expect(r).toHaveProperty(k)
      }
    }
  })
})

describe('Noticias como cable', () => {
  const ahora = new Date(2026, 8, 29, 21, 30)           // 29/09 21:30, hora local
  it('la columna de la izquierda: la hora si es de hoy, "ayer", o la fecha', () => {
    expect(horaDelCable(new Date(2026, 8, 29, 9, 5).toISOString(), ahora)).toBe('09:05')
    expect(horaDelCable(new Date(2026, 8, 28, 23, 50).toISOString(), ahora)).toBe('ayer')
    expect(horaDelCable(new Date(2026, 8, 25, 12, 0).toISOString(), ahora)).toBe('25/09')
    expect(horaDelCable(null, ahora)).toBe('')
  })
  it('"Nueva" es lo que llegó mientras mirabas: la primera carga no marca nada', () => {
    const lista = [{ url: 'a' }, { url: 'b' }]
    expect(urlsNuevas(new Set(), lista).size).toBe(0)
    const n = urlsNuevas(new Set(['a', 'b']), [{ url: 'c' }, ...lista])
    expect([...n]).toEqual(['c'])
  })
  it('la noticia nueva lleva la marca, el punto violeta y el destello; las otras no', () => {
    const news = [
      { url: 'https://x/nueva', title: 'Llegó recién', source: 'reuters', published_at: new Date().toISOString(), tags: ['rates'] },
      { url: 'https://x/vieja', title: 'Ya estaba', source: 'investing', published_at: new Date().toISOString(), tags: [] },
    ]
    const html = renderToStaticMarkup(<Cable news={news} nuevas={new Set(['https://x/nueva'])} visto />)
    const [nueva, vieja] = html.split('</li>')
    expect(nueva).toContain('· Nueva')
    expect(nueva).toContain('destello-nueva')
    expect(nueva).toContain('bg-data-violet')
    expect(nueva).toContain('Tasas')                 // el tema, con el distintivo de /novedades
    expect(vieja).not.toContain('Nueva')
    expect(vieja).not.toContain('destello-nueva')
  })
  it('sin tono positivo/negativo: el cable no pinta noticias de verde o rojo', () => {
    const html = renderToStaticMarkup(<Cable news={[{ url: 'u', title: 'Cae la inflación', sentiment: 'negative', tags: [] }]} />)
    expect(html).not.toMatch(/rendi-(pos|neg)/)
  })
  it('las noticias del demo traen temas que el distintivo reconoce', () => {
    const { news } = handleDemoRequest('GET', '/news/market?limit=4')
    const conocidos = ['earnings', 'm_and_a', 'rates', 'inflation', 'forex', 'dividend', 'regulatory', 'debt']
    news.forEach(n => (n.tags || []).forEach(t => expect(conocidos).toContain(t)))
    expect(news.some(n => (n.tags || []).length > 0)).toBe(true)
  })
})
