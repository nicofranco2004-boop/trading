// comparar-sectores.mjs — ¿en qué papeles la torta de sectores de la Cartera
// (src/utils/assetSector.js) y el termómetro (la clasificación del S&P, GICS,
// en backend/home/sp500_constituyentes.json) ponen la misma empresa en sectores
// distintos?
//
// Existe para decidir si la torta se unifica a GICS (pieza 7, 29/10): hoy hay
// dos clasificaciones para el mismo papel, y esta lista dice dónde chocan.
// Compara sólo las empresas que están en las DOS (las del S&P 500 que la torta
// conoce) y por el grupo grande: «Semiconductores» de la torta cuenta como
// Tecnología, porque en GICS es una industria adentro de Tecnología.
//
// Uso (desde frontend/):  npx vite-node scripts/comparar-sectores.mjs
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { classifySector, SECTOR_META } from '../src/utils/assetSector.js'

const RAIZ = fileURLToPath(new URL('../../backend/home/sp500_constituyentes.json', import.meta.url))
const lista = JSON.parse(readFileSync(RAIZ, 'utf8'))
const GRANDE = { semis: 'tecnologia' }
const nombre = k => SECTOR_META[k]?.label || k

const distintas = []
let comparadas = 0
for (const e of lista.empresas) {
  const torta = classifySector({ asset: e.symbol, asset_type: 'STOCK', broker: 'Schwab' }, [{ name: 'Schwab', currency: 'USD' }])
  if (!SECTOR_META[torta] || torta === 'sin_dato' || torta === 'diversificado') continue
  comparadas++
  if ((GRANDE[torta] || torta) !== e.sector) distintas.push([e.symbol, e.nombre, nombre(torta), nombre(e.sector)])
}
console.log(`Lista del S&P bajada el ${lista.bajada}. Empresas en las dos clasificaciones: ${comparadas}. Distintas: ${distintas.length}.`)
console.log('| Papel | Empresa | Torta de la Cartera | Termómetro (GICS) |')
console.log('|---|---|---|---|')
for (const [s, n, a, b] of distintas) console.log(`| ${s} | ${n} | ${a} | ${b} |`)
