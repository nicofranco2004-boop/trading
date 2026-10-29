"""El mapa de calor de tu cartera (Dashboard, pieza 8): lo que le pide al servidor.

El mapa NO valúa: pide POST /api/tecnico/lista sin watchlist (`activos: []`),
el MISMO pedido de Tu lista, y dibuja cada cuadro con el `peso` de `tenencias`
(senales_semana.cartera / peso) más dos cuadros para efectivo y plazos fijos
(`sin_medir`, senales_semana.pesos_sin_medir).

Entra por el camino de producción, como test_tus_senales.py (del que toma la
cartera de prueba): posiciones, efectivo y plazo fijo por HTTP, velas por el
trabajo nocturno real con Yahoo reemplazado en su punto más bajo.

Los casos que importan:
  · el peso de cada cuadro es el de Tu lista (con watchlist) y el de Señales,
    al decimal 12;
  · efectivo y plazos fijos traen su parte, y todo junto suma 1 (toda tu plata)
    — el efectivo HOY no entra: ver test_el_efectivo_cuenta_en_tu_plata;
  · sin efectivo ni plazos fijos, `sin_medir` dice None (el mapa no dibuja esos
    cuadros) y las tenencias solas suman 1.

Corre con: cd backend && python3 -m pytest tests/test_mapa_cartera.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402,F401
from fechas import hoy_art_date  # noqa: E402
import tests.test_tus_senales as ts  # noqa: E402  (módulo, no la clase: pytest no la vuelve a correr)


class MapaCarteraTest(unittest.TestCase):
    setUp = ts.TusSenalesTest.setUp
    tearDown = ts.TusSenalesTest.tearDown
    _velas = ts.TusSenalesTest._velas
    _post = ts.TusSenalesTest._post

    def _mapa(self):
        r = self.client.post("/api/tecnico/lista", json={"activos": []}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_el_peso_del_mapa_es_el_de_tu_lista_y_el_de_senales(self):
        self._velas(hoy_art_date())
        # Plata que no es una tenencia: un plazo fijo.
        self._post("/api/plazos-fijos", {"banco": "Galicia", "capital": 1_000_000, "moneda": "ARS",
                                         "tasa": 0.3, "fecha_inicio": hoy_art_date().isoformat(),
                                         "plazo_dias": 30})
        mapa = self._mapa()
        lista = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "MSFT"}]}, headers=self.h).json()
        del_mapa = {(t["asset"], t["local"]): t["peso"] for t in mapa["tenencias"]}
        de_la_lista = {(t["asset"], t["local"]): t["peso"] for t in lista["tenencias"]}
        self.assertEqual(set(del_mapa), {("NVDA", False), ("KO", False), ("AAPL", False), ("GGAL", True)})
        self.assertEqual(set(del_mapa), set(de_la_lista))
        for k, p in de_la_lista.items():
            self.assertAlmostEqual(del_mapa[k], p, places=12, msg=k)
        senales = self.client.get("/api/tus-senales", headers=self.h).json()["senales"]
        comparados = 0
        for x in senales:
            if x["tenes"]:
                self.assertAlmostEqual(x["peso"], del_mapa[(x["asset"], x["local"])], places=12, msg=x["asset"])
                comparados += 1
        self.assertGreater(comparados, 0, "la prueba tiene que comparar al menos uno")

        sin = mapa["sin_medir"]
        self.assertGreater(sin["plazos_fijos"], 0)
        self.assertEqual(sin, lista["sin_medir"], "el mismo pedido, la misma cuenta")
        self.assertAlmostEqual(sum(del_mapa.values()) + sin["plazos_fijos"], 1.0, places=9,
                               msg="los cuadros del mapa son toda tu plata")
        with main.db_abierta() as conn:
            car = ts.senales_semana.cartera(conn, self.uid)
        self.assertAlmostEqual(sin["plazos_fijos"], car["plazos_fijos"] / car["total"], places=12)

    @unittest.expectedFailure
    def test_el_efectivo_cuenta_en_tu_plata(self):
        # ⚠️ FALLA HOY, a propósito marcada: `senales_semana.cartera` lee las
        # posiciones con `COALESCE(quantity, 0) > 0`, y el efectivo se guarda con
        # quantity 0 (invested = el monto). Queda afuera del total: el peso de Tu
        # lista, Señales, la ficha y este mapa sale más alto para quien tiene
        # efectivo, y el mapa no dibuja su cuadro. Avisado a la sesión que lleva
        # los arreglos de la rama congelada (29/10). Cuando se arregle, esta prueba
        # pasa y pytest la marca roja («unexpected success»): sacar el marcador.
        self._velas(hoy_art_date())
        self._post("/api/cash/flow", {"broker_name": "Schwab", "direction": "deposit", "amount": 500,
                                      "date": "2026-01-10"})
        mapa = self._mapa()
        self.assertIsNotNone(mapa["sin_medir"]["efectivo"])
        self.assertAlmostEqual(sum(t["peso"] for t in mapa["tenencias"]) + mapa["sin_medir"]["efectivo"], 1.0,
                               places=9)

    def test_sin_efectivo_ni_plazos_fijos(self):
        self._velas(hoy_art_date())
        mapa = self._mapa()
        self.assertEqual(mapa["sin_medir"], {"efectivo": None, "plazos_fijos": None})
        self.assertAlmostEqual(sum(t["peso"] for t in mapa["tenencias"]), 1.0, places=9)
        self.assertEqual([t["asset"] for t in mapa["tenencias"]][:2], ["NVDA", "KO"], "de más a menos plata")


if __name__ == "__main__":
    unittest.main()
