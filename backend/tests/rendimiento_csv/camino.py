"""Una cuenta por EL MISMO CAMINO QUE PRODUCCIÓN, con el mercado inventado.

    subida HTTP  /api/imports/preview → /api/imports/confirm   (movimientos)
                 /api/imports/tenencia/preview → /confirm      (foto de tenencia)
    post-proceso del confirm y reconstrucción a mercado en su hilo
    cron diario real (snapshots_job.take_snapshot_for_user), día por día
    lectores: twr.curva_indexada / rendimiento_publicable y los endpoints

Es el arnés de la auditoría (`audit/rendimiento_csv/arnes.py`) hecho para la suite:
la red se reemplaza con parches que el TestCase arranca y frena (el arnés los pone
al importarse, para todo el proceso), y la base es la del módulo de test
(`tests/conftest.py`). Lo reemplazado es SÓLO la red: Yahoo (`yfinance.Ticker`), la
foto de precios del cron, el feed vivo y las velas de data912, y el dólar.
"""
from __future__ import annotations

import io
import os
import sys
import time
from datetime import date, timedelta
from unittest import mock

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import pandas as pd  # noqa: E402
import requests  # noqa: E402

import main  # noqa: E402
import snapshots_job as sj  # noqa: E402
import twr  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from mercado import Mercado, BONOS, dias, fin_de_mes  # noqa: E402,F401


class _Respuesta:
    def __init__(self, status, cuerpo):
        self.status_code, self._c, self.ok = status, cuerpo, status == 200

    def json(self):
        return self._c


