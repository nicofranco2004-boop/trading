"""E2E del layout "Histórico compacto" de Bull Market — el CSV que el broker
MANDA POR MAIL cuando el portal no deja bajar toda la historia (reporte de un
usuario, 2026-09-09). Antes Rendi lo rechazaba entero: "no parece un export de
Bull Market".

Este test NO llama al parser y listo: atraviesa el MISMO camino que producción
(run_preview → load_session_for_confirm → persist_batch → rebuild FIFO), porque
lo que hay que probar no es que las filas se lean, sino que la plata termine en
la moneda y la cuenta correctas después de que el recálculo pase por encima.

Lo que certifica:
  1. El archivo se acepta y se autodetecta como Bull Market.
  2. Una fila con `Mda` lleno es plata EN DÓLARES: entra al broker en dólares por
     el monto de la columna `Dolares` — NO por el equivalente en pesos al dólar
     oficial que el mismo archivo trae en `Importe` (1.000 dólares, no 1.061.510
     pesos).
  3. El dólar MEP (las dos patas del bono) se colapsa en UNA conversión: no
     infla el capital aportado ni deja el bono como tenencia fantasma.
  4. Un CPU$ sin contraparte en pesos NO es una conversión: es una compra real
     en dólares y queda como posición.

Corre con: cd backend && python3 -m pytest tests/test_bullmarket_historico_compacto_e2e.py
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
from importing.parsers.registry import autodetect
import main


# Datos SINTÉTICOS con la forma exacta del archivo real (no de nadie).
HC = (
    "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
    "02/01/23;COBA;6668;-500000;;;CREDITO CTA. CTE.\n"
    # Compra común en pesos (el precio se deriva: 120000 / 100 = 1200).
    "03/01/23;CPRA;21126;120000;;;100.0000  ALUA\n"
    # Dólar MEP: sale plata en pesos (CPRA) y entran dólares (VTU$). El
    # `Importe` de la pata dólar es el equivalente al oficial → se ignora.
    "03/02/23;CPRA;21127;99000;;;833.0000  GD30\n"
    "04/02/23;VTU$;33940;-43118,28;-300;DOLAR;833.0000- GD30\n"
    # Cobro EN DÓLARES: US$1.000. En pesos el archivo dice 1.061.510,37 (dólar
    # oficial): si tomáramos esa columna, el depósito quedaría 1000× inflado.
    "28/12/23;CDOA;153020;-1061510,37;-1000;DOLAR;CREDITO CTA. CTE.\n"
    # CPU$ SUELTO: compra de verdad en dólares (US$250 por 1.000 nominales).
    "03/08/24;CPU$;3449524;70054,6;250;DOLAR;1,000.0000  AL30\n"
    # Pie del export: totales + leyenda (sin fecha).
    ";Total;;0;;;\n"
    ";;;0;;;COBA   RECIBO DE COBRO\n"
    ";;;0;;;CPRA   COMPRA\n"
).encode("utf-8")


# Período ANTERIOR del mismo pedido al broker: cierra con 1.000 pesos, que son
# los mismos 1.000 con los que abre el `S.ANTERIOR` de HC_CON_SALDO.
HC_PREVIO = (
    "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
    "11/04/21;COBA;145726;-5000;;;CREDITO CTA. CTE.\n"
    "15/04/21;PAGA;145727;4000;;;TRANSFERENCIA VIA MEP\n"
).encode("utf-8")

HC_CON_SALDO = (
    "F.Liquid;Cpbt;N.Cpbt;Importe;Dolares;Mda;Ref./Cantidad\n"
    ";S.ANT;ERIOR;-1000;;;\n"
    "02/01/23;COBA;6668;-500000;;;CREDITO CTA. CTE.\n"
).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    h._recalc_pnl_realized_from_ops = main._recalc_pnl_realized_from_ops
    return h


class BullMarketHistoricoCompactoE2E(unittest.TestCase):
    BROKER = "Bull Market"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("bm_hc@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _import(self):
        return self._import_bytes(HC)

    def _import_bytes(self, blob):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=blob, file_name="HC12345.CSV",
                broker_hint=self.BROKER, parser_format="bullmarket")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(
                self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return payload

    def _held(self, asset):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()
        return float(r["q"] or 0)

    def _brokers(self):
        return {r["name"]: (r["currency"] or "").upper() for r in self.conn.execute(
            "SELECT name, currency FROM brokers WHERE user_id=?", (self.uid,))}

    def test_autodetecta_como_bull_market(self):
        # Regresión: el gate pedía la columna `Especie`, que este layout no trae
        # → ningún parser lo agarraba y el usuario veía "archivo no válido".
        p = autodetect(HC.decode("utf-8").split("\n")[0].split(";"))
        self.assertIsNotNone(p)
        self.assertEqual(p.format_id, "bullmarket")

    def test_preview_sin_errores(self):
        payload = self._import()
        self.assertEqual(payload.get("errors") or [], [])

    def test_la_plata_en_dolares_entra_en_dolares(self):
        self._import()
        # El cobro de US$1.000 tiene que aparecer como 1.000 dólares en la cuenta
        # en dólares — NO como los 1.061.510,37 pesos que el archivo muestra al
        # lado (equivalente al dólar oficial, informativo).
        # El efectivo de una cuenta vive en positions.invested de la fila is_cash.
        cash = {(r["broker"], r["asset"]): float(r["invested"] or 0)
                for r in self.conn.execute(
                    "SELECT broker, asset, invested FROM positions "
                    "WHERE user_id=? AND is_cash=1", (self.uid,))}
        usd_total = sum(v for (_b, a), v in cash.items()
                        if a.upper() in ("USD", "USDT", "U$S"))
        ars_total = sum(v for (_b, a), v in cash.items() if a.upper() == "ARS")
        # 1000 del cobro + 300 del MEP − 250 de la compra del AL30 = 1050.
        self.assertAlmostEqual(usd_total, 1050.0, places=2)
        # Pesos: 500.000 del recibo − 120.000 del ALUA − 99.000 que se fueron en
        # el MEP = 281.000. Los 1.061.510 del cobro en dólares NO son pesos.
        self.assertAlmostEqual(ars_total, 281000.0, places=2)
        self.assertNotIn(1061510.37, [round(v, 2) for v in cash.values()])
        # Y la cuenta en dólares existe como hermana de la de pesos.
        self.assertIn("Bull Market · USD", self._brokers())

    def test_el_mep_no_deja_bono_fantasma_ni_infla_el_aportado(self):
        self._import()
        # El GD30 de la conversión netea a 0 (no es tenencia).
        self.assertAlmostEqual(self._held("GD30"), 0.0, places=6)
        # La conversión no se persiste como depósito/retiro: el capital aportado
        # sale sólo del recibo de cobro en pesos y del cobro en dólares.
        tipos = [r["op_type"] for r in self.conn.execute(
            "SELECT op_type FROM operations WHERE user_id=?", (self.uid,))]
        self.assertTrue(any("CONVERSION" in (t or "").upper() for t in tipos), tipos)
        # …y ninguna de las dos patas quedó como compra/venta del bono.
        self.assertNotIn("GD30", {r["asset"] for r in self.conn.execute(
            "SELECT asset FROM operations WHERE user_id=?", (self.uid,))})

    def test_pata_dolar_suelta_queda_como_posicion(self):
        self._import()
        # El CPU$ sin contraparte en pesos es una compra real: 1.000 nominales.
        self.assertAlmostEqual(self._held("AL30"), 1000.0, places=6)

    def _cash_ars(self):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions "
            "WHERE user_id=? AND is_cash=1 AND asset='ARS'", (self.uid,)).fetchone()
        return float(r["v"] or 0)

    def test_saldo_de_apertura_no_se_cuenta_dos_veces_subiendo_de_a_uno(self):
        # Bull Market manda la historia PARTIDA. Si el usuario sube los archivos
        # de a uno, el saldo de apertura del segundo ya está contado como
        # movimientos en el primero. El parser sólo ve un archivo por vez, así
        # que el corte lo hace el pipeline, que sí puede mirar la base.
        self._import_bytes(HC_PREVIO)
        self.assertAlmostEqual(self._cash_ars(), 1000.0, places=2)
        payload = self._import_bytes(HC_CON_SALDO)
        # Sólo entra el recibo de cobro; el "Saldo anterior" se cae.
        self.assertEqual(payload["summary"]["valid_rows"], 1)
        self.assertAlmostEqual(self._cash_ars(), 501000.0, places=2)

    def test_saldo_de_apertura_si_entra_cuando_es_el_principio(self):
        # El mismo archivo, pero SIN historia previa: acá el saldo de apertura
        # es real y tiene que entrar, o el efectivo arranca corrido.
        payload = self._import_bytes(HC_CON_SALDO)
        self.assertEqual(payload["summary"]["valid_rows"], 2)
        self.assertAlmostEqual(self._cash_ars(), 501000.0, places=2)


if __name__ == "__main__":
    unittest.main()
