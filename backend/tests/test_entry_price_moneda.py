"""En una venta cruzada, las dos puntas de la fila tienen que estar en la MISMA moneda.

QUÉ SE ROMPÍA
─────────────
`operations.entry_price` guardaba el precio del lote en la moneda en que se
COMPRÓ, y `exit_price` en la que se VENDIÓ. En una venta cross-currency eso
dejaba las dos puntas en unidades distintas dentro de la misma fila, sin ningún
campo que lo dijera (`fx_to_usd` se estampa sólo en ventas ARS).

Reportado por un usuario de IOL (2026-08-06) con un GD30 real: compró a 0,3430
DÓLARES por lámina y vendió a 68,6415 PESOS, y la app le mostraba
"US$0,34 → US$68,64" con −82% de pérdida. Y al revés: un lote comprado a 71,98
pesos vendido a 0,3617 dólares se veía como una caída del 99% cuando en realidad
la fila daba +611% de resultado.

QUÉ SE ARREGLÓ
──────────────
`entry_invested` ya viene convertido a la moneda de la venta (es con lo que se
calcula el P&L), así que dividirlo por la cantidad da el precio de entrada en esa
misma moneda. Con eso la fila cierra sola: en el GD30 reportado quedó
73,75 → 68,64 = −6,9%, que es exactamente el pnl_pct que la fila ya mostraba.

El P&L NO cambia por este arreglo: siempre se calculó con `entry_invested`, nunca
con `entry_price`. Estos tests lo verifican explícitamente.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class _CruzadaBase(_Base):
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _ventas(self, asset):
        return [dict(r) for r in self.conn.execute(
            "SELECT entry_price, exit_price, quantity, pnl_usd, pnl_pct, currency "
            "FROM operations WHERE user_id=? AND asset=? AND op_type='Venta' "
            "ORDER BY date, id", (self.uid, asset))]


class CompraPesosVentaDolaresTest(_CruzadaBase):
    """Compró en pesos, vendió en dólares: el precio de entrada tiene que quedar
    expresado en DÓLARES, igual que el de salida."""

    def test_la_fila_queda_en_una_sola_moneda(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5000,500000,,,0,ARS,",   # 500.000 ARS = 500 USD al tc 1000
            "2025-06-01,VENTA,IOL,KO,100,8,800,,,0,USD,",          # 800 USD
        ), rebuild=True)
        v = self._ventas("KO")
        self.assertEqual(len(v), 1)
        fila = v[0]

        # 500.000 ARS / 1000 = 500 USD de costo → 5,00 USD por nominal.
        self.assertAlmostEqual(fila["entry_price"], 5.0, places=4,
                               msg="el precio de entrada tiene que estar en dólares, como el de salida")
        self.assertAlmostEqual(fila["exit_price"], 8.0, places=4)
        # Y el P&L es el de siempre: 800 - 500 = 300.
        self.assertAlmostEqual(fila["pnl_usd"], 300.0, places=2)

    def test_el_porcentaje_de_la_fila_cierra_con_los_precios(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,KO,100,8,800,,,0,USD,",
        ), rebuild=True)
        fila = self._ventas("KO")[0]
        pct_por_precios = (fila["exit_price"] / fila["entry_price"] - 1) * 100
        self.assertAlmostEqual(pct_por_precios, fila["pnl_pct"], places=1,
                               msg="el % de la fila tiene que poder derivarse de sus dos precios")


class CompraDolaresVentaPesosTest(_CruzadaBase):
    """El sentido inverso — el caso exacto que reportó el usuario con GD30."""

    def test_la_fila_queda_en_una_sola_moneda(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5,500,,,0,USD,",          # 500 USD = 500.000 ARS al tc 1000
            "2025-06-01,VENTA,IOL,KO,100,6000,600000,,,0,ARS,",     # 600.000 ARS
        ), rebuild=True)
        fila = self._ventas("KO")[0]

        # 500 USD * 1000 = 500.000 ARS de costo → 5.000 ARS por nominal.
        self.assertAlmostEqual(fila["entry_price"], 5000.0, places=2,
                               msg="el precio de entrada tiene que estar en pesos, como el de salida")
        self.assertAlmostEqual(fila["exit_price"], 6000.0, places=2)
        # P&L de siempre: (600.000 - 500.000) / 1000 = 100 USD.
        self.assertAlmostEqual(fila["pnl_usd"], 100.0, places=2)

    def test_el_porcentaje_de_la_fila_cierra_con_los_precios(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5,500,,,0,USD,",
            "2025-06-01,VENTA,IOL,KO,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        fila = self._ventas("KO")[0]
        pct_por_precios = (fila["exit_price"] / fila["entry_price"] - 1) * 100
        self.assertAlmostEqual(pct_por_precios, fila["pnl_pct"], places=1)


class MismaMonedaNoSeToracTest(_CruzadaBase):
    """La enorme mayoría de las ventas son de la misma moneda: ahí el precio de
    entrada tiene que seguir siendo exactamente el del lote, sin tocar."""

    def test_venta_en_pesos_de_lote_en_pesos(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,KO,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        fila = self._ventas("KO")[0]
        self.assertAlmostEqual(fila["entry_price"], 5000.0, places=4,
                               msg="sin cruce de monedas el precio de entrada es el del lote, intacto")

    def test_venta_en_dolares_de_lote_en_dolares(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5,500,,,0,USD,",
            "2025-06-01,VENTA,IOL,KO,100,8,800,,,0,USD,",
        ), rebuild=True)
        fila = self._ventas("KO")[0]
        self.assertAlmostEqual(fila["entry_price"], 5.0, places=4)


class VentaParcialTest(_CruzadaBase):
    """Con una venta parcial el precio es por unidad, así que no tiene que
    depender de cuántos nominales entraron en el chunk."""

    def test_el_precio_unitario_no_depende_del_tamano_del_chunk(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,KO,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,KO,40,8,320,,,0,USD,",
            "2025-07-01,VENTA,IOL,KO,60,9,540,,,0,USD,",
        ), rebuild=True)
        v = self._ventas("KO")
        self.assertEqual(len(v), 2)
        for fila in v:
            self.assertAlmostEqual(fila["entry_price"], 5.0, places=4,
                                   msg="el mismo lote da el mismo precio unitario en las dos ventas")


if __name__ == "__main__":
    unittest.main()
