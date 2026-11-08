"""¿Sirve «BA.C» (el CEDEAR de Bank of America en pesos, en BYMA) como precio de BAC
en vez del estimado (acción de Nueva York × contado con liqui de cada día ÷ 4)?

Datos reales bajados el 06/11/2026 ~19:30 (carpeta DATOS):
  · BA.C.json  data912 historical/cedears/BA.C (o h l c v dr sa; v = CEDEARs operados)
  · live_cedears.json  data912 live/arg_cedears (c, v, q_op, px_bid, px_ask, pct_change)
  · bac_ny.json  Yahoo BAC diario, auto_adjust=False (como la noche)
  · ccl.json  argentinadatos contadoconliqui (el medio con fx.punta_media, como la app)
  · SPY.json, AAPL.json, … : otros CEDEARs de data912, para el calendario de BYMA y
    para comparar cuánto se opera.

Uso: python3 medir_ba_c.py <DATOS> <BACKEND>
"""
import json
import os
import statistics as st
import sys
from datetime import date, timedelta

DATOS, BACKEND = sys.argv[1], sys.argv[2]
os.environ["DB_PATH"] = os.path.join(DATOS, "no_usar.db")
sys.path.insert(0, BACKEND)
from fx import punta_media  # noqa: E402
from ratios_cedear import CEDEAR_RATIOS  # noqa: E402

RATIO = CEDEAR_RATIOS["BAC"]


def cargar(n):
    return json.load(open(os.path.join(DATOS, n)))


def hist(n):
    d = cargar(n)
    return d if isinstance(d, list) else []


bac = hist("BA.C.json")
ny = cargar("bac_ny.json")
CCL = {f["fecha"]: punta_media(f.get("compra"), f.get("venta")) for f in cargar("ccl.json") if f.get("fecha")}
CCL = {k: v for k, v in CCL.items() if v}
live = {r["symbol"]: r for r in cargar("live_cedears.json")}


def del_dia(serie, d, dias=7):
    x = date.fromisoformat(d)
    for i in range(dias + 1):
        v = serie.get((x - timedelta(days=i)).isoformat())
        if v:
            return v
    return None


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def miles(x):
    return f"{x:,.0f}".replace(",", ".")


print(f"Ratio de la tabla para BAC: {RATIO}")
print(f"BA.C: {len(bac)} ruedas, de {bac[0]['date']} a {bac[-1]['date']}")

# ── 1. Calendario de BYMA y huecos ─────────────────────────────────────────────
otros = ["SPY", "AAPL", "KO", "MELI", "MSFT", "GOOGL", "DISN", "XOM", "PFE", "GS", "WFC", "BABA",
         "JPM", "C", "NVDA", "BRKB"]
H = {t: hist(f"{t}.json") for t in otros if os.path.exists(os.path.join(DATOS, f"{t}.json"))}
calendario = set()
for t in ("SPY", "AAPL", "KO", "MSFT", "GOOGL"):
    calendario |= {str(f["date"])[:10] for f in H.get(t, []) if (f.get("v") or 0) > 0}
desde, hasta = bac[0]["date"], bac[-1]["date"]
cal = sorted(d for d in calendario if desde <= d <= hasta)
fechas_bac = {str(f["date"])[:10]: f for f in bac}
faltan = [d for d in cal if d not in fechas_bac]
sin_vol = [f["date"] for f in bac if not (f.get("v") or 0) > 0]
print("\n== 1. Huecos (ruedas de BYMA sin fila de BA.C) y ruedas sin operar (volumen 0)")
print(f"Ruedas de BYMA entre {desde} y {hasta} (SPY/AAPL/KO/MSFT/GOOGL con volumen): {len(cal)}")
por_anio = {}
for d in cal:
    a = d[:4]
    x = por_anio.setdefault(a, {"ruedas": 0, "falta": 0, "sinvol": 0})
    x["ruedas"] += 1
    if d not in fechas_bac:
        x["falta"] += 1
    elif not (fechas_bac[d].get("v") or 0) > 0:
        x["sinvol"] += 1
for a, x in sorted(por_anio.items()):
    print(f"  {a}: {x['ruedas']} ruedas · sin fila {x['falta']} · fila con volumen 0: {x['sinvol']}")
print(f"  Total sin fila: {len(faltan)} · con volumen 0: {len(sin_vol)}")
if faltan:
    print("  Últimas sin fila:", ", ".join(faltan[-12:]))
