"""MEDICION 5a — ¿el reseteo de contrasena invalida las sesiones vivas?

Replica LITERAL de backend/main.py:2681-2718 (create_token + el chequeo pca de
get_current_user) contra una SQLite con el MISMO esquema que produce
main.py:711-722 y la migracion de main.py:781-782.
No toca produccion: base en memoria, usuarios inventados.
"""
import sqlite3
from datetime import datetime, timedelta
from jose import jwt, JWTError

SECRET_KEY = "clave-de-laboratorio-no-es-la-de-nadie"
ALGORITHM = "HS256"
TOKEN_DAYS = 7

# --- copia literal de main.py:2681-2689 ---------------------------------
def create_token(user_id, pw_changed_at=None):
    payload = {"sub": str(user_id), "iat": datetime.utcnow(),
               "exp": datetime.utcnow() + timedelta(days=TOKEN_DAYS)}
    if pw_changed_at:
        payload["pca"] = pw_changed_at
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# --- copia literal de main.py:2704-2718 ---------------------------------
def token_sigue_valido(conn, token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        uid = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return False, "401 firma/exp"
    row = conn.execute("SELECT id, password_changed_at FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        return False, "401 user borrado"
    pca = payload.get("pca")
    if pca and row["password_changed_at"] and pca != row["password_changed_at"]:
        return False, "401 pca distinto"
    return True, "ACEPTADO"

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
# esquema NUEVO (main.py:711-722): password_changed_at con DEFAULT
conn.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT,
                password_hash TEXT, password_changed_at TEXT DEFAULT (datetime('now')))""")
# usuario NUEVO: pca poblado por el DEFAULT
conn.execute("INSERT INTO users (email, password_hash) VALUES ('nuevo@x','h')")
# usuario LEGACY: la migracion de main.py:782 es ALTER TABLE ... ADD COLUMN sin
# DEFAULT -> las filas preexistentes quedan en NULL. Lo reproducimos explicito.
conn.execute("INSERT INTO users (email, password_hash, password_changed_at) VALUES ('legacy@x','h',NULL)")
conn.commit()

for uid, etiqueta in ((1, "usuario NUEVO (pca poblado)"), (2, "usuario LEGACY (pca NULL)")):
    pca_login = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (uid,)).fetchone()[0]
    tok = create_token(uid, pca_login)   # main.py:3220, exactamente como en login()
    claims = jwt.get_unverified_claims(tok)
    print(f"\n--- {etiqueta} ---")
    print("  password_changed_at al loguear :", repr(pca_login))
    print("  claim 'pca' en el JWT emitido  :", repr(claims.get('pca')))
    ok, por = token_sigue_valido(conn, tok)
    print("  antes del reseteo              :", por)
    # main.py:3441 — reset-password bumpea password_changed_at
    conn.execute("UPDATE users SET password_hash='nuevo', password_changed_at=datetime('now','+1 second') WHERE id=?", (uid,))
    conn.commit()
    ok, por = token_sigue_valido(conn, tok)
    print("  DESPUES del reseteo            :", por, "<-- el token robado sigue sirviendo" if ok else "")
