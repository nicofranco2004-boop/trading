"""Traspaso de títulos de un broker a otro: el papel no puede quedar en los dos.

Caso real (Agustín Sapino, 2026-09-10): operó en Bull Market hasta 2024 y se
llevó los TÍTULOS a Balanz. Bull Market no declara que salieron —su export es el
libro de caja, y mover papeles no mueve plata—, sólo deja el gasto del trámite
("GTOS. TRANS. TITULOS"). Resultado: 9 títulos abiertos en los DOS brokers a la
vez, $8.493.784 de "capital aportado" que eran los papeles que trajo, y los
$5.650.621 (+232 %) que ganó en Bull Market sin aparecer en ningún lado.

El cierre se hace AL VALOR DEL PASE: el tramo viejo realiza su resultado en el
broker de origen y el nuevo arranca desde ahí, así los dos suman el rendimiento
completo; y el retiro del origen netea contra el depósito del destino para que
el aporte no se cuente dos veces.

Los tests corren el PIPELINE COMPLETO (preview → confirm → persist → rebuild)
porque el mecanismo depende de tres cosas que un test de unidad no ve: que las
filas sintéticas se guarden con su fila cruda, que la aprobación las filtre, y
que el rebuild no las reviva desde la tabla.

La segunda mitad del archivo son los CUATRO defectos que salieron de auditar
este mismo código. Los dos primeros habrían cerrado posiciones que el usuario SÍ
tiene, que es el error grave de todo esto.

Corre con: cd backend && python3 -m pytest tests/test_traspaso_entre_brokers.py
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

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
from importing import tenencia as _ten
from importing import traspasos as tr
from importing.schema import NormalizedTx
import main


# ── El broker VIEJO: compra 7 VIST y el 22/01 paga el gasto del traspaso ──────
VIEJO = (
    "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
    "03/01/23;COBA;6668;-500000;;;CREDITO CTA. CTE.\n"
    "10/05/23;CPRA;1753959;67957,11;;;7.0000  VIST\n"
    "22/01/24;DTRT;257047;1210;;;GTOS. TRANS. TITULOS\n"
).encode("utf-8")

# El mismo archivo SIN el gasto: sin señal de salida no se toca nada.
VIEJO_SIN_SENAL = VIEJO.replace(
    b"22/01/24;DTRT;257047;1210;;;GTOS. TRANS. TITULOS\n", b"")

# ── El broker NUEVO: recibe 21 VIST el 22/01 (ratio del CEDEAR x3) ───────────
BHDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
        "Liquidacion,Moneda,Importe\n")
NUEVO = (BHDR +
    "Recibo de Cobro / 1,,,2024-01-20,0,-1,2024-01-20,Pesos,1000000\n"
    "Transferencia Externa (Crédito) / CEDEAR Vista,VIST,Cedears,"
    "2024-01-22,21,13492,2024-01-22,,0\n"
).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class _Base(unittest.TestCase):
    VIEJO_N, NUEVO_N = "Bull Market", "Balanz"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("traspaso@rendi.test", "x")).lastrowid
        for b in (self.VIEJO_N, self.NUEVO_N):
            self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                              (self.uid, b, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def importar(self, data, broker, fmt, aprobar=None, nombre="f.csv"):
        """Replica el camino del endpoint: lo que no se aprueba se BORRA de
        import_normalized_tx — si sólo se filtra la lista en memoria, el rebuild
        lo revive desde la tabla y el test certifica lo contrario de la verdad."""
        with self.conn:
            p = pl.run_preview(self.conn, uid=self.uid, file_bytes=data,
                               file_name=nombre, broker_hint=broker, parser_format=fmt)
        sid = p["session_id"]
        propuestos = [dict(r) for r in self.conn.execute(
            "SELECT broker, asset_symbol, quantity, gross_amount FROM import_normalized_tx "
            "WHERE batch_id=? AND operation_type='SELL' AND notes LIKE '%requiere-aprobacion%'",
            (sid,)).fetchall()]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ap = {str(x).upper() for x in (aprobar or [])}
            skip = {t.row_index for t in txs
                    if _ten.requiere_aprobacion(t.notes)
                    and (t.asset_symbol or "").upper() not in ap}
            skip |= pl.already_imported_row_indices(
                self.conn, self.uid, sid, txs, already_skipped=skip)
            if skip:
                txs = [t for t in txs if t.row_index not in skip]
                ph = ",".join("?" * len(skip))
                self.conn.execute(
                    f"""DELETE FROM import_normalized_tx WHERE batch_id=? AND raw_row_id IN
                        (SELECT id FROM import_raw_rows WHERE batch_id=? AND row_index IN ({ph}))""",
                    (sid, sid, *skip))
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(
                self.conn, self.uid, sid,
                tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))
        return propuestos

    def qty(self, broker, activo):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
            (self.uid, broker, activo)).fetchone()
        return float(r["q"] or 0)


class ElPapelNoQuedaEnLosDosBrokers(_Base):
    def test_sin_aprobar_no_se_toca_nada(self):
        """El freno que importa: falla CERRADO. Aunque la pantalla no implemente
        nada, el default es NO aplicar."""
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=[])
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 7.0,
                         "se cerró la posición sin que nadie la aprobara")

    def test_aprobando_el_papel_se_va_del_broker_viejo(self):
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=["VIST"])
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 0.0)
        self.assertEqual(self.qty(self.NUEVO_N, "VIST"), 21.0,
                         "el broker nuevo tiene que conservar lo que recibió")

    def test_se_propone_con_su_motivo(self):
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        prop = self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=[])
        self.assertEqual(len(prop), 1)
        self.assertEqual(prop[0]["broker"], self.VIEJO_N)
        self.assertEqual(prop[0]["asset_symbol"], "VIST")

    def test_sin_senal_de_salida_no_se_toca_nada(self):
        """Tener el mismo papel en dos brokers es normalísimo. Sin la marca de
        que de ahí salieron títulos, no se cierra nada."""
        self.importar(VIEJO_SIN_SENAL, self.VIEJO_N, "bullmarket")
        prop = self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=["VIST"])
        self.assertEqual(prop, [], "cerró sin señal de salida")
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 7.0)

    def test_el_cambio_de_ratio_no_lo_confunde(self):
        """Salieron 7 y entraron 21 (el CEDEAR cambió de ratio). Se cierra lo que
        el ORIGEN tenía abierto, no la cantidad del destino."""
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        prop = self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=["VIST"])
        self.assertEqual(float(prop[0]["quantity"]), 7.0)

    def test_funciona_en_los_dos_ORDENES_de_importacion(self):
        """El caso real: el usuario ya tenía el broker NUEVO cargado y sube el
        viejo después. La entrada está en un lote ya confirmado."""
        self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos")
        prop = self.importar(VIEJO, self.VIEJO_N, "bullmarket", aprobar=["VIST"])
        self.assertEqual(len(prop), 1, "no detectó el traspaso al revés")
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 0.0)
        self.assertEqual(self.qty(self.NUEVO_N, "VIST"), 21.0)


class LoQueEncontroAuditarEsteCodigo(_Base):
    """Los cuatro defectos que salieron de auditar el propio fix."""

    def test_1_no_confunde_una_ENTRADA_de_titulos_con_una_salida(self):
        # El patrón matcheaba "TRANSFERENCIA DE TITULOS RECIBIDOS" —una ENTRADA—
        # y esa alternativa no salía de ningún archivo real: la inventé. Tomar
        # una entrada por salida cierra posiciones que el usuario SÍ tiene.
        for texto in ("TRANSFERENCIA DE TITULOS RECIBIDOS",
                      "Transferencia de títulos (ingreso)",
                      "TRANSFERENCIA VIA MEP"):
            self.assertFalse(tr._SENAL_SALIDA.search(tr._norm(texto)), texto)
        self.assertTrue(tr._SENAL_SALIDA.search(tr._norm("GTOS. TRANS. TITULOS")))

    def test_1b_ademas_del_texto_tiene_que_ser_una_COMISION(self):
        # Segundo freno del mismo punto: un gasto de traspaso siempre se importa
        # como comisión; una entrada de títulos, nunca.
        t = NormalizedTx(row_index=1, date="2024-01-22", broker="X",
                         operation_type="DEPOSIT", gross_amount=1,
                         notes="GTOS. TRANS. TITULOS")
        self.assertEqual(tr.senales_del_lote([t]), set())
        t.operation_type = "FEE"
        self.assertEqual(tr.senales_del_lote([t]), {("X", "2024-01-22")})

    def test_2_no_cierra_el_sub_broker_del_PROPIO_destino(self):
        # "Balanz" y "Balanz · USD" son el MISMO broker partido por moneda: una
        # entrada a uno no puede cerrar la posición del otro.
        pid = self.conn.execute(
            "SELECT id FROM brokers WHERE user_id=? AND name=?",
            (self.uid, self.NUEVO_N)).fetchone()["id"]
        sib = f"{self.NUEVO_N} · USD"
        self.conn.execute(
            "INSERT INTO brokers (user_id,name,currency,parent_broker_id) VALUES (?,?,?,?)",
            (self.uid, sib, "USDT", pid))
        self.conn.commit()
        entrada = NormalizedTx(row_index=1, date="2024-01-22", broker=self.NUEVO_N,
                               operation_type="BUY", asset_symbol="VIST", quantity=21,
                               gross_amount=283332, currency="ARS")
        entrada.transfer_in = True
        gasto = NormalizedTx(row_index=2, date="2024-01-22", broker=sib,
                             operation_type="FEE", gross_amount=1, currency="ARS",
                             notes="GTOS. TRANS. TITULOS")
        r = tr.cerrar_origen_de_traspasos(
            self.conn, self.uid, [entrada, gasto], {(sib, "VIST"): 21.0})
        self.assertEqual(r, [], "le cerró la posición de su propio sub-broker")

    def test_3_re_importar_el_mismo_archivo_no_cierra_de_nuevo(self):
        # Sin el freno, la segunda importación volvía a proponer los cierres y
        # descontaba DE NUEVO lo ya cerrado.
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=["VIST"])
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 0.0)
        prop = self.importar(VIEJO, self.VIEJO_N, "bullmarket", aprobar=["VIST"])
        self.assertEqual(prop, [], "propuso cerrar un traspaso que ya estaba cerrado")
        self.assertEqual(self.qty(self.VIEJO_N, "VIST"), 0.0)

    def test_4_el_SQL_no_usa_la_forma_que_Postgres_rechaza(self):
        # `IS NOT ''` lo acepta SQLite y lo rechaza Postgres, que es a donde va
        # la base. Nadie más en el repo lo usa.
        src = open(os.path.join(BACKEND, "importing", "traspasos.py"),
                   encoding="utf-8").read()
        self.assertNotIn("IS NOT ''", src)

    def test_el_retiro_lleva_ticker_para_poder_aprobarse(self):
        # La aprobación se pide POR TICKER. Un retiro sin ticker nunca queda
        # aprobado → se aplicaba la venta sin su retiro y el capital aportado
        # quedaba contado dos veces, que es justo lo que esto arregla.
        self.importar(VIEJO, self.VIEJO_N, "bullmarket")
        self.importar(NUEVO, self.NUEVO_N, "balanz_movimientos", aprobar=["VIST"])
        r = self.conn.execute(
            """SELECT COUNT(*) n FROM import_normalized_tx n
                 JOIN import_batches b ON b.id=n.batch_id
                WHERE b.user_id=? AND n.operation_type='WITHDRAW'
                  AND COALESCE(n.notes,'') LIKE ?""",
            (self.uid, f"%{tr.MARCA_TRASPASO}%")).fetchone()
        self.assertEqual(int(r["n"]), 1,
                         "el retiro que acompaña a la venta no se aplicó")


if __name__ == "__main__":
    unittest.main()
