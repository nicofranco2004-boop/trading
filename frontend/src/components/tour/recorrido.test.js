import { describe, it, expect, beforeEach } from 'vitest'
import { destino, tomarTurno, soltarTurno, turnoLibre, pedirTour, tomarPedido, hayPedido, escucharTurno, presentarse } from './recorrido'

describe('a dónde hay que ir para cada paso', () => {
  it('sin ruta, se queda donde está', () => {
    expect(destino({ ruta: null }, '/cartera', '')).toBeNull()
  })

  it('en otra pantalla, va a la ruta con lo que el paso pide', () => {
    expect(destino({ ruta: '/alertas', busqueda: '?tab=crear' }, '/ai', '')).toBe('/alertas?tab=crear')
    expect(destino({ ruta: '/ai' }, '/cartera', '')).toBe('/ai')
  })

  it('ya está: no se mueve', () => {
    expect(destino({ ruta: '/alertas', busqueda: '?tab=crear' }, '/alertas', '?tab=crear')).toBeNull()
  })

  it('en la misma pantalla cambia sólo lo que el paso pide y respeta el resto', () => {
    // El gráfico guarda su activo en la dirección: cambiar de pestaña no lo pierde.
    const p = { ruta: '/analisis-tecnico', busqueda: '?tab=lista' }
    expect(destino(p, '/analisis-tecnico', '?activo=GGAL')).toBe('/analisis-tecnico?activo=GGAL&tab=lista')
    expect(destino(p, '/analisis-tecnico', '?activo=GGAL&tab=lista')).toBeNull()
  })

  it('un valor vacío pide que NO esté (la pestaña de entrada)', () => {
    const p = { ruta: '/analisis-tecnico', busqueda: '?tab=' }
    expect(destino(p, '/analisis-tecnico', '?tab=senales&activo=AAPL')).toBe('/analisis-tecnico?activo=AAPL')
    expect(destino(p, '/analisis-tecnico', '?activo=AAPL')).toBeNull()
    expect(destino(p, '/analisis-tecnico', '')).toBeNull()
    // Antes comparaba la dirección entera: con `?activo=` nunca se daba por llegado.
  })
})

describe('nunca dos tutoriales a la vez', () => {
  beforeEach(() => { soltarTurno('a'); soltarTurno('b'); tomarPedido('a'); tomarPedido('b') })

  it('el que llega segundo espera', () => {
    expect(tomarTurno('a')).toBe(true)
    expect(turnoLibre('b')).toBe(false)
    expect(tomarTurno('b')).toBe(false)
    // El que lo tiene puede volver a pedirlo (abrirlo a mano estando abierto).
    expect(tomarTurno('a')).toBe(true)
  })

  it('al soltarlo, los que esperaban se enteran', () => {
    let avisos = 0
    const dejar = escucharTurno(() => { avisos += 1 })
    tomarTurno('a')
    soltarTurno('b')            // no era suyo: no pasa nada
    expect(avisos).toBe(0)
    expect(turnoLibre('b')).toBe(false)
    soltarTurno('a')
    expect(avisos).toBe(1)
    expect(turnoLibre('b')).toBe(true)
    dejar()
  })

  it('abrir uno a mano: el pedido se consume una vez y avisa', () => {
    let avisos = 0
    const dejar = escucharTurno(() => { avisos += 1 })
    const irse = presentarse('b')
    expect(pedirTour('b')).toBe(true)
    expect(avisos).toBe(1)
    expect(hayPedido('b')).toBe(true)
    expect(tomarPedido('a')).toBe(false)
    expect(tomarPedido('b')).toBe(true)
    expect(tomarPedido('b')).toBe(false)
    irse(); dejar()
  })

  it('un pedido para un tutorial que no está montado no queda guardado', () => {
    // Si la red que lo envuelve lo apagó, el pedido quedaba guardado y, al
    // volver a montarse en otra pantalla, arrancaba sin que nadie tocara nada.
    expect(pedirTour('b')).toBe(false)
    expect(hayPedido('b')).toBe(false)
    const irse = presentarse('b')
    pedirTour('b')
    irse()                       // se desmonta con el pedido pendiente: se tira
    expect(hayPedido('b')).toBe(false)
  })
})

describe('las pruebas apagan TODOS los tutoriales, con la clave de verdad', () => {
  it('la lista sale del catálogo y tiene los dos', async () => {
    const { CLAVES_DE_LOS_TOURS } = await import('./recorrido')
    const { CATALOGO } = await import('../../utils/catalogoDelAlmacen')
    expect(CLAVES_DE_LOS_TOURS).toContain(CATALOGO.vioNovedades.clave)
    expect(CLAVES_DE_LOS_TOURS).toContain(CATALOGO.vioTourTecnico.clave)
  })

  it('nadie escribe la clave de un tutorial a mano', async () => {
    // Dos pruebas de pantalla usaban la clave de antes del catálogo, que ya
    // no existía: el tutorial corría en el medio y se llevaba la
    // pantalla a otra ruta. Una clave escrita a mano envejece sin avisar.
    const { readdirSync, readFileSync, statSync } = await import('node:fs')
    const { join } = await import('node:path')
    // Todo el frontend: las pruebas y también los scripts que miran pantallas.
    const raiz = new URL('../../../', import.meta.url).pathname
    const fuera = []
    const recorrer = (d) => {
      for (const n of readdirSync(d)) {
        const p = join(d, n)
        // Lo que arma `npm run build` (dist, dist-ssr) no es fuente: el prerender trae
        // el catálogo entero adentro, y después de un build esto daba rojo (05/11).
        if (statSync(p).isDirectory()) { if (!['node_modules', 'dist', 'dist-ssr'].includes(n)) recorrer(p); continue }
        // El catálogo las declara; recorrido.js las reconoce por su prefijo; esta prueba las busca.
        if (!/\.(js|jsx|mjs)$/.test(n) || /(catalogoDelAlmacen|tour\/recorrido|tour\/recorrido\.test)\.js$/.test(p)) continue
        if (/rendi[:_]tour[:_]/.test(readFileSync(p, 'utf8'))) fuera.push(p.slice(raiz.length))
      }
    }
    recorrer(raiz)
    expect(fuera).toEqual([])
  })
})
