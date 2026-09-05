"""Capital aportado de las CONVERSIONES de moneda, por el camino REAL de la app.

⚠️ ESTE ARCHIVO YA CERTIFICÓ EN VERDE LO CONTRARIO DE LO QUE PASABA EN PRODUCCIÓN.
La versión anterior llamaba `persist_batch` directo y por eso nunca llegaba a
`_recalc_pnl_realized_from_ops`, que es quien tiene la última palabra sobre
`monthly_entries.deposits/withdrawals` y corre en el confirm justo después del
persister. El "FIX bug #1" que este test daba por bueno nunca funcionó un solo
día: el recalc lo pisaba con cero. Por eso ahora TODO pasa por el endpoint HTTP
(`/api/imports/preview` + `/api/imports/confirm`) — si el test no atraviesa el
recalc, no está mirando lo que ve el usuario.

El modelo que se testea: una conversión es una TRANSFERENCIA INTERNA NETA CERO.
No es plata que entra ni sale de Rendi, así que el capital aportado GLOBAL no se
mueve; lo que se corrige es a QUÉ BROKER está atribuida. El monto que se mueve es
el mismo que movió el efectivo, así que `valor − aportado` queda invariante por
broker: la atribución no puede inventar ni ganancias ni pérdidas.

Corre con: cd backend && python3 -m pytest tests/test_fx_capital.py
"""
import io
import unittest

import main
from fastapi.testclient import TestClient

HDR = ("fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,"
       "comisiones,moneda,notas\n")


