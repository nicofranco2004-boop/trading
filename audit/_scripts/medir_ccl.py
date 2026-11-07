"""¿El CEDEAR estimado con el contado con liqui (CCL) DE CADA DÍA resuelve lo que
deja el MEP? Tres preguntas, con datos reales (06/11/2026):

  1. Precisión: el estimado (acción de Nueva York × dólar del día ÷ ratio) contra
     el cierre del CEDEAR en BYMA, día por día, 5 años.
  2. Saltos sin mercado: (a) el día que una serie de BYMA vieja pasa al estimado
     (DIAS_ATRASO: el pasado se corre y la tendencia puede dar vuelta) y (b) el
     día que la noche poda la serie vieja (A_PEDIDO_DIAS_SIN_USO: la escala
     medida pasa a la de la tabla y todo el gráfico salta).
  3. BAC: el gráfico (MEP de cada día) contra la valuación (CCL vivo).

Datos, ninguno de la base de desarrollo:
  · la acción de Nueva York: `medir_original.db` (la de la auditoría del 06/11:
    159 acciones de Yahoo, 5 años, sin ajustar por dividendos, como las guarda
    la noche);
  · el MEP y el CCL de cada día: argentinadatos (`bolsa`, `contadoconliqui`), el
    MEDIO con la regla de la app (`fx.punta_media`);
  · el CEDEAR en BYMA: data912 (`historical/cedears/X`), sólo ruedas con volumen.

Uso: DATOS=<carpeta> BACKEND=<carpeta backend> python3 medir_ccl.py > medir_ccl.out
"""
import json
import os
import sqlite3
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
# Los datos (no van al repo: 23 MB): medir_original.db de la auditoría del 06/11
# (~/Documents/rendi-archivo/auditoria-cedear-estimado-2026-11-06/), ad_bolsa.json y
# ad_contadoconliqui.json (argentinadatos) y d912/ (se baja solo, queda guardado).
DATOS = os.environ.get("DATOS") or os.path.join(os.path.dirname(AQUI), "datos")
os.environ["DB_PATH"] = os.path.join(DATOS, "no_usar.db")   # nunca la base de desarrollo
sys.path.insert(0, os.environ["BACKEND"])
import logging
logging.disable(logging.WARNING)
from fx import punta_media                                   # noqa: E402
from ratios_cedear import CEDEAR_RATIOS                      # noqa: E402
import velas_diarias                                         # noqa: E402
import tecnico                                               # noqa: E402

HASTA = "2026-11-05"          # la última rueda de Nueva York de la base
CORTE_ATRASO = 4              # ruedas sin bajar = 6 días corridos (DIAS_ATRASO = 5)
CORTE_PODA = 31               # ~45 días corridos (A_PEDIDO_DIAS_SIN_USO)
RUEDAS = tecnico.RUEDAS_ESCALA


def dolar(nombre):
    filas = json.load(open(os.path.join(DATOS, f"ad_{nombre}.json")))
    if nombre == "contadoconliqui" and os.environ.get("CCL_CORREGIDO"):
        # Con la fecha como la guarda la app (`fx.fechas_de_argentinadatos`: desde
        # septiembre de 2026 la fuente fecha cada cierre con el día siguiente).
        from fx import fechas_de_argentinadatos
        return {f: punta_media(c, v) for f, c, v in fechas_de_argentinadatos(
            [(x.get("fecha"), x.get("compra"), x.get("venta")) for x in filas], "2026-11-06")}
    return {f["fecha"]: punta_media(f.get("compra"), f.get("venta")) for f in filas if f.get("fecha")}


MEP, CCL = dolar("bolsa"), dolar("contadoconliqui")


def del_dia(serie, d, dias=7):
    """El dólar de `d` o el último antes (hasta `dias`): la regla de `fx.serie_diaria`."""
    x = date.fromisoformat(d)
    for i in range(dias + 1):
        v = serie.get((x - timedelta(days=i)).isoformat())
        if v:
            return v
    return None


