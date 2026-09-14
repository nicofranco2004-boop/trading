import { describe, it, expect } from 'vitest'
import {
  tieneCupoDeEscuchas, restantesTexto, contadorCorto, costoDeEscuchar, avisoDeCuota,
} from './cuotaTexto.js'

// Free: 1 consulta escrita + 1 escucha con CUPO PROPIO (no sale de las consultas).
const FREE = { tier: 'free', chat_limit: 1, chat_count: 0, listens_limit: 1, listen_count: 0, listens_remaining: 1, resets_on: '2026-09-19' }
// Plus/Pro: escuchar descuenta una consulta → una respuesta hablada gasta 2.
const PLUS = { tier: 'plus', chat_limit: 9, chat_count: 0, listens_limit: null, listens_remaining: null, resets_on: '2026-09-19' }
const PRO  = { tier: 'pro',  chat_limit: 40, chat_count: 0, listens_limit: null, listens_remaining: null, resets_on: '2026-09-19' }
const con = (base, over) => ({ ...base, ...over })

describe('quién paga la escucha con qué', () => {
  it('sólo Free tiene cupo propio', () => {
    expect(tieneCupoDeEscuchas(FREE)).toBe(true)
    expect(tieneCupoDeEscuchas(PLUS)).toBe(false)
    expect(tieneCupoDeEscuchas(PRO)).toBe(false)
  })
})

describe('lo que le queda, en el pie del chat', () => {
  it('a Free le muestra las escuchas — antes eran invisibles hasta gastarse', () => {
    expect(restantesTexto(FREE)).toBe('1 consulta y 1 audio esta semana')
  })

  it('a Free le cuenta cada cosa por su lado', () => {
    // Gastó la consulta pero NO la escucha: decirle "no te queda nada" sería falso.
    expect(restantesTexto(con(FREE, { chat_count: 1 })))
      .toBe('0 consultas y 1 audio esta semana')
    expect(restantesTexto(con(FREE, { chat_count: 1, listen_count: 1, listens_remaining: 0 })))
      .toBe('Sin consultas ni audios esta semana')
  })

  it('a los pagos les avisa que escuchar cuesta una más', () => {
    // El contador les bajaba de a dos sin ninguna explicación.
    expect(restantesTexto(PLUS)).toBe('9 consultas restantes · escuchar gasta 1 consulta más')
    expect(restantesTexto(con(PRO, { chat_count: 39 }))).toBe('1 consulta restante · escuchar gasta 1 consulta más')
  })

  it('sin cuota que mostrar no inventa nada', () => {
    expect(restantesTexto(null)).toBeNull()
    expect(restantesTexto({ chat_limit: 0 })).toBeNull()
  })
})

describe('el contador corto del encabezado', () => {
  it('a Free le agrega el de escuchas', () => {
    expect(contadorCorto(FREE)).toBe('0/1 · 0/1 🔊')
  })
  it('a los pagos los deja como estaban', () => {
    expect(contadorCorto(PLUS)).toBe('0/9 esta semana')
  })
})

describe('qué dice el globo del parlante', () => {
  it('a los pagos les dice el precio: una hablada sale 2', () => {
    expect(costoDeEscuchar(PRO)).toContain('te sale 2')
    expect(costoDeEscuchar(PRO)).toContain('gratis')      // re-escuchar no se cobra
  })
  it('a Free le dice que es un cupo aparte', () => {
    expect(costoDeEscuchar(FREE)).toContain('aparte de tus consultas')
    expect(costoDeEscuchar(FREE)).not.toContain('te sale 2')
  })
})

describe('las fechas se dicen, no se muestran como en la base', () => {
  it('nunca sale un 2026-09-19 en la cara del usuario', () => {
    const a = avisoDeCuota(con(PLUS, { chat_count: 9 }))
    expect(a.texto).not.toMatch(/\d{4}-\d{2}-\d{2}/)
    expect(a.texto).toContain('19 de septiembre')
  })
})

