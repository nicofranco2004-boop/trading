"""BAC por HTTP, como la pantalla, con datos REALES: el código de antes (el
estimado: Nueva York × contado con liqui ÷ 4) contra el de ahora (su CEDEAR en
pesos de la Bolsa, «BA.C»), 06/11/2026.

Sobre una COPIA de medir_original.db (la base de la auditoría del 06/11: Yahoo 5
años de las acciones de afuera, BAC incluido, y el MEP), con el contado con liqui
de cada día guardado igual en las dos (argentinadatos, el medio con
`fx.punta_media`). Una cuenta con 10 CEDEARs de BAC en un broker en pesos; corre
la noche de verdad (`velas_diarias.correr`: Yahoo y data912 de verdad) y pide:
  · la Cartera: `/api/prices`, `/api/prices/prev-close`, la variación del día;
  · la foto de la noche: `snapshots_job.fetch_prices_for_symbols`;
  · el mini-gráfico: `/api/prices/history` (1 mes y 1 año);
  · la ficha en pesos (`/api/tecnico/BAC?moneda=ars`), la vela de hoy (`/hoy`) y
    las de 1 hora (`/horas`); en dólares, que no tiene que cambiar;
  · la liquidez de la ficha (`/api/liquidez/BAC`).
Y lo compara con lo que dice la Bolsa (data912: el feed en vivo y la historia de
BA.C).

Uso (una corrida por versión del código, cada una con su copia de la base):
  cp medir_original.db a.db && DB_PATH=a.db python3 medir_ba_c_http.py <backend de antes> ad_ccl.json > antes.json
  cp medir_original.db b.db && DB_PATH=b.db python3 medir_ba_c_http.py <backend de ahora> ad_ccl.json > ahora.json
  python3 medir_ba_c_http.py --comparar antes.json ahora.json
(`ad_ccl.json`: https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui)
"""
import json
import os
import sys


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
    import snapshots_job
    import velas_diarias
    from fastapi.testclient import TestClient
    from pricing import data912

    with main.db_abierta() as conn:
        for it in json.load(open(ccl_json)):
            v = _fx.punta_media(it.get("compra"), it.get("venta"))
            if v:
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CCL', ?, ?, 'argentinadatos', 'medicion') "
                             "ON CONFLICT(index_name, date) DO NOTHING", (it["fecha"], v))
        cur = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                           "VALUES ('medir-ba-c@rendi.test', 'x', 1, 1, 'pro')")
        uid = cur.lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, 'IOL', 'ARS')", (uid,))
        conn.execute("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, quantity, "
                     "commissions, price_override, currency) VALUES (?, 'IOL', 'BAC', 'CEDEAR', 0, 200000, 10, "
                     "0, NULL, 'ARS')", (uid,))
        conn.commit()
        # La noche de verdad: qué se sigue y de dónde se baja (Yahoo y data912).
        noche = velas_diarias.correr(conn)
    h = {"Authorization": f"Bearer {main.create_token(uid)}"}
    out = {"noche": {k: noche.get(k) for k in ("pedidos", "bajados", "sin_datos")}}
    with main.db_abierta() as conn:
        out["noche"]["guardado"] = {t: conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM velas_diarias WHERE symbol=?", (t,)).fetchone()[:]
            for t in ("BAC", "BAC.BA")}

    with mock.patch("main._check_rate_limit"):
        c = TestClient(main.app)
        main._get_dolar_data()           # el dólar de ahora en el caché, como la pantalla
        bac = out["cartera"] = {}
        bac["precio"] = c.get("/api/prices?symbols=BAC.BA", headers=h).json().get("BAC.BA")
        bac["cierre_anterior"] = c.get("/api/prices/prev-close?symbols=BAC.BA", headers=h).json().get("BAC.BA")
        v = main._variacion_del_dia(["BAC.BA"], uid).get("BAC.BA") or {}
        bac["variacion"] = {k: v.get(k) for k in ("price", "prev_close", "change_pct", "mercado", "as_of")}
        bac["foto_de_la_noche"] = snapshots_job.fetch_prices_for_symbols(["BAC.BA"], main.CRYPTO_YF).get("BAC.BA")
        bac["ccl_ahora"] = main._current_ccl()
        for p in ("1m", "1y"):
            mini = c.get(f"/api/prices/history?symbol=BAC.BA&period={p}", headers=h).json().get("points") or []
            out[f"mini_{p}"] = {pt["date"]: pt["close"] for pt in mini}
        f = c.get("/api/tecnico/BAC?moneda=ars", headers=h).json()
        out["ficha_ars"] = {k: f.get(k) for k in ("disponible", "ticker", "convertida", "escala", "motivo")}
        out["ficha_ars"]["puntos"] = {p["d"]: p["c"] for p in f.get("puntos") or []}
        out["ficha_ars"]["tendencia"] = (f.get("lectura") or {}).get("tendencia")
        u = c.get("/api/tecnico/BAC?moneda=usd", headers=h).json()
        out["ficha_usd"] = {"ticker": u.get("ticker"), "ultimo": (u.get("puntos") or [{}])[-1].get("c"),
                            "n": len(u.get("puntos") or [])}
        hoy = c.get("/api/tecnico/BAC/hoy?moneda=ars", headers=h).json()
        out["hoy"] = [{k: x[k] for k in ("d", "o", "c", "hoy")} for x in hoy.get("velas") or []]
        horas = c.get("/api/tecnico/BAC/horas?cada=1h&moneda=ars", headers=h).json()
        out["horas"] = {"ticker": horas.get("ticker"), "convertida": horas.get("convertida"),
                        "escala": horas.get("escala"),
                        "ultimas": [(p["d"], p["c"]) for p in (horas.get("puntos") or [])[-2:]]}
        out["liquidez"] = c.get("/api/liquidez/BAC", headers=h).json()
    # La Bolsa: lo que dice data912 de BA.C (el feed en vivo y la historia).
    vivo = (main._fetch_data912_equities() or {}).get("BA.C") or {}
    out["bolsa"] = {"vivo": {k: vivo.get(k) for k in ("c", "pct", "v")},
                    "historia": data912.cierres("cedears", "BA.C", timeout=20)}
    json.dump(out, sys.stdout, indent=1, ensure_ascii=False)


