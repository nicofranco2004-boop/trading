// El CSV de /admin/pruebas sale de la MISMA lista de columnas que la tabla.
//
// Este archivo existe por una forma de bug que no rompe nada y se descubre
// tarde y mal: alguien agrega una columna a la tabla, el export sigue con su
// propia lista, y el CSV que se abre en Excel no tiene justo la columna que se
// fue a buscar. Nadie ve un error — simplemente falta.
//
// La defensa es que haya UNA lista (`columnas()`) y que el CSV se arme de ella.
// Estos tests lo comprueban de las dos puntas: que el encabezado del CSV sea
// exactamente las etiquetas de la tabla, y que cada fila tenga tantos campos
// como columnas.
import { describe, it, expect } from 'vitest'
import { columnas, aCSV, ordenarFilas } from './AdminPruebas'

const HOY = '2026-09-23'

function persona(extra = {}) {
  return {
    id: 1, email: 'sofia@ejemplo.com', name: 'Sofía Ramírez',
    estado: 'activa', vencida: false, stage: 'pro',
    inicio: '2026-09-17', termina: '2026-10-07', dia: 7, days_left: 14,
    tiene: { brokers: 2, posiciones: 210, operaciones: 64, a_mano: 0 },
    ventanas: {
      1: { filas: 0, archivos: 0, ia: 0, entradas: 1, dias_entro: 1, dias_posibles: 1 },
      3: { filas: 8, archivos: 1, ia: 0, entradas: 3, dias_entro: 2, dias_posibles: 3 },
      7: { filas: 210, archivos: 3, ia: 6, entradas: 9, dias_entro: 6, dias_posibles: 7 },
      15: { filas: 210, archivos: 3, ia: 6, entradas: 9, dias_entro: 6, dias_posibles: 7 },
    },
    ultimo_login: '2026-09-23', ultima_importacion: '2026-09-22',
    estado_uso: 'avanzando',
    ...extra,
  }
}

const cols = () => columnas(HOY, 20, 3)

describe('el CSV y la tabla no se pueden separar', () => {
  it('el encabezado del CSV son las etiquetas de la tabla, en orden', () => {
    const csv = aCSV(cols(), [persona()])
    const cabecera = csv.replace(/^﻿/, '').split('\r\n')[0]
    expect(cabecera).toBe(cols().map(c => c.label).join(';'))
  })

  it('cada fila trae un campo por columna', () => {
    const csv = aCSV(cols(), [persona(), persona({ id: 2 })])
    const filas = csv.replace(/^﻿/, '').split('\r\n')
    expect(filas).toHaveLength(3)              // encabezado + 2
    for (const f of filas) expect(f.split(';')).toHaveLength(cols().length)
  })

  it('lleva BOM y separador ; — es lo que abre el Excel en español sin preguntar', () => {
    const csv = aCSV(cols(), [persona()])
    expect(csv.startsWith('﻿')).toBe(true)
    expect(csv).toContain(';')
  })
})

describe('los valores que van al CSV son los CRUDOS', () => {
  it('las fechas van en ISO, no en "hace 5 días"', () => {
    const fila = aCSV(cols(), [persona()]).split('\r\n')[1]
    expect(fila).toContain('2026-09-17')     // arrancó
    expect(fila).toContain('2026-09-22')     // última carga
    expect(fila).not.toContain('hace ')
  })

  it('los números van como números, para que Excel pueda sumarlos', () => {
    const c = cols()
    const p = persona()
    expect(c.find(x => x.key === 'posiciones').get(p)).toBe(210)
    expect(c.find(x => x.key === 'carga7').get(p)).toBe(210)
    // La frecuencia va como PORCENTAJE: 6 de 7 días = 86%.
    expect(c.find(x => x.key === 'frecuencia').get(p)).toBe(86)
  })

  it('la frecuencia se mide contra los días que la prueba PUDO vivir', () => {
    // ⭐ El que arrancó ayer y entró los dos días tiene frecuencia 100%, no
    // "2 de 7". Con la cuenta cruda, el orden por frecuencia premiaba tener la
    // prueba más vieja en vez de entrar más seguido.
    const c = cols()
    const novato = persona({
      ventanas: { ...persona().ventanas,
                  7: { filas: 5, archivos: 1, ia: 0, entradas: 4,
                       dias_entro: 2, dias_posibles: 2 } },
    })
    const viejo = persona({
      ventanas: { ...persona().ventanas,
                  7: { filas: 5, archivos: 1, ia: 0, entradas: 3,
                       dias_entro: 3, dias_posibles: 7 } },
    })
    const frec = c.find(x => x.key === 'frecuencia')
    expect(frec.get(novato)).toBe(100)
    expect(frec.get(viejo)).toBe(43)
    // Y el orden los pone en ese orden, no al revés.
    const [primero] = ordenarFilas([viejo, novato], frec, 'desc')
    expect(primero.ventanas[7].dias_posibles).toBe(2)
  })

  it('sin días vividos la frecuencia es vacía, no cero ni infinito', () => {
    const c = cols()
    const p = persona({
      ventanas: { ...persona().ventanas,
                  7: { filas: 0, archivos: 0, ia: 0, entradas: 0,
                       dias_entro: 0, dias_posibles: 0 } },
    })
    expect(c.find(x => x.key === 'frecuencia').get(p)).toBeNull()
  })

  it('escapa lo que rompería el archivo', () => {
    const csv = aCSV(cols(), [persona({ name: 'Pérez; Juan "el flaco"' })])
    expect(csv).toContain('"Pérez; Juan ""el flaco"""')
    // Y el campo escapado sigue siendo UNO solo.
    expect(csv.split('\r\n')[1].split(';')).toHaveLength(cols().length + 1)
  })
})

