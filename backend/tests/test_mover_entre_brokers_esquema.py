"""«Mover a otro broker», etapa 1: el esquema y la ida y vuelta por la base.

Un pase entre dos brokers del usuario escribe sus filas con
`pipeline.store_preview_txs` y el confirm las vuelve a leer con
`pipeline.load_session_for_confirm` (no de la lista en memoria). Las seis columnas
nuevas de `import_normalized_tx` —traspaso_id, fecha_compra, valor_usd, valor_ars,
costo_usd, costo_nativo— tienen que hacer ese viaje enteras: si una se cae en el
camino, el persister no reconoce las patas del pase (sin traspaso_id), el lote del
destino pierde su compra original (sin fecha_compra) o no hay patas de capital (sin
V ni C). Es la misma familia que tc_compra y asset_symbol_raw, que se guardaban y
no volvían.

Y la otra mitad: una base SQLite que ya existía antes de esta etapa (sin las seis
columnas, sin `positions.en_broker_desde` y sin la tabla `traspasos_a_mano`) las
recibe al arrancar, sin perder lo que tenía. Una base NUEVA nace completa y no
puede fallar nunca: por eso acá se FABRICA la base vieja antes de correr init_db().

Corre con: cd backend && python3 -m pytest tests/test_mover_entre_brokers_esquema.py
"""
import os
import sys
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from importing import pipeline as pl  # noqa: E402
from importing import normalizer  # noqa: E402
from importing.schema import (  # noqa: E402
    NormalizedTx, OP_BUY, OP_SELL, OP_FEE, OP_DEPOSIT,
    OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA, OPERATION_TYPES_INTERNOS,
    OPERATION_TYPES, OP_TYPE_ALIASES,
)

CAMPOS_DEL_PASE = ("traspaso_id", "fecha_compra", "valor_usd", "valor_ars",
                   "costo_usd", "costo_nativo")

COLUMNAS_TRASPASOS_A_MANO = {
    "id", "user_id", "lote_salida", "lote_entrada", "fecha", "asset", "cantidad",
    "moneda", "receta_json", "creado_at", "deshecho_at", "desfasado_at",
    "desfasado_motivo", "omitidas_json",
}

PASE = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def _filas_de_un_pase():
    """Las filas que escribe un pase (A.6 de la especificación), con números que no
    se confunden entre sí: si una columna se cruza con otra, el test lo ve. Y una
    fila común (un depósito) que no es de ningún pase: tiene que volver con None."""
    return [
        # Salida de lotes importados: SELL transfer_out a precio 0, con la inversión
        # movida SIN comisiones en costo_nativo.
        NormalizedTx(row_index=-49999, date="2026-11-20", broker="Cocos",
                     operation_type=OP_SELL, asset_symbol="NVDA", asset_type="CEDEAR",
                     quantity=4.0, unit_price=0.0, gross_amount=0.0, fees=0.0,
                     currency="ARS", transfer_out=True, traspaso_id=PASE,
                     costo_nativo=120000.0,
                     notes="Traspaso a otro broker tuyo el 20/11/2026 — sale al costo, sin ganancia"),
        # Pata de salida: V y C, sin gross_amount.
        NormalizedTx(row_index=-49998, date="2026-11-20", broker="Cocos",
                     operation_type=OP_TRASPASO_SALIDA, asset_symbol="NVDA",
                     asset_type="CEDEAR", quantity=4.0, unit_price=62500.0,
                     gross_amount=None, fees=0.0, currency="ARS", traspaso_id=PASE,
                     valor_usd=178.57, valor_ars=250000.0, costo_usd=92.3,
                     costo_nativo=120600.0,
                     notes="Salieron 4 NVDA a otro broker tuyo (valor del día)"),
        # Gasto del pase: valor_usd = el gasto en USD.
        NormalizedTx(row_index=-49997, date="2026-11-20", broker="Cocos",
                     operation_type=OP_FEE, gross_amount=5000.0, fees=0.0,
                     currency="ARS", traspaso_id=PASE, valor_usd=3.57,
                     notes="Costo del pase de NVDA a otro broker tuyo"),
        # Llegada al destino: BUY con la fecha de compra original.
        NormalizedTx(row_index=-49996, date="2026-11-20", broker="Balanz",
                     operation_type=OP_BUY, asset_symbol="NVDA", asset_type="CEDEAR",
                     quantity=4.0, unit_price=30000.0, gross_amount=120000.0,
                     fees=600.0, currency="ARS", tc_compra=1150.0, traspaso_id=PASE,
                     fecha_compra="2024-03-15",
                     notes="Llegó desde otro broker tuyo el 20/11/2026 · compra original del 15/03/2024"),
        # Pata de entrada: los mismos cuatro números que su par.
        NormalizedTx(row_index=-49995, date="2026-11-20", broker="Balanz",
                     operation_type=OP_TRASPASO_ENTRADA, asset_symbol="NVDA",
                     asset_type="CEDEAR", quantity=4.0, unit_price=62500.0,
                     gross_amount=None, fees=0.0, currency="ARS", traspaso_id=PASE,
                     valor_usd=178.57, valor_ars=250000.0, costo_usd=92.3,
                     costo_nativo=120600.0,
                     notes="Entraron 4 NVDA desde otro broker tuyo (valor del día)"),
        # Una fila que no es de ningún pase.
        NormalizedTx(row_index=-49994, date="2026-11-19", broker="Cocos",
                     operation_type=OP_DEPOSIT, gross_amount=1000.0, currency="ARS"),
    ]


