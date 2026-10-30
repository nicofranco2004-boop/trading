// 🔴 UNA SOLA PUERTA AL ALMACENAMIENTO DEL NAVEGADOR.
//
// Toda lectura y escritura de localStorage / sessionStorage pasa por
// utils/almacen.js, y sólo con claves de utils/catalogoDelAlmacen.js, donde
// cada una declara qué es (dato de una cuenta, preferencia, la sesión) y por
// qué. Este guardián se pone rojo con CUALQUIER mención de localStorage o
// sessionStorage fuera de la puerta — también entre comillas, como
// `window['localStorage']` —, sin intentar adivinar las formas de escribir.
//
// POR QUÉ (re-test a ciegas 2, 30/10). El censo anterior buscaba
// `.setItem(clave, …)` y tenía puntos ciegos: `localStorage['x'] = …`,
// `localStorage.x = …`, `.call` / `.bind` / `Object.assign`, los envoltorios
// que ya existían (VozContext.guardar, useArrastrable) y el reuso de un nombre
// clasificado como «sin datos» para guardar un total. Con una sola puerta no
// hay formas que adivinar: o se pasa por ella, o hay una mención afuera.
//
// Re-test a ciegas 3 (30/10) encontró cuatro puntos ciegos más, cerrados acá:
// los archivos .ts/.tsx no se miraban; src/testing/ queda afuera del censo, así
// que la app no puede importar de ahí; la familia de la conversación con la IA
// aceptaba cualquier sufijo (ahora declara `restos`); y nada impedía guardar con
// el dueño de la PESTAÑA en vez del de los DATOS (ahora quién lo pide es una
// lista cerrada).
//
// Lo que queda abierto, dicho: armar el nombre a propósito para esquivarlo
// ('local' + 'Storage'), reusar una entrada del catálogo para guardar otra
// cosa, y otros almacenes del navegador (cookies, IndexedDB, window.name: hoy
// la app no usa ninguno). Eso no lo frena una máquina: lo frena que cada
// entrada dice qué guarda.
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { CATALOGO, CON_DUENO, DUENO_PROPIO, PREFERENCIA, SESION_MECANICA, LOCAL, SESION } from '../utils/catalogoDelAlmacen'

const SRC = join(__dirname, '..')
const PUERTA = 'utils/almacen.js'

// Los archivos de la app (sin pruebas ni ayudas de prueba).
function archivos(dir = SRC, out = []) {
  for (const n of readdirSync(dir)) {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) {
      if (n === '__guards__' || n === 'testing' || n === '__design__') continue
      archivos(p, out)
    } else if (/\.(js|jsx|ts|tsx)$/.test(n) && !/\.test\.|\.spec\./.test(n)) out.push(p)
  }
  return out
}

// El código sin comentarios (los textos entre comillas quedan: una mención
// entre comillas también cuenta).
function sinComentarios(t) {
  let out = '', i = 0, comilla = null
  while (i < t.length) {
    const c = t[i], d = t[i + 1]
    if (comilla) {
      out += c
      if (c === '\\') { out += d ?? ''; i += 2; continue }
      if (c === comilla) comilla = null
      i++; continue
    }
    if (c === '/' && d === '/') { while (i < t.length && t[i] !== '\n') i++; continue }
    if (c === '/' && d === '*') { const f = t.indexOf('*/', i + 2); i = f === -1 ? t.length : f + 2; continue }
    if (c === '\'' || c === '"' || c === '`') comilla = c
    out += c; i++
  }
  return out
}

const MENCION = /(local|session)Storage|\bStorage\s*\.\s*prototype/

