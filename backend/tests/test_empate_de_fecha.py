"""Dos operaciones del MISMO día: el número no puede depender del motor.

`operations.date` no tiene hora, así que todo un día empata. Una consulta que
ordena sólo por fecha deja el empate al motor:

  · SQLite lo resuelve por el índice `idx_operations_user_date (user_id, date
    DESC)` y el número de fila: ordenando por fecha ASCENDENTE, el empate sale
    con `id` DESCENDENTE (la última cargada primero); DESCENDENTE, con `id`
    ascendente (medido el 31/10/2026). Es un accidente del índice, no una regla
    escrita — pero es lo que producción muestra hoy.
  · Postgres no garantiza nada: acá, con la tabla chica, lee en orden físico y
    el empate sale por orden de carga. Al revés que SQLite.

Y hay números que dependen de ese orden. Se prueban dos, por el camino real:
  · «promediar a la baja» (`/api/behavioral/insights`): compara cada compra con
    la ANTERIOR del mismo activo;
  · el patrón de compras de una posición que lee la IA (`ai/builders/position_lots`).

El arreglo copia lo que SQLite da hoy (`orden_estable.py`), así la mudanza no
cambia ningún número. Si ese orden es el CORRECTO —el día no tiene hora— es otra
discusión (memoria `project_orden_filas_desempate`).
"""
import unittest

from fastapi.testclient import TestClient

import main
from tests._limpieza import vaciar  # noqa: E402

DIA = "2024-03-04"


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        vaciar(self.conn, "operations", "positions", "brokers", "users")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,?,1,'pro')",
            (f"empate-{id(self)}@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "IBKR", "USD"))
        self.conn.commit()

    def compra(self, oid, fecha, precio, qty=10):
        # El id va explícito y las filas se cargan EN ORDEN DE id: así Postgres
        # (orden físico) y SQLite (índice, id descendente) resuelven el empate al
        # revés uno del otro si nadie lo fija.
        self.conn.execute(
            "INSERT INTO operations (id, user_id, date, asset, broker, op_type, quantity, "
            "entry_price, entry_date, currency) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (oid, self.uid, fecha, "AAPL", "IBKR", "Compra", qty, precio, fecha, "USD"))
        self.conn.commit()


class PromediarALaBajaTest(_Base):
    """Compras: 100 el día anterior; el MISMO día, 110 (id 2) y 90 (id 3).

    Lo que SQLite muestra hoy (empate por id descendente): 100 → 90 → 110, o sea
    UNA instancia de 100 a 90, 10 % de caída. Con el empate al revés: 100 → 110 →
    90, una instancia de 110 a 90, 18,18 %. Misma cantidad, OTRO número.

    Se carga de las DOS formas (en orden de id y al revés): SQLite ordena por el
    número de fila —que es el id— y da lo mismo; Postgres sigue el orden físico,
    y alguna de las dos lo da vuelta según el plan que elija."""

    def _medir(self):
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        self.addCleanup(main.app.dependency_overrides.pop, main.get_effective_user, None)
        r = TestClient(main.app).get("/api/behavioral/insights")
        self.assertEqual(r.status_code, 200, r.text)
        tarjeta = next(c for c in r.json()["cards"] if c.get("code") == "averaging_down")
        ev = tarjeta["evidence"]
        self.assertEqual(ev["total_instances"], 1, ev)
        self.assertEqual(ev["avg_drop_pct"], 10.0, ev)
        par = ev["instances"][0]
        self.assertEqual((par["first_buy"]["price"], par["second_buy"]["price"]), (100.0, 90.0))

    def test_cargadas_en_orden_de_id(self):
        self.compra(1, "2024-03-01", 100.0)
        self.compra(2, DIA, 110.0)
        self.compra(3, DIA, 90.0)
        self._medir()

    def test_cargadas_al_reves(self):
        self.compra(3, DIA, 90.0)
        self.compra(2, DIA, 110.0)
        self.compra(1, "2024-03-01", 100.0)
        self._medir()


class PatronDeComprasDeLaIATest(_Base):
    """Compras: 100; el MISMO día 110 (id 2) y 90 (id 3); y 95 después.

    Lo que SQLite muestra hoy: 100, 90, 110, 95 → bajó, subió, bajó →
    «averaging_down». Con el empate al revés: 100, 110, 90, 95 → subió, bajó,
    subió → «averaging_up». La IA leería lo contrario."""

    def _medir(self):
        from ai.builders import position_lots
        r = position_lots.build(self.conn, self.uid, asset="AAPL")
        precios = [l["price"] for l in r["lots"] if l["op_type"] == "Compra"]
        self.assertEqual(precios, [100.0, 90.0, 110.0, 95.0])
        self.assertEqual(r["pattern"], "averaging_down", r)

    def test_cargadas_en_orden_de_id(self):
        for oid, fecha, precio in ((1, "2024-03-01", 100.0), (2, DIA, 110.0),
                                   (3, DIA, 90.0), (4, "2024-03-08", 95.0)):
            self.compra(oid, fecha, precio)
        self._medir()

    def test_cargadas_al_reves(self):
        for oid, fecha, precio in ((4, "2024-03-08", 95.0), (3, DIA, 90.0),
                                   (2, DIA, 110.0), (1, "2024-03-01", 100.0)):
            self.compra(oid, fecha, precio)
        self._medir()


if __name__ == "__main__":
    unittest.main()
