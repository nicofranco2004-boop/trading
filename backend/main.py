from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, Field
from typing import Optional
import sqlite3, os, secrets, time, hashlib, hmac, json
from collections import defaultdict
import yfinance as yf
import requests
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import math

# ─── Config ──────────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    # In dev, generate a random key per process (tokens reset on restart — acceptable for dev)
    SECRET_KEY = secrets.token_hex(32)
    print("⚠️  WARNING: SECRET_KEY not set. Generated ephemeral key — tokens will reset on restart. Set SECRET_KEY env var in production.")

ALGORITHM = "HS256"
TOKEN_DAYS = 7  # reduced from 30

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "trading.db"))

# Registro abierto por defecto. Para cerrar (solo admin crea cuentas) setear ALLOW_REGISTRATION=false
ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "true").lower() == "true"

# Admin gating ─ el email del admin no se guarda en plano. Comparamos hash SHA-256 + HMAC.
# El email real es nicofranco2004@gmail.com pero solo se sabe por el hash. Para rotar admin,
# generar el hash nuevo con: python -c "import hashlib; print(hashlib.sha256(b'EMAIL').hexdigest())"
_ADMIN_EMAIL_HASH = "3dace40cc1cb114012ba2380fac26f81c0f97c19d13862f3b5e7a5e96448b74d"
# Override opcional via env var (también hash hex SHA-256)
ADMIN_EMAIL_HASH = os.environ.get("ADMIN_EMAIL_HASH", _ADMIN_EMAIL_HASH)


def _is_admin_email(email: str) -> bool:
    h = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
    # constant-time compare evita timing attacks de enumeración del email admin
    return hmac.compare_digest(h, ADMIN_EMAIL_HASH)

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

app = FastAPI(title="Rendi", docs_url=None, redoc_url=None)  # disable public docs in prod

# CORS — restrict to known origins; wildcard is OK for Bearer-auth but better to be explicit
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ─── Security headers middleware ──────────────────────────────────────────────

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


# ─── Rate limiting (in-memory, per key) ──────────────────────────────────────
# Per-process. Para multi-worker o multi-host conviene migrar a Redis.

_rate_store: dict = defaultdict(list)  # key → [timestamps]
_RATE_STORE_MAX_KEYS = 10_000  # cap para evitar memory bloat por IPs random

def _check_rate_limit(request: Request, max_calls: int, window_seconds: int, suffix: str = ""):
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}|{suffix}" if suffix else ip
    now = time.time()
    # Limpieza global periódica si crece demasiado
    if len(_rate_store) > _RATE_STORE_MAX_KEYS:
        cutoff = now - 3600
        for k in list(_rate_store.keys()):
            _rate_store[k] = [t for t in _rate_store[k] if t > cutoff]
            if not _rate_store[k]:
                del _rate_store[k]
    timestamps = _rate_store[key]
    _rate_store[key] = [t for t in timestamps if now - t < window_seconds]
    if len(_rate_store[key]) >= max_calls:
        raise HTTPException(429, "Demasiados intentos. Esperá un momento.")
    _rate_store[key].append(now)


# ─── DB helpers ──────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_cols(conn, table: str) -> set:
    # Table name is always hardcoded in callers — never user-supplied
    allowed = {'positions', 'monthly_entries', 'operations', 'config', 'brokers', 'users', 'snapshots', 'goals',
               'import_batches', 'import_raw_rows', 'import_normalized_tx', 'import_op_links'}
    if table not in allowed:
        return set()
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def init_db():
    conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            approved INTEGER NOT NULL DEFAULT 0,
            password_changed_at TEXT DEFAULT (datetime('now')),
            last_login_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS brokers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USDT',
            parent_broker_id INTEGER REFERENCES brokers(id) ON DELETE CASCADE,
            UNIQUE(user_id, name)
        );
    """)
    conn.commit()

    # brokers — agregar columna parent_broker_id si la tabla ya existía
    broker_cols = _table_cols(conn, 'brokers')
    if broker_cols and 'parent_broker_id' not in broker_cols:
        conn.execute("ALTER TABLE brokers ADD COLUMN parent_broker_id INTEGER REFERENCES brokers(id)")
        conn.commit()

    # users — agregar columnas nuevas si la tabla ya existía
    user_cols = _table_cols(conn, 'users')
    if user_cols and 'is_admin' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if user_cols and 'password_changed_at' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
    if user_cols and 'last_login_at' not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    if user_cols and 'approved' not in user_cols:
        # Migración: usuarios pre-existentes quedan aprobados (no romper acceso)
        conn.execute("ALTER TABLE users ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET approved=1")
    # Sincronizar is_admin + approved para usuarios con email admin
    rows = conn.execute("SELECT id, email FROM users").fetchall()
    for r in rows:
        if _is_admin_email(r["email"]):
            conn.execute("UPDATE users SET is_admin=1, approved=1 WHERE id=?", (r["id"],))
    conn.commit()

    # positions
    cols = _table_cols(conn, 'positions')
    if not cols:
        conn.executescript("""
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                broker TEXT NOT NULL,
                asset TEXT NOT NULL,
                is_cash INTEGER DEFAULT 0,
                buy_price REAL,
                quantity REAL,
                invested REAL,
                tc_compra REAL,
                price_override REAL,
                notes TEXT
            );
        """)
    elif 'user_id' not in cols:
        conn.executescript("""
            ALTER TABLE positions RENAME TO positions_old;
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                broker TEXT NOT NULL,
                asset TEXT NOT NULL,
                is_cash INTEGER DEFAULT 0,
                buy_price REAL,
                quantity REAL,
                invested REAL,
                tc_compra REAL,
                price_override REAL,
                notes TEXT
            );
            INSERT INTO positions
                SELECT id, 0, broker, asset, is_cash, buy_price, quantity, invested,
                       tc_compra, price_override, notes FROM positions_old;
            DROP TABLE positions_old;
        """)
    # Migración: columna entry_date para fecha de compra
    cols = _table_cols(conn, 'positions')
    if cols and 'entry_date' not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN entry_date TEXT")
    # Migración: columna commissions (fees al comprar — afecta el cost basis real)
    cols = _table_cols(conn, 'positions')
    if cols and 'commissions' not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN commissions REAL DEFAULT 0")
    conn.commit()

    # monthly_entries
    cols = _table_cols(conn, 'monthly_entries')
    if not cols:
        conn.executescript("""
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                broker TEXT NOT NULL,
                deposits REAL DEFAULT 0,
                withdrawals REAL DEFAULT 0,
                pnl_realized REAL DEFAULT 0,
                pnl_unrealized REAL DEFAULT 0,
                capital_inicio REAL DEFAULT 0,
                capital_final REAL DEFAULT 0,
                UNIQUE(user_id, year, month, broker)
            );
        """)
    elif 'user_id' not in cols:
        conn.executescript("""
            ALTER TABLE monthly_entries RENAME TO monthly_entries_old;
            CREATE TABLE monthly_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                broker TEXT NOT NULL,
                deposits REAL DEFAULT 0,
                withdrawals REAL DEFAULT 0,
                pnl_realized REAL DEFAULT 0,
                pnl_unrealized REAL DEFAULT 0,
                capital_inicio REAL DEFAULT 0,
                capital_final REAL DEFAULT 0,
                UNIQUE(user_id, year, month, broker)
            );
            INSERT INTO monthly_entries
                SELECT id, 0, year, month, broker, deposits, withdrawals,
                       pnl_realized, pnl_unrealized, capital_inicio, capital_final
                FROM monthly_entries_old;
            DROP TABLE monthly_entries_old;
        """)
    conn.commit()

    # operations
    cols = _table_cols(conn, 'operations')
    if not cols:
        conn.executescript("""
            CREATE TABLE operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                date TEXT NOT NULL,
                broker TEXT NOT NULL,
                asset TEXT NOT NULL,
                op_type TEXT,
                entry_price REAL,
                exit_price REAL,
                quantity REAL,
                pnl_usd REAL DEFAULT 0,
                pnl_pct REAL
            );
        """)
    elif 'user_id' not in cols:
        conn.executescript("""
            ALTER TABLE operations RENAME TO operations_old;
            CREATE TABLE operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                date TEXT NOT NULL,
                broker TEXT NOT NULL,
                asset TEXT NOT NULL,
                op_type TEXT,
                entry_price REAL,
                exit_price REAL,
                quantity REAL,
                pnl_usd REAL DEFAULT 0,
                pnl_pct REAL
            );
            INSERT INTO operations
                SELECT id, 0, date, broker, asset, op_type, entry_price, exit_price,
                       quantity, pnl_usd, pnl_pct FROM operations_old;
            DROP TABLE operations_old;
        """)
    cols = _table_cols(conn, 'operations')
    if cols and 'entry_date' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN entry_date TEXT")
    # Migración: columna commissions (fees al vender — reducen el net cash recibido)
    cols = _table_cols(conn, 'operations')
    if cols and 'commissions' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN commissions REAL DEFAULT 0")
    conn.commit()

    # config
    cols = _table_cols(conn, 'config')
    if not cols:
        conn.executescript("""
            CREATE TABLE config (
                key TEXT NOT NULL,
                value TEXT,
                user_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (key, user_id)
            );
        """)
    elif 'user_id' not in cols:
        conn.executescript("""
            ALTER TABLE config RENAME TO config_old;
            CREATE TABLE config (
                key TEXT NOT NULL,
                value TEXT,
                user_id INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (key, user_id)
            );
            INSERT INTO config SELECT key, value, 0 FROM config_old;
            DROP TABLE config_old;
        """)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            total_invested REAL NOT NULL,
            UNIQUE(user_id, date)
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_user_date ON snapshots(user_id, date);
    """)
    # Phase 6 — net_deposited (Σ deposits − Σ withdrawals al cierre del día) para
    # graficar Total Return (value − net_deposited). Compatible con snapshots viejos
    # que tienen net_deposited=0 (legacy: el frontend hace fallback a total_invested).
    snap_cols = _table_cols(conn, 'snapshots')
    if 'net_deposited' not in snap_cols:
        conn.execute("ALTER TABLE snapshots ADD COLUMN net_deposited REAL NOT NULL DEFAULT 0")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_usd REAL NOT NULL,
            target_date TEXT NOT NULL,
            expected_return_pct REAL NOT NULL DEFAULT 10,
            label TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_goals_user ON goals(user_id);
    """)

    # ─── CSV Importer ────────────────────────────────────────────────────────
    # import_batches: cada upload (en estado 'preview' es la sesión; al confirm
    # pasa a 'confirmed'; al revert pasa a 'reverted').
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS import_batches (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            broker TEXT NOT NULL,
            parser_format TEXT NOT NULL,
            file_name TEXT,
            file_hash TEXT NOT NULL,
            total_rows INTEGER NOT NULL DEFAULT 0,
            valid_rows INTEGER NOT NULL DEFAULT 0,
            invalid_rows INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            confirmed_at TEXT,
            reverted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_import_batches_user
            ON import_batches(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_import_batches_hash
            ON import_batches(user_id, file_hash, status);

        CREATE TABLE IF NOT EXISTS import_raw_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            row_index INTEGER NOT NULL,
            raw_json TEXT NOT NULL,
            status TEXT NOT NULL,
            errors_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_import_raw_rows_batch ON import_raw_rows(batch_id);

        CREATE TABLE IF NOT EXISTS import_normalized_tx (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            raw_row_id INTEGER NOT NULL REFERENCES import_raw_rows(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            broker TEXT NOT NULL DEFAULT '',
            operation_type TEXT NOT NULL,
            asset_symbol TEXT,
            asset_name TEXT,
            asset_type TEXT,
            quantity REAL,
            unit_price REAL,
            gross_amount REAL,
            fees REAL DEFAULT 0,
            taxes REAL DEFAULT 0,
            currency TEXT,
            settlement_currency TEXT,
            notes TEXT,
            created_position_id INTEGER,
            created_operation_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_import_norm_batch
            ON import_normalized_tx(batch_id);

        -- Mapping auxiliar: una fila puede crear múltiples positions/operations
        -- (ej.: SELL FIFO genera N rows en operations). Acá guardamos todos los
        -- IDs para poder revertir.
        CREATE TABLE IF NOT EXISTS import_op_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            raw_row_id INTEGER REFERENCES import_raw_rows(id) ON DELETE CASCADE,
            position_id INTEGER,
            operation_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_import_op_links_batch ON import_op_links(batch_id);
    """)

    # Migración: columna broker en import_normalized_tx (agregada después de la
    # versión inicial de las tablas).
    norm_cols = _table_cols(conn, 'import_normalized_tx')
    if norm_cols and 'broker' not in norm_cols:
        conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN broker TEXT NOT NULL DEFAULT ''")

    # Migración: route_by_currency en import_batches. Cuando es 1 y el broker
    # del batch es ARS, las filas USD/USDT se ruteán al sub-broker USD al persistir.
    batch_cols = _table_cols(conn, 'import_batches')
    if batch_cols and 'route_by_currency' not in batch_cols:
        conn.execute("ALTER TABLE import_batches ADD COLUMN route_by_currency INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()


init_db()


# ─── Auth ────────────────────────────────────────────────────────────────────

def create_token(user_id: int, pw_changed_at: Optional[str] = None) -> str:
    payload = {
        "sub": str(user_id),
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=TOKEN_DAYS),
    }
    if pw_changed_at:
        payload["pca"] = pw_changed_at  # password_changed_at — invalida tokens viejos al cambiar pass
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        uid = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Token inválido")
    # Verificar que el user existe y que el token no quedó invalidado por cambio de pass
    conn = get_db()
    row = conn.execute(
        "SELECT id, password_changed_at FROM users WHERE id=?", (uid,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Token inválido")
    pca = payload.get("pca")
    if pca and row["password_changed_at"] and pca != row["password_changed_at"]:
        raise HTTPException(401, "Token expirado por cambio de contraseña")
    return uid


def get_admin_user(uid: int = Depends(get_current_user)) -> int:
    conn = get_db()
    row = conn.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row or not row["is_admin"]:
        raise HTTPException(403, "Acceso restringido")
    return uid


ARS_BROKER_NAMES = {'cocos', 'iol', 'bull', 'balanz', 'lemon', 'naranja', 'pppi', 'invertironline'}

MAX_STR = 100   # max length for names/assets
MAX_NOTES = 500


_EMAIL_RE = __import__('re').compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


class RegisterIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=10, max_length=128)
    name: Optional[str] = Field(None, max_length=MAX_STR)

    @field_validator('email')
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError('Email inválido')
        return v

    @field_validator('password')
    @classmethod
    def password_strength(cls, v):
        if len(v) < 10:
            raise ValueError('La contraseña debe tener al menos 10 caracteres')
        return v


class LoginIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)


