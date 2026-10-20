/**
 * opcionesCedear — qué CEDEARs ofrece el buscador de "Registrar compra".
 *
 * En una cuenta argentina cada CEDEAR aparece DOS veces: en pesos (AAPL) y en
 * dólares (AAPLD). Elegir una u otra decide la moneda de la compra — ya no hay
 * que elegir el sub-broker "· USD". La compra se guarda siempre como "AAPL" con
 * su moneda: "AAPLD" es sólo cómo se llama en la Bolsa, para que el usuario lo
 * reconozca; guardarlo como otro activo separaría AAPL de AAPLD en el cálculo de
 * ganancias y en los precios.
 *
 * La lista sale de `GET /api/cedears` (todos los de BYMA, con su precio en pesos
 * y en dólares — ver backend/cedears_dolar.py) unida a la lista curada de
 * utils/tickers (que trae los nombres). Si el backend no contesta, se ofrecen los
 * de la lista curada en las dos monedas, sin código ni precio: mejor eso que
 * dejar al usuario sin poder cargar una compra en dólares.
 */
import { api } from './api'
import { tickerName, CEDEAR_EN_EEUU } from './tickers'

// La promesa, con su hora: vence a los 5 minutos (lo mismo que el caché del
// backend). Sin vencimiento, en la app instalada el precio en dólares que se
// precarga podía tener horas mientras el formulario decía "precio actual".
const VIGENCIA_MS = 5 * 60 * 1000
let _cache = null
let _desde = 0

export function cargarCedears() {
  if (!_cache || Date.now() - _desde > VIGENCIA_MS) {
    _desde = Date.now()
    _cache = api.get('/cedears')
      // Una lista VACÍA es "no hay dato" (data912 contestó a medias), no "no hay
      // CEDEARs": se trata como un error y no se guarda. Antes quedaba guardada
      // hasta recargar la app y el buscador no ofrecía ningún CEDEAR en dólares.
      .then(d => {
        const items = Array.isArray(d?.items) && d.items.length ? d.items : null
        if (!items) _cache = null
        return items
      })
      .catch(() => { _cache = null; return null })
  }
  return _cache
}

// Sólo para tests.
export function _olvidarCedears() { _cache = null; _desde = 0 }

/**
 * @param {Array<{s,n}>} curada   la lista CEDEARS_LIST de utils/tickers
 * @param {Array|null|undefined} items  lo que devolvió /api/cedears: `undefined`
 *   = todavía cargando (sólo pesos: ofrecer filas en dólares que después
 *   cambian corre la lista bajo el dedo); `null` = no llegó (respaldo: la lista
 *   curada en las dos monedas, sin código ni precio).
 * @param {{enCuentaArgentina: boolean}} opts
 * @returns filas para el buscador: {s, n, _ccy, _sub, _codigo, _px}
 *   `_ccy` ('ARS'|'USD') viaja como la moneda de la compra.
 */
export function opcionesCedear(curada, items, { enCuentaArgentina }) {
  if (!enCuentaArgentina) return curada
  const nombres = new Map((curada || []).map(c => [c.s, c.n]))
  const porSimbolo = new Map()
  const deLaBolsa = new Set((items || []).map(it => it?.s).filter(Boolean))
  for (const c of curada || []) {
    // La lista curada tiene a Berkshire dos veces ('BRK-B' y 'BRKB', el código de
    // la Bolsa): si la Bolsa ya lo trae con el ticker canónico, el alias sobra —
    // si no, aparecía dos veces y elegir uno u otro partía la tenencia en dos.
    const canon = CEDEAR_EN_EEUU[c.s]
    if (canon && deLaBolsa.has(canon)) continue
    porSimbolo.set(c.s, { s: c.s })
  }
  for (const it of items || []) {
    if (it?.s) porSimbolo.set(it.s, { ...it })
  }
  const filas = []
  const orden = [...porSimbolo.keys()]
  // Primero los de la lista curada (los populares, en su orden), después el resto
  // alfabético: abrir la categoría y ver ABEV3 primero no ayuda a nadie.
  orden.sort((a, b) => {
    const ia = nombres.has(a), ib = nombres.has(b)
    if (ia !== ib) return ia ? -1 : 1
    return ia ? 0 : a.localeCompare(b)
  })
  for (const s of orden) {
    const it = porSimbolo.get(s)
    const n = nombres.get(s) || tickerName(s) || s
    filas.push({
      s, n, _ccy: 'ARS',
      _codigo: it.pesos || s,
      _sub: 'CEDEAR en pesos',
      _px: it.px_ars ?? null,
    })
    // En dólares: si el backend dice que existe la especie, o si el backend no
    // contestó (items null, no undefined) y es de la lista curada.
    if (it.dolares || (items === null && nombres.has(s))) {
      filas.push({
        s, n, _ccy: 'USD',
        _codigo: it.dolares || null,
        _sub: it.dolares ? `CEDEAR en dólares · ${it.dolares}` : 'CEDEAR en dólares',
        _px: it.px_usd ?? null,
        _estimado: it.fuente_usd === 'estimado',
      })
    }
  }
  return filas
}

/**
 * Los CEDEARs que cotizan en dólares, por su símbolo de precio en pesos
 * ('AAPL.BA' → { px: 18.04, codigo: 'AAPLD' }). Lo usan las alertas, que
 * guardan el CEDEAR como 'AAPL.BA' + la moneda. Se indexa por el código de la
 * Bolsa (BRKB.BA, el que arma priceSymbol) y por el ticker de Rendi (BRK-B.BA),
 * igual que alerts_engine._codigos en el servidor.
 * @returns {Map<string,{px:number|null, codigo:string}>|null} null = no llegó.
 */
export function dolaresPorSimbolo(items) {
  if (!Array.isArray(items)) return null
  const m = new Map()
  for (const it of items) {
    if (!it?.dolares) continue
    for (const c of [it.pesos, it.s]) {
      if (c) m.set(`${String(c).toUpperCase()}.BA`, { px: it.px_usd ?? null, codigo: it.dolares })
    }
  }
  return m
}

/** El precio en dólares de un CEDEAR, para precargar la compra. */
export async function precioCedearEnDolares(simbolo) {
  const items = await cargarCedears()
  const it = (items || []).find(x => x.s === String(simbolo || '').toUpperCase())
  return it?.px_usd ?? null
}
