"""«Empezar de cero»: los bordes que encontró la auditoría del 07/11/2026.

Cada clase es un defecto que estaba, con la forma en que se veía:

  1. La foto del cron escrita DESPUÉS del borrado. El cron lee la cuenta sin el
     turno, sale a buscar precios y recién después toma el turno y escribe. Si la
     persona vaciaba la cuenta en esa ventana, amanecía con una foto 'cron' de la
     cartera de antes que ya nadie borraba (medido por la auditoría).
  2. La foto que manda el navegador (una pestaña vieja en otro dispositivo) con el
     total de antes, sobre una cuenta ya vacía.
  3. La marca de Wallbit: con ella, la primera sincronización después de vaciar
     traía sólo 3 días y la historia no volvía.
  4. Un error al CONTAR una tabla (en Postgres: una consulta cancelada, la
     conexión) se salteaba igual que una tabla inexistente, y el borrado decía
     «listo» con esa tabla entera adentro.
  5. Dos arranques a la vez arrancaban dos borrados, y el apagado del servidor no
     esperaba al borrado (lo cortaba en seco).
  6. La barra mostraba el nombre interno de la tabla («Borrando import_raw_rows…»)
     y el error, el nombre de la excepción.
  7. El freno entre tandas: en Postgres empeora (medido el 06/11), así que es por
     motor y vale igual para los dos botones.

Todas van por las mismas puertas que producción: el cron por `run_daily_snapshot`
con el turno que le pasa `_run_daily_snapshot_job`, el navegador por HTTP, el
borrado por `_arrancar_reset` / `_reset_data_worker`.

Corre con: cd backend && python3 -m pytest tests/test_empezar_de_cero_bordes.py
"""
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
import main  # noqa: E402
import snapshots_job  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class _Cuenta(unittest.TestCase):
    """Una cuenta con cartera (broker + posición + foto vieja) y su limpieza."""
    _seq = 91000

    def setUp(self):
        _Cuenta._seq += 1
        self.UID = _Cuenta._seq
        c = main.get_db()
        try:
            c.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                      (self.UID, f"bordes{self.UID}@rendi.test", "x"))
            c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'IBKR','USD')", (self.UID,))
            c.execute("INSERT INTO positions (user_id,broker,asset,asset_type,quantity,invested,is_cash,currency) "
                      "VALUES (?,'IBKR','AAPL','STOCK',10,1500,0,'USD')", (self.UID,))
            c.commit()
        finally:
            c.close()

    def tearDown(self):
        c = main.get_db()
        try:
            for t in ("snapshots", "positions", "brokers", "monthly_entries",
                      "user_broker_credentials", "config", "users"):
                col = "id" if t == "users" else "user_id"
                with main._si_falla_se_deshace_solo_esto(c, "limpieza"):
                    c.execute(f"DELETE FROM {t} WHERE {col}=?", (self.UID,))
            c.commit()
        finally:
            c.close()
        main._soltar_corrida(main._corrida_del_reset(self.UID))
        main._reset_progress.pop(self.UID, None)

    def _n(self, tabla, extra=""):
        c = main.get_db()
        try:
            return c.execute(f"SELECT COUNT(*) FROM {tabla} WHERE user_id=? {extra}",
                             (self.UID,)).fetchone()[0]
        finally:
            c.close()


class FotoDelCronDespuesDelBorrado(_Cuenta):
    """1. La persona vacía la cuenta mientras el cron le busca precios."""

    def _correr_cron_con_borrado_en_el_medio(self):
        uid = self.UID

        def precios_y_en_el_medio_el_borrado(simbolos, crypto_yf):
            main._reset_data_worker(uid)          # el borrado real, entero
            return {s: 150.0 for s in simbolos}   # y el cron sigue con lo que leyó

        with mock.patch.object(snapshots_job, "fetch_prices_for_symbols",
                               side_effect=precios_y_en_el_medio_el_borrado):
            # La MISMA llamada que `main._run_daily_snapshot_job`.
            return snapshots_job.run_daily_snapshot(
                db_path=main.DB_PATH, fetch_tc_blue=lambda: 1500.0, crypto_yf={},
                fetch_tc_mep=lambda: 1500.0, abrir=main.get_db,
                tomar_turno=main._tomar_turno_de_la_puerta)

    def test_no_escribe_la_cartera_de_antes(self):
        self._correr_cron_con_borrado_en_el_medio()
        self.assertEqual(main._reset_estado(self.UID).get("estado"), "listo")
        self.assertEqual(self._n("positions"), 0)
        self.assertEqual(self._n("snapshots"), 0,
                         "el cron escribió la foto de la cartera borrada")

    def test_sin_borrado_la_foto_se_escribe(self):
        """El control: la misma corrida, sin vaciar la cuenta, sí escribe."""
        with mock.patch.object(snapshots_job, "fetch_prices_for_symbols",
                               side_effect=lambda s, c: {x: 150.0 for x in s}):
            snapshots_job.run_daily_snapshot(
                db_path=main.DB_PATH, fetch_tc_blue=lambda: 1500.0, crypto_yf={},
                fetch_tc_mep=lambda: 1500.0, abrir=main.get_db,
                tomar_turno=main._tomar_turno_de_la_puerta)
        self.assertEqual(self._n("snapshots", "AND source='cron'"), 1)


