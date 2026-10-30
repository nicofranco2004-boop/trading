// De quién es lo que la pestaña guarda sobre una cuenta (utils/duenoDeLaPestana),
// en los dos lugares ya publicados que no tienen su propia prueba montada:
//   · la marca «ya guardé la foto de hoy» del inicio (yaSeGuardoLaFotoDeHoy /
//     marcarFotoDeHoy, las que usa Dashboard alrededor de POST /snapshots);
//   · la última tanda de importación del asesor, con nombres de clientes
//     (guardarLocal / leerLocal, las que usa AdvisorImports).
// Cada pantalla trabaja con el dueño de SUS datos: el de la pestaña cuando se
// abrió (useDuenoDeLosDatos). Acá, «abrir el inicio» es tomar ese dueño.
// (Los números que cambian y el último total visto: NumeroQueCambia.test.js y
// RecalculoDeCartera.test.js.)
//
// Con las piezas DE VERDAD: la sesión es la que AuthContext guarda en
// `rendi_user` y la que api.js borra con un 401 (la sesión que vence); el
// cliente del asesor es el contexto de api.js (setClientContext).
import { describe, it, expect, beforeAll, beforeEach, afterEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'

let api, dueno, yaSeGuardoLaFotoDeHoy, marcarFotoDeHoy, guardarLocal, leerLocal
beforeAll(async () => {
  instalarNavegadorMinimo()
  api = await import('./api')
  dueno = await import('./duenoDeLaPestana')
  ;({ yaSeGuardoLaFotoDeHoy, marcarFotoDeHoy } = await import('./guardarValuacion'))
  ;({ guardarLocal, leerLocal } = await import('../pages/AdvisorImports'))
})

const entrar = (email) => localStorage.setItem('rendi_user', JSON.stringify({ name: email, email }))
const seVencioLaSesion = () => localStorage.removeItem('rendi_user')   // lo que hace api.js con un 401
const HOY = '2026-10-30'
// Abrir el inicio: sus datos son del dueño de la pestaña en ese momento.
const abrirInicio = () => dueno.duenoDeLaPestana()
// Lo que hace el inicio después de guardar la foto, y lo que mira antes.
const guardoLaFoto = () => marcarFotoDeHoy(abrirInicio(), HOY)
const fotoPendiente = () => !yaSeGuardoLaFotoDeHoy(abrirInicio(), HOY)
// La pantalla de importación del asesor: la tanda es de la persona, a su nivel.
const abrirImportacion = () => dueno.duenoPropioDeLaPestana()

beforeEach(() => entrar('ana@prueba.test'))
afterEach(() => { localStorage.clear(); sessionStorage.clear(); api.setClientContext(null) })

describe('la regla', () => {
  it('es la persona (como la compara quienEs) y la cuenta abierta; sin nadie, null', () => {
    entrar(' Ana@Prueba.test')
    expect(dueno.duenoDeLaPestana()).toBe('ana@prueba.test|propia')
    api.setClientContext({ id: 7, label: 'Juan' })
    expect(dueno.duenoDeLaPestana()).toBe('ana@prueba.test|cliente-7')
    seVencioLaSesion()
    expect(dueno.duenoDeLaPestana()).toBeNull()
  })
})

describe('«ya guardé la foto de hoy» (inicio)', () => {
  it('el asesor guarda la del cliente 2 y abre el cliente 3: al 3 todavía le falta la suya', () => {
    api.setClientContext({ id: 2, label: 'Dos' })
    guardoLaFoto()
    expect(fotoPendiente()).toBe(false)
    api.setClientContext({ id: 3, label: 'Tres' })
    expect(fotoPendiente()).toBe(true)
    api.setClientContext(null)
    expect(fotoPendiente()).toBe(true)                 // y su propia cuenta, también
  })

  it('a Ana se le vence la sesión y entra Bruno: a Bruno le falta la suya', () => {
    guardoLaFoto()
    seVencioLaSesion()
    expect(fotoPendiente()).toBe(false)                // sin nadie no se manda foto
    expect(guardoLaFoto()).toBe(false)                 // ni se marca
    entrar('bruno@prueba.test')
    expect(fotoPendiente()).toBe(true)
    entrar('ana@prueba.test')
    expect(fotoPendiente()).toBe(false)                // la de Ana sigue marcada
  })
})

describe('la última tanda de importación del asesor (con nombres de clientes)', () => {
  const TANDA = { momento: 'listo', filas: [{ id: 1, nombre: 'Juan Pérez', estado: 'completo' }] }

  it('a Ana se le vence la sesión y entra Bruno: no ve la tanda ni los clientes de Ana', () => {
    guardarLocal(TANDA, abrirImportacion())
    expect(leerLocal(abrirImportacion())?.filas?.[0]?.nombre).toBe('Juan Pérez')
    seVencioLaSesion()
    expect(leerLocal(abrirImportacion())).toBeNull()
    entrar('bruno@prueba.test')
    expect(leerLocal(abrirImportacion())).toBeNull()
    entrar('ana@prueba.test')
    expect(leerLocal(abrirImportacion())?.filas?.[0]?.nombre).toBe('Juan Pérez')   // la de Ana sigue siendo de Ana
  })

  it('al volver de revisar un cliente (con el cliente todavía abierto), la tanda sigue ahí', () => {
    // La tanda es del asesor a SU nivel: 28c4b60a la buscaba con la clave del
    // cliente abierto y «volver a la tanda» no la encontraba.
    guardarLocal(TANDA, abrirImportacion())
    api.setClientContext({ id: 2, label: 'Dos' })          // fue a revisar al cliente 2
    expect(leerLocal(abrirImportacion())?.filas?.[0]?.nombre).toBe('Juan Pérez')
  })

  it('pantalla abierta y otra pestaña entra como otra persona: la tanda no se guarda a nombre de nadie', () => {
    const deAna = abrirImportacion()
    entrar('bruno@prueba.test')
    guardarLocal(TANDA, deAna)
    expect(leerLocal(abrirImportacion())).toBeNull()       // Bruno no la tiene
    entrar('ana@prueba.test')
    expect(leerLocal(abrirImportacion())).toBeNull()       // y no se guardó: la pestaña ya no era de Ana
  })

  it('sin nadie logueado no queda nada guardado', () => {
    seVencioLaSesion()
    guardarLocal(TANDA, abrirImportacion())
    const claves = Array.from({ length: sessionStorage.length }, (_, i) => sessionStorage.key(i))
    expect(claves.filter(k => k.startsWith('rendi_tanda_ultima'))).toEqual([])
  })
})