describe('las celdas que dependen del estado', () => {
  it('"le queda" es null cuando la prueba ya no corre: al CSV va vacío, no 0', () => {
    const c = cols().find(x => x.key === 'quedan')
    expect(c.get(persona())).toBe(14)
    expect(c.get(persona({ estado: 'terminada', days_left: 0 }))).toBeNull()
    expect(c.get(persona({ estado: 'pago', days_left: 0 }))).toBeNull()
  })

  it('el plan queda vacío cuando no hay etapa', () => {
    const c = cols().find(x => x.key === 'plan')
    expect(c.get(persona())).toBe('Pro')
    expect(c.get(persona({ stage: 'plus' }))).toBe('Plus')
    expect(c.get(persona({ stage: null }))).toBe('')
  })

  it('la señal va en palabras, no en el código interno', () => {
    const c = cols().find(x => x.key === 'senal')
    expect(c.get(persona({ estado_uso: 'sin_datos' }))).toBe('App vacía')
    expect(c.get(persona({ estado_uso: 'frenado' }))).toBe('Frenado')
  })

  it('una persona sin datos no rompe ninguna columna', () => {
    const vacia = persona({
      name: null, stage: null, estado: 'terminada', estado_uso: 'sin_datos',
      tiene: { brokers: 0, posiciones: 0, operaciones: 0, a_mano: 0 },
      ventanas: {}, ultimo_login: null, ultima_importacion: null,
    })
    expect(() => aCSV(cols(), [vacia])).not.toThrow()
    const fila = aCSV(cols(), [vacia]).split('\r\n')[1]
    expect(fila.split(';')).toHaveLength(cols().length)
  })
})

describe('el orden de la tabla', () => {
  const p = (id, quedan, nombre) => persona({
    id, name: nombre, days_left: quedan,
    estado: quedan == null ? 'terminada' : 'activa',
  })
  const colQuedan = () => cols().find(c => c.key === 'quedan')
  const nombres = filas => filas.map(f => f.name)

  it('ordena de menor a mayor', () => {
    const filas = [p(1, 14, 'Sofía'), p(2, 3, 'Tomás'), p(3, 9, 'Valen')]
    expect(nombres(ordenarFilas(filas, colQuedan(), 'asc')))
      .toEqual(['Tomás', 'Valen', 'Sofía'])
  })

  it('⭐ los vacíos quedan al final TAMBIÉN al ordenar al revés', () => {
    // El caso real: "¿a quién le queda menos?" con dos pruebas terminadas en
    // la lista. Si el vacío viajara con el orden, arriba quedarían los que ya
    // no tienen tiempo y abajo los que hay que salir a buscar.
    const filas = [p(1, 14, 'Sofía'), p(2, null, 'Carolina'), p(3, 3, 'Tomás')]
    expect(nombres(ordenarFilas(filas, colQuedan(), 'asc')))
      .toEqual(['Tomás', 'Sofía', 'Carolina'])
    expect(nombres(ordenarFilas(filas, colQuedan(), 'desc')))
      .toEqual(['Sofía', 'Tomás', 'Carolina'])
  })

  it('el texto ordena con las reglas del español (la ñ y los acentos)', () => {
    const filas = [persona({ id: 1, name: 'Zárate' }), persona({ id: 2, name: 'Ñandú' }),
                   persona({ id: 3, name: 'Álvarez' })]
    const col = cols().find(c => c.key === 'usuario')
    expect(nombres(ordenarFilas(filas, col, 'asc'))).toEqual(['Álvarez', 'Ñandú', 'Zárate'])
  })

  it('no toca el array que recibe', () => {
    const filas = [p(1, 14, 'Sofía'), p(2, 3, 'Tomás')]
    ordenarFilas(filas, colQuedan(), 'asc')
    expect(nombres(filas)).toEqual(['Sofía', 'Tomás'])
  })
})
