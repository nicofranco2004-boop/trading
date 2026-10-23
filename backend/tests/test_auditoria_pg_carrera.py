"""AUDITORÍA 23/10/2026 — intentar ROMPER los arreglos de concurrencia.

No confirma nada: aprieta. Cada test dice qué se espera y, cuando falla,
imprime el número REAL para que no haya que deducirlo.

⚠️ Contra SQLite todos pasan con y sin los arreglos (el motor serializa).
Sólo miden algo con DATABASE_URL puesta.
"""
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
import efectivo as _ef
from ai import quota as _q

PG = bool(getattr(main, "USANDO_PG", False))


def _en_paralelo(n, trabajo):
    """Corre `trabajo(i, conn)` en n hilos que arrancan JUNTOS, con la conexión
    YA ABIERTA antes de la barrera: si se abriera después, los hilos entrarían
    escalonados por el costo de conectar y la carrera no se daría.

    Devuelve (resultados, errores) — los errores NO se tragan: son dato, y una
    medición en la que todos dicen lo mismo es un instrumento roto, no un
    hallazgo."""
    listo = threading.Barrier(n)
    res, errs = [], []
    cerrojo = threading.Lock()

    def correr(i):
        c = None
        try:
            c = main.get_db()
            listo.wait(timeout=30)
            r = trabajo(i, c)
            with cerrojo:
                res.append(r)
        except Exception as ex:                       # noqa: BLE001
            with cerrojo:
                errs.append(f"{type(ex).__name__}: {ex}")
        finally:
            if c is not None:
                try: c.close()
                except Exception: pass

    hilos = [threading.Thread(target=correr, args=(i,)) for i in range(n)]
    [h.start() for h in hilos]
    [h.join(timeout=90) for h in hilos]
    return res, errs


