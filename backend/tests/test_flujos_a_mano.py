"""Cada depósito o retiro CARGADO A MANO queda anotado, de a uno y con su hora.

Por qué. `monthly_entries.manual_*` es una suma por mes y broker: tres depósitos a
mano de marzo son un número. Las fotos diarias anotan lo aportado en el momento en
que se sacan (el cron suma todo lo cargado hasta ahí, sin mirar fechas), así que para
que un borrado le saque a cada foto sólo lo que esa foto tenía hace falta saber
CUÁNDO entró cada parte de la suma. Sin eso, `main._cambio_de_aportado` lo deduce de
los saltos entre fotos, y con varias cargas en un mismo renglón falla casi siempre
(prueba al azar, 2026-10-08: 167 de 175 escenarios con fotos mal).

Acá se fija:
  · cada puerta que suma lo manual anota su carga (`flujos_a_mano`), con la hora del
    MISMO reloj que la confirmación de un import, el día del movimiento y de dónde
    salió; las que lo sacan la anulan y los deshacer la reviven con su hora original;
  · la suma del mes es, siempre, la suma de sus cargas vigentes (con una seguidilla
    al azar de todas las puertas por HTTP);
  · nadie vuelve a sumar lo manual por fuera de las puertas (guardián del código).

Todo por HTTP, como la app, salvo la compensación de la transferencia del chat (que
la app llama como función y acá también).
"""
import ast
import json
import os
import random
import re
import sys
import tempfile
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient

import main

MAIN = os.path.join(BACKEND, "main.py")
_AHORA_UTC_DE_VERDAD = main._ahora_utc    # antes de que ningún test lo reemplace


class Reloj:
    """La hora que ve la app al anotar una carga (`main._ahora_utc`)."""

    def __init__(self, t="2026-03-10 15:00:00"):
        self.t = t

    def __call__(self):
        return self.t