def bajar_byma(codigo):
    ruta = os.path.join(DATOS, "d912", f"{codigo}.json")
    if not os.path.exists(ruta):
        for intento in range(3):
            try:
                r = requests.get(f"https://data912.com/historical/cedears/{codigo}", timeout=30)
                if r.status_code == 200:
                    json.dump(r.json(), open(ruta, "w"))
                    break
            except Exception:
                time.sleep(2)
        else:
            return {}
    try:
        filas = json.load(open(ruta))
    except Exception:
        return {}
    if not isinstance(filas, list):      # {"Error": "...no tengo ese ticker..."}
        return {}
    return {str(f["date"])[:10]: float(f["c"]) for f in filas
            if f.get("c") and float(f["c"]) > 0 and (f.get("v") or 0) > 0}


con = sqlite3.connect(os.path.join(DATOS, "medir_original.db"))
afuera_de = {}
for k in sorted(CEDEAR_RATIOS):
    if k == "BRK-B":          # la misma que BRKB (el código de BYMA)
        continue
    afuera_de[k] = velas_diarias.ticker_de_afuera(k)
usa = {}
for k, t in afuera_de.items():
    filas = con.execute("SELECT date, close FROM velas_diarias WHERE symbol=? AND date<=? ORDER BY date",
                        (t, HASTA)).fetchall()
    if filas:
        usa[k] = dict(filas)
os.makedirs(os.path.join(DATOS, "d912"), exist_ok=True)
with ThreadPoolExecutor(4) as ex:
    byma = dict(zip(usa, ex.map(bajar_byma, list(usa))))


def tramo(k):
    """Las ruedas en común desde el último cambio de ratio (un salto de más de
    25 % del dólar implícito de un día al otro: BYMA no lo corrige y Yahoo ajusta
    los splits). [(fecha, usa, byma, mep, ccl)]."""
    r = CEDEAR_RATIOS[k]
    filas = []
    for d in sorted(set(usa[k]) & set(byma.get(k) or {})):
        m, c = del_dia(MEP, d), del_dia(CCL, d)
        if m and c:
            filas.append((d, usa[k][d], byma[k][d], m, c))
    desde = 0
    for i in range(1, len(filas)):
        a, b = filas[i - 1], filas[i]
        if abs((b[2] * r / b[1]) / (a[2] * r / a[1]) - 1) > 0.25:
            desde = i
    return filas[desde:]


def med(xs):
    return statistics.median(xs) if xs else None


def pct(x, n=1):
    return "—" if x is None else f"{x * 100:+.{n}f} %"


def cuantos(xs, tope):
    return f"{sum(abs(x) <= tope for x in xs) * 100 / len(xs):.0f} %" if xs else "—"


tramos = {k: tramo(k) for k in usa}
tabla_dudosa, buenos = {}, {}
for k, f in tramos.items():
    if len(f) < 20:
        continue
    r = CEDEAR_RATIOS[k]
    e = med([u * c / r / b - 1 for _, u, b, m, c in f[-20:]])
    if abs(e) > 0.15:
        tabla_dudosa[k] = e
    else:
        buenos[k] = f

print(f"CEDEARs de la tabla con la acción de afuera en la base: {len(usa)}; con BYMA en data912: "
      f"{sum(1 for k in usa if byma.get(k))}; comparables: {len(buenos)}")
print("Tabla dudosa (el estimado con el CCL a más de 15 % de BYMA en las últimas 20 ruedas): "
      + ", ".join(f"{k} {pct(e, 0)}" for k, e in sorted(tabla_dudosa.items())))
print(f"MEP {HASTA}: {del_dia(MEP, HASTA):.2f} · CCL {HASTA}: {del_dia(CCL, HASTA):.2f} "
      f"(CCL/MEP − 1 = {pct(del_dia(CCL, HASTA) / del_dia(MEP, HASTA) - 1)})")