extra = [d for d in fechas_bac if d not in calendario and d >= desde]
print(f"  Filas de BA.C en días que el calendario no tiene: {len(extra)} {extra[-5:]}")
# Huecos largos: cuántas ruedas seguidas sin fila o sin volumen
peor, actual, peor_fin = 0, 0, None
for d in cal:
    f = fechas_bac.get(d)
    if not f or not (f.get("v") or 0) > 0:
        actual += 1
        if actual > peor:
            peor, peor_fin = actual, d
    else:
        actual = 0
print(f"  La racha más larga sin operar (sin fila o volumen 0): {peor} ruedas, terminó {peor_fin}")

# ── 2. Volumen ────────────────────────────────────────────────────────────────
print("\n== 2. Cuánto se opera (v = CEDEARs por rueda; monto = v × cierre, en pesos)")


def resumen_volumen(filas, desde_d):
    xs = [f for f in filas if str(f["date"])[:10] >= desde_d]
    v = [float(f.get("v") or 0) for f in xs]
    m = [float(f.get("v") or 0) * float(f.get("c") or 0) for f in xs]
    return xs, v, m


for a in ("2021", "2022", "2023", "2024", "2025", "2026"):
    xs = [f for f in bac if str(f["date"]).startswith(a)]
    if not xs:
        continue
    v = [float(f.get("v") or 0) for f in xs]
    m = [float(f.get("v") or 0) * float(f.get("c") or 0) for f in xs]
    usd = [mm / del_dia(CCL, str(f["date"])[:10]) for mm, f in zip(m, xs) if del_dia(CCL, str(f["date"])[:10])]
    print(f"  {a}: mediana {miles(st.median(v))} CEDEARs/rueda · p10 {miles(pct(v, 10))} · "
          f"monto mediano $ {miles(st.median(m))} (≈ US$ {miles(st.median(usd))}) · ruedas con < 100 CEDEARs: "
          f"{sum(1 for x in v if x < 100)} de {len(v)}")
ULT = 250
ult = bac[-ULT:]
print(f"\n  Últimas {ULT} ruedas, monto mediano por rueda (pesos), BA.C contra otros CEDEARs de data912:")
fila_monto = []
for t, filas in [("BA.C", bac)] + sorted(H.items()):
    xs = filas[-ULT:]
    if len(xs) < 50:
        continue
    m = [float(f.get("v") or 0) * float(f.get("c") or 0) for f in xs]
    ceros = sum(1 for f in xs if not (f.get("v") or 0) > 0)
    fila_monto.append((st.median(m), t, ceros, len(xs)))
for mm, t, ceros, n in sorted(fila_monto, reverse=True):
    print(f"    {t:6s} $ {miles(mm):>15s}  · ruedas con volumen 0: {ceros} de {n}")

# ── 3. Precio clavado ─────────────────────────────────────────────────────────
print("\n== 3. Cierre repetido (el mismo cierre ruedas seguidas)")
rachas, r = [], 1
for i in range(1, len(bac)):
    if bac[i]["c"] == bac[i - 1]["c"]:
        r += 1
    else:
        if r >= 2:
            rachas.append((r, bac[i - 1]["date"]))
        r = 1
print(f"  Rachas de 2+ ruedas con el mismo cierre: {len(rachas)}; la más larga: {max(rachas) if rachas else None}")
print(f"  En las últimas {ULT} ruedas: {sum(1 for x in rachas if x[1] >= ult[0]['date'])}")

# ── 4. Cambios de ratio: el ratio implícito (acción de NY × CCL ÷ BA.C) ───────
print("\n== 4. Ratio implícito día por día (Nueva York × CCL ÷ BA.C): ¿cambió alguna vez?")
filas = []
for f in bac:
    d = str(f["date"])[:10]
    p, c = ny.get(d), del_dia(CCL, d)
    if p and c and f.get("c") and (f.get("v") or 0) > 0:
        filas.append((d, p * c / float(f["c"]), float(f["c"]), p, c, float(f.get("v") or 0)))
saltos = [(filas[i][0], filas[i - 1][1], filas[i][1]) for i in range(1, len(filas))
          if abs(filas[i][1] / filas[i - 1][1] - 1) > 0.25]
print(f"  Ruedas con los tres datos (y volumen): {len(filas)}")
print(f"  Saltos de más de 25 % del ratio implícito de un día al otro: {len(saltos)} {saltos[:5]}")
for a in sorted({x[0][:4] for x in filas}):
    rs = [x[1] for x in filas if x[0].startswith(a)]
    print(f"  {a}: ratio implícito mediano {st.median(rs):.3f} (p5 {pct(rs, 5):.3f} · p95 {pct(rs, 95):.3f})")

