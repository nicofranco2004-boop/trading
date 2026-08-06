"""El eje `s` de /api/admin/diagnose-sell-fx necesita que `entry_price` esté en
la moneda del LOTE. Este test lo fija para que nadie lo rompa sin enterarse.

QUÉ PROTEGE
───────────
`diagnose-sell-fx` clasifica cada venta para decidir si su P&L está corrompido
por el tipo de cambio y cuánto habría que repararlo. Su segundo eje es

    invested = 100 * pnl_usd / pnl_pct        (queda en DÓLARES)
    ratio_h  = entry_price * quantity / invested
    s        = ratio_h / T_rec

y su docstring dice para qué existe (main.py:13683-13685): "es lo que separa el
lote-USD-vendido-en-ARS (s≈1/T) del lote-ARS-vendido-en-ARS (s≈1)".

Eso FUNCIONA sólo porque `entry_price` está en la moneda en que se COMPRÓ:
  · lote ARS vendido en ARS → entry_price*Q en pesos / invested en USD → s ≈ 1
  · lote USD vendido en ARS → entry_price*Q en USD  / invested en USD → s ≈ 1/T
Si `entry_price` pasara a estar siempre en la moneda de la VENTA, los dos darían
s ≈ 1 y los buckets colapsarían.

POR QUÉ EXISTE ESTE ARCHIVO
───────────────────────────
Porque ya pasó. El 2026-08-06 se implementó justamente eso —convertir
`entry_price` a la moneda de la venta, para que la fila no mostrara
"US$0,34 → US$68,64"— y hubo que revertirlo: medido sobre un GD30 real, la
reparación simulada pasaba de +383,42 USD (la aritmética exacta) a −23.150,24
sobre una operación cuyo costo total fue 3.430 USD, y `B4B_MEP_COSTO_RANCIO`
dejaba de detectarse.

El problema de presentación sigue abierto y hay que arreglarlo — pero SIN tocar
la unidad de `entry_price`. Ver test_entry_price_moneda.py.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class EjeSDiscriminaLaMonedaDelLoteTest(_Base):
    BROKER = "IOL"
    BROKER_CCY = "ARS"
    TC = 1000.0

    def setUp(self):
        super().setUp()
        self._set_tc_blue(self.TC)

    def _venta(self, asset):
        r = self.conn.execute(
            "SELECT entry_price, exit_price, quantity, pnl_usd, pnl_pct, commissions "
            "FROM operations WHERE user_id=? AND asset=? AND op_type='Venta' "
            "ORDER BY date, id LIMIT 1", (self.uid, asset)).fetchone()
        return dict(r) if r else None

    def _s(self, fila):
        """El mismo cálculo que hace el endpoint (main.py:13797-13818)."""
        pnl, pct = float(fila["pnl_usd"]), float(fila["pnl_pct"])
        invested = 100.0 * pnl / pct
        den = pnl + invested
        num = float(fila["exit_price"]) * float(fila["quantity"]) - float(fila["commissions"] or 0)
        T = num / den
        ratio_h = float(fila["entry_price"]) * float(fila["quantity"]) / invested
        return ratio_h / T

    def test_lote_en_pesos_vendido_en_pesos_da_s_cercano_a_1(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,AA,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,AA,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        s = self._s(self._venta("AA"))
        self.assertAlmostEqual(s, 1.0, delta=0.05,
                               msg=f"lote ARS vendido en ARS tiene que dar s≈1, dio {s:.4f}")

    def test_lote_en_dolares_vendido_en_pesos_da_s_cercano_a_1_sobre_T(self):
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,BB,100,5,500,,,0,USD,",
            "2025-06-01,VENTA,IOL,BB,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        s = self._s(self._venta("BB"))
        esperado = 1.0 / self.TC
        self.assertLess(
            s, 0.1,
            msg=(f"lote USD vendido en ARS tiene que dar s≈1/T (≈{esperado:.6f}), dio {s:.4f}. "
                 f"Si dio ≈1, alguien puso entry_price en la moneda de la VENTA y el "
                 f"clasificador de diagnose-sell-fx ya no distingue los dos casos — "
                 f"leé el docstring de este archivo antes de 'arreglar' el test."))

    def test_los_dos_casos_no_pueden_colapsar(self):
        # El invariante de verdad: sean cuales sean los umbrales, los dos tienen
        # que estar SEPARADOS por al menos un orden de magnitud.
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,AA,100,5000,500000,,,0,ARS,",
            "2025-06-01,VENTA,IOL,AA,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        s_ars = self._s(self._venta("AA"))
        self._import(_csv(
            "2025-01-10,COMPRA,IOL,BB,100,5,500,,,0,USD,",
            "2025-06-01,VENTA,IOL,BB,100,6000,600000,,,0,ARS,",
        ), rebuild=True)
        s_usd = self._s(self._venta("BB"))
        self.assertGreater(
            s_ars / s_usd, 10.0,
            msg=(f"los dos buckets colapsaron: s(lote ARS)={s_ars:.4f} contra "
                 f"s(lote USD)={s_usd:.4f}. diagnose-sell-fx deja de poder "
                 f"clasificar y sus reparaciones simuladas dan números imposibles."))


if __name__ == "__main__":
    unittest.main()