class FlujosAManoBase(unittest.TestCase):
    BROKER = "IBKR"
    VACIO = "MANUAL"       # sin saldo: una posición ahí dispara un autodepósito

    def setUp(self):
        self.conn = main.get_db()
        self.conn.execute("PRAGMA foreign_keys=OFF")
        for t in ("flujos_a_mano", "deleted_ops_journal", "positions", "operations",
                  "monthly_entries", "snapshots", "plazos_fijos", "brokers", "config"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"flujos-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        for b in (self.BROKER, self.VACIO):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, b, "USDT"))
        self.conn.commit()
        self.reloj = Reloj()
        for p in (mock.patch.object(main, "_ahora_utc", side_effect=self.reloj),
                  # la reconstrucción a mercado en otro hilo no es lo que se mide
                  mock.patch.object(main, "_reconstruir_mtm_post_import",
                                    side_effect=lambda *a, **k: None),
                  mock.patch.object(main, "_reconstruir_en_fila",
                                    side_effect=lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        self.http = TestClient(main.app)

    def tearDown(self):
        self.conn.close()

    # ── infra ──
    def _flujos(self, **donde):
        where = ["user_id=?"] + [f"{k}=?" for k in donde]
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM flujos_a_mano WHERE {' AND '.join(where)} ORDER BY id",
            (self.uid, *donde.values())).fetchall()]

    def _vigentes(self, **donde):
        return [f for f in self._flujos(**donde) if f["anulado_at"] is None]

    def _renglon(self, broker, y, m):
        return self.conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
            (self.uid, broker, y, m)).fetchone()

    def _depositar(self, monto, fecha=None, direction="deposit", broker=None):
        body = {"broker_name": broker or self.BROKER, "direction": direction, "amount": monto}
        if fecha:
            body["date"] = fecha
        r = self.http.post("/api/cash/flow", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _posicion(self, monto, fecha="2026-03-05", activo="KO"):
        r = self.http.post("/api/positions", json={
            "broker": self.VACIO, "asset": activo, "buy_price": 50.0,
            "quantity": monto / 50.0, "invested": monto, "entry_date": fecha})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def assert_suma_es_sus_cargas(self, cuando=""):
        """La suma de lo manual de cada renglón (broker) es la suma de sus cargas
        vigentes. Y la moneda del broker también, salvo en renglones tocados desde
        /mensual (esa puerta nunca escribió las columnas en moneda del broker)."""
        mal = []
        for r in self.conn.execute(
                "SELECT * FROM monthly_entries WHERE user_id=? AND broker <> 'global'",
                (self.uid,)).fetchall():
            fl = self._vigentes(broker=r["broker"], year=r["year"], month=r["month"])
            for direction, col, nat in (("deposit", "manual_deposits", "manual_deposits_native"),
                                        ("withdraw", "manual_withdrawals", "manual_withdrawals_native")):
                de = [f for f in fl if f["direction"] == direction]
                suma = sum(f["monto_usd"] for f in de)
                if abs(float(r[col] or 0) - suma) > 0.01:
                    mal.append(f"{r['broker']} {r['year']}-{r['month']:02d} {col}: "
                               f"renglón {float(r[col] or 0):.2f}, cargas {suma:.2f}")
                if not any(f["origen"] == "mensual" for f in self._flujos(
                        broker=r["broker"], year=r["year"], month=r["month"])):
                    snat = sum(f["monto_nativo"] or 0 for f in de)
                    if abs(float(r[nat] or 0) - snat) > 0.01:
                        mal.append(f"{r['broker']} {r['year']}-{r['month']:02d} {nat}: "
                                   f"renglón {float(r[nat] or 0):.2f}, cargas {snat:.2f}")
        # Cargas vigentes de un mes SIN renglón: tienen que sumar 0 (si no, vuelven a
        # contar cuando el renglón renace).
        con_renglon = {(r["broker"], r["year"], r["month"]) for r in self.conn.execute(
            "SELECT broker, year, month FROM monthly_entries WHERE user_id=?", (self.uid,))}
        huerfanas = {}
        for f in self._vigentes():
            k = (f["broker"], f["year"], f["month"])
            if k not in con_renglon:
                huerfanas[k] = huerfanas.get(k, 0.0) + (1 if f["direction"] == "deposit" else -1) * f["monto_usd"]
        mal += [f"{k}: cargas vigentes sin renglón por {v:.2f}" for k, v in huerfanas.items()
                if abs(v) > 0.01]
        self.assertEqual(mal, [], f"{cuando}: la suma del mes no es la de sus cargas")


class CadaPuertaAnotaSuCarga(FlujosAManoBase):

    def test_el_boton_anota_la_carga_con_su_hora_y_su_dia(self):
        self.reloj.t = "2026-03-10 17:30:00"
        out = self._depositar(1500.0, fecha="2026-02-20")
        [f] = self._flujos()
        self.assertEqual(out.get("flujo_id"), f["id"])
        self.assertEqual((f["broker"], f["year"], f["month"], f["direction"]),
                         (self.BROKER, 2026, 2, "deposit"))
        self.assertAlmostEqual(f["monto_usd"], 1500.0)
        self.assertAlmostEqual(f["monto_nativo"], 1500.0)
        self.assertEqual(f["fecha"], "2026-02-20")
        # El MISMO reloj y formato que `import_batches.confirmed_at`.
        self.assertEqual(f["cargado_at"], "2026-03-10 17:30:00")
        self.assertEqual(f["origen"], "efectivo")
        self.assertIsNone(f["anulado_at"])
        self.assert_suma_es_sus_cargas()

    def test_el_reloj_es_el_de_la_confirmacion_de_un_import(self):
        """El reloj de verdad da lo mismo, y en el mismo formato, que `datetime('now')`
        de SQLite — con el que se guarda `import_batches.confirmed_at`."""
        antes = self.conn.execute("SELECT datetime('now') AS t").fetchone()["t"]
        t = _AHORA_UTC_DE_VERDAD()
        despues = self.conn.execute("SELECT datetime('now') AS t").fetchone()["t"]
        self.assertRegex(t, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertTrue(antes <= t <= despues, (antes, t, despues))

    def test_un_retiro_tambien(self):
        self._depositar(1000.0, fecha="2026-03-01")
        self._depositar(300.0, fecha="2026-03-02", direction="withdraw")
        w = self._flujos(direction="withdraw")
        self.assertEqual(len(w), 1)
        self.assertAlmostEqual(w[0]["monto_usd"], 300.0)
        self.assert_suma_es_sus_cargas()

    def test_sin_fecha_el_dia_es_hoy_en_argentina(self):
        with mock.patch.object(main, "_iso_today", return_value="2026-03-10"):
            self._depositar(200.0)
        self.assertEqual(self._flujos()[0]["fecha"], "2026-03-10")

    def test_la_posicion_a_mano_anota_su_autodeposito(self):
        self.reloj.t = "2026-03-06 13:00:00"
        pid = self._posicion(2000.0, fecha="2026-03-05")
        [f] = self._flujos()
        self.assertEqual((f["broker"], f["origen"], f["ref"], f["fecha"]),
                         (self.VACIO, "autodeposito", f"pos:{pid}", "2026-03-05"))
        self.assertEqual(f["cargado_at"], "2026-03-06 13:00:00")
        meta = json.loads(self.conn.execute(
            "SELECT undo_meta_json FROM positions WHERE id=?", (pid,)).fetchone()[0])
        self.assertEqual(meta["autodep"]["flujo_id"], f["id"])
        self.assert_suma_es_sus_cargas()

    def test_borrar_la_posicion_anula_y_deshacer_revive_con_la_hora_original(self):
        self.reloj.t = "2026-03-06 13:00:00"
        pid = self._posicion(2000.0)
        self.reloj.t = "2026-03-20 10:00:00"
        r = self.http.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        [f] = self._flujos()
        self.assertEqual((f["anulado_at"], f["anulado_motivo"]),
                         ("2026-03-20 10:00:00", "posicion_borrada"))
        self.assert_suma_es_sus_cargas("después de borrar")
        self.reloj.t = "2026-03-21 10:00:00"
        r = self.http.post(f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(r.status_code, 200, r.text)
        [f] = self._flujos()
        self.assertIsNone(f["anulado_at"])
        self.assertEqual(f["cargado_at"], "2026-03-06 13:00:00",
                         "el deshacer devuelve LA MISMA carga: las fotos la tenían desde antes")
        self.assert_suma_es_sus_cargas("después de deshacer")

    def test_el_plazo_fijo_anota_su_autodeposito(self):
        r = self.http.post("/api/plazos-fijos", json={
            "banco": "Galicia", "capital": 1000.0, "moneda": "USD", "tasa": 0.03,
            "fecha_inicio": "2026-03-01", "plazo_dias": 30, "source_broker": self.VACIO})
        self.assertEqual(r.status_code, 200, r.text)
        [f] = self._flujos()
        self.assertEqual((f["origen"], f["ref"], f["fecha"]),
                         ("plazo_fijo", f"pf:{r.json()['id']}", "2026-03-01"))
        self.assert_suma_es_sus_cargas()

    def test_conciliar_el_saldo_anota_la_diferencia_sin_dia(self):
        self._depositar(1000.0, fecha="2026-01-10")
        r = self.http.post("/api/brokers/reconcile-cash",
                           json={"broker_name": self.BROKER, "target_cash": 1250.0})
        self.assertEqual(r.status_code, 200, r.text)
        f = self._flujos(origen="conciliacion")
        self.assertEqual(len(f), 1)
        self.assertAlmostEqual(f[0]["monto_usd"], 250.0)
        self.assertIsNone(f[0]["fecha"])
        self.assertEqual((f[0]["year"], f[0]["month"]), (2026, 1))   # el mes más viejo
        self.assert_suma_es_sus_cargas()

    def test_editar_mensual_anota_la_diferencia_y_global_no(self):
        self._depositar(1000.0, fecha="2026-03-01")
        for broker, mas in ((self.BROKER, 400.0), ("global", 250.0)):
            row = self._renglon(broker, 2026, 3)
            body = {k: float(row[k] or 0) for k in ("deposits", "withdrawals", "pnl_realized",
                                                    "capital_inicio", "capital_final")}
            body.update({"year": 2026, "month": 3, "broker": broker, "pnl_unrealized": 0.0})
            body["deposits"] += mas
            body["capital_final"] += mas
            r = self.http.put(f"/api/monthly/{row['id']}", json=body)
            self.assertEqual(r.status_code, 200, r.text)
        m = self._flujos(origen="mensual")
        self.assertEqual([(f["broker"], round(f["monto_usd"], 2)) for f in m],
                         [(self.BROKER, 400.0)],
                         "Global no se anota: el recálculo la rearma con la suma de los brokers")
        self.assert_suma_es_sus_cargas()

    def test_editar_un_broker_en_mensual_llega_al_total_en_el_momento(self):
        """El total que leen el Dashboard, el cron y las fotos es el renglón Global.
        Editar el mes de un broker en /mensual lo cambiaba recién en el próximo
        recálculo (un import o un borrado): mientras tanto el capital aportado no se
        movía, y después ninguna foto sabía desde cuándo tenía esa plata."""
        import snapshots_job
        self._depositar(1000.0, fecha="2026-03-01")
        antes = snapshots_job.compute_net_deposited_db(self.conn, self.uid)
        row = self._renglon(self.BROKER, 2026, 3)
        body = {k: float(row[k] or 0) for k in ("deposits", "withdrawals", "pnl_realized",
                                                "capital_inicio", "capital_final")}
        body.update({"year": 2026, "month": 3, "broker": self.BROKER, "pnl_unrealized": 0.0})
        body["deposits"] += 400.0
        body["capital_final"] += 400.0
        self.assertEqual(self.http.put(f"/api/monthly/{row['id']}", json=body).status_code, 200)
        self.assertAlmostEqual(snapshots_job.compute_net_deposited_db(self.conn, self.uid),
                               antes + 400.0, places=2)
        # Y bajarlo lo baja.
        row = self._renglon(self.BROKER, 2026, 3)
        body["deposits"] -= 150.0
        body["capital_final"] -= 150.0
        self.assertEqual(self.http.put(f"/api/monthly/{row['id']}", json=body).status_code, 200)
        self.assertAlmostEqual(snapshots_job.compute_net_deposited_db(self.conn, self.uid),
                               antes + 250.0, places=2)
        # Lo mismo que dice el recálculo (antes, el recálculo era el que lo hacía llegar).
        main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        self.conn.commit()
        self.assertAlmostEqual(snapshots_job.compute_net_deposited_db(self.conn, self.uid),
                               antes + 250.0, places=2)
        self.assert_suma_es_sus_cargas()

    def test_crear_un_renglon_en_mensual_anota_lo_manual(self):
        """Sin renglón de Global ese mes, no se crea (declarar el capital inicial es
        broker primero y Global después, con su arranque): la carga queda como que el
        cron no la vio."""
        r = self.http.post("/api/monthly", json={
            "year": 2026, "month": 1, "broker": self.BROKER, "deposits": 700.0,
            "withdrawals": 50.0, "capital_inicio": 0.0, "capital_final": 650.0})
        self.assertEqual(r.status_code, 200, r.text)
        m = sorted((f["direction"], f["monto_usd"]) for f in self._flujos(origen="mensual_sin_global"))
        self.assertEqual(m, [("deposit", 700.0), ("withdraw", 50.0)])
        self.assertIsNone(self._renglon("global", 2026, 1))
        self.assert_suma_es_sus_cargas()

    def test_declarar_el_capital_inicial_broker_y_despues_global(self):
        """El camino de /mensual para el capital que ya tenías: el renglón del broker
        y después el de Global, cada uno con su arranque."""
        for b in (self.BROKER, "global"):
            r = self.http.post("/api/monthly", json={
                "year": 2026, "month": 2, "broker": b, "capital_inicio": 50000,
                "deposits": 1000, "capital_final": 51000})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(float(self._renglon("global", 2026, 2)["capital_inicio"]), 50000.0)

    def test_crear_un_renglon_con_global_ya_creado_llega_a_global(self):
        """"Pasar al mes siguiente" crea Global primero y después cada broker: lo que se
        escriba en el broker llega a Global en el momento."""
        for b, dep in (("global", 0.0), (self.BROKER, 300.0)):
            r = self.http.post("/api/monthly", json={
                "year": 2026, "month": 4, "broker": b, "deposits": dep,
                "capital_inicio": 0.0, "capital_final": dep})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(float(self._renglon("global", 2026, 4)["deposits"]), 300.0)
        self.assertEqual([f["origen"] for f in self._flujos()], ["mensual"])
        self.assert_suma_es_sus_cargas()

    def test_borrar_el_mes_desde_movimientos_anula_sus_cargas(self):
        self._depositar(1000.0, fecha="2026-03-01")
        self._depositar(500.0, fecha="2026-03-15")
        self._depositar(100.0, fecha="2026-03-16", direction="withdraw")
        self._depositar(70.0, fecha="2026-04-02")
        row = self._renglon(self.BROKER, 2026, 3)
        r = self.http.delete(f"/api/movements/me-{row['id']}-dep")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self._vigentes(year=2026, month=3, direction="deposit")), 0)
        self.assertEqual(len(self._vigentes(year=2026, month=3, direction="withdraw")), 1)
        self.assertEqual(len(self._vigentes(year=2026, month=4)), 1)
        self.assertTrue(all(f["anulado_motivo"] == "movimiento_borrado"
                            for f in self._flujos(year=2026, month=3, direction="deposit")))
        self.assert_suma_es_sus_cargas()

    def test_borrar_lo_de_uno_no_toca_lo_de_otro(self):
        """Otra persona con un broker del mismo nombre y cargas el mismo mes: borrar el
        mes, el renglón o el broker de una no le anula nada a la otra (los brokers se
        atan por NOMBRE, así que el nombre solo no alcanza)."""
        otro = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"otro-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (otro, self.BROKER, "USDT"))
        self.conn.commit()
        main.app.dependency_overrides[main.get_effective_user] = lambda: otro
        self._depositar(800.0, fecha="2026-03-03")
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self._depositar(1000.0, fecha="2026-03-01")
        row = self._renglon(self.BROKER, 2026, 3)
        self.assertEqual(self.http.delete(f"/api/movements/me-{row['id']}-dep").status_code, 200)
        self._depositar(500.0, fecha="2026-03-09")
        row = self._renglon(self.BROKER, 2026, 3)
        self.assertEqual(self.http.delete(f"/api/monthly/{row['id']}").status_code, 200)
        bid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                (self.uid, self.BROKER)).fetchone()["id"]
        self.assertEqual(self.http.delete(f"/api/brokers/{bid}",
                                          params={"force": "true"}).status_code, 200)
        vivas = self.conn.execute(
            "SELECT COUNT(*) FROM flujos_a_mano WHERE user_id=? AND anulado_at IS NULL",
            (otro,)).fetchone()[0]
        self.assertEqual(vivas, 1, "se anularon cargas de otra persona")

    def test_borrar_un_renglon_de_mensual_anula_sus_cargas(self):
        self._depositar(1000.0, fecha="2026-03-01")
        row = self._renglon(self.BROKER, 2026, 3)
        r = self.http.delete(f"/api/monthly/{row['id']}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._vigentes(), [])

    def test_borrar_el_broker_anula_y_renombrar_mueve(self):
        self._depositar(1000.0, fecha="2026-03-01")
        self._posicion(300.0)
        bid = self.conn.execute("SELECT id FROM brokers WHERE user_id=? AND name=?",
                                (self.uid, self.BROKER)).fetchone()["id"]
        r = self.http.put(f"/api/brokers/{bid}", json={"name": "Interactive", "currency": "USDT"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({f["broker"] for f in self._flujos(origen="efectivo")}, {"Interactive"})
        self.assert_suma_es_sus_cargas("después de renombrar")
        r = self.http.delete(f"/api/brokers/{bid}", params={"force": "true"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._vigentes(broker="Interactive"), [])
        self.assertEqual(len(self._vigentes(broker=self.VACIO)), 1, "el otro broker no se toca")

    def test_vaciar_el_broker_desde_el_importador_anula(self):
        self._depositar(1000.0, fecha="2026-03-01")
        self._posicion(300.0)
        r = self.http.post("/api/imports/wipe-broker", params={"broker": self.BROKER})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._vigentes(broker=self.BROKER), [])
        self.assertEqual([f["anulado_motivo"] for f in self._flujos(broker=self.BROKER)],
                         ["broker_vaciado"])
        self.assertEqual(len(self._vigentes(broker=self.VACIO)), 1, "el otro broker no se toca")

    def test_empezar_de_cero_se_lleva_el_detalle(self):
        self.assertIn("flujos_a_mano", main._RESET_PORTFOLIO_TABLES)
        self.assertIn("flujos_a_mano", main.NAME_KEYED_TABLES)

    def test_la_transferencia_del_chat_compensada_anula_el_retiro(self):
        """El chat transfiere con dos `cash_flow`; si el depósito en el destino falla,
        compensa el retiro con `_revert_cash_flow`. Las mismas funciones, en el mismo
        orden."""
        self._depositar(1000.0, fecha="2026-03-01")
        ret = main.cash_flow(main.CashFlowIn(broker_name=self.BROKER, direction="withdraw",
                                             amount=400.0, tc_blue=1200.0, date="2026-03-05"),
                             self.uid)
        main._revert_cash_flow(self.uid, self.BROKER, "withdraw", 400.0, 1200.0, "2026-03-05",
                               flujo_id=ret.get("flujo_id"))
        [w] = self._flujos(direction="withdraw")
        self.assertEqual(w["anulado_motivo"], "transferencia_compensada")
        mal = [f for f in self._vigentes() if f["direction"] == "withdraw"]
        self.assertEqual(mal, [])
        # La compensación nunca restó la columna en moneda del broker (se conserva
        # igual): sólo se compara el USD.
        r = self._renglon(self.BROKER, 2026, 3)
        self.assertAlmostEqual(float(r["manual_withdrawals"] or 0), 0.0)

    def test_la_compensacion_en_pesos_resta_exactamente_lo_que_sumo_la_carga(self):
        """En un broker en pesos `cash_flow` convierte con el dólar del DÍA y el chat
        compensa con el suyo. Si no son el mismo, restar recalculando dejaba un resto
        en el mes (400.000 / 1.200 − 400.000 / 1.500 = US$ 66,67) y la columna en
        pesos inflada. Se resta lo que dice la carga."""
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        self.conn.commit()
        r = self.http.post("/api/cash/flow", json={"broker_name": "Cocos", "direction": "deposit",
                                                   "amount": 1_000_000.0, "date": "2026-03-01"})
        self.assertEqual(r.status_code, 200, r.text)
        with mock.patch.object(main, "_manual_flow_rate", return_value=1500.0):
            ret = main.cash_flow(main.CashFlowIn(broker_name="Cocos", direction="withdraw",
                                                 amount=400_000.0, tc_blue=1200.0,
                                                 date="2026-03-05"), self.uid)
        main._revert_cash_flow(self.uid, "Cocos", "withdraw", 400_000.0, 1200.0, "2026-03-05",
                               flujo_id=ret.get("flujo_id"))
        r = self._renglon("Cocos", 2026, 3)
        self.assertAlmostEqual(float(r["manual_withdrawals"] or 0), 0.0, places=4)
        self.assertAlmostEqual(float(r["manual_withdrawals_native"] or 0), 0.0, places=4)
        self.assert_suma_es_sus_cargas()


class LoQueEncontroLaAuditoria1(FlujosAManoBase):
    """Defectos de la primera versión (auditoría 2026-10-09). Cada uno falla sin su
    arreglo."""

    def test_borrar_la_posicion_cuando_su_deposito_ya_se_fue_no_se_come_otro(self):
        """El renglón del mes se borró en /mensual (se llevó el autodepósito); después
        entró otro depósito del mismo monto. Borrar la posición restaba el autodepósito
        otra vez y se comía el depósito nuevo. Ahora frena, como ya frenaba cuando el
        depósito se había borrado desde Movimientos."""
        pid = self._posicion(1000.0, fecha="2026-03-05")
        row = self._renglon(self.VACIO, 2026, 3)
        self.assertEqual(self.http.delete(f"/api/monthly/{row['id']}").status_code, 200)
        self._depositar(1000.0, fecha="2026-03-10", broker=self.VACIO)
        r = self.http.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 409, r.text)
        self.assertAlmostEqual(float(self._renglon(self.VACIO, 2026, 3)["manual_deposits"]), 1000.0)
        self.assert_suma_es_sus_cargas()

    def test_bajar_el_mes_en_mensual_y_despues_borrar_la_posicion_frena(self):
        """/mensual no escribe la columna en moneda del broker: el control viejo (sólo
        con esa columna) dejaba pasar el borrado y lo manual quedaba en −1.000."""
        pid = self._posicion(1000.0, fecha="2026-03-05")
        row = self._renglon(self.VACIO, 2026, 3)
        body = {k: max(0.0, float(row[k] or 0)) for k in (
            "withdrawals", "pnl_realized", "capital_inicio", "capital_final")}
        body.update({"year": 2026, "month": 3, "broker": self.VACIO, "deposits": 0.0,
                     "pnl_unrealized": 0.0})
        self.assertEqual(self.http.put(f"/api/monthly/{row['id']}", json=body).status_code, 200)
        self.assertEqual(self.http.delete(f"/api/positions/{pid}").status_code, 409)
        self.assert_suma_es_sus_cargas()

    def test_el_recalculo_que_borra_un_renglon_vacio_anula_sus_cargas(self):
        self._depositar(1000.0, fecha="2026-03-05")
        row = self._renglon(self.BROKER, 2026, 3)
        body = {k: max(0.0, float(row[k] or 0)) for k in (
            "withdrawals", "pnl_realized", "capital_inicio")}
        body.update({"year": 2026, "month": 3, "broker": self.BROKER, "deposits": 0.0,
                     "capital_final": 0.0, "pnl_unrealized": 0.0})
        self.assertEqual(self.http.put(f"/api/monthly/{row['id']}", json=body).status_code, 200)
        main._recalc_pnl_realized_from_ops(self.conn, self.uid)   # lo que corre un import
        self.conn.commit()
        self.assertIsNone(self._renglon(self.BROKER, 2026, 3))
        self.assertEqual(self._vigentes(year=2026, month=3), [])
        self._depositar(500.0, fecha="2026-03-20")
        self.assert_suma_es_sus_cargas()

    def test_editar_mensual_toma_el_turno_antes_de_leer(self):
        """SQLite abre la transacción en la primera escritura: lo que se lee antes
        puede cambiar. El turno tiene que tomarse antes de leer lo manual que había."""
        self._depositar(1000.0, fecha="2026-03-01")
        orden = []
        tomar, derivar = main._tomar_turno, main._derive_manual_flows
        with mock.patch.object(main, "_tomar_turno",
                               side_effect=lambda *a: (orden.append("turno"), tomar(*a))[1]), \
                mock.patch.object(main, "_derive_manual_flows",
                                  side_effect=lambda *a: (orden.append("leer"), derivar(*a))[1]):
            row = self._renglon(self.BROKER, 2026, 3)
            body = {k: float(row[k] or 0) for k in ("deposits", "withdrawals", "pnl_realized",
                                                    "capital_inicio", "capital_final")}
            body.update({"year": 2026, "month": 3, "broker": self.BROKER, "pnl_unrealized": 0.0})
            self.assertEqual(self.http.put(f"/api/monthly/{row['id']}", json=body).status_code, 200)
        self.assertEqual(orden[:2], ["turno", "leer"])

    def test_sin_fecha_el_mes_es_el_argentino_en_las_cuatro_puertas(self):
        """De 21 a 24 hs del último día del mes, UTC ya es el mes siguiente."""
        with mock.patch.object(main, "_iso_today", return_value="2026-11-30"):
            self._depositar(100.0)
            ret = main.cash_flow(main.CashFlowIn(broker_name=self.BROKER, direction="withdraw",
                                                 amount=40.0, tc_blue=1.0), self.uid)
            main._revert_cash_flow(self.uid, self.BROKER, "withdraw", 40.0, 1.0,
                                   flujo_id=ret.get("flujo_id"))
            r = self.http.post("/api/brokers/reconcile-cash",
                               json={"broker_name": self.VACIO, "target_cash": 50.0})
            self.assertEqual(r.status_code, 200, r.text)
        fl = self._flujos()
        self.assertEqual({(f["year"], f["month"]) for f in fl}, {(2026, 11)}, fl)
        self.assertEqual(self._flujos(origen="efectivo")[0]["fecha"], "2026-11-30")
        self.assertIsNotNone(self._renglon(self.BROKER, 2026, 11))
        self.assertIsNotNone(self._renglon(self.VACIO, 2026, 11))
        self.assert_suma_es_sus_cargas()

    def test_la_reparacion_del_dolar_1415_no_toca_meses_con_cargas(self):
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status, "
            "confirmed_at) VALUES (?,?,?,?,?,?,?)",
            (f"lote-{uuid.uuid4().hex[:6]}", self.uid, "Cocos", "x", "x", "confirmed",
             "2026-07-02 15:00:00"))
        self.conn.commit()
        with mock.patch.object(main, "_manual_flow_rate", return_value=1415.0):
            r = self.http.post("/api/cash/flow", json={"broker_name": "Cocos", "direction": "deposit",
                                                       "amount": 1_415_000.0, "date": "2026-06-02"})
        self.assertEqual(r.status_code, 200, r.text)
        with mock.patch.object(main, "_manual_flow_rate", return_value=1500.0):
            main._repair_caja_1415(self.conn, apply=True)
        self.assertAlmostEqual(float(self._renglon("Cocos", 2026, 6)["manual_deposits"]), 1000.0)
        self.assert_suma_es_sus_cargas()

    def test_deshacer_la_posicion_deja_la_carga_apuntando_al_id_nuevo(self):
        pid = self._posicion(700.0)
        r = self.http.delete(f"/api/positions/{pid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.http.post(f"/api/operations/undo/{r.json()['undo_token']}").status_code, 200)
        nuevo = self.conn.execute("SELECT id FROM positions WHERE user_id=? AND is_cash=0",
                                  (self.uid,)).fetchone()["id"]
        self.assertEqual(self._flujos()[0]["ref"], f"pos:{nuevo}")


class LoQueEncontroLaAuditoria2(FlujosAManoBase):
    """/mensual y Global (auditoría 2026-10-09, segunda vuelta)."""

    def _put(self, broker, y, m, **cambios):
        row = self._renglon(broker, y, m)
        body = {k: max(0.0, float(row[k] or 0)) for k in (
            "deposits", "withdrawals", "pnl_realized", "capital_inicio", "capital_final")}
        body.update({"year": y, "month": m, "broker": broker, "pnl_unrealized": 0.0})
        body.update(cambios)
        r = self.http.put(f"/api/monthly/{row['id']}", json=body)
        self.assertEqual(r.status_code, 200, r.text)

    def _aportado(self):
        import snapshots_job
        return round(snapshots_job.compute_net_deposited_db(self.conn, self.uid), 2)

    def test_global_emparejado_a_mano_y_despues_el_broker_no_cuenta_dos_veces(self):
        """Antes la app no avisaba a Global al editar un broker y la gente lo emparejaba
        a mano: si edita Global primero y el broker después, sumarle lo del broker
        contaba la plata dos veces."""
        self._depositar(20000.0, fecha="2026-02-01")
        self._put("global", 2026, 2, deposits=20500.0)
        self._put(self.BROKER, 2026, 2, deposits=20500.0)
        self.assertEqual(self._aportado(), 20500.0)
        self.assertEqual([f["origen"] for f in self._flujos(origen="mensual_sin_global")],
                         ["mensual_sin_global"])

    def test_crear_global_y_despues_el_broker_con_la_misma_plata(self):
        self._depositar(1000.0, fecha="2026-03-01")
        for b in ("global", self.BROKER):
            r = self.http.post("/api/monthly", json={"year": 2026, "month": 2, "broker": b,
                                                     "deposits": 10000.0, "capital_final": 10000.0})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._aportado(), 11000.0)

    def test_borrar_el_renglon_de_un_broker_lo_saca_del_total_en_el_momento(self):
        self._depositar(20000.0, fecha="2026-02-01")
        self._depositar(100.0, fecha="2026-03-01")
        self._put(self.BROKER, 2026, 3, deposits=5100.0)
        self.assertEqual(self._aportado(), 25100.0)
        r = self.http.delete(f"/api/monthly/{self._renglon(self.BROKER, 2026, 3)['id']}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._aportado(), 20000.0)
        main._recalc_pnl_realized_from_ops(self.conn, self.uid)   # y el recálculo dice lo mismo
        self.conn.commit()
        self.assertEqual(self._aportado(), 20000.0)
        self.assert_suma_es_sus_cargas()

    def test_deshacer_anota_el_tramo_en_que_estuvo_borrada(self):
        self.reloj.t = "2026-03-05 15:00:00"
        pid = self._posicion(1000.0)
        self.reloj.t = "2026-03-10 15:00:00"
        r = self.http.delete(f"/api/positions/{pid}")
        self.reloj.t = "2026-03-13 15:00:00"
        self.assertEqual(self.http.post(f"/api/operations/undo/{r.json()['undo_token']}").status_code, 200)
        self.assertEqual(json.loads(self._flujos()[0]["pausas"]), [["2026-03-10", "2026-03-13"]])


class OperacionGrupalDelAsesor(FlujosAManoBase):
    """La operación grupal da de alta la misma posición en N clientes (autodepósito
    en los que no tienen saldo) y su deshacer la saca."""

    def setUp(self):
        super().setUp()
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        tag = uuid.uuid4().hex[:8]
        c = self.conn
        self.asesor = c.execute("INSERT INTO users (email, password_hash, approved, tier) "
                                "VALUES (?,?,1,'advisor')", (f"asesor-{tag}@rendi.test", "x")).lastrowid
        self.cliente = c.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,0)",
                                 (f"cliente-{tag}@rendi.test", "x")).lastrowid
        c.execute("UPDATE users SET managed_by=? WHERE id=?", (self.asesor, self.cliente))
        c.execute("""INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission,
                     status, label) VALUES (?,?,'managed','read_write','active','Juan')""",
                  (self.asesor, self.cliente))
        c.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                  (self.cliente, "Cocos", "USDT"))
        c.commit()
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.asesor)}"}

        def _limpiar():
            k = main.get_db()
            k.execute("""DELETE FROM advisor_op_batch_items WHERE batch_id IN
                         (SELECT id FROM advisor_op_batches WHERE advisor_uid=?)""", (self.asesor,))
            k.execute("DELETE FROM advisor_op_batches WHERE advisor_uid=?", (self.asesor,))
            k.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.asesor,))
            k.commit()
            k.close()
        self.addCleanup(_limpiar)

    def test_anota_el_autodeposito_y_el_deshacer_lo_anula(self):
        self.reloj.t = "2026-03-06 12:00:00"
        r = self.http.post("/api/advisor/group-op", headers=self.hdr, json={
            "asset": "GD30", "currency": "USD", "entry_date": "2026-03-06",
            "rows": [{"client_uid": self.cliente, "broker": "Cocos",
                      "quantity": 10, "buy_price": 100}]})
        self.assertEqual(r.status_code, 200, r.text)
        fl = [dict(x) for x in self.conn.execute(
            "SELECT * FROM flujos_a_mano WHERE user_id=?", (self.cliente,)).fetchall()]
        self.assertEqual(len(fl), 1)
        self.assertEqual((fl[0]["origen"], fl[0]["cargado_at"]),
                         ("autodeposito", "2026-03-06 12:00:00"))
        self.reloj.t = "2026-03-07 12:00:00"
        r = self.http.post(f"/api/advisor/group-op/{r.json()['batch_id']}/undo", headers=self.hdr)
        self.assertEqual(r.status_code, 200, r.text)
        f = self.conn.execute("SELECT * FROM flujos_a_mano WHERE id=?", (fl[0]["id"],)).fetchone()
        self.assertEqual(f["anulado_motivo"], "operacion_grupal_deshecha")
        row = self.conn.execute(
            "SELECT manual_deposits FROM monthly_entries WHERE user_id=? AND broker='Cocos' "
            "AND year=2026 AND month=3", (self.cliente,)).fetchone()
        self.assertAlmostEqual(float(row["manual_deposits"] or 0), 0.0)

    def test_deshacer_cuando_el_autodeposito_ya_se_fue_no_se_come_otra_carga(self):
        """El cliente borró el renglón de marzo en /mensual (se llevó el autodepósito
        del lote) y después cargó otro depósito igual. El deshacer del asesor restaba
        el autodepósito otra vez y se comía el depósito nuevo."""
        r = self.http.post("/api/advisor/group-op", headers=self.hdr, json={
            "asset": "GD30", "currency": "USD", "entry_date": "2026-03-06",
            "rows": [{"client_uid": self.cliente, "broker": "Cocos",
                      "quantity": 10, "buy_price": 100}]})
        self.assertEqual(r.status_code, 200, r.text)
        lote = r.json()["batch_id"]
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.cliente
        fila = self.conn.execute("SELECT id FROM monthly_entries WHERE user_id=? AND broker='Cocos' "
                                 "AND year=2026 AND month=3", (self.cliente,)).fetchone()
        self.assertEqual(self.http.delete(f"/api/monthly/{fila['id']}").status_code, 200)
        r = self.http.post("/api/cash/flow", json={"broker_name": "Cocos", "direction": "deposit",
                                                   "amount": 1000.0, "date": "2026-03-10"})
        self.assertEqual(r.status_code, 200, r.text)
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        r = self.http.post(f"/api/advisor/group-op/{lote}/undo", headers=self.hdr)
        self.assertEqual(r.status_code, 200, r.text)
        row = self.conn.execute(
            "SELECT manual_deposits FROM monthly_entries WHERE user_id=? AND broker='Cocos' "
            "AND year=2026 AND month=3", (self.cliente,)).fetchone()
        self.assertAlmostEqual(float(row["manual_deposits"] or 0), 1000.0)
        vivas = self.conn.execute(
            "SELECT COALESCE(SUM(monto_usd),0) FROM flujos_a_mano WHERE user_id=? AND broker='Cocos' "
            "AND anulado_at IS NULL", (self.cliente,)).fetchone()[0]
        self.assertAlmostEqual(float(vivas), 1000.0)


