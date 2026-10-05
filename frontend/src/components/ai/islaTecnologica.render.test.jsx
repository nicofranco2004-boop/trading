import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { renderToStaticMarkup } from 'react-dom/server'
import ViendoTuCartera from './ViendoTuCartera'

// La isla y la página de Mervall-E AI: lo que se mueve al abrirlas tiene que
// decir lo mismo que la lectura que viaja con la pregunta.

const leer = (ruta) => readFileSync(new URL(ruta, import.meta.url), 'utf8')
const sinComentarios = (t) => t.split('\n').filter(l => !/^\s*(\/\/|\/?\*|\{\/\*)/.test(l)).join('\n')

describe('ViendoTuCartera — el mismo texto en la isla y en /ai', () => {
  const html = (resumen, extra) => renderToStaticMarkup(<ViendoTuCartera resumen={resumen} {...extra} />)
  it('con la lectura: posiciones y brokers, con su plural', () => {
    expect(html({ posiciones: 12, brokers: 3 })).toContain('Viendo tu cartera')
    expect(html({ posiciones: 12, brokers: 3 }).replace(/<[^>]+>/g, '')).toBe('Viendo tu cartera · 12 posiciones · 3 brokers')
    expect(html({ posiciones: 1, brokers: 1 }).replace(/<[^>]+>/g, '')).toBe('Viendo tu cartera · 1 posición · 1 broker')
  })
  it('sin brokers no dice "0 brokers"; sin cuenta de posiciones no inventa una', () => {
    expect(html({ posiciones: 4, brokers: 0 }).replace(/<[^>]+>/g, '')).toBe('Viendo tu cartera · 4 posiciones')
    expect(html({ posiciones: null, brokers: 2 }).replace(/<[^>]+>/g, '')).toBe('Viendo tu cartera · 2 brokers')
  })
  it('sin lectura todavía: lo que le pasen (la isla, "Leyendo tu cartera…")', () => {
    expect(html(null, { sinLectura: <span>Leyendo tu cartera…</span> })).toBe('<span>Leyendo tu cartera…</span>')
  })
})

describe('el texto "Viendo tu cartera" se arma en UN lugar', () => {
  // La cabecera de /ai lo armaba a mano ("1 posiciones") y la isla iba a ser
  // la segunda copia.
  it('ni la página ni la isla lo escriben por su cuenta', () => {
    for (const f of ['../../pages/RendiAI.jsx', '../voz/RendiMate.jsx']) {
      const codigo = sinComentarios(leer(f))
      expect(codigo, f).not.toMatch(/Viendo tu cartera/)
      expect(codigo, f).toMatch(/<ViendoTuCartera/)
    }
  })
})

describe('/ai: el cargador son los pedidos de verdad', () => {
  const pagina = sinComentarios(leer('../../pages/RendiAI.jsx'))
  it('ya no es una rueda con "Cargando el contexto de tu cartera…"', () => {
    expect(pagina).not.toMatch(/Cargando el contexto/)
    expect(pagina).toMatch(/<CargaPorPasos[^>]*pasos=\{pasosContextoIA\(llego\)\}/)
  })
  it('cada renglón se tilda con lo que avisa fetchAiSnapshot al volver ese pedido', () => {
    // La lectura es la de VozContext (la misma de la isla): de ahí sale `llego`.
    expect(pagina).toMatch(/cartera\?\.estado === 'leyendo' \? cartera\.llego/)
    expect(pagina).not.toMatch(/fetchAiSnapshot/)
  })
  it('al pasar a otro cliente se vuelve a leer (antes seguía con la del anterior)', () => {
    expect(pagina).toMatch(/\[bookMode, clienteId, persona, leerCartera\]/)
    // Y relee por la identidad del aviso, no por un sí/no que puede no cambiar.
    expect(pagina).toMatch(/\[bookMode, cartera, leerCartera\]/)
  })
  it('aparece sólo si tarda (useDemora), como el de Novedades', () => {
    expect(pagina).toMatch(/useDemora\(loading\)/)
  })
})

describe('la isla crece desde la burbuja sin pelearse con el arrastre', () => {
  const isla = leer('../voz/RendiMate.jsx')
  it('la animación va en el elemento de ADENTRO, no en el que mueve useArrastrable', () => {
    // El de afuera lleva ref={islaRef} y el `transform` del arrastre; si
    // creciera ese, la animación pisaría su transform y el recorte contra los
    // bordes mediría la tarjeta achicada.
    const seccion = isla.slice(isla.indexOf('<section'), isla.indexOf('</section>'))
    const abre = seccion.slice(0, seccion.indexOf('>') + 1)
    expect(abre).toMatch(/ref=\{islaRef\}/)
    expect(abre).not.toMatch(/isla-despliega|transform/)
    expect(seccion).toMatch(/ref=\{tarjetaRef\}\s+className="isla-despliega/)
  })
  it('el centro del crecimiento se recalcula cuando el arrastre la reacomoda al abrir', () => {
    expect(isla).toMatch(/tarjeta\.style\.transformOrigin =[\s\S]{0,400}\}, \[open, corrida, islaRef\]\)/)
  })
  it('con "reducir movimiento" no crece', () => {
    const css = leer('../../index.css')
    const reducido = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(reducido).toMatch(/\.isla-despliega \{ animation: none; \}/)
  })
})

describe('VozContext: la pregunta usa la MISMA lectura que muestra la isla', () => {
  const voz = sinComentarios(leer('../../contexts/VozContext.jsx'))
  it('nada pide la cartera por fuera de lecturaDeCartera (ni /ai)', () => {
    expect((voz.match(/fetchAiSnapshot\(/g) || []).length).toBe(1)
    expect(voz).toMatch(/leer: \(alLlegar, signal\) => fetchAiSnapshot\(\{ alLlegar, signal \}\)/)
    expect(voz).toMatch(/traer: \(\) => lectura\.paraPreguntar\(\)/)
  })
  it('se tira cuando cambia algo: el chat, el importador, una escritura o el cliente', () => {
    expect(voz).toMatch(/addEventListener\('rendi:portfolio-changed', trasEscribir\)/)
    expect(voz).toMatch(/addEventListener\(EVENTO_ESCRITURA, trasEscribir\)/)
    // El cambio de cliente, junto con la conversación (cambiarDeCuenta), sin pausa.
    const cambiar = voz.slice(voz.indexOf('const cambiarDeCuenta = useCallback'))
    expect(cambiar.slice(0, 1500)).toMatch(/lectura\.invalidar\(\{ pausa: false \}\)/)
    expect(voz).toMatch(/addEventListener\(EVENTO_CUENTA_CAMBIADA, alCambiar\)/)
  })
  it('al cambiar de persona se olvida la lectura ANTES de que la isla pida la nueva', () => {
    // useLayoutEffect corre antes que los efectos de los hijos; con useEffect,
    // el olvido llegaba después y tiraba la lectura recién pedida.
    expect(voz).toMatch(/useLayoutEffect\(\(\) => \{\s*if \(quienLeiaRef\.current !== quienLee\) lectura\.olvidar\(\)/)
  })
  it('el modo libro se decide al preguntar y al leer, no con el valor del último dibujo', () => {
    // VozProvider vive arriba de AdvisorProvider: `modoLibro` puede ser de
    // antes de entrar a un cliente, y la IA recibía `{}` sobre el cliente.
    const ask = voz.slice(voz.indexOf('const ask = useCallback'))
    expect(ask.slice(0, ask.indexOf('const res = await api.chatStream'))).toMatch(/libro: esModoLibro\(\)/)
  })
})