class Camino:
    """`Camino(test, mercado)`: arranca los parches (se frenan solos al terminar el
    test) y carga el dólar del mercado en `fx_rates_daily`."""

    def __init__(self, test, mercado: Mercado):
        self.t, self.m = test, mercado
        self.fecha_cron = date.today()
        self.red_bloqueada = []
        # Bonos con precio vivo pero SIN velas históricas en data912 (como un bono
        # nuevo o una especie que data912 no tiene): la reconstrucción los deja al costo.
        self.sin_historia = set()
        camino = self

        class _Yahoo:
            def __init__(self, sym):
                self.sym = sym

            def history(self, start, interval="1mo", **k):
                return camino._yahoo(self.sym, start, interval)

        for p in (mock.patch("yfinance.Ticker", _Yahoo),
                  mock.patch.object(sj, "fetch_prices_for_symbols", self._precios_cron),
                  mock.patch.object(sj, "apply_last_known_prices", lambda *a, **k: {}),
                  mock.patch.object(main, "_fetch_dolar", self._dolar),
                  mock.patch.object(requests.Session, "request", self._red)):
            p.start()
            test.addCleanup(p.stop)
        # El universo de renta fija de data912 (feed vivo, por 100 nominales: en pesos
        # el ticker, en dólares la especie 'D').
        previo = dict(main._data912_cache)
        test.addCleanup(main._data912_cache.update, previo)
        hoy = date.today()
        univ = {}
        for b in BONOS:
            univ[b] = round(mercado.ars(b, hoy) * 100, 2)
            univ[b + "D"] = round(mercado.usd(b, hoy) * 100, 4)
        main._data912_cache.update({"data": univ, "ts": time.time() + 10 ** 7})
        bf._HIST_CACHE.clear()
        test.addCleanup(bf._HIST_CACHE.clear)
        self.http = TestClient(main.app)
        self._cargar_fx()

    # ── red reemplazada ──
    def _yahoo(self, sym, start, interval):
        hoy = date.today()
        if interval == "1d":
            idx, vals = [], []
            for d in dias(date.fromisoformat(str(start)[:10]), hoy - timedelta(days=1)):
                p = self.m.precio_clave(sym, d)
                if p is None:
                    return pd.DataFrame()
                idx.append(pd.Timestamp(d))
                vals.append(float(p))
            return pd.DataFrame({"Close": vals}, index=pd.DatetimeIndex(idx))
        d0 = date.fromisoformat(str(start)[:10]).replace(day=1)
        idx, vals = [], []
        y, mo = d0.year, d0.month
        while date(y, mo, 1) <= hoy:
            p = self.m.precio_clave(sym, min(fin_de_mes(y, mo), hoy))
            if p is None:
                return pd.DataFrame()
            idx.append(pd.Timestamp(date(y, mo, 1)))
            vals.append(float(p))
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return pd.DataFrame({"Close": vals}, index=pd.DatetimeIndex(idx))

    def _red(self, method, url, *a, **k):
        # Reemplaza `requests.Session.request`: llega ligado a ESTE objeto, sin la sesión.
        url = str(url)
        if url.startswith("https://data912.com/historical/"):
            tipo, ticker = url.split("/historical/", 1)[1].split("/", 1)
            usd = ticker.endswith("D") and ticker[:-1] in BONOS
            base = ticker[:-1] if usd else ticker
            if tipo != "bonds" or base not in BONOS or base in self.sin_historia:
                return _Respuesta(404, {"detail": "not found"})
            filas = [{"date": d.isoformat(),
                      "c": round((self.m.usd(base, d) if usd else self.m.ars(base, d)) * 100,
                                 4 if usd else 2)}
                     for d in dias(date(2023, 6, 1), date.today() - timedelta(days=1))]
            return _Respuesta(200, filas)
        self.red_bloqueada.append(url[:120])
        raise requests.ConnectionError(f"test: red bloqueada ({url})")

    def _precios_cron(self, symbols, crypto_yf=None, *a, **k):
        return {s: self.m.precio_clave(s, self.fecha_cron) for s in symbols}

    def _dolar(self, casa):
        d = self.fecha_cron
        v = {"blue": self.m.blue(d), "bolsa": self.m.mep(d), "mep": self.m.mep(d),
             "contadoconliqui": self.m.ccl(d)}.get(casa, self.m.blue(d))
        return {"compra": v * 0.99, "venta": v * 1.01, "medio": v}

    def _cargar_fx(self, desde="2023-06-01"):
        conn = main.get_db()
        try:
            filas = []
            for d in dias(desde, date.today()):
                b, mp = self.m.blue(d), self.m.mep(d)
                filas.append((d.isoformat(), b * 1.01, b * 0.99, mp * 1.005, mp * 0.995, "manual"))
            with conn:
                conn.executemany(
                    "INSERT INTO fx_rates_daily (date, blue_venta, blue_compra, mep_venta, "
                    "mep_compra, source) VALUES (?,?,?,?,?,?) ON CONFLICT (date) DO UPDATE SET "
                    "blue_venta=EXCLUDED.blue_venta, blue_compra=EXCLUDED.blue_compra, "
                    "mep_venta=EXCLUDED.mep_venta, mep_compra=EXCLUDED.mep_compra", filas)
        finally:
            conn.close()

    # ── cuenta ──
    def usuario(self, email):
        conn = main.get_db()
        try:
            with conn:
                self.uid = conn.execute(
                    "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                    (email, "x")).lastrowid
                conn.execute("INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
                             "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
                             (self.uid, "tc_blue", str(round(self.m.blue(date.today())))))
        finally:
            conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        return self.uid

    def _esperar(self, limite=120):
        t = time.time() + limite
        while time.time() < t:
            with main._MTM_RUNNING_LOCK:
                if self.uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.t.fail("la reconstrucción no terminó")

    def subir(self, nombre, contenido, broker, fmt, extra=None):
        data = {"broker": broker, "format": fmt, **(extra or {})}
        r = self.http.post("/api/imports/preview", headers=self.h, data=data,
                           files=[("files", (nombre, io.BytesIO(contenido)))])
        self.t.assertEqual(r.status_code, 200, r.text)
        c = self.http.post("/api/imports/confirm", headers=self.h,
                           json={"session_id": r.json()["session_id"], "aprobar_tickers": []})
        self.t.assertEqual(c.status_code, 200, c.text)
        self._esperar()

    def subir_foto(self, nombre, contenido, broker, fmt):
        r = self.http.post("/api/imports/tenencia/preview", headers=self.h,
                           data={"broker": broker, "format": fmt},
                           files={"file": (nombre, io.BytesIO(contenido))})
        self.t.assertEqual(r.status_code, 200, r.text)
        c = self.http.post("/api/imports/confirm", headers=self.h,
                           json={"session_id": r.json()["session_id"], "aprobar_tickers": []})
        self.t.assertEqual(c.status_code, 200, c.text)
        self._esperar()

    def cron(self, desde, hasta):
        """El cron diario real, día hábil por día hábil, con los precios de ESE día."""
        conn = main.get_db()
        try:
            for d in dias(desde, hasta):
                if d.weekday() >= 5:
                    continue
                self.fecha_cron = d
                with conn:
                    sj.take_snapshot_for_user(conn, self.uid, self.m.blue(d), {},
                                              target_date=d.isoformat(), tc_mep=self.m.mep(d))
        finally:
            self.fecha_cron = date.today()
            conn.close()

    def reconstruir(self):
        conn = main.get_db()
        try:
            with conn:
                return bf.backfill_user(conn, self.uid, date.today())
        finally:
            conn.close()

    def curva(self, modo, desde=None, hasta=None):
        conn = main.get_db()
        try:
            return twr.curva_indexada(conn, self.uid, desde, hasta, modo=modo)
        finally:
            conn.close()

    def q(self, sql, *a):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, a).fetchall()]
        finally:
            conn.close()
