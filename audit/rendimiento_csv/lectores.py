"""Lo que publica CADA lector para el mismo usuario, en los dos modos.

  python3 lectores.py <salida.json> broker:escenario [broker:escenario ...]
"""
import json, sys
from datetime import date
import arnes, correr_escenarios as ce
from mercado import Mercado

PCT_KEYS = ("twr", "pct", "rend", "acum", "cagr", "return", "rendimiento", "vs_", "ganancia", "anual", "ytd")


def numeros(obj, pref="", out=None, prof=0):
    """Aplana los campos numéricos que suenan a rendimiento (+ sus ventanas)."""
    out = {} if out is None else out
    if prof > 6:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            kk = f"{pref}.{k}" if pref else str(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and any(p in str(k).lower() for p in PCT_KEYS):
                out[kk] = v
            elif isinstance(v, str) and any(p in str(k).lower() for p in ("desde", "hasta", "base", "modo", "motivo", "basis", "ventana")):
                out[kk] = v
            elif isinstance(v, (dict, list)):
                numeros(v, kk, out, prof + 1)
    elif isinstance(obj, list) and obj and len(obj) <= 3:
        for i, v in enumerate(obj):
            numeros(v, f"{pref}[{i}]", out, prof + 1)
    return out


def leer(a, modo):
    conn = arnes.main.get_db()
    with conn:
        conn.execute("UPDATE users SET modo_rendimiento=? WHERE id=?", (modo, a.uid))
    conn.close()
    r = {}
    for nombre, url in (("metricas", f"/api/insights/performance?bench=sp500&modo={modo}"),
                        ("metricas_sin_modo", "/api/insights/performance?bench=sp500"),
                        ("metas", "/api/goals/cagr"),
                        ("reportes_2026", "/api/reports/period/year/2026"),
                        ("reportes_2025", "/api/reports/period/year/2025"),
                        ("wrapped_2025", "/api/wrapped/2025")):
        st, js = a.get(url)
        r[nombre] = {"status": st, "n": numeros(js) if st == 200 else str(js)[:200]}
        if nombre.startswith(("wrapped", "reportes")) and st == 200:
            r[nombre]["crudo"] = {k: js.get(k) for k in ("summary", "metrics", "basis", "base", "modo") if k in js}
    import importlib
    conn = arnes.main.get_db()
    try:
        for b in ("dashboard", "insights", "reports", "insights_evolution", "dashboard_evolution"):
            try:
                mod = importlib.import_module(f"ai.builders.{b}")
                r[f"ia_{b}"] = {"n": numeros(mod.build(conn, a.uid))}
            except Exception as ex:
                r[f"ia_{b}"] = {"error": repr(ex)[:200]}
        r["motor_publicable"] = arnes.twr.rendimiento_publicable(conn, a.uid)
    finally:
        conn.close()
    return r


def main():
    salida, casos = sys.argv[1], sys.argv[2:]
    m = Mercado(); a = arnes.Arnes(m); res = {}
    for caso in casos:
        br, esc = caso.split(":")
        h, omitir, ajustar, hasta = ce.escenarios(m)[esc]; h.simular()
        gen, broker, fmt, nombre = ce.MOV[br]
        a.usuario(f"lect_{br}_{esc}@rendi.test")
        a.subir([(nombre, gen(h, omitir=omitir, hasta=hasta))], broker=broker, fmt=fmt,
                extra={"route_by_currency": "1"} if br == "generico" else None)
        if br in ce.FOTOS:
            fg, ff, fn = ce.FOTOS[br]; a.subir_foto(fn, fg(h, ce.FOTO, ajustar), broker, ff)
        a.cron(date(2026, 8, 4), date.today()); a.reconstruir()
        res[caso] = {m_: leer(a, m_) for m_ in ("certero", "estimado")}
        res[caso]["verdad"] = {"twr_total": h.twr_verdad("2024-01-31", date.today().isoformat()),
                               "twr_2025": h.twr_verdad("2024-12-31", "2025-12-31"),
                               "twr_2026_ytd": h.twr_verdad("2025-12-31", date.today().isoformat()),
                               "contable": h.contable_verdad()}
        json.dump(res, open(salida, "w"), ensure_ascii=False, default=str, indent=1)
        print("listo", caso, flush=True)


if __name__ == "__main__":
    main()
