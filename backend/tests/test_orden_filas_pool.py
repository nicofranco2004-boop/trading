"""¿El ORDEN de las filas dentro del archivo cambia la plata?

Un verificador reporto que al sacar el cap del presupuesto, el desempate por
`n.id ASC` (o sea el orden en que llego la fila) pasa a decidir cual lote paga
una venta cross-currency. Antes eso solo desempataba entre lotes de la MISMA
moneda; ahora decide entre monedas, y por lo tanto decide un costo convertido
por FX.

Si es cierto, es un bloqueante: el mismo archivo, con las filas impresas al
reves, le daria al usuario dos P&L distintas.

RESULTADO MEDIDO (2026-08-06). Es cierto, pero la raiz NO es el pool unico: es
que `date` no tiene hora (schema.py:205), asi que TODAS las operaciones de un
dia empatan y el desempate lo termina fijando `n.id ASC` = el orden en que
llego la fila. Ver test_orden_mismodia.py: el MISMO defecto se reproduce con
UNA SOLA MONEDA (+400 contra -400 USD) identico en los dos motores.

Lo que si hace el pool unico es AMPLIFICAR la superficie: antes el empate solo
decidia entre lotes de la misma moneda, ahora tambien decide cual moneda paga
la venta, y por lo tanto un costo convertido por FX.

Medido sobre el export real de IOL (5.002 ventas), permutando filas dentro de
cada dia, en el motor QUE HOY ESTA EN PRODUCCION: la P&L total del usuario va
de 4.725,92 a 21.577,00 USD segun el orden. La inestabilidad ya esta desplegada
y es de esa magnitud.

Los tres van `expectedFailure`: son defectos ABIERTOS, no una regresion de este
commit. El dia que se arregle el desempate, pasan a XPASS y avisan. NO los
borres para poner la suite en verde — estan rojos a proposito.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from test_rebuild_fifo import _Base, _csv  # noqa: E402


class OrdenDeFilasTest(_Base):
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _pnl(self, asset="KK"):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) p FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta'", (self.uid, asset)).fetchone()
        return round(float(r["p"] or 0), 2)

    # Dos fills del MISMO dia a precios distintos, mas un lote en la otra moneda,
    # mas una venta que obliga a cruzar. Lo unico que cambia entre los dos casos
    # es cual de los dos fills se imprimio primero en el archivo.
    FILL_A = "2024-01-10,COMPRA,IOL,KK,100,8.50,850,,,0,USD,"
    FILL_B = "2024-01-10,COMPRA,IOL,KK,100,9.20,920,,,0,USD,"
    RESTO = (
        "2024-02-01,COMPRA,IOL,KK,50,10000,500000,,,0,ARS,",
        "2024-06-01,VENTA,IOL,KK,150,12000,1800000,,,0,ARS,",
    )

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
    def test_permutar_dos_filas_no_puede_cambiar_la_plata(self):
        self._import(_csv(self.FILL_A, self.FILL_B, *self.RESTO), rebuild=True)
        primero = self._pnl()
        abierto_1 = self._open_qty("KK")

        self.tearDown()
        self.setUp()

        self._import(_csv(self.FILL_B, self.FILL_A, *self.RESTO), rebuild=True)
        segundo = self._pnl()
        abierto_2 = self._open_qty("KK")

        self.assertEqual(abierto_1, abierto_2, "los nominales abiertos no dependen del orden")
        self.assertEqual(
            primero, segundo,
            f"el mismo archivo con dos filas permutadas da P&L distinta: "
            f"{primero} vs {segundo} (delta {round(segundo - primero, 2)} USD)")


class OrdenDeTandasTest(_Base):
    """Lo mismo pero partiendo el historial en dos imports, que es como el usuario
    sube el export ano por ano."""
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _pnl(self, asset="JJ"):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) p FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta'", (self.uid, asset)).fetchone()
        return round(float(r["p"] or 0), 2)

    A = "2024-01-10,COMPRA,IOL,JJ,10,2,20,,,0,USD,"
    B = "2024-01-10,COMPRA,IOL,JJ,10,50,500,,,0,USD,"
    RESTO = (
        "2024-02-01,COMPRA,IOL,JJ,5,1000,5000,,,0,ARS,",
        "2024-06-01,VENTA,IOL,JJ,10,3000,30000,,,0,ARS,",
    )

    @unittest.expectedFailure   # DEFECTO ABIERTO — ver docstring del modulo
    def test_partir_el_historial_en_dos_tandas_no_puede_cambiar_la_plata(self):
        self._import(_csv(self.A), rebuild=True)
        self._import(_csv(self.B, *self.RESTO), rebuild=True)
        primero = self._pnl()

        self.tearDown()
        self.setUp()

        self._import(_csv(self.B), rebuild=True)
        self._import(_csv(self.A, *self.RESTO), rebuild=True)
        segundo = self._pnl()

        self.assertEqual(
            primero, segundo,
            f"subir el mismo historial en distinto orden de tandas da P&L distinta: "
            f"{primero} vs {segundo} (delta {round(segundo - primero, 2)} USD)")


class PoolEsFifoPorFechaTest(_Base):
    """El modelo declarado del cambio es 'un activo es UN pool'. Entonces la venta
    tiene que consumir el lote MAS VIEJO del pool, sin importar en que moneda se
    hizo la venta."""
    BROKER = "IOL"
    BROKER_CCY = "ARS"

    def setUp(self):
        super().setUp()
        self._set_tc_blue(1000.0)

    def _pnl(self, asset="NN"):
        r = self.conn.execute(
            "SELECT COALESCE(SUM(pnl_usd),0) p FROM operations "
            "WHERE user_id=? AND asset=? AND op_type='Venta'", (self.uid, asset)).fetchone()
        return round(float(r["p"] or 0), 2)

    COMPRAS = (
        "2020-01-01,COMPRA,IOL,NN,100,1000,100000,,,0,ARS,",   # el mas viejo
        "2024-01-01,COMPRA,IOL,NN,100,50,5000,,,0,USD,",
    )

    @unittest.expectedFailure   # DEFECTO ABIERTO — preexistente, falla igual en prod
    def test_la_moneda_de_la_venta_no_decide_que_lote_se_consume(self):
        # Misma economia expresada en las dos monedas: 100 nominales a 60 USD,
        # o los mismos 100 a 60.000 ARS (= 60 USD al tc 1000).
        self._import(_csv(*self.COMPRAS,
                          "2025-01-01,VENTA,IOL,NN,100,60,6000,,,0,USD,"), rebuild=True)
        en_usd = self._pnl()

        self.tearDown()
        self.setUp()

        self._import(_csv(*self.COMPRAS,
                          "2025-01-01,VENTA,IOL,NN,100,60000,6000000,,,0,ARS,"), rebuild=True)
        en_ars = self._pnl()

        self.assertEqual(
            en_usd, en_ars,
            f"la misma venta expresada en distinta moneda da P&L distinta: "
            f"USD {en_usd} vs ARS {en_ars}. FIFO por fecha tiene que consumir el "
            f"lote de 2020 en los dos casos.")


if __name__ == "__main__":
    unittest.main()
