"""tecnico.cambios_desde — LA cuenta de «qué cambió» (pieza 15).

Pruebas de la función sola, con velas armadas a mano. Lo que importa:
  · cada tipo sale de la MISMA regla que la alerta y la tarjeta de la ficha
    (`senal_desde` → `ultimo_cruce`), no de una copia;
  · sólo cuenta lo que pasó DESPUÉS de `desde` (un cruce de hace 30 días no es
    de esta semana);
  · de cada tipo vale el último del período (cruzó y volvió: no hay cambio
    «para arriba»).
El camino entero (HTTP, velas de la noche, el sábado) está en
test_tus_senales.py.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tecnico  # noqa: E402


def _velas(cierres, hasta=date(2026, 10, 23)):
    """Una vela por día CORRIDO terminando en `hasta` (alcanza para las cuentas:
    la regla mira fechas, no días de la semana)."""
    n = len(cierres)
    return [{"date": (hasta - timedelta(days=n - 1 - i)).isoformat(), "open": c, "high": c * 1.01,
             "low": c * 0.99, "close": c, "volume": 1000.0} for i, c in enumerate(cierres)]


HOY = date(2026, 10, 23)
SEMANA = (HOY - timedelta(days=7)).isoformat()


class CambiosDesdeTest(unittest.TestCase):

    def test_cruce_del_200_de_esta_semana_y_no_el_de_hace_un_mes(self):
        # 400 días en 100 con ruido, 2 en 90 (abajo) y salta a 120 hace 2 días.
        base = [100 + (1 if i % 2 else -1) for i in range(400)]
        v = _velas(base + [90.0] * 40 + [120.0, 121.0, 122.0])
        tipos = {c["tipo"]: c for c in tecnico.cambios_desde(v, SEMANA)}
        self.assertIn("media200", tipos)
        self.assertEqual(tipos["media200"]["sentido"], "arriba")
        self.assertEqual(tipos["media200"]["fecha"], (HOY - timedelta(days=2)).isoformat())
        # La misma respuesta que la alerta técnica (misma función, misma regla).
        self.assertEqual({k: tipos["media200"][k] for k in ("fecha", "sentido", "cierre", "referencia")},
                         {k: tecnico.senal_desde(v, "media200", SEMANA)[k]
                          for k in ("fecha", "sentido", "cierre", "referencia")})
        # Contado desde hace 2 días (exclusive), el cruce ya no entra.
        hace_2 = (HOY - timedelta(days=2)).isoformat()
        self.assertNotIn("media200", {c["tipo"] for c in tecnico.cambios_desde(v, hace_2)})

    def test_un_cruce_de_hace_30_dias_no_es_de_esta_semana(self):
        base = [100 + (1 if i % 2 else -1) for i in range(400)]
        v = _velas(base + [90.0] * 40 + [130.0] * 30)
        self.assertIsNotNone(tecnico.senal_desde(v, "media200", (HOY - timedelta(days=40)).isoformat()),
                             "el cruce existe, hace 30 días")
        tipos = {c["tipo"] for c in tecnico.cambios_desde(v, SEMANA)}
        self.assertNotIn("media200", tipos)
        self.assertNotIn("media50", tipos)

    def test_cruzo_y_volvio_vale_el_ultimo(self):
        base = [100 + (1 if i % 2 else -1) for i in range(400)]
        v = _velas(base + [90.0] * 40 + [120.0, 85.0, 84.0])
        c = {x["tipo"]: x for x in tecnico.cambios_desde(v, SEMANA)}
        # Lo que dice la ficha hoy: abajo. No hay «pasó arriba» esta semana.
        self.assertEqual(c["media200"]["sentido"], "abajo")
        self.assertEqual(c["media200"]["fecha"], (HOY - timedelta(days=1)).isoformat())

    def test_la_fuerza_cayo_muy_rapido_con_de_donde_venia(self):
        # Sube despacio un año (RSI alto), y esta semana cae fuerte 5 días.
        sube = [100 + i * 0.1 + (0.5 if i % 2 else -0.5) for i in range(400)]
        cae = [sube[-1] * (0.95 ** k) for k in range(1, 6)]
        v = _velas(sube + cae)
        c = {x["tipo"]: x for x in tecnico.cambios_desde(v, SEMANA)}
        self.assertIn("rsi_bajo_30", c)
        r = tecnico.rsi([x["close"] for x in v])
        i = next(k for k, x in enumerate(v) if x["date"] == c["rsi_bajo_30"]["fecha"])
        self.assertLess(r[i], 30)
        self.assertGreaterEqual(r[i - 1], 30, "el día del cruce, no otro")
        self.assertEqual(c["rsi_bajo_30"]["rsi"], r[i])
        self.assertEqual(c["rsi_bajo_30"]["rsi_antes"], r[i - tecnico.RUEDAS_SEMANA])
        self.assertNotIn("rsi_sobre_70", c)

    def test_maximo_del_anio(self):
        base = [100 + (3 if i % 2 else -3) for i in range(400)]
        v = _velas(base + [100.0] * 35 + [110.0, 100.0])
        c = {x["tipo"]: x for x in tecnico.cambios_desde(v, SEMANA)}
        self.assertEqual(c["maximo_12m"]["fecha"], (HOY - timedelta(days=1)).isoformat())
        self.assertEqual(c["maximo_12m"]["cierre"], 110.0)

    def test_adx_pasa_23_con_su_direccion_y_la_regla_de_la_ficha(self):
        # De costado mucho tiempo y esta semana arranca una suba sostenida.
        lateral = [100 + (1 if i % 2 else -1) for i in range(400)]
        v = _velas(lateral + [100 * 1.02 ** k for k in range(1, 13)])
        cam = [x for x in tecnico.cambios_desde(v, SEMANA) if x["tipo"] == "adx23"]
        self.assertEqual(len(cam), 1)
        a = tecnico.adx(v)["adx"]
        i = next(k for k, x in enumerate(v) if x["date"] == cam[0]["fecha"])
        self.assertTrue(a[i - 1] < tecnico.ADX_CLAVE <= a[i], "la regla de cruce_adx: ≥ 23 es arriba")
        self.assertEqual(cam[0]["adx"], a[i])
        self.assertEqual(cam[0]["squeeze"], 1, "marca dirección para arriba")
        # El aviso de la ficha (cruce_adx) dice lo mismo, el mismo día.
        cruce = tecnico.cruce_adx(a, tecnico.squeeze(v)["valor"])
        self.assertEqual(cruce["tipo"], "paso_arriba")
        self.assertEqual(len(v) - 1 - cruce["hace"], i)

    def test_adx_que_baja_de_23_no_es_un_cambio(self):
        lateral = [100 + (1 if i % 2 else -1) for i in range(400)]
        sube = [100 * 1.02 ** k for k in range(1, 30)]
        v = _velas(lateral + sube + [sube[-1] + (1 if i % 2 else -1) for i in range(40)])
        self.assertNotIn("adx23", {x["tipo"] for x in tecnico.cambios_desde(v, SEMANA)})

    def test_orden_mas_nuevo_primero_y_sin_velas(self):
        base = [100 + (1 if i % 2 else -1) for i in range(400)]
        v = _velas(base + [90.0] * 40 + [120.0, 121.0, 135.0])
        cam = tecnico.cambios_desde(v, SEMANA)
        fechas = [c["fecha"] for c in cam]
        self.assertEqual(fechas, sorted(fechas, reverse=True))
        mismo_dia = [c["tipo"] for c in cam if c["fecha"] == fechas[-1]]
        self.assertEqual(mismo_dia, [t for t in tecnico.TIPOS_CAMBIO if t in mismo_dia],
                         "el mismo día, en el orden de importancia")
        self.assertEqual(tecnico.cambios_desde([], SEMANA), [])
        # Con 100 días no hay promedio de 200 ni máximo del año: no se inventa.
        corto = {c["tipo"] for c in tecnico.cambios_desde(_velas([90.0] * 99 + [130.0]), SEMANA)}
        self.assertNotIn("media200", corto)
        self.assertNotIn("maximo_12m", corto)

    def test_adx23_no_es_un_tipo_de_alerta(self):
        self.assertNotIn("adx23", tecnico.SENALES)


if __name__ == "__main__":
    unittest.main()
