"""Arnés: corre un usuario por EL MISMO CAMINO QUE PRODUCCIÓN, con precios controlados.

    subida HTTP  /api/imports/preview → /api/imports/confirm   (movimientos)
                 /api/imports/tenencia/preview → /confirm      (foto de tenencia)
    post-proceso del confirm (rebuild FIFO, sweeps, recalc, snapshots al costo)
    reconstrucción a mercado en su hilo (scripts/backfill_historical_mtm.backfill_user)
    cron diario real (snapshots_job.take_snapshot_for_user) para las fechas que pidas
    lectores: twr.curva_indexada / rendimiento_publicable en los dos modos + endpoints

Lo único reemplazado es la RED: Yahoo (yfinance.Ticker), la foto de precios del cron
(sj.fetch_prices_for_symbols), el universo de bonos de data912 (caché precargada) y el
dólar (fx_rates_daily precargada). Cualquier otro intento de salir a internet se
registra en ARNES.red_bloqueada y falla — así se sabe qué paso dependió de la red.

Uso:  import arnes; a = arnes.Arnes(mercado); uid = a.usuario("x@rendi.test")
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
from datetime import date, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(AQUI, "..", "..", "backend"))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

# La base SIEMPRE temporal, antes de importar main (main lee DB_PATH al importarse y
# si no está cae a backend/trading.db).
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="arnes_")
_TMP.close()
os.environ["DB_PATH"] = _TMP.name
os.environ.setdefault("SECRET_KEY", "arnes-auditoria")
for _k in ("RESEND_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_k, None)

# ── Red bloqueada (se registra cada intento) ──────────────────────────────────
import requests  # noqa: E402

RED_BLOQUEADA: list = []
# Respuestas que el arnés SÍ sirve desde el mercado inventado: {prefijo de URL:
# función(url) -> (status, json)}. Lo carga `Arnes` (las velas de data912).
SERVIDAS: dict = {}


class _RespuestaFalsa:
    def __init__(self, status, cuerpo):
        self.status_code, self._c = status, cuerpo
        self.ok = status == 200

    def json(self):
        return self._c


def _sin_red(self, method, url, *a, **k):
    for pref, fn in SERVIDAS.items():
        if str(url).startswith(pref):
            return _RespuestaFalsa(*fn(str(url)))
    RED_BLOQUEADA.append(str(url)[:120])
    raise requests.ConnectionError(f"arnés: red bloqueada ({url})")


requests.Session.request = _sin_red
try:
    import httpx  # noqa: E402

    def _sin_red_httpx(self, request, *a, **k):
        RED_BLOQUEADA.append(str(request.url)[:120])
        raise httpx.ConnectError("arnés: red bloqueada")
    httpx.HTTPTransport.handle_request = _sin_red_httpx
except Exception:
    pass

import io as _io  # noqa: E402,F811
import contextlib  # noqa: E402

with contextlib.redirect_stdout(_io.StringIO()):
    import main  # noqa: E402
import snapshots_job as sj  # noqa: E402
import twr  # noqa: E402
import scripts.backfill_historical_mtm as bf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import pandas as pd  # noqa: E402

from mercado import Mercado, BONOS, dias, fin_de_mes  # noqa: E402

FECHA_CRON = {"d": date.today()}


class _YahooFalso:
    """yfinance.Ticker con el mercado sintético: así corre el `_fetch_monthly_close`
    de verdad (con sus salteos de bonos/FCI)."""
    mercado: Mercado = None

    def __init__(self, sym):
        self.sym = sym

    def history(self, start, interval="1mo", auto_adjust=False, timeout=8, **k):
        m = _YahooFalso.mercado
        hoy = date.today()
        if interval == "1d":
            # El cierre de cada día (el mercado inventado se mueve todos los días).
            # Lo pide la foto del día anterior a un aporte grande; el código de
            # antes nunca pedía velas diarias.
            idx, vals = [], []
            for d in dias(date.fromisoformat(str(start)[:10]), hoy - timedelta(days=1)):
                p = m.precio_clave(self.sym, d)
                if p is None:
                    return pd.DataFrame()
                idx.append(pd.Timestamp(d))
                vals.append(float(p))
            return pd.DataFrame({"Close": vals}, index=pd.DatetimeIndex(idx))
        d0 = date.fromisoformat(str(start)[:10]).replace(day=1)
        idx, vals = [], []
        y, mo = d0.year, d0.month
        while date(y, mo, 1) <= hoy:
            fm = min(fin_de_mes(y, mo), hoy)
            p = m.precio_clave(self.sym, fm)
            if p is None:
                return pd.DataFrame()
            idx.append(pd.Timestamp(date(y, mo, 1)))
            vals.append(float(p))
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return pd.DataFrame({"Close": vals}, index=pd.DatetimeIndex(idx))


class Arnes:
    def __init__(self, mercado: Mercado):
        self.m = mercado
        _YahooFalso.mercado = mercado
        import yfinance
        yfinance.Ticker = _YahooFalso
        bf._HIST_CACHE.clear()
        sj.fetch_prices_for_symbols = self._precios_cron
        sj.apply_last_known_prices = lambda *a, **k: {}
        # Universo de renta fija de data912 (prod: los bonos van al costo en la
        # reconstrucción porque data912 no tiene historia).
        hoy = date.today()
        univ = {}
        for b in BONOS:
            univ[b] = round(mercado.ars(b, hoy) * 100, 2)
            univ[b + "D"] = round(mercado.usd(b, hoy) * 100, 4)
        main._data912_cache["data"] = univ
        main._data912_cache["ts"] = time.time() + 10 ** 7
        # Las velas diarias de data912 (`/historical/bonds/<ticker>`), con la
        # misma convención que el feed vivo de arriba: por 100 nominales, en pesos
        # el ticker base y en dólares la especie 'D'. Es lo que lee la
        # reconstrucción para la renta fija (H3); el código de antes no lo pedía.
        SERVIDAS["https://data912.com/historical/"] = self._velas_data912
        main._fetch_dolar = self._dolar
        self.http = TestClient(main.app)
        self._fx_cargado = False

    # ── red reemplazada ──
    def _velas_data912(self, url):
        tipo, ticker = url.split("/historical/", 1)[1].split("/", 1)
        base, usd = ((ticker[:-1], True) if ticker.endswith("D") and ticker[:-1] in BONOS
                     else (ticker, False))
        if tipo != "bonds" or base not in BONOS:
            return 404, {"detail": "not found"}
        hoy = date.today()
        filas = []
        # Todos los días, también sábados y domingos: el mercado inventado se mueve
        # todos los días (igual que el Yahoo falso, que cierra el mes en el último
        # día calendario). Con sólo días hábiles, el cierre de un mes que termina
        # en domingo salía del viernes y el error era del arnés, no de Rendi.
        for d in dias(date(2023, 6, 1), hoy - timedelta(days=1)):
            p = self.m.usd(base, d) if usd else self.m.ars(base, d)
            filas.append({"date": d.isoformat(), "c": round(p * 100, 4 if usd else 2)})
        return 200, filas

    def _precios_cron(self, symbols, crypto_yf=None, *a, **k):
        d = FECHA_CRON["d"]
        return {s: self.m.precio_clave(s, d) for s in symbols}

    def _dolar(self, casa):
        d = FECHA_CRON["d"]
        v = {"blue": self.m.blue(d), "bolsa": self.m.mep(d), "mep": self.m.mep(d),
             "contadoconliqui": self.m.ccl(d)}.get(casa, self.m.blue(d))
        return {"compra": v * 0.99, "venta": v * 1.01, "medio": v}

    def cargar_fx(self, desde="2023-06-01"):
        conn = main.get_db()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(fx_rates_daily)")}
        hoy = date.today()
        filas = []
        for d in dias(desde, hoy):
            b, mp = self.m.blue(d), self.m.mep(d)
            fila = {"date": d.isoformat(), "blue_venta": b * 1.01, "blue_compra": b * 0.99,
                    "mep_venta": mp * 1.005, "mep_compra": mp * 0.995, "source": "manual"}
            filas.append({k: v for k, v in fila.items() if k in cols})
        ks = list(filas[0])
        with conn:
            conn.executemany(
                f"INSERT INTO fx_rates_daily ({','.join(ks)}) VALUES ({','.join('?' * len(ks))}) "
                f"ON CONFLICT (date) DO UPDATE SET " + ",".join(f"{k}=EXCLUDED.{k}" for k in ks if k != "date"),
                [tuple(f[k] for k in ks) for f in filas])
        conn.close()
        self._fx_cargado = True

    # ── cuenta ──
    def usuario(self, email, tc_blue=None):
        if not self._fx_cargado:
            self.cargar_fx()
        conn = main.get_db()
        with conn:
            uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                               (email, "x")).lastrowid
            tc = tc_blue or round(self.m.blue(date.today()))
            conn.execute("INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
                         "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
                         (uid, "tc_blue", str(tc)))
        conn.close()
        self.uid = uid
        self.h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        return uid

    def _esperar_mtm(self, uid, limite=180):
        t = time.time() + limite
        while time.time() < t:
            with main._MTM_RUNNING_LOCK:
                if uid not in main._MTM_RUNNING:
                    return True
            time.sleep(0.05)
        return False

    def subir(self, archivos, broker=None, fmt=None, confirmar=True, aprobar=None, extra=None):
        """archivos: [(nombre, bytes)]. Devuelve (preview_json, confirm_json)."""
        files = [("files", (n, io.BytesIO(b))) for n, b in archivos]
        data = {}
        if broker:
            data["broker"] = broker
        if fmt:
            data["format"] = fmt
        data.update(extra or {})
        r = self.http.post("/api/imports/preview", files=files, data=data, headers=self.h)
        prev = _json(r)
        if r.status_code != 200 or not confirmar:
            return prev, None
        c = self.http.post("/api/imports/confirm", headers=self.h,
                           json={"session_id": prev["session_id"],
                                 "aprobar_tickers": aprobar or []})
        self._esperar_mtm(self.uid)
        return prev, _json(c)

    def subir_foto(self, nombre, contenido, broker, fmt=None, confirmar=True, aprobar=None):
        data = {"broker": broker}
        if fmt:
            data["format"] = fmt
        r = self.http.post("/api/imports/tenencia/preview", headers=self.h, data=data,
                           files={"file": (nombre, io.BytesIO(contenido))})
        prev = _json(r)
        if r.status_code != 200 or not confirmar:
            return prev, None
        c = self.http.post("/api/imports/confirm", headers=self.h,
                           json={"session_id": prev["session_id"],
                                 "aprobar_tickers": aprobar or []})
        self._esperar_mtm(self.uid)
        return prev, _json(c)

    def cron(self, desde, hasta, solo_habiles=True):
        """El cron diario real, fecha por fecha, con los precios de ESA fecha."""
        conn = main.get_db()
        n = 0
        for d in dias(desde, hasta):
            if solo_habiles and d.weekday() >= 5:
                continue
            FECHA_CRON["d"] = d
            with conn:
                sj.take_snapshot_for_user(conn, self.uid, self.m.blue(d), {},
                                          target_date=d.isoformat(), tc_mep=self.m.mep(d))
            n += 1
        FECHA_CRON["d"] = date.today()
        conn.close()
        return n

    def reconstruir(self):
        """La misma reconstrucción que dispara el confirm, sincrónica (para después
        del cron o de una foto)."""
        conn = main.get_db()
        with conn:
            res = bf.backfill_user(conn, self.uid, date.today())
        conn.close()
        return res

    # ── lectura ──
    def q(self, sql, *a):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, a).fetchall()]
        finally:
            conn.close()

    def motor(self, desde=None, hasta=None):
        conn = main.get_db()
        out = {}
        try:
            for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
                c = twr.curva_indexada(conn, self.uid, desde, hasta, modo=modo)
                rp = twr.rendimiento_publicable(conn, self.uid, modo=modo, desde=desde, hasta=hasta)
                out[modo] = {
                    "twr_pct": None if c.get("twr") is None else round(c["twr"] * 100, 2),
                    "ventana": (c.get("ventana_desde"), c.get("ventana_hasta")),
                    "motivo": c.get("motivo"), "base_del_twr": c.get("base_del_twr"),
                    "publicable": {k: rp.get(k) for k in ("pct", "base", "motivo", "desde", "hasta", "meses")},
                    "extra": {k: c.get(k) for k in ("contable_superado", "contable_realineado",
                                                    "cortes_capital_chico", "cagr", "drawdown",
                                                    "max_drawdown", "pico")
                              if k in c},
                }
        finally:
            conn.close()
        return out

    def get(self, url):
        r = self.http.get(url, headers=self.h)
        return r.status_code, _json(r)


def _json(r):
    try:
        return r.json()
    except Exception:
        return {"_status": r.status_code, "_text": r.text[:500]}


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, default=str, indent=1)


def resumen(a: "Arnes", desde=None, hasta=None) -> dict:
    """Lo que hay que mirar de una cuenta después del import, en un dict."""
    uid = a.uid
    me = a.q("SELECT year, month, capital_inicio ci, capital_final cf, deposits dep, "
             "withdrawals wd, pnl_realized pnl FROM monthly_entries "
             "WHERE user_id=? AND broker='global' ORDER BY year, month", uid)
    snaps = a.q("SELECT date, source, total_value, net_deposited, mtm_coverage, base, apto "
                "FROM snapshots WHERE user_id=? ORDER BY date", uid)
    por_src = {}
    for s in snaps:
        k = f"{s['source']}|{s.get('base')}|apto={s.get('apto')}"
        por_src[k] = por_src.get(k, 0) + 1
    pos = a.q("SELECT broker, asset, asset_type, is_cash, quantity, invested, currency "
              "FROM positions WHERE user_id=? AND ABS(quantity) > 1e-9 ORDER BY broker, asset", uid)
    nt = a.q("SELECT n.operation_type t, n.currency c, COUNT(*) n, ROUND(SUM(n.gross_amount),2) monto "
             "FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
             "WHERE b.user_id=? AND b.status='confirmed' GROUP BY 1,2 ORDER BY 1,2", uid)
    return {"motor": a.motor(desde, hasta), "monthly": me, "snaps_por_origen": por_src,
            "snaps": snaps, "positions": pos, "normalized": nt,
            "red_bloqueada": sorted(set(RED_BLOQUEADA))}


def tx_confirmadas(a: "Arnes", session_id=None):
    sql = ("SELECT n.* FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
           "WHERE b.user_id=?")
    args = [a.uid]
    if session_id:
        sql += " AND b.id=?"
        args.append(session_id)
    return a.q(sql + " ORDER BY n.date", *args)


def mercado_de_archivo(txs, base: "Mercado" = None):
    """Precios observados en las operaciones de un archivo real → series para el
    mercado (pesos para lo local, dólares para lo que opera en USD). No es la verdad
    de mercado: es lo más cercano que hay sin red, y es consistente con el archivo."""
    ars, usd = {}, {}
    for t in txs:
        if t.get("operation_type") not in ("BUY", "SELL"):
            continue
        tk, px, q = t.get("asset_symbol"), t.get("unit_price"), t.get("quantity")
        if not tk or not px or px <= 0 or not q:
            continue
        cur = (t.get("currency") or "").upper()
        (usd if cur in ("USD", "USDT", "USDC") else ars).setdefault(tk, []).append((t["date"][:10], px))
    return Mercado(extra_ars=ars, extra_usd=usd)


@contextlib.contextmanager
def copia_de_la_base():
    """La base actual copiada a un temporal y `main` apuntando a la copia: para
    contrafácticos que escriben, sin tocar la corrida."""
    import shutil
    previo = main.DB_PATH
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="cf_").name
    c = main.get_db()
    c.execute("PRAGMA wal_checkpoint(FULL)")
    c.close()
    shutil.copy(previo, tmp)
    main.DB_PATH = tmp
    try:
        yield tmp
    finally:
        main.DB_PATH = previo
        for p in (tmp, tmp + "-wal", tmp + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


_SIN_COBROS = ("FROM operations WHERE user_id=?",
               "FROM operations WHERE user_id=? AND op_type NOT IN ('Dividendo','Amortización','Interés')")


def contrafactico_sin_cobros(a: "Arnes"):
    """H1: ¿qué publicaría el motor si los cobros (dividendo/cupón/amortización de
    `operations`) no contaran como 'tenencia que la reconstrucción no ve'?"""
    orig = bf._tenencia_no_vista

    class _Filtro:
        def __init__(s, c):
            s.c = c

        def execute(s, sql, args=()):
            return s.c.execute(sql.replace(*_SIN_COBROS) if "FROM operations" in sql else sql, args)

    bf._tenencia_no_vista = lambda conn, uid, d, vistos: orig(_Filtro(conn), uid, d, vistos)
    try:
        with copia_de_la_base():
            a.reconstruir()
            out = a.motor()
            out["snaps"] = a.q("SELECT date, source, ROUND(total_value) v, ROUND(net_deposited) nd, "
                               "mtm_coverage cob, base, apto FROM snapshots WHERE user_id=? ORDER BY date", a.uid)
            conn = main.get_db()
            try:
                out["curva"] = {m: twr.curva_indexada(conn, a.uid, modo=m) for m in ("certero", "estimado")}
            finally:
                conn.close()
            out["mtm_aptas"] = a.q("SELECT SUM(apto=1) si, SUM(apto=0) no FROM snapshots "
                                   "WHERE user_id=? AND source='mtm_backfill'", a.uid)[0]
    finally:
        bf._tenencia_no_vista = orig
    return out