# ── 5. Error del estimado contra BA.C (mismo día) ─────────────────────────────
print("\n== 5. Estimado (NY × CCL del día ÷ 4) contra BA.C, mismo día: estimado/BA.C − 1")


def err_lineas(xs, rot):
    e = [x[2] for x in xs]
    if not e:
        return
    ab = [abs(z) for z in e]
    peor = max(xs, key=lambda x: abs(x[2]))
    print(f"  {rot}: {len(e)} ruedas · mediana {st.median(e) * 100:+.2f} % · a menos de 1 %: "
          f"{sum(1 for z in ab if z <= 0.01) * 100 / len(e):.0f} % · de 2 %: "
          f"{sum(1 for z in ab if z <= 0.02) * 100 / len(e):.0f} % · p5 {pct(e, 5) * 100:+.2f} · "
          f"p95 {pct(e, 95) * 100:+.2f} · el peor {peor[2] * 100:+.1f} % ({peor[0]})")


errs = [(x[0], x[5], x[3] * x[4] / RATIO / x[2] - 1) for x in filas]
for a in sorted({x[0][:4] for x in errs}):
    err_lineas([x for x in errs if x[0].startswith(a)], a)
err_lineas(errs[-ULT:], f"últimas {ULT}")
chicas = [x for x in errs[-ULT:] if x[1] < pct([y[1] for y in errs[-ULT:]], 10)]
err_lineas(chicas, f"últimas {ULT}, el 10 % de ruedas con MENOS volumen")

# ── 6. Variación del día: la de BA.C contra la del estimado ──────────────────
print("\n== 6. Variación del día: BA.C (cierre/cierre anterior) contra el estimado (ídem)")
dif, signo, n = [], 0, 0
for i in range(1, len(filas)):
    d0, d1 = filas[i - 1], filas[i]
    if (date.fromisoformat(d1[0]) - date.fromisoformat(d0[0])).days > 5:
        continue
    vb = d1[2] / d0[2] - 1
    ve = (d1[3] * d1[4]) / (d0[3] * d0[4]) - 1
    if d1[0] >= filas[-ULT][0]:
        dif.append(abs(vb - ve))
        n += 1
        if (vb > 0) != (ve > 0) and abs(vb) > 0.002 and abs(ve) > 0.002:
            signo += 1
print(f"  Últimas {ULT}: |diferencia| mediana {st.median(dif) * 100:.2f} puntos · p90 {pct(dif, 90) * 100:.2f} · "
      f"p99 {pct(dif, 99) * 100:.2f} · días con signo opuesto (los dos > 0,2 %): {signo} de {n}")

# ── 7. Hoy, en vivo ───────────────────────────────────────────────────────────
print("\n== 7. Hoy (feed en vivo de data912, ~19:30 del 06/11/2026)")
b = live.get("BA.C") or {}
print(f"  BA.C: último {b.get('c')} · var {b.get('pct_change')} % · volumen {b.get('v')} · operaciones {b.get('q_op')}"
      f" · punta compradora {b.get('px_bid')} / vendedora {b.get('px_ask')} "
      f"(separación {(b['px_ask'] / b['px_bid'] - 1) * 100:.2f} %)")
x = live.get("BAC") or {}
print(f"  'BAC' del feed (lo que hoy NO se usa por roto): último {x.get('c')} · volumen {x.get('v')} · operaciones {x.get('q_op')}")
ccl_vivo = punta_media(1658.4, 1664.9)
ny_hoy = ny.get("2026-11-06")
est = ny_hoy * ccl_vivo / RATIO
print(f"  Estimado: NY {ny_hoy:.2f} × CCL vivo {ccl_vivo:.2f} ÷ {RATIO} = {est:,.0f} → {(est / b['c'] - 1) * 100:+.2f} % de BA.C")
pesos = [(r["v"] * r["c"], s) for s, r in live.items()
         if r.get("c") and r["c"] > 1000 and r.get("v") is not None]
pesos.sort(reverse=True)
pos = [s for _, s in pesos].index("BA.C") + 1 if "BA.C" in [s for _, s in pesos] else None
print(f"  Monto operado hoy: BA.C puesto {pos} de {len(pesos)} CEDEARs en pesos del feed")
print("  Puntas (separación compra/venta) de los CEDEARs en pesos con monto hoy, mediana: "
      f"{st.median([(r['px_ask'] / r['px_bid'] - 1) * 100 for r in live.values() if r.get('c') and r['c'] > 1000 and r.get('px_bid') and r.get('px_ask') and r['v'] > 0]):.2f} %")
