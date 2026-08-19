"""Cierre del free trial: status(), el tope mensual, el largo de la etapa Pro,
los caminos con plata y los dos mails que mentían.

Corre con: cd backend && python3 -m pytest tests/test_trial_cierre.py
"""
import os
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import main                          # noqa: E402
from billing import trial as tr      # noqa: E402
from billing import credits as cr    # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self._cap = os.environ.get("TRIALS_MONTHLY_CAP")
        self.addCleanup(self._restore_cap)
        os.environ.pop("TRIALS_MONTHLY_CAP", None)
        for t in ("ai_usage_daily", "credit_ledger", "subscriptions",
                  "trial_consumed", "trial_email_log", "import_batches", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self._user("t@rendi.test")

    def _restore_cap(self):
        if self._cap is None:
            os.environ.pop("TRIALS_MONTHLY_CAP", None)
        else:
            os.environ["TRIALS_MONTHLY_CAP"] = self._cap

    def _user(self, email):
        uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?,?,1,1)", (email, "x")).lastrowid
        self.conn.commit()
        return uid


# ═══════════════════════════════════════════════════════════════════════════
# B. status() y el cuarto lector de credit_active_until
# ═══════════════════════════════════════════════════════════════════════════

class StatusEsDelTrialTest(Base):
    """trial_started_at queda PARA SIEMPRE, así que cualquier crédito posterior
    heredaba la etiqueta de "estás en prueba" — incluido el de quien pagó."""

    def _con_trial_viejo_y_credito(self, cau, **extra):
        """Hizo el trial (ya vencido) y HOY tiene otro crédito vigente."""
        viejo = (datetime.utcnow() - timedelta(days=40)).isoformat()
        fin_trial = (datetime.utcnow() - timedelta(days=25)).isoformat()
        campos = {"trial_started_at": viejo, "trial_used_at": viejo,
                  "trial_ends_at": fin_trial, "credit_active_until": cau, "tier": "plus"}
        campos.update(extra)
        sets = ", ".join(f"{k}=?" for k in campos)
        self.conn.execute(f"UPDATE users SET {sets} WHERE id=?",
                          (*campos.values(), self.uid))
        self.conn.commit()

    def test_el_que_pago_anual_no_esta_en_prueba(self):
        """Veía "Estás probando Rendi Plus. Te quedan 365 días" habiendo puesto
        USD 54."""
        self._con_trial_viejo_y_credito(
            (datetime.utcnow() + timedelta(days=365)).isoformat(),
            credit_anchor_plan="plus", credit_anchor_period="annual",
            credit_anchor_amount_usd=54.0)
        st = tr.status(self.conn, self.uid)
        self.assertFalse(st["active"])
        self.assertTrue(st["used"])          # sí la usó alguna vez: eso no cambia

    def test_el_que_pago_y_cancelo_no_esta_en_prueba(self):
        """En su período de gracia veía "En prueba · no cargamos ninguna
        tarjeta" al lado de "Reactivar suscripción". _has_paid_sub solo tapaba
        el caso 'authorized'; 'cancelled' pasaba derecho."""
        self._con_trial_viejo_y_credito(
            (datetime.utcnow() + timedelta(days=12)).isoformat(),
            credit_anchor_plan="pro", credit_anchor_period="monthly",
            credit_anchor_amount_usd=9.0)
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference, "
            "period, status, amount_ars) VALUES (?,?,?,'monthly','cancelled',0)",
            (self.uid, "sub-x", f"rendi-{self.uid}-pro-monthly"))
        self.conn.commit()
        self.assertFalse(tr.status(self.conn, self.uid)["active"])

    def test_al_regalado_no_le_repite_manana_pasas_a_plus(self):
        """days_to_switch quedaba clavado en 0 y se lo decía todos los días."""
        self._con_trial_viejo_y_credito(
            (datetime.utcnow() + timedelta(days=30)).isoformat(),
            tier="pro", credit_anchor_plan="pro", credit_anchor_period="monthly",
            credit_anchor_amount_usd=0.0)
        st = tr.status(self.conn, self.uid)
        self.assertFalse(st["active"])
        self.assertIsNone(st["days_to_switch"])

    def test_la_prueba_DE_VERDAD_sigue_activa(self):
        """La contracara: el fix no puede apagar el trial real."""
        tr.start(self.conn, self.uid)
        st = tr.status(self.conn, self.uid)
        self.assertTrue(st["active"])
        self.assertEqual(st["stage"], "pro")

    def test_usa_el_mismo_discriminador_que_los_otros_lectores(self):
        row = self.conn.execute(
            "SELECT credit_active_until, trial_ends_at FROM users WHERE id=?",
            (self.uid,)).fetchone()
        tr.start(self.conn, self.uid)
        row = self.conn.execute(
            "SELECT credit_active_until, trial_ends_at FROM users WHERE id=?",
            (self.uid,)).fetchone()
        self.assertTrue(tr.credit_is_trial(row["credit_active_until"], row["trial_ends_at"]))


