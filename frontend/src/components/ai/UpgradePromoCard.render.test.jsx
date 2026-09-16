import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import UpgradePromoCard from './UpgradePromoCard.jsx'

// Lo que importa de esta tarjeta es EL TEXTO QUE LEE EL USUARIO, no sus props.
// Así que se renderiza de verdad y se lee la salida. Los dos casos de abajo son
// los dos carteles que hasta 2026-09-16 decían lo mismo siendo cosas distintas.
function texto(el) {
  return renderToStaticMarkup(<MemoryRouter>{el}</MemoryRouter>)
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
}

const UPGRADE_PRO = { available: true, current_tier: 'free', target_tier: 'pro', benefits: ['Chat libre con el Coach IA'] }

describe('UpgradePromoCard — el cartel de cuota agotada', () => {
  it('dice el contador que SÍ frenó (análisis), no el otro', () => {
    const t = texto(
      <UpgradePromoCard
        usage={{ analyses_count: 1, analyses_limit: 1, analyses_remaining: 0,
                 chat_count: 0, chat_limit: 1, chat_remaining: 1, resets_on: '2026-09-21' }}
        upgrade={{ ...UPGRADE_PRO, target_tier: 'plus' }}
        kind="analyses"
        codigo="chat_quota_exceeded"
      />,
    )
    expect(t).toContain('Llegaste al límite del plan Free')
    expect(t).toContain('Usaste 1 de 1 análisis esta semana')
    // El bug de producción, congelado: NUNCA más "0 de 1 consultas".
    expect(t).not.toContain('0 de 1')
    expect(t).toContain('Tu próximo análisis se libera')
  })

  it('y cuando el que se agotó es el de consultas, dice ese', () => {
    const t = texto(
      <UpgradePromoCard
        usage={{ analyses_count: 0, analyses_limit: 6, analyses_remaining: 6,
                 chat_count: 1, chat_limit: 1, chat_remaining: 0, resets_on: '2026-09-21' }}
        upgrade={UPGRADE_PRO}
        kind="chat"
        codigo="chat_quota_exceeded"
      />,
    )
    expect(t).toContain('Usaste 1 de 1 consultas')
    expect(t).toContain('Tu próxima consulta se libera')
  })
})

describe('UpgradePromoCard — el candado de plan NO es una cuota', () => {
  // El caso REAL: un Free escribió "tengo 0,001 bitcoin" y la tarjeta le dijo
  // "Llegaste al límite del plan Free · Usaste 0 de 1 consultas al Coach IA",
  // con el contador intacto y tapando el texto que le decía qué SÍ podía hacer.
  const MENSAJE = 'El chat libre está disponible solo en el plan Pro. Elegí una de las preguntas guiadas, registrá una operación o un movimiento.'
  const gate = texto(
    <UpgradePromoCard
      usage={{ analyses_count: 1, analyses_limit: 1, analyses_remaining: 0,
               chat_count: 0, chat_limit: 1, chat_remaining: 1, resets_on: '2026-09-21' }}
      upgrade={UPGRADE_PRO}
      kind="chat"
      codigo="free_chat_not_allowed"
      mensaje={MENSAJE}
    />,
  )

  it('no dice que llegó a un límite, porque no llegó a ninguno', () => {
    expect(gate).toContain('No llegaste a ningún límite')
    expect(gate).not.toContain('Llegaste al límite')
  })

  it('no muestra NINGÚN contador inventado — ese era el bug', () => {
    expect(gate).not.toContain('0 de 1')
    expect(gate).not.toContain('Usaste')
  })

  it('no promete una renovación: no hay nada que se renueve', () => {
    expect(gate).not.toContain('se libera')
  })

  it('dice qué es y, sobre todo, qué SÍ puede hacer ahora', () => {
    expect(gate).toContain('Las preguntas libres son del plan Pro')
    expect(gate).toContain('preguntas guiadas')
    expect(gate).toContain('registrá una operación')
  })
})
