import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// Métricas (Diagnóstico, Comportamiento, Reportes y sus textos): un porcentaje
// escrito a mano con `toFixed` muestra "-0,7%" con GUION al lado del "−0,7%"
// de la regla común (pctVar/pctTxt, utils/format) — medido el 2026-10-02 en la
// misma pantalla. Y dos formas dan basura: "+-1,2%" ("Mejor mes" de un año todo
// en rojo) y "undefined%" (una evidencia sin el dato). Este guard no prohíbe
// `toFixed` (un peso de cartera nunca es negativo): prohíbe las tres formas que
// escriben mal.
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const ARCHIVOS = [
  'pages/Insights.jsx', 'pages/Behavioral.jsx', 'pages/Reports.jsx',
  'components/reports/PerformanceCalendar.jsx', 'components/reports/MonthCard.jsx',
  'components/ArAlternativesVerdict.jsx', 'utils/diagnostics.js',
]
const FORMAS = [
  // "+" sólo si es positivo y el número crudo: el negativo sale con guion.
  { nombre: '+ opcional y toFixed (guion en los negativos)', re: /'\+' : ''\}\$?\{[\w.?]+\.toFixed\(/g },
  // "+" fijo y el número crudo: un negativo sale "+-".
  { nombre: '+ fijo y toFixed ("+-")', re: /(`\+\$\{|>\+\{|^\s*\+\{)[\w.?]+\.toFixed\(/gm },
  // `?.toFixed(…)` pegado al %: sin el dato escribe "undefined%".
  { nombre: '?.toFixed y % ("undefined%")', re: /\?\.toFixed\(\d\)\.replace\('\.', ','\)\}\s?%/g },
  // El signo de la plata con guion: "-USD 240,00" al lado de "−USD 240".
  { nombre: "signo '-' (guion) en vez de '−'", re: /'\+' : '-'/g },
]

describe('porcentajes de Métricas — sin guion, sin "+-", sin "undefined%"', () => {
  for (const a of ARCHIVOS) {
    it(a, () => {
      const t = readFileSync(join(SRC, a), 'utf8')
      const malas = FORMAS.flatMap(({ nombre, re }) => [...t.matchAll(re)].map(m => {
        const linea = t.slice(0, m.index).split('\n').length
        return `${nombre} · línea ${linea}`
      }))
      expect(malas).toEqual([])
    })
  }
})
