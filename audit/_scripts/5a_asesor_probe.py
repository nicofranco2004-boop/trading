"""Sonda del MODELO de permisos del rol asesor (audit 05_seguridad / 5a).

NO toca produccion: levanta main.py de la copia congelada /tmp/rendi-main
contra una base SQLite temporal y hace requests con TestClient.

Uso:  cd /tmp/rendi-main/backend && python3 <ruta>/5a_asesor_probe.py
"""
import os, sys, tempfile, uuid, json

BACKEND = "/tmp/rendi-main/backend"
sys.path.insert(0, BACKEND)
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ["DB_PATH"] = _tmp.name
os.environ.setdefault("SECRET_KEY", "probe-only-not-a-real-secret")
os.environ.setdefault("RENDI_ENV", "dev")

import main
from fastapi.testclient import TestClient

C = TestClient(main.app)
OUT = []
def say(*a):
    line = " ".join(str(x) for x in a); OUT.append(line); print(line)

conn = main.get_db()
tag = uuid.uuid4().hex[:8]

def mkuser(email, tier=None, approved=1):
    cur = conn.execute("INSERT INTO users (email, password_hash, approved, tier, email_verified)"
                       " VALUES (?,?,?,?,1)", (email, "x", approved, tier))
    return cur.lastrowid

adv   = mkuser(f"a-{tag}@rendi.test", tier="advisor")
adv2  = mkuser(f"a2-{tag}@rendi.test", tier="advisor")
cli   = mkuser(f"c-{tag}@rendi.test", approved=0)     # shadow managed
cli_ro= mkuser(f"cro-{tag}@rendi.test", approved=1)   # linked read-only
otro  = mkuser(f"x-{tag}@rendi.test")                 # sin vinculo
conn.execute("UPDATE users SET managed_by=? WHERE id=?", (adv, cli))
for (a, c, perm, st, lt) in [(adv, cli, "read_write", "active", "managed"),
                             (adv, cli_ro, "read", "active", "linked")]:
    conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type,"
                 " permission, status, label) VALUES (?,?,?,?,?,?)",
                 (a, c, lt, perm, st, f"Cli{c}"))
conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (cli, "Cocos", "ARS"))
conn.execute("INSERT INTO positions (user_id, broker, asset, quantity, buy_price, invested, is_cash)"
             " VALUES (?,?,?,?,?,?,0)", (cli, "Cocos", "GGAL", 100, 1000, 100000))
conn.execute("INSERT INTO ai_user_facts (user_id, content, source, is_active)"
             " VALUES (?,?,?,1)", (cli, "Cobro 3.500.000 ARS por mes y tengo un hijo", "chat"))
conn.commit()

def tok(uid):
    r = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (uid,)).fetchone()
    return main.create_token(uid, r["password_changed_at"] if r else None)

H  = {"Authorization": f"Bearer {tok(adv)}"}
H2 = {"Authorization": f"Bearer {tok(adv2)}"}

say("\n=== 1) resolver: header con vinculo INEXISTENTE / REVOCADO ===")
for label, cid, hh in [("sin vinculo (otro user)", otro, H),
                       ("cliente de OTRO asesor", cli, H2)]:
    r = C.get("/api/positions", headers={**hh, "X-Rendi-Client-Id": str(cid)})
    say(f"  GET /api/positions ctx={label}: {r.status_code} {str(r.text)[:60]}")

say("\n=== 2) permiso 'read' (linked v1): lectura OK / escritura 403 ===")
r = C.get("/api/positions", headers={**H, "X-Rendi-Client-Id": str(cli_ro)})
say(f"  GET  /api/positions      -> {r.status_code}")
r = C.post("/api/positions", headers={**H, "X-Rendi-Client-Id": str(cli_ro)},
           json={"broker": "Cocos", "asset": "AAPL", "buy_price": 1, "quantity": 1})
say(f"  POST /api/positions      -> {r.status_code} {str(r.text)[:80]}")

say("\n=== 3) que ALCANZA el contexto: datos NO-cartera del cliente ===")
for path in ["/api/ai/facts", "/api/wallbit/status", "/api/export/positions.csv"]:
    r = C.get(path, headers={**H, "X-Rendi-Client-Id": str(cli)})
    body = (r.text or "")[:150].replace("\n", " ")
    say(f"  GET {path:28} -> {r.status_code}  {body}")

say("\n=== 4) prefijos EXENTOS: el header se ignora (uid = asesor) ===")
r = C.get("/api/me/advisor", headers={**H, "X-Rendi-Client-Id": str(cli)})
say(f"  GET /api/me/advisor ctx=cliente -> {r.status_code} {str(r.text)[:120]}")

say("\n=== 5) informes: sobreviven la REVOCACION del cliente? ===")
r = C.post("/api/advisor/reports/generate", headers=H,
           json={"period_start": "2026-01-01", "period_end": "2026-06-30",
                 "client_uids": [cli]})
say(f"  POST /advisor/reports/generate -> {r.status_code}")
rep = r.json().get("reports", []) if r.status_code == 200 else []
token_pub = rep[0]["token"] if rep else None
say(f"  token publico len={len(token_pub) if token_pub else 0}")
# el CLIENTE revoca
C_cli = {"Authorization": f"Bearer {tok(cli)}"}
r = C.post(f"/api/me/advisor/{adv}/revoke", headers=C_cli)
say(f"  POST /api/me/advisor/{adv}/revoke (por el CLIENTE) -> {r.status_code} {str(r.text)[:60]}")
r = C.get("/api/positions", headers={**H, "X-Rendi-Client-Id": str(cli)})
say(f"  GET /api/positions ctx=cliente DESPUES de revocar -> {r.status_code}")
if token_pub:
    r = C.get(f"/api/reports/public/{token_pub}")
    say(f"  GET /api/reports/public/<token> DESPUES de revocar -> {r.status_code}"
        f"  (cartera del ex-cliente visible: {'value_end_usd' in r.text})")
r = C.get("/api/advisor/reports", headers=H)
n = len(r.json().get("reports", [])) if r.status_code == 200 else -1
say(f"  GET /advisor/reports (historial del asesor) DESPUES de revocar -> {r.status_code}, informes listados: {n}")
if r.status_code == 200 and n:
    say(f"      primera fila: {json.dumps(r.json()['reports'][0], ensure_ascii=False)[:220]}")

say("\n=== 6) alta sin consentimiento: crear cliente shadow ===")
r = C.post("/api/advisor/clients", headers=H, json={"label": "Persona real", "name": "Persona"})
say(f"  POST /advisor/clients -> {r.status_code} {str(r.text)[:160]}")

print("\n".join([]))
