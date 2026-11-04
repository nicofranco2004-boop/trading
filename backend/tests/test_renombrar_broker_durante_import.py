"""Renombrar un broker MIENTRAS corre un import no puede dejar filas huérfanas.

Los brokers se enlazan por NOMBRE (`main.BROKER_POR_NOMBRE`). El renombre
reescribe ese nombre en todas las tablas, adentro de su transacción y con el
turno de la cuenta. Un import lee el nombre en un momento y lo escribe más
tarde: si el renombre entra entre esas dos cosas, el import escribe el nombre
viejo DESPUÉS de que el renombre ya pasó, y esas filas no son de ningún broker.

CÓMO SE PRUEBA. Por las puertas de verdad (`/api/imports/preview`,
`/api/imports/confirm`, `PUT /api/brokers/{id}`). Justo DESPUÉS de la lectura que
decide el nombre se lanza el renombre en otro hilo y se lo espera unos segundos:
si el import tiene la cuenta tomada, el renombre espera, la espera se vence y el
import sigue; si no, el renombre entra en el medio. Las dos cosas se miden.
"""
import io
import threading
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import main
from tests._limpieza import vaciar  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
FILAS = (
    "2025-03-01,DEPOSITO,Cocos,,,,1000000,,,0,ARS,\n"
    "2025-03-03,COMPRA,Cocos,GGAL,100,5000,500000,,,0,ARS,\n"
)
ESPERA = 3.0   # segundos que el import le da al renombre para entrar en el medio


