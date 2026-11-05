"""¿Cuántas conexiones a la base quedan tomadas mientras la LISTA DE SEGUIMIENTO
espera a Yahoo?

Segunda parte del hallazgo 4 de la auditoría del backtesting. La primera
(`medir_conexion_esperando_yahoo.py`) midió la ficha, que tiene un freno de 8
lecturas pesadas a la vez. La lista de seguimiento (`GET /api/watchlist`) no
tiene freno: abre la base, pide la variación del día de cada activo
(`_variacion_del_dia`, que baja de Yahoo hasta 8 s) y recién después cierra.
Con más personas a la vez que lugares en el pozo (10 por copia de la app,
`pgshim._Pozo`), las que quedan afuera —y cualquier otro pedido, aunque sea
liviano— esperan a que Yahoo les conteste a las primeras.

Contra un Postgres LOCAL de prueba (`scripts/pg_de_prueba.py`), por HTTP en el
mismo proceso (TestClient), con un Yahoo falso que tarda ESPERA_YAHOO segundos
(8 por defecto: `PRECIOS_TOPE_YAHOO_SEG`):
  1. Sin carga: cuánto tarda un pedido liviano (`GET /api/brokers`: chequear la
     sesión y leer una tabla), de a uno y 20 a la vez.
  2. Con 12 listas de seguimiento esperando a Yahoo (12 cuentas, 3 activos de
     EEUU distintos cada una): cuántas de las 10 conexiones están prestadas en
     medio de la espera, y lo mismo del 1.

USO (desde backend/, con el DSN que imprime scripts/pg_de_prueba.py):

    DATABASE_URL='<DSN>' python3 ../audit/_scripts/medir_conexion_esperando_afuera.py [etiqueta]

Se niega a correr contra algo que no sea un Postgres local. Usa un esquema propio
(`medir_<pid>`) que borra al terminar, y `DB_PATH` a un archivo temporal (regla
del repo: un script que importa `main` nunca toca `backend/trading.db`).
"""
import os
import statistics
import sys
import tempfile
import threading
import time
from datetime import timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "backend")

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

DSN = os.environ.get("DATABASE_URL", "").strip()
if not DSN:
    raise SystemExit("Falta DATABASE_URL: el DSN de un Postgres de prueba (scripts/pg_de_prueba.py).")
_host = conninfo_to_dict(DSN).get("host") or ""
if not (_host.startswith("/") or _host in ("localhost", "127.0.0.1", "::1")):
    raise SystemExit(f"Sólo contra un Postgres LOCAL de prueba (host={_host!r}).")
if os.path.exists(os.path.join(BACKEND, ".env")):
    raise SystemExit("backend/.env existe: main lo lee pisando el entorno y podría cambiar DATABASE_URL.")
if os.environ.get("RENDI_PG_POOL_MAX"):
    raise SystemExit("RENDI_PG_POOL_MAX está puesta: la medición es con el pozo de producción (10).")

ETIQUETA = sys.argv[1] if len(sys.argv) > 1 else ""
ESPERA_YAHOO = float(os.environ.get("ESPERA_YAHOO", "8"))
LISTAS = 12
ESQUEMA = f"medir_{os.getpid()}"
with psycopg.connect(DSN, autocommit=True) as _c:
    _c.execute(f'CREATE SCHEMA "{ESQUEMA}"')
os.environ["DATABASE_URL"] = make_conninfo(DSN, options=f"-c search_path={ESQUEMA}")
os.environ["RENDI_MANTENIMIENTO"] = "0"
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, BACKEND)

import logging  # noqa: E402
logging.disable(logging.WARNING)

import pandas as pd  # noqa: E402
import requests  # noqa: E402
import main  # noqa: E402
import pgshim  # noqa: E402
import pricing.yahoo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from home.market import SP500_TOP_50  # noqa: E402

assert main.USANDO_PG and ESQUEMA in main.DATABASE_URL, "no quedó apuntando al esquema de prueba"

# ─── Sin red: Yahoo lento y falso; data912 y lo demás, vacíos ────────────────
_hoy = hoy_art_date()
RUEDAS, _d = [], _hoy - timedelta(days=1)
while len(RUEDAS) < 22:
    if _d.weekday() < 5:
        RUEDAS.append(_d)
    _d -= timedelta(days=1)
RUEDAS.sort()
LLAMADAS_YAHOO = []


def yahoo_lento(ticker, period, interval, auto_adjust, timeout):
    LLAMADAS_YAHOO.append(ticker)
    time.sleep(ESPERA_YAHOO)
    c = [100.0 + i * 0.1 for i in range(len(RUEDAS))]
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1000.0] * len(c)},
                        index=pd.DatetimeIndex([pd.Timestamp(d) for d in RUEDAS]))


class _Nada:
    status_code = 404

    def json(self):
        return []


