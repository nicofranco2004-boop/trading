"""Un pase entre brokers no vuelve «reconstruible» una cuenta cargada a mano (F.2 #46).

La historia a mercado sólo se reconstruye en las cuentas que importaron un archivo:
de ahí sale qué títulos había cada fin de mes (`backfill_user`, «Cuenta reconstruible
solo si hay import confirmado»). Una cuenta 100 % cargada a mano no se reconstruye:
su curva son las fotos que midió el cron.

Un pase entre brokers escribe dos lotes de import confirmados (A.7), pero son de la
app, no de un archivo. Si contaran como import, mover un lote de una cuenta a mano:
  · la volvía reconstruible, y la reconstrucción la armaba con lo que ve en el
    registro —sólo el lote que llegó al broker nuevo—, sin el resto de la cartera;
  · y al deshacer el pase la cuenta volvía a «sin import», y la limpieza de fotos
    reconstruidas borraba las que habían reemplazado a las sintéticas.

Por eso los lotes de un pase no cuentan para decidir si hay import (D.13.4), y la
MISMA regla decide si las fotos reconstruidas que quedaron ya no valen: una cuenta
con un import de verdad y un pase, que revierte su import, se queda sin las fotos
que describían ese import aunque el pase siga.

CAMINO. Los lotes a mano entran por HTTP con un token real (`POST /api/positions`);
las fotos del cron se plantan con el mismo UPSERT del cron; la historia se arma con
`main._reconstruir_mtm`, la misma función que corre después de cada pedido.
Todavía no hay endpoint que haga ni deshaga un pase (llegan en E6 y E7): las filas
del pase entran por el camino del confirm (`store_preview_txs` → `persist_batch`)
como las va a escribir `aplicar_plan`, y el deshacer se hace como C.8 (lotes en
`reverted`, `deshecho_at`, el lote vuelve a su broker). ⚠️ En E6/E7 se agrega la
versión por HTTP de estos mismos casos (`POST /api/positions/traspaso` y
`/deshacer`), en `test_mover_entre_brokers.py`.

Corre con: cd backend && python3 -m pytest tests/test_cuenta_manual_no_se_vuelve_reconstruible.py
"""
import io
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import main  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from test_holdings_asof_tipo_mezclado_y_venta_manual import _Cuenta  # noqa: E402

# Fotos del cron (medidas), fecha → (valor, aportado).
FOTOS_DEL_CRON = {"2025-03-31": (1600.0, 1500.0), "2025-06-30": (1700.0, 1500.0),
                  "2025-09-30": (1800.0, 1500.0)}

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


class _CuentaAMano(_Cuenta):

    def _plantar_fotos_del_cron(self):
        with self.conn:
            for d, (valor, aportado) in FOTOS_DEL_CRON.items():
                self.conn.execute(
                    """INSERT INTO snapshots (user_id, date, total_value, total_invested,
                           net_deposited, fx_to_usd_blue, holdings_json, source, base, apto)
                       VALUES (?,?,?,?,?,1200,'[{"asset": "MSFT", "value_usd": 1}]',
                               'cron','mercado',1)
                       ON CONFLICT(user_id, date) DO UPDATE SET
                           total_value=excluded.total_value,
                           total_invested=excluded.total_invested,
                           net_deposited=excluded.net_deposited,
                           fx_to_usd_blue=excluded.fx_to_usd_blue,
                           holdings_json=excluded.holdings_json,
                           source='cron', base='mercado', apto=1""",
                    (self.uid, d, valor, aportado, aportado))

    def _fotos_del_cron(self):
        return {r["date"]: (r["total_value"], r["net_deposited"]) for r in self.conn.execute(
            "SELECT date, total_value, net_deposited FROM snapshots WHERE user_id=? "
            "AND source='cron'", (self.uid,)).fetchall()}

    def _reconstruidas(self):
        return self.conn.execute("SELECT COUNT(*) c FROM snapshots WHERE user_id=? AND source=?",
                                 (self.uid, bf.MTM_SOURCE)).fetchone()["c"]

    def _hay_import_reconstruible(self):
        return self.conn.execute(bf._HAY_IMPORT_RECONSTRUIBLE, (self.uid,)).fetchone() is not None

    def _lote_a_mano(self):
        """5 MSFT cargados a mano en IBKR el 01/02/2025 (con el autodepósito del alta)."""
        self._ok(self.http.post("/api/positions", headers=self.h, json={
            "broker": "IBKR", "asset": "MSFT", "quantity": 5, "buy_price": 300,
            "invested": 1500, "entry_date": "2025-02-01", "currency": "USD"}))

    def _pase_del_lote_a_mano(self):
        """El lote a mano de MSFT pasa de IBKR a Schwab el 10/06/2025."""
        self._lote_a_mano()
        return self._pasar_el_lote()

    def _pasar_el_lote(self):
        self._plantar_fotos_del_cron()
        self.foto = dict(self.conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset='MSFT' AND is_cash=0",
            (self.uid,)).fetchone())
        with self.conn:
            self.conn.execute("DELETE FROM positions WHERE id=?", (self.foto["id"],))
        lote = {"origen": "a_mano", "lote_id": self.foto["id"], "broker": "IBKR",
                "broker_destino": "Schwab", "fila_origen": None, "cantidad": 5.0,
                "invested": 1500.0, "commissions": 0.0, "parcial": False, "foto": self.foto}
        return self._pase(fecha="2025-06-10", de="IBKR", a="Schwab", activo="MSFT",
                          llegadas=[(5.0, 300.0, 1500.0, "2025-02-01")], lotes_receta=[lote],
                          valor_usd=1900.0, costo_usd=1500.0)

    def _deshacer(self, pid, lote_a, lote_b):
        """Lo que hace el deshacer (C.8) con un lote cargado a mano: los dos lotes del
        pase a `reverted`, el lote vuelve a su broker con su foto, `deshecho_at`."""
        with self.conn:
            self.conn.execute("UPDATE import_batches SET status='reverted' WHERE id IN (?,?)",
                              (lote_a, lote_b))
            self.conn.execute("DELETE FROM positions WHERE user_id=? AND broker='Schwab' "
                              "AND is_cash=0", (self.uid,))
            cols = ", ".join(self.foto)
            self.conn.execute(f"INSERT INTO positions ({cols}) VALUES "
                              f"({', '.join('?' * len(self.foto))})", tuple(self.foto.values()))
            self.conn.execute("UPDATE traspasos_a_mano SET deshecho_at=datetime('now') "
                              "WHERE id=?", (pid,))
            main._recalc_pnl_realized_from_ops(self.conn, self.uid)


