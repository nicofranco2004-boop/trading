// useListaDelGrafico — los datos y lo que se puede hacer con tu lista al
// costado del gráfico (components/ListaDelGrafico.jsx). Las cuentas, sin React,
// en utils/listaDelGrafico.js.
// ════════════════════════════════════════════════════════════════════════════
// No pide la lista de nuevo: usa la de la página (`lista`, useListaTecnica de
// pages/TuLista.jsx, que Análisis técnico pide UNA vez para todas sus
// pestañas: tu watchlist, lo que tenés y la lectura de cada uno). Lo que cambia
// acá (una bandera, su nombre, el orden) se escribe en esa misma lista
// (`lista.cambiar`) y en la cuenta, sin volver a pedir la lectura de todo: así
// «Tu lista» muestra la bandera nueva sin recargar. Agregar o sacar un activo
// avisa a toda la app (utils/watchlistEvents): la página vuelve a pedir y el
// activo nuevo llega con su lectura, y el inicio también se entera.
//
// Los precios se refrescan solos cada 5 minutos con alguna rueda de la lista en
// horario y, con todas cerradas, a la próxima media hora (la misma regla del
// inicio, utils/relojVisible.refrescoSegunRueda). Si la lectura técnica de la
// página no se pudo traer, la lista no se queda vacía: pide sólo tu watchlist.
//
// La opción «Cartera» (lo que tenés) se pide recién cuando se elige
// (GET /api/watchlist/cartera, `cargarCartera`) y desde ahí se refresca con el
// mismo reloj. Lo que pesa cada activo sale de la página (`tenencias`).

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { notifyWatchlistChanged } from '../utils/watchlistEvents'
import { refrescoSegunRueda } from '../utils/relojVisible'
import { useRelojVisible } from './useRelojVisible'
import { filaDe, nombresDeBanderas, pesosDeTuCartera } from '../utils/listaDelGrafico'

const mismo = (a, b) => String(a || '').toUpperCase() === String(b || '').toUpperCase()

