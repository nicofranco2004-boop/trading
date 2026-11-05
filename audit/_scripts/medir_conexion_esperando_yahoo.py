"""¿Cuántas conexiones a la base quedan tomadas mientras la ficha espera a Yahoo?

Hallazgo 4 de la auditoría de seguridad del backtesting (04/11/2026): la ficha de
un activo que nadie sigue lo baja de Yahoo en el momento (hasta 10 s,
`velas_diarias.A_PEDIDO_TOPE_SEG`) y, según el código, mientras espera retiene
una de las conexiones a Postgres (10 por copia de la app, `pgshim._Pozo`). El
freno deja correr 8 lecturas pesadas a la vez (`main.PESADOS_A_LA_VEZ`). La
auditoría lo dedujo leyendo; esto lo MIDE.

Contra un Postgres LOCAL de prueba (`scripts/pg_de_prueba.py`), por HTTP en el
mismo proceso (TestClient), con un Yahoo falso que tarda ESPERA_YAHOO segundos
(8 por defecto; el tope de la ficha es 10):
  1. Sin carga: cuánto tarda un pedido liviano (`GET /api/brokers`: chequear la
     sesión y leer una tabla), de a uno y 20 a la vez.
  2. Con 8 fichas esperando a Yahoo (8 cuentas, 8 activos distintos): cuántas de
     las 10 conexiones están prestadas en medio de la espera, y lo mismo del 1.
  3. Lo mismo, con otras 2 conexiones tomadas por otra cosa mientras tanto (la
     corrida de la noche, que también espera a Yahoo con su conexión en la mano,
     u otro pedido lento): el caso en que el pozo se queda sin lugares.

Qué NO dice: mide la espera principal a Yahoo de la ficha; las otras esperas del
camino a pedido (data912, los splits, la historia de BYMA…) las vigilan las
pruebas (backend/tests/test_velas_a_pedido.py). Y los segundos que espera un
pedido liviano con el pozo lleno los pone el Yahoo falso: son lo que le falta a
Yahoo para contestar (en producción, lo que tarde Yahoo: hasta 10 s, el tope de
la ficha), no una estimación de producción.

USO (desde backend/, con el DSN que imprime scripts/pg_de_prueba.py):

    DATABASE_URL='<DSN>' python3 ../audit/_scripts/medir_conexion_esperando_yahoo.py [etiqueta]

Se niega a correr contra algo que no sea un Postgres local. Usa un esquema propio
(`medir_<pid>`) que borra al salir pase lo que pase (también con Ctrl-C), y
`DB_PATH` a un archivo temporal (regla del repo: un script que importa `main`
nunca toca `backend/trading.db`).
"""
import atexit
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
_partes = conninfo_to_dict(DSN)
_host, _hostaddr = _partes.get("host") or "", _partes.get("hostaddr") or ""
# `hostaddr` manda sobre `host` al conectar: `host=localhost hostaddr=<IP de afuera>` es afuera.
if (not (_host.startswith("/") or _host in ("localhost", "127.0.0.1", "::1"))
        or _hostaddr not in ("", "127.0.0.1", "::1")):
    raise SystemExit(f"Sólo contra un Postgres LOCAL de prueba (host={_host!r}, hostaddr={_hostaddr!r}).")
if os.path.exists(os.path.join(BACKEND, ".env")):
    raise SystemExit("backend/.env existe: main lo lee pisando el entorno y podría cambiar DATABASE_URL.")
if os.environ.get("RENDI_PG_POOL_MAX"):
    raise SystemExit("RENDI_PG_POOL_MAX está puesta: la medición es con el pozo de producción (10).")

ETIQUETA = sys.argv[1] if len(sys.argv) > 1 else ""
ESPERA_YAHOO = float(os.environ.get("ESPERA_YAHOO", "8"))
ESQUEMA = f"medir_{os.getpid()}"
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()