class LaSumaDelMesEsLaDeSusCargas(FlujosAManoBase):
    """Una seguidilla al azar de TODAS las puertas, por HTTP; después de cada paso la
    suma de cada renglón tiene que ser la de sus cargas vigentes."""

    def test_al_azar(self):
        for semilla in range(25):
            with self.subTest(semilla=semilla):
                self._una_seguidilla(random.Random(semilla))

    def _una_seguidilla(self, rnd):
        self.conn.close()
        self.setUp()
        posiciones, tokens = [], []
        for paso in range(35):
            self.reloj.t = f"2026-{rnd.randint(1, 4):02d}-{rnd.randint(1, 28):02d} 1{rnd.randint(0, 9)}:00:00"
            fecha = f"2026-{rnd.randint(1, 4):02d}-{rnd.randint(1, 28):02d}"
            x = rnd.random()
            if x < 0.30:
                self.http.post("/api/cash/flow", json={
                    "broker_name": self.BROKER, "direction": "deposit",
                    "amount": rnd.choice([100.0, 250.5, 1000.0]), "date": fecha})
            elif x < 0.40:
                self.http.post("/api/cash/flow", json={
                    "broker_name": self.BROKER, "direction": "withdraw",
                    "amount": rnd.choice([50.0, 120.0]), "date": fecha})
            elif x < 0.55:
                r = self.http.post("/api/positions", json={
                    "broker": self.VACIO, "asset": rnd.choice(["KO", "PEP"]), "buy_price": 10.0,
                    "quantity": 10.0, "invested": 100.0, "entry_date": fecha})
                if r.status_code == 200:
                    posiciones.append(r.json()["id"])
            elif x < 0.65 and posiciones:
                r = self.http.delete(f"/api/positions/{posiciones.pop(rnd.randrange(len(posiciones)))}")
                if r.status_code == 200 and r.json().get("undo_token"):
                    tokens.append(r.json()["undo_token"])
            elif x < 0.72 and tokens:
                self.http.post(f"/api/operations/undo/{tokens.pop()}")
            elif x < 0.82:
                rows = self.conn.execute(
                    "SELECT * FROM monthly_entries WHERE user_id=? AND broker=?",
                    (self.uid, self.BROKER)).fetchall()
                if rows:
                    row = rnd.choice(rows)
                    body = {k: max(0.0, float(row[k] or 0)) for k in (
                        "deposits", "withdrawals", "capital_inicio", "capital_final")}
                    body.update({"year": row["year"], "month": row["month"],
                                 "broker": self.BROKER, "pnl_realized": float(row["pnl_realized"] or 0),
                                 "pnl_unrealized": 0.0})
                    body["deposits"] = max(0.0, body["deposits"] + rnd.choice([-80.0, 40.0, 300.0]))
                    if rnd.random() < 0.3:
                        body["deposits"] = 0.0            # bajar el mes a cero
                    self.http.put(f"/api/monthly/{row['id']}", json=body)
                    if rnd.random() < 0.3:
                        # lo que corre un import: borra los renglones que quedaron en 0
                        main._recalc_pnl_realized_from_ops(self.conn, self.uid)
                        self.conn.commit()
            elif x < 0.86:
                rows = self.conn.execute(
                    "SELECT id FROM monthly_entries WHERE user_id=? AND broker IN (?, ?)",
                    (self.uid, self.BROKER, self.VACIO)).fetchall()
                if rows:
                    self.http.delete(f"/api/monthly/{rnd.choice(rows)['id']}")
            elif x < 0.93:
                rows = self.conn.execute(
                    "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? "
                    "AND manual_deposits > 0", (self.uid, self.BROKER)).fetchall()
                if rows:
                    self.http.delete(f"/api/movements/me-{rnd.choice(rows)['id']}-dep")
            else:
                self.http.post("/api/brokers/reconcile-cash", json={
                    "broker_name": self.BROKER, "target_cash": float(rnd.choice([0, 500, 2000]))})
            self.assert_suma_es_sus_cargas(f"paso {paso}")


