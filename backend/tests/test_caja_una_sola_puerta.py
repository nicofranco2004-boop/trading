"""La caja de efectivo: leerla toma el turno, y crearla tiene UNA sola puerta.

🔴 LOS DOS BUGS QUE VIGILA, los dos de plata y los dos de la misma familia: leer
para decidir y escribir después.

1 · LEER EL SALDO SIN EL TURNO. `efectivo.caja()` decía en su docstring «para
    leer el saldo VIGENTE, llamar antes a `tomar_saldo`» y lo dejaba en manos
    del que llamara. **2 de los 4 que la llamaban no lo hacían.** Uno de esos
    dos decide si se puede borrar un depósito cargado a mano
    (`main._frenar_si_la_plata_del_deposito_no_esta`): leía el saldo, decidía
    que alcanzaba, y 50 líneas después debitaba permitiendo negativo. En el
    medio corre `_foto_contable`, que el propio código mide en 0,8 a 1,65
    segundos. Un retiro por `/api/cash/flow` en esa ventana dejaba el efectivo
    en rojo con la compra viva y el capital aportado en 0 — el estado que esa
    función existe para impedir y que Nico vio en la app el 10/10/2026.

    Y no lo tapaba el turno de escritura que el borrado toma antes
    (`UPDATE users SET tier=tier`): en SQLite eso agarra la base entera, pero en
    Postgres sólo la fila de `users`, y `/api/cash/flow` no la escribe nunca.

2 · TRES PUERTAS PARA CREAR LA CAJA, dos de ellas leyendo primero. `positions`
    **no tiene ningún índice único** (verificado en los dos esquemas), así que
    nada abajo rechaza una segunda fila de caja. Dos de las tres puertas estaban
    tapadas por el `UNIQUE(user_id, name)` de `brokers` —comprobado en vivo:
    SQLite rechaza el broker duplicado—, pero la del importador NO: ahí el
    sibling '· USD' ya existe, así que no hay nada que frene al que llega
    segundo. Consecuencia: dos filas de caja, y como todo lee «la más vieja»
    (`ORDER BY id LIMIT 1`), la plata de la segunda no la mueve nadie nunca más.

CÓMO SE MIDE CADA COSA, porque son dos técnicas distintas a propósito:
· El turno se mide por su EFECTO en `pg_locks`, no leyendo el código. Un test
  que comprueba que el código dice `tomar_saldo` pasa igual si ese `tomar_saldo`
  dejó de tomar nada.
· La puerta única se mide con la carrera de verdad: cinco pedidos a la vez.
  Contra SQLite esto pasa con y sin el arreglo (el motor serializa), y está
  dicho acá para que nadie lea ese verde como prueba.
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
import pgsesion as _ps

CON_POSTGRES = bool(getattr(main, "USANDO_PG", False))


def _nuevo_user(conn, etiqueta):
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
        (f"{etiqueta}-{os.urandom(5).hex()}@rendi.test", "x")).lastrowid
    conn.commit()
    return uid


class LeerLaCajaTomaElTurno(unittest.TestCase):
    """Que `caja()` deje el turno TOMADO, medido en `pg_locks`."""

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "cajaturno")
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "IOL", "ARS"))
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

    @unittest.skipUnless(CON_POSTGRES, "el candado de aviso sólo existe en Postgres")
    def test_despues_de_leer_la_caja_el_turno_esta_tomado(self):
        _ef.caja(self.conn, self.uid, "IOL")
        fila = self.conn.execute(
            "SELECT COUNT(*) AS n FROM pg_locks "
            " WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            "   AND classid = ? AND objid = ?",
            (_ps.TURNO_CAJA_DEL_BROKER, self.uid)).fetchone()
        self.assertEqual(
            int(fila["n"]), 1,
            "leer la caja NO dejó el turno tomado: el que decide con ese saldo "
            "puede estar leyendo un número que otro pedido ya cambió")

    @unittest.skipUnless(CON_POSTGRES, "el candado de aviso sólo existe en Postgres")
    def test_el_turno_es_por_usuario_y_no_por_broker(self):
        """Dos brokers del MISMO usuario comparten turno (es la misma clave), y
        eso es a propósito: así una transacción que toca dos brokers no puede
        tomar los candados en distinto orden y trabarse con otra al revés.
        Si alguien lo cambia a «un turno por broker», esto se pone rojo."""
        _ef.caja(self.conn, self.uid, "IOL")
        _ef.caja(self.conn, self.uid, "Otro")
        fila = self.conn.execute(
            "SELECT COUNT(DISTINCT objid) AS n FROM pg_locks "
            " WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            "   AND classid = ?", (_ps.TURNO_CAJA_DEL_BROKER,)).fetchone()
        self.assertEqual(int(fila["n"]), 1,
                         "el turno de la caja dejó de ser por usuario")


class CrearLaCajaTieneUnaSolaPuerta(unittest.TestCase):
    """La carrera de verdad: cinco pedidos pidiendo la caja del mismo broker.

    ⚠️ Contra SQLite pasa con y sin el arreglo. Sólo mide algo con DATABASE_URL.
    """

    def setUp(self):
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn, "cajapuerta")
        # El sibling '· USD' nace SIN caja, que es el caso del importador: el
        # broker ya existe, así que el único de `brokers` no frena a nadie.
        for nombre, mon in (("IOL", "ARS"), ("IOL · USD", "USD")):
            self.conn.execute(
                "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                (self.uid, nombre, mon))
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

    def test_cinco_pedidos_dejan_UNA_caja(self):
        listo = threading.Barrier(5)
        errs, cerrojo = [], threading.Lock()

        def asegurar(i):
            c = None
            try:
                c = main.get_db()
                listo.wait(timeout=30)
                with c:
                    _ef.asegurar_caja(c, self.uid, "IOL · USD", "USD")
            except Exception as ex:                       # noqa: BLE001
                with cerrojo:
                    errs.append(f"{type(ex).__name__}: {str(ex)[:90]}")
            finally:
                if c is not None:
                    try: c.close()
                    except Exception: pass

        hilos = [threading.Thread(target=asegurar, args=(i,)) for i in range(5)]
        [h.start() for h in hilos]
        [h.join(timeout=60) for h in hilos]
        self.conn.rollback()
        cuantas = self.conn.execute(
            "SELECT COUNT(*) AS n FROM positions "
            " WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, "IOL · USD")).fetchone()["n"]
        self.assertEqual(
            int(cuantas), 1,
            f"quedaron {cuantas} filas de caja para el mismo broker: la plata de "
            f"las que no son la más vieja no la mueve nadie. errores={errs}")

    def test_el_importador_no_tiene_su_propia_puerta(self):
        """Guardián por texto, con sus límites dichos: el persister NO puede
        volver a tener su propio «¿existe? → la inserto».

        Es un guardián por texto y no ve todo (no vería un INSERT armado por
        pedazos), pero este caso concreto se escapó justo porque un barrido por
        texto pedía `is_cash` y el INSERT en la misma línea. Acá se busca al
        revés: que el archivo NO inserte filas de caja por su cuenta.
        """
        ruta = os.path.join(BACKEND, "importing", "persister.py")
        with open(ruta, encoding="utf-8") as f:
            codigo = f.read()
        self.assertIn(
            "asegurar_caja", codigo,
            "el importador dejó de usar la puerta única de efectivo")
        # Un INSERT en `positions` con is_cash=1 dentro del persister.
        import re
        for m in re.finditer(r"INSERT\s+INTO\s+positions[^;]{0,400}", codigo,
                             re.I | re.S):
            self.assertNotRegex(
                m.group(0), r"is_cash[^)]*\)\s*\n?\s*VALUES\s*\([^)]*,\s*1\b",
                "el importador volvió a insertar una fila de caja por su cuenta: "
                "tiene que ir por `efectivo.asegurar_caja`")


if __name__ == "__main__":
    unittest.main()
