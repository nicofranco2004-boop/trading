"""La foto reconstruida de fin de mes vale lo mismo que mediría el cron.

Encontrado al filmar el video de portada (03/11/2026): una cuenta nueva que importó
4 brokers (Cocos e IOL en pesos) veía en el Dashboard «Últimos 3 días −9,3 %» y
«Noviembre −US$ 6.766» con un mercado que se había movido −US$ 347. La foto
reconstruida del 31/10 decía US$ 72.606; la tenencia más la caja de ese día, al
dólar de ese día, US$ 67.199. La reconstrucción DEDUCÍA la caja de la contabilidad
(aportes − retiros + realizado, en dólares de la fecha de cada aporte), así que la
devaluación de los pesos nunca entraba en el pasado y aparecía de golpe en la
primera medición del cron. Ver "LA CAJA SE MIDE, NO SE DEDUCE DE LA CONTABILIDAD"
en `scripts/backfill_historical_mtm.py`.

Todo entra por las puertas reales: `POST /api/imports/preview` + `/confirm` (que
lanza la reconstrucción en su hilo, como en producción) y la referencia es el cron
de verdad (`snapshots_job.take_snapshot_for_user`). Entre el último fin de mes y
hoy no se mueve ni un precio ni el dólar: la diferencia tiene que ser cero.

Las fechas se cuentan desde hoy (una prueba con fecha fija vence).
"""
import io
import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import ledger_replay  # noqa: E402
import snapshots_job as sj  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from tests.test_reconstruccion_sigue_a_la_contabilidad import _Despues  # noqa: E402
from tests.test_reconstruccion_aportado_canonico import HDR  # noqa: E402

MESES = 14                      # la historia: del mes 0 al 14, el último cerrado


def _mes(k):
    """(año, mes) del mes k: el 14 es el último cerrado, el 15 el de hoy."""
    hoy = hoy_art_date()
    n = hoy.year * 12 + (hoy.month - 1) - (MESES + 1 - k)
    return n // 12, n % 12 + 1


def _dia(k, d):
    y, m = _mes(k)
    return f"{y:04d}-{m:02d}-{d:02d}"


def _dolar(k):
    """El dólar sube 50 pesos por mes; hoy vale lo mismo que el último fin de mes."""
    return 1000.0 + 50.0 * min(k, MESES)


def _aapl_ba(k):
    """El CEDEAR acompaña al dólar: AAPL vale US$ 20 todos los meses."""
    return 20.0 * _dolar(k)


def _cierres(price_key, start_iso):
    out = {}
    for k in range(MESES + 1):
        y, m = _mes(k)
        if price_key == "AAPL.BA":
            out[f"{y}-{m:02d}"] = _aapl_ba(k)
        elif price_key == "NVDA":
            out[f"{y}-{m:02d}"] = 300.0
    return out


def _hoy(syms, crypto_yf, *a, **k):
    return {s: {"AAPL.BA": _aapl_ba(MESES), "NVDA": 300.0}.get(s) for s in syms}


