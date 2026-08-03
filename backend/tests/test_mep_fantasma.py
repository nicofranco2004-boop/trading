"""El MEP no deja activos fantasma: end-to-end, import real → rebuild → cartera.

EL CASO (reportado por un usuario el 2026-08-01): hacer "dólar MEP" son dos
operaciones el mismo día sobre el mismo instrumento — se compra AL30 con pesos y
se vende su pata dólar AL30D unas horas después. El broker las exporta con
TICKERS DISTINTOS y el replay FIFO arma un ledger por símbolo EXACTO, así que
quedaban dos libros que nunca se veían: la compra abierta como activo fantasma y
la venta sin stock resuelta con un lote semilla al precio de venta (P&L 0).

Textual: "puede registrarse una ganancia irreal o que te tome venta de un activo
que no tenías registro inicial y posterior comprar, dejando un activo en la
cartera que no existe".

Estos tests corren el pipeline COMPLETO (preview → confirm → persist → rebuild),
no la función de consolidación aislada.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class MepMismoDiaTest(_Base):
    BROKER = "Balanz"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def test_las_dos_patas_se_netean_y_no_queda_fantasma(self):
        """Compro AL30 en pesos y vendo AL30D en dólares el mismo día."""
        self._import(_csv(
            "2026-03-10,COMPRA,Balanz,AL30,100,1000,100000,,,0,ARS,",
            "2026-03-10,VENTA,Balanz,AL30D,100,0.7,70,,,0,USD,",
        ), rebuild=True)
        # El fantasma era AL30 quedando abierto con 100 nominales.
        self.assertEqual(self._open_qty("AL30"), 0.0,
                         "quedó abierta la pata en pesos: el activo fantasma")
        self.assertEqual(self._open_qty("AL30D"), 0.0,
                         "AL30D no debería existir como símbolo propio")

    def test_no_inventa_ganancia(self):
        """La venta sin stock salía con un lote semilla al precio de venta."""
        self._import(_csv(
            "2026-03-10,COMPRA,Balanz,AL30,100,1000,100000,,,0,ARS,",
            "2026-03-10,VENTA,Balanz,AL30D,100,0.7,70,,,0,USD,",
        ), rebuild=True)
        # Un MEP no genera resultado: es una conversión, no una ganancia.
        self.assertLess(abs(self._global_pnl()), 1.0,
                        f"P&L realizado irreal: {self._global_pnl()}")

    def test_la_tenencia_previa_sobrevive_intacta(self):
        """Lo que el usuario YA tenía no se puede tocar."""
        self._import(_csv(
            "2025-01-05,COMPRA,Balanz,AL30,50,300,15000,,,0,ARS,",
        ), rebuild=True)
        self._import(_csv(
            "2026-03-10,COMPRA,Balanz,AL30,100,1000,100000,,,0,ARS,",
            "2026-03-10,VENTA,Balanz,AL30D,100,0.7,70,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._open_qty("AL30"), 50.0,
                         "el MEP se comió (o infló) la tenencia previa")

    def test_el_mep_inverso_tambien(self):
        """Vender pesos y comprar dólares: la otra dirección del mismo puente."""
        self._import(_csv(
            "2025-01-05,COMPRA,Balanz,AL30,100,300,30000,,,0,ARS,",
        ), rebuild=True)
        self._import(_csv(
            "2026-03-10,VENTA,Balanz,AL30,100,1000,100000,,,0,ARS,",
            "2026-03-10,COMPRA,Balanz,AL30D,100,0.7,70,,,0,USD,",
        ), rebuild=True)
        self.assertEqual(self._open_qty("AL30D"), 0.0)

    def test_un_ticker_que_termina_en_D_de_verdad_no_se_toca(self):
        """YPFD es una acción argentina, no la pata dólar de "YPF"."""
        self._import(_csv(
            "2026-03-10,COMPRA,Balanz,YPFD,10,50000,500000,,,0,ARS,",
        ), rebuild=True)
        self.assertEqual(self._open_qty("YPFD"), 10.0,
                         "se consolidó de más: partió el historial de YPFD")


if __name__ == "__main__":
    unittest.main()
