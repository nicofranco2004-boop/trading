"""SONDA: borrar un deposito cargado a mano mientras entra un retiro.

El freno `_frenar_si_la_plata_del_deposito_no_esta` (main.py:19420) existe por un
caso que Nico vio en la app el 2026-10-10: efectivo en -$990.000 con la compra
viva. Su docstring dice «Va ANTES de la primera escritura: si frena, no se movio
nada» -- y eso es cierto, pero no alcanza: entre el freno y el debito corre
`_foto_contable`, que el propio codigo mide en 0,8-1,65 s.

El turno que se toma antes (`_tomar_turno`, main.py:18448) es
`UPDATE users SET tier=tier`: en SQLite toma la base ENTERA y serializa de
verdad; en Postgres traba SOLO la fila de ese usuario en `users`, y
`/api/cash/flow` no la escribe nunca.

La ventana se FUERZA con un handshake para que la medicion no dependa del
scheduler. La ventana es real y esta medida en produccion por el propio codigo;
lo que se fuerza es CUANDO cae el otro pedido, no que exista.
"""
import os, sys, threading, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main

BROKER = "IOL"
MONTO = 1_000_000.0
DIA = "2026-10-05"


def _motor():
    return "PG" if getattr(main, "USANDO_PG", False) else "SQLite"


class BorrarDepositoMientrasEntraUnRetiro(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"dep-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, BROKER, "ARS"))
        self.conn.commit()
        # El deposito, por el camino real.
        main.cash_flow(main.CashFlowIn(broker_name=BROKER, direction="deposit",
                                       amount=MONTO, date=DIA), uid=self.uid)
        self.fid = self.conn.execute(
            "SELECT id FROM flujos_a_mano WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (self.uid,)).fetchone()["id"]
        self.conn.commit()

    def tearDown(self):
        try:
            for t in ("flujos_a_mano", "monthly_entries", "positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _saldo(self):
        self.conn.rollback()
        f = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1 "
            "ORDER BY id LIMIT 1", (self.uid, BROKER)).fetchone()
        return float(f["invested"] or 0) if f else 0.0

    def test_el_saldo_no_queda_en_negativo(self):
        decidio = threading.Event()      # A ya paso el freno
        retiro_listo = threading.Event() # B termino
        estado = {}
        import time as _t; t0 = _t.monotonic()

        original = main._frenar_si_la_plata_del_deposito_no_esta

        def freno_con_ventana(conn, uid, broker, monto):
            original(conn, uid, broker, monto)       # el freno REAL
            estado['t_freno'] = round(_t.monotonic() - t0, 2)
            decidio.set()                            # A decidio: la ventana se abre
            retiro_listo.wait(timeout=20)            # cae el otro pedido acá
            estado['t_sigue'] = round(_t.monotonic() - t0, 2)

        def borrar():
            try:
                main._frenar_si_la_plata_del_deposito_no_esta = freno_con_ventana
                main.delete_movement(f"mf-{self.fid}", uid=self.uid)
                estado["borrado"] = "ok"
            except Exception as ex:
                estado["borrado"] = f"{type(ex).__name__}: {str(ex)[:70]}"
            finally:
                main._frenar_si_la_plata_del_deposito_no_esta = original

        def retirar():
            try:
                decidio.wait(timeout=20)
                main.cash_flow(main.CashFlowIn(broker_name=BROKER, direction="withdraw",
                                               amount=MONTO, date=DIA), uid=self.uid)
                estado["retiro"] = "ok"
                estado["t_retiro"] = round(_t.monotonic() - t0, 2)
            except Exception as ex:
                estado["retiro"] = f"{type(ex).__name__}: {str(ex)[:70]}"
            finally:
                retiro_listo.set()

        def vigia():
            """Durante la ventana, que la BASE diga quien espera y por que."""
            if not getattr(main, "USANDO_PG", False): return
            decidio.wait(timeout=20); _t.sleep(3)
            import psycopg, os as _os
            try:
                with psycopg.connect(_os.environ["DATABASE_URL"]) as c:
                    filas = c.execute("""
                        SELECT pid, state, wait_event_type, wait_event,
                               left(query, 90) AS q
                          FROM pg_stat_activity
                         WHERE datname = current_database()
                           AND pid <> pg_backend_pid()
                         ORDER BY pid""").fetchall()
                    estado["pg"] = [
                        f"pid{r[0]} {r[1]} wait={r[2]}/{r[3]} :: {(r[4] or '').strip()[:80]}"
                        for r in filas]
            except Exception as ex:
                estado["pg"] = [f"no pude mirar: {type(ex).__name__}: {str(ex)[:60]}"]

        hs = [threading.Thread(target=borrar), threading.Thread(target=retirar),
              threading.Thread(target=vigia)]
        [h.start() for h in hs]; [h.join(timeout=40) for h in hs]
        saldo = self._saldo()
        print(f"\n>>> {_motor()}: saldo_final={saldo:,.2f} | borrado={estado.get('borrado')} "
              f"| retiro={estado.get('retiro')} | t_freno={estado.get('t_freno')}s "
              f"t_retiro={estado.get('t_retiro')}s t_sigue={estado.get('t_sigue')}s")
        for l in (estado.get("pg") or []):
            print(f">>>    pg_stat_activity: {l}")
        self.assertGreaterEqual(
            saldo, -0.005,
            f"el efectivo quedo en {saldo:,.2f} — el freno existe para impedir "
            f"exactamente esto (borrado={estado.get('borrado')}, retiro={estado.get('retiro')})")


if __name__ == "__main__":
    unittest.main()