pricing.yahoo._historia = yahoo_lento
main._fetch_prev_close_one = lambda t: None
main._fetch_data912_equities = lambda: {}
main._fetch_data912_bonds = lambda: {}
main._check_rate_limit = lambda *a, **k: None
requests.get = lambda *a, **k: _Nada()

C = TestClient(main.app)
SIMBOLOS = [s for s in SP500_TOP_50 if s.isalpha()][:3 * LISTAS]
assert len(set(SIMBOLOS)) == 3 * LISTAS, SIMBOLOS
with main.db_abierta() as conn:
    UIDS = [conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                         "VALUES (?, 'x', 1, 1, 'free')", (f"medir{k}@rendi.test",)).lastrowid
            for k in range(LISTAS + 1)]
    for k, u in enumerate(UIDS[:LISTAS]):
        for s in SIMBOLOS[3 * k:3 * k + 3]:
            conn.execute("INSERT INTO watchlist (user_id, symbol, asset_type) VALUES (?, ?, 'STOCK')", (u, s))
    conn.commit()
H = [{"Authorization": f"Bearer {main.create_token(u)}"} for u in UIDS]
PESADOS, LIVIANO = H[:LISTAS], H[LISTAS]


def prestadas() -> int:
    pozo = pgshim._POZOS.get(main.DATABASE_URL)
    return 0 if pozo is None else pozo._maximo - pozo._cupo._value


def liviano():
    t0 = time.perf_counter()
    r = C.get("/api/brokers", headers=LIVIANO)
    return (time.perf_counter() - t0) * 1000, r.status_code


def de_a_uno(n=5):
    return [liviano() for _ in range(n)]


def juntos(n=20):
    out = [None] * n

    def uno(i):
        out[i] = liviano()
    hilos = [threading.Thread(target=uno, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return out


def ms(xs):
    v = sorted(x for x, _ in xs)
    codigos = sorted({c for _, c in xs})
    return f"mediana {statistics.median(v):7.1f} ms · máx {v[-1]:7.1f} ms · códigos {codigos}"


def lista(k, out):
    t0 = time.perf_counter()
    r = C.get("/api/watchlist", headers=PESADOS[k])
    precios = sum(1 for it in (r.json().get("items") or []) if it.get("price")) if r.status_code == 200 else 0
    out[k] = (r.status_code, time.perf_counter() - t0, precios)


try:
    print(f"=== {ETIQUETA or 'medición'} · Postgres local · pozo de "
          f"{pgshim._pozo_de(main.DATABASE_URL)._maximo} conexiones ===")
    print("\n1. Sin carga")
    print(f"  pedido liviano de a uno (5):   {ms(de_a_uno())}")
    print(f"  pedido liviano, 20 a la vez:   {ms(juntos())}")
    print(f"  conexiones prestadas en reposo: {prestadas()} de 10")

    print(f"\n2. Con {LISTAS} listas de seguimiento esperando a Yahoo")
    res = [None] * LISTAS
    hilos = [threading.Thread(target=lista, args=(k, res)) for k in range(LISTAS)]
    for h in hilos:
        h.start()
    # Que lleguen a esperar a Yahoo (el falso anota al empezar a esperar).
    t_fin = time.monotonic() + 5
    while len(LLAMADAS_YAHOO) < 3 * LISTAS and time.monotonic() < t_fin:
        time.sleep(0.05)
    time.sleep(0.5)
    p = prestadas()
    t0 = time.perf_counter()
    uno = de_a_uno()
    varios = juntos()
    medio = time.perf_counter() - t0
    for h in hilos:
        h.join()
    print(f"  pedidos a Yahoo en curso cuando se midió: {len(LLAMADAS_YAHOO)} de {3 * LISTAS} "
          f"(Yahoo falso: {ESPERA_YAHOO:.0f} s cada uno)")
    print(f"  conexiones prestadas en medio de la espera: {p} de 10")
    print(f"  pedido liviano de a uno (5):   {ms(uno)}")
    print(f"  pedido liviano, 20 a la vez:   {ms(varios)}")
    print(f"  (las dos mediciones del pedido liviano tardaron {medio:.1f} s en total)")
    print(f"  las {LISTAS} listas: códigos {sorted({r[0] for r in res})}, con precio "
          f"{sum(r[2] for r in res)} de {3 * LISTAS} activos, tardaron "
          f"{min(r[1] for r in res):.1f}–{max(r[1] for r in res):.1f} s")
finally:
    pgshim.cerrar_pozos()
    with psycopg.connect(DSN, autocommit=True) as _c:
        _c.execute(f'DROP SCHEMA IF EXISTS "{ESQUEMA}" CASCADE')
    for _p in (_tmp.name, _tmp.name + "-wal", _tmp.name + "-shm"):
        try:
            os.unlink(_p)
        except OSError:
            pass
