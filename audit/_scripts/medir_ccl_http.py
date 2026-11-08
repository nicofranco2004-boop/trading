"""El CEDEAR estimado en pesos por HTTP, como la pantalla, con datos REALES: el
código de antes (MEP de cada día) contra el de ahora (contado con liqui de cada
día), 06/11/2026.

Sobre una COPIA de medir_original.db (la base de la auditoría del 06/11: Yahoo
5 años de las acciones de afuera + el MEP de argentinadatos; ningún '.BA'), con
el contado con liqui de cada día guardado igual en las dos (argentinadatos, el
medio con `fx.punta_media`, en `bond_indices_daily` 'CCL': el código de antes no
lo mira). Pide:
  · la ficha en pesos (`/api/tecnico/X?moneda=ars`) de CEDEARs a pedido y BAC;
  · la de MELI y KO con su serie de BYMA (data912) guardada y cortada hace 20
    ruedas (alguien la tuvo), y la misma después de podarla (la noche la borra);
  · la vela de hoy (`/hoy`) y las de 1 hora (`/horas`) de AAPL y BAC;
  · BAC en la Cartera: `/api/prices` y `/api/prices/prev-close`.
Y compara cada último cierre con el de BYMA ese día (data912; BAC: «BA.C», su
CEDEAR en pesos).

Uso (una corrida por versión del código, cada una con su copia de la base):
  cp medir_original.db a.db && DB_PATH=a.db python3 medir_ccl_http.py <backend de antes> ad_ccl.json > antes.json
  cp medir_original.db b.db && DB_PATH=b.db python3 medir_ccl_http.py <backend de ahora> ad_ccl.json > ahora.json
  python3 medir_ccl_http.py --comparar antes.json ahora.json
(`ad_ccl.json`: https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui)
"""
import json
import os
import sys

FICHAS = ["AAPL", "MELI", "NVDA", "KO", "GOOGL", "MSFT", "DISN", "BRKB", "SPY", "BAC", "NET", "SCHD"]
VIEJAS = ["MELI", "KO"]          # con su serie de BYMA guardada y cortada hace 20 ruedas
CORTE = 20
EN_LA_BOLSA = {"BAC": "BA.C"}    # el código de su CEDEAR en pesos en BYMA


