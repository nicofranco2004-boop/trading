"""Borrar la cuenta apaga TODOS los mails de Rendi para esa persona.

Rendi manda mail por ~30 caminos distintos (alertas de precio, resumen de
mercado, recordatorios de plan, prueba gratis, los blasts del panel de admin...)
y todos pasan por el mismo embudo: `billing.emails._send(to=...)`. La garantía
de que a una cuenta borrada no le llega NADA es que todos resuelven la dirección
leyendo `users` en el momento de enviar — si la fila no está, no hay a quién
escribirle.

Este archivo verifica esa garantía de las dos maneras que pueden fallar:

  1. ESTRUCTURAL — después del borrado, la dirección no queda guardada en
     NINGUNA columna de NINGUNA tabla. Es la que ataja el bug del futuro: una
     tabla nueva que guarde el mail por su cuenta (una lista de novedades, una
     cola de envíos) volvería a hacer alcanzable a alguien que se fue, sin que
     nadie lo note.

  2. DE COMPORTAMIENTO — se corren los motores de verdad y se espía el embudo.

⚠️ Cada prueba de comportamiento lleva un TESTIGO: un segundo usuario, vivo y
con los mismos datos, que SÍ tiene que aparecer en la lista de envío. Sin eso,
un motor que no hace nada (porque le falta un dato del fixture) daría verde
diciendo "no le llegó al borrado" cuando en realidad no le llegó a nadie.
"""
import os, sys, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from billing import emails as _emails

BORRADO = "victima.borrada@gmail.com"
TESTIGO = "testigo.vivo@gmail.com"


class _Resp:
    def delete_cookie(self, *a, **k): pass
    def set_cookie(self, *a, **k): pass


