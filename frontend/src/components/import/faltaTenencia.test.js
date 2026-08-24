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

// Forma real de /imports/parsers/grouped.
const GRUPOS = [
  { platform: 'generic', platform_label: 'Genérico', tenencia_format: null, tenencia_label: null },
  { platform: 'cocos', platform_label: 'Cocos Capital', tenencia_format: 'cocos_tenencia', tenencia_label: 'Inversiones → Estado de cuenta → Exportar' },
  { platform: 'balanz', platform_label: 'Balanz', tenencia_format: 'balanz_tenencia', tenencia_label: 'Mi cuenta → Resumen de cuenta (PDF)' },
  { platform: 'balanz_internacional', platform_label: 'Balanz Internacional', tenencia_format: null, tenencia_label: null },
  { platform: 'binance', platform_label: 'Binance', tenencia_format: null, tenencia_label: null },
]
const BASE = { isSpecificParser: true, tenenciaFile: null }

describe('resolverFaltaTenencia', () => {
  it('sugiere la foto cuando el broker la tiene y no la trajeron', () => {
    const r = resolverFaltaTenencia(GRUPOS, 'cocos', BASE)
    expect(r).toEqual({
      broker: 'Cocos Capital',
      label: 'Inversiones → Estado de cuenta → Exportar',
    })
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
    expect(r.label).toContain('Resumen de cuenta')
  })

  it('falla CERRADO con datos incompletos', () => {
    // Si el backend todavía no respondió, o mandó una plataforma desconocida,
    // no se inventa un aviso.
    expect(resolverFaltaTenencia([], 'cocos', BASE)).toBeNull()
    expect(resolverFaltaTenencia(null, 'cocos', BASE)).toBeNull()
    expect(resolverFaltaTenencia(GRUPOS, 'inexistente', BASE)).toBeNull()
  })

  it('sin instrucciones igual avisa, sin la linea de "donde bajarla"', () => {
    const grupos = [{ platform: 'x', platform_label: 'X', tenencia_format: 'x_tenencia', tenencia_label: null }]
    expect(resolverFaltaTenencia(grupos, 'x', BASE)).toEqual({ broker: 'X', label: null })
  })
})