describe('el aviso de que se está acabando', () => {
  it('no aparece cuando sobra cuota — si aparece siempre, deja de leerse', () => {
    expect(avisoDeCuota(PRO)).toBeNull()
    expect(avisoDeCuota(PLUS)).toBeNull()
    expect(avisoDeCuota(con(PLUS, { chat_count: 6 }))).toBeNull()   // quedan 3
  })

  it('a Free NO le avisa mientras tenga su única consulta', () => {
    // Con límite 1, "te queda 1" sería avisar desde el minuto cero.
    expect(avisoDeCuota(FREE)).toBeNull()
  })

  it('avisa con 2 o menos, y con 0 dice que se acabó', () => {
    expect(avisoDeCuota(con(PLUS, { chat_count: 7 })).texto).toBe('Te quedan 2 consultas esta semana. Se renuevan el 19 de septiembre.')
    expect(avisoDeCuota(con(PLUS, { chat_count: 8 })).texto).toBe('Te queda 1 consulta esta semana. Se renuevan el 19 de septiembre.')
    expect(avisoDeCuota(con(PLUS, { chat_count: 9 })).agotado).toBe(true)
  })

  it('el atajo a Planes sólo si hay adónde ir', () => {
    expect(avisoDeCuota(con(FREE, { chat_count: 1 })).cta).toBe(true)
    expect(avisoDeCuota(con(PLUS, { chat_count: 9 })).cta).toBe(true)
    // Arriba de Pro no hay plan retail: ofrecerle "mejorá tu plan" es ruido.
    expect(avisoDeCuota(con(PRO, { chat_count: 40 })).cta).toBe(false)
    expect(avisoDeCuota(con(PRO, { chat_count: 40 })).texto).toContain('Se renuevan el 19 de septiembre')
  })

  it('a Free sin consultas pero CON escucha no le dice que no le queda nada', () => {
    const a = avisoDeCuota(con(FREE, { chat_count: 1 }))
    expect(a.texto).toContain('Todavía te queda 1 audio')
  })
})

// ─── El cupo que el usuario no ve ────────────────────────────────────────────
// El botón ✦ escribe en el chat pero descuenta del cupo de ANÁLISIS, que es
// otro. En esta pantalla no se muestra en ningún lado: el pie cuenta consultas
// y el contador de arriba también. Un Free toca ✦ una vez, el pie le sigue
// diciendo "1 consulta restante", toca otro y se come "llegaste al máximo de
// análisis (1/1)" sin haber tenido cómo verlo venir.
describe('avisar que los análisis se acabaron', () => {
  const freeConAnalisis = (analisis, consultas = 1) => ({
    tier: 'free', chat_limit: 1, chat_count: 1 - consultas,
    analyses_limit: 1, analyses_remaining: analisis,
    listens_limit: 1, listens_remaining: 1, resets_on: '2026-09-19',
  })

  it('con consultas de sobra pero sin análisis, igual avisa', () => {
    const a = avisoDeCuota({ ...freeConAnalisis(0), chat_limit: 40, chat_count: 0, tier: 'pro' })
    expect(a).not.toBeNull()
    expect(a.texto).toMatch(/✦/)
    expect(a.texto).toMatch(/escrito sigue andando/i)
  })

  it('con análisis de sobra y consultas de sobra, se queda callado', () => {
    expect(avisoDeCuota({ tier: 'pro', chat_limit: 40, chat_count: 0,
                          analyses_limit: 60, analyses_remaining: 59 })).toBeNull()
  })

  it('sin consultas Y con análisis, no le dice que se quedó sin nada', () => {
    const a = avisoDeCuota(freeConAnalisis(1, 0))
    expect(a.agotado).toBe(true)
    expect(a.texto).toMatch(/✦/)
  })

  it('sin consultas y sin análisis, no inventa un cupo que no hay', () => {
    const a = avisoDeCuota(freeConAnalisis(0, 0))
    expect(a.texto).not.toMatch(/✦/)
  })

  it('un plan sin cupo de análisis declarado no rompe nada', () => {
    // usage viejo o incompleto: mejor callado que inventando.
    expect(avisoDeCuota({ tier: 'pro', chat_limit: 40, chat_count: 0 })).toBeNull()
  })
})
