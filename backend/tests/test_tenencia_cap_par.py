"""La guarda del 50% de la foto de tenencia y la cuenta en dólares del par.

Una foto (el PDF/CSV de posición del broker) se aplica en modo OVERRIDE: PISA lo
que hay. El wizard la aplica SIN checkpoint, así que hay una guarda dura para que
una foto mal leída no vacíe una cartera: si el corte se llevaría más del 50% del
valor —o más de la mitad de los activos— aborta y hace sólo gap-fill.

El bug: la mitad por CANTIDAD medía `n_cut` (lo que este broker corta) contra
`len(current)`, que viene sumado sobre TODO el par (broker padre en pesos +
sibling '· USD'). Los activos del sibling NUNCA son cortables —`_reducible` los
saca vía sibling_assets— pero engordaban el denominador igual. O sea que tener
una cuenta en dólares, que sólo AGREGA cosas intocables, volvía más PERMISIVA la
guarda del lado en pesos.

Corre con: cd backend && python3 -m pytest tests/test_tenencia_cap_par.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import main                                       # noqa: E402
from importing import tenencia as tn              # noqa: E402
from importing.persister import broker_pair       # noqa: E402


class CapDelParTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("import_op_links", "import_raw_rows", "import_batches",
                  "positions", "operations", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES ('cap@rendi.test','x',1,1)").lastrowid
        self.pid = self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,'TB','ARS')",
            (self.uid,)).lastrowid
        self.bid = "batch-cap"
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, status, broker, file_name, "
            "parser_format, file_hash) VALUES (?,?,'confirmed','TB','x.csv','balanz','h')",
            (self.bid, self.uid))
        self._n = 0
        self.conn.commit()

    def _sibling_usd(self):
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
            "VALUES (?,'TB · USD','USD',?)", (self.uid, self.pid))

    def _pos(self, broker, asset, qty, invested):
        """Posición VENIDA DE UN IMPORT (linkeada), para que _is_safe_to_rebuild
        la considere reproducible — si no, se saltea por 'manual' y no se corta."""
        self._n += 1
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) "
            "VALUES (?,?,'{}','valid')", (self.bid, self._n)).lastrowid
        p = self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, quantity, invested, is_cash) "
            "VALUES (?,?,?,?,?,0)", (self.uid, broker, asset, qty, invested)).lastrowid
        self.conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            (self.bid, rr, p))

    def _aplicar_foto_del_grande(self):
        """Foto del broker en pesos que lista SÓLO el activo grande → los 9
        chicos quedan como not_in_snapshot (candidatos a borrarse)."""
        self.conn.commit()
        pair = broker_pair(self.conn, self.uid, "TB")
        ph = ",".join("?" * len(pair))
        current, invested = {}, {}
        for r in self.conn.execute(
                f"SELECT asset, SUM(quantity) q, SUM(invested) inv FROM positions "
                f"WHERE user_id=? AND is_cash=0 AND broker IN ({ph}) GROUP BY asset",
                (self.uid, *pair)):
            current[r["asset"]] = r["q"] or 0
            invested[r["asset"]] = r["inv"] or 0
        snap = tn.TenenciaSnapshot(
            holdings=[tn.Holding(ticker="GRANDE", asset_type="CEDEAR", quantity=1,
                                 value=1_000_000.0, currency="ARS",
                                 price_per1=1_000_000.0)],
            date="2026-08-19")
        rec = tn.compute_reconcile(current, snap)
        _, ov = main._tenencia_apply_override(
            self.conn, self.uid, "TB", pair, rec, invested, current,
            "2026-08-19", complete=True)
        return ov

    def _cartera_pesos(self):
        """1 activo grande + 9 chicos. Cortar los 9 es el 90% de los activos
        pero menos del 1% del valor → sólo la mitad por CANTIDAD puede frenarlo."""
        self._pos("TB", "GRANDE", 1, 1_000_000.0)
        for i in range(9):
            self._pos("TB", f"CHICO{i}", 1, 1_000.0)

    def test_sin_cuenta_en_dolares_la_guarda_corta(self):
        self._cartera_pesos()
        ov = self._aplicar_foto_del_grande()
        self.assertTrue(ov["capped"])
        self.assertEqual(ov["removed"], [])

    def test_con_cuenta_en_dolares_la_guarda_sigue_cortando(self):
        """El bug: los 12 tickers del sibling —intocables— pasaban el
        denominador de 10 a 22, y 9 > 0.5*22 dejaba de ser cierto. Misma
        cartera en pesos, misma foto: el veredicto no puede cambiar porque
        el usuario además tenga dólares."""
        self._cartera_pesos()
        self._sibling_usd()
        for i in range(12):
            self._pos("TB · USD", f"USA{i}", 1, 500.0)
        ov = self._aplicar_foto_del_grande()
        self.assertTrue(ov["capped"], "la cuenta en dólares desarmó la guarda")
        self.assertEqual(ov["removed"], [])

    def test_los_dolares_nunca_se_cortan_desde_la_foto_del_padre(self):
        """Complemento: el sibling está protegido por sibling_assets, así que
        una foto del broker en pesos no puede llevarse los dólares — aparecen
        como salteados, no como borrados."""
        self._pos("TB", "GRANDE", 1, 1_000_000.0)
        self._sibling_usd()
        self._pos("TB · USD", "AAPL", 20, 3_000.0)
        self._pos("TB · USD", "MSFT", 10, 2_000.0)
        ov = self._aplicar_foto_del_grande()
        self.assertFalse(ov["capped"])
        self.assertEqual(ov["removed"], [])
        self.assertEqual(sorted(ov["skipped_manual"]), ["AAPL", "MSFT"])

    def test_un_corte_chico_sigue_pasando(self):
        """La guarda no puede volverse tan estricta que no deje trabajar: de 10
        activos en pesos se cortan 2 → pasa."""
        self._pos("TB", "GRANDE", 1, 1_000_000.0)
        for i in range(9):
            self._pos("TB", f"CHICO{i}", 1, 1_000.0)
        self.conn.commit()
        pair = broker_pair(self.conn, self.uid, "TB")
        current, invested = {}, {}
        for r in self.conn.execute(
                "SELECT asset, SUM(quantity) q, SUM(invested) inv FROM positions "
                "WHERE user_id=? AND is_cash=0 GROUP BY asset", (self.uid,)):
            current[r["asset"]] = r["q"] or 0
            invested[r["asset"]] = r["inv"] or 0
        # La foto lista todo menos 2 chicos.
        hs = [tn.Holding(ticker="GRANDE", asset_type="CEDEAR", quantity=1,
                         value=1_000_000.0, currency="ARS", price_per1=1_000_000.0)]
        hs += [tn.Holding(ticker=f"CHICO{i}", asset_type="ACCION", quantity=1,
                          value=1_000.0, currency="ARS", price_per1=1_000.0)
               for i in range(2, 9)]
        rec = tn.compute_reconcile(current, tn.TenenciaSnapshot(holdings=hs, date="2026-08-19"))
        _, ov = main._tenencia_apply_override(
            self.conn, self.uid, "TB", pair, rec, invested, current,
            "2026-08-19", complete=True)
        self.assertFalse(ov["capped"])
        self.assertEqual(sorted(x["ticker"] for x in ov["removed"]), ["CHICO0", "CHICO1"])


if __name__ == "__main__":
    unittest.main()
