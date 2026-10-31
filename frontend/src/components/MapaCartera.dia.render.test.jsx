// Lo del día del «Mapa de tu cartera» (GET /api/cartera/mapa-del-dia):
//   · D3 (auditoría 31/10): mientras llegaba el pedido, cada cuadrito decía
//     «sin dato de hoy», y si fallaba quedaba así para siempre. Ahora hay tres
//     estados (pedirElDia): cargando, listo y falló (con «Reintentar»).
//   · A4 (Nico 31/10): en el Panorama el renglón es «Hoy tus activos · vie
//     30/10» (la fecha de la rueda que mide; un sábado, la del viernes y sin
//     llamarla «hoy»), tapado con el ojito. En el Dashboard el mapa va SIN ese
//     renglón: ahí el «hoy» de la cartera lo cuenta sólo la tarjeta «Hoy».
// Las pantallas se dibujan sin efectos (renderToStaticMarkup): lo que llegó
// del pedido entra por `dia` (el Panorama lo pasa con `diaDelMapa`).
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../contexts/PrivacyContext', () => ({ usePrivacy: () => ({ hidden: false, toggle: () => {} }), OCULTO: '••••' }))
vi.mock('../utils/api', () => ({ api: { get: vi.fn(async () => ({ items: [] })), post: vi.fn(), put: vi.fn(), patch: vi.fn() } }))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../hooks/usePlanFeatures', () => ({ usePlanFeatures: () => ({}) }))
vi.mock('../utils/almacen', async (orig) => ({ ...(await orig()), leer: () => 'hoy' }))

import MapaCartera from './MapaCartera'
import { Panorama } from '../pages/AnalisisTecnico'
import { pedirElDia } from '../utils/mapaCartera'
import fuenteDashboard from '../pages/Dashboard.jsx?raw'

const fila = (nombre, peso) => ({ clave: `${nombre}|0`, nombre, ruta: nombre, tenes: true, peso, vigente: true, fondo: { id: 'alcista' } })
const FILAS = [fila('GGAL', 60), fila('MELI', 40)]
const activo = (asset, pct) => ({ asset, local: false, hoy: pct == null ? null : { pct, usd: pct * 10 }, dia_txt: pct == null ? 'el viernes 30/10' : 'hoy', promedio_pct: 5 })
const LISTO = (ultima) => ({ estado: 'listo', datos: { hoy: '2026-10-31', cartera: null, ultima_rueda: ultima, activos: [activo('GGAL', 1.5), activo('MELI', -2)] } })
const VIERNES_HOY = { rueda: '2026-10-30', es_hoy: true, pct: 0.83, usd: 120, mercados: ['eeuu'] }
const SABADO = { rueda: '2026-10-30', es_hoy: false, pct: 0.83, usd: 120, mercados: ['eeuu'] }

const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')
const panorama = (dia, hidden = false) => texto(renderToStaticMarkup(
  <MemoryRouter>
    <Panorama lista={{ cargando: false, error: null, sinMedir: {} }} filas={FILAS} semana={{ datos: null, cargando: false }}
      hidden={hidden} onVer={() => {}} onPestana={() => {}} diaDelMapa={dia} />
  </MemoryRouter>))
// El mapa como lo monta el Dashboard (sin `conTusActivos`).
const comoEnElDashboard = (dia) => texto(renderToStaticMarkup(
  <MemoryRouter><MapaCartera filas={FILAS} cargando={false} error={false} hidden={false} dia={dia} /></MemoryRouter>))

describe('A4: «Hoy tus activos» con la fecha de la rueda, sólo en el Panorama', () => {
  it('el Panorama: «Hoy tus activos · vie 30/10» con su %', () => {
    const t = panorama(LISTO(VIERNES_HOY))
    expect(t).toContain('Hoy tus activos · vie 30/10 : +0,8')
    expect(t).not.toContain('Hoy tu cartera')
  })

  it('un sábado: la rueda del viernes, con su fecha y sin llamarla «hoy»', () => {
    const t = panorama(LISTO(SABADO))
    expect(t).toContain('Tus activos en la última rueda · vie 30/10 :')
    expect(t).not.toContain('Hoy tus activos')
  })

  it('con el ojito, el % tapado y la fecha a la vista', () => {
    const t = panorama(LISTO(VIERNES_HOY), true)
    expect(t).toContain('Hoy tus activos · vie 30/10 : ••••')
    expect(t).not.toMatch(/0,8/)
  })

  it('el Dashboard: el mapa sin el renglón; lo que más sumó y restó, igual', () => {
    const t = comoEnElDashboard(LISTO(VIERNES_HOY))
    expect(t).not.toMatch(/tus activos|tu cartera:/i)
    expect(t).toContain('Lo que más sumó hoy: GGAL')
    // Y el Dashboard de verdad monta el mapa sin la opción.
    const enElDashboard = fuenteDashboard.match(/<MapaCartera\b[^>]*\/>/)?.[0]
    expect(enElDashboard).toBeTruthy()
    expect(enElDashboard).not.toMatch(/conTusActivos/)
  })
})

describe('D3: cargando y falló no son «sin dato»', () => {
  it('mientras llega: «cargando», no «sin dato de hoy»', () => {
    const html = renderToStaticMarkup(<MemoryRouter><MapaCartera filas={FILAS} cargando={false} error={false} hidden={false} /></MemoryRouter>)
    expect(html).toContain('cargando lo de hoy…')
    expect(html).toContain('Cargando cuánto se movió cada uno…')
    expect(html).not.toContain('sin dato de hoy')
    expect(texto(html)).not.toMatch(/\bsin dato\b/)
  })

  it('si falló: lo dice y deja reintentar', () => {
    const html = renderToStaticMarkup(<MemoryRouter><MapaCartera filas={FILAS} cargando={false} error={false} hidden={false} dia={{ estado: 'fallo', datos: null }} /></MemoryRouter>)
    expect(html).toContain('No pudimos traer cuánto se movió cada uno.')
    expect(html).toContain('Reintentar')
    expect(html).toContain('no pudimos traer lo de hoy')
    expect(html).not.toContain('sin dato de hoy')
  })

  it('con los datos, cada uno con lo suyo (y «sin dato» cuando de verdad no hay)', () => {
    const datos = LISTO(VIERNES_HOY)
    datos.datos.activos[1] = { ...activo('MELI', null), dia_txt: null }
    const html = renderToStaticMarkup(<MemoryRouter><MapaCartera filas={FILAS} cargando={false} error={false} hidden={false} dia={datos} /></MemoryRouter>)
    expect(html).toContain('+1,5% hoy')
    expect(html).toContain('sin dato de hoy')
    expect(html).not.toContain('Reintentar')
    expect(html).not.toContain('cargando lo de hoy')
  })

  it('el pedido: falló si revienta o si no trae la forma esperada', async () => {
    expect(await pedirElDia(async () => { throw new Error('502') })).toEqual({ estado: 'fallo', datos: null })
    expect(await pedirElDia(async () => ({ detail: 'x' }))).toEqual({ estado: 'fallo', datos: null })
    const r = { hoy: '2026-10-31', activos: [] }
    expect(await pedirElDia(async (url) => (url === '/cartera/mapa-del-dia' ? r : null))).toEqual({ estado: 'listo', datos: r })
  })
})