class _CajaMedida(_Despues):

    def setUp(self):
        super().setUp()
        bf._fetch_monthly_close = _cierres
        self._sql("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                  self.uid, "Cocos", "ARS")
        # `fx_rates_daily` no es de nadie (la fecha es la clave): se limpia antes
        # y después, en su propio paso (ver reference_tests_una_base_por_modulo).
        self._sql("DELETE FROM fx_rates_daily")
        self.addCleanup(self._sql, "DELETE FROM fx_rates_daily")
        conn = main.get_db()
        try:
            for k in range(MESES + 1):
                v = _dolar(k)
                conn.execute(
                    "INSERT INTO fx_rates_daily (date, blue_venta, blue_compra, mep_venta, "
                    "mep_compra, source) VALUES (?,?,?,?,?,'test')",
                    (_dia(k, 1), v, v, v, v))
            conn.commit()
        finally:
            conn.close()
        for p in (mock.patch.object(sj, "fetch_prices_for_symbols", _hoy),
                  mock.patch.object(sj, "apply_last_known_prices", lambda *a, **k: {})):
            p.start()
            self.addCleanup(p.stop)

    def _imp(self, broker, *filas):
        csv = (HDR + "".join(f + "\n" for f in filas)).encode()
        p = self.http.post("/api/imports/preview",
                           files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                           data={"format": "rendi_generic", "broker": broker}, headers=self.h)
        self.assertEqual(p.status_code, 200, p.text)
        c = self.http.post("/api/imports/confirm",
                           json={"session_id": p.json()["session_id"],
                                 "skip_row_indices": [], "aprobar_tickers": []},
                           headers=self.h)
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar()

    def _cocos(self, *extra):
        self._imp("Cocos",
                  f"{_dia(0, 5)},DEPOSITO,Cocos,,,,10000000,,,0,ARS,Aporte",
                  f"{_dia(0, 6)},COMPRA,Cocos,AAPL,200,20000,4000000,,,0,ARS,",
                  *extra)

    def _ibkr(self):
        # Dos compras a precios distintos y una venta parcial: el realizado de la
        # contabilidad sale del lote (FIFO) y la tenencia, del costo promedio.
        self._imp("IBKR",
                  f"{_dia(0, 5)},DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  f"{_dia(0, 6)},COMPRA,IBKR,NVDA,10,100,1000,,,0,USD,",
                  f"{_dia(2, 6)},COMPRA,IBKR,NVDA,10,200,2000,,,0,USD,",
                  f"{_dia(6, 6)},VENTA,IBKR,NVDA,10,300,3000,,,0,USD,")

    def _cron_hoy(self):
        conn = main.get_db()
        try:
            r = sj.take_snapshot_for_user(conn, self.uid, _dolar(MESES), {},
                                          target_date=hoy_art_date().isoformat(),
                                          tc_mep=_dolar(MESES))
            self.assertTrue(r["ok"], r)
            v = conn.execute("SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
                             (self.uid, hoy_art_date().isoformat())).fetchone()[0]
            conn.rollback()
            return v
        finally:
            conn.close()

    def _foto(self, k):
        y, m = _mes(k)
        conn = main.get_db()
        try:
            d = bf._month_end(y, m)
            r = conn.execute("SELECT total_value, source FROM snapshots WHERE user_id=? "
                             "AND date=?", (self.uid, d)).fetchone()
            self.assertIsNotNone(r, d)
            self.assertEqual(r["source"], bf.MTM_SOURCE, d)
            return r["total_value"]
        finally:
            conn.close()


class LaFotoValeLoQueMideElCron(_CajaMedida):

    def test_pesos_que_se_devaluan(self):
        self._cocos()
        # Hoy: 200 AAPL a US$ 20 + 6.000.000 de pesos al dólar de hoy (1.700).
        hoy = self._cron_hoy()
        self.assertAlmostEqual(hoy, 4000 + 6_000_000 / 1700, delta=0.05)
        # Antes: US$ 11.647 (la caja y el costo en pesos al dólar de 1.000 del
        # aporte) — una caída falsa de US$ 4.118 entre el último cierre y hoy.
        self.assertAlmostEqual(self._foto(MESES), hoy, delta=0.05)
        # Y cada mes, con SU dólar: no hay una caída escondida más atrás.
        for k in (0, 3, 7, 11):
            self.assertAlmostEqual(self._foto(k), 4000 + 6_000_000 / _dolar(k), delta=0.05,
                                   msg=f"mes {k}")

    def test_venta_parcial_en_dolares(self):
        self._ibkr()
        hoy = self._cron_hoy()
        self.assertAlmostEqual(hoy, 10 * 300 + 10_000, delta=0.05)
        # Antes: 13.500 — la caja deducida con el costo promedio (US$ 1.500 de
        # NVDA) en vez del lote que quedó (US$ 2.000).
        self.assertAlmostEqual(self._foto(MESES), hoy, delta=0.05)

    def test_las_dos_juntas_y_la_conversion_a_dolares(self):
        # Comprar dólares MEP saca pesos de Cocos y pone dólares en 'Cocos · USD'.
        self._cocos(f"{_dia(9, 3)},CONVERSION_ARS_USD,Cocos,,,,2000000,1360.54,1470,0,,MEP")
        self._ibkr()
        hoy = self._cron_hoy()
        self.assertAlmostEqual(self._foto(MESES), hoy, delta=0.1)

    def test_lo_que_el_archivo_no_explica_queda_como_antes(self):
        """Plata cargada a mano en el broker en pesos: los movimientos importados ya
        no explican su caja, y la del pasado no se puede afirmar. Ese broker queda
        con la caja deducida y se anota; el de dólares se sigue midiendo."""
        self._cocos()
        self._ibkr()
        r = self.http.post("/api/cash/flow", json={
            "broker_name": "Cocos", "direction": "deposit", "amount": 500000,
            "tc_blue": _dolar(MESES), "date": hoy_art_date().isoformat()}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar()
        conn = main.get_db()
        try:
            res = bf.backfill_user(conn, self.uid, hoy_art_date())
        finally:
            conn.rollback()
            conn.close()
        self.assertEqual(res["cajas_sin_medir"], ["Cocos"])


class NadieLaPisaDespues(_CajaMedida):

    def test_el_cron_y_otra_reconstruccion_no_la_cambian(self):
        self._cocos()
        self._ibkr()
        antes = self._foto(MESES)
        # El cron de hoy escribe su foto; el Dashboard repara la cadena cada 90 s;
        # otra reconstrucción sobre la misma contabilidad.
        conn = main.get_db()
        try:
            sj.take_snapshot_for_user(conn, self.uid, _dolar(MESES), {},
                                      target_date=hoy_art_date().isoformat(),
                                      tc_mep=_dolar(MESES))
            conn.commit()
        finally:
            conn.close()
        self._pedir("post", "/api/snapshots", json={
            "total_value": antes, "total_invested": antes, "net_deposited": 0})
        self._pedir("post", "/api/monthly/sync-unrealized", json={
            "broker": "Cocos", "pnl_unrealized_usd": 123.0})
        main._reconstruir_mtm(self.uid)
        self.assertEqual(self._foto(MESES), antes)

    def test_cambiar_el_motor_pide_reconstruir(self):
        """Las cuentas que ya tenían la historia escrita con el motor viejo la
        rehacen una vez: la versión del motor entra en la huella."""
        self._cocos()
        conn = main.get_db()
        try:
            h = bf.huella_de_entrada(conn, self.uid, hoy_art_date())
            with mock.patch.object(bf, "MOTOR_VERSION", bf.MOTOR_VERSION + 1):
                self.assertNotEqual(bf.huella_de_entrada(conn, self.uid, hoy_art_date()), h)
        finally:
            conn.close()


class LaConversionEnElReplay(unittest.TestCase):
    """`ledger_replay.cash_en` mueve las dos puntas de una conversión."""

    def test_pesos_salen_y_dolares_entran(self):
        conn = main.get_db()
        try:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) "
                               "VALUES ('conv-replay@rendi.test','x',1)").lastrowid
            pid = conn.execute("INSERT INTO brokers (user_id, name, currency) "
                               "VALUES (?, 'Cocos', 'ARS')", (uid,)).lastrowid
            conn.execute("INSERT INTO brokers (user_id, name, currency, parent_broker_id) "
                         "VALUES (?, 'Cocos · USD', 'USDT', ?)", (uid, pid))
            conn.execute("INSERT INTO import_batches (id, user_id, broker, parser_format, "
                         "file_hash, status) VALUES ('CR1', ?, 'Cocos', 'g', 'h', 'confirmed')",
                         (uid,))
            for i, (op, broker, monto, q) in enumerate((
                    ("DEPOSIT", "Cocos", 3_000_000, None),
                    ("FX_ARS_TO_USD", "Cocos", 1_500_000, 1000),
                    ("FX_USD_TO_ARS", "Cocos · USD", 750_000, 500))):
                rr = conn.execute("INSERT INTO import_raw_rows (batch_id, row_index, raw_json, "
                                  "status) VALUES ('CR1', ?, '{}', 'valid')", (i,)).lastrowid
                conn.execute("INSERT INTO import_normalized_tx (batch_id, raw_row_id, broker, "
                             "operation_type, quantity, gross_amount, currency, date) "
                             "VALUES ('CR1', ?, ?, ?, ?, ?, 'ARS', '2026-01-0' || ?)",
                             (rr, broker, op, q, monto, i + 1))
            saldos = ledger_replay.cash_en(conn, uid, "2026-01-31")
        finally:
            conn.rollback()
            conn.close()
        self.assertEqual(saldos[("Cocos", "ARS")], 3_000_000 - 1_500_000 + 750_000)
        self.assertEqual(saldos[("Cocos · USD", "USD")], 1000 - 500)


if __name__ == "__main__":
    unittest.main()
