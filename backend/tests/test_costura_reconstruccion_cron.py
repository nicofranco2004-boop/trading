"""La costura entre la historia RECONSTRUIDA y las fotos del CRON.

Las dos escriben fotos "a mercado", pero no valúan lo mismo: el cron mira las
POSICIONES de la cuenta × precio; la reconstrucción
(`scripts/backfill_historical_mtm.py`) mira la CONTABILIDAD al costo más lo no
realizado de lo importado. Dan lo mismo sólo si la contabilidad describe toda la
plata. Cuando no, la resta entre una foto y otra no es un movimiento del mercado.
Medido en la copia de producción del 2026-08-16 (ver "LA COSTURA" en twr.py):
uid 635 publicaba +267,89 % de acumulado y +141,95 % en agosto con la cartera
quieta; uid 783 tenía −65 % y +189 % en dos días por una reconstrucción escrita
entre dos fotos del cron.

Las cuentas entran por las puertas reales: import por la API (`/api/imports/
preview` + `/confirm`, que dispara la reconstrucción en su hilo, como en
producción), el cron de verdad (`snapshots_job.take_snapshot_for_user`), y se lee
por donde lee la pantalla (`/api/insights/performance`, `/api/reports/period`).
Lo único reemplazado es lo que sale a internet: los cierres de Yahoo.

Las fechas se arman contra HOY (la reconstrucción sólo escribe meses cerrados):
M = el último mes cerrado, M1 = el anterior.
"""
import calendar
import io
import os
import sys
import time
import unittest
import uuid
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import twr  # noqa: E402
import snapshots_job as sj  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

BLUE = MEP = 1450.0
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _mes(ym, k):
    """'AAAA-MM' corrido k meses."""
    y, m = int(ym[:4]), int(ym[5:7]) + k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def _fin(ym):
    return f"{ym}-{calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]:02d}"


_HOY = twr._hoy_art()
M = _mes(_HOY[:7], -1)          # último mes cerrado
M1 = _mes(M, -1)
INICIO = _mes(M, -5)            # el import arranca cinco meses antes


