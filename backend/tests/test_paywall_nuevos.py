"""El que se registra de ahora en adelante NACE SIN PLAN GRATIS.

La prueba de 20 días es su puerta de entrada, y cuando se termina la cuenta
queda EN PAUSA hasta que elija un plan. A los que ya existían no les cambia
nada — esa mitad se prueba acá también, porque es la que puede romperse sin
que nadie se dé cuenta.

Lo que estos tests protegen, en orden de importancia:

  1. **Que el muro corte de verdad.** No se prueba llamando al helper que
     decide: se prueba pegándole a un endpoint de datos con el cliente HTTP,
     que es el camino que recorre el navegador. Un muro que el helper reporta
     bien pero el endpoint no aplica es exactamente el bug que el usuario ve.
  2. **Que el muro se pueda cruzar pagando.** `/api/auth/me` y los endpoints
     de billing pasan por la MISMA función que pone el muro, así que sin una
     excepción explícita la cuenta en pausa se queda sin forma de enterarse
     ni de pagar: una puerta cerrada con la llave adentro.
  3. Que la prueba arranque sola al verificar el mail, una sola vez.
  4. Que ningún freno de promoción (el tope mensual, el interruptor de
     campaña) pueda dejar a esta cohorte sin prueba Y sin plan gratis.
  5. Que a los usuarios de antes no les aparezca ningún muro.

Los días NO se escriben acá: se derivan de `billing/trial.py`.

Corre con: cd backend && python3 -m pytest tests/test_paywall_nuevos.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Base propia del módulo (ver reference_tests_una_base_por_modulo): compartirla
# con otro archivo de tests hace que el orden de ejecución decida el resultado.
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main                                      # noqa: E402
from ai import quota                              # noqa: E402
from billing import trial as tr                   # noqa: E402


def _iso(dt):
    return dt.isoformat()


class Base(unittest.TestCase):
    """Un usuario de la cohorte nueva, con la prueba arrancada."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed",
                  "trial_email_log", "ai_usage_daily", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        os.environ.pop("TRIALS_ENABLED", None)
        os.environ.pop("TRIALS_MONTHLY_CAP", None)
        os.environ.pop("PAYWALL_NUEVOS", None)
        # Nadie manda mails de verdad: el envío sale a la red, tarda ~90s y deja
        # la base trabada para los tests que siguen.
        from billing import emails as _em
        self.enviados = []
        self._orig = {}
        for _fn in ("send_trial_started", "send_trial_pro_ending",
                    "send_trial_ending_soon", "send_trial_ended",
                    "send_welcome_free", "send_verification_code",
                    "send_new_signup_admin"):
            if hasattr(_em, _fn):
                self._orig[_fn] = getattr(_em, _fn)
                setattr(_em, _fn, self._spy(_fn))

    def tearDown(self):
        from billing import emails as _em
        for _fn, _o in getattr(self, "_orig", {}).items():
            setattr(_em, _fn, _o)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    def _spy(self, nombre):
        def _fake(**kw):
            self.enviados.append((nombre, kw))
            return True
        return _fake

    # ── helpers ─────────────────────────────────────────────────────────────

    def _usuario(self, *, requires_plan=1, con_prueba=True):
        """Un usuario ya verificado. `con_prueba` le arranca la prueba igual
        que lo hace verify-email."""
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   requires_plan) VALUES (?,?,1,1,?)",
            (f"u-{uuid.uuid4().hex[:8]}@rendi.test", "x", requires_plan))
        uid = cur.lastrowid
        self.conn.commit()
        if con_prueba:
            self.assertTrue(tr.start(self.conn, uid).get("ok"))
        return uid

    def _headers(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _viajar(self, uid, dias):
        """Mueve el arranque de la prueba hacia atrás. Los TRES campos viajan
        juntos o `step_down_due_trials` deja de matchear y el repro miente."""
        row = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (uid,)).fetchone()
        d = timedelta(days=dias)
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=? WHERE id=?",
            (_iso(datetime.fromisoformat(row["trial_started_at"]) - d),
             _iso(datetime.fromisoformat(row["credit_active_until"]) - d),
             _iso(datetime.fromisoformat(row["trial_ends_at"]) - d), uid))
        self.conn.commit()

    def _en_pausa(self, uid):
        return main.cuenta_en_pausa(self.conn, uid)


