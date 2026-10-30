"""Una tesis por activo y por día, aunque lleguen dos «Guardar» a la vez.

La regla de tesis.py es «el mismo día se corrige la última; otro día se guarda
una nueva». Hasta el 29/10 la hacía cumplir sólo el código: `guardar` lee «¿hay
una de hoy?» y después inserta. Con doble click o dos pestañas, el segundo pedido
lee ANTES de que el primero confirme, no ve la de hoy e inserta otra: la historia
mostraba dos versiones del mismo día (auditoría C, hallazgo 4).

La auditoría lo midió en Postgres, donde los dos escriben a la vez. Este test lo
mide también en SQLite con el orden real (el segundo lee, el primero confirma, el
segundo escribe), y ahí pasaba igual: SQLite tiene un solo escritor, pero la
lectura de `guardar` no queda dentro de la escritura, así que el segundo pedido
espera su turno y después inserta con lo que leyó antes.

El arreglo es una regla en la BASE (índice único usuario + activo + día) y un
guardado que la respeta (`INSERT … ON CONFLICT … DO UPDATE`). Y como una base que
ya tenga duplicados no deja crear el índice, el arranque primero los junta.

Corre con: cd backend && python3 -m pytest tests/test_tesis_un_dia.py
"""
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
import main
import tesis
from fastapi.testclient import TestClient
from fechas import hoy_art_date


class _Base(unittest.TestCase):
    _seq = 61000

    def setUp(self):
        _Base._seq += 1
        self.UID = _Base._seq
        with main.db_abierta() as c:
            c.execute("INSERT INTO users (id,email,password_hash,approved) VALUES (?,?,?,1)",
                      (self.UID, f"tesis{self.UID}@t.com", "x"))
            c.commit()

    def tearDown(self):
        main.app.dependency_overrides.pop(main.get_effective_user, None)
        with main.db_abierta() as c:
            for t in ("tesis", "alerts"):
                c.execute(f"DELETE FROM {t} WHERE user_id=?", (self.UID,))
            c.execute("DELETE FROM users WHERE id=?", (self.UID,))
            c.commit()

    def _filas(self, asset="AAPL"):
        with main.db_abierta() as c:
            return [tuple(r) for r in c.execute(
                "SELECT id, texto, escrita_el, alert_id FROM tesis "
                "WHERE user_id=? AND asset=? ORDER BY id", (self.UID, asset)).fetchall()]


class DosGuardarALaVez(_Base):

    def test_dos_pedidos_cruzados_dejan_una_sola_de_hoy(self):
        """Por HTTP, como la app. El pedido «segunda» lee primero y se queda
        esperando; «primera» entra, guarda y confirma; recién ahí «segunda» sigue
        y escribe. Es el orden de un doble click: no se fuerza el resultado, sólo
        el turno de cada uno.

        Al juntar con Arreglos E (30/10): `guardar` ahora toma el turno de la
        persona (`_tomar_turno`, para contar el tope de 20 por día) ANTES de leer,
        así que «primera» ya no puede confirmar mientras «segunda» espera: se
        queda esperando el turno. Por eso a «segunda» la suelta un reloj y no el
        fin de «primera»; y «vale la última» es la que terminó última, sea cuál
        sea (con el turno, «primera»; sin él, «segunda»). Lo que no cambia: una
        sola de hoy y los dos pedidos hablan de la misma."""
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.UID
        cli = TestClient(main.app)
        leyo, seguir = threading.Event(), threading.Event()
        real = tesis._ultima
        llamadas = []

        def _ultima_con_turno(conn, uid, asset):
            r = real(conn, uid, asset)
            llamadas.append(1)
            if len(llamadas) == 1:          # el pedido «segunda»: leyó, espera
                leyo.set()
                seguir.wait(10)
            return r

        resultado, terminaron = {}, []

        def _segunda():
            resultado["r"] = cli.put("/api/tesis", json={"asset": "AAPL", "texto": "segunda"})
            terminaron.append("segunda")

        with mock.patch.object(tesis, "_ultima", _ultima_con_turno):
            t = threading.Thread(target=_segunda)
            t.start()
            self.assertTrue(leyo.wait(10), "el pedido «segunda» no llegó a leer")
            threading.Timer(1.0, seguir.set).start()
            r1 = cli.put("/api/tesis", json={"asset": "AAPL", "texto": "primera"})
            terminaron.append("primera")
            seguir.set()
            t.join(30)
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(resultado["r"].status_code, 200, resultado["r"].text)

        hoy = hoy_art_date().isoformat()
        filas = self._filas()
        self.assertEqual(len(filas), 1, f"dos tesis del mismo día: {filas}")
        self.assertEqual(filas[0][1], terminaron[-1], "vale la última que se guardó")
        self.assertEqual(filas[0][2], hoy)
        self.assertEqual(r1.json()["id"], resultado["r"].json()["id"],
                         "los dos pedidos hablan de la misma tesis")

    def test_otro_dia_sigue_guardando_una_nueva_y_muda_el_recordatorio(self):
        """La regla de la base es POR DÍA: reescribirla otro día guarda otra y la
        vieja queda, con el recordatorio mudado a la nueva (como antes)."""
        with main.db_abierta() as c:
            vieja = tesis.guardar(c, self.UID, "AAPL", "la de ayer")
            c.execute("UPDATE tesis SET escrita_el='2026-01-02' WHERE id=?", (vieja,))
            tesis.fijar_recordatorio(c, self.UID, vieja, "3m")
            c.commit()
            nueva = tesis.guardar(c, self.UID, "AAPL", "la de hoy")
            c.commit()
        filas = self._filas()
        self.assertEqual([f[0] for f in filas], [vieja, nueva])
        self.assertIsNone(filas[0][3], "el recordatorio ya no está en la vieja")
        self.assertIsNotNone(filas[1][3], "el recordatorio se mudó a la nueva")


