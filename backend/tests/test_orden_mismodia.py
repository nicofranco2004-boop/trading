"""¿El empate de fecha ya decidía plata ANTES del pool único?

Los dos casos que reportó el verificador usan dos fills del MISMO día. Como
`import_normalized_tx.date` es YYYY-MM-DD sin hora (schema.py:205), todas las
operaciones de un día empatan y el desempate lo termina fijando `n.id ASC`, o
sea el orden en que llegó la fila.

Esta prueba aísla la pregunta: ese empate, ¿ya cambiaba la plata en el caso
SIMPLE de una sola moneda, sin nada cross-currency? Si sí, el defecto es
preexistente y estructural (falta la hora), y el pool único sólo lo expone a
más ventas. Si no, lo introduje yo.

RESPUESTA MEDIDA (2026-08-06): es PREEXISTENTE, y grande. Los dos tests fallan
IDÉNTICO en el motor de producción y en el del pool único: permutar dos fills
del mismo día en UNA SOLA MONEDA da +400,00 o −400,00 USD según cuál se imprimió
primero. Cambia de ganancia a pérdida.

Sobre un export real de IOL (5.002 ventas), permutar filas sólo DENTRO de cada
día mueve la P&L total del usuario entre 4.725,92 y 21.577,00 USD — en el motor
que hoy está en producción.

Van marcados `expectedFailure` para que la suite quede verde SIN tapar el
defecto: el día que alguien lo arregle, estos tests pasan a XPASS y avisan.
NO los borres para "poner la suite en verde" — están rojos a propósito.

QUÉ HABRÍA QUE ARREGLAR: el desempate de `_full_events`
(backend/importing/rebuild.py, ORDER BY … n.id ASC) usa el AUTOINCREMENT de
import_normalized_tx, o sea el orden en que llegó la fila — que depende de cómo
imprimió el broker y de qué archivo se subió primero. Necesita un criterio
estable derivado del CONTENIDO de la operación, o la hora real (hoy sólo la
mandan Balanz-Órdenes y Binance; `date` es YYYY-MM-DD, schema.py:205).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class EmpateMismoDiaUnaSolaMonedaTest(_Base):
    """Todo en pesos. Ni una fila en dólares. Nada que ver con el pool único."""
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _pnl(self, asset="ZZ"):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) p FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta'", (self.uid, asset)).fetchone()
        return round(float(r["p"] or 0), 2)

    # Dos fills del mismo día a precios muy distintos, y una venta que consume
    # sólo uno de los dos.
    FILL_BARATO = "2024-01-10,COMPRA,IOL,ZZ,100,1000,100000,,,0,ARS,"
    FILL_CARO = "2024-01-10,COMPRA,IOL,ZZ,100,9000,900000,,,0,ARS,"
    VENTA = "2024-06-01,VENTA,IOL,ZZ,100,5000,500000,,,0,ARS,"

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver el docstring del módulo
    def test_permutar_dos_fills_del_mismo_dia_en_una_sola_moneda(self):
        self._import(_csv(self.FILL_BARATO, self.FILL_CARO, self.VENTA), rebuild=True)
        barato_primero = self._pnl()

        self.tearDown()
        self.setUp()

        self._import(_csv(self.FILL_CARO, self.FILL_BARATO, self.VENTA), rebuild=True)
        caro_primero = self._pnl()

        self.assertEqual(
            barato_primero, caro_primero,
            f"con UNA SOLA MONEDA, permutar dos fills del mismo día ya cambia la "
            f"P&L: {barato_primero} vs {caro_primero}")

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver el docstring del módulo
    def test_partir_en_dos_tandas_en_una_sola_moneda(self):
        self._import(_csv(self.FILL_BARATO), rebuild=True)
        self._import(_csv(self.FILL_CARO, self.VENTA), rebuild=True)
        barato_primero = self._pnl()

        self.tearDown()
        self.setUp()

        self._import(_csv(self.FILL_CARO), rebuild=True)
        self._import(_csv(self.FILL_BARATO, self.VENTA), rebuild=True)
        caro_primero = self._pnl()

        self.assertEqual(
            barato_primero, caro_primero,
            f"con UNA SOLA MONEDA, subir los fills en distinto orden de tandas ya "
            f"cambia la P&L: {barato_primero} vs {caro_primero}")


if __name__ == "__main__":
    unittest.main()
