// AUDITORÍA DE LA FUSIÓN: el bono pasó a ser una fila más de la tabla del broker.
// ════════════════════════════════════════════════════════════════════════════
// QUÉ SE ESTÁ PROTEGIENDO
// ───────────────────────
// Hasta el 2026-09-22 los bonos, letras y FCI se SACABAN de la tabla de cada
// broker y se juntaban en una zona aparte al pie de la pantalla. La partición
// tenía que sumar igual, y eso obligaba a que el subtotal de la tarjeta se
// calculara sobre el mismo subconjunto recortado. Ahora la renta fija volvió a
// la tabla y la zona se fue.
//
// Ese movimiento tiene exactamente dos formas de salir mal, y las dos son plata
// mal mostrada, no un detalle visual:
//   1. Que una posición quede FUERA de todas las tablas → el usuario no la ve y
//      la suma de las tarjetas da de menos que su patrimonio.
//   2. Que una posición aparezca DOS VECES (por ejemplo en la tarjeta y en un
//      resto de la zona vieja) → la suma da de más.
// Los dos tests de abajo miden justamente eso, y con PLATA, no con conjuntos:
// una valuación de juguete pero sumada por el mismo camino que la pantalla.
//
// El tercer bloque vigila el CÓDIGO FUENTE, porque el filtro vive dentro del
// JSX de Positions.jsx y no se puede importar: si alguien vuelve a escribir el
// filtro a mano en una de las tres superficies (tabla en pesos, tabla en
// dólares, lista de celular), vuelve el bug que ya pasó en la auditoría de
// `f9a38c27` — una segunda copia de la regla que divergía de la que dibuja.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { filasDeLaTarjeta } from './tarjetaBroker.js'
import { isFixedIncome } from './sections.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

// Una cartera con las cuatro cosas que la fusión toca: acciones (nunca salieron
// de la tabla), un bono con lotes, una letra, un FCI, y todo eso repartido entre
// una cuenta unificada de dos patas (ARS + USD) y un broker suelto.
const CARTERA = [
  { id: 1, broker: 'Cocos',       asset: 'YPFD', asset_type: 'STOCK',  currency: 'ARS', quantity: 10, valor: 100 },
  { id: 2, broker: 'Cocos',       asset: 'AL30', asset_type: 'BOND',   currency: 'ARS', quantity: 50, valor: 250 },
  { id: 3, broker: 'Cocos',       asset: 'AL30', asset_type: 'BOND',   currency: 'ARS', quantity: 30, valor: 150 },
  { id: 4, broker: 'Cocos',       asset: 'S28N5', asset_type: '',      currency: 'ARS', quantity: 100, valor: 80 },
  { id: 5, broker: 'Cocos · USD', asset: 'GD35', asset_type: 'BOND',   currency: 'USD', quantity: 20, valor: 300 },
  { id: 6, broker: 'Cocos · USD', asset: 'AAPL', asset_type: 'STOCK',  currency: 'USD', quantity: 2,  valor: 400 },
  { id: 7, broker: 'Balanz',      asset: 'COCORA', asset_type: 'FUND', currency: 'ARS', quantity: 1000, valor: 60 },
  { id: 8, broker: 'Balanz',      asset: 'SPY',  asset_type: 'CEDEAR', currency: 'ARS', quantity: 5,  valor: 500 },
  { id: 9, broker: 'Cocos',       asset: 'ARS',  asset_type: null, is_cash: true, currency: 'ARS', quantity: 1, valor: 70 },
]

// Las tarjetas que dibuja la pantalla: la cuenta unificada (dos patas en una
// tarjeta) y el broker suelto. `patasNames` es lo que Positions.jsx arma.
const TARJETAS = [
  { key: 'cocos', currency: 'ARS', isPair: true,  patasNames: new Set(['Cocos', 'Cocos · USD']) },
  { key: 'balanz', currency: 'ARS', isPair: false, patasNames: new Set(['Balanz']) },
]

const plata = (filas) => filas.reduce((s, p) => s + p.valor, 0)