def correr(backend, ccl_json):
    db = os.environ.get("DB_PATH") or ""
    if not db or os.path.abspath(db).endswith(os.path.join("backend", "trading.db")):
        sys.exit("DB_PATH tiene que apuntar a una COPIA aparte de la base de la medición")
    sys.path.insert(0, backend)
    os.chdir(backend)
    import logging
    logging.disable(logging.WARNING)
    from unittest import mock
    import main
    import fx as _fx
    from fastapi.testclient import TestClient
    from pricing import data912

    filas_ccl = [(it["fecha"], it.get("compra"), it.get("venta")) for it in json.load(open(ccl_json))]
    if hasattr(main, "_actualizar_ccl"):
        # El código que lo guarda: por su escritor, como en producción (la fecha de
        # argentinadatos corregida y el cierre de hoy de dolarapi, de verdad).
        with mock.patch("main._bajar_ccl", lambda: filas_ccl):
            main._actualizar_ccl()
    with main.db_abierta() as conn:
        for f, c, v in filas_ccl if not hasattr(main, "_actualizar_ccl") else []:
            v = _fx.punta_media(c, v)
            if v:
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CCL', ?, ?, 'argentinadatos', 'medicion') "
                             "ON CONFLICT(index_name, date) DO NOTHING", (f, v))
        cur = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                           "VALUES ('medir-ccl@rendi.test', 'x', 1, 1, 'pro')")
        uid = cur.lastrowid
        for b in VIEJAS:
            byma = data912.cierres("cedears", b, timeout=20)
            for d in sorted(byma)[:-CORTE]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                             "VALUES (?, ?, ?, ?, ?, ?, 0)", (f"{b}.BA", d, byma[d], byma[d], byma[d], byma[d]))
        conn.commit()
    h = {"Authorization": f"Bearer {main.create_token(uid)}"}
    bolsa = {}

    def cierre_de_byma(base, fecha):
        codigo = EN_LA_BOLSA.get(base, base)
        if codigo not in bolsa:
            try:
                bolsa[codigo] = data912.cierres("cedears", codigo, timeout=20)
            except Exception:
                bolsa[codigo] = {}
        return bolsa[codigo].get(fecha)

    def ficha(c, a, m="ars"):
        f = c.get(f"/api/tecnico/{a}?moneda={m}", headers=h).json()
        if not f.get("disponible"):
            return {"disponible": False, "motivo": f.get("motivo")}
        lec = f.get("lectura") or {}
        pts = f["puntos"]
        hace_un_anio = next((p for p in reversed(pts) if p["d"] <= f"{int(pts[-1]['d'][:4]) - 1}{pts[-1]['d'][4:]}"), None)
        return {"disponible": True, "ticker": f.get("ticker"), "convertida": f.get("convertida"),
                "escala": f.get("escala"), "fecha": pts[-1]["d"], "ultimo": pts[-1]["c"],
                "hace_un_anio": hace_un_anio and [hace_un_anio["d"], hace_un_anio["c"]],
                "tendencia": lec.get("tendencia"), "rsi": lec.get("rsi"), "rend_12m": lec.get("rend_12m"),
                "puntos": {p["d"]: p["c"] for p in pts}}

    out = {"fichas": {}, "podadas": {}, "hoy": {}, "horas": {}, "bac": {}}
    with mock.patch("main._check_rate_limit"):
        c = TestClient(main.app)
        for a in FICHAS + [f"{b}.BA" for b in VIEJAS]:
            r = {"ars": ficha(c, a), "usd": ficha(c, a, "usd")}
            base = a[:-3] if a.endswith(".BA") else a
            r["byma_ese_dia"] = cierre_de_byma(base, r["ars"].get("fecha"))
            for v in ("ars", "usd"):
                r[v].pop("puntos", None) if v == "usd" else None
            if r["ars"].get("hace_un_anio"):
                r["byma_hace_un_anio"] = cierre_de_byma(base, r["ars"]["hace_un_anio"][0])
            out["fichas"][a] = r
        # La noche borra la serie vieja: la misma ficha, sin ella.
        with main.db_abierta() as conn:
            for b in VIEJAS:
                conn.execute("DELETE FROM velas_diarias WHERE symbol = ?", (f"{b}.BA",))
            conn.commit()
        for b in VIEJAS:
            out["podadas"][f"{b}.BA"] = ficha(c, f"{b}.BA")
        for a in ("AAPL", "BAC"):
            hoy = c.get(f"/api/tecnico/{a}/hoy?moneda=ars", headers=h).json()
            out["hoy"][a] = [{k: v[k] for k in ("d", "c", "hoy")} for v in hoy.get("velas") or []]
            horas = c.get(f"/api/tecnico/{a}/horas?cada=1h&moneda=ars", headers=h).json()
            out["horas"][a] = {"convertida": horas.get("convertida"), "escala": horas.get("escala"),
                               "ultimas": [(p["d"], p["c"]) for p in (horas.get("puntos") or [])[-3:]]}
        # Como en producción, con el dólar de ahora en el caché (lo llena /api/dolar,
        # que la pantalla pide siempre): sin él, la Cartera cae al blue de la
        # configuración de la cuenta, en los dos códigos.
        main._get_dolar_data()
        out["bac"]["precio"] = c.get("/api/prices?symbols=BAC.BA", headers=h).json().get("BAC.BA")
        out["bac"]["cierre_anterior"] = c.get("/api/prices/prev-close?symbols=BAC.BA", headers=h).json().get("BAC.BA")
        mini = c.get("/api/prices/history?symbol=BAC.BA&period=1y", headers=h).json()
        out["bac"]["mini_primero_y_ultimo"] = [(p["date"], p["close"]) for p in (mini.get("points") or [])[::51]]
        out["bac"]["ccl_ahora"] = main._current_ccl()
    for r in out["fichas"].values():
        r["ars"].pop("puntos", None)
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


