import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { MAX_SEGUNDOS } from '../hooks/useDictado.js'
import { VOZ_ARRANCA_PRENDIDA } from '../contexts/VozContext.jsx'

// La página de Privacidad promete cosas concretas sobre el micrófono. Si el
// código cambia y la página no, la página pasa a MENTIR — y nadie se entera,
// porque una promesa incumplida no rompe ningún test ni tira ningún error.
//
// Esto ata las dos cosas. No verifica que el texto esté bien redactado: eso lo
// lee una persona. Verifica que los HECHOS que afirma sigan siendo los hechos.
const pagina = readFileSync(new URL('./Privacidad.jsx', import.meta.url), 'utf8')

describe('lo que la página promete sobre el micrófono sigue siendo cierto', () => {
  it('el tope de grabación que dice es el que el código aplica', () => {
    // Si mañana el tope sube a 60 y la página sigue diciendo 30, le estamos
    // diciendo al usuario que grabamos menos de lo que grabamos.
    expect(pagina).toContain(`${MAX_SEGUNDOS} segundos`)
  })

  it('dice que el audio se manda a OpenAI y no lo guardamos', () => {
    expect(pagina).toMatch(/No guardamos el audio/i)
    expect(pagina).toMatch(/se descarta/i)
  })

  it('declara la ayuda de vocabulario — que SÍ son datos de la cartera', () => {
    // El detalle que era fácil omitir: junto con el audio viajan los códigos y
    // nombres de los activos del usuario y los nombres de sus brokers. Es
    // información de su cartera yendo a un tercero, y tiene que estar dicho.
    expect(pagina).toMatch(/activos que[\s\S]{0,40}ten[eé]s/i)
    expect(pagina).toMatch(/brokers/i)
    // Y el límite de esa ayuda, que es lo que la hace aceptable.
    expect(pagina).toMatch(/no van montos/i)
  })

  it('dice que el navegador pide permiso aparte', () => {
    expect(pagina).toMatch(/te pide permiso/i)
  })

  it('dice que lo dictado no se manda solo', () => {
    // Es la decisión de diseño que sostiene todo lo demás (ver
    // components/voz/BotonMicrofono.jsx). Si deja de ser cierta en el código,
    // esta línea de la página hay que sacarla en el mismo movimiento.
    expect(pagina).toMatch(/no se env[ií]a solo/i)
  })

  it('dice que OpenAI lo retiene un tiempo, y cuánto', () => {
    // La promesa que FALTABA. "No guardamos el audio" es cierto y estaba, pero
    // un lector podía inferir que entonces desaparece del todo. No es así:
    // OpenAI lo retiene para controlar abusos. Ninguna frase era falsa sin
    // esto; la que faltaba era ésta, y es la que más se le puede reclamar.
    expect(pagina).toMatch(/30 días/)
    expect(pagina).toMatch(/abusiv|abuso/i)
    // Y que se aclare que eso NO es entrenamiento, para no confundir las dos.
    expect(pagina).toMatch(/No lo usan para entrenar/i)
  })

  it('la retención también está en el resumen de arriba', () => {
    const resumen = pagina.slice(0, pagina.indexOf('1. Introducción'))
    expect(resumen).toMatch(/30 días/)
  })

  it('el micrófono aparece también en el resumen de arriba', () => {
    // El resumen es lo único que lee la mayoría. Una función nueva que manda
    // datos a un tercero no puede estar sólo en la letra chica.
    const resumen = pagina.slice(0, pagina.indexOf('1. Introducción'))
    expect(resumen).toMatch(/micr[oó]fono/i)
    expect(resumen).toMatch(/OpenAI/)
  })

  it('el micrófono está en la lista de con quién compartimos', () => {
    const seccion5 = pagina.slice(pagina.indexOf('5. Con quién compartimos'))
    expect(seccion5).toMatch(/micr[oó]fono/i)
  })

  it('la frase vieja de la voz quedó ACOTADA, no contradicha', () => {
    // Decía "No le enviamos tu snapshot, ni tu email, ni ningún otro dato de
    // tu cuenta" a secas. Con el micrófono eso dejó de ser cierto en general
    // —viajan los nombres de tus activos—, así que ahora dice "para ESTA
    // función". Sin ese acote, dos párrafos de la misma página se contradicen.
    expect(pagina).toMatch(/Para esta función no le enviamos tu\s*\n?\s*snapshot/i)
  })
})