class NadieSumaLoManualPorFuera(unittest.TestCase):
    """El detalle sirve sólo si TODO lo que mueve la suma pasa por las puertas. La
    causa raíz más frecuente de este repo es el arreglo que no se propagó a todos
    los lugares: si alguien agrega otro `_update_monthly_flow` con lo manual, o
    escribe `manual_*` en SQL desde una función nueva, esto sale en rojo y lo obliga
    a decidir qué pasa con el detalle.

    Mira TODO el backend (menos los tests), y no sólo el texto literal: la primera
    versión no veía `is_manual` pasado por posición ni columnas armadas en un
    f-string (auditoría 1, 2026-10-09)."""

    PUERTAS = {"_registrar_flujo_a_mano", "_restar_flujo_a_mano", "_revivir_flujo_a_mano"}
    # Funciones que nombran `manual_*` Y escriben `monthly_entries`, y por qué está bien.
    SQL_PERMITIDO = {
        "_update_monthly_flow": "el que suma (lo llaman sólo las puertas con is_manual)",
        "init_db": "migraciones: crean las columnas manual_* (y la copia de filas viejas "
                   "es anterior a ellas)",
        "_backfill_manual_flows": "migración vieja: corre una vez, al crear la columna",
        "_recalc_pnl_realized_from_ops": "sólo Global = suma de los brokers",
        "_delete_one_movement": "me-: pone el mes en 0 y anula sus cargas",
        "create_monthly": "/mensual: anota la diferencia (_anotar_ajuste_mensual)",
        "update_monthly": "/mensual: anota la diferencia (_anotar_ajuste_mensual)",
        "_repair_caja_1415": "reparación de admin del dólar 1.415 (A-6, anterior al "
                             "detalle): no toca los meses que tienen cargas anotadas",
        "seed_f1": "script de desarrollo",
    }
    MAN = re.compile(r"manual_(deposits|withdrawals)")
    ESCRIBE = re.compile(r"(UPDATE\s+monthly_entries|INSERT\s+(OR\s+\w+\s+)?INTO\s+monthly_entries)",
                         re.I)

    def _archivos(self):
        for d, _, fs in os.walk(BACKEND):
            if os.path.relpath(d, BACKEND).split(os.sep)[0] in ("tests", "node_modules"):
                continue
            for f in fs:
                if f.endswith(".py"):
                    yield os.path.join(d, f)

    def _funciones(self, ruta):
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
        padres = {}
        for n in ast.walk(arbol):
            for h in ast.iter_child_nodes(n):
                padres[h] = n

        def funcion_de(n):
            while n in padres:
                n = padres[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return n.name
            return "<módulo>"
        return arbol, funcion_de

    def test_solo_las_puertas_suman_lo_manual(self):
        fuera = []
        for ruta in self._archivos():
            arbol, funcion_de = self._funciones(ruta)
            for n in ast.walk(arbol):
                if not (isinstance(n, ast.Call) and getattr(
                        n.func, "id", getattr(n.func, "attr", None)) == "_update_monthly_flow"):
                    continue
                kw = [k.value for k in n.keywords if k.arg == "is_manual"]
                # `is_manual` es el 8º argumento: también puede ir por posición.
                valor = kw[0] if kw else (n.args[7] if len(n.args) >= 8 else None)
                es_falso = valor is None or (isinstance(valor, ast.Constant) and not valor.value)
                if not es_falso and funcion_de(n) not in self.PUERTAS:
                    fuera.append(f"{os.path.relpath(ruta, BACKEND)}:{n.lineno} en {funcion_de(n)}")
        self.assertEqual(fuera, [], "suman lo manual sin anotar la carga: pasalo por "
                                    "_registrar_flujo_a_mano / _restar / _revivir")

    def test_solo_una_funcion_inserta_en_el_detalle(self):
        donde = set()
        for ruta in self._archivos():
            arbol, funcion_de = self._funciones(ruta)
            donde |= {funcion_de(n) for n in ast.walk(arbol)
                      if isinstance(n, ast.Constant) and isinstance(n.value, str)
                      and re.search(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+flujos_a_mano", n.value, re.I)}
        self.assertEqual(donde, {"_anotar_flujo_a_mano"})

    def test_quien_escribe_manual_en_sql(self):
        """Toda función que NOMBRA una columna manual_* y además ESCRIBE en
        monthly_entries (aunque arme el nombre de la columna en un f-string)."""
        donde = {}
        for ruta in self._archivos():
            arbol = ast.parse(open(ruta, encoding="utf-8").read())
            for fn in ast.walk(arbol):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                textos = [n.value for n in ast.walk(fn)
                          if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                if any(self.MAN.search(t) for t in textos) and any(self.ESCRIBE.search(t) for t in textos):
                    donde[fn.name] = os.path.relpath(ruta, BACKEND)
        nuevos = {f: r for f, r in donde.items() if f not in self.SQL_PERMITIDO}
        self.assertEqual(nuevos, {},
                         "escriben manual_* por fuera: decidí qué pasa con flujos_a_mano y "
                         "agregalo a SQL_PERMITIDO con el motivo")

    def test_el_guardian_ve_lo_que_dice_ver(self):
        """Control del instrumento: las dos formas que la primera versión no veía."""
        codigo = (
            "def a(conn):\n"
            "    _update_monthly_flow(conn, 1, 'X', 2026, 3, 'deposit', 1.0, True)\n"
            "def b(conn, col):\n"
            "    col = 'manual_deposits'\n"
            "    conn.execute(f'UPDATE monthly_entries SET {col}=0')\n")
        arbol = ast.parse(codigo)
        llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", None) == "_update_monthly_flow"]
        self.assertTrue(len(llamadas[0].args) >= 8 and llamadas[0].args[7].value is True)
        fb = [f for f in arbol.body if f.name == "b"][0]
        textos = [n.value for n in ast.walk(fb) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertTrue(any(self.MAN.search(t) for t in textos)
                        and any(self.ESCRIBE.search(t) for t in textos))


if __name__ == "__main__":
    unittest.main()
