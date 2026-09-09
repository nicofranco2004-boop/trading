"""Sonda de autorizacion — tramo 2 (endpoints main.py 9103-15039).

NO toca produccion: levanta la copia congelada /tmp/rendi-main sobre una SQLite
temporal y usa TestClient en proceso. Dos preguntas:

  A) IDOR: ¿un usuario logueado llega a los recursos con id de OTRO usuario?
  B) Escrituras por GET: ¿un GET escribe en la base? (get_effective_user solo
     exige permission='read_write' para metodos != GET/HEAD/OPTIONS)
"""
import os, sys, tempfile, json

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name
os.environ.setdefault("SECRET_KEY", "probe-only-not-a-real-secret")
sys.path.insert(0, "/tmp/rendi-main/backend")

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

c = TestClient(main.app)
db = main.get_db()


def mkuser(email):
    cur = db.execute(
        "INSERT INTO users (email, password_hash) VALUES (?,?)", (email, "x"))
    db.commit()
    return cur.lastrowid


victim = mkuser("victima@probe.test")
attacker = mkuser("atacante@probe.test")
advisor = mkuser("asesor@probe.test")

# Datos de la VICTIMA
db.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
           (victim, "BrokerV", "ARS"))
db.execute("""INSERT INTO plazos_fijos (user_id, banco, capital, moneda, tasa,
              rate_type, fecha_inicio, plazo_dias, fecha_vencimiento, renovacion_auto,
              modalidad) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
           (victim, "BancoV", 1000000.0, "ARS", 0.4, "TNA", "2026-01-01", 30,
            "2026-01-31", 0, "vencimiento"))
pf_id = db.execute("SELECT id FROM plazos_fijos WHERE user_id=?", (victim,)).fetchone()["id"]
db.execute("""INSERT INTO monthly_entries (user_id, year, month, broker, deposits,
              withdrawals, pnl_realized, pnl_unrealized, capital_inicio, capital_final)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",
           (victim, 2026, 1, "BrokerV", 500.0, 0, 0, 0, 0, 500.0))
me_id = db.execute("SELECT id FROM monthly_entries WHERE user_id=?", (victim,)).fetchone()["id"]
db.execute("""INSERT INTO operations (user_id, date, broker, asset, op_type, pnl_usd)
              VALUES (?,?,?,?,?,?)""", (victim, "2026-01-10", "BrokerV", "AL30", "Venta", 123.0))
op_id = db.execute("SELECT id FROM operations WHERE user_id=?", (victim,)).fetchone()["id"]
db.execute("""INSERT INTO futures_positions (user_id, broker, symbol, base_asset, side,
              quantity, entry_price, leverage, margin_usd, opened_at)
              VALUES (?,?,?,?,?,?,?,?,?,?)""",
           (victim, "BrokerV", "BTCUSDT", "BTC", "long", 1.0, 60000.0, 5, 1000.0, "2026-01-05"))
fu_id = db.execute("SELECT id FROM futures_positions WHERE user_id=?", (victim,)).fetchone()["id"]
db.commit()

tok_a = main.create_token(attacker)
tok_v = main.create_token(victim)
tok_ad = main.create_token(advisor)
H = lambda t: {"Authorization": f"Bearer {t}"}

print("=" * 72)
print("A) IDOR — el ATACANTE apunta a los ids de la VICTIMA")
print("=" * 72)
pf_body = {"banco": "HACKED", "capital": 1.0, "moneda": "ARS", "tasa": 0.1,
           "rate_type": "TNA", "fecha_inicio": "2026-01-01", "plazo_dias": 30,
           "renovacion_auto": False, "modalidad": "vencimiento"}
me_body = {"year": 2026, "month": 1, "broker": "BrokerV", "deposits": 99999.0,
           "withdrawals": 0, "pnl_realized": 0, "pnl_unrealized": 0,
           "capital_inicio": 0, "capital_final": 99999.0}
op_body = {"date": "2026-01-10", "broker": "BrokerV", "asset": "HACK",
           "op_type": "Venta", "pnl_usd": 99999.0}
fu_body = {"broker": "BrokerV", "symbol": "ETHUSDT", "side": "long", "quantity": 9.0,
           "entry_price": 1.0, "leverage": 1, "margin_usd": 1.0, "opened_at": "2026-01-05"}