def _f(x, n=0):
    return "—" if x is None else f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(a, b):
    return (f"{(a / b - 1) * 100:+.2f} %".replace(".", ",")) if (a and b) else "—"


def comparar(antes_p, ahora_p):
    antes, ahora = json.load(open(antes_p)), json.load(open(ahora_p))
    byma = ahora["bolsa"]["historia"]
    vivo = ahora["bolsa"]["vivo"]
    print(f"La Bolsa (data912): BA.C en vivo {_f(vivo['c'])} ({vivo['pct']} %, {vivo['v']} CEDEARs operados)")
    print()
    print("## La noche: qué guardó de BAC (velas, primera y última fecha)")
    for k in ("BAC", "BAC.BA"):
        print(f"  {k:7s} antes {antes['noche']['guardado'][k]}   ahora {ahora['noche']['guardado'][k]}")
    print()
    print("## La Cartera (contra BA.C en vivo y su cierre anterior)")
    ca, cb = antes["cartera"], ahora["cartera"]
    prev_byma = vivo["c"] / (1 + vivo["pct"] / 100) if vivo.get("c") and vivo.get("pct") is not None else None
    for k, ref in (("precio", vivo.get("c")), ("cierre_anterior", prev_byma), ("foto_de_la_noche", vivo.get("c"))):
        print(f"  {k:17s} antes {_f(ca[k], 2):>11s} ({_pct(ca[k], ref)} de la Bolsa)   "
              f"ahora {_f(cb[k], 2):>11s} ({_pct(cb[k], ref)})")
    print(f"  variación del día antes {ca['variacion']}")
    print(f"                    ahora {cb['variacion']}")
    print()
    from datetime import date, timedelta
    fechas_byma = sorted(byma)

    def de_la_semana(lunes):
        """El último cierre de BA.C de la semana que empieza `lunes` (la vela semanal)."""
        fin = (date.fromisoformat(lunes) + timedelta(days=6)).isoformat()
        dias = [f for f in fechas_byma if lunes <= f <= fin]
        return byma[dias[-1]] if dias else None

    for p in ("1m", "1y"):
        print(f"## El mini-gráfico ({p}): cada punto contra el cierre de BA.C de esa fecha"
              + (" (semanal: el último de la semana)" if p == "1y" else ""))
        for nombre, d in (("antes", antes[f"mini_{p}"]), ("ahora", ahora[f"mini_{p}"])):
            ref = {f: (de_la_semana(f) if p == "1y" else byma.get(f)) for f in d}
            dif = [d[f] / ref[f] - 1 for f in d if ref.get(f)]
            if dif:
                dif.sort()
                print(f"  {nombre}: {len(d)} puntos · mediana {dif[len(dif) // 2] * 100:+.2f} % · "
                      f"el más lejos {max(dif, key=abs) * 100:+.2f} % · último {list(d.items())[-1]}")
            else:
                print(f"  {nombre}: {len(d)} puntos, ninguno con fecha de la Bolsa")
    print()
    print("## La ficha en pesos")
    for nombre, f in (("antes", antes["ficha_ars"]), ("ahora", ahora["ficha_ars"])):
        pts = f["puntos"]
        dif = [pts[d] / byma[d] - 1 for d in pts if d in byma]
        peor = max(dif, key=abs) if dif else None
        dif.sort()
        ult = max(pts) if pts else None
        print(f"  {nombre}: {f['ticker']} · dólar {f['convertida']} · escala {f['escala']} · {len(pts)} velas · "
              f"última {ult} {_f(pts.get(ult), 2)} (BA.C ese día {_f(byma.get(ult), 2)}) · "
              f"contra BA.C: mediana {dif[len(dif) // 2] * 100 if dif else 0:+.2f} %, el más lejos "
              f"{(peor or 0) * 100:+.2f} % · tendencia {f['tendencia']}")
    print()
    print(f"## La vela de hoy:   antes {antes['hoy']}   ahora {ahora['hoy']}")
    print(f"## Las de 1 hora:    antes {antes['horas']}")
    print(f"                     ahora {ahora['horas']}")
    print(f"## En dólares:       antes {antes['ficha_usd']}   ahora {ahora['ficha_usd']}")
    print()
    print("## La liquidez de la ficha")
    for nombre, l in (("antes", antes["liquidez"]), ("ahora", ahora["liquidez"])):
        print(f"  {nombre}: {{nivel: {l.get('nivel')}, pesos_por_dia: {_f(l.get('pesos_por_dia'))}, "
              f"en_dolares: {l.get('en_dolares')}, fuente: {l.get('fuente')}, ruedas: {l.get('ruedas')}, "
              f"spread_pct: {l.get('spread_pct')}}}")


if __name__ == "__main__":
    if sys.argv[1] == "--comparar":
        comparar(sys.argv[2], sys.argv[3])
    else:
        correr(sys.argv[1], sys.argv[2])