class _Base(unittest.TestCase):
    def setUp(self):
        # La reconstrucción de fondo que lanza cada import sale a Yahoo y sigue
        # viva después del test: no es lo que se mide acá.
        for nombre in ("_reconstruir_mtm_post_import", "_reconstruir_en_fila"):
            p = mock.patch.object(main, nombre, side_effect=lambda *a, **k: None)
            p.start()
            self.addCleanup(p.stop)
        self.conn = main.get_db()
        vaciar(self.conn, "import_op_links", "import_normalized_tx", "import_raw_rows",
               "import_batches", "operations", "positions", "monthly_entries",
               "snapshots", "config", "brokers", "users")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("renombre-import@rendi.test", "x")).lastrowid
        self.bid = self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "Cocos", "ARS")).lastrowid
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.addCleanup(self.conn.close)
        self.client = TestClient(main.app)
        self.renombre = None

    # ── las puertas ────────────────────────────────────────────────────────
    def _preview(self):
        r = self.client.post(
            "/api/imports/preview",
            files=[("files", ("x.csv", io.BytesIO((HDR + FILAS).encode()), "text/csv"))],
            data={"format": "rendi_generic", "broker": "Cocos"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_id"]

    def _confirmar(self, sid):
        return self.client.post("/api/imports/confirm", json={"session_id": sid})

    def _renombrar_en_el_medio(self):
        """Lanza el renombre Cocos → Cocos Capital y le da ESPERA segundos.
        Devuelve si terminó adentro de la ventana (o sea: entró en el medio)."""
        resultado = {}

        def renombrar():
            resultado["r"] = TestClient(main.app).put(
                f"/api/brokers/{self.bid}", json={"name": "Cocos Capital", "currency": "ARS"})

        hilo = threading.Thread(target=renombrar)
        hilo.start()
        hilo.join(ESPERA)
        self.renombre = (hilo, resultado)
        return not hilo.is_alive()

    def _esperar_renombre(self):
        hilo, resultado = self.renombre
        hilo.join(60)
        self.assertFalse(hilo.is_alive(), "el renombre quedó colgado")
        return resultado["r"]

    def _cuenta(self):
        """Brokers de la cuenta y la tenencia (sin efectivo) de cada uno."""
        c = main.get_db()
        try:
            brokers = sorted(r[0] for r in c.execute(
                "SELECT name FROM brokers WHERE user_id=?", (self.uid,)))
            tenencia = {f"{r[0]}/{r[1]}": r[2] for r in c.execute(
                "SELECT broker, asset, SUM(quantity) FROM positions "
                "WHERE user_id=? AND is_cash=0 GROUP BY broker, asset", (self.uid,))}
            return brokers, tenencia
        finally:
            c.close()

    def _huerfanas(self):
        """{tabla: [nombres]} con filas cuyo broker no existe en la cuenta."""
        c = main.get_db()
        try:
            vivos = {r[0] for r in c.execute(
                "SELECT name FROM brokers WHERE user_id=?", (self.uid,))}
            out = {}
            for tabla in ("positions", "operations", "monthly_entries", "import_batches"):
                malos = sorted({r[0] for r in c.execute(
                    f"SELECT DISTINCT broker FROM {tabla} WHERE user_id=?", (self.uid,))
                    if r[0] not in vivos and r[0] != "global"})
                if malos:
                    out[tabla] = malos
            malos = sorted({r[0] for r in c.execute(
                "SELECT DISTINCT n.broker FROM import_normalized_tx n "
                "JOIN import_batches b ON b.id = n.batch_id WHERE b.user_id=?", (self.uid,))
                if r[0] and r[0] not in vivos})
            if malos:
                out["import_normalized_tx"] = malos
            return out
        finally:
            c.close()


class RenombrarDuranteLaVistaPreviaTest(_Base):
    """La vista previa lee los brokers (`fetch_user_brokers`) y escribe el lote al
    final. El renombre entra justo después de esa lectura."""

    def test_el_lote_no_queda_con_el_nombre_viejo(self):
        import importing.pipeline as pl
        original = pl.fetch_user_brokers
        ventana = {}

        def leer_y_dejar_entrar(conn, uid):
            leido = original(conn, uid)
            if "entro" not in ventana:
                ventana["entro"] = self._renombrar_en_el_medio()
            return leido

        with mock.patch.object(pl, "fetch_user_brokers", leer_y_dejar_entrar):
            sid = self._preview()
        r = self._esperar_renombre()
        self.assertEqual(r.status_code, 200, r.text)
        r = self._confirmar(sid)
        print(f"\n[vista previa] renombre entró en el medio: {ventana['entro']}; "
              f"confirm: {r.status_code}; huérfanas: {self._huerfanas()}; "
              f"cuenta: {self._cuenta()}")
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        self.assertEqual(self._huerfanas(), {})
        # Y la tenencia entró UNA vez, entera, en un broker que existe.
        self.assertEqual(list(self._cuenta()[1].values()), [100])


class RenombrarDuranteLaConfirmacionTest(_Base):
    """La confirmación relee el lote (con sus nombres) y después escribe las
    posiciones y operaciones. El renombre entra justo después de esa lectura."""

    def test_las_posiciones_no_quedan_con_el_nombre_viejo(self):
        sid = self._preview()
        original = main._import_pipeline.load_session_with_seed_revalidate
        ventana = {}

        def leer_y_dejar_entrar(*a, **k):
            leido = original(*a, **k)
            ventana["entro"] = self._renombrar_en_el_medio()
            return leido

        with mock.patch.object(main._import_pipeline, "load_session_with_seed_revalidate",
                               leer_y_dejar_entrar):
            r = self._confirmar(sid)
        rr = self._esperar_renombre()
        print(f"\n[confirmación] renombre entró en el medio: {ventana['entro']}; "
              f"confirm: {r.status_code}; renombre: {rr.status_code}; "
              f"huérfanas: {self._huerfanas()}; cuenta: {self._cuenta()}")
        self.assertIn(r.status_code, (200, 400, 409), r.text)
        self.assertIn(rr.status_code, (200, 409), rr.text)
        self.assertEqual(self._huerfanas(), {})
        # Y la tenencia entró UNA vez, entera, en un broker que existe.
        self.assertEqual(list(self._cuenta()[1].values()), [100])


class RenombrarDuranteLaReconstruccionTest(_Base):
    """Después de confirmar, la reconstrucción FIFO (otra transacción) lee los
    pares (broker, activo) del lote y reescribe sus lotes. El renombre entra justo
    después de esa lectura (en el primer `broker_pair`)."""

    def test_los_lotes_reconstruidos_no_quedan_con_el_nombre_viejo(self):
        import importing.rebuild as rb
        sid = self._preview()
        original = rb.broker_pair
        ventana = {}

        def leer_y_dejar_entrar(*a, **k):
            if "entro" not in ventana:
                ventana["entro"] = self._renombrar_en_el_medio()
            return original(*a, **k)

        with mock.patch.object(rb, "broker_pair", leer_y_dejar_entrar):
            r = self._confirmar(sid)
        rr = self._esperar_renombre()
        print(f"\n[reconstrucción] renombre entró en el medio: {ventana.get('entro')}; "
              f"confirm: {r.status_code}; renombre: {rr.status_code}; "
              f"huérfanas: {self._huerfanas()}; cuenta: {self._cuenta()}")
        self.assertIn("entro", ventana, "la reconstrucción no pasó por broker_pair")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(rr.status_code, (200, 409), rr.text)
        self.assertEqual(self._huerfanas(), {})
        # Y la tenencia entró UNA vez, entera, en un broker que existe.
        self.assertEqual(list(self._cuenta()[1].values()), [100])


class RenombrarEntreVistaPreviaYConfirmacionTest(_Base):
    """Sin carrera: vista previa, la persona renombra el broker (minutos, en otra
    pestaña) y después confirma. El renombre reescribe el lote guardado; pero el
    «Estado inicial» relee el ARCHIVO, que dice el nombre de antes, y la pantalla
    manda lo sembrado con los nombres que tenía al cargar."""

    SEED_VACIO = {"seed_date": "2025-02-28",
                  "brokers": [{"broker": "Cocos Capital", "cash": {"ARS": 0}, "assets": []}]}

    def _renombrar_y_confirmar(self, seed=None):
        sid = self._preview()
        r = self.client.put(f"/api/brokers/{self.bid}",
                            json={"name": "Cocos Capital", "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        body = {"session_id": sid}
        if seed is not None:
            body["seed_state"] = seed
        r = self.client.post("/api/imports/confirm", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_sin_estado_inicial(self):
        self._renombrar_y_confirmar()
        self.assertEqual(self._huerfanas(), {})
        self.assertEqual(self._cuenta(), (["Cocos Capital"], {"Cocos Capital/GGAL": 100}))

    def test_con_estado_inicial_las_filas_del_archivo_no_se_pierden(self):
        """El bug: 200 «ok» con 0 posiciones; el depósito y la compra, descartados."""
        r = self._renombrar_y_confirmar(self.SEED_VACIO)
        self.assertEqual((r["positions_created"], r["cash_movements"]), (1, 1), r)
        self.assertEqual(self._huerfanas(), {})
        self.assertEqual(self._cuenta(), (["Cocos Capital"], {"Cocos Capital/GGAL": 100}))

    def test_el_estado_inicial_con_el_nombre_de_antes_va_al_broker_de_hoy(self):
        """El bug: YPFD sembrado en «Cocos», un broker que ya no existe."""
        seed = {"seed_date": "2025-02-28",
                "brokers": [{"broker": "Cocos", "cash": {"ARS": 0},
                             "assets": [{"symbol": "YPFD", "qty": 10,
                                         "cost_basis_unit": 20000}]}]}
        self._renombrar_y_confirmar(seed)
        self.assertEqual(self._huerfanas(), {})
        self.assertEqual(self._cuenta(), (["Cocos Capital"], {
            "Cocos Capital/GGAL": 100, "Cocos Capital/YPFD": 10}))


if __name__ == "__main__":
    unittest.main()