# ── 1. Precisión ──────────────────────────────────────────────────────────────
print("\n1. EL ESTIMADO CONTRA EL CIERRE DE BYMA (estimado/BYMA − 1), todas las ruedas en común")
print(f"{'año':6s} {'ruedas':>7s} {'CEDEARs':>8s} │ {'MEP: mediana':>12s} {'|err| med.':>10s} {'≤2 %':>5s} {'≤3 %':>5s}"
      f" │ {'CCL: mediana':>12s} {'|err| med.':>10s} {'≤2 %':>5s} {'≤3 %':>5s}")
por_anio = {}
for k, f in buenos.items():
    r = CEDEAR_RATIOS[k]
    for d, u, b, m, c in f:
        por_anio.setdefault(d[:4], []).append((k, u * m / r / b - 1, u * c / r / b - 1))
for a in sorted(por_anio):
    xs = por_anio[a]
    em, ec = [x[1] for x in xs], [x[2] for x in xs]
    print(f"{a:6s} {len(xs):7d} {len({x[0] for x in xs}):8d} │ {pct(med(em)):>12s} {pct(med([abs(x) for x in em])):>10s} "
          f"{cuantos(em, .02):>5s} {cuantos(em, .03):>5s} │ {pct(med(ec)):>12s} {pct(med([abs(x) for x in ec])):>10s} "
          f"{cuantos(ec, .02):>5s} {cuantos(ec, .03):>5s}")
ult = [(k, f[-1]) for k, f in buenos.items() if f[-1][0] == HASTA]
em = [u * m / CEDEAR_RATIOS[k] / b - 1 for k, (d, u, b, m, c) in ult]
ec = [u * c / CEDEAR_RATIOS[k] / b - 1 for k, (d, u, b, m, c) in ult]
print(f"{HASTA} ({len(ult)} CEDEARs): MEP mediana {pct(med(em))}, a más de 3 %: {sum(abs(x) > .03 for x in em)} · "
      f"CCL mediana {pct(med(ec))}, a más de 3 %: {sum(abs(x) > .03 for x in ec)}")

print("\n   Mes a mes (la mediana de todos los CEDEARs): con el MEP el error se mueve con la distancia CCL/MEP;")
print("   con el CCL queda quieto. «CCL/MEP» = cuánto más caro estuvo el CCL que el MEP ese mes (mediana).")
por_mes = {}
for k, f in buenos.items():
    r = CEDEAR_RATIOS[k]
    for d, u, b, m, c in f:
        por_mes.setdefault(d[:7], []).append((u * m / r / b - 1, u * c / r / b - 1, c / m - 1))
print(f"   {'mes':8s} {'MEP':>8s} {'CCL':>8s} {'CCL/MEP':>8s}")
for mes in sorted(por_mes):
    xs = por_mes[mes]
    print(f"   {mes:8s} {pct(med([x[0] for x in xs])):>8s} {pct(med([x[1] for x in xs])):>8s} {pct(med([x[2] for x in xs])):>8s}")


# ── 1b. Desde septiembre de 2026 ──────────────────────────────────────────────
# Desde ahí la fuente fecha cada cierre con el día siguiente (`fx.fechas_de_argentinadatos`;
# con CCL_CORREGIDO=1 se corrige como en la app). La variación del día no depende de
# la escala: dice si cada vela va con el dólar de SU día.
print("\n1b. DESDE SEPTIEMBRE DE 2026, con el CCL " + ("con la fecha corregida" if os.environ.get("CCL_CORREGIDO")
                                                     else "con la fecha de la fuente"))
errs, variaciones = [], []
for k, f in buenos.items():
    r = CEDEAR_RATIOS[k]
    antes = None
    for d, u, b, m, c in f:
        if d >= "2026-09-01":
            errs.append(abs(u * c / r / b - 1))
            if antes:
                variaciones.append(abs((u * c) / (antes[0] * antes[2]) - b / antes[1]))
        antes = (u, b, c)
print(f"   {len(errs)} ruedas de {len({k for k, f in buenos.items() if f[-1][0] >= '2026-09-01'})} CEDEARs: "
      f"|estimado/BYMA − 1| mediana {pct(med(errs), 2)} · la variación del día, mediana de cuánto "
      f"se aleja de la de BYMA: {pct(med(variaciones), 2)} (puntos)")