class BaseViejaConDuplicados(_Base):
    """Una base que ya tiene dos tesis del mismo día (de antes de la regla) no
    deja crear el índice único: el arranque reventaría. Primero se juntan."""

    def _sin_la_regla(self, c):
        c.execute("DROP INDEX IF EXISTS ux_tesis_un_dia")
        c.commit()

    def test_el_arranque_junta_las_repetidas_y_crea_la_regla(self):
        with main.db_abierta() as c:
            self._sin_la_regla(c)
            ins = ("INSERT INTO tesis (user_id, asset, texto, escrita_el, recordar_tipo, "
                   "recordar_el, alert_id) VALUES (?,?,?,?,?,?,?)")
            rec = c.execute(
                "INSERT INTO alerts (user_id, kind, symbol, scope, direction, channel, repeat, "
                "cooldown_min, armed, active) VALUES (?, 'recordatorio', 'AAPL', 'ticker', "
                "'either', 'both', 'once', 0, 1, 1)", (self.UID,)).lastrowid
            huerfana = c.execute(
                "INSERT INTO alerts (user_id, kind, symbol, scope, direction, channel, repeat, "
                "cooldown_min, armed, active) VALUES (?, 'recordatorio', 'AAPL', 'ticker', "
                "'either', 'both', 'once', 0, 1, 1)", (self.UID,)).lastrowid
            # Tres del mismo día: la primera con recordatorio, la del medio con
            # otro, la última (la que vale) sin. Más una de otro día, intacta.
            c.execute(ins, (self.UID, "AAPL", "uno", "2026-10-20", "3m", "2027-01-20", rec))
            c.execute(ins, (self.UID, "AAPL", "dos", "2026-10-20", "3m", "2027-01-21", huerfana))
            c.execute(ins, (self.UID, "AAPL", "tres", "2026-10-20", None, None, None))
            c.execute(ins, (self.UID, "AAPL", "otra", "2026-10-21", None, None, None))
            c.commit()
        main.init_db()                      # el arranque, como en producción
        filas = self._filas()
        self.assertEqual([(f[1], f[2]) for f in filas],
                         [("tres", "2026-10-20"), ("otra", "2026-10-21")],
                         "queda la última de cada día; la de otro día no se toca")
        self.assertEqual(filas[0][3], huerfana,
                         "la que vale hereda el recordatorio más reciente")
        with main.db_abierta() as c:
            n = c.execute("SELECT COUNT(*) FROM alerts WHERE id=?", (rec,)).fetchone()[0]
            self.assertEqual(n, 0, "el recordatorio que quedó sin tesis se borra: no "
                                   "avisaría nunca y contaría como alerta de la persona")
            # Y la regla quedó puesta: un duplicado nuevo ya no entra.
            with self.assertRaises(Exception):
                c.execute("INSERT INTO tesis (user_id, asset, texto, escrita_el) "
                          "VALUES (?,?,?,?)", (self.UID, "AAPL", "cuatro", "2026-10-20"))
            c.rollback()

    def test_el_arranque_dos_veces_no_cambia_nada(self):
        main.init_db()
        antes = self._filas()
        main.init_db()
        self.assertEqual(self._filas(), antes)


if __name__ == "__main__":
    unittest.main()