def _nuevo_user(conn, etiqueta):
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (f"{etiqueta}-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
    conn.commit()
    return uid


# ─────────────────────────────────────────────────────────────────────────────
# 1 · El turno de DOS claves: ¿la sentencia existe en Postgres?
# ─────────────────────────────────────────────────────────────────────────────
class TurnoDeDosClaves(unittest.TestCase):
    """`pg_advisory_xact_lock(a, b)` sólo existe para int4. Si psycopg manda los
    parámetros como bigint o como numeric, Postgres contesta «function does not
    exist» y el camino de la caja revienta. Es la forma NUEVA del commit."""

    def test_el_turno_de_dos_claves_corre(self):
        import pgsesion as _ps
        c = main.get_db()
        try:
            _ps.turno_exclusivo(c, _ps.TURNO_CAJA_DEL_BROKER, 12345)
            _ps.turno_exclusivo(c, _ps.TURNO_TOPE_TRIALS_DEL_MES)
            c.rollback()
        finally:
            c.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2 · El tope de la cuota de IA, con MÁS de dos pedidos (foco del informe)
# ─────────────────────────────────────────────────────────────────────────────
class TopeDeCuotaIABajoCarga(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "cuota")

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM ai_usage_daily WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _usadas(self, col="chat_count"):
        return self.conn.execute(
            f"SELECT COALESCE(SUM({col}),0) s FROM ai_usage_daily WHERE user_id=?",
            (self.uid,)).fetchone()["s"]

    def test_chat_con_la_cuota_VACIA_y_diez_pedidos(self):
        """Free tiene 1 consulta. Diez a la vez tienen que dejar pasar UNA."""
        def pedir(_i, c):
            ok, _ = _q.reserve_chat(c, self.uid, tier_override="free")
            return bool(ok)

        res, errs = _en_paralelo(10, pedir)
        pasaron = sum(1 for r in res if r)
        self.conn.rollback()
        self.assertEqual(
            (pasaron, self._usadas()), (1, 1),
            f"tope 1: dijeron OK {pasaron} y quedaron {self._usadas()} "
            f"consumidas. errores={errs}")

    def test_chat_con_la_cuota_CASI_llena(self):
        """Pro: lleno hasta tope−1 y pido N a la vez. Tiene que entrar UNO.
        Éste es el caso que el informe midió con sólo dos pedidos."""
        tope = _q.limites_del_usuario(self.conn, self.uid, "pro")["chat_per_week"]
        self.assertTrue(tope and tope > 1, f"tope raro: {tope}")
        from datetime import date
        self.conn.execute(
            "INSERT INTO ai_usage_daily (user_id, date, chat_count, cost_usd_cents) "
            "VALUES (?,?,?,0)", (self.uid, date.today().isoformat(), tope - 1))
        self.conn.commit()

        def pedir(_i, c):
            ok, _ = _q.reserve_chat(c, self.uid, tier_override="pro")
            return bool(ok)

        res, errs = _en_paralelo(8, pedir)
        pasaron = sum(1 for r in res if r)
        self.conn.rollback()
        self.assertEqual(
            (pasaron, self._usadas()), (1, tope),
            f"quedaba 1 lugar de {tope}: dijeron OK {pasaron} y quedaron "
            f"{self._usadas()} consumidas. errores={errs}")

    def test_analisis_con_la_cuota_vacia(self):
        """El hermano del chat, mismo patrón, columna distinta. Free = 1."""
        def pedir(_i, c):
            ok, _ = _q.reserve_analysis(c, self.uid, tier_override="free")
            return bool(ok)

        res, errs = _en_paralelo(8, pedir)
        pasaron = sum(1 for r in res if r)
        self.conn.rollback()
        self.assertEqual(
            (pasaron, self._usadas("analyses_count")), (1, 1),
            f"tope 1: OK={pasaron}, consumidas={self._usadas('analyses_count')}. "
            f"errores={errs}")


class TopeDeCuotaIAUsuariosDistintos(unittest.TestCase):
    """Tres usuarios pidiendo a la vez. Cada uno tiene que gastar SU tope: ni
    más (el turno no alcanza) ni menos (el turno los hace esperar de más)."""

    def setUp(self):
        self.conn = main.get_db()
        self.uids = [_nuevo_user(self.conn, "multi") for _ in range(3)]

    def tearDown(self):
        try:
            for u in self.uids:
                self.conn.execute("DELETE FROM ai_usage_daily WHERE user_id=?", (u,))
                self.conn.execute("DELETE FROM users WHERE id=?", (u,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def test_cada_uno_gasta_lo_suyo(self):
        def pedir(i, c):
            uid = self.uids[i % len(self.uids)]
            ok, _ = _q.reserve_chat(c, uid, tier_override="free")
            return (uid, bool(ok))

        res, errs = _en_paralelo(12, pedir)
        self.conn.rollback()
        por_user = {}
        for uid, ok in res:
            por_user[uid] = por_user.get(uid, 0) + (1 if ok else 0)
        quedaron = {u: self.conn.execute(
            "SELECT COALESCE(SUM(chat_count),0) s FROM ai_usage_daily WHERE user_id=?",
            (u,)).fetchone()["s"] for u in self.uids}
        self.assertEqual(
            (sorted(por_user.values()), sorted(quedaron.values())),
            ([1, 1, 1], [1, 1, 1]),
            f"cada uno tenía 1: OK por usuario={por_user}, consumidas={quedaron}. "
            f"errores={errs}")


# ─────────────────────────────────────────────────────────────────────────────
# 3 · La caja de efectivo: ¿queda UNA sola?
# ─────────────────────────────────────────────────────────────────────────────
class PrimerDepositoSimultaneo(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "caja")
        self.broker = "BrokerCarrera"
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.broker, "ARS"))
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM positions WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM brokers WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def test_cinco_primeros_depositos_dejan_UNA_caja(self):
        montos = [300.0, 200.0, 100.0, 50.0, 25.0]

        def depositar(i, c):
            with c:
                _ef.mover(c, self.uid, self.broker, montos[i])
            return montos[i]

        res, errs = _en_paralelo(len(montos), depositar)
        self.conn.rollback()
        filas = self.conn.execute(
            "SELECT id, invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1 "
            "ORDER BY id", (self.uid, self.broker)).fetchall()
        saldos = [float(f["invested"] or 0) for f in filas]
        self.assertEqual(
            len(filas), 1,
            f"tenía que quedar UNA caja y quedaron {len(filas)} con saldos {saldos}. "
            f"errores={errs}")
        self.assertAlmostEqual(
            saldos[0], sum(montos), places=6,
            msg=f"la caja tenía que tener {sum(montos)} y tiene {saldos[0]}")


# ─────────────────────────────────────────────────────────────────────────────
# 4 · La fila del mes: el ON CONFLICT tiene que SUMAR igual que el UPDATE
# ─────────────────────────────────────────────────────────────────────────────
_COLS_MES = ("deposits", "withdrawals", "manual_deposits", "manual_withdrawals",
             "manual_deposits_native", "manual_withdrawals_native",
             "pnl_realized", "pnl_unrealized", "capital_inicio", "capital_final")


class FilaDelMesDosCaminos(unittest.TestCase):
    """El commit dice que el ON CONFLICT «suma exactamente lo mismo» que la rama
    de «la fila ya existe». Acá se construye la MISMA fila por los dos caminos y
    se comparan las diez columnas, una por una."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "mes")

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _fila(self, broker):
        r = self.conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
            (self.uid, broker, 2026, 7)).fetchone()
        return {k: r[k] for k in _COLS_MES}

    MANUALES_NULL = False

    def _sembrar(self, broker):
        """Una fila ya existente, con pnl y capital_inicio puestos a mano.

        Con MANUALES_NULL, las cuatro columnas de lo manual quedan en NULL: el
        ON CONFLICT las pasa por COALESCE(...,0)+0 y la rama del UPDATE no las
        toca, así que NULL y 0 son el único lugar donde los dos caminos podrían
        no dar lo mismo."""
        man = "NULL, NULL, NULL, NULL" if self.MANUALES_NULL else "0, 0, 0, 0"
        self.conn.execute(
            f"""INSERT INTO monthly_entries
                 (user_id, year, month, broker, deposits, withdrawals,
                  pnl_realized, pnl_unrealized, capital_inicio, capital_final,
                  manual_deposits, manual_withdrawals,
                  manual_deposits_native, manual_withdrawals_native)
               VALUES (?,?,?,?,?,?,?,?,?,?, {man})""",
            (self.uid, 2026, 7, broker, 10.0, 0.0, 7.5, 3.25, 1000.0, 1010.0))
        self.conn.commit()

    def _correr(self, broker, **kw):
        with self.conn:
            main._update_monthly_flow(self.conn, self.uid, broker, 2026, 7, **kw)

    def _por_los_dos_caminos(self, **kw):
        """Devuelve (lo_que_da_el_UPDATE, lo_que_da_el_ON_CONFLICT)."""
        self._sembrar("ViaUpdate")
        self._correr("ViaUpdate", **kw)

        # El camino del ON CONFLICT: la fila se siembra DESPUÉS de que
        # `_update_monthly_flow` leyó «no existe» — es justo la carrera.
        broker = "ViaConflict"
        fn = main._update_monthly_flow
        import types
        orig_select = main._capital_inicio_de_fila_nueva

        def siembra_en_el_medio(conn, uid, brk, year, month):
            v = orig_select(conn, uid, brk, year, month)
            if brk == broker and not getattr(siembra_en_el_medio, "hecho", False):
                siembra_en_el_medio.hecho = True
                self._sembrar(broker)
            return v

        main._capital_inicio_de_fila_nueva = siembra_en_el_medio
        try:
            self._correr(broker, **kw)
        finally:
            main._capital_inicio_de_fila_nueva = orig_select
        return self._fila("ViaUpdate"), self._fila(broker)

    def test_deposito_a_mano_con_nativo(self):
        a, b = self._por_los_dos_caminos(
            direction="deposit", amount=200.0, is_manual=True, native_amount=2.0)
        self.assertEqual(a, b, f"UPDATE={a}\nON CONFLICT={b}")

    def test_retiro_a_mano_con_nativo(self):
        a, b = self._por_los_dos_caminos(
            direction="withdraw", amount=120.0, is_manual=True, native_amount=1.5)
        self.assertEqual(a, b, f"UPDATE={a}\nON CONFLICT={b}")

    def test_deposito_importado_sin_nativo(self):
        a, b = self._por_los_dos_caminos(
            direction="deposit", amount=90.0, is_manual=False)
        self.assertEqual(a, b, f"UPDATE={a}\nON CONFLICT={b}")

    def test_deposito_a_mano_sin_nativo(self):
        a, b = self._por_los_dos_caminos(
            direction="deposit", amount=75.0, is_manual=True, native_amount=None)
        self.assertEqual(a, b, f"UPDATE={a}\nON CONFLICT={b}")


class FilaDelMesSimultanea(unittest.TestCase):
    """Cinco depósitos a la vez sobre un mes que no tiene fila: ni 500 ni plata
    perdida."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "mesrace")

    def tearDown(self):
        try:
            self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def test_cinco_a_la_vez_suman_todo(self):
        montos = [100.0, 200.0, 300.0, 50.0, 25.0]

        def flujo(i, c):
            with c:
                main._update_monthly_flow(c, self.uid, "global", 2026, 8,
                                          direction="deposit", amount=montos[i],
                                          is_manual=True, native_amount=montos[i])
            return montos[i]

        res, errs = _en_paralelo(len(montos), flujo)
        self.conn.rollback()
        filas = self.conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? AND broker='global' "
            "AND year=2026 AND month=8", (self.uid,)).fetchall()
        self.assertEqual(len(filas), 1,
                         f"tenía que quedar UNA fila y quedaron {len(filas)}. errores={errs}")
        f = filas[0]
        self.assertEqual(len(errs), 0, f"nadie tenía que reventar: {errs}")
        self.assertAlmostEqual(float(f["deposits"]), sum(montos), places=6,
                               msg=f"deposits={f['deposits']} (esperado {sum(montos)})")
        self.assertAlmostEqual(float(f["manual_deposits"]), sum(montos), places=6,
                               msg=f"manual_deposits={f['manual_deposits']}")
        self.assertAlmostEqual(float(f["manual_deposits_native"]), sum(montos), places=6,
                               msg=f"manual_deposits_native={f['manual_deposits_native']}")


