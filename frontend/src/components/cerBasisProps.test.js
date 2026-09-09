// La serie de ajuste de los bonos CER tiene que llegar entera, y decir cuál es.
//
// POR QUÉ ESTE TEST
// ─────────────────
// La fuente de CER (`api.argentinadatos.com/.../indices/cer`) devuelve 404 desde
// hace meses. El backend ahora sirve UVA en su lugar —el BCRA la actualiza POR
// CER, así que el RATIO entre dos fechas es el mismo— y lo declara en `basis`.
//
// Ese dato tiene que viajar Positions → RentaFijaSections → BondDetail. Si se
// cae en el camino, la pantalla vuelve a rotular como "CER" un ajuste hecho con
// otra serie: el número sería correcto y el rótulo mentiría. Es el mismo defecto
// que la tanda F2 arregló en el Wrapped, en otra pantalla.
//
// Y el segundo caso: sin serie, la tarjeta se contradecía sola. Arriba decía
// "Serie CER no disponible — flujos en nominal sin ajuste" y doce líneas abajo
// rotulaba el número grande como "TIR real (sobre CER)… es lo que ganás POR
// ENCIMA de la inflación". Sin ajuste no es real: es nominal.
//
// CÓMO FUNCIONA
// ─────────────
// No hay jsdom en este proyecto (ver `pages/sellModalProps.test.js`, mismo
// patrón): se verifica sobre el CÓDIGO FUENTE.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { finDeEtiqueta } from '../pages/sellModalProps.test.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

function archivosJsx(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivosJsx(p)
    return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
  })
}

/** Índice del `)` que cierra el paréntesis abierto en `desde`. */
function finDeParentesis(src, desde) {
  let d = 0
  for (let i = desde; i < src.length; i++) {
    if (src[i] === '(') d++
    else if (src[i] === ')') { d--; if (d === 0) return i + 1 }
  }
  return src.length
}

/** Cada render de un componente, con su archivo y su bloque de props. */
function renders(tag) {
  const out = []
  for (const f of archivosJsx(SRC)) {
    const src = readFileSync(f, 'utf8')
    let i = src.indexOf(`<${tag}`)
    while (i !== -1) {
      out.push({ archivo: f.slice(SRC.length + 1), props: src.slice(i, finDeEtiqueta(src, i)) })
      i = src.indexOf(`<${tag}`, i + 1)
    }
  }
  return out
}

describe('el basis del ajuste CER viaja hasta la tarjeta', () => {
  it('quien renderiza la tarjeta del bono le pasa cerBasis', () => {
    const rs = renders('BondDetail')
    expect(rs.length).toBeGreaterThan(0)
    for (const r of rs) {
      // Sólo los que ya pasan la serie: el que no ajusta no necesita el rótulo.
      if (!/cerSeries/.test(r.props)) continue
      expect(r.props, `${r.archivo}: renderiza la tarjeta sin cerBasis`).toMatch(/cerBasis/)
    }
  })

  it('quien renderiza la zona de renta fija también', () => {
    for (const r of renders('RentaFijaSections')) {
      if (!/cerSeries/.test(r.props)) continue
      expect(r.props, `${r.archivo}: sin cerBasis`).toMatch(/cerBasis/)
    }
  })

  it('el fetch lee `basis` de la respuesta, no lo asume', () => {
    // El fetch vive en el hook desde que la serie se comparte con las pantallas
    // de eventos (antes lo hacía Positions a mano, y sólo al expandir un bono).
    const src = readFileSync(join(SRC, 'hooks/useCerSeries.js'), 'utf8')
    expect(src).toMatch(/res\?\.basis/)
    expect(src).toMatch(/\|\| 'CER'/)   // backend viejo → no rompe
  })

  it('la serie se pide en UN solo lugar', () => {
    const malos = []
    for (const f of archivosJsx(SRC)) {
      if (/hooks\/useCerSeries\.js$/.test(f)) continue
      const src = readFileSync(f, 'utf8')
      if (/['\`]\/bond-indices/.test(src)) malos.push(f.slice(SRC.length + 1))
    }
    expect(malos, 'alguien volvió a pedir la serie por su cuenta').toEqual([])
  })
})

describe('la tarjeta no afirma un ajuste que no ocurrió', () => {
  const src = readFileSync(join(SRC, 'components/BondDetail.jsx'), 'utf8')

  it('el rótulo "TIR real (sobre CER)" está condicionado al factor', () => {
    // ⚠️ Se ancla al texto RENDERIZADO (`>…<`), no al texto suelto: el comentario
    // que explica el bug cita el rótulo, y un `indexOf` pelado lo encontraba a él
    // primero — el test pasaba en verde midiendo un comentario.
    const i = src.indexOf('>TIR real (sobre CER) a precio de hoy<')
    expect(i, 'no está el rótulo renderizado').toBeGreaterThan(-1)
    // Justo antes tiene que estar el chequeo de que el ajuste EXISTE. La rama
    // del ternario entra en pocos cientos de caracteres; el otro uso de
    // `cerFactorToday` (la línea del factor) está a ~5.000.
    const antes = src.slice(Math.max(0, i - 500), i)
    expect(antes, 'el rótulo se publica sin chequear que haya ajuste')
      .toMatch(/cerFactorToday\s*!=\s*null/)
  })

  it('sin ajuste, el rótulo dice nominal', () => {
    expect(src).toMatch(/TIR nominal — sin ajuste por CER/)
  })
})

describe('el ajuste llega al pago que se REGISTRA, no sólo al que se muestra', () => {
  // `nextPaymentForPosition` acepta options desde que el cronograma se ajusta.
  // Un caller que la llame sin ellas muestra el pago en nominal al lado de un
  // "factor hoy ≈ 37×" — y el del modal además lo escribe.
  it('ningún caller llama a nextPaymentForPosition sin las options del CER', () => {
    const malos = []
    for (const f of archivosJsx(SRC)) {
      if (/utils\/bondSchedule\.js$/.test(f)) continue      // la definición
      const src = readFileSync(f, 'utf8')
      for (const fn of ['nextPaymentForPosition(', 'generateSchedule(']) {
        let i = src.indexOf(fn)
        while (i !== -1) {
          // Paréntesis balanceados: cortar en el primer `)` parte la llamada en
          // `today()` y deja invisible el argumento que este test busca.
          const llamada = src.slice(i, finDeParentesis(src, i + fn.length - 1))
          if (!/cerOpts/.test(llamada)) {
            malos.push(`${f.slice(SRC.length + 1)}: ${llamada.replace(/\s+/g, ' ')}`)
          }
          i = src.indexOf(fn, i + 1)
        }
      }
    }
    expect(malos, 'llaman al próximo pago sin el ajuste').toEqual([])
  })

  it('el modal que registra el cobro recibe la serie', () => {
    for (const r of renders('BondCashflowModal')) {
      expect(r.props, `${r.archivo}: el modal escribe un monto sin ajustar`)
        .toMatch(/cerSeries/)
    }
  })

  it('el modal la declara como prop y la usa en las deps del memo', () => {
    const src = readFileSync(join(SRC, 'components/BondCashflowModal.jsx'), 'utf8')
    expect(src).toMatch(/^\s*cerSeries,/m)
    // Sin `cerSeries` en las deps, la serie que llega async no re-calcula nada.
    expect(src).toMatch(/\}, \[asset, flowType, position\?\.quantity, prefill, cerSeries\]\)/)
  })
})
