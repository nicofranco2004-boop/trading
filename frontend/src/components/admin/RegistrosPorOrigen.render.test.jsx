// El panel «Registros por origen» de /admin dibujado con una ventana como la
// que arma el servidor (`_registros_por_origen` en backend/main.py). Las claves
// son las que fija `test_lo_que_manda_el_panel` en
// backend/tests/test_origen_registros.py: si el servidor cambia una, se pone
// rojo allá.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { VentanaDeOrigenes } from './RegistrosPorOrigen'

const canal = (id, nombre, registros, confirmaron = 0, cargaron = 0) =>
  ({ canal: id, nombre, explica: `Qué entra en ${nombre}`, registros, confirmaron, cargaron })
const origen = (codigo, id, fuente, registros, confirmaron = 0, cargaron = 0) =>
  ({ origen: codigo, registros, confirmaron, cargaron, canal: id, fuente })

const VENTANA = {
  desde: '2026-10-31', hasta: '2026-11-06', registros: 8, con_dato: 7,
  canales: [
    canal('ia', 'IA', 1, 1),
    canal('x', 'X', 2, 1, 1),
    canal('meta_anuncios', 'Meta (anuncios)', 0),
    canal('meta_posts', 'Meta (tus posts)', 0),
    canal('meta_sin_saber', 'Meta (sin saber si fue anuncio)', 3, 1),
    canal('google', 'Google', 0),
    canal('otro_codigo', 'Otro link con código', 0),
    canal('otro_sitio', 'Otro sitio o app', 1),
    canal('sin_dato', 'Sin dato', 1),
  ],
  origenes: [
    origen('sitio/l.instagram.com/fbclid', 'meta_sin_saber', 'Instagram', 3, 1),
    origen('x-20261019', 'x', null, 1, 1, 1),
    origen('sitio/t.co', 'x', 'X', 1),
    origen('chatgpt.com', 'ia', 'ChatGPT', 1, 1),
    origen('app/com.google.android.gm', 'otro_sitio', 'Gmail', 1),
    origen(null, 'sin_dato', null, 1),
  ],
}

const texto = (v) => renderToStaticMarkup(<VentanaDeOrigenes v={v} />)
  .replace(/<[^>]+>/g, ' ')
  .replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
  .replace(/\s+/g, ' ')

describe('el panel de registros por origen', () => {
  it('arriba, los canales en el orden del servidor, también los que dan 0', () => {
    const t = texto(VENTANA)
    const nombres = VENTANA.canales.map(c => c.nombre)
    const donde = nombres.map(n => t.indexOf(` ${n} Qué entra en ${n} `))
    for (let i = 0; i < nombres.length; i++) expect(donde[i], nombres[i]).toBeGreaterThan(-1)
    expect([...donde].sort((a, b) => a - b)).toEqual(donde)
    // «Meta (anuncios): 0» es un dato: se ve, con su cero.
    expect(t).toContain('Meta (anuncios) Qué entra en Meta (anuncios) 0 0 0')
    // Y el resumen va antes que el detalle.
    expect(t.indexOf('Canal Registros')).toBeLessThan(t.indexOf('Código o sitio Registros'))
  })

  it('cada código dice de dónde es y en qué canal cayó, sin repetir', () => {
    const t = texto(VENTANA)
    expect(t).toContain('sitio/l.instagram.com/fbclid Instagram · Meta (sin saber si fue anuncio) 3 1 · 33%')
    expect(t).toContain('chatgpt.com ChatGPT · IA')
    expect(t).toContain('app/com.google.android.gm Gmail · Otro sitio o app')
    expect(t).toContain('x-20261019 X 1 1 · 100% 1 · 100%')
    // t.co es «X» en el canal X: una vez, no «X · X».
    expect(t).toContain('sitio/t.co X 1')
    expect(t).not.toContain('X · X')
    expect(t).toContain('Sin dato 1')
  })

  it('la cuenta de arriba dice de cuántos se sabe de dónde vinieron', () => {
    expect(texto(VENTANA)).toContain('8 registros · de 7 se sabe de dónde vinieron')
    expect(texto({ ...VENTANA, registros: 1, con_dato: 1 })).toContain('1 registro · de 1 se sabe de dónde vino')
  })

  it('el pie dice cómo marcar los anuncios de Meta, con las llaves tal cual', () => {
    expect(texto(VENTANA)).toContain('utm_source=meta-anuncios&utm_campaign={{campaign.name}}')
  })

  it('sin registros no dibuja una tabla de ceros', () => {
    const vacia = { ...VENTANA, registros: 0, con_dato: 0, origenes: [],
      canales: VENTANA.canales.map(c => ({ ...c, registros: 0, confirmaron: 0, cargaron: 0 })) }
    const t = texto(vacia)
    expect(t).toContain('Nadie se registró en este período.')
    expect(t).toContain('0 registros')
    expect(t).not.toContain('se sabe de dónde')
    expect(t).not.toContain('Canal Registros')
  })

  it('con la respuesta de antes (sin canales) no se rompe: muestra el detalle', () => {
    const vieja = { desde: VENTANA.desde, hasta: VENTANA.hasta, registros: 2, con_codigo: 1,
      origenes: [{ origen: 'x-1019', registros: 1, confirmaron: 0, cargaron: 0 },
        { origen: null, registros: 1, confirmaron: 0, cargaron: 0 }] }
    const t = texto(vieja)
    expect(t).toContain('x-1019 1')
    expect(t).not.toContain('Canal Registros')
  })
})
