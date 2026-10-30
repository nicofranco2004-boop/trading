"""Los dos últimos que escribían la plata sin el turno: la reconstrucción a
mercado y el arranque (tests/test_turno_en_todas_las_puertas.py, `PENDIENTES`).

LA RECONSTRUCCIÓN (`main._reconstruir_mtm` → `backfill_user`) le pregunta a
Yahoo durante minutos. Con el turno tomado durante esa espera, cada depósito o
borrado de la persona esperaría a Yahoo; sin turno al escribir, un depósito
podía confirmarse entre la última comparación de la contabilidad y la escritura
de las fotos. Ahora: Yahoo sin transacción, y el turno recién antes de comparar
y escribir. Dos pruebas, una por cada mitad:
  · durante Yahoo la cuenta está libre — también en la segunda pasada, después
    de que la contabilidad cambió (el turno de la primera se soltó);
  · un depósito que llega entre la comparación y la escritura espera.

EL ARRANQUE (`init_db` → `reparaciones_de_arranque`). Sin volumen, Railway deja
a la copia vieja atendiendo mientras arranca la nueva. Tres pruebas:
  · una reparación de `positions` espera al turno de la cuenta que toca;
  · si una reparación falla, las de abajo corren igual (en Postgres un error
    arruinaba la transacción y, con un solo commit al final, se llevaba todo);
  · dos arranques a la vez van en fila (`_de_a_un_arranque_por_vez`).

Todo entra por las funciones de producción: el import por la API, la
reconstrucción que corre su hilo, un depósito por `cash_flow`, `init_db()`.
Lo único reemplazado es Yahoo y la lista de bonos de data912.
"""
import io
import os
import sys
import threading
import time
import unittest
import uuid
from datetime import date, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import pgsesion  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PG = bool(getattr(main, "USANDO_PG", False))
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
PRECIOS = {f"{2025 + (n - 1) // 12}-{(n - 1) % 12 + 1:02d}": 200.0 + 10 * (n - 3)
           for n in range(1, (date.today().year + 2 - 2025) * 12 + 1)}


def _la_cuenta_esta_libre(uid: int) -> bool:
    """¿Otro pedido podría tomar AHORA el turno de `uid`? Lo intenta desde una
    conexión propia, con un tope de espera corto, y lo suelta."""
    c = main.get_db()
    try:
        if PG:
            c.execute("SET LOCAL lock_timeout = '800ms'")
        else:
            c.execute("PRAGMA busy_timeout = 800")
        main._tomar_turno(c, uid)
        return True
    except Exception:
        return False
    finally:
        try:
            c.rollback()
        finally:
            c.close()


class _CuentaImportada(unittest.TestCase):
    """Una cuenta en IBKR que importa su historia por la app (como
    test_reconstruccion_aportado_canonico)."""

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"turno-mtm-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.http = TestClient(main.app)
        _data912 = mock.patch.object(main, "_fetch_data912_bonds", return_value={})
        _data912.start()
        self.addCleanup(_data912.stop)
        self._fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        bf._fetch_monthly_close = lambda price_key, start_iso: dict(PRECIOS)
        self._importar(
            "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
            "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
            "2025-07-10,DEPOSITO,IBKR,,,,5000,,,0,USD,",
        )

    def tearDown(self):
        bf._fetch_monthly_close = self._fetch_orig
        bf._HIST_CACHE.clear()

    def _importar(self, *filas):
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data={"format": "rendi_generic", "broker": "IBKR"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        for _ in range(300):                  # la reconstrucción del confirm, en su hilo
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.05)
        self.fail("la reconstrucción del import no terminó")

    def _huella_guardada(self):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT huella FROM mtm_huella WHERE user_id=?",
                             (self.uid,)).fetchone()
            return r["huella"] if r else None
        finally:
            conn.close()


