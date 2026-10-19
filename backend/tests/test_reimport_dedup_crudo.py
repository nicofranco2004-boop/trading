"""Re-importar el mismo archivo no puede duplicar los fondos ni los bonos en dólares.

EL BUG (encontrado al pasar SQ→XYZ, 2026-10-19). La huella anti-duplicados de
cada fila se arma con el ticker TAL COMO LO MANDA EL BROKER (`asset_symbol_raw`):
el de un fondo de Cocos es "COCOA", aunque Rendi lo guarde como
"FCI:cocos-ahorro-a"; el de la pata dólar de un bono es "AL30D", aunque Rendi lo
guarde como "AL30". Así quedó desde 706b74c7, para que agregar un fondo al
catálogo no cambiara la huella.

Pero el ticker del broker no viajaba a la base: la previsualización calcula la
huella con él y la guarda, y el confirm relee las filas de `import_normalized_tx`
—que no tenía esa columna— y calcula la huella con el ticker de Rendi. Las dos
huellas no coinciden nunca. Resultado: la pantalla avisa «ya estaba importada —
se omite» y el confirm la carga igual. Reimportar el mismo archivo duplicaba
cada fondo y cada compra de bono en dólares.

Entra por las MISMAS puertas que la app (`/api/imports/preview` + `/confirm`);
lo único reemplazado es el login.
"""
import io
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

from fastapi.testclient import TestClient

import main

HDR = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;instrumento;"
       "moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n")
FILAS = (
    "85601659;4608176;05-01-2026;05-01-2026;Recibo De Cobro;;ARS;;;;10.000.000;0;0;0;0;10.000.000\n"
    # Fondo: Cocos lo manda como COCOA; Rendi lo guarda como FCI:cocos-ahorro-a.
    "85601660;4608177;06-01-2026;06-01-2026;Liquidacion Suscripcion Fci;FCI COCOS AHORRO (COCOA);"
    "ARS;;100.000;10;1.000.000;0;0;0;0;-1.000.000\n"
    # Pata dólar de un bono: Cocos lo manda como AL30D; Rendi lo guarda como AL30.
    "85601661;4608178;07-01-2026;08-01-2026;Compra;BONO REP. ARGENTINA USD 2030 (AL30D);"
    "USD;BYMA;100;0,60;-60;0;0;0;0;-60\n"
    # Testigo: un CEDEAR, cuyo ticker del broker y de Rendi coinciden.
    "85601662;4608179;07-01-2026;08-01-2026;Compra;CEDEAR TESLA, INC. (TSLA);"
    "ARS;BYMA;10;44.760;-447.600;0;0;0;0;-447.600\n"
)
CSV_ENERO = (HDR + FILAS).encode("utf-8")
# El export del mes siguiente: las mismas 4 filas (se solapan) + 1 compra nueva.
CSV_FEBRERO = (HDR + FILAS +
    "85601663;4608180;03-02-2026;04-02-2026;Compra;CEDEAR TESLA, INC. (TSLA);"
    "ARS;BYMA;5;45.000;-225.000;0;0;0;0;-225.000\n").encode("utf-8")


class ReimportConTickerDelBroker(unittest.TestCase):
    BROKER = "Cocos"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("dedup_crudo@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _preview(self, csv_bytes, nombre):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", (nombre, io.BytesIO(csv_bytes), "text/csv"))],
            data={"format": "cocos", "broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _import(self, csv_bytes, nombre):
        """Previsualizar + confirmar, como el asistente de importación."""
        prev = self._preview(csv_bytes, nombre)
        r = self.client.post("/api/imports/confirm", json={"session_id": prev["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        return prev

    def _tenencia(self):
        rows = self.conn.execute(
            "SELECT asset, SUM(quantity) q FROM positions "
            "WHERE user_id=? AND is_cash=0 GROUP BY asset", (self.uid,)).fetchall()
        return {r["asset"]: round(float(r["q"] or 0), 6) for r in rows}

    def _fondo(self, tenencia):
        fci = [a for a in tenencia if a.startswith("FCI:")]
        self.assertEqual(len(fci), 1, f"esperaba un fondo en la tenencia: {tenencia}")
        return fci[0]

    def test_el_mismo_archivo_dos_veces_no_duplica(self):
        self._import(CSV_ENERO, "enero.csv")
        antes = self._tenencia()
        fondo = self._fondo(antes)
        self.assertEqual(antes[fondo], 100000.0)
        self.assertIn("AL30", antes)       # la cantidad baja por la amortización del bono
        self.assertEqual(antes.get("TSLA"), 10.0)

        self._import(CSV_ENERO, "enero_otra_vez.csv")
        self.assertEqual(self._tenencia(), antes,
                         "reimportar el mismo archivo no puede cambiar la tenencia")

    def test_el_mes_siguiente_solo_agrega_lo_nuevo(self):
        self._import(CSV_ENERO, "enero.csv")
        antes = self._tenencia()
        fondo = self._fondo(antes)
        self._import(CSV_FEBRERO, "febrero.csv")
        despues = self._tenencia()
        self.assertEqual(despues[fondo], 100000.0)
        self.assertEqual(despues.get("AL30"), antes["AL30"])
        self.assertEqual(despues.get("TSLA"), 15.0)

    def test_la_pantalla_avisa_lo_mismo_que_hace_el_confirm(self):
        """Lo que la previsualización marca como «ya importada» es exactamente lo
        que el confirm omite: ni una fila menos."""
        self._import(CSV_ENERO, "enero.csv")
        prev = self._preview(CSV_FEBRERO, "febrero.csv")
        self.assertEqual(len(prev["duplicate_row_indices"]), 4)
        r = self.client.post("/api/imports/confirm", json={"session_id": prev["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        cargadas = self.conn.execute(
            "SELECT COUNT(*) c FROM import_normalized_tx WHERE batch_id=?",
            (prev["session_id"],)).fetchone()["c"]
        self.assertEqual(cargadas, 1, "sólo tiene que entrar la compra nueva de febrero")

    def test_el_ticker_del_broker_queda_guardado(self):
        """La huella guardada se recalcula igual desde la base: sin esto, cada
        lector que la rehidrata la calcula con otro ticker."""
        self._import(CSV_ENERO, "enero.csv")
        sid = self.conn.execute("SELECT id FROM import_batches WHERE user_id=?",
                                (self.uid,)).fetchone()["id"]
        filas = self.conn.execute(
            "SELECT asset_symbol, asset_symbol_raw FROM import_normalized_tx WHERE batch_id=?",
            (sid,)).fetchall()
        crudos = {r["asset_symbol"]: r["asset_symbol_raw"] for r in filas if r["asset_symbol"]}
        self.assertEqual(crudos.get("AL30"), "AL30D")
        self.assertIn("COCOA", crudos.values())


if __name__ == "__main__":
    unittest.main()
