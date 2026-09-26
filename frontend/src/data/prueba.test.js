import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { archivosConTexto, esPublica, relativa, sinComentarios } from '../../scripts/texto-visible.mjs'
import {
  CTA_PRUEBA, PRUEBA_EN_UNA_LINEA, PASO_CREAR_CUENTA, alTerminar, conservaElFree,
} from './prueba'
import { TRIAL_TOTAL_DAYS, TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS } from './planCatalog'

describe('las frases de la prueba salen de los días del catálogo', () => {
  it('el botón y el paso dicen el total', () => {
    expect(CTA_PRUEBA).toBe(`Probar ${TRIAL_TOTAL_DAYS} días gratis`)
    expect(PASO_CREAR_CUENTA.title).toContain(`${TRIAL_TOTAL_DAYS} días gratis`)
  })

  it('la oración dice las dos etapas y que no hay tarjeta', () => {
    expect(PRUEBA_EN_UNA_LINEA).toContain(`${TRIAL_PRO_DAYS} días con Pro`)
    expect(PRUEBA_EN_UNA_LINEA).toContain(`${TRIAL_PLUS_DAYS} con Plus`)
    expect(PRUEBA_EN_UNA_LINEA).toMatch(/sin tarjeta/i)
    expect(PASO_CREAR_CUENTA.desc).toBe(PRUEBA_EN_UNA_LINEA)
  })
})

describe('qué pasa cuando se termina lo que tenía', () => {
  it('quien nació sin plan gratis queda en pausa, no "vuelve a Free"', () => {
    expect(alTerminar(true)).toMatch(/en pausa/)
    expect(alTerminar(true)).not.toMatch(/free/i)
  })

  it('quien ya tenía el Free vuelve a él, como siempre', () => {
    expect(alTerminar(false)).toMatch(/vuelve a Free/)
    // `requires_plan` puede venir ausente (usuarios de antes del campo).
    expect(alTerminar(undefined)).toBe(alTerminar(false))
  })
})

describe('a quién se le muestra la tarjeta de Free en /planes', () => {
  it('al visitante sin sesión, no: si se registra, arranca la prueba', () => {
    expect(conservaElFree(null)).toBe(false)
    expect(conservaElFree(undefined)).toBe(false)
  })

  it('al que se registró con la prueba, tampoco — ni en pausa ni pagando', () => {
    expect(conservaElFree({ tier: 'free', requires_plan: true })).toBe(false)
    expect(conservaElFree({ tier: 'plus', requires_plan: true })).toBe(false)
  })

  it('al demo, tampoco: es un visitante mirando la app', () => {
    expect(conservaElFree({ tier: 'pro', demo: true })).toBe(false)
  })

  it('a la cuenta vieja, sí: el Free es su plan, o al que vuelve si cancela', () => {
    expect(conservaElFree({ tier: 'free', requires_plan: false })).toBe(true)
    expect(conservaElFree({ tier: 'pro', requires_plan: false })).toBe(true)
  })
})

// ── Las páginas públicas no vuelven a ofrecer el plan Free ──────────────────
// Esto lee los ARCHIVOS, como `Privacidad.test.js`: el texto de una página
// pública es el producto, y una promesa vieja no rompe ningún test ni tira
// ningún error — sale en Google y calla. Son las páginas que lee alguien que
// todavía no tiene cuenta, o sea alguien que nunca va a tener el plan Free.
//
// Qué páginas son públicas lo dice `scripts/texto-visible.mjs`, por carpeta: la
// misma definición que usa el guard del nombre de la IA. Acá había una lista a
// mano de 17 archivos que no incluía, por ejemplo, /planes ni el índice del blog.
const PUBLICAS = archivosConTexto().filter(esPublica)
const leer = (rel) => readFileSync(new URL(`../${rel}`, import.meta.url), 'utf8')
// El texto como lo lee la persona, sin comentarios (que SÍ nombran el bug para
// explicarlo; los decide un parser, ver texto-visible.mjs), en dos versiones:
//   · sin etiquetas ni cortes de línea: sin sacarlas, "vuelve a
//     <strong>Free</strong> automáticamente" se le escapaba al patrón;
//   · con las etiquetas: sacándolas se iban también sus ATRIBUTOS, que es donde
//     están la metaDescription de cada página y los <meta> que lee Google.
const textosVisibles = (ruta) => {
  const texto = sinComentarios(ruta, readFileSync(ruta, 'utf8'))
  const plano = (s) => s.replace(/\{' '\}/g, ' ').replace(/\s+/g, ' ')
  return [plano(texto.replace(/<[^>]+>/g, ' ')), plano(texto)]
}