probes = [
    ("PUT    /api/plazos-fijos/{pid}",   "put",    f"/api/plazos-fijos/{pf_id}", pf_body),
    ("DELETE /api/plazos-fijos/{pid}",   "delete", f"/api/plazos-fijos/{pf_id}", None),
    ("POST   /api/plazos-fijos/{pid}/renovar", "post", f"/api/plazos-fijos/{pf_id}/renovar", {}),
    ("POST   /api/plazos-fijos/{pid}/cobrar",  "post", f"/api/plazos-fijos/{pf_id}/cobrar", {}),
    ("PUT    /api/monthly/{eid}",        "put",    f"/api/monthly/{me_id}", me_body),
    ("DELETE /api/monthly/{eid}",        "delete", f"/api/monthly/{me_id}", None),
    ("PUT    /api/operations/{oid}",     "put",    f"/api/operations/{op_id}", op_body),
    ("DELETE /api/operations/{oid}",     "delete", f"/api/operations/{op_id}", None),
    ("PUT    /api/futures/{fid}",        "put",    f"/api/futures/{fu_id}", fu_body),
    ("DELETE /api/futures/{fid}",        "delete", f"/api/futures/{fu_id}", None),
    ("POST   /api/futures/{fid}/close",  "post",   f"/api/futures/{fu_id}/close",
     {"exit_price": 1.0, "commissions": 0}),
    ("POST   /api/brokers/{bid}/usd-sibling", "post", "/api/brokers/1/usd-sibling", {}),
]
for label, verb, url, body in probes:
    kw = {"headers": H(tok_a)}
    if body is not None:
        kw["json"] = body
    r = getattr(c, verb)(url, **kw)
    print(f"  {label:42s} -> {r.status_code}  {str(r.text)[:70]}")

print("\n  Estado de la VICTIMA despues de las 12 sondas:")
for t, q in (("plazos_fijos", "SELECT banco, capital, closed_at FROM plazos_fijos WHERE user_id=?"),
             ("monthly_entries", "SELECT deposits, capital_final FROM monthly_entries WHERE user_id=?"),
             ("operations", "SELECT asset, pnl_usd FROM operations WHERE user_id=?"),
             ("futures_positions", "SELECT symbol, quantity, closed_at FROM futures_positions WHERE user_id=?")):
    rows = [dict(r) for r in db.execute(q, (victim,)).fetchall()]
    print(f"    {t:18s} {rows}")

print("\n  Lecturas del atacante (no deben contener nada de la victima):")
for url in ("/api/plazos-fijos", "/api/operations", "/api/futures", "/api/monthly",
            "/api/movements", "/api/bonds/cashflow/skips"):
    r = c.get(url, headers=H(tok_a))
    n = len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else "?"
    print(f"    GET {url:34s} -> {r.status_code}  filas={n}")

print("\n" + "=" * 72)
print("B) ESCRITURAS POR GET — asesor con permission='read' (solo lectura)")
print("=" * 72)
db.execute("""INSERT INTO advisor_clients (advisor_uid, client_uid, link_type,
              permission, status) VALUES (?,?,?,?,?)""",
           (advisor, victim, "linked", "read", "active"))
db.commit()
Hc = dict(H(tok_ad)); Hc["X-Rendi-Client-Id"] = str(victim)

# el gate de escritura funciona para POST
r = c.post("/api/monthly", headers=Hc, json=me_body)
print(f"  POST /api/monthly (control, debe dar 403) -> {r.status_code} {r.text[:80]}")

antes = db.execute("SELECT COUNT(*) n FROM monthly_entries WHERE user_id=?", (victim,)).fetchone()["n"]
r = c.get("/api/monthly", headers=Hc)
db2 = main.get_db()
despues = db2.execute("SELECT COUNT(*) n FROM monthly_entries WHERE user_id=?", (victim,)).fetchone()["n"]
print(f"  GET  /api/monthly  -> {r.status_code}")
print(f"  monthly_entries del CLIENTE: antes={antes}  despues={despues}  "
      f"({'ESCRIBIO' if despues != antes else 'no escribio'})")
print("  filas del cliente ahora:",
      [dict(x) for x in db2.execute(
          "SELECT year, month, broker, capital_inicio, capital_final FROM monthly_entries "
          "WHERE user_id=? ORDER BY year, month", (victim,)).fetchall()])

print("\n" + "=" * 72)
print("C) X-Rendi-Client-Id sin vinculo / revocado / autoreferencia")
print("=" * 72)
Hx = dict(H(tok_a)); Hx["X-Rendi-Client-Id"] = str(victim)   # atacante SIN vinculo
r = c.get("/api/operations", headers=Hx)
print(f"  atacante sin vinculo  GET /api/operations -> {r.status_code} {r.text[:60]}")
r = c.get("/api/export/transactions.csv", headers=Hx)
print(f"  atacante sin vinculo  GET /api/export/transactions.csv -> {r.status_code} {r.text[:60]}")

