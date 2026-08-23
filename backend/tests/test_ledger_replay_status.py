"""El replay del ledger sólo cuenta batches CONFIRMADOS.

🔴 POR QUÉ EXISTE ESTE ARCHIVO. `tenencia_en` y `cash_en` no filtraban
`b.status`, mientras `censo_flujos.py` y `diagnostico.py` sí. Medido contra la
copia de producción del 2026-08-16: eso metía **208.896 filas BUY/SELL de
batches no confirmados**, en 312 usuarios (el 59% de los 588 con import
confirmado). El caso extremo, uid 109: cero posiciones vivas y el replay le
devolvía 82 activos — la cartera de un import que la persona ya deshizo.

Y el daño no era sólo un número feo. `verificar_contra_hoy` usa `tenencia_en`
para decidir **si a este usuario se le puede reconstruir el pasado**, así que un
replay inflado le hacía reportar "el ledger no reproduce las posiciones" cuando
en realidad estaba CONTANDO DE MÁS. Con el filtro puesto, la tasa de usuarios
reproducibles pasó de 14,3% a 20,1% (+34 usuarios) y los activos en desacuerdo
cayeron de 8.002 a 3.525.

⚠️ Los fixtures viejos usaban `status='done'`, un estado que NO EXISTE en
producción (sólo hay 'confirmed', 'reverted' y 'preview'). Pasaban porque la
función ignoraba el status: modelaban un mundo imposible.
"""
import unittest
import uuid

import main
import ledger_replay


class LedgerReplayStatusTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) "
            "VALUES (?, 'x', 1)", (f"lr-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.commit(); conn.close()

    def _batch(self, status, *, broker="Cocos"):
        bid = uuid.uuid4().hex[:12]
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO import_batches (id,user_id,broker,parser_format,"
                "file_hash,status) VALUES (?,?,?,'test',?,?)",
                (bid, self.uid, broker, bid, status))
            conn.commit()
        finally:
            conn.close()
        return bid

    def _tx(self, bid, op, asset, qty, date="2026-01-15", *, broker="Cocos",
            gross=0.0, ccy="USD"):
        conn = main.get_db()
        try:
            rid = conn.execute(
                "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
                "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,gross_amount,currency) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (bid, rid, date, broker, op, asset, qty, gross, ccy))
            conn.commit()
        finally:
            conn.close()

    def _ten(self, **kw):
        conn = main.get_db()
        try:
            return ledger_replay.tenencia_en(conn, self.uid, "2026-12-31", **kw)
        finally:
            conn.close()

    # ── el bug ──────────────────────────────────────────────────────────────
    def test_un_import_REVERTIDO_no_cuenta(self):
        # uid 109 en prod: cero posiciones, y el replay le devolvía 82 activos.
        b = self._batch("reverted")
        self._tx(b, "BUY", "AAPL", 10)
        self.assertEqual(self._ten(), {})

    def test_un_import_CONFIRMADO_si_cuenta(self):
        b = self._batch("confirmed")
        self._tx(b, "BUY", "AAPL", 10)
        self.assertEqual(self._ten(), {("Cocos", "AAPL"): 10.0})

    def test_el_revertido_no_le_come_la_tenencia_al_confirmado(self):
        # El caso que más engaña: la VENTA de un batch deshecho restándole al
        # stock que el batch bueno sí creó. El activo desaparecía entero.
        ok = self._batch("confirmed")
        self._tx(ok, "BUY", "AAPL", 10)
        malo = self._batch("reverted")
        self._tx(malo, "SELL", "AAPL", 10, date="2026-02-01")
        self.assertEqual(self._ten(), {("Cocos", "AAPL"): 10.0})

    # ── el preview: opt-in explícito, nunca por default ─────────────────────
    def test_un_PREVIEW_no_cuenta_por_default(self):
        b = self._batch("preview")
        self._tx(b, "BUY", "AAPL", 10)
        self.assertEqual(self._ten(), {})

    def test_el_preview_cuenta_SOLO_si_se_lo_pide_por_session_id(self):
        # Es lo que va a necesitar la proyección: "qué quedaría si confirmo esto".
        b = self._batch("preview")
        self._tx(b, "BUY", "AAPL", 10)
        self.assertEqual(self._ten(session_id=b), {("Cocos", "AAPL"): 10.0})

    def test_pedir_UN_preview_no_trae_los_otros(self):
        # Un preview ajeno (otra sesión abierta del mismo usuario) no se cuela.
        mio = self._batch("preview")
        self._tx(mio, "BUY", "AAPL", 10)
        ajeno = self._batch("preview")
        self._tx(ajeno, "BUY", "MSFT", 5)
        self.assertEqual(self._ten(session_id=mio), {("Cocos", "AAPL"): 10.0})

    # ── cash_en tiene el mismo agujero ──────────────────────────────────────
    def test_el_cash_de_un_revertido_tampoco_cuenta(self):
        # Acá iba peor que en tenencia: `cash_en` no filtra operation_type en el
        # WHERE, así que los DEPOSIT de un batch deshecho entraban enteros.
        b = self._batch("reverted")
        self._tx(b, "DEPOSIT", None, 0, gross=100000.0)
        conn = main.get_db()
        try:
            self.assertEqual(ledger_replay.cash_en(conn, self.uid, "2026-12-31"), {})
        finally:
            conn.close()

    def test_el_cash_confirmado_si_cuenta(self):
        b = self._batch("confirmed")
        self._tx(b, "DEPOSIT", None, 0, gross=1000.0)
        conn = main.get_db()
        try:
            self.assertEqual(
                ledger_replay.cash_en(conn, self.uid, "2026-12-31"),
                {("Cocos", "USD"): 1000.0})
        finally:
            conn.close()

    # ── el estado que los fixtures inventaban ───────────────────────────────
    def test_un_status_que_no_existe_no_cuenta(self):
        # Los fixtures viejos usaban 'done', que no existe en prod. Pasaban
        # porque la función ignoraba el status. Un estado desconocido tiene que
        # fallar CERRADO: si no sabemos qué es, no es tenencia de nadie.
        b = self._batch("done")
        self._tx(b, "BUY", "AAPL", 10)
        self.assertEqual(self._ten(), {})


if __name__ == "__main__":
    unittest.main()
