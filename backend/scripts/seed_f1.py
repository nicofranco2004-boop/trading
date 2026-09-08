"""Fixture para probar A MANO los fixes de la tanda F1.

Arma una cuenta donde cada fix de F1 se puede verificar con pocos clicks, y deja
plantados los datos que hacen falta para que el caso se dispare.

Corre con:  cd backend && DB_PATH=trading-f1.db python3 scripts/seed_f1.py

Idempotente: reusa el usuario si existe (borrarlo le cambiaría el id y la sesión
abierta en el navegador quedaría apuntando a una cuenta que ya no está).
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DB_PATH", "trading-f1.db")

import main  # noqa: E402  — importarlo crea el esquema (init_db en el import)
from passlib.context import CryptContext  # noqa: E402

EMAIL = "f1@rendi.test"
PASS = "Rendi-F1-2026"
BASELINE = 50_000.0

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
conn = main.get_db()
c = conn.cursor()

old = c.execute("SELECT id FROM users WHERE email=?", (EMAIL,)).fetchone()
if old:
    uid = old["id"]
    for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
              "import_batches", "operations", "positions", "monthly_entries",
              "snapshots", "brokers", "config"):
        try:
            c.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
        except Exception:
            pass
    c.execute("UPDATE users SET password_hash=?, approved=1, tier='admin', "
              "email_verified=1 WHERE id=?", (pwd.hash(PASS), uid))
else:
    uid = c.execute(
        "INSERT INTO users (email, name, password_hash, approved, tier, email_verified) "
        "VALUES (?,?,?,1,'admin',1)", (EMAIL, "Prueba F1", pwd.hash(PASS))).lastrowid

# FX v2: es la versión que resuelve el TC por fecha (lo que prueba A-7).
c.execute("INSERT INTO config (user_id,key,value) VALUES (?,?,?)", (uid, "fx_version", "v2"))

# ── Serie de cotizaciones ────────────────────────────────────────────────────
# Sin serie no hay nada que probar: los fixes justamente eligen el TC por FECHA.
# Valores redondos y bien separados para que la diferencia se vea de un vistazo.
hoy = datetime.utcnow().date()
serie = [
    ("2024-03-15", 1000.0),                        # la fecha de la venta retro
    ("2025-01-10", 1200.0),
    (str(hoy - timedelta(days=30)), 1450.0),
    (str(hoy), 1500.0),                            # el dólar de HOY
]
for fecha, tc in serie:
    c.execute("INSERT OR REPLACE INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
              "VALUES (?,?,?,'seed-f1')", (fecha, tc * 0.95, tc))

# ── Brokers ──────────────────────────────────────────────────────────────────
padre = c.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,'Cocos','ARS')",
                  (uid,)).lastrowid
c.execute("INSERT INTO brokers (user_id,name,currency,parent_broker_id) "
          "VALUES (?,'Cocos · USD','USDT',?)", (uid, padre))

# ── A-4: la baseline declarada a mano ────────────────────────────────────────
# El mes MÁS VIEJO del broker, con capital_inicio distinto de cero. Es el dato
# que el recalc borraba en el primer import.
ANIO_VIEJO, MES_VIEJO = hoy.year - 1, 1
for broker in ("Cocos", "global"):
    c.execute("""INSERT INTO monthly_entries
                 (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                  pnl_unrealized,capital_inicio,capital_final,
                  manual_deposits,manual_withdrawals)
                 VALUES (?,?,?,?,2000,0,0,0,?,?,2000,0)""",
              (uid, ANIO_VIEJO, MES_VIEJO, broker, BASELINE, BASELINE + 2000))

# ── A-7 / A-8: algo para vender en pesos ─────────────────────────────────────
# 10 GGAL comprados a $1.000 = $10.000 invertidos. Vendiéndolos a $2.000 la
# ganancia es de $10.000 nominales; al TC del 15/03/2024 (1.000) son US$10.
c.execute("""INSERT INTO positions
             (user_id,broker,asset,is_cash,buy_price,quantity,invested,currency,
              entry_date,commissions,asset_type)
             VALUES (?,'Cocos','GGAL',0,1000,10,10000,'ARS','2024-01-10',0,NULL)""", (uid,))
# Cash en pesos, para que la cuenta no quede en descubierto al vender.
c.execute("""INSERT INTO positions (user_id,broker,asset,is_cash,invested,currency)
             VALUES (?,'Cocos','ARS',1,500000,'ARS')""", (uid,))
# Un lote en la pata dólar, para mirar la Cartera con las dos monedas.
c.execute("""INSERT INTO positions
             (user_id,broker,asset,is_cash,buy_price,quantity,invested,currency,
              entry_date,commissions,asset_type)
             VALUES (?,'Cocos · USD','MELI',0,20,25,500,'USD','2025-01-10',0,'CEDEAR')""",
          (uid,))

# ── Fecha futura: la fila que congelaba el calendario ────────────────────────
# Una operación mal fechada, del tipo que ya pasó en este repo con cupones.
c.execute("""INSERT INTO operations
             (user_id,date,broker,asset,op_type,pnl_usd,currency,fx_to_usd,notes)
             VALUES (?,'2030-06-15','Cocos','GGAL','Dividendo',1200,'USD',1.0,
                     'Fecha futura a propósito — fixture F1')""", (uid,))
c.execute("""INSERT INTO monthly_entries
             (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
              pnl_unrealized,capital_inicio,capital_final)
             VALUES (?,2030,6,'Cocos',0,0,1200,0,50000,51200)""", (uid,))

conn.commit()

print(f"""
Listo. Base: {os.environ['DB_PATH']}

  usuario     {EMAIL}
  contraseña  {PASS}
  user_id     {uid}

Sembrado:
  · baseline capital_inicio = US$ {BASELINE:,.0f} en {ANIO_VIEJO}-{MES_VIEJO:02d} (broker y global)
  · 10 GGAL en pesos (invertido $10.000) + cash $500.000 en Cocos
  · 25 MELI en Cocos · USD (US$500)
  · operación con fecha 2030-06-15 + su fila mensual
  · cotizaciones: 15/03/2024 = 1.000 · hoy = 1.500
""")
conn.close()