def _f(x, n=0):
    return "—" if x is None else f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(a, b):
    return (_f((a / b - 1) * 100, 1) + " %") if (a and b) else "—"


def comparar(antes_p, ahora_p):
    antes, ahora = json.load(open(antes_p)), json.load(open(ahora_p))
    print("## La ficha en pesos: el último cierre, el código de antes (MEP) → el de ahora (contado con liqui)")
    print("   contra el cierre de BYMA ese día (data912; BAC: «BA.C», su CEDEAR en pesos)")
    print(f"  {'ficha':8s} {'antes':>10s} {'ahora':>10s} {'BYMA':>10s} {'antes/BYMA':>11s} {'ahora/BYMA':>11s}"
          f"  {'dólar':>6s} {'escala':>7s}  {'hace un año: antes/BYMA → ahora/BYMA':38s} tendencia")
    for a, y in ahora["fichas"].items():
        x = antes["fichas"][a]
        xa, ya = x["ars"], y["ars"]
        if not ya["disponible"]:
            print(f"  {a:8s} {'—' if not xa['disponible'] else _f(xa['ultimo']):>10s} {'sin gráfico':>10s}"
                  f"   ({ya.get('motivo')})")
            continue
        b = y.get("byma_ese_dia")
        b1 = y.get("byma_hace_un_anio")
        anio = (f"{_pct(xa['hace_un_anio'][1], b1)} → {_pct(ya['hace_un_anio'][1], b1)}"
                if (b1 and xa.get("hace_un_anio") and ya.get("hace_un_anio")) else "—")
        print(f"  {a:8s} {_f(xa.get('ultimo')):>10s} {_f(ya['ultimo']):>10s} {_f(b):>10s} {_pct(xa.get('ultimo'), b):>11s}"
              f" {_pct(ya['ultimo'], b):>11s}  {str(ya.get('convertida')):>6s} {_f(ya.get('escala'), 2):>7s}  {anio:38s}"
              f" {xa.get('tendencia')} → {ya.get('tendencia')}")
    print()
    print("## El día que la noche borra la serie vieja: cuánto salta el último cierre")
    for a, y in ahora["podadas"].items():
        x = antes["podadas"][a]
        vx, vy = antes["fichas"][a]["ars"].get("ultimo"), ahora["fichas"][a]["ars"].get("ultimo")
        print(f"  {a:8s} antes: {_f(vx)} → {_f(x.get('ultimo'))} ({_pct(x.get('ultimo'), vx)})   "
              f"ahora: {_f(vy)} → {_f(y.get('ultimo'))} ({_pct(y.get('ultimo'), vy)})")
    print()
    print("## La vela de hoy y las de 1 hora (en pesos)")
    for a in ahora["hoy"]:
        print(f"  {a:5s} hoy antes {antes['hoy'][a]}  ahora {ahora['hoy'][a]}")
        print(f"        1h  antes {antes['horas'][a]}  ahora {ahora['horas'][a]}")
    print()
    print("## BAC en la Cartera (el precio y el cierre anterior; el gráfico, arriba)")
    for k in ("precio", "cierre_anterior", "ccl_ahora", "mini_primero_y_ultimo"):
        print(f"  {k:22s} antes {antes['bac'][k]}  ahora {ahora['bac'][k]}")
    print()
    print("## En dólares, ¿algo cambió? (no tendría que cambiar nada)")
    cambios = [a for a in ahora["fichas"] if antes["fichas"][a]["usd"] != ahora["fichas"][a]["usd"]]
    print("  ", "nada" if not cambios else cambios)


if __name__ == "__main__":
    if sys.argv[1] == "--comparar":
        comparar(sys.argv[2], sys.argv[3])
    else:
        correr(sys.argv[1], sys.argv[2])
