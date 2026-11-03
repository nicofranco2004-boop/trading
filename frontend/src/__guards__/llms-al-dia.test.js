// public/llms.txt es lo que leen las IA y los buscadores sobre Rendi. Está
// escrito a mano, y nada lo ataba al menú: el 29/10 (auditoría D12) seguía
// diciendo «Calidad de cartera» —que desde el 28/10 se llama «Análisis
// fundamental»— y no nombraba Análisis técnico, la sección nueva.
// Esta prueba lo ata al menú (utils/navegacion.js, de donde lo toman el menú
// lateral, el buscador y «Más» del celular): cada sección de «Análisis de
// mercado» y «Salud de cartera» se nombra, y los nombres viejos no vuelven.
import { describe, it, expect } from 'vitest'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { GROUPS } from '../utils/navegacion'

const llms = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../public/llms.txt'), 'utf8')
const NOMBRES_VIEJOS = ['Calidad de cartera']
// Secciones que no hace falta nombrar: «Resumen» es la portada de la app y
// «Métricas» se describe por lo que mide (Sharpe, TWR…), no por el nombre.
const SIN_NOMBRE = new Set(['Resumen', 'Métricas'])

describe('llms.txt sigue al menú', () => {
  it('nombra cada sección de análisis', () => {
    const secciones = GROUPS.filter(g => ['mercado', 'analisis'].includes(g.id))
      .flatMap(g => g.items.map(i => i.label)).filter(n => !SIN_NOMBRE.has(n))
    expect(secciones).toContain('Análisis técnico')
    for (const n of secciones) expect(llms, n).toContain(n)
  })
  it('no usa nombres viejos', () => {
    for (const v of NOMBRES_VIEJOS) expect(llms).not.toContain(v)
  })
})