# ── 2. Saltos ─────────────────────────────────────────────────────────────────
def escala_medida(f, cortar, fx):
    """`_escala_en_bolsa` con la serie de BYMA guardada sin sus últimas `cortar`
    ruedas: la mediana de (afuera × dólar ÷ BYMA) de sus últimas RUEDAS en común."""
    g = f[:-cortar] if cortar else f
    cocientes = sorted(u * (m if fx == "mep" else c) / b for d, u, b, m, c in g[-RUEDAS:])
    return statistics.median(cocientes) if cocientes else None


def velas(pares):
    return [{"date": d, "open": x, "high": x, "low": x, "close": x, "volume": 0} for d, x in pares]


def hace(d, dias):
    return (date.fromisoformat(d) - timedelta(days=dias)).isoformat()


def en(serie, d):
    ks = [x for x in serie if x <= d]
    return serie[max(ks)] if ks else None


print("\n2a. EL DÍA QUE LA SERIE DE BYMA QUEDA VIEJA (lo vendió hace 4 ruedas: pasa al estimado con la escala")
print("    medida en las últimas 5 ruedas guardadas). Mismo último día; real = BYMA. ¿Cuánto se corre el pasado")
print("    y cambia la lectura? (como exp_f de la auditoría, con MEP y con CCL)")
filas_2a = []
for k, f in sorted(buenos.items()):
    if f[-1][0] != HASTA or len(f) < 300:
        continue
    f = f[-520:]
    real = {d: b for d, u, b, m, c in f}
    lr = tecnico.lectura(velas(sorted(real.items())))
    fila = {"k": k, "real": lr}
    for fx in ("mep", "ccl"):
        esc = escala_medida(f, CORTE_ATRASO, fx)
        tc = MEP if fx == "mep" else CCL
        serie_us = {d: x for d, x in usa[k].items() if d >= f[0][0]}
        est = {d: u * del_dia(tc, d) / esc for d, u in serie_us.items() if del_dia(tc, d)}
        le = tecnico.lectura(velas(sorted(est.items())))
        fila[fx] = {"esc": esc, "lect": le,
                    "6m": en(est, hace(HASTA, 182)) / en(real, hace(HASTA, 182)) - 1,
                    "1a": en(est, hace(HASTA, 365)) / en(real, hace(HASTA, 365)) - 1,
                    "hoy": est[HASTA] / real[HASTA] - 1}
    filas_2a.append(fila)
print(f"   {'':6s} {'hoy':>15s} {'hace 6 meses':>15s} {'hace un año':>15s}   {'tendencia (real → MEP / CCL)':34s}"
      f" {'«en un año» real → MEP / CCL':30s}")
vuelta = {"mep": [], "ccl": []}
d12 = {"mep": [], "ccl": []}
for x in filas_2a:
    r = x["real"]
    for fx in ("mep", "ccl"):
        if x[fx]["lect"]["tendencia"] != r["tendencia"]:
            vuelta[fx].append(x["k"])
        if r["rend_12m"] is not None and x[fx]["lect"]["rend_12m"] is not None:
            d12[fx].append(abs(x[fx]["lect"]["rend_12m"] - r["rend_12m"]))
    marca = "  ← CAMBIA LA TENDENCIA con el " + " y ".join(fx.upper() for fx in ("mep", "ccl")
                                                         if x[fx]["lect"]["tendencia"] != r["tendencia"]) \
        if any(x[fx]["lect"]["tendencia"] != r["tendencia"] for fx in ("mep", "ccl")) else ""
    def r12(l):
        return "—" if l.get("rend_12m") is None else f"{l['rend_12m']:.1f}"
    print(f"   {x['k']:6s} {pct(x['mep']['hoy']):>7s}/{pct(x['ccl']['hoy']):>7s} {pct(x['mep']['6m']):>7s}/{pct(x['ccl']['6m']):>7s} "
          f"{pct(x['mep']['1a']):>7s}/{pct(x['ccl']['1a']):>7s}   "
          f"{r['tendencia'] + ' → ' + x['mep']['lect']['tendencia'] + ' / ' + x['ccl']['lect']['tendencia']:34s} "
          f"{r12(r)} → {r12(x['mep']['lect'])} / {r12(x['ccl']['lect'])}{marca}")
