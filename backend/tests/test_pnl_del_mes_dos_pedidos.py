"""SONDA: la ganancia realizada del mes se suma en Python, sin candado.

`_update_monthly_pnl_realized` (main.py:13746) es la hermana de
`_update_monthly_flow` (13793) — misma tabla, misma fila, 47 lineas al lado. A la
hermana se le aplicaron las dos mitades del arreglo de concurrencia; a esta
ninguna: suma en Python y su INSERT no tiene ON CONFLICT.

Entra por el camino REAL (`main.create_operation`), que es el que decide si
SQLite lo tapa: lo primero que escribe es el INSERT de la operacion.
"""
import os, sys, threading, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main

BROKER = "SondaPnl"
MES = ("2026-10-05", 2026, 10)


def _motor():
    return "PG" if getattr(main, "USANDO_PG", False) else "SQLite"


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"pnl-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, BROKER, "USD"))
        self.conn.commit()

    def tearDown(self):
        try:
            for t in ("operations", "monthly_entries", "positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _fila(self, broker="global"):
        self.conn.rollback()
        return self.conn.execute(
            "SELECT pnl_realized, deposits, capital_final FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=? AND month=?",
            (self.uid, broker, MES[1], MES[2])).fetchone()

    def _en_paralelo(self, trabajos):
        listo = threading.Barrier(len(trabajos))
        errs, lock = [], threading.Lock()

        def correr(fn):
            c = None
            try:
                c = main.get_db()
                listo.wait(timeout=25)
                fn(c)
            except Exception as ex:
                with lock: errs.append(f"{type(ex).__name__}: {str(ex)[:100]}")
            finally:
                if c is not None:
                    try: c.close()
                    except Exception: pass

        hs = [threading.Thread(target=correr, args=(t,)) for t in trabajos]
        [h.start() for h in hs]; [h.join(timeout=60) for h in hs]
        return errs


def _op(pnl):
    def hacer(_c):
        main.create_operation(main.OperationIn(
            date=MES[0], broker=BROKER, asset="AAPL", op_type="Venta",
            pnl_usd=pnl), uid=_UID[0])
    return hacer


_UID = [None]


class DosOperacionesALaVez(Base):
    def setUp(self):
        super().setUp()
        _UID[0] = self.uid
        # La fila del mes YA existe, con una ganancia previa.
        main.create_operation(main.OperationIn(
            date=MES[0], broker=BROKER, asset="MSFT", op_type="Venta",
            pnl_usd=100.0), uid=self.uid)

    def test_dos_resultados_simultaneos_se_suman_los_dos(self):
        antes = float(self._fila()["pnl_realized"] or 0)
        errs = self._en_paralelo([_op(50.0), _op(30.0)])
        f = self._fila()
        got = float(f["pnl_realized"] or 0)
        n_ops = self.conn.execute(
            "SELECT COUNT(*) c FROM operations WHERE user_id=?", (self.uid,)).fetchone()["c"]
        print(f"\n>>> {_motor()} dos-ops: antes={antes} ahora={got} "
              f"esperado={antes+80} ops_en_la_base={n_ops} err={errs}")
        self.assertAlmostEqual(
            got, antes + 80, places=2,
            msg=f"se perdio una ganancia: {got} en vez de {antes+80} "
                f"(hay {n_ops} operaciones en el historial)")


class DepositoYOperacionALaVez(Base):
    def setUp(self):
        super().setUp()
        _UID[0] = self.uid
        main.create_operation(main.OperationIn(
            date=MES[0], broker=BROKER, asset="MSFT", op_type="Venta",
            pnl_usd=100.0), uid=self.uid)

    def test_el_deposito_no_desaparece_del_capital_final(self):
        """El efecto cruzado: la hermana suma el deposito EN LA BASE y esta
        funcion reescribe capital_final con el deposits que LEYO."""
        def deposito(_c):
            # El camino REAL: el endpoint. Llamar a `_update_monthly_flow`
            # directo deja la suma SIN su detalle en `flujos_a_mano`, y el
            # recalculo posterior la borra -> rojo falso (me pasó).
            main.cash_flow(main.CashFlowIn(
                broker_name=BROKER, direction="deposit", amount=1000.0,
                date=MES[0]), uid=self.uid)
        errs = self._en_paralelo([deposito, _op(50.0)])
        f = self._fila()
        dep = float(f["deposits"] or 0); cap = float(f["capital_final"] or 0)
        pnl = float(f["pnl_realized"] or 0)
        print(f"\n>>> {_motor()} cruzado: deposits={dep} pnl={pnl} capital_final={cap} err={errs}")
        self.assertAlmostEqual(
            cap, dep + pnl, places=2,
            msg=f"capital_final={cap} no refleja deposits={dep} + pnl={pnl} "
                f"(diferencia {dep + pnl - cap})")


class PrimeraOperacionDelMesALaVez(Base):
    def setUp(self):
        super().setUp()
        _UID[0] = self.uid

    def test_dos_primeras_del_mes_no_dan_500(self):
        """La otra mitad sin propagar: el INSERT del `else` no tiene ON CONFLICT,
        y hay UNIQUE (user_id, year, month, broker) esperandolo."""
        errs = self._en_paralelo([_op(40.0), _op(60.0)])
        f = self._fila()
        got = float(f["pnl_realized"] or 0) if f else 0.0
        # ¿Se perdió la OPERACIÓN o sólo el total del mes? No es lo mismo:
        # el total lo puede rearmar un recálculo; la operación no vuelve.
        ops = self.conn.execute(
            "SELECT pnl_usd FROM operations WHERE user_id=? ORDER BY id",
            (self.uid,)).fetchall()
        suma_ops = sum(float(o["pnl_usd"] or 0) for o in ops)
        filas = self.conn.execute(
            "SELECT broker, pnl_realized FROM monthly_entries WHERE user_id=? "
            "ORDER BY broker", (self.uid,)).fetchall()
        print(f"\n>>> {_motor()} mes-nuevo: pnl_global={got} esperado=100 | "
              f"operaciones={[float(o['pnl_usd'] or 0) for o in ops]} suma={suma_ops} | "
              f"filas={[(r['broker'], float(r['pnl_realized'] or 0)) for r in filas]} | "
              f"err={errs}")
        self.assertEqual(errs, [], f"alguien revento: {errs}")
        self.assertAlmostEqual(got, 100.0, places=2, msg=f"pnl={got} en vez de 100")


class VentaYOperacionALaVez(Base):
    """La otra puerta: `POST /api/positions/sell` tambien llama a
    `_update_monthly_pnl_realized`, y despues de ella NO corre
    `_recalc_pnl_realized_from_ops` (solo `_repair_monthly_chain`)."""

    def setUp(self):
        super().setUp()
        _UID[0] = self.uid
        # Un lote para vender, y la fila del mes ya creada.
        self.pos = main.create_position(main.PositionIn(
            broker=BROKER, asset="AAPL", buy_price=100.0, quantity=10.0,
            entry_date="2026-09-01"), uid=self.uid)
        main.create_operation(main.OperationIn(
            date=MES[0], broker=BROKER, asset="MSFT", op_type="Venta",
            pnl_usd=100.0), uid=self.uid)

    def test_una_venta_y_una_operacion_a_la_vez(self):
        antes = float(self._fila()["pnl_realized"] or 0)

        def venta(_c):
            main.sell_position_fifo(main.SellIn(
                broker=BROKER, asset="AAPL", quantity=5.0, exit_price=120.0,
                date=MES[0]), uid=self.uid)

        errs = self._en_paralelo([venta, _op(50.0)])
        f = self._fila()
        got = float(f["pnl_realized"] or 0)
        # La venta deja +100 (5 x (120-100)) y la operacion +50.
        print(f"\n>>> {_motor()} venta+op: antes={antes} ahora={got} "
              f"esperado={antes+150} err={errs}")
        self.assertAlmostEqual(
            got, antes + 150, places=2,
            msg=f"se perdio una ganancia: {got} en vez de {antes+150}")


if __name__ == "__main__":
    unittest.main()
