"""El dólar POR FECHA es el punto MEDIO, igual que el vivo.

EL BUG
──────
`fx_rates_daily` guardaba UNA sola punta —la de venta— mientras la valuación viva
usa el punto medio `(compra+venta)/2` desde agosto de 2026 (`_val_rate`), porque
es el que muestran los brokers. Venía de un usuario real: veía US$ 6.884 donde
Cocos le mostraba US$ 6.933 — los mismos 10,53 M de pesos divididos por 1.529,71
(la punta cara) en vez de por 1.518,43.

Esas dos bases distintas son la "pérdida fantasma" que `ledger_replay` documenta
en su límite 2 y que parcheaba estampando `fx_basis` y marcando los tramos: un
borde reconstruido a la venta y otro medido al medio difieren por el spread
(~0,7 %) y encadenarlos fabrica retorno de la nada.

MEDIDO sobre la fuente (2026-09-11): las dos series traen la punta compradora en
el 100 % de sus filas — blue 5.731 desde 2011-01-03, bolsa 2.875 desde
2018-10-29. El medio está 0,65 % por debajo de la venta en el blue y entre 0,13 %
y 0,48 % en el MEP.

⚠️ EL DEPLOY SOLO NO CAMBIA NINGÚN NÚMERO. Sin `blue_compra`/`mep_compra`
pobladas, el COALESCE deja medio = venta. El backfill ES el cambio.

Corre con: cd backend && python3 -m pytest tests/test_dolar_medio_historico.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
import fx
import twr


VENTA, COMPRA = 1400.0, 1300.0      # medio = 1350. Spread ancho: con uno real
MEDIO = 1350.0                      # (~0,7 %) el test no distinguiría las ramas.
FECHA = "2026-04-15"


def _sembrar(compra_mep=None, compra_blue=None):
    """⚠️ SÓLO LA FECHA DE ESTE ARCHIVO. `fx_rates_daily` es GLOBAL —no lleva
    user_id— y toda la suite comparte UNA base (`main.DB_PATH` se resuelve en el
    primer import de main, así que el DB_PATH del primer módulo gana). Un
    `DELETE FROM fx_rates_daily` acá borra las cotizaciones que sembró
    `test_advisor_plan` y lo pone en rojo — pasó, y pasaba sólo en la suite
    completa: aislado, este archivo daba verde."""
    c = main.get_db()
    try:
        c.execute("DELETE FROM fx_rates_daily WHERE date = ?", (FECHA,))
        c.execute("INSERT INTO fx_rates_daily "
                  "(date, blue_venta, mep_venta, blue_compra, mep_compra) "
                  "VALUES (?,?,?,?,?)",
                  (FECHA, VENTA, VENTA, compra_blue, compra_mep))
        c.commit()
    finally:
        c.close()


class ElDolarPorFechaEsElMedioTest(unittest.TestCase):

    def tearDown(self):
        c = main.get_db()
        c.execute("DELETE FROM fx_rates_daily WHERE date = ?", (FECHA,))
        c.commit()
        c.close()

    def test_fx_for_date_devuelve_el_medio(self):
        """El riel canónico del costo y del P&L. Contra el código viejo: 1400."""
        _sembrar(compra_mep=COMPRA, compra_blue=COMPRA)
        c = main.get_db()
        try:
            self.assertAlmostEqual(fx.fx_for_date(c, FECHA), MEDIO, places=4)
            self.assertNotAlmostEqual(fx.fx_for_date(c, FECHA), VENTA, places=2)
            self.assertAlmostEqual(
                fx.fx_for_date(c, FECHA, riel=fx.RIEL_BLUE), MEDIO, places=4)
        finally:
            c.close()

    def test_sin_punta_compradora_cae_a_la_venta(self):
        """El COALESCE. Es lo que hace que el deploy no mueva nada hasta el
        backfill — y la red permanente para las fechas que la fuente no cubra."""
        _sembrar(compra_mep=None, compra_blue=None)
        c = main.get_db()
        try:
            self.assertAlmostEqual(fx.fx_for_date(c, FECHA), VENTA, places=4)
        finally:
            c.close()

    def test_una_compra_en_CERO_no_arrastra_el_medio_a_la_mitad(self):
        """`0` es "no hay dato", no "el dólar vale cero". Sin esto el medio de una
        fila con compra=0 sería venta/2: un error del 50 %, no del 0,7 %."""
        _sembrar(compra_mep=0, compra_blue=0)
        c = main.get_db()
        try:
            self.assertAlmostEqual(fx.fx_for_date(c, FECHA), VENTA, places=4)
        finally:
            c.close()

    def test_una_compra_podrida_NO_se_usa(self):
        """LA FUENTE TIENE DATO MALO, y usarlo es peor que no arreglar nada.

        Medido el 2026-09-11 sobre argentinadatos:
          · 2025-05-02 (bolsa): compra 751,67 contra venta 1.363,60 = 45 % de
            spread. El MEP nunca tuvo eso; su medio mueve el dólar −22,4 %.
          · 73 días con la compra POR ENCIMA de la venta (70 blue, 3 bolsa).

        Descartar deja la punta de venta, que es el valor que ya se usaba: el
        statu quo. Por eso ante la duda NO se usa.
        """
        c = main.get_db()
        try:
            for compra, esperado, motivo in (
                (VENTA * 0.50, VENTA, "spread del 50 %: dato podrido"),
                (VENTA * 0.89, VENTA, "spread del 11 %: por encima del tope"),
                (VENTA * 1.10, VENTA, "compra POR ENCIMA de la venta"),
                (VENTA, VENTA, "compra == venta: el medio es la venta igual"),
                (VENTA * 0.92, VENTA * 0.96, "spread del 8 %: legítimo, se usa"),
            ):
                _sembrar(compra_mep=compra, compra_blue=compra)
                self.assertAlmostEqual(fx.fx_for_date(c, FECHA), esperado, places=4,
                                       msg=motivo)
        finally:
            c.close()

    def test_serie_fx_devuelve_el_medio(self):
        """La curva en pesos y `_pct_en_pesos` pasan por acá."""
        _sembrar(compra_mep=COMPRA, compra_blue=COMPRA)
        c = main.get_db()
        try:
            fn, riel = twr.serie_fx(c, None, FECHA)
            self.assertAlmostEqual(fn(FECHA), MEDIO, places=4)
            self.assertEqual(riel, "mep")
        finally:
            c.close()

    def test_el_endpoint_devuelve_el_medio(self):
        """`/api/fx-rates` alimenta toda la conversión histórica del frontend."""
        _sembrar(compra_mep=COMPRA, compra_blue=COMPRA)
        out = [r for r in main.get_fx_rates(uid=1) if r["date"] == FECHA]
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["blue"], MEDIO, places=4)
        self.assertAlmostEqual(out[0]["mep"], MEDIO, places=4)

    def test_el_escritor_guarda_las_dos_puntas(self):
        c = main.get_db()
        c.execute("DELETE FROM fx_rates_daily WHERE date = ?", (FECHA,))
        c.commit()
        c.close()
        main._persist_blue_for_date(FECHA, VENTA, source="dolarapi", mep=VENTA,
                                    blue_compra=COMPRA, mep_compra=COMPRA)
        c = main.get_db()
        try:
            r = c.execute("SELECT blue_compra, mep_compra FROM fx_rates_daily "
                          "WHERE date=?", (FECHA,)).fetchone()
            self.assertAlmostEqual(r["blue_compra"], COMPRA, places=4)
            self.assertAlmostEqual(r["mep_compra"], COMPRA, places=4)
            # Y un upsert SIN compra no la pisa (COALESCE), igual que el MEP.
            main._persist_blue_for_date(FECHA, VENTA, source="cron")
            r2 = c.execute("SELECT blue_compra FROM fx_rates_daily WHERE date=?",
                           (FECHA,)).fetchone()
            self.assertAlmostEqual(r2["blue_compra"], COMPRA, places=4)
        finally:
            c.close()


class UnaSolaCuentaGuardTest(unittest.TestCase):
    """Guards que leen CÓDIGO. Los lectores de `fx_rates_daily` son SIETE: si
    cada uno escribe su propio `(compra+venta)/2`, en el próximo cambio quedan
    seis actualizados y uno no — que es exactamente la forma de bug que esta
    tanda viene cerrando."""

    # `scripts/backfill_historical_mtm.py` ESTÁ en la lista: no es un script
    # suelto, lo llaman dos endpoints de main.py (16897 y 31955) y escribe
    # `capital_final` a mercado. Se me escapó del primer censo justo por llamarse
    # "scripts/".
    LECTORES = ("fx.py", "twr.py", "main.py", "ledger_replay.py", "advisor_brief.py",
                "scripts/backfill_historical_mtm.py")

    @staticmethod
    def _fuente(rel):
        with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
            return f.read()

    def test_la_expresion_existe_una_sola_vez(self):
        # Booleano y no `assertIn`: sobre un archivo de 300 líneas el mensaje de
        # fallo de `assertIn` pega el archivo entero en la salida.
        src = self._fuente("fx.py")
        self.assertEqual(src.count("def _sql_medio("), 1,
                         "la cuenta del medio dejó de vivir en un solo lugar")
        self.assertEqual(src.count('SQL_MEDIO_MEP = _sql_medio('), 1)
        self.assertEqual(src.count('SQL_MEDIO_BLUE = _sql_medio('), 1)
        # Las dos salen de la MISMA función, sólo cambian las columnas.
        self.assertEqual(
            fx.SQL_MEDIO_MEP.replace("mep_", "X_"),
            fx.SQL_MEDIO_BLUE.replace("blue_", "X_"),
            "los dos rieles se calculan distinto")
        # Y el filtro de cordura sigue adentro (no es decorativo: sin él, el
        # 2025-05-02 del MEP mueve el dólar de esa fecha −22,4 %).
        self.assertIn(str(fx.SPREAD_MAX), fx.SQL_MEDIO_MEP)
        self.assertIn("CASE WHEN", fx.SQL_MEDIO_MEP)

    def test_la_version_de_SQL_y_la_de_PYTHON_dan_lo_mismo(self):
        """La regla vive en dos medios porque hay dos caminos: los lectores de la
        tabla arman consultas, y `_fetch_dolar_blue_monthly` recibe el JSON de la
        fuente sin tocar la tabla. Mismo patrón que `fechas.py` ↔ `fecha.js`: dos
        implementaciones y un test que las ata.

        Sin esto, el día podrido del 45 % entraba por la puerta de Python —la
        única sin guardia— mientras la de SQL lo rechazaba.
        """
        import sqlite3
        casos = [(1300, 1400), (None, 1400), (0, 1400), (751.67, 1363.6),
                 (1500, 1400), (1288, 1400), (1400, 1400), (-5, 1400),
                 (1399.99, 1400), (1260, 1400)]
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE t (mep_compra REAL, mep_venta REAL)")
        c.executemany("INSERT INTO t VALUES (?,?)", casos)
        en_sql = [r[0] for r in c.execute(f"SELECT {fx.SQL_MEDIO_MEP} FROM t")]
        for (compra, venta), sql in zip(casos, en_sql):
            self.assertAlmostEqual(
                fx.punta_media(compra, venta), sql, places=9,
                msg=f"SQL y Python se separaron en compra={compra} venta={venta}")

    def test_nadie_re_escribe_la_cuenta(self):
        """Nadie arma el promedio a mano en una consulta propia."""
        for rel in self.LECTORES:
            src = self._fuente(rel)
            cuerpo = src.replace(
                "COALESCE((NULLIF(mep_compra, 0) + mep_venta) / 2.0, mep_venta)", "")
            cuerpo = cuerpo.replace(
                "COALESCE((NULLIF(blue_compra, 0) + blue_venta) / 2.0, blue_venta)", "")
            for copia in ("mep_compra + mep_venta", "blue_compra + blue_venta",
                          "mep_venta + mep_compra", "blue_venta + blue_compra",
                          "NULLIF(mep_compra", "NULLIF(blue_compra"):
                self.assertTrue(copia not in cuerpo,
                                f"{rel} escribió su propia copia del punto medio")

    def test_ningun_lector_quedo_pidiendo_la_punta_de_venta_pelada(self):
        """El censo del que salió este cambio, congelado.

        Se permite nombrar `mep_venta`/`blue_venta` en un WHERE (el criterio de
        cobertura mira la columna cruda) y en los INSERT/UPDATE. Lo que no puede
        volver es un SELECT que las entregue como si fueran el dólar.
        """
        import re
        for rel in self.LECTORES:
            for linea in self._fuente(rel).splitlines():
                s = linea.strip()
                if not s.upper().startswith(('"SELECT', "F\"SELECT", 'SELECT',
                                             '"""SELECT', 'F"""SELECT')):
                    continue
                if "fx_rates_daily" not in self._fuente(rel):
                    continue
                self.assertIsNone(
                    re.search(r'SELECT\s+(date,\s*)?(mep_venta|blue_venta)\s+FROM\s+fx_rates_daily', s),
                    f"{rel} volvió a entregar la punta de venta como el dólar: {s!r}")


if __name__ == "__main__":
    unittest.main()