def _limpiar():
    """Al salir, pase lo que pase (también con Ctrl-C): el esquema y el archivo."""
    try:
        import pgshim
        pgshim.cerrar_pozos()
    except Exception:
        pass
    try:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{ESQUEMA}" CASCADE')
    except Exception as ex:
        print(f"⚠️ No se pudo borrar el esquema {ESQUEMA}: {ex!r}")
    for p in (_tmp.name, _tmp.name + "-wal", _tmp.name + "-shm"):
        try:
            os.unlink(p)
        except OSError:
            pass


atexit.register(_limpiar)    # ANTES de crear el esquema
with psycopg.connect(DSN, autocommit=True) as _c:
    _c.execute(f'CREATE SCHEMA "{ESQUEMA}"')
os.environ["DATABASE_URL"] = make_conninfo(DSN, options=f"-c search_path={ESQUEMA}")
os.environ["RENDI_MANTENIMIENTO"] = "0"
os.environ["DB_PATH"] = _tmp.name
sys.path.insert(0, BACKEND)

import logging  # noqa: E402
logging.disable(logging.WARNING)

import pandas as pd  # noqa: E402
import main  # noqa: E402
import pgshim  # noqa: E402
import velas_diarias  # noqa: E402
import cambios_ratio  # noqa: E402
import pricing.yahoo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from home.market import SP500_TOP_50  # noqa: E402

assert main.USANDO_PG and ESQUEMA in main.DATABASE_URL, "no quedó apuntando al esquema de prueba"

# ─── Sin red: Yahoo lento y falso; data912 y los splits, vacíos ─────────────
_hoy = hoy_art_date()
RUEDAS, _d = [], _hoy - timedelta(days=1)
while len(RUEDAS) < 300:
    if _d.weekday() < 5:
        RUEDAS.append(_d)
    _d -= timedelta(days=1)
RUEDAS.sort()
LLAMADAS_YAHOO = []          # (ticker, cuándo empezó a esperar)
ESPERANDO = [0]              # cuántas están esperando a Yahoo AHORA
_candado = threading.Lock()


def yahoo_lento(ticker, period, interval, auto_adjust, timeout):
    with _candado:
        LLAMADAS_YAHOO.append((ticker, time.monotonic()))
        ESPERANDO[0] += 1
    try:
        time.sleep(ESPERA_YAHOO)
    finally:
        with _candado:
            ESPERANDO[0] -= 1
    c = [100.0 + i * 0.1 for i in range(len(RUEDAS))]
    return pd.DataFrame({"Open": c, "High": [x * 1.01 for x in c], "Low": [x * 0.99 for x in c],
                         "Close": c, "Volume": [1000.0] * len(c)},
                        index=pd.DatetimeIndex([pd.Timestamp(d) for d in RUEDAS]))


pricing.yahoo._historia = yahoo_lento
cambios_ratio._splits_de_yahoo = lambda t: []
cambios_ratio._historia_byma = lambda c: {}
main._fetch_data912_equities = lambda: {}
main._check_rate_limit = lambda *a, **k: None
velas_diarias._dormir = lambda s: None

C = TestClient(main.app)
with main.db_abierta() as conn:
    UIDS = [conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                         "VALUES (?, 'x', 1, 1, 'free')", (f"medir{k}@rendi.test",)).lastrowid
            for k in range(9)]
    conn.commit()
H = [{"Authorization": f"Bearer {main.create_token(u)}"} for u in UIDS]
PESADOS, LIVIANO = H[:8], H[8]
SIMBOLOS = [s for s in SP500_TOP_50 if s.isalpha()][:8]
assert len(set(SIMBOLOS)) == 8, SIMBOLOS


def prestadas() -> int:
    pozo = pgshim._POZOS.get(main.DATABASE_URL)
    return 0 if pozo is None else pozo._maximo - pozo._cupo._value


TERMINARON = []              # cuándo terminó cada pedido liviano (para ubicarlo en la espera)


