"""Edición a nivel GRUPO de una posición multi-lote (main.edit_position_group).

La fila agregada de Cartera es una VISTA, no un registro: editarla es aplicar una
regla a cada lote. Lo que se testea es justamente que la regla sea la correcta por
campo, porque mezclarlas rompe el costo FIFO:

  • precio promedio → ESCALA proporcional (k): el promedio da EXACTO el pedido y se
    preserva la forma (qué lote fue más barato). Igualar todos rompería cada lote.
  • tipo de cambio  → NO se prorratea: o el histórico de la fecha de CADA lote, o
    uno fijo para todos.
  • activo          → igual en todos, y también en la fila FUENTE del import (si no,
    el próximo import re-deriva el lote y la corrección se deshace sola).

Corre con: cd backend && python3 -m pytest tests/test_position_group_edit.py
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


class GroupEditTest(unittest.TestCase):
    BROKER = "Galicia"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("positions", "operations", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches", "deleted_ops_journal",
                  "fx_rates_daily", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("grupo@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        # Serie FX: dos fechas con TC bien distintos, para que 'historical' se note.
        for d, mep in (("2025-03-25", 1100.0), ("2025-09-10", 1400.0)):
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                (d, mep, mep))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _lote(self, qty, price, date, asset="FIMA-ACCIONES", ccy="ARS"):
        return self.conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, quantity, buy_price,
                                      invested, entry_date, currency)
               VALUES (?,?,?,0,?,?,?,?,?)""",
            (self.uid, self.BROKER, asset, qty, price, qty * price, date, ccy)).lastrowid

    def _lotes(self, asset="FIMA-ACCIONES"):
        return self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset=? ORDER BY id",
            (self.uid, asset)).fetchall()

    def _edit(self, **kw):
        body = main.PositionGroupEditIn(broker=self.BROKER, asset="FIMA-ACCIONES", **kw)
        return main._edit_position_group(self.conn, self.uid, body)

    def _prom(self, asset="FIMA-ACCIONES"):
        rows = self._lotes(asset)
        q = sum(float(r["quantity"] or 0) for r in rows)
        i = sum(float(r["invested"] or 0) for r in rows)
        return i / q if q else None

    # ── precio promedio ──────────────────────────────────────────────────────
    def test_promedio_escala_proporcional_y_da_exacto(self):
        self._lote(500000, 180, "2025-03-25")
        self._lote(300000, 220, "2025-06-01")
        self._lote(253104, 250, "2025-09-10")
        self.conn.commit()
        # Ponderado por plata: 219.276.000 / 1.053.104 = 208,22. El promedio SIMPLE de
        # los tres precios daría 216,67 — es justamente lo que no hay que hacer.
        self.assertAlmostEqual(self._prom(), 208.2188, places=3)

        self._edit(avg_price=200)
        self.assertAlmostEqual(self._prom(), 200.0, places=6,
                               msg="el promedio tiene que dar EXACTO el pedido")
        rows = self._lotes()
        # FORMA preservada: la relación entre lotes no cambia (el barato sigue barato).
        self.assertAlmostEqual(rows[1]["buy_price"] / rows[0]["buy_price"], 220 / 180, places=9)
        self.assertAlmostEqual(rows[2]["buy_price"] / rows[0]["buy_price"], 250 / 180, places=9)
        # Cantidades y fechas INTACTAS (repartir cantidad rompería el FIFO).
        self.assertEqual([r["quantity"] for r in rows], [500000, 300000, 253104])
        self.assertEqual([r["entry_date"] for r in rows],
                         ["2025-03-25", "2025-06-01", "2025-09-10"])
        # invested = precio × cantidad en cada lote (no queda desalineado)
        for r in rows:
            self.assertAlmostEqual(r["invested"], r["buy_price"] * r["quantity"], places=4)

    def test_promedio_sobre_grupo_a_costo_cero_iguala(self):
        # Lotes semilla / transferencias sin costo: no hay proporción que preservar,
        # así que el precio pedido va igual en todos (si escaláramos, k sería infinito).
        self._lote(100, 0, "2025-03-25")
        self._lote(200, 0, "2025-06-01")
        self.conn.commit()
        self._edit(avg_price=50)
        rows = self._lotes()
        self.assertEqual([r["buy_price"] for r in rows], [50, 50])
        self.assertEqual([r["invested"] for r in rows], [5000, 10000])

    # ── tipo de cambio ───────────────────────────────────────────────────────
    def test_tc_historico_usa_la_fecha_de_cada_lote(self):
        self._lote(100, 180, "2025-03-25")
        self._lote(100, 250, "2025-09-10")
        self.conn.commit()
        self._edit(tc_mode="historical")
        rows = self._lotes()
        self.assertAlmostEqual(rows[0]["tc_compra"], 1100.0, places=4)
        self.assertAlmostEqual(rows[1]["tc_compra"], 1400.0, places=4)

    def test_tc_fijo_va_igual_en_todos(self):
        self._lote(100, 180, "2025-03-25")
        self._lote(100, 250, "2025-09-10")
        self.conn.commit()
        self._edit(tc_mode="fixed", tc_value=1250)
        self.assertEqual([r["tc_compra"] for r in self._lotes()], [1250.0, 1250.0])

    def test_tc_no_toca_el_precio_ni_al_reves(self):
        self._lote(100, 180, "2025-03-25")
        self.conn.commit()
        self._edit(tc_mode="fixed", tc_value=1250)
        self.assertEqual(self._lotes()[0]["buy_price"], 180)
        self._edit(avg_price=200)
        self.assertEqual(self._lotes()[0]["tc_compra"], 1250.0)

    # ── renombrar ────────────────────────────────────────────────────────────
    def _lote_importado(self, qty, price, date):
        pid = self._lote(qty, price, date)
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,'g','h','confirmed')", (f"b{pid}", self.uid, self.BROKER))
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) "
            "VALUES (?,0,'{}','valid')", (f"b{pid}",)).lastrowid
        tx = self.conn.execute(
            """INSERT INTO import_normalized_tx (batch_id, raw_row_id, date, broker,
                   operation_type, asset_symbol, quantity, unit_price, gross_amount)
               VALUES (?,?,?,?,'BUY','FIMA-ACCIONES',?,?,?)""",
            (f"b{pid}", rr, date, self.BROKER, qty, price, qty * price)).lastrowid
        self.conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            (f"b{pid}", rr, pid))
        self.conn.commit()
        return pid, tx

    def test_renombrar_alcanza_lotes_operaciones_y_la_fila_del_import(self):
        _, tx = self._lote_importado(100, 180, "2025-03-25")
        self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type) VALUES (?,?,?,?,'Venta')",
            (self.uid, "2025-10-01", self.BROKER, "FIMA-ACCIONES"))
        self.conn.commit()

        self._edit(new_asset="FCI:FIMA-ACCIONES-A")

        self.assertEqual(self._lotes("FCI:FIMA-ACCIONES-A")[0]["asset"], "FCI:FIMA-ACCIONES-A")
        self.assertEqual(self.conn.execute(
            "SELECT asset FROM operations WHERE user_id=?", (self.uid,)).fetchone()["asset"],
            "FCI:FIMA-ACCIONES-A")
        # La FUENTE también: sin esto el próximo import re-deriva el lote con el
        # ticker viejo y la corrección se deshace sola.
        self.assertEqual(self.conn.execute(
            "SELECT asset_symbol FROM import_normalized_tx WHERE id=?", (tx,)).fetchone()["asset_symbol"],
            "FCI:FIMA-ACCIONES-A")

    def test_precio_escala_tambien_la_fila_del_import(self):
        _, tx = self._lote_importado(100, 180, "2025-03-25")
        self._edit(avg_price=90)
        src = self.conn.execute(
            "SELECT unit_price, gross_amount FROM import_normalized_tx WHERE id=?", (tx,)).fetchone()
        self.assertAlmostEqual(src["unit_price"], 90.0, places=6)
        self.assertAlmostEqual(src["gross_amount"], 9000.0, places=4)

    # ── moneda ───────────────────────────────────────────────────────────────
    def test_la_moneda_separa_grupos(self):
        # Un activo con pata ARS y pata USD son DOS grupos en Cartera: promediarlos
        # juntos mezclaría monedas.
        self._lote(100, 180, "2025-03-25", ccy="ARS")
        self._lote(10, 5, "2025-06-01", ccy="USD")
        self.conn.commit()
        main._edit_position_group(self.conn, self.uid, main.PositionGroupEditIn(
            broker=self.BROKER, asset="FIMA-ACCIONES", currency="ARS", avg_price=200))
        rows = self._lotes()
        self.assertAlmostEqual(rows[0]["buy_price"], 200.0, places=6)   # ARS: editado
        self.assertAlmostEqual(rows[1]["buy_price"], 5.0, places=6)     # USD: intacto

    # ── undo ─────────────────────────────────────────────────────────────────
    def test_undo_restaura_todo(self):
        _, tx = self._lote_importado(100, 180, "2025-03-25")
        self._lote(50, 220, "2025-09-10")
        self.conn.commit()
        antes = [(r["asset"], r["buy_price"], r["invested"], r["tc_compra"]) for r in self._lotes()]

        res = self._edit(new_asset="FCI:FIMA-ACCIONES-A", avg_price=100, tc_mode="fixed", tc_value=1250)
        self.assertNotEqual(
            [(r["asset"], r["buy_price"], r["invested"], r["tc_compra"])
             for r in self._lotes("FCI:FIMA-ACCIONES-A")], antes)

        main._undo_edit_position_group(self.conn, self.uid, res["undo_token"])
        self.assertEqual([(r["asset"], r["buy_price"], r["invested"], r["tc_compra"])
                          for r in self._lotes()], antes)
        self.assertEqual(self.conn.execute(
            "SELECT asset_symbol, unit_price FROM import_normalized_tx WHERE id=?", (tx,)).fetchone()[0],
            "FIMA-ACCIONES")
        # idempotente: deshacer dos veces no revierte una edición posterior
        with self.assertRaises(main.HTTPException):
            main._undo_edit_position_group(self.conn, self.uid, res["undo_token"])

    def test_sin_cambios_es_400(self):
        self._lote(100, 180, "2025-03-25")
        self.conn.commit()
        with self.assertRaises(main.HTTPException):
            self._edit()

    def test_grupo_inexistente_es_404(self):
        with self.assertRaises(main.HTTPException):
            main._edit_position_group(self.conn, self.uid, main.PositionGroupEditIn(
                broker=self.BROKER, asset="NO-EXISTE", avg_price=10))


if __name__ == "__main__":
    unittest.main()
