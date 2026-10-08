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
from tests.test_reconstruccion_sigue_a_la_contabilidad import _Despues, _YahooDeMentira  # noqa: E402
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

    def _imp(self, broker, *filas, route=False, tardio=False):
        """Importa por la app. Salvo `tardio`, el lote queda confirmado ANTES de las
        fotos (así existen en la vida real: el cron midió una cuenta que ya tenía su
        historia; una foto no ve un import confirmado después de su fecha)."""
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
        if not tardio:
            self._sql("UPDATE import_batches SET confirmed_at='2025-01-01 00:00:00' "
                      "WHERE user_id=?", self.uid)

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


class ElImportTardio(_TresActivos):
    """Una compra con fecha vieja que entró DESPUÉS de la foto (un CSV superpuesto
    que trajo un duplicado). La foto nunca la vio: borrarla no le cambia nada.
    Antes, la foto correcta (como la mide el cron) pasaba a otra cosa y quedaba
    certificada (auditoría 4: 10.600 → 10.733)."""

    def test_borrar_lo_que_la_foto_no_vio(self):
        self._imp("IBKR", "2025-03-06,COMPRA,IBKR,AAPL,5,200,1000,,,0,USD,", tardio=True)
        antes = self._foto()
        r = self._q("SELECT n.id FROM import_normalized_tx n JOIN import_batches b ON "
                    "b.id=n.batch_id WHERE b.user_id=? AND n.date='2025-03-06'", self.uid)
        self._pedir("delete", f"/api/movements/tx-{r[0]['id']}")
        self.assertEqual(self._foto(), antes)


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

    def test_un_lote_que_la_foto_valua_lejos_de_lo_que_costo(self):
        # La foto dice que las 10 MSFT valían US$ 4.000 y el import dice que costaron
        # US$ 1.000 (4×): uno de los dos está mal (en prod: montos ×1.000 de pesos
        # cargados como dólares). El salto total queda bajo el 50 %, así que sólo la
        # banda por lote lo frena.
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,")
        self._cron(D)
        self._sql("UPDATE import_normalized_tx SET gross_amount=1000 WHERE operation_type='BUY' "
                  "AND asset_symbol='MSFT' AND batch_id IN (SELECT id FROM import_batches "
                  "WHERE user_id=?)", self.uid)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self.assertFueraDelCertero()

    def test_pesos_con_el_mep_del_dia(self):
        # Con el MEP histórico (el del día de la foto, que usa el cron para el
        # efectivo en pesos, y el del día de la compra, para el control del lote) la
        # corrección es exacta.
        for dia in (D, "2025-03-05"):
            self._sql("DELETE FROM fx_rates_daily WHERE date=?", dia)
            self._sql("INSERT INTO fx_rates_daily (date, blue_venta, blue_compra, mep_venta, "
                      "mep_compra) VALUES (?,?,?,?,?)", dia, BLUE, BLUE, MEP, MEP)
            self.addCleanup(self._sql, "DELETE FROM fx_rates_daily WHERE date=?", dia)
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


class LaCuentaEnPesosYSuCuentaEnDolares(_ContraElCron):
    """El dólar MEP: el CEDEAR se compra en pesos (cuenta padre) y se vende en
    dólares (la "· USD"). Son UN broker, valuado igual en las dos. Contarlas como
    dos sacaba del certero el 57 % de las fotos tras borrar una compra suelta
    (auditoría 4, datos de prod)."""

    def test_borrar_la_venta_en_dolares_se_corrige(self):
        self._broker("Balanz", "ARS")
        self._imp("Balanz", "2025-03-03,DEPOSITO,Balanz,,,,5000000,,,0,ARS,",
                  "2025-03-06,COMPRA,Balanz,SPY,30,28000,840000,,,0,ARS,",
                  "2025-04-10,VENTA,Balanz,SPY,10,20,200,,,0,USD,", route=True)
        self._sql("UPDATE import_normalized_tx SET asset_type='CEDEAR' WHERE asset_symbol='SPY' "
                  "AND batch_id IN (SELECT id FROM import_batches WHERE user_id=?)", self.uid)
        conn = main.get_db()
        try:
            main._import_rebuild.rebuild_pair_asset(conn, self.uid, "Balanz", "SPY", tc_blue=BLUE)
            conn.execute("UPDATE positions SET asset_type='CEDEAR' WHERE user_id=? AND asset='SPY'",
                         (self.uid,))
            conn.commit()
        finally:
            conn.close()
        brokers = {r["broker"] for r in self._q(
            "SELECT DISTINCT n.broker FROM import_normalized_tx n JOIN import_batches b ON "
            "b.id=n.batch_id WHERE b.user_id=? AND n.asset_symbol='SPY'", self.uid)}
        self.assertEqual(brokers, {"Balanz", "Balanz · USD"})       # el caso de verdad
        self._cron(D)
        venta = self._q("SELECT l.operation_id AS x FROM import_op_links l JOIN "
                        "import_normalized_tx n ON n.batch_id=l.batch_id AND "
                        "n.raw_row_id=l.raw_row_id JOIN import_batches b ON b.id=n.batch_id "
                        "WHERE b.user_id=? AND n.operation_type='SELL' "
                        "AND l.operation_id IS NOT NULL", self.uid)[0]["x"]
        self._pedir("delete", f"/api/operations/{venta}")
        self.assertComoElCron()