describe('una sola puerta al almacenamiento del navegador', () => {
  it('nadie fuera de utils/almacen.js nombra localStorage ni sessionStorage', () => {
    const afuera = []
    for (const p of archivos()) {
      const rel = relative(SRC, p).split('\\').join('/')
      if (rel === PUERTA) continue
      sinComentarios(readFileSync(p, 'utf8')).split('\n').forEach((l, i) => {
        if (MENCION.test(l)) afuera.push(`${rel}:${i + 1}  ${l.trim().slice(0, 100)}`)
      })
    }
    expect(afuera, 'Esto toca el almacenamiento del navegador sin pasar por la puerta. Usá '
      + 'utils/almacen.js con una entrada de utils/catalogoDelAlmacen.js: si guarda algo de UNA '
      + 'cuenta (montos, nombres, lo que la persona hizo), CON_DUENO y leerDe/guardarDe con el '
      + 'dueño de los datos; si no, PREFERENCIA o SESION, con su porqué.').toEqual([])
  })

  it('cada entrada del catálogo dice qué es, dónde vive y por qué', () => {
    const tipos = [CON_DUENO, DUENO_PROPIO, PREFERENCIA, SESION_MECANICA]
    for (const [nombre, e] of Object.entries(CATALOGO)) {
      expect(tipos, `${nombre}: tipo`).toContain(e.tipo)
      expect([LOCAL, SESION], `${nombre}: donde`).toContain(e.donde)
      expect((e.porque || '').trim(), `${nombre}: falta el porqué`).not.toBe('')
      expect((e.clave != null) !== (e.prefijo != null), `${nombre}: clave O prefijo`).toBe(true)
      if (e.tipo === CON_DUENO) expect(e.prefijo, `${nombre}: un dato con dueño va por prefijo`).toBeTruthy()
    }
  })

  it('ninguna clave pisa a otra (ni una familia se come a otra entrada)', () => {
    const lista = Object.entries(CATALOGO).map(([n, e]) => [n, e.clave ?? e.prefijo, e.prefijo != null])
    for (const [n1, k1, esFamilia] of lista) {
      for (const [n2, k2] of lista) {
        if (n1 === n2) continue
        expect(k1 === k2 || (esFamilia && k2.startsWith(k1)), `${n1} y ${n2}`).toBe(false)
      }
    }
  })

  it('una familia que no es de una cuenta dice qué sufijos acepta', () => {
    for (const [nombre, e] of Object.entries(CATALOGO)) {
      if (e.prefijo == null || e.tipo === CON_DUENO) continue
      expect(e.restos instanceof RegExp, `${nombre}: falta \`restos\``).toBe(true)
      expect(e.restos.source, `${nombre}: \`restos\` va anclado (^…$)`).toMatch(/^\^.*\$$/)
    }
  })

  it('la app no importa de src/testing (queda afuera de este censo)', () => {
    const importan = []
    for (const p of archivos()) {
      const rel = relative(SRC, p).split('\\').join('/')
      if (/from\s+['"][^'"]*\/testing\/|import\(\s*['"][^'"]*\/testing\//.test(sinComentarios(readFileSync(p, 'utf8')))) importan.push(rel)
    }
    expect(importan).toEqual([])
  })

  // Guardar con el dueño de la PESTAÑA (el de ahora) en vez del de los DATOS
  // (el de cuando se cargaron) es justo lo que la regla frena. Quién pregunta
  // por el dueño de la pestaña es una lista cerrada, cada uno con su porqué.
  const PIDEN_EL_DE_LA_PESTANA = {
    'utils/duenoDeLaPestana.js': 'es la regla',
    'utils/valoresVistos.js': 'sube la versión de la cartera de la pestaña tras una escritura que hizo esta misma pestaña, en el mismo instante',
    'utils/dibujos.js': 'el gráfico SIGUE a la pestaña (useDuenoDeLaCopia): si cambia la cuenta, se vacía y carga los de la nueva; lo que guarda y sube lo hace con el dueño de los dibujos en pantalla',
  }
  it('pedir el dueño de la pestaña (no el de los datos) es una lista cerrada', () => {
    const piden = new Set()
    for (const p of archivos()) {
      const rel = relative(SRC, p).split('\\').join('/')
      // Cualquier mención, no sólo la llamada: un alias (`const x = duenoDeLaPestana`) también cuenta.
      // (La ruta del módulo, './duenoDeLaPestana', no es una mención.)
      const codigo = sinComentarios(readFileSync(p, 'utf8')).replace(/(['"`])[^'"`\n]*\/duenoDeLaPestana(\.js)?\1/g, '')
      if (/\b(duenoDeLaPestana|useDuenoDeLaPestana|duenoPropioDeLaPestana)\b/.test(codigo)) piden.add(rel)
    }
    expect([...piden].sort(), 'Para guardar o mandar algo de una cuenta, usá useDuenoDeLosDatos (el dueño '
      + 'de cuando la pantalla pidió los datos), no el de la pestaña.').toEqual(Object.keys(PIDEN_EL_DE_LA_PESTANA).sort())
  })

  it('«dueño propio» es una lista cerrada', () => {
    const propios = Object.entries(CATALOGO).filter(([, e]) => e.tipo === DUENO_PROPIO).map(([n]) => n).sort()
    expect(propios, 'no se suman datos con un dueño propio: usan la regla (CON_DUENO)')
      .toEqual(['conversacionIA', 'instaladaAvisada'])
  })
})

describe('la puerta frena', () => {
  let almacen, api
  beforeAll(async () => {
    instalarNavegadorMinimo()
    almacen = await import('../utils/almacen')
    api = await import('../utils/api')
    await import('../utils/duenoDeLaPestana')        // registra la regla en la puerta
  })
  afterEach(() => { localStorage.clear(); sessionStorage.clear(); api.setClientContext(null) })
  const entrar = (email) => localStorage.setItem('rendi_user', JSON.stringify({ email }))

  it('una clave que no está en el catálogo no se lee ni se escribe', () => {
    expect(() => almacen.leer({ clave: 'rendi_total', donde: LOCAL, tipo: PREFERENCIA, porque: 'x' })).toThrow(/no está en utils\/catalogoDelAlmacen/)
    expect(() => almacen.guardar('rendi_total', 1)).toThrow(/no está en utils\/catalogoDelAlmacen/)
  })

  it('un dato de una cuenta no se escribe como preferencia, ni al revés', () => {
    expect(() => almacen.guardar(CATALOGO.fotoDelDia, '2026-10-30')).toThrow(/dueño/)
    expect(() => almacen.guardarDe(CATALOGO.tema, 'ana@x|propia', 'dark')).toThrow(/no es un dato/)
  })

  it('un dato no se guarda a nombre de un dueño que ya no es el de la pestaña', () => {
    entrar('ana@prueba.test')
    const deAna = 'ana@prueba.test|propia'
    expect(almacen.guardarDe(CATALOGO.fotoDelDia, deAna, 'hoy')).toBe(true)
    entrar('bruno@prueba.test')                          // otra pestaña cambió la sesión
    expect(almacen.guardarDe(CATALOGO.fotoDelDia, deAna, 'otro')).toBe(false)
    expect(almacen.leerDe(CATALOGO.fotoDelDia, deAna)).toBe('hoy')   // no se pisó
    expect(almacen.leerDe(CATALOGO.fotoDelDia, 'bruno@prueba.test|propia')).toBeNull()
    api.setClientContext({ id: 3, label: 'Tres' })
    expect(almacen.guardarDe(CATALOGO.fotoDelDia, 'bruno@prueba.test|propia', 'x')).toBe(false)
    expect(almacen.guardarDe(CATALOGO.fotoDelDia, null, 'x')).toBe(false)
  })

  it('la familia de la conversación sólo acepta los sufijos que declara', () => {
    expect(() => almacen.guardar(CATALOGO.conversacionIA, '[]', 'v1_c3')).not.toThrow()
    expect(() => almacen.guardar(CATALOGO.conversacionIA, '1', 'total_cartera')).toThrow(/no es de las que declara/)
    expect(() => almacen.leer(CATALOGO.conversacionIA, 'v1_c3_x')).toThrow(/no es de las que declara/)
  })

  it('lo del asesor a su nivel (la tanda) es de la persona aunque tenga un cliente abierto', () => {
    entrar('asesora@prueba.test')
    api.setClientContext({ id: 2, label: 'Dos' })
    expect(almacen.guardarDe(CATALOGO.tandaAsesor, 'asesora@prueba.test|propia', '{}')).toBe(true)
    expect(almacen.guardarDe(CATALOGO.tandaAsesor, 'asesora@prueba.test|cliente-2', '{}')).toBe(false)
  })
})
