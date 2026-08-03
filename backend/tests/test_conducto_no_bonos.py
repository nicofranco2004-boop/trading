"""El conducto MEP cross-día también existe con acciones y CEDEARs, no solo bonos.

`_cancel_conduit_pairs` cancela pares COMPRA/VENTA del mismo activo en monedas
distintas, mismo nominal, ≤7 días: el MEP que se le escapó al parser. Tenía un
gate `if not is_bond: return events` con el comentario "restringido a BONOS para
no tocar el neteo de acciones (ya testeado en _replay_asset)".

Pero el spill de `_replay_asset` no alcanza un caso: cuando la VENTA llega ANTES
que la compra no hay lote de dónde salir, se sintetiza una semilla al precio de
venta (P&L 0) y la compra queda abierta como fantasma. Reproducido con GGAL
vendido el 2026-03-10 en USD y comprado el 2026-03-11 en ARS; la misma secuencia
con AL30 salía bien.

El cambio entra SOLO en ese caso —venta antes que compra— y con dos guardas
(exchange cripto afuera, y denylist de tipos). Compra-antes-de-venta lo sigue
resolviendo el spill, intacto.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

sys.path.insert(0, os.path.dirname(HERE))

from importing.rebuild import _cancel_conduit_pairs, _CONDUIT_BLOCKED_TYPES  # noqa: E402


def ev(op, asset, qty, ccy, date, atype=None, name=None):
    return {"operation_type": op, "asset_symbol": asset, "quantity": qty,
            "currency": ccy, "date": date, "asset_type": atype, "asset_name": name,
            "unit_price": 1.0, "gross_amount": qty}


class AccionesCrossDiaTest(unittest.TestCase):
    """El caso del reporte: venta en USD, compra en ARS al día siguiente."""

    def test_ggal_venta_antes_que_compra_se_cancela(self):
        evs = [ev("SELL", "GGAL", 100, "USD", "2026-03-10", "STOCK"),
               ev("BUY", "GGAL", 100, "ARS", "2026-03-11", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 0,
                         "quedó el par sin cancelar: seed + activo fantasma")

    def test_cedear_igual(self):
        evs = [ev("SELL", "AAPL", 50, "USD", "2026-03-10", "CEDEAR"),
               ev("BUY", "AAPL", 50, "ARS", "2026-03-12", "CEDEAR")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 0)

    def test_bonos_siguen_andando_igual(self):
        evs = [ev("SELL", "AL30", 100, "USD", "2026-03-10", "BOND"),
               ev("BUY", "AL30", 100, "ARS", "2026-03-11", "BOND")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 0)


class LoQueNoSeTocaTest(unittest.TestCase):
    """El cambio entra solo donde el spill no llega. Todo lo demás, idéntico."""

    def test_compra_antes_que_venta_lo_sigue_manejando_el_spill(self):
        # Con la compra primero hay lote de dónde salir: el spill cross-currency
        # de _replay_asset ya lo resuelve, así que el conducto NO debe meterse.
        evs = [ev("BUY", "GGAL", 100, "ARS", "2026-03-10", "STOCK"),
               ev("SELL", "GGAL", 100, "USD", "2026-03-11", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 2,
                         "se metió en un caso que el spill ya resolvía")

    def test_en_bonos_la_restriccion_no_aplica(self):
        # Los bonos entran en las dos direcciones, como antes del cambio.
        evs = [ev("BUY", "AL30", 100, "ARS", "2026-03-10", "BOND"),
               ev("SELL", "AL30", 100, "USD", "2026-03-11", "BOND")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 0)

    def test_exchange_cripto_afuera(self):
        # Guard LOAD-BEARING: un altcoin sin asset_type cae en OTHER y pasaría
        # el filtro de tipos. El broker sí sabe que es un exchange.
        evs = [ev("SELL", "PEPE", 1000, "USD", "2026-03-10", None),
               ev("BUY", "PEPE", 1000, "ARS", "2026-03-11", None)]
        self.assertEqual(len(_cancel_conduit_pairs(evs, is_exchange=True)), 2)

    def test_tipos_bloqueados(self):
        for atype in ("CRYPTO", "FIAT", "FUND"):
            evs = [ev("SELL", "XXX", 10, "USD", "2026-03-10", atype),
                   ev("BUY", "XXX", 10, "ARS", "2026-03-11", atype)]
            self.assertEqual(len(_cancel_conduit_pairs(evs)), 2, atype)
        self.assertEqual(_CONDUIT_BLOCKED_TYPES, {"CRYPTO", "FIAT", "FUND"})

    def test_fuera_de_ventana(self):
        evs = [ev("SELL", "GGAL", 100, "USD", "2026-03-01", "STOCK"),
               ev("BUY", "GGAL", 100, "ARS", "2026-03-20", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 2)

    def test_nominal_distinto_es_tenencia_genuina(self):
        evs = [ev("SELL", "GGAL", 100, "USD", "2026-03-10", "STOCK"),
               ev("BUY", "GGAL", 70, "ARS", "2026-03-11", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 2)

    def test_misma_moneda_no_es_conducto(self):
        evs = [ev("SELL", "GGAL", 100, "ARS", "2026-03-10", "STOCK"),
               ev("BUY", "GGAL", 100, "ARS", "2026-03-11", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 2)

    def test_el_gate_net_short_sigue_protegiendo(self):
        # Si las compras en la moneda de la venta ya la cubren, es tenencia
        # genuina dual-currency, no conducto.
        evs = [ev("BUY", "GGAL", 100, "USD", "2026-03-09", "STOCK"),
               ev("SELL", "GGAL", 100, "USD", "2026-03-10", "STOCK"),
               ev("BUY", "GGAL", 100, "ARS", "2026-03-11", "STOCK")]
        self.assertEqual(len(_cancel_conduit_pairs(evs)), 3)

    def test_lista_vacia(self):
        self.assertEqual(_cancel_conduit_pairs([]), [])


class FirmaCompatibleTest(unittest.TestCase):
    def test_is_exchange_es_keyword_only_con_default(self):
        # `maturity.py:278` llama sin el kwarg: si dejara de tener default, rompe.
        import inspect
        from importing.rebuild import _cancel_conduit_pairs as f
        p = inspect.signature(f).parameters["is_exchange"]
        self.assertEqual(p.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(p.default, False)

    def test_los_dos_call_sites_del_rebuild_pasan_el_guard(self):
        # Si alguien amplía el gate y se olvida de pasar is_exchange, el guard
        # queda muerto y se rompe Binance en silencio.
        import inspect
        import importing.rebuild as rb
        src = inspect.getsource(rb)
        self.assertEqual(src.count("_cancel_conduit_pairs(events, is_exchange=grp_is_exchange)"), 2)


if __name__ == "__main__":
    unittest.main()
