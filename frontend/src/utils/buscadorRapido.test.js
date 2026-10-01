import { describe, it, expect } from 'vitest'
import {
  normalizar, puntaje, resultadosDelBuscador, opcionesDeActivos, opcionesDeEmpresas, MAXIMO_RESULTADOS,
} from './buscadorRapido'
import { menuVisible, pantallasVisibles, GROUPS, LOOSE } from './navegacion'

const pantallas = [
  { clase: 'pantalla', id: 'p:/dashboard', titulo: 'Dashboard', claves: ['inicio'], ir: '/dashboard', deEntrada: true },
  { clase: 'pantalla', id: 'p:/', titulo: 'Resumen', claves: ['mercado', 'dólar', 'mep'], ir: '/', deEntrada: true },
  { clase: 'pantalla', id: 'p:/analisis', titulo: 'Métricas', claves: ['rendimiento'], ir: '/analisis' },
]
const accion = { clase: 'accion', id: 'a:cargar', titulo: 'Cargar una operación', claves: ['compra', 'venta'], ir: '/operaciones?nueva=1', deEntrada: true }
const activos = opcionesDeActivos(
  [{ asset: 'NVDA' }, { asset: 'NVDA', broker: 'otro' }, { asset: 'USD', is_cash: true }, { asset: 'meli' }],
  s => ({ NVDA: 'NVIDIA', MELI: 'Mercado Libre' }[s] || null),
)
const empresas = opcionesDeEmpresas([{ symbol: 'NVDA', name: 'NVIDIA' }, { symbol: 'AAPL', name: 'Apple' }, { symbol: 'AMZN', name: 'Amazon' }])
const todas = [...activos, accion, ...pantallas, ...empresas]

describe('normalizar y puntaje', () => {
  it('sin tildes ni mayúsculas: "dolar" encuentra "dólar"', () => {
    expect(normalizar('Dólar MEP')).toBe('dolar mep')
    expect(puntaje(pantallas[1], 'dolar')).toBeGreaterThan(0)
  })
  it('el título que empieza igual gana a una clave', () => {
    expect(puntaje(pantallas[0], 'dash')).toBeGreaterThan(puntaje(pantallas[0], 'inicio'))
  })
  it('lo que no tiene que ver, 0', () => {
    expect(puntaje(pantallas[0], 'zzz')).toBe(0)
  })
})

describe('opcionesDeActivos', () => {
  it('uno por ticker, sin el efectivo, con nombre y a su ficha', () => {
    expect(activos.map(a => a.titulo)).toEqual(['NVDA · NVIDIA', 'MELI · Mercado Libre'])
    expect(activos[0].ir).toBe('/activo/NVDA')
  })
})

describe('resultadosDelBuscador', () => {
  it('sin nada escrito: los accesos de siempre, sin Rendi AI', () => {
    const r = resultadosDelBuscador(todas, '')
    expect(r.map(o => o.id)).toEqual(['a:cargar', 'p:/dashboard', 'p:/'])
  })
  it('"dolar" lleva a Mercado (por su clave) y al final, preguntarle a Rendi AI', () => {
    const r = resultadosDelBuscador(todas, 'dolar')
    expect(r[0].ir).toBe('/')
    expect(r[r.length - 1].clase).toBe('ia')
    expect(r[r.length - 1].pregunta).toBe('dolar')
  })
  it('un ticker tuyo va primero, a TU posición, y no se repite como empresa', () => {
    const r = resultadosDelBuscador(todas, 'nvda')
    expect(r[0].ir).toBe('/activo/NVDA')
    expect(r.filter(o => o.simbolo === 'NVDA')).toHaveLength(1)
  })
  it('uno que no tenés va a la empresa en Calidad de cartera', () => {
    const r = resultadosDelBuscador(todas, 'aapl')
    expect(r[0].ir).toBe('/fundamentals?ticker=AAPL')
  })
  it('con UNA letra no aparecen empresas que no tenés (taparían lo tuyo)', () => {
    const r = resultadosDelBuscador(todas, 'a')
    expect(r.some(o => o.clase === 'empresa')).toBe(false)
  })
  it('una pregunta cualquiera siempre se puede mandar a Rendi AI', () => {
    const r = resultadosDelBuscador(todas, '¿le gano a la inflación?')
    expect(r).toHaveLength(1)
    expect(r[0].clase).toBe('ia')
  })
  it('nunca más de MAXIMO_RESULTADOS', () => {
    const muchas = Array.from({ length: 30 }, (_, i) => ({ clase: 'pantalla', id: `x${i}`, titulo: `Cosa ${i}` }))
    expect(resultadosDelBuscador(muchas, 'cosa')).toHaveLength(MAXIMO_RESULTADOS)
  })
})

