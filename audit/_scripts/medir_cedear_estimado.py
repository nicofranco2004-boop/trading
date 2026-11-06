"""¿Qué tan cerca del CEDEAR de verdad queda «el CEDEAR estimado»? (06/11/2026)

`tecnico.serie` en pesos, cuando el CEDEAR no tiene su serie en pesos al día (la
ficha a pedido baja sólo la acción de afuera; o la serie en pesos quedó vieja
porque nadie la sigue), dibuja «la acción de afuera × el MEP de cada día»: la
acción ENTERA en pesos, el CEDEAR × su ratio (AAPL ×20, MELI ×120).

Esto mide, con datos REALES, dos maneras de llevarla a la escala del CEDEAR,
contra el cierre de BYMA (data912: la referencia; el '.BA' de Yahoo puede venir
clavado, ver medir_ba_congelados.py):

  A. afuera × MEP ÷ el ratio de la TABLA (lista oficial de Comafi del 17/09/2026,
     `frontend/src/utils/cedearRatio.js`, la que ya usa la pantalla para los
     dividendos);
  B. afuera × MEP ÷ el COCIENTE de un día en común (afuera × MEP ÷ BYMA ese día),
     como si la serie en pesos hubiera dejado de actualizarse hace N ruedas.

Lo que se mira:
  · el último día: cuánto se aleja cada estimación del cierre de BYMA (lo que
    ve la persona en su broker);
  · el último año, día por día: la mediana y los extremos de ese error (si la
    forma del gráfico se sostiene, no sólo la punta);
  · el «ratio medido» de hoy (afuera × MEP ÷ BYMA) contra el de la tabla: la
    diferencia es el dólar de los CEDEARs contra el MEP, y un ratio de la tabla
    que quedó viejo (un cambio de ratio después del 17/09) aparece como un
    error de ×2, ×3…

El MEP es el de la app (`fx.serie_diaria`, por `tecnico._convertir`: la MISMA
cuenta que la ficha), bajado de argentinadatos a una base SQLite APARTE.

Corre con (red: Yahoo, data912, argentinadatos):
  cd backend && DB_PATH=<carpeta nueva>/medir.db YF_TZ_CACHE_LOCATION=<carpeta nueva> \\
      python3 ../audit/_scripts/medir_cedear_estimado.py > ../audit/_scripts/medir_cedear_estimado.out
"""
import os
import statistics
import sys
import time

DB = os.environ.get("DB_PATH") or ""
if not DB or os.path.abspath(DB).endswith(os.path.join("backend", "trading.db")):
    sys.exit("DB_PATH tiene que apuntar a una base nueva y aparte (ver el docstring)")

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(os.path.dirname(os.path.dirname(AQUI)), "backend")
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))
os.chdir(BACKEND)

import logging
logging.disable(logging.WARNING)

import main            # noqa: E402  (arma el esquema en DB_PATH)
import tecnico         # noqa: E402
import velas_diarias   # noqa: E402
from check_cedear_ratios import leer_tabla_js  # noqa: E402
from pricing import data912  # noqa: E402

# Cuántas ruedas atrás pudo quedar vieja la serie en pesos (variante B).
ATRASOS = (6, 20, 60, 250)


