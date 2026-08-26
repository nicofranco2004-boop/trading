"""Topics de IA del libro del asesor — book.composition_type / _sector.

Los primeros topics del registry que NO miran una cuenta sino el conjunto de
las carteras administradas.

Lo que estos tests protegen:

1. QUE NO COLISIONEN CON `distribution`. `book.distribution` ya existe del
   lado asesor y significa otra cosa: la distribución de PERFORMANCE (cuántos
   clientes en verde y cuántos en rojo, la card "¿Cómo vienen tus clientes?").
   El prompt del libro ya se la describe al modelo con ese sentido.
2. QUE EL PACKET DIGA QUE ES UN LIBRO. Si el modelo lo lee como la cartera de
   una persona, escribe en segunda persona sobre plata que no es del que lee.
3. `mas_difundidos`. Es lo que distingue una postura del asesor (un activo en
   muchas carteras) de una cartera grande dominando el promedio ponderado
   (una sola). Son dos conversaciones distintas con el cliente.
4. QUE EL SANEO SIGA SIENDO EL DEL RETAIL — se reusa builders.distribution, no
   se reimplementa.

Corre con: cd backend && python3 -m pytest tests/test_ai_book_composition.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from ai.registry import get_topic, list_topics   # noqa: E402


def _params(**over):
    p = {
        "total_usd": 1000,
        "unclassified_pct": 0.0,
        "clientes": 12,
        "slices": [
            {"label": "CEDEARs", "value_usd": 600, "weight_pct": 60.0,
             "pnl_usd": 50, "pnl_pct": 9.1,
             "assets": [{"a": "AAPL", "w": 30.0, "p": 12.0}]},
            {"label": "Efectivo", "value_usd": 400, "weight_pct": 40.0},
        ],
        "mas_difundidos": [{"a": "AAPL", "c": 9}, {"a": "GGAL", "c": 7}],
    }
    p.update(over)
    return p


class RegistryTest(unittest.TestCase):
    def test_los_dos_topics_estan_registrados(self):
        for t in ("book.composition_type", "book.composition_sector"):
            self.assertIsNotNone(get_topic(t), f"falta el topic {t}")
            self.assertIn(t, list_topics())

    def test_NO_pisan_los_topics_de_distribution_del_retail(self):
        # portfolio.distribution_* es la torta de UNA cartera y sigue viva.
        for t in ("portfolio.distribution_type", "portfolio.distribution_sector"):
            self.assertIsNotNone(get_topic(t))
        self.assertIsNot(get_topic("book.composition_type"),
                         get_topic("portfolio.distribution_type"))

    def test_no_existe_un_topic_book_distribution(self):
        # `book.distribution` es la distribución de PERFORMANCE del libro
        # (verde/rojo). Registrar un topic con ese nombre para la composición
        # haría que dos cosas distintas compartan palabra.
        for t in ("book.distribution", "book.distribution_type",
                  "book.distribution_sector"):
            self.assertIsNone(get_topic(t), f"{t} colisiona con la card de performance")


class PacketTest(unittest.TestCase):
    def _pkt(self, topic, **over):
        build, _ = get_topic(topic)
        return build(None, 1, **_params(**over))

    def test_el_packet_se_identifica_como_libro_no_como_cartera(self):
        pkt = self._pkt("book.composition_type")
        self.assertEqual(pkt["screen"], "book.composition_type")
        self.assertIn("libro", pkt["objeto"])
        self.assertEqual(pkt["clientes"], 12)

    def test_el_eje_lo_fija_el_topic_no_el_cliente(self):
        self.assertEqual(self._pkt("book.composition_type")["eje"], "tipo de activo")
        self.assertEqual(self._pkt("book.composition_sector")["eje"], "sector económico")

    def test_mas_difundidos_llega_normalizado(self):
        pkt = self._pkt("book.composition_type")
        self.assertEqual(pkt["mas_difundidos"],
                         [{"ticker": "AAPL", "clientes": 9}, {"ticker": "GGAL", "clientes": 7}])

    def test_un_activo_de_un_solo_cliente_no_es_difundido(self):
        pkt = self._pkt("book.composition_type",
                        mas_difundidos=[{"a": "SOLO", "c": 1}, {"a": "AAPL", "c": 5}])
        self.assertEqual([d["ticker"] for d in pkt["mas_difundidos"]], ["AAPL"])

    def test_sin_contexto_de_libro_no_inventa_las_claves(self):
        build, _ = get_topic("book.composition_type")
        pkt = build(None, 1, total_usd=1000, slices=[
            {"label": "CEDEARs", "value_usd": 1000, "weight_pct": 100.0}])
        self.assertNotIn("clientes", pkt)
        self.assertNotIn("mas_difundidos", pkt)
        self.assertIn("objeto", pkt)   # esto sí es constante del topic

    def test_reusa_la_lectura_del_retail(self):
        # Rankings, concentración y "sin rendimiento medible" salen del mismo
        # motor que la torta del cliente: no se reimplementan.
        pkt = self._pkt("book.composition_type")
        self.assertEqual(pkt["concentracion"]["top1_pct"], 60.0)
        self.assertEqual(pkt["sin_rendimiento_medible_pct"], 40.0)   # Efectivo
        self.assertEqual([m["nombre"] for m in pkt["mejores"]], ["CEDEARs"])

    def test_aguanta_basura_sin_reventar(self):
        build, _ = get_topic("book.composition_sector")
        pkt = build(None, 1, slices="no soy una lista", clientes="doce",
                    mas_difundidos=[{"nope": 1}, "tampoco", None])
        self.assertEqual(pkt["porciones"], [])
        self.assertNotIn("mas_difundidos", pkt)
        self.assertNotIn("clientes", pkt)


class PromptTest(unittest.TestCase):
    def test_el_tier_advisor_recibe_prompt_pro_no_descriptivo(self):
        for t in ("book.composition_type", "book.composition_sector"):
            _, render = get_topic(t)
            p = render("advisor")
            self.assertGreater(len(p), 2000)
            # El marcador de la rama descriptiva (free/plus) no tiene que estar.
            self.assertNotIn("Describí lo que ves sin explicar por qué", p)

    def test_el_prompt_encuadra_el_objeto_como_libro_ajeno(self):
        _, render = get_topic("book.composition_type")
        p = render("advisor")
        self.assertIn("LIBRO", p)
        self.assertIn("clientes", p)
        # La regla que evita el error de registro: no hablarle al asesor como
        # si la plata fuera suya.
        self.assertIn("segunda persona", p)

    def test_el_prompt_prohibe_prescribir_la_cartera(self):
        for t in ("book.composition_type", "book.composition_sector"):
            _, render = get_topic(t)
            p = render("advisor")
            self.assertIn("rebalance", p.lower())

    def test_sector_aclara_que_renta_fija_y_cash_no_son_sectores(self):
        _, render = get_topic("book.composition_sector")
        self.assertIn("NO son sectores económicos", render("advisor"))


if __name__ == "__main__":
    unittest.main()