class NoLleganMailsTrasBorrar(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        # ⚠️ `users` va ÚLTIMO. Con `PRAGMA foreign_keys=ON`, borrarlo primero
        # falla por FK, el `except` se lo come en silencio y los usuarios del
        # test anterior SOBREVIVEN: el siguiente test inserta emails duplicados,
        # borra uno y el otro sigue recibiendo mails. Se veía como un bug del
        # código (verde solo, rojo acompañado) y era el fixture.
        for t in ("brokers", "positions", "operations", "alerts", "alert_events",
                  "subscriptions", "config", "broadcast_send_log", "users"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.admin = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,is_admin,email_verified) "
            "VALUES ('admin@t','x',1,1,1)").lastrowid
        self.victima = self._alta(BORRADO)
        self.testigo = self._alta(TESTIGO)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _alta(self, email):
        """Un usuario con todo lo que lo hace destinatario de algo."""
        uid = self.conn.execute(
            "INSERT INTO users (email,name,password_hash,approved,email_verified,tier) "
            "VALUES (?,?,?,1,1,'pro')", (email, email.split("@")[0], "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (uid, "X", "ARS"))
        self.conn.execute(
            "INSERT INTO alerts (user_id,kind,symbol,direction,threshold,channel,active) "
            "VALUES (?,?,?,?,?,?,1)", (uid, "price", "AAPL", "above", 1.0, "email"))
        self.conn.execute(
            "INSERT INTO subscriptions (user_id,external_reference,mp_subscription_id,"
            "status,period,amount_ars) VALUES (?,?,?,?,?,?)",
            (uid, f"ref_{uid}", f"sub_{uid}", "authorized", "monthly", 12100))
        return uid

    def _borrar_victima(self):
        res = main.delete_my_account(_Resp(), uid=self.victima)
        self.assertTrue(res["ok"])

    # ── 1. Estructural ───────────────────────────────────────────────────────

    def test_la_direccion_no_queda_en_ninguna_tabla(self):
        """Ninguna columna de ninguna tabla guarda la dirección después del borrado.

        Si esto se pone en rojo, la tabla que reporta es una por la que alguien
        puede volver a ser alcanzado: o se borra con la cuenta, o se le saca el
        mail."""
        antes = self._donde_aparece(BORRADO)
        self.assertTrue(antes, "el fixture no guardó la dirección en ningún lado: "
                               "la prueba no estaría midiendo nada")
        self._borrar_victima()
        despues = self._donde_aparece(BORRADO)
        self.assertEqual(despues, [], f"la dirección sobrevive al borrado en: {despues}")
        # El testigo sigue guardado: el borrado no barre de más.
        self.assertTrue(self._donde_aparece(TESTIGO))

    def _donde_aparece(self, email):
        """['tabla.columna', ...] donde esté guardada esa dirección."""
        hits = []
        tablas = [r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tablas:
            for c in [x["name"] for x in self.conn.execute(f"PRAGMA table_info({t})")]:
                try:
                    n = self.conn.execute(
                        f'SELECT COUNT(*) c FROM "{t}" WHERE "{c}" LIKE ?',
                        (f"%{email}%",)).fetchone()["c"]
                except Exception:
                    continue          # columna no comparable con texto
                if n:
                    hits.append(f"{t}.{c}")
        return hits

    # ── 2. De comportamiento: los motores de verdad ──────────────────────────

    def test_alerta_de_precio_no_se_entrega_a_la_cuenta_borrada(self):
        """El peor caso: una entrega YA EN CURSO cuando la cuenta se borra.

        Se agarra la fila real de `alerts` ANTES de borrar y se la pasa al
        entregador después — igual que un ciclo del motor que ya tenía la alerta
        en la mano cuando el usuario apretó "eliminar cuenta". Es el único
        momento en que el motor podría escribirle a alguien que se fue.

        Se llama a `_deliver` directo a propósito: lo que se mide es a qué
        dirección se entrega, no si el precio cruzó el umbral."""
        import alerts_engine
        alertas = {u: dict(self.conn.execute(
            "SELECT * FROM alerts WHERE user_id=?", (u,)).fetchone())
            for u in (self.victima, self.testigo)}
        self._borrar_victima()
        # Mismas claves que arma `_fire` en producción (alerts_engine.py).
        items = [{"symbol": "AAPL", "price": 100.0, "change_pct": 5.0,
                  "message": "AAPL superó los USD 100", "label": "AAPL",
                  "line": "AAPL +5%", "event_id": 1}]
        with mock.patch.object(_emails, "_send", return_value=True) as spy:
            for alerta in alertas.values():
                alerts_engine._deliver(self.conn, alerta, items)
        self._assert_solo_testigo(spy, "alerta de precio")

    def test_reengagement_no_incluye_a_la_cuenta_borrada(self):
        self._borrar_victima()
        with mock.patch.object(_emails, "_send", return_value=True) as spy:
            main.admin_email_reengagement(
                main.ReengagementEmailIn(confirm=True, threshold=99), uid=self.admin)
        self._assert_solo_testigo(spy, "re-engagement")

    def test_broadcast_no_incluye_a_la_cuenta_borrada(self):
        self._borrar_victima()
        with mock.patch.object(_emails, "_send", return_value=True) as spy:
            main.admin_email_broadcast(
                main.BroadcastEmailIn(subject="Novedades", body="Hola {nombre}",
                                      confirm=True), uid=self.admin)
        self._assert_solo_testigo(spy, "broadcast")

    def _assert_solo_testigo(self, spy, motor):
        destinos = [(c.args[0] if c.args else c.kwargs.get("to")) for c in spy.call_args_list]
        self.assertNotIn(BORRADO, destinos,
                         f"{motor}: le escribió a una cuenta BORRADA ({destinos})")
        self.assertIn(TESTIGO, destinos,
                      f"{motor}: tampoco le escribió al testigo vivo — el motor no "
                      f"corrió y el verde de arriba no significa nada ({destinos})")


if __name__ == "__main__":
    unittest.main()
