import { describe, it, expect } from 'vitest'
import {
  normalizar, puntaje, resultadosDelBuscador, opcionesDeActivos, opcionesDeEmpresas, MAXIMO_RESULTADOS,
  destinoDeTicker, tickerDeEmpresa, empresaDeTicker, urlDeActivo,
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
  it('sin nada escrito: los accesos de siempre, sin Mervall-E AI', () => {
    const r = resultadosDelBuscador(todas, '')
    expect(r.map(o => o.id)).toEqual(['a:cargar', 'p:/dashboard', 'p:/'])
  })
  it('"dolar" lleva a Mercado (por su clave) y al final, preguntarle a Mervall-E AI', () => {
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
  it('uno que no tenés va a su ficha, con el gráfico (Nico, 22/10)', () => {
    const r = resultadosDelBuscador(todas, 'aapl')
    expect(r[0].ir).toBe('/activo/AAPL')
  })
  it('con UNA letra no aparecen empresas que no tenés (taparían lo tuyo)', () => {
    const r = resultadosDelBuscador(todas, 'a')
    expect(r.some(o => o.clase === 'empresa')).toBe(false)
  })
  it('una pregunta cualquiera siempre se puede mandar a Mervall-E AI', () => {
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
describe('Mervall-E AI según el plan', () => {
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
import { mapMeToUser, DEMO_USER } from '../contexts/AuthContext'
import { hayPrecios } from './preciosEnVivo'
import { UTILIDADES } from './navegacion'
import { POPULAR_TICKERS, CEDEARS_DE_ETF } from './tickers'

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
  // El usuario sale de mapMeToUser, como en la app: armarlo a mano con `id`
  // fue lo que tapó que en las cuentas de verdad la llave quedaba vacía (ver
  // components/buscadorTusActivos.test.js, que lo prueba montado).
  it('tus activos se guardan por PERSONA: el que entra después no ve los del anterior', () => {
    const ana = mapMeToUser({ id: 1, email: 'ana@x.com', name: 'Ana', tier: 'pro' })
    const beto = mapMeToUser({ id: 2, email: 'beto@x.com', name: 'Beto', tier: 'pro' })
    expect(claveDeActivos(ana, null)).not.toBeNull()
    expect(claveDeActivos(ana, null)).not.toBe(claveDeActivos(beto, null))
    expect(claveDeActivos(ana, { id: 7 })).not.toBe(claveDeActivos(ana, null))
    expect(claveDeActivos(null, null)).toBeNull()
    // Al iniciar sesión el email es el que se tipeó; después llega el del
    // servidor. Es la misma persona: no se vuelven a pedir.
    expect(claveDeActivos({ name: 'Ana', email: ' Ana@X.com' }, null)).toBe(claveDeActivos(ana, null))
    expect(claveDeActivos(DEMO_USER, null)).not.toBeNull()
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

describe('destinoDeTicker: a dónde lleva un ticker en los dos buscadores (⌘K y la lupa del celular)', () => {
  it('lo tuyo va a tu ficha, sea lo que sea', () => {
    expect(destinoDeTicker('al30', { tuyo: true, tipo: 'bond' })).toBe('/activo/AL30')
    expect(destinoDeTicker('BRK.B', { tuyo: true })).toBe('/activo/BRK.B')
  })
  it('lo que no tenés también va a la ficha: acciones, CEDEARs, cripto y ETFs', () => {
    expect(destinoDeTicker('AAPL', { tipo: 'stock_us' })).toBe('/activo/AAPL')
    expect(destinoDeTicker('KO.BA', { tipo: 'cedear' })).toBe('/activo/KO.BA')
    expect(destinoDeTicker('GGAL.BA', { tipo: 'stock_ar' })).toBe('/activo/GGAL.BA')
    expect(destinoDeTicker('btc', { tipo: 'crypto' })).toBe('/activo/BTC')
    expect(destinoDeTicker('SPY', { tipo: 'etf' })).toBe('/activo/SPY')
  })
  it('un bono o un fondo que no tenés no lleva a ningún lado (no tienen gráfico técnico)', () => {
    for (const tipo of ['bond', 'fci']) expect(destinoDeTicker('X', { tipo }), tipo).toBe(null)
  })
  it('urlDeActivo: un solo armado del link, en mayúsculas y escapado', () => {
    expect(urlDeActivo('brk.b')).toBe('/activo/BRK.B')
    expect(urlDeActivo('A/B')).toBe('/activo/A%2FB')
  })
  it('el ⌘K ofrece el gráfico de lo que no tenés, sin bonos', () => {
    const r = opcionesDeEmpresas([
      { symbol: 'AAPL', name: 'Apple', type: 'stock_us' }, { symbol: 'AL30', name: 'Bonar', type: 'bond' },
      { symbol: 'BTC', name: 'Bitcoin', type: 'crypto' },
    ])
    expect(r.map(o => o.ir)).toEqual(['/activo/AAPL', '/activo/BTC'])
    expect(r[0].detalle).toBe('Ver el gráfico')
  })
  it('al asesor en su nivel el ⌘K no le ofrece tickers sueltos (no tiene cartera propia)', () => {
    const universo = [{ symbol: 'AAPL', name: 'Apple', type: 'stock_us' }]
    expect(opcionesDeEmpresas(universo, { asesorEnSuNivel: true })).toEqual([])
    expect(opcionesDeEmpresas(universo)).toHaveLength(1)
  })
})

describe('tickerDeEmpresa: la empresa correcta en Análisis fundamental, o ninguna', () => {
  // Buscar el ticker tal cual abría OTRA empresa (verificado contra yfinance):
  // TEN era una naviera griega, AGRO Adecoagro, BOLT/CELU/PCAR/HAVA otras.
  it('una acción de EE.UU. es ella misma; un CEDEAR, su acción de EE.UU.', () => {
    expect(tickerDeEmpresa('AAPL', 'stock_us')).toBe('AAPL')
    expect(tickerDeEmpresa('KO.BA', 'cedear')).toBe('KO')
  })
  it('bonos, cripto y ETFs no tienen empresa', () => {
    for (const tipo of ['bond', 'crypto', 'etf']) expect(tickerDeEmpresa('X', tipo), tipo).toBe(null)
  })
  it('una acción argentina va por su ADR; sin ADR, a ningún lado', () => {
    expect(tickerDeEmpresa('GGAL', 'stock_ar')).toBe('GGAL')
    expect(tickerDeEmpresa('YPFD', 'stock_ar')).toBe('YPF')
    expect(tickerDeEmpresa('TECO2', 'stock_ar')).toBe('TEO')
    for (const s of ['TEN', 'AGRO', 'BOLT', 'CELU', 'PCAR', 'HAVA', 'TXAR']) {
      expect(tickerDeEmpresa(s, 'stock_ar'), s).toBe(null)
    }
  })
  it('un CEDEAR con ticker distinto en EE.UU. va por el de allá; uno de un ETF, a ningún lado', () => {
    expect(tickerDeEmpresa('DISN.BA', 'cedear')).toBe('DIS')
    expect(tickerDeEmpresa('BRKB.BA', 'cedear')).toBe('BRK-B')
    expect(tickerDeEmpresa('NOKA.BA', 'cedear')).toBe('NOK')
    expect(tickerDeEmpresa('SPY.BA', 'cedear')).toBe(null)
  })
  it('empresaDeTicker (la ficha de lo que no tenés) deduce el tipo del ticker', () => {
    expect(empresaDeTicker('YPFD.BA')).toEqual({ ticker: 'YPF', ir: '/fundamentals?ticker=YPF' })
    expect(empresaDeTicker('DISN.BA')).toEqual({ ticker: 'DIS', ir: '/fundamentals?ticker=DIS' })
    expect(empresaDeTicker('NVDA')).toEqual({ ticker: 'NVDA', ir: '/fundamentals?ticker=NVDA' })
    expect(empresaDeTicker('AGRO.BA')).toBe(null)
    expect(empresaDeTicker('BTC')).toBe(null)
  })
  it('la lista de sugeridos ya no tiene "TEN" como Ternium Argentina', () => {
    const ternium = POPULAR_TICKERS.find(t => /Ternium Argentina/.test(t.name))
    expect(ternium.symbol).toBe('TXAR')
  })
})

describe('⌘K adentro de un cliente', () => {
  it('sus activos dicen de quién son, no "Tu posición"', () => {
    expect(opcionesDeActivos([{ asset: 'GGAL' }], () => null, { cliente: 'Ana' })[0].detalle).toBe('Posición de Ana')
    expect(opcionesDeActivos([{ asset: 'GGAL' }])[0].detalle).toBe('Tu posición')
  })
})

describe('CEDEARs de ETFs: ninguno lleva a "no tenemos fundamentales"', () => {
  it('todos los marcados como ETF en la lista de CEDEARs (no sólo SPY)', () => {
    expect(CEDEARS_DE_ETF.size).toBeGreaterThanOrEqual(17)
    for (const s of ['URA', 'COPX', 'FXI', 'ACWI', 'EWY', 'ETHA', 'GLD', 'IBIT']) {
      expect(CEDEARS_DE_ETF.has(s), s).toBe(true)
      expect(tickerDeEmpresa(`${s}.BA`, 'cedear'), s).toBe(null)
    }
    // Una acción con CEDEAR sí abre su empresa.
    expect(tickerDeEmpresa('KO.BA', 'cedear')).toBe('KO')
  })
})