class LaReconstruccionNoTieneLaCuentaMientrasPreguntaAYahoo(_CuentaImportada):

    def test_la_cuenta_esta_libre_durante_yahoo_tambien_en_la_segunda_pasada(self):
        consultas = {"n": 0, "tomada": [], "despues_del_cambio": 0}

        def yahoo(price_key, start_iso):
            consultas["n"] += 1
            if not _la_cuenta_esta_libre(self.uid):
                consultas["tomada"].append(consultas["n"])
            if consultas["n"] == 1:
                # La persona cambia la contabilidad mientras tanto: la pasada 1
                # termina con la huella distinta, suelta el turno y vuelve a Yahoo.
                c = main.get_db()
                try:
                    if PG:                    # si la cuenta estuviera tomada, no colgarse
                        c.execute("SET LOCAL lock_timeout = '2s'")
                    main._tomar_turno_de_la_puerta(c, self.uid)
                    c.execute("UPDATE monthly_entries SET deposits = deposits + 1 "
                              "WHERE user_id=? AND broker='global' AND year=2025 AND month=7",
                              (self.uid,))
                    c.commit()
                finally:
                    c.close()
                consultas["despues_del_cambio"] = consultas["n"]
            return dict(PRECIOS)

        bf._fetch_monthly_close = yahoo
        r = main._reconstruir_mtm(self.uid)
        segunda = consultas["n"] - consultas["despues_del_cambio"]
        print(f"\n>>> [{'PG' if PG else 'SQLite'}] consultas={consultas['n']} "
              f"(segunda pasada: {segunda}) tomada_en={consultas['tomada']} r={r}")
        self.assertTrue(r.get("reconstruida"), r)
        self.assertGreater(segunda, 0, "no hubo segunda pasada: la prueba no midió nada")
        self.assertEqual(consultas["tomada"], [],
                         "la cuenta estaba tomada mientras se le preguntaba a Yahoo")


@unittest.skipUnless(PG, "en SQLite el turno no hace nada: la primera escritura toma la base entera")
class UnDepositoEntreLaComparacionYLaEscrituraEspera(_CuentaImportada):

    def test_el_deposito_espera_a_que_la_reconstruccion_confirme(self):
        real = bf._persist_mtm_snapshots
        ventana = {"deposito_terminado_adentro": None}
        listo = threading.Event()
        errores = []

        def depositar():
            try:
                main.cash_flow(main.CashFlowIn(broker_name="IBKR", direction="deposit",
                                               amount=50.0, date="2025-05-10"), uid=self.uid)
            except Exception as ex:
                errores.append(repr(ex))
            finally:
                listo.set()

        def persistir(conn, uid, por_mes):
            # Ya comparó la contabilidad y está por escribir: entra un depósito.
            if ventana["deposito_terminado_adentro"] is None:
                threading.Thread(target=depositar, daemon=True).start()
                ventana["deposito_terminado_adentro"] = listo.wait(timeout=1.5)
            return real(conn, uid, por_mes)

        with mock.patch.object(bf, "_persist_mtm_snapshots", persistir):
            r = main._reconstruir_mtm(self.uid)
        self.assertTrue(listo.wait(timeout=30), "el depósito no terminó nunca")
        conn = main.get_db()
        try:
            dep = conn.execute(
                "SELECT deposits FROM monthly_entries WHERE user_id=? AND broker='global' "
                "AND year=2025 AND month=5", (self.uid,)).fetchone()
            from fechas import hoy_art_date
            ahora = bf.huella_de_entrada(conn, self.uid, hoy_art_date())
        finally:
            conn.close()
        print(f"\n>>> depósito terminado DENTRO de la ventana: "
              f"{ventana['deposito_terminado_adentro']} r={r} err={errores}")
        self.assertTrue(r.get("reconstruida"), r)
        self.assertEqual(errores, [])
        self.assertFalse(ventana["deposito_terminado_adentro"],
                         "el depósito se confirmó entre la comparación de la contabilidad "
                         "y la escritura de las fotos: la reconstrucción escribía sin el turno")
        self.assertIsNotNone(dep, "el depósito no quedó")
        # Las fotos describen la contabilidad de ANTES del depósito, y la huella
        # guardada lo dice: el próximo pedido la ve distinta y reconstruye.
        self.assertNotEqual(self._huella_guardada(), ahora)