class _Cuenta(unittest.TestCase):
    """Una cuenta importada por la API, reconstruida y medida por el cron."""

    BROKER, MONEDA = "IBKR", "USD"
    FILAS = ()                  # filas del CSV, sin encabezado
    CIERRES = {}                # 'AAAA-MM' → cierre mensual de SPY (Yahoo, para la reconstrucción)
    PRECIO_CRON = 100.0         # el precio de SPY que ve el cron
    DIAS_CRON = ()              # fechas en que corre el cron
    FX = {}                     # fecha → dólar histórico (fx_rates_daily)

    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(main.app)
        conn = main.get_db()
        cls.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"costura-{uuid.uuid4().hex[:10]}@rendi.test", "x")).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (cls.uid, cls.BROKER, cls.MONEDA))
        for d, tc in cls.FX.items():
            conn.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                         "VALUES (?,?,?,'manual')", (d, tc, tc))
        conn.commit()
        conn.close()
        cls.h = {"Authorization": f"Bearer {main.create_token(cls.uid)}"}
        fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        cierres = dict(cls.CIERRES)
        bf._fetch_monthly_close = (
            lambda key, start: dict(cierres) if key.upper().startswith("SPY") else {})
        try:
            with mock.patch.object(main, "_fetch_data912_bonds", return_value={}):
                csv = (HDR + "".join(f + "\n" for f in cls.FILAS)).encode()
                p = cls.http.post("/api/imports/preview",
                                  files=[("files", ("mov.csv", io.BytesIO(csv), "text/csv"))],
                                  data={"format": "rendi_generic", "broker": cls.BROKER},
                                  headers=cls.h)
                assert p.status_code == 200, p.text
                c = cls.http.post("/api/imports/confirm",
                                  json={"session_id": p.json()["session_id"],
                                        "skip_row_indices": [], "aprobar_tickers": []},
                                  headers=cls.h)
                assert c.status_code == 200, c.text
                cls._esperar()
                # El cron, día por día, con el precio fijo.
                with mock.patch.object(sj, "fetch_prices_for_symbols",
                                       lambda syms, *a, **k: {s: cls.PRECIO_CRON for s in syms}), \
                        mock.patch.object(sj, "apply_last_known_prices", lambda *a, **k: {}):
                    for d in cls.DIAS_CRON:
                        conn = main.get_db()
                        try:
                            r = sj.take_snapshot_for_user(conn, cls.uid, BLUE, {},
                                                          target_date=d, tc_mep=MEP)
                            assert r["ok"], r
                            conn.commit()
                        finally:
                            conn.close()
        finally:
            bf._fetch_monthly_close = fetch_orig
            bf._HIST_CACHE.clear()

    @classmethod
    def _esperar(cls):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if (cls.uid not in main._MTM_RUNNING and cls.uid not in main._MTM_FILA
                        and not main._MTM_FILA_ACTIVA):
                    return
            time.sleep(0.02)
        raise AssertionError("la reconstrucción no terminó en 60 s")

    def _foto(self, d):
        conn = main.get_db()
        try:
            r = conn.execute("SELECT total_value, source, base, apto FROM snapshots "
                             "WHERE user_id=? AND date=?", (self.uid, d)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def _performance(self):
        r = self.http.get("/api/insights/performance", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _reporte_mes(self, ym):
        r = self.http.get(f"/api/reports/period/month/{ym}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class LaCosturaQueNoCierra(_Cuenta):
    """La costura que no cierra: una cuenta en pesos con la plata en la caja.

    $10.000.000 depositados a un dólar de 1.000, y después $1.000.000 en M1 y
    otro en M (uno por mes para que esos meses tengan fila en la contabilidad).
    Nada más: ni compras ni ventas. La reconstrucción vale la cuenta por su
    CONTABILIDAD, que guarda cada depósito en los dólares de su día: US$11.000 al
    cierre de M1. El cron vale la CAJA al dólar de hoy (1.450): $12.000.000 son
    US$8.276. La cuenta no hizo nada: cualquier rendimiento distinto de cero es la
    brecha entre las dos formas de valuar. (En producción la brecha más grande la
    dan los imports que arrancan con la cuenta ya andando —uid 635, +267,89 %—;
    acá se usa la de la caja en pesos porque se recorre entera por las puertas
    reales y es igual de cotidiana: toda cuenta argentina con pesos quietos.)
    """
    BROKER, MONEDA = "Cocos", "ARS"
    FILAS = (f"{INICIO}-10,DEPOSITO,Cocos,,,,10000000,10000,1000,0,ARS,",
             f"{M1}-15,DEPOSITO,Cocos,,,,1000000,1000,1000,0,ARS,",
             f"{M}-15,DEPOSITO,Cocos,,,,1000000,1000,1000,0,ARS,")
    FX = {f"{INICIO}-10": 1000.0}
    CIERRES = {}
    DIAS_CRON = tuple(f"{M}-{d:02d}" for d in range(1, int(_fin(M)[-2:]) + 1))
    CRON_ESPERADO = 12_000_000 / MEP

    def test_0_el_caso_discrimina(self):
        """Las dos fotos de la costura existen y valen lo que dice el docstring. Sin
        esto el test no probaría nada."""
        rec, cron = self._foto(_fin(M1)), self._foto(f"{M}-01")
        self.assertEqual(rec["source"], "mtm_backfill")
        self.assertEqual(rec["apto"], 1)
        self.assertAlmostEqual(rec["total_value"], 11000.0, delta=1)
        self.assertEqual(cron["source"], "cron")
        self.assertAlmostEqual(cron["total_value"], self.CRON_ESPERADO, delta=1)
        # Y el motor de antes la encadenaba: ×0,69 está adentro del corte ×3.
        self.assertIsNone(twr.leg_dudoso(rec["total_value"], cron["total_value"], 1000.0))

    def test_el_acumulado_no_publica_el_salto(self):
        """Antes: −32,38 % "a mercado" sin haber hecho nada."""
        p = self._performance()
        self.assertIsNone(p.get("twr"), p.get("twr"))
        self.assertEqual(p.get("motivo"), "cadena_implausible")
        self.assertTrue(any(c.get("cadena") == "costura" for c in p.get("cortes_dudosos") or []))

    def test_rendimiento_publicable_cae_a_la_contabilidad_etiquetada(self):
        conn = main.get_db()
        try:
            r = twr.rendimiento_publicable(conn, self.uid)
        finally:
            conn.close()
        self.assertNotEqual(r["base"], "mercado", r)
        if r["pct"] is not None:
            self.assertLess(abs(r["pct"]), 1.0, r)        # la cuenta no hizo nada

    def test_el_mes_de_la_costura_no_se_mide_a_mercado(self):
        """Antes: el mes M a mercado −32,38 %."""
        conn = main.get_db()
        try:
            meses = {m["mes"]: m for m in twr.rendimientos_mensuales(conn, self.uid)}
        finally:
            conn.close()
        self.assertNotEqual(meses[M]["base"], "mercado", meses[M])
        if meses[M]["pct"] is not None:
            self.assertLess(abs(meses[M]["pct"]), 1.0, meses[M])

    def test_reportes_no_usa_la_costura_como_mes(self):
        """Reportes arma el mes con su propio par de bordes (cierre de M1 y de M):
        uno reconstruido y otro del cron. Antes publicaba −32,38 % a mercado."""
        rep = self._reporte_mes(M)
        m = rep.get("metrics") or rep
        pct = m.get("delta_pct")
        self.assertFalse(m.get("basis") == "mercado" and pct is not None and abs(pct) > 1.0, m)

    def test_los_meses_de_la_reconstruccion_siguen_midiendo(self):
        """El corte es en la costura, no en la historia: los meses reconstruidos
        entre sí (contabilidad quieta) siguen dando 0 % a mercado."""
        conn = main.get_db()
        try:
            meses = {m["mes"]: m for m in twr.rendimientos_mensuales(conn, self.uid)}
        finally:
            conn.close()
        self.assertEqual(meses[M1]["base"], "mercado", meses[M1])
        self.assertAlmostEqual(meses[M1]["pct"], 0.0, places=4)


class LaReconstruccionAdentroDelCron(_Cuenta):
    """El caso del uid 783: el cron no corrió el último día de M1 y la
    reconstrucción de ese fin de mes quedó ENTRE dos fotos del cron.

    Contabilidad completa (US$10.000 depositados, 100 SPY a 100). El cron ve SPY a
    100 todos los días; Yahoo dice que M1 cerró a 60, así que la reconstrucción de
    ese día vale 6.000. Las dos valúan distinto —en producción, porque miran cosas
    distintas; acá, con dos precios— y la curva hacía 10.000 → 6.000 → 10.000.
    """
    FILAS = (f"{INICIO}-10,DEPOSITO,IBKR,,,,10000,,,0,USD,",
             f"{INICIO}-10,COMPRA,IBKR,SPY,100,100,10000,,,0,USD,")
    CIERRES = {**{_mes(INICIO, k): 100.0 for k in range(0, 7)}, M1: 60.0}
    DIAS_CRON = (tuple(f"{M1}-{d:02d}" for d in range(20, int(_fin(M1)[-2:])))
                 + tuple(f"{M}-{d:02d}" for d in range(1, 11)))

    def test_0_el_caso_discrimina(self):
        rec = self._foto(_fin(M1))
        self.assertEqual(rec["source"], "mtm_backfill")
        self.assertAlmostEqual(rec["total_value"], 6000.0, delta=1)
        self.assertIsNone(self._foto(f"{M1}-19"), "el cron no tiene que haber corrido antes")

    def test_el_cron_la_marca_como_no_cierre(self):
        """La reconstrucción se escribió antes de que existiera la foto del cron que
        la cubre; el cron, al medir, la deja como no-cierre. No la borra: es la
        historia de la cuenta (y borrarla cortaría la racha de las fotos viejas del
        cron, ver `marcar_reconstrucciones_superadas`)."""
        rec = self._foto(_fin(M1))
        self.assertEqual(rec["source"], "mtm_backfill")
        self.assertEqual((rec["base"], rec["apto"]), (twr.VALUADO_AL_COSTO, 0))

    def test_la_curva_no_pasa_por_la_reconstruccion(self):
        """Antes: caída máxima −40 % (10.000 → 6.000) en una cartera quieta."""
        p = self._performance()
        self.assertNotIn(_fin(M1), [q["date"] for q in p.get("curva") or []])
        self.assertIsNotNone(p.get("twr"), p.get("motivo"))
        self.assertAlmostEqual(p["twr"], 0.0, places=6)
        self.assertAlmostEqual(p.get("drawdown_maximo") or 0.0, 0.0, places=6)

    def test_reportes_cierra_el_mes_con_el_cron(self):
        """Antes: Reportes cerraba M1 con la reconstrucción (−40 %) y abría M con ella
        (+67 %)."""
        for ym in (M1, M):
            m = self._reporte_mes(ym)
            m = m.get("metrics") or m
            pct = m.get("delta_pct")
            self.assertFalse(pct is not None and abs(pct) > 1.0, (ym, m))

    def test_la_reconstruccion_ya_no_la_vuelve_a_dejar_de_cierre(self):
        """Una corrida nueva del reconstructor re-estampa sus fotos por cobertura; la
        superada vuelve a quedar como no-cierre en la misma corrida."""
        fetch_orig = bf._fetch_monthly_close
        bf._HIST_CACHE.clear()
        cierres = dict(self.CIERRES)
        bf._fetch_monthly_close = (
            lambda key, start: dict(cierres) if key.upper().startswith("SPY") else {})
        conn = main.get_db()
        try:
            res = bf.backfill_user(conn, self.uid, date.fromisoformat(_HOY))
            conn.commit()
        finally:
            conn.close()
            bf._fetch_monthly_close = fetch_orig
            bf._HIST_CACHE.clear()
        self.assertFalse(res["skipped"], res)
        rec = self._foto(_fin(M1))
        self.assertEqual((rec["base"], rec["apto"]), (twr.VALUADO_AL_COSTO, 0))


if __name__ == "__main__":
    unittest.main()
