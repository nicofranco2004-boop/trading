import { describe, it, expect, vi } from 'vitest'

// Con qué pestaña se abre /alertas. Pedido de Nico (2026-10-19): si no creaste
// ninguna alerta, se abre en «Crear alerta», no en «Mis alertas». Antes el
// resumen diario prendido contaba como «tener algo» y te mandaba a «Mis».
vi.mock('../components/alerts/CrearAlerta', () => ({ default: () => null }))
vi.mock('../components/alerts/MisAlertas', () => ({ default: () => null }))
vi.mock('../components/alerts/AlertaForm', () => ({ default: () => null }))
vi.mock('../components/advisor/AdvisorAlerts', () => ({ default: () => null }))
import { pestanaInicial } from './Alertas'

describe('pestanaInicial', () => {
  it('sin alertas creadas: Crear (aunque tenga el resumen prendido, que acá ni se mira)', () => {
    expect(pestanaInicial({ tabUrl: null, cargando: false, cantidadAvisos: 0 })).toBe('crear')
  })
  it('con alguna alerta: Mis alertas', () => {
    expect(pestanaInicial({ tabUrl: null, cargando: false, cantidadAvisos: 2 })).toBe('mis')
  })
  it('mientras cargan las alertas no elige (no muestra Crear un instante a quien tiene)', () => {
    expect(pestanaInicial({ tabUrl: null, cargando: true, cantidadAvisos: 0 })).toBeNull()
  })
  it('la dirección manda: el tutorial pide crear, el mail de un aviso pide mis', () => {
    expect(pestanaInicial({ tabUrl: 'crear', cargando: true, cantidadAvisos: 5 })).toBe('crear')
    expect(pestanaInicial({ tabUrl: 'mis', cargando: false, cantidadAvisos: 0 })).toBe('mis')
  })
  it('una pestaña inventada en la dirección se ignora', () => {
    expect(pestanaInicial({ tabUrl: 'otra', cargando: false, cantidadAvisos: 0 })).toBe('crear')
  })
})
