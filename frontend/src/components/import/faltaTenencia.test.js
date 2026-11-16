/**
 * Cuándo sugerir la foto de tenencia — la decisión, no la caja azul.
 *
 * La foto del broker es el mejor chequeo del sistema porque no depende de
 * conocer el bug: la referencia es el broker. Pero sólo la sube el 57,8% de la
 * gente elegible (160 de 277 usuarios, medido contra la copia de prod del
 * 2026-08-16). Al 42,2% restante no se le verifica nada.
 *
 * Cocos es el que más pierde: 68 usuarios elegibles sin foto, el 53% de todo lo
 * que se pierde, con 42% de cobertura.
 */
import { describe, it, expect } from 'vitest'
import { resolverFaltaTenencia } from './ImportWizard.jsx'
import { BROKER_GUIDES, pasosDeLaFoto } from './BrokerInstructions'

// Forma real de /imports/parsers/grouped. Dónde bajar la foto ya no viene
// del servidor (era una copia que se había separado de la guía): sale de
// BROKER_GUIDES.
const GRUPOS = [
  { platform: 'generic', platform_label: 'Genérico', tenencia_format: null },
  { platform: 'cocos', platform_label: 'Cocos Capital', tenencia_format: 'cocos_tenencia' },
  { platform: 'balanz', platform_label: 'Balanz', tenencia_format: 'balanz_tenencia' },
  { platform: 'balanz_internacional', platform_label: 'Balanz Internacional', tenencia_format: null },
  { platform: 'binance', platform_label: 'Binance', tenencia_format: null },
]
const guia = (id) => BROKER_GUIDES.find(g => g.id === id)
const BASE = { isSpecificParser: true, tenenciaFile: null }

describe('resolverFaltaTenencia', () => {
  it('sugiere la foto cuando el broker la tiene y no la trajeron', () => {
    const r = resolverFaltaTenencia(GRUPOS, 'cocos', BASE)
    expect(r).toEqual({
      broker: 'Cocos Capital',
      pasos: pasosDeLaFoto(guia('cocos')),
      pasoEnLaGuia: 2,
    })
    expect(r.pasos.join(' ')).toContain('Descargar portfolio')
  })

  it('no dice nada si YA subieron la foto', () => {
    expect(resolverFaltaTenencia(GRUPOS, 'cocos',
      { ...BASE, tenenciaFile: new File([''], 'x.csv') })).toBeNull()
  })

  it('no dice nada si el broker no tiene foto', () => {
    expect(resolverFaltaTenencia(GRUPOS, 'binance', BASE)).toBeNull()
  })

  // ⭐ El caso que motivó leer la capacidad del backend en vez del dict del
  // frontend: `balanz_internacional` está mapeado en TENENCIA_BROKER_BY_FORMAT
  // pero su parser de foto NO existe. Sugerirla mandaría a la persona a buscar
  // un archivo que nadie sabe leer.
  it('NO pide una foto que todavia no existe (balanz_internacional)', () => {
    expect(resolverFaltaTenencia(GRUPOS, 'balanz_internacional', BASE)).toBeNull()
  })

  it('no molesta en el flujo generico (CSV propio)', () => {
    // Ahí no hay broker del que bajar una foto: el archivo lo arma la persona.
    expect(resolverFaltaTenencia(GRUPOS, 'cocos',
      { ...BASE, isSpecificParser: false })).toBeNull()
  })

  it('los tres exports de Balanz comparten la misma foto', () => {
    // La capacidad va a nivel PLATAFORMA: Balanz tiene tres formatos de
    // movimientos y una sola foto.
    const r = resolverFaltaTenencia(GRUPOS, 'balanz', BASE)
    expect(r.broker).toBe('Balanz')
    expect(r.pasos.join(' ')).toContain('Posición consolidada')
  })

  it('falla CERRADO con datos incompletos', () => {
    // Si el backend todavía no respondió, o mandó una plataforma desconocida,
    // no se inventa un aviso.
    expect(resolverFaltaTenencia([], 'cocos', BASE)).toBeNull()
    expect(resolverFaltaTenencia(null, 'cocos', BASE)).toBeNull()
    expect(resolverFaltaTenencia(GRUPOS, 'inexistente', BASE)).toBeNull()
  })

  it('sin guía igual avisa, sin la linea de "donde bajarla"', () => {
    const grupos = [{ platform: 'x', platform_label: 'X', tenencia_format: 'x_tenencia' }]
    expect(resolverFaltaTenencia(grupos, 'x', BASE)).toEqual({ broker: 'X', pasos: [], pasoEnLaGuia: null })
  })
})
