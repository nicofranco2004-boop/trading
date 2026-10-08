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

    def test_la_ia_es_lo_que_la_persona_pidio_no_el_cupo(self):
        """El cupo de IA sube solo al abrir un ticker en Fundamentals (el
        resumen se pide sin que nadie lo toque). Eso no es "usó la IA"."""
        hoy = hoy_art_date()
        solo_cupo = self._registrar_y_confirmar("cupo")
        pidio = self._registrar_y_confirmar("pidio")
        self._x("INSERT INTO ai_usage_daily (user_id, date, analyses_count) VALUES (?,?,3)", (solo_cupo, hoy.isoformat()))
        self._mandar_uso(solo_cupo, {"app_abierta": 1, "vista:fundamentals_ai_summary_loaded": 1})
        self._mandar_uso(pidio, {"ai_chat_sent": 2, "ai_analyze_opened": 1})
        data = self._uso(desde=hoy, hasta=hoy)
        self.assertEqual(self._fila(data, solo_cupo)["ia"], 0)
        self.assertEqual(self._fila(data, pidio)["ia"], 3)
        self.assertEqual(self._fila(data, solo_cupo)["toques"], 0, "lo que se mostró solo no es un toque")
        avisos = {x["evento"] for x in data["ranking"]["avisos"]}
        self.assertIn("vista:fundamentals_ai_summary_loaded", avisos)
        self.assertNotIn("vista:fundamentals_ai_summary_loaded", {x["evento"] for x in data["ranking"]["botones"]})

    def test_volvio_con_la_sesion_abierta_cuenta_como_volvio(self):
        """Quien vuelve dentro de los 7 días de sesión no inicia sesión, pero volvió."""
        hoy = hoy_art_date()
        uid = self._registrar_y_confirmar("volvio")
        self._ingresos_hace(uid, 3)
        self._x("UPDATE users SET created_at=? WHERE id=?",
                (inicio_dia_art_en_utc(hoy - timedelta(days=20)), uid))
        antes = self._uso(desde=hoy, hasta=hoy)["resumen"]
        self._mandar_uso(uid, {"app_abierta": 1})
        r = self._uso(desde=hoy, hasta=hoy)["resumen"]
        self.assertEqual(r["volvieron"], antes["volvieron"] + 1)
        self.assertEqual(r["primera_vez"], antes["primera_vez"])

    def test_importacion_deshecha_igual_cuenta_esa_semana(self):
        hoy = hoy_art_date()
        uid = self._registrar_y_confirmar("importo")
        antes = self._uso(desde=hoy, hasta=hoy)["resumen"]["importaron"]
        ahora = inicio_dia_art_en_utc(hoy).replace("03:00:00", "15:00:00")
        self._x("INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status, confirmed_at, reverted_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (f"b-{self.tag}", uid, "IOL", "x", "h", "reverted", ahora, ahora))
        self._x("INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status) "
                "VALUES (?,?,?,?,?,?)", (f"p-{self.tag}", uid, "IOL", "x", "h2", "reverted"))
        self.assertEqual(self._uso(desde=hoy, hasta=hoy)["resumen"]["importaron"], antes + 1)

    def test_posiciones_sin_efectivo_ni_lotes_repetidos(self):
        uid = self._registrar_y_confirmar("lotes")
        for asset, is_cash, qty, broker in [("USD", 1, 100, "IOL"), ("GGAL", 0, 10, "IOL"), ("GGAL", 0, 5, "IOL"),
                                            ("GGAL", 0, 3, "Balanz"), ("AL30", 0, 0, "IOL")]:
            self._x("INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity) VALUES (?,?,?,?,1,?)",
                    (uid, broker, asset, is_cash, qty))
        fila = self._fila(self._uso(), uid)
        # GGAL en IOL (2 lotes) + GGAL en Balanz. Sin la caja ni el AL30 en cero.
        self.assertEqual(fila["posiciones"], 2)

    def test_la_fila_es_la_misma_que_la_de_la_tabla_usuarios(self):
        uid = self._registrar_y_confirmar("misma")
        self._x("INSERT INTO brokers (user_id, name) VALUES (?, 'IOL')", (uid,))
        self._x("INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity) VALUES (?,?,?,1,1,0)",
                (uid, "IOL", "ARS"))
        self._x("INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity) VALUES (?,?,?,0,1,4)",
                (uid, "IOL", "YPF"))
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
        # La cuenta se creó ese mismo día (primera vez = día de alta).
        self._x("UPDATE users SET created_at=? WHERE id=?",
                (inicio_dia_art_en_utc(hoy - timedelta(days=2)).replace("03:00:00", "17:00:00"), uid))
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

    def test_periodo_demasiado_largo(self):
        hoy = hoy_art_date()
        r = self.client.get("/api/admin/uso", headers=self.h, params={
            "desde": (hoy - timedelta(days=main._USO_DIAS_GUARDADOS)).isoformat(), "hasta": hoy.isoformat()})
        self.assertEqual(r.status_code, 400)
        r = self.client.get("/api/admin/uso", headers=self.h, params={
            "desde": (hoy - timedelta(days=main._USO_DIAS_GUARDADOS - 1)).isoformat(), "hasta": hoy.isoformat()})
        self.assertEqual(r.status_code, 200, r.text)

    def test_solo_admin(self):
        uid = self._registrar_y_confirmar("intruso")
        r = self.client.get("/api/admin/uso",
                            headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 403)


class Topes(Base):
    """Nadie puede inflar su uso ni llenar la tabla mandando nombres inventados."""

    def test_un_evento_no_pasa_el_tope_del_dia(self):
        uid = self._registrar_y_confirmar("inflar")
        for _ in range(main._USO_TOPE_DIA // main._USO_MAX_CANTIDAD + 3):
            self._mandar_uso(uid, {"moneda_cambiada": main._USO_MAX_CANTIDAD})
        n = self._q("SELECT cantidad FROM uso_diario WHERE user_id=? AND evento='moneda_cambiada'", (uid,))[0][0]
        self.assertEqual(n, main._USO_TOPE_DIA)

    def test_nombres_inventados_tienen_tope_por_dia(self):
        uid = self._registrar_y_confirmar("basura")
        self._mandar_uso(uid, {"moneda_cambiada": 1})
        tope = main._USO_TOPE_NOMBRES_DIA
        for tanda in range(0, tope + 100, main._USO_MAX_EVENTOS):
            self._mandar_uso(uid, {f"inventado_{i}": 1 for i in range(tanda, min(tanda + main._USO_MAX_EVENTOS, tope + 100))})
        nombres = self._q("SELECT COUNT(*) FROM uso_diario WHERE user_id=?", (uid,))[0][0]
        self.assertEqual(nombres, tope)
        # Lo que ya tenía se sigue sumando aunque esté en el tope.
        self._mandar_uso(uid, {"moneda_cambiada": 2})
        n = self._q("SELECT cantidad FROM uso_diario WHERE user_id=? AND evento='moneda_cambiada'", (uid,))[0][0]
        self.assertEqual(n, 3)


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

    def test_tambien_poda_el_primer_envio_del_dia(self):
        """En Postgres el arranque no corre las migraciones: la poda tiene que
        pasar también por el camino que sí corre ahí, el envío de uso."""
        uid = self._insert(f"poda2-{self.tag}@ejemplo.com")
        viejo = (hoy_art_date() - timedelta(days=main._USO_DIAS_GUARDADOS + 5)).isoformat()
        self._x("INSERT INTO uso_diario (user_id, dia, evento, cantidad) VALUES (?,?,'app_abierta',1)", (uid, viejo))
        main._USO_PODADO_EL = None
        self._mandar_uso(uid, {"app_abierta": 1})
        self.assertEqual({r["dia"] for r in self._q("SELECT dia FROM uso_diario WHERE user_id=?", (uid,))},
                         {hoy_art_date().isoformat()})


if __name__ == "__main__":
    unittest.main()