class FotoDelNavegadorSobreCuentaVacia(_Cuenta):
    """2. POST /api/snapshots con el total que calculó una pestaña vieja."""

    def setUp(self):
        super().setUp()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.UID
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        super().tearDown()

    def _postear(self):
        return self.client.post("/api/snapshots", json={
            "total_value": 9999.0, "total_invested": 1500.0, "net_deposited": 1500.0})

    def test_cuenta_vaciada_no_recibe_foto(self):
        main._reset_data_worker(self.UID)
        r = self._postear()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._n("snapshots"), 0)

    def test_cuenta_a_mano_sin_posiciones_si_recibe_foto(self):
        """Las cuentas cargadas por mes no tienen posiciones y se fotografían: la
        regla del navegador es «sin brokers», no la del cron."""
        c = main.get_db()
        try:
            c.execute("DELETE FROM positions WHERE user_id=?", (self.UID,))
            c.commit()
        finally:
            c.close()
        r = self._postear()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._n("snapshots"), 1)


class MarcaDeWallbit(_Cuenta):
    """3. La marca de «hasta dónde ya traje» es cartera; las claves no."""

    def setUp(self):
        super().setUp()
        c = main.get_db()
        try:
            c.execute("INSERT INTO user_broker_credentials (user_id,broker,api_key_enc,last_sync_at,last_sync_status) "
                      "VALUES (?,'wallbit','ENC','2026-11-01 10:00:00','ok')", (self.UID,))
            c.execute("INSERT INTO user_broker_credentials (user_id,broker,api_key_enc,last_sync_at,last_sync_status) "
                      "VALUES (?,'iol_lab','ENC2','2026-11-01 10:00:00','ok')", (self.UID,))
            c.commit()
        finally:
            c.close()

    def _cred(self, broker):
        c = main.get_db()
        try:
            return c.execute("SELECT api_key_enc, last_sync_at FROM user_broker_credentials "
                             "WHERE user_id=? AND broker=?", (self.UID, broker)).fetchone()
        finally:
            c.close()

    def test_el_borrado_del_usuario_olvida_la_marca_y_conserva_la_clave(self):
        main._reset_data_worker(self.UID)
        w = self._cred("wallbit")
        self.assertEqual(w["api_key_enc"], "ENC")
        self.assertIsNone(w["last_sync_at"])
        c = main.get_db()
        try:
            self.assertIsNone(main._wallbit_last_from_date(c, self.UID),
                              "la próxima sincronización tiene que traer todo")
        finally:
            c.close()

    def test_la_marca_de_iol_lab_no_se_toca(self):
        """Ahí dice cuándo renovar una clave, no qué datos hay."""
        main._reset_data_worker(self.UID)
        self.assertEqual(str(self._cred("iol_lab")["last_sync_at"])[:10], "2026-11-01")


class ErrorAlContar(_Cuenta):
    """4. Sólo se saltea una tabla que NO EXISTE; cualquier otro error corta."""

    def test_un_error_al_contar_no_termina_en_listo(self):
        import sqlite3
        real = main.get_db

        class _Envoltorio:
            def __init__(self, c):
                self._c = c

            def execute(self, sql, *a, **k):
                if sql.startswith("SELECT COUNT(*) FROM snapshots"):
                    raise sqlite3.OperationalError("interrupted")   # consulta cancelada
                return self._c.execute(sql, *a, **k)

            def __getattr__(self, n):
                return getattr(self._c, n)

            def __enter__(self):
                return self._c.__enter__()

            def __exit__(self, *a):
                return self._c.__exit__(*a)

        with mock.patch.object(main, "get_db", side_effect=lambda: _Envoltorio(real())):
            main._reset_data_worker(self.UID)
        st = main._reset_estado(self.UID)
        self.assertEqual(st.get("estado"), "error")
        self.assertNotIn("Error", st.get("error", ""), "el nombre de la excepción no va a la pantalla")
        self.assertIn("volvé a tocar", st.get("error", ""))

    def test_una_tabla_que_no_existe_se_saltea(self):
        main._reset_data_worker(self.UID, tablas=("positions", "tabla_que_no_existe"))
        st = main._reset_estado(self.UID)
        self.assertEqual(st.get("estado"), "listo")
        self.assertEqual(self._n("positions"), 0)


