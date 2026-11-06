"""Qué cambia en la ficha de DISN, BRKB y NOKA con el traductor nuevo (H8, 05/11/2026).

Disney es DISN en BYMA y DIS en Nueva York; Berkshire BRKB y BRK-B; Nokia NOKA y
NOK. Hasta el arreglo, `velas_diarias.ticker_de_afuera` no los traducía: la noche
pedía «DISN», que Yahoo no tiene, y la ficha en dólares era el CEDEAR en pesos ÷
el MEP. Esto mide, con datos REALES, lo que ve la ficha antes y después:

  · las velas de Yahoo (5 años) de los seis papeles y del S&P 500, y el MEP de
    argentinadatos, en una base SQLite APARTE (DB_PATH: nunca la de desarrollo
    ni la de producción);
  · la MISMA base para «antes» y «después»: sólo cambia el traductor (el de
    antes queda escrito acá, `_viejo`);
  · la ficha (`tecnico.para_la_ficha`, la que arma GET /api/tecnico), la empresa
    de sus balances y dividendos (`tecnico.ticker_de_la_empresa`) y la lista de
    cambios de ratio (`cambios_ratio.recalcular` con los pares que arma la noche:
    `velas_diarias._yahoo_de`), con los splits de Yahoo y la historia de BYMA
    (data912) de verdad;
  · cuántos días el DISN.BA de Yahoo no es el precio de BYMA (data912).

Corre con (red: Yahoo, data912, argentinadatos):
  cd backend && DB_PATH=<carpeta nueva>/medir.db YF_TZ_CACHE_LOCATION=<carpeta nueva> \\
      python3 ../audit/_scripts/medir_cedear_afuera.py > ../audit/_scripts/medir_cedear_afuera.out
"""
import os
import sys
from datetime import date, timedelta

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
from cripto import yahoo_de_cripto  # noqa: E402

# (código con que Rendi guarda el CEDEAR, su acción de Nueva York)
PAPELES = [("DISN", "DIS"), ("BRKB", "BRK-B"), ("NOKA", "NOK")]
# Berkshire también se guarda como BRK-B (el formulario de compra lo canoniza:
# cedears_dolar._CANONICO): ése ya andaba y no tiene que cambiar.
FICHAS = ["DISN", "BRKB", "NOKA", "BRK-B"]
NUEVO = velas_diarias.ticker_de_afuera


def _viejo(a):
    """El traductor de antes del arreglo: sólo punto → guión."""
    a = (a or '').strip().upper()
    return a.replace('.', '-') if '.' in a and not a.endswith('.BA') else a


def _pct(a, b):
    return (b / a - 1) * 100 if a and b else None


