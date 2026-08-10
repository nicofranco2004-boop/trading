"""Cancelar una suscripción hace DOS cosas que fallan por separado: la baja en
Rebill (red) y anotarla acá (escritura en SQLite). Un usuario real no pudo darse
de baja el 2026-08-10 —la migración de arranque tenía tomado el lock de
escritura— y vio "No pudimos cancelar".

Ese cartel es lo peor que puede pasar acá, porque puede ser MENTIRA: si la baja
en Rebill ya salió, la persona está cancelada y no lo sabe. Y si reintenta,
Rebill devuelve 4xx sobre una sub ya cancelada y quedaba trabada para siempre.

Estos tests fijan la regla: una vez que Rebill dice que sí, nada de lo que pase
después puede reportarse como "no se pudo".
"""
import sqlite3
import unittest
import uuid
from unittest.mock import patch

import main


def _new_user(conn):
    email = f"cancel-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (email,),
    )
    return cur.lastrowid


class CancelResilienteTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_user(conn)
        self.sub_id = f"sub-{uuid.uuid4().hex[:10]}"
        conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, 'rendi-x-monthly', 'monthly', 'authorized', 12100)""",
            (self.uid, self.sub_id),
        )
        conn.commit()
        conn.close()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _estado(self):
        conn = main.get_db()
        row = conn.execute(
            "SELECT status FROM subscriptions WHERE mp_subscription_id=?", (self.sub_id,)
        ).fetchone()
        conn.close()
        return row["status"]

    def _cancelar(self):
        return self.client.post("/api/billing/cancel", headers=self.headers)

    # ── el camino feliz sigue andando ────────────────────────────────────────

    def test_baja_normal(self):
        with patch("billing.rebill.cancel_subscription") as m:
            m.return_value = {"id": self.sub_id, "status": "cancelled"}
            r = self._cancelar()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["local_sync_pending"])
        self.assertEqual(self._estado(), "cancelled")

    # ── el bug reportado ─────────────────────────────────────────────────────

    def test_reintento_sobre_una_sub_YA_cancelada_en_rebill_no_traba_al_usuario(self):
        """El primer intento canceló en Rebill y murió al persistir. La persona
        reintenta: Rebill ya la tiene cancelada y tira 4xx. Antes eso era un 502
        y el cartel "No pudimos cancelar" para siempre, sobre una baja hecha."""
        with patch("billing.rebill.cancel_subscription", side_effect=RuntimeError("409 already cancelled")), \
             patch("billing.rebill.get_subscription", return_value={"status": "cancelled"}):
            r = self._cancelar()
        self.assertEqual(r.status_code, 200, r.text)
        # y además nos deja la fila en orden, que era lo que había fallado antes
        self.assertEqual(self._estado(), "cancelled")

    def test_si_la_escritura_local_falla_NO_le_decimos_que_no_se_pudo(self):
        """Rebill ya no le cobra más. Decirle "no pudimos cancelar" lo empuja a
        reintentar o a llamar al banco por una baja que ya ocurrió."""
        with patch("billing.rebill.cancel_subscription") as m, \
             patch.object(main, "_run_with_lock_retry",
                          side_effect=sqlite3.OperationalError("database is locked")):
            m.return_value = {"id": self.sub_id, "status": "cancelled"}
            r = self._cancelar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "cancelled")
        # pero lo admite, para que la UI pueda avisar que tarda en reflejarse
        self.assertTrue(r.json()["local_sync_pending"])

    def test_un_mail_caido_no_convierte_una_baja_exitosa_en_error(self):
        with patch("billing.rebill.cancel_subscription") as m, \
             patch.object(main, "_maybe_send_cancellation_email",
                          side_effect=RuntimeError("Resend caído")):
            m.return_value = {"id": self.sub_id, "status": "cancelled"}
            r = self._cancelar()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._estado(), "cancelled")

    # ── pero seguimos avisando cuando de verdad falla ────────────────────────

    def test_si_rebill_esta_caido_de_verdad_SI_falla(self):
        """El contrapeso: la tolerancia de arriba no puede tragarse una baja que
        nunca ocurrió. Si Rebill falla y al releer NO está cancelada, es 502."""
        with patch("billing.rebill.cancel_subscription", side_effect=RuntimeError("timeout")), \
             patch("billing.rebill.get_subscription", return_value={"status": "authorized"}):
            r = self._cancelar()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self._estado(), "authorized")   # no la tocamos

    def test_si_rebill_no_responde_ni_para_releer_tampoco_inventamos(self):
        with patch("billing.rebill.cancel_subscription", side_effect=RuntimeError("timeout")), \
             patch("billing.rebill.get_subscription", side_effect=RuntimeError("timeout")):
            r = self._cancelar()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self._estado(), "authorized")


if __name__ == "__main__":
    unittest.main()