class FilaDelMesConNullLaDiferenciaConocida(FilaDelMesDosCaminos):
    """CON LAS COLUMNAS MANUALES EN NULL los dos caminos **no** dan lo mismo, y
    esto fija exactamente en qué: el ON CONFLICT las pasa por
    `COALESCE(col,0) + 0` y deja **0**, mientras que la rama del UPDATE no las
    toca y las deja en **NULL**.

    No le pasa a nadie hoy: las cuatro columnas nacen con `DEFAULT 0` en los dos
    esquemas (en SQLite entraron por `ALTER TABLE … ADD COLUMN … DEFAULT 0`, que
    rellena las filas viejas con 0, no con NULL) y ningún lector distingue NULL
    de 0 — todos leen con COALESCE. Medido en las dos bases: la diferencia es la
    misma, así que no es cosa de Postgres sino de la sentencia.

    Se deja fijado y no borrado: si mañana la diferencia CRECE —si se cuela una
    columna de plata o un `capital_*`— este test lo dice. Si alguien iguala los
    dos caminos, también (y entonces se borra esta clase)."""
    MANUALES_NULL = True

    # Las únicas columnas donde se acepta que difieran, y sólo NULL ↔ 0.
    DIFERENCIA_ACEPTADA = ("manual_deposits", "manual_withdrawals",
                           "manual_deposits_native", "manual_withdrawals_native")

    def assertEqual(self, a, b, msg=None):          # noqa: N802
        """Para los cuatro tests heredados: igual en todo salvo la diferencia
        conocida, y ahí sólo se acepta NULL en el UPDATE contra 0.0 en el
        ON CONFLICT."""
        if not (isinstance(a, dict) and isinstance(b, dict)):
            return super().assertEqual(a, b, msg)
        inesperadas = []
        for col in a:
            if a[col] == b[col]:
                continue
            if col in self.DIFERENCIA_ACEPTADA and a[col] is None and b[col] == 0.0:
                continue
            inesperadas.append(f"{col}: UPDATE={a[col]!r} ON CONFLICT={b[col]!r}")
        super().assertEqual(
            inesperadas, [],
            "con las manuales en NULL aparecieron diferencias NUEVAS (la "
            "conocida es NULL↔0 en las cuatro manuales):\n  "
            + "\n  ".join(inesperadas))


