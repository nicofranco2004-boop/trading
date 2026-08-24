"""La tenencia a la fecha de la foto, anclada en `positions`.

🔴 EL ANCLA ES LA DECISIÓN DEL MÓDULO. Existe `ledger_replay.tenencia_en`, que
replaya el ledger hacia adelante. Usarla acá sería un SEGUNDO MOTOR DE TENENCIA:
cuando el resultado y la foto no coincidieran, no habría forma de saber si el
import está mal o si el segundo motor está mal. Es lo que ya pasó con `valor_en`,
que terminó siendo un segundo motor de valuación y hubo que enderezarlo para que
delegara en el canónico.

Anclando en `positions` se compara lo que el usuario EFECTIVAMENTE VE, rodado
hacia atrás, contra lo que el broker dijo. Una sola cadena, un solo motor.

Verificado contra la copia de prod del 2026-08-16, comparando la proyección
contra `snapshots.holdings_json` del cron —una referencia que no es ni el replay
ni la foto—: **98,6% de composición exacta** sobre 3.855 pares (usuario, fecha).
"""
import unittest
import uuid

import main
from importing.proyeccion import (ESTADO_NO_COINCIDE, ESTADO_OK, ESTADO_SIN_REFERENCIA,
                                  MOTIVO_MANUAL, MOTIVO_SPLIT, MOTIVO_VENCIMIENTO,
                                  proyectar, verificar_contra_snapshot)

HOY = "2026-08-16"


class ProyeccionTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,'x',1)",
            (f"proy-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')",
                          (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _pos(self, asset, qty, **kw):
        self.conn.execute(
            "INSERT INTO positions (user_id,broker,asset,is_cash,quantity,buy_price,"
            "invested,split_adjusted_through) VALUES (?,'Cocos',?,0,?,1,1,?)",
            (self.uid, asset, qty, kw.get("split")))
        self.conn.commit()

    def _mov(self, asset, op, qty, date, *, batch_status="confirmed", bid=None):
        bid = bid or uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT OR IGNORE INTO import_batches (id,user_id,broker,parser_format,"
            "file_hash,status) VALUES (?,?,'Cocos','cocos',?,?)",
            (bid, self.uid, bid, batch_status))
        rid = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
            "VALUES (?,0,'{}','valid')", (bid,)).lastrowid
        self.conn.execute(
            "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,"
            "operation_type,asset_symbol,quantity,currency) VALUES (?,?,?,'Cocos',?,?,?,'ARS')",
            (bid, rid, date, op, asset, qty))
        self.conn.commit()
        return bid

    def _proy(self, fecha, **kw):
        return proyectar(self.conn, self.uid, pair=["Cocos"], fecha=fecha, hoy=HOY, **kw)

    # ── el corazón: rodar hacia atrás ───────────────────────────────────────
    def test_una_compra_POSTERIOR_a_la_foto_no_cuenta(self):
        # ⭐ El caso que motivó todo el módulo. Sin esto, una compra hecha
        # después del corte aparece como "Rendi tiene de más" contra el broker,
        # y el asesor tiene que decidir sobre una discrepancia inventada.
        self._pos("AAPL", 15)
        self._mov("AAPL", "BUY", 5, "2026-07-01")
        q, _ = self._proy("2026-06-30")
        self.assertEqual(q["AAPL"], 10)

    def test_una_venta_POSTERIOR_se_devuelve(self):
        # Al revés: lo vendido después SÍ estaba a la fecha de la foto. Sin
        # esto sale un falso "coincide" o un falso "falta".
        self._pos("AAPL", 10)
        self._mov("AAPL", "SELL", 4, "2026-07-01")
        q, _ = self._proy("2026-06-30")
        self.assertEqual(q["AAPL"], 14)

    def test_lo_ANTERIOR_a_la_foto_no_se_toca(self):
        self._pos("AAPL", 10)
        self._mov("AAPL", "BUY", 10, "2026-01-15")
        q, _ = self._proy("2026-06-30")
        self.assertEqual(q["AAPL"], 10)

    def test_un_activo_comprado_entero_despues_desaparece(self):
        self._pos("TSLA", 7)
        self._mov("TSLA", "BUY", 7, "2026-07-10")
        q, _ = self._proy("2026-06-30")
        self.assertNotIn("TSLA", q)

    # ── el preview ──────────────────────────────────────────────────────────
    def test_el_preview_suma_solo_hasta_la_fecha(self):
        self._pos("AAPL", 10)
        bid = self._mov("AAPL", "BUY", 3, "2026-06-01", batch_status="preview")
        self._mov("AAPL", "BUY", 99, "2026-07-01", batch_status="preview", bid=bid)
        q, _ = self._proy("2026-06-30", session_id=bid)
        self.assertEqual(q["AAPL"], 13)

    def test_un_preview_AJENO_no_se_cuela(self):
        self._pos("AAPL", 10)
        self._mov("AAPL", "BUY", 50, "2026-06-01", batch_status="preview")
        q, _ = self._proy("2026-06-30")
        self.assertEqual(q["AAPL"], 10)

    def test_un_batch_REVERTIDO_no_se_deshace(self):
        # El ledger de un import deshecho no describe nada que haya pasado.
        self._pos("AAPL", 10)
        self._mov("AAPL", "BUY", 5, "2026-07-01", batch_status="reverted")
        q, _ = self._proy("2026-06-30")
        self.assertEqual(q["AAPL"], 10)

    # ── lo que NO se puede rodar hacia atrás ────────────────────────────────
    def test_una_operacion_MANUAL_posterior_hace_no_reconciliable(self):
        # No hay fila en el ledger que restar, así que el retroceso no la
        # deshace y el número quedaría mal EN SILENCIO.
        self._pos("AAPL", 10)
        self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,entry_price,"
            "exit_price,quantity,pnl_usd) VALUES (?,'2026-07-05','Cocos','AAPL','Venta',1,2,3,3)",
            (self.uid,))
        self.conn.commit()
        q, nr = self._proy("2026-06-30")
        self.assertNotIn("AAPL", q)
        self.assertEqual(nr[0]["motivo"], MOTIVO_MANUAL)

    def test_un_split_dentro_de_la_ventana_hace_no_reconciliable(self):
        self._pos("NVDA", 40, split="2026-07-20")
        q, nr = self._proy("2026-06-30")
        self.assertNotIn("NVDA", q)
        self.assertEqual(nr[0]["motivo"], MOTIVO_SPLIT)

    def test_un_split_ANTERIOR_a_la_foto_no_molesta(self):
        self._pos("NVDA", 40, split="2026-01-10")
        q, nr = self._proy("2026-06-30")
        self.assertEqual(q["NVDA"], 40)
        self.assertEqual(nr, [])

    def test_una_letra_vencida_en_la_ventana_hace_no_reconciliable(self):
        # `sweep_matured_letras` BORRÓ la posición entre D y hoy, así que
        # `positions` ya no tiene el nominal que la persona sí tenía en D.
        # Recuperarlo del ledger sería reintroducir el segundo motor.
        #
        # El último dígito del ticker es el AÑO: G5 = agosto 2025, G6 = agosto
        # 2026. Con la ventana D=2026-06-30 .. hoy=2026-08-16:
        self._pos("S15G6", 500)      # vence 2026-08-15 → DENTRO de la ventana
        self._pos("S30S6", 1000)     # vence 2026-09-30 → todavía viva
        self._pos("S15G5", 700)      # venció 2025-08-15 → ya no estaba en D
        q, nr = self._proy("2026-06-30")
        motivos = {x["ticker"]: x["motivo"] for x in nr}
        self.assertEqual(motivos.get("S15G6"), MOTIVO_VENCIMIENTO)
        self.assertNotIn("S15G6", q)
        # La que vence después de hoy no se toca: sigue viva en positions.
        self.assertEqual(q["S30S6"], 1000)
        # Y la que ya había vencido ANTES de la foto tampoco es un problema:
        # en D tampoco la tenía.
        self.assertNotIn("S15G5", motivos)

    # ── la guarda contra la referencia independiente ────────────────────────
    def _snap(self, date, assets, source="cron"):
        import json
        self.conn.execute(
            "INSERT INTO snapshots (user_id,date,total_value,total_invested,"
            "net_deposited,holdings_json,source) VALUES (?,?,0,0,0,?,?)",
            (self.uid, date, json.dumps([{"asset": a, "value_usd": 1} for a in assets]),
             source))
        self.conn.commit()

    def test_si_la_composicion_coincide_lo_dice(self):
        self._snap("2026-06-30", ["AAPL", "TSLA"])
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30",
                                      {"AAPL": 1.0, "TSLA": 2.0})
        self.assertEqual(r["estado"], ESTADO_OK)
        self.assertEqual(r["snapshot_fecha"], "2026-06-30")

    def test_marca_lo_que_SOBRA_en_la_proyeccion(self):
        # El caso peligroso: la proyección afirma una tenencia que la referencia
        # no respalda. Contra la foto saldría `not_in_snapshot`, que el override
        # cierra con una venta sintética.
        self._snap("2026-06-30", ["AAPL"])
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30",
                                      {"AAPL": 1.0, "FANTASMA": 5.0})
        self.assertEqual(r["sobra"], ["FANTASMA"])

    def test_marca_lo_que_FALTA(self):
        self._snap("2026-06-30", ["AAPL", "KO"])
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30", {"AAPL": 1.0})
        self.assertEqual(r["falta"], ["KO"])

    def test_sin_snapshot_del_cron_no_inventa_un_veredicto(self):
        # Falla ABIERTO: "no pude verificar" no es "está mal". Pero TAMPOCO es
        # "está bien", y esa es la parte que faltaba.
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30", {"AAPL": 1.0})
        self.assertEqual(r["estado"], ESTADO_SIN_REFERENCIA)
        self.assertEqual(r["motivo_sin_referencia"],
                         "no_hay_snapshot_del_cron_hasta_esa_fecha")

    def test_un_snapshot_que_NO_es_del_cron_no_sirve_de_referencia(self):
        # Los de `source='import'` son copias del capital_final, no mediciones
        # independientes: usarlos sería verificarse contra uno mismo.
        self._snap("2026-06-30", ["AAPL"], source="import")
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30", {"OTRO": 1.0})
        self.assertEqual(r["estado"], ESTADO_SIN_REFERENCIA)

    def test_COINCIDE_y_SIN_REFERENCIA_no_pueden_dar_lo_mismo(self):
        """🔴 El bug que este archivo tenía escrito y no veía.

        Hasta acá, `test_si_la_composicion_coincide_no_dice_nada` y
        `test_sin_snapshot_del_cron_no_inventa_un_veredicto` afirmaban los DOS
        `assertIsNone(...)`. O sea que los tests documentaban que "verifiqué y
        coincide" y "no tenía con qué verificar" salían por el mismo valor — y
        el endpoint los publicaba juntos como `verifica: true`.

        Se destapó corriendo una foto REAL de tres meses atrás contra una base
        sin snapshots del cron: el flag dio `true` sin haber comprobado nada.
        """
        self._snap("2026-06-30", ["AAPL"])
        coincide = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30", {"AAPL": 1.0})
        sin_ref = verificar_contra_snapshot(self.conn, self.uid, "2020-01-01", {"AAPL": 1.0})
        self.assertNotEqual(coincide["estado"], sin_ref["estado"])
        self.assertEqual(coincide["estado"], ESTADO_OK)
        self.assertEqual(sin_ref["estado"], ESTADO_SIN_REFERENCIA)
        # Y el tercero tampoco puede confundirse con ninguno de los dos.
        no_coincide = verificar_contra_snapshot(
            self.conn, self.uid, "2026-06-30", {"FANTASMA": 1.0})
        self.assertEqual(no_coincide["estado"], ESTADO_NO_COINCIDE)
        self.assertEqual(len({coincide["estado"], sin_ref["estado"],
                              no_coincide["estado"]}), 3)

    def test_sin_referencia_NUNCA_se_presenta_como_tranquilizador(self):
        # El texto que ve una persona no puede sonar a "todo bien".
        r = verificar_contra_snapshot(self.conn, self.uid, "2026-06-30", {"AAPL": 1.0})
        d = r["detalle"].lower()
        self.assertIn("no se pudo comprobar", d)
        for tranquilizador in ("todo bien", "coincide", "verificado", "correcto"):
            self.assertNotIn(tranquilizador, d)


if __name__ == "__main__":
    unittest.main()