# ═══════════════════════════════════════════════════════════════════════════
# 1. El muro, por el camino real (el cliente HTTP, no el helper)
# ═══════════════════════════════════════════════════════════════════════════

class ElMuroCorta(Base):
    # Un endpoint de DATOS cualquiera: lo que se prueba es el paso obligado
    # (`get_effective_user`), no este endpoint en particular.
    RUTA_DE_DATOS = "/api/positions"

    def test_durante_la_prueba_entra_normal(self):
        uid = self._usuario()
        r = self.client.get(self.RUTA_DE_DATOS, headers=self._headers(uid))
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)

    def test_cuando_se_termina_la_prueba_el_endpoint_de_datos_corta(self):
        """El test que de verdad importa: 402 por el camino del navegador."""
        uid = self._usuario()
        self._viajar(uid, tr.TRIAL_TOTAL_DAYS + 1)
        r = self.client.get(self.RUTA_DE_DATOS, headers=self._headers(uid))
        self.assertEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)
        self.assertEqual(r.json()["detail"]["code"], "plan_requerido")

    def test_no_hace_falta_que_corra_ningun_cron(self):
        """El muro lo decide `quota.get_tier` en tiempo real. Si dependiera del
        cron diario, entre el vencimiento y la corrida habría una ventana en la
        que la cuenta sigue abierta — y si el cron falla, no se cierra nunca."""
        uid = self._usuario()
        self._viajar(uid, tr.TRIAL_TOTAL_DAYS + 1)
        # A propósito NO se llama a step_down_due_trials ni a ningún job.
        self.assertTrue(self._en_pausa(uid))

    def test_el_dia_de_gracia_no_existe_pero_el_ultimo_dia_si(self):
        """El último día de la prueba todavía entra; el siguiente ya no."""
        uid = self._usuario()
        self._viajar(uid, tr.TRIAL_TOTAL_DAYS - 1)
        self.assertFalse(self._en_pausa(uid), "le cortamos un día antes")
        self._viajar(uid, 2)
        self.assertTrue(self._en_pausa(uid))


# ═══════════════════════════════════════════════════════════════════════════
# 2. Y se puede cruzar: la llave no queda adentro
# ═══════════════════════════════════════════════════════════════════════════

class ElMuroSePuedeCruzar(Base):
    def setUp(self):
        super().setUp()
        self.uid = self._usuario()
        self._viajar(self.uid, tr.TRIAL_TOTAL_DAYS + 1)
        self.assertTrue(self._en_pausa(self.uid), "el fixture no dejó la cuenta en pausa")

    def test_auth_me_sigue_contestando_y_lo_dice(self):
        """`/api/auth/me` pasa por la MISMA función que pone el muro. Si lo
        bloqueara, el frontend no tendría cómo saber que hay que mostrar el
        muro: vería un error y no una pantalla."""
        r = self.client.get("/api/auth/me", headers=self._headers(self.uid))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["cuenta_en_pausa"])
        self.assertTrue(d["requires_plan"])

    def test_el_endpoint_de_pago_no_esta_bloqueado(self):
        """Sin esto el muro es inescapable: la única salida es pagar y el
        endpoint que cobra pasa por el mismo paso obligado. No se prueba que
        el pago FUNCIONE (eso pide Rebill), sino que no lo corte el muro."""
        r = self.client.post("/api/billing/subscribe",
                             json={"plan": "pro", "period": "monthly"},
                             headers=self._headers(self.uid))
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)

    def test_el_estado_de_billing_tampoco(self):
        r = self.client.get("/api/billing/status", headers=self._headers(self.uid))
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)

    def test_pagar_levanta_el_muro_en_el_acto(self):
        """Sin esperar ningún cron: el crédito del pago hace que get_tier
        devuelva un plan pago, y el muro deja de aplicar."""
        from billing import credits
        credits.grant_payment_credit(
            self.conn, user_id=self.uid, plan="pro", period="monthly",
            amount_usd=None, subscription_id="s1", payment_id="p1")
        self.assertFalse(self._en_pausa(self.uid))
        r = self.client.get(ElMuroCorta.RUTA_DE_DATOS, headers=self._headers(self.uid))
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)


# ═══════════════════════════════════════════════════════════════════════════
# 3. A los de antes no les pasa nada
# ═══════════════════════════════════════════════════════════════════════════