# ─────────────────────────────────────────────────────────────────────────────
# 5 · El tope de brokers del plan: el MISMO patrón, armado de otra forma
# ─────────────────────────────────────────────────────────────────────────────
class TopeDeBrokersDelPlan(unittest.TestCase):
    """El cuarto tope de la familia, y el que el grep no podía encontrar.

    Los tres topes del informe se hacen cumplir DENTRO de una sentencia
    (`INSERT … WHERE (SELECT COUNT…) < tope`), así que un grep de ese texto los
    encuentra. Éste se hace cumplir en DOS pasos y en Python:

        allowed, info = plan.check_broker_quota(conn, uid)   # cuenta
        if not allowed: 403
        conn.execute("INSERT INTO brokers …")                # escribe

    Es el mismo bug con otra cara: entre contar y escribir entra cualquiera. En
    SQLite no se notaba —el motor serializa— y en Postgres cada transacción lee
    su propia foto.

    Medido el 23/10/2026 con tope 1 (Free) y cinco pedidos a la vez:
        Postgres  → quedaron 2 y 4 brokers (dos corridas)
        SQLite    → quedó 1 y 1

    Qué se escapa: la pared del plan. Un Free con tope 1 se queda con 4 brokers.
    No gasta plata de proveedor como la cuota de IA, pero es el paywall.

    Corre el endpoint de verdad (`main.create_broker`), no una copia."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "topebrk")
        from ai import plan as _plan
        self.tope = _plan.PLAN_LIMITS["free"]["brokers_max"]

    def tearDown(self):
        try:
            for t in ("positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def test_free_con_tope_1_y_cinco_pedidos(self):
        listo = threading.Barrier(5)
        aceptados, cerrojo = [], threading.Lock()

        def crear(i):
            try:
                listo.wait(timeout=30)
                main.create_broker(main.BrokerIn(name=f"Carrera{i}", currency="ARS"),
                                   uid=self.uid)
                with cerrojo:
                    aceptados.append(i)
            except Exception:
                pass          # un 403 del tope o un choque del índice único

        hilos = [threading.Thread(target=crear, args=(i,)) for i in range(5)]
        [h.start() for h in hilos]
        [h.join(timeout=60) for h in hilos]
        self.conn.rollback()
        quedaron = self.conn.execute(
            "SELECT COUNT(*) c FROM brokers WHERE user_id=?", (self.uid,)).fetchone()["c"]
        self.assertLessEqual(
            quedaron, self.tope,
            f"el tope del plan es {self.tope} y quedaron {quedaron} brokers "
            f"({len(aceptados)} pedidos aceptados)")


if __name__ == "__main__":
    unittest.main()
