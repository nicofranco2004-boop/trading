"""El tope de cordura del backfill: que no pueda vaciarle la cartera a nadie.

EL ACCIDENTE QUE FRENA. El backfill "seguro" decide qué borrar comparando la
cartera real contra la que sale de recomputar sobre una COPIA de la base. Si esa
copia sale vacía o incompleta, la comparación dice "esto tenía cantidad y ahora
es cero" para TODO, `_classify_safe` lo marca como fantasma, y se borran tenencias
REALES. El usuario abre la app y no están sus acciones. Sólo se recupera de backup.

Hasta la sesión 6 no había ningún piso en todo el archivo, y ese código ya corrió
sobre 830 cuentas.

DOS TOPES, con trabajos distintos:
  · POR USUARIO — >50% de las posiciones de alguien, y que sean ≥5 filas.
  · POR TANDA   — >25% de los usuarios con cambios frenados, y que sean ≥3.

Los pisos absolutos (5 y 3) no son decoración: sin ellos el porcentaje frena
cuentas chicas legítimas. Alguien con 2 letras vencidas pierde el 100% de sus
posiciones y está perfecto.

VERIFICADO QUE FALLA CON EL COMPORTAMIENTO VIEJO: con `_ejecutar_plan` llamado
directo (que es lo que hacía `_apply_safe`), `test_no_vacia_la_cartera_de_nadie`
deja la cartera en 0 y el assert se cae.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main                                        # noqa: E402
from importing import recompute_backfill as rb     # noqa: E402


def _mk_user(conn, email):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (email, "x")).lastrowid


def _mk_pos(conn, uid, asset, qty=10.0, broker="Cocos", batch=None):
    """Crea una posición. Si se pasa `batch`, la deja VINCULADA a ese import.

    El vínculo no es cosmético: el backfill sólo toca posiciones creadas por un
    import (`_import_linked_position_ids`) y respeta las cargadas a mano. Una
    posición sin vincular hace que el plan salga VACÍO y el test pase por el
    motivo equivocado — pasó al escribir esto.
    """
    pid = conn.execute(
        "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, "
        "buy_price, entry_date, currency) VALUES (?,?,?,0,?,?,?,?,?)",
        (uid, broker, asset, qty, qty * 100.0, 100.0, "2024-03-15", "ARS")).lastrowid
    if batch:
        conn.execute("INSERT INTO import_op_links (batch_id, position_id) VALUES (?,?)",
                     (batch, pid))
    return pid


def _mk_batch(conn, uid, bid):
    conn.execute(
        "INSERT INTO import_batches (id, user_id, broker, parser_format, file_hash, status) "
        "VALUES (?,?,?,?,?,?)", (bid, uid, "Cocos", "rendi_generic", f"h{bid}", "confirmed"))
    return bid


class TopePorUsuarioTest(unittest.TestCase):
    """El tope aislado: `_excede_tope_usuario` decide, y hay que poder leerlo."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _mk_user(self.conn, f"tope-{self._testMethodName}@rendi.test")

    def tearDown(self):
        self.conn.close()

    def _con_n_posiciones(self, n):
        for i in range(n):
            _mk_pos(self.conn, self.uid, f"ACC{i}")
        self.conn.commit()

    def test_cuenta_chica_que_se_va_entera_NO_se_frena(self):
        """2 letras vencidas que van a cero = 100%, y está bien.

        Es el caso que justifica el piso de 5. Un tope de sólo-porcentaje frenaría
        esto, que es trabajo legítimo, y el freno se volvería ruido que uno aprende
        a ignorar."""
        self._con_n_posiciones(2)
        self.assertIsNone(rb._excede_tope_usuario(self.conn, self.uid, 2))

    def test_cuatro_filas_no_alcanzan_el_piso(self):
        self._con_n_posiciones(4)
        self.assertIsNone(rb._excede_tope_usuario(self.conn, self.uid, 4))

    def test_la_mitad_justa_pasa(self):
        """50% no es "más del 50%". El borde importa: un tope que frena en el
        empate frena carteras partidas al medio, que son comunes."""
        self._con_n_posiciones(20)
        self.assertIsNone(rb._excede_tope_usuario(self.conn, self.uid, 10))

    def test_mas_de_la_mitad_y_cinco_o_mas_frena(self):
        self._con_n_posiciones(20)
        r = rb._excede_tope_usuario(self.conn, self.uid, 11)
        self.assertIsNotNone(r)
        self.assertEqual(r["borraria"], 11)
        self.assertEqual(r["tiene"], 20)
        self.assertEqual(r["pct"], 55.0)

    def test_vaciar_la_cartera_entera_frena(self):
        self._con_n_posiciones(30)
        r = rb._excede_tope_usuario(self.conn, self.uid, 30)
        self.assertIsNotNone(r)
        self.assertEqual(r["pct"], 100.0)


