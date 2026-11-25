import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'

// La regla de la bienvenida obligatoria: quién no ve Rendi hasta cargar su
// historial, y qué pantallas quedan a la vista igual. El dato de fondo lo da el
// servidor (`falta_cargar_historial`); acá se prueban las excepciones de
// pantalla (pausa, demo, asesor adentro de un cliente) y las rutas libres.

let regla, almacen, CATALOGO
beforeAll(async () => {
  instalarNavegadorMinimo()
  regla = await import('./bienvenidaObligatoria')
  almacen = await import('./almacen')
  ;({ CATALOGO } = await import('./catalogoDelAlmacen'))
})
afterAll(() => { vi.unstubAllGlobals() })
afterEach(() => { sessionStorage.clear() })

const NUEVO = { email: 'ana@prueba.test', falta_cargar_historial: true }

describe('faltaConfigurar', () => {
  it('la cuenta que el servidor marca, sí', () => {
    expect(regla.faltaConfigurar(NUEVO)).toBe(true)
  })
  it('sin la marca (cuenta vieja, ya cargó, asesor, admin…), no', () => {
    expect(regla.faltaConfigurar({ email: 'x@prueba.test' })).toBe(false)
    expect(regla.faltaConfigurar({ ...NUEVO, falta_cargar_historial: false })).toBe(false)
  })
  it('sin sesión, no', () => {
    expect(regla.faltaConfigurar(null)).toBe(false)
    expect(regla.faltaConfigurar(undefined)).toBe(false)
  })
  it('con la cuenta en pausa gana el muro de plan (con la pausa no se puede importar)', () => {
    expect(regla.faltaConfigurar({ ...NUEVO, cuenta_en_pausa: true })).toBe(false)
  })
  it('el demo, nunca', () => {
    expect(regla.faltaConfigurar(NUEVO, { isDemo: true })).toBe(false)
  })
  it('un asesor adentro de un cliente, nunca: la bienvenida es de quien se loguea', () => {
    expect(regla.faltaConfigurar(NUEVO, { clientCtx: { id: 7, label: 'Ana' } })).toBe(false)
  })
})

describe('bienvenidaTapaLaPantalla', () => {
  it('a quien le falta, le tapa la app entera', () => {
    for (const r of ['/', '/posiciones', '/dashboard', '/imports', '/config', '/ai', '/mas', '/bienvenida']) {
      expect(regla.bienvenidaTapaLaPantalla(NUEVO, r), r).toBe(true)
    }
  })
  it('deja a la vista la bienvenida, los planes, el pago y lo legal', () => {
    for (const r of ['/onboarding', '/planes', '/billing/success', '/billing/failure', '/terminos', '/reembolso', '/privacidad']) {
      expect(regla.bienvenidaTapaLaPantalla(NUEVO, r), r).toBe(false)
    }
  })
  it('deja a la vista lo que llega por un link de mail: el pedido de acceso del asesor y su informe', () => {
    // Si la puerta los tapara, el token del link se perdía: no había forma de
    // aceptar (ni rechazar) al asesor sin antes subir un archivo.
    for (const r of ['/acceso', '/i/abc123']) {
      expect(regla.bienvenidaTapaLaPantalla(NUEVO, r), r).toBe(false)
    }
  })
  it('deja a la vista la guía pública', () => {
    for (const r of ['/guia', '/guia/empezar', '/guia/cuenta-y-planes']) {
      expect(regla.bienvenidaTapaLaPantalla(NUEVO, r), r).toBe(false)
    }
  })
  it('«/i/» es el informe, no cualquier cosa que empiece con i: Importar sigue tapado', () => {
    expect(regla.bienvenidaTapaLaPantalla(NUEVO, '/imports')).toBe(true)
    expect(regla.bienvenidaTapaLaPantalla(NUEVO, '/i')).toBe(true)
  })
  it('la lista es la del muro de plan más lo propio: lo que se sume al muro queda a la vista acá también', async () => {
    const muro = await import('./muroDePlan')
    expect(muro.SIEMPRE_A_LA_VISTA.length).toBeGreaterThan(0)
    for (const r of muro.SIEMPRE_A_LA_VISTA) {
      expect(regla.SIEMPRE_A_LA_VISTA, r).toContain(r)
      expect(regla.bienvenidaTapaLaPantalla(NUEVO, r), r).toBe(false)
    }
  })
  it('a quien no le falta, no le tapa nada', () => {
    expect(regla.bienvenidaTapaLaPantalla({ email: 'x@prueba.test' }, '/')).toBe(false)
    expect(regla.bienvenidaTapaLaPantalla({ ...NUEVO, cuenta_en_pausa: true }, '/')).toBe(false)
    expect(regla.bienvenidaTapaLaPantalla(NUEVO, '/', { isDemo: true })).toBe(false)
  })
})

describe('«se acaba de configurar» (para que el tutorial de novedades espere)', () => {
  it('arranca en no, y al marcarlo queda en esta pestaña', () => {
    expect(regla.recienConfigurado()).toBe(false)
    regla.marcarRecienConfigurado()
    expect(regla.recienConfigurado()).toBe(true)
    // En el almacén de la PESTAÑA (no queda para la próxima visita).
    expect(almacen.leer(CATALOGO.recienConfigurado)).toBe('1')
    expect(localStorage.getItem('rendi_bienvenida_recien')).toBeNull()
  })
  it('el tutorial de novedades no va en la misma visita en que terminó la bienvenida', async () => {
    const { dondeVaNovedades } = await import('../components/tour/TourNovedades')
    expect(dondeVaNovedades('/')).toBe(true)
    regla.marcarRecienConfigurado()
    expect(dondeVaNovedades('/')).toBe(false)
  })
})

