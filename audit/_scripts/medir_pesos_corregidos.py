"""El gráfico en pesos de Disney antes y después de corregir con BYMA (06/11/2026).

Corre la descarga de la noche DE VERDAD (`velas_diarias.actualizar`, con Yahoo y
data912 reales) en una base SQLite aparte, dos veces, como va a pasar en producción
las dos primeras noches después de publicar:
  · «antes»: la noche sin la corrección (`_rachas_a_corregir` no devuelve nada) →
    se guarda lo que da Yahoo, como hasta hoy (DISN.BA clavado en 10.416 desde el
    24/05/2024);
  · «después»: la noche siguiente, con data912 → el último mes corregido no coincide
    con lo guardado (`_historia_reescrita`), se baja la historia entera y se corrige
    entera.
En cada una: la ficha en pesos y en dólares (`tecnico.para_la_ficha`), la lista de
cambios de ratio con el par DISN.BA ↔ DIS (`cambios_ratio.recalcular`, con los
splits de Yahoo y la historia de BYMA de verdad) y lo que ofrecería «Ajustar».

Corre con (red: Yahoo, data912, argentinadatos):
  cd backend && DB_PATH=<carpeta nueva>/medir.db YF_TZ_CACHE_LOCATION=<carpeta nueva> \\
      python3 ../audit/_scripts/medir_pesos_corregidos.py > ../audit/_scripts/medir_pesos_corregidos.out
"""
import os
import sys
from datetime import date, timedelta
from unittest import mock

DB = os.environ.get("DB_PATH") or ""
if not DB or os.path.abspath(DB).endswith(os.path.join("backend", "trading.db")):
    sys.exit("DB_PATH tiene que apuntar a una base nueva y aparte (ver el docstring)")

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "backend")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import logging
logging.disable(logging.WARNING)

import main            # noqa: E402  (arma el esquema en DB_PATH)
import cambios_ratio   # noqa: E402
import tecnico         # noqa: E402
import velas_diarias   # noqa: E402
from pricing import data912  # noqa: E402

TICKERS = ["DISN.BA", "DIS", velas_diarias.SP500]
FECHAS = ("2023-06-30", "2024-12-31", "2025-11-04")


def _f(x, n=0):
    return "—" if x is None else f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _en(cierres: dict, f: str):
    antes = [d for d in sorted(cierres) if d <= f]
    return cierres[antes[-1]] if antes else None


def _rend(cierres: dict):
    ult = max(cierres)
    base = _en(cierres, (date.fromisoformat(ult) - timedelta(days=365)).isoformat())
    return (cierres[ult] / base - 1) * 100 if base else None


def ficha(conn, moneda):
    f = tecnico.para_la_ficha(conn, "DISN", moneda)
    s = tecnico.serie(conn, "DISN", moneda)
    c = {v["date"]: v["close"] for v in s["velas"]}
    lec = f.get("lectura") or {}
    return (f"serie {f.get('ticker')}{' (convertida)' if f.get('convertida') else ''} · último "
            f"{_f(c[max(c)], 2 if moneda == 'usd' else 0)} ({max(c)}) · 1 año {_f(_rend(c), 1)} % · "
            + " · ".join(f"{d} {_f(_en(c, d), 2 if moneda == 'usd' else 0)}" for d in FECHAS)
            + f" · tendencia {lec.get('tendencia')} · vs media 200 {_f(lec.get('dist_media200'), 1)} % · "
              f"RSI {_f(lec.get('rsi'))}")


def clavados(conn):
    filas = [(r["close"], r["volume"]) for r in conn.execute(
        "SELECT close, volume FROM velas_diarias WHERE symbol='DISN.BA' ORDER BY date").fetchall()]
    return sum(1 for a, b in zip(filas, filas[1:]) if b[0] == a[0] and not b[1])


def pasada(conn, nombre):
    res = cambios_ratio.recalcular(conn, ["DISN"], pares={"DISN": "DIS"})
    print(f"## {nombre}")
    print(f"  DISN.BA guardado: {clavados(conn)} ruedas con el mismo cierre que la anterior y sin volumen")
    print(f"  ficha en pesos:   {ficha(conn, 'ars')}")
    print(f"  ficha en dólares: {ficha(conn, 'usd')}")
    print(f"  cambios de ratio: {[(r['fecha'], r['tipo'], r['estado'], r['factor'] or r['factor_medido'], r['en_la_serie']) for r in cambios_ratio.todos(conn, 'DISN')] or 'nada'}"
          f" (sin respuesta de Yahoo: {res.get('sin_yahoo') or 'ninguno'})")
    print(f"  «Ajustar» ofrece: {cambios_ratio.para_lotes(conn, 'DISN') or 'nada'} · el gráfico empalma "
          f"{cambios_ratio.para_el_grafico(conn, 'DISN')['escalones'] or 'nada'}\n")


def main_():
    conn = main.get_db()
    try:
        print(f"Medido el {date.today().isoformat()} sobre {os.path.basename(DB)} (aparte)\n")
        main._backfill_fx_rates_if_empty()
        main._backfill_mep_rates_if_missing()
        main._backfill_compras_if_missing()
        byma = data912.cierres("cedears", "DISN", timeout=20)
        print("BYMA (data912), de referencia: último "
              f"{_f(byma[max(byma)])} ({max(byma)}) · 1 año {_f(_rend(byma), 1)} % · "
              + " · ".join(f"{d} {_f(_en(byma, d))}" for d in FECHAS) + "\n")

        with mock.patch("velas_diarias._rachas_a_corregir", lambda velas, guardado=None: []):
            r = velas_diarias.actualizar(conn, TICKERS, podar=False)
        print("1.ª noche (sin la corrección, como el código de antes):", {k: r.get(k) for k in (
            "completas", "incrementales", "corregidos_con_byma", "byma_sin_respuesta", "reescritas")})
        pasada(conn, "ANTES: lo que da Yahoo (como hoy en producción)")

        r = velas_diarias.actualizar(conn, TICKERS, podar=False)
        print("2.ª noche (con la corrección):", {k: r.get(k) for k in (
            "completas", "incrementales", "corregidos_con_byma", "dias_corregidos_con_byma",
            "byma_sin_respuesta", "reescritas")})
        pasada(conn, "DESPUÉS: corregido con BYMA")

        r = velas_diarias.actualizar(conn, TICKERS, podar=False)
        print("3.ª noche:", {k: r.get(k) for k in (
            "completas", "incrementales", "corregidos_con_byma", "dias_corregidos_con_byma", "reescritas")},
              "← sin bajar otra vez la historia entera")
    finally:
        conn.close()


if __name__ == "__main__":
    main_()