class UnSoloBorradoALaVez(_Cuenta):
    """5. Arranque atómico, y el apagado lo espera."""

    def test_dos_arranques_a_la_vez_arrancan_uno(self):
        listos = threading.Barrier(8)
        resultados = []
        frenar = threading.Event()

        def trabajo_lento(uid, **kw):
            frenar.wait(5)
            main._soltar_corrida(main._corrida_del_reset(uid))

        def apretar():
            listos.wait()
            resultados.append(main._arrancar_reset(self.UID))

        with mock.patch.object(main, "_reset_data_worker", side_effect=trabajo_lento):
            hilos = [threading.Thread(target=apretar) for _ in range(8)]
            for h in hilos:
                h.start()
            for h in hilos:
                h.join()
            frenar.set()
        self.assertEqual(resultados.count(True), 1, resultados)

    def test_el_apagado_ve_el_borrado_y_lo_suelta_al_terminar(self):
        frenar = threading.Event()
        visto = {}
        real = main._reset_data_worker

        def trabajo(uid, **kw):
            visto["anotado"] = main._corrida_del_reset(uid) in main._corridas_en_curso
            frenar.wait(5)
            real(uid, **kw)

        with mock.patch.object(main, "_reset_data_worker", side_effect=trabajo):
            self.assertTrue(main._arrancar_reset(self.UID))
            self.assertFalse(main._esperar_corridas(0.3), "el apagado no esperaría al borrado")
            frenar.set()
            self.assertTrue(main._esperar_corridas(10))
        self.assertTrue(visto["anotado"])
        self.assertEqual(main._reset_estado(self.UID).get("estado"), "listo")
        # Y suelta: se puede volver a apretar.
        self.assertTrue(main._arrancar_reset(self.UID))
        self.assertTrue(main._esperar_corridas(10))

    def test_el_boton_del_usuario_pasa_por_la_puerta(self):
        os.environ["RENDI_RESET_DATA_ENABLED"] = "1"
        try:
            with mock.patch.object(main, "_arrancar_reset", return_value=False) as puerta:
                r = main.reset_my_data(uid=self.UID)
        finally:
            os.environ.pop("RENDI_RESET_DATA_ENABLED", None)
        puerta.assert_called_once()
        self.assertTrue(r.get("ya_corriendo"))


class LoQueVeLaPersona(unittest.TestCase):
    """6. Ningún nombre interno en la barra."""

    def test_ninguna_tabla_del_borrado_se_muestra_con_su_nombre(self):
        for t in set(main._RESET_PORTFOLIO_TABLES) | set(main._reset_admin_tablas()) | {
                "import_normalized_tx", "import_op_links", "import_raw_rows", "import_batches"}:
            etapa = main._reset_etapa(t)
            self.assertTrue(etapa, t)
            self.assertNotIn("_", etapa, f"{t} → {etapa}")
            self.assertNotEqual(etapa, t)

    def test_sin_tabla_no_hay_etapa(self):
        self.assertIsNone(main._reset_etapa(None))


class FrenoPorMotor(unittest.TestCase):
    """7. El freno entre tandas sale de la base, no de una constante del admin."""

    def setUp(self):
        self._antes = os.environ.pop("RENDI_RESET_PAUSA_MS", None)

    def tearDown(self):
        os.environ.pop("RENDI_RESET_PAUSA_MS", None)
        if self._antes is not None:
            os.environ["RENDI_RESET_PAUSA_MS"] = self._antes

    def test_sqlite_frena_60_ms(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        try:
            self.assertAlmostEqual(main._reset_pausa_s(c), 0.06)
        finally:
            c.close()

    def test_postgres_no_frena(self):
        import pgsesion
        c = main.get_db()
        try:
            if not pgsesion.habla_postgres(c):
                self.skipTest("la suite corre sobre SQLite")
            self.assertEqual(main._reset_pausa_s(c), 0.0)
        finally:
            c.close()

    def test_la_variable_manda_en_los_dos(self):
        import sqlite3
        os.environ["RENDI_RESET_PAUSA_MS"] = "0"
        c = sqlite3.connect(":memory:")
        try:
            self.assertEqual(main._reset_pausa_s(c), 0.0)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
