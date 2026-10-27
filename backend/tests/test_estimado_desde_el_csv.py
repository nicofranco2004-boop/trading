"""El rendimiento ESTIMADO desde el CSV (auditoría 2026-10-27, fase B — H6).

Decisión del dueño: el Estimado es "precio real donde lo hay, costo donde no". Lo que
tuvo precio histórico se valúa a mercado; lo que no (un bono sin velas en data912, un
FCI) queda al costo, y la pantalla dice qué parte quedó a precio real en vez de "no
cuenta lo que todavía no vendiste".

El caso: la historia base de la auditoría por el camino real (subida HTTP de Balanz,
foto de tenencia, cron día por día), con el GD38 con precio vivo pero SIN historia en
data912. La reconstrucción no llega al 90 % de cobertura mientras lo tiene (base
'parcial', no apta), y el Certero —con el hueco en el medio— no publica (decisión 2,
`twr.py` no se toca ahí).

Lo que estaba roto, medido en este caso con el código anterior al fix:
  · el Estimado publicaba sólo desde el cron (2026-08-04): el silencio de la cadena
    CERTERA cortaba la serie aunque el estimado tuviera un punto por mes;
  · y con la serie entera, el ancla por base medía el leg mercado(2024-02-13) →
    mercado(2026-08-04) POR ENCIMA de los 30 meses parciales, que también encadenaban:
    el mismo período contado dos veces.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import twr  # noqa: E402
from tests.rendimiento_csv.camino import Camino  # noqa: E402
from mercado import Mercado  # noqa: E402
from historia import historia_base  # noqa: E402
import generadores as g  # noqa: E402

FOTO = "2026-08-03"
HOY = date.today().isoformat()


class ElBonoSinPrecioHistorico(unittest.TestCase):

    def cuenta(self):
        m = Mercado()
        h = historia_base(m)
        h.simular()
        c = Camino(self, m)
        c.usuario(f"estimado-parcial-{id(self)}@rendi.test")
        c.sin_historia = {"GD38"}
        c.subir("mov.xlsx", g.balanz_mov(h), "Balanz", "balanz_movimientos")
        c.subir_foto("ResumenDeCuenta.pdf", g.balanz_foto(h, FOTO), "Balanz",
                     "balanz_tenencia")
        c.cron(date.fromisoformat(FOTO) + timedelta(days=1), date.today())
        c.reconstruir()
        return c, h

    def test_la_reconstruccion_parcial_queda_en_su_base(self):
        c, _ = self.cuenta()
        filas = c.q("SELECT date, base, apto, mtm_coverage FROM snapshots WHERE user_id=? "
                    "AND source='mtm_backfill' AND date >= '2024-03-01'", c.uid)
        self.assertTrue(filas)
        # Con el bono al costo ningún mes llega al 90 %: base 'parcial', no apta.
        self.assertEqual({(r["base"], r["apto"]) for r in filas}, {(twr.VALUADO_PARCIAL, 0)})
        self.assertTrue(all(0 < r["mtm_coverage"] < twr.COBERTURA_MEDICION for r in filas))

    def test_el_estimado_da_la_historia_entera_sin_contar_dos_veces(self):
        c, h = self.cuenta()
        cer = c.curva("certero")
        # El Certero no cruza el hueco: no publica, o publica sólo desde el cron.
        self.assertTrue(cer["twr"] is None or cer["ventana_desde"] > FOTO)

        cv = c.curva("estimado")
        self.assertIsNotNone(cv["twr"], cv.get("motivo"))
        self.assertEqual(cv["ventana_desde"], "2024-01-31")
        legs = [leg for t in cv["tramos_detalle"] for leg in t["legs_est_detalle"]]
        # Ningún leg une dos reglas…
        self.assertEqual([leg for leg in legs if leg["base_desde"] != leg["base_hasta"]], [])
        # …ni pasa por encima de otro: cada día de la ventana se cuenta una vez.
        legs.sort(key=lambda leg: leg["desde"])
        for a, b in zip(legs, legs[1:]):
            self.assertLessEqual(a["hasta"], b["desde"], (a, b))
        # El número es la historia con el bono al costo: por debajo de la verdad,
        # que sí lleva la suba del bono, y por encima de no haber ganado nada.
        verdad = h.twr_verdad(cv["ventana_desde"], HOY)
        self.assertLess(cv["twr"] * 100, verdad)
        self.assertGreater(cv["twr"], 0.0)

    def test_la_pantalla_dice_cuanto_quedo_a_precio_real(self):
        c, _ = self.cuenta()
        r = c.http.get("/api/insights/performance", headers=c.h,
                       params={"modo": "estimado"})
        self.assertEqual(r.status_code, 200, r.text)
        perf = r.json()
        self.assertEqual(perf["base_del_twr"], "contable")
        self.assertIsNotNone(perf["twr"])
        # Es una reconstrucción a mercado donde hubo precio: NO "no cuenta lo que
        # todavía no vendiste" (eso es de la contabilidad pura).
        self.assertFalse(perf["excluye_no_realizado"])
        # Ponderado por tiempo: dos años y medio con el bono al costo pesan más que
        # los dos meses y pico del cron. Promediado por punto daba ~0,90.
        self.assertGreater(perf["cobertura_estimado"], 0.5)
        self.assertLess(perf["cobertura_estimado"], 0.85)
        # El estimado nunca publica drawdown ni pico.
        self.assertIsNone(perf.get("drawdown_maximo"))


if __name__ == "__main__":
    unittest.main()
