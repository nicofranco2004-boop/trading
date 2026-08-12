/**
 * `errorMessage` — el mensaje que ve el usuario cuando una escritura falla.
 *
 * Existe por un bug real: Positions.jsx leía `e.response.data.detail` (forma de
 * axios) sobre un cliente hecho con fetch, así que `detail` era SIEMPRE undefined
 * y el toast caía siempre al texto genérico "Revisá los datos" — incluso cuando
 * el backend devolvía un 500 que explicaba la causa exacta.
 */
import { describe, it, expect } from 'vitest'
import { errorMessage } from './api'

// Réplica de lo que arma `buildHttpError`: el mensaje ya viene resuelto en
// .message, y el body crudo queda en .payload.
function httpError(status, detail) {
  const msg = typeof detail === 'string' ? detail : `HTTP ${status}`
  const e = new Error(msg)
  e.status = status
  e.payload = { detail }
  return e
}

describe('errorMessage', () => {
  it('devuelve el detail del backend cuando es texto (el 500 que explicaba la causa)', () => {
    const e = httpError(500, 'Error al registrar flujo de caja: database or disk is full')
    expect(errorMessage(e)).toBe('Error al registrar flujo de caja: database or disk is full')
  })

  it('traduce el 422 de Pydantic a "campo: qué pasa" en vez de un choclo de JSON', () => {
    const e = httpError(422, [
      { type: 'greater_than', loc: ['body', 'amount'], msg: 'Input should be greater than 0' },
    ])
    // 'body' se descarta: al usuario no le dice nada dónde viajaba el campo.
    expect(errorMessage(e)).toBe('amount: Input should be greater than 0')
  })

  it('junta varios errores de campo del mismo 422', () => {
    const e = httpError(422, [
      { loc: ['body', 'amount'], msg: 'Input should be greater than 0' },
      { loc: ['body', 'tc_blue'], msg: 'Input should be greater than 0' },
    ])
    expect(errorMessage(e)).toBe(
      'amount: Input should be greater than 0 · tc_blue: Input should be greater than 0',
    )
  })

  it('cae a e.message cuando el body no trae detail usable (ej. el 502 del gateway)', () => {
    const e = new Error('El servidor no respondió, así que no sabemos si la operación llegó a completarse.')
    e.status = 502
    e.payload = null
    expect(errorMessage(e)).toContain('no sabemos si la operación llegó a completarse')
  })

  it('devuelve "" —no "undefined"— cuando no hay NADA legible, para que el caller ponga su fallback', () => {
    expect(errorMessage(undefined)).toBe('')
    expect(errorMessage({})).toBe('')
  })

  it('NO lee la forma de axios: es la que rompía, y confirmarlo evita que vuelva', () => {
    const e = new Error('')
    e.response = { data: { detail: 'esto nunca existió en este cliente' } }
    expect(errorMessage(e)).toBe('')
  })
})
