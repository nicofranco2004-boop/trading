"""Editar una posición de CEDEAR a acción (o al revés) cambia el precio con que se valúa.

Reporte real (2026-10-20): alguien cargó el CEDEAR de IREN cuando había comprado
la acción. En «Editar» eligió la acción en el buscador, puso el precio y guardó:
el precio de compra cambió, el precio ACTUAL siguió siendo el del CEDEAR.

El código del CEDEAR y el de la acción es el mismo (AMZN, IREN): lo único que los
separa es `asset_type`, y es lo que decide el precio (`position_price_key`: un
CEDEAR pide el `.BA`, la acción el ticker de Nueva York). La edición de un lote
no lo mandaba y la de la posición entera no sabía cambiarlo.

Todo entra por las MISMAS puertas HTTP que la app (cargar, editar, deshacer,
importar un archivo); lo único reemplazado es el login. El rehacer del FIFO
(`rebuild_pair_asset`) se llama tal cual corre en producción después de borrar
una operación: es el escritor POSTERIOR que devolvía el tipo viejo en los lotes
importados.
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

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import snapshots_job  # noqa: E402
from importing import rebuild as _rebuild  # noqa: E402

BROKER = "IBKR"   # broker en dólares del exterior: ahí el tipo decide el precio
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows: str) -> bytes:
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "deleted_ops_journal", "snapshots", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cedear-accion@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, BROKER, "USD"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        self.conn.close()

    def _cargar(self, asset_type, qty=10, precio=40.0, fecha="2026-10-01"):
        r = self.client.post("/api/positions", json={
            "broker": BROKER, "asset": "IREN", "quantity": qty, "buy_price": precio,
            "currency": "USD", "entry_date": fecha, "asset_type": asset_type})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _lotes(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='IREN' AND is_cash=0 "
            "ORDER BY id", (self.uid,))]

    def _precio_de(self, lote) -> str:
        """El símbolo con que el servidor valúa el lote (foto diaria, curva, mails)."""
        brokers = [dict(r) for r in self.conn.execute(
            "SELECT * FROM brokers WHERE user_id=?", (self.uid,))]
        ars, ar_usd = snapshots_job._broker_name_sets(brokers)
        return snapshots_job.position_price_key(lote, ars, ar_usd)


class TestUnLote(_Base):
    def test_cedear_a_accion_cambia_el_precio_con_que_se_valua(self):
        lote = self._cargar("CEDEAR")
        self.assertEqual(self._precio_de(lote), "IREN.BA")   # el caso del reporte
        r = self.client.put(f"/api/positions/{lote['id']}", json={
            **{k: lote[k] for k in ("broker", "asset", "quantity", "currency", "entry_date")},
            "buy_price": 42.5, "asset_type": "STOCK"})
        self.assertEqual(r.status_code, 200, r.text)
        (lote,) = self._lotes()
        self.assertEqual(lote["asset_type"], "STOCK")
        self.assertEqual(self._precio_de(lote), "IREN")

    def test_accion_a_cedear(self):
        lote = self._cargar("STOCK")
        self.assertEqual(self._precio_de(lote), "IREN")
        r = self.client.put(f"/api/positions/{lote['id']}", json={
            **{k: lote[k] for k in ("broker", "asset", "quantity", "buy_price", "currency",
                                    "entry_date")},
            "asset_type": "CEDEAR"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._precio_de(self._lotes()[0]), "IREN.BA")

    def test_sin_tipo_en_el_pedido_no_lo_borra(self):
        # Un cliente viejo (o el chat) que no manda el tipo no tiene que dejar al
        # CEDEAR sin tipo: se valuaría como la acción, 15-100 veces inflado.
        lote = self._cargar("CEDEAR")
        r = self.client.put(f"/api/positions/{lote['id']}", json={
            **{k: lote[k] for k in ("broker", "asset", "quantity", "buy_price", "currency",
                                    "entry_date")}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._lotes()[0]["asset_type"], "CEDEAR")


class TestPosicionEntera(_Base):
    def test_cambiar_solo_el_tipo_de_todos_los_lotes(self):
        self._cargar("CEDEAR", qty=10, fecha="2026-09-01")
        self._cargar("CEDEAR", qty=5, fecha="2026-10-01")
        r = self.client.patch("/api/positions/group", json={
            "broker": BROKER, "asset": "IREN", "currency": "USD", "new_asset_type": "STOCK"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["lots"], 2)
        lotes = self._lotes()
        self.assertEqual([l["asset_type"] for l in lotes], ["STOCK", "STOCK"])
        self.assertEqual({self._precio_de(l) for l in lotes}, {"IREN"})

    def test_tipo_y_promedio_juntos_y_deshacer(self):
        self._cargar("CEDEAR", qty=10, precio=4.0, fecha="2026-09-01")
        self._cargar("CEDEAR", qty=10, precio=6.0, fecha="2026-10-01")
        r = self.client.patch("/api/positions/group", json={
            "broker": BROKER, "asset": "IREN", "currency": "USD",
            "new_asset_type": "STOCK", "avg_price": 50.0})
        self.assertEqual(r.status_code, 200, r.text)
        lotes = self._lotes()
        self.assertEqual({l["asset_type"] for l in lotes}, {"STOCK"})
        self.assertAlmostEqual(sum(l["invested"] for l in lotes) / 20, 50.0, places=6)

        r = self.client.post(f"/api/positions/group/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        lotes = self._lotes()
        self.assertEqual({l["asset_type"] for l in lotes}, {"CEDEAR"})
        self.assertEqual({self._precio_de(l) for l in lotes}, {"IREN.BA"})
        self.assertAlmostEqual(sum(l["invested"] for l in lotes), 100.0, places=6)

    def test_deshacer_una_edicion_vieja_no_toca_el_tipo(self):
        # Las ediciones guardadas antes de este cambio no tienen el tipo en su foto:
        # su deshacer restaura lo que sí guardaron y deja el tipo como está.
        self._cargar("CEDEAR", qty=10, fecha="2026-09-01")
        self._cargar("CEDEAR", qty=10, fecha="2026-10-01")
        r = self.client.patch("/api/positions/group", json={
            "broker": BROKER, "asset": "IREN", "currency": "USD", "avg_price": 7.0})
        token = r.json()["undo_token"]
        import json
        row = self.conn.execute("SELECT id, payload_json FROM deleted_ops_journal WHERE token=?",
                                (token,)).fetchone()
        pl = json.loads(row["payload_json"])
        for l in pl["lots"]:
            l.pop("asset_type")
        self.conn.execute("UPDATE deleted_ops_journal SET payload_json=? WHERE id=?",
                          (json.dumps(pl), row["id"]))
        self.conn.execute("UPDATE positions SET asset_type='STOCK' WHERE user_id=?", (self.uid,))
        self.conn.commit()
        r = self.client.post(f"/api/positions/group/undo/{token}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({l["asset_type"] for l in self._lotes()}, {"STOCK"})


class TestImportadoSobreviveAlRehacer(_Base):
    """Un lote importado se vuelve a escribir desde la fila del archivo cada vez que
    corre el rehacer del FIFO. Si el tipo nuevo quedaba sólo en `positions`, el
    activo volvía a ser lo que decía el archivo."""

    def _importar(self, *filas):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO(_csv(*filas)), "text/csv"))],
            data={"format": "rendi_generic", "broker": BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/imports/confirm", json={"session_id": r.json()["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)

    def _rehacer(self):
        with self.conn:
            _rebuild.rebuild_pair_asset(self.conn, self.uid, BROKER, "IREN")

    def _tipo_en_el_archivo(self):
        return {r["t"] for r in self.conn.execute(
            "SELECT n.asset_type t FROM import_normalized_tx n "
            "JOIN import_batches b ON b.id = n.batch_id "
            "WHERE b.user_id=? AND n.asset_symbol='IREN'", (self.uid,))}

    def test_un_lote_importado(self):
        self._importar("2026-09-01,DEPOSITO,IBKR,,,,1000,,,0,USD,",
                       "2026-09-02,COMPRA,IBKR,IREN,10,40,400,,,0,USD,")
        (lote,) = self._lotes()
        self.assertNotEqual((lote["asset_type"] or "").upper(), "CEDEAR")
        r = self.client.put(f"/api/positions/{lote['id']}", json={
            **{k: lote[k] for k in ("broker", "asset", "quantity", "buy_price", "currency",
                                    "entry_date")},
            "asset_type": "CEDEAR"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._tipo_en_el_archivo(), {"CEDEAR"})
        self._rehacer()
        (lote,) = self._lotes()
        self.assertEqual(lote["asset_type"], "CEDEAR")
        self.assertEqual(self._precio_de(lote), "IREN.BA")

    def test_varios_lotes_importados(self):
        self._importar("2026-09-01,DEPOSITO,IBKR,,,,1000,,,0,USD,",
                       "2026-09-02,COMPRA,IBKR,IREN,10,40,400,,,0,USD,",
                       "2026-09-03,COMPRA,IBKR,IREN,5,42,210,,,0,USD,")
        self.assertEqual(len(self._lotes()), 2)
        r = self.client.patch("/api/positions/group", json={
            "broker": BROKER, "asset": "IREN", "currency": "USD", "new_asset_type": "CEDEAR"})
        self.assertEqual(r.status_code, 200, r.text)
        self._rehacer()
        lotes = self._lotes()
        self.assertEqual({l["asset_type"] for l in lotes}, {"CEDEAR"})
        self.assertEqual({self._precio_de(l) for l in lotes}, {"IREN.BA"})

        # Y el deshacer devuelve también la fila del archivo: si no, el próximo
        # rehacer volvería a dejarlo CEDEAR.
        r = self.client.post(f"/api/positions/group/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        self._rehacer()
        self.assertNotIn("CEDEAR", {(l["asset_type"] or "").upper() for l in self._lotes()})


if __name__ == "__main__":
    unittest.main()
