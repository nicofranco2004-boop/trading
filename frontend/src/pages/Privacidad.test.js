import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { MAX_SEGUNDOS } from '../hooks/useDictado.js'

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
