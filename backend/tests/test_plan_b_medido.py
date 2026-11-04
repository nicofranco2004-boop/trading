"""Los «plan B» que el censo deja pasar, MEDIDOS por el camino real.

`tests/test_plan_b_tiene_punto_de_guardado.py` frena todo `try: SQL → except:
SQL` sin punto de guardado, salvo los de su lista `CONOCIDOS`. Una excepción del
censo no puede apoyarse en un razonamiento: acá cada una se provoca por la
puerta de verdad, en el motor en que corra la suite, y se mira qué contesta.

  · Wallbit (`wallbit_connect`, `wallbit_sync_endpoint`): el `except` atrapa
    `WallbitError`, que nace de la RED (Wallbit caído, key vencida, límite de
    consultas) o de una validación (`_wallbit_ensure_broker`: ya hay un
    «Wallbit» en pesos). Ninguno de los dos es un error de SQL, así que la
    transacción llega sana al plan B, que anota el error del sync. Se mide que
    lo anote y conteste 502, no 500.
  · `_db_internals` (`/api/admin/disk-usage`): lee las tripas de SQLite
    (`PRAGMA`, `dbstat`, `sqlite_master`). En Postgres se mide que el panel
    conteste igual, con el error adentro, en vez de caerse.
"""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import main
import wallbit as W
from tests._limpieza import vaciar  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        vaciar(self.conn, "credit_ledger", "user_broker_credentials", "import_op_links",
               "import_normalized_tx", "import_raw_rows", "import_batches",
               "operations", "positions", "brokers", "users")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"planb-{id(self)}@rendi.test", "x")).lastrowid
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.client = TestClient(main.app)

    def _estado_del_sync(self):
        r = self.conn.execute(
            "SELECT last_sync_status FROM user_broker_credentials "
            "WHERE user_id=? AND broker='wallbit'", (self.uid,)).fetchone()
        self.conn.commit()
        return r["last_sync_status"] if r else None


def _red_caida(*a, **k):
    raise W.WallbitError(0, "No se pudo conectar con Wallbit: timeout")


class WallbitPlanBTest(_Base):
    """El plan B de Wallbit corre sobre una transacción SANA: anota y contesta 502."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(W, "validate_key", lambda api_key: None)
        p.start()
        self.addCleanup(p.stop)

    def test_conectar_con_wallbit_caido(self):
        with mock.patch.object(W, "fetch_trades", _red_caida):
            r = self.client.post("/api/wallbit/connect", json={"api_key": "k-1"})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertEqual(self._estado_del_sync(),
                         "error: No se pudo conectar con Wallbit: timeout")

    def test_conectar_con_un_wallbit_en_pesos_ya_cargado(self):
        """El otro origen de WallbitError: una validación después de una lectura."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Wallbit", "ARS"))
        self.conn.commit()
        r = self.client.post("/api/wallbit/connect", json={"api_key": "k-1"})
        self.assertEqual(r.status_code, 502, r.text)
        self.assertTrue((self._estado_del_sync() or "").startswith("error: Ya tenés un broker"),
                        self._estado_del_sync())

    def test_sincronizar_con_wallbit_caido(self):
        self.conn.execute(
            "INSERT INTO user_broker_credentials (user_id, broker, api_key_enc, scope) "
            "VALUES (?, 'wallbit', ?, 'read')", (self.uid, main._wallbit_encrypt("k-1")))
        self.conn.commit()
        with mock.patch.object(W, "fetch_trades", _red_caida):
            r = self.client.post("/api/wallbit/sync")
        self.assertEqual(r.status_code, 502, r.text)
        self.assertEqual(self._estado_del_sync(),
                         "error: No se pudo conectar con Wallbit: timeout")


