"""¿El rendimiento pondera el capital de cada momento? US$1.000 que suben 30 %, aporte de US$39.000,
baja de 10 %. Por el camino de producción (Schwab, USD), contra: TWR verdadero, TIR (ponderado por plata) y
resultado en dólares."""
from datetime import date, timedelta
import arnes
from mercado import Mercado

PX = [("2025-01-06", 100), ("2025-04-30", 130), ("2025-05-02", 130), ("2025-05-31", 120),
      ("2025-08-31", 117), (date.today().isoformat(), 117)]
FLUJOS = [("2025-01-06", 1000, 10), ("2025-05-02", 39000, 300)]   # (fecha, aporte USD, XYZ comprados)
m = Mercado(extra_usd={"XYZ": PX})
a = arnes.Arnes(m); a.usuario("pesos@rendi.test")
filas = ['"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"']
for f, ap, q in FLUJOS:
    d = date.fromisoformat(f).strftime("%m/%d/%Y"); px = ap / q
    filas.append(f'"{d}","MoneyLink Transfer","","Tfr BANK","","","","${ap:.2f}"')
    filas.append(f'"{d}","Buy","XYZ","XYZ CORP","{q}","${px:.2f}","","-${ap:.2f}"')
a.subir([("schwab.csv", "\n".join(filas).encode())], broker="Schwab", fmt="schwab")
a.cron(date(2026, 10, 1), date.today()); a.reconstruir()

def px(d): return m.usd("XYZ", d)
def valor(d):
    q = sum(qq for f, _, qq in FLUJOS if f <= d.isoformat()); return q * px(d)
def twr_verdad(d0, d1):
    idx, d, prev = 1.0, date.fromisoformat(d0), valor(date.fromisoformat(d0))
    while d < date.fromisoformat(d1):
        d += timedelta(days=1); fl = sum(ap for f, ap, _ in FLUJOS if f == d.isoformat())
        idx *= valor(d) / (prev + fl); prev = valor(d)
    return (idx - 1) * 100
def tir():
    hoy = date.today(); cfs = [(date.fromisoformat(f), -ap) for f, ap, _ in FLUJOS] + [(hoy, valor(hoy))]
    f = lambda r: sum(c / (1 + r) ** ((d - cfs[0][0]).days / 365.25) for d, c in cfs)
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2; (lo, hi) = (mid, hi) if f(mid) > 0 else (lo, mid)
    return mid * 100

mot = a.motor()
hoy = date.today().isoformat()
for modo in ("certero", "estimado"):
    r = mot[modo]; vd = r["ventana"][0]
    print(f"{modo:9s} Rendi {r['twr_pct']} % desde {vd} | TWR verdadero misma ventana "
          f"{twr_verdad(vd, hoy) if vd else float('nan'):.2f} % | motivo {r['motivo']}")
print(f"TWR verdadero desde la 1ª compra: {twr_verdad('2025-01-06', hoy):.2f} %")
print(f"TIR anual (ponderada por plata): {tir():.2f} %   ·   resultado en US$: {valor(date.today()) - 40000:,.0f} sobre 40.000 aportados")
conn = arnes.main.get_db()
c = arnes.twr.curva_indexada(conn, a.uid, modo="certero")
for p in c["curva"]:
    if "2025-03-31" <= p["date"] <= "2025-06-30":
        print("   punto", p["date"], p["clase"], "valor", round(p.get("value") or p.get("value_no_medible") or 0), "aportado", round(p["net_deposited"]), "ret leg", p.get("ret"))
print("   leg de mayo verdadero:", round((120 / 130 - 1) * 100, 2), "% (la plata nueva entró el 2/5 y estuvo todo el mes)")