def _f(x, n=2):
    return "—" if x is None else (f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", "."))


def preparar(conn):
    main._backfill_fx_rates_if_empty()
    main._backfill_mep_rates_if_missing()
    main._backfill_compras_if_missing()
    n = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM fx_rates_daily WHERE mep_venta IS NOT NULL").fetchone()
    print(f"MEP de argentinadatos: {n[0]} días, del {n[1]} al {n[2]}")
    tickers = [t for b, ny in PAPELES for t in (ny, f"{b}.BA", b)] + [velas_diarias.SP500]
    res = velas_diarias.actualizar(conn, tickers, podar=False)
    print("Lo bajado de Yahoo:", {k: res.get(k) for k in ("pedidos", "completas", "sin_datos", "filas")})
    for t in tickers:
        r = conn.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM velas_diarias WHERE symbol=?", (t,)).fetchone()
        print(f"  {t:9s} {r[0]:5d} velas  {r[1] or '':10s} → {r[2] or ''}")
    print()


def calidad_de_byma(conn):
    """¿Cuántos días el '.BA' de Yahoo no es el cierre de BYMA (data912)?"""
    from pricing import data912
    print("## El CEDEAR en pesos de Yahoo contra el cierre de BYMA (data912)")
    for b, _ in PAPELES:
        yahoo = {r["date"]: (r["close"], r["volume"]) for r in conn.execute(
            "SELECT date, close, volume FROM velas_diarias WHERE symbol=? ORDER BY date", (f"{b}.BA",))}
        byma = data912.cierres("cedears", b, timeout=20)
        comunes = sorted(d for d in yahoo if d in byma)
        lejos = [d for d in comunes if abs(yahoo[d][0] / byma[d] - 1) > 0.05]
        # Racha más larga de días con el MISMO cierre y volumen 0 (Yahoo «congelado»).
        racha, mejor, fin, prev = 0, 0, None, None
        for d in sorted(yahoo):
            c, v = yahoo[d]
            racha = racha + 1 if (prev is not None and c == prev and not v) else 0
            if racha > mejor:
                mejor, fin = racha, d
            prev = c
        ult = comunes[-1] if comunes else None
        print(f"  {b}.BA: {len(comunes)} días con los dos; {len(lejos)} a más de 5 % de BYMA "
              f"({_f(100 * len(lejos) / len(comunes) if comunes else None, 1)} %); "
              f"racha más larga clavado con volumen 0: {mejor} días (hasta el {fin})")
        if lejos:
            peor = max(lejos, key=lambda d: abs(yahoo[d][0] / byma[d] - 1))
            print(f"    peor día: {peor} Yahoo {_f(yahoo[peor][0], 0)} vs BYMA {_f(byma[peor], 0)}; "
                  f"últimos: {', '.join(lejos[-5:])}")
        if ult:
            print(f"    último día con los dos ({ult}): Yahoo {_f(yahoo[ult][0], 0)} vs BYMA {_f(byma[ult], 0)}")
    print()


def pares(traductor):
    """Los pares {papel: afuera} que arma la noche para cada CEDEAR (`_yahoo_de`),
    con este traductor, para el código con que Rendi lo guarda."""
    velas_diarias.ticker_de_afuera = traductor
    out = {}
    try:
        for b in [b for b, _ in PAPELES] + ["BRK-B"]:
            ys = velas_diarias._yahoo_de(b, "CEDEAR", True, yahoo_de_cripto)
            if len(ys) == 2:
                out[b] = (ys[1][:-3], ys[0])
    finally:
        velas_diarias.ticker_de_afuera = NUEVO
    return out


def rend_1_anio(velas):
    if not velas:
        return None
    ult = velas[-1]
    piso = (date.fromisoformat(ult["date"]) - timedelta(days=365)).isoformat()
    base = [v for v in velas if v["date"] <= piso]
    return _pct(base[-1]["close"], ult["close"]) if base else None


def ficha(conn, asset, moneda):
    f = tecnico.para_la_ficha(conn, asset, moneda)
    if not f.get("disponible"):
        return {"disponible": False}
    s = tecnico.serie(conn, asset, moneda)
    lec = f["lectura"]
    return {"ticker": f["ticker"], "convertida": f["convertida"], "hasta": f["puntos"][-1]["d"],
            "ultimo": f["puntos"][-1]["c"], "rend_1a": rend_1_anio(s["velas"]),
            "tendencia": lec.get("tendencia"), "dist_media200": lec.get("dist_media200"),
            "rsi": lec.get("rsi"), "dia_normal": lec.get("mov_dia_anio"),
            "dist_maximo_12m": lec.get("dist_maximo_12m")}


def una_pasada(conn, nombre, traductor, pares_cambios):
    """La lista de cambios de ratio con estos pares, y las fichas con este traductor."""
    print(f"## {nombre}")
    print("  Pares de la noche (papel → acción de afuera):", pares_cambios)
    velas_diarias.ticker_de_afuera = traductor
    try:
        papeles = sorted({p for p in pares_cambios})
        res = cambios_ratio.recalcular(conn, papeles, pares=pares_cambios)
        print("  Cambios de ratio:", {k: v for k, v in res.items() if k != "sin_yahoo"},
              "sin respuesta de Yahoo:", res.get("sin_yahoo"))
        out = {"cambios": {}, "fichas": {}, "empresa": {}}
        for p in papeles:
            filas = cambios_ratio.todos(conn, p)
            out["cambios"][p] = {
                "filas": [(r["fecha"], r["tipo"], r["estado"], r["factor"], r["factor_medido"],
                           r["en_la_serie"], r["origen"]) for r in filas],
                "ajustar": cambios_ratio.para_lotes(conn, p),
                "grafico": cambios_ratio.para_el_grafico(conn, p)}
        for a in FICHAS:
            for m in ("usd", "ars"):
                out["fichas"][(a, m)] = ficha(conn, a, m)
            out["empresa"][a] = tecnico.ticker_de_la_empresa(conn, a)
        return out
    finally:
        velas_diarias.ticker_de_afuera = NUEVO


def mostrar(antes, despues):
    print("## La ficha, antes → después")
    for a in FICHAS:
        for m in ("usd", "ars"):
            x, y = antes["fichas"][(a, m)], despues["fichas"][(a, m)]
            mon = "dólares" if m == "usd" else "pesos"
            igual = "  (igual)" if x == y else ""
            print(f"  {a} en {mon}{igual}")
            for nom, v in (("antes", x), ("después", y)):
                if not v.get("disponible", True):
                    print(f"    {nom:8s}: sin gráfico")
                    continue
                print(f"    {nom:8s}: serie {v['ticker']}{' ÷ MEP' if v['convertida'] and m == 'usd' else ''}"
                      f"{' × MEP' if v['convertida'] and m == 'ars' else ''}"
                      f" · último {_f(v['ultimo'])} ({v['hasta']}) · 1 año {_f(v['rend_1a'], 1)} %"
                      f" · tendencia {v['tendencia']} · vs media 200 {_f(v['dist_media200'], 1)} %"
                      f" · RSI {_f(v['rsi'], 0)} · día normal ±{_f(v['dia_normal'], 1)} %"
                      f" · debajo del máximo del año {_f(v['dist_maximo_12m'], 1)} %")
        print(f"    balances y dividendos de: {antes['empresa'][a]} → {despues['empresa'][a]}")
    print()
    print("## Cambios de ratio (lo que usa el gráfico en pesos y el aviso «Ajustar»)")
    for p in sorted(set(antes["cambios"]) | set(despues["cambios"])):
        x, y = antes["cambios"].get(p), despues["cambios"].get(p)
        print(f"  {p}{'  (igual)' if x == y else ''}")
        for nom, v in (("antes", x), ("después", y)):
            if v is None:
                continue
            print(f"    {nom:8s}: «Ajustar» ofrece {v['ajustar'] or 'nada'}; el gráfico empalma "
                  f"{v['grafico']['escalones'] or 'nada'}, saca {v['grafico']['rotos'] or 'nada'}, "
                  f"esconde desde {v['grafico']['pendientes'] or 'nada'}")
            for fila in v["filas"]:
                print(f"              {fila}")
    print()


def simular_salida_de_yahoo(conn, n=7):
    """¿Qué dibuja la ficha EN PESOS de Disney las noches en que el DISN.BA de
    Yahoo deja de estar clavado? (El 05/11 Yahoo ya mostraba 16.370 con volumen.)
    Se agregan `n` ruedas con el último cierre de BYMA (data912), Disney quieto en
    Nueva York, y se recalcula la lista de cambios de ratio cada noche con los
    pares de antes y de después. Escribe en esta base de prueba: va al final."""
    from pricing import data912
    byma = data912.cierres("cedears", "DISN", timeout=20)
    ult = conn.execute("SELECT MAX(date) FROM velas_diarias WHERE symbol='DISN.BA'").fetchone()[0]
    ba = byma.get(ult) or max(byma.items())[1]
    dis = conn.execute("SELECT close FROM velas_diarias WHERE symbol='DIS' ORDER BY date DESC LIMIT 1").fetchone()[0]
    mep = conn.execute("SELECT mep_venta FROM fx_rates_daily WHERE mep_venta IS NOT NULL "
                       "ORDER BY date DESC LIMIT 1").fetchone()[0]
    hace1 = (date.fromisoformat(ult) - timedelta(days=365)).isoformat()
    ref = max(d for d in byma if d <= hace1)
    print(f"## Si el DISN.BA de Yahoo deja de estar clavado (simulado: {n} ruedas a ${_f(ba, 0)} de BYMA)")
    print(f"  De referencia, BYMA (data912): 1 año en pesos {_f(_pct(byma[ref], byma[max(d for d in byma if d <= ult)]), 1)} %;"
          f" 30/06/2023 ${_f(byma.get('2023-06-30'), 0)}")
    d = date.fromisoformat(ult) + timedelta(days=1)
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        f = d.isoformat()
        for sym, c, v in (("DISN.BA", ba, 20000.0), ("DIS", dis, 1e7)):
            conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                         "VALUES (?,?,?,?,?,?,?)", (sym, f, c, c, c, c, v))
        conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?) "
                     "ON CONFLICT(date) DO NOTHING", (f, mep * 1.02, mep))
        conn.commit()
        print(f"  Después de guardar la rueda del {f} ({i + 1}.ª fuera de 10.416):")
        for nombre, traductor, par in (("antes", _viejo, {"DISN": "DISN"}), ("después", NUEVO, {"DISN": "DIS"})):
            velas_diarias.ticker_de_afuera = traductor
            try:
                cambios_ratio.recalcular(conn, ["DISN"], pares=par)
                g = cambios_ratio.para_el_grafico(conn, "DISN")
                s = tecnico.serie(conn, "DISN", "ars")
                v = s["velas"]
                junio = [x for x in v if x["date"] <= "2023-06-30"]
                print(f"    {nombre:8s}: serie {s['ticker']}{' × MEP' if s['convertida'] else ''} · último dibujado "
                      f"{v[-1]['date']} ${_f(v[-1]['close'], 0)} · 1 año {_f(rend_1_anio(v), 1)} % · 30/06/2023 "
                      f"dibujado ${_f(junio[-1]['close'] if junio else None, 0)} · empalma "
                      f"{[(x, round(y, 2)) for x, y in g['escalones']] or 'nada'} · esconde desde "
                      f"{g['pendientes'] or 'nada'} · «Ajustar» {cambios_ratio.para_lotes(conn, 'DISN') or 'nada'}")
            finally:
                velas_diarias.ticker_de_afuera = NUEVO
        d += timedelta(days=1)
    print()


def main_():
    conn = main.get_db()
    try:
        print(f"Medido el {date.today().isoformat()} sobre {os.path.basename(DB)} (aparte)\n")
        preparar(conn)
        calidad_de_byma(conn)
        viejos, nuevos = pares(_viejo), pares(NUEVO)
        # Antes, el par de Berkshire en la noche dependía de cómo estaba guardado:
        # BRK-B daba BRK-B (andaba), BRKB daba «BRKB» (no). Se mide el que no andaba.
        antes = una_pasada(conn, "ANTES (traductor viejo)", _viejo,
                           {p: af for b, (p, af) in viejos.items() if b != "BRK-B"})
        despues = una_pasada(conn, "DESPUÉS (traductor nuevo)", NUEVO,
                             {p: af for b, (p, af) in nuevos.items() if b != "BRK-B"})
        print()
        mostrar(antes, despues)
        simular_salida_de_yahoo(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main_()
