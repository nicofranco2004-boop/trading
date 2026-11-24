// El aviso que confirma el borrado de un broker tiene que nombrar TODO lo que el
// backend dice que se va, y vivir en un solo lugar.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { avisoBorrarBroker, partesDelBorrado } from './avisoBorrarBroker'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('avisoBorrarBroker', () => {
  it('nombra los futuros abiertos y las posiciones guardadas', () => {
    // REGRESIÓN: el borrado se los llevaba (o peor, los dejaba) sin decirlo.
    const partes = partesDelBorrado({
      positions: 1, operations: 0, monthly_entries: 1, import_batches: 0,
      futures: 1, archived: 25,
    })
    expect(partes).toContain('1 futuro abierto')
    expect(partes.some(p => p.startsWith('25 posiciones guardadas en "Posiciones eliminadas"'))).toBe(true)
  })

  it('singular y plural', () => {
    expect(partesDelBorrado({ futures: 2, archived: 1 })).toEqual([
      '2 futuros abiertos',
      '1 posición guardada en "Posiciones eliminadas" (ya no se van a poder restaurar)',
    ])
  })

  it('lo que ya decía lo sigue diciendo, en el mismo orden', () => {
    expect(partesDelBorrado({ positions: 2, operations: 1, monthly_entries: 3, import_batches: 1 }))
      .toEqual(['2 posiciones', '1 operación', '3 entradas mensuales', '1 import'])
  })

  it('avisa de los pases con otro broker: lo que llegó allá se queda', () => {
    expect(partesDelBorrado({ positions: 1, traspasos: 2 })).toEqual([
      '1 posición',
      '2 pases de títulos con otro broker tuyo (los títulos que llegaron al otro broker se quedan allá; si después reimportás este broker, van a aparecer en los dos lados)',
    ])
    expect(partesDelBorrado({ traspasos: 1 })[0]).toMatch(/^1 pase de títulos/)
  })

  it('con el lado de cada pase: el broker de DESTINO no dice que «se quedan allá»', () => {
    // Revisión final (contrato #1): borrar el broker al que LLEGARON los títulos los
    // borra con él, y no vuelven al de origen salvo que se deshaga el pase. El texto
    // de la salida era falso para ese lado.
    const destino = partesDelBorrado({ positions: 1, traspasos: 1, traspasos_salida: 0, traspasos_entrada: 1 })
    expect(destino).toEqual([
      '1 posición',
      '1 pase de títulos que llegaron desde otro broker tuyo (se borran con este broker y no vuelven al de origen; para que vuelvan, deshacé el pase en Movimientos → «Deshacer pase», antes o después de borrar)',
    ])
    expect(destino.join(' ')).not.toMatch(/se quedan allá/)
    const origen = partesDelBorrado({ traspasos: 1, traspasos_salida: 1, traspasos_entrada: 0 })
    expect(origen).toEqual([
      '1 pase de títulos con otro broker tuyo (los títulos que llegaron al otro broker se quedan allá; si después reimportás este broker, van a aparecer en los dos lados)',
    ])
    // Un broker que es origen de un pase y destino de otro: las dos líneas.
    expect(partesDelBorrado({ traspasos: 2, traspasos_salida: 1, traspasos_entrada: 1 })).toHaveLength(2)
  })

  it('un resumen viejo (sin las claves nuevas) no rompe ni inventa líneas', () => {
    expect(partesDelBorrado({ positions: 1 })).toEqual(['1 posición'])
    expect(partesDelBorrado(undefined)).toEqual([])
  })

  it('arma el mensaje completo, con el aviso de la sub-cuenta', () => {
    const msg = avisoBorrarBroker('Cocos', {
      counts: { positions: 1, futures: 1 },
      sibling: { name: 'Cocos · USD', currency: 'USD' },
    })
    expect(msg).toContain('El broker "Cocos" tiene data:')
    expect(msg).toContain('  • 1 posición\n  • 1 futuro abierto')
    expect(msg).toContain('es PADRE de "Cocos · USD" (USD)')
    expect(msg).toContain('¿Borrar TODO? Esta acción no se puede deshacer.')
  })
})

describe('el aviso vive en un solo lugar', () => {
  // Estaba copiado en las dos pantallas que borran brokers: una clave nueva del
  // resumen había que acordarse de sumarla en las dos.
  for (const archivo of ['components/BrokerManager.jsx', 'pages/PositionsMobile.jsx']) {
    it(`${archivo} usa el helper y no arma su propio texto`, () => {
      const src = readFileSync(join(SRC, archivo), 'utf8')
      expect(src).toContain('avisoBorrarBroker(b.name, detail)')
      expect(src).not.toContain('¿Borrar TODO?')
      expect(src).not.toContain('c.import_batches')
    })
  }
})