// ── La lectura en voz alta viene PRENDIDA, y los dos legales tienen que decirlo ──
// Hasta el 2026-09-26, Privacidad decía "Es opcional: se activa con el botón del
// parlante" y los Términos "si pedís escuchar". Era al revés: el parlante arranca
// prendido (`VOZ_ARRANCA_PRENDIDA` en VozContext.jsx) y, en los planes pagos y en
// la prueba, Rendi lee sola cada respuesta —o sea, le manda el resumen a OpenAI—
// sin que la persona toque nada. Esto ata los textos a ese valor: si alguien
// apaga el parlante de entrada, o vuelve a escribir que se activa a pedido, rojo.
describe('lo que los legales dicen de la lectura en voz alta sigue siendo cierto', () => {
  const plano = (s) => s.replace(/\{\/\*[\s\S]*?\*\/\}/g, ' ').replace(/<[^>]+>/g, ' ')
    .replace(/\{' '\}/g, ' ').replace(/\s+/g, ' ')
  const privacidad = plano(pagina)
  const terminos = plano(readFileSync(new URL('./Terminos.jsx', import.meta.url), 'utf8'))
  const COMO_SI_SE_PIDIERA = /si pedís escuchar|elegís escuchar|es opcional: se activa|se activa con el botón/i

  it('arranca como dice VOZ_ARRANCA_PRENDIDA, y los dos legales lo dicen igual', () => {
    for (const [nombre, texto] of [['Privacidad', privacidad], ['Términos', terminos]]) {
      if (VOZ_ARRANCA_PRENDIDA) {
        expect(texto, `${nombre} tiene que decir que la voz viene activada`).toMatch(/viene activad/i)
        expect(texto, `${nombre} tiene que decir cómo se apaga`).toMatch(/lo apagás|la apagás/i)
        expect(texto, `${nombre} vuelve a presentar la voz como algo que se pide`).not.toMatch(COMO_SI_SE_PIDIERA)
      } else {
        expect(texto, `la voz arranca apagada: ${nombre} no puede decir que viene activada`).not.toMatch(/viene activad/i)
      }
    }
  })

  it('también en el resumen de arriba, que es lo único que lee la mayoría', () => {
    const corte = pagina.indexOf('1. Introducción')
    expect(corte, 'no encuentro dónde termina el resumen').toBeGreaterThan(0)
    expect(/viene activad/i.test(plano(pagina.slice(0, corte)))).toBe(VOZ_ARRANCA_PRENDIDA)
  })
})

