"""Lo que devuelve una letra el día que vence (pricing/letras.py).

Una letra no paga cupones: devuelve todo junto al vencer, y CAPITALIZA — por eso
"cantidad × 100" no es el monto del cobro. Acá se prueba la fórmula, y sobre todo
los casos en los que NO hay que estimar: el feed llama "letras" a papeles que no
lo son, y aplicarles la fórmula inventaría plata.

Los datos son los medidos contra la fuente el 2026-09-22 (ver la cabecera de
pricing/letras.py). El "hoy" siempre se pasa a mano: acá no se lee ningún reloj.

Corre con: cd backend && python3 -m pytest tests/test_letras_cashflow.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.maturity import letra_maturity  # noqa: E402
from pricing import letras as L  # noqa: E402

HOY = "2026-09-22"

# Tal cual lo publica ArgentinaDatos (recortado a los campos que se usan).
FEED = {"letras": [
    {"ticker": "S30O6", "precioArs": 132.45, "temPorcentaje": 1.71,
     "fechaVencimiento": "2026-10-30", "monedaCupon": "ARS"},
    {"ticker": "S30S6", "precioArs": 117.00, "temPorcentaje": 1.74,
     "fechaVencimiento": "2026-09-30", "monedaCupon": "ARS"},
    # No decodifica como letra estándar (TO26 no matchea el patrón del ticker).
    {"ticker": "TO26", "precioArs": 106.15, "temPorcentaje": 1.70,
     "fechaVencimiento": "2026-10-19", "monedaCupon": "ARS"},
    # TEM negativa: proyectar con ella daría MENOS plata que el precio de hoy.
    {"ticker": "TTD26", "precioArs": 170.85, "temPorcentaje": -2.10,
     "fechaVencimiento": "2026-12-15", "monedaCupon": "ARS"},
    # Bono con cupones que el feed mete en la misma bolsa: no es cero-cupón.
    {"ticker": "TY30P", "precioArs": 111.25, "temPorcentaje": 2.24,
     "fechaVencimiento": "2030-05-30", "monedaCupon": "ARS"},
]}


class Formula(unittest.TestCase):
    def test_el_pago_es_el_precio_capitalizado_a_la_tasa_del_mercado(self):
        # S30O6 al 2026-09-22: 132,45 por 100, TEM 1,71 %, 38 días al vencimiento.
        self.assertAlmostEqual(L.payout_per_100(132.45, 1.71, 38), 135.33, places=1)

    def test_el_pago_es_mayor_que_el_nominal_porque_capitaliza(self):
        # La trampa que motivó todo esto: mostrar 100 (el nominal) es mostrar
        # ~26 % menos plata de la que el cliente cobra.
        self.assertGreater(L.payout_per_100(132.45, 1.71, 38), 100.0)

    def test_sin_datos_no_hay_numero(self):
        self.assertIsNone(L.payout_per_100(None, 1.71, 38))
        self.assertIsNone(L.payout_per_100(0, 1.71, 38))
        self.assertIsNone(L.payout_per_100(132.45, None, 38))
        self.assertIsNone(L.payout_per_100(132.45, 0, 38))     # tasa nula no es capitalizar
        self.assertIsNone(L.payout_per_100(132.45, -2.1, 38))  # ni negativa
        self.assertIsNone(L.payout_per_100(132.45, 1.71, None))
        self.assertIsNone(L.payout_per_100(132.45, 1.71, -5))

    def test_a_cero_dias_el_pago_es_el_precio(self):
        self.assertAlmostEqual(L.payout_per_100(117.0, 1.74, 0), 117.0, places=4)


class QuienCalifica(unittest.TestCase):
    def setUp(self):
        self.recs = L.parse_letras_feed(FEED)

    def test_el_feed_se_lee_entero(self):
        self.assertEqual(sorted(self.recs), ["S30O6", "S30S6", "TO26", "TTD26", "TY30P"])
        self.assertEqual(self.recs["S30O6"]["maturity"], "2026-10-30")
        self.assertEqual(self.recs["S30O6"]["price_per_100"], 132.45)

    def test_letra_estandar_califica(self):
        cf = L.letra_cashflow(self.recs["S30O6"], letra_maturity("S30O6"), HOY)
        self.assertEqual(cf["maturity"], "2026-10-30")
        self.assertEqual(cf["currency"], "ARS")
        self.assertAlmostEqual(cf["payout_per_100"], 135.33, places=1)
        self.assertEqual(cf["source"], "ArgentinaDatos")

    def test_el_ticker_y_el_feed_tienen_que_decir_lo_mismo(self):
        # TO26 y TY30P no decodifican con la regla del importador → no se estiman.
        # Es lo que deja afuera al bono con cupones sin necesidad de lista negra.
        self.assertIsNone(letra_maturity("TO26"))
        self.assertIsNone(L.letra_cashflow(self.recs["TO26"], letra_maturity("TO26"), HOY))
        self.assertIsNone(L.letra_cashflow(self.recs["TY30P"], letra_maturity("TY30P"), HOY))
        # Y si el símbolo decodifica pero a OTRA fecha que la del feed, tampoco.
        rec = dict(self.recs["S30O6"], maturity="2026-11-30")
        self.assertIsNone(L.letra_cashflow(rec, letra_maturity("S30O6"), HOY))

    def test_tasa_negativa_no_estima(self):
        self.assertIsNone(L.letra_cashflow(self.recs["TTD26"], letra_maturity("TTD26"), HOY))

    def test_una_letra_vencida_no_es_un_cobro_por_venir(self):
        # Mismo corte que el motor de bonos del frontend: estrictamente futuro.
        self.assertIsNone(L.letra_cashflow(self.recs["S30S6"], letra_maturity("S30S6"),
                                           "2026-09-30"))
        self.assertIsNotNone(L.letra_cashflow(self.recs["S30S6"], letra_maturity("S30S6"),
                                              "2026-09-29"))

    def test_el_precio_esta_en_pesos_y_la_tasa_tambien(self):
        # Un papel que pagara en otra moneda tendría su TEM en ESA moneda:
        # mezclarlas sería proyectar pesos con una tasa en dólares.
        rec = dict(self.recs["S30O6"], currency="USD")
        self.assertIsNone(L.letra_cashflow(rec, letra_maturity("S30O6"), HOY))

    def test_el_catalogo_trae_solo_lo_que_se_pide_y_solo_lo_que_califica(self):
        cat = L.letras_catalog(self.recs, ["S30O6", "TO26", "GGAL", "s30o6"],
                               HOY, letra_maturity)
        self.assertEqual(list(cat), ["S30O6"])          # TO26 no califica, GGAL no existe
        self.assertEqual(L.letras_catalog(self.recs, [], HOY, letra_maturity), {})
        self.assertEqual(L.letras_catalog({}, ["S30O6"], HOY, letra_maturity), {})


if __name__ == "__main__":
    unittest.main()