class ElBackfillNoVaciaCarterasTest(unittest.TestCase):
    """De punta a punta, con el accidente real: la copia sale VACÍA."""

    def setUp(self):
        self.conn = main.get_db()
        self.uids = []
        for i in range(4):
            uid = _mk_user(self.conn, f"vaciar-{self._testMethodName}-{i}@rendi.test")
            b = _mk_batch(self.conn, uid, f"batch-{self._testMethodName}-{i}")
            for j in range(10):
                _mk_pos(self.conn, uid, f"ACC{j}", batch=b)
            self.uids.append(uid)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _posiciones(self, uid):
        r = self.conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0",
            (uid,)).fetchone()
        return int(r["c"] or 0)

    def _correr_con_copia_vacia(self, apply):
        """Simula el accidente: el recompute sobre la copia deja al usuario en cero.

        No se rompe el clon a mano (eso probaría el clon, no el tope): se
        reemplaza `recompute_user` por uno que borra todo EN LA COPIA, que es
        exactamente el estado que produce una copia incompleta.
        """
        def recompute_vacia_todo(clone_conn, uid, **kw):
            clone_conn.execute("DELETE FROM positions WHERE user_id=?", (uid,))

        original = rb.recompute_user
        rb.recompute_user = recompute_vacia_todo
        try:
            return rb.safe_backfill(self.conn, self.uids, recalc=lambda *a, **k: None,
                                    apply=apply)
        finally:
            rb.recompute_user = original

    @unittest.skipIf(getattr(main, "USANDO_PG", False),
                     "pasa por safe_backfill, que clona la base: sólo-SQLite")
    def test_no_vacia_la_cartera_de_nadie(self):
        antes = {u: self._posiciones(u) for u in self.uids}
        self.assertEqual(set(antes.values()), {10})

        res = self._correr_con_copia_vacia(apply=True)

        # Los 4 usuarios pedían borrar 10 de 10 → los 4 frenados → 4 de 4 supera
        # el 25% y llega al piso de 3 → la TANDA no escribe nada.
        self.assertTrue(res["tanda_abortada"], res)
        self.assertEqual(len(res["frenados"]), 4, res["frenados"])
        for u in self.uids:
            self.assertEqual(self._posiciones(u), 10,
                             f"al usuario {u} le borraron posiciones REALES")

    @unittest.skipIf(getattr(main, "USANDO_PG", False),
                     "pasa por safe_backfill, que clona la base: sólo-SQLite")
    def test_el_ensayo_avisa_del_freno_antes_de_aplicar(self):
        """Simular tiene que mostrar el freno, no descubrirlo recién al aplicar."""
        res = self._correr_con_copia_vacia(apply=False)
        self.assertTrue(res["tanda_abortada"], res)
        self.assertEqual(len(res["frenados"]), 4)
        # Y sigue sin tocar nada, obvio: apply=False.
        for u in self.uids:
            self.assertEqual(self._posiciones(u), 10)

    @unittest.skipIf(getattr(main, "USANDO_PG", False),
                     "pasa por safe_backfill, que clona la base: sólo-SQLite")
    def test_el_mensaje_dice_los_numeros_y_no_solo_que_fallo(self):
        res = self._correr_con_copia_vacia(apply=True)
        msg = " ".join(e["error"] for e in res["errors"])
        self.assertIn("TANDA ABORTADA", msg)
        self.assertIn("No se escribió nada", msg)
        f = res["frenados"][0]
        self.assertEqual((f["borraria"], f["tiene"], f["pct"]), (10, 10, 100.0))

    @unittest.skipIf(getattr(main, "USANDO_PG", False),
                     "pasa por safe_backfill, que clona la base: sólo-SQLite")
    def test_tanda_MIXTA_el_freno_de_tanda_tampoco_toca_al_usuario_SANO(self):
        """Aísla el freno de TANDA, que hasta ahora ningún test probaba.

        ⚠️ POR QUÉ HACE FALTA ESTE CASO. Los otros tests arman 4 usuarios y a los
        4 les hacen borrar 10 de 10: los 4 quedan frenados, así que el salteo
        individual de la pasada 2 los cubre uno por uno y el `return` de la tanda
        **nunca es lo que salva nada**. Sacándolo, la suite quedaba verde.

        Acá hay un usuario que SÍ pasaría el tope (borra 2 de 10) metido en una
        tanda que se aborta. Es el único escenario donde el `return` es lo único
        que impide escribir: sin él, ese usuario se toca mientras el resumen dice
        "no se escribió nada".
        """
        sano = self.uids[0]
        # Al sano le dejamos 8 de sus 10 posiciones (borra 2 → por debajo del piso
        # de 5, así que su plan PASA el tope de usuario).
        def recompute_mixto(clone_conn, uid, **kw):
            if uid == sano:
                clone_conn.execute(
                    "DELETE FROM positions WHERE user_id=? AND asset IN ('ACC0','ACC1')",
                    (uid,))
            else:
                clone_conn.execute("DELETE FROM positions WHERE user_id=?", (uid,))

        original = rb.recompute_user
        rb.recompute_user = recompute_mixto
        try:
            res = rb.safe_backfill(self.conn, self.uids, recalc=lambda *a, **k: None,
                                   apply=True)
        finally:
            rb.recompute_user = original

        self.assertTrue(res["tanda_abortada"], res)
        # 3 frenados de 4 con cambios: pasa el 25% y llega al piso de 3.
        self.assertEqual(len(res["frenados"]), 3, res["frenados"])
        self.assertNotIn(sano, [f["uid"] for f in res["frenados"]])
        self.assertEqual(
            self._posiciones(sano), 10,
            "la tanda se abortó pero igual se le escribió al usuario que pasaba el "
            "tope: falta el corte de la tanda ANTES de la pasada de escritura")

    @unittest.skipIf(getattr(main, "USANDO_PG", False),
                     "pasa por safe_backfill, que clona la base: sólo-SQLite")
    def test_UN_solo_usuario_frenado_no_aborta_la_tanda_pero_igual_se_lo_saltea(self):
        """Aísla el freno POR USUARIO, que tampoco tenía test propio.

        Con UN solo frenado la tanda NO se aborta (hacen falta 3 y más del 25%),
        así que el `continue` de la pasada 2 es lo único que separa a ese usuario
        del DELETE. `TopePorUsuarioTest` prueba la función que decide, pero no que
        `safe_backfill` le haga caso.
        """
        malo = self.uids[0]

        def recompute_uno_malo(clone_conn, uid, **kw):
            if uid == malo:
                clone_conn.execute("DELETE FROM positions WHERE user_id=?", (uid,))
            # los demás quedan igual → sin cambios, no entran en los planes

        original = rb.recompute_user
        rb.recompute_user = recompute_uno_malo
        try:
            res = rb.safe_backfill(self.conn, self.uids, recalc=lambda *a, **k: None,
                                   apply=True)
        finally:
            rb.recompute_user = original

        self.assertFalse(res["tanda_abortada"],
                         "con UN solo frenado la tanda no tiene que abortarse")
        self.assertEqual([f["uid"] for f in res["frenados"]], [malo], res["frenados"])
        self.assertEqual(
            self._posiciones(malo), 10,
            "al usuario frenado le borraron las posiciones igual: la pasada de "
            "escritura no está respetando el tope por usuario")
        msg = " ".join(e["error"] for e in res["errors"])
        self.assertIn("FRENADO POR EL TOPE", msg)

    def test_sin_tope_la_cartera_se_vacia(self):
        """La contraprueba: el comportamiento VIEJO sí vaciaba.

        Es el que le da sentido a los otros. `_ejecutar_plan` es lo que hacía
        `_apply_safe` sin ninguna revisión en el medio.
        """
        uid = self.uids[0]
        borrar = [r["id"] for r in self.conn.execute(
            "SELECT id FROM positions WHERE user_id=?", (uid,)).fetchall()]
        rb._ejecutar_plan(self.conn, uid, borrar, [])
        self.conn.commit()
        self.assertEqual(self._posiciones(uid), 0)


if __name__ == "__main__":
    unittest.main()
