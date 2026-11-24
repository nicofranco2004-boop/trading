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

Y AL REVÉS: UN PASE NO DESCANCELA UN CONDUCTO VIEJO. El emparejador sólo cancela una
venta en la moneda X si X está «corta» (las compras en X no cubren las ventas en X), y
esa cuenta mira todo el historial. Si la llegada de un pase en X entrara en esa cuenta,
un conducto de 2024 del broker de destino dejaría de cancelarse por una llegada de 2026:
el pase reescribiría la historia de antes del pase (C.11) y el rebuild fabricaría
títulos fantasma. Las filas de un pase cuentan sólo para las ventas que el replay
procesa después de ellas.

CÓMO SE SABE QUE EL TEST MIDE. Cada caso corre dos veces: con `traspaso_id` y SIN él,
con las mismas filas. Si el control no diera distinto, el caso pasaría con cualquier
código.

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
    """CEDEAR en la cuenta en pesos, con la forma exacta de un conducto de no-bono: una
    venta en pesos seguida, a dos días, de una compra en dólares de la misma cantidad.

    El 02/01 se venden en pesos 4 KO comprados en dólares (una venta común: no hay
    lotes en pesos y consume el de dólares), el 05/01 se compran 4 en pesos, el 10/06
    salen esos 4 por un pase —en pesos, la moneda del lote, desde la pata donde vive
    (A.6)— y el 12/06 se compran 4 en dólares. Las ventas en pesos (8) superan a las
    compras en pesos (4): la moneda está «corta», y sin `traspaso_id` la salida y la
    compra del 12/06 se cancelarían como conducto."""
    return [
        _ev(1, "2024-01-01", OP_BUY, "Cocos · USD", 4.0, 10.0, 40.0, "USD"),
        _ev(2, "2024-01-02", OP_SELL, "Cocos", 4.0, 10500.0, 42000.0, "ARS"),
        _ev(3, "2024-01-05", OP_BUY, "Cocos", 4.0, 10000.0, 40000.0, "ARS", fees=120.0),
        _ev(4, "2024-06-10", OP_SELL, "Cocos", 4.0, 0.0, 0.0, "ARS", transfer_out=1,
            traspaso_id=(PASE if con_pase else None)),
        _ev(5, "2024-06-12", OP_BUY, "Cocos · USD", 4.0, 12.0, 48.0, "USD"),
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
        self.assertEqual([e["id"] for e in sin], [1, 2, 3],
                         "el control no cancela: el test no estaría midiendo nada")
        # Con pase, no se toca ninguna.
        con = rb._cancel_conduit_pairs(_salida_del_pase(True))
        self.assertEqual([e["id"] for e in con], [1, 2, 3, 4, 5])

    def test_y_el_replay_saca_los_titulos_del_broker_de_origen(self):
        """Lo que importa al final: el pase se llevó los 4 en pesos y quedan sólo los 4
        comprados después en dólares. Si el conducto se hubiera comido el par, quedarían
        los 4 en pesos (el pase no habría ocurrido).

        Y lo que se llevó el pase, completo: el lote ENTERO va con su inversión y sus
        comisiones (`invested`, `commissions`). Es lo que comparan la comprobación del
        pase (#23) y el detector de desfase; el caso común es mover lotes enteros."""
        eventos = _salida_del_pase(True)
        out = rb._replay_asset(rb._cancel_conduit_pairs(eventos), "ARS", 1000.0,
                               conn=None, is_exchange=False, use_hist=False)
        self.assertEqual([op["raw_row_id"] for op in out["operations"]], [102],
                         "la única venta es la del 02/01: la salida de un pase no es una venta")
        self.assertEqual([(l["entry_date"], l["currency"], l["qty"]) for l in out["open_lots"]],
                         [("2024-06-12", "USD", 4.0)])
        self.assertEqual([(t["entry_date"], t["qty"], t["invested"], t["commissions"],
                           t["currency"], t["raw_row_id"])
                          for t in out["traspasos"][PASE]],
                         [("2024-01-05", 4.0, 40000.0, 120.0, "ARS", 103)])
        self.assertEqual(out["semillas"], [])

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


def _conducto_viejo_en_b():
    """Balanz, KO (no-bono): el 01/03/2024 vende 10 en dólares y el 03/03 compra 10 en
    pesos. Una venta en dólares sin compras en dólares seguida de una compra en pesos de
    la misma cantidad: un conducto, que se cancela (el neto del papel es 0)."""
    return [
        _ev(1, "2024-03-01", OP_SELL, "Balanz · USD", 10.0, 50.0, 500.0, "USD"),
        _ev(2, "2024-03-03", OP_BUY, "Balanz", 10.0, 60000.0, 600000.0, "ARS"),
    ]


class UnPaseNoReescribeUnConductoViejo(unittest.TestCase):
    """Las filas de un pase cuentan para la compuerta de «moneda corta» sólo desde que
    ocurren: no pueden cambiar si un conducto anterior al pase se cancela o no."""

    def _llegada(self, con_pase):
        return _ev(3, "2026-11-20", OP_BUY, "Balanz · USD", 10.0, 9.0, 90.0, "USD",
                   fecha_compra=("2023-01-10" if con_pase else None),
                   traspaso_id=(PASE if con_pase else None))

    def test_la_llegada_no_descancela_un_conducto_viejo_del_destino(self):
        eventos = _conducto_viejo_en_b()
        self.assertEqual(rb._cancel_conduit_pairs(eventos), [], "sin la llegada se cancela")
        # Control: una COMPRA COMÚN en dólares de 2026 sí lo descancela. Es la regla de
        # siempre para las filas comunes (mira todo el historial) y no se toca acá.
        comun = eventos + [self._llegada(False)]
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(comun)], [1, 2, 3],
                         "el control no descancela: el test no estaría midiendo nada")
        # La llegada del pase, no: el conducto de 2024 se sigue cancelando.
        con = eventos + [self._llegada(True)]
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(con)], [3])

    def test_y_el_replay_de_b_queda_con_lo_que_llego_y_nada_mas(self):
        """Sin la regla, el rebuild de B dejaba 10 KO en pesos de 2024 que no existen,
        una 'Venta' de más y un lote semilla."""
        con = _conducto_viejo_en_b() + [self._llegada(True)]
        out = rb._replay_asset(rb._cancel_conduit_pairs(con), "ARS", 1000.0,
                               conn=None, is_exchange=False, use_hist=False)
        self.assertEqual(out["operations"], [])
        self.assertEqual(out["semillas"], [])
        self.assertEqual([(l["entry_date"], l["en_broker_desde"], l["currency"], l["qty"])
                          for l in out["open_lots"]],
                         [("2023-01-10", "2026-11-20", "USD", 10.0)])

    def test_la_llegada_cubre_las_ventas_posteriores_del_destino(self):
        """La otra mitad: DESPUÉS de llegar, los títulos están en B, y una venta en
        dólares seguida de una compra en pesos de la misma cantidad es una venta de lo
        que llegó, no un conducto."""
        llegada = self._llegada(True)
        llegada.update(date="2024-05-01")
        despues = [
            _ev(4, "2024-06-10", OP_SELL, "Balanz · USD", 10.0, 12.0, 120.0, "USD"),
            _ev(5, "2024-06-12", OP_BUY, "Balanz", 10.0, 15000.0, 150000.0, "ARS"),
        ]
        self.assertEqual(rb._cancel_conduit_pairs(despues), [],
                         "el control (sin la llegada) no cancela: el test no mediría nada")
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs([llegada] + despues)],
                         [3, 4, 5])

    def test_la_salida_no_descancela_ni_cancela_lo_anterior_del_origen(self):
        """Cocos: 10 KO en pesos, el 10/06/2024 vende 3 en pesos y el 12/06 compra 3 en
        dólares (pesos no está «corta»: 10 compras contra 3 ventas, así que es una venta
        genuina y no se cancela). En 2026 salen 8 por un pase —más de lo que el registro
        tiene, como queda después de un PUT que sólo tocó `positions`—. La salida no
        puede volver «corta» la moneda para la venta de 2024."""
        base = [
            _ev(1, "2024-01-05", OP_BUY, "Cocos", 10.0, 10000.0, 100000.0, "ARS"),
            _ev(2, "2024-06-10", OP_SELL, "Cocos", 3.0, 11000.0, 33000.0, "ARS"),
            _ev(3, "2024-06-12", OP_BUY, "Cocos · USD", 3.0, 11.0, 33.0, "USD"),
        ]

        def salida(con_pase):
            return _ev(4, "2026-11-20", OP_SELL, "Cocos", 8.0, 0.0, 0.0, "ARS", transfer_out=1,
                       traspaso_id=(PASE if con_pase else None))

        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(base)], [1, 2, 3])
        # Control: una venta COMÚN de 8 sí vuelve corta la moneda (11 > 10) y la venta de
        # 2024 se cancela con la compra en dólares.
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(base + [salida(False)])],
                         [1, 4], "el control no cancela: el test no estaría midiendo nada")
        self.assertEqual([e["id"] for e in rb._cancel_conduit_pairs(base + [salida(True)])],
                         [1, 2, 3, 4])