@unittest.skipUnless(PG, "en SQLite la primera escritura toma la base entera: no hay cruce")
class BorrarLaCuentaMientrasSeReconstruye(_CuentaImportada):
    """La persona borra su cuenta justo cuando su reconstrucción ya tomó el turno
    y está por escribir las fotos. El borrado toca las fotos y al final `users`;
    la reconstrucción tiene `users` y quiere las fotos. Sin el turno adelante en
    el borrado, Postgres corta a uno de los dos con `deadlock detected`."""

    def test_el_borrado_espera_entero_y_no_quedan_fotos(self):
        real = bf._persist_mtm_snapshots
        errores, listo = [], threading.Event()

        def borrar():
            c = main.get_db()
            try:
                main._borrar_cuenta(c, self.uid)
            except Exception as ex:
                errores.append(f"borrar: {ex!r}")
            finally:
                c.close()
                listo.set()

        def persistir(conn, uid, por_mes):
            if not listo.is_set() and not getattr(persistir, "una_vez", False):
                persistir.una_vez = True
                threading.Thread(target=borrar, daemon=True).start()
                listo.wait(timeout=1.5)          # el borrado no puede terminar: espera el turno
            return real(conn, uid, por_mes)

        with mock.patch.object(bf, "_persist_mtm_snapshots", persistir):
            try:
                r = main._reconstruir_mtm(self.uid)
            except Exception as ex:
                r = {"excepcion": repr(ex)}
        self.assertTrue(listo.wait(timeout=30), "el borrado no terminó")
        conn = main.get_db()
        try:
            queda_usuario = conn.execute("SELECT 1 FROM users WHERE id=?", (self.uid,)).fetchone()
            fotos = conn.execute("SELECT count(*) c FROM snapshots WHERE user_id=?",
                                 (self.uid,)).fetchone()["c"]
        finally:
            conn.close()
        print(f"\n>>> borrar la cuenta durante la reconstrucción: r={r} err={errores} "
              f"usuario={'queda' if queda_usuario else 'borrado'} fotos={fotos}")
        self.assertEqual(errores, [], "el borrado de la cuenta falló")
        self.assertTrue(r.get("reconstruida"), r)
        self.assertIsNone(queda_usuario)
        self.assertEqual(fotos, 0, "quedaron fotos de una cuenta borrada")


class _CajaUSDTEnBrokerDeDolares(unittest.TestCase):
    """La reparación por-boot de `reparaciones_de_arranque`: la caja 'USDT' de un
    broker en dólares pasa a 'USD'."""

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"turno-arranque-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "SchwabTurno", "USD"))
        conn.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested) "
                     "VALUES (?,?,'USDT',1,?)", (self.uid, "SchwabTurno", 321.0))
        conn.commit()
        conn.close()

    def _caja(self):
        conn = main.get_db()
        try:
            return conn.execute("SELECT asset FROM positions WHERE user_id=? AND is_cash=1",
                                (self.uid,)).fetchone()["asset"]
        finally:
            conn.close()


@unittest.skipUnless(PG, "en SQLite el turno no hace nada: la primera escritura toma la base entera")
class LaReparacionEsperaAlTurnoDeLaCuenta(_CajaUSDTEnBrokerDeDolares):

    def test_no_renombra_la_caja_mientras_otro_pedido_tiene_la_cuenta(self):
        otro = main.get_db()
        main._tomar_turno(otro, self.uid)          # un depósito de la copia vieja, a medio camino
        termino = threading.Event()
        errores = []

        def arrancar():
            try:
                with main.db_abierta() as conn:
                    main.reparaciones_de_arranque(conn)
            except Exception as ex:
                errores.append(repr(ex))
            finally:
                termino.set()

        threading.Thread(target=arrancar, daemon=True).start()
        try:
            espero = termino.wait(timeout=1.5)
            caja_mientras = self._caja()
        finally:
            otro.rollback()
            otro.close()
        self.assertTrue(termino.wait(timeout=30), "el arranque no terminó al soltar el turno")
        print(f"\n>>> reparación terminó con la cuenta tomada: {espero}; caja mientras: "
              f"{caja_mientras}; después: {self._caja()}; err={errores}")
        self.assertFalse(espero, "la reparación escribió sin esperar el turno de la cuenta")
        self.assertEqual(caja_mientras, "USDT")
        self.assertEqual(self._caja(), "USD")
        self.assertEqual(errores, [])


