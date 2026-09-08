"""La baseline que el usuario declara a mano sobrevive al recalc.

CONTEXTO. En `/mensual` el usuario puede declarar `capital_inicio`: cuánto ya
tenía antes de empezar a usar Rendi (`MonthlyIn.capital_inicio`, POST/PUT
`/api/monthly`). Ese número **no se deriva de ninguna fuente** — no está en
`operations`, no está en los imports, no se puede recomputar con nada.

EL BUG (auditoría 1A, hallazgo A-4). `_recalc_pnl_realized_from_ops` terminaba
forzando `capital_inicio = 0` en la primera fila de cada broker tocado, y
`brokers_touched` incluye `'global'` incondicionalmente. O sea que el dato tipeado
se borraba, sin deshacer, la primera vez que el usuario importaba un CSV, revertía
uno, borraba un broker o cerraba un futuro. Su "Capital aportado" caía de golpe y
su rendimiento saltaba en la proporción inversa.

El reset sólo podía hacer daño: cuando la baseline ya es 0 es un no-op, así que la
única vez que hacía algo era cuando había un valor declarado.

⚠️ Estos tests van por el camino REAL (`/api/imports/preview` + `/confirm`), que es
el que corre el recalc. Un test que llamara al persister directo no lo atravesaría
y certificaría en verde lo contrario de lo que pasa en producción — ya ocurrió en
este repo con `test_fx_capital.py`.

Corre con: cd backend && python3 -m pytest tests/test_capital_inicio_baseline.py
"""
import io
import unittest

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class CapitalInicioBaselineTest(unittest.TestCase):
    BROKER = "TestBase"
    BASELINE = 50_000.0
    ANIO, MES = 2020, 1          # el mes más viejo: el que el reset atacaba

    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "brokers", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('base@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'USDT')",
                     (self.uid, self.BROKER))
        # La baseline declarada a mano, en el broker y en 'global'. Lleva un
        # movimiento manual para no caer en el DELETE de filas todo-en-cero.
        for b in (self.BROKER, "global"):
            conn.execute(
                """INSERT INTO monthly_entries
                   (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                    pnl_unrealized,capital_inicio,capital_final,
                    manual_deposits,manual_withdrawals)
                   VALUES (?,?,?,?,1000,0,0,0,?,?,1000,0)""",
                (self.uid, self.ANIO, self.MES, b,
                 self.BASELINE, self.BASELINE + 1000))
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _importar(self, csv):
        """El camino real: preview + confirm por HTTP. El confirm corre el
        persister Y `_recalc_pnl_realized_from_ops`, que es donde vivía el reset."""
        r = self.client.post(
            "/api/imports/preview", headers=self.hdr,
            files=[("files", ("x.csv", io.BytesIO(csv.encode("utf-8")), "text/csv"))],
            data={"format": "rendi_generic", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", headers=self.hdr,
                             json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _baseline(self, broker):
        conn = main.get_db()
        row = conn.execute(
            """SELECT capital_inicio FROM monthly_entries
                WHERE user_id=? AND broker=? ORDER BY year, month LIMIT 1""",
            (self.uid, broker)).fetchone()
        conn.close()
        return float(row["capital_inicio"]) if row else None

    def test_el_import_no_borra_la_baseline_del_broker(self):
        """REGRESIÓN A-4: era el disparador más común."""
        self._importar(HDR + "2022-05-10,DEPOSITO,TestBase,,,,500,500,,,USD,dep\n")
        self.assertAlmostEqual(self._baseline(self.BROKER), self.BASELINE, places=2)

    def test_el_import_no_borra_la_baseline_global(self):
        """`brokers_touched.add()` es incondicional, así que 'global' también
        entraba al reset — y es el que ve el usuario en el Dashboard."""
        self._importar(HDR + "2022-05-10,DEPOSITO,TestBase,,,,500,500,,,USD,dep\n")
        self.assertAlmostEqual(self._baseline("global"), self.BASELINE, places=2)

    def test_sigue_sobreviviendo_a_un_segundo_import(self):
        """El reset se disparaba en CADA recalc, no sólo en el primero."""
        self._importar(HDR + "2022-05-10,DEPOSITO,TestBase,,,,500,500,,,USD,dep\n")
        self._importar(HDR + "2022-06-10,DEPOSITO,TestBase,,,,700,700,,,USD,dep2\n")
        self.assertAlmostEqual(self._baseline(self.BROKER), self.BASELINE, places=2)
        self.assertAlmostEqual(self._baseline("global"), self.BASELINE, places=2)

    def test_una_baseline_en_cero_sigue_en_cero(self):
        """El fix no inventa nada donde no había: sin baseline declarada, la
        primera fila sigue arrancando en 0."""
        conn = main.get_db()
        conn.execute("UPDATE monthly_entries SET capital_inicio=0, capital_final=1000 "
                     "WHERE user_id=?", (self.uid,))
        conn.commit()
        conn.close()
        self._importar(HDR + "2022-05-10,DEPOSITO,TestBase,,,,500,500,,,USD,dep\n")
        self.assertAlmostEqual(self._baseline(self.BROKER), 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
