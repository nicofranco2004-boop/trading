"""El turno de la caja puede dar un bloqueo mutuo (auditoría 23/10/2026).

QUÉ MIDE. `efectivo.tomar_saldo` pide el turno por usuario **sólo cuando la caja
todavía no existe** (el UPDATE no tocó ninguna fila). Entonces una transacción
que toca DOS brokers toma los candados en distinto orden según cuál de las dos
cajas exista:

    broker con caja   → candado de FILA (el UPDATE que no cambia nada)
    broker sin caja   → candado de TURNO (pg_advisory_xact_lock)

Dos pedidos del MISMO usuario que recorren los dos brokers en orden opuesto se
esperan cruzados y Postgres corta con `deadlock detected` → 500 al usuario.
Medido 3 de 3, y el detalle de Postgres nombra el candado nuevo:
`advisory lock [16388,823471003,1,2]`.

ES REAL Y ES RARO. Hace falta: el mismo usuario, dos pedidos simultáneos, los
mismos dos brokers, en orden opuesto, y uno de los dos sin caja. El par realista
es un broker en pesos (su caja la crea `/api/brokers` al nacer) y su sub-broker
'<Padre> · USD' (que nace SIN caja): un dividendo acredita primero los dólares y
después descuenta la comisión en pesos (`dividendos.py:398`), y una conversión
va al revés.

NO ERA UNA REGRESIÓN A FAVOR DEL BUG VIEJO: sin el turno, estos dos pedidos
dejaban DOS cajas y la plata de una desaparecía. Un 500 ruidoso es mejor que
plata invisible. Pero se tienen las dos cosas, y así quedó: **el turno se pide
SIEMPRE y ANTES del UPDATE** —no sólo cuando la caja falta—, así que todos los
pedidos toman el mismo candado primero y no hay orden que invertir.

ESTE TEST ES EL GUARDIÁN DE ESO. Falla si alguien vuelve a mover el turno
adentro del `if` del UPDATE (que es como estaba escrito al principio, porque
parecía de sentido común pedirlo sólo cuando hace falta). Se verificó que
distingue: con el turno adentro del `if`, 3 de 3 con `deadlock detected`; con el
turno siempre y primero, 3 de 3 sin error."""
import os, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main, efectivo as _ef


class OrdenDeCandados(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"dl-{os.urandom(4).hex()}@rendi.test", "x")).lastrowid
        for b in ("ConCaja", "SinCaja"):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, b, "ARS"))
        # ConCaja YA tiene fila de efectivo (la crea /api/brokers en la vida real);
        # SinCaja no (así nacen los sub-brokers '· USD' y lo del importador).
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity) "
            "VALUES (?,?, 'ARS', 1, 1000, 0)", (self.uid, "ConCaja"))
        self.conn.commit()

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

    @unittest.skipUnless(getattr(main, "USANDO_PG", False),
                         "en SQLite el motor serializa: no hay orden que invertir")
    def test_dos_pedidos_en_ORDEN_OPUESTO(self):
        listo = threading.Barrier(2); errs = []; lock = threading.Lock()

        def pedir(orden):
            c = None
            try:
                c = main.get_db()
                listo.wait(timeout=20)
                with c:
                    for brk, delta in orden:
                        _ef.mover(c, self.uid, brk, delta)
            except Exception as ex:
                with lock: errs.append(f"{type(ex).__name__}: {str(ex)[:120]}")
            finally:
                if c is not None:
                    try: c.close()
                    except Exception: pass

        h = [threading.Thread(target=pedir, args=(o,)) for o in (
            [("ConCaja", -10.0), ("SinCaja", 10.0)],
            [("SinCaja", 5.0), ("ConCaja", -5.0)])]
        [x.start() for x in h]; [x.join(timeout=60) for x in h]
        self.assertEqual(errs, [], f"reventó: {errs}")


if __name__ == "__main__":
    unittest.main()
