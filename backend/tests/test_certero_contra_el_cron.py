"""Las fotos MEDIDAS corregidas tras borrar compras o ventas, contra el cron real.

La referencia no se escribe a mano: es el cron de verdad
(`snapshots_job.take_snapshot_for_user`) corrido sobre la contabilidad de DESPUÉS
del borrado, con los MISMOS precios y dólares que midieron la foto. Si la
corrección (`main._recalcular_mediciones`) es exacta, la foto corregida es la foto
que el cron sacaría hoy. Cuando la corrección no se puede afirmar, la foto tiene
que salir del certero (`source='medicion_vieja'`, `apto=0`), nunca quedarse como
medición con un número que el cron no daría.

El método y los casos salen de la auditoría del 2026-10-08, que encontró con él lo
que esta versión arregla:
  · borrar A, borrar B, deshacer A devolvía como medición válida una foto con la
    compra de B adentro (+US$ 1.000);
  · una foto que el cron volvió a medir después de un borrado se recalculaba desde
    el original viejo y contaba el borrado dos veces;
  · AAPL acción en IBKR y AAPL CEDEAR en Balanz no valen lo mismo por unidad:
    escalar la composición por las unidades sumadas daba +US$ 2.358;
  · el CEDEAR pagado en dólares: borrar la compra acreditaba PESOS en la cuenta
    en pesos (la plata en vivo y la foto); los dólares no volvían.
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import snapshots_job as sj  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from tests.test_reconstruccion_sigue_a_la_contabilidad import _Despues  # noqa: E402
from tests.test_reconstruccion_aportado_canonico import HDR  # noqa: E402

D = "2025-09-15"
BLUE, MEP = 1500.0, 1450.0
PRECIOS = {"AAPL": 260.0, "MSFT": 400.0, "NVDA": 130.0,
           "AAPL.BA": 18000.0, "KO.BA": 12000.0, "SPY.BA": 30000.0}


def _px(syms, crypto_yf, *a, **k):
    return {s: PRECIOS.get(s) for s in syms}


class _ContraElCron(_Despues):

    def setUp(self):
        super().setUp()
        bf._fetch_monthly_close = lambda key, start: {
            f"{y}-{m:02d}": 200.0 for y in (2025, 2026) for m in range(1, 13)}
        for p in (mock.patch.object(sj, "fetch_prices_for_symbols", _px),
                  mock.patch.object(sj, "apply_last_known_prices", lambda *a, **k: {})):
            p.start()
            self.addCleanup(p.stop)

    def _broker(self, name, ccy):
        self._sql("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", self.uid, name, ccy)

    def _imp(self, broker, *filas, route=False):
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        data = {"format": "rendi_generic", "broker": broker}
        if route:
            data["route_by_currency"] = "1"
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data=data, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar()

    def _cron(self, fecha, persist=True):
        """El cron real. Devuelve (total, {activo: valor})."""
        conn = main.get_db()
        try:
            r = sj.take_snapshot_for_user(conn, self.uid, BLUE, {}, target_date=fecha, tc_mep=MEP)
            self.assertTrue(r["ok"], r)
            f = conn.execute("SELECT total_value, holdings_json FROM snapshots WHERE user_id=? "
                             "AND date=?", (self.uid, fecha)).fetchone()
            out = (round(f["total_value"], 2),
                   {h["asset"]: h["value_usd"] for h in json.loads(f["holdings_json"] or "[]")})
            (conn.commit if persist else conn.rollback)()
            return out
        finally:
            conn.close()

    def _referencia(self):
        """Lo que el cron mediría hoy con la contabilidad de ahora y los mismos precios."""
        return self._cron("2099-01-01", persist=False)

    def _foto(self, fecha=D):
        conn = main.get_db()
        try:
            f = conn.execute("SELECT total_value, holdings_json, source, apto FROM snapshots "
                             "WHERE user_id=? AND date=?", (self.uid, fecha)).fetchone()
            return (round(f["total_value"], 2),
                    {h["asset"]: h["value_usd"] for h in json.loads(f["holdings_json"] or "[]")},
                    f["source"], f["apto"])
        finally:
            conn.close()

    def _q(self, sql, *a):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, a).fetchall()]
        finally:
            conn.close()

    def _pos_id(self, broker, asset):
        return self._q("SELECT id FROM positions WHERE user_id=? AND broker=? AND asset=? "
                       "AND is_cash=0", self.uid, broker, asset)[0]["id"]

    def _efectivo(self, broker):
        r = self._q("SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
                    self.uid, broker)
        return round(r[0]["invested"], 2) if r else None

    def assertComoElCron(self):
        """Igual a lo que mediría el cron, al centavo (el cron redondea cada activo
        antes de sumar: un peso convertido puede caer un centavo para cada lado)."""
        (total, hold, src, apto), (ref_total, ref_hold) = self._foto(), self._referencia()
        self.assertAlmostEqual(total, ref_total, delta=0.05)
        self.assertEqual(set(hold), set(ref_hold))
        for a in hold:
            self.assertAlmostEqual(hold[a], ref_hold[a], delta=0.05, msg=a)
        self.assertEqual((src, apto), ("cron", 1))

    def assertFueraDelCertero(self):
        self.assertEqual(self._foto()[2:], (main._MEDICION_VIEJA, 0))


class _TresActivos(_ContraElCron):

    def setUp(self):
        super().setUp()
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,",
                  "2025-04-01,COMPRA,IBKR,NVDA,5,100,500,,,0,USD,",
                  "2025-06-02,VENTA,IBKR,NVDA,5,120,600,,,0,USD,")
        self.foto0 = self._cron(D)

    def _venta(self, asset):
        return self._q("SELECT l.operation_id AS x FROM import_op_links l JOIN import_normalized_tx n "
                       "ON n.batch_id=l.batch_id AND n.raw_row_id=l.raw_row_id JOIN import_batches b "
                       "ON b.id=n.batch_id WHERE b.user_id=? AND n.operation_type='SELL' "
                       "AND n.asset_symbol=? AND l.operation_id IS NOT NULL", self.uid, asset)[0]["x"]


class Secuencias(_TresActivos):

    def test_borrar_una_compra(self):
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self.assertComoElCron()

    def test_ida_y_vuelta_cruzada_vuelve_exacta(self):
        a = self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}").json()["undo_token"]
        b = self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'AAPL')}").json()["undo_token"]
        self.assertComoElCron()
        self._pedir("post", f"/api/operations/undo/{a}")
        self.assertComoElCron()
        self._pedir("post", f"/api/operations/undo/{b}")
        self.assertEqual(self._foto()[:2], self.foto0)

    def test_borrar_A_borrar_B_deshacer_A(self):
        # A deja la foto fuera del certero (la venta borrada de algo vendido entero:
        # NVDA reaparece sin precio medido). Antes, deshacer A la devolvía como
        # medición con la compra de B adentro.
        a = self._pedir("delete", f"/api/operations/{self._venta('NVDA')}").json()["undo_token"]
        self.assertFueraDelCertero()
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self.assertFueraDelCertero()
        self._pedir("post", f"/api/operations/undo/{a}")
        self.assertComoElCron()

    def test_una_foto_que_el_cron_volvio_a_medir(self):
        # Borrar MSFT; comprar otra vez y que el cron vuelva a medir D (ya ve la
        # cartera nueva); después borrar todo el historial de MSFT. La foto nueva no
        # tiene que recibir otra vez el primer borrado.
        a = self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}").json()["undo_token"]
        self._imp("IBKR", "2025-08-01,COMPRA,IBKR,MSFT,3,350,1050,,,0,USD,")
        self._cron(D)
        h = self._pedir("delete", "/api/assets/history", params={"asset": "MSFT"}).json()["undo_token"]
        self.assertComoElCron()
        self._pedir("post", f"/api/assets/undo/{h}")
        self._pedir("post", f"/api/operations/undo/{a}")
        self.assertEqual(self._foto()[:2], self._referencia())


class LoQueNoSePuedeAfirmar(_ContraElCron):

    def test_el_mismo_ticker_en_dos_brokers(self):
        # AAPL acción (US$ 260) y AAPL CEDEAR (unos US$ 12): la composición los suma
        # por nombre y no se puede saber cuánto era de cada uno.
        self._broker("Balanz", "ARS")
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-05,COMPRA,Balanz,AAPL,200,15000,3000000,,,0,ARS,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'AAPL')}")
        self.assertFueraDelCertero()

    def test_pesos_sin_el_mep_del_dia(self):
        self._broker("Balanz", "ARS")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-05,COMPRA,Balanz,KO,100,10000,1000000,,,0,ARS,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('Balanz', 'KO')}")
        self.assertFueraDelCertero()

    def test_pesos_con_el_blue_pero_sin_el_mep(self):
        # `fx_for_date` cae al blue si falta el MEP; el cron valuó el efectivo en
        # pesos al MEP, así que con el blue la foto quedaría 1–3 % corrida.
        self._sql("DELETE FROM fx_rates_daily WHERE date=?", D)
        self._sql("INSERT INTO fx_rates_daily (date, blue_venta, blue_compra) VALUES (?,?,?)",
                  D, BLUE, BLUE)
        self.addCleanup(self._sql, "DELETE FROM fx_rates_daily WHERE date=?", D)
        self._broker("Balanz", "ARS")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-05,COMPRA,Balanz,KO,100,10000,1000000,,,0,ARS,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('Balanz', 'KO')}")
        self.assertFueraDelCertero()

    def test_un_monto_importado_absurdo(self):
        # El import trae montos malos (pesos cargados como dólares, filas
        # triplicadas): medido en la copia de prod, 5 de 43 borrados dejaban fotos
        # como −US$ 16 M sobre una cartera de US$ 35.000. Una compra de 10 MSFT que
        # el import anotó por US$ 300.000: devolver esa plata a la foto no es creíble.
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,")
        self._cron(D)
        self._sql("UPDATE import_normalized_tx SET gross_amount=300000 WHERE operation_type='BUY' "
                  "AND batch_id IN (SELECT id FROM import_batches WHERE user_id=?)", self.uid)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self.assertFueraDelCertero()

    def test_pesos_con_el_mep_del_dia(self):
        # Con el MEP histórico de esa fecha (el que usa el cron para el efectivo en
        # pesos) la corrección es exacta.
        self._sql("DELETE FROM fx_rates_daily WHERE date=?", D)
        self._sql("INSERT INTO fx_rates_daily (date, blue_venta, blue_compra, mep_venta, mep_compra) "
                  "VALUES (?,?,?,?,?)", D, BLUE, BLUE, MEP, MEP)
        self.addCleanup(self._sql, "DELETE FROM fx_rates_daily WHERE date=?", D)
        self._broker("Balanz", "ARS")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-05,COMPRA,Balanz,KO,100,10000,1000000,,,0,ARS,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('Balanz', 'KO')}")
        self.assertComoElCron()


class ElCedearPagadoEnDolares(_ContraElCron):
    """La tenencia vive en la cuenta en pesos y la plata salió de la "· USD"."""

    def setUp(self):
        super().setUp()
        self._broker("Balanz", "ARS")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-03,DEPOSITO,Balanz,,,,2000,,,0,USD,",
                  "2025-03-06,COMPRA,Balanz,SPY,30,40,1200,,,0,USD,", route=True)
        # El CSV genérico no clasifica SPY como CEDEAR: se deja la fila como la deja
        # un parser de Balanz (tenencia en el padre, plata del sibling) y se re-deriva.
        self._sql("UPDATE import_normalized_tx SET broker='Balanz', asset_type='CEDEAR' "
                  "WHERE asset_symbol='SPY' AND batch_id IN (SELECT id FROM import_batches "
                  "WHERE user_id=?)", self.uid)
        conn = main.get_db()
        try:
            main._import_rebuild.rebuild_pair_asset(conn, self.uid, "Balanz", "SPY", tc_blue=BLUE)
            conn.execute("UPDATE positions SET asset_type='CEDEAR' WHERE user_id=? AND asset='SPY'",
                         (self.uid,))
            conn.commit()
        finally:
            conn.close()
        self.foto0 = self._cron(D)

    def test_borrar_la_compra_devuelve_dolares_a_la_cuenta_en_dolares(self):
        pesos, dolares = self._efectivo("Balanz"), self._efectivo("Balanz · USD")
        r = self._pedir("delete", f"/api/positions/{self._pos_id('Balanz', 'SPY')}")
        # La plata en vivo: vuelven los US$ 1.200 a la cuenta en dólares; la de pesos
        # no se toca (antes recibía 1.200 PESOS y los dólares no volvían).
        self.assertEqual(self._efectivo("Balanz · USD"), round(dolares + 1200, 2))
        self.assertEqual(self._efectivo("Balanz"), pesos)
        self.assertComoElCron()
        # Y el deshacer los saca de la misma cuenta.
        self._pedir("post", f"/api/operations/undo/{r.json()['undo_token']}")
        self.assertEqual(self._efectivo("Balanz · USD"), dolares)
        self.assertEqual(self._efectivo("Balanz"), pesos)
        self.assertEqual(self._foto()[:2], self.foto0)


if __name__ == "__main__":
    unittest.main()