# ═══════════════════════════════════════════════════════════════════════════
# C. El tope mensual
# ═══════════════════════════════════════════════════════════════════════════

class TopeMensualTest(Base):
    def test_el_dia_1_del_mes_cuenta(self):
        """created_at lo escribe SQLite con ESPACIO y el piso salía de Python
        con 'T'. Como ' ' < 'T', toda fila del día 1 caía debajo del piso y no
        se contaba nunca: con tope 3 entraron 8 y el mes cerró con 11."""
        dia1 = datetime.utcnow().strftime("%Y-%m-01")
        for i in range(8):
            self.conn.execute(
                "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at) "
                "VALUES (?, 'trial', 0, 15, ?)", (self.uid, f"{dia1} 14:0{i}:00"))
        self.conn.commit()
        self.assertEqual(tr._activations_this_month(self.conn), 8)

    def test_con_el_tope_lleno_no_deja_entrar(self):
        os.environ["TRIALS_MONTHLY_CAP"] = "3"
        dia1 = datetime.utcnow().strftime("%Y-%m-01")
        for i in range(8):
            self.conn.execute(
                "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at) "
                "VALUES (?, 'trial', 0, 15, ?)", (self.uid, f"{dia1} 14:0{i}:00"))
        self.conn.commit()
        otro = self._user("otro@rendi.test")
        self.assertFalse(tr.eligibility(self.conn, otro)["can_start"])
        self.assertEqual(tr.start(self.conn, otro)["reason"], "monthly_cap_reached")

    def test_el_mes_pasado_no_cuenta(self):
        """El piso tiene que seguir cortando: no vale contar todo el historial."""
        viejo = (datetime.utcnow().replace(day=1) - timedelta(days=5)).strftime("%Y-%m-%d")
        self.conn.execute(
            "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at) "
            "VALUES (?, 'trial', 0, 15, ?)", (self.uid, f"{viejo} 10:00:00"))
        self.conn.commit()
        self.assertEqual(tr._activations_this_month(self.conn), 0)

    def test_el_tope_aguanta_pedidos_simultaneos(self):
        """El chequeo estaba fuera de la transacción: 20 activaciones a la vez
        con tope 5 entraban las 20."""
        os.environ["TRIALS_MONTHLY_CAP"] = "5"
        uids = [self._user(f"race{i}@rendi.test") for i in range(20)]
        listo = threading.Barrier(len(uids))
        entraron = []

        def correr(uid):
            c = main.get_db()
            try:
                listo.wait()
                if tr.start(c, uid).get("ok"):
                    entraron.append(uid)
            except Exception:
                pass
            finally:
                c.close()

        hilos = [threading.Thread(target=correr, args=(u,)) for u in uids]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual(len(entraron), 5)
        self.assertEqual(tr._activations_this_month(self.conn), 5)

    def test_al_que_no_entro_no_le_queda_la_prueba_puesta(self):
        """Si el alta se deshace, no puede quedar tier='pro' sin fila en el
        ledger: sería una prueba invisible para el tope del mes que viene."""
        os.environ["TRIALS_MONTHLY_CAP"] = "1"
        primero = self._user("uno@rendi.test")
        self.assertTrue(tr.start(self.conn, primero)["ok"])
        segundo = self._user("dos@rendi.test")
        self.assertFalse(tr.start(self.conn, segundo).get("ok"))
        row = self.conn.execute(
            "SELECT tier, trial_used_at, credit_active_until FROM users WHERE id=?",
            (segundo,)).fetchone()
        self.assertIsNone(row["tier"])
        self.assertIsNone(row["trial_used_at"])
        self.assertIsNone(row["credit_active_until"])

    def test_sin_tope_el_ledger_no_frena_el_alta(self):
        """Con TRIALS_MONTHLY_CAP=0 (el default de hoy) el camino no cambia."""
        self.assertTrue(tr.start(self.conn, self.uid)["ok"])


