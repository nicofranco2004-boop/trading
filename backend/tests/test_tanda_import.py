"""Carga de historiales por tanda (Plan Asesor) — el camino REAL del servidor.

La tanda no tiene endpoint propio en F1: es el importador de siempre
(/imports/preview + /imports/confirm) llamado N veces en serie, cada vez con el
header `X-Rendi-Client-Id` del cliente de esa fila. Lo que estos tests
certifican es exactamente lo que la pantalla da por hecho:

  1. dos clientes seguidos, con headers distintos, quedan cada uno con SU lote
     y SUS posiciones — nada se cruza;
  2. un vínculo de sólo lectura no deja ni previsualizar (403), así que la fila
     deshabilitada de la pantalla no es cosmética;
  3. un cliente ajeno también es 403;
  4. el decorador de medición no rompe la firma del endpoint (si la rompiera,
     FastAPI devolvería 422 en TODOS los imports, no sólo en la tanda).
"""
import io
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _new_user(conn, email, tier=None, approved=1):
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,?,?)",
        (email, "x", approved, tier))
    return cur.lastrowid


def _link(conn, advisor_uid, client_uid, permission="read_write", label="Cliente"):
    conn.execute(
        """INSERT INTO advisor_clients
               (advisor_uid, client_uid, link_type, permission, status, label)
           VALUES (?,?,?,?,?,?)""",
        (advisor_uid, client_uid, "managed", permission, "active", label))


_COCOS_HEADER = (
    "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
    "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
    "montoBruto;comision;ddmm;iva;otros;total"
)


def _cocos_csv(*rows):
    return ("\n".join([_COCOS_HEADER] + list(rows)) + "\n").encode("utf-8")