class LosDeAntesSiguenIgual(Base):
    def test_sin_la_marca_no_hay_muro_aunque_no_tenga_plan(self):
        uid = self._usuario(requires_plan=0, con_prueba=False)
        self.assertEqual(quota.get_tier(self.conn, uid), "free")
        self.assertFalse(self._en_pausa(uid))
        r = self.client.get(ElMuroCorta.RUTA_DE_DATOS, headers=self._headers(uid))
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)

    def test_al_de_antes_que_hizo_la_prueba_le_sigue_quedando_el_plan_gratis(self):
        uid = self._usuario(requires_plan=0)
        self._viajar(uid, tr.TRIAL_TOTAL_DAYS + 1)
        self.assertEqual(quota.get_tier(self.conn, uid), "free")
        self.assertFalse(self._en_pausa(uid), "le pusimos un muro a alguien de antes")

    def test_el_admin_nunca_queda_en_pausa(self):
        uid = self._usuario(requires_plan=1, con_prueba=False)
        self.conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
        self.conn.commit()
        self.assertFalse(self._en_pausa(uid))

    def test_la_cuenta_que_maneja_un_asesor_no_queda_en_pausa(self):
        """El plan lo paga el asesor; el cliente no tiene nada que elegir."""
        otro = self._usuario(requires_plan=0, con_prueba=False)
        uid = self._usuario(requires_plan=1, con_prueba=False)
        self.conn.execute("UPDATE users SET managed_by=? WHERE id=?", (otro, uid))
        self.conn.commit()
        self.assertFalse(self._en_pausa(uid))


# ═══════════════════════════════════════════════════════════════════════════
# 4. Ningún freno de promoción puede dejarlo sin prueba Y sin plan gratis
# ═══════════════════════════════════════════════════════════════════════════

class LosFrenosDePromocionNoAplican(Base):
    def test_el_tope_del_mes_no_lo_deja_afuera(self):
        """El tope se chequea DOS veces: en eligibility() y otra vez adentro de
        `_start_tx`, que es el que cuenta. Eximir uno solo dejaba el alta
        muriendo adentro con _TopeDelMes — verde en eligibility, sin prueba en
        la realidad. Por eso el test pide el alta completa, no la elegibilidad."""
        os.environ["TRIALS_MONTHLY_CAP"] = "1"
        try:
            gastado = self._usuario(requires_plan=0)          # consume el tope
            self.assertIsNotNone(gastado)
            uid = self._usuario(requires_plan=1, con_prueba=False)
            res = tr.start(self.conn, uid)
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(quota.get_tier(self.conn, uid), "pro")
            self.assertFalse(self._en_pausa(uid))
        finally:
            os.environ.pop("TRIALS_MONTHLY_CAP", None)

    def test_el_interruptor_de_campana_tampoco(self):
        os.environ["TRIALS_ENABLED"] = "0"
        try:
            uid = self._usuario(requires_plan=1, con_prueba=False)
            self.assertTrue(tr.start(self.conn, uid).get("ok"))
            self.assertEqual(quota.get_tier(self.conn, uid), "pro")
        finally:
            os.environ.pop("TRIALS_ENABLED", None)

    def test_al_de_antes_el_tope_le_sigue_aplicando(self):
        """La contracara: el freno no se rompió para todos, sólo no aplica a
        quien no tiene plan gratis al que caer."""
        os.environ["TRIALS_MONTHLY_CAP"] = "1"
        try:
            self._usuario(requires_plan=0)                    # consume el tope
            uid = self._usuario(requires_plan=0, con_prueba=False)
            res = tr.start(self.conn, uid)
            self.assertFalse(res.get("ok"))
            self.assertEqual(res.get("reason"), "monthly_cap_reached")
        finally:
            os.environ.pop("TRIALS_MONTHLY_CAP", None)


# ═══════════════════════════════════════════════════════════════════════════
# 5. El alta: la marca y el arranque automático
# ═══════════════════════════════════════════════════════════════════════════

