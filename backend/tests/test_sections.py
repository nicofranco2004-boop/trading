"""Secciones de Renta Fija: clasificación + borrado/restore reversible.

Corre con: cd backend && python3 -m pytest tests/test_sections.py
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

import main  # noqa: E402
from importing import sections as S  # noqa: E402


class SectionClassifierTest(unittest.TestCase):
    def test_bono_by_currency(self):
        self.assertEqual(S.position_section("BOND", "AL30", "USD"), ("BONO", "USD"))
        self.assertEqual(S.position_section("BOND", "AL30", "ARS"), ("BONO", "ARS"))
        self.assertEqual(S.position_section("BOND", "AL30", "USDT"), ("BONO", "USD"))

    def test_bono_by_ticker_without_type(self):
        # IEB no etiqueta tipo (asset_type vacío) → igual se clasifica por ticker.
        self.assertEqual(S.position_section("", "GD35", "USD"), ("BONO", "USD"))
        self.assertEqual(S.position_section(None, "AL30", "ARS"), ("BONO", "ARS"))

    def test_letra_by_pattern(self):
        # S28N5 matchea el patrón de letra aunque no esté en el catálogo de bonos.
        self.assertEqual(S.position_section("", "S28N5", "ARS"), ("LETRA", "ARS"))
        self.assertEqual(S.position_section("OTHER", "T13F6", "ARS"), ("LETRA", "ARS"))

    def test_fci(self):
        self.assertEqual(S.position_section("FUND", "COCORA", "ARS"), ("FCI", "ARS"))
        self.assertEqual(S.position_section("FUND", "BAHUSDA", "USD"), ("FCI", "USD"))

    def test_renta_variable_is_none(self):
        self.assertIsNone(S.position_section("CEDEAR", "SPY", "USD"))
        self.assertIsNone(S.position_section("STOCK", "YPFD", "ARS"))
        self.assertIsNone(S.position_section("CRYPTO", "BTC", "USD"))

    def test_keys_and_labels(self):
        self.assertEqual(S.section_key("BONO", "USD"), "BONO|USD")
        self.assertEqual(S.section_label("BONO", "USD"), "Bonos USD")
        self.assertEqual(S.section_label("FCI", "ARS"), "FCI ARS")
        self.assertEqual(S.parse_section_key("LETRA|ARS"), ("LETRA", "ARS"))
        self.assertIsNone(S.parse_section_key("XX|YY"))


class SectionArchiveRestoreTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        try:
            for t in ("archived_positions", "positions", "brokers", "users"):
                try:
                    conn.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                ("sections@rendi.test", "x"))
            self.uid = cur.lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (self.uid, "IEB", "ARS"))
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "VALUES (?,?,?,(SELECT id FROM brokers WHERE user_id=? AND name='IEB'))",
                         (self.uid, "IEB · USD", "USD", self.uid))
            # Renta fija + variable mezclada en el broker
            for broker, asset, bp, ccy, at in [
                ("IEB · USD", "AL30", 0.6, "USD", "BOND"),     # Bonos USD
                ("IEB · USD", "GD35", 0.7, "USD", "BOND"),     # Bonos USD
                ("IEB", "AL30", 800.0, "ARS", "BOND"),         # Bonos ARS
                ("IEB", "S28N5", 950.0, "ARS", ""),            # Letra ARS (por patrón)
                ("IEB · USD", "SPY", 12.4, "USD", "CEDEAR"),   # renta variable (no se toca)
            ]:
                conn.execute(
                    "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
                    "invested, buy_price, currency, asset_type) VALUES (?,?,?,0,?,?,?,?,?)",
                    (self.uid, broker, asset, 100.0, bp * 100, bp, ccy, at))
            conn.commit()
        finally:
            conn.close()

    def _assets(self):
        c = main.get_db()
        try:
            rows = c.execute("SELECT asset, broker FROM positions WHERE user_id=? AND is_cash=0",
                             (self.uid,)).fetchall()
            return sorted((r["asset"], r["broker"]) for r in rows)
        finally:
            c.close()

    def test_archive_then_restore_bonos_usd(self):
        # Archivar Bonos USD → quedan los demás (Bonos ARS, Letra, CEDEAR).
        res = main.sections_archive(main.SectionKeyIn(section="BONO|USD"), uid=self.uid)
        self.assertEqual(res["archived"], 2)
        self.assertEqual(res["label"], "Bonos USD")
        self.assertEqual(self._assets(),
                         sorted([("AL30", "IEB"), ("S28N5", "IEB"), ("SPY", "IEB · USD")]))
        # Aparece en la lista de archivadas.
        arch = main.sections_archived(uid=self.uid)["archived"]
        self.assertEqual(len(arch), 1)
        self.assertEqual(arch[0]["count"], 2)
        # Restaurar → vuelven los 2 bonos USD, lista vacía.
        r2 = main.sections_restore(main.SectionRestoreIn(archive_id=arch[0]["id"]), uid=self.uid)
        self.assertEqual(r2["restored"], 2)
        self.assertEqual(self._assets(), sorted([
            ("AL30", "IEB · USD"), ("GD35", "IEB · USD"), ("AL30", "IEB"),
            ("S28N5", "IEB"), ("SPY", "IEB · USD")]))
        self.assertEqual(main.sections_archived(uid=self.uid)["archived"], [])

    def test_archive_letra_ars(self):
        res = main.sections_archive(main.SectionKeyIn(section="LETRA|ARS"), uid=self.uid)
        self.assertEqual(res["archived"], 1)
        self.assertNotIn(("S28N5", "IEB"), self._assets())

    def test_archive_empty_section_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            main.sections_archive(main.SectionKeyIn(section="FCI|USD"), uid=self.uid)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cedear_never_in_a_section(self):
        # Archivar todas las secciones de bonos/letras NO debe tocar la CEDEAR.
        for k in ("BONO|USD", "BONO|ARS", "LETRA|ARS"):
            try:
                main.sections_archive(main.SectionKeyIn(section=k), uid=self.uid)
            except Exception:
                pass
        self.assertIn(("SPY", "IEB · USD"), self._assets())


if __name__ == "__main__":
    unittest.main()