class TandaImportTest(unittest.TestCase):

    def setUp(self):
        conn = main.get_db()
        tag = uuid.uuid4().hex[:10]
        self.advisor = _new_user(conn, f"asesor-{tag}@rendi.test", tier="advisor")
        self.c1 = _new_user(conn, f"c1-{tag}@rendi.test", approved=0)
        self.c2 = _new_user(conn, f"c2-{tag}@rendi.test", approved=0)
        self.ro = _new_user(conn, f"ro-{tag}@rendi.test", approved=0)
        self.stranger = _new_user(conn, f"ajeno-{tag}@rendi.test")
        for c in (self.c1, self.c2, self.ro):
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, c))
        _link(conn, self.advisor, self.c1, label="Juan P")
        _link(conn, self.advisor, self.c2, label="Ana G")
        _link(conn, self.advisor, self.ro, permission="read", label="Pablo T")
        conn.commit()
        conn.close()
        self.http = TestClient(main.app)

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.advisor,))
            conn.commit()
        finally:
            conn.close()

    def _hdr(self, client_uid=None):
        h = {"Authorization": f"Bearer {main.create_token(self.advisor)}"}
        if client_uid is not None:
            h["X-Rendi-Client-Id"] = str(client_uid)
        return h

    def _preview(self, client_uid, csv_bytes, name="cocos.csv"):
        return self.http.post(
            "/api/imports/preview",
            files=[("files", (name, io.BytesIO(csv_bytes), "text/csv"))],
            data={"format": "cocos"},
            headers=self._hdr(client_uid),
        )

    def _confirm(self, client_uid, session_id):
        # Exactamente el cuerpo que manda la tanda: sin seed_state, sin
        # include_duplicates, aprobar_tickers vacío.
        return self.http.post(
            "/api/imports/confirm",
            json={"session_id": session_id, "skip_row_indices": [], "aprobar_tickers": []},
            headers=self._hdr(client_uid),
        )

    def _batches_de(self, uid):
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT id, status FROM import_batches WHERE user_id=? ORDER BY created_at",
                (uid,)).fetchall()
        finally:
            conn.close()

    def test_dos_clientes_en_serie_cada_uno_con_su_lote(self):
        csv1 = _cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000",
            "3;4;16-01-2024;16-01-2024;Compra;BONO AL30 (AL30);ARS;BYMA;100;500;50.000;0;0;0;0;-50.000",
        )
        csv2 = _cocos_csv(
            "5;6;15-02-2024;15-02-2024;Recibo De Cobro;;ARS;;;;200000;0;0;0;0;200000",
        )
        p1 = self._preview(self.c1, csv1)
        self.assertEqual(p1.status_code, 200, p1.text)
        c1 = self._confirm(self.c1, p1.json()["session_id"])
        self.assertEqual(c1.status_code, 200, c1.text)

        p2 = self._preview(self.c2, csv2)
        self.assertEqual(p2.status_code, 200, p2.text)
        c2 = self._confirm(self.c2, p2.json()["session_id"])
        self.assertEqual(c2.status_code, 200, c2.text)

        # Cada lote quedó en la cuenta de SU cliente, confirmado.
        b1 = self._batches_de(self.c1)
        b2 = self._batches_de(self.c2)
        self.assertEqual([r["id"] for r in b1], [p1.json()["session_id"]])
        self.assertEqual([r["id"] for r in b2], [p2.json()["session_id"]])
        self.assertEqual(b1[0]["status"], "confirmed")
        self.assertEqual(b2[0]["status"], "confirmed")
        # Y NADA cayó en la cuenta del asesor (el bug que el header evita).
        self.assertEqual(self._batches_de(self.advisor), [])

        # El confirm devuelve lo que la pantalla suma como "movimientos cargados".
        j = c1.json()
        for k in ("positions_created", "operations_created", "cash_movements", "conversions",
                  "auto_skipped_duplicates", "skipped_rows", "cash_health", "post_proceso"):
            self.assertIn(k, j, f"falta {k} en la respuesta del confirm")
        self.assertGreaterEqual(j["cash_movements"] + j["operations_created"], 1)

        # Las posiciones del cliente 1 no aparecen en el cliente 2.
        conn = main.get_db()
        try:
            # `positions` guarda también la CAJA de cada broker (is_cash=1) —
            # se cuentan sólo los activos, que es lo que podría cruzarse.
            n2 = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0", (self.c2,)).fetchone()[0]
            n1 = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=? AND is_cash=0", (self.c1,)).fetchone()[0]
            ajenas = conn.execute("SELECT COUNT(*) FROM positions WHERE user_id=?", (self.advisor,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(n2, 0)
        self.assertGreaterEqual(n1, 1)
        self.assertEqual(ajenas, 0)

    def test_reimportar_lo_mismo_no_duplica(self):
        csv1 = _cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000",
        )
        p = self._preview(self.c1, csv1)
        self.assertEqual(self._confirm(self.c1, p.json()["session_id"]).status_code, 200)
        p2 = self._preview(self.c1, csv1)
        c2 = self._confirm(self.c1, p2.json()["session_id"])
        self.assertEqual(c2.status_code, 200, c2.text)
        self.assertGreaterEqual(c2.json()["auto_skipped_duplicates"], 1)

        # Lo repetido NO cuenta como "requiere aprobación" ni como "omitido por
        # el usuario": la tanda del asesor decide "Revisar" con esos dos números.
        self.assertEqual(c2.json().get("skipped_by_user"), 0, c2.json())
        self.assertEqual(c2.json().get("skipped_pending_approval"), 0, c2.json())

    def test_solo_lectura_no_puede_ni_previsualizar(self):
        csv1 = _cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000")
        r = self._preview(self.ro, csv1)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(self._batches_de(self.ro), [])

    def test_cliente_ajeno_es_403(self):
        csv1 = _cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000")
        r = self._preview(self.stranger, csv1)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(self._batches_de(self.stranger), [])

    def test_confirm_con_header_de_otro_cliente_no_encuentra_el_lote(self):
        """El session_id del cliente 1 presentado a nombre del cliente 2: el lote
        no es suyo → no se confirma en ninguna cuenta."""
        csv1 = _cocos_csv("1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100000;0;0;0;0;100000")
        p = self._preview(self.c1, csv1)
        sid = p.json()["session_id"]
        r = self._confirm(self.c2, sid)
        self.assertIn(r.status_code, (400, 404), r.text)
        self.assertEqual(self._batches_de(self.c1)[0]["status"], "preview")
        self.assertEqual(self._batches_de(self.c2), [])

    def test_venta_sin_compra_previa_pide_estado_inicial(self):
        """La tanda no manda seed_state: lo que la pantalla puede hacer es marcar
        'Revisar'. Eso depende de que el preview traiga `seed_suggestions.needed`
        para un archivo que arranca vendiendo algo que nunca compró."""
        csv1 = _cocos_csv(
            "1;2;15-01-2024;15-01-2024;Recibo De Cobro;;ARS;;;;100.000;0;0;0;0;100.000",
            "3;4;16-01-2024;16-01-2024;Venta;BONO AL30 (AL30);ARS;BYMA;-100;500;50.000;0;0;0;0;50.000",
        )
        p = self._preview(self.c1, csv1)
        self.assertEqual(p.status_code, 200, p.text)
        seed = p.json().get("seed_suggestions") or {}
        self.assertTrue(seed.get("needed"), f"el preview no pidió estado inicial: {seed}")
        # Y el confirm sin seed igual entra (la tanda carga lo que había).
        c = self._confirm(self.c1, p.json()["session_id"])
        self.assertEqual(c.status_code, 200, c.text)
        self.assertEqual(c.json().get("post_proceso"), {}, "ningún paso del post-proceso debería fallar")

    def test_el_decorador_de_medicion_conserva_la_firma(self):
        import inspect
        for path in ("/api/imports/preview", "/api/imports/confirm"):
            route = next(x for x in main.app.routes if getattr(x, "path", "") == path)
            params = list(inspect.signature(route.endpoint).parameters)
            self.assertIn("uid", params, f"{path}: la firma perdió `uid` → FastAPI no inyecta el usuario")


if __name__ == "__main__":
    unittest.main()