class UnaCasillaUnTrialTest(Base):
    VARIANTES = ["juan.perez@gmail.com", "juanperez@gmail.com",
                 "juan.perez+rendi@gmail.com", "j.u.a.n.perez@gmail.com",
                 "JuanPerez@googlemail.com"]

    def test_las_variantes_de_gmail_son_la_misma_bandeja(self):
        claves = {tr._email_key(v) for v in self.VARIANTES}
        self.assertEqual(len(claves), 1, "una casilla de Gmail saca trials infinitos")

    def test_el_segundo_alias_ya_no_puede_activar(self):
        u1 = self._user(self.VARIANTES[0])
        self.assertTrue(tr.start(self.conn, u1)["ok"])
        u2 = self._user(self.VARIANTES[1])
        self.assertEqual(tr.eligibility(self.conn, u2)["reason"], "already_used")

    def test_en_otros_dominios_los_puntos_NO_se_tocan(self):
        """'a.b@empresa.com' y 'ab@empresa.com' pueden ser dos personas."""
        self.assertNotEqual(tr._email_key("a.b@empresa.com"),
                            tr._email_key("ab@empresa.com"))

    def test_el_alias_si_se_corta_en_cualquier_dominio(self):
        self.assertEqual(tr._email_key("a.b+x@empresa.com"),
                         tr._email_key("a.b@empresa.com"))

    def test_dos_personas_distintas_siguen_siendo_distintas(self):
        self.assertNotEqual(tr._email_key("ana@gmail.com"), tr._email_key("beto@gmail.com"))


# ═══════════════════════════════════════════════════════════════════════════
# D. La etapa Pro se llevaba DOS ventanas de cuota
# ═══════════════════════════════════════════════════════════════════════════

class LargoDeLaEtapaProTest(Base):
    def _dia_del_cambio(self, hora_de_arranque):
        """Simula día por día con el cron corriendo AHORA. Devuelve en qué día
        del trial el tier pasó a plus."""
        tr.start(self.conn, self.uid)
        r = self.conn.execute(
            "SELECT trial_started_at, trial_ends_at FROM users WHERE id=?",
            (self.uid,)).fetchone()
        ini0 = datetime.fromisoformat(r["trial_started_at"]).replace(
            hour=hora_de_arranque, minute=59, second=0, microsecond=0)
        fin0 = datetime.fromisoformat(r["trial_ends_at"]).replace(
            hour=hora_de_arranque, minute=59, second=0, microsecond=0)
        for dia in range(1, 12):
            d = timedelta(days=dia - 1)
            self.conn.execute(
                "UPDATE users SET trial_started_at=?, trial_ends_at=?, credit_active_until=? "
                "WHERE id=?", ((ini0 - d).isoformat(), (fin0 - d).isoformat(),
                               (fin0 - d).isoformat(), self.uid))
            self.conn.commit()
            tr.step_down_due_trials(self.conn)
            if self.conn.execute("SELECT tier FROM users WHERE id=?",
                                 (self.uid,)).fetchone()["tier"] == "plus":
                return dia
        return None

    def test_el_cambio_cae_el_dia_8_aunque_el_cron_corra_antes(self):
        """El trial arranca a la hora que el usuario aprieta el botón y el cron
        corre de madrugada. Con el corte por INSTANTE la etapa Pro duraba 8 días
        calendario y se comía DOS ventanas de cuota (120 análisis, el doble del
        modelo de costo). Por fecha, cae siempre el día 8."""
        self.assertEqual(self._dia_del_cambio(23), tr.TRIAL_PRO_DAYS + 1)

    def test_tampoco_se_adelanta_si_arranco_temprano(self):
        """La contracara: no puede cortar el día 7 y quedarse corto de los 7
        días de Pro que se le prometieron."""
        self.assertEqual(self._dia_del_cambio(0), tr.TRIAL_PRO_DAYS + 1)


# ═══════════════════════════════════════════════════════════════════════════
# E. Pagar durante la prueba
# ═══════════════════════════════════════════════════════════════════════════

