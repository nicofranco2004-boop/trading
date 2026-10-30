// ¿Acción argentina o no? — la copia de la pantalla contra la tabla de casos
// que también lee el servidor (backend/tests/test_accion_local.py →
// accion_local.py). Auditoría A 29/10: «GGAL» del buscador se leía con el ADR
// en Señales y con BYMA en la ficha (A1); BLK sin tipo en IOL era «acción
// argentina» acá porque se miraba la tabla de ratios, que no la tiene (P1).
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import casos from './fixtures/accionLocal.json'
import { esLoteLocal } from './accionLocal'
import { lecturaDeSeguido } from './listaTecnica'
import { miradaSinTenencia } from './buscadorRapido'
import { setBrokersRegistry } from './valuation'
import { activoTecnico } from '../components/alerts/alertasTexto'

beforeAll(() => setBrokersRegistry(casos.brokers))
afterAll(() => setBrokersRegistry([]))

describe('lo que tenés (esLoteLocal)', () => {
  for (const c of casos.lotes) {
    it(c.por_que, () => expect(esLoteLocal(c.lote)).toBe(c.local))
  }
})

describe('lo que seguís: Tu lista, la ficha sin tenencia y la alerta técnica, con LA misma regla', () => {
  for (const c of casos.seguidos) {
    it(c.por_que, () => {
      const { asset, local } = lecturaDeSeguido(c.simbolo, c.tipo)
      expect({ asset, local }).toEqual({ asset: c.asset, local: c.local })
      // «Ver el gráfico» abre la ficha: la mira con la misma regla (y el mismo tipo).
      expect(miradaSinTenencia(c.simbolo, c.tipo).accionLocal).toBe(c.local)
      // Una alerta técnica creada desde Alertas sin tenerlo mira la misma serie
      // que la ficha a la que lleva el mail (re-test A1a, 29/10).
      if (!c.tipo && !c.simbolo.endsWith('-USD')) expect(activoTecnico(c.simbolo, []).accion_local).toBe(c.local)
    })
  }
})