class _ConUsuario(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        try:
            self.uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                (f"pase-esquema-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
            for nombre in ("Cocos", "Balanz"):
                conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                             (self.uid, nombre, "ARS"))
            conn.commit()
        finally:
            conn.close()

    def _ida_y_vuelta(self):
        """Guarda las filas como lo hará el pase y las relee como lo hace el confirm.
        Devuelve (lo que se mandó, lo que quedó en la base, lo que volvió)."""
        txs = _filas_de_un_pase()
        conn = main.get_db()
        try:
            sid = pl.store_preview_txs(conn, self.uid, broker="Cocos",
                                       parser_format="traspaso_a_mano",
                                       file_name="Pase entre brokers", txs=txs)
            conn.commit()
            en_la_base = [dict(r) for r in conn.execute(
                f"SELECT r.row_index, {', '.join('n.' + c for c in CAMPOS_DEL_PASE)} "
                "  FROM import_normalized_tx n JOIN import_raw_rows r ON r.id = n.raw_row_id "
                " WHERE n.batch_id=? ORDER BY n.id", (sid,)).fetchall()]
            volvieron, raw_por_indice = pl.load_session_for_confirm(
                conn, uid=self.uid, session_id=sid)
        finally:
            conn.close()
        return txs, en_la_base, volvieron, raw_por_indice

    def _comparar(self, mandadas, en_la_base, volvieron):
        self.assertEqual(len(volvieron), len(mandadas))
        self.assertEqual(len(en_la_base), len(mandadas))
        por_indice = {t.row_index: t for t in mandadas}
        for fila in en_la_base:
            t = por_indice[fila["row_index"]]
            for c in CAMPOS_DEL_PASE:
                self.assertEqual(fila[c], getattr(t, c),
                                 f"fila {t.row_index} ({t.operation_type}): la columna {c} "
                                 "no quedó en import_normalized_tx como se mandó")
        for v in volvieron:
            t = por_indice[v.row_index]
            for c in CAMPOS_DEL_PASE:
                self.assertEqual(getattr(v, c), getattr(t, c),
                                 f"fila {t.row_index} ({t.operation_type}): {c} no volvió "
                                 "en load_session_for_confirm")
            # Lo de antes sigue viajando igual (que sumar columnas no corra ninguna).
            self.assertEqual(v.operation_type, t.operation_type)
            self.assertEqual(v.broker, t.broker)
            self.assertEqual(v.gross_amount, t.gross_amount)
            self.assertEqual(v.transfer_out, t.transfer_out)
            self.assertEqual(v.tc_compra, t.tc_compra)
            self.assertEqual(v.notes, t.notes)


class IdaYVueltaPorLaBase(_ConUsuario):

    def test_las_seis_columnas_del_pase_van_y_vuelven(self):
        mandadas, en_la_base, volvieron, _raw = self._ida_y_vuelta()
        self._comparar(mandadas, en_la_base, volvieron)
        # Y en concreto, lo que cada lector va a necesitar:
        por_op = {}
        for v in volvieron:
            por_op.setdefault(v.operation_type, []).append(v)
        self.assertEqual({v.traspaso_id for v in volvieron if v.operation_type != OP_DEPOSIT},
                         {PASE}, "todas las filas del pase llevan su id")
        self.assertEqual(por_op[OP_BUY][0].fecha_compra, "2024-03-15")
        self.assertEqual(por_op[OP_SELL][0].costo_nativo, 120000.0)
        self.assertEqual(por_op[OP_FEE][0].valor_usd, 3.57)
        salida, entrada = por_op[OP_TRASPASO_SALIDA][0], por_op[OP_TRASPASO_ENTRADA][0]
        self.assertIsNone(salida.gross_amount, "el valor del pase NO va en gross_amount")
        self.assertIsNone(salida.gross_amount_usd, "ni en gross_amount_usd (lo pisa el reestampado)")
        self.assertEqual((salida.valor_usd, salida.valor_ars, salida.costo_usd, salida.costo_nativo),
                         (entrada.valor_usd, entrada.valor_ars, entrada.costo_usd, entrada.costo_nativo))

    def test_una_fila_que_no_es_de_un_pase_vuelve_sin_nada(self):
        _m, _b, volvieron, _raw = self._ida_y_vuelta()
        deposito = [v for v in volvieron if v.operation_type == OP_DEPOSIT]
        self.assertEqual(len(deposito), 1)
        for c in CAMPOS_DEL_PASE:
            self.assertIsNone(getattr(deposito[0], c), c)

    def test_el_lote_queda_en_preview_con_su_formato(self):
        """El pase lo confirma después `persist_batch`: store_preview_txs lo deja en
        'preview', sin ruteo por moneda (el broker de cada fila va tal cual)."""
        _m, _b, volvieron, raw = self._ida_y_vuelta()
        self.assertEqual(len(raw), len(volvieron))
        conn = main.get_db()
        try:
            lotes = [dict(r) for r in conn.execute(
                "SELECT status, parser_format, route_by_currency, broker FROM import_batches "
                " WHERE user_id=?", (self.uid,)).fetchall()]
        finally:
            conn.close()
        self.assertEqual(lotes, [{"status": "preview", "parser_format": "traspaso_a_mano",
                                  "route_by_currency": 0, "broker": "Cocos"}])


class LosTiposInternosNoLosFabricaUnArchivo(unittest.TestCase):
    """Un CSV del usuario, el genérico o el mapeo que arma la IA nunca tienen que
    poder fabricar una pata de capital (subiría el aportado de un broker sin plata)."""

    def test_no_estan_en_los_tipos_ni_en_los_alias(self):
        self.assertEqual(OPERATION_TYPES_INTERNOS, {OP_TRASPASO_SALIDA, OP_TRASPASO_ENTRADA})
        self.assertEqual(OPERATION_TYPES_INTERNOS & set(OPERATION_TYPES), set())
        self.assertEqual(OPERATION_TYPES_INTERNOS & set(OP_TYPE_ALIASES.values()), set())

    def test_un_archivo_que_dice_traspaso_salida_no_da_una_pata(self):
        for escrito in ("TRASPASO_SALIDA", "traspaso entrada", "Traspaso_Entrada"):
            self.assertNotIn(normalizer._coerce_op_type(escrito), OPERATION_TYPES_INTERNOS,
                             escrito)

    def test_los_campos_nuevos_nacen_vacios(self):
        t = NormalizedTx(row_index=1, date="2026-11-20", broker="Cocos", operation_type=OP_BUY)
        for c in CAMPOS_DEL_PASE:
            self.assertIsNone(getattr(t, c), c)


class LaRecetaDelPaseSeRenombra(unittest.TestCase):
    """`traspasos_a_mano.receta_json` está en `renombre_broker.COLUMNAS_JSON`: con la
    forma de la receta v1 (A.2 de la especificación), renombrar un broker cambia cada
    nombre guardado y no toca la fecha `en_broker_desde` de la foto de cada lote."""

    RECETA = {
        "v": 1, "broker_origen": "Cocos", "broker_destino": "Balanz", "fx_version": "v2",
        "lotes": [{
            "origen": "a_mano", "lote_id": 123, "broker": "Cocos · USD",
            "broker_destino": "Balanz · USD", "fila_origen": None,
            "fila_destino_raw_row_id": 991, "cantidad": 4.0, "invested": 120.0,
            "commissions": 1.0, "parcial": False,
            "foto": {"id": 123, "broker": "Cocos · USD", "asset": "NVDA", "quantity": 4.0,
                     "entry_date": "2024-03-15", "en_broker_desde": "2026-11-20",
                     "undo_meta_json": None},
        }],
        "gasto": {"broker": "Cocos", "monto": 5000.0, "moneda": "ARS"},
        "brokers_usd_creados": ["Balanz · USD"],
        "precio_cargado_en_destino": {"brokers_destino": ["Balanz"], "antes": None,
                                      "puesto": 25000.0},
    }

    def test_esta_en_la_lista_del_renombre(self):
        import renombre_broker
        self.assertIn(("traspasos_a_mano", "receta_json"), renombre_broker.COLUMNAS_JSON)
        self.assertEqual(main.BROKER_POR_NOMBRE["traspasos_a_mano"], ("json", "conservar"))
        self.assertIn("traspasos_a_mano", main._RESET_PORTFOLIO_TABLES)

    def test_cada_nombre_cambia_y_la_fecha_no(self):
        import json
        import renombre_broker
        texto = json.dumps(self.RECETA)
        self.assertEqual(renombre_broker.nombres_en_json(texto),
                         {"Cocos", "Balanz", "Cocos · USD", "Balanz · USD"},
                         "la fecha en_broker_desde no es un broker")
        nuevo = json.loads(renombre_broker.renombrar_en_json(texto, {
            "Cocos": "Cocos Capital", "Cocos · USD": "Cocos Capital · USD",
            "Balanz": "Balanz AR", "Balanz · USD": "Balanz AR · USD"}))
        self.assertEqual(renombre_broker.nombres_en_json(json.dumps(nuevo)),
                         {"Cocos Capital", "Balanz AR", "Cocos Capital · USD", "Balanz AR · USD"})
        self.assertEqual(nuevo["lotes"][0]["foto"]["en_broker_desde"], "2026-11-20")
        self.assertEqual(nuevo["gasto"]["broker"], "Cocos Capital")
        self.assertEqual(nuevo["brokers_usd_creados"], ["Balanz AR · USD"])

    def test_una_fecha_que_se_llama_como_el_broker_no_se_renombra(self):
        """El borde: un broker llamado como una fecha. `en_broker_desde` no es una
        clave de broker, así que la fecha queda."""
        import json
        import renombre_broker
        texto = json.dumps({"foto": {"broker": "2026-11-20", "en_broker_desde": "2026-11-20"}})
        nuevo = json.loads(renombre_broker.renombrar_en_json(texto, {"2026-11-20": "Otro"}))
        self.assertEqual(nuevo["foto"], {"broker": "Otro", "en_broker_desde": "2026-11-20"})


@unittest.skipIf(main.USANDO_PG, "Sólo SQLite: en Postgres no hay migraciones incrementales; "
                                 "manda schema_pg.sql (lo vigilan test_schema_pg_*)")
class UnaBaseViejaLasRecibeAlArrancar(_ConUsuario):
    """Se fabrica la base de antes de esta etapa sobre la base del módulo: las mismas
    tablas, sin las seis columnas, sin `positions.en_broker_desde` y sin
    `traspasos_a_mano`. Con una fila vieja en cada tabla, para ver que no se pierde."""

    def _columnas(self, conn, tabla):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}

    def setUp(self):
        super().setUp()
        conn = main.get_db()
        try:
            for c in CAMPOS_DEL_PASE:
                conn.execute(f"ALTER TABLE import_normalized_tx DROP COLUMN {c}")
            conn.execute("ALTER TABLE positions DROP COLUMN en_broker_desde")
            conn.execute("DROP TABLE traspasos_a_mano")
            # Una fila vieja en cada tabla que gana columnas.
            self.lote = f"lote-viejo-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO import_batches (id, user_id, broker, parser_format, file_name, "
                " file_hash, total_rows, valid_rows, invalid_rows, status) "
                "VALUES (?, ?, 'Cocos', 'cocos', 'viejo.csv', 'h', 1, 1, 0, 'confirmed')",
                (self.lote, self.uid))
            raw = conn.execute(
                "INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status) "
                "VALUES (?, 1, '{}', 'valid')", (self.lote,)).lastrowid
            conn.execute(
                "INSERT INTO import_normalized_tx (batch_id, raw_row_id, date, broker, "
                " operation_type, gross_amount, currency) "
                "VALUES (?, ?, '2025-01-02', 'Cocos', 'DEPOSIT', 777.0, 'ARS')", (self.lote, raw))
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, invested, entry_date) "
                "VALUES (?, 'Cocos', 'NVDA', 3, 9000, '2024-03-15')", (self.uid,))
            conn.commit()
            self.assertEqual(self._columnas(conn, "import_normalized_tx") & set(CAMPOS_DEL_PASE),
                             set(), "el setUp tiene que reproducir la base vieja")
            self.assertNotIn("en_broker_desde", self._columnas(conn, "positions"))
            self.assertEqual(self._columnas(conn, "traspasos_a_mano"), set())
        finally:
            conn.close()

    def tearDown(self):
        # La base del módulo queda completa aunque el test falle a mitad: si no,
        # las clases que corren después heredarían la base vieja.
        main.init_db()

    def test_init_db_agrega_columnas_y_tabla_sin_perder_lo_que_habia(self):
        main.init_db()
        conn = main.get_db()
        try:
            self.assertTrue(set(CAMPOS_DEL_PASE) <= self._columnas(conn, "import_normalized_tx"))
            self.assertIn("en_broker_desde", self._columnas(conn, "positions"))
            self.assertEqual(self._columnas(conn, "traspasos_a_mano"), COLUMNAS_TRASPASOS_A_MANO)
            indices = {r[1] for r in conn.execute("PRAGMA index_list(traspasos_a_mano)").fetchall()}
            self.assertIn("idx_traspasos_a_mano_user", indices)
            # Lo que había sigue ahí, con las columnas nuevas vacías.
            vieja = conn.execute(
                "SELECT gross_amount, traspaso_id, fecha_compra, valor_usd, valor_ars, "
                "       costo_usd, costo_nativo FROM import_normalized_tx WHERE batch_id=?",
                (self.lote,)).fetchone()
            self.assertEqual(tuple(vieja), (777.0, None, None, None, None, None, None))
            lote = conn.execute(
                "SELECT quantity, entry_date, en_broker_desde FROM positions "
                " WHERE user_id=? AND asset='NVDA'", (self.uid,)).fetchone()
            self.assertEqual(tuple(lote), (3, "2024-03-15", None))
        finally:
            conn.close()
        # Y la base migrada hace la ida y vuelta completa.
        mandadas, en_la_base, volvieron, _raw = self._ida_y_vuelta()
        self._comparar(mandadas, en_la_base, volvieron)

    def test_arrancar_dos_veces_no_rompe(self):
        """init_db corre en cada arranque: con todo ya agregado no hace nada."""
        main.init_db()
        main.init_db()
        conn = main.get_db()
        try:
            self.assertEqual(self._columnas(conn, "traspasos_a_mano"), COLUMNAS_TRASPASOS_A_MANO)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