for fx in ("mep", "ccl"):
    a1 = sorted(abs(x[fx]["1a"]) for x in filas_2a)
    print(f"   Con el {fx.upper()}: comparados {len(filas_2a)}; el precio de hace un año se corre {pct(med(a1))} (mediana, "
          f"sin signo), hasta {pct(a1[-1])}; la tendencia de fondo cambia en {len(vuelta[fx])}: {vuelta[fx]}; "
          f"«en un año» cambia {med(d12[fx]):.1f} puntos (mediana), hasta {max(d12[fx]):.1f}")

print("\n2b. EL DÍA QUE LA NOCHE PODA LA SERIE VIEJA (guardada hasta hace 31 ruedas): la escala medida pasa a la")
print("    de la tabla y TODO el gráfico se mueve lo mismo. Salto = escala medida ÷ tabla − 1; y cómo queda contra BYMA.")
saltos = {"mep": [], "ccl": []}
lejos = {"mep": [], "ccl": []}
for k, f in sorted(buenos.items()):
    if f[-1][0] != HASTA or len(f) < CORTE_PODA + RUEDAS:
        continue
    r = CEDEAR_RATIOS[k]
    d, u, b, m, c = f[-1]
    for fx in ("mep", "ccl"):
        esc = escala_medida(f, CORTE_PODA, fx)
        saltos[fx].append(esc / r - 1)
        tc = m if fx == "mep" else c
        lejos[fx].append((u * tc / esc / b - 1, u * tc / r / b - 1))
for fx in ("mep", "ccl"):
    s = saltos[fx]
    print(f"   Con el {fx.upper()} ({len(s)} CEDEARs): salto mediano {pct(med(s))}; más de 2 %: {sum(abs(x) > .02 for x in s)}; "
          f"contra BYMA: antes de la poda {pct(med([x[0] for x in lejos[fx]]))}, después {pct(med([x[1] for x in lejos[fx]]))} (medianas)")

# ── 3. BAC ─────────────────────────────────────────────────────────────────────
print("\n3. BAC (BYMA lo cotiza roto: su gráfico en pesos es SIEMPRE el estimado; la cartera lo valúa × CCL vivo ÷ 4)")
u = usa["BAC"][HASTA]
m, c = del_dia(MEP, HASTA), del_dia(CCL, HASTA)
vivo = requests.get("https://dolarapi.com/v1/dolares/contadoconliqui", timeout=20).json()
c_vivo = punta_media(vivo.get("compra"), vivo.get("venta"))
print(f"   BAC en Nueva York, cierre {HASTA}: US$ {u:.2f}")
print(f"   gráfico hoy (MEP {m:.2f}):            $ {u * m / 4:,.0f}")
print(f"   gráfico con el CCL de ese día ({c:.2f}): $ {u * c / 4:,.0f}")
print(f"   cartera, «cierre anterior» (× el CCL vivo de dolarapi, {c_vivo:.2f} al {vivo.get('fechaActualizacion')}): $ {u * c_vivo / 4:,.0f}")
print(f"   CCL de argentinadatos del {vivo.get('fechaActualizacion', '')[:10]}: "
      f"{del_dia(CCL, vivo.get('fechaActualizacion', '')[:10]):.2f} (el mismo número que el de dolarapi: "
      f"{abs(del_dia(CCL, vivo.get('fechaActualizacion', '')[:10]) - c_vivo) < 0.01})")

json.dump({"filas_2a": [{"k": x["k"], "mep": {kk: v for kk, v in x["mep"].items() if kk != "lect"},
                         "ccl": {kk: v for kk, v in x["ccl"].items() if kk != "lect"}} for x in filas_2a],
           "saltos": saltos, "tabla_dudosa": tabla_dudosa},
          open(os.path.join(AQUI, "medir_ccl.json"), "w"))