def _f(x, n=1):
    return "—" if x is None else (f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", "."))


def _pct(x):
    return None if x is None else 100.0 * x


def main_():
    tabla, _, _ = leer_tabla_js()
    feed = main._fetch_data912_equities() or {}
    cedears = sorted(s for s, v in feed.items() if (v or {}).get("mercado") == "arg_cedears")
    # Los de la tabla que BYMA lista hoy como CEDEAR (los que tienen precio en pesos).
    papeles = [b for b in sorted(tabla) if b in cedears and "-" not in b]
    print(f"Tabla de ratios: {len(tabla)} · CEDEARs que lista BYMA hoy: {len(cedears)} · "
          f"de la tabla y de BYMA: {len(papeles)}")
    sin_tabla = [c for c in cedears if c not in tabla]
    print(f"CEDEARs de BYMA SIN ratio en la tabla: {len(sin_tabla)} (p. ej. {', '.join(sin_tabla[:25])})")

    with main.db_abierta() as conn:
        main._backfill_fx_rates_if_empty()
        main._backfill_mep_rates_if_missing()
        n = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM fx_rates_daily "
                         "WHERE mep_venta IS NOT NULL").fetchone()
        print(f"MEP de argentinadatos: {n[0]} días, del {n[1]} al {n[2]}")
        afuera = sorted({velas_diarias.ticker_de_afuera(b) for b in papeles})
        t0 = time.time()
        res = velas_diarias.actualizar(conn, afuera, podar=False)
        print(f"Yahoo (acciones de afuera, 5 años): {res.get('pedidos')} pedidos, "
              f"{res.get('sin_datos')} sin datos, {time.time() - t0:.0f} s")
        print()

        filas = []
        for b in papeles:
            us = velas_diarias.ticker_de_afuera(b)
            en_pesos = {v["date"]: v["close"] for v in
                        tecnico._convertir(conn, velas_diarias.serie(conn, us), "multiplicar")}
            try:
                byma = data912.cierres("cedears", b, timeout=20)
            except Exception as ex:
                print(f"  {b}: data912 no contestó ({ex})")
                continue
            comunes = sorted(d for d in en_pesos if d in byma)
            if len(comunes) < 30:
                filas.append({"b": b, "us": us, "sin": f"{len(comunes)} días en común"})
                continue
            ratio = float(tabla[b])
            ult = comunes[-1]
            medido_hoy = en_pesos[ult] / byma[ult]
            anio = [d for d in comunes if d > _restar_anio(ult)]
            err_a = [en_pesos[d] / ratio / byma[d] - 1 for d in anio]
            fila = {"b": b, "us": us, "ratio": ratio, "ult": ult, "byma": byma[ult],
                    "est_a": en_pesos[ult] / ratio, "err_a_hoy": en_pesos[ult] / ratio / byma[ult] - 1,
                    "medido_hoy": medido_hoy, "err_a_med": statistics.median(err_a),
                    "err_a_min": min(err_a), "err_a_max": max(err_a), "dias": len(anio)}
            for n_ in ATRASOS:
                if len(comunes) > n_:
                    d0 = comunes[-1 - n_]
                    coc = en_pesos[d0] / byma[d0]
                    fila[f"err_b_{n_}"] = en_pesos[ult] / coc / byma[ult] - 1
            filas.append(fila)

    buenas = [f for f in filas if "sin" not in f]
    print("## Cada CEDEAR (último día en común; error = estimado ÷ cierre de BYMA − 1)")
    print(f"  {'papel':6s} {'afuera':6s} {'ratio':>6s} {'medido':>7s} {'BYMA':>10s} {'A hoy':>7s} "
          f"{'A mediana año':>13s} {'A peor año':>17s} " + " ".join(f"{'B ' + str(n_) + 'r':>7s}" for n_ in ATRASOS))
    for f in sorted(buenas, key=lambda f: -abs(f["err_a_hoy"])):
        print(f"  {f['b']:6s} {f['us']:6s} {_f(f['ratio'], 2):>6s} {_f(f['medido_hoy'], 2):>7s} "
              f"{_f(f['byma'], 0):>10s} {_f(_pct(f['err_a_hoy'])):>6s}% {_f(_pct(f['err_a_med'])):>12s}% "
              f"{_f(_pct(f['err_a_min'])):>7s}% a {_f(_pct(f['err_a_max'])):>5s}% "
              + " ".join(f"{_f(_pct(f.get(f'err_b_{n_}'))):>6s}%" for n_ in ATRASOS)
              + f"  ({f['ult']})")
    for f in filas:
        if "sin" in f:
            print(f"  {f['b']:6s} {f['us']:6s} sin comparar: {f['sin']}")
    print()

    print("## Resumen")
    abs_a = sorted(abs(f["err_a_hoy"]) for f in buenas)
    lejos = [f for f in buenas if abs(f["err_a_hoy"]) > 0.15]
    print(f"  Papeles comparados: {len(buenas)}")
    print(f"  A (tabla), el último día: mediana {_f(_pct(statistics.median(abs_a)))} % de diferencia; "
          f"{sum(1 for x in abs_a if x <= 0.05)} a 5 % o menos, {sum(1 for x in abs_a if x <= 0.10)} a 10 % o menos, "
          f"{len(lejos)} a más de 15 %")
    print(f"  A con signo, mediana: {_f(_pct(statistics.median(f['err_a_hoy'] for f in buenas)))} % "
          f"(positivo = el estimado da más que BYMA: el MEP está arriba del dólar de los CEDEARs)")
    for f in lejos:
        print(f"    lejos: {f['b']} ratio tabla {_f(f['ratio'], 2)}, medido hoy {_f(f['medido_hoy'], 2)} "
              f"→ {_f(_pct(f['err_a_hoy']))} %")
    for n_ in ATRASOS:
        xs = sorted(abs(f[f"err_b_{n_}"]) for f in buenas if f"err_b_{n_}" in f)
        if xs:
            print(f"  B (cociente de hace {n_} ruedas), el último día: mediana {_f(_pct(statistics.median(xs)))} %; "
                  f"{sum(1 for x in xs if x <= 0.05)} de {len(xs)} a 5 % o menos; "
                  f"{sum(1 for x in xs if x > 0.15)} a más de 15 %")


def _restar_anio(iso):
    from datetime import date, timedelta
    return (date.fromisoformat(iso) - timedelta(days=365)).isoformat()


if __name__ == "__main__":
    main_()