@app.post("/api/auth/register")
def register(data: RegisterIn, request: Request):
    is_admin_signup = _is_admin_email(data.email)
    # Si registro está cerrado, solo se permite el registro del admin (idempotente).
    if not ALLOW_REGISTRATION and not is_admin_signup:
        raise HTTPException(403, "Registro deshabilitado")
    _check_rate_limit(request, max_calls=5, window_seconds=300, suffix="register")  # 5 / 5min por IP

    conn = get_db()
    try:
        h = pwd_ctx.hash(data.password)
        # admin se auto-aprueba; resto queda pending hasta que admin apruebe
        approved = 1 if is_admin_signup else 0
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash, is_admin, approved) VALUES (?,?,?,?,?)",
            (data.email, data.name, h, 1 if is_admin_signup else 0, approved),
        )
        uid = cur.lastrowid

        # SOLO el admin hereda los datos legacy con user_id=0 (datos iniciales del owner).
        # Esto cierra el agujero: si la DB tiene datos huérfanos, solo el dueño los puede absorber.
        if is_admin_signup:
            for table in ['positions', 'monthly_entries', 'operations', 'config']:
                conn.execute(f"UPDATE {table} SET user_id=? WHERE user_id=0", (uid,))
            existing_brokers = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT broker FROM positions WHERE user_id=?", (uid,)
                ).fetchall()
            ]
            for bname in existing_brokers:
                currency = 'ARS' if bname.lower() in ARS_BROKER_NAMES else 'USDT'
                conn.execute(
                    "INSERT OR IGNORE INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                    (uid, bname, currency),
                )

        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_mep', '1415', ?)", (uid,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_blue', '1415', ?)", (uid,))

        conn.commit()
        pca_row = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        # Si no está aprobado, no devolvemos token: el usuario debe esperar aprobación
        if not approved:
            return {
                "pending": True,
                "message": "Cuenta creada. Esperando aprobación del administrador.",
            }
        return {
            "token": create_token(uid, pca_row["password_changed_at"] if pca_row else None),
            "name": data.name or data.email,
            "is_admin": bool(is_admin_signup),
        }
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Email ya registrado")


@app.post("/api/auth/login")
def login(data: LoginIn, request: Request):
    email_norm = data.email.strip().lower()
    # Rate limit por IP y por email (mitiga brute-force distribuido sobre una cuenta puntual)
    _check_rate_limit(request, max_calls=10, window_seconds=60, suffix="login_ip")
    _check_rate_limit(request, max_calls=10, window_seconds=60, suffix=f"login_email:{email_norm}")
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email_norm,)).fetchone()
    if not row:
        conn.close()
        pwd_ctx.dummy_verify()
        raise HTTPException(401, "Credenciales inválidas")
    if not pwd_ctx.verify(data.password, row["password_hash"]):
        conn.close()
        raise HTTPException(401, "Credenciales inválidas")
    if not row["approved"]:
        conn.close()
        raise HTTPException(403, "Cuenta pendiente de aprobación por el administrador")
    # Update last_login
    try:
        conn.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (row["id"],))
        conn.commit()
    except Exception:
        pass
    conn.close()
    return {
        "token": create_token(row["id"], row["password_changed_at"]),
        "name": row["name"] or row["email"],
        "is_admin": bool(row["is_admin"]),
    }


@app.post("/api/auth/logout")
def logout(uid: int = Depends(get_current_user)):
    return {"ok": True}


@app.get("/api/auth/me")
def me(uid: int = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, name, is_admin, created_at, last_login_at FROM users WHERE id=?", (uid,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    d = dict(row)
    d["is_admin"] = bool(d["is_admin"])
    return d


@app.post("/api/auth/change-password")
def change_password(data: ChangePasswordIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
    if not row or not pwd_ctx.verify(data.current_password, row["password_hash"]):
        conn.close()
        raise HTTPException(401, "Contraseña actual incorrecta")
    new_hash = pwd_ctx.hash(data.new_password)
    conn.execute(
        "UPDATE users SET password_hash=?, password_changed_at=datetime('now') WHERE id=?",
        (new_hash, uid),
    )
    conn.commit()
    pca = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (uid,)).fetchone()["password_changed_at"]
    conn.close()
    # Devolvemos token nuevo con el pca actualizado para que la sesión actual siga válida
    return {"ok": True, "token": create_token(uid, pca)}


# ─── Brokers ─────────────────────────────────────────────────────────────────

class BrokerIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_STR)
    currency: str = Field('USDT')
    parent_broker_id: Optional[int] = None

    @field_validator('currency')
    @classmethod
    def valid_currency(cls, v):
        if v not in ('USDT', 'ARS'):
            raise ValueError('currency debe ser USDT o ARS')
        return v

    @field_validator('name')
    @classmethod
    def strip_name(cls, v):
        return v.strip()


