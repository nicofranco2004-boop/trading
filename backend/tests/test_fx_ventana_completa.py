"""F5 — /api/fx-rates entrega la serie ENTERA, y `days` recorta por FECHA.

EL BUG
──────
El endpoint cortaba con `ORDER BY date DESC LIMIT ?` pasándole `days`. O sea que
`days=3650` —lo que pedía el front, creyendo pedir diez años— devolvía las últimas
3.650 *ruedas*. La serie tiene ruedas, no días corridos, así que la ventana real
arrancaba en 2016-06-09 teniendo datos desde 2011-01-03: 1.984 días de cotización
que existían en la tabla y no se entregaban.

Toda fecha anterior caía al fallback de `useFxHistory` — el dólar de HOY — y sin
decirlo. Medido sobre la serie real: ×389 en el arranque, ×111 justo en el borde.

POR QUÉ NO ALCANZA CON CAMBIAR `LIMIT` POR `WHERE date >= ?`
────────────────────────────────────────────────────────────
Porque el tope también estaba mal. Filtrando por fecha con el mismo 3650 el corte
queda en 2016-09, o sea la MISMA ventana ciega. El tope tiene que ser más largo
que la serie; si no, el criterio nuevo tapa el mismo agujero.

Corre con: cd backend && python3 -m pytest tests/test_fx_ventana_completa.py
"""
import os
import sys
import tempfile
import unittest
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from fechas import hoy_art_date


# La serie real NO tiene un punto por día corrido: tiene ruedas (sin fines de
# semana). Esa es exactamente la diferencia que el bug confundía, así que el
# fixture la reproduce en vez de sembrar días seguidos — con días seguidos
# "las últimas N filas" y "los últimos N días" coinciden y el test no mide nada.
def _sembrar_ruedas(anios: int = 15):
    """Un punto por día hábil, hacia atrás desde hoy. Devuelve (primera, ultima)."""
    hoy = hoy_art_date()
    filas = []
    d = hoy
    while d > hoy - timedelta(days=int(365.25 * anios)):
        if d.weekday() < 5:                      # 0..4 = lunes a viernes
            filas.append((d.isoformat(), 100.0 + len(filas), None))
        d -= timedelta(days=1)
    c = main.get_db()
    try:
        c.execute("DELETE FROM fx_rates_daily")
        c.executemany(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            filas)
        c.commit()
    finally:
        c.close()
    fechas = sorted(f[0] for f in filas)
    return fechas[0], fechas[-1], len(filas)


class FxVentanaCompletaTest(unittest.TestCase):
    def setUp(self):
        self.primera, self.ultima, self.n_ruedas = _sembrar_ruedas()

    def tearDown(self):
        c = main.get_db()
        c.execute("DELETE FROM fx_rates_daily")
        c.commit()
        c.close()

    def test_el_default_entrega_la_serie_entera(self):
        """Sin parámetros vuelve TODO — incluida la rueda más vieja.

        Contra el código viejo esto falla: con 15 años de ruedas hábiles hay
        ~3.900 filas y el `LIMIT 3650` recortaba las más viejas.
        """
        out = main.get_fx_rates(uid=1)
        self.assertEqual(len(out), self.n_ruedas)
        self.assertEqual(out[0]["date"], self.primera,
                         "la rueda más vieja de la tabla no llegó al frontend")
        self.assertEqual(out[-1]["date"], self.ultima)

    def test_ordenado_de_viejo_a_nuevo(self):
        """El contrato que `useFxHistory` asume para su búsqueda binaria."""
        out = main.get_fx_rates(uid=1)
        fechas = [r["date"] for r in out]
        self.assertEqual(fechas, sorted(fechas))

    def test_days_recorta_por_fecha_y_no_por_filas(self):
        """`days=365` = un año CALENDARIO, no 365 ruedas.

        365 ruedas hábiles se estiran ~511 días corridos: si el corte fuera por
        filas, entrarían fechas de hace más de un año. Esta es la aserción que
        distingue los dos criterios, y la que falla contra el código viejo.
        """
        out = main.get_fx_rates(days=365, uid=1)
        corte = (hoy_art_date() - timedelta(days=365)).isoformat()
        self.assertTrue(out, "un año de ventana no puede volver vacío")
        self.assertGreaterEqual(
            out[0]["date"], corte,
            "entró una fecha más vieja que la ventana pedida: el corte sigue "
            "siendo por cantidad de filas")
        # ~261 ruedas hábiles en un año. Con el corte por filas serían 365.
        self.assertLess(len(out), 300,
                        "volvieron ~365 filas: eso es cortar por filas, no por fecha")

    def test_ventana_corta_no_pierde_el_extremo_nuevo(self):
        """Recortar por fecha recorta lo VIEJO, nunca lo último conocido."""
        out = main.get_fx_rates(days=30, uid=1)
        self.assertEqual(out[-1]["date"], self.ultima)


class FxVentanaGuardTest(unittest.TestCase):
    """Guard contra la re-copia. Lee el CÓDIGO, no el resultado.

    Un test de comportamiento pasa igual aunque mañana alguien reintroduzca el
    `LIMIT` por filas en otra consulta a la misma tabla — y esa copia sería el
    bug de vuelta. Por eso acá se mira el texto.
    """

    def test_el_endpoint_no_corta_por_cantidad_de_filas(self):
        import inspect
        src = inspect.getsource(main.get_fx_rates)
        cuerpo = src.split('"""')[-1]          # sin el docstring, que NOMBRA el bug
        self.assertNotIn("LIMIT", cuerpo.upper(),
                         "/api/fx-rates volvió a cortar por cantidad de filas")
        self.assertIn("WHERE date >= ?", cuerpo,
                      "/api/fx-rates tiene que recortar por FECHA")

    def test_el_tope_es_mas_largo_que_la_serie(self):
        """Un tope más corto que la serie deja el mismo agujero con otro nombre.

        La serie arranca en 2011 (~5.700 días corridos) y crece ~365 por año.
        """
        self.assertGreaterEqual(
            main._FX_DIAS_TODO, 20000,
            "el tope de días quedó del orden de la serie: volvería a ser la "
            "restricción que manda")


if __name__ == "__main__":
    unittest.main()