// Las formas en que estas páginas ofrecían el Free. No se prohíbe NOMBRAR el
// plan Free (la guía lo explica para las cuentas que lo conservan): se prohíbe
// ofrecerlo.
const OFERTAS = [
  /gratis para siempre/i,
  /free para siempre/i,
  /plan free (te alcanza|te permite|cubre|suficiente|es gratis)/i,
  /free incluye/i,
  /crear cuenta gratis|creá tu cuenta gratis|empezar gratis|empezá gratis/i,
  /vuelve a free (automáticamente|de forma automática)/i,
  /ofrece un plan gratuito/i,
  /volvés al plan free/i,
]

describe('ninguna página pública ofrece el plan Free', () => {
  it('se leen, como mínimo, las 17 que se vigilaban a mano', () => {
    // Contra el falso verde: si el recorrido se rompe, las de abajo pasan sin
    // mirar nada. Éstas son las que ofrecían el Free el 22/09.
    const leidas = PUBLICAS.map(relativa)
    for (const rel of [
      'components/landing/FAQ.jsx', 'components/landing/KeywordLanding.jsx',
      'components/blog/BlogPost.jsx', 'components/guide/GuidePage.jsx', 'pages/Landing.jsx',
      'pages/keywords/Cedears.jsx', 'pages/keywords/Cocos.jsx', 'pages/keywords/IOL.jsx',
      'pages/keywords/Binance.jsx', 'pages/keywords/BonosAR.jsx', 'pages/keywords/AfipCripto.jsx',
      'pages/blog/articles/ComparativaBrokersArgentina.jsx', 'pages/guia/Empezar.jsx',
      'pages/guia/CuentaYPlanes.jsx', 'pages/Terminos.jsx', 'pages/Reembolso.jsx',
      'pages/Privacidad.jsx',
    ]) {
      expect(leidas, rel).toContain(`src/${rel}`)
    }
  })

  for (const ruta of PUBLICAS) {
    it(relativa(ruta), () => {
      for (const texto of textosVisibles(ruta)) {
        for (const oferta of OFERTAS) {
          expect(texto, `${relativa(ruta)} volvió a ofrecer el Free (${oferta})`).not.toMatch(oferta)
        }
      }
    })
  }
})

// ── Los legales dicen los días de la prueba con número ──────────────────────
// En Términos los días están escritos a mano A PROPÓSITO: es un texto con fecha
// de versión, y un número que cambia solo cambiaría el contrato sin cambiar la
// fecha. Este test es el que avisa: si la prueba cambia de largo, se pone en
// rojo, y quien lo arregla tiene que actualizar el párrafo Y la fecha.
describe('Términos dice la prueba que da el producto', () => {
  const terminos = leer('pages/Terminos.jsx').replace(/\s+/g, ' ')
  it('el total, y las dos etapas', () => {
    expect(terminos).toContain(`prueba gratuita de ${TRIAL_TOTAL_DAYS} días`)
    expect(terminos).toContain(`primeros ${TRIAL_PRO_DAYS} días con el plan Pro`)
    expect(terminos).toContain(`los ${TRIAL_PLUS_DAYS} siguientes con el plan Plus`)
  })
  it('y qué pasa si no elegís un plan', () => {
    expect(terminos).toMatch(/queda en pausa y tus datos se conservan/)
  })
})
