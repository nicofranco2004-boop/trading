"""Sonda 2: el flujo CLAIM (invitacion a cuenta shadow) y que queda despues."""
import os, sys, tempfile, uuid, json
sys.path.insert(0, "/tmp/rendi-main/backend")
_t = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _t.close()
os.environ["DB_PATH"] = _t.name
os.environ.setdefault("SECRET_KEY", "probe-only-not-a-real-secret")
import main
from fastapi.testclient import TestClient
C = TestClient(main.app)
conn = main.get_db(); tag = uuid.uuid4().hex[:8]
adv = conn.execute("INSERT INTO users (email,password_hash,approved,tier,email_verified)"
                   " VALUES (?,?,1,'advisor',1)", (f"a-{tag}@rendi.test","x")).lastrowid
conn.commit()
def tok(u):
    r = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (u,)).fetchone()
    return main.create_token(u, r["password_changed_at"] if r else None)
H = {"Authorization": f"Bearer {tok(adv)}"}

r = C.post("/api/advisor/clients", headers=H, json={"label": "Juan P"})
cid = r.json()["client_uid"]
print("1) shadow creado:", r.json())

victima = f"victima-{tag}@gmail.com"
r = C.post(f"/api/advisor/clients/{cid}/invite", headers=H, json={"email": victima})
print("2) invite ->", r.status_code, r.text[:120])
row = conn.execute("SELECT token, expires_at, used_at, email FROM advisor_claim_tokens"
                   " WHERE user_id=?", (cid,)).fetchone()
print("   token len:", len(row["token"]), "| expira:", row["expires_at"], "| usado:", row["used_at"])
pv = C.get(f"/api/auth/claim/preview?token={row['token']}")
print("3) claim/preview (SIN auth) ->", pv.status_code, pv.text[:200])
cl = C.post("/api/auth/claim", json={"token": row["token"], "new_password": "unaClaveLarga1"})
C.cookies.clear()  # el claim auto-loguea y TestClient guarda la cookie del CLIENTE:
                   # sin esto los pasos 6-9 corren como el cliente, no como el asesor
                   # (get_current_user PREFIERE la cookie sobre el header Authorization)
print("4) claim ->", cl.status_code, str(cl.json())[:120])
link = conn.execute("SELECT link_type, permission, status FROM advisor_clients"
                    " WHERE advisor_uid=? AND client_uid=?", (adv, cid)).fetchone()
print("5) vinculo DESPUES del claim:", dict(link))
u = conn.execute("SELECT email, approved, managed_by FROM users WHERE id=?", (cid,)).fetchone()
print("   users row:", dict(u))
r = C.get("/api/positions", headers={**H, "X-Rendi-Client-Id": str(cid)})
print("6) el asesor sigue leyendo la cuenta reclamada ->", r.status_code)
r = C.post("/api/positions", headers={**H, "X-Rendi-Client-Id": str(cid)},
           json={"broker":"X","asset":"AAPL","buy_price":1,"quantity":1})
print("7) y ESCRIBIENDO en ella ->", r.status_code, r.text[:90])
# reuso del token
cl2 = C.post("/api/auth/claim", json={"token": row["token"], "new_password": "otraClaveLarga1"})
print("8) reuso del token de claim ->", cl2.status_code, cl2.text[:90])
# email sin validar formato
r = C.post(f"/api/advisor/clients/{cid}/invite", headers=H, json={"email": "no-es-un-email"})
print("9) invite con email invalido ->", r.status_code, r.text[:120])