class LaSalidaNoCruzaDeMoneda(unittest.TestCase):
    """El rebuild no completa la salida de un pase con lotes de la otra moneda (el
    persister tampoco: frena). Registro de Cocos: 10 GGAL en pesos y 5 en dólares; la
    salida es de 12 en pesos porque `positions` decía 12 (un PUT o `/adjust-ratio`
    tocan sólo `positions`)."""

    def _eventos(self, con_pase):
        return [
            _ev(1, "2024-01-05", OP_BUY, "Cocos", 10.0, 1000.0, 10000.0, "ARS",
                activo="GGAL", tipo="STOCK"),
            _ev(2, "2024-02-05", OP_BUY, "Cocos · USD", 5.0, 1.0, 5.0, "USD",
                activo="GGAL", tipo="STOCK"),
            _ev(3, "2024-06-10", OP_SELL, "Cocos", 12.0, 0.0, 0.0, "ARS", activo="GGAL",
                tipo="STOCK", transfer_out=1, traspaso_id=(PASE if con_pase else None)),
        ]

    def _replay(self, eventos):
        return rb._replay_asset(rb._cancel_conduit_pairs(eventos), "ARS", 1000.0,
                                conn=None, is_exchange=False, use_hist=False)

    def test_los_lotes_de_la_otra_moneda_quedan_intactos(self):
        # Control: una venta COMÚN sí completa con la otra moneda (el pool único).
        comun = self._replay(self._eventos(False))
        self.assertEqual([(l["currency"], l["qty"]) for l in comun["open_lots"]], [("USD", 3.0)],
                         "el control no cruza: el test no estaría midiendo nada")
        out = self._replay(self._eventos(True))
        self.assertEqual([(l["currency"], l["qty"]) for l in out["open_lots"]], [("USD", 5.0)],
                         "el pase se llevó dólares que el usuario no movió")
        # El faltante queda a la vista: un tramo sin origen y a costo 0, y su semilla.
        self.assertEqual([(t["currency"], t["qty"], t["invested"], t["raw_row_id"])
                          for t in out["traspasos"][PASE]],
                         [("ARS", 10.0, 10000.0, 101), ("ARS", 2.0, 0.0, None)])
        self.assertEqual(out["semillas"], ["2024-06-10"])
        self.assertEqual(out["operations"], [])


if __name__ == "__main__":
    unittest.main()