// 🔴 06/11/2026: la sección 7 decía «NO usamos … pixels de Facebook» y «no hay
// nada de tracking que aceptar o rechazar», y el sitio cargaba Google Analytics y
// el píxel de Meta. El resumen, la §2, la §3, la §5 y la pregunta frecuente de la
// portada decían lo mismo con otras palabras. Nadie se enteró: un texto que miente
// no rompe nada. Esto ata los textos a lo que el código carga: si se prende, se
// apaga o se reconfigura una de las dos herramientas, los textos cambian en el
// mismo movimiento.
describe('lo que los legales dicen de la medición y los anuncios sigue siendo cierto', () => {
  const plano = (s) => s.replace(/\{\/\*[\s\S]*?\*\/\}/g, ' ').replace(/<[^>]+>/g, ' ')
    .replace(/\{' '\}/g, ' ').replace(/\s+/g, ' ')
  const fuente = (ruta) => readFileSync(new URL(ruta, import.meta.url), 'utf8')
  const metaPixel = fuente('../utils/metaPixel.js')
  const analytics = fuente('../utils/analytics.js')
  const pixelPrendido = /const META_PIXEL_ID = '\d+'/.test(metaPixel)
  const googlePrendido = /const GA_ID = 'G-[A-Z0-9]+'/.test(analytics)
  const privacidad = plano(pagina)
  const entre = (a, b) => {
    const i = pagina.indexOf(a)
    const j = pagina.indexOf(b)
    expect(i, `no encuentro «${a}»`).toBeGreaterThanOrEqual(0)
    expect(j, `no encuentro «${b}»`).toBeGreaterThan(i)
    return plano(pagina.slice(i, j))
  }
  const resumen = entre('Resumen rápido', '1. Introducción')
  const seccion5 = entre('title="5. ', 'title="6. ')
  const seccion7 = entre('title="7. ', 'title="8. ')
  // Sin los comentarios del código: ahí se cuenta qué decía antes.
  const faq = plano(fuente('../components/landing/FAQ.jsx').replace(/^\s*\/\/.*$/gm, ' '))

  it('si el píxel de Meta está prendido, lo dicen el resumen, la §5, la §7 y la portada', () => {
    for (const [donde, texto] of [['el resumen', resumen], ['la §5', seccion5], ['la §7', seccion7], ['la pregunta frecuente', faq]]) {
      expect(/píxel de Meta/i.test(texto), `${donde} tiene que decir si se usa el píxel de Meta`).toBe(pixelPrendido)
    }
  })

  it('si Google Analytics está prendido, lo dicen el resumen, la §5, la §7 y la portada', () => {
    for (const [donde, texto] of [['el resumen', resumen], ['la §5', seccion5], ['la §7', seccion7], ['la pregunta frecuente', faq]]) {
      expect(/Google Analytics/.test(texto), `${donde} tiene que decir si se usa Google Analytics`).toBe(googlePrendido)
    }
  })

  it('la §7 tiene un renglón propio para cada herramienta prendida', () => {
    // Nombrarla de pasada («…y el píxel de Meta no se activa») no alcanza: tiene
    // que estar dicho qué es y para qué.
    expect(/Google Analytics — cuenta las visitas/.test(seccion7)).toBe(googlePrendido)
    expect(/Píxel de Meta — le avisa a Meta/.test(seccion7)).toBe(pixelPrendido)
  })

  it('las cookies que nombra la §7 son las de esas herramientas', () => {
    expect(/_ga\b/.test(seccion7)).toBe(googlePrendido)
    expect(/_fbp\b/.test(seccion7)).toBe(pixelPrendido)
  })

  it('lo que promete de Google es la configuración del código', () => {
    // Si alguien prende las señales de Google o la personalización de anuncios,
    // la frase de la página deja de ser cierta.
    expect(analytics).toMatch(/allow_google_signals:\s*false/)
    expect(analytics).toMatch(/allow_ad_personalization_signals:\s*false/)
    expect(privacidad).toMatch(/sin las funciones de Google para personalizar anuncios/)
  })

  it('la lista de mails para los anuncios de Meta: qué es, quiénes no van y cómo salir', () => {
    // Lo cumple el servidor: backend/tests/test_admin_mails_meta.py (quiénes van).
    expect(seccion5).toMatch(/lista con el email y el nombre/)
    expect(seccion5).toMatch(/No van en esa lista los clientes que dio de alta un asesor ni quienes se dieron de baja de los emails promocionales/)
    expect(faq).toMatch(/te podés dar de baja/)
  })

  it('ninguna de las frases que eran falsas volvió', () => {
    const VIEJAS = [
      /no hay nada de tracking/i,
      /NO usamos[^.]*pixels? de Facebook/i,
      /solo cookies funcionales/i,
      /cookies de terceros con fines de advertising/i,
      /NO hacemos profiling/i,
      /identificarte individualmente con fines publicitarios/i,
      /ni hacemos profiling publicitario/i,
      /los usamos solo para prestarte el servicio/i,
    ]
    for (const [donde, texto] of [['Privacidad', privacidad], ['la pregunta frecuente', faq]]) {
      for (const vieja of VIEJAS) expect(texto, `${donde} volvió a decir ${vieja}`).not.toMatch(vieja)
    }
  })
})
