"""Con el asesor la vara es otra — porque la CONSECUENCIA es otra.

No es que el asesor merezca más cuidado. Es que el mismo dato tiene un efecto
distinto según quién lo suba:

  · Usuario en su cuenta: la foto le COMPLETA la apertura. Es aditivo, y lo peor
    que puede pasar es que le falte algo.
  · Asesor por un cliente: la foto va a DIRIGIR DECISIONES, incluida la de
    cerrar posiciones que "no están en el resumen". Con el modo override
    prendido (vivo en prod para 7 brokers), un `not_in_snapshot` calculado
    contra una fecha inventada BORRA una tenencia real de alguien que ni
    siquiera está mirando la pantalla.

Por eso el corte por `fecha_desconocida` sólo aplica en contexto de asesor.
Prenderlo para todos alcanzaría al 61% de las fotos —incluidas las 47 de Cocos,
que son el 100% de ese parser— y rompería un flujo que hoy funciona para gente
que en su mayoría no es asesor.
"""
import io
import unittest
import uuid

import main
from fastapi.testclient import TestClient

# CSV real de la foto de Cocos: header EXACTO de 5 columnas, sin preámbulo y sin
# ninguna celda donde pueda venir la fecha. Por eso `parse_cocos_tenencia` nunca
# la setea (47 de 47 en producción caen al fallback).
FOTO_COCOS = ("instrumento;cantidad;precio;moneda;total\n"
              "Galicia (GGAL);1000;60,00;ARS;60000,00\n")


def _user(conn, email, tier=None, approved=1):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,'x',?,?)",
        (email, approved, tier)).lastrowid


class GateAsesorTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.advisor = _user(conn, f"asesor-{tag}@rendi.test", tier="advisor")
        self.client_uid = _user(conn, f"cliente-{tag}@rendi.test", approved=0)
        self.solo = _user(conn, f"solo-{tag}@rendi.test")
        conn.execute("UPDATE users SET managed_by=? WHERE id=?",
                     (self.advisor, self.client_uid))
        conn.execute(
            "INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, "
            "permission, status, label) VALUES (?,?,'managed','read_write','active','C')",
            (self.advisor, self.client_uid))
        for u in (self.client_uid, self.solo):
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (u, "Cocos", "ARS"))
        conn.commit(); conn.close()

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.advisor,))
            conn.commit()
        finally:
            conn.close()

    def _subir(self, uid, *, client_ctx=None, nombre="EstadoDeCuenta.csv",
               contenido=FOTO_COCOS):
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        if client_ctx:
            h["X-Rendi-Client-Id"] = str(client_ctx)
        r = self.http.post(
            "/api/imports/tenencia/preview",
            files={"file": (nombre, io.BytesIO(contenido.encode()), "text/csv")},
            data={"broker": "Cocos", "format": "cocos"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── el corte ────────────────────────────────────────────────────────────
    def test_el_asesor_NO_reconcilia_contra_una_fecha_inventada(self):
        j = self._subir(self.advisor, client_ctx=self.client_uid)
        self.assertEqual(j["fecha_origen"], "fallback_hoy")
        self.assertEqual(j["motivo"], "fecha_desconocida")
        self.assertTrue(j["no_reconciliable"])
        self.assertIsNone(j["session_id"])

    def test_el_mensaje_NO_dice_que_todo_coincide(self):
        # ⭐ La mentira más cara posible. Con el corte activo `to_seed` queda
        # vacío por construcción, así que sin una rama propia el flujo caía en
        # "tu cartera ya coincide con la foto" — le diría al asesor que verificó
        # cuando no verificó nada.
        j = self._subir(self.advisor, client_ctx=self.client_uid)
        self.assertNotIn("coincide", j["message"])
        self.assertIn("fecha", j["message"].lower())

    def test_el_usuario_en_SU_cuenta_sigue_como_siempre(self):
        # Mismo archivo, misma falta de fecha, otra consecuencia → otra vara.
        j = self._subir(self.solo)
        self.assertEqual(j["fecha_origen"], "fallback_hoy")
        self.assertIsNone(j.get("motivo"))
        self.assertFalse(j.get("no_reconciliable"))

    def test_el_asesor_en_SU_PROPIA_cuenta_tampoco_corta(self):
        # Sin header de cliente no hay tercero decidiendo sobre plata ajena:
        # el asesor está mirando su propia cartera.
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.advisor, "Cocos", "ARS"))
        conn.commit(); conn.close()
        j = self._subir(self.advisor)
        self.assertIsNone(j.get("motivo"))

    # ── lo que desbloquea el fix de la fecha en el nombre ───────────────────
    def test_con_la_fecha_en_el_NOMBRE_el_asesor_si_reconcilia(self):
        # 82 de 82 exports de Cocos se llaman portfolio_report_YYYYMMDD.csv.
        # Sin este escalón, el parser de foto más usado quedaría permanentemente
        # inservible en el único flujo que estamos construyendo.
        j = self._subir(self.advisor, client_ctx=self.client_uid,
                        nombre="portfolio_report_20260630.csv")
        self.assertEqual(j["fecha_origen"], "nombre_archivo")
        self.assertEqual(j["fecha_usada"], "2026-06-30")
        self.assertIsNone(j.get("motivo"))
        self.assertFalse(j.get("no_reconciliable"))

    def test_la_fecha_del_nombre_NO_se_hace_pasar_por_leida_del_archivo(self):
        # Es evidencia más débil —el nombre lo cambia cualquiera— así que tiene
        # su propio origen y quien decide puede verlo.
        j = self._subir(self.advisor, client_ctx=self.client_uid,
                        nombre="portfolio_report_20260630.csv")
        self.assertNotEqual(j["fecha_origen"], "archivo")


if __name__ == "__main__":
    unittest.main()
