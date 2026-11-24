"""#32 — El rebuild consume los lotes por fecha de COMPRA, no por fecha de llegada.

QUÉ CAMBIA CON «MOVER A OTRO BROKER». Cuando un lote pasa de A a B, en el registro
de B aparece una COMPRA fechada el día del pase pero con la fecha de compra
original guardada aparte (`import_normalized_tx.fecha_compra`). El rebuild de B
tiene que tratarla como lo que es: un lote viejo. Si la ordenara por el día en que
llegó, una venta posterior en B consumiría primero un lote más nuevo y el costo (y
la ganancia) saldrían de otra compra. Es el cambio H2 de la especificación (D.5.2):
la venta ordena los lotes por `(entry_date, orden de llegada)`.

LAS DOS MITADES DE ESTE ARCHIVO:
  1. `SinFechaDeCompraSaleIgual`: una secuencia SIN `fecha_compra` (todo lo que
     existe hoy) y la salida de `rebuild._replay_asset` CONGELADA con el código
     anterior al cambio (6f28f2fc). Con los datos de hoy la fecha de compra es la del
     evento, así que ordenar por ella no puede mover nada: si esta mitad se pone en
     rojo, el cambio tocó cuentas que no tenían pases.
  2. `UnaCompraViejaQueLlegaTarde`: lo nuevo. Hoy falla a propósito
     (`expectedFailure`). La etapa E2b implementa D.5.2 y tiene que SACAR el
     marcador: si lo deja, la corrida avisa con «unexpected success».

Los números de la mitad 1 salieron de la corrida real (no de una cuenta a mano). Los
de la mitad 2 son la especificación: qué lote tiene que consumirse.

Corre con: cd backend && python3 -m pytest tests/test_rebuild_ordena_por_fecha_de_compra.py
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing import rebuild as rb  # noqa: E402
from importing.schema import OP_BUY, OP_SELL  # noqa: E402

TC_BLUE = 1000.0


def _ev(i, fecha, op, broker, qty, precio, monto, comision, moneda, **extra):
    """Un evento con las mismas claves que devuelve `rebuild._full_events`."""
    ev = {"id": i, "batch_id": "lote-1", "raw_row_id": 100 + i, "date": fecha,
          "broker": broker, "asset_symbol": "KO", "asset_name": None,
          "operation_type": op, "quantity": qty, "unit_price": precio,
          "gross_amount": monto, "fees": comision, "currency": moneda,
          "asset_type": "CEDEAR", "transfer_out": 0, "created_position_id": None,
          "tc_compra": None}
    ev.update(extra)
    return ev


def _en_orden_de_full_events(eventos):
    """El orden de `_full_events`: fecha, compras antes que ventas el mismo día, id."""
    return sorted(eventos, key=lambda e: (e["date"], 0 if e["operation_type"] == OP_BUY else 1,
                                          e["id"]))


def _parecidos(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return (a is not None and b is not None
                and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9))
    return a == b


# ─── Mitad 1: sin fecha de compra, la salida de hoy ──────────────────────────

def _secuencia_sin_fecha_de_compra():
    """Pesos y dólares en el mismo par (a 1.000 pesos por dólar, el mismo precio en
    las dos monedas), una compra y una venta el mismo día, una venta que tiene que
    cruzar de moneda, una que fabrica un lote semilla, una compra sin monto (precio ×
    cantidad) y un lote abierto con su dólar de compra."""
    return [
        _ev(1, "2024-01-10", OP_BUY, "Cocos", 10.0, 1000.0, 10000.0, 10.0, "ARS"),
        _ev(2, "2024-01-20", OP_BUY, "Cocos · USD", 6.0, 1.0, 6.0, 0.06, "USD"),
        _ev(3, "2024-02-01", OP_BUY, "Cocos", 4.0, 1100.0, 4400.0, 4.0, "ARS"),
        _ev(4, "2024-02-01", OP_SELL, "Cocos", 8.0, 1300.0, 10400.0, 8.0, "ARS"),
        _ev(5, "2024-03-01", OP_SELL, "Cocos", 9.0, 1400.0, 12600.0, 9.0, "ARS"),
        _ev(6, "2024-04-01", OP_SELL, "Cocos · USD", 5.0, 1.25, 6.25, 0.025, "USD"),
        _ev(7, "2024-05-01", OP_BUY, "Cocos · USD", 2.0, 1.1, None, 0.02, "USD"),
        _ev(8, "2024-06-01", OP_SELL, "Cocos", 1.0, 1500.0, 1500.0, 1.0, "ARS"),
        _ev(9, "2024-06-15", OP_BUY, "Cocos", 3.0, 1500.0, 4500.0, 3.0, "ARS", tc_compra=1200.0),
    ]


CLAVES_OPERACION = ("date", "broker", "asset", "op_type", "entry_price", "exit_price",
                    "quantity", "pnl_usd", "pnl_pct", "entry_date", "commissions",
                    "currency", "fx_to_usd", "resultado", "batch_id", "raw_row_id")
CLAVES_LOTE = ("qty", "invested", "buy_price", "commissions", "entry_date", "currency",
               "batch_id", "raw_row_id", "is_seed", "_broker", "_asset", "_asset_type",
               "tc_compra")

# Salida de `_replay_asset(secuencia, "ARS", 1000.0, conn=None, use_hist=False)` con
# el código de 6f28f2fc. Una tupla por fila, en el orden de CLAVES_OPERACION /
# CLAVES_LOTE.
OPERACIONES_CONGELADAS = [
    ('2024-02-01', 'Cocos', 'KO', 'Venta', 1000.0, 1300.0, 8.0, 2.38, 29.7702,
     '2024-01-10', 8.0, 'ARS', 1000.0, None, 'lote-1', 104),
    ('2024-03-01', 'Cocos', 'KO', 'Venta', 1000.0, 1400.0, 2.0, 0.8, 39.7602,
     '2024-01-10', 2.0, 'ARS', 1000.0, None, 'lote-1', 105),
    ('2024-03-01', 'Cocos', 'KO', 'Venta', 1100.0, 1400.0, 4.0, 1.19, 27.0663,
     '2024-02-01', 4.0, 'ARS', 1000.0, None, 'lote-1', 105),
    ('2024-03-01', 'Cocos', 'KO', 'Venta', 1.0, 1400.0, 3.0, 1.17, 38.5149,
     '2024-01-20', 3.0, 'ARS', 1000.0, None, 'lote-1', 105),
    ('2024-04-01', 'Cocos · USD', 'KO', 'Venta', 1.0, 1.25, 3.0, 0.71, 23.2673,
     '2024-01-20', 0.015, 'USD', None, None, 'lote-1', 106),
    ('2024-04-01', 'Cocos · USD', 'KO', 'Venta', 1.25, 1.25, 2.0, -0.01, -0.4,
     '2024-04-01', 0.01, 'USD', None, None, 'lote-1', 106),
    ('2024-06-01', 'Cocos', 'KO', 'Venta', 1.1, 1500.0, 1.0, 0.39, 35.045,
     '2024-05-01', 1.0, 'ARS', 1000.0, None, 'lote-1', 108),
]
LOTES_CONGELADOS = [
    (1.0, 1.1, 1.1, 0.01, '2024-05-01', 'USD', 'lote-1', 107,
     False, 'Cocos · USD', 'KO', 'CEDEAR', None),
    (3.0, 4500.0, 1500.0, 3.0, '2024-06-15', 'ARS', 'lote-1', 109,
     False, 'Cocos', 'KO', 'CEDEAR', 1200.0),
]


class SinFechaDeCompraSaleIgual(unittest.TestCase):

    def _replay(self):
        eventos = _secuencia_sin_fecha_de_compra()
        self.assertEqual([e["id"] for e in eventos],
                         [e["id"] for e in _en_orden_de_full_events(eventos)],
                         "la secuencia tiene que venir en el orden de _full_events")
        return rb._replay_asset(eventos, "ARS", TC_BLUE, conn=None,
                                is_exchange=False, use_hist=False)

    def _comparar(self, obtenidas, congeladas, claves, que):
        self.assertEqual(len(obtenidas), len(congeladas), f"cantidad de {que}")
        for i, (o, c) in enumerate(zip(obtenidas, congeladas)):
            for k, v in zip(claves, c):
                self.assertTrue(_parecidos(o.get(k), v),
                                f"{que}[{i}].{k}: obtenido {o.get(k)!r}, congelado {v!r}")

    def test_las_ventas_son_las_de_antes(self):
        out = self._replay()
        self._comparar(out["operations"], OPERACIONES_CONGELADAS, CLAVES_OPERACION, "ventas")

    def test_los_lotes_abiertos_son_los_de_antes(self):
        out = self._replay()
        self._comparar(out["open_lots"], LOTES_CONGELADOS, CLAVES_LOTE, "lotes")
        # Sin fecha de compra, ningún lote dice que llegó de otro broker. Vale antes
        # de E2b (la clave no existe) y después (tiene que ser None).
        for lote in out["open_lots"]:
            self.assertIsNone(lote.get("en_broker_desde"))


# ─── Mitad 2: una compra vieja que llega tarde (lo que agrega E2b) ───────────

PASE = "f0e1d2c3b4a5968778695a4b3c2d1e0f"


def _secuencia_con_llegada_de_un_pase(cantidad_vendida):
    """B ya tenía 10 KO comprados el 01/03/2024. El 01/05/2024 llegan 5 más por un
    pase, comprados originalmente el 15/01/2023. El 01/06/2024 se vende."""
    return [
        _ev(1, "2024-03-01", OP_BUY, "Balanz", 10.0, 1000.0, 10000.0, 0.0, "ARS"),
        _ev(2, "2024-05-01", OP_BUY, "Balanz", 5.0, 500.0, 2500.0, 0.0, "ARS",
            fecha_compra="2023-01-15", traspaso_id=PASE),
        _ev(3, "2024-06-01", OP_SELL, "Balanz", cantidad_vendida, 2000.0,
            2000.0 * cantidad_vendida, 0.0, "ARS"),
    ]


class UnaCompraViejaQueLlegaTarde(unittest.TestCase):

    def _replay(self, cantidad_vendida):
        return rb._replay_asset(_secuencia_con_llegada_de_un_pase(cantidad_vendida), "ARS",
                                TC_BLUE, conn=None, is_exchange=False, use_hist=False)

    # E2b: sacar este marcador cuando D.5.2 esté implementado.
    @unittest.expectedFailure
    def test_la_venta_consume_primero_el_lote_mas_viejo(self):
        out = self._replay(7.0)
        ventas = [(o["entry_date"], o["quantity"], o["entry_price"], o["pnl_usd"])
                  for o in out["operations"]]
        # Primero los 5 comprados en 2023 (a 500), después 2 de los del 01/03/2024.
        # (2000 − 500) × 5 / 1000 = 7,5 y (2000 − 1000) × 2 / 1000 = 2,0.
        self.assertEqual(ventas, [("2023-01-15", 5.0, 500.0, 7.5),
                                  ("2024-03-01", 2.0, 1000.0, 2.0)])
        lotes = [(l["entry_date"], l["qty"], l["invested"], l.get("en_broker_desde"))
                 for l in out["open_lots"]]
        self.assertEqual(lotes, [("2024-03-01", 8.0, 8000.0, None)])

    # E2b: sacar este marcador cuando D.5.2 esté implementado.
    @unittest.expectedFailure
    def test_el_lote_que_llego_guarda_su_compra_y_su_llegada(self):
        out = self._replay(3.0)
        ventas = [(o["entry_date"], o["quantity"]) for o in out["operations"]]
        self.assertEqual(ventas, [("2023-01-15", 3.0)])
        lotes = sorted((l["entry_date"], l["qty"], l.get("en_broker_desde"))
                       for l in out["open_lots"])
        # El que llegó por el pase: compra original y desde cuándo está en ESTE broker.
        self.assertEqual(lotes, [("2023-01-15", 2.0, "2024-05-01"),
                                 ("2024-03-01", 10.0, None)])


if __name__ == "__main__":
    unittest.main()
