"""La ficha en pesos de CEDEARs sin su serie en pesos, pedida por HTTP como la
pantalla, con datos REALES: el código de antes contra el de ahora (06/11/2026).

Corre `GET /api/tecnico/{X}?moneda=ars` (y en dólares, y la vela de hoy) sobre
una COPIA de la base de medir_cedear_estimado.py (Yahoo 5 años de las acciones
de afuera + el MEP de argentinadatos; sin ningún '.BA' guardado: es el caso de
la ficha a pedido), con el backend que se le pase. Agrega además un caso de
serie vieja: la de BYMA (data912) de MELI y KO cortada hace 20 ruedas, guardada
como si alguien la hubiera tenido.

Uso (una corrida por versión del código, cada una con su copia de la base):
  cp medir.db a.db && DB_PATH=a.db python3 medir_cedear_estimado_http.py <backend de antes> > antes.json
  cp medir.db b.db && DB_PATH=b.db python3 medir_cedear_estimado_http.py <backend de ahora> > ahora.json
  python3 medir_cedear_estimado_http.py --comparar antes.json ahora.json
"""
import json
import os
import sys

FICHAS = ["AAPL", "MELI", "NVDA", "KO", "GOOGL", "DISN", "BRKB", "BAC", "AZN", "SPY", "NET", "SCHD"]
VIEJAS = ["MELI", "KO"]          # con su serie de BYMA guardada y cortada hace 20 ruedas
CORTE = 20


def correr(backend):
    db = os.environ.get("DB_PATH") or ""
    if not db or os.path.abspath(db).endswith(os.path.join("backend", "trading.db")):
        sys.exit("DB_PATH tiene que apuntar a una COPIA aparte de la base de la medición")
    sys.path.insert(0, backend)
    os.chdir(backend)
    import logging
    logging.disable(logging.WARNING)
    from unittest import mock
    import main
    from fastapi.testclient import TestClient
    from pricing import data912

    with main.db_abierta() as conn:
        cur = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                           "VALUES ('medir-escala@rendi.test', 'x', 1, 1, 'pro')")
        uid = cur.lastrowid
        # La serie vieja: la de BYMA hasta hace CORTE ruedas, como la guardaba la noche.
        for b in VIEJAS:
            byma = data912.cierres("cedears", b, timeout=20)
            dias = sorted(byma)[:-CORTE]
            for d in dias:
                conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                             "VALUES (?, ?, ?, ?, ?, ?, 0)", (f"{b}.BA", d, byma[d], byma[d], byma[d], byma[d]))
        conn.commit()
    h = {"Authorization": f"Bearer {main.create_token(uid)}"}
    out = {}
    with mock.patch("main._check_rate_limit"):
        c = TestClient(main.app)
        for a in FICHAS + [f"{b}.BA" for b in VIEJAS]:
            r = {}
            for m in ("usd", "ars"):
                f = c.get(f"/api/tecnico/{a}?moneda={m}", headers=h).json()
                if not f.get("disponible"):
                    r[m] = {"disponible": False}
                    continue
                lec = f.get("lectura") or {}
                r[m] = {"disponible": True, "ticker": f.get("ticker"), "convertida": f.get("convertida"),
                        "escala": f.get("escala"), "fecha": f["puntos"][-1]["d"], "ultimo": f["puntos"][-1]["c"],
                        "primero": f["puntos"][0]["c"], "tendencia": lec.get("tendencia"),
                        "dist_media200": lec.get("dist_media200"), "rsi": lec.get("rsi"),
                        "rend_12m": lec.get("rend_12m"), "dist_maximo_12m": lec.get("dist_maximo_12m")}
            base = a[:-3] if a.endswith(".BA") else a
            # El cierre de BYMA del MISMO día que el último punto (no el precio de hoy).
            try:
                cierres = data912.cierres("cedears", base, timeout=20)
            except Exception:
                cierres = {}
            r["byma_ese_dia"] = cierres.get((r["ars"].get("fecha") or r["usd"].get("fecha") or ""))
            out[a] = r
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


def _f(x, n=0):
    return "—" if x is None else f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def comparar(antes_p, ahora_p):
    antes, ahora = json.load(open(antes_p)), json.load(open(ahora_p))
    print("## La ficha en pesos, el código de antes → el de ahora (último cierre guardado; BYMA: su cierre ese día, data912)")
    print(f"  {'ficha':8s} {'antes':>12s} {'ahora':>10s} {'escala':>7s} {'BYMA':>9s} {'ahora/BYMA':>10s}  lectura igual")
    for a in ahora:
        x, y = antes[a]["ars"], ahora[a]["ars"]
        byma = ahora[a].get("byma_ese_dia")
        if not y["disponible"]:
            print(f"  {a:8s} {_f(x.get('ultimo')) if x['disponible'] else 'sin gráfico':>12s} {'sin gráfico':>10s}")
            continue
        igual = all(x.get(k) is not None and abs(x[k] - y[k]) < 1e-6 for k in
                    ("dist_media200", "rsi", "rend_12m", "dist_maximo_12m")) and x["tendencia"] == y["tendencia"]
        rel = (y["ultimo"] / byma - 1) * 100 if (byma and y.get("escala")) else None
        print(f"  {a:8s} {_f(x['ultimo']):>12s} {_f(y['ultimo']):>10s} {_f(y.get('escala'), 2):>7s} "
              f"{_f(byma):>9s} {(_f(rel, 1) + ' %') if rel is not None else '—':>10s}  "
              f"{'sí' if igual else 'NO: ' + str({k: (x.get(k), y.get(k)) for k in ('tendencia', 'rsi')})}")
    print()
    print("## En dólares, ¿algo cambió? (no tendría que cambiar nada)")
    cambios = [a for a in ahora if antes[a]["usd"] != ahora[a]["usd"]]
    print("  ", "nada" if not cambios else cambios)


if __name__ == "__main__":
    if sys.argv[1] == "--comparar":
        comparar(sys.argv[2], sys.argv[3])
    else:
        correr(sys.argv[1])