class LoQueQuedaDeAntes(_TresActivos):

    def test_un_borrado_de_antes_de_este_cambio(self):
        # Los journals viejos no guardaban `eventos`: se arman de sus filas. Sin eso,
        # un borrado nuevo del mismo activo calculaba mal (US$ 8.000 vs 10.000).
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        conn = main.get_db()
        try:
            for j in conn.execute("SELECT id, payload_json FROM deleted_ops_journal "
                                  "WHERE user_id=?", (self.uid,)).fetchall():
                p = json.loads(j["payload_json"])
                p.pop("eventos", None)
                conn.execute("UPDATE deleted_ops_journal SET payload_json=? WHERE id=?",
                             (json.dumps(p), j["id"]))
            conn.commit()
        finally:
            conn.close()
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'AAPL')}")
        self.assertComoElCron()



class LosBorradosDeAntesDelDeploy(_TresActivos):
    """Un borrado hecho con la versión vieja: el journal existe, la foto medida antes
    de él quedó como el cron la midió (con la compra adentro) y no hay copia del
    original. La reconstrucción que corre en el primer pedido de la cuenta después
    del deploy la corrige; la foto medida DESPUÉS del borrado ya lo reflejaba y no se
    toca (corregirla otra vez restaría la compra dos veces)."""

    def _como_la_version_vieja(self, borrado_el):
        conn = main.get_db()
        try:
            for o in conn.execute("SELECT * FROM medicion_original WHERE user_id=?",
                                  (self.uid,)).fetchall():
                conn.execute(
                    f"UPDATE snapshots SET {', '.join(c + '=?' for c in main._MEDICION_COLS)} "
                    "WHERE user_id=? AND date=?",
                    (*[o[c] for c in main._MEDICION_COLS], self.uid, o["date"]))
            conn.execute("DELETE FROM medicion_original WHERE user_id=?", (self.uid,))
            for j in conn.execute("SELECT id, payload_json FROM deleted_ops_journal "
                                  "WHERE user_id=?", (self.uid,)).fetchall():
                p = json.loads(j["payload_json"])
                p.pop("eventos", None)
                conn.execute("UPDATE deleted_ops_journal SET payload_json=?, created_at=? "
                             "WHERE id=?", (json.dumps(p), borrado_el, j["id"]))
            conn.commit()
        finally:
            conn.close()

    def test_la_foto_de_antes_del_borrado_se_corrige(self):
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self._como_la_version_vieja("2025-09-20 15:00:00")
        self.assertEqual(self._foto()[:2], self.foto0)            # la foto quedó vieja
        despues = self._cron("2025-09-25")                         # ya sin MSFT
        main._reconstruir_mtm(self.uid)
        self.assertComoElCron()
        self.assertEqual(self._foto("2025-09-25")[:2], despues)

    def test_la_foto_que_ya_lo_reflejaba_no_se_toca(self):
        # El borrado fue ANTES de la foto: el cron ya la midió sin MSFT.
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self._como_la_version_vieja("2025-09-01 15:00:00")
        sin_msft = self._cron(D)
        main._reconstruir_mtm(self.uid)
        self.assertEqual(self._foto()[:2], sin_msft)
        self.assertComoElCron()

    def test_con_yahoo_caido_igual_se_corrige(self):
        # La corrección de las fotos medidas no necesita a Yahoo.
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self._como_la_version_vieja("2025-09-20 15:00:00")
        bf._fetch_monthly_close = self._fetch_orig            # el de verdad
        bf._HIST_CACHE.clear()
        _YahooDeMentira.caido = True
        self.addCleanup(setattr, _YahooDeMentira, "caido", False)
        with mock.patch("yfinance.Ticker", _YahooDeMentira):
            main._reconstruir_mtm(self.uid)
        self.assertEqual(self._q("SELECT huella FROM mtm_huella WHERE user_id=?",
                                 self.uid)[0]["huella"], main._MTM_FALLIDA)
        self.assertComoElCron()

    def test_sin_historia_que_reconstruir_igual_se_corrige(self):
        # La reconstrucción se saltea (no hay meses que rearmar) y antes salía por
        # un camino que no corregía.
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self._como_la_version_vieja("2025-09-20 15:00:00")
        self._sql("DELETE FROM monthly_entries WHERE user_id=?", self.uid)
        self._sql("DELETE FROM snapshots WHERE user_id=? AND source='mtm_backfill'", self.uid)
        r = main._reconstruir_mtm(self.uid)
        self.assertEqual((r.get("motivo"), r.get("snapshots_borrados")),
                         ("sin monthly_entries", None), r)
        self.assertComoElCron()

    def test_al_arrancar_van_a_la_fila_las_que_no_se_reconstruyeron(self):
        # La cuenta que sólo mira no hace ningún pedido que dispare la reconstrucción.
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        anotadas = []
        with mock.patch.object(main, "_reconstruir_en_fila", anotadas.extend):
            self._sql("DELETE FROM mtm_huella WHERE user_id=?", self.uid)
            main._corregir_borrados_de_antes()
            self.assertEqual(anotadas, [self.uid])
            anotadas.clear()
            main._reconstruir_mtm(self.uid)          # ya con marca: no se repite
            main._corregir_borrados_de_antes()
            self.assertEqual(anotadas, [])