// El buscador ofrece las MISMAS pantallas que el menú lateral (utils/navegacion).
describe('menuVisible / pantallasVisibles', () => {
  it('usuario común: los 3 grupos y los dos sueltos', () => {
    const m = menuVisible({ user: { tier: 'pro' } })
    expect(m.groups).toBe(GROUPS)
    expect(m.loose).toBe(LOOSE)
    expect(m.asesorPropio).toEqual([])
  })
  it('asesor en su nivel: su home, sin cartera propia ni Importar', () => {
    const m = menuVisible({ user: { tier: 'advisor' }, clientCtx: null })
    expect(m.groups).toEqual([])
    expect(m.loose.map(i => i.to)).toEqual(['/alertas'])
    expect(m.asesorPropio.map(i => i.to)).toContain('/clientes')
    const tos = pantallasVisibles({ user: { tier: 'advisor' } }).map(p => p.to)
    expect(tos).not.toContain('/posiciones')
  })
  it('asesor adentro de un cliente: la cartera del cliente + volver a Clientes, sin repetidos', () => {
    const tos = pantallasVisibles({ user: { tier: 'advisor' }, clientCtx: { id: 7 } }).map(p => p.to)
    expect(tos).toContain('/posiciones')
    expect(tos).toContain('/clientes')
    expect(new Set(tos).size).toBe(tos.length)
  })
  it('is_admin sin plan Asesor NO ve Clientes', () => {
    const tos = pantallasVisibles({ user: { tier: 'pro', is_admin: true } }).map(p => p.to)
    expect(tos).not.toContain('/clientes')
  })
})

import { puedeChatLibre } from './chatLibre'

// Sin chat libre (Plus) mandar el texto rebotaría en el servidor.
describe('Rendi AI según el plan', () => {
  it('Pro, admin y asesor en su nivel pueden escribir libre; Plus no; el asesor adentro de un cliente va por el plan', () => {
    expect(puedeChatLibre({ isPro: true })).toBe(true)
    expect(puedeChatLibre({ isAdmin: true })).toBe(true)
    expect(puedeChatLibre({ user: { tier: 'advisor' }, clientCtx: null })).toBe(true)
    expect(puedeChatLibre({ user: { tier: 'plus' } })).toBe(false)
    expect(puedeChatLibre({ user: { tier: 'advisor' }, clientCtx: { id: 3 } })).toBe(false)
  })
  it('sin chat libre el buscador NO manda el texto: ofrece ir a ver las preguntas', () => {
    const r = resultadosDelBuscador(todas, '¿le gano a la inflación?', { chatLibre: false })
    const ia = r[r.length - 1]
    expect(ia.clase).toBe('ia')
    expect(ia.pregunta).toBeNull()
    expect(ia.titulo).toMatch(/preguntas que le podés hacer/)
  })
})

import { esAtajoBuscador, urlNuevaOperacion, claveDeActivos } from './buscadorRapido'
import { hayPrecios } from './preciosEnVivo'
import { UTILIDADES } from './navegacion'

describe('arreglos de la vuelta 1 de auditoría', () => {
  const k = (o) => ({ key: 'k', metaKey: false, ctrlKey: false, altKey: false, ...o })
  it('el atajo: ⌘K en Mac (Ctrl+K ahí es "borrar hasta el final"), Ctrl+K en el resto', () => {
    expect(esAtajoBuscador(k({ metaKey: true }), true)).toBe(true)
    expect(esAtajoBuscador(k({ ctrlKey: true }), true)).toBe(false)
    expect(esAtajoBuscador(k({ ctrlKey: true }), false)).toBe(true)
    expect(esAtajoBuscador(k({ metaKey: true }), false)).toBe(false)
    expect(esAtajoBuscador(k({ metaKey: true, altKey: true }), true)).toBe(false)
    expect(esAtajoBuscador({ key: 'j', metaKey: true }, true)).toBe(false)
  })
  it('tus activos se guardan por USUARIO: el que entra después no ve los del anterior', () => {
    expect(claveDeActivos({ id: 1 }, null)).not.toBe(claveDeActivos({ id: 2 }, null))
    expect(claveDeActivos({ id: 1 }, { id: 7 })).not.toBe(claveDeActivos({ id: 1 }, null))
    expect(claveDeActivos(null, null)).toBeNull()
    // el demo es el usuario 0: 0 es un usuario, no "ninguno"
    expect(claveDeActivos({ id: 0 }, null)).not.toBeNull()
  })
  it('"Cargar una operación" estando en Movimientos conserva la pestaña', () => {
    expect(urlNuevaOperacion('/dashboard', '?x=1')).toBe('/operaciones?nueva=1')
    expect(urlNuevaOperacion('/operaciones', '?tab=todos')).toBe('/operaciones?tab=todos&nueva=1')
  })
  it('sin ningún precio en la respuesta no hay "Precios de hace…"', () => {
    expect(hayPrecios({})).toBe(false)
    expect(hayPrecios({ __meta: { NVDA: 'yf' } })).toBe(false)
    expect(hayPrecios({ NVDA: null })).toBe(false)
    expect(hayPrecios({ NVDA: 181.2 })).toBe(true)
  })
  it('Guía y Configuración están en la lista compartida; Admin sólo para is_admin', () => {
    expect(UTILIDADES.map(u => u.to)).toEqual(['/admin', '/guia', '/config'])
    const comun = pantallasVisibles({ user: { tier: 'pro' } }).map(p => p.to)
    expect(comun).toContain('/guia')
    expect(comun).toContain('/config')
    expect(comun).not.toContain('/admin')
    expect(pantallasVisibles({ user: { tier: 'pro', is_admin: true } }).map(p => p.to)).toContain('/admin')
  })
})