@app.get("/api/brokers")
def get_brokers(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM brokers WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/brokers")
def create_broker(data: BrokerIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    # Validar parent_broker_id (si se pasa, debe pertenecer al user)
    if data.parent_broker_id is not None:
        parent = conn.execute(
            "SELECT id FROM brokers WHERE id=? AND user_id=?",
            (data.parent_broker_id, uid),
        ).fetchone()
        if not parent:
            conn.close()
            raise HTTPException(400, "Broker padre inválido")
    try:
        cur = conn.execute(
            "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
            (uid, data.name, data.currency, data.parent_broker_id),
        )
        conn.commit()
        # Safe: lastrowid always belongs to this user (just inserted)
        row = conn.execute("SELECT * FROM brokers WHERE id=? AND user_id=?", (cur.lastrowid, uid)).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Ya existe un broker con ese nombre")


@app.put("/api/brokers/{bid}")
def update_broker(bid: int, data: BrokerIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        "UPDATE brokers SET name=?, currency=? WHERE id=? AND user_id=?",
        (data.name, data.currency, bid, uid),
    )
    conn.commit()
    # FIXED: include user_id in SELECT to prevent IDOR
    row = conn.execute("SELECT * FROM brokers WHERE id=? AND user_id=?", (bid, uid)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return dict(row)


@app.delete("/api/brokers/{bid}")
def delete_broker(bid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM brokers WHERE id=? AND user_id=?", (bid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Config ──────────────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    tc_mep: Optional[float] = Field(None, ge=0, le=1_000_000)
    tc_blue: Optional[float] = Field(None, ge=0, le=1_000_000)


@app.get("/api/config")
def get_config(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    try:
        cfg = {r["key"]: float(r["value"]) for r in rows}
    except (ValueError, TypeError):
        cfg = {}
    cfg.setdefault("tc_mep", 1415)
    cfg.setdefault("tc_blue", 1415)
    return cfg


@app.put("/api/config")
def update_config(data: ConfigUpdate, uid: int = Depends(get_current_user)):
    conn = get_db()
    if data.tc_mep is not None:
        conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_mep', ?, ?)", (str(data.tc_mep), uid))
    if data.tc_blue is not None:
        conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_blue', ?, ?)", (str(data.tc_blue), uid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Dólar (auto-update blue/MEP) ────────────────────────────────────────────

_dolar_cache = {"data": None, "ts": 0.0}
DOLAR_TTL = 300  # 5 minutes


def _fetch_dolar(casa: str):
    try:
        r = requests.get(f"https://dolarapi.com/v1/dolares/{casa}", timeout=5)
        if r.status_code != 200:
            return None
        j = r.json()
        compra = float(j.get("compra") or 0) or None
        venta = float(j.get("venta") or 0) or None
        if not venta:
            return None
        return {"compra": compra, "venta": venta, "updated_at": j.get("fechaActualizacion")}
    except Exception:
        return None


@app.get("/api/dolar")
def get_dolar(uid: int = Depends(get_current_user)):
    now = time.time()
    if _dolar_cache["data"] and now - _dolar_cache["ts"] < DOLAR_TTL:
        return _dolar_cache["data"]
    blue = _fetch_dolar("blue")
    mep = _fetch_dolar("bolsa")
    data = {"blue": blue, "mep": mep, "fetched_at": datetime.utcnow().isoformat() + "Z"}
    if blue or mep:
        _dolar_cache["data"] = data
        _dolar_cache["ts"] = now
    return data


# ─── Portfolio snapshots (daily) ─────────────────────────────────────────────

class SnapshotIn(BaseModel):
    total_value: float = Field(..., ge=0)
    total_invested: float = Field(..., ge=0)        # cost basis (legacy)
    net_deposited: float = Field(0, ge=0)           # Phase 6 — Σ deposits − Σ withdrawals (USD)


@app.post("/api/snapshots")
def post_snapshot(data: SnapshotIn, uid: int = Depends(get_current_user)):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    conn = get_db()
    conn.execute(
        """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, date) DO UPDATE SET
             total_value=excluded.total_value,
             total_invested=excluded.total_invested,
             net_deposited=excluded.net_deposited""",
        (uid, today, data.total_value, data.total_invested, data.net_deposited),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "date": today}


@app.get("/api/snapshots")
def get_snapshots(days: int = 30, uid: int = Depends(get_current_user)):
    # Phase 6 — cap subido de 365 → 3650 (10 años) para soportar histórico multi-año.
    days = max(1, min(days, 3650))
    conn = get_db()
    rows = conn.execute(
        "SELECT date, total_value, total_invested, net_deposited FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT ?",
        (uid, days),
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


# ─── Benchmarks (inflación AR, S&P 500, dólar blue histórico) ────────────────

_bench_cache = {"data": None, "ts": 0.0}
BENCH_TTL = 3600  # 1 hour


def _fetch_inflation_ar():
    """Monthly inflation % from argentinadatos.com. Returns dict {YYYY-MM: pct}."""
    try:
        r = requests.get("https://api.argentinadatos.com/v1/finanzas/indices/inflacion", timeout=8)
        if r.status_code != 200:
            return {}
        out = {}
        for item in r.json():
            fecha = item.get("fecha", "")
            val = item.get("valor")
            if fecha and val is not None:
                out[fecha[:7]] = float(val)
        return out
    except Exception:
        return {}


def _fetch_sp500_monthly():
    """S&P 500 month-end close from yfinance. Returns dict {YYYY-MM: close}."""
    try:
        data = yf.Ticker("^GSPC").history(period="5y", interval="1mo")
        if data.empty:
            return {}
        out = {}
        for idx, row in data.iterrows():
            key = idx.strftime("%Y-%m")
            close = float(row["Close"]) if not math.isnan(row["Close"]) else None
            if close:
                out[key] = close
        return out
    except Exception:
        return {}


def _fetch_dolar_blue_monthly():
    """Monthly dolar blue venta from argentinadatos.com. Returns dict {YYYY-MM: venta} (last of month)."""
    try:
        r = requests.get("https://api.argentinadatos.com/v1/cotizaciones/dolares/blue", timeout=8)
        if r.status_code != 200:
            return {}
        out = {}
        for item in r.json():
            fecha = item.get("fecha", "")
            venta = item.get("venta")
            if fecha and venta is not None:
                out[fecha[:7]] = float(venta)  # last entry of month wins (dict overwrite)
        return out
    except Exception:
        return {}


@app.get("/api/benchmarks")
def get_benchmarks(uid: int = Depends(get_current_user)):
    now = time.time()
    if _bench_cache["data"] and now - _bench_cache["ts"] < BENCH_TTL:
        return _bench_cache["data"]
    data = {
        "inflation_ar": _fetch_inflation_ar(),
        "sp500": _fetch_sp500_monthly(),
        "dolar_blue": _fetch_dolar_blue_monthly(),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }
    _bench_cache["data"] = data
    _bench_cache["ts"] = now
    return data


# ─── Prices ──────────────────────────────────────────────────────────────────

CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOGE', 'TRX', 'DOT',
    'MATIC', 'POL', 'LINK', 'LTC', 'BCH', 'NEAR', 'UNI', 'ATOM', 'XLM', 'ETC',
    'APT', 'ARB', 'OP', 'AAVE', 'MKR', 'SNX', 'CRV', 'COMP', 'SUSHI', 'YFI',
    '1INCH', 'BAL', 'DYDX', 'GMX', 'BLUR', 'GRT', 'LRC', 'ZRX', 'BAT', 'REN',
    'ALGO', 'VET', 'EGLD', 'FTM', 'FLOW', 'HBAR', 'THETA', 'XTZ', 'EOS', 'WAVES',
    'ZIL', 'NEO', 'QTUM', 'ICX', 'ONT', 'IOTA', 'ZEC', 'DASH', 'XMR', 'KAVA',
    'SAND', 'MANA', 'AXS', 'ENJ', 'IMX', 'CHZ', 'GALA', 'ILV',
    'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'DEGEN',
    'SUI', 'SEI', 'TIA', 'INJ', 'JTO', 'PYTH', 'STRK', 'WLD', 'MANTA', 'ALT',
    'ORDI', 'RUNE', 'FIL', 'STX', 'CORE', 'CFX', 'ID', 'ARKM', 'CYBER',
    'RDNT', 'APE', 'LDO', 'RPL', 'FXS', 'CVX', 'FRAX', 'PENDLE', 'SSV',
    'WBTC', 'STETH',
}

CRYPTO_YF = {sym: f"{sym}-USD" for sym in CRYPTO_SYMBOLS}

# Allowed symbol characters — only alphanumeric + dot (for .BA suffix)
import re
_SYMBOL_RE = re.compile(r'^[A-Z0-9]{1,10}(\.BA)?$')

MAX_SYMBOLS = 60  # hard cap on number of symbols per request


def _fetch_one(yf_ticker: str):
    try:
        # period="1mo" es más confiable que "5d" — cubre findes y feriados
        hist = yf.Ticker(yf_ticker).history(period="1mo")
        if hist.empty:
            return None
        val = float(hist["Close"].dropna().iloc[-1])
        return val if not math.isnan(val) and val > 0 else None
    except Exception:
        return None


@app.get("/api/prices")
def get_prices(symbols: str, uid: int = Depends(get_current_user)):
    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    # Validate each symbol format
    sym_list = [s for s in raw if _SYMBOL_RE.match(s)]

    # Hard cap to prevent resource abuse
    sym_list = sym_list[:MAX_SYMBOLS]

    if not sym_list:
        return {}

    sym_to_yf = {}
    for sym in sym_list:
        sym_to_yf[sym] = CRYPTO_YF[sym] if sym in CRYPTO_YF else sym

    yf_tickers = list(set(sym_to_yf.values()))
    result = {sym: None for sym in sym_list}

    try:
        tickers_str = " ".join(yf_tickers)
        # period="1mo" es más confiable que "5d" — cubre findes y feriados
        data = yf.download(tickers_str, period="1mo", progress=False, auto_adjust=True)

        if not data.empty:
            close = data.get("Close") if hasattr(data, 'get') else (data["Close"] if "Close" in data.columns else None)

            if close is not None and not (hasattr(close, 'empty') and close.empty):
                if hasattr(close, 'dropna'):
                    last = close.dropna(how='all').iloc[-1] if len(close.dropna(how='all')) > 0 else None
                else:
                    last = None

                if last is not None:
                    for sym, yf_t in sym_to_yf.items():
                        try:
                            if hasattr(last, '__getitem__'):
                                val = float(last[yf_t]) if yf_t in last.index else float(last)
                            else:
                                val = float(last)
                            if not math.isnan(val) and val > 0:
                                result[sym] = val
                        except Exception:
                            pass
    except Exception:
        pass

    for sym in [s for s in sym_list if result[s] is None]:
        yf_t = sym_to_yf[sym]
        price = _fetch_one(yf_t)
        if price is None and not sym.endswith('.BA') and sym not in CRYPTO_YF:
            price = _fetch_one(f"{sym}-USD")
        result[sym] = price

    return result


# ─── Positions ───────────────────────────────────────────────────────────────

class PositionIn(BaseModel):
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=20)
    is_cash: bool = False
    buy_price: Optional[float] = Field(None, ge=0)
    quantity: Optional[float] = Field(None, ge=0)
    invested: Optional[float] = Field(None, ge=0)
    tc_compra: Optional[float] = Field(None, gt=0)  # > 0 para evitar div-by-zero silencioso
    price_override: Optional[float] = Field(None, ge=0)
    commissions: Optional[float] = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES)
    entry_date: Optional[str] = Field(None, max_length=10)

    @field_validator('entry_date')
    @classmethod
    def valid_entry_date(cls, v):
        if v is None or v == '':
            return None
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v

    @field_validator('asset')
    @classmethod
    def clean_asset(cls, v):
        return v.strip().upper()

    @field_validator('broker')
    @classmethod
    def clean_broker(cls, v):
        return v.strip()


@app.get("/api/positions")
def get_positions(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM positions WHERE user_id=?
           ORDER BY broker ASC, asset ASC,
                    COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/positions")
def create_position(p: PositionIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    try:
        with conn:  # transacción atómica: insert + cash debit
            # Auto-fill entry_date a hoy si no viene del cliente
            entry_date = p.entry_date or datetime.utcnow().strftime("%Y-%m-%d")
            cur = conn.execute(
                """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
                   invested, tc_compra, price_override, notes, entry_date, commissions)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
                 p.invested, p.tc_compra, p.price_override, p.notes, entry_date, p.commissions or 0),
            )
            new_id = cur.lastrowid

            # Phase 2 — descontar del cash del broker (moneda nativa).
            # Costo real = invested + commissions (las comisiones se debitan del cash).
            if not p.is_cash:
                cost = p.invested if p.invested is not None else \
                       (p.buy_price or 0) * (p.quantity or 0)
                cost = (cost or 0) + (p.commissions or 0)
                if cost and cost > 0:
                    _adjust_broker_cash(conn, uid, p.broker, -cost)

            row = conn.execute(
                "SELECT * FROM positions WHERE id=? AND user_id=?", (new_id, uid)
            ).fetchone()
        conn.close()
        return dict(row)
    except HTTPException:
        conn.close()
        raise
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error al crear posición: {ex}")


@app.put("/api/positions/{pid}")
def update_position(pid: int, p: PositionIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        """UPDATE positions SET broker=?, asset=?, is_cash=?, buy_price=?, quantity=?,
           invested=?, tc_compra=?, price_override=?, notes=?, commissions=?,
           entry_date=COALESCE(?, entry_date)
           WHERE id=? AND user_id=?""",
        (p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
         p.invested, p.tc_compra, p.price_override, p.notes, p.commissions or 0,
         p.entry_date, pid, uid),
    )
    conn.commit()
    # FIXED: include user_id in SELECT to prevent IDOR data leak
    row = conn.execute("SELECT * FROM positions WHERE id=? AND user_id=?", (pid, uid)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@app.delete("/api/positions/{pid}")
def delete_position(pid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (pid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Cash deposit / withdraw ─────────────────────────────────────────────────

class CashFlowIn(BaseModel):
    broker_name: str = Field(..., min_length=1, max_length=MAX_STR)
    direction: str = Field(...)   # "deposit" | "withdraw"
    amount: float = Field(..., gt=0, le=1e12)
    tc_blue: float = Field(1415, gt=0, le=1_000_000)  # needed to convert ARS→USD for global entry

    @field_validator('direction')
    @classmethod
    def valid_direction(cls, v):
        if v not in ('deposit', 'withdraw'):
            raise ValueError('direction debe ser deposit o withdraw')
        return v

    @field_validator('broker_name')
    @classmethod
    def strip_name(cls, v):
        return v.strip()


def _repair_monthly_chain(conn, uid: int, broker: str) -> None:
    """Phase 8 — repara la cadena de monthly_entries para (uid, broker).

    Invariantes garantizados después de la llamada:
      • capital_inicio[N+1] = capital_final[N]  (chain integrity)
      • Meses cerrados (no el último): pnl_unrealized = 0 y
        capital_final = capital_inicio + deposits − withdrawals + pnl_realized
      • El último mes (en curso) conserva su pnl_unrealized y capital_final
        — son live, los maneja sync-unrealized. Si su capital_inicio drifta del
        previo, capital_final se recalcula con la fórmula completa.

    Idempotente. El caller es responsable del commit (funciona dentro o fuera
    de `with conn:`).
    """
    rows = conn.execute(
        """SELECT id, year, month, capital_inicio, capital_final, deposits, withdrawals,
                  pnl_realized, pnl_unrealized
           FROM monthly_entries
           WHERE user_id=? AND broker=?
           ORDER BY year ASC, month ASC""",
        (uid, broker),
    ).fetchall()
    if not rows:
        return

    EPS = 0.01
    prev_cap_final = None

    for i, row in enumerate(rows):
        is_last = (i == len(rows) - 1)
        cur_cap_inicio = row['capital_inicio'] or 0
        cur_cap_final  = row['capital_final'] or 0
        cur_pnl_unr    = row['pnl_unrealized'] or 0
        deposits       = row['deposits'] or 0
        withdrawals    = row['withdrawals'] or 0
        pnl_realized   = row['pnl_realized'] or 0

        # 1. Chain integrity: capital_inicio = capital_final del mes anterior
        new_cap_inicio = cur_cap_inicio
        if prev_cap_final is not None and abs(cur_cap_inicio - prev_cap_final) > EPS:
            new_cap_inicio = prev_cap_final

        if not is_last:
            # Closed month: aplicar fórmula canónica y zero pnl_unrealized
            new_cap_final = round(
                new_cap_inicio + deposits - withdrawals + pnl_realized, 4
            )
            needs_update = (
                abs(cur_cap_inicio - new_cap_inicio) > EPS
                or abs(cur_cap_final - new_cap_final) > EPS
                or cur_pnl_unr != 0
            )
            if needs_update:
                conn.execute(
                    """UPDATE monthly_entries
                       SET capital_inicio = ?, capital_final = ?, pnl_unrealized = 0
                       WHERE id = ?""",
                    (new_cap_inicio, new_cap_final, row['id']),
                )
            prev_cap_final = new_cap_final
        else:
            # Open (current) month: respetar pnl_unrealized; recalcular cap_final
            # solo si cap_inicio drifta del mes anterior.
            if abs(cur_cap_inicio - new_cap_inicio) > EPS:
                new_cap_final = round(
                    new_cap_inicio + deposits - withdrawals + pnl_realized + cur_pnl_unr, 4
                )
                conn.execute(
                    "UPDATE monthly_entries SET capital_inicio = ?, capital_final = ? WHERE id = ?",
                    (new_cap_inicio, new_cap_final, row['id']),
                )


def _adjust_broker_cash(conn, uid: int, broker: str, delta: float) -> None:
    """Ajusta el saldo cash del broker en `delta` unidades (moneda nativa del broker).
    Phase 2 — ledger automático en buy/sell.

    Convención:
    - Si el broker tiene una posición cash (is_cash=1), se actualiza su `invested`.
    - Si NO hay cash position, no-op. Es opt-in: el usuario decide trackear cash
      creando un depósito vía /api/cash/flow. Así no aparecen cash positions
      "fantasma" para quien no quiere trackear.
    - Se permiten balances negativos — señal visible de overdraft / margen.
    """
    if delta == 0:
        return
    cash = conn.execute(
        "SELECT id, invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
        (uid, broker),
    ).fetchone()
    if not cash:
        return  # opt-in: solo si ya hay cash trackeado
    new_invested = (cash['invested'] or 0) + delta
    conn.execute(
        "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
        (new_invested, cash['id'], uid),
    )


def _update_monthly_pnl_realized(conn, uid: int, broker: str, year: int, month: int,
                                  pnl_amount: float) -> None:
    """Suma pnl_amount a pnl_realized del mes (año/mes exacto) y recalcula capital_final.
    Si la fila no existe la crea con capital_inicio = capital_final del mes anterior."""
    row = conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
        (uid, broker, year, month),
    ).fetchone()

    if row:
        new_pnl_realized = round((row['pnl_realized'] or 0) + pnl_amount, 4)
        new_cap_final = round(
            (row['capital_inicio'] or 0)
            + (row['deposits'] or 0)
            - (row['withdrawals'] or 0)
            + new_pnl_realized
            + (row['pnl_unrealized'] or 0),
            4,
        )
        conn.execute(
            """UPDATE monthly_entries
               SET pnl_realized = ?, capital_final = ?
               WHERE user_id=? AND broker=? AND year=? AND month=?""",
            (new_pnl_realized, new_cap_final, uid, broker, year, month),
        )
    else:
        prev = conn.execute(
            """SELECT capital_final FROM monthly_entries
               WHERE user_id=? AND broker=? ORDER BY year DESC, month DESC LIMIT 1""",
            (uid, broker),
        ).fetchone()
        cap_inicio = float(prev['capital_final']) if prev else 0.0
        pnl = round(pnl_amount, 4)
        cap_final = round(cap_inicio + pnl, 4)
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, deposits, withdrawals,
                pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?,?,?,?,0,0,?,0,?,?)""",
            (uid, year, month, broker, pnl, cap_inicio, cap_final),
        )


def _update_monthly_flow(conn, uid: int, broker: str, year: int, month: int,
                         direction: str, amount: float) -> None:
    """Suma amount a deposits (o withdrawals) del mes actual del broker.
    Ajusta capital_final en la misma dirección.
    Si la fila no existe, la crea con capital_inicio = capital_final del mes anterior."""
    row = conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
        (uid, broker, year, month),
    ).fetchone()

    if row:
        if direction == 'deposit':
            conn.execute(
                """UPDATE monthly_entries
                   SET deposits = deposits + ?, capital_final = capital_final + ?
                   WHERE user_id=? AND broker=? AND year=? AND month=?""",
                (amount, amount, uid, broker, year, month),
            )
        else:
            conn.execute(
                """UPDATE monthly_entries
                   SET withdrawals = withdrawals + ?, capital_final = capital_final - ?
                   WHERE user_id=? AND broker=? AND year=? AND month=?""",
                (amount, amount, uid, broker, year, month),
            )
    else:
        # Crear fila del mes — capital_inicio = capital_final del mes anterior más reciente
        prev = conn.execute(
            """SELECT capital_final FROM monthly_entries
               WHERE user_id=? AND broker=? ORDER BY year DESC, month DESC LIMIT 1""",
            (uid, broker),
        ).fetchone()
        cap_inicio = float(prev['capital_final']) if prev else 0.0
        deposits = amount if direction == 'deposit' else 0.0
        withdrawals = 0.0 if direction == 'deposit' else amount
        cap_final = cap_inicio + (amount if direction == 'deposit' else -amount)
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id, year, month, broker, deposits, withdrawals,
                pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?,?,?,?,?,?,0,0,?,?)""",
            (uid, year, month, broker, deposits, withdrawals, cap_inicio, max(0.0, cap_final)),
        )


@app.post("/api/cash/flow")
def cash_flow(data: CashFlowIn, uid: int = Depends(get_current_user)):
    """Depósito o retiro de cash en un broker.
    Actualiza la posición cash del broker y las entradas mensuales (broker + global)."""
    conn = get_db()
    try:
        with conn:
            # 1. Validar broker
            broker_row = conn.execute(
                "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, data.broker_name)
            ).fetchone()
            if not broker_row:
                raise HTTPException(404, f"Broker '{data.broker_name}' no encontrado")

            currency = broker_row['currency']   # 'USDT' or 'ARS'
            sign = 1 if data.direction == 'deposit' else -1

            # 2. Actualizar posición cash
            cash_pos = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                (uid, data.broker_name),
            ).fetchone()

            if cash_pos:
                new_invested = (cash_pos['invested'] or 0) + sign * data.amount
                if new_invested < 0:
                    raise HTTPException(
                        400,
                        f"Saldo insuficiente. Disponible: {cash_pos['invested'] or 0:.2f} {currency}"
                    )
                conn.execute(
                    "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                    (new_invested, cash_pos['id'], uid),
                )
            else:
                if data.direction == 'withdraw':
                    raise HTTPException(400, "No hay posición cash para este broker.")
                # Crear posición cash si no existe (solo en depósito)
                asset_name = 'ARS' if currency == 'ARS' else 'USDT'
                conn.execute(
                    """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
                       VALUES (?,?,?,1,?)""",
                    (uid, data.broker_name, asset_name, data.amount),
                )

            # 3 & 4. Ambas entradas (broker + global) se guardan en USD.
            # Toda la tabla monthly_entries usa USD como unidad. La conversión ARS→USD
            # la hace Monthly.jsx al mostrar (multiplica × TC para tabs ARS).
            now = datetime.utcnow()
            amount_usd = data.amount / data.tc_blue if currency == 'ARS' else data.amount
            _update_monthly_flow(conn, uid, data.broker_name, now.year, now.month,
                                 data.direction, amount_usd)
            _update_monthly_flow(conn, uid, 'global', now.year, now.month,
                                 data.direction, amount_usd)
            # Phase 8 — repair chain for both touched brokers.
            _repair_monthly_chain(conn, uid, data.broker_name)
            _repair_monthly_chain(conn, uid, 'global')

        conn.close()
        return {"ok": True, "direction": data.direction, "amount": data.amount, "currency": currency}
    except HTTPException:
        conn.close()
        raise
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error al registrar flujo de caja: {ex}")


# ─── Conversión ARS ↔ USD dentro de un broker ────────────────────────────────
#
# Cuando un usuario "compra USD" desde un broker ARS (Cocos, Balanz, IOL, etc.),
# se debita cash ARS del broker padre y se acredita cash USD a un sub-broker
# auto-creado. Lo inverso (vender USD por ARS) hace el camino opuesto.
#
# Esto resuelve el problema del "FX phantom": antes, los pesos parados en un
# broker ARS generaban P&L en USD por el mero movimiento del blue, aunque el
# usuario nunca hubiera comprado dólares. Con este modelo, los pesos viven en
# ARS hasta que el usuario decide explícitamente convertirlos.

class ConversionIn(BaseModel):
    from_broker: str = Field(..., min_length=1, max_length=MAX_STR)
    direction: str  # 'ars_to_usd' | 'usd_to_ars'
    ars_amount: float = Field(..., gt=0)
    usd_amount: float = Field(..., gt=0)
    tc: float = Field(..., gt=0)              # tipo de cambio efectivo (ARS por USD)
    kind: str = Field('MEP', max_length=20)   # MEP | CCL | USDT | otro
    date: Optional[str] = Field(None, max_length=10)

    @field_validator('direction')
    @classmethod
    def valid_direction(cls, v):
        if v not in ('ars_to_usd', 'usd_to_ars'):
            raise ValueError("direction debe ser 'ars_to_usd' o 'usd_to_ars'")
        return v

    @field_validator('date')
    @classmethod
    def valid_date(cls, v):
        if v is None or v == '':
            return None
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v


def _ensure_usd_sibling(conn, uid: int, parent_broker_row) -> dict:
    """Devuelve el broker hijo USDT del broker ARS padre. Si no existe, lo crea.

    Convención de nombre: '<Padre> · USD'. El campo `parent_broker_id` apunta al
    padre. La currency del hijo es USDT.
    """
    parent_id = parent_broker_row['id']
    parent_name = parent_broker_row['name']
    sibling = conn.execute(
        "SELECT * FROM brokers WHERE user_id=? AND parent_broker_id=? AND currency='USDT'",
        (uid, parent_id),
    ).fetchone()
    if sibling:
        return dict(sibling)
    sibling_name = f"{parent_name} · USD"
    # Si por algún motivo ya existe un broker con ese nombre (sin parent), lo
    # reutilizamos asignándole parent.
    existing = conn.execute(
        "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, sibling_name)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE brokers SET parent_broker_id=?, currency='USDT' WHERE id=? AND user_id=?",
            (parent_id, existing['id'], uid),
        )
        return dict(conn.execute(
            "SELECT * FROM brokers WHERE id=? AND user_id=?", (existing['id'], uid)
        ).fetchone())
    cur = conn.execute(
        "INSERT INTO brokers (user_id, name, currency, parent_broker_id) VALUES (?,?,?,?)",
        (uid, sibling_name, 'USDT', parent_id),
    )
    return dict(conn.execute(
        "SELECT * FROM brokers WHERE id=? AND user_id=?", (cur.lastrowid, uid)
    ).fetchone())


def _adjust_cash(conn, uid: int, broker_name: str, asset: str, delta: float, tc_for_basis: Optional[float] = None):
    """Suma `delta` (puede ser negativo) al cash del broker. Crea la posición
    cash si no existe (solo si delta>0).

    Cuando se llama con `tc_for_basis` (caso compra de USD para sub-broker), se
    actualiza el `tc_compra` promedio ponderado del cash USD. Esto permite
    después computar P&L cambiario al vender los USD a un TC distinto.

    Average ponderado:
      new_tc = (existing_usd * existing_tc + delta_usd * tc_for_basis) / (existing_usd + delta_usd)

    Si `tc_for_basis` es None: comportamiento legacy, no toca tc_compra.
    """
    cash = conn.execute(
        "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
        (uid, broker_name),
    ).fetchone()
    if cash:
        existing = cash['invested'] or 0
        new_invested = existing + delta
        if new_invested < -1e-6:
            raise HTTPException(
                400,
                f"Saldo insuficiente en {broker_name}. Disponible: {existing:.2f}"
            )
        new_invested = max(0.0, new_invested)
        # Actualizar tc_compra promedio ponderado solo en compras (delta>0) y si nos pasaron TC
        if tc_for_basis is not None and delta > 0:
            existing_tc = cash['tc_compra'] or tc_for_basis
            if new_invested > 0:
                new_tc = (existing * existing_tc + delta * tc_for_basis) / new_invested
            else:
                new_tc = tc_for_basis
            conn.execute(
                "UPDATE positions SET invested=?, tc_compra=? WHERE id=? AND user_id=?",
                (new_invested, new_tc, cash['id'], uid),
            )
        else:
            conn.execute(
                "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                (new_invested, cash['id'], uid),
            )
    else:
        if delta < 0:
            raise HTTPException(400, f"No hay cash en {broker_name} para debitar.")
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra)
               VALUES (?,?,?,1,?,?)""",
            (uid, broker_name, asset, delta, tc_for_basis),
        )


@app.post("/api/conversions")
def create_conversion(data: ConversionIn, uid: int = Depends(get_current_user)):
    """Conversión interna entre cash ARS y cash USD dentro de un mismo broker.

    Flujo `ars_to_usd`:
      1. Valida que `from_broker` sea ARS y exista
      2. Auto-crea (o reutiliza) un sub-broker USDT con parent = from_broker
      3. Debita `ars_amount` del cash ARS de `from_broker`
      4. Acredita `usd_amount` al cash USDT del sub-broker
      5. Registra una operación tipo CONVERSION en el log

    Flujo `usd_to_ars`: simétrico — debita USD del sub-broker, acredita ARS al padre.
    Si el TC de venta difiere del tc_compra promedio del cash USD, se computa
    P&L cambiario realizado y se registra en `operations` + `monthly_entries`.

    Cost basis tracking
    ───────────────────
    Cada compra de USD actualiza el `tc_compra` promedio ponderado del cash USD
    en el sub-broker. Cuando se venden esos USD, el cost basis ARS se calcula
    como `usd_amount * tc_compra_promedio`, y el P&L se compara contra los ARS
    efectivamente recibidos.
    """
    conn = get_db()
    try:
        with conn:
            pnl_usd_realized = 0.0  # solo aplica a usd_to_ars

            # 1. Resolver broker(s) según dirección
            if data.direction == 'ars_to_usd':
                # from_broker debe ser ARS
                ars_broker = conn.execute(
                    "SELECT * FROM brokers WHERE user_id=? AND name=?",
                    (uid, data.from_broker),
                ).fetchone()
                if not ars_broker:
                    raise HTTPException(404, f"Broker '{data.from_broker}' no encontrado")
                if ars_broker['currency'] != 'ARS':
                    raise HTTPException(400, "La compra de USD solo aplica a brokers ARS.")
                usd_broker = _ensure_usd_sibling(conn, uid, ars_broker)
                # Debitar ARS, acreditar USD (con cost basis = TC de la conversión)
                _adjust_cash(conn, uid, ars_broker['name'], 'ARS', -data.ars_amount)
                _adjust_cash(conn, uid, usd_broker['name'], 'USDT', data.usd_amount,
                             tc_for_basis=data.tc)
                from_b, to_b = ars_broker['name'], usd_broker['name']
                from_curr, to_curr = 'ARS', 'USDT'
            else:  # usd_to_ars
                usd_broker = conn.execute(
                    "SELECT * FROM brokers WHERE user_id=? AND name=?",
                    (uid, data.from_broker),
                ).fetchone()
                if not usd_broker:
                    raise HTTPException(404, f"Broker '{data.from_broker}' no encontrado")
                if usd_broker['currency'] != 'USDT':
                    raise HTTPException(400, "La venta de USD solo aplica a brokers USDT.")
                if not usd_broker['parent_broker_id']:
                    raise HTTPException(400, "Este broker USD no tiene un padre ARS asociado.")
                ars_broker = conn.execute(
                    "SELECT * FROM brokers WHERE id=? AND user_id=?",
                    (usd_broker['parent_broker_id'], uid),
                ).fetchone()
                if not ars_broker:
                    raise HTTPException(400, "Broker padre ARS no encontrado.")

                # Computar P&L cambiario ANTES de modificar el cash:
                # cost_basis_ars = usd_amount * tc_compra_promedio_actual
                cash_usd = conn.execute(
                    "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                    (uid, usd_broker['name']),
                ).fetchone()
                tc_avg = (cash_usd['tc_compra'] if cash_usd else None) or data.tc
                cost_basis_ars = data.usd_amount * tc_avg
                pnl_ars_realized = data.ars_amount - cost_basis_ars
                # P&L USD se mide al TC de la venta (mismo patrón que valuation.js)
                pnl_usd_realized = pnl_ars_realized / data.tc if data.tc > 0 else 0.0

                # Debitar USD, acreditar ARS
                _adjust_cash(conn, uid, usd_broker['name'], 'USDT', -data.usd_amount)
                _adjust_cash(conn, uid, ars_broker['name'], 'ARS', data.ars_amount)
                from_b, to_b = usd_broker['name'], ars_broker['name']
                from_curr, to_curr = 'USDT', 'ARS'

            # 2. Registrar operación tipo CONVERSION en el log de operations
            op_date = data.date or datetime.utcnow().strftime('%Y-%m-%d')
            op_type = f"CONVERSION {data.kind} {from_curr}→{to_curr}"
            pnl_pct = None
            if data.direction == 'usd_to_ars' and data.usd_amount > 0:
                # P&L % sobre el USD vendido (cost basis USD = usd_amount, no varía)
                pnl_pct = (pnl_usd_realized / data.usd_amount) * 100
            conn.execute(
                """INSERT INTO operations
                   (user_id, date, broker, asset, op_type, entry_price, exit_price,
                    quantity, pnl_usd, pnl_pct, commissions)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                (uid, op_date, from_b,
                 f"{from_curr}→{to_curr}", op_type,
                 tc_avg if data.direction == 'usd_to_ars' else data.tc,
                 data.tc if data.direction == 'usd_to_ars' else None,
                 data.ars_amount if data.direction == 'ars_to_usd' else data.usd_amount,
                 round(pnl_usd_realized, 2),
                 round(pnl_pct, 4) if pnl_pct is not None else None),
            )

            # 3. Si fue venta de USD con P&L, sumarlo al pnl_realized del mes
            #    (broker padre ARS + global). Esto hace que aparezca en Resumen
            #    Mensual y en la atribución de Insights.
            if data.direction == 'usd_to_ars' and abs(pnl_usd_realized) > 1e-6:
                op_year, op_month = int(op_date[:4]), int(op_date[5:7])
                _update_monthly_pnl_realized(conn, uid, ars_broker['name'],
                                             op_year, op_month, pnl_usd_realized)
                _update_monthly_pnl_realized(conn, uid, 'global',
                                             op_year, op_month, pnl_usd_realized)

        conn.close()
        return {
            "ok": True,
            "from_broker": from_b,
            "to_broker": to_b,
            "ars_amount": data.ars_amount,
            "usd_amount": data.usd_amount,
            "tc": data.tc,
            "kind": data.kind,
            "pnl_usd_realized": round(pnl_usd_realized, 2) if data.direction == 'usd_to_ars' else None,
        }
    except HTTPException:
        conn.close()
        raise
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error en la conversión: {ex}")


# ─── Sub-broker USD manual (para CEDEARs y similares pagados con USD) ────────

@app.post("/api/brokers/{bid}/usd-sibling")
def create_usd_sibling(bid: int, uid: int = Depends(get_current_user)):
    """Crea (o devuelve si ya existe) el sub-broker USD asociado a un broker ARS.

    Use case: el usuario tiene USD del exterior y quiere comprar CEDEARs en
    Cocos pagando con esos USD, sin pasar por una conversión ARS→USD.
    Crear el sub-broker permite cargar las posiciones USD directamente ahí.
    """
    conn = get_db()
    try:
        parent = conn.execute(
            "SELECT * FROM brokers WHERE id=? AND user_id=?", (bid, uid)
        ).fetchone()
        if not parent:
            raise HTTPException(404, "Broker no encontrado")
        if parent['currency'] != 'ARS':
            raise HTTPException(400, "Solo los brokers ARS pueden tener un sub-broker USD.")
        sibling = _ensure_usd_sibling(conn, uid, parent)
        conn.commit()
        return sibling
    finally:
        conn.close()


# ─── Sync pnl_unrealized for current month ───────────────────────────────────

class SyncUnrealizedIn(BaseModel):
    broker: str
    pnl_unrealized_usd: float


@app.post("/api/monthly/sync-unrealized")
def sync_unrealized(data: SyncUnrealizedIn, uid: int = Depends(get_current_user)):
    """Actualiza pnl_unrealized del MES CALENDARIO ACTUAL (UTC) del broker, y
    pone en 0 pnl_unrealized en todas las demás entradas (meses cerrados, históricos
    o futuros pre-abiertos).

    Si no existe entrada para el mes calendario actual → no-op silencioso. El
    frontend (`autoRolloverIfNeeded` en MonthlySummary.jsx) crea la entrada del mes
    en curso antes de llamar a este endpoint. Phase 8 moverá ese rollover al backend.

    Phase 4 fix: antes el endpoint usaba `ORDER BY year DESC, month DESC LIMIT 1`,
    lo que stuffeaba P&L vivo en meses cerrados si había gaps en el calendario, o en
    meses futuros si el usuario los abría manualmente.
    """
    conn = get_db()
    try:
        now = datetime.utcnow()
        current = conn.execute(
            """SELECT id, capital_inicio, deposits, withdrawals, pnl_realized
               FROM monthly_entries
               WHERE user_id=? AND broker=? AND year=? AND month=?""",
            (uid, data.broker, now.year, now.month),
        ).fetchone()
        if current:
            # Zero pnl_unrealized en TODAS las demás entradas — incluye meses cerrados
            # (snapshot histórico) y futuros pre-abiertos (no deben tener P&L vivo).
            # NO tocar su capital_final.
            conn.execute(
                "UPDATE monthly_entries SET pnl_unrealized=0 WHERE user_id=? AND broker=? AND id != ?",
                (uid, data.broker, current['id']),
            )
            # En el mes en curso: actualizar pnl_unrealized Y recalcular capital_final
            # con la fórmula canónica para mantener coherencia:
            # capital_final = capital_inicio + deposits − withdrawals + pnl_realized + pnl_unrealized
            pnl = round(data.pnl_unrealized_usd, 4)
            new_cap_final = round(
                (current['capital_inicio'] or 0)
                + (current['deposits'] or 0)
                - (current['withdrawals'] or 0)
                + (current['pnl_realized'] or 0)
                + pnl,
                4,
            )
            conn.execute(
                "UPDATE monthly_entries SET pnl_unrealized=?, capital_final=? WHERE id=?",
                (pnl, new_cap_final, current['id']),
            )
            # Phase 8 — repair chain after sync (catches drift in closed months).
            _repair_monthly_chain(conn, uid, data.broker)
            conn.commit()
        # Si no existe entrada del mes calendario → no-op (el frontend la creará).
        conn.close()
        return {"ok": True}
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error al sincronizar pnl_unrealized: {ex}")


# ─── Sell position (atomic) ──────────────────────────────────────────────────

_FINITE_BOUND = 1e12  # bound razonable para detectar inf/NaN/garbage


def _finite(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    if not math.isfinite(v):
        raise ValueError('Valor numérico inválido (NaN/Inf)')
    if abs(v) > _FINITE_BOUND:
        raise ValueError('Valor numérico fuera de rango')
    return v


class SellIn(BaseModel):
    """Venta FIFO: cierra posiciones del par (broker, asset) en orden de entry_date asc."""
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=20)
    quantity: float = Field(..., gt=0, le=_FINITE_BOUND)
    exit_price: float = Field(..., ge=0, le=_FINITE_BOUND)
    date: Optional[str] = Field(None, max_length=10)
    tc_venta: Optional[float] = Field(None, ge=0, le=_FINITE_BOUND)  # opcional para brokers ARS
    commissions: Optional[float] = Field(0, ge=0, le=_FINITE_BOUND)  # comisión total de la venta (en moneda nativa del broker)

    @field_validator('exit_price', 'quantity', 'tc_venta', 'commissions')
    @classmethod
    def finite_check(cls, v):
        return _finite(v) if v is not None else v

    @field_validator('asset')
    @classmethod
    def clean_asset(cls, v):
        return v.strip().upper()

    @field_validator('broker')
    @classmethod
    def clean_broker(cls, v):
        return v.strip()

    @field_validator('date')
    @classmethod
    def valid_date(cls, v):
        if v is None or v == '':
            return None
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v


@app.post("/api/positions/sell")
def sell_position_fifo(data: SellIn, uid: int = Depends(get_current_user)):
    """Cierre FIFO: descuenta `quantity` empezando por la posición más vieja (entry_date asc).
    Crea una operación por cada posición tocada (cantidad parcial o total).
    Si la cantidad excede el total disponible, falla atómicamente sin tocar nada."""
    conn = get_db()
    try:
        with conn:  # transacción
            # Obtener moneda del broker
            br = conn.execute(
                "SELECT currency FROM brokers WHERE name=? AND user_id=?", (data.broker, uid)
            ).fetchone()
            currency = br["currency"] if br else "USDT"

            # Posiciones del par, FIFO por entry_date (NULLs al final como fallback), tie-break por id
            positions = conn.execute(
                """SELECT * FROM positions
                   WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 AND quantity > 0
                   ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
                (uid, data.broker, data.asset)
            ).fetchall()

            total = sum((p["quantity"] or 0) for p in positions)
            if data.quantity > total + 1e-9:
                raise HTTPException(400, f"Cantidad solicitada ({data.quantity}) excede el total disponible ({total})")

            op_date = data.date or datetime.utcnow().strftime("%Y-%m-%d")
            remaining = data.quantity
            ops_created = []
            total_pnl_usd = 0.0          # "true USD" P&L → goes to monthly_entries global
            total_pnl_ars_native = 0.0   # native ARS P&L → used for monthly_entries broker (ARS only)
            total_proceeds_native = 0.0  # Phase 2 — ingreso en cash (moneda nativa del broker)

            # Comisión de venta — se prorratea entre los chunks FIFO según la cantidad
            # vendida de cada lote, y reduce el P&L y el proceeds del cash.
            total_commission_native = float(data.commissions or 0)

            for p in positions:
                if remaining <= 1e-9:
                    break
                pos_qty = p["quantity"] or 0
                take = min(remaining, pos_qty)
                if take <= 0:
                    continue

                ratio = take / pos_qty if pos_qty > 0 else 0
                buy_price = p["buy_price"]
                # Cost basis incluye comisiones de COMPRA (prorrateadas).
                # Las comisiones de compra reducen el P&L de la venta — son
                # parte del costo real de adquirir el lote.
                pos_buy_commissions = p["commissions"] if "commissions" in p.keys() else 0
                pos_buy_commissions = pos_buy_commissions or 0
                # `entry_invested` ahora incluye buy commissions prorrateadas.
                base_invested = ((p["invested"] or 0) + pos_buy_commissions)
                entry_invested = base_invested * ratio if base_invested else None

                # Comisión de VENTA prorrateada para este chunk (sobre el total vendido)
                chunk_commission_native = total_commission_native * (take / data.quantity) if data.quantity else 0

                # P&L por chunk = sale − cost_basis_with_buy_comm − sell_commission
                if currency == "ARS":
                    # FX-phantom fix: cost basis y venta se valúan al MISMO TC
                    # (el de venta). Eso hace que pnl_usd sea exactamente
                    # pnl_ars / tc_venta y no aparezca P&L sintético por
                    # variaciones del blue entre compra y venta. tc_compra
                    # queda como dato informativo pero no afecta el P&L.
                    tc_venta = data.tc_venta or 1
                    pnl_ars_chunk = data.exit_price * take - (entry_invested or 0) - chunk_commission_native
                    pnl_usd = pnl_ars_chunk / tc_venta
                    invested_usd = (entry_invested or 0) / tc_venta if entry_invested else 0
                    total_pnl_ars_native += pnl_ars_chunk
                else:
                    # Para USD broker: si hay invested registrado, usar el cost basis prorrateado
                    # (incluye buy commissions). Caso contrario fallback a buy_price × qty.
                    cost = entry_invested if entry_invested is not None else ((buy_price or 0) * take)
                    pnl_usd = (data.exit_price * take) - cost - chunk_commission_native
                    invested_usd = cost

                total_pnl_usd += pnl_usd
                # Proceeds en cash = sale_amount − commission (lo que efectivamente entra al cash)
                total_proceeds_native += data.exit_price * take - chunk_commission_native
                pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None

                cur = conn.execute(
                    """INSERT INTO operations (user_id, date, broker, asset, op_type, entry_price,
                       exit_price, quantity, pnl_usd, pnl_pct, entry_date, commissions)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, op_date, p["broker"], p["asset"], 'Venta',
                     buy_price, data.exit_price, take,
                     round(pnl_usd, 2),
                     round(pnl_pct, 4) if pnl_pct is not None else None,
                     p["entry_date"] if "entry_date" in p.keys() else None,
                     round(chunk_commission_native, 4)),
                )
                ops_created.append(cur.lastrowid)

                # Actualizar / eliminar la posición
                if take >= pos_qty - 1e-9:
                    conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (p["id"], uid))
                else:
                    # Partial sell — el lote remanente conserva su porción
                    # proporcional de invested y commissions (1 - ratio).
                    new_qty = pos_qty - take
                    remaining_ratio = 1 - ratio
                    new_invested = round((p["invested"] or 0) * remaining_ratio, 6) if p["invested"] is not None else None
                    new_commissions = round(pos_buy_commissions * remaining_ratio, 6)
                    conn.execute(
                        "UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=?",
                        (new_qty, new_invested, new_commissions, p["id"], uid)
                    )
                remaining -= take

            # ── Phase 2 — acreditar proceeds al cash del broker (moneda nativa) ──
            if total_proceeds_native > 0:
                _adjust_broker_cash(conn, uid, data.broker, total_proceeds_native)

            # ── Registrar P&L realizado en monthly_entries ────────────────────────
            # Usar el año/mes de la operación (no necessarily el mes actual).
            op_year = int(op_date[:4])
            op_month = int(op_date[5:7])

            if currency == "ARS":
                # Broker entry: store in USD-equivalent (same convention as sync_unrealized).
                # Display in ARS tab = stored_value * tcBlue (current rate, approx).
                tc_v = data.tc_venta or 1
                pnl_for_broker = total_pnl_ars_native / tc_v
            else:
                pnl_for_broker = total_pnl_usd

            _update_monthly_pnl_realized(conn, uid, data.broker, op_year, op_month, pnl_for_broker)
            _update_monthly_pnl_realized(conn, uid, 'global',    op_year, op_month, total_pnl_usd)

            # Phase 8 — repair chain for both touched brokers (still in tx).
            _repair_monthly_chain(conn, uid, data.broker)
            _repair_monthly_chain(conn, uid, 'global')

            ops = [dict(conn.execute(
                "SELECT * FROM operations WHERE id=? AND user_id=?", (oid, uid)
            ).fetchone()) for oid in ops_created]
        conn.close()
        return {"ok": True, "operations": ops, "closed_count": len(ops)}
    except HTTPException:
        conn.close()
        raise
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error al vender: {ex}")


# ─── Monthly ─────────────────────────────────────────────────────────────────


class MonthlyIn(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    deposits: float = Field(0, ge=0, le=_FINITE_BOUND)
    withdrawals: float = Field(0, ge=0, le=_FINITE_BOUND)
    pnl_realized: float = Field(0, ge=-_FINITE_BOUND, le=_FINITE_BOUND)
    pnl_unrealized: float = Field(0, ge=-_FINITE_BOUND, le=_FINITE_BOUND)
    capital_inicio: float = Field(0, ge=0, le=_FINITE_BOUND)
    capital_final: float = Field(0, ge=0, le=_FINITE_BOUND)

    @field_validator('pnl_realized', 'pnl_unrealized', 'deposits', 'withdrawals',
                     'capital_inicio', 'capital_final')
    @classmethod
    def finite_check(cls, v):
        return _finite(v)


@app.get("/api/monthly")
def get_monthly(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? ORDER BY year, month, broker", (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/monthly")
def create_monthly(e: MonthlyIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    # Validar que el broker exista (excepto el especial 'global' que se usa para totales)
    if e.broker != 'global':
        exists = conn.execute(
            "SELECT 1 FROM brokers WHERE user_id=? AND name=?", (uid, e.broker)
        ).fetchone()
        if not exists:
            conn.close()
            raise HTTPException(400, f"Broker '{e.broker}' no existe. Agregalo en Config primero.")
    try:
        with conn:  # tx: insert + repair atómico
            cur = conn.execute(
                """INSERT INTO monthly_entries (user_id, year, month, broker, deposits, withdrawals,
                   pnl_realized, pnl_unrealized, capital_inicio, capital_final)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (uid, e.year, e.month, e.broker, e.deposits, e.withdrawals,
                 e.pnl_realized, e.pnl_unrealized, e.capital_inicio, e.capital_final),
            )
            new_id = cur.lastrowid
            _repair_monthly_chain(conn, uid, e.broker)  # Phase 8
        row = conn.execute("SELECT * FROM monthly_entries WHERE id=? AND user_id=?", (new_id, uid)).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Ya existe una entrada para ese mes/broker")


@app.put("/api/monthly/{eid}")
def update_monthly(eid: int, e: MonthlyIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    with conn:  # tx: update + repair atómico
        conn.execute(
            """UPDATE monthly_entries SET deposits=?, withdrawals=?, pnl_realized=?,
               pnl_unrealized=?, capital_inicio=?, capital_final=? WHERE id=? AND user_id=?""",
            (e.deposits, e.withdrawals, e.pnl_realized, e.pnl_unrealized,
             e.capital_inicio, e.capital_final, eid, uid),
        )
        _repair_monthly_chain(conn, uid, e.broker)  # Phase 8
    # FIXED: include user_id in SELECT to prevent IDOR data leak
    row = conn.execute("SELECT * FROM monthly_entries WHERE id=? AND user_id=?", (eid, uid)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@app.delete("/api/monthly/{eid}")
def delete_monthly(eid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    # Capturar el broker ANTES del delete para poder repair la chain.
    target = conn.execute(
        "SELECT broker FROM monthly_entries WHERE id=? AND user_id=?", (eid, uid)
    ).fetchone()
    with conn:  # tx: delete + repair atómico
        conn.execute("DELETE FROM monthly_entries WHERE id=? AND user_id=?", (eid, uid))
        if target:
            _repair_monthly_chain(conn, uid, target['broker'])  # Phase 8
    conn.close()
    return {"ok": True}


# ─── Operations ──────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class OperationIn(BaseModel):
    date: str = Field(..., max_length=10)
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=20)
    op_type: Optional[str] = Field(None, max_length=MAX_STR)
    entry_price: Optional[float] = Field(None, ge=0, le=_FINITE_BOUND)
    exit_price: Optional[float] = Field(None, ge=0, le=_FINITE_BOUND)
    quantity: Optional[float] = Field(None, ge=0, le=_FINITE_BOUND)
    pnl_usd: float = Field(0, ge=-_FINITE_BOUND, le=_FINITE_BOUND)
    pnl_pct: Optional[float] = Field(None, ge=-1e6, le=1e6)
    commissions: Optional[float] = Field(0, ge=0, le=_FINITE_BOUND)

    @field_validator('date')
    @classmethod
    def valid_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida, formato esperado: YYYY-MM-DD')
        return v

    @field_validator('asset')
    @classmethod
    def clean_asset(cls, v):
        return v.strip().upper()

    @field_validator('entry_price', 'exit_price', 'quantity', 'pnl_usd', 'pnl_pct')
    @classmethod
    def finite_check(cls, v):
        return _finite(v)


@app.get("/api/operations")
def get_operations(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date DESC", (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/operations")
def create_operation(op: OperationIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type, entry_price, exit_price,
           quantity, pnl_usd, pnl_pct, commissions) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct, op.commissions or 0),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM operations WHERE id=? AND user_id=?", (cur.lastrowid, uid)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/operations/{oid}")
def update_operation(oid: int, op: OperationIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        """UPDATE operations SET date=?, broker=?, asset=?, op_type=?, entry_price=?,
           exit_price=?, quantity=?, pnl_usd=?, pnl_pct=?, commissions=?
           WHERE id=? AND user_id=?""",
        (op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct, op.commissions or 0, oid, uid),
    )
    conn.commit()
    # FIXED: include user_id in SELECT to prevent IDOR data leak
    row = conn.execute("SELECT * FROM operations WHERE id=? AND user_id=?", (oid, uid)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@app.delete("/api/operations/{oid}")
def delete_operation(oid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM operations WHERE id=? AND user_id=?", (oid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Goals (objetivos de portfolio) ──────────────────────────────────────────

class GoalIn(BaseModel):
    target_usd: float = Field(..., gt=0, le=_FINITE_BOUND)
    target_date: str = Field(..., max_length=10)
    expected_return_pct: float = Field(10, ge=-50, le=200)
    label: Optional[str] = Field(None, max_length=MAX_STR)

    @field_validator('target_date')
    @classmethod
    def valid_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v


@app.get("/api/goals")
def list_goals(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM goals WHERE user_id=? ORDER BY target_date ASC", (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/goals")
def create_goal(g: GoalIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO goals (user_id, target_usd, target_date, expected_return_pct, label) VALUES (?,?,?,?,?)",
        (uid, g.target_usd, g.target_date, g.expected_return_pct, g.label),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (cur.lastrowid, uid)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/goals/{gid}")
def update_goal(gid: int, g: GoalIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        "UPDATE goals SET target_usd=?, target_date=?, expected_return_pct=?, label=? WHERE id=? AND user_id=?",
        (g.target_usd, g.target_date, g.expected_return_pct, g.label, gid, uid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (gid, uid)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@app.delete("/api/goals/{gid}")
def delete_goal(gid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM goals WHERE id=? AND user_id=?", (gid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/goals/cagr")
def historical_cagr(uid: int = Depends(get_current_user)):
    """Calcula el CAGR histórico real del usuario usando monthly_entries (broker='global').
    TWR mensual: ret_m = (capital_final - capital_inicio - net_deposits) / capital_inicio
    Annualizado vía media geométrica."""
    conn = get_db()
    rows = conn.execute(
        """SELECT year, month, deposits, withdrawals, capital_inicio, capital_final
           FROM monthly_entries WHERE user_id=? AND broker='global'
           ORDER BY year ASC, month ASC""",
        (uid,),
    ).fetchall()
    conn.close()
    if len(rows) < 2:
        return {"cagr": None, "months": len(rows), "reason": "Necesitás al menos 2 meses cargados."}
    factors = []
    for r in rows:
        ci = r["capital_inicio"] or 0
        cf = r["capital_final"] or 0
        net = (r["deposits"] or 0) - (r["withdrawals"] or 0)
        if ci <= 0:
            continue
        ret_m = (cf - ci - net) / ci
        # cap razonable para evitar outliers locos
        ret_m = max(-0.95, min(5.0, ret_m))
        factors.append(1 + ret_m)
    if not factors:
        return {"cagr": None, "months": len(rows), "reason": "Datos insuficientes."}
    # media geométrica anualizada
    prod = 1.0
    for f in factors:
        prod *= f
    avg_monthly = prod ** (1 / len(factors))
    cagr = avg_monthly ** 12 - 1
    return {"cagr": round(cagr * 100, 2), "months": len(factors), "reason": None}


# ─── Admin ───────────────────────────────────────────────────────────────────
# Solo accesible para users con is_admin=1. El email del admin se compara contra
# un hash SHA-256 al registrarse (ver _is_admin_email arriba).

@app.get("/api/admin/stats")
def admin_stats(uid: int = Depends(get_admin_user)):
    conn = get_db()
    users_total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    users_admin = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]
    users_last_7d = conn.execute(
        "SELECT COUNT(*) FROM users WHERE created_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    active_last_7d = conn.execute(
        "SELECT COUNT(*) FROM users WHERE last_login_at >= datetime('now','-7 days')"
    ).fetchone()[0]
    positions_total = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    operations_total = conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    monthly_total = conn.execute("SELECT COUNT(*) FROM monthly_entries").fetchone()[0]
    snapshots_total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    brokers_total = conn.execute("SELECT COUNT(*) FROM brokers").fetchone()[0]
    users_pending = conn.execute("SELECT COUNT(*) FROM users WHERE approved=0").fetchone()[0]
    conn.close()
    return {
        "users_total": users_total,
        "users_admin": users_admin,
        "users_pending": users_pending,
        "users_last_7d": users_last_7d,
        "active_last_7d": active_last_7d,
        "positions_total": positions_total,
        "operations_total": operations_total,
        "monthly_total": monthly_total,
        "snapshots_total": snapshots_total,
        "brokers_total": brokers_total,
        "registration_open": ALLOW_REGISTRATION,
    }


@app.get("/api/admin/users")
def admin_users(uid: int = Depends(get_admin_user)):
    """Lista de usuarios con métricas básicas. NO devuelve password hashes."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            u.id, u.email, u.name, u.is_admin, u.approved, u.created_at, u.last_login_at,
            (SELECT COUNT(*) FROM positions p WHERE p.user_id = u.id) AS positions_count,
            (SELECT COUNT(*) FROM operations o WHERE o.user_id = u.id) AS operations_count,
            (SELECT COUNT(*) FROM brokers b WHERE b.user_id = u.id) AS brokers_count,
            (SELECT COUNT(*) FROM monthly_entries m WHERE m.user_id = u.id) AS monthly_count
        FROM users u
        ORDER BY u.created_at DESC
    """).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["is_admin"] = bool(d["is_admin"])
        d["approved"] = bool(d["approved"])
        out.append(d)
    return out


@app.post("/api/admin/users/{user_id}/approve")
def admin_approve_user(user_id: int, uid: int = Depends(get_admin_user)):
    conn = get_db()
    target = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(404, "Usuario no existe")
    conn.execute("UPDATE users SET approved=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, uid: int = Depends(get_admin_user)):
    """Borra un usuario y todos sus datos. No permite borrarse a sí mismo ni a otros admins."""
    if user_id == uid:
        raise HTTPException(400, "No podés borrar tu propio usuario admin")
    conn = get_db()
    target = conn.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(404, "Usuario no existe")
    if target["is_admin"]:
        conn.close()
        raise HTTPException(403, "No se puede borrar otro admin desde la API")
    try:
        with conn:
            for table in ('positions', 'monthly_entries', 'operations', 'brokers', 'snapshots', 'config'):
                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.close()
        return {"ok": True}
    except Exception as ex:
        conn.close()
        raise HTTPException(500, f"Error al borrar: {ex}")


# ─── AI (Claude) ────────────────────────────────────────────────────────────
# Insights dinámicos generados por IA. Usa Haiku 4.5 con prompt caching.

_anthropic_client = None
def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        try:
            from anthropic import Anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return None
            _anthropic_client = Anthropic(api_key=api_key)
        except ImportError:
            return None
    return _anthropic_client


_AI_SYSTEM = """Sos el coach financiero de Rendi, una app argentina de seguimiento de inversiones personales.

Estilo:
- Hablás en español rioplatense (vos, tenés, etc.), tono cercano pero profesional.
- Sos directo y honesto: si algo está mal, lo decís sin endulzar. Si está bien, lo elogiás sin exagerar.
- Nunca das consejos financieros específicos ("comprá X"), pero sí observaciones y preguntas que ayuden al usuario a pensar.
- Frases cortas y claras. Evitás jerga financiera salvo que la expliques.
- Sin emojis salvo que aporten claridad. Sin disclaimers genéricos tipo "consultá un profesional".

Output: SIEMPRE devolvés un JSON válido con la estructura solicitada en el mensaje del usuario. Nada de texto antes ni después del JSON."""


class AIInsightsIn(BaseModel):
    """Snapshot mínimo del portfolio para generar insights."""
    total_usd: float = Field(..., ge=0)
    pnl_total_usd: float
    pnl_total_pct: float
    months_tracked: int = Field(0, ge=0)
    drawdown_max_pct: Optional[float] = None
    drawdown_current_pct: Optional[float] = None
    best_month_pct: Optional[float] = None
    worst_month_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    total_trades: int = Field(0, ge=0)
    top_asset: Optional[str] = None
    top_asset_pnl: Optional[float] = None
    concentration_top3_pct: Optional[float] = None
    avg_hold_days: Optional[float] = None


@app.post("/api/ai/insights")
def ai_insights(data: AIInsightsIn, request: Request, uid: int = Depends(get_current_user)):
    """Genera 1-3 textos de insights personalizados usando Claude Haiku.
    Devuelve { observations: [{title, text, tone: 'positive'|'neutral'|'warning'}] }"""
    _check_rate_limit(request, max_calls=20, window_seconds=3600, suffix=f"ai_insights:{uid}")

    client = _get_anthropic_client()
    if client is None:
        raise HTTPException(503, "AI no configurada (falta ANTHROPIC_API_KEY)")

    portfolio_json = data.model_dump_json(indent=2)

    user_msg = f"""Datos del portfolio del usuario:
```json
{portfolio_json}
```

Generá 3 observaciones cortas (60-100 palabras cada una) sobre lo que ves. Cada una debe:
- Tener un título de 3-5 palabras (sin emojis, sin signos)
- Mencionar al menos un número específico del JSON
- Terminar con una pregunta accionable o una observación concreta

Devolvé EXACTAMENTE este JSON (sin markdown, sin texto extra):
{{"observations": [
  {{"title": "...", "text": "...", "tone": "positive|neutral|warning"}},
  {{"title": "...", "text": "...", "tone": "positive|neutral|warning"}},
  {{"title": "...", "text": "...", "tone": "positive|neutral|warning"}}
]}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=[
                {"type": "text", "text": _AI_SYSTEM, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = msg.content[0].text.strip()
        # Por las dudas: si el modelo envuelve en ```json ... ``` lo limpiamos
        if text.startswith("```"):
            text = text.split("```")[1].lstrip("json\n").rstrip("`").strip()
        return json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(502, "La IA devolvió un formato inválido. Intentá de nuevo.")
    except Exception as ex:
        raise HTTPException(500, f"Error al generar insights: {ex}")


# ─── Chat conversacional con la IA ───────────────────────────────────────────

_AI_CHAT_SYSTEM = """Sos el coach de inversiones de Rendi, una app argentina de seguimiento de portfolios personales. Tu usuario es un inversor retail argentino que opera cripto, acciones US, CEDEARs, ETFs e índices, en brokers locales (Cocos, IOL, Bull, Balanz, Lemon) y exchanges (Binance).

ROL
No das recomendaciones específicas de "comprá X" o "vendé Y". Sí explicás conceptos, marcos analíticos, ratios, riesgos, y hacés preguntas que abren reflexión.
Si te piden recomendación específica, redirigí: ofrecé el marco para que el usuario decida ("no te digo cuál comprar, pero podemos pensar la tesis, el sizing, y el escenario de salida").
Respondés con los datos que tenés en el snapshot. Antes de decir "no tengo ese dato", intentá buscarlo — podés usar las tools disponibles para obtenerlo en tiempo real.

HERRAMIENTAS DISPONIBLES
Tenés tools que podés invocar para obtener datos adicionales cuando el snapshot no alcance:
- get_current_prices: precios en tiempo real de cualquier activo. Usala cuando el usuario pregunta el precio actual, o cuando querés comparar el precio de entrada con el precio de hoy.
- get_asset_operations: historial completo de operaciones cerradas de un activo específico del usuario. Útil para análisis de performance de un papel en particular.
- get_monthly_detail: detalle mensual completo de todos los brokers. Útil para análisis de períodos que no están en el snapshot resumido.
Usá las tools solo cuando sean necesarias. Si la respuesta está en el snapshot ya enviado, no las invoques.

ESTILO RIOPLATENSE
Vos, tenés, querés. Tono cercano pero profesional. Sin emojis.
CORTO: 2-4 oraciones por defecto, salvo que pidan explícitamente "explicame en detalle".
NO uses markdown (sin bold con asteriscos, sin listas con guión, sin headers con numeral). Escribí en prosa fluida con saltos de línea naturales. La UI no renderiza markdown.
Directo cuando está eufórico ("buen mes, pero un mes no es sistema"). Empático cuando está en rojo real ("32% duele, entiendo. Pero la decisión que viene no se toma desde ahí").
Separá la persona de la decisión: "los números muestran X" en vez de "estás haciendo mal".
Anti-patrones a EVITAR: disclaimers genéricos en cada respuesta; jerga vacía ("diversificá inteligentemente"); falsa modestia ("yo no sé pero..."); listas infinitas cuando preguntan algo puntual.

MÉTRICAS Y RANGOS CONCRETOS
Drawdown máx: 10-20% sano retail diversificado · 20-35% atención · >35% revisar tesis y sizing · cripto-heavy 40-50% es estructural pero indica concentración.
Win rate solo: irrelevante. 40-45% con payoff 2:1 es excelente. 70% con payoff 0.5:1 es trampa. Expectancy = (WR × Gprom) − ((1−WR) × Pprom). Si es negativa, el sistema pierde por construcción.
Payoff (Gprom/Pprom): <1 sangrante salvo WR>60% · 1-1.5 aceptable · 1.5-2.5 sano · >3 probable sample chico.
Concentración top-3: <30% diversificado · 30-50% enfocado normal · 50-70% requiere convicción explícita · >70% es apuesta, no portfolio. Ojo: BTC+ETH+SOL = una sola apuesta direccional cripto, no tres.
Hold time: <30 días trading, 1-6 meses swing, >6 meses inversión. Si alguien dice "invierto" pero hold medio es 18 días, está tradeando sin saberlo.
Sample size: con <30 trades cerrados los resultados son ruido. Recién a 50-100 cierres se puede hablar de edge.
Correlación oculta: la pregunta clave para diversificación es "si mañana cae 20% el S&P, ¿cuánto cae mi portfolio?". Si la respuesta es ~20%, no está diversificado.

CONTEXTO ARGENTINO
Medir en USD: regla operativa. Convertir todo a CCL/MEP. Evita la ilusión nominal.
Dólar: blue = informal, termómetro psicológico, NO operable legalmente. MEP (AL30/GD30) = dolarizar dentro del país. CCL = sacar afuera.
CEDEAR: certificado local que replica acción US. Ventaja: dolarización implícita vía CCL. Desventaja: spread más ancho, comisiones de custodia, tracking error.
Inflación AR: benchmark mínimo en ARS = inflación + 5% real. El snapshot incluye comparativo con inflación acumulada y con S&P 500.
Riesgo país: spread bonos soberanos vs Treasury. >1500 estrés alto · <800 optimismo. Cuando comprime, GGAL/YPF tienden a rallear.

RISK MANAGEMENT
Position sizing: 1-2% del capital por idea de trading · 5-10% por activo en portfolio de inversión · single name >15% requiere tesis escrita · >25% concentración consciente.
"Buy and hold" tiene sentido en activos con expected value positivo de LP (índices amplios, BTC horizonte +4 años). NO en single names sin tesis, altcoins baja cap, o cuando se perdió la tesis original. Hold no es estrategia si no podés articular por qué seguís adentro.

SESGOS
Anclaje al precio de compra: el precio al que compraste no le importa al mercado. Pregunta: "si compraras hoy a este precio, ¿lo harías?".
FOMO / revenge trading: tamaño de posición sube cuando la convicción debería bajar.
Suerte vs habilidad: <30 trades = ruido. Win rate alto en sample chico = aleatoriedad.
Ilusión de control: controlás el sizing, el stop, la entrada, el journaling. No controlás el resultado de un trade individual.

PREGUNTAS-COACH BUENAS (abiertas)
"¿Qué tesis tenías cuando entraste? ¿Sigue vigente?"
"Si tuvieras que justificar esta posición ante alguien que no la conoce, ¿qué dirías?"
"¿Cuál sería el escenario que te haría salir?"
Evitar cerradas sí/no tipo "¿pensás vender?" — cierran reflexión.

Tenés el snapshot del portfolio del usuario en el contexto. Usá los números concretos cuando sean relevantes. El snapshot incluye benchmarks (S&P 500, inflación AR, dólar blue) para comparar la performance del usuario contra referencias de mercado."""


class ChatMsg(BaseModel):
    role: str = Field(..., max_length=20)
    content: str = Field(..., min_length=1, max_length=4000)

    @field_validator('role')
    @classmethod
    def valid_role(cls, v):
        if v not in ('user', 'assistant'):
            raise ValueError('role debe ser user o assistant')
        return v


class AIChatIn(BaseModel):
    """Mensaje del usuario + historial + snapshot rico del portfolio."""
    messages: list[ChatMsg] = Field(..., min_length=1, max_length=30)
    # snapshot es un dict abierto para incluir posiciones, operaciones, mensuales, etc.
    snapshot: dict = Field(default_factory=dict)

    @field_validator('snapshot')
    @classmethod
    def cap_snapshot_size(cls, v):
        s = json.dumps(v)
        if len(s) > 200_000:
            raise ValueError('Snapshot demasiado grande (>200 KB)')
        return v


# ── Tool definitions para el coach IA ────────────────────────────────────────

_AI_TOOLS = [
    {
        "name": "get_current_prices",
        "description": "Obtiene cotizaciones actuales en tiempo real de uno o más activos. Usala cuando el usuario pregunta el precio actual de un activo, o cuando querés comparar el precio de entrada con el precio de hoy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de símbolos. Acciones US y cripto sin sufijo (BTC, ETH, AAPL, TSLA). CEDEARs con .BA (AAPL.BA, GGAL.BA). Máximo 10.",
                    "maxItems": 10,
                }
            },
            "required": ["symbols"],
        },
    },
    {
        "name": "get_asset_operations",
        "description": "Obtiene el historial completo de operaciones cerradas de un activo específico del usuario. Útil para analizar la performance histórica en un papel particular.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset": {
                    "type": "string",
                    "description": "Símbolo del activo (ej: BTC, AAPL, GGAL). Sin sufijo .BA.",
                }
            },
            "required": ["asset"],
        },
    },
    {
        "name": "get_monthly_detail",
        "description": "Obtiene el detalle mensual completo del portfolio (todas las filas por broker). Útil cuando necesitás datos de períodos específicos no cubiertos en el snapshot resumido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months": {
                    "type": "integer",
                    "description": "Cuántos meses traer desde el más reciente (máximo 24, default 12).",
                    "default": 12,
                }
            },
        },
    },
]


def _execute_ai_tool(name: str, input_data: dict, uid: int) -> dict:
    """Ejecuta una tool del coach IA y devuelve el resultado como dict."""
    if name == "get_current_prices":
        symbols = [str(s).strip().upper() for s in input_data.get("symbols", [])][:10]
        valid = [s for s in symbols if _SYMBOL_RE.match(s)]
        if not valid:
            return {"error": "No se proporcionaron símbolos válidos"}
        result = {}
        for sym in valid:
            yf_t = CRYPTO_YF.get(sym, sym)
            result[sym] = _fetch_one(yf_t)
        return {"prices": result, "note": "Precios en USD (o ARS para .BA)"}

    elif name == "get_asset_operations":
        asset = str(input_data.get("asset", "")).strip().upper()
        if not asset:
            return {"error": "asset requerido"}
        conn = get_db()
        rows = conn.execute(
            """SELECT date, op_type, entry_price, exit_price, quantity,
                      pnl_usd, pnl_pct, entry_date
               FROM operations WHERE user_id=? AND asset=? ORDER BY date DESC""",
            (uid, asset),
        ).fetchall()
        conn.close()
        return {"asset": asset, "operations": [dict(r) for r in rows], "count": len(rows)}

    elif name == "get_monthly_detail":
        months = min(int(input_data.get("months", 12)), 24)
        conn = get_db()
        rows = conn.execute(
            """SELECT year, month, broker, deposits, withdrawals,
                      pnl_realized, pnl_unrealized, capital_inicio, capital_final
               FROM monthly_entries WHERE user_id=? ORDER BY year DESC, month DESC LIMIT ?""",
            (uid, months * 6),
        ).fetchall()
        conn.close()
        return {"entries": [dict(r) for r in rows]}

    return {"error": f"Tool '{name}' no reconocida"}


@app.post("/api/ai/chat")
def ai_chat(data: AIChatIn, request: Request, uid: int = Depends(get_current_user)):
    """Chat libre con el coach IA. Usa el historial + snapshot rico como contexto.
    Soporta tool_use: el modelo puede pedir precios en tiempo real u otro dato de DB."""
    _check_rate_limit(request, max_calls=40, window_seconds=3600, suffix=f"ai_chat:{uid}")

    client = _get_anthropic_client()
    if client is None:
        raise HTTPException(503, "AI no configurada (falta ANTHROPIC_API_KEY)")

    portfolio_json = json.dumps(data.snapshot, indent=2, ensure_ascii=False, default=str)
    system_text = f"""{_AI_CHAT_SYSTEM}

DATOS COMPLETOS DEL USUARIO
El snapshot incluye: summary (métricas agregadas: total USD, PnL, drawdown, win rate, etc.), positions (posiciones abiertas con broker, activo, cantidad, valor USD, PnL, % del portfolio), cash, operations (operaciones cerradas), monthly (historial mes a mes), brokers, y benchmarks (S&P 500, inflación AR, dólar blue — para comparar la performance del usuario con referencias de mercado).
Cuando el usuario pregunta algo específico ("¿qué % es Tesla?", "¿cuánto perdí en BTC?", "¿mi mejor mes?"), buscá primero en estos datos. Usá las tools para complementar solo si necesitás algo que no está acá.

```json
{portfolio_json}
```"""

    # Construir messages para el loop de tool_use
    messages_loop: list = [m.model_dump() for m in data.messages]
    MAX_TOOL_LOOPS = 3  # límite de rondas para evitar loops infinitos

    try:
        for _ in range(MAX_TOOL_LOOPS + 1):
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1000,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                tools=_AI_TOOLS,
                messages=messages_loop,
            )

            if response.stop_reason != "tool_use":
                # Respuesta final en texto
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    ""
                )
                return {"reply": text.strip()}

            # Hay tool_use: ejecutar cada tool y continuar el loop
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_ai_tool(block.name, block.input, uid)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

            # Agregar respuesta del asistente (con tool_use blocks) + resultados al historial
            messages_loop.append({
                "role": "assistant",
                "content": [b.model_dump() for b in response.content],
            })
            messages_loop.append({"role": "user", "content": tool_results})

        # Si llegó al límite de loops sin respuesta final, forzar respuesta sin tools
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=800,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=messages_loop,
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        return {"reply": text.strip()}

    except Exception as ex:
        raise HTTPException(500, f"Error en el chat: {ex}")


# ─── CSV Importer ────────────────────────────────────────────────────────────
# Pipeline: parse → normalize → validate → preview → (confirm) persist → batch.
# La persistencia reusa los helpers de bajo nivel ya existentes
# (_adjust_broker_cash, _adjust_cash, _update_monthly_pnl_realized,
# _update_monthly_flow, _repair_monthly_chain, _ensure_usd_sibling) para no
# duplicar la contabilidad. Ver `backend/importing/persister.py`.

from importing import pipeline as _import_pipeline
from importing import persister as _import_persister
from importing.parsers.registry import get_parser as _get_parser

# Namespace simple con los helpers que el persister consume.
class _ImportHelpers:
    pass
_import_helpers = _ImportHelpers()
_import_helpers._adjust_broker_cash = _adjust_broker_cash
_import_helpers._adjust_cash = _adjust_cash
_import_helpers._update_monthly_pnl_realized = _update_monthly_pnl_realized
_import_helpers._update_monthly_flow = _update_monthly_flow
_import_helpers._repair_monthly_chain = _repair_monthly_chain
_import_helpers._ensure_usd_sibling = _ensure_usd_sibling


@app.get("/api/imports/template")
def import_template(format: str = "rendi_generic", uid: int = Depends(get_current_user)):
    """Devuelve el CSV de ejemplo del formato pedido."""
    parser = _get_parser(format)
    if parser is None:
        raise HTTPException(404, f"Formato '{format}' desconocido.")
    csv_text = parser.template_csv()
    if not csv_text:
        raise HTTPException(404, f"El formato '{format}' no tiene template descargable.")
    return PlainTextResponse(
        csv_text,
        headers={"Content-Disposition": f'attachment; filename="rendi_template_{format}.csv"'},
        media_type="text/csv",
    )


@app.get("/api/imports/parsers")
def import_parsers(uid: int = Depends(get_current_user)):
    """Lista los parsers disponibles + cuáles están soportados (para el dropdown)."""
    return _import_pipeline.parser_options()


@app.post("/api/imports/inspect")
async def import_inspect(
    file: UploadFile = File(...),
    uid: int = Depends(get_current_user),
):
    """Lee headers y primeras filas del CSV. Devuelve también un mapping
    sugerido (auto-detect) y la lista de campos internos de Rendi para
    armar el wizard de mapeo de columnas."""
    contents = await file.read()
    payload = _import_pipeline.inspect(contents)
    if payload.get("error"):
        raise HTTPException(400, payload["error"])
    return payload


@app.post("/api/imports/preview")
async def import_preview(
    file: UploadFile = File(...),
    broker: Optional[str] = Form(None),
    format: Optional[str] = Form(None),
    mapping: Optional[str] = Form(None),  # JSON string: {"columns": {...}, "defaults": {...}}
    route_by_currency: Optional[str] = Form(None),  # "1"/"true" → activa ruteo per-row USD→sub
    uid: int = Depends(get_current_user),
):
    """Sube el CSV y genera el preview. Persiste un batch en estado 'preview'.
    Devuelve session_id (= batch_id) para usar en /confirm."""
    contents = await file.read()
    parsed_mapping = None
    if mapping:
        try:
            parsed_mapping = json.loads(mapping)
        except json.JSONDecodeError:
            raise HTTPException(400, "El mapping enviado no es un JSON válido.")
    flag_route = (route_by_currency or "").strip().lower() in ("1", "true", "yes", "on")
    conn = get_db()
    try:
        with conn:
            payload = _import_pipeline.run_preview(
                conn,
                uid=uid,
                file_bytes=contents,
                file_name=file.filename,
                broker_hint=broker,
                parser_format=format,
                mapping=parsed_mapping,
                route_by_currency=flag_route,
            )
        if payload.get("error"):
            # No es 500 — es un error esperado (archivo inválido, formato no soportado).
            raise HTTPException(400, payload["error"])
        return payload
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al previsualizar el CSV: {ex}")
    finally:
        conn.close()


class ImportConfirmIn(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)


@app.post("/api/imports/confirm")
def import_confirm(data: ImportConfirmIn, uid: int = Depends(get_current_user)):
    """Confirma el import: aplica los side-effects y marca el batch como 'confirmed'."""
    conn = get_db()
    try:
        with conn:
            try:
                txs, raw_id_by_index = _import_pipeline.load_session_for_confirm(
                    conn, uid=uid, session_id=data.session_id,
                )
            except ValueError as ex:
                raise HTTPException(400, str(ex))

            try:
                summary = _import_persister.persist_batch(
                    conn,
                    uid=uid,
                    batch_id=data.session_id,
                    txs=txs,
                    raw_row_ids_by_index=raw_id_by_index,
                    helpers=_import_helpers,
                )
            except _import_persister.PersistError as ex:
                raise HTTPException(400, f"Error en fila {ex.row_index}: {ex.message}")

        return {"ok": True, "batch_id": data.session_id, **summary}
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al confirmar el import: {ex}")
    finally:
        conn.close()


@app.get("/api/imports")
def import_list(uid: int = Depends(get_current_user)):
    """Lista los batches confirmados / revertidos del usuario."""
    conn = get_db()
    try:
        return _import_pipeline.list_batches(conn, uid=uid)
    finally:
        conn.close()


@app.get("/api/imports/{batch_id}")
def import_detail(batch_id: str, uid: int = Depends(get_current_user)):
    """Detalle de un batch — incluye filas válidas y errores para auditoría."""
    conn = get_db()
    try:
        batch = conn.execute(
            "SELECT * FROM import_batches WHERE id=? AND user_id=?", (batch_id, uid),
        ).fetchone()
        if not batch:
            raise HTTPException(404, "Batch no encontrado.")
        rows = conn.execute(
            """SELECT id, row_index, raw_json, status, errors_json
                 FROM import_raw_rows WHERE batch_id=? ORDER BY row_index ASC""",
            (batch_id,),
        ).fetchall()
        return {
            "batch": dict(batch),
            "rows": [dict(r) for r in rows],
        }
    finally:
        conn.close()


@app.post("/api/imports/{batch_id}/revert")
def import_revert(batch_id: str, uid: int = Depends(get_current_user)):
    """Reversa todos los side-effects de un batch confirmado.
    Falla si el batch incluye SELL o FX (no son revertibles automáticamente),
    o si alguna posición creada ya fue vendida."""
    conn = get_db()
    try:
        with conn:
            try:
                result = _import_persister.revert_batch(
                    conn, uid=uid, batch_id=batch_id, helpers=_import_helpers,
                )
            except _import_persister.PersistError as ex:
                raise HTTPException(400, ex.message)
        return result
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al revertir el import: {ex}")
    finally:
        conn.close()