class LaCasillaQueYaUsoLaPrueba(Base):
    """🔴 Encontrado auditando PRODUCCIÓN, no los tests.

    `trial_consumed` marca la casilla de mail para siempre —sobrevive al
    borrado de la cuenta— y `normalizar_email` trata al +alias y a los puntos
    de Gmail como la MISMA bandeja. Efecto: alguien que ya hizo la prueba se
    registra de nuevo, la prueba no le arranca, y como nació sin plan gratis
    queda en pausa EL DÍA 1 — viendo "terminaron tus 20 días" sin haber tenido
    ninguno en esa cuenta.

    Que quede en pausa es la regla de negocio (una prueba por persona). Lo que
    no se puede es mentirle: el muro tiene que decir otra cosa, y para eso
    /api/auth/me manda `pausa_motivo`.
    """

    def _con_la_casilla_quemada(self):
        vieja = self._usuario(requires_plan=0)       # usa su prueba y la quema
        self.assertIsNotNone(vieja)
        email = self.conn.execute(
            "SELECT email FROM users WHERE id=?", (vieja,)).fetchone()["email"]
        usuario, dominio = email.split("@")
        # Un +alias de la MISMA bandeja: para Rendi es el mismo mail.
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   requires_plan) VALUES (?,?,1,1,1)",
            (f"{usuario}+otra@{dominio}", "x"))
        self.conn.commit()
        return cur.lastrowid

    def test_la_prueba_no_le_arranca(self):
        uid = self._con_la_casilla_quemada()
        res = tr.start(self.conn, uid)
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("reason"), "already_used")

    def test_queda_en_pausa_el_dia_uno(self):
        """La regla de negocio: una prueba por persona, y sin plan gratis al
        que caer. Lo que se vigila acá es que el estado sea EXPLÍCITO."""
        uid = self._con_la_casilla_quemada()
        tr.start(self.conn, uid)
        self.assertTrue(self._en_pausa(uid))

    def test_el_muro_NO_le_dice_que_terminaron_sus_20_dias(self):
        """El motivo tiene que distinguir los dos casos. Sin esto, a alguien que
        se acaba de registrar le aparece "Terminaron tus 20 días de prueba"."""
        uid = self._con_la_casilla_quemada()
        tr.start(self.conn, uid)
        me = self.client.get("/api/auth/me", headers=self._headers(uid)).json()
        self.assertTrue(me["cuenta_en_pausa"])
        self.assertEqual(me["pausa_motivo"], "prueba_usada")

    def test_al_que_SI_hizo_sus_dias_el_motivo_es_el_otro(self):
        """La contracara: el caso normal no se contamina."""
        uid = self._usuario()                        # prueba arrancada de verdad
        self._viajar(uid, tr.TRIAL_TOTAL_DAYS + 1)
        me = self.client.get("/api/auth/me", headers=self._headers(uid)).json()
        self.assertTrue(me["cuenta_en_pausa"])
        self.assertEqual(me["pausa_motivo"], "prueba_terminada")

    def test_sin_pausa_no_hay_motivo(self):
        uid = self._usuario()
        me = self.client.get("/api/auth/me", headers=self._headers(uid)).json()
        self.assertFalse(me["cuenta_en_pausa"])
        self.assertIsNone(me["pausa_motivo"])


class ElAlta(Base):
    def test_la_prueba_dura_20_dias_repartidos_10_y_10(self):
        """No es decoración: son los días que prometen la pantalla y los mails."""
        self.assertEqual(tr.TRIAL_PRO_DAYS, 10)
        self.assertEqual(tr.TRIAL_PLUS_DAYS, 10)
        self.assertEqual(tr.TRIAL_TOTAL_DAYS, 20)

    def test_arranca_en_pro_con_los_20_dias(self):
        uid = self._usuario()
        st = tr.status(self.conn, uid)
        self.assertEqual(st["stage"], "pro")
        self.assertEqual(st["days_left"], tr.TRIAL_TOTAL_DAYS)
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")

    def test_el_mail_de_bienvenida_sale_una_sola_vez_y_es_el_de_la_prueba(self):
        """`trial.start()` ya manda el suyo. El de "bienvenido al plan gratis"
        no puede salir además: a este usuario le prometería un plan que no
        tiene, y serían dos mails en el mismo minuto."""
        self._usuario()
        nombres = [n for n, _ in self.enviados]
        self.assertEqual(nombres.count("send_trial_started"), 1)
        self.assertNotIn("send_welcome_free", nombres)

    def test_el_mail_de_la_prueba_lleva_los_dias_de_verdad(self):
        self._usuario()
        kw = [k for n, k in self.enviados if n == "send_trial_started"][0]
        self.assertEqual(kw["pro_days"], tr.TRIAL_PRO_DAYS)
        self.assertEqual(kw["total_days"], tr.TRIAL_TOTAL_DAYS)


if __name__ == "__main__":
    unittest.main()