db.execute("UPDATE advisor_clients SET status='revoked' WHERE advisor_uid=? AND client_uid=?",
           (advisor, victim))
db.commit()
r = c.get("/api/operations", headers=Hc)
print(f"  asesor REVOCADO       GET /api/operations -> {r.status_code} {r.text[:60]}")
db.execute("UPDATE advisor_clients SET status='active' WHERE advisor_uid=? AND client_uid=?",
           (advisor, victim))
db.commit()

for raw in (" %d " % victim, "+%d" % victim, "0%d" % victim, "abc", "-1", "0",
            str(2**63), "1e3"):
    hh = dict(H(tok_ad)); hh["X-Rendi-Client-Id"] = raw
    r = c.get("/api/operations", headers=hh)
    print(f"  header={raw!r:14s} -> {r.status_code} {r.text[:52]}")

print("\n  D) exports del CLIENTE via asesor SOLO-LECTURA (GET, gate de plan):")
for u in ("/api/export/operations.csv", "/api/export/positions.csv",
          "/api/export/transactions.csv", "/api/export/monthly.csv"):
    r = c.get(u, headers=Hc)
    print(f"    {u:34s} -> {r.status_code} bytes={len(r.content)}")

print("\n" + "=" * 72)
print("E) Broker NO validado en POST /api/operations y POST /api/futures")
print("=" * 72)
r = c.post("/api/operations", headers=H(attacker and tok_a), json={
    "date": "2026-02-01", "broker": "BrokerQueNoExiste", "asset": "XXX",
    "op_type": "Futuros", "pnl_usd": 5000.0, "kind": "futures"})
print(f"  POST /api/operations broker inexistente -> {r.status_code}")
r = c.post("/api/futures", headers=H(tok_a), json={
    "broker": "OtroBrokerFantasma", "symbol": "BTCUSDT", "side": "long",
    "quantity": 1.0, "entry_price": 1.0, "leverage": 1, "margin_usd": 1.0,
    "opened_at": "2026-02-01"})
print(f"  POST /api/futures    broker inexistente -> {r.status_code}")
r = c.post("/api/monthly", headers=H(tok_a), json={
    "year": 2026, "month": 2, "broker": "BrokerQueNoExiste", "deposits": 1.0,
    "withdrawals": 0, "pnl_realized": 0, "pnl_unrealized": 0,
    "capital_inicio": 0, "capital_final": 1.0})
print(f"  POST /api/monthly    broker inexistente -> {r.status_code} (control: SI valida)")
d3 = main.get_db()
print("  brokers reales del atacante:",
      [dict(x) for x in d3.execute("SELECT name FROM brokers WHERE user_id=?", (attacker,)).fetchall()])
print("  positions creadas:",
      [dict(x) for x in d3.execute(
          "SELECT broker, asset, is_cash, invested FROM positions WHERE user_id=?", (attacker,)).fetchall()])
print("  monthly_entries creadas:",
      [dict(x) for x in d3.execute(
          "SELECT broker, pnl_realized FROM monthly_entries WHERE user_id=?", (attacker,)).fetchall()])

print("\n" + "=" * 72)
print("F) 500 con el texto crudo de la excepcion (7 endpoints del tramo)")
print("=" * 72)
d4 = main.get_db()
d4.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
           (attacker, "BrokerA", "ARS")); d4.commit()
casos = [
    ("POST /api/bonds/cashflow", "/api/bonds/cashflow",
     {"broker": "BrokerA", "asset": "AL30", "flow_type": "coupon",
      "amount": 100.0, "date": "2020-13-45"}),
    ("POST /api/cash/flow", "/api/cash/flow",
     {"broker_name": "BrokerA", "direction": "deposit", "amount": 10.0,
      "tc_blue": 1000.0, "date": "2020-13-45"}),
    ("POST /api/brokers/reconcile-cash", "/api/brokers/reconcile-cash",
     {"broker_name": "BrokerA", "target_cash": 1e11, "tc_blue": 1000.0}),
    ("POST /api/conversions", "/api/conversions",
     {"from_broker": "BrokerA", "direction": "ars_to_usd", "ars_amount": 1.0,
      "usd_amount": 1.0, "tc": 1.0, "kind": "MEP", "date": "2020-13-45"}),
]
for label, url, body in casos:
    r = c.post(url, headers=H(tok_a), json=body)
    print(f"  {label:34s} -> {r.status_code}  {r.text[:170]}")
