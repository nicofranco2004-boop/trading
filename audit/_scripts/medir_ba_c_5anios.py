"""BAC con BA.C: lo que la gente vería, 06/11/2026. El gráfico de 5 años
(desde 2021-11-08): cuántas ruedas el estimado (Nueva York × contado con liqui
del día ÷ 4) quedaba lejos del CEDEAR de la Bolsa, los meses peores, el máximo y
el mínimo del último año; y el día de hoy (precio, cierre anterior, variación).
Los mismos datos que medir_ba_c.py (data912, Yahoo, argentinadatos).

Uso: python3 -I medir_ba_c_5anios.py <DATOS> <BACKEND> > medir_ba_c_5anios.out"""
import json, os, sys, statistics as st
from datetime import date, timedelta
D = sys.argv[1]
sys.path.insert(0, sys.argv[2])
from fx import punta_media
bac = {f["date"][:10]: f for f in json.load(open(os.path.join(D, "BA.C.json")))}
ny = json.load(open(os.path.join(D, "bac_ny.json")))
CCL = {f["fecha"]: punta_media(f.get("compra"), f.get("venta")) for f in json.load(open(os.path.join(D, "ccl.json")))}
CCL = {k: v for k, v in CCL.items() if v}
def del_dia(d, dias=7):
    x = date.fromisoformat(d)
    for i in range(dias + 1):
        v = CCL.get((x - timedelta(days=i)).isoformat())
        if v:
            return v
desde = "2021-11-08"
filas = []
for d in sorted(bac):
    if d < desde or d not in ny or not del_dia(d):
        continue
    est = ny[d] * del_dia(d) / 4
    filas.append((d, est, bac[d]["c"], est / bac[d]["c"] - 1))
print(f"Gráfico de 5 años ({desde} → {filas[-1][0]}): {len(filas)} ruedas")
for lim in (0.01, 0.02, 0.05, 0.10):
    print(f"  ruedas con el estimado a más de {lim*100:.0f} % de BA.C: {sum(1 for f in filas if abs(f[3]) > lim)}")
meses = {}
for f in filas:
    meses.setdefault(f[0][:7], []).append(f[3])
print("  Meses con la mediana a más de 2 %:")
for m, e in sorted(meses.items()):
    if abs(st.median(e)) > 0.02:
        print(f"    {m}: mediana {st.median(e)*100:+.1f} % · el peor {min(e, key=lambda x: -abs(x))*100:+.1f} %")
# El máximo y el mínimo del período (lo que mira el análisis técnico)
for etiqueta, idx in (("estimado", 1), ("BA.C", 2)):
    ult = [f for f in filas if f[0] >= "2025-11-06"]
    mx = max(ult, key=lambda f: f[idx]); mn = min(ult, key=lambda f: f[idx])
    print(f"  Último año, {etiqueta}: máximo {mx[idx]:,.0f} ({mx[0]}) · mínimo {mn[idx]:,.0f} ({mn[0]})")
# Hoy
ccl_vivo = punta_media(1658.4, 1664.9)
est_hoy = ny["2026-11-06"] * ccl_vivo / 4
est_ayer = ny["2026-11-05"] * del_dia("2026-11-05") / 4
print(f"\nHoy 06/11: estimado {est_hoy:,.0f} (NY {ny['2026-11-06']:.2f} × CCL {ccl_vivo:.2f} ÷ 4) · BA.C {bac['2026-11-06']['c']:,.0f}")
print(f"  cierre anterior: estimado {est_ayer:,.0f} (NY {ny['2026-11-05']:.2f} × CCL del 05/11 {del_dia('2026-11-05'):.2f} ÷ 4) · BA.C {bac['2026-11-05']['c']:,.0f}")
print(f"  var. del día: estimado {(est_hoy/est_ayer-1)*100:+.2f} % · BA.C {(bac['2026-11-06']['c']/bac['2026-11-05']['c']-1)*100:+.2f} %")
print(f"  100 CEDEARs: estimado $ {est_hoy*100:,.0f} · BA.C $ {bac['2026-11-06']['c']*100:,.0f} · diferencia $ {(bac['2026-11-06']['c']-est_hoy)*100:,.0f}")
# El salto del día del cambio en la variación diaria: cierre anterior = el que guardó la noche (estimado) vs BA.C
