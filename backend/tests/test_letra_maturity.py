"""Tests del cierre de letras/LECAPs al vencer (importing/maturity.py).

Cubre: decodificación del ticker AR (S31O5 → 31/10/2025), síntesis para letras
sin ticker, el fallback del parser de Cocos, y el sweep que cierra posiciones
vencidas respetando data manual y la ventana de fechas importada.

Corre con: cd backend && python3 -m pytest tests/test_letra_maturity.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing.maturity import (
    letra_maturity, maturity_from_name, synth_letra_ticker, is_bond_like_name,
    sweep_matured_letras,
)
from importing.parsers.cocos import CocosParser
import main  # init_db


class TestLetraMaturity(unittest.TestCase):
    def test_decodes_real_lecaps(self):
        casos = {
            "S31O5": "2025-10-31",   # 31 octubre 2025
            "T17O5": "2025-10-17",
            "S15G5": "2025-08-15",   # agosto
            "S31L5": "2025-07-31",   # julio
            "S29G5": "2025-08-29",
            "S17A6": "2026-04-17",   # abril 2026
            "S16M6": "2026-03-16",   # marzo
            "S17E5": "2025-01-17",   # enero
            "S14F5": "2025-02-14",   # febrero
        }
        for sym, iso in casos.items():
            self.assertEqual(letra_maturity(sym), iso, sym)

    def test_no_letra_devuelve_none(self):
        # Acciones, CEDEARs, FCI, bonos largos, CER → NO son letras.
        for sym in ("GGAL", "AAPL", "MELI", "AL30", "AE38", "T2X5", "COCORMA",
                    "SBSACAR", "YPFD", "TECO2", "", None):
            self.assertIsNone(letra_maturity(sym), sym)

    def test_dia_invalido_no_es_letra(self):
        self.assertIsNone(letra_maturity("S31F5"))   # 31 de febrero no existe

    def test_synth_roundtrip(self):
        # synth desde fecha → ticker que letra_maturity vuelve a decodificar.
        for iso in ("2024-11-11", "2024-12-13", "2025-01-17", "2026-03-16"):
            t = synth_letra_ticker(iso)
            self.assertIsNotNone(t)
            self.assertEqual(letra_maturity(t), iso, iso)

    def test_maturity_from_name(self):
        self.assertEqual(maturity_from_name("LT REP ARGENTINA CAP V11/11/24 $ CG"), "2024-11-11")
        self.assertEqual(maturity_from_name("BONO TESORO $ AJ. CER 4,25% V.14/02/25 (T2X5)"), "2025-02-14")
        self.assertEqual(maturity_from_name("LETRAS DEL TESORO CAP $ 14/02/25  (S14F5)"), "2025-02-14")
        self.assertIsNone(maturity_from_name("GRUPO FINANCIERO GALICIA (GGAL)"))

    def test_is_bond_like_name(self):
        self.assertTrue(is_bond_like_name("LT REP ARGENTINA CAP V11/11/24 $ CG"))
        self.assertTrue(is_bond_like_name("LETRAS DEL TESORO CAP $ V31/07/25 (S31L5)"))
        self.assertFalse(is_bond_like_name("CEDEAR APPLE INC. (AAPL)"))


class TestCocosSynthTicker(unittest.TestCase):
    HEADER = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
              "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total")

    def test_letra_sin_ticker_recibe_synth(self):
        # "LT REP ARGENTINA CAP V11/11/24" no trae (TICKER) → antes activo=''.
        # Ahora recibe un ticker sintético decodable, distinto por vencimiento.
        csv = (self.HEADER + "\n"
               "1;;16-10-2024;17-10-2024;Compra;LT REP ARGENTINA CAP V11/11/24 $ CG;"
               "ARS;BYMA;89148;105,942;-94.445,17;0;-0,94;0;0;-94.446,11\n")
        r = CocosParser().parse(csv)
        self.assertEqual(len(r.raw_rows), 1)
        activo = r.raw_rows[0].data["activo"]
        self.assertTrue(activo, "el activo no debería quedar vacío")
        self.assertEqual(letra_maturity(activo), "2024-11-11")


def _seed_position(conn, uid, broker, asset, qty, *, linked):
    """Crea una posición y, si linked, la vincula como creada por un import."""
    cur = conn.execute(
        "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested) "
        "VALUES (?,?,?,0,?,?)", (uid, broker, asset, qty, qty),
    )
    pid = cur.lastrowid
    if linked:
        # raw_row_id NULL: tiene FK a import_raw_rows; el sweep linkea por
        # position_id, así que no necesitamos una raw row real.
        conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            ("batch_sweep_test", None, pid),
        )
    return pid


class TestSweep(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_batches",
                  "positions", "brokers", "users"):
            conn.execute(f"DELETE FROM {t}")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("sweep@rendi.test", "x"),
        )
        self.uid = cur.lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Cocos", "ARS"))
        conn.execute(
            """INSERT INTO import_batches
                 (id, user_id, broker, parser_format, file_name, file_hash,
                  total_rows, valid_rows, invalid_rows, status, route_by_currency, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            ("batch_sweep_test", self.uid, "Cocos", "cocos", "x.csv", "hash",
             1, 1, 0, "confirmed", 0),
        )
        conn.commit()
        conn.close()

    def test_cierra_vencidas_respeta_vivas_y_manuales(self):
        conn = main.get_db()
        try:
            # Vencida + import → se cierra
            _seed_position(conn, self.uid, "Cocos", "S31O5", 12_147_939, linked=True)
            # No vencida (S17A6 = abr 2026) con ref_date oct 2025 → se mantiene
            _seed_position(conn, self.uid, "Cocos", "S17A6", 1_406_983, linked=True)
            # Letra vencida pero MANUAL (sin link) → no se toca
            _seed_position(conn, self.uid, "Cocos", "S15G5", 4_059_048, linked=False)
            # No-letra (acción) vencida-irrelevante → se mantiene
            _seed_position(conn, self.uid, "Cocos", "GGAL", 228, linked=True)
            conn.commit()

            res = sweep_matured_letras(conn, self.uid, ref_date="2025-10-31")
            swept = {s["asset"] for s in res["swept"]}
            self.assertEqual(swept, {"S31O5"})

            remaining = {r["asset"] for r in conn.execute(
                "SELECT asset FROM positions WHERE user_id=? AND is_cash=0", (self.uid,),
            ).fetchall()}
            self.assertEqual(remaining, {"S17A6", "S15G5", "GGAL"})
        finally:
            conn.close()

    def test_idempotente(self):
        conn = main.get_db()
        try:
            _seed_position(conn, self.uid, "Cocos", "S31L5", 2_801_539, linked=True)
            conn.commit()
            r1 = sweep_matured_letras(conn, self.uid, ref_date="2025-12-31")
            r2 = sweep_matured_letras(conn, self.uid, ref_date="2025-12-31")
            self.assertEqual(len(r1["swept"]), 1)
            self.assertEqual(len(r2["swept"]), 0)  # ya no queda nada que cerrar
        finally:
            conn.close()

    def test_cierra_bono_por_nombre_del_instrumento(self):
        # T2X5 (Boncer) no matchea el patrón de letra, pero su NOMBRE trae el
        # vencimiento ("V.14/02/25") → el sweep lo cierra vía maturity_from_name.
        conn = main.get_db()
        try:
            pid = _seed_position(conn, self.uid, "Cocos", "T2X5", 27_286, linked=True)
            conn.execute(
                "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) "
                "VALUES (?,?,?,?)", ("batch_sweep_test", 1, "{}", "confirmed"),
            )
            rrid = conn.execute("SELECT id FROM import_raw_rows LIMIT 1").fetchone()["id"]
            conn.execute(
                """INSERT INTO import_normalized_tx
                     (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name)
                   VALUES (?,?,?,?,?,?,?)""",
                ("batch_sweep_test", rrid, "2025-01-23", "Cocos", "BUY", "T2X5",
                 "BONO TESORO $ AJ. CER 4,25% V.14/02/25 (T2X5)"),
            )
            conn.commit()
            res = sweep_matured_letras(conn, self.uid, ref_date="2026-06-25")
            self.assertEqual({s["asset"] for s in res["swept"]}, {"T2X5"})
            n = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0",
                             (self.uid,)).fetchone()["c"]
            self.assertEqual(n, 0)
        finally:
            conn.close()

    def test_ventana_de_datos_no_cierra_futuras(self):
        # Si la data del usuario termina antes del vencimiento, la letra sigue viva.
        conn = main.get_db()
        try:
            _seed_position(conn, self.uid, "Cocos", "S31O5", 100, linked=True)  # vence 31/10/25
            conn.commit()
            res = sweep_matured_letras(conn, self.uid, ref_date="2025-06-30")  # data hasta jun
            self.assertEqual(res["swept"], [])
            n = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=?", (self.uid,)).fetchone()["c"]
            self.assertEqual(n, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
