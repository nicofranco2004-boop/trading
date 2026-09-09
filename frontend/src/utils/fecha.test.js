/**
 * La fecha por defecto de una operación cargada a las 22:00 era la de mañana.
 *
 * EL BUG (auditoría 1B, H-10). Veintisiete lugares del frontend calculaban "hoy"
 * con `new Date().toISOString().slice(0, 10)`, que es el día UTC. De 21:00 a
 * 23:59 hora argentina eso devuelve mañana.
 *
 * Lo que hace daño no es la pantalla: son los DEFAULTS PERSISTIDOS. Esos 27
 * sitios fijan la fecha de una compra, una venta, un movimiento de caja, un
 * cupón, un plazo fijo y un futuro. El backend los aceptaba, porque su guard de
 * fecha futura compara contra el reloj del proceso, que en Railway también es
 * UTC. Es la misma clase de fila que dejó 25 cupones de AL35 fechados en 2027.
 *
 * EL ARREGLO YA EXISTÍA EN 1 DE 28. `AdvisorDashboard.jsx` lo tenía con su
 * comentario de auditoría; los otros 27 nunca lo recibieron. El patrón exacto que
 * la auditoría midió como causa raíz dominante del repo.
 *
 * POR QUÉ EL SEGUNDO TEST LEE CÓDIGO. Un test sobre `hoyISO()` pasa igual aunque
 * mañana alguien escriba el número 28 en otro archivo — y ese es el bug.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { fechaISO, hoyISO, hoyMasDias } from './fecha.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(AQUI, '..')

describe('fechaISO — el día calendario del usuario, no el UTC', () => {
  it('las 22:00 del 9 de septiembre son el 9 de septiembre', () => {
    // `new Date(y, m, d, h)` construye en hora LOCAL: son las 22:00 de acá.
    const nocheDelNueve = new Date(2026, 8, 9, 22, 0, 0)
    expect(fechaISO(nocheDelNueve)).toBe('2026-09-09')
  })

  it('y es exactamente ahí donde toISOString se equivocaba', () => {
    const nocheDelNueve = new Date(2026, 8, 9, 22, 0, 0)
    const viejo = nocheDelNueve.toISOString().slice(0, 10)
    if (nocheDelNueve.getTimezoneOffset() > 0) {
      // Husos al oeste de Greenwich (Argentina entre ellos): UTC ya es mañana.
      expect(viejo).toBe('2026-09-10')
      expect(fechaISO(nocheDelNueve)).not.toBe(viejo)
    } else {
      // El runner corre en UTC o al este: acá los dos coinciden y no hay bug
      // que observar. Se deja dicho en vez de simular un huso.
      expect(fechaISO(nocheDelNueve)).toBe(viejo)
    }
  })

  it('zero-padea mes y día', () => {
    expect(fechaISO(new Date(2026, 0, 5, 12, 0, 0))).toBe('2026-01-05')
  })

  it('una fecha inválida devuelve null en vez de reventar', () => {
    expect(fechaISO(new Date('no soy una fecha'))).toBeNull()
    expect(fechaISO('2026-09-09')).toBeNull()
    expect(fechaISO(null)).toBeNull()
  })

  it('hoyISO es fechaISO de ahora, y hoyMasDias se mueve de a un día', () => {
    expect(hoyISO()).toBe(fechaISO(new Date()))
    expect(hoyISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    const ayer = new Date(); ayer.setDate(ayer.getDate() - 1)
    expect(hoyMasDias(-1)).toBe(fechaISO(ayer))
  })
})

describe('"hoy" se calcula en un solo lugar', () => {
  const EXCLUIDOS = new Set(['demo.js', 'fecha.js', 'fecha.test.js'])

  function fuentes(dir) {
    const salida = []
    for (const nombre of readdirSync(dir)) {
      const ruta = join(dir, nombre)
      if (statSync(ruta).isDirectory()) { salida.push(...fuentes(ruta)); continue }
      if (!/\.jsx?$/.test(nombre) || nombre.includes('.test.') || EXCLUIDOS.has(nombre)) continue
      salida.push(ruta)
    }
    return salida
  }

  it('ningún archivo vuelve a sacar el día de toISOString', () => {
    const culpables = []
    for (const ruta of fuentes(SRC)) {
      const lineas = readFileSync(ruta, 'utf-8').split('\n')
      lineas.forEach((linea, i) => {
        if (/new Date\(\)\.toISOString\(\)\.slice\(0,\s*10\)/.test(linea)) {
          culpables.push(`${ruta.slice(SRC.length + 1)}:${i + 1}`)
        }
      })
    }
    expect(culpables, 'usá `import { hoyISO } from "utils/fecha"`').toEqual([])
  })

  it('las marcas de tiempo SIGUEN en UTC, que es lo correcto para un instante', () => {
    // Contraprueba del guard de arriba: no se barrió `toISOString()` entero.
    // `created_at`, el `ts` de analytics y el `since` de los permisos son
    // INSTANTES, no días calendario, y en UTC están bien.
    const conTimestamp = fuentes(SRC).filter(r => {
      const t = readFileSync(r, 'utf-8')
      return /new Date\(\)\.toISOString\(\)(?!\.slice)/.test(t)
    })
    expect(conTimestamp.length).toBeGreaterThan(0)
  })
})