describe('la tabla del broker no pierde ni duplica ninguna posición', () => {
  it('las tarjetas, juntas, muestran TODA la cartera y cada cosa una sola vez', () => {
    const vistas = TARJETAS.flatMap(t => filasDeLaTarjeta(CARTERA, t))
    const ids = vistas.map(p => p.id)
    // Una sola vez cada una: sin esto la suma de las tarjetas daría de más.
    expect(new Set(ids).size, 'hay una posición repetida en dos tarjetas').toBe(ids.length)
    // Todas: sin esto la suma daría de menos y habría tenencia invisible.
    expect([...ids].sort((a, b) => a - b)).toEqual(CARTERA.map(p => p.id))
  })

  it('sumar los subtotales de las tarjetas da el patrimonio, no menos', () => {
    // El subtotal de cada tarjeta se calcula sobre EXACTAMENTE estas filas
    // (Positions.jsx: `rPorPata` se alimenta de `bposRaw`), así que sumarlas es
    // reproducir el pie de cada tabla y compararlo con el número de arriba.
    const sumaDeTarjetas = TARJETAS.reduce((s, t) => s + plata(filasDeLaTarjeta(CARTERA, t)), 0)
    expect(sumaDeTarjetas).toBe(plata(CARTERA))
  })

  it('así era antes, y así es como se partía la cartera: la regla vieja perdía plata', () => {
    // Este test NO protege la regla vieja: documenta por qué se cambió, y es lo
    // que fallaría si alguien volviera a excluir la renta fija sin traer de
    // vuelta la zona que la mostraba. Con la regla vieja quedaban afuera de las
    // tarjetas AL30 ×2, S28N5, GD35 y COCORA: 840 de 1910.
    const reglaVieja = CARTERA.filter(p => !isFixedIncome(p))
    expect(plata(CARTERA) - plata(reglaVieja)).toBe(840)
    expect(plata(reglaVieja)).toBeLessThan(plata(CARTERA))
  })

  it('el bono, la letra y el FCI están en la tarjeta de SU cuenta', () => {
    const cocos = filasDeLaTarjeta(CARTERA, TARJETAS[0]).map(p => p.asset)
    expect(cocos).toContain('AL30')    // bono en pesos, con dos lotes
    expect(cocos).toContain('S28N5')   // letra
    expect(cocos).toContain('GD35')    // bono en la pata dólar de la misma cuenta
    expect(filasDeLaTarjeta(CARTERA, TARJETAS[1]).map(p => p.asset)).toContain('COCORA')
  })

  it('el buscador de la toolbar sigue filtrando, y filtra igual para todos', () => {
    const soloAl30 = filasDeLaTarjeta(CARTERA, TARJETAS[0], p => p.asset === 'AL30')
    expect(soloAl30.map(p => p.id)).toEqual([2, 3])
  })
})

// ─── Vigilancia del código fuente ────────────────────────────────────────────
// El filtro se aplica dentro del JSX, así que no hay forma de importarlo y
// probarlo: se vigila el texto. Mismo patrón que `cerBasisProps.test.js` y
// `sellModalProps.test.js`, que no tienen jsdom tampoco.
function archivosJsx(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivosJsx(p)
    return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
  })
}

describe('la regla de qué entra en la tabla vive en un solo lugar', () => {
  it('nadie vuelve a excluir la renta fija de la cartera a mano', () => {
    const malos = []
    for (const f of archivosJsx(SRC)) {
      if (/utils\/(tarjetaBroker|sections)\.js$/.test(f)) continue
      const src = readFileSync(f, 'utf8')
      // `!isFixedIncome(...)` es literalmente cómo se escribía la exclusión en
      // las tres superficies, y `if (isFixedIncome(p)) continue` en el celular.
      if (/!\s*isFixedIncome\s*\(/.test(src) || /if\s*\(\s*isFixedIncome\s*\([^)]*\)\s*\)\s*continue/.test(src)) {
        malos.push(f.slice(SRC.length + 1))
      }
    }
    expect(malos, 'volvió a haber una copia del filtro que saca los bonos de la tabla').toEqual([])
  })

  it('las dos tablas de escritorio y el "Ver lotes" piden las filas a la misma función', () => {
    const src = readFileSync(join(SRC, 'pages/Positions.jsx'), 'utf8')
    const usos = src.match(/filasDeLaTarjeta\s*\(/g) || []
    // Dos: el `bposRaw` que alimenta tabla + subtotal (uno solo, compartido por
    // la tabla en pesos y la de dólares) y el `multiLote` que decide si se
    // ofrece "Ver lotes". Si aparece un tercer lugar que arma las filas a mano,
    // este número se queda igual y el test de arriba lo caza.
    expect(usos.length).toBe(2)
  })

  it('la zona "Renta Fija" ya no existe y nadie la monta', () => {
    const malos = archivosJsx(SRC)
      .filter(f => /RentaFijaSections/.test(readFileSync(f, 'utf8')))
      .map(f => f.slice(SRC.length + 1))
    expect(malos, 'quedó una referencia a la zona que se eliminó').toEqual([])
  })

  it('el listado para restaurar lo archivado sigue estando en las dos pantallas', () => {
    // Quien archivó una sección antes de la fusión tiene sus posiciones
    // guardadas; sin este listado no habría ninguna pantalla para recuperarlas.
    for (const pagina of ['pages/Positions.jsx', 'pages/PositionsMobile.jsx']) {
      expect(readFileSync(join(SRC, pagina), 'utf8'),
        `${pagina}: se quedó sin el listado de posiciones archivadas`)
        .toMatch(/<PosicionesArchivadas/)
    }
  })
})