class CuentaCargadaAMano(_CuentaAMano):

    def test_el_pase_no_la_vuelve_reconstruible(self):
        pid, lote_a, lote_b = self._pase_del_lote_a_mano()
        # Control: los dos lotes del pase están confirmados. Sin la regla, la cuenta
        # tendría «import confirmado» y se reconstruiría.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM import_batches WHERE user_id=? AND status='confirmed'",
            (self.uid,)).fetchone()["c"], 2)
        self.assertFalse(self._hay_import_reconstruible())
        res = main._reconstruir_mtm(self.uid)
        self.assertEqual(res, {"reconstruida": False,
                               "motivo": "sin import confirmado (cuenta manual)"})
        self.assertEqual(self._reconstruidas(), 0)
        self.assertEqual(self._fotos_del_cron(), FOTOS_DEL_CRON)

    def test_deshacer_el_pase_no_borra_fotos(self):
        pid, lote_a, lote_b = self._pase_del_lote_a_mano()
        main._reconstruir_mtm(self.uid)
        self._deshacer(pid, lote_a, lote_b)
        res = main._reconstruir_mtm(self.uid)
        self.assertFalse(res["reconstruida"], res)
        self.assertEqual(res.get("snapshots_borrados", 0), 0, res)
        self.assertEqual(self._reconstruidas(), 0)
        self.assertEqual(self._fotos_del_cron(), FOTOS_DEL_CRON)


class CuentaConImportYPase(_CuentaAMano):
    """Con un archivo importado de verdad la cuenta SÍ se reconstruye, haya o no un
    pase. Y si revierte ese archivo, las fotos que lo describían se van aunque el pase
    siga: la regla que decide «hay import» es la misma que decide que ya no valen."""

    def _importar(self, *filas):
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data={"format": "rendi_generic", "broker": "IBKR"}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        sid = p.json()["session_id"]
        self._ok(self.http.post("/api/imports/confirm", headers=self.h, json={
            "session_id": sid, "skip_row_indices": [], "aprobar_tickers": []}))
        return sid

    def test_revertir_el_import_borra_sus_fotos_aunque_quede_el_pase(self):
        """El lote a mano de febrero (y su autodepósito) le da contabilidad a febrero,
        antes del archivo de marzo. Revertir el archivo borra las fotos desde su
        primera fecha (`revert_batch`), pero no la reconstruida de febrero: ésa la
        tiene que borrar la reconstrucción siguiente, porque la cuenta ya no tiene
        import. Con el pase contado como import, febrero quedaba para siempre."""
        self._lote_a_mano()
        sid = self._importar("2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                             "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,")
        self._pasar_el_lote()
        self.assertTrue(self._hay_import_reconstruible())
        self._reconstruir()
        febrero = "SELECT 1 FROM snapshots WHERE user_id=? AND source=? AND date='2025-02-28'"
        self.assertIsNotNone(self.conn.execute(febrero, (self.uid, bf.MTM_SOURCE)).fetchone(),
                             "control: febrero tiene foto reconstruida antes de revertir")
        # La reconstrucción que el revert lanza en otro hilo al terminar (la misma
        # `_reconstruir_mtm` de abajo) se corre a mano, para ver el estado entre las dos.
        with mock.patch.object(main, "_reconstruir_mtm_post_import", return_value=None):
            self._ok(self.http.post(f"/api/imports/{sid}/revert", headers=self.h))
        self.assertIsNotNone(self.conn.execute(febrero, (self.uid, bf.MTM_SOURCE)).fetchone(),
                             "control: el revert no borra la foto de febrero")
        self.assertFalse(self._hay_import_reconstruible())
        res = main._reconstruir_mtm(self.uid)
        self.assertFalse(res["reconstruida"], res)
        self.assertEqual(self._reconstruidas(), 0)


if __name__ == "__main__":
    unittest.main()
