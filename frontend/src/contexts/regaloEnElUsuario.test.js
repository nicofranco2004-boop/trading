// `credit_es_regalo` tiene que llegar del servidor al `user` que leen
// Configuración y Planes. El mapeo copia campo por campo: un campo que el
// servidor manda y acá no se copia llega `undefined`, y la pantalla sigue
// diciendo «Cambiaste de plan… con el crédito convertido» a quien recibió un
// regalo, sin ningún error. Lo que manda el servidor lo fija
// backend/tests/test_regalo_masivo.py (LosTextosDelRegaloTest).
import { describe, it, expect } from 'vitest'
import { mapMeToUser } from './AuthContext'

describe('el regalo llega al usuario de la app', () => {
  it('copia credit_es_regalo tal cual', () => {
    expect(mapMeToUser({ email: 'a@ejemplo.com', access_mode: 'credit_only', credit_es_regalo: true })
      .credit_es_regalo).toBe(true)
  })

  it('sin el dato (servidor viejo, o no es regalo) es false, no undefined', () => {
    expect(mapMeToUser({ email: 'a@ejemplo.com' }).credit_es_regalo).toBe(false)
  })
})
