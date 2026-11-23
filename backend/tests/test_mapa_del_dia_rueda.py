"""«Hoy tus activos · vie 30/10» del Panorama (A4, Nico 31/10): GET
/api/cartera/mapa-del-dia manda `ultima_rueda`, lo que se movieron tus activos
en la ÚLTIMA rueda medida y su FECHA. Un sábado sin cripto no hay rueda de hoy:
antes `cartera` venía None y el renglón desaparecía sin explicación; ahora va la
del viernes, con su fecha y `es_hoy` False (la pantalla no la llama «hoy»).

Pasa por el endpoint de verdad y por `cartera_hoy.armar` (LA cuenta del día);
sólo se reemplaza `_lotes_del_dia`, que sale a buscar precios."""
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main

SABADO, VIERNES, JUEVES = "2026-10-31", "2026-10-30", "2026-10-29"


def lote(asset, valor, previo, rueda, es_hoy, mercado="eeuu"):
    return {"asset": asset, "broker": "Schwab", "valor": valor, "valor_previo": previo, "rueda": rueda,
            "es_hoy": es_hoy, "mercado": mercado, "local": False, "costo": valor}


class TestUltimaRueda(unittest.TestCase):
    def correr(self, hoy, lotes):
        main._MAPA_DEL_DIA_CACHE.clear()
        with patch.object(main, "_lotes_del_dia", return_value=(hoy, lotes, {}, 1000.0)):
            return main.get_mapa_del_dia(uid=987654)

    def test_un_sabado_va_la_rueda_del_viernes_con_su_fecha(self):
        r = self.correr(SABADO, [lote("AAPL", 1010.0, 1000.0, VIERNES, False),
                                 lote("MELI", 995.0, 1000.0, VIERNES, False)])
        self.assertIsNone(r["cartera"], "«Hoy tu cartera» sigue siendo sólo de hoy")
        u = r["ultima_rueda"]
        self.assertEqual(u["rueda"], VIERNES)
        self.assertFalse(u["es_hoy"])
        self.assertEqual(u["usd"], 5.0)
        self.assertEqual(u["pct"], 0.25)

    def test_con_rueda_de_hoy_es_la_misma_que_hoy_tu_cartera(self):
        r = self.correr(VIERNES, [lote("AAPL", 1020.0, 1000.0, VIERNES, True),
                                  lote("GGAL", 990.0, 1000.0, JUEVES, False, "byma")])
        u = r["ultima_rueda"]
        self.assertTrue(u["es_hoy"])
        self.assertEqual(u["rueda"], VIERNES)
        self.assertEqual(u["pct"], r["cartera"]["pct"])
        self.assertEqual(u["usd"], r["cartera"]["usd"])

    def test_sin_nada_medido_no_inventa(self):
        r = self.correr(SABADO, [lote("AL30", 500.0, None, None, False, "byma")])
        self.assertIsNone(r["ultima_rueda"])


class TestDiaConDe(unittest.TestCase):
    """23/11/2026: el globo de un cuadrito sin movimiento de hoy decía «lo último
    es de el viernes 20/11». `dia_txt` abre frases («el viernes…»); detrás de
    «de» va `dia_con_de`, que el servidor manda armado. Por el endpoint de
    verdad, como TestUltimaRueda."""

    def correr(self, hoy, lotes):
        main._MAPA_DEL_DIA_CACHE.clear()
        with patch.object(main, "_lotes_del_dia", return_value=(hoy, lotes, {}, 1000.0)):
            return {a["asset"]: a for a in main.get_mapa_del_dia(uid=987655)["activos"]}

    def test_un_dia_con_nombre_va_con_del(self):
        a = self.correr(SABADO, [lote("GGAL", 990.0, 1000.0, JUEVES, False, "byma"),
                                 lote("AAPL", 1010.0, 1000.0, VIERNES, False)])
        self.assertEqual(a["GGAL"]["dia_txt"], "el jueves 29/10")
        self.assertEqual(a["GGAL"]["dia_con_de"], "del jueves 29/10")
        self.assertEqual(a["AAPL"]["dia_con_de"], "de ayer")

    def test_sin_fecha_confirmada_no_se_pega_a_de(self):
        # Un lote con la fecha de hoy que su mercado no confirma como de hoy.
        a = self.correr(VIERNES, [lote("MELI", 990.0, 1000.0, VIERNES, False)])
        self.assertEqual(a["MELI"]["dia_txt"], "sin fecha confirmada")
        self.assertIsNone(a["MELI"]["dia_con_de"])

    def test_la_regla_de_la_contraccion(self):
        import cartera_hoy
        self.assertEqual(cartera_hoy.dia_con_de("el viernes 20/11"), "del viernes 20/11")
        self.assertEqual(cartera_hoy.dia_con_de("ayer"), "de ayer")
        self.assertEqual(cartera_hoy.dia_con_de("hoy"), "de hoy")
        self.assertIsNone(cartera_hoy.dia_con_de("sin fecha confirmada"))
        self.assertIsNone(cartera_hoy.dia_con_de(None))

    def test_la_frase_para_la_ia_usa_la_misma_regla(self):
        """`_estado_mercado` tenía la contracción escrita a mano; ahora usa la
        misma función. Un sábado, «lo último es la rueda del jueves 29/10»."""
        from datetime import datetime, timezone
        sabado_mediodia = datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc)
        t = main._estado_mercado("byma", JUEVES, SABADO, ahora=sabado_mediodia)
        self.assertIn("lo último es la rueda del jueves 29/10", t)
        self.assertNotIn("de el", t)


if __name__ == "__main__":
    unittest.main()
