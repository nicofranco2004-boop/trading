"""Backtest: ¿cuánto se parece el dividendo que Rendi ESTIMARÍA al que el broker PAGÓ?

Estimado = CEDEARs que tenías antes del ex-date / ratio × dividendo por acción (historial yfinance).
Pagado   = fila DIVIDEND importada (USD, con activo).
Solo lectura sobre una copia de prod. Uso: YF_TZ_CACHE_LOCATION=$(mktemp -d) python3 backend/scripts/backtest_dividendos.py [ruta.db]
Resultado 09/10 (copia 16/08): brokers AR pagan ~64,5 % del bruto en acciones y ~70 % en ETFs; ~21 días después del ex-date.
"""
import re, sqlite3, random, json, sys, os, bisect
from collections import defaultdict
import yfinance as yf
import pandas as pd

DB = "file:" + (sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/Downloads/trading-2026-08-16.db")) + "?immutable=1"
RATIO_JS = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "utils", "cedearRatio.js")
OUT = os.environ.get("OUT_DIR", "/tmp")

# ── ratios ──
src = open(RATIO_JS).read()
block = src[src.index("export const CEDEAR_RATIOS"):]
block = block[:block.index("\n}")]
RATIO = {}
for m in re.finditer(r"['\"]?([A-Z0-9.]+)['\"]?\s*:\s*([0-9./ ]+)", block):
    k, v = m.group(1), m.group(2).strip()
    try:
        RATIO[k] = eval(v)
    except Exception:
        pass
print("ratios:", len(RATIO), file=sys.stderr)

con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row
fam = lambda b: (b or "").replace(" · USD", "").strip().lower()

rows = con.execute("""
  select b.user_id, b.parser_format f, n.broker, n.date, n.asset_symbol a, n.gross_amount g, n.currency c
  from import_normalized_tx n join import_batches b on b.id=n.batch_id
  where b.reverted_at is null and n.excluded_at is null and n.operation_type='DIVIDEND'
    and coalesce(n.asset_symbol,'')<>'' and n.currency='USD' and n.date>='2023-01-01'
    and b.parser_format in ('iol','balanz_movimientos','bullmarket','ppi','schwab','balanz_resultados','inviu','cocos')
""").fetchall()
US_BROKER_FMT = {"schwab"}
rows = [r for r in rows if r["f"] in US_BROKER_FMT or r["a"] in RATIO]
print("dividendos candidatos:", len(rows), file=sys.stderr)

random.seed(7)
tickers = sorted({r["a"] for r in rows})
# limitar llamadas: tickers con más filas primero
cnt = defaultdict(int)
for r in rows: cnt[r["a"]] += 1
tickers = sorted(tickers, key=lambda t: -cnt[t])[:70]
rows = [r for r in rows if r["a"] in tickers]

# ── historial de dividendos ──
DIV = {}
for t in tickers:
    try:
        s = yf.Ticker(t).dividends
        if s is not None and len(s):
            DIV[t] = [(d.strftime("%Y-%m-%d"), float(v)) for d, v in s.items()]
    except Exception as e:
        pass
print("tickers con historial:", len(DIV), "/", len(tickers), file=sys.stderr)

# ── tenencias: compras-ventas por (user, familia broker, activo) ──
trades = defaultdict(list)
for r in con.execute("""
  select b.user_id, n.broker, n.date, n.asset_symbol a, n.operation_type t, n.quantity q
  from import_normalized_tx n join import_batches b on b.id=n.batch_id
  where b.reverted_at is null and n.excluded_at is null and n.operation_type in ('BUY','SELL')
    and coalesce(n.quantity,0)>0"""):
    if r["a"] in DIV:
        trades[(r["user_id"], fam(r["broker"]), r["a"])].append((r["date"], r["q"] if r["t"] == "BUY" else -r["q"]))

def held(key, before):
    return sum(q for d, q in trades.get(key, []) if d < before)

out = []
for r in rows:
    hist = DIV.get(r["a"])
    if not hist:
        continue
    # ex-date más reciente entre 0 y 60 días antes del pago
    cands = [(d, v) for d, v in hist if d <= r["date"] and (pd.Timestamp(r["date"]) - pd.Timestamp(d)).days <= 60]
    if not cands:
        out.append(dict(f=r["f"], a=r["a"], estado="sin ex-date en yfinance")); continue
    exd, dps = cands[-1]
    q = held((r["user_id"], fam(r["broker"]), r["a"]), exd)
    if q <= 0:
        out.append(dict(f=r["f"], a=r["a"], estado="no puedo reconstruir tenencia")); continue
    ratio = 1.0 if r["f"] in US_BROKER_FMT else RATIO[r["a"]]
    est = q / ratio * dps
    out.append(dict(f=r["f"], a=r["a"], estado="ok", pagado=r["g"], estimado=est,
                    prop=r["g"] / est if est else None, exd=exd, pago=r["date"],
                    dias=(pd.Timestamp(r["date"]) - pd.Timestamp(exd)).days))

json.dump(out, open(os.path.join(OUT, "backtest_div.json"), "w"))
df = pd.DataFrame(out)
print(df.groupby(["f", "estado"]).size().unstack(fill_value=0))
ok = df[df.estado == "ok"].copy()
def banda(p):
    if p < 0.5: return "<50%"
    if p < 0.65: return "50-65%"
    if p < 0.75: return "65-75% (≈ −30%)"
    if p < 0.85: return "75-85%"
    if p < 0.95: return "85-95%"
    if p <= 1.05: return "95-105% (≈ bruto)"
    if p <= 1.5: return "105-150%"
    return ">150%"
ok["banda"] = ok.prop.apply(banda)
print(ok.groupby("f").prop.describe(percentiles=[.25, .5, .75]).round(3))
print(pd.crosstab(ok.f, ok.banda))
print("días ex-date→pago, mediana por broker:\n", ok.groupby("f").dias.median())