class PagarDuranteLaPruebaTest(Base):
    def _pagar_y_cambiar(self, con_prueba):
        uid = self._user(f"pago-{con_prueba}@rendi.test")
        if con_prueba:
            tr.start(self.conn, uid)
        cr.grant_payment_credit(self.conn, user_id=uid, plan="pro", period="monthly",
                                amount_usd=None, subscription_id=f"s{con_prueba}",
                                payment_id=f"p{con_prueba}")
        return cr.convert_plan(self.conn, uid, "plus", "monthly")["days_remaining"]

    def test_los_dias_regalados_no_se_convierten_en_plata(self):
        """El invariante que hizo que el trial naciera SIN anchor volvía a entrar
        por la puerta del pago: quien paga durante la prueba sí queda con anchor,
        y a partir de ahí los 15 días regalados se valuaban al rate del plan
        pagado. Medido: 101,25 días de Plus donde el mismo pago sin prueba da
        67,5 — 33,75 fabricados, USD 4,50 de lista."""
        sin = self._pagar_y_cambiar(False)
        con = self._pagar_y_cambiar(True)
        # Los días de prueba se arrastran COMO DÍAS (regla de producto), así que
        # la diferencia es exactamente la prueba: ni más (plata fabricada) ni
        # menos (perderle los días que se le prometieron).
        self.assertAlmostEqual(con - sin, tr.TRIAL_TOTAL_DAYS, delta=0.1)

    def test_el_que_no_hizo_la_prueba_convierte_igual_que_siempre(self):
        self.assertAlmostEqual(self._pagar_y_cambiar(False), 67.5, delta=0.1)

    def test_pagar_no_le_acorta_la_ventana(self):
        """La regla de producto: los días de prueba se respetan al pagar."""
        uid = self._user("respeta@rendi.test")
        tr.start(self.conn, uid)
        cr.grant_payment_credit(self.conn, user_id=uid, plan="pro", period="monthly",
                                amount_usd=None, subscription_id="sr", payment_id="pr")
        self.assertAlmostEqual(
            cr.get_credit_state(self.conn, uid)["days_remaining"],
            tr.TRIAL_TOTAL_DAYS + 30, delta=0.1)


# ═══════════════════════════════════════════════════════════════════════════
# F. Los dos mails que decían otra cosa que la app
# ═══════════════════════════════════════════════════════════════════════════

class MailDeCierreTest(Base):
    def test_cuenta_lo_que_CARGO_no_lo_que_ocurrio_en_esos_dias(self):
        """operations.date es la fecha de la OPERACIÓN: a quien importó 343
        movimientos de tres años de historial el mail le decía "3 operaciones
        importadas" — contaba solo las que además pasaron en los últimos 15
        días. Justo el mail que empuja a pagar, y justo el que SÍ usó la prueba."""
        tr.start(self.conn, self.uid)
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, status, broker, file_name, "
            "parser_format, file_hash, valid_rows, created_at) "
            "VALUES ('b1',?,'confirmed','Balanz','x.csv','balanz','h',343,?)",
            (self.uid, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()
        self.assertEqual(tr._trial_stats(self.conn, self.uid).get("operations"), 343)

    def test_un_batch_de_antes_de_la_prueba_no_cuenta(self):
        tr.start(self.conn, self.uid)
        viejo = (datetime.utcnow() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO import_batches (id, user_id, status, broker, file_name, "
            "parser_format, file_hash, valid_rows, created_at) "
            "VALUES ('b2',?,'confirmed','Balanz','x.csv','balanz','h',999,?)",
            (self.uid, viejo))
        self.conn.commit()
        self.assertIsNone(tr._trial_stats(self.conn, self.uid).get("operations"))


class DiasRestantesTest(Base):
    def test_una_sola_definicion_para_el_mail_y_la_app(self):
        """La app redondeaba para arriba y el mail truncaba: el mismo día la
        barra decía "te quedan 2 días" y el mail "te queda 1"."""
        ahora = datetime(2026, 8, 19, 10, 0, 0)
        self.assertEqual(tr.dias_restantes(ahora + timedelta(days=1, hours=8), ahora), 2)
        self.assertEqual(tr.dias_restantes(ahora + timedelta(days=2), ahora), 2)
        self.assertEqual(tr.dias_restantes(ahora + timedelta(hours=3), ahora), 1)

    def test_lo_ya_vencido_es_cero_y_nunca_negativo(self):
        ahora = datetime(2026, 8, 19, 10, 0, 0)
        self.assertEqual(tr.dias_restantes(ahora - timedelta(days=3), ahora), 0)
        self.assertEqual(tr.dias_restantes(None, ahora), 0)
        self.assertEqual(tr.dias_restantes("no-es-fecha", ahora), 0)

    def test_status_usa_el_helper(self):
        tr.start(self.conn, self.uid)
        st = tr.status(self.conn, self.uid)
        fin = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (self.uid,)).fetchone()["trial_ends_at"]
        self.assertEqual(st["days_left"], tr.dias_restantes(fin))


if __name__ == "__main__":
    unittest.main()