def liviano():
    t0 = time.perf_counter()
    r = C.get("/api/brokers", headers=LIVIANO)
    with _candado:
        TERMINARON.append(time.monotonic())
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


def ficha(k, out):
    t0 = time.perf_counter()
    r = C.get(f"/api/tecnico/{SIMBOLOS[k]}", headers=PESADOS[k])
    j = r.json() if r.status_code == 200 else {}
    out[k] = (r.status_code, time.perf_counter() - t0, j.get("disponible"), j.get("motivo"))


def escenario(titulo, otras_tomadas=0):
    with main.db_abierta() as conn:
        conn.execute("DELETE FROM velas_diarias")
        conn.execute("DELETE FROM velas_estado")
        conn.commit()
    velas_diarias._a_pedido_hechos.clear()
    main._freno_reiniciar()
    del LLAMADAS_YAHOO[:]
    del TERMINARON[:]
    print(f"\n{titulo}")
    otras = [main.get_db() for _ in range(otras_tomadas)]
    res = [None] * 8
    hilos = [threading.Thread(target=ficha, args=(k, res)) for k in range(8)]
    for h in hilos:
        h.start()
    # Que las 8 lleguen a esperar a Yahoo (el falso anota al empezar a esperar).
    t_fin = time.monotonic() + 5
    while len(LLAMADAS_YAHOO) < 8 and time.monotonic() < t_fin:
        time.sleep(0.05)
    time.sleep(0.5)
    # Las tres cosas en el MISMO momento: cuántas esperan, desde cuándo, y el pozo.
    with _candado:
        esperando = ESPERANDO[0]
        empezo = min((t for _, t in LLAMADAS_YAHOO), default=time.monotonic())
    p = prestadas()
    a_los = time.monotonic() - empezo
    t0 = time.perf_counter()
    uno = de_a_uno()
    varios = juntos()
    medio = time.perf_counter() - t0
    for h in hilos:
        h.join()
    for c in otras:
        c.close()
    print(f"  al medir: {esperando} de 8 fichas esperando a Yahoo, a los {a_los:.1f} s de los "
          f"{ESPERA_YAHOO:.0f} s que tarda el Yahoo falso")
    print(f"  conexiones prestadas en ese momento: {p} de 10"
          + (f" ({otras_tomadas} de ellas, de «otra cosa»)" if otras_tomadas else ""))
    print(f"  pedido liviano de a uno (5):   {ms(uno)}")
    print(f"  pedido liviano, 20 a la vez:   {ms(varios)}")
    fines = sorted(t - empezo for t in TERMINARON)
    print(f"  los 25 pedidos livianos terminaron entre los {fines[0]:.1f} y los {fines[-1]:.1f} s de "
          f"empezada la espera ({medio:.1f} s en total)")
    print(f"  las 8 fichas: códigos {sorted({r[0] for r in res})}, disponibles "
          f"{sum(1 for r in res if r[2])} de 8, tardaron {min(r[1] for r in res):.1f}–"
          f"{max(r[1] for r in res):.1f} s")


# El esquema y el archivo los borra `_limpiar` al salir, pase lo que pase (atexit).
print(f"=== {ETIQUETA or 'medición'} · Postgres local · pozo de {pgshim._pozo_de(main.DATABASE_URL)._maximo} "
      f"conexiones · {main.PESADOS_A_LA_VEZ} lecturas pesadas a la vez ===")
main._freno_reiniciar()
print("\n1. Sin carga")
print(f"  pedido liviano de a uno (5):   {ms(de_a_uno())}")
print(f"  pedido liviano, 20 a la vez:   {ms(juntos())}")
print(f"  conexiones prestadas en reposo: {prestadas()} de 10")
escenario("2. Con 8 fichas esperando a Yahoo")
escenario("3. Con 8 fichas esperando a Yahoo y otras 2 conexiones tomadas", otras_tomadas=2)
