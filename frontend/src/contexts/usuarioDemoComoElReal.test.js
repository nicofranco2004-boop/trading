import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mapMeToUser, DEMO_USER } from './AuthContext'
import { quienEs } from '../utils/quienEs'

// 🔴 LO QUE ANDA EN EL DEMO TIENE QUE ANDAR EN LAS CUENTAS DE VERDAD (2026-10-07).
//
// El usuario de verdad lo arma mapMeToUser con lo que manda /auth/me, y copia
// una lista FIJA de campos. El del demo está escrito a mano. Cuando el de
// demo tenía un campo que el real no, todo lo que lo leía andaba en el demo
// —donde se prueba— y en ninguna cuenta de verdad:
//   · `id`         → el buscador ⌘K nunca pedía tus activos ("nvda" + Enter
//                    llevaba a la empresa, no a tu posición).
//   · `created_at` → "Miembro desde" en Configuración decía "—".
// Antes, la lectura de la cartera para la IA ya se había armado con `user.id`
// y había quedado igual para todos (auditoría 2026-10-05).

const REAL = mapMeToUser({})   // todos sus campos salen siempre, con o sin dato

describe('el usuario del demo tiene la forma del de verdad', () => {
  it('ni un campo que el de verdad no tenga (salvo `demo`, que lo distingue)', () => {
    const deMas = Object.keys(DEMO_USER).filter(k => k !== 'demo' && !(k in REAL))
    expect(deMas).toEqual([])
  })

  it('"Miembro desde": la fecha de alta que manda /auth/me llega al usuario', () => {
    expect(mapMeToUser({ email: 'a@x.com', created_at: '2025-03-01 12:00:00' }).created_at).toBe('2025-03-01 12:00:00')
  })

  it('la app no lee de la persona un campo que el usuario de verdad no trae', () => {
    // Recorre el código de la app (no las pruebas) buscando `user.X` /
    // `user?.X`. Hueco declarado: si alguien lo llama distinto (`u.id`), no lo
    // ve — Admin.jsx usa `u.id` para los usuarios de la lista, que sí lo traen.
    const raiz = join(dirname(fileURLToPath(import.meta.url)), '..')
    const archivos = []
    const recorrer = (dir) => {
      for (const n of readdirSync(dir)) {
        const p = join(dir, n)
        if (statSync(p).isDirectory()) { if (n !== 'testing' && n !== '__design__') recorrer(p); continue }
        if (/\.(js|jsx)$/.test(n) && !/\.test\./.test(n)) archivos.push(p)
      }
    }
    recorrer(raiz)
    const permitidos = new Set([...Object.keys(REAL), 'demo'])
    const raros = []
    for (const p of archivos) {
      // Sin comentarios: los que cuentan esta historia nombran `user.id`.
      const codigo = readFileSync(p, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1')
      for (const m of codigo.matchAll(/\buser\??\.([A-Za-z_]\w*)/g)) {
        if (!permitidos.has(m[1])) raros.push(`${relative(raiz, p)}: user.${m[1]}`)
      }
    }
    expect(raros).toEqual([])
  })
})

describe('quién es la persona: una sola regla', () => {
  it('el email, sin espacios y en minúsculas; null sin sesión', () => {
    expect(quienEs(mapMeToUser({ id: 7, email: 'Ana@X.com ' }))).toBe('ana@x.com')
    expect(quienEs(null)).toBeNull()
    expect(quienEs({})).toBeNull()
    expect(quienEs(DEMO_USER)).not.toBeNull()
  })
})
