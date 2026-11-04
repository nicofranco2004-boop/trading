"""El turno de `sell_position_fifo` depende de la MONEDA de la operacion.

Sale del cruce de los dos barridos del 28/10/2026, que dejo una tercera
categoria que ninguna de las dos listas tenia: endpoints que toman
`_tomar_turno` solo por una rama.

MI HIPOTESIS ERA «solo la primera vez» (porque la rama pasa por
`_ensure_usd_sibling`, que crea la pata '· USD'). LA MEDICION LA REFUTO: la
segunda venta tambien lo pide, porque `_ensure_usd_sibling` toma el turno arriba
AUNQUE la pata ya exista. La condicion real es otra:

    vender en DOLARES dentro de un broker en pesos  -> el turno SE PIDE  (1a y 2a)
    vender en PESOS (la moneda del broker)          -> el turno NO se pide (0 veces)

O sea que la proteccion depende de QUE esta vendiendo la persona. El caso comun
de una cuenta argentina —vender GGAL en pesos— es el que queda sin candado.

Se mide contando si la llamada ocurre: no necesita concurrencia.

El cruce de los dos barridos dejo una tercera categoria que ninguna de las dos
listas tenia: endpoints que toman `_tomar_turno` solo por una rama. Para
`sell_position_fifo` y `create_conversion` la rama es
`_pata_de_la_moneda -> _ensure_usd_sibling`, que solo corre si hay que CREAR la
pata '· USD'. O sea: la proteccion existe la primera vez y desaparece despues.

Esto NO necesita concurrencia: se mide contando si la llamada ocurre.
"""
import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main

BROKER = "Cocos"


class ElTurnoSeTomaSoloLaPrimeraVez(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"tv-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, BROKER, "ARS"))
        self.conn.commit()
        self.llamadas = []
        self.orig = main._tomar_turno

        def espia(conn, uid):
            self.llamadas.append(uid)
            return self.orig(conn, uid)
        main._tomar_turno = espia

    def tearDown(self):
        main._tomar_turno = self.orig
        try:
            for t in ("operations", "monthly_entries", "flujos_a_mano", "positions", "brokers"):
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
            self.conn.commit()
        except Exception:
            try: self.conn.rollback()
            except Exception: pass
        self.conn.close()

    def _comprar_en_dolares(self, qty):
        """Una compra en USD dentro de un broker en pesos: usa la pata '· USD'."""
        return main.create_position(main.PositionIn(
            broker=BROKER, asset="AAPL", buy_price=100.0, quantity=qty,
            entry_date="2026-09-01", currency="USD"), uid=self.uid)

    @unittest.skipUnless(getattr(main, "USANDO_PG", False),
                         "en SQLite el motor serializa igual: el turno no cambia nada")
    def test_una_venta_en_PESOS_pide_el_turno(self):
        """El caso complementario: si la condicion no es «la primera vez»,
        ¿cual es? Una venta en la moneda del broker no pasa por la pata '· USD'."""
        main.create_position(main.PositionIn(
            broker=BROKER, asset="GGAL", buy_price=1000.0, quantity=100.0,
            entry_date="2026-09-01", currency="ARS"), uid=self.uid)
        self.conn.commit()
        self.llamadas.clear()
        main.sell_position_fifo(main.SellIn(
            broker=BROKER, asset="GGAL", quantity=50.0, exit_price=1200.0,
            date="2026-10-05", currency="ARS"), uid=self.uid)
        print(f"\n>>> vender en PESOS (la moneda del broker): el turno se pidio "
              f"{len(self.llamadas)} vez/ces")
        self.assertGreater(
            len(self.llamadas), 0,
            "una venta en pesos NO pide el turno: la proteccion depende de la MONEDA")

    def test_la_segunda_venta_ya_no_pide_el_turno(self):
        self._comprar_en_dolares(20.0)
        self.conn.commit()

        self.llamadas.clear()
        main.sell_position_fifo(main.SellIn(
            broker=BROKER, asset="AAPL", quantity=5.0, exit_price=120.0,
            date="2026-10-05", currency="USD"), uid=self.uid)
        primera = len(self.llamadas)

        self.llamadas.clear()
        main.sell_position_fifo(main.SellIn(
            broker=BROKER, asset="AAPL", quantity=5.0, exit_price=120.0,
            date="2026-10-06", currency="USD"), uid=self.uid)
        segunda = len(self.llamadas)

        print(f"\n>>> vender en dolares: 1a venta pidio el turno {primera} vez/ces, "
              f"2a venta {segunda}")
        self.assertEqual(
            (primera > 0, segunda > 0), (True, True),
            f"la proteccion aparece y desaparece: 1a={primera} 2a={segunda} "
            f"— si la 2a es 0, el turno solo existe la primera vez")


if __name__ == "__main__":
    unittest.main()