export function useListaDelGrafico(lista) {
  // Lo propio, sólo si la página no pudo traer su lista (`lista.error`).
  const sinLaDeLaPagina = !lista || !!lista.error
  const [propia, setPropia] = useState(null)        // { seguidos, banderas }
  const [propiaFallo, setPropiaFallo] = useState(false)
  const [vuelta, setVuelta] = useState(0)
  // Lo último que no se pudo guardar, para decirlo: { texto }.
  const [aviso, setAviso] = useState(null)

  useEffect(() => {
    if (!sinLaDeLaPagina) return undefined
    let vivo = true
    setPropiaFallo(false)
    api.get('/watchlist')
      .then(r => { if (vivo) setPropia({ seguidos: r?.items || [], banderas: r?.banderas || [] }) })
      .catch(() => { if (vivo) setPropiaFallo(true) })
    return () => { vivo = false }
  }, [sinLaDeLaPagina, vuelta])

  const fuente = sinLaDeLaPagina
    ? {
      cargando: !propia && !propiaFallo,
      error: propiaFallo && !propia,
      seguidos: propia?.seguidos || [],
      banderas: propia?.banderas || [],
      tenencias: [],
      indice: null,
      cambiar: (fn) => setPropia(e => (e ? { ...e, ...fn(e) } : e)),
    }
    : lista
  const { cambiar } = fuente

  const filas = useMemo(() => (fuente.seguidos || []).map(filaDe).filter(f => f.simbolo), [fuente.seguidos])
  const nombres = useMemo(() => nombresDeBanderas(fuente.banderas), [fuente.banderas])

  // Tu cartera: 'nada' (no se pidió) | 'cargando' | 'listo' | 'error'. Un
  // refresco que falla deja lo que había.
  const [cartera, setCartera] = useState({ estado: 'nada', items: [] })
  const cargarCartera = () => {
    setCartera(c => (c.items.length ? c : { estado: 'cargando', items: [] }))
    api.get('/watchlist/cartera')
      .then(r => setCartera({ estado: 'listo', items: Array.isArray(r?.items) ? r.items : [] }))
      .catch(() => setCartera(c => (c.items.length ? c : { estado: 'error', items: [] })))
  }
  const filasCartera = useMemo(() => cartera.items.map(filaDe).filter(f => f.simbolo), [cartera.items])
  const pesos = useMemo(() => pesosDeTuCartera(fuente.tenencias), [fuente.tenencias])

  // Los precios, solos. Un refresco que falla no toca lo que se ve.
  const algunaEnHorario = filas.some(f => f.enHorario) || filasCartera.some(f => f.enHorario)
  const plazo = useMemo(() => refrescoSegunRueda({ en_horario: algunaEnHorario }), [algunaEnHorario])
  useRelojVisible(() => {
    if (cartera.estado === 'listo') cargarCartera()
    if (fuente.cargando || fuente.error) return
    api.get('/watchlist')
      .then(r => { if (Array.isArray(r?.items)) cambiar(() => ({ seguidos: r.items, banderas: r.banderas || [] })) })
      .catch(() => {})
  }, plazo)

  // Cambia en pantalla ya; si el servidor no lo guarda, vuelve como estaba y
  // se dice. `antes` es lo que había (para volver).
  async function guardar({ cambio, pedido, que }) {
    const antes = { seguidos: fuente.seguidos || [], banderas: fuente.banderas || [] }
    cambiar(cambio)
    setAviso(null)
    try {
      await pedido()
      return true
    } catch (err) {
      cambiar(() => antes)
      // Lo que dice el servidor cuando es para la persona (el tope de 100, el
      // permiso de sólo lectura de un asesor); si no, lo nuestro.
      const delServidor = err?.status >= 400 && err.status < 500 && err.status !== 422
        && typeof err.message === 'string' && !/^[[{]/.test(err.message) ? err.message : null
      setAviso({ texto: delServidor || `No pudimos guardar ${que}. Probá de nuevo en un rato.` })
      return false
    }
  }

  const ponerBandera = (simbolo, bandera) => guardar({
    que: 'la bandera',
    cambio: (e) => ({ seguidos: e.seguidos.map(it => (mismo(it.symbol, simbolo) ? { ...it, bandera } : it)) }),
    pedido: () => api.patch(`/watchlist/${encodeURIComponent(simbolo)}`, { bandera }),
  })

  const nombrarBandera = (id, nombre) => {
    const limpio = String(nombre || '').split(/\s+/).filter(Boolean).join(' ').slice(0, 30) || null
    return guardar({
      que: 'el nombre',
      cambio: (e) => ({ banderas: (e.banderas?.length ? e.banderas : []).some(b => b.id === id)
        ? e.banderas.map(b => (b.id === id ? { ...b, nombre: limpio } : b))
        : [...(e.banderas || []), { id, nombre: limpio }] }),
      pedido: () => api.put(`/watchlist/banderas/${encodeURIComponent(id)}`, { nombre: limpio || '' }),
    })
  }

  // `simbolos`: tu lista entera en el orden nuevo.
  const ordenar = (simbolos) => guardar({
    que: 'el orden',
    cambio: (e) => {
      const lugar = new Map(simbolos.map((s, i) => [String(s).toUpperCase(), i]))
      return { seguidos: e.seguidos.map(it => (lugar.has(String(it.symbol).toUpperCase()) ? { ...it, orden: lugar.get(String(it.symbol).toUpperCase()) } : it)) }
    },
    pedido: () => api.put('/watchlist/orden', { simbolos }),
  })

  // `assetType`: sólo para una acción argentina que se mira en Nueva York
  // ('STOCK', la regla de listaTecnica.lecturaDeSeguido).
  const agregar = async (simbolo, bandera = null, assetType = null) => {
    const sym = String(simbolo || '').toUpperCase()
    const ultimo = Math.max(-1, ...filas.map(f => f.orden ?? -1))
    const ok = await guardar({
      que: sym,
      cambio: (e) => (e.seguidos.some(it => mismo(it.symbol, sym)) ? {}
        : { seguidos: [{ symbol: sym, asset_type: assetType, bandera, orden: ultimo + 1, added_at: new Date().toISOString(), price: null, change_pct: null, _pending: true }, ...e.seguidos] }),
      pedido: () => api.post('/watchlist', { symbol: sym, ...(bandera ? { bandera } : {}), ...(assetType ? { asset_type: assetType } : {}) }),
    })
    if (ok) notifyWatchlistChanged({ symbol: sym, added: true })
    return ok
  }

  const sacar = async (simbolo) => {
    const ok = await guardar({
      que: 'el cambio',
      cambio: (e) => ({ seguidos: e.seguidos.filter(it => !mismo(it.symbol, simbolo)) }),
      pedido: () => api.delete(`/watchlist/${encodeURIComponent(simbolo)}`),
    })
    if (ok) notifyWatchlistChanged({ symbol: simbolo, removed: true })
    return ok
  }

  return {
    cargando: !!fuente.cargando,
    error: !!fuente.error,
    reintentar: () => setVuelta(v => v + 1),
    filas,
    nombres,
    tenencias: fuente.tenencias || [],
    indice: fuente.indice || null,
    cartera: {
      pedida: cartera.estado !== 'nada',
      cargando: cartera.estado === 'cargando',
      error: cartera.estado === 'error',
      filas: filasCartera,
      pesos,
      cargar: cargarCartera,
    },
    aviso,
    cerrarAviso: () => setAviso(null),
    ponerBandera, nombrarBandera, ordenar, agregar, sacar,
  }
}
