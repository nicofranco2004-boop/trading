"""Los envíos masivos del panel de admin: pausa, tandas y freno al doble click.

Re-engagement, regalo de plan, invitación a la prueba y el mail libre mandaban
todo en UN pedido, sin pausa:

  · Resend rechaza lo que pasa de su tope de pedidos por segundo, y un
    rechazo es un mail que no llega (contaba como "fallado").
  · El proxy de Vercel corta a ~30 s: con más de ~30 personas el admin veía un
    error mientras los mails seguían saliendo, y volvía a apretar. El segundo
    pedido releía la lista y le volvía a mandar a los que el primero todavía no
    había marcado.

Ahora los cinco envíos (estos cuatro y el de feedback, que tiene su archivo)
salen por el mismo motor, `main._envio_masivo`. Lo que estos tests protegen,
para CADA uno de los cuatro:

  1. Pausa entre un mail y el siguiente.
  2. Como mucho ENVIO_MASIVO_LOTE personas por pedido, y sólo las que el admin
     vio (`vistos`): sin la lista no se manda.
  3. Doble click, o dos pestañas a la vez, no le mandan dos veces a nadie.
  4. Un envío fallido no deja a nadie marcado como que lo recibió.
  5. El que dejó de calificar entre la vista previa y el click no recibe nada.

Y para los dos que tienen "reenviar" (re-engagement y regalo de plan), que un
reenvío cortado a la mitad no le vuelva a llegar a los de las primeras tandas.

Todo por HTTP, como el panel: vista previa → `vistos` → envío en tandas.

Corre con: cd backend && python3 -m pytest tests/test_envio_masivo.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from billing import emails
from billing import trial as tr

ASUNTO, CUERPO = "Novedades", "Hola {nombre}, hay cosas nuevas."

# Lo que cambia de un envío a otro. El resto del test es el mismo para los cuatro.
CAMPAÑAS = {
    "re-engagement": dict(
        url="/api/admin/email/re-engagement", manda="send_reengagement",
        cuerpo={}, columna="reengagement_email_sent_at"),
    "gift-plan": dict(
        url="/api/admin/email/gift-plan", manda="send_gift_plan_history",
        cuerpo={}, columna="gift_plan_email_sent_at"),
    "trial-invite": dict(
        url="/api/admin/email/trial-invite", manda="send_trial_invite",
        cuerpo={"limit": 200}, columna="trial_invite_email_sent_at"),
    "broadcast": dict(
        url="/api/admin/email/broadcast", manda="send_custom",
        cuerpo={"subject": ASUNTO, "body": CUERPO}, columna=None),
}


def _visto(campaña, fila):
    """Lo que manda el panel por cada fila: el id y la fecha de envío que se ve."""
    if campaña in ("re-engagement", "gift-plan"):
        return {"id": fila["id"], "sent_at": fila["already_sent_at"]}
    return {"id": fila["id"]}


def _pendiente(campaña, fila):
    """¿El botón principal del panel la cuenta? (los que todavía no lo recibieron)"""
    if campaña in ("re-engagement", "gift-plan"):
        return not fila["already_sent_at"]
    if campaña == "broadcast":
        return not fila["ya_recibio"]
    return True


class EnvioMasivo(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "broadcast_send_log", "operations", "positions", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"admin-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.admin = cur.lastrowid
        self.conn.commit()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        for var in ("TRIALS_ENABLED", "TRIALS_MONTHLY_CAP", "PAYWALL_NUEVOS"):
            os.environ.pop(var, None)
        self.addCleanup(self.conn.close)

    # ── el mundo ────────────────────────────────────────────────────────────

    def _personas(self, n):
        """Usuarios recién registrados y verificados, sin nada cargado: le
        califican a los cuatro envíos a la vez."""
        ids = []
        for _ in range(n):
            cur = self.conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified) "
                "VALUES (?, 'Ana', 'x', 1, 1)", (f"u-{uuid.uuid4().hex[:10]}@rendi.test",))
            ids.append(cur.lastrowid)
        self.conn.commit()
        return ids

    def _email(self, uid):
        return self.conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()["email"]

    def _marca(self, campaña, uid):
        """¿Figura como que lo recibió? (la columna, o la fila del log del mail libre)"""
        col = CAMPAÑAS[campaña]["columna"]
        if col:
            return self.conn.execute(f"SELECT {col} m FROM users WHERE id=?", (uid,)).fetchone()["m"]
        fila = self.conn.execute(
            "SELECT sent_at FROM broadcast_send_log WHERE content_hash=? AND email=?",
            (main._broadcast_hash(ASUNTO, CUERPO, True), self._email(uid))).fetchone()
        return fila["sent_at"] if fila else None

    def _otra_pestaña_le_manda(self, campaña, uid):
        """Lo que haría otro pedido que le gana la marca a esta persona."""
        # Con su propia conexión, como un pedido aparte: corre adentro del envío,
        # en otro hilo, donde la conexión del test no se puede usar.
        otra = main.get_db()
        col = CAMPAÑAS[campaña]["columna"]
        if col:
            otra.execute(f"UPDATE users SET {col}=? WHERE id=?",
                         (datetime.utcnow().isoformat(), uid))
        else:
            email = otra.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()["email"]
            otra.execute("INSERT INTO broadcast_send_log (content_hash, email) VALUES (?, ?)",
                         (main._broadcast_hash(ASUNTO, CUERPO, True), email))
        otra.commit()
        otra.close()

    def _envejecer(self, campaña, uid, horas):
        col = CAMPAÑAS[campaña]["columna"]
        m = datetime.fromisoformat(self._marca(campaña, uid)) - timedelta(hours=horas)
        self.conn.execute(f"UPDATE users SET {col}=? WHERE id=?", (m.isoformat(), uid))
        self.conn.commit()

    # ── el panel ────────────────────────────────────────────────────────────

    def _vista(self, campaña, **extra):
        c = CAMPAÑAS[campaña]
        r = self.client.post(c["url"], json={**c["cuerpo"], **extra, "confirm": False},
                             headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _vistos(self, campaña, vista=None, todos=False, **extra):
        vista = vista or self._vista(campaña, **extra)
        return [_visto(campaña, f) for f in vista["recipients"]
                if todos or _pendiente(campaña, f)]

    def _post(self, campaña, vistos, **extra):
        c = CAMPAÑAS[campaña]
        return self.client.post(c["url"], json={**c["cuerpo"], **extra, "confirm": True,
                                                "vistos": vistos}, headers=self.headers)

    def _mandar(self, campaña, vistos=None, ok=True, side_effect=None, **extra):
        """Un pedido de envío, como lo arma el panel. Devuelve (respuesta, espía)."""
        if vistos is None:
            vistos = self._vistos(campaña, **extra)
        kw = {"side_effect": side_effect} if side_effect else {"return_value": ok}
        with patch(f"billing.emails.{CAMPAÑAS[campaña]['manda']}", **kw) as spy, \
             patch("billing.emails.PAUSA_ENTRE_ENVIOS", 0):
            r = self._post(campaña, vistos, **extra)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), spy

    def _cada_campaña(self):
        for campaña in CAMPAÑAS:
            with self.subTest(campaña=campaña):
                self.setUp()
                yield campaña

    # ── 1. pausa ────────────────────────────────────────────────────────────

    def test_entre_mail_y_mail_hay_pausa(self):
        for campaña in self._cada_campaña():
            self._personas(3)
            vistos = self._vistos(campaña)
            with patch(f"billing.emails.{CAMPAÑAS[campaña]['manda']}", return_value=True), \
                 patch("main.time.sleep") as dormir:
                r = self._post(campaña, vistos)
            self.assertEqual(r.json()["sent_count"], 3)
            self.assertEqual([c.args[0] for c in dormir.call_args_list],
                             [emails.PAUSA_ENTRE_ENVIOS] * 2)   # entre 3 mails, 2 pausas

    def test_la_pausa_es_la_del_servicio_de_mail(self):
        # Una sola constante para todos los envíos, al lado de `_send`.
        self.assertGreater(emails.PAUSA_ENTRE_ENVIOS, 0)
        import market_brief
        self.assertEqual(market_brief.SEND_GAP_SECONDS, emails.PAUSA_ENTRE_ENVIOS)

    # ── 2. tandas y lista vista ─────────────────────────────────────────────

    def test_como_mucho_un_lote_por_pedido_y_sin_lista_no_se_manda(self):
        lote = main.ENVIO_MASIVO_LOTE
        for campaña in self._cada_campaña():
            self._personas(2)
            self.assertEqual(self._vista(campaña)["lote"], lote)
            muchos = [{"id": i} for i in range(1, lote + 2)]
            with patch(f"billing.emails.{CAMPAÑAS[campaña]['manda']}") as spy:
                self.assertEqual(self._post(campaña, muchos).status_code, 422)
                c = CAMPAÑAS[campaña]
                sin_lista = self.client.post(c["url"], json={**c["cuerpo"], "confirm": True},
                                             headers=self.headers)
                self.assertEqual(sin_lista.status_code, 422)
            spy.assert_not_called()

    def test_si_se_acaba_el_tiempo_del_pedido_devuelve_los_que_faltan_sin_marcar(self):
        """Resend lento: el pedido no empieza otro mail pasado el presupuesto, y
        los que no intentó vuelven sin marca para el pedido siguiente. Con
        presupuesto vencido desde el arranque, cada pedido manda UNO (siempre
        avanza) y el panel, reenviando los pendientes, termina con todos."""
        for campaña in self._cada_campaña():
            ids = self._personas(3)
            cola = self._vistos(campaña)
            pedidos, enviados = 0, []
            with patch.object(main, "ENVIO_MASIVO_PRESUPUESTO_SEG", -1):
                while cola:
                    res, spy = self._mandar(campaña, cola)
                    pedidos += 1
                    self.assertEqual(spy.call_count, 1)
                    enviados += [x["id"] for x in res["sent"]]
                    quedan = {p["id"] for p in res["pendientes"]}
                    for uid in quedan:
                        self.assertIsNone(self._marca(campaña, uid),
                                          "quedó marcado alguien que no se intentó")
                    cola = [v for v in cola if v["id"] in quedan]
            self.assertEqual(pedidos, 3)
            self.assertEqual(sorted(enviados), sorted(ids))

    def test_solo_les_llega_a_los_que_vio_el_admin(self):
        for campaña in self._cada_campaña():
            ids = self._personas(5)
            vistos = [v for v in self._vistos(campaña) if v["id"] in ids[:2]]
            res, spy = self._mandar(campaña, vistos)
            self.assertEqual({x["id"] for x in res["sent"]}, set(ids[:2]))
            self.assertEqual(spy.call_count, 2)
            for uid in ids[2:]:
                self.assertIsNone(self._marca(campaña, uid))

    def test_la_invitacion_les_llega_a_los_que_sorteo_la_vista_previa(self):
        """Antes el envío volvía a sortear: el admin veía una lista y el aviso
        le llegaba a otra."""
        self._personas(30)
        vista = self._vista("trial-invite", limit=5)
        sorteados = {f["id"] for f in vista["recipients"]}
        res, _ = self._mandar("trial-invite", self._vistos("trial-invite", vista))
        self.assertEqual({x["id"] for x in res["sent"]}, sorteados)
        avisados = {r["id"] for r in self.conn.execute(
            "SELECT id FROM users WHERE trial_invite_email_sent_at IS NOT NULL")}
        self.assertEqual(avisados, sorteados)

    # ── 3. doble click y dos pestañas ───────────────────────────────────────

    def test_doble_click_no_le_manda_dos_veces_a_nadie(self):
        for campaña in self._cada_campaña():
            self._personas(3)
            en_pantalla = self._vistos(campaña)          # lo que ve el admin
            primero, spy1 = self._mandar(campaña, en_pantalla)
            segundo, spy2 = self._mandar(campaña, en_pantalla)
            self.assertEqual(primero["sent_count"], 3)
            self.assertEqual(spy1.call_count, 3)
            self.assertEqual(segundo["sent_count"], 0, "el segundo click volvió a mandar")
            self.assertEqual(segundo["skipped_count"], 3)
            spy2.assert_not_called()

    def test_otra_pestaña_que_le_gana_a_alguien_a_mitad_de_camino(self):
        """La marca se toma ANTES de mandar y sólo si sigue como la vio el
        admin: si otro pedido se la ganó mientras éste mandaba al anterior, se
        saltea. (Con la marca DESPUÉS de mandar, como estaba, los dos pedidos
        leían "no lo recibió" y le mandaban los dos.)"""
        for campaña in self._cada_campaña():
            a, b = self._personas(2)
            vistos = self._vistos(campaña)
            emails_ab = {self._email(a): a, self._email(b): b}

            def le_gana_al_otro(**kw):
                otro = next(u for e, u in emails_ab.items() if e != kw["to"])
                self._otra_pestaña_le_manda(campaña, otro)
                return True

            res, spy = self._mandar(campaña, vistos, side_effect=le_gana_al_otro)
            self.assertEqual(spy.call_count, 1, "al segundo le llegó dos veces")
            self.assertEqual(res["sent_count"], 1)
            self.assertEqual(res["skipped_count"], 1)

    # ── 4. fallas ───────────────────────────────────────────────────────────

    def test_envio_fallido_no_deja_marca_y_vuelve_a_la_lista(self):
        for campaña in self._cada_campaña():
            ids = self._personas(2)
            res, _ = self._mandar(campaña, ok=False)
            self.assertEqual(res["failed_count"], 2)
            self.assertEqual(res["sent_count"], 0)
            for uid in ids:
                self.assertIsNone(self._marca(campaña, uid),
                                  "quedó marcado como enviado sin que el mail saliera")
            # La próxima vez el panel los vuelve a ofrecer, y salen.
            self.assertEqual({v["id"] for v in self._vistos(campaña)}, set(ids))
            otra, _ = self._mandar(campaña)
            self.assertEqual(otra["sent_count"], 2)

    def _mandar_por_resend(self, campaña, vistos, respuesta):
        """El envío de verdad hasta la llamada a Resend: `respuesta` es lo que
        devuelve (un código) o lo que tira (una excepción) `httpx.post`."""
        import httpx

        class _R:
            def __init__(self, code):
                self.status_code, self.text = code, "x"

        def _post(*a, **k):
            if isinstance(respuesta, Exception):
                raise respuesta
            return _R(respuesta)

        with patch.object(emails, "_running_under_pytest", return_value=False), \
             patch.object(emails, "_is_test_address", return_value=False), \
             patch.object(emails, "_is_configured", return_value=True), \
             patch.object(emails, "_api_key", return_value="re_test"), \
             patch.object(emails, "PAUSA_ENTRE_ENVIOS", 0), \
             patch.object(httpx, "post", side_effect=_post) as spy:
            r = self._post(campaña, vistos)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), spy

    def test_si_resend_no_contesta_a_tiempo_queda_marcado_y_no_se_le_vuelve_a_mandar(self):
        """Resend recibe el pedido, manda el mail y su respuesta no llega en
        10 s. Devolver la marca lo ponía otra vez como pendiente y el click
        siguiente le mandaba un segundo mail (lo reprodujo la auditoría)."""
        import httpx
        for campaña in self._cada_campaña():
            uid = self._personas(1)[0]
            vistos = self._vistos(campaña)
            res, _ = self._mandar_por_resend(campaña, vistos, httpx.ReadTimeout("lento"))
            self.assertEqual([t["id"] for t in res["inciertos"]], [uid])
            self.assertEqual(res["sent_count"], 0)
            self.assertEqual(res["failed_count"], 0)
            self.assertIsNotNone(self._marca(campaña, uid), "se devolvió la marca")
            # Ni la vista previa lo ofrece, ni un pedido con la lista vieja lo manda.
            self.assertNotIn(uid, {v["id"] for v in self._vistos(campaña)})
            otra, spy = self._mandar_por_resend(campaña, vistos, 200)
            spy.assert_not_called()
            self.assertEqual(otra["sent_count"], 0)

    def test_un_5xx_de_resend_tambien_es_incierto(self):
        uid = self._personas(1)[0]
        res, _ = self._mandar_por_resend("broadcast", self._vistos("broadcast"), 503)
        self.assertEqual([t["id"] for t in res["inciertos"]], [uid])
        self.assertIsNotNone(self._marca("broadcast", uid))

    def test_si_resend_lo_rechaza_seguro_se_devuelve_la_marca(self):
        """429 (muy rápido) o sin conexión: el mail no salió, la persona vuelve
        a la lista para el próximo intento."""
        import httpx
        for respuesta in (429, 422, httpx.ConnectError("sin red")):
            for campaña in self._cada_campaña():
                with self.subTest(respuesta=repr(respuesta)):
                    uid = self._personas(1)[0]
                    res, _ = self._mandar_por_resend(campaña, self._vistos(campaña), respuesta)
                    self.assertEqual(res["failed_count"], 1)
                    self.assertEqual(res["inciertos"], [])
                    self.assertIsNone(self._marca(campaña, uid))

    def test_si_no_se_puede_borrar_la_anotacion_del_mail_libre_se_informa(self):
        uid = self._personas(1)[0]
        vistos = self._vistos("broadcast")
        real_get_db = main.get_db

        class _ConnQueNoDeja:
            """Deja anotar, pero no deja borrar la anotación (base trabada)."""
            def __init__(self):
                self._c = real_get_db()
            def execute(self, sql, params=()):
                if sql.startswith("DELETE FROM broadcast_send_log"):
                    raise sqlite3.OperationalError("database is locked")
                return self._c.execute(sql, params)
            def __getattr__(self, n):
                return getattr(self._c, n)

        with patch("main.get_db", side_effect=lambda: _ConnQueNoDeja()):
            res, _ = self._mandar("broadcast", vistos, ok=False)
        self.assertEqual(res["failed_count"], 1)
        self.assertEqual([t["id"] for t in res["marcas_trabadas"]], [uid])

    # ── 5. el que dejó de calificar ─────────────────────────────────────────

    def test_el_que_dejo_de_calificar_despues_de_la_vista_previa_no_recibe_nada(self):
        cambios = {
            # cargó su historial: ya no es "registrado sin nada"
            "re-engagement": lambda u: [self.conn.execute(
                "INSERT INTO operations (user_id, date, broker, asset, op_type, quantity) "
                "VALUES (?, '2026-01-02', 'X', 'AAPL', 'buy', 1)", (u,)) for _ in range(3)],
            # arrancó la prueba: el regalo se pisaría con lo que ya tiene
            "gift-plan": lambda u: tr.start(self.conn, u),
            # arrancó la prueba: ya no la puede activar
            "trial-invite": lambda u: tr.start(self.conn, u),
            # se le desconfirmó el mail
            "broadcast": lambda u: self.conn.execute(
                "UPDATE users SET email_verified=0 WHERE id=?", (u,)),
        }
        for campaña in self._cada_campaña():
            sigue, cambio = self._personas(2)
            vistos = self._vistos(campaña)
            cambios[campaña](cambio)
            self.conn.commit()
            res, spy = self._mandar(campaña, vistos)
            self.assertEqual({x["id"] for x in res["sent"]}, {sigue})
            self.assertEqual(res["discarded_count"], 1)
            self.assertEqual(spy.call_count, 1)

    # ── 6. reenviar (re-engagement y regalo de plan) ────────────────────────

    def _cada_reenvio(self):
        for campaña in ("re-engagement", "gift-plan"):
            with self.subTest(campaña=campaña):
                self.setUp()
                yield campaña

    def test_sin_reenviar_no_le_manda_a_quien_ya_lo_recibio(self):
        for campaña in self._cada_reenvio():
            uid = self._personas(1)[0]
            self._mandar(campaña)
            self._envejecer(campaña, uid, 48)
            ya = self._vistos(campaña, todos=True)
            res, spy = self._mandar(campaña, ya, resend=False)
            self.assertEqual(res["sent_count"], 0)
            spy.assert_not_called()

    def test_reenviar_dos_veces_con_la_misma_lista_no_duplica(self):
        """El doble click de "reenviar": la persona SIGUE en la lista después
        del primer envío. Comparar la marca contra lo que leyó el pedido (y no
        contra lo que vio el admin) dejaba que el segundo click la ganara."""
        for campaña in self._cada_reenvio():
            ids = self._personas(2)
            self._mandar(campaña)
            for u in ids:
                self._envejecer(campaña, u, 48)
            en_pantalla = self._vistos(campaña, todos=True)
            primero, spy1 = self._mandar(campaña, en_pantalla, resend=True)
            segundo, spy2 = self._mandar(campaña, en_pantalla, resend=True)
            self.assertEqual(primero["sent_count"], 2)
            self.assertEqual(spy1.call_count, 2)
            self.assertEqual(segundo["sent_count"], 0, "el segundo click volvió a reenviar")
            spy2.assert_not_called()

    def test_reenvio_cortado_no_le_vuelve_a_llegar_a_los_de_la_primera_tanda(self):
        """Se cortó después de la primera tanda; el panel recarga la lista y el
        admin vuelve a apretar "reenviar". Al que le acaba de llegar se lo ve
        esperando, y aunque el pedido lo nombre, no se le manda."""
        for campaña in self._cada_reenvio():
            a, b = self._personas(2)
            self._mandar(campaña)
            for u in (a, b):
                self._envejecer(campaña, u, 48)
            primera_tanda = [v for v in self._vistos(campaña, todos=True) if v["id"] == a]
            self._mandar(campaña, primera_tanda, resend=True)      # …y se cortó

            vista = self._vista(campaña)                          # el panel recarga
            fila_a = next(f for f in vista["recipients"] if f["id"] == a)
            self.assertTrue(fila_a["espera"], "no avisa que a A le acaba de llegar")
            self.assertEqual(vista["espera_horas"], main.REENVIO_ESPERA_HORAS)

            res, spy = self._mandar(campaña, self._vistos(campaña, vista, todos=True),
                                    resend=True)
            self.assertEqual({x["id"] for x in res["sent"]}, {b})
            self.assertEqual(spy.call_count, 1, "a A le llegó dos veces")

    def test_reenvio_fallido_deja_la_fecha_que_tenia(self):
        for campaña in self._cada_reenvio():
            uid = self._personas(1)[0]
            self._mandar(campaña)
            self._envejecer(campaña, uid, 48)
            antes = self._marca(campaña, uid)
            res, _ = self._mandar(campaña, self._vistos(campaña, todos=True),
                                  resend=True, ok=False)
            self.assertEqual(res["failed_count"], 1)
            self.assertEqual(self._marca(campaña, uid), antes)

    # ── 7. el mail libre ve lo que ya salió ─────────────────────────────────

    def test_la_vista_previa_del_mail_libre_marca_a_quien_ya_lo_recibio(self):
        a, b = self._personas(2)
        self._mandar("broadcast", [{"id": a}])
        vista = self._vista("broadcast")
        ya = {f["id"]: f["ya_recibio"] for f in vista["recipients"]}
        self.assertEqual(ya, {a: True, b: False})
        self.assertEqual(vista["ya_recibieron"], 1)
        # Otro texto es otro mail: nadie lo recibió todavía.
        otro = self._vista("broadcast", body="Otro texto")
        self.assertEqual(otro["ya_recibieron"], 0)

    def test_la_vista_previa_del_mail_libre_trae_a_todos(self):
        """El panel manda de esta lista, de a tandas: si se recortara (como
        antes, a 500), a los que quedan afuera no les llegaría nunca."""
        self._personas(3)
        vista = self._vista("broadcast")
        self.assertEqual(len(vista["recipients"]), vista["total_recipients"])
        self.assertNotIn("truncated", vista)


if __name__ == "__main__":
    unittest.main()
