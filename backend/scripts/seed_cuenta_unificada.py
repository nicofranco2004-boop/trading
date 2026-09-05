"""Fixture para probar la tarjeta de cuenta unificada a mano.

Arma un usuario con UN broker bimonetario (padre ARS + sibling '· USD') y
posiciones deliberadamente mezcladas, incluyendo el caso que NO existe en
ninguna base real: el MISMO ticker comprado en las dos patas.
"""
import os, sys, sqlite3
sys.path.insert(0, os.getcwd())
from passlib.context import CryptContext

EMAIL = "unificada@rendi.test"
PASS  = "Unificada2026"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

conn = sqlite3.connect("trading.db"); conn.row_factory = sqlite3.Row
c = conn.cursor()

# idempotente: si ya existe, se borra y se rearma
# Se REUSA el usuario si ya existe: borrar y recrear le cambiaba el id, y la
# sesión abierta en el navegador quedaba apuntando a una cuenta que ya no está
# (se ve como "la cartera se vació"). Sólo se limpian sus datos.
old = c.execute("SELECT id FROM users WHERE email=?", (EMAIL,)).fetchone()
if old:
    uid = old["id"]
    for t in ("positions", "operations", "monthly_entries", "brokers"):
        c.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    c.execute("UPDATE users SET password_hash=?, approved=1, tier='admin', "
              "email_verified=1 WHERE id=?", (pwd.hash(PASS), uid))
else:
    uid = c.execute(
        "INSERT INTO users (email, name, password_hash, approved, tier, email_verified) "
        "VALUES (?,?,?,1,'admin',1)", (EMAIL, "Test Unificada", pwd.hash(PASS))).lastrowid

PADRE, SIB = "Cocos", "Cocos · USD"
pid = c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'ARS')",
                (uid, PADRE)).lastrowid
c.execute("INSERT INTO brokers (user_id,name,currency,parent_broker_id) VALUES (?,?,'USDT',?)",
          (uid, SIB, pid))
# Un broker suelto, para confirmar que una cuenta de una sola pata no cambia.
c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Schwab','USD')", (uid,))

def pos(broker, asset, qty, invested, *, ccy, atype=None, cash=0, date=None, tc=None):
    c.execute("""INSERT INTO positions (user_id,broker,asset,is_cash,buy_price,quantity,
                 invested,currency,asset_type,entry_date,tc_compra,commissions)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
              (uid, broker, asset, cash, (invested/qty) if qty else None, qty,
               invested, ccy, atype, date, tc))

# ── EL CASO CLAVE: el mismo ticker en las DOS patas ───────────────────────
# GGAL: 100 en pesos a ARS 1.000 + 50 por dólar-MEP a US$0,80.
# Es el ejemplo exacto del análisis: promedio crudo daría 666,93 (sin unidad);
# convertido da ARS 1.053,33, que es el real.
pos(PADRE, "GGAL", 100, 100_000, ccy="ARS", atype="ACCION_AR", date="2026-02-10", tc=1200)
pos(SIB,   "GGAL",  50,      40, ccy="USD", atype="ACCION_AR", date="2026-05-20")

# Mismo ticker en las dos patas Y multi-lote de cada lado (fusionada + expandible)
pos(PADRE, "AAPL", 10, 120_000, ccy="ARS", atype="CEDEAR", date="2026-01-15", tc=1150)
pos(PADRE, "AAPL",  5,  70_000, ccy="ARS", atype="CEDEAR", date="2026-03-02", tc=1290)
pos(SIB,   "AAPL",  8,     190, ccy="USD", atype="CEDEAR", date="2026-06-11")

# ── Sólo en el padre (pesos) ──────────────────────────────────────────────
pos(PADRE, "YPFD", 30, 450_000, ccy="ARS", atype="ACCION_AR", date="2026-04-01", tc=1310)
pos(PADRE, "PAMP", 200, 380_000, ccy="ARS", atype="ACCION_AR", date="2026-02-22", tc=1240)
pos(PADRE, "MELI",  2, 260_000, ccy="ARS", atype="CEDEAR",    date="2026-07-08", tc=1380)

# ── Sólo en el sibling (dólares) ──────────────────────────────────────────
pos(SIB, "NVDA", 12, 1_450, ccy="USD", atype="CEDEAR", date="2026-03-18")
pos(SIB, "KO",   40,   980, ccy="USD", atype="CEDEAR", date="2026-05-05")
pos(SIB, "TSLA",  6, 1_120, ccy="USD", atype="CEDEAR", date="2026-08-01")

# ── Cash en las dos patas ─────────────────────────────────────────────────
pos(PADRE, "ARS",  1, 850_000, ccy="ARS", cash=1)
pos(SIB,   "USDT", 1,   2_300, ccy="USD", cash=1)

# ── El broker suelto, sin sibling (control) ───────────────────────────────
pos("Schwab", "MSFT", 15, 6_200, ccy="USD", date="2026-01-20")
pos("Schwab", "GOOGL", 20, 3_400, ccy="USD", date="2026-04-14")
pos("Schwab", "USD", 1, 1_500, ccy="USD", cash=1)

conn.commit()

print(f"uid={uid}  email={EMAIL}  pass={PASS}")
for r in c.execute("""SELECT broker, COUNT(*) n, SUM(is_cash) cash FROM positions
                      WHERE user_id=? GROUP BY broker ORDER BY broker""", (uid,)):
    print(f"  {r['broker']:<14} {r['n']} filas ({r['cash']} cash)")
dup = c.execute("""SELECT a.asset FROM positions a JOIN positions b
                   ON b.user_id=a.user_id AND b.asset=a.asset AND b.broker=a.broker||' · USD'
                   WHERE a.user_id=? AND a.is_cash=0 AND b.is_cash=0
                   GROUP BY a.asset""", (uid,)).fetchall()
print("  tickers en LAS DOS patas:", ", ".join(r["asset"] for r in dup) or "ninguno")
conn.close()
