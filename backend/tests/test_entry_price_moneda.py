"""DEFECTO ABIERTO: en una venta cruzada las dos puntas de la fila están en monedas distintas.

QUÉ SE VE MAL
─────────────
`operations.entry_price` guarda el precio del lote en la moneda en que se COMPRÓ
y `exit_price` en la que se VENDIÓ. En una venta cross-currency las dos puntas
quedan en unidades distintas dentro de la misma fila, sin ningún campo que lo
diga (`fx_to_usd` se estampa sólo en ventas ARS).

Reportado por un usuario de IOL (2026-08-06) con un GD30 real: compró a 0,3430
DÓLARES la lámina y vendió a 68,6415 PESOS, y la app le mostraba
"US$0,34 → US$68,64" con −82%. Al revés, un lote comprado a 71,98 pesos y
vendido a 0,3617 dólares se ve como una caída del 99% cuando la fila da +611%.

POR QUÉ ESTOS TESTS ESTÁN EN ROJO A PROPÓSITO
─────────────────────────────────────────────
El arreglo evidente —convertir `entry_price` a la moneda de la venta usando
`entry_invested/take`— se implementó, se midió y se REVIRTIÓ el mismo día. No
porque estuviera mal calculado (el P&L no se movía en 502 ventas de un fuzz, y
la fila pasaba a cerrar sola: 73,75 → 68,64 = −6,9%, exacto el pnl_pct que ya
mostraba) sino porque ROMPE EL DIAGNÓSTICO:

`/api/admin/diagnose-sell-fx` deriva `invested` en dólares (100*pnl/pct) y usa
`s = (entry_price*Q/invested) / T_rec` como segundo eje — es literalmente "lo que
separa el lote-USD-vendido-en-ARS (s≈1/T) del lote-ARS-vendido-en-ARS (s≈1)"
(main.py:13683-13685). Poniendo `entry_price` siempre en la moneda de la venta,
los dos casos pasan a dar s≈1 y los buckets COLAPSAN. Medido sobre el GD30 del
reporte: la reparación simulada pasaba de +383,42 USD (que es la aritmética
exacta: 686.415/180 − 3.430) a −23.150,24 sobre una operación cuyo costo total
fue 3.430 — imposible. Y `B4B_MEP_COSTO_RANCIO` desaparecía del radar, cayendo
en "venta sana".

O sea: `entry_price` tiene hoy DOS consumidores con expectativas opuestas —la UI
lo quiere en la moneda de la fila, el diagnóstico lo quiere en la del lote— y no
se puede servir a los dos con un solo campo.

CÓMO SE ARREGLA DE VERDAD (pendiente)
─────────────────────────────────────
Sin sobrecargar el campo existente. Dos caminos, los dos aditivos:
  a) una columna `entry_ccy` en `operations` que diga en qué moneda está
     `entry_price`, y que el frontend formatee/convierta con eso; o
  b) estampar el FX del lote en las filas cruzadas (hoy `fx_to_usd` va NULL en
     las ventas USD) y convertir en la capa de presentación.
Cualquiera de los dos deja `entry_price` intacto y el diagnóstico sigue andando.
Ver test_diagnose_sell_fx_eje_s.py, que fija ese invariante.

Estos tests describen el comportamiento DESEADO. Van `expectedFailure`: el día
que se implemente bien, pasan a XPASS y avisan solos.
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

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
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

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
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

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
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

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
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

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
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