class RevertirYReimportar(_ContraElCron):

    def test_revertir_reimportar_y_borrar(self):
        # Revertir borra las fotos; si el original guardado quedaba, el próximo
        # borrado le devolvía a la cuenta re-importada la medición vieja como "cron"
        # (auditoría 4: 13.600 donde el cron daba 21.800). (Sin ventas: la app no
        # revierte un import con ventas.)
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        lote = self._q("SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'",
                       self.uid)[0]["id"]
        self._pedir("post", f"/api/imports/{lote}/revert")
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,20000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,")
        self._cron(D)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        self.assertComoElCron()


class ElOriginalEsDeEsaFoto(_ContraElCron):
    """Un original guardado pertenece a UNA fila de `snapshots`. Revertir el import
    borra la foto; la reconstrucción vuelve a escribir ese fin de mes con otra fila.
    El original viejo no puede volver encima de ella como "medición del cron"."""

    def test_revertir_y_reimportar_no_resucita_la_medicion_vieja(self):
        fin = "2025-09-30"
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,MSFT,10,300,3000,,,0,USD,")
        self._cron(fin)
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'MSFT')}")
        lote = self._q("SELECT id FROM import_batches WHERE user_id=? AND status='confirmed'",
                       self.uid)[0]["id"]
        self._pedir("post", f"/api/imports/{lote}/revert")
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,20000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,20,200,4000,,,0,USD,",
                  "2025-03-05,COMPRA,IBKR,NVDA,10,100,1000,,,0,USD,")
        self.assertEqual(self._foto(fin)[2], "mtm_backfill")      # la reescribió la reconstrucción
        self._pedir("delete", f"/api/positions/{self._pos_id('IBKR', 'NVDA')}")
        self.assertEqual(self._foto(fin)[2], "mtm_backfill")
        self.assertEqual(self._q("SELECT COUNT(*) AS n FROM medicion_original WHERE user_id=? "
                                 "AND date=?", self.uid, fin)[0]["n"], 0)


class LaReconstruccionNoPisaUnaMedicion(_ContraElCron):
    """El candado de `_persist_mtm_snapshots`: la clase de cada fecha se lee al
    empezar la corrida (minutos antes, por Yahoo). Si en el medio un "deshacer"
    devolvió la medición del cron a esa fecha, la reconstrucción no la pisa."""

    def test_el_candado(self):
        self._imp("IBKR", "2025-03-03,DEPOSITO,IBKR,,,,10000,,,0,USD,",
                  "2025-03-04,COMPRA,IBKR,AAPL,10,200,2000,,,0,USD,")
        fin_de_mes = "2025-09-30"
        self._cron(fin_de_mes)
        medida = self._foto(fin_de_mes)
        conn = main.get_db()
        try:
            # La corrida "leyó" la fecha cuando no era una medición:
            with mock.patch("twr.clasificar_serie",
                            side_effect=lambda filas, primera: ["reconstruido"] * len(filas)):
                bf._persist_mtm_snapshots(conn, self.uid, {"2025-09": {
                    "date": fin_de_mes, "value": 1.0, "cost": 1.0, "net_dep": 1.0,
                    "coverage": 1.0, "holdings": []}})
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._foto(fin_de_mes), medida)


if __name__ == "__main__":
    unittest.main()
