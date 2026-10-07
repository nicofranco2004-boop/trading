"""Una compra o una venta borrada sale de la historia reconstruida a mercado.

Borrar una compra importada le pone la lápida (`excluded_at`) a su fila y el
recálculo saca la posición de la cartera. Pero el reconstructor de las fotos de
fin de mes (`_holdings_asof`) filtraba el import confirmado y NO la lápida: la
compra borrada seguía en cada foto, valuada a mercado. Medido (3fbb2f95): import
de 10 AAPL y 10 MSFT a 100, borrar la compra de MSFT → la cartera mostraba sólo
AAPL y la curva 10.300 / 10.700 / 11.050 (MSFT a mercado) en vez de 10.000 /
10.200 / 10.350. Con una VENTA borrada pasa lo contrario: la foto seguía sin las
acciones vendidas y con la plata de la venta.

Ahora el reconstructor lee `importing.schema.TX_VIVAS` (import confirmado y sin
lápida), el mismo fragmento que el resto de los lectores, y la historia se rehace
al terminar el pedido que borró (`_ReconstruirAlTerminar`).

Todo por las puertas reales: import por `POST /api/imports/preview` + `/confirm`
con el hilo de reconstrucción, y cada camino de borrado que tiene la app
(Movimientos, Cartera, el historial del activo, la operación de venta, y sus
deshacer). Sólo se reemplaza lo que sale a internet. Cada foto se compara contra
una cuenta escrita a mano.

(Reescrito el 2026-10-07: la versión original se perdió con el worktree de la
sesión que hizo el arreglo.)
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from tests.test_reconstruccion_sigue_a_la_contabilidad import _Despues  # noqa: E402

# Cierre de cada mes: AAPL 200 en marzo de 2025 y +10 por mes; MSFT 300 y +20.
def _serie(base, paso):
    return {f"{y}-{m:02d}": base + paso * min(max((y - 2025) * 12 + m - 3, 0), 7)
            for y in (2025, 2026) for m in range(1, 13)}


PRECIO = {"AAPL": _serie(200.0, 10.0), "MSFT": _serie(300.0, 20.0)}

CUENTA = (
    "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
    "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,",
    "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,",
    "2025-07-10,VENTA,IBKR,AAPL,5,240,1200,,,0,USD,",
)


def esperado(fecha, sin_msft=False, sin_venta=False):
    """(valor, aportado) de la foto de `fecha`, escrito a mano."""
    efectivo = 10000 - 2000 - (0 if sin_msft else 3000)
    aapl = 10
    if not sin_venta and fecha >= "2025-07-10":
        efectivo += 1200
        aapl -= 5
    ym = fecha[:7]
    valor = efectivo + aapl * PRECIO["AAPL"][ym] + (0 if sin_msft else 10 * PRECIO["MSFT"][ym])
    return (round(valor, 2), 10000.0)


class _ConDosActivos(_Despues):

    def setUp(self):
        super().setUp()
        bf._fetch_monthly_close = lambda key, start: dict(PRECIO.get(key, {}))
        self._importar(*CUENTA)

    def _cada_foto(self, **cual):
        filas = self._filas()
        self.assertTrue(filas)
        for d, v, n in filas:
            self.assertEqual((v, n), esperado(d, **cual), d)
        fotos = {d: (v, n) for d, v, n in filas}
        for d in ("2025-03-31", "2025-07-31", "2025-09-30"):
            self.assertIn(d, fotos)
        self.assertEqual(fotos, self._reconstruccion_nueva())
        return fotos

    def _composicion(self):
        conn = main.get_db()
        try:
            return {r["date"]: {h["asset"] for h in json.loads(r["holdings_json"] or "[]")}
                    for r in conn.execute(
                        "SELECT date, holdings_json FROM snapshots WHERE user_id=? "
                        "AND source='mtm_backfill'", (self.uid,)).fetchall()}
        finally:
            conn.close()

    def _link(self, op, fecha, col):
        conn = main.get_db()
        try:
            return conn.execute(
                f"SELECT l.{col} AS x FROM import_op_links l JOIN import_normalized_tx n "
                "ON n.batch_id=l.batch_id AND n.raw_row_id=l.raw_row_id JOIN import_batches b "
                "ON b.id=n.batch_id WHERE b.user_id=? AND n.operation_type=? AND n.date=? "
                f"AND l.{col} IS NOT NULL", (self.uid, op, fecha)).fetchone()["x"]
        finally:
            conn.close()


class LaCompraBorrada(_ConDosActivos):

    def _sin_msft(self):
        self._cada_foto(sin_msft=True)
        for fecha, activos in self._composicion().items():
            self.assertNotIn("MSFT", activos, fecha)

    def test_antes_de_borrar_estan_las_dos(self):
        self._cada_foto()
        self.assertIn("MSFT", self._composicion()["2025-03-31"])

    def test_desde_movimientos(self):
        self._pedir("delete", f"/api/movements/tx-{self._tx('BUY', '2025-03-05')}")
        self._sin_msft()

    def test_desde_cartera(self):
        self._pedir("delete", f"/api/positions/{self._link('BUY', '2025-03-05', 'position_id')}")
        self._sin_msft()

    def test_borrando_el_historial_del_activo(self):
        self._pedir("delete", "/api/assets/history", params={"asset": "MSFT"})
        self._sin_msft()

    def test_y_al_deshacer_vuelve(self):
        r = self._pedir("delete", f"/api/positions/{self._link('BUY', '2025-03-05', 'position_id')}")
        self._sin_msft()
        self._pedir("post", f"/api/operations/undo/{r.json()['undo_token']}")
        self._cada_foto()


class LaVentaBorrada(_ConDosActivos):
    """Sin la venta, desde julio las 5 AAPL siguen en la cartera y la plata de la
    venta no entró."""

    def test_desde_movimientos(self):
        self._pedir("delete", f"/api/movements/tx-{self._tx('SELL', '2025-07-10')}")
        self._cada_foto(sin_venta=True)

    def test_desde_la_operacion(self):
        self._pedir("delete", f"/api/operations/{self._link('SELL', '2025-07-10', 'operation_id')}")
        self._cada_foto(sin_venta=True)

    def test_y_al_deshacer_vuelve(self):
        r = self._pedir("delete",
                        f"/api/operations/{self._link('SELL', '2025-07-10', 'operation_id')}")
        self._cada_foto(sin_venta=True)
        self._pedir("post", f"/api/operations/undo/{r.json()['undo_token']}")
        self._cada_foto()


if __name__ == "__main__":
    unittest.main()