class FxCapitalTest(unittest.TestCase):
    BROKER = "TestMEP"
    SIB = "TestMEP · USD"

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
            "VALUES ('fx@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                     (self.uid, self.BROKER))
        conn.commit()
        conn.close()
        self.token = main.create_token(self.uid)
        self.client = TestClient(main.app)

    def _import(self, csv):
        """El camino real: preview + confirm por HTTP. El confirm corre el
        persister Y el recalc, que es donde el bug vivía."""
        h = {"Authorization": f"Bearer {self.token}"}
        r = self.client.post(
            "/api/imports/preview", headers=h,
            files=[("files", ("fx.csv", io.BytesIO(csv.encode("utf-8")), "text/csv"))],
            data={"format": "rendi_generic", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        sid = r.json()["session_id"]
        r = self.client.post("/api/imports/confirm", headers=h,
                             json={"session_id": sid})
        self.assertEqual(r.status_code, 200, r.text)
        return main.get_db()

    def _cap(self, conn, broker):
        """Capital aportado de un broker = deposits − withdrawals."""
        r = conn.execute(
            "SELECT COALESCE(SUM(deposits),0) d, COALESCE(SUM(withdrawals),0) w "
            "FROM monthly_entries WHERE user_id=? AND broker=?",
            (self.uid, broker)).fetchone()
        return float(r["d"] or 0) - float(r["w"] or 0)

    def test_conversion_ars_usd_atribuye_al_sibling(self):
        """1M ARS (706,71 al blue 1415) → 1000 USD al MEP.

        REGRESIÓN: sin el fix el sibling USD quedaba en CERO —su fila ni siquiera
        sobrevivía a la GC del recalc— mientras tenía 1000 USD adentro, y el padre
        se quedaba con todo el capital de una plata que ya no tenía."""
        conn = self._import(
            HDR +
            "2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n"
            "2022-01-11,CONVERSION_ARS_USD,TestMEP,,,,1000000,1000,1000,,,MEP\n")
        # El sibling recibe los 1000 USD que efectivamente entraron.
        self.assertAlmostEqual(self._cap(conn, self.SIB), 1000.0, places=1)
        # El padre entrega esos mismos 1000: le queda lo que aportó (706,71)
        # menos lo que mandó. Negativo y CORRECTO — mandó más de lo que recibió,
        # y su VALOR también bajó 1000, así que (valor − aportado) no se movió.
        self.assertAlmostEqual(self._cap(conn, self.BROKER), 706.71 - 1000, places=1)
        # Lo global NO se mueve: una conversión no es un aporte.
        self.assertAlmostEqual(self._cap(conn, "global"), 706.71, places=1)
        # Y el cash vivo sigue exacto.
        cash = {r["broker"]: r["invested"] for r in conn.execute(
            "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1",
            (self.uid,))}
        self.assertAlmostEqual(cash.get(self.BROKER, 0), 0, places=1)
        self.assertAlmostEqual(cash.get(self.SIB, 0), 1000, places=1)
        conn.close()

    def test_conversion_usd_ars_tambien_se_atribuye(self):
        """La vuelta USD→ARS. `_persist_fx` NUNCA escribió flujos en este sentido
        —ni siquiera uno que el recalc pudiera pisar—, así que estos 400 USD no
        los acreditaba nadie. Son US$217.932 en producción."""
        conn = self._import(
            HDR +
            "2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n"
            "2022-01-11,CONVERSION_ARS_USD,TestMEP,,,,1000000,1000,1000,,,MEP\n"
            "2022-02-15,CONVERSION_USD_ARS,TestMEP · USD,,,,400000,400,1000,,,MEP\n")
        # Ida 1000, vuelta 400 → al sibling le quedan 600 atribuidos.
        self.assertAlmostEqual(self._cap(conn, self.SIB), 600.0, places=1)
        # El padre recupera los 400 que volvieron.
        self.assertAlmostEqual(self._cap(conn, self.BROKER), 706.71 - 1000 + 400, places=1)
        self.assertAlmostEqual(self._cap(conn, "global"), 706.71, places=1)
        conn.close()

    def test_las_patas_siempre_suman_cero(self):
        """El invariante que sostiene todo: Σ(capital por broker) == capital
        global. Si una pata se atribuyera sin la otra, el aportado global se
        movería y el rendimiento de TODA la cartera saldría mal."""
        conn = self._import(
            HDR +
            "2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n"
            "2022-01-11,CONVERSION_ARS_USD,TestMEP,,,,300000,300,1000,,,MEP\n"
            "2022-03-02,CONVERSION_ARS_USD,TestMEP,,,,200000,200,1000,,,MEP\n"
            "2022-04-20,CONVERSION_USD_ARS,TestMEP · USD,,,,150000,150,1000,,,MEP\n")
        suma = sum(self._cap(conn, b) for b in (self.BROKER, self.SIB))
        self.assertAlmostEqual(suma, self._cap(conn, "global"), places=1)
        self.assertAlmostEqual(self._cap(conn, "global"), 706.71, places=1)
        # 300 + 200 − 150 quedaron del lado dólar.
        self.assertAlmostEqual(self._cap(conn, self.SIB), 350.0, places=1)
        conn.close()

    def test_es_idempotente_ante_recalcs_repetidos(self):
        """El recalc corre en ~12 call sites. Al recomputar desde la fuente en vez
        de acumular, correrlo N veces tiene que dar lo mismo que una. Acumularlo
        en `manual_*` desde el persister —la otra opción de arreglo— no habría
        pasado este test."""
        conn = self._import(
            HDR +
            "2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n"
            "2022-01-11,CONVERSION_ARS_USD,TestMEP,,,,1000000,1000,1000,,,MEP\n")
        antes = [self._cap(conn, b) for b in (self.BROKER, self.SIB, "global")]
        for _ in range(3):
            with conn:
                main._recalc_pnl_realized_from_ops(conn, self.uid)
        self.assertEqual([self._cap(conn, b) for b in (self.BROKER, self.SIB, "global")],
                         antes)
        conn.close()

    def test_sin_conversion_el_capital_no_se_toca(self):
        """Control: un depósito ARS sin conversión queda al blue y nadie lo mueve."""
        conn = self._import(HDR + "2022-01-10,DEPOSITO,TestMEP,,,,1000000,,,,ARS,dep\n")
        self.assertAlmostEqual(self._cap(conn, "global"), 1000000 / 1415.0, places=1)
        self.assertAlmostEqual(self._cap(conn, self.BROKER), 1000000 / 1415.0, places=1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
