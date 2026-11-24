"""#33 — El emparejador de conductos dólar-MEP no se come las filas de un pase.

QUÉ ES UN CONDUCTO. Comprar un título en pesos y venderlo en dólares (o al revés)
la misma cantidad y a pocos días es una conversión de moneda, no una tenencia: el
rebuild cancela ese par antes del FIFO (`rebuild._cancel_conduit_pairs`).

QUÉ PUEDE SALIR MAL CON «MOVER A OTRO BROKER». La salida del pase es una VENTA a
precio 0 en el broker de origen, y la llegada una COMPRA con su costo en el de
destino. Si cerca hubiera una compra (o una venta) de la misma cantidad en la otra
moneda, el emparejador las tomaría por un conducto y cancelaría las dos: el pase
desaparecería del replay, los títulos quedarían en el broker de origen y la compra
de la otra moneda también —tenencia de más, sin que nadie lo vea—. Por eso las filas
con `traspaso_id` no pueden ser candidatas (D.5.3 de la especificación).

CÓMO SE SABE QUE EL TEST MIDE. Cada caso corre dos veces: con `traspaso_id` (no se
cancela nada) y SIN él, con las mismas filas (se cancela el par). Si el segundo no
cancelara, el primero pasaría con cualquier código.

Corre con: cd backend && python3 -m pytest tests/test_conducto_no_se_come_la_salida.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from importing import rebuild as rb  # noqa: E402
from importing.schema import OP_BUY, OP_SELL  # noqa: E402

PASE = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"


def _ev(i, fecha, op, broker, qty, precio, monto, moneda, *, activo="KO", nombre=None,
        tipo="CEDEAR", **extra):
    """Un evento con las mismas claves que devuelve `rebuild._full_events`."""
    ev = {"id": i, "batch_id": "lote-1", "raw_row_id": 100 + i, "date": fecha,
          "broker": broker, "asset_symbol": activo, "asset_name": nombre,
          "operation_type": op, "quantity": qty, "unit_price": precio,
          "gross_amount": monto, "fees": 0.0, "currency": moneda,
          "asset_type": tipo, "transfer_out": 0, "created_position_id": None,
          "tc_compra": None, "traspaso_id": None, "fecha_compra": None}
    ev.update(extra)
    return ev


def _salida_del_pase(con_pase):
    """CEDEAR: 4 KO comprados en dólares; el 10/06 salen por un pase desde la cuenta
    en pesos (la venta a precio 0 consume el lote en dólares del par) y el 12/06 se
    compran otros 4 en dólares. Una venta en pesos seguida de una compra en dólares
    de la misma cantidad, a dos días: la forma exacta de un conducto de no-bono."""
    return [
        _ev(1, "2024-01-05", OP_BUY, "Cocos · USD", 4.0, 10.0, 40.0, "USD"),
        _ev(2, "2024-06-10", OP_SELL, "Cocos", 4.0, 0.0, 0.0, "ARS", transfer_out=1,
            traspaso_id=(PASE if con_pase else None)),
        _ev(3, "2024-06-12", OP_BUY, "Cocos · USD", 4.0, 12.0, 48.0, "USD"),
    ]


def _llegada_del_pase(con_pase):
    """Bono: el 01/03 llegan por un pase 1.000 AL30 en pesos y el 03/03 se venden
    1.000 en dólares. En los bonos el emparejador no mira el orden: compra y venta de
    igual nominal en monedas distintas a dos días se cancelan."""
    return [
        _ev(1, "2024-03-01", OP_BUY, "Balanz", 1000.0, 600.0, 600000.0, "ARS",
            activo="AL30", tipo="BOND", fecha_compra=("2023-05-02" if con_pase else None),
            traspaso_id=(PASE if con_pase else None)),
        _ev(2, "2024-03-03", OP_SELL, "Balanz · USD", 1000.0, 0.55, 550.0, "USD",
            activo="AL30", tipo="BOND"),
    ]


class ElConductoNoSeComeElPase(unittest.TestCase):

    def test_la_salida_del_pase_no_se_cancela_con_una_compra_en_la_otra_moneda(self):
        # Control: sin pase, las mismas filas SON un conducto y se cancelan.
        sin = rb._cancel_conduit_pairs(_salida_del_pase(False))
        self.assertEqual([e["id"] for e in sin], [1],
                         "el control no cancela: el test no estaría midiendo nada")
        # Con pase, no se toca ninguna.
        con = rb._cancel_conduit_pairs(_salida_del_pase(True))
        self.assertEqual([e["id"] for e in con], [1, 2, 3])

    def test_y_el_replay_saca_los_titulos_del_broker_de_origen(self):
        """Lo que importa al final: el pase se llevó los 4 viejos y quedan sólo los 4
        comprados después. Si el conducto se hubiera comido el par, quedarían los 4
        viejos (el pase no habría ocurrido)."""
        eventos = _salida_del_pase(True)
        out = rb._replay_asset(rb._cancel_conduit_pairs(eventos), "ARS", 1000.0,
                               conn=None, is_exchange=False, use_hist=False)
        self.assertEqual(out["operations"], [], "la salida de un pase no es una venta")
        self.assertEqual([(l["entry_date"], l["qty"]) for l in out["open_lots"]],
                         [("2024-06-12", 4.0)])
        self.assertEqual([(t["entry_date"], t["qty"], t["raw_row_id"])
                          for t in out["traspasos"][PASE]], [("2024-01-05", 4.0, 101)])

    def test_la_llegada_del_pase_no_se_cancela_con_una_venta_en_la_otra_moneda(self):
        sin = rb._cancel_conduit_pairs(_llegada_del_pase(False))
        self.assertEqual(sin, [], "el control no cancela: el test no estaría midiendo nada")
        con = rb._cancel_conduit_pairs(_llegada_del_pase(True))
        self.assertEqual([e["id"] for e in con], [1, 2])

    def test_un_conducto_de_verdad_al_lado_de_un_pase_se_sigue_cancelando(self):
        """La exclusión es de las filas del pase, no del activo: un conducto genuino
        del mismo bono, en otras fechas, se cancela igual."""
        eventos = _llegada_del_pase(True) + [
            _ev(3, "2024-08-01", OP_BUY, "Balanz", 500.0, 650.0, 325000.0, "ARS",
                activo="AL30", tipo="BOND"),
            _ev(4, "2024-08-02", OP_SELL, "Balanz · USD", 500.0, 0.6, 300.0, "USD",
                activo="AL30", tipo="BOND"),
        ]
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(eventos)], [1, 2])


if __name__ == "__main__":
    unittest.main()
