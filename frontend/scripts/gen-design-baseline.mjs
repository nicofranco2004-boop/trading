#!/usr/bin/env node
// gen-design-baseline.mjs — regenera src/__design__/design-baseline.json.
// ═══════════════════════════════════════════════════════════════════════════
// Uso:
//   node scripts/gen-design-baseline.mjs           # muestra el diff, no escribe
//   node scripts/gen-design-baseline.mjs --write   # escribe el JSON
//
// CUÁNDO CORRERLO: sólo cuando bajaste deuda a propósito (migraste font-mono,
// sacaste un rounded-md) y el test falla diciendo "bajó". Correr esto para
// "arreglar" un test que dice "SUBIÓ" es desarmar el guard — el punto es que
// subir requiera una conversación, no un comando.
//
// Comparte walker y patrones con el test vía scripts/design-patterns.mjs. Si
// alguna vez se copian en vez de importarse, el baseline deja de significar nada.

import fs from 'node:fs'
import path from 'node:path'
import { medir, total, CATEGORIAS, CATEGORIAS_ESPECIALES, FRONTEND_ROOT } from './design-patterns.mjs'

const DESTINO = path.join(FRONTEND_ROOT, 'src/__design__/design-baseline.json')
const escribir = process.argv.includes('--write')

const { porCategoria, especiales, totalArchivos } = medir()

const nuevo = {
  _leeme:
    'Baseline del contrato de diseño. NO editar a mano: regenerar con ' +
    '`node scripts/gen-design-baseline.mjs --write` y sólo cuando la deuda BAJÓ. ' +
    'Unidad: ocurrencias (salvo mono_uppercase, que es coocurrencia por línea, y ' +
    'paginas_mobile, que cuenta archivos). Ruta ausente en un mapa = 0. ' +
    'El contrato está en frontend/CLAUDE.md; los patrones en scripts/design-patterns.mjs.',
  _archivosEscaneados: totalArchivos,
  totales: Object.fromEntries([
    ...Object.keys(CATEGORIAS).map((k) => [k, total(porCategoria[k])]),
    ...Object.entries(especiales),
  ]),
  porArchivo: porCategoria,
}

const previo = fs.existsSync(DESTINO) ? JSON.parse(fs.readFileSync(DESTINO, 'utf8')) : null

console.log(`archivos escaneados: ${totalArchivos}\n`)
console.log('categoría'.padEnd(22), 'regla'.padEnd(7), 'total'.padStart(6), previo ? '   antes    Δ' : '')
for (const [k, v] of Object.entries(nuevo.totales)) {
  const regla = (CATEGORIAS[k] || CATEGORIAS_ESPECIALES[k]).regla
  let cola = ''
  if (previo) {
    const antes = previo.totales?.[k] ?? 0
    const d = v - antes
    cola = `${String(antes).padStart(8)}${d === 0 ? '    ·' : (d > 0 ? `  +${d} ⚠` : `  ${d} ✓`)}`
  }
  console.log(k.padEnd(22), regla.padEnd(7), String(v).padStart(6), cola)
}

if (escribir) {
  fs.mkdirSync(path.dirname(DESTINO), { recursive: true })
  fs.writeFileSync(DESTINO, JSON.stringify(nuevo, null, 2) + '\n')
  console.log(`\n✓ escrito ${path.relative(FRONTEND_ROOT, DESTINO)}`)
} else {
  console.log('\n(dry-run — pasá --write para escribir)')
}
