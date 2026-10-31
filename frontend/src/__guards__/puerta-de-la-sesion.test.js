// 🔴 UNA SOLA PUERTA: «ESTA PESTAÑA INICIA SESIÓN» (re-test a ciegas 7, 31/10).
//
// Antes, la persona de la pestaña la fijaba cada pantalla de entrada con el
// email que tuviera a mano. «Restablecer la contraseña» no lo tenía (el
// servidor no lo devuelve): la pestaña quedaba «de nadie», sin freno ni
// encabezado, y lo que se tocaba se guardaba en la cuenta de quien entrara en
// otra pestaña. La regla vivía en N pantallas y una se quedó afuera.
//
// Ahora hay una puerta, AuthContext.entrar: la persona sale de preguntarle al
// servidor «¿quién soy?» con la sesión nueva. Este guardián da rojo si:
//   · el servidor pone la cookie de sesión en una ruta que no está clasificada
//     acá (una entrada nueva tiene que pasar por la puerta);
//   · una pantalla llama a una ruta de entrada y no pasa por `entrar(`;
//   · algo guarda «quién está logueado», o fija la persona al entrar, fuera de
//     la puerta.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(__dirname, '..')
const MAIN = join(SRC, '..', '..', 'backend', 'main.py')

// Las rutas del servidor que ponen la cookie de sesión, clasificadas.
const ENTRADAS = ['/api/auth/register', '/api/auth/login', '/api/auth/verify-email', '/api/auth/reset-password', '/api/auth/claim']
const NO_SON_ENTRADAS = {
  '/api/auth/change-password': 'rota la cookie de la MISMA persona: sale por utils/api diciendo quién es, y el servidor la rechaza si la sesión es de otra',
}

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
const rel = (p) => relative(SRC, p).split('\\').join('/')
const sinComentarios = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')

describe('la puerta de la sesión', () => {
  it('toda ruta del servidor que pone la cookie de sesión está clasificada', () => {
    const t = readFileSync(MAIN, 'utf8')
    const rutas = new Set()
    let ultima = null
    for (const linea of t.split('\n')) {
      const m = linea.match(/^@app\.(?:post|get|put|patch|delete)\("([^"]+)"/)
      if (m) ultima = m[1]
      if (/^\s+set_auth_cookie\(/.test(linea) && ultima) rutas.add(ultima)
    }
    expect([...rutas].sort(), 'Una ruta nueva que pone la sesión: si alguien entra por ahí, la pantalla '
      + 'tiene que pasar por AuthContext.entrar; sumala a ENTRADAS (o a NO_SON_ENTRADAS con su porqué).')
      .toEqual([...ENTRADAS, ...Object.keys(NO_SON_ENTRADAS)].sort())
  })

  it('toda pantalla que llama a una ruta de entrada pasa por la puerta', () => {
    const llaman = {}
    for (const p of archivos()) {
      const t = sinComentarios(readFileSync(p, 'utf8'))
      for (const r of ENTRADAS) {
        const corta = r.replace(/^\/api/, '')
        if (t.includes(`'${r}'`) || t.includes(`"${r}"`) || t.includes(`\`${r}`) || t.includes(`'${corta}'`)) {
          ;(llaman[rel(p)] ||= []).push(r)
        }
      }
    }
    const sinPuerta = Object.keys(llaman).filter(r => !/\bentrar\(/.test(sinComentarios(readFileSync(join(SRC, r), 'utf8'))))
    expect(Object.keys(llaman).length, 'el censo encuentra las pantallas de entrada').toBeGreaterThan(0)
    expect(sinPuerta, 'Pantallas que ponen la sesión sin pasar por AuthContext.entrar').toEqual([])
  })

  it('«quién está logueado» se guarda sólo por la puerta', () => {
    const fuera = []
    for (const p of archivos()) {
      const r = rel(p)
      const t = sinComentarios(readFileSync(p, 'utf8'))
      const veces = (t.match(/\bguardar\w*\(\s*CATALOGO\.usuario\b/g) || []).length
      if (r === 'contexts/AuthContext.jsx') { if (veces !== 1) fuera.push(`${r}: ${veces} escrituras (sólo guardarSesion)`) }
      else if (r === 'components/ErrorBoundary.jsx') { /* «Limpiar y recargar»: vuelve a poner la MISMA sesión que había */ }
      else if (veces) fuera.push(r)
    }
    expect(fuera).toEqual([])
  })

  it('fijar la persona de la pestaña es cosa de AuthContext; borrar lo de otras, sólo al entrar', () => {
    const fijan = [], borran = []
    for (const p of archivos()) {
      const r = rel(p)
      const t = sinComentarios(readFileSync(p, 'utf8'))
      if (r !== 'utils/api.js' && /\bfijarPersonaDeLaPestana\(/.test(t)) fijan.push(r)
      const n = (t.match(/borrarOtras:\s*true/g) || []).length
      if (n) borran.push(`${r}:${n}`)
    }
    expect(fijan).toEqual(['contexts/AuthContext.jsx'])
    expect(borran, 'una sola vez, adentro de entrar()').toEqual(['contexts/AuthContext.jsx:1'])
  })
})