class _SinVerElCobroYaAnotado:
    """La conexión real, salvo que el chequeo previo de «¿este cobro ya entró?» no
    encuentra nada: es lo que ve un proceso cuando el otro anota el mismo cobro
    entre su chequeo y su INSERT (un reintento de Rebill a la par)."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        if "FROM credit_ledger" in sql and "payment_id = ?" in sql and sql.lstrip().startswith("SELECT"):
            return self._c.execute(sql.replace("LIMIT 1", "AND 1=0 LIMIT 1"), params)
        return self._c.execute(sql, params)

    def __enter__(self):
        self._c.__enter__()
        return self

    def __exit__(self, *exc):
        return self._c.__exit__(*exc)

    def __getattr__(self, nombre):
        return getattr(self._c, nombre)


class CobroDuplicadoTest(_Base):
    """`billing.credits.grant_payment_credit`: el INSERT del cobro choca contra el
    índice único y el `except` lee el estado (el plan B). El `with conn:` de
    adentro del `try` deshace la transacción ANTES del `except`, así que el plan B
    lee sobre una transacción limpia. Medido: devuelve «duplicado» y el crédito no
    se extiende dos veces."""

    def test_el_mismo_cobro_dos_veces_acredita_una(self):
        from billing import credits
        primero = credits.grant_payment_credit(
            self.conn, self.uid, "plus", "monthly", subscription_id="sub_1", payment_id="pay_1")
        # El aviso «INSERT race» lo deja SÓLO el `except`: prueba que se pasó por el
        # choque contra el índice y no por el chequeo previo.
        with self.assertLogs("billing.credits", level="WARNING") as avisos:
            segundo = credits.grant_payment_credit(
                _SinVerElCobroYaAnotado(self.conn), self.uid, "plus", "monthly",
                subscription_id="sub_1", payment_id="pay_1")
        self.assertTrue(any("INSERT race" in a for a in avisos.output), avisos.output)
        self.assertTrue(segundo.get("duplicate"), segundo)
        self.assertEqual(segundo["active_until"], primero["active_until"])
        n = self.conn.execute("SELECT COUNT(*) FROM credit_ledger WHERE user_id=?",
                              (self.uid,)).fetchone()[0]
        self.conn.commit()
        self.assertEqual(n, 1)


class _ElLedgerRoto:
    """La conexión real, salvo que la lectura previa de `grant_payment_credit`
    («¿este cobro ya entró?») es un SQL que la base rechaza DE VERDAD: una columna
    que no existe, como en un deploy a mitad de camino. En Postgres eso deja la
    transacción abortada; en SQLite, no."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql, params=()):
        if "FROM credit_ledger" in sql and "payment_id = ?" in sql and sql.lstrip().startswith("SELECT"):
            sql = sql.replace("SELECT id,", "SELECT columna_que_no_existe,", 1)
        return self._c.execute(sql, params)

    def __enter__(self):
        self._c.__enter__()
        return self

    def __exit__(self, *exc):
        return self._c.__exit__(*exc)

    def __getattr__(self, nombre):
        return getattr(self._c, nombre)


class ActivarConElLedgerRotoTest(_Base):
    """`_rebill_activate`: si acreditar el cobro falla, la red de seguridad del
    `except` pone una fecha de vencimiento de respaldo. Sin fecha, el usuario
    queda en el plan pago para siempre (el cron sólo baja a los que tienen)."""

    def test_el_usuario_que_pago_queda_con_fecha_de_vencimiento(self):
        # Con el id del cobro, que es lo que activa la lectura previa que se rompe.
        # El registro del fallo prueba que se pasó por el `except` y no por el
        # camino normal.
        with self.assertLogs(main.log.name, level="ERROR") as avisos:
            main._rebill_activate(_ElLedgerRoto(self.conn), self.uid,
                                  {"rendi_plan": "plus", "rendi_period": "monthly"},
                                  "sub_roto", {"payment_id": "pay_roto"})
        self.assertTrue(any("grant_payment_credit falló" in a for a in avisos.output),
                        avisos.output)
        self.conn.rollback()   # leer lo CONFIRMADO, no lo que quedó a medias
        u = self.conn.execute("SELECT tier, credit_active_until FROM users WHERE id=?",
                              (self.uid,)).fetchone()
        self.conn.commit()
        print(f"\n[activar con ledger roto] tier={u['tier']} vence={u['credit_active_until']}")
        self.assertIsNotNone(u["credit_active_until"],
                             f"quedó en {u['tier']} sin fecha de vencimiento")


class DiagnosticoDeLaBaseTest(_Base):
    """`_db_internals`: el panel contesta en los dos motores."""

    def test_el_panel_de_disco_contesta(self):
        main.app.dependency_overrides[main.get_admin_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_admin_user, None)
        r = self.client.get("/api/admin/disk-usage")
        self.assertEqual(r.status_code, 200, r.text)
        internos = r.json()["db_internals"]
        print(f"\n[db_internals] {str(internos)[:300]}")
        if main.USANDO_PG:
            self.assertIn("error", internos)
        else:
            self.assertIn("page_size", str(internos))


if __name__ == "__main__":
    unittest.main()