class UnaReparacionQueFallaNoSeLlevaALasDemas(_CajaUSDTEnBrokerDeDolares):

    def test_si_falla_la_de_las_cajas_vacias_igual_corren_las_de_abajo(self):
        conn = main.get_db()
        conn.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?,?,?)",
            (self.uid, "token-en-claro-" + uuid.uuid4().hex,
             (datetime.utcnow() + timedelta(hours=1)).isoformat()))
        conn.commit()
        conn.close()
        # La reparación de las cajas vacías revienta con un error de SQL (en
        # Postgres eso arruina la transacción). Las de abajo tienen que correr.
        with mock.patch.object(main._efectivo, "SQL_CAJA_VACIA_CON_PRECIO",
                               "columna_que_no_existe = 1"):
            with main.db_abierta() as conn:
                main.reparaciones_de_arranque(conn)
        conn = main.get_db()
        try:
            tok = conn.execute("SELECT token FROM password_reset_tokens WHERE user_id=?",
                               (self.uid,)).fetchone()["token"]
        finally:
            conn.close()
        print(f"\n>>> [{'PG' if PG else 'SQLite'}] caja={self._caja()} "
              f"token_es_huella={main._es_huella(tok)}")
        self.assertEqual(self._caja(), "USD", "la de arriba de la que falla no quedó")
        self.assertTrue(main._es_huella(tok),
                        "el token quedó en claro: la reparación que falló se llevó a las de abajo")


@unittest.skipUnless(PG, "el candado del arranque es de Postgres (con SQLite hay volumen y no se superponen copias)")
class DosArranquesVanEnFila(unittest.TestCase):

    def test_el_segundo_arranque_espera_al_primero(self):
        primero = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        primero.execute("SELECT pg_advisory_lock(%s, hashtext(current_schema()))",
                        (pgsesion.TURNO_ARRANQUE,))
        termino = threading.Event()
        errores = []

        def arrancar():
            try:
                main.init_db()
            except Exception as ex:
                errores.append(repr(ex))
            finally:
                termino.set()

        threading.Thread(target=arrancar, daemon=True).start()
        try:
            espero = termino.wait(timeout=1.5)
        finally:
            primero.execute("SELECT pg_advisory_unlock(%s, hashtext(current_schema()))",
                            (pgsesion.TURNO_ARRANQUE,))
            primero.close()
        self.assertTrue(termino.wait(timeout=120), "el segundo arranque no terminó")
        print(f"\n>>> segundo arranque terminó con el primero adentro: {espero}; err={errores}")
        self.assertFalse(espero, "dos arranques corrieron a la vez")
        self.assertEqual(errores, [])

    def test_el_candado_se_suelta_al_terminar(self):
        main.init_db()
        otro = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        try:
            libre = otro.execute("SELECT pg_try_advisory_lock(%s, hashtext(current_schema()))",
                                 (pgsesion.TURNO_ARRANQUE,)).fetchone()[0]
            if libre:
                otro.execute("SELECT pg_advisory_unlock(%s, hashtext(current_schema()))",
                             (pgsesion.TURNO_ARRANQUE,))
        finally:
            otro.close()
        self.assertTrue(libre, "init_db terminó y dejó el candado del arranque puesto")


if __name__ == "__main__":
    unittest.main()
