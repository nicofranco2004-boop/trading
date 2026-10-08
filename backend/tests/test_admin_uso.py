"""El panel "Uso de Rendi" de /admin: quién usó la app, qué tocó y cuánto tiene.

El caso que lo disparó (2026-10-08): Nico abrió Rendi y el panel no lo contó.
Dos motivos, y los dos se prueban acá:

1. Ya tenía la sesión abierta. La sesión dura 7 días, así que abrir la app con
   la sesión viva NO es un inicio de sesión y `login_history` no se entera.
   Para eso existe `uso_diario`: el navegador manda lo que se tocó y cualquier
   fila de un día = usó la app ese día.
2. Es admin. Por defecto el panel cuenta sólo usuarios reales; con
   `internos=true` cuenta también admins y cuentas internas.

Todo por HTTP: el usuario se registra y confirma el mail como en producción, y
el navegador manda el uso a POST /api/uso/eventos con su propia sesión. Lo
único que se escribe a mano es el RELOJ (la hora de un ingreso viejo).

Corre con: cd backend && python3 -m pytest tests/test_admin_uso.py
"""
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from fechas import hoy_art_date, inicio_dia_art_en_utc


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


PASS = "Password123$"


class Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        self.admin = self._insert(f"adm-{self.tag}@rendi.test", admin=True)
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()

    def tearDown(self):
        self._mails.stop()

    def _insert(self, email, admin=False):
        conn = main.get_db()
        try:
            uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
                "VALUES (?, 'x', 1, ?, 1)", (email, 1 if admin else 0)).lastrowid
            conn.commit()
            return uid
        finally:
            conn.close()

    def _q(self, sql, params=()):
        conn = main.get_db()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def _x(self, sql, params=()):
        conn = main.get_db()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _registrar_y_confirmar(self, quien):
        email = f"{quien}-{self.tag}@ejemplo.com"
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": PASS, "name": quien})
        self.assertEqual(r.status_code, 200, r.text)
        code = self._q(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY created_at DESC LIMIT 1""", (email,))[0]["code"]
        r = self.client.post("/api/auth/verify-email", json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()
        return self._q("SELECT id FROM users WHERE email=?", (email,))[0]["id"]

    def _mandar_uso(self, uid, eventos):
        """Lo que hace el navegador: POST con la sesión de ESA persona."""
        r = self.client.post("/api/uso/eventos", json={"eventos": eventos},
                             headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 204, r.text)

    def _uso(self, **params):
        p = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in params.items()}
        r = self.client.get("/api/admin/uso", params=p, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _fila(self, data, uid):
        f = [u for u in data["usuarios"] if u["id"] == uid]
        return f[0] if f else None

    def _ingresos_hace(self, uid, dias):
        """El reloj: todos los ingresos de `uid` pasan a hace `dias` días (15:00 ART)."""
        d = hoy_art_date() - timedelta(days=dias)
        self._x("UPDATE login_history SET created_at=? WHERE user_id=?",
                (inicio_dia_art_en_utc(d).replace("03:00:00", "18:00:00"), uid))


class SesionYaAbierta(Base):

    def test_abrir_la_app_con_la_sesion_viva_cuenta_como_uso_no_como_ingreso(self):
        """EL caso de Nico: entró hace 3 días, hoy abre la app sin loguearse."""
        uid = self._registrar_y_confirmar("sesionviva")
        self._ingresos_hace(uid, 3)
        hoy = hoy_art_date()
        antes = self._uso(desde=hoy, hasta=hoy)["resumen"]
        self._mandar_uso(uid, {"app_abierta": 1, "pantalla:/posiciones": 1})
        despues = self._uso(desde=hoy, hasta=hoy)
        self.assertEqual(despues["resumen"]["usuarios"], antes["usuarios"], "no inició sesión hoy")
        self.assertEqual(despues["resumen"]["usaron_app"], (antes["usaron_app"] or 0) + 1)
        fila = self._fila(despues, uid)
        self.assertIsNotNone(fila, "tiene que aparecer en la lista aunque no haya iniciado sesión")
        self.assertEqual(fila["ingresos"], 0)
        self.assertEqual(fila["dias_con_uso"], 1)
        self.assertEqual(fila["ultimo"], hoy.isoformat())

    def test_el_admin_no_cuenta_salvo_que_se_pida(self):
        hoy = hoy_art_date()
        self._mandar_uso(self.admin, {"app_abierta": 1})
        self.assertIsNone(self._fila(self._uso(desde=hoy, hasta=hoy), self.admin))
        con = self._uso(desde=hoy, hasta=hoy, internos="true")
        self.assertIsNotNone(self._fila(con, self.admin))
        self.assertTrue(con["internos"])

    def test_sin_sesion_no_se_registra_nada(self):
        r = self.client.post("/api/uso/eventos", json={"eventos": {"app_abierta": 1}})
        self.assertEqual(r.status_code, 401)


class LoQueManda(Base):

    def test_se_suma_por_dia_y_se_frena_la_basura(self):
        uid = self._registrar_y_confirmar("suma")
        self._mandar_uso(uid, {"position_add_started": 2, "pantalla:/ai": 1})
        self._mandar_uso(uid, {"position_add_started": 3,
                               "Esto No Es Un Evento": 5,          # forma inválida → afuera
                               "pantalla:https://otro.com": 1,     # no es una ruta → afuera
                               "operation_added": -4,              # negativo → afuera
                               "watchlist_added": 99999})          # se recorta al tope
        filas = {r["evento"]: r["cantidad"] for r in self._q(
            "SELECT evento, cantidad FROM uso_diario WHERE user_id=?", (uid,))}
        self.assertEqual(filas, {"position_add_started": 5, "pantalla:/ai": 1,
                                 "watchlist_added": main._USO_MAX_CANTIDAD})
        self.assertEqual(set(self._q("SELECT DISTINCT dia FROM uso_diario WHERE user_id=?", (uid,))[0]),
                         {hoy_art_date().isoformat()})

    def test_demasiados_nombres_en_un_envio_se_rechaza(self):
        uid = self._registrar_y_confirmar("muchos")
        eventos = {f"evento_{i}": 1 for i in range(main._USO_MAX_EVENTOS + 1)}
        r = self.client.post("/api/uso/eventos", json={"eventos": eventos},
                             headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 400)


class ElPanel(Base):

    def test_ranking_separa_botones_de_pantallas_y_compara_con_antes(self):
        a = self._registrar_y_confirmar("rank-a")
        b = self._registrar_y_confirmar("rank-b")
        hoy = hoy_art_date()
        ev = f"boton_{self.tag}"
        self._mandar_uso(a, {ev: 4, "pantalla:/alertas": 2, "app_abierta": 1})
        self._mandar_uso(b, {ev: 1})
        # La semana anterior sólo lo tocó `a`. Y la medición ya existía antes de
        # esa semana (si no, la comparación no se hace: ver el test de abajo).
        antes = (hoy - timedelta(days=7)).isoformat()
        self._x("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,?,?)", (a, antes, ev, 9))
        self._x("INSERT OR IGNORE INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,'app_abierta',1)",
                (a, (hoy - timedelta(days=30)).isoformat()))
        data = self._uso(desde=hoy - timedelta(days=6), hasta=hoy)
        botones = {x["evento"]: x for x in data["ranking"]["botones"]}
        pantallas = {x["evento"] for x in data["ranking"]["pantallas"]}
        self.assertEqual(botones[ev]["personas"], 2)
        self.assertEqual(botones[ev]["cantidad"], 5)
        self.assertEqual(botones[ev]["personas_antes"], 1)
        self.assertIn("pantalla:/alertas", pantallas)
        self.assertNotIn("app_abierta", botones, "abrir la app no es un botón")
        self.assertNotIn("pantalla:/alertas", botones)
        self.assertEqual(self._fila(data, a)["toques"], 4, "toques = botones, sin pantallas ni abrir la app")

    def test_sin_periodo_anterior_medido_no_se_compara(self):
        """El día en que arrancó la medición no tiene "antes": comparar diría
        que todo es nuevo y que el uso creció."""
        from datetime import date
        uid = self._registrar_y_confirmar("sinantes")
        self._mandar_uso(uid, {"moneda_cambiada": 1})
        # Un día ANTERIOR a todo lo medido pasa a ser el primero de la medición.
        primero = (date.fromisoformat(self._uso()["uso_desde"]) - timedelta(days=1)).isoformat()
        self._x("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,'moneda_cambiada',1)",
                (uid, primero))
        self.assertEqual(self._uso()["uso_desde"], primero)
        data = self._uso(desde=primero, hasta=primero)
        self.assertTrue(data["ranking"]["botones"])
        for f in data["ranking"]["botones"]:
            self.assertIsNone(f["personas_antes"], f["evento"])

    def test_la_fila_es_la_misma_que_la_de_la_tabla_usuarios(self):
        uid = self._registrar_y_confirmar("misma")
        self._x("INSERT INTO brokers (user_id, name) VALUES (?, 'IOL')", (uid,))
        data = self._uso()
        fila = self._fila(data, uid)
        r = self.client.get("/api/admin/users/search", params={"q": str(uid)}, headers=self.h)
        tabla = [u for u in r.json() if u["id"] == uid][0]
        for k in ("plan", "estado", "requires_plan", "days_remaining"):
            self.assertEqual(fila[k], tabla[k], k)
        self.assertEqual(fila["brokers"], tabla["brokers_count"])
        self.assertEqual(fila["posiciones"], tabla["positions_count"])
        self.assertEqual(fila["operaciones"], tabla["operations_count"])
        self.assertTrue(fila["primera_vez"])

    def test_cartera_reparte_a_todos_los_que_tienen_cuenta(self):
        self._registrar_y_confirmar("cartera")
        data = self._uso()
        c = data["cartera"]
        total = sum(t["activos"] + t["inactivos"] for t in c["tramos"])
        self.assertEqual(total, data["resumen"]["base"])
        self.assertEqual(c["activos"]["cuantos"] + c["inactivos"]["cuantos"], data["resumen"]["base"])

    def test_el_dia_por_dia_cuadra_con_el_total(self):
        uid = self._registrar_y_confirmar("dia")
        hoy = hoy_art_date()
        self._ingresos_hace(uid, 2)
        data = self._uso(desde=hoy - timedelta(days=4), hasta=hoy)
        self.assertEqual(len(data["por_dia"]), 5)
        dia = [d for d in data["por_dia"] if d["dia"] == (hoy - timedelta(days=2)).isoformat()][0]
        self.assertGreaterEqual(dia["ingresaron"], 1)
        self.assertGreaterEqual(dia["primera_vez"], 1)

    def test_periodo_anterior_a_la_medicion_dice_que_no_hay_dato(self):
        """Antes del día en que empezó la medición, "usaron la app" no es 0: es
        que no se sabe. El panel lo tiene que poder distinguir."""
        uid = self._registrar_y_confirmar("medicion")
        self._mandar_uso(uid, {"app_abierta": 1})
        viejo = hoy_art_date() - timedelta(days=200)
        data = self._uso(desde=viejo, hasta=viejo)
        primero = data["uso_desde"]
        if primero and primero > viejo.isoformat():
            self.assertIsNone(data["resumen"]["usaron_app"])

    def test_solo_admin(self):
        uid = self._registrar_y_confirmar("intruso")
        r = self.client.get("/api/admin/uso",
                            headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 403)


class Poda(Base):

    def test_el_arranque_borra_lo_de_mas_de_13_meses(self):
        uid = self._insert(f"poda-{self.tag}@ejemplo.com")
        hoy = hoy_art_date()
        viejo = (hoy - timedelta(days=main._USO_DIAS_GUARDADOS + 1)).isoformat()
        justo = (hoy - timedelta(days=main._USO_DIAS_GUARDADOS - 1)).isoformat()
        for d in (viejo, justo):
            self._x("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,'app_abierta',1)", (uid, d))
        main.init_db()
        dias = {r["dia"] for r in self._q("SELECT dia FROM uso_diario WHERE user_id=?", (uid,))}
        self.assertEqual(dias, {justo})


if __name__ == "__main__":
    unittest.main()
