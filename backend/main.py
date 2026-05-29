from fastapi import FastAPI, HTTPException, Depends, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator, Field
from typing import Optional, List
import sqlite3, os, secrets, time, hashlib, hmac, json
from collections import defaultdict

# ─── Cargar .env del backend antes de leer cualquier variable de entorno ────
# Permite tener `backend/.env` con secretos (ANTHROPIC_API_KEY, SECRET_KEY,
# ADMIN_EMAIL_HASH, etc.) sin exportarlos a mano cada vez que se levanta
# uvicorn. En producción (Railway) las env vars se setean en el dashboard
# y este load_dotenv() es no-op porque no hay archivo .env.
#
# IMPORTANTE: usamos override=True. Caso real: el user tenía una API key
# vieja exportada en ~/.zshrc; al hacer cd y arrancar uvicorn, esa key
# vieja llegaba al proceso por herencia del shell. Sin override, load_dotenv
# preserva la del shell y nuestro .env queda ignorado. Con override=True el
# .env del repo siempre gana — comportamiento esperado para dev local.
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
except ImportError:
    # python-dotenv opcional — si no está, seguimos con env vars del sistema.
    pass
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf
import requests
import logging
log = logging.getLogger(__name__)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from snapshots_job import (
    run_daily_snapshot,
    compute_live_portfolio_value,
    fetch_prices_for_symbols,
    compute_broker_value_usd,
)
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta, date
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
# auto_error=False: get_current_user mira primero la cookie HttpOnly; si no hay,
# cae al header Authorization (back-compat / clientes no-browser). Sin esto, no
# tener header genera 401 antes de que podamos chequear la cookie.
bearer = HTTPBearer(auto_error=False)

# ─── Auth cookie helpers ─────────────────────────────────────────────────────
# El token JWT se setea como cookie HttpOnly para que JS no lo pueda leer (XSS
# no roba la sesión). En prod (RENDI_ENV=prod) la cookie va con Secure=True;
# en dev local (HTTP) no — sino el browser la rechaza.

COOKIE_NAME = "rendi_token"
_COOKIE_SECURE = os.environ.get("RENDI_ENV", "dev").lower() == "prod"


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_DAYS * 86400,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")

app = FastAPI(title="Rendi", docs_url=None, redoc_url=None)  # disable public docs in prod

# CORS — origins explícitos (allow_credentials no admite "*"). En prod estos
# son la URL del frontend (Vercel) seteada por env. En dev acepta los
# puertos de Vite. allow_credentials=True es necesario para que el browser
# acepte la cookie HttpOnly cross-origin.
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
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
    # HSTS — solo en prod (con HTTPS). Previene downgrade attacks + SSL strip.
    # max-age=31536000 (1 año) + includeSubDomains para api.rendi.finance.
    if os.environ.get("RENDI_ENV") == "prod":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Permissions-Policy: bloquear features que no usamos. Defensa en profundidad
    # contra XSS que intente acceder a sensores / pagos del browser.
    response.headers["Permissions-Policy"] = (
        "geolocation=(), microphone=(), camera=(), payment=(), usb=(), "
        "bluetooth=(), magnetometer=(), gyroscope=(), accelerometer=()"
    )
    response.headers["Cache-Control"] = "no-store"
    return response


# ─── Rate limiting (in-memory, per key) ──────────────────────────────────────
# Per-process. Para multi-worker o multi-host conviene migrar a Redis.

_rate_store: dict = defaultdict(list)  # key → [timestamps]
_RATE_STORE_MAX_KEYS = 10_000  # cap para evitar memory bloat por IPs random

def _rate_limit_ip(request: Request) -> str:
    """Extrae la IP del cliente respetando X-Forwarded-For (Railway/Vercel
    proxean — `request.client.host` sería siempre la IP del LB, generando
    un solo cubo global para todos los users → cualquier atacante puede
    DoS-ear el rate limit de TODOS al mismo tiempo).

    SECURITY: solo confiamos en X-Forwarded-For si vamos detrás de un
    proxy de confianza (RENDI_ENV=prod). En dev/local, fallback a
    request.client.host para evitar spoofing trivial.
    """
    if os.environ.get("RENDI_ENV") == "prod":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(request: Request, max_calls: int, window_seconds: int, suffix: str = ""):
    ip = _rate_limit_ip(request)
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
    # WAL: lectores no bloquean al writer (multi-user OK)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # busy_timeout: si otra conexión está escribiendo, esperar 5s antes de
    # tirar "database is locked". Sin esto, requests concurrentes fallan
    # inmediatamente bajo carga (FastAPI corre handlers en threadpool).
    conn.execute("PRAGMA busy_timeout=5000")
    # synchronous=NORMAL: con WAL es seguro y 2-3× más rápido que FULL
    # (no fsync después de cada commit; el WAL checkpoint sí).
    conn.execute("PRAGMA synchronous=NORMAL")
    # cache: 64MB vs default 2MB. Evita evicción constante de índices hot.
    conn.execute("PRAGMA cache_size=-64000")
    # temp_store: usar memoria para tablas/índices temporarios (sorts, joins).
    conn.execute("PRAGMA temp_store=MEMORY")
    # mmap_size: 256MB de memory-mapped I/O acelera lecturas grandes.
    conn.execute("PRAGMA mmap_size=268435456")
    return conn


def _table_cols(conn, table: str) -> set:
    # Table name is always hardcoded in callers — never user-supplied
    allowed = {'positions', 'monthly_entries', 'operations', 'config', 'brokers', 'users', 'snapshots', 'goals',
               'import_batches', 'import_raw_rows', 'import_normalized_tx', 'import_op_links',
               'import_mappings', 'news', 'subscriptions', 'ai_usage_daily', 'ai_user_facts',
               'ai_tool_usage', 'yfinance_cache', 'credit_ledger'}
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
            tier TEXT,                         -- override explícito: 'pro' | 'free' | NULL
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
    if user_cols and 'tier' not in user_cols:
        # Override de tier (Pro paid). NULL = sigue lógica is_admin → free/admin.
        conn.execute("ALTER TABLE users ADD COLUMN tier TEXT")
    if user_cols and 'email_verified' not in user_cols:
        # Verificación de email post-register. NULL = sin migrar, 0 = no verificado,
        # 1 = verificado. Migración: existing users → 1 (no les pedimos verificar
        # retroactivamente para no romper su acceso).
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0")
        conn.execute("UPDATE users SET email_verified = 1")
    if user_cols and 'investor_profile' not in user_cols:
        # Perfil de inversor (7 respuestas guardadas como JSON). NULL = no completó
        # el test todavía. Se inyecta en el system prompt del Coach IA cuando hay
        # un valor, así la IA conoce horizonte/tolerancia/objetivo/estilo/etc.
        conn.execute("ALTER TABLE users ADD COLUMN investor_profile TEXT")
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
    # Migración: columna currency — moneda en que está expresado `invested`.
    # Sin esto, el persister no podía saber si una posición fue comprada en
    # USD (Compra Dolar Mep en Cocos) vs ARS, generando P&L cross-currency
    # absurdo en SELLs posteriores. Default NULL = back-compat (asume ARS o
    # USDT según el broker, igual que antes).
    cols = _table_cols(conn, 'positions')
    if cols and 'currency' not in cols:
        conn.execute("ALTER TABLE positions ADD COLUMN currency TEXT")
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
    # Migración: columna notes (texto libre — usada por cobranzas de bonos,
    # eventualmente extensible a otras ops para capturar contexto del user)
    cols = _table_cols(conn, 'operations')
    if cols and 'notes' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN notes TEXT")
    # Migración Phase 3D: tracking de moneda nativa y FX al momento del evento.
    # Esto permite convertir operations.pnl_usd (que históricamente guardaba
    # el monto en moneda del broker, no necesariamente USD) a un USD canónico
    # consistente para reportes cross-broker / cross-currency.
    #   • currency: 'ARS' | 'USD' | 'USDT' | 'EUR' (futuras). Moneda nativa del flujo.
    #   • fx_to_usd: factor de conversión nativa→USD al momento del evento.
    #     - ARS broker recibiendo cupón ARS de bono USD: fx_to_usd = MEP del día.
    #     - ARS broker recibiendo cupón ARS de bono ARS (CER): fx_to_usd = blue.
    #     - USD broker (USDT/USD): fx_to_usd = 1.0.
    #     - NULL para ops históricas → frontend usa blue actual como fallback con warning.
    cols = _table_cols(conn, 'operations')
    if cols and 'currency' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN currency TEXT")
    if cols and 'fx_to_usd' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN fx_to_usd REAL")
    # Phase 3D sub-fix: cost basis consumido por amortizaciones (lo que costó
    # el face devuelto). Permite distinguir "devolución de capital" de
    # "ganancia realizada del amort":
    #   • Cash recibido (pnl_usd) = monto neto acreditado al broker.
    #   • Cost basis consumido = parte proporcional del invested original.
    #   • Ganancia del amort = pnl_usd − cost_basis_consumed.
    # NULL para cupones (no aplica) y para amorts viejas (legacy, pre Phase 3D).
    cols = _table_cols(conn, 'operations')
    if cols and 'cost_basis_consumed' not in cols:
        conn.execute("ALTER TABLE operations ADD COLUMN cost_basis_consumed REAL")
    conn.commit()

    # ─── Índices secundarios — positions / operations / monthly_entries ────
    # Históricamente solo había PK por `id`. Cada query filtra por `user_id`
    # → full table scan. Con 1k+ rows acumulados cross-user, eso son 20-80ms
    # perdidos por query. En endpoints como /api/insights que pegan a las 3
    # tablas en paralelo, llegamos a 60-240ms perdidos por request.
    #
    # `idx_operations_user_date` es compuesto (user, date DESC) porque casi
    # todas las queries del módulo operations ordenan por fecha desc:
    #   /operations, reports/period, monthly aggregation, wrapped/year.
    # Compuesto = index range scan + sort eliminado.
    #
    # `idx_monthly_user_period` (user, year, month) acelera /monthly,
    # /reports/timeline (12 meses × user) y monthly_entries lookups.
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id);
        CREATE INDEX IF NOT EXISTS idx_operations_user_date ON operations(user_id, date DESC);
        CREATE INDEX IF NOT EXISTS idx_monthly_user_period ON monthly_entries(user_id, year, month);
    """)
    conn.commit()

    # ─── bond_indices_daily ────────────────────────────────────────────────
    # Cache de índices financieros publicados diariamente (CER, UVA, A3500).
    # Tabla shared cross-user — los índices son datos públicos macro, no
    # personales. Phase 3C: CER para bonos AR ajustados por inflación
    # (TX26, TX28, TZX26/27/28).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bond_indices_daily (
            index_name TEXT NOT NULL,    -- 'CER' | 'UVA' | 'A3500'
            date TEXT NOT NULL,          -- 'YYYY-MM-DD'
            value REAL NOT NULL,         -- coeficiente del día
            source TEXT,                 -- 'bcra' | 'argentinadatos' | 'manual'
            updated_at TEXT NOT NULL,
            PRIMARY KEY (index_name, date)
        );
        CREATE INDEX IF NOT EXISTS idx_bond_indices_date ON bond_indices_daily(date);
    """)

    # ─── news (Noticias del mercado y portfolio) ───────────────────────────
    # Cache de noticias financieras del mercado + tagged por ticker.
    # Compartido cross-user — las noticias son data pública. La personalización
    # se hace en query time (filtrar a tickers del user).
    #
    # Source primaria: Google News RSS — sin auth, sin quota. Patrón
    # `query → items`, donde el query es "AAPL stock" o "BCRA Argentina"
    # según el contexto.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,            -- 'google_news_rss' | 'investing_com' | ...
            external_id TEXT NOT NULL,       -- guid del feed — para dedup
            title TEXT NOT NULL,
            summary TEXT,                    -- description del RSS (opcional)
            url TEXT NOT NULL,
            image_url TEXT,
            published_at TEXT NOT NULL,      -- ISO datetime
            tickers TEXT,                    -- JSON array: '["AAPL","NVDA"]'
            category TEXT,                   -- 'market' | 'portfolio' | 'macro'
            query_source TEXT,               -- el query que la trajo (para debug + dedup soft)
            tags TEXT,                       -- CSV: 'earnings,m_and_a,regulatory,…'
            fetched_at TEXT NOT NULL,
            UNIQUE(source, external_id)
        );
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_news_category ON news(category);
        -- /news/portfolio filtra con `category='portfolio' AND query_source LIKE '{ticker} %'`
        -- contra 20 tickers a la vez (20 LIKE ORs). Sin este index es full scan.
        -- query_source es el primer field para aprovechar el prefix match del LIKE.
        CREATE INDEX IF NOT EXISTS idx_news_qsource_cat ON news(query_source, category);
    """)
    # news — migración: agregar columna `tags` si existía la tabla pero sin ella
    news_cols = _table_cols(conn, 'news')
    if news_cols and 'tags' not in news_cols:
        conn.execute("ALTER TABLE news ADD COLUMN tags TEXT")
        conn.commit()

    # ─── financial_events (Eventos financieros) ────────────────────────────
    # Cache de eventos por ticker: earnings, ex-dividend, payment date, etc.
    # Compartido cross-user — los eventos son data pública. El frontend filtra
    # según el portfolio del user en query time.
    #
    # Para eventos de BONOS (cupones / amortizaciones / vencimientos), NO usamos
    # esta tabla — esos se generan runtime en frontend desde bondSchedule.js
    # (que ya tiene la data, sin duplicar en backend).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS financial_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,            -- 'AAPL', 'MSFT', 'TSLA', etc.
            event_type TEXT NOT NULL,        -- 'earnings' | 'ex_dividend' | 'payment_date' | 'split'
            event_date TEXT NOT NULL,        -- 'YYYY-MM-DD'
            details TEXT,                    -- JSON: {eps_estimate, dividend_amount, ...}
            confirmed INTEGER DEFAULT 0,     -- 1 si la fuente lo confirma, 0 estimado
            source TEXT,                     -- 'yfinance' | 'finnhub' | 'manual'
            fetched_at TEXT NOT NULL,
            UNIQUE(ticker, event_type, event_date)
        );
        CREATE INDEX IF NOT EXISTS idx_events_date ON financial_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_events_ticker ON financial_events(ticker);
    """)

    # ─── bond_cashflow_skips (Phase 3E) ────────────────────────────────────
    # El frontend detecta cobranzas teóricas pendientes comparando el cronograma
    # del bono vs operations existentes. Si el user no recibió ese pago (default,
    # bono ya vendido, etc.) puede marcarlo como "skipped" para que no aparezca
    # más en el inbox. Esta tabla persiste esos skips por (user, broker, asset, date).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bond_cashflow_skips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            broker TEXT NOT NULL,
            asset TEXT NOT NULL,
            date TEXT NOT NULL,          -- fecha del pago teórico saltado
            reason TEXT,                 -- opcional: 'default', 'sold_before', 'already_in_cocos', etc.
            created_at TEXT NOT NULL,
            UNIQUE(user_id, broker, asset, date)
        );
        CREATE INDEX IF NOT EXISTS idx_bond_skips_user ON bond_cashflow_skips(user_id, broker, asset);
    """)
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

    # ─── Watchlist (Home V1.5) ───────────────────────────────────────────────
    # Tickers que el user "sigue" sin tenerlos en portfolio. Se renderiza en el
    # Home como sección dedicada. No tiene relación con `positions` — son
    # universos separados.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            asset_type TEXT,
            added_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
    """)

    # ─── Push notifications (M4) ──────────────────────────────────────────────
    # Una sub por device. Un user puede tener varias (laptop + celular + tablet).
    # endpoint es el URL único que devuelve el browser al subscribirse — distinto
    # por device. Si el endpoint expira (HTTP 410 al hacer send), borramos la sub.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            last_used_at TEXT,
            UNIQUE(user_id, endpoint)
        );
        CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);
    """)

    # ─── AI v2 — cache de análisis + usage diario (Sprint AI v2) ───────────
    # ai_analyses_cache: cache_key = sha256(uid+screen+packet_json). TTL 24h.
    #   Mismo packet → mismo análisis durante 24h, sin nuevo call a LLM.
    # ai_usage_daily: contadores por user por día — alimenta el badge Free
    #   (3/5 análisis) y permite auditar costos por user.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ai_analyses_cache (
            cache_key TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            screen TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            packet_hash TEXT NOT NULL,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            cost_usd_cents INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ai_cache_user_screen
            ON ai_analyses_cache(user_id, screen);
        CREATE INDEX IF NOT EXISTS idx_ai_cache_expires
            ON ai_analyses_cache(expires_at);

        CREATE TABLE IF NOT EXISTS ai_usage_daily (
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            analyses_count INTEGER NOT NULL DEFAULT 0,
            hub_queries_count INTEGER NOT NULL DEFAULT 0,
            -- chat_count: consultas al /api/ai/chat (cuota separada de analyses).
            -- Free/Plus tienen acceso solo a whitelist de 12 preguntas pre-armadas
            -- (cap 6/sem). Pro desbloquea chat libre (cap 60/sem). Agregada en
            -- migración post-launch de chat tiered.
            chat_count INTEGER NOT NULL DEFAULT 0,
            cost_usd_cents INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, date)
        );

        -- ─── ai_tool_usage: contador de uso de tools del chat IA ────────────
        -- Cada vez que _execute_ai_tool corre exitosamente, suma 1. Permite
        -- detectar:
        --   • Tools no usadas (candidatas a borrar)
        --   • Patrones de uso por tier (Pro vs Free)
        --   • Detección de abuso (1 user con miles de calls a un tool)
        -- Admin lee via /api/admin/ai/tool-usage. Sin esto, agregar tools
        -- es disparar en la oscuridad.
        CREATE TABLE IF NOT EXISTS ai_tool_usage (
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, date, tool_name)
        );
        CREATE INDEX IF NOT EXISTS idx_ai_tool_usage_date
            ON ai_tool_usage(date DESC);
        CREATE INDEX IF NOT EXISTS idx_ai_tool_usage_tool
            ON ai_tool_usage(tool_name, date DESC);

        -- ─── yfinance_cache: cache de calls a yfinance (Pack A v2) ──────────
        -- yfinance tarda 1-3s por call. Cuando el chat IA llama tools de
        -- fundamentales/earnings/analysts, esta tabla cachea el payload
        -- normalizado por 6h para que la 2da consulta sobre el mismo ticker
        -- sea instantánea (~10ms desde DB vs 1-3s desde yfinance).
        --
        -- kind enum: 'fundamentals' | 'scorecard' | 'earnings' | 'analysts' | 'profile'
        --   Cada kind tiene shape distinto, serializado a JSON en payload_json.
        --   El consumer (_yf_fetch_cached) parsea y normaliza al leer.
        --
        -- fetched_at en ISO. TTL hardcoded 6h en el lector.
        -- Cleanup: cron diario borra rows > 7 días.
        CREATE TABLE IF NOT EXISTS yfinance_cache (
            ticker TEXT NOT NULL,
            kind TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (ticker, kind)
        );
        CREATE INDEX IF NOT EXISTS idx_yfinance_cache_fetched
            ON yfinance_cache(fetched_at DESC);

        -- ─── ai_user_facts: memoria persistente del coach IA ─────────────────
        -- "Hechos" textuales que el user le aclara al bot ("AL30 lo compré en
        -- broker IOL", "mi sueldo en dolares es 2500"), o que el bot infiere y
        -- confirma. Se inyectan al system prompt del chat para que respuestas
        -- futuras los respeten sin necesidad de re-explicar.
        --
        -- Diseño:
        --   • content: texto libre (cap 280 chars — bullet point conciso)
        --   • source: 'user_correction' (el user lo dijo) |
        --             'ai_inferred' (bot infirió y user confirmó) |
        --             'manual' (admin lo puso)
        --   • created_at: ordenamos DESC para usar siempre los más recientes
        --     si superamos el límite N inyectado al prompt
        --   • is_active: soft-delete (toggle desde UI). Inactivos no se inyectan.
        --
        -- Por qué soft-delete: si el user "olvida" un hecho y luego lo quiere
        -- de vuelta, lo reactiva sin perder created_at original (auditoría).
        CREATE TABLE IF NOT EXISTS ai_user_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user_correction',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ai_user_facts_user_active
            ON ai_user_facts(user_id, is_active, created_at DESC);
        -- Evita que el LLM (o el user) persista el mismo fact 50 veces.
        -- INDEX único parcial sobre (user_id, content) cuando is_active=1.
        -- Soft-deleted no cuenta — el user puede borrar y re-insertar el
        -- mismo content (re-activación implícita). Auditoría #2 H5.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_user_facts_unique_active
            ON ai_user_facts(user_id, content) WHERE is_active=1;

        -- ─── subscriptions: estado de billing por user ──────────────────────
        -- Una fila por user con suscripción ACTIVA o cancelada (histórica).
        -- mp_subscription_id es el preapproval_id de MP. external_reference
        -- es el campo `rendi-{user_id}-{period}` que mandamos a MP.
        -- status: 'pending' (esperando pago), 'authorized' (activa, pagando),
        -- 'paused', 'cancelled', 'failed'.
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mp_subscription_id TEXT,             -- preapproval_id de MP (puede ser NULL hasta que MP confirma)
            external_reference TEXT NOT NULL,    -- 'rendi-{uid}-{period}'
            period TEXT NOT NULL,                -- 'monthly' | 'annual'
            status TEXT NOT NULL DEFAULT 'pending',
            amount_ars INTEGER NOT NULL,         -- monto en pesos cobrado por período
            current_period_start TEXT,           -- ISO date inicio período pagado
            current_period_end TEXT,             -- ISO date fin período pagado (cuando expira Pro)
            next_charge_date TEXT,               -- próxima fecha de cobro automático
            init_point TEXT,                     -- URL del checkout (útil para retry)
            last_payment_id TEXT,                -- último payment_id procesado por webhook
            cancelled_at TEXT,
            -- Idempotencia de emails: cada flag es el timestamp del último envío.
            -- Vacíos = nunca enviado, no-vacíos = ya enviado (no reintentar).
            welcome_email_sent_at TEXT,
            cancellation_email_sent_at TEXT,
            expiration_reminder_sent_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_subscriptions_user
            ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_mp_id
            ON subscriptions(mp_subscription_id);
        CREATE INDEX IF NOT EXISTS idx_subscriptions_status
            ON subscriptions(status);

        -- ─── billing_events: log de webhooks de MP para auditoría ────────────
        -- Cada webhook recibido (incluso los rechazados por signature inválida)
        -- queda registrado. Útil para debug + cumplimiento + reproducción.
        CREATE TABLE IF NOT EXISTS billing_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mp_event_id TEXT,                    -- 'id' del payload top-level
            mp_event_type TEXT,                  -- 'subscription_authorized_payment', 'preapproval', ...
            mp_data_id TEXT,                     -- 'data.id' del payload (preapproval_id o payment_id)
            user_id INTEGER,                     -- decoded desde external_reference (si match)
            signature_valid INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            raw_payload TEXT,                    -- JSON serializado para debug
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_billing_events_user
            ON billing_events(user_id);
        CREATE INDEX IF NOT EXISTS idx_billing_events_mp_data
            ON billing_events(mp_data_id);

        -- ─── plan_events: telemetría del paywall Free → Pro ─────────────────
        -- Cada click en un CTA bloqueado (LockedSection, UpgradeModal, PlanHero)
        -- inserta una fila acá. Permite medir CTR de upgrade por feature/source
        -- y priorizar qué bloqueos convierten más.
        CREATE TABLE IF NOT EXISTS plan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tier TEXT NOT NULL,                  -- 'free' | 'pro' | 'admin' al momento del evento
            event_name TEXT NOT NULL,            -- 'feature_blocked_clicked' | 'upgrade_modal_cta_clicked' | ...
            feature_id TEXT,                     -- 'comportamiento.full' | 'brokers.create' | ...
            source TEXT,                         -- 'behavioral_grid' | 'config_add_broker' | ...
            props_json TEXT,                     -- extras opcionales (JSON serializado)
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_plan_events_user
            ON plan_events(user_id);
        CREATE INDEX IF NOT EXISTS idx_plan_events_feature
            ON plan_events(feature_id, event_name);
        CREATE INDEX IF NOT EXISTS idx_plan_events_created
            ON plan_events(created_at);

        -- ─── email_verification_codes: códigos OTP de 6 dígitos ──────────────
        -- Generado al registrarse o al pedir resend. Vence en 15 min.
        -- used_at se setea al confirmar; rows usadas se mantienen para auditoría
        -- (no se borran). Cleanup en cron de codes > 30 días.
        CREATE TABLE IF NOT EXISTS email_verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code TEXT NOT NULL,                  -- 6 dígitos como string ('384721')
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_email_codes_user_unused
            ON email_verification_codes(user_id, used_at);

        -- ─── password_reset_tokens: magic links para "olvidé mi contraseña" ──
        -- Token es URL-safe random 256-bit (secrets.token_urlsafe(32)).
        -- Vence en 30 min. used_at se setea al confirmar el reset.
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pwd_reset_token ON password_reset_tokens(token);
        CREATE INDEX IF NOT EXISTS idx_pwd_reset_user ON password_reset_tokens(user_id, used_at);

        -- ─── login_history: dispositivos vistos por user (alerta de nuevo login) ──
        -- Si el ua_hash actual no apareció antes para este user, se envía un email
        -- de alerta (después del primer login, que es esperado y no alerta).
        CREATE TABLE IF NOT EXISTS login_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ip TEXT,
            ua_hash TEXT,
            ua_brief TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_login_history_user ON login_history(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_login_history_ua ON login_history(user_id, ua_hash);
    """)

    # subscriptions: columnas de idempotencia de emails (idempotent migration
    # para tablas pre-existentes — las new tienen estas cols ya en el CREATE).
    sub_cols = _table_cols(conn, 'subscriptions')
    for col in ['welcome_email_sent_at', 'cancellation_email_sent_at',
                'expiration_reminder_sent_at']:
        if sub_cols and col not in sub_cols:
            conn.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} TEXT")
    # subscriptions: amount_usd para tracking del valor real cobrado (los planes
    # son USD desde la migración a Rebill — amount_ars queda como legacy).
    if sub_cols and 'amount_usd' not in sub_cols:
        conn.execute("ALTER TABLE subscriptions ADD COLUMN amount_usd REAL")
    conn.commit()

    # ─── Credit window model (Rendi-managed proration) ──────────────────────
    # Cuando un user cambia de plan (Plus ↔ Pro) o cancela mid-período, NO
    # le cobramos de nuevo ni le devolvemos plata. Convertimos el tiempo no
    # consumido en una "ventana de crédito" tracked en `users`:
    #
    #   credit_active_until: timestamp hasta el que el user mantiene tier ≠ free
    #   credit_anchor_*:     plan/period/amount que originó el último anchor
    #
    # Funcionamiento:
    #  • Rebill cobra → grant credit (extend credit_active_until por X días al
    #    daily_rate del plan)
    #  • User cambia plan → convert: remaining_credit_usd al daily_rate nuevo
    #    extiende o acorta credit_active_until
    #  • credit_active_until vence → cron baja a free + email re-suscribirse
    #
    # NULL en estas cols = user nunca tuvo crédito (free o pre-migración).
    user_cols_after = _table_cols(conn, 'users')
    if user_cols_after and 'credit_active_until' not in user_cols_after:
        conn.execute("ALTER TABLE users ADD COLUMN credit_active_until TEXT")
    if user_cols_after and 'credit_anchor_plan' not in user_cols_after:
        conn.execute("ALTER TABLE users ADD COLUMN credit_anchor_plan TEXT")
    if user_cols_after and 'credit_anchor_period' not in user_cols_after:
        conn.execute("ALTER TABLE users ADD COLUMN credit_anchor_period TEXT")
    if user_cols_after and 'credit_anchor_amount_usd' not in user_cols_after:
        conn.execute("ALTER TABLE users ADD COLUMN credit_anchor_amount_usd REAL")
    if user_cols_after and 'credit_anchor_at' not in user_cols_after:
        conn.execute("ALTER TABLE users ADD COLUMN credit_anchor_at TEXT")
    conn.commit()

    # Ledger de movimientos de crédito — audit trail completo de cada
    # grant / consume / plan_change. Permite debuggear "por qué este user
    # tiene X días de crédito" y reconstruir el historial.
    # NOTA migración: el `CREATE UNIQUE INDEX ... ON credit_ledger(payment_id ...)`
    # tiene que ir DESPUÉS del ALTER TABLE que agrega payment_id, porque
    # SQLite valida que la columna exista al crear el índice. Por eso
    # separamos en 3 pasos: CREATE TABLE (con payment_id si es DB nueva) →
    # ALTER TABLE (agrega payment_id si DB vieja) → CREATE INDEX (siempre
    # corre y el IF NOT EXISTS lo hace idempotente).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS credit_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,                  -- 'payment' | 'plan_change' | 'manual_adjust' | 'expiration'
            amount_usd REAL NOT NULL,            -- positivo: crédito agregado; negativo: consumido
            days_delta REAL NOT NULL,            -- positivo: tiempo agregado; negativo: tiempo removido
            from_plan TEXT,                      -- 'plus' | 'pro' | NULL
            from_period TEXT,                    -- 'monthly' | 'annual' | NULL
            to_plan TEXT,
            to_period TEXT,
            active_until_before TEXT,            -- ISO ts antes del cambio
            active_until_after TEXT,             -- ISO ts después del cambio
            source_subscription_id TEXT,         -- Rebill subscription_id si aplica
            payment_id TEXT,                     -- Rebill payment_id (idempotency key)
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_credit_ledger_user ON credit_ledger(user_id, created_at DESC);
    """)
    conn.commit()

    # Migración: agregar payment_id si la tabla ya existía sin esa columna.
    # CRÍTICO: este ALTER tiene que correr ANTES del CREATE UNIQUE INDEX
    # de abajo, sino el CREATE INDEX falla con "no such column: payment_id".
    credit_cols = _table_cols(conn, 'credit_ledger')
    if credit_cols and 'payment_id' not in credit_cols:
        conn.execute("ALTER TABLE credit_ledger ADD COLUMN payment_id TEXT")
        conn.commit()

    # Ahora SÍ podemos crear el partial unique index (la columna existe).
    # Idempotency: prevenir crédito doble si Rebill manda el mismo
    # payment.created 2 veces (retry por timeout, race del LB).
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_credit_ledger_payment_dedup
            ON credit_ledger(source_subscription_id, payment_id, kind)
            WHERE payment_id IS NOT NULL AND source_subscription_id IS NOT NULL
    """)
    conn.commit()

    # ─── Backfill de crédito para subs pre-proration ───────────────────────
    # Users que pagaron antes del commit a09891a no tienen credit_active_until
    # poblado — el _rebill_activate viejo no llamaba a grant_payment_credit.
    # Inferimos la ventana desde:
    #   • subscriptions.current_period_end si está
    #   • sino, subscriptions.created_at + period_days
    # Idempotente: solo aplica si credit_active_until IS NULL.
    rows = conn.execute(
        """SELECT u.id AS user_id, u.tier,
                  s.id AS sub_id, s.mp_subscription_id, s.period,
                  s.current_period_end, s.created_at AS sub_created_at,
                  s.external_reference
           FROM users u
           JOIN subscriptions s ON s.user_id = u.id
           WHERE u.tier IN ('plus', 'pro')
             AND u.credit_active_until IS NULL
             AND s.status = 'authorized'
        """
    ).fetchall()
    if rows:
        from datetime import datetime as _dt, timedelta as _td
        _period_days = {'monthly': 30.0, 'annual': 365.0}
        _prices = {('plus','monthly'): 4.0, ('plus','annual'): 40.0,
                   ('pro','monthly'): 9.0, ('pro','annual'): 90.0}
        seen_users = set()
        for r in rows:
            uid = r['user_id']
            if uid in seen_users:
                continue
            seen_users.add(uid)
            plan = r['tier']
            period = r['period'] or 'monthly'
            # Determinar active_until: si tenemos current_period_end usamos eso;
            # si no, asumimos que el período arrancó en sub.created_at.
            until_iso = None
            if r['current_period_end']:
                until_iso = r['current_period_end']
            else:
                try:
                    started = _dt.fromisoformat(
                        (r['sub_created_at'] or '').replace('Z','').split('.')[0]
                    )
                    period_days = _period_days.get(period, 30.0)
                    until_iso = (started + _td(days=period_days)).isoformat()
                except Exception:
                    # Fallback: NOW + period_days (peor caso, el user igual no pierde nada)
                    until_iso = (_dt.utcnow() + _td(days=_period_days.get(period, 30.0))).isoformat()
            amount = _prices.get((plan, period), 0.0)
            now_iso = _dt.utcnow().isoformat()
            conn.execute(
                """UPDATE users
                   SET credit_active_until = ?,
                       credit_anchor_plan = ?,
                       credit_anchor_period = ?,
                       credit_anchor_amount_usd = ?,
                       credit_anchor_at = ?
                   WHERE id = ?""",
                (until_iso, plan, period, amount, now_iso, uid),
            )
            conn.execute(
                """INSERT INTO credit_ledger
                       (user_id, kind, amount_usd, days_delta,
                        from_plan, from_period, to_plan, to_period,
                        active_until_before, active_until_after,
                        source_subscription_id, note)
                   VALUES (?, 'manual_adjust', ?, 0, NULL, NULL, ?, ?, NULL, ?, ?, ?)""",
                (
                    uid, amount, plan, period, until_iso,
                    r['mp_subscription_id'] or None,
                    f"Backfill pre-proration: inferido desde sub {r['mp_subscription_id']}",
                ),
            )
        conn.commit()

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

    # Migración: ai_usage_daily.chat_count (agregada al introducir chat tiered).
    # DBs prod existentes no tienen esta columna — ADD COLUMN con default 0.
    ai_usage_cols = _table_cols(conn, 'ai_usage_daily')
    if ai_usage_cols and 'chat_count' not in ai_usage_cols:
        conn.execute("ALTER TABLE ai_usage_daily ADD COLUMN chat_count INTEGER NOT NULL DEFAULT 0")

    # Migración: columna broker en import_normalized_tx (agregada después de la
    # versión inicial de las tablas).
    norm_cols = _table_cols(conn, 'import_normalized_tx')
    if norm_cols and 'broker' not in norm_cols:
        conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN broker TEXT NOT NULL DEFAULT ''")
    # Migración: fingerprint para detectar duplicados a nivel fila entre imports
    norm_cols = _table_cols(conn, 'import_normalized_tx')
    if norm_cols and 'fingerprint' not in norm_cols:
        conn.execute("ALTER TABLE import_normalized_tx ADD COLUMN fingerprint TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_import_norm_fingerprint ON import_normalized_tx(fingerprint)")

    # Migración: route_by_currency en import_batches. Cuando es 1 y el broker
    # del batch es ARS, las filas USD/USDT se ruteán al sub-broker USD al persistir.
    batch_cols = _table_cols(conn, 'import_batches')
    if batch_cols and 'route_by_currency' not in batch_cols:
        conn.execute("ALTER TABLE import_batches ADD COLUMN route_by_currency INTEGER NOT NULL DEFAULT 0")

    # Mapping templates guardados por usuario. Sirve para reusar el mapeo
    # de columnas entre imports recurrentes (ej.: usuario que importa export
    # de IBKR mensualmente, mapea una vez y reusa).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS import_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            mapping_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_import_mappings_user ON import_mappings(user_id);
    """)

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


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> int:
    # Preferimos la cookie HttpOnly (web), fallback al Authorization header
    # (clientes no-browser / back-compat). El que esté primero gana.
    token = request.cookies.get(COOKIE_NAME)
    if not token and creds:
        token = creds.credentials
    if not token:
        raise HTTPException(401, "Token inválido")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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

# Sets de brokers cripto vs tradicionales — usado para inferir currency al
# auto-crear un broker desde un import o desde la migración del admin.
# Lemon aparece en ambos sets a propósito (Lemon Cash maneja ARS y crypto):
# acá lo dejamos en ARS para fidelidad histórica; si en algún momento Lemon
# tiene un parser propio cripto, ese parser hardcodea el nombre.
CRYPTO_BROKER_NAMES = {'binance', 'coinbase', 'kraken', 'bybit', 'kucoin',
                       'bitget', 'okx', 'huobi', 'gemini', 'crypto.com',
                       'ripio', 'buenbit', 'satoshitango', 'fiwind'}

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


class VerifyEmailIn(BaseModel):
    email: str = Field(..., max_length=254)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendVerificationIn(BaseModel):
    email: str = Field(..., max_length=254)


class ForgotPasswordIn(BaseModel):
    email: str = Field(..., max_length=254)


class ResetPasswordIn(BaseModel):
    token: str = Field(..., min_length=20, max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)


# ─── Email verification + password reset helpers ────────────────────────────

EMAIL_CODE_TTL_MINUTES = 15
EMAIL_CODE_RESEND_COOLDOWN_SECONDS = 60
PASSWORD_RESET_TTL_MINUTES = 30


def _frontend_url() -> str:
    """Base URL del frontend para construir magic links (password reset, etc).

    Para dev: http://localhost:5173. Para prod: https://rendi.finance (cambiar
    en el .env vía MP_FRONTEND_BASE_URL — el nombre es histórico, se usa
    también para no-billing)."""
    return (os.environ.get("MP_FRONTEND_BASE_URL") or "http://localhost:5173").rstrip("/")


def _gen_reset_token() -> str:
    """URL-safe random ~43 chars (~256 bits de entropía)."""
    return secrets.token_urlsafe(32)


# ─── Login history / device tracking ─────────────────────────────────────────
# El UA fingerprint se hashea — si la DB se filtra, no exponemos el UA en
# plano. ua_brief es el resumen legible que mostramos al user en el email.

def _ua_brief(ua: Optional[str]) -> str:
    """Resume el User-Agent en 'Chrome 124 / macOS' para mostrar al user."""
    if not ua:
        return "Dispositivo desconocido"
    import re
    m = re.search(r'(Chrome|Firefox|Safari|Edge|Opera)/(\d+)', ua)
    browser = f"{m.group(1)} {m.group(2)}" if m else "Browser"
    if "Windows" in ua:        os_name = "Windows"
    elif "Mac OS X" in ua or "Macintosh" in ua: os_name = "macOS"
    elif "Android" in ua:      os_name = "Android"
    elif "iPhone" in ua or "iPad" in ua: os_name = "iOS"
    elif "Linux" in ua:        os_name = "Linux"
    else:                       os_name = "Sistema operativo desconocido"
    return f"{browser} / {os_name}"


def _ua_hash(ua: Optional[str]) -> str:
    if not ua:
        return ""
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()[:32]


def _client_ip(request: Request) -> str:
    """Extrae la IP real respetando X-Forwarded-For (Vercel/Railway proxy)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _record_login_and_maybe_alert(
    conn,
    user_id: int,
    email: str,
    name: Optional[str],
    request: Request,
) -> None:
    """Inserta el login en login_history. Si el dispositivo (ua_hash) no fue
    visto antes para este user — y NO es el primer login ever — manda un
    email de alerta. Nunca tira: si la alerta falla, el login sigue OK."""
    try:
        ua = request.headers.get("user-agent", "")
        ip = _client_ip(request)
        uah = _ua_hash(ua)
        uab = _ua_brief(ua)

        total_prev = conn.execute(
            "SELECT COUNT(*) AS c FROM login_history WHERE user_id=?", (user_id,)
        ).fetchone()["c"]

        is_new_device = False
        if total_prev > 0:
            prev = conn.execute(
                "SELECT id FROM login_history WHERE user_id=? AND ua_hash=? LIMIT 1",
                (user_id, uah),
            ).fetchone()
            is_new_device = not prev

        conn.execute(
            "INSERT INTO login_history (user_id, ip, ua_hash, ua_brief) VALUES (?,?,?,?)",
            (user_id, ip, uah, uab),
        )
        conn.commit()

        if is_new_device:
            try:
                from billing import emails
                emails.send_new_login_alert(
                    to=email,
                    user_name=(name or email.split("@")[0]),
                    device=uab,
                    ip=ip or "desconocida",
                    when=datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
                )
            except Exception as ex:
                log.error("Login alert email failed for uid=%s: %s", user_id, ex)
    except Exception as ex:
        log.error("login_history record failed for uid=%s: %s", user_id, ex)


def _gen_verification_code() -> str:
    """6 dígitos, sin ceros al inicio (más fácil de tipear y se ve completo)."""
    return f"{secrets.randbelow(900000) + 100000}"


def _create_verification_code(conn, user_id: int) -> str:
    """Invalida códigos previos del user e inserta uno nuevo. Devuelve el código."""
    from datetime import datetime, timedelta
    code = _gen_verification_code()
    expires = (datetime.utcnow() + timedelta(minutes=EMAIL_CODE_TTL_MINUTES)).isoformat()
    with conn:
        # Invalidamos códigos previos (que no estén usados) para evitar
        # que un user tenga 5 códigos válidos simultáneos
        conn.execute(
            """UPDATE email_verification_codes SET used_at = datetime('now')
               WHERE user_id = ? AND used_at IS NULL""",
            (user_id,),
        )
        conn.execute(
            """INSERT INTO email_verification_codes (user_id, code, expires_at)
               VALUES (?, ?, ?)""",
            (user_id, code, expires),
        )
    return code


def _send_verification_email(conn, user_id: int, email: str, name: Optional[str]) -> None:
    """Genera el código y manda el email (best-effort, no levanta si email falla)."""
    from billing import emails
    code = _create_verification_code(conn, user_id)
    display_name = name or (email.split("@")[0] if email else "Inversor")
    try:
        emails.send_verification_code(
            to=email,
            user_name=display_name,
            code=code,
            expires_minutes=EMAIL_CODE_TTL_MINUTES,
        )
    except Exception as ex:
        log.error("Verification email failed for uid=%s: %s", user_id, ex)


@app.post("/api/auth/register")
def register(data: RegisterIn, request: Request, response: Response):
    is_admin_signup = _is_admin_email(data.email)
    # Si registro está cerrado, solo se permite el registro del admin (idempotente).
    if not ALLOW_REGISTRATION and not is_admin_signup:
        raise HTTPException(403, "Registro deshabilitado")
    _check_rate_limit(request, max_calls=5, window_seconds=300, suffix="register")  # 5 / 5min por IP

    conn = get_db()
    try:
        h = pwd_ctx.hash(data.password)
        # admin se auto-aprueba + auto-verifica; resto queda pending + sin verificar
        approved = 1 if is_admin_signup else 0
        email_verified = 1 if is_admin_signup else 0
        cur = conn.execute(
            """INSERT INTO users (email, name, password_hash, is_admin, approved, email_verified)
               VALUES (?,?,?,?,?,?)""",
            (data.email, data.name, h, 1 if is_admin_signup else 0, approved, email_verified),
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
                bname_lower = bname.lower()
                # Inferencia: ARS para brokers AR conocidos, USDT para crypto-
                # native, USD por default para el resto (Schwab, IBKR, etc.).
                if bname_lower in ARS_BROKER_NAMES:
                    currency = 'ARS'
                elif bname_lower in CRYPTO_BROKER_NAMES:
                    currency = 'USDT'
                else:
                    currency = 'USD'
                conn.execute(
                    "INSERT OR IGNORE INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                    (uid, bname, currency),
                )

        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_mep', '1415', ?)", (uid,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_blue', '1415', ?)", (uid,))

        conn.commit()

        # User NO admin → mandamos código de verificación al email registrado.
        # NO devolvemos token todavía — el frontend redirige a /verify-email.
        if not is_admin_signup:
            _send_verification_email(conn, uid, data.email, data.name)
            conn.close()
            return {
                "needs_verification": True,
                "email": data.email,
                "message": "Te enviamos un código a tu email para confirmar tu cuenta.",
            }

        # Admin: bypass verificación + token directo (acceso interno)
        pca_row = conn.execute("SELECT password_changed_at FROM users WHERE id=?", (uid,)).fetchone()
        conn.close()
        token = create_token(uid, pca_row["password_changed_at"] if pca_row else None)
        set_auth_cookie(response, token)
        return {
            "token": token,
            "name": data.name or data.email,
            "is_admin": True,
        }
    except sqlite3.IntegrityError:
        conn.close()
        # Estructurado para que el frontend pueda detectar el caso y ofrecer
        # un botón "Ir al login" en lugar del flow de error genérico.
        raise HTTPException(409, {
            "code": "EMAIL_ALREADY_REGISTERED",
            "error": "Este email ya está registrado.",
            "email": data.email,
        })


@app.post("/api/auth/login")
def login(data: LoginIn, request: Request, response: Response):
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
    # Email verification PRIMERO — el user debe probar que el email es suyo
    # antes que cualquier otro gate (incluso approval del admin).
    if row["email_verified"] == 0:
        conn.close()
        raise HTTPException(403, {
            "code": "EMAIL_NOT_VERIFIED",
            "error": "Confirmá tu email antes de ingresar.",
            "email": email_norm,
        })
    if not row["approved"]:
        conn.close()
        raise HTTPException(403, "Cuenta pendiente de aprobación por el administrador")
    # Update last_login
    try:
        conn.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (row["id"],))
        conn.commit()
    except Exception:
        pass
    # Registrar el login en login_history; si el dispositivo es nuevo (ua_hash
    # no visto antes), dispara email de alerta. Nunca tira.
    _record_login_and_maybe_alert(conn, row["id"], row["email"], row["name"], request)
    conn.close()
    token = create_token(row["id"], row["password_changed_at"])
    set_auth_cookie(response, token)
    # Mantenemos `token` en el body por back-compat (clientes legacy / mobile).
    # El frontend web ahora usa la cookie HttpOnly y puede ignorarlo.
    return {
        "token": token,
        "name": row["name"] or row["email"],
        "is_admin": bool(row["is_admin"]),
    }


@app.post("/api/auth/logout")
def logout(response: Response):
    """Borra la cookie de auth. Para clientes que usan Bearer header, esto es
    no-op server-side (el token sigue vigente hasta exp) — sirven con cambiar
    la contraseña si querés invalidar todo."""
    clear_auth_cookie(response)
    return {"ok": True}


@app.post("/api/auth/verify-email")
def verify_email(data: VerifyEmailIn, request: Request, response: Response):
    """Confirma el email del user con un código OTP de 6 dígitos.

    Si el código es válido (existe, no expiró, no fue usado), marcamos
    `email_verified=1` e issue token (logueamos al user).

    SECURITY: rate limit por email (no global) para evitar que un atacante
    bloquee la verificación de todos los users iterando 15 attempts/min."""
    email_norm = data.email.strip().lower()
    _check_rate_limit(request, max_calls=5, window_seconds=60, suffix=f"verify_email:{email_norm}")
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, name, email_verified, password_changed_at FROM users WHERE email=?",
            (email_norm,),
        ).fetchone()
        if not user:
            # Mensaje genérico para no leakear si el email existe
            raise HTTPException(400, "Código inválido o expirado")
        if user["email_verified"]:
            raise HTTPException(400, "Tu cuenta ya está verificada. Iniciá sesión.")

        # Buscar el código más reciente no usado y no vencido para este user
        row = conn.execute(
            """SELECT id, code, expires_at FROM email_verification_codes
               WHERE user_id = ? AND used_at IS NULL
               ORDER BY created_at DESC LIMIT 1""",
            (user["id"],),
        ).fetchone()
        if not row:
            raise HTTPException(400, "Código inválido o expirado")
        # Constant-time compare para evitar side-channel timing.
        if not hmac.compare_digest(str(row["code"]), str(data.code)):
            raise HTTPException(400, "Código inválido o expirado")
        # Vence?
        from datetime import datetime
        try:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires < datetime.utcnow():
                raise HTTPException(400, "Código inválido o expirado")
        except (ValueError, TypeError):
            raise HTTPException(400, "Código inválido o expirado")

        with conn:
            conn.execute(
                "UPDATE email_verification_codes SET used_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
            conn.execute(
                "UPDATE users SET email_verified = 1 WHERE id = ?",
                (user["id"],),
            )
        # Verificar email = login implícito. Registramos en login_history
        # también (igual no manda alerta porque es el primer login post-signup).
        _record_login_and_maybe_alert(conn, user["id"], email_norm, user["name"], request)
        conn.close()
        token = create_token(user["id"], user["password_changed_at"])
        set_auth_cookie(response, token)
        return {
            "token": token,
            "name": user["name"] or email_norm,
            "verified": True,
        }
    except HTTPException:
        conn.close()
        raise


@app.post("/api/auth/resend-verification")
def resend_verification(data: ResendVerificationIn, request: Request):
    """Genera un código nuevo y lo manda al email del user.

    Rate limit: 1 request cada 60s + 5 por hora por IP. Si el user ya
    está verificado, devolvemos OK sin mandar (idempotente)."""
    _check_rate_limit(request, max_calls=1, window_seconds=60, suffix=f"resend:{data.email.lower()}")
    _check_rate_limit(request, max_calls=5, window_seconds=3600, suffix=f"resend_hourly:{data.email.lower()}")
    email_norm = data.email.strip().lower()
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, name, email, email_verified FROM users WHERE email=?",
            (email_norm,),
        ).fetchone()
        # Respuesta genérica para no leakear si el email existe
        if not user or user["email_verified"]:
            return {"sent": True, "message": "Si la cuenta existe, te enviamos un código nuevo."}
        _send_verification_email(conn, user["id"], user["email"], user["name"])
        return {"sent": True, "message": "Te enviamos un código nuevo."}
    finally:
        conn.close()


@app.post("/api/auth/forgot-password")
def forgot_password(data: ForgotPasswordIn, request: Request):
    """Inicia el flow de reset de contraseña. Manda un magic link al email
    del user (si existe). Respuesta SIEMPRE 200 con mensaje genérico para
    no leakear qué emails están registrados.

    Rate limit: 3 requests/hora por email + 5 por 5min por IP para mitigar
    spam de password reset (atacante haciendo flood al inbox del user)."""
    _check_rate_limit(request, max_calls=5, window_seconds=300, suffix="forgot_pw_ip")
    email_norm = data.email.strip().lower()
    _check_rate_limit(request, max_calls=3, window_seconds=3600,
                     suffix=f"forgot_pw_email:{email_norm}")

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, name, email FROM users WHERE email=?", (email_norm,)
        ).fetchone()
        if user:
            from datetime import datetime, timedelta
            token = _gen_reset_token()
            expires = (datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)).isoformat()
            with conn:
                # Invalidamos tokens previos del user (un solo link válido a la vez)
                conn.execute(
                    """UPDATE password_reset_tokens SET used_at = datetime('now')
                       WHERE user_id = ? AND used_at IS NULL""",
                    (user["id"],),
                )
                conn.execute(
                    """INSERT INTO password_reset_tokens (user_id, token, expires_at)
                       VALUES (?, ?, ?)""",
                    (user["id"], token, expires),
                )
            reset_url = f"{_frontend_url()}/reset-password?token={token}"
            try:
                from billing import emails
                emails.send_password_reset(
                    to=user["email"],
                    user_name=(user["name"] or user["email"].split("@")[0]),
                    reset_url=reset_url,
                    expires_minutes=PASSWORD_RESET_TTL_MINUTES,
                )
            except Exception as ex:
                log.error("Password reset email failed for uid=%s: %s", user["id"], ex)
        # Respuesta SIEMPRE genérica para no leakear si el email existe
        return {
            "sent": True,
            "message": "Si la cuenta existe, te enviamos un link para restablecer la contraseña.",
        }
    finally:
        conn.close()


@app.post("/api/auth/reset-password")
def reset_password(data: ResetPasswordIn, request: Request, response: Response):
    """Confirma el reset usando el token + nueva contraseña.

    Valida que el token exista, no esté usado y no haya vencido.
    Actualiza el password_hash, marca el token usado, y rota el JWT
    (vía password_changed_at) para invalidar sesiones viejas."""
    _check_rate_limit(request, max_calls=10, window_seconds=300, suffix="reset_pw_ip")
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT id, user_id, expires_at, used_at FROM password_reset_tokens
               WHERE token = ?""",
            (data.token,),
        ).fetchone()
        if not row or row["used_at"]:
            raise HTTPException(400, "Link inválido o ya usado. Pedí uno nuevo.")
        from datetime import datetime
        try:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires < datetime.utcnow():
                raise HTTPException(400, "El link expiró. Pedí uno nuevo.")
        except (ValueError, TypeError):
            raise HTTPException(400, "Link inválido")

        # Hash nueva password + bump password_changed_at (invalida JWTs viejos)
        new_hash = pwd_ctx.hash(data.new_password)
        with conn:
            conn.execute(
                """UPDATE users SET password_hash = ?, password_changed_at = datetime('now')
                   WHERE id = ?""",
                (new_hash, row["user_id"]),
            )
            conn.execute(
                "UPDATE password_reset_tokens SET used_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        # Emitir token nuevo para que el user quede logueado tras el reset (UX)
        user = conn.execute(
            "SELECT name, email, password_changed_at FROM users WHERE id = ?",
            (row["user_id"],),
        ).fetchone()
        token = create_token(row["user_id"], user["password_changed_at"])
        set_auth_cookie(response, token)
        return {
            "token": token,
            "name": user["name"] or user["email"],
            "message": "Contraseña restablecida.",
        }
    except HTTPException:
        conn.close()
        raise
    finally:
        try: conn.close()
        except Exception: pass


@app.get("/api/auth/me")
def me(uid: int = Depends(get_current_user)):
    from ai import quota
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, name, is_admin, created_at, last_login_at FROM users WHERE id=?", (uid,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    d = dict(row)
    d["is_admin"] = bool(d["is_admin"])
    d["tier"] = quota.get_tier(conn, uid)

    # Estado de la suscripción "relevante". Priorizamos authorized > cancelled
    # > superseded > otros porque cycles previos pueden dejar varias rows
    # pending (intentos abandonados) que un simple ORDER BY created_at DESC
    # devolvería antes que la authorized real.
    #   • status='authorized' → user con sub Rebill activa, autorrenovable
    #   • status='cancelled'  → user canceló manualmente, en grace period
    #   • status='superseded' → user cambió de plan; vive en modo crédito
    sub = conn.execute(
        """SELECT status, current_period_end, cancelled_at, period FROM subscriptions
           WHERE user_id = ? AND status IN ('authorized', 'cancelled', 'superseded', 'paused', 'retrying')
           ORDER BY
               CASE status
                   WHEN 'authorized' THEN 0
                   WHEN 'retrying' THEN 1
                   WHEN 'paused' THEN 2
                   -- IMPORTANTE: 'superseded' va ANTES que 'cancelled' porque
                   -- semánticamente representa el estado actual (cambio de
                   -- plan reciente) mientras que 'cancelled' suele ser una
                   -- row histórica anterior al cambio. Si el user hizo
                   -- cancel → reactivó → change-plan, hay rows en ambos
                   -- estados. La que importa es la del cambio (superseded).
                   WHEN 'superseded' THEN 3
                   WHEN 'cancelled' THEN 4
                   ELSE 9
               END,
               created_at DESC
           LIMIT 1""",
        (uid,),
    ).fetchone()
    d["subscription_status"] = sub["status"] if sub else None
    d["subscription_period_end"] = sub["current_period_end"] if sub else None
    d["subscription_cancelled_at"] = sub["cancelled_at"] if sub else None
    d["subscription_period"] = sub["period"] if sub else None

    # Estado del crédito (modelo Rendi-managed proration). Source of truth
    # para acceso al tier — si credit_active_until vence y no hay sub
    # authorized, el cron baja a free. El frontend usa esto para mostrar
    # "Tu plan vence en X días" y la UI de cambio de plan con preview.
    try:
        from billing import credits as billing_credits
        cstate = billing_credits.get_credit_state(conn, uid)
        d["credit_active_until"]   = cstate["active_until"]
        d["credit_days_remaining"] = cstate["days_remaining"]
        d["credit_remaining_usd"]  = cstate["remaining_usd"]
        d["credit_anchor_plan"]    = cstate["anchor_plan"]
        d["credit_anchor_period"]  = cstate["anchor_period"]
    except Exception as ex:
        log.warning("credits.get_credit_state failed for user %s: %s", uid, ex)
        d["credit_active_until"]   = None
        d["credit_days_remaining"] = 0
        d["credit_remaining_usd"]  = 0
        d["credit_anchor_plan"]    = None
        d["credit_anchor_period"]  = None

    # access_mode: estado canónico del acceso del user al tier. Single source
    # of truth para el frontend — evita lógica condicional duplicada en cada
    # página. Valores posibles:
    #   • 'authorized'  → user con sub Rebill activa que se va a renovar sola
    #   • 'credit_only' → user accedió a tier vía change-plan / cancel; sin
    #                     sub Rebill que renueve, vive del crédito hasta que
    #                     se acabe (entonces va a 'free' o tiene que re-sub)
    #   • 'cancelled'   → user canceló manualmente, sigue en grace period
    #                     hasta credit_active_until
    #   • 'free'        → tier = free (o anulado)
    sub_status = d.get("subscription_status")
    cred_active = bool(d.get("credit_days_remaining", 0) > 0)
    tier = d.get("tier")
    if tier in (None, "free"):
        d["access_mode"] = "free"
    elif sub_status == "authorized":
        d["access_mode"] = "authorized"
    elif sub_status == "cancelled" and cred_active:
        d["access_mode"] = "cancelled"
    elif sub_status == "superseded" and cred_active:
        d["access_mode"] = "credit_only"
    elif cred_active:
        # Edge case: tiene crédito pero no hay sub trackeable (legacy?)
        d["access_mode"] = "credit_only"
    else:
        # Sin crédito + sin sub authorized → en transición; cron va a bajar
        # a free en próximo run. Trato como cancelled visualmente para que
        # el user vea "expirado" sin sorpresas.
        d["access_mode"] = "cancelled"

    conn.close()
    return d


@app.post("/api/auth/change-password")
def change_password(data: ChangePasswordIn, response: Response, uid: int = Depends(get_current_user)):
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
    # Token nuevo con el pca actualizado para que la sesión actual siga válida
    # (los JWTs viejos del mismo user quedaron invalidados al bumpear pca).
    token = create_token(uid, pca)
    set_auth_cookie(response, token)
    return {"ok": True, "token": token}


# ─── Investor profile (test de 7 preguntas para enriquecer el Coach IA) ─────

# Valores aceptados por cada pregunta. Si el frontend manda algo distinto, lo
# rechazamos para evitar prompt injection y mantener consistencia con el system
# prompt de Coach IA.
_INVESTOR_PROFILE_OPTS = {
    "horizon":     {"short", "medium", "long"},
    "drawdown":    {"sell_all", "sell_some", "hold", "buy_more"},
    "goal":        {"retirement", "freedom", "learn", "hobby", "specific_purchase"},
    "style":       {"passive", "active", "mixed"},
    "net_worth":   {"under_10", "10_to_30", "30_to_60", "over_60"},
    "liquidity":   {"yes", "no", "partial"},
    "experience":  {"first_time", "under_2", "2_to_5", "over_5"},
}


class InvestorProfileIn(BaseModel):
    horizon: Optional[str] = None
    drawdown: Optional[str] = None
    goal: Optional[str] = None
    style: Optional[str] = None
    net_worth: Optional[str] = None
    liquidity: Optional[str] = None
    experience: Optional[str] = None


@app.get("/api/auth/investor-profile")
def get_investor_profile(uid: int = Depends(get_current_user)):
    """Devuelve el perfil de inversor del user (o {} si no completó el test)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT investor_profile FROM users WHERE id=?", (uid,)
        ).fetchone()
        if not row or not row["investor_profile"]:
            return {}
        try:
            return json.loads(row["investor_profile"])
        except (ValueError, TypeError):
            return {}
    finally:
        conn.close()


@app.post("/api/auth/investor-profile")
def save_investor_profile(data: InvestorProfileIn, uid: int = Depends(get_current_user)):
    """Guarda/actualiza el perfil. Valida valores contra el whitelist para
    evitar basura/inyecciones que terminen en el prompt de IA."""
    payload = data.model_dump(exclude_none=True)
    clean: Dict[str, str] = {}
    for key, val in payload.items():
        allowed = _INVESTOR_PROFILE_OPTS.get(key)
        if not allowed:
            continue
        if isinstance(val, str) and val in allowed:
            clean[key] = val
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET investor_profile=? WHERE id=?",
            (json.dumps(clean) if clean else None, uid),
        )
        conn.commit()
        # El perfil se inyecta en el system prompt de TODOS los packets de IA.
        # Sin invalidación, los análisis cacheados (24h TTL) siguen mostrando
        # interpretación del perfil ANTERIOR aunque el user lo haya cambiado.
        # Auditoría #2 M1.
        _ai_cache_invalidate(uid)
        return {"ok": True, "profile": clean}
    finally:
        conn.close()


# ─── Brokers ─────────────────────────────────────────────────────────────────

class BrokerIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_STR)
    currency: str = Field('USDT')
    parent_broker_id: Optional[int] = None

    @field_validator('currency')
    @classmethod
    def valid_currency(cls, v):
        # USDT (exchanges crypto) y USD (brokers tradicionales) ambos representan
        # 1 USD a efectos de valuación — la diferencia es solo semántica.
        if v not in ('USDT', 'USD', 'ARS'):
            raise ValueError('currency debe ser USDT, USD o ARS')
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
    from ai import plan
    conn = get_db()
    # Feature gate: Free permite 1 broker máximo. Grandfather: usuarios
    # preexistentes con N > 1 conservan sus brokers pero no agregan más
    # hasta upgrade. Admin/Pro: sin tope.
    allowed, quota_info = plan.check_broker_quota(conn, uid)
    if not allowed:
        conn.close()
        raise HTTPException(403, {
            "error": (
                f"El plan Free permite 1 broker. Pasate a Rendi Pro para "
                f"conectar todos tus brokers."
            ),
            "quota": quota_info,
            "upgrade": {
                "available": quota_info["tier"] == "free",
                "current_tier": quota_info["tier"],
                "target_tier": "pro",
                "feature": "brokers.create",
                "benefits": [
                    "Brokers ilimitados",
                    "10× más análisis IA (60/sem vs 6/sem)",
                    "Comportamiento completo (todas las tags)",
                    "Reportes históricos + Distribución por activo",
                ],
            },
        })
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
        # Auto-crear posición cash con saldo 0. Esto evita el gap donde el
        # usuario crea un broker nuevo y no tiene cómo hacer su primer
        # depósito (el botón 'Depositar' vive dentro del menú de cada
        # posición). Con la cash position pre-creada, el menú aparece
        # inmediatamente con saldo $0.
        cash_asset = 'ARS' if data.currency == 'ARS' else ('USD' if data.currency == 'USD' else 'USDT')
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
               VALUES (?, ?, ?, 1, 0, 0)""",
            (uid, data.name, cash_asset),
        )
        conn.commit()
        # Safe: lastrowid always belongs to this user (just inserted)
        row = conn.execute("SELECT * FROM brokers WHERE id=? AND user_id=?", (cur.lastrowid, uid)).fetchone()
        conn.close()
        _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
    return dict(row)


@app.delete("/api/brokers/{bid}")
def delete_broker(bid: int, uid: int = Depends(get_current_user)):
    """Borra el broker + cascade delete de toda su data asociada.

    Antes solo borraba el row de brokers, dejando operations / positions /
    monthly_entries / snapshots huérfanos con `broker = name` (texto) que
    seguían sumando en aggregates y dashboard. Ahora limpia en cascada.

    Los batches del broker se marcan como 'reverted' (no se borran físicamente
    para mantener auditoría); las normalized_tx asociadas siguen en disco pero
    no afectan ningún calculo porque el broker ya no existe.
    """
    conn = get_db()
    try:
        broker_row = conn.execute(
            "SELECT name FROM brokers WHERE id=? AND user_id=?", (bid, uid),
        ).fetchone()
        if not broker_row:
            return {"ok": True}  # idempotente — no error si ya no existe
        broker_name = broker_row["name"]

        with conn:
            conn.execute(
                "DELETE FROM operations WHERE user_id=? AND broker=?", (uid, broker_name),
            )
            conn.execute(
                "DELETE FROM positions WHERE user_id=? AND broker=?", (uid, broker_name),
            )
            conn.execute(
                "DELETE FROM monthly_entries WHERE user_id=? AND broker=?", (uid, broker_name),
            )
            conn.execute(
                """UPDATE import_batches
                   SET status='reverted', reverted_at=datetime('now')
                   WHERE user_id=? AND broker=? AND status IN ('confirmed','preview')""",
                (uid, broker_name),
            )
            conn.execute("DELETE FROM brokers WHERE id=? AND user_id=?", (bid, uid))

        # Recalc global aggregates (el broker 'global' sumaba el broker borrado)
        try:
            with conn:
                _recalc_pnl_realized_from_ops(conn, uid)
        except Exception as ex:
            log.error("Recalc tras delete_broker falló: %s", ex)

        _ai_cache_invalidate(uid)
        return {"ok": True}
    finally:
        conn.close()


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
    ccl = _fetch_dolar("contadoconliqui")
    cripto = _fetch_dolar("cripto")
    data = {
        "blue": blue,
        "mep": mep,
        "ccl": ccl,
        "cripto": cripto,
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }
    if blue or mep or ccl or cripto:
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
_bench_refresh_inflight = {"flag": False}  # SWR: evita disparar múltiples refreshes
BENCH_TTL = 3600  # 1 hour

# Executor dedicado para paralelizar los 3 fetches externos del /api/benchmarks
# + para el refresh SWR background. Wall time del fetch coordinado:
#   • Secuencial: ~45s peor caso
#   • Paralelo (este executor): ~15-20s
# Patrón módulo-level (no `with`) para evitar el bug de shutdown documentado
# en el módulo (ver _YFThreadPoolExecutor más abajo).
_bench_fetch_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bench-fetch")


def _benchmarks_fetch_and_cache():
    """Fetch los 7 benchmarks externos en paralelo y persiste en cache.
    Llamado tanto del cold-start sincrónico como del SWR background refresh.

    Benchmarks:
      • inflation_ar       — IPC INDEC mensual (% mensual)
      • sp500              — ^SP500TR total return (close mensual)
      • dolar_blue         — blue venta mensual
      • shv                — T-Bills USD via SHV ETF (close mensual)
      • gld                — Oro via GLD ETF (close mensual)
      • merval             — Índice Merval ARS via ^MERV (close mensual)
      • plazo_fijo         — TNA Minorista BCRA (% anual mensual)

    Paralelización: 7 fetches concurrent en _bench_fetch_executor (max_workers=4
    → algunos quedarán en cola pero el wall time domina al más lento ~15-20s).
    """
    f_inf = _bench_fetch_executor.submit(_fetch_inflation_ar)
    f_sp = _bench_fetch_executor.submit(_fetch_sp500_monthly)
    f_blue = _bench_fetch_executor.submit(_fetch_dolar_blue_monthly)
    f_shv = _bench_fetch_executor.submit(_fetch_shv_monthly)
    f_gld = _bench_fetch_executor.submit(_fetch_gld_monthly)
    f_merval = _bench_fetch_executor.submit(_fetch_merval_monthly)
    f_uva = _bench_fetch_executor.submit(_fetch_uva_monthly)

    def _safe(future, key, default=None):
        """Resultado del future con fallback a stale cache si timeout/exception."""
        try:
            return future.result(timeout=25)
        except Exception:
            return (_bench_cache["data"] or {}).get(key, default if default is not None else {})

    data = {
        "inflation_ar": _safe(f_inf, "inflation_ar"),
        "sp500":        _safe(f_sp, "sp500"),
        "dolar_blue":   _safe(f_blue, "dolar_blue"),
        "shv":          _safe(f_shv, "shv"),
        "gld":          _safe(f_gld, "gld"),
        "merval":       _safe(f_merval, "merval"),
        "uva":          _safe(f_uva, "uva"),
        "fetched_at":   datetime.utcnow().isoformat() + "Z",
    }
    _bench_cache["data"] = data
    _bench_cache["ts"] = time.time()
    return data


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
    """S&P 500 month-end close from yfinance. Returns dict {YYYY-MM: close}.

    Usamos ^SP500TR (Total Return Index): incluye reinversión de dividendos.
    Eso hace comparación JUSTA contra portfolios del user, que sí acumulan
    dividendos vía monthly_entries.pnl_realized.

    Si usáramos ^GSPC (price only), el benchmark subestimaría al SPY en
    ~1.5-2% anual — un portfolio que apenas empata al SPY total aparecería
    como "outperform" engañoso, y un portfolio rezagado parecería un poco
    menos rezagado de lo que realmente está.

    Fallback a ^GSPC si ^SP500TR no devuelve data (algunos plans de yfinance
    no tienen el ticker TR, mejor degradar a price que devolver vacío).
    """
    for ticker in ("^SP500TR", "^GSPC"):
        try:
            data = yf.Ticker(ticker).history(period="5y", interval="1mo")
            if data.empty:
                continue
            out = {}
            for idx, row in data.iterrows():
                key = idx.strftime("%Y-%m")
                close = float(row["Close"]) if not math.isnan(row["Close"]) else None
                if close:
                    out[key] = close
            if out:
                if ticker == "^GSPC":
                    log.warning("SPY: ^SP500TR no disponible, usando ^GSPC (sin dividendos)")
                return out
        except Exception:
            continue
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


def _fetch_yf_monthly(ticker: str):
    """Helper genérico: mes-cierre de un ticker yfinance. Returns {YYYY-MM: close}.

    Usado para SHV (T-Bills), GLD (Oro), ^MERV (índice Merval). Mismo patrón
    que _fetch_sp500_monthly pero sin fallback (esos índices/ETFs son únicos).
    """
    try:
        data = yf.Ticker(ticker).history(period="5y", interval="1mo")
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


def _fetch_shv_monthly():
    """T-Bills USD via SHV ETF (iShares 0-3 Month Treasury Bond).
    Returns {YYYY-MM: close USD}. Proxy de tasa libre de riesgo USD."""
    return _fetch_yf_monthly("SHV")


def _fetch_gld_monthly():
    """Oro via GLD ETF (SPDR Gold Trust).
    Returns {YYYY-MM: close USD}. Hedge contra inflación."""
    return _fetch_yf_monthly("GLD")


def _fetch_merval_monthly():
    """Índice Merval en ARS via yfinance (^MERV).
    Returns {YYYY-MM: close ARS}. Benchmark mercado AR."""
    return _fetch_yf_monthly("^MERV")


def _fetch_uva_monthly():
    """UVA (Unidad de Valor Adquisitivo) mensual desde argentinadatos.com.
    Returns {YYYY-MM: uva_value} (último valor del mes).

    UVA ajusta por inflación INDEC (CER): el ratio UVA_t / UVA_{t-1} es
    el factor de capitalización del mes (= inflación del mes).

    Usado para simular un Plazo Fijo UVA — la opción de PF más popular en AR
    para preservar poder de compra. Su retorno mensual = inflación + spread
    chico (~0.5-1% TNA); asumimos spread = 0 (impacto <1pp anual, despreciable).

    Endpoint verificado activo 2026-05-26. argentinadatos.com NO tiene una
    serie histórica de TNA Minorista del BCRA — UVA es el mejor proxy
    disponible para el comportamiento del PF retail AR.
    """
    try:
        r = requests.get(
            "https://api.argentinadatos.com/v1/finanzas/indices/uva",
            timeout=8,
        )
        if r.status_code != 200:
            return {}
        # La API devuelve daily. Tomamos el último valor de cada mes
        # (dict overwrite gana porque las entries vienen ordenadas por fecha).
        out = {}
        for item in r.json():
            fecha = item.get("fecha", "")
            valor = item.get("valor")
            if fecha and valor is not None:
                out[fecha[:7]] = float(valor)
        return out
    except Exception:
        return {}


@app.get("/api/benchmarks")
def get_benchmarks(uid: int = Depends(get_current_user)):
    """Endpoint stale-while-revalidate:
       • cache fresco (< 1h) → return inmediato.
       • cache stale pero existente → return stale + dispatch refresh background.
       • sin cache (cold start post-restart) → bloquea fetcheando.

    Sin SWR, el primer user después del restart del worker bloqueaba 15-20s
    esperando los 3 fetches externos (yfinance + 2× argentinadatos.com). Con
    SWR, ve data hasta 1h vieja (igual válida — los benchmarks son mensuales)
    y el próximo request ve data fresca.
    """
    now = time.time()
    cached_data = _bench_cache["data"]
    cache_age = now - _bench_cache["ts"]

    # Cache fresco → return inmediato
    if cached_data and cache_age < BENCH_TTL:
        return cached_data

    # Cache stale pero existe → return stale + refresh bg (SWR).
    # Lock simple para evitar 10 refreshes paralelos si llegan 10 requests.
    if cached_data:
        if not _bench_refresh_inflight["flag"]:
            _bench_refresh_inflight["flag"] = True
            def _bg_refresh():
                try:
                    _benchmarks_fetch_and_cache()
                except Exception as ex:
                    log.warning(f"benchmarks SWR refresh failed: {ex}")
                finally:
                    _bench_refresh_inflight["flag"] = False
            _bench_fetch_executor.submit(_bg_refresh)
        return cached_data

    # Cold start (cache vacío) → bloquea fetcheando. Solo el primer request
    # post-restart paga este costo (~15-20s con paralelización interna).
    return _benchmarks_fetch_and_cache()


# ─── Bond indices (CER / UVA / A3500) ─────────────────────────────────────────
# Phase 3C: serie diaria de coeficientes para bonos AR ajustados por
# inflación o tipo de cambio. CER es el más urgente (audit hallazgo C1):
# bonos TX26/TX28/TZX26/27/28 ajustan capital diariamente por este índice.
#
# Estrategia de cache:
#   • Persistimos cada (index_name, date) en `bond_indices_daily`.
#   • Una request entra → consultamos tabla → si falta cobertura del rango
#     pedido, fetcheamos source externa → upsert → devolvemos.
#   • Frescura: TTL de 4 horas en MEMORY cache (`_indices_fetched`) para
#     no martillar la fuente cuando se piden los mismos rangos repetidamente.
#   • Fallback graceful: si la fuente externa falla, devolvemos lo cacheado
#     + flag `stale: true` para que el frontend muestre warning.

_indices_fetched = {}  # { index_name: last_fetch_ts }
INDICES_TTL = 4 * 3600  # 4 hours


def _fetch_cer_series():
    """Trae la serie histórica diaria de CER desde argentinadatos.com.

    Endpoint público: https://api.argentinadatos.com/v1/finanzas/indices/cer
    Formato: [{ fecha: 'YYYY-MM-DD', valor: number }]. Returns dict
    {YYYY-MM-DD: value} o {} en caso de error.
    """
    try:
        r = requests.get("https://api.argentinadatos.com/v1/finanzas/indices/cer", timeout=10)
        if r.status_code != 200:
            return {}
        out = {}
        for item in r.json():
            fecha = item.get("fecha", "")
            val = item.get("valor")
            if fecha and val is not None and _DATE_RE.match(fecha):
                out[fecha] = float(val)
        return out
    except Exception:
        return {}


def _ensure_index_cached(conn, index_name: str):
    """Refresca el cache de un índice si TTL expiró. No-op si fresh."""
    now = time.time()
    last = _indices_fetched.get(index_name, 0)
    if now - last < INDICES_TTL:
        return
    fetcher_map = {"CER": _fetch_cer_series}
    fetcher = fetcher_map.get(index_name)
    if not fetcher:
        return
    series = fetcher()
    if not series:
        return  # No actualizamos timestamp en caso de error
    iso_now = datetime.utcnow().isoformat() + "Z"
    with conn:
        for date, value in series.items():
            conn.execute(
                """INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(index_name, date) DO UPDATE SET
                       value = excluded.value,
                       source = excluded.source,
                       updated_at = excluded.updated_at""",
                (index_name, date, value, 'argentinadatos', iso_now),
            )
    _indices_fetched[index_name] = now


@app.get("/api/bond-indices/{index_name}")
def get_bond_index_series(
    index_name: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date: Optional[str] = None,
    uid: int = Depends(get_current_user),
):
    """Devuelve la serie diaria del índice solicitado.

    Query params:
      • date_from + date_to: rango cerrado [from, to].
      • date: un solo día (atajo, equivalente a from=to=date).
      • sin params: serie completa disponible en cache.

    Response:
      {
        index_name: 'CER',
        series: { 'YYYY-MM-DD': 123.45, ... },
        count: number,
        latest_date: 'YYYY-MM-DD',
        stale: false   // true si TTL expiró y no se pudo actualizar
      }
    """
    if index_name not in ("CER", "UVA", "A3500"):
        raise HTTPException(400, f"Índice no soportado: {index_name}")
    if date and (date_from or date_to):
        raise HTTPException(400, "Usá `date` o `date_from`/`date_to`, no ambos")
    if date:
        if not _DATE_RE.match(date):
            raise HTTPException(422, f"Fecha inválida: {date}")
        date_from = date_to = date
    for d in (date_from, date_to):
        if d and not _DATE_RE.match(d):
            raise HTTPException(422, f"Fecha inválida: {d}")

    conn = get_db()
    try:
        # Best-effort refresh del cache (no falla si la fuente externa cae).
        try:
            _ensure_index_cached(conn, index_name)
        except Exception:
            pass

        q = "SELECT date, value FROM bond_indices_daily WHERE index_name = ?"
        params = [index_name]
        if date_from:
            q += " AND date >= ?"
            params.append(date_from)
        if date_to:
            q += " AND date <= ?"
            params.append(date_to)
        q += " ORDER BY date ASC"
        rows = conn.execute(q, params).fetchall()
        series = {r["date"]: r["value"] for r in rows}

        # Stale check: si no se actualizó hace TTL+1h Y no hay data fresh
        last_fetch = _indices_fetched.get(index_name, 0)
        stale = (time.time() - last_fetch) > (INDICES_TTL + 3600)

        latest_date = rows[-1]["date"] if rows else None
        return {
            "index_name": index_name,
            "series": series,
            "count": len(series),
            "latest_date": latest_date,
            "stale": stale,
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Eventos financieros (earnings / ex-dividend / payment date)
# ═══════════════════════════════════════════════════════════════════════════
# Para STOCKS / ETFs / CEDEARs: usamos yfinance .calendar y .actions().
# Para BONOS (cupones / amorts): los genera el frontend desde bondSchedule.js
# en runtime — no se cachean acá (la data del cronograma vive en el frontend).
#
# Caching:
#   • Persistente: tabla `financial_events`, upsert por (ticker, type, date).
#   • In-memory TTL: 6 horas — earnings dates no cambian más rápido que eso.
#
# Auto-refresh: si el cache está stale al pedir, refresh sólo para los tickers
# del portfolio del user (no para todo el universo).

_events_fetched_at = {}  # { ticker: timestamp último fetch }
EVENTS_TTL = 6 * 3600  # 6 horas


# ═══════════════════════════════════════════════════════════════════════════
# PR #2.B — Eventos populares (Tab "Popular" en /eventos)
# ═══════════════════════════════════════════════════════════════════════════
# Dos sources distintas:
#
#   1. MACRO_EVENTS_CALENDAR: fechas hardcoded de eventos económicos
#      conocidos (FOMC, CPI, NFP, INDEC, etc.) USA + AR. Como son fechas
#      relativamente predecibles, hardcodear es más confiable y barato que
#      API externa con quota.
#
#   2. POPULAR_TICKERS_US + POPULAR_TICKERS_AR_ADR: lista de empresas
#      "que mueven el mercado" cuyas earnings sí valen la pena mostrar
#      aunque el user no las tenga. Se fetchean via yfinance con el mismo
#      patrón que el endpoint /events/portfolio.
#
# Mantenimiento: las fechas macro hay que renovarlas cada año (las publican
# oficialmente Fed/BLS/INDEC). Los tickers populares pueden refinarse según
# feedback del user.

# Macro events de USA + AR — fechas próximas conocidas.
# Para regenerar: copiar del calendario oficial de Fed/BLS/INDEC.
# Cada entry: { date, country, code, title, category }
MACRO_EVENTS_CALENDAR = [
    # ─── USA — FOMC 2026 (8 reuniones programadas Reserva Federal) ─────────
    {"date": "2026-01-28", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-03-18", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-04-29", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-06-17", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-07-29", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-09-16", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-10-28", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},
    {"date": "2026-12-09", "country": "USA", "code": "USA-FOMC", "title": "FOMC — Decisión de tasas", "category": "fed_rate"},

    # ─── USA — CPI Release ~día 11-15 cada mes (Bureau of Labor Statistics) ─
    {"date": "2026-05-13", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-06-11", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-07-15", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-08-12", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-09-10", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-10-15", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-11-12", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},
    {"date": "2026-12-10", "country": "USA", "code": "USA-CPI", "title": "Inflación USA (CPI)", "category": "cpi"},

    # ─── USA — NFP (Non-Farm Payrolls), primer viernes de cada mes ─────────
    {"date": "2026-05-01", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-06-05", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-07-03", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-08-07", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-09-04", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-10-02", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-11-06", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},
    {"date": "2026-12-04", "country": "USA", "code": "USA-NFP", "title": "Empleo USA (Non-Farm Payrolls)", "category": "employment"},

    # ─── AR — INDEC IPC mensual (release ~día 13-15) ───────────────────────
    {"date": "2026-05-14", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-06-15", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-07-14", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-08-13", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-09-15", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-10-14", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-11-13", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
    {"date": "2026-12-15", "country": "AR", "code": "AR-IPC", "title": "Inflación AR (IPC INDEC)", "category": "cpi"},
]

# Tickers "que mueven el mercado" cuyas earnings se muestran en Popular
# aunque el user no las tenga en cartera. Mantenimiento manual periódico.
POPULAR_TICKERS_US = [
    # Magnificent 7
    'NVDA', 'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'META', 'TSLA',
    # Otras grandes US que generan ruido
    'NFLX', 'AMD', 'INTC', 'COIN', 'DIS', 'PYPL',
]

# ADRs argentinos populares (cotizan en NYSE/NASDAQ — yfinance los tiene)
POPULAR_TICKERS_AR_ADR = [
    'GGAL', 'YPF', 'BMA', 'PAM', 'TEO', 'EDN', 'SUPV',
]


@app.get("/api/events/popular")
def get_popular_events(
    days: int = 90,
    uid: int = Depends(get_current_user),
):
    """Eventos "del mercado" en general — no filtrados al portfolio del user.

    Dos categorías combinadas:
      1. Macro events hardcoded (FOMC, CPI, NFP, INDEC IPC) — USA + AR.
      2. Earnings de tickers populares (magnificent 7 + ADRs AR) via yfinance.

    Para items en los que el user TIENE el ticker en cartera, agregamos el
    flag `in_portfolio=True` para que el frontend marque "👁 En tu cartera".

    Query params:
      • days: ventana hacia adelante. Default 90, max 365.
    """
    if days <= 0 or days > 365:
        raise HTTPException(422, "days debe estar entre 1 y 365")

    today = datetime.utcnow().strftime('%Y-%m-%d')
    end_date = (datetime.utcnow() + timedelta(days=days)).strftime('%Y-%m-%d')

    conn = get_db()
    try:
        # Tickers que el user tiene en cartera (para flag in_portfolio)
        user_rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
               WHERE user_id=? AND is_cash=0""",
            (uid,),
        ).fetchall()
        user_tickers = {r['asset'] for r in user_rows}

        # 1. Macro events filtrados por ventana
        macro_events = []
        for ev in MACRO_EVENTS_CALENDAR:
            if today <= ev['date'] <= end_date:
                macro_events.append({
                    'ticker': ev['code'],          # ej: 'USA-CPI'
                    'event_type': 'macro',
                    'event_date': ev['date'],
                    'details': {
                        'country': ev['country'],
                        'title': ev['title'],
                        'category': ev['category'],
                    },
                    'confirmed': True,
                    'source': 'hardcoded',
                    'in_portfolio': False,
                })

        # 2. Earnings de tickers populares — refresh + query
        popular = POPULAR_TICKERS_US + POPULAR_TICKERS_AR_ADR
        try:
            _refresh_events_for_tickers(conn, popular)
        except Exception:
            pass

        placeholders = ','.join('?' for _ in popular)
        rows = conn.execute(
            f"""SELECT ticker, event_type, event_date, details, confirmed, source
                FROM financial_events
                WHERE ticker IN ({placeholders})
                  AND event_date >= ?
                  AND event_date <= ?
                ORDER BY event_date ASC""",
            (*popular, today, end_date),
        ).fetchall()

        ticker_events = []
        for r in rows:
            try:
                details = json.loads(r['details']) if r['details'] else {}
            except Exception:
                details = {}
            ticker_events.append({
                'ticker': r['ticker'],
                'event_type': r['event_type'],
                'event_date': r['event_date'],
                'details': details,
                'confirmed': bool(r['confirmed']),
                'source': r['source'],
                'in_portfolio': r['ticker'] in user_tickers,
            })

        # Combinamos y ordenamos por fecha
        all_events = macro_events + ticker_events
        all_events.sort(key=lambda e: e['event_date'])

        return {
            'events': all_events,
            'macro_count': len(macro_events),
            'ticker_count': len(ticker_events),
        }
    finally:
        conn.close()


def _fetch_yf_events(ticker: str) -> list:
    """Trae earnings + ex-dividend + dividend payment dates de un ticker via yfinance.

    Returns: lista de eventos como dicts (sin guardar todavía).
    Falla gracefully — si yfinance no tiene data, devuelve [].
    """
    events = []
    try:
        t = yf.Ticker(ticker)

        # Earnings (próximos + recientes)
        try:
            cal = t.calendar
            if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                # cal puede ser DataFrame o dict según versión de yfinance
                earnings_date = None
                eps_estimate = None
                if hasattr(cal, 'loc'):
                    # DataFrame variant — buscar Earnings Date
                    if 'Earnings Date' in cal.index:
                        ed = cal.loc['Earnings Date']
                        earnings_date = ed.iloc[0] if hasattr(ed, 'iloc') else ed
                    if 'Earnings Average' in cal.index:
                        ea = cal.loc['Earnings Average']
                        eps_estimate = float(ea.iloc[0]) if hasattr(ea, 'iloc') else float(ea)
                elif isinstance(cal, dict):
                    earnings_date = cal.get('Earnings Date')
                    if isinstance(earnings_date, list):
                        earnings_date = earnings_date[0] if earnings_date else None
                    eps_estimate = cal.get('Earnings Average')
                if earnings_date is not None:
                    date_str = (earnings_date.strftime('%Y-%m-%d')
                                if hasattr(earnings_date, 'strftime')
                                else str(earnings_date)[:10])
                    if _DATE_RE.match(date_str):
                        details = {}
                        if eps_estimate is not None and isinstance(eps_estimate, (int, float)) and not math.isnan(eps_estimate):
                            details['eps_estimate'] = round(float(eps_estimate), 4)
                        events.append({
                            'ticker': ticker,
                            'event_type': 'earnings',
                            'event_date': date_str,
                            'details': details,
                            'confirmed': 1,
                        })
        except Exception:
            pass

        # Ex-dividend date + dividend amount (próximo)
        try:
            info = t.info  # cache interno de yfinance
            ex_div = info.get('exDividendDate')  # timestamp UNIX
            div_amount = info.get('lastDividendValue')
            if ex_div:
                # ex_div es timestamp unix (segundos); convertir a fecha ISO
                d = datetime.utcfromtimestamp(ex_div).strftime('%Y-%m-%d')
                if _DATE_RE.match(d):
                    details = {}
                    if div_amount is not None and isinstance(div_amount, (int, float)):
                        details['dividend_per_share'] = round(float(div_amount), 4)
                    events.append({
                        'ticker': ticker,
                        'event_type': 'ex_dividend',
                        'event_date': d,
                        'details': details,
                        'confirmed': 1,
                    })
        except Exception:
            pass

    except Exception:
        # ticker desconocido o yfinance error → vacío
        pass
    return events


def _refresh_events_in_background(tickers: list):
    """Stale-while-revalidate para events: dispara refresh en daemon thread."""
    import threading
    def worker():
        local_conn = get_db()
        try:
            _refresh_events_for_tickers(local_conn, tickers)
        except Exception as ex:
            logging.getLogger(__name__).warning("background events refresh failed: %s", ex)
        finally:
            local_conn.close()
    threading.Thread(target=worker, daemon=True).start()


def _has_events_for_tickers(conn, tickers: list, days: int = 90) -> bool:
    """Quick check: ¿hay eventos en DB para alguno de esos tickers en ventana?"""
    if not tickers:
        return False
    today = datetime.utcnow().strftime('%Y-%m-%d')
    end_date = (datetime.utcnow() + timedelta(days=days)).strftime('%Y-%m-%d')
    placeholders = ','.join('?' for _ in tickers)
    row = conn.execute(
        f"SELECT 1 FROM financial_events WHERE ticker IN ({placeholders}) "
        f"AND event_date >= ? AND event_date <= ? LIMIT 1",
        (*tickers, today, end_date),
    ).fetchone()
    return row is not None


def _refresh_events_for_tickers(conn, tickers: list):
    """Refresca el cache de eventos para una lista de tickers. Idempotente:
    si un ticker ya fue refrescado hace <TTL, lo skipea."""
    now = time.time()
    iso_now = datetime.utcnow().isoformat() + "Z"
    for ticker in tickers:
        if not ticker:
            continue
        if now - _events_fetched_at.get(ticker, 0) < EVENTS_TTL:
            continue
        events = _fetch_yf_events(ticker)
        if not events:
            # Marcamos como "fetched" igual para no retry constantemente
            _events_fetched_at[ticker] = now
            continue
        with conn:
            for ev in events:
                conn.execute(
                    """INSERT INTO financial_events
                       (ticker, event_type, event_date, details, confirmed, source, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ticker, event_type, event_date) DO UPDATE SET
                           details = excluded.details,
                           confirmed = excluded.confirmed,
                           fetched_at = excluded.fetched_at""",
                    (ev['ticker'], ev['event_type'], ev['event_date'],
                     json.dumps(ev['details']), ev['confirmed'], 'yfinance', iso_now),
                )
        _events_fetched_at[ticker] = now


@app.get("/api/events/portfolio")
def get_portfolio_events(
    days: int = 90,
    uid: int = Depends(get_current_user),
):
    """Eventos próximos para los activos en el portfolio del user.

    Sólo devuelve eventos de STOCKS / ETFs / CEDEARs (de yfinance). Los eventos
    de BONOS los calcula el frontend desde bondSchedule — están filtrados por
    `_is_bond_like_ticker` y se excluyen acá para no duplicar.

    Query params:
      • days: ventana hacia adelante. Default 90, max 365.

    Response:
      {
        events: [{ticker, event_type, event_date, details, confirmed, source}],
        refreshed_tickers: number,  // cuántos tickers se refrescaron del cache
      }
    """
    if days <= 0 or days > 365:
        raise HTTPException(422, "days debe estar entre 1 y 365")

    conn = get_db()
    try:
        # Tickers del portfolio del user, excluyendo cash + bonos (que se generan frontend).
        # Convención: bonos AR tienen tickers en BOND_TICKERS_BACKEND (set hardcoded);
        # ETFs y stocks son los que cuentan acá.
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
               WHERE user_id=? AND is_cash=0 AND asset NOT IN ('USDT', 'USD', 'ARS')""",
            (uid,),
        ).fetchall()
        all_tickers = [r['asset'] for r in rows]
        # Excluir bonos AR (los maneja frontend via bondSchedule)
        stock_tickers = [t for t in all_tickers if t not in AR_BONDS_DATA912 and t not in CRYPTO_SYMBOLS]

        # SWR: si ya hay eventos en DB para algún ticker del portfolio en la
        # ventana, devolvemos esa data al instante y refrescamos en background.
        # Si NO hay nada (primer load), bloqueamos.
        refreshed = 0
        if _has_events_for_tickers(conn, stock_tickers, days=days):
            _refresh_events_in_background(stock_tickers)
        else:
            try:
                before = sum(1 for t in stock_tickers if _events_fetched_at.get(t, 0) > 0)
                _refresh_events_for_tickers(conn, stock_tickers)
                after = sum(1 for t in stock_tickers if _events_fetched_at.get(t, 0) > 0)
                refreshed = after - before
            except Exception:
                pass

        # Query: eventos próximos para los tickers del portfolio
        today = datetime.utcnow().strftime('%Y-%m-%d')
        end_date = (datetime.utcnow() + timedelta(days=days)).strftime('%Y-%m-%d')
        if not stock_tickers:
            return {'events': [], 'refreshed_tickers': 0}

        placeholders = ','.join('?' for _ in stock_tickers)
        rows = conn.execute(
            f"""SELECT ticker, event_type, event_date, details, confirmed, source
                FROM financial_events
                WHERE ticker IN ({placeholders})
                  AND event_date >= ?
                  AND event_date <= ?
                ORDER BY event_date ASC""",
            (*stock_tickers, today, end_date),
        ).fetchall()

        events = []
        for r in rows:
            details = {}
            try:
                details = json.loads(r['details']) if r['details'] else {}
            except Exception:
                pass
            events.append({
                'ticker': r['ticker'],
                'event_type': r['event_type'],
                'event_date': r['event_date'],
                'details': details,
                'confirmed': bool(r['confirmed']),
                'source': r['source'],
            })

        return {'events': events, 'refreshed_tickers': refreshed}
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PR #3 — Noticias (Google News RSS)
# ═══════════════════════════════════════════════════════════════════════════
# Source: Google News RSS — sin auth, sin quota declarada. Queries por ticker
# o macro topic. Parsing con xml.etree (stdlib).
#
# Estrategia de cache:
#   • Persistente: tabla `news`, dedup por (source, external_id).
#   • TTL in-memory por query: 30 min para tickers del user, 60 min macro.
#   • Fetch lazy al endpoint, idempotente (no refetch si stale<TTL).
#
# Queries macro hardcoded — cubren el bloque "Noticias generales del mercado"
# del plan original.

_news_fetched_at = {}  # { query: timestamp }
NEWS_TICKER_TTL = 30 * 60   # 30 min
NEWS_MARKET_TTL = 60 * 60   # 60 min

# Queries macro precanned para el feed "Mercado".
# Mix USA + AR — apuntamos a market+macro relevantes para un inversor (acciones,
# bonos, tasas, inflación, FX). Cada query incluye un anchor financiero
# explícito para reducir basura en el resultado de Google News (en vez de
# "Federal Reserve" → "Federal Reserve interest rates": filtra mejor).
MARKET_NEWS_QUERIES = [
    # ── USA: acciones e índices
    ("S&P 500 stocks today", "market", "en"),
    ("Nasdaq stock market", "market", "en"),
    # ── USA: tasas y bonos
    ("Federal Reserve interest rates", "macro", "en"),
    ("US Treasury yields", "macro", "en"),
    # ── USA: inflación
    ("US CPI inflation", "macro", "en"),
    # ── AR: mercado local
    ("Merval acciones Argentina", "market", "es"),
    ("bonos argentinos soberanos", "market", "es"),
    # ── AR: macro relevante para inversor
    ("inflación Argentina INDEC", "macro", "es"),
    ("dolar blue MEP CCL Argentina", "macro", "es"),
    ("BCRA tasa interés Argentina", "macro", "es"),
]


# Feeds RSS de Investing.com — complemento de Google News con cobertura más
# profunda de acciones, mercados e indicadores macro. RSS 2.0 estándar, no
# requiere auth. Si alguno no responde el fetcher lo skipea silenciosamente.
#
# Codes documentados:
#   news_25  → Stock market (acciones)
#   news_285 → Economic indicators (macro)
INVESTING_FEEDS = [
    # (url, category, lang)
    ("https://www.investing.com/rss/news_25.rss",  "market", "en"),
    ("https://www.investing.com/rss/news_285.rss", "macro",  "en"),
    ("https://es.investing.com/rss/news_25.rss",   "market", "es"),
    ("https://es.investing.com/rss/news_285.rss",  "macro",  "es"),
]

# Whitelist de relevancia (rediseñada 2026-05-26).
#
# Versión vieja: filtro demasiado inclusivo — bastaba que la noticia tuviera
# "stock", "share" o "ipo" para pasar. Resultado: el feed traía empresas
# chiquitas (Insulet, Verra Mobility, Forgent, Suncrete, etc.) que ningún
# usuario AR tiene en cartera.
#
# Versión nueva — DOS PATHS:
#   Path A (empresa): noticia menciona una empresa/asset conocido (S&P 50 +
#                     Merval 25 + cripto top + algunos extras populares LATAM)
#   Path B (macro):   noticia tiene una keyword macro FUERTE (Fed, CPI, S&P 500,
#                     dólar blue, Merval, BCRA, inflación, etc.)
#   Default → DESCARTA.
#
# Sólo se aplica a categorías "market" y "macro". Las noticias de "portfolio"
# ya están filtradas por el ticker en la query, no necesitan otro filtro.

# Tokens de empresas/assets — word-boundary matching (no substring) para evitar
# falsos positivos. Cubre tickers y nombres en EN/ES. Tickers de 1-2 chars
# (V, F, MA) NO se incluyen — demasiado ambiguos para boundary matching.
_KNOWN_ENTITIES = frozenset({
    # ── US Top S&P (top 50 + extras populares LATAM) ──────────────────────
    'apple', 'aapl',
    'microsoft', 'msft',
    'nvidia', 'nvda',
    'alphabet', 'google', 'googl', 'goog',
    'amazon', 'amzn',
    'meta', 'facebook',
    'berkshire', 'brk-a', 'brk-b', 'brkb',
    'tesla', 'tsla',
    'lilly', 'lly',
    'broadcom', 'avgo',
    'jpmorgan', 'jpm',
    'walmart', 'wmt',
    'exxonmobil', 'exxon', 'xom',
    'unitedhealth', 'unh',
    'mastercard',
    'procter', 'p&g',
    'johnson',
    'costco', 'cost',
    'abbvie', 'abbv',
    'oracle', 'orcl',
    'salesforce',
    'chevron', 'cvx',
    'coca-cola',
    'adobe', 'adbe',
    'merck', 'mrk',
    'amd', 'pepsico', 'pepsi', 'pep',
    'netflix', 'nflx',
    'qualcomm', 'qcom',
    'intel', 'intc',
    'disney', 'dis',
    'cisco', 'csco',
    'abbott',
    'accenture', 'acn',
    'mcdonald', "mcdonald's",
    'verizon',
    'amgen', 'amgn',
    'pfizer', 'pfe',
    'philip morris',
    'ibm',
    'servicenow',
    # Extras populares para LATAM / retail
    'palantir', 'pltr',
    'spotify',
    'mercadolibre', 'meli',
    'globant', 'glob',
    'starbucks',
    'paypal', 'pypl',
    'shopify',
    'uber',
    'airbnb',
    'snap',
    'pinterest',
    'roblox', 'rblx',

    # ── AR Top Merval ─────────────────────────────────────────────────────
    'merval',  # índice — standalone porque las noticias varían: "Merval cerró", "Merval abre", "Merval +2%"
    'ggal', 'galicia',
    'ypf', 'ypfd',
    'pampa', 'pampa energía', 'pamp',
    'macro', 'bma',
    'bbva', 'bbar',
    'aluar', 'alua',
    'cresud', 'cres',
    'ternium', 'txar',
    'edenor', 'edn',
    'tgs', 'tgno4',
    'cepu', 'central puerto',
    'mirgor', 'mirg',
    'transener',
    'loma negra',
    'supervielle', 'supv',
    'byma',
    'holcim',
    'cablevisión', 'cablevision', 'cvh',
    # Bonos AR + soberanos
    'al30', 'al29', 'al35', 'gd30', 'gd29', 'gd35', 'gd38', 'gd41', 'gd46',
    'tx26', 'tx28', 'tzx26', 'tzx27', 'tzx28',

    # ── Crypto Top 30 ─────────────────────────────────────────────────────
    'bitcoin', 'btc',
    'ethereum', 'eth',
    'solana',
    'binance',
    'xrp', 'ripple',
    'cardano', 'ada',
    'dogecoin', 'doge',
    'avalanche', 'avax',
    'polkadot',
    'polygon',
    'chainlink',
    'litecoin', 'ltc',
    'shiba',
    'tron',
    'uniswap',
    'cosmos',
    'stellar',
    'aave',
})

# Macro keywords FUERTES — siempre relevantes para un inversor AR/LATAM.
# Multi-word OK (substring match). A diferencia del filtro viejo, estas son
# específicas: no aceptamos "stock" solo, hay que tener contexto macro.
_STRONG_MACRO_KEYWORDS = frozenset({
    # USA — macro
    'federal reserve', 'fomc', 'rate hike', 'rate cut', 'rate decision',
    'powell', 'monetary policy', 'fed minutes', 'fed pivot',
    'cpi data', 'core cpi', 'core inflation', 'inflation report', 'inflation data',
    'jobs report', 'nonfarm payrolls', 'unemployment rate',
    'jobless claims', 'retail sales', 'gdp growth', 'recession risk',
    'treasury yield', 'treasury yields', '10-year treasury', '2-year treasury',
    # USA — mercados/índices
    's&p 500', 'sp500', 'nasdaq', 'nasdaq 100', 'nasdaq composite', 'dow jones',
    'wall street', 'russell 2000', 'magnificent 7', 'mag seven',
    # USA — commodities
    'crude oil', 'oil prices', 'gold prices', 'natural gas prices',
    # AR — macro
    'inflación argentina', 'inflacion argentina', 'ipc indec', 'indec',
    'bcra', 'banco central argentina', 'tasa de referencia', 'tasa badlar',
    'política monetaria argentina', 'politica monetaria argentina',
    'dolar blue', 'dólar blue', 'dolar mep', 'dolar ccl', 'dolar oficial',
    'cepo cambiario', 'control de cambios', 'brecha cambiaria',
    'reservas bcra', 'reservas internacionales',
    # AR — mercados
    's&p merval', 'merval cierra', 'merval abre', 'índice merval',
    'bonos argentinos', 'bonos soberanos', 'deuda argentina',
    'lecap', 'cer bonos',
    # AR — política económica
    'milei', 'caputo', 'ley bases', 'rigi', 'fmi argentina',
    # Crypto — macro
    'bitcoin halving', 'crypto market', 'crypto regulation', 'spot etf',
})


# Regex pre-compilado para Path A — word boundary matching evita falsos
# positivos como "amid" matcheando "amd" o "macro" matcheando dentro de
# otras palabras. Compilado al startup una sola vez.
import re as _re_news
_KNOWN_ENTITIES_REGEX = _re_news.compile(
    r'\b(' + '|'.join(_re_news.escape(t) for t in sorted(_KNOWN_ENTITIES, key=len, reverse=True)) + r')\b',
    _re_news.IGNORECASE,
)


def _is_market_relevant(item):
    """True si la noticia menciona una empresa conocida O tiene macro fuerte.

    Cambio 2026-05-26: el filtro viejo era demasiado inclusivo (bastaba
    "stock" o "share"). Traía noticias irrelevantes de empresas chicas.
    Ahora exige una de dos cosas:
       Path A: la noticia menciona una empresa/asset de la whitelist
               (S&P 50 + Merval 25 + crypto top + extras populares LATAM).
       Path B: la noticia tiene una keyword macro fuerte (Fed, CPI, S&P 500,
               dólar blue, Merval, BCRA, inflación, etc.).

    Falla abierto: si no hay title, deja pasar.
    """
    title = item.get('title') or ''
    summary = item.get('summary') or ''
    if not title:
        return True
    haystack = title + ' ' + summary

    # Path A: empresa/asset conocido (word boundary regex)
    if _KNOWN_ENTITIES_REGEX.search(haystack):
        return True

    # Path B: macro fuerte (substring sobre lowercase)
    haystack_l = haystack.lower()
    return any(kw in haystack_l for kw in _STRONG_MACRO_KEYWORDS)


# ─── News tagging ─────────────────────────────────────────────────────────────
#
# Cada noticia recibe 0-N tags por keyword-match. Permite filtrar el feed por
# "tipo" en el frontend (earnings, M&A, regulación, tasas, etc.) sin necesidad
# de un clasificador ML.
#
# Filosofía: keyword-match permisivo. Una noticia puede tener varios tags
# (ej: "Apple sube tras earnings y anuncio de buyback" → earnings + dividend).
# Si no matchea ningún tag, queda sin etiquetas (tag-less en el feed).
#
# Tags estables (no cambiar los IDs — quedan en DB):
#   earnings    — resultados, EPS, guidance, beat/miss
#   m_and_a     — fusiones, adquisiciones, OPAs
#   rates       — Fed, FOMC, BCRA, tasas, política monetaria
#   inflation   — CPI, IPC, INDEC, inflación
#   forex       — dólar, peso, FX, blue/MEP/CCL
#   dividend    — dividendos, payout, reparto
#   regulatory  — SEC, demandas, multas, antitrust, CNV
#   debt        — default, deuda soberana, FMI, restructuring

NEWS_TAG_KEYWORDS = {
    'earnings': [
        # English
        'earnings', 'eps', 'revenue', 'beat estimates', 'beat expectations',
        'missed estimates', 'guidance', 'outlook', 'quarterly', 'q1 ', 'q2 ',
        'q3 ', 'q4 ', 'reported', 'profit',
        # Spanish
        'resultados', 'ganancias', 'beneficios', 'utilidades', 'ingresos',
        'trimestre', 'trimestral', 'reportó', 'reporta', 'reportar',
    ],
    'm_and_a': [
        # English
        'merger', 'acquisition', 'acquire', 'acquired', 'buyout', 'takeover',
        'm&a', 'deal close', 'tender offer',
        # Spanish
        'fusión', 'fusion', 'fusiona', 'adquisición', 'adquisicion', 'adquiere',
        'absorbió', 'compró', 'oferta pública', 'opa ', 'opa.',
    ],
    'rates': [
        # English
        'fed ', 'federal reserve', 'fomc', 'rate hike', 'rate cut', 'rate decision',
        'interest rate', 'powell', 'monetary policy',
        # Spanish
        'bcra', 'banco central', 'política monetaria', 'politica monetaria',
        'tasa de interés', 'tasa de interes', 'tasa de referencia',
        'sube la tasa', 'baja la tasa',
    ],
    'inflation': [
        # English
        'inflation', 'cpi', 'ppi', 'core inflation', 'price index',
        # Spanish
        'inflación', 'inflacion', 'ipc', 'indec', 'índice de precios',
        'indice de precios',
    ],
    'forex': [
        # English
        'dollar', 'fx ', 'forex', 'currency', 'exchange rate',
        # Spanish
        'dólar', 'dolar', 'blue', 'mep', 'ccl', 'contado con liqui',
        'peso ', ' peso', 'cotización', 'cotizacion', 'cepo cambiario',
        'tipo de cambio',
    ],
    'dividend': [
        # English
        'dividend', 'payout', 'distribution',
        # Spanish
        'dividendo', 'dividendos', 'reparto',
    ],
    'regulatory': [
        # English
        ' sec ', 'lawsuit', 'investigation', 'fine ', 'penalty', 'antitrust',
        'regulator', 'ruling', 'court',
        # Spanish
        'demanda', 'investigación', 'investigacion', 'multa', 'sanción',
        'tribunal', 'cnv ', 'cnv.', 'denuncia',
    ],
    'debt': [
        # English
        'default', 'restructuring', 'imf', 'sovereign bond', 'sovereign debt',
        # Spanish
        'default', 'reestructuración', 'reestructuracion', 'fmi',
        'bonos soberanos', 'deuda soberana', 'staff level', 'desembolso',
    ],
}


def _tag_news_item(item):
    """Asigna 0-N tags a una noticia por keyword matching sobre title+summary.

    Devuelve lista de strings (tag IDs estables — ver NEWS_TAG_KEYWORDS).
    Orden estable según orden de definición en NEWS_TAG_KEYWORDS.
    """
    title = (item.get('title') or '').lower()
    summary = (item.get('summary') or '').lower()
    if not title:
        return []
    haystack = ' ' + title + ' ' + summary + ' '
    tags = []
    for tag_id, kws in NEWS_TAG_KEYWORDS.items():
        for kw in kws:
            if kw in haystack:
                tags.append(tag_id)
                break  # un match por tag — no contamos múltiples
    return tags


def _fetch_google_news_rss(query: str, lang: str = "en", limit: int = 15):
    """Trae items del Google News RSS para un query dado.

    Devuelve lista de dicts con: external_id, title, summary, url,
    published_at (ISO), source_label.
    Falla gracefully con [] si HTTP no-200 o parseo falla.
    """
    # gl/ceid por idioma — para AR usamos es-419, para US en-US.
    if lang == "es":
        params = {"q": query, "hl": "es-419", "gl": "AR", "ceid": "AR:es-419"}
    else:
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    try:
        from urllib.parse import urlencode
        url = "https://news.google.com/rss/search?" + urlencode(params)
        # Timeout 6s (antes 10). Google News responde típicamente en 1-2s; si
        # no respondió en 6, probablemente está caído y no nos sirve esperar
        # más. Bajar el techo reduce exposición a DoS via tool storm:
        # 5 tickers × 3 tool loops × 10s = 150s → ×6s = 90s. Auditoría #2.
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0 (compatible; RendiBot/1.0; +https://rendi.finance/bot)", "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
        if r.status_code != 200:
            return []
        return _parse_google_news_rss(r.content, limit=limit)
    except Exception:
        return []


def _parse_rss_feed(xml_bytes: bytes, limit: int = 15):
    """Parser genérico de RSS 2.0 → lista de items normalizados.

    Soporta tanto Google News (con tag `<source>`) como Investing.com (sin él).
    El shape común que devuelve permite que el resto del pipeline trate ambas
    fuentes igual.

    Usa `defusedxml` cuando está disponible para protegernos de XML bombs
    (billion laughs / quadratic blowup). Fallback a `xml.etree` si no está
    instalado (dev local sin pip install).
    """
    # Try defusedxml first (production-safe), fall back to stdlib
    try:
        from defusedxml.ElementTree import fromstring as _fromstring
        from xml.etree.ElementTree import ParseError
    except ImportError:
        from xml.etree.ElementTree import fromstring as _fromstring, ParseError
    items = []
    try:
        root = _fromstring(xml_bytes)
        for item in root.findall('.//item')[:limit]:
            guid = item.findtext('guid') or item.findtext('link') or ''
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub = (item.findtext('pubDate') or '').strip()
            desc = (item.findtext('description') or '').strip()
            source_elem = item.find('source')
            source_label = source_elem.text if source_elem is not None else None
            if not title or not link:
                continue
            published_iso = _rfc822_to_iso(pub) or datetime.utcnow().isoformat() + "Z"
            items.append({
                'external_id': guid[:200],
                'title': title[:500],
                'summary': _strip_html(desc)[:1000] if desc else None,
                'url': link,
                'published_at': published_iso,
                'source_label': source_label,
            })
    except (ParseError, Exception):
        # ParseError + defusedxml.EntitiesForbidden / DTDForbidden — todos seguros.
        pass
    return items


# Alias para back-compat con tests del PR original de Google News
_parse_google_news_rss = _parse_rss_feed


def _strip_html(text):
    """Saca tags HTML simples + decodifica entidades del summary (Investing.com
    inyecta `<p>`, `<b>`, y entidades como `&amp;` / `&#39;`)."""
    if not text:
        return text
    import re, html
    return html.unescape(re.sub(r'<[^>]+>', '', text)).strip()


def _fetch_investing_rss(url: str, limit: int = 15):
    """Fetcher para Investing.com RSS. Cualquier URL del dominio investing.com
    sirve — el feed sigue RSS 2.0 estándar.

    Falla gracefully con [] si HTTP no-200 o parseo falla.
    """
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; RendiBot/1.0; +https://rendi.finance/bot)", "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"})
        if r.status_code != 200:
            return []
        return _parse_rss_feed(r.content, limit=limit)
    except Exception:
        return []


def _rfc822_to_iso(s: str):
    """Convierte 'Tue, 28 Apr 2026 17:00:22 GMT' → ISO. None si falla."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.isoformat()
    except Exception:
        return None


def _persist_news_items(conn, items, source_id: str, category: str, query_source: str):
    """Path común para insertar items pre-fetcheados a la tabla news.

    Aplica tagging por keywords y filtro de relevancia (sólo market/macro).
    Devuelve la cantidad de filas nuevas insertadas (los items conocidos por
    UNIQUE(source, external_id) son skippeados via INSERT OR IGNORE).
    """
    if not items:
        return 0
    # Filtro de relevancia — sólo market/macro. La DB acumula histórico, así
    # que aunque cada refresh quede con menos items, el endpoint sigue
    # devolviendo los últimos N por published_at DESC.
    if category in ('market', 'macro'):
        items = [it for it in items if _is_market_relevant(it)]
    if not items:
        return 0
    iso_now = datetime.utcnow().isoformat() + "Z"
    inserted = 0
    with conn:
        for it in items:
            try:
                tags = _tag_news_item(it)
                tags_csv = ','.join(tags) if tags else None
                cur = conn.execute(
                    """INSERT OR IGNORE INTO news
                       (source, external_id, title, summary, url, image_url,
                        published_at, tickers, category, query_source, tags, fetched_at)
                       VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, ?)""",
                    (source_id, it['external_id'], it['title'], it['summary'],
                     it['url'], it['published_at'], category, query_source,
                     tags_csv, iso_now),
                )
                # rowcount es el delta del execute (0 si IGNORE saltó por dedup).
                inserted += cur.rowcount if cur.rowcount > 0 else 0
            except Exception as e:
                # No silenciamos del todo — un INSERT que falla repetidamente
                # señaliza un bug de schema / constraint violation que conviene
                # ver en logs (sin tumbar el batch).
                logging.getLogger(__name__).warning(
                    "persist news item failed (source=%s, ext_id=%s): %s",
                    source_id, it.get('external_id'), e,
                )
    return inserted


def _refresh_news_query(conn, query: str, lang: str, category: str, limit: int = 15):
    """Refresca el cache de Google News para un query dado. Idempotente.

    Delega a _persist_news_items con source='google_news_rss'.
    """
    items = _fetch_google_news_rss(query, lang=lang, limit=limit)
    return _persist_news_items(conn, items, 'google_news_rss', category, query)


def _refresh_investing_feed(conn, url: str, category: str, limit: int = 15):
    """Refresca el cache desde un feed RSS de Investing.com.

    Delega a _persist_news_items con source='investing_com'. Como query_source
    usamos la URL del feed (sirve para debug + dedup soft).
    """
    items = _fetch_investing_rss(url, limit=limit)
    return _persist_news_items(conn, items, 'investing_com', category, url)


def _ensure_news_for_query(conn, query: str, lang: str, category: str, ttl_seconds: int):
    """Refresh idempotente: sólo fetcha si TTL expiró."""
    now = time.time()
    cache_key = f"{category}:{query}"
    if now - _news_fetched_at.get(cache_key, 0) < ttl_seconds:
        return
    _refresh_news_query(conn, query, lang, category)
    _news_fetched_at[cache_key] = now


def _cache_key_for(kind: str, category: str, identifier: str) -> str:
    """Key estable para _news_fetched_at. Formato distinto por source para no
    colisionar (Google News usa 'cat:query', Investing usa 'investing:cat:url').
    """
    if kind == 'google_news':
        return f"{category}:{identifier}"  # formato legacy — no romper tests
    return f"{kind}:{category}:{identifier}"


def _refresh_news_in_background(specs, ttl_seconds):
    """Stale-while-revalidate: dispara el refresh batch en un daemon thread
    sin bloquear la response. El próximo request ya tiene data fresca.

    Si hay data en DB, los endpoints devuelven esa data inmediatamente y
    delegan el refresh acá — el user nunca espera 1-3s de yfinance.
    """
    import threading
    def worker():
        try:
            _ensure_news_batch_parallel(specs, ttl_seconds)
        except Exception as ex:
            logging.getLogger(__name__).warning("background news refresh failed: %s", ex)
    threading.Thread(target=worker, daemon=True).start()


def _has_news_for_categories(conn, categories: list) -> bool:
    """Quick check: ¿hay alguna noticia en DB para esas categorías?"""
    if not categories:
        return False
    placeholders = ','.join('?' for _ in categories)
    row = conn.execute(
        f"SELECT 1 FROM news WHERE category IN ({placeholders}) LIMIT 1",
        categories,
    ).fetchone()
    return row is not None


def _has_news_for_tickers(conn, tickers: list) -> bool:
    """Quick check: ¿hay news para AL MENOS uno de los tickers del user?

    Más granular que `_has_news_for_categories(['portfolio'])`: esa devuelve
    True si CUALQUIER user tiene portfolio news, pero los tickers del user
    activo pueden no estar fetcheados. Esta función chequea per-ticker para
    decidir si bloquear (cold cache del user) o ir directo a SWR.
    """
    if not tickers:
        return False
    # Pattern matches `_persist_news_items` query_source: "{TICKER} stock" o
    # "{TICKER} acciones". Usamos LIKE con prefix porque ticker es lo primero.
    like_clauses = ' OR '.join(['query_source LIKE ?'] * len(tickers))
    like_params = [f'{t} %' for t in tickers]
    row = conn.execute(
        f"SELECT 1 FROM news WHERE category='portfolio' AND ({like_clauses}) LIMIT 1",
        like_params,
    ).fetchone()
    return row is not None


# Semaphore global para limitar concurrencia process-wide de fetches de news.
# Sin esto, N usuarios concurrentes × 8 workers cada uno saturan el threadpool
# de FastAPI (default 40 threads) y todas las demás requests se cuelgan.
# 16 in-flight a la vez es suficiente para que el batch siga siendo rápido,
# pero acota el peor caso. Auditoría #2 E5.
import threading as _threading_news
_news_fetch_semaphore = _threading_news.BoundedSemaphore(16)

# Pool dedicado para news fetches (no usar with — global, lifetime = proceso).
# Cuando un batch llama con max_wait_seconds y se llega al timeout, los workers
# pendientes quedan en este pool corriendo en background — el caller libera
# pero el thread persiste hasta terminar su fetch + persist a DB.
# Sin esto, crear un nuevo executor por batch leakea memoria (cada batch
# acumula ~16 workers que no se reciclan).
_news_fetch_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="news-fetch")


def _ensure_news_batch_parallel(specs, ttl_seconds, max_workers=8, max_wait_seconds=None):
    """Versión paralelizada: fetcha múltiples feeds en threads concurrentes.

    `specs`: iterable de:
       • 3-tuplas (query, lang, category) — Google News (legacy, back-compat)
       • 4-tuplas (kind, identifier, lang_or_None, category) — multi-source
         con `kind ∈ {'google_news', 'investing'}`.

    `max_wait_seconds`: opcional. Si está set, la función NO espera más allá
    de ese tiempo total — los workers que no terminaron quedan corriendo en
    background (sus resultados se persisten cuando terminen). Sirve para que
    el endpoint que llama no se quede colgado en cold cache. Sin esto, con
    20 tickers + max_workers=8 + 6s timeout per fetch = hasta 18s blocking.
    Con `max_wait_seconds=4`, devolvemos a los 4s con lo que haya en DB.

    Cada worker:
      • Hace HTTP al source correspondiente (I/O-bound).
      • Persiste a DB en su propia conexión (sqlite3 no comparte cursors entre
        threads).
      • Captura su propio timestamp DESPUÉS del fetch para que el TTL refleje
        cuándo se obtuvo la data, no cuándo arrancó el batch.

    Errores individuales se aíslan + se loguean: una falla no rompe el resto.
    """
    now = time.time()

    # Normalizamos a 4-tuplas (kind, identifier, lang, category).
    normalized = []
    for s in specs:
        if len(s) == 3:
            q, lang, cat = s
            normalized.append(('google_news', q, lang, cat))
        elif len(s) == 4:
            normalized.append(tuple(s))
        # else: spec malformado — ignorar silenciosamente

    # Filtrar lo que está fresh — no spawneamos threads para esos.
    stale = [
        spec for spec in normalized
        if now - _news_fetched_at.get(_cache_key_for(spec[0], spec[3], spec[1]), 0) >= ttl_seconds
    ]
    if not stale:
        return

    def _worker(spec):
        # Adquirimos el semaphore global ANTES de hacer el fetch. Si todos los
        # slots están en uso (16 in-flight process-wide), esperamos. Esto
        # serializa graciosamente sin saturar el threadpool de FastAPI.
        with _news_fetch_semaphore:
            kind, identifier, lang, cat = spec
            local_conn = get_db()
            try:
                if kind == 'google_news':
                    _refresh_news_query(local_conn, identifier, lang, cat)
                elif kind == 'investing':
                    _refresh_investing_feed(local_conn, identifier, cat)
                else:
                    return  # source desconocido — skip
                _news_fetched_at[_cache_key_for(kind, cat, identifier)] = time.time()
            finally:
                local_conn.close()

    # IMPORTANTE: usamos el _news_fetch_executor GLOBAL (no `with` local) —
    # cuando hay max_wait_seconds, los futures que no terminan al timeout
    # quedan corriendo en background y persisten resultados a DB cuando
    # terminan. Un executor local con `with` bloquearía en __exit__,
    # defeats el timeout. Patrón idéntico al de _yf_executor.
    futures = [_news_fetch_executor.submit(_worker, spec) for spec in stale]

    if max_wait_seconds is not None:
        # Path con timeout: capper total tiempo de espera.
        deadline = time.time() + max_wait_seconds
        completed = 0
        try:
            for fut in as_completed(futures, timeout=max_wait_seconds + 0.5):
                remaining = deadline - time.time()
                if remaining <= 0:
                    break  # tiempo agotado — el resto sigue en bg
                try:
                    fut.result(timeout=max(remaining, 0.1))
                    completed += 1
                except Exception as e:
                    logging.getLogger(__name__).debug(
                        "news batch worker failed/timeout: %s", e
                    )
        except TimeoutError:
            pass  # as_completed timeout — esperado, no es error
        if completed < len(stale):
            logging.getLogger(__name__).info(
                "news batch returned early: %d/%d completed (max_wait=%ss). "
                "Resto sigue corriendo en background.",
                completed, len(stale), max_wait_seconds,
            )
        return

    # Path sin timeout — esperamos a TODOS los workers.
    for fut in as_completed(futures):
        try:
            fut.result()
        except Exception as e:
            logging.getLogger(__name__).warning(
                "news batch worker failed: %s", e
            )


@app.get("/api/news/market")
def get_market_news(
    limit: int = 20,
    uid: int = Depends(get_current_user),
):
    """Feed general del mercado — noticias macro y de índices populares.

    Combina queries hardcoded de USA + AR (FED, S&P, inflación, Merval, BCRA, etc.).
    """
    if limit <= 0 or limit > 100:
        raise HTTPException(422, "limit debe estar entre 1 y 100")

    specs = (
        [(q, lang, cat) for q, cat, lang in MARKET_NEWS_QUERIES] +
        [('investing', url, lang, cat) for url, cat, lang in INVESTING_FEEDS]
    )

    conn = get_db()
    try:
        # Stale-while-revalidate: si hay data en DB la devolvemos al instante
        # y refrescamos en background. Si NO hay nada (primer boot tras
        # restart de Railway antes que _prewarm_news_cache termine), bloqueamos
        # con cap de 4s — el resto sigue en bg.
        if _has_news_for_categories(conn, ['market', 'macro']):
            _refresh_news_in_background(specs, NEWS_MARKET_TTL)
        else:
            try:
                _ensure_news_batch_parallel(specs, NEWS_MARKET_TTL, max_wait_seconds=4)
            except Exception:
                pass

        # Fetcheamos MÁS rows que el limit final + filtramos en Python.
        # Esto cubre las noticias viejas que están en DB de antes del cambio
        # del filtro de relevancia (2026-05-26) — sin esto el feed seguiría
        # mostrando Insulet, Forgent, Suncrete, etc. hasta que rote naturalmente.
        # Overhead aceptable: ~5x rows fetchadas, filter in-mem es O(n) chico.
        rows = conn.execute(
            """SELECT title, summary, url, published_at, query_source,
                      category, source, tags
               FROM news
               WHERE category IN ('market', 'macro')
               ORDER BY published_at DESC
               LIMIT ?""",
            (limit * 5,),  # overfetch para tener margen tras filtro
        ).fetchall()

        # Re-aplicamos _is_market_relevant para descartar las que ya
        # estaban persistidas con el filtro viejo (más laxo).
        filtered = []
        for r in rows:
            item = {'title': r['title'] or '', 'summary': r['summary'] or ''}
            if _is_market_relevant(item):
                filtered.append(r)
            if len(filtered) >= limit:
                break

        return {'news': [_news_row_to_dict(r) for r in filtered], 'count': len(filtered)}
    finally:
        conn.close()


@app.get("/api/news/portfolio")
def get_portfolio_news(
    limit: int = 15,
    uid: int = Depends(get_current_user),
):
    """Noticias relevantes a los tickers en el portfolio del user.

    Para cada ticker, query "{TICKER} stock" en Google News (con idioma según
    si es AR o US). Excluye crypto y cash. Cache TTL 30 min por ticker.
    """
    if limit <= 0 or limit > 100:
        raise HTTPException(422, "limit debe estar entre 1 y 100")

    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
               WHERE user_id=? AND is_cash=0 AND asset NOT IN ('USDT','USD','ARS')""",
            (uid,),
        ).fetchall()
        all_tickers = [r['asset'] for r in rows]
        # Filtrar crypto (no relevante para news en este endpoint)
        tickers = [t for t in all_tickers if t not in CRYPTO_SYMBOLS]
        if not tickers:
            return {'news': [], 'count': 0}

        # Build queries batch (cap a 20 para no martillar Google) + paralelo
        queries_batch = []
        for ticker in tickers[:20]:
            is_ar = (ticker in POPULAR_TICKERS_AR_ADR) or (ticker in AR_BONDS_DATA912)
            lang = "es" if is_ar else "en"
            query = f"{ticker} {'acciones' if is_ar else 'stock'}"
            queries_batch.append((query, lang, 'portfolio'))

        # SWR per-ticker: si tenemos news para AL MENOS un ticker del user,
        # refresh en background y devolvemos lo que hay. Si NINGÚN ticker
        # tiene news (cold cache real del user), bloqueamos pero con cap
        # tight de 4s — el resto continúa fetcheando en background, el user
        # ve lo que hayamos juntado y la próxima carga ya está caliente.
        #
        # Antes: `_has_news_for_categories(['portfolio'])` era category-wide,
        # un user con tickers únicos veía respuesta vacía (otros users habían
        # poblado la categoría pero no SUS tickers) → mala UX silenciosa.
        if _has_news_for_tickers(conn, tickers):
            _refresh_news_in_background(queries_batch, NEWS_TICKER_TTL)
        else:
            try:
                _ensure_news_batch_parallel(queries_batch, NEWS_TICKER_TTL, max_wait_seconds=4)
            except Exception:
                pass

        # Devolver noticias del portfolio matcheando query_source con cualquiera
        # de los tickers (que es el "{TICKER} stock"/"acciones" que sembramos).
        like_clauses = ' OR '.join(['query_source LIKE ?'] * len(tickers))
        like_params = [f'{t} %' for t in tickers]
        rows = conn.execute(
            f"""SELECT title, summary, url, published_at, query_source,
                       category, source, tags
                FROM news
                WHERE category = 'portfolio'
                  AND ({like_clauses})
                ORDER BY published_at DESC
                LIMIT ?""",
            (*like_params, limit),
        ).fetchall()

        # Extraer el ticker del query_source y parsear tags.
        result = []
        for r in rows:
            d = _news_row_to_dict(r)
            # query_source es "AAPL stock" o "GGAL acciones"
            d['ticker'] = d.get('query_source', '').split(' ', 1)[0] if d.get('query_source') else None
            result.append(d)
        return {'news': result, 'count': len(result)}
    finally:
        conn.close()


def _news_row_to_dict(row):
    """Convierte un sqlite3.Row de la tabla `news` a dict listo para el cliente.

    Parsea `tags` (CSV en DB → array en JSON). Si no hay tags, devuelve [].
    """
    d = dict(row)
    raw_tags = d.pop('tags', None)
    d['tags'] = [t for t in (raw_tags or '').split(',') if t] if raw_tags else []
    return d


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
# Acepta:
#  - Símbolos US/CEDEAR: NVDA, AAPL, GGAL
#  - Sufijo .BA para AR (TSLA.BA)
#  - Tickers con clase con guión: BRK-B, BF-B (Berkshire B, Brown-Forman B)
#  - Cripto USD: BTC-USD, ETH-USD (-USD se reconoce en path separado del normalize)
# Audit Pack A v2 fix: antes el regex bloqueaba BRK-B y similares.
_SYMBOL_RE = re.compile(r'^[A-Z0-9]{1,10}([\.\-][A-Z0-9]{1,4})?$')

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


# ─── Bonos AR — live price via data912.com ───────────────────────────────────
# data912 expone cotizaciones live de BYMA (que yfinance no cubre para bonos
# AR). Convención de los sufijos en data912:
#   • Sin sufijo (AL30, GD30, AE38, TX26): cotización en ARS pesos por 100 face.
#   • Sufijo D (AL30D, GD30D, AE38D): cotización USD MEP por 100 face.
#   • Sufijo C: cotización USD CCL por 100 face.
#
# Rendi mapea según el broker en el frontend:
#   • Broker ARS → fetcha el ticker sin sufijo (precio en ARS).
#   • Broker USD/USDT → fetcha ticker + "D" (precio USD MEP).
#
# Convertimos data912 (per 100 face) a "per VN" dividiendo por 100, así el
# resto del frontend que computa `value = price × quantity` funciona sin
# cambios de convención.

# Cobertura validada (2026-05-12): 11 soberanos canje 2020 + 5 CER con precio.
# ONs corporativas tienen tickers no-coincidentes con bondMeta.js — se fixea
# por separado actualizando los IDs en bondMeta.
AR_BONDS_DATA912 = {
    'AL29', 'AL30', 'AL35', 'AE38', 'AL41',
    'GD29', 'GD30', 'GD35', 'GD38', 'GD41', 'GD46',
    'TX26', 'TX28', 'T2X5', 'TZX26', 'TZX27', 'TZX28',
}

_data912_cache = {'data': None, 'ts': 0}
DATA912_TTL = 300  # 5 minutos — los precios cambian frecuente pero no hace
                   # falta refrescar más rápido para tracking de cartera


def _fetch_data912_bonds():
    """Fetch + cache de precios live de bonos AR. Devuelve dict {symbol: close}.

    Falla gracefully: si data912 cae, devolvemos el cache anterior (puede ser
    stale pero mejor que nada) o {} si nunca tuvimos data.
    """
    now = time.time()
    cached = _data912_cache['data']
    if cached is not None and now - _data912_cache['ts'] < DATA912_TTL:
        return cached
    try:
        result = {}
        for endpoint in ('arg_bonds', 'arg_corp'):
            r = requests.get(f"https://data912.com/live/{endpoint}", timeout=8)
            if r.status_code != 200:
                continue
            for item in r.json():
                sym = item.get('symbol')
                close = item.get('c')
                if sym and close and close > 0:
                    result[sym] = close
        if result:  # sólo actualizamos cache si hubo data nueva
            _data912_cache['data'] = result
            _data912_cache['ts'] = now
        return result
    except Exception:
        return cached or {}


def _resolve_ar_bond_price(symbol):
    """Resuelve el precio per-VN de un bono AR usando data912.

    Reglas de mapeo según convención del frontend (ver `fetchPrices` en
    Positions.jsx):
      • Sufijo .BA: tipico de broker ARS → usamos el ticker base SIN sufijo
        para obtener precio en ARS por 100 face → divido por 100.
      • Sin sufijo .BA: vino de broker USD/USDT → usamos ticker base + 'D'
        para obtener precio USD MEP por 100 face → divido por 100.

    Devuelve None si el ticker no está en AR_BONDS_DATA912 o data912 no
    tiene precio. El caller cae a yfinance como fallback.
    """
    if not symbol:
        return None
    base = symbol[:-3] if symbol.endswith('.BA') else symbol
    if base not in AR_BONDS_DATA912:
        return None
    prices = _fetch_data912_bonds()
    if not prices:
        return None
    # ARS si vino con .BA, USD MEP si vino sin sufijo
    lookup_key = base if symbol.endswith('.BA') else (base + 'D')
    raw = prices.get(lookup_key)
    if raw is None or raw <= 0:
        return None
    # data912 quotea per 100 face. El resto del sistema usa per VN.
    return raw / 100.0


# ─── Cache in-memory para /api/prices ────────────────────────────────────────
# Endpoint más caliente del stack: Dashboard, Positions, Insights, HomeMobile,
# Goals y Events lo pegan en cada page-mount con sets de símbolos casi
# idénticos (las posiciones del user). Sin cache, cada navegación entre
# páginas re-ejecuta yf.download() — 1-4s contra Yahoo Finance.
#
# Cache PER-SYMBOL (no per-set) — más granular. Si Dashboard pide 15 syms y
# Positions pide 18 syms con 13 overlap, el 2° hit solo fetchea los 5 nuevos.
#
# TTL 60s: igual que _QUOTE_CACHE en home/market.py. Los precios intraday
# cambian seguido pero 60s es aceptable para UX (LCP < 200ms) — la mayoría
# de queries dentro de una sesión activa hit cache.
#
# Thread-safe con Lock (FastAPI ejecuta requests en threadpool por default).
import threading as _threading_prices
_PRICE_CACHE: dict = {}  # symbol → (timestamp_epoch, price_or_None)
_PRICE_CACHE_TTL_S = 60
_PRICE_CACHE_LOCK = _threading_prices.Lock()

# Stats acumulados — loggeamos a INFO cada N lookups para observabilidad.
# Sin esto, si el cache regresa (TTL=0, lock contention, etc.) no nos
# enteramos hasta que la app se sienta lenta. Con esto vemos en logs el
# hit rate en tiempo real.
_PRICE_CACHE_STATS = {"hits": 0, "misses": 0, "lookups": 0}
_PRICE_CACHE_LOG_EVERY = 100  # log cada 100 lookups acumulados


def _prices_cache_get(symbols: list[str]) -> tuple[dict, list[str]]:
    """Returns (cached_results, uncached_symbols). Cached incluye None values."""
    now = time.time()
    cached: dict = {}
    uncached: list[str] = []
    hits = 0
    misses = 0
    with _PRICE_CACHE_LOCK:
        for sym in symbols:
            entry = _PRICE_CACHE.get(sym)
            if entry is not None and (now - entry[0]) < _PRICE_CACHE_TTL_S:
                cached[sym] = entry[1]
                hits += 1
            else:
                uncached.append(sym)
                misses += 1
        _PRICE_CACHE_STATS["hits"] += hits
        _PRICE_CACHE_STATS["misses"] += misses
        _PRICE_CACHE_STATS["lookups"] += 1
        # Log periódico — cada N lookups (no por símbolo, para no spammear).
        if _PRICE_CACHE_STATS["lookups"] % _PRICE_CACHE_LOG_EVERY == 0:
            total = _PRICE_CACHE_STATS["hits"] + _PRICE_CACHE_STATS["misses"]
            ratio = (_PRICE_CACHE_STATS["hits"] / total * 100) if total > 0 else 0
            log.info(
                "prices_cache stats: lookups=%d total_syms=%d hits=%d misses=%d hit_rate=%.1f%% cache_size=%d",
                _PRICE_CACHE_STATS["lookups"], total, _PRICE_CACHE_STATS["hits"],
                _PRICE_CACHE_STATS["misses"], ratio, len(_PRICE_CACHE),
            )
    return cached, uncached


def _prices_cache_set(prices: dict) -> None:
    """Persiste resultados en cache. Cachea AMBOS hits y misses (None) — si
    yfinance no devolvió price, no insistimos en re-fetchear durante 60s."""
    now = time.time()
    with _PRICE_CACHE_LOCK:
        for sym, price in prices.items():
            _PRICE_CACHE[sym] = (now, price)


# ─── Prev-close cache (variación diaria por posición) ───────────────────────
# Cierre del día hábil ANTERIOR por símbolo. A diferencia del precio live,
# cambia 1×/día (al cerrar el mercado) → TTL largo (10 min). Mismo patrón
# thread-safe que _PRICE_CACHE. Cachea None para no reintentar símbolos sin
# cobertura (ej. bonos AR de data912, que yfinance no tiene).
_PREVCLOSE_CACHE: dict = {}  # symbol → (timestamp_epoch, prevclose_or_None)
_PREVCLOSE_CACHE_TTL_S = 600
_PREVCLOSE_CACHE_LOCK = _threading_prices.Lock()


def _prevclose_cache_get(symbols: list[str]) -> tuple[dict, list[str]]:
    """Returns (cached_results, uncached_symbols). Cached incluye None values."""
    now = time.time()
    cached: dict = {}
    uncached: list[str] = []
    with _PREVCLOSE_CACHE_LOCK:
        for sym in symbols:
            entry = _PREVCLOSE_CACHE.get(sym)
            if entry is not None and (now - entry[0]) < _PREVCLOSE_CACHE_TTL_S:
                cached[sym] = entry[1]
            else:
                uncached.append(sym)
    return cached, uncached


def _prevclose_cache_set(values: dict) -> None:
    now = time.time()
    with _PREVCLOSE_CACHE_LOCK:
        for sym, v in values.items():
            _PREVCLOSE_CACHE[sym] = (now, v)


@app.get("/api/prices")
def get_prices(symbols: str, uid: int = Depends(get_current_user)):
    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    # Validate each symbol format
    sym_list = [s for s in raw if _SYMBOL_RE.match(s)]

    # Hard cap to prevent resource abuse
    sym_list = sym_list[:MAX_SYMBOLS]

    if not sym_list:
        return {}

    # ─── Layer 1: cache hit fast path ───────────────────────────────────────
    # Si TODOS los símbolos están cacheados frescos (< 60s), devolvemos sin
    # tocar data912 ni yfinance. Típico de navegación entre páginas: 2do hit
    # en < 5ms.
    cached_results, uncached_symbols = _prices_cache_get(sym_list)
    if not uncached_symbols:
        return cached_results

    # Hay misses — procesamos solo los uncached. Resultado base incluye lo
    # que ya teníamos cacheado para no perderlo en el merge final.
    result = dict(cached_results)
    for sym in uncached_symbols:
        result[sym] = None

    # Phase 3F: prefetch de bonos AR via data912.com (precio live de BYMA).
    # Para tickers conocidos como bonos AR canje 2020 o CER, resolvemos acá
    # — yfinance no tiene cobertura. Lo que NO resuelva data912 (acciones,
    # ETFs, crypto, ONs corporativas con tickers exactos no cubiertos) cae
    # al path yfinance de abajo.
    yf_targets = []
    for sym in uncached_symbols:
        ar_price = _resolve_ar_bond_price(sym)
        if ar_price is not None:
            result[sym] = ar_price
        else:
            yf_targets.append(sym)

    if not yf_targets:
        # Solo había símbolos resolved por data912 — persistir y salir.
        _prices_cache_set({sym: result[sym] for sym in uncached_symbols})
        return result

    sym_to_yf = {}
    for sym in yf_targets:
        sym_to_yf[sym] = CRYPTO_YF[sym] if sym in CRYPTO_YF else sym

    yf_tickers = list(set(sym_to_yf.values()))

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

    for sym in [s for s in yf_targets if result[s] is None]:
        yf_t = sym_to_yf[sym]
        price = _fetch_one(yf_t)
        if price is None and not sym.endswith('.BA') and sym not in CRYPTO_YF:
            price = _fetch_one(f"{sym}-USD")
        result[sym] = price

    # Persistir todos los uncached que acabamos de fetchear (incluyendo None
    # para los que fallaron — evita retry storm si Yahoo está down).
    _prices_cache_set({sym: result[sym] for sym in uncached_symbols})
    return result


@app.get("/api/prices/prev-close")
def get_prev_close(symbols: str, uid: int = Depends(get_current_user)):
    """Cierre del día hábil ANTERIOR por símbolo — base de la variación diaria
    por posición en Positions. Mismo shape que /api/prices: {symbol: number|null}.

    ADITIVO: no toca /api/prices ni sus consumidores. El frontend computa el
    delta del día con (precio_actual − prev_close) × cantidad, usando el precio
    que ya muestra la fila (de /api/prices) para que los números reconcilien.

    Reusa el mismo download mensual de yfinance que /api/prices (period="1mo",
    auto_adjust=True) pero toma el PENÚLTIMO cierre válido (iloc[-2]). Símbolos
    sin cobertura yfinance (ej. bonos AR vía data912) devuelven null → el
    frontend muestra '—' para esas filas.
    """
    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    sym_list = [s for s in raw if _SYMBOL_RE.match(s)][:MAX_SYMBOLS]
    if not sym_list:
        return {}

    cached_results, uncached_symbols = _prevclose_cache_get(sym_list)
    if not uncached_symbols:
        return cached_results

    result = dict(cached_results)
    for sym in uncached_symbols:
        result[sym] = None

    # Crypto mapea a su ticker yfinance (BTC → BTC-USD, etc), igual que /api/prices.
    sym_to_yf = {sym: (CRYPTO_YF[sym] if sym in CRYPTO_YF else sym) for sym in uncached_symbols}
    yf_tickers = list(set(sym_to_yf.values()))

    try:
        data = yf.download(" ".join(yf_tickers), period="1mo", progress=False, auto_adjust=True)
        if not data.empty:
            close = data.get("Close") if hasattr(data, 'get') else (data["Close"] if "Close" in data.columns else None)
            if close is not None and not (hasattr(close, 'empty') and close.empty):
                for sym, yf_t in sym_to_yf.items():
                    try:
                        # Multi-ticker → columna por ticker; single-ticker → Series directa.
                        if hasattr(close, 'columns') and yf_t in getattr(close, 'columns', []):
                            ser = close[yf_t].dropna()
                        elif not hasattr(close, 'columns'):
                            ser = close.dropna()
                        else:
                            ser = None
                        if ser is not None and len(ser) >= 2:
                            prev = float(ser.iloc[-2])
                            if not math.isnan(prev) and prev > 0:
                                result[sym] = prev
                    except Exception:
                        pass
    except Exception:
        pass

    _prevclose_cache_set({sym: result[sym] for sym in uncached_symbols})
    return result


# ─── Historical prices (mini-chart en AssetQuickView) ───────────────────────
# Cache simple in-memory keyed por (symbol, period). yfinance fetchea las
# series históricas — para periods chicos (1mo) es rápido. TTL 1h porque
# las velas diarias no cambian dentro del día.

_history_cache: dict = {}  # key → (timestamp, data)
_HISTORY_TTL_S = 3600  # 1 hora

_HISTORY_PERIODS = {
    "1w":  ("7d",   "1d"),    # 7 días, vela diaria
    "1m":  ("1mo",  "1d"),    # 30 días, vela diaria
    "3m":  ("3mo",  "1d"),    # 90 días, vela diaria
    "1y":  ("1y",   "1wk"),   # 1 año, vela semanal (52 puntos)
}


@app.get("/api/prices/history")
def get_price_history(symbol: str, period: str = "1m", uid: int = Depends(get_current_user)):
    """Devuelve serie histórica de close-prices para mini-chart.

    Params:
      symbol — ticker (formato igual que /api/prices: AAPL, BTC, BMA.BA, etc.)
      period — '1w' | '1m' | '3m' | '1y' (default '1m')

    Response:
      {
        symbol: str,
        period: str,
        points: [{date: 'YYYY-MM-DD', close: float}, ...]
      }
    """
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(400, f"Símbolo inválido: {symbol}")
    if period not in _HISTORY_PERIODS:
        raise HTTPException(400, f"period inválido. Usa: {list(_HISTORY_PERIODS.keys())}")

    cache_key = f"{sym}:{period}"
    now = time.time()
    cached = _history_cache.get(cache_key)
    if cached and (now - cached[0]) < _HISTORY_TTL_S:
        return cached[1]

    # Resolver el símbolo igual que /api/prices: bono AR via data912, sino yfinance
    yf_period, interval = _HISTORY_PERIODS[period]
    yf_sym = sym
    if sym in CRYPTO_YF:
        yf_sym = CRYPTO_YF[sym]
    elif sym.endswith(".BA"):
        yf_sym = sym  # yfinance entiende el .BA directo
    elif not sym.endswith(".BA"):
        # Para cripto sin sufijo (BTC, ETH) que no estén en CRYPTO_YF, probamos -USD
        # solo si no es un ticker conocido US.
        pass

    points = []
    try:
        ticker = yf.Ticker(yf_sym)
        hist = ticker.history(period=yf_period, interval=interval, auto_adjust=False)
        if hist.empty and yf_sym == sym and not sym.endswith(".BA") and "-" not in sym:
            # Retry con sufijo -USD para crypto desconocido
            ticker = yf.Ticker(f"{sym}-USD")
            hist = ticker.history(period=yf_period, interval=interval, auto_adjust=False)
        if not hist.empty:
            for idx, row in hist.iterrows():
                close = row.get("Close")
                if close is None or (hasattr(close, "__float__") and math.isnan(float(close))):
                    continue
                points.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "close": round(float(close), 4),
                })
    except Exception as ex:
        # No raise — devolvemos series vacía, el frontend muestra "sin chart"
        pass

    result = {"symbol": sym, "period": period, "points": points}
    _history_cache[cache_key] = (now, result)
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
        _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
    return dict(row)


@app.delete("/api/positions/{pid}")
def delete_position(pid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (pid, uid))
    conn.commit()
    conn.close()
    _ai_cache_invalidate(uid)
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


def _recalc_pnl_realized_from_ops(conn, uid: int) -> int:
    """Recalcula `monthly_entries.pnl_realized`, `deposits` y `withdrawals`
    desde las fuentes (operations + import_normalized_tx confirmados).

    Self-healing de drift acumulado por cycles import/revert/reimport con
    cálculos cambiantes entre versiones. Cada fila queda con:
      pnl_realized = SUM(operations.pnl_usd)
      deposits     = SUM(imports DEPOSIT en USD) + MANUAL RESIDUAL
      withdrawals  = SUM(imports WITHDRAW en USD) + MANUAL RESIDUAL

    Para broker='global', suma cross-broker.

    Re-repara la cadena de capital_final.

    HISTORIA (bug fix 2026-05-27): antes esta función SOBREESCRIBÍA
    deposits/withdrawals con SOLO los valores de imports → los cash flows
    manuales del user (form /mensual + botón Cash + reconcile-cash) se
    ZERO-eaban silenciosamente cada vez que se llamaba (post-import,
    post-revert). El user perdía sus deposits manuales sin notar.

    Fix: preservamos el residual manual. Calculamos `manual_residual =
    max(0, deposits_actual - imports_DEPOSIT_USD)`. El nuevo deposits =
    imports_DEPOSIT_USD + manual_residual. Si el residual era 0 (nada
    manual cargado), el resultado es el mismo que antes — y los tests
    que validaban la reconstrucción desde imports siguen pasando.

    Idempotente. Devuelve cantidad de rows actualizados.
    """
    rows = conn.execute(
        "SELECT DISTINCT broker, year, month FROM monthly_entries WHERE user_id=?",
        (uid,),
    ).fetchall()
    updates = 0
    brokers_touched: set = set()
    # TC blue para convertir DEPOSITs/WITHDRAWs en ARS a USD-equivalente
    # (consistente con _persist_cash_in/out)
    tc_blue_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        tc_blue = float(tc_blue_row["value"]) if tc_blue_row else 1415.0
        if tc_blue <= 0:
            tc_blue = 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0

    for r in rows:
        broker, y, m = r["broker"], r["year"], r["month"]
        year_str = f"{y:04d}"
        month_str = f"{m:02d}"
        broker_filter_sql = "" if broker == "global" else " AND o.broker = ?"
        broker_filter_args = () if broker == "global" else (broker,)

        # 1) pnl_realized desde operations — ÚNICA fuente autoritativa
        pnl_row = conn.execute(
            f"""SELECT COALESCE(SUM(o.pnl_usd), 0) AS s FROM operations o
                WHERE o.user_id=?
                  AND strftime('%Y', o.date)=?
                  AND strftime('%m', o.date)=?
                  {broker_filter_sql}""",
            (uid, year_str, month_str, *broker_filter_args),
        ).fetchone()
        new_pnl = round(float(pnl_row["s"] or 0), 4)

        # 2) deposits + withdrawals desde imports (solo batches confirmed)
        tx_broker_filter = "" if broker == "global" else " AND n.broker = ?"
        tx_broker_args = () if broker == "global" else (broker,)
        flow_row = conn.execute(
            f"""SELECT n.operation_type AS op,
                       COALESCE(SUM(n.gross_amount), 0) AS s,
                       n.currency AS cur
                FROM import_normalized_tx n
                JOIN import_batches b ON b.id = n.batch_id
                WHERE b.user_id=? AND b.status='confirmed'
                  AND n.operation_type IN ('DEPOSIT', 'WITHDRAW')
                  AND strftime('%Y', n.date)=?
                  AND strftime('%m', n.date)=?
                  {tx_broker_filter}
                GROUP BY n.operation_type, n.currency""",
            (uid, year_str, month_str, *tx_broker_args),
        ).fetchall()
        imp_deposits = 0.0
        imp_withdrawals = 0.0
        for f in flow_row:
            amt = float(f["s"] or 0)
            cur_norm = (f["cur"] or "").upper()
            amt_usd = amt / tc_blue if cur_norm == "ARS" else amt
            if f["op"] == "DEPOSIT":
                imp_deposits += amt_usd
            else:
                imp_withdrawals += amt_usd

        # 3) Preservar residual MANUAL. Lo que está en monthly_entries por
        #    encima de la suma de imports es manual (form /mensual + cash_flow
        #    + reconcile-cash) y NO debe destruirse.
        existing = conn.execute(
            "SELECT deposits, withdrawals FROM monthly_entries WHERE user_id=? AND broker=? AND year=? AND month=?",
            (uid, broker, y, m),
        ).fetchone()
        existing_dep = float(existing["deposits"] or 0) if existing else 0.0
        existing_wit = float(existing["withdrawals"] or 0) if existing else 0.0
        # Residual manual = max(0, existing - imports). Si el persister es
        # correcto, existing >= imports siempre. El clamp a 0 protege contra
        # drift que daría residual negativo.
        manual_dep_residual = max(0.0, existing_dep - imp_deposits)
        manual_wit_residual = max(0.0, existing_wit - imp_withdrawals)
        new_deposits = round(imp_deposits + manual_dep_residual, 4)
        new_withdrawals = round(imp_withdrawals + manual_wit_residual, 4)

        # Reseteamos pnl_unrealized: live snapshot que se recalcula desde
        # positions via /sync-unrealized. Si quedó stale de cycles previos
        # rompe deltaUsd en /reportes.
        conn.execute(
            """UPDATE monthly_entries
               SET pnl_realized=?, pnl_unrealized=0,
                   deposits=?, withdrawals=?
               WHERE user_id=? AND broker=? AND year=? AND month=?""",
            (new_pnl, new_deposits, new_withdrawals, uid, broker, y, m),
        )
        updates += 1
        brokers_touched.add(broker)

    # Limpieza: borrar monthly_entries que quedaron TODAS en 0 después del recalc
    # (sin pnl, sin deposits, sin withdrawals, sin pnl_unrealized). Estas son
    # filas huérfanas de cycles previos que no tienen respaldo en ninguna fuente.
    # Sin borrarlas, su `capital_inicio` heredado de cycles anteriores ensucia
    # netDeposited del dashboard.
    conn.execute(
        """DELETE FROM monthly_entries
            WHERE user_id=?
              AND COALESCE(deposits, 0) = 0
              AND COALESCE(withdrawals, 0) = 0
              AND COALESCE(pnl_realized, 0) = 0
              AND COALESCE(pnl_unrealized, 0) = 0""",
        (uid,),
    )

    # Si tras el recalc no quedan positions ni operations ni monthly_entries,
    # el user está en "estado limpio" — también borramos snapshots stale para
    # que el gráfico de evolución no muestre data de cycles previos.
    has_positions = conn.execute(
        "SELECT 1 FROM positions WHERE user_id=? LIMIT 1", (uid,),
    ).fetchone()
    has_operations = conn.execute(
        "SELECT 1 FROM operations WHERE user_id=? LIMIT 1", (uid,),
    ).fetchone()
    has_monthly = conn.execute(
        "SELECT 1 FROM monthly_entries WHERE user_id=? LIMIT 1", (uid,),
    ).fetchone()
    if not has_positions and not has_operations and not has_monthly:
        conn.execute("DELETE FROM snapshots WHERE user_id=?", (uid,))

    # Para brokers que SÍ tienen actividad, resetear capital_inicio del primer
    # mes a 0 (es la "baseline" y debería empezar en 0 si nada precede al
    # primer movimiento; _repair_monthly_chain propaga forward desde ahí).
    for b in brokers_touched:
        first = conn.execute(
            """SELECT id FROM monthly_entries
               WHERE user_id=? AND broker=?
               ORDER BY year ASC, month ASC LIMIT 1""",
            (uid, b),
        ).fetchone()
        if first:
            conn.execute(
                "UPDATE monthly_entries SET capital_inicio=0 WHERE id=?",
                (first["id"],),
            )

    # Re-reparar capital_final chain con los nuevos valores
    for b in brokers_touched:
        _repair_monthly_chain(conn, uid, b)
    return updates


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
    - Si NO hay cash position pero hay un movimiento (delta != 0), la creamos
      automáticamente con el delta como balance inicial. Antes era opt-in (no-op
      si no había cash), pero eso causaba que imports con BUYs sin DEPOSITs
      previos quedaran con cash $0 en la pantalla — confuso. Ahora los BUYs
      generan un balance negativo visible (señal de que falta cargar el cash
      inicial / hacer un import del estado inicial).
    - Se permiten balances negativos — señal visible de overdraft / margen.
    """
    if delta == 0:
        return
    cash = conn.execute(
        "SELECT id, invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
        (uid, broker),
    ).fetchone()
    if not cash:
        # Inferir el asset name según la moneda del broker. Si no hay broker
        # row (caso raro), default a USDT.
        broker_row = conn.execute(
            "SELECT currency FROM brokers WHERE user_id=? AND name=? LIMIT 1",
            (uid, broker),
        ).fetchone()
        currency = broker_row["currency"] if broker_row else "USDT"
        # ARS para brokers en pesos; USD para brokers tradicionales; USDT para
        # exchanges crypto. Antes USD se forzaba a USDT — ahora es independiente.
        asset_name = "ARS" if currency == "ARS" else ("USD" if currency == "USD" else "USDT")
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (uid, broker, asset_name, delta),
        )
        return
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


class BrokerReconcileCashIn(BaseModel):
    """Reconcilia el cash de un broker con el balance real reportado por el
    broker externo (ej.: lo que ves cuando abrís Schwab en la app)."""
    broker_name: str = Field(..., min_length=1, max_length=MAX_STR)
    target_cash: float = Field(..., ge=-1e12, le=1e12)  # cash real ahora — puede ser 0
    tc_blue: float = Field(1415, gt=0, le=1_000_000)    # ARS→USD para monthly_entries global

    @field_validator('broker_name')
    @classmethod
    def strip_broker(cls, v):
        return v.strip()


@app.post("/api/brokers/reconcile-cash")
def broker_reconcile_cash(data: BrokerReconcileCashIn, uid: int = Depends(get_current_user)):
    """Ajusta el cash actual de un broker a un valor real (el que el broker
    externo reporta), y registra la diferencia como movimiento sintético en
    el primer mes del broker — de modo que:

      • La posición cash queda en el valor exacto que dijo el usuario.
      • La diferencia se acredita/debita en `monthly_entries` del mes más
        antiguo del broker, así "capital aportado" refleja correctamente
        el cash pre-CSV (deposits) o las salidas pre-CSV que el CSV no
        capturó (withdrawals).

    Casos:
      • diff > 0 (target > computed) → DEPOSITO sintético = cash que ya estaba
        antes de que arranque el CSV. Suma a "capital aportado".
      • diff < 0 (target < computed) → RETIRO sintético = cash que salió por
        movimientos que el CSV no incluyó. Resta de "capital aportado".

    Útil después de un import con CSV parcial (historia incompleta del broker).
    """
    conn = get_db()
    try:
        with conn:
            broker_row = conn.execute(
                "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, data.broker_name),
            ).fetchone()
            if not broker_row:
                raise HTTPException(404, f"Broker '{data.broker_name}' no encontrado")
            currency = broker_row['currency']

            # 1. Cash actual del broker
            cash_pos = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                (uid, data.broker_name),
            ).fetchone()
            current_cash = float(cash_pos['invested'] or 0) if cash_pos else 0.0
            diff = round(data.target_cash - current_cash, 6)

            if abs(diff) < 0.01:
                return {"ok": True, "no_change": True, "current_cash": current_cash}

            # 2. Update / create cash position con el target exacto
            if cash_pos:
                conn.execute(
                    "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                    (data.target_cash, cash_pos['id'], uid),
                )
            else:
                asset_name = 'ARS' if currency == 'ARS' else ('USD' if currency == 'USD' else 'USDT')
                conn.execute(
                    """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
                       VALUES (?,?,?,1,?)""",
                    (uid, data.broker_name, asset_name, data.target_cash),
                )

            # 3. Registrar diff en monthly_entries del mes más antiguo del broker
            # (preserva cronología — el ajuste representa historia pre-CSV).
            first = conn.execute(
                """SELECT year, month FROM monthly_entries
                   WHERE user_id=? AND broker=? ORDER BY year, month LIMIT 1""",
                (uid, data.broker_name),
            ).fetchone()
            if first:
                target_year, target_month = first['year'], first['month']
            else:
                # Sin historia previa — usar mes actual
                now = datetime.utcnow()
                target_year, target_month = now.year, now.month

            direction = 'deposit' if diff > 0 else 'withdraw'
            magnitude = abs(diff)
            # Convertir a USD para monthly_entries (que vive en USD)
            amount_usd = magnitude / data.tc_blue if currency == 'ARS' else magnitude

            _update_monthly_flow(conn, uid, data.broker_name, target_year, target_month,
                                 direction, amount_usd)
            _update_monthly_flow(conn, uid, 'global', target_year, target_month,
                                 direction, amount_usd)
            _repair_monthly_chain(conn, uid, data.broker_name)
            _repair_monthly_chain(conn, uid, 'global')

        return {
            "ok": True,
            "broker": data.broker_name,
            "previous_cash": current_cash,
            "new_cash": data.target_cash,
            "diff": diff,
            "diff_direction": direction,
            "recorded_in_period": f"{target_year}-{target_month:02d}",
        }
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al reconciliar cash: {ex}")
    finally:
        conn.close()


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
                # Solo bloqueamos cuando es un WITHDRAW que dejaría negativo.
                # Para DEPOSIT permitimos siempre (incluso si el resultado sigue
                # negativo porque la deuda era mayor al depósito — la idea es
                # ir reduciendo el overdraft progresivamente).
                if data.direction == 'withdraw' and new_invested < 0:
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
                asset_name = 'ARS' if currency == 'ARS' else ('USD' if currency == 'USD' else 'USDT')
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


# ─── Bonos: cobranza de cupones / amortizaciones ─────────────────────────────

class BondCashflowIn(BaseModel):
    """Registro de un pago recibido de un bono (cupón o amortización).

    Phase 3D: agrega tracking de moneda + FX para enable reportes cross-broker
    + reduce quantity de la posición cuando es amortización (cost basis amortizante).

    Crea:
      1. Una operation type='Cupón' o 'Amortización' con currency + fx_to_usd
         stampados.
      2. Acreditación al cash del broker por el monto neto.
      3. Si decrement_quantity=True Y flow_type='amortization': reduce FIFO la
         quantity + invested de los lotes de la posición proporcionalmente al
         face amortizado.

    Todo atómico.
    """
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=20)
    flow_type: str = Field(..., max_length=20)  # 'coupon' | 'amortization'
    amount: float = Field(..., gt=0, le=1e12)
    date: str = Field(..., max_length=10)
    commissions: Optional[float] = Field(0, ge=0, le=1e12)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES)
    # Phase 3D fields (todos opcionales para backward-compat):
    #   • currency: moneda nativa del flujo. Default: derivada del broker.
    #   • fx_to_usd: factor nativa→USD al momento del evento. Default: 1.0 si
    #     broker es USD/USDT, NULL si ARS (frontend mostrará warning).
    #   • decrement_quantity: si True Y flow_type='amortization', se reduce la
    #     quantity de la posición. Default: False (preserva comportamiento legacy).
    currency: Optional[str] = Field(None, max_length=10)
    fx_to_usd: Optional[float] = Field(None, gt=0, le=1e6)
    decrement_quantity: Optional[bool] = Field(False)
    # Phase 3F: cantidad explícita de VN a decrementar cuando decrement_quantity=True.
    # Necesario para evitar el bug cross-currency (broker ARS + bono USD):
    # `amount` está en pesos pero `quantity` está en VN; trataralos como
    # equivalentes borra la posición entera.
    # Si está NULL, fallback a `amount` como qty (comportamiento legacy — sólo
    # seguro si broker_currency == bond_currency).
    face_amortized: Optional[float] = Field(None, ge=0, le=1e12)

    @field_validator('flow_type')
    @classmethod
    def valid_flow_type(cls, v):
        if v not in ('coupon', 'amortization'):
            raise ValueError("flow_type debe ser 'coupon' o 'amortization'")
        return v

    @field_validator('date')
    @classmethod
    def valid_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v


@app.post("/api/bonds/cashflow")
def bond_cashflow(data: BondCashflowIn, uid: int = Depends(get_current_user)):
    """Registra un cupón cobrado o amortización recibida de un bono.

    Hace 2-3 cosas atómicamente:
      1. INSERT en operations (op_type='Cupón' o 'Amortización') con
         currency + fx_to_usd stampados.
      2. _adjust_cash del broker por el monto neto (amount - commissions).
      3. Si decrement_quantity=True Y flow_type='amortization': reduce FIFO
         la quantity + invested de los lotes hasta cubrir el monto amortizado.
         Esto refleja que en un bono amortizante, cada amort te devuelve face
         (reduce tu nominal en cartera) — sin afectar tu cost basis por VN
         remanente.

    El monto se acredita en la moneda del broker (USDT/USD/ARS). Si el bono
    paga en USD pero el broker es ARS, el user carga el equivalente en pesos.
    """
    conn = get_db()
    try:
        # Validar broker existe y es del user
        broker_row = conn.execute(
            "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, data.broker)
        ).fetchone()
        if not broker_row:
            raise HTTPException(404, f"Broker '{data.broker}' no encontrado")

        op_type = 'Cupón' if data.flow_type == 'coupon' else 'Amortización'
        commissions = data.commissions or 0
        net_amount = data.amount - commissions
        if net_amount <= 0:
            raise HTTPException(400, "El monto neto (descontando comisiones) debe ser > 0")

        # Resolver currency + fx_to_usd con defaults sensatos.
        broker_currency = broker_row['currency']
        currency = data.currency or broker_currency
        if data.fx_to_usd is not None:
            fx_to_usd = data.fx_to_usd
        elif broker_currency in ('USD', 'USDT'):
            fx_to_usd = 1.0  # ya es USD-equivalente
        else:
            fx_to_usd = None  # ARS sin FX explícito — frontend usa fallback

        with conn:  # tx atómica
            # Pre-cálculo del cost basis consumido para amortizaciones.
            # Esto se necesita ANTES del INSERT para guardarlo en la operation,
            # y también ANTES del decrement (si aplica) — aunque si decrementamos,
            # la versión "read-only" debería dar el mismo número que la "mutate".
            cost_basis_consumed = None
            qty_decremented = 0.0
            invested_decremented = 0.0
            cross_currency_skipped = False
            if data.flow_type == 'amortization':
                # Resolver la qty a decrementar. Si el frontend pasó
                # `face_amortized` explícito (caso cross-currency, donde
                # `amount` está en moneda del broker pero la qty está en VN
                # del bono), usamos ESE valor. Sino, fallback a `net_amount`
                # como qty (comportamiento legacy — sólo correcto cuando
                # broker_currency == bond_currency).
                face_to_decrement = (
                    data.face_amortized
                    if data.face_amortized is not None and data.face_amortized > 0
                    else net_amount
                )
                if data.decrement_quantity:
                    # Sanity check (Phase 3F / hallazgo N1): si la qty a
                    # decrementar parece desproporcionadamente alta vs el
                    # face disponible (e.g., user pasó amount en ARS sin
                    # face_amortized → 95.000 ARS vs 1.000 VN), abortamos
                    # el decrement para no destruir la posición. Igual
                    # registramos la operation + acreditamos el cash.
                    total_qty = _bond_total_qty(conn, uid, data.broker, data.asset.upper())
                    if total_qty > 0 and face_to_decrement > total_qty * 1.5:
                        cross_currency_skipped = True
                        # Calculamos cost basis conservador sobre el face
                        # plausible (al menos quedó la cobranza registrada).
                        plausible_face = min(face_to_decrement, total_qty)
                        cost_basis_consumed = _compute_amort_cost_basis_fifo(
                            conn, uid, data.broker, data.asset.upper(), plausible_face
                        )
                    else:
                        qty_decremented, invested_decremented = _amortize_position_fifo(
                            conn, uid, data.broker, data.asset.upper(), face_to_decrement
                        )
                        cost_basis_consumed = invested_decremented
                else:
                    # Calcular sin tocar las posiciones — útil para tracking
                    # del P&L real cuando el user prefiere mantener qty intacta.
                    cost_basis_consumed = _compute_amort_cost_basis_fifo(
                        conn, uid, data.broker, data.asset.upper(), face_to_decrement
                    )

            # 1. Insert operation (con cost_basis_consumed si aplica)
            conn.execute(
                """INSERT INTO operations (user_id, date, broker, asset, op_type,
                   pnl_usd, commissions, notes, currency, fx_to_usd, cost_basis_consumed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (uid, data.date, data.broker, data.asset.upper(), op_type,
                 net_amount, commissions, data.notes, currency, fx_to_usd, cost_basis_consumed),
            )
            # 2. Acreditar cash del broker
            _adjust_cash(conn, uid, data.broker, _cash_asset_for_currency(broker_currency), net_amount)

        # Ganancia realizada del amort (sólo para diagnóstico / response):
        # cash recibido − cost basis consumido. Para cupones siempre = cash.
        realized_gain = None
        if data.flow_type == 'amortization' and cost_basis_consumed is not None:
            realized_gain = round(net_amount - cost_basis_consumed, 6)

        return {
            'ok': True,
            'amount_net': net_amount,
            'op_type': op_type,
            'broker': data.broker,
            'asset': data.asset.upper(),
            'currency': currency,
            'fx_to_usd': fx_to_usd,
            'qty_decremented': qty_decremented,
            'invested_decremented': invested_decremented,
            'cost_basis_consumed': cost_basis_consumed,
            'realized_gain': realized_gain,
            # Flag para el frontend: si pidió decrement pero el sanity check
            # lo aborto (probable mismatch ARS/VN cross-currency), el toast
            # del frontend explica que la cobranza se registró pero la qty
            # quedó intacta.
            'cross_currency_skipped': cross_currency_skipped,
        }
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al registrar el cashflow del bono: {ex}")
    finally:
        conn.close()


def _bond_total_qty(conn, uid: int, broker: str, asset: str) -> float:
    """Suma de quantity de todos los lotes de (broker, asset) — para sanity
    checks que necesitan saber el face total disponible antes de decrementar.
    """
    row = conn.execute(
        """SELECT COALESCE(SUM(quantity), 0) AS total FROM positions
           WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 AND quantity > 0""",
        (uid, broker, asset),
    ).fetchone()
    return float(row['total'] or 0)


def _compute_amort_cost_basis_fifo(conn, uid: int, broker: str, asset: str, amort_amount: float) -> float:
    """Versión READ-ONLY de _amortize_position_fifo. Calcula cuánto cost basis
    SE CONSUMIRÍA al aplicar una amortización FIFO, sin modificar las posiciones.

    Útil cuando el user registra una amortización pero NO quiere decrementar la
    quantity (decrement_quantity=false): igual queremos saber la ganancia
    realizada del amort para reportes de P&L correctos.

    Devuelve 0 si no hay posiciones de ese (broker, asset) o si amort_amount
    es 0 o no aplica.
    """
    lots = conn.execute(
        """SELECT quantity, invested FROM positions
           WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 AND quantity > 0
           ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, broker, asset),
    ).fetchall()
    if not lots or amort_amount <= 0:
        return 0.0
    total_qty = sum((l['quantity'] or 0) for l in lots)
    qty_to_take = min(amort_amount, total_qty)
    if qty_to_take <= 0:
        return 0.0
    remaining = qty_to_take
    total_consumed = 0.0
    for lot in lots:
        if remaining <= 1e-9:
            break
        lot_qty = lot['quantity'] or 0
        take = min(remaining, lot_qty)
        if take <= 0:
            continue
        ratio = take / lot_qty
        total_consumed += (lot['invested'] or 0) * ratio
        remaining -= take
    return round(total_consumed, 6)


def _amortize_position_fifo(conn, uid: int, broker: str, asset: str, amort_amount: float):
    """Reduce FIFO la quantity + invested de los lotes de (broker, asset).

    Conceptualmente: una amortización te devuelve `amort_amount` de face value.
    Para bonos AR canje 2020 (USD denominado, 1 VN = 1 USD face), eso significa
    qty_a_descontar = amort_amount. Cada lote se reduce proporcionalmente:
        ratio = take / lot.quantity
        lot.quantity -= take
        lot.invested *= (1 - ratio)  # cost basis remanente proporcional
        lot.commissions *= (1 - ratio)

    Si el monto excede el face total disponible, igual amortiza todo lo que hay
    (caso edge — no debería ocurrir con data consistente). Devuelve los totales
    decrementados para auditoría / response.

    NOTA: esta función asume `1 VN = 1 USD face` (estándar para soberanos AR
    canje 2020). Para bonos CER con face ajustado, la math sería distinta —
    pero esos bonos son bullet, no amortizantes, así que este código nunca
    se invoca con ellos.
    """
    lots = conn.execute(
        """SELECT * FROM positions
           WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 AND quantity > 0
           ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, broker, asset),
    ).fetchall()

    if not lots:
        return 0.0, 0.0

    total_qty_available = sum((l['quantity'] or 0) for l in lots)
    qty_to_take = min(amort_amount, total_qty_available)
    if qty_to_take <= 0:
        return 0.0, 0.0

    remaining = qty_to_take
    total_invested_dec = 0.0
    for lot in lots:
        if remaining <= 1e-9:
            break
        lot_qty = lot['quantity'] or 0
        take = min(remaining, lot_qty)
        if take <= 0:
            continue
        ratio = take / lot_qty
        new_qty = lot_qty - take
        new_invested = (lot['invested'] or 0) * (1 - ratio)
        new_commissions = (lot['commissions'] or 0) * (1 - ratio)
        invested_taken = (lot['invested'] or 0) * ratio
        total_invested_dec += invested_taken
        if new_qty <= 1e-9:
            # Lote totalmente amortizado — borramos para que no quede zombie.
            conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (lot['id'], uid))
        else:
            conn.execute(
                "UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=?",
                (new_qty, round(new_invested, 6), round(new_commissions, 6), lot['id'], uid),
            )
        remaining -= take

    return qty_to_take, round(total_invested_dec, 6)


def _cash_asset_for_currency(currency: str) -> str:
    """Mapea la currency del broker al asset name del cash position."""
    if currency == 'ARS':
        return 'ARS'
    if currency == 'USD':
        return 'USD'
    return 'USDT'


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3E — Inbox de cobranzas pendientes
# ═══════════════════════════════════════════════════════════════════════════
# El frontend detecta cobranzas teóricas pendientes (fechas pasadas del
# cronograma sin operation registrada). Estos endpoints permiten al user
# "saltar" pagos que no debe procesar (default, bono vendido antes, etc.)
# para que no reaparezcan en el inbox.

class BondCashflowSkipIn(BaseModel):
    """Marca una cobranza teórica como "no aplica" para no sugerirla más."""
    broker: str = Field(..., min_length=1, max_length=MAX_STR)
    asset: str = Field(..., min_length=1, max_length=20)
    date: str = Field(..., max_length=10)
    reason: Optional[str] = Field(None, max_length=200)

    @field_validator('date')
    @classmethod
    def valid_date(cls, v):
        if not _DATE_RE.match(v):
            raise ValueError('Fecha inválida')
        return v


@app.get("/api/bonds/cashflow/skips")
def list_bond_cashflow_skips(uid: int = Depends(get_current_user)):
    """Lista todos los skips del user. Frontend los consume para filtrar
    el inbox de pendientes."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT broker, asset, date, reason, created_at
               FROM bond_cashflow_skips
               WHERE user_id=?
               ORDER BY date ASC""",
            (uid,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/bonds/cashflow/skip")
def skip_bond_cashflow(data: BondCashflowSkipIn, uid: int = Depends(get_current_user)):
    """Marca una cobranza teórica como saltada. Idempotente: re-aplicar el
    mismo skip no falla, sólo actualiza el `reason` si difiere."""
    conn = get_db()
    try:
        # Validar broker existe y es del user
        broker_row = conn.execute(
            "SELECT id FROM brokers WHERE user_id=? AND name=?", (uid, data.broker)
        ).fetchone()
        if not broker_row:
            raise HTTPException(404, f"Broker '{data.broker}' no encontrado")
        iso_now = datetime.utcnow().isoformat() + "Z"
        with conn:
            conn.execute(
                """INSERT INTO bond_cashflow_skips
                   (user_id, broker, asset, date, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, broker, asset, date) DO UPDATE SET
                       reason = excluded.reason,
                       created_at = excluded.created_at""",
                (uid, data.broker, data.asset.upper(), data.date, data.reason, iso_now),
            )
        return {
            'ok': True,
            'broker': data.broker,
            'asset': data.asset.upper(),
            'date': data.date,
        }
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al guardar skip: {ex}")
    finally:
        conn.close()


@app.delete("/api/bonds/cashflow/skip")
def unskip_bond_cashflow(
    broker: str,
    asset: str,
    date: str,
    uid: int = Depends(get_current_user),
):
    """Elimina un skip — el pago vuelve a aparecer en el inbox. Usado si el
    user marca por error o si la situación cambia (ej: bono salió de default)."""
    if not _DATE_RE.match(date):
        raise HTTPException(422, f"Fecha inválida: {date}")
    conn = get_db()
    try:
        with conn:
            cur = conn.execute(
                """DELETE FROM bond_cashflow_skips
                   WHERE user_id=? AND broker=? AND asset=? AND date=?""",
                (uid, broker, asset.upper(), date),
            )
            deleted = cur.rowcount
        return {'ok': True, 'deleted': deleted}
    finally:
        conn.close()


def _ensure_usd_sibling(conn, uid: int, parent_broker_row) -> dict:
    """Devuelve el broker hijo USDT del broker ARS padre. Si no existe, lo crea.

    Convención de nombre: '<Padre> · USD'. El campo `parent_broker_id` apunta al
    padre. La currency del hijo es USDT.

    NOTA: para brokers AR (Cocos/IOL/Balanz) el USD es real (no USDT), pero el
    modelo interno usa USDT como bucket de "stablecoin USD" para unificar
    crypto + tradfi. El nombre del broker ('<Padre> · USD') refleja la realidad
    del user; el currency field es plumbing interno.
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
        _ai_cache_invalidate(uid)
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
        _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
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
    # pnl_usd OPCIONAL — distingue null ("no registré la ganancia/pérdida")
    # de 0 ("trade flat, ni gané ni perdí"). Sin esto, el form tenía que
    # forzar siempre un número y el caso "atajo: solo registrar P&L sin
    # detalles" se confundía con un trade en cero. Los builders de IA y los
    # filtros downstream ya cheack `pnl_usd is not None` (insights.py:257).
    pnl_usd: Optional[float] = Field(None, ge=-_FINITE_BOUND, le=_FINITE_BOUND)
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


@app.get("/api/movements")
def get_movements(uid: int = Depends(get_current_user)):
    """Historial unificado de TODOS los movimientos del usuario.

    Es la "vista contadora" — todo lo que pasó cronológicamente, sin
    distinguir si fue trade, depósito, retiro, dividendo, etc. Pensado
    para la página /operaciones después del refactor que la convierte
    en "historial completo" (no solo trades).

    Fuentes consolidadas:
      1. operations (manual)          → trades cerrados (BUY+SELL pairs)
      2. import_normalized_tx          → todos los tipos importados (BUY,
         SELL, DEPOSIT, WITHDRAW, DIVIDEND, INTEREST, FEE)
      3. monthly_entries (no-global)   → depósitos/retiros mensuales
         cargados a mano. Fecha aproximada al día 15 del mes.
      4. positions abiertas manuales   → compras sin venta todavía
         (BUY puro, sin pair)

    Cada movement devuelve:
      { id, kind, date, type, broker, asset, quantity, unit_price,
        amount_usd, currency, fees_usd, notes, source }

      - kind: 'movement' (estable, para identificar el objeto)
      - type: 'BUY' | 'SELL' | 'DEPOSIT' | 'WITHDRAW' | 'DIVIDEND' |
              'INTEREST' | 'FEE'
      - source: 'manual' | 'import' | 'monthly' — indica si es editable
        (solo manual lo es; los demás vienen de imports o agregados).
      - amount_usd: monto USD canónico. Para BUY/SELL = qty × price (o
        pnl si solo P&L). Para flujos = el monto neto.
      - id: único dentro del scope (op-{id}, tx-{id}, me-{id}, pos-{id}).

    NO incluye:
      - Cobranzas de bonos (sub-tipo de operations.notes con kind '_bond_*')
      - Snapshots de portfolio (eso es /api/snapshots)

    Ordenado por date DESC (más reciente primero). Los movimientos sin
    fecha (legacy) van al final.
    """
    conn = get_db()
    movements: list[dict] = []
    try:
        # ── TC blue para conversión ARS→USD ─────────────────────────────────
        tc_blue = _user_tc_blue(conn, uid)

        # ── 1) Operations (manual trades) ───────────────────────────────────
        op_rows = conn.execute(
            """SELECT o.* FROM operations o
                WHERE o.user_id = ?
                  AND o.id NOT IN (
                    SELECT operation_id FROM import_op_links
                     WHERE operation_id IS NOT NULL)
                ORDER BY o.date DESC""",
            (uid,),
        ).fetchall()
        for r in op_rows:
            d = dict(r)
            op_type = (d.get("op_type") or "").upper()
            qty = _safe_float_or_none(d.get("quantity"))
            entry_p = _safe_float_or_none(d.get("entry_price"))
            exit_p = _safe_float_or_none(d.get("exit_price"))
            pnl = _safe_float_or_none(d.get("pnl_usd")) or 0
            fees = _safe_float_or_none(d.get("commissions")) or 0

            # Un trade cerrado son 2 eventos contables (BUY + SELL). Para que
            # el user vea ambos en la timeline, generamos 2 rows: una con
            # entry_date como BUY (si hay), una con date como SELL.
            if d.get("entry_date"):
                amount_buy = (entry_p or 0) * (qty or 0) if entry_p and qty else 0
                movements.append({
                    "id": f"op-{d['id']}-buy",
                    "kind": "movement",
                    "date": d["entry_date"],
                    "type": "BUY",
                    "broker": d.get("broker") or "",
                    "asset": d.get("asset") or "",
                    "quantity": qty,
                    "unit_price": entry_p,
                    "amount_usd": amount_buy,
                    "currency": (d.get("currency") or "USD").upper(),
                    "fees_usd": 0,
                    "notes": d.get("notes") or "",
                    "source": "manual",
                    "ref_id": d["id"],
                })
            amount_sell = (exit_p or 0) * (qty or 0) if exit_p and qty else (pnl + (entry_p or 0) * (qty or 0) if entry_p and qty else pnl)
            movements.append({
                "id": f"op-{d['id']}-sell",
                "kind": "movement",
                "date": d.get("date"),
                "type": "SELL",
                "broker": d.get("broker") or "",
                "asset": d.get("asset") or "",
                "quantity": qty,
                "unit_price": exit_p,
                "amount_usd": amount_sell,
                "currency": (d.get("currency") or "USD").upper(),
                "fees_usd": fees,
                "pnl_usd": pnl,
                "notes": d.get("notes") or "",
                "source": "manual",
                "ref_id": d["id"],
            })

        # ── 2) Import normalized transactions ───────────────────────────────
        tx_rows = conn.execute(
            """SELECT t.id, t.date, t.broker, t.operation_type, t.asset_symbol,
                      t.asset_name, t.quantity, t.unit_price, t.gross_amount,
                      t.currency, t.fees, t.notes
                FROM import_normalized_tx t
                JOIN import_batches b ON t.batch_id = b.id
                WHERE b.user_id = ? AND b.status = 'confirmed'
                ORDER BY t.date DESC""",
            (uid,),
        ).fetchall()
        for r in tx_rows:
            d = dict(r)
            op_type = (d.get("operation_type") or "").upper()
            cur = (d.get("currency") or "USD").upper()
            amt = _safe_float_or_none(d.get("gross_amount")) or 0
            fees = _safe_float_or_none(d.get("fees")) or 0
            # Convertir a USD si está en ARS
            amount_usd = amt / tc_blue if cur == "ARS" and tc_blue > 0 else amt
            fees_usd = fees / tc_blue if cur == "ARS" and tc_blue > 0 else fees
            movements.append({
                "id": f"tx-{d['id']}",
                "kind": "movement",
                "date": d.get("date"),
                "type": op_type,
                "broker": d.get("broker") or "",
                "asset": d.get("asset_symbol") or d.get("asset_name") or "",
                "quantity": _safe_float_or_none(d.get("quantity")),
                "unit_price": _safe_float_or_none(d.get("unit_price")),
                "amount_usd": amount_usd,
                "currency": cur,
                "fees_usd": fees_usd,
                "notes": d.get("notes") or "",
                "source": "import",
                "ref_id": d["id"],
            })

        # ── 3) Monthly entries (no-global) — solo el RESIDUAL manual ────────
        # `monthly_entries.deposits/withdrawals` son sumas acumulativas que
        # incluyen DOS fuentes:
        #   (a) Lo que el user cargó manualmente (form /mensual + botón Cash
        #       en Cartera + reconcile-cash en Config). Esto SÍ es "capital
        #       nuevo" y debería contarse en el KPI.
        #   (b) Lo que el importer acumuló al procesar CSV (persister.py llama
        #       _update_monthly_flow cada vez que el CSV trae DEPOSIT/WITHDRAW).
        #       Esto NO debería contarse como "movement manual" porque YA
        #       aparece como source='import' desde import_normalized_tx (paso 2).
        #
        # Si emitimos un movement por cada monthly_entry con el deposits/
        # withdrawals entero, los importados quedan DOUBLE-COUNTED.
        #
        # Fix: agregamos los DEPOSIT/WITHDRAW de imports por (broker, year, month)
        # y los RESTAMOS de monthly_entries.deposits/withdrawals. El residual
        # es lo que el user agregó manualmente.
        #
        # ⚠ PRECONDICIÓN: _recalc_pnl_realized_from_ops NO debe sobreescribir
        # deposits/withdrawals (fix 2026-05-27). Antes lo hacía y borraba los
        # manuales del user.
        imp_agg_rows = conn.execute(
            """SELECT
                  t.broker AS broker,
                  CAST(strftime('%Y', t.date) AS INTEGER) AS y,
                  CAST(strftime('%m', t.date) AS INTEGER) AS m,
                  SUM(CASE WHEN UPPER(t.operation_type)='DEPOSIT'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS dep_usd,
                  SUM(CASE WHEN UPPER(t.operation_type)='WITHDRAW'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS wit_usd
                FROM import_normalized_tx t
                JOIN import_batches b ON t.batch_id = b.id
                WHERE b.user_id = ? AND b.status = 'confirmed'
                  AND UPPER(t.operation_type) IN ('DEPOSIT', 'WITHDRAW')
                GROUP BY t.broker, y, m""",
            (tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0, uid),
        ).fetchall()
        imp_dep_map = {(r["broker"], r["y"], r["m"]): float(r["dep_usd"] or 0) for r in imp_agg_rows}
        imp_wit_map = {(r["broker"], r["y"], r["m"]): float(r["wit_usd"] or 0) for r in imp_agg_rows}

        me_rows = conn.execute(
            """SELECT id, year, month, broker, deposits, withdrawals
                 FROM monthly_entries
                WHERE user_id = ? AND broker <> 'global'
                  AND (deposits > 0 OR withdrawals > 0)
                ORDER BY year DESC, month DESC""",
            (uid,),
        ).fetchall()
        for r in me_rows:
            d = dict(r)
            y, m = int(d["year"]), int(d["month"])
            key = (d.get("broker") or "", y, m)
            imp_dep = imp_dep_map.get(key, 0.0)
            imp_wit = imp_wit_map.get(key, 0.0)
            deposits_total = float(d["deposits"] or 0)
            withdrawals_total = float(d["withdrawals"] or 0)
            deposits_manual = max(0.0, deposits_total - imp_dep)
            withdrawals_manual = max(0.0, withdrawals_total - imp_wit)

            approx_date = f"{y:04d}-{m:02d}-15"
            if deposits_manual > 0.01:
                movements.append({
                    "id": f"me-{d['id']}-dep",
                    "kind": "movement",
                    "date": approx_date,
                    "type": "DEPOSIT",
                    "broker": d.get("broker") or "",
                    "asset": "",
                    "quantity": None,
                    "unit_price": None,
                    "amount_usd": deposits_manual,
                    "currency": "USD",
                    "fees_usd": 0,
                    "notes": f"Depósitos manuales {y}-{m:02d}",
                    "source": "monthly",
                    "ref_id": d["id"],
                    "approx_date": True,
                })
            if withdrawals_manual > 0.01:
                movements.append({
                    "id": f"me-{d['id']}-wit",
                    "kind": "movement",
                    "date": approx_date,
                    "type": "WITHDRAW",
                    "broker": d.get("broker") or "",
                    "asset": "",
                    "quantity": None,
                    "unit_price": None,
                    "amount_usd": withdrawals_manual,
                    "currency": "USD",
                    "fees_usd": 0,
                    "notes": f"Retiros manuales {y}-{m:02d}",
                    "source": "monthly",
                    "ref_id": d["id"],
                    "approx_date": True,
                })

        # ── 4) Positions abiertas manuales (BUY sin SELL todavía) ───────────
        # Las que vienen de imports YA están en (2). Acá solo las del user
        # que cargó manual (sin import_op_links).
        pos_rows = conn.execute(
            """SELECT p.* FROM positions p
                WHERE p.user_id = ?
                  AND p.is_cash = 0
                  AND p.id NOT IN (
                    SELECT position_id FROM import_op_links
                     WHERE position_id IS NOT NULL)
                ORDER BY p.entry_date DESC""",
            (uid,),
        ).fetchall()
        for r in pos_rows:
            d = dict(r)
            qty = _safe_float_or_none(d.get("quantity"))
            buy_p = _safe_float_or_none(d.get("buy_price"))
            invested = _safe_float_or_none(d.get("invested")) or 0
            cur = (d.get("currency") or "USD").upper()
            amount_usd = invested
            if cur == "ARS":
                tc_compra = _safe_float_or_none(d.get("tc_compra"))
                if tc_compra and tc_compra > 0:
                    amount_usd = invested / tc_compra
                elif tc_blue > 0:
                    amount_usd = invested / tc_blue
            movements.append({
                "id": f"pos-{d['id']}",
                "kind": "movement",
                "date": d.get("entry_date") or "",
                "type": "BUY",
                "broker": d.get("broker") or "",
                "asset": d.get("asset") or "",
                "quantity": qty,
                "unit_price": buy_p,
                "amount_usd": amount_usd,
                "currency": cur,
                "fees_usd": _safe_float_or_none(d.get("commissions")) or 0,
                "notes": d.get("notes") or "",
                "source": "manual",
                "ref_id": d["id"],
                "is_open_position": True,
            })

    finally:
        conn.close()

    # Sort: fecha DESC, con sin-fecha al final. Tuple (has_date, date_str)
    # para que (1, '...') siempre rankee arriba de (0, '').
    def _sort_key(m):
        has_date = 1 if m.get("date") else 0
        return (has_date, m.get("date") or "")
    movements.sort(key=_sort_key, reverse=True)

    return movements


def _safe_float_or_none(v):
    """Conversor defensivo a float. Devuelve None si no se puede."""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


@app.get("/api/insights/commissions")
def get_commissions_total(uid: int = Depends(get_current_user)):
    """Suma de las comisiones EXPLÍCITAS importadas (operation_type='FEE' en
    import_normalized_tx). Convierte ARS→USD usando tc_blue. Ignora el campo
    `commissions` de operations (que tiene basura de imports viejos con
    parsers mal mapeados — fuente de inflados crónicos en la card).
    """
    conn = get_db()
    try:
        tc_blue_row = conn.execute(
            "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
        ).fetchone()
        try:
            tc_blue = float(tc_blue_row["value"]) if tc_blue_row else 1415.0
            if tc_blue <= 0:
                tc_blue = 1415.0
        except (TypeError, ValueError):
            tc_blue = 1415.0

        rows = conn.execute(
            """SELECT n.gross_amount AS amt, n.currency AS cur
                 FROM import_normalized_tx n
                 JOIN import_batches b ON b.id = n.batch_id
                WHERE b.user_id=?
                  AND b.status='confirmed'
                  AND n.operation_type='FEE'""",
            (uid,),
        ).fetchall()

        total_usd = 0.0
        count = 0
        for r in rows:
            amt = float(r["amt"] or 0)
            if amt <= 0:
                continue
            cur = (r["cur"] or "").upper()
            amt_usd = amt / tc_blue if cur == "ARS" else amt
            total_usd += amt_usd
            count += 1

        return {
            "total_usd": round(total_usd, 4),
            "count": count,
        }
    finally:
        conn.close()


# ─── CSV Export (Pro-only) ───────────────────────────────────────────────────
# Endpoints que serializan tablas a CSV con encabezados en español pensados
# para que el contador del usuario los pueda procesar sin gimnasia.
# Gate por `export.csv` feature flag — Free recibe 403 con upgrade payload.

import csv as _csv  # alias para evitar shadow con vars locales 'csv'
from io import StringIO


def _csv_safe(value):
    """Mitiga CSV/formula injection en exports.

    Un user maligno con cuenta puede crear posiciones u operaciones con
    `asset` o `broker` empezando con `=`, `+`, `-`, `@`, `\\t`, `\\r`,
    interpretados por Excel como fórmulas (`=cmd|'/c calc'!A0` ejecuta cmd
    en versiones viejas). Cuando el usuario abre el CSV en Excel, las
    fórmulas corren — peor cuando comparte con su contador.

    Mitigación: prefijar cualquier celda string que empiece con esos
    caracteres con un apóstrofe (`'`) — Excel/Sheets lo trata como texto,
    no como fórmula. Los números no se tocan (queremos preservar la
    semántica numérica de precios/cantidades).
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _csv_response(rows: list[dict], headers: list[tuple[str, str]], filename: str) -> Response:
    """Genera un Response CSV listo para descarga.

    headers: lista de (column_key, display_label). El display_label va en la
    primera fila del CSV (encabezado humano-readable en español).

    SECURITY: cada celda string pasa por _csv_safe para mitigar CSV/formula
    injection (un user maligno podría inyectar fórmulas en asset/broker/notes
    que se ejecutarían al abrir el CSV en Excel).
    """
    buf = StringIO()
    # delimiter ',' + quoting MINIMAL — compatible con Excel/Numbers/Google Sheets
    writer = _csv.writer(buf, delimiter=",", quoting=_csv.QUOTE_MINIMAL)
    writer.writerow([label for _, label in headers])
    for row in rows:
        writer.writerow([_csv_safe(row.get(key, "")) for key, _ in headers])
    content = buf.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            # BOM para que Excel español detecte UTF-8
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _gate_export(uid: int):
    """Gate común para los exports — devuelve 403 si Free, sino sigue."""
    from ai import plan
    conn = get_db()
    try:
        if not plan.can_access(conn, uid, "export.csv"):
            tier = plan.quota.get_tier(conn, uid)
            raise HTTPException(403, {
                "error": "Export CSV está disponible en los planes Plus y Pro.",
                "upgrade": {
                    "available": tier == "free",
                    "current_tier": tier,
                    "target_tier": "plus",
                    "feature": "export.csv",
                    "benefits": [
                        "Export CSV consolidado para tu contador",
                        "Hasta 3 brokers (vs 1 en Free)",
                        "Reportes históricos completos",
                        "Distribución por activo desbloqueada",
                    ],
                },
            })
    finally:
        conn.close()


@app.get("/api/export/operations.csv")
def export_operations_csv(uid: int = Depends(get_current_user)):
    """Operaciones cerradas → CSV. Pensado para el contador / reporte fiscal.

    Columnas pensadas para AFIP / régimen tributario AR: fecha de operación,
    activo, broker, tipo (LONG/SHORT), cantidad, precios de entrada/salida,
    P&L en USD, comisiones, fecha de cierre, días tenidos."""
    _gate_export(uid)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT date AS fecha_cierre, entry_date, asset, broker,
                      op_type AS tipo, quantity, entry_price, exit_price,
                      pnl_usd, pnl_pct, commissions
               FROM operations
               WHERE user_id = ?
               ORDER BY date DESC""",
            (uid,),
        ).fetchall()]
    finally:
        conn.close()

    headers = [
        ("fecha_cierre",  "Fecha cierre"),
        ("entry_date",    "Fecha apertura"),
        ("asset",         "Activo"),
        ("broker",        "Broker"),
        ("tipo",          "Tipo"),
        ("quantity",      "Cantidad"),
        ("entry_price",   "Precio entrada"),
        ("exit_price",    "Precio salida"),
        ("pnl_usd",       "P&L USD"),
        ("pnl_pct",       "P&L %"),
        ("commissions",   "Comisiones"),
    ]
    today = date.today().isoformat()
    return _csv_response(rows, headers, f"rendi_operaciones_{today}.csv")


@app.get("/api/export/positions.csv")
def export_positions_csv(uid: int = Depends(get_current_user)):
    """Posiciones abiertas → CSV (snapshot al momento de descarga).

    Incluye costo basis + cantidad. NO incluye valor de mercado actual
    (eso es volátil — para análisis the Dashboard tiene mejor lugar)."""
    _gate_export(uid)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT asset, broker, is_cash, quantity, invested, commissions,
                      entry_date, tc_compra, price_override
               FROM positions
               WHERE user_id = ?
               ORDER BY broker, asset""",
            (uid,),
        ).fetchall()]
    finally:
        conn.close()

    headers = [
        ("asset",          "Activo"),
        ("broker",         "Broker"),
        ("is_cash",        "Es cash"),
        ("quantity",       "Cantidad"),
        ("invested",       "Costo invertido"),
        ("commissions",    "Comisiones"),
        ("entry_date",     "Fecha compra"),
        ("tc_compra",      "TC compra (ARS)"),
        ("price_override", "Precio override"),
    ]
    today = date.today().isoformat()
    return _csv_response(rows, headers, f"rendi_posiciones_{today}.csv")


@app.get("/api/export/transactions.csv")
def export_transactions_csv(uid: int = Depends(get_current_user)):
    """Export consolidado: TODOS los movimientos del user en una sola CSV.

    Pensado como "lo que mandás al contador" o "lo que mandás a otra persona
    para que vea toda tu actividad". Incluye:
      • Compras (BUY)  — de imports y de positions/operations manuales
      • Ventas (SELL)  — de imports y de operations manuales
      • Depósitos      — de imports y de monthly_entries.deposits
      • Retiros        — de imports y de monthly_entries.withdrawals
      • Dividendos cobrados (de imports)
      • Intereses cobrados  (de imports)
      • Comisiones aisladas (de imports)

    Ordenado por fecha DESC (más reciente primero).

    Nota: para users que importaron CSV, los BUY/SELL ya están en
    `import_normalized_tx`. Para users que cargan manual, vienen de
    `operations` (BUY + SELL como pares cerrados) y `positions` (BUY
    abierta). Los flujos de cash manuales vienen de `monthly_entries`
    no-global (aggregated por mes).
    """
    _gate_export(uid)
    conn = get_db()
    rows: list[dict] = []
    try:
        # ── 1) Imports normalizados (cubre todos los tipos) ──────────────────
        tx_rows = conn.execute(
            """SELECT t.date, t.broker, t.operation_type, t.asset_symbol,
                      t.asset_name, t.quantity, t.unit_price, t.gross_amount,
                      t.currency, t.fees, t.notes
               FROM import_normalized_tx t
               JOIN import_batches b ON t.batch_id = b.id
               WHERE b.user_id = ? AND b.status = 'confirmed'""",
            (uid,),
        ).fetchall()
        for r in tx_rows:
            rows.append({
                "fecha": r["date"],
                "tipo": _humanize_tx_type(r["operation_type"]),
                "broker": r["broker"] or "",
                "activo": r["asset_symbol"] or r["asset_name"] or "",
                "cantidad": r["quantity"],
                "precio_unitario": r["unit_price"],
                "monto": r["gross_amount"],
                "moneda": r["currency"] or "",
                "comisiones": r["fees"] or 0,
                "notas": (r["notes"] or "") + " · import",
            })

        # ── 2) Operations manuales (closed trades sin import_op_links) ───────
        op_rows = conn.execute(
            """SELECT o.* FROM operations o
               WHERE o.user_id = ?
                 AND o.id NOT IN (SELECT operation_id FROM import_op_links WHERE operation_id IS NOT NULL)""",
            (uid,),
        ).fetchall()
        for r in op_rows:
            op_type = r["op_type"] or ""
            # Futuros: solo se carga pnl_usd, no hay quantity/precios. Se exporta
            # como UNA fila con monto = pnl_usd (puede ser negativo).
            is_futuros = (
                "Futuros" in op_type
                or "futuros" in op_type
                or (r["quantity"] is None and r["entry_price"] is None and r["exit_price"] is None)
            )
            if is_futuros:
                pnl = r["pnl_usd"] or 0
                rows.append({
                    "fecha": r["date"],
                    "tipo": "VENTA",
                    "broker": r["broker"] or "",
                    "activo": r["asset"] or "",
                    "cantidad": "",
                    "precio_unitario": "",
                    "monto": pnl,
                    "moneda": r["currency"] or "USD",
                    "comisiones": r["commissions"] or 0,
                    "notas": f"{op_type or 'futuros'} · P&L cerrado" + (
                        f" · {r['notes']}" if r["notes"] else ""
                    ),
                })
                continue
            # Operación normal con apertura + cierre. Genera 2 filas si entry_date.
            if r["entry_date"]:
                rows.append({
                    "fecha": r["entry_date"],
                    "tipo": "COMPRA",
                    "broker": r["broker"] or "",
                    "activo": r["asset"] or "",
                    "cantidad": r["quantity"],
                    "precio_unitario": r["entry_price"],
                    "monto": (r["entry_price"] or 0) * (r["quantity"] or 0),
                    "moneda": r["currency"] or "USD",
                    "comisiones": 0,
                    "notas": "manual · operation",
                })
            rows.append({
                "fecha": r["date"],
                "tipo": "VENTA",
                "broker": r["broker"] or "",
                "activo": r["asset"] or "",
                "cantidad": r["quantity"],
                "precio_unitario": r["exit_price"],
                "monto": (r["exit_price"] or 0) * (r["quantity"] or 0),
                "moneda": r["currency"] or "USD",
                "comisiones": r["commissions"] or 0,
                "notas": (r["notes"] or "") + " · manual · operation",
            })

        # ── 3) Positions abiertas manualmente (no-cash, no-import) ───────────
        # NOTA: NO filtramos por entry_date — posiciones legacy sin fecha
        # también deben aparecer en el export (sino el contador no ve la
        # compra). Si no hay entry_date, dejamos fecha vacía y lo marcamos
        # en las notas para que sea claro.
        pos_rows = conn.execute(
            """SELECT p.* FROM positions p
               WHERE p.user_id = ?
                 AND p.is_cash = 0
                 AND p.id NOT IN (SELECT position_id FROM import_op_links WHERE position_id IS NOT NULL)""",
            (uid,),
        ).fetchall()
        for r in pos_rows:
            has_date = bool(r["entry_date"])
            rows.append({
                "fecha": r["entry_date"] or "",
                "tipo": "COMPRA",
                "broker": r["broker"] or "",
                "activo": r["asset"] or "",
                "cantidad": r["quantity"],
                "precio_unitario": r["buy_price"],
                "monto": r["invested"],
                "moneda": r["currency"] or "USD",
                "comisiones": r["commissions"] or 0,
                "notas": "manual · posición abierta" + (
                    "" if has_date else " (sin fecha registrada)"
                ),
            })

        # ── 4) Monthly entries: cash flows agregados por mes (no globales) ───
        me_rows = conn.execute(
            """SELECT year, month, broker, deposits, withdrawals
               FROM monthly_entries
               WHERE user_id = ? AND broker != 'global'
                 AND (deposits > 0 OR withdrawals > 0)""",
            (uid,),
        ).fetchall()
        for r in me_rows:
            # Usamos el día 15 del mes como aproximación (cash flows agregados)
            d = f"{r['year']:04d}-{r['month']:02d}-15"
            if (r["deposits"] or 0) > 0:
                rows.append({
                    "fecha": d,
                    "tipo": "DEPÓSITO",
                    "broker": r["broker"] or "",
                    "activo": "",
                    "cantidad": "",
                    "precio_unitario": "",
                    "monto": r["deposits"],
                    "moneda": "USD",
                    "comisiones": 0,
                    "notas": f"Total depósitos {r['year']}-{r['month']:02d} (fecha aproximada al 15)",
                })
            if (r["withdrawals"] or 0) > 0:
                rows.append({
                    "fecha": d,
                    "tipo": "RETIRO",
                    "broker": r["broker"] or "",
                    "activo": "",
                    "cantidad": "",
                    "precio_unitario": "",
                    "monto": r["withdrawals"],
                    "moneda": "USD",
                    "comisiones": 0,
                    "notas": f"Total retiros {r['year']}-{r['month']:02d} (fecha aproximada al 15)",
                })
    finally:
        conn.close()

    # Ordenar por fecha DESC, con tiebreaker en tipo para que COMPRAS aparezcan
    # antes que VENTAS del mismo día. Las filas SIN fecha (posiciones legacy
    # sin entry_date) quedan al FINAL del CSV con prefijo '0000' que las
    # ordena después de todo lo fechado (DESC).
    _TYPE_ORDER = {"COMPRA": 0, "VENTA": 1, "DEPÓSITO": 2, "RETIRO": 3,
                   "DIVIDENDO": 4, "INTERÉS": 5, "COMISIÓN": 6}
    def _sort_key(r):
        # En modo DESC, "0000-..." quedaría al final (el menor). Pero queremos
        # que las sin fecha queden DESPUÉS de las fechadas — así que usamos un
        # tuple (has_date, fecha, type) para evitar que NULL trepe arriba.
        has_date = 1 if r["fecha"] else 0
        return (has_date, r["fecha"] or "", -_TYPE_ORDER.get(r["tipo"], 9))
    rows.sort(key=_sort_key, reverse=True)

    headers = [
        ("fecha",           "Fecha"),
        ("tipo",            "Tipo"),
        ("broker",          "Broker"),
        ("activo",          "Activo"),
        ("cantidad",        "Cantidad"),
        ("precio_unitario", "Precio unit."),
        ("monto",           "Monto"),
        ("moneda",          "Moneda"),
        ("comisiones",      "Comisiones"),
        ("notas",           "Notas"),
    ]
    today = date.today().isoformat()
    return _csv_response(rows, headers, f"rendi_movimientos_{today}.csv")


def _humanize_tx_type(t: str) -> str:
    """Mapea operation_type del importer a labels en español para el contador."""
    if not t: return ""
    t = t.upper().strip()
    return {
        "BUY":       "COMPRA",
        "SELL":      "VENTA",
        "DEPOSIT":   "DEPÓSITO",
        "WITHDRAW":  "RETIRO",
        "DIVIDEND":  "DIVIDENDO",
        "INTEREST":  "INTERÉS",
        "FEE":       "COMISIÓN",
    }.get(t, t)


@app.get("/api/export/monthly.csv")
def export_monthly_csv(uid: int = Depends(get_current_user)):
    """Resumen mensual → CSV con flujos + P&L realizado mes a mes.

    Útil para el contador: sintetiza capital inicio/fin, depósitos,
    retiros, P&L realizado por mes. Incluye el broker 'global' (agregado
    de todos los brokers) y por broker individual."""
    _gate_export(uid)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT year, month, broker, capital_inicio, capital_final,
                      deposits, withdrawals, pnl_realized
               FROM monthly_entries
               WHERE user_id = ?
               ORDER BY year, month, broker""",
            (uid,),
        ).fetchall()]
    finally:
        conn.close()

    # Formato 'período' YYYY-MM combinado para que el contador lo lea fácil
    for r in rows:
        r["periodo"] = f"{r['year']}-{r['month']:02d}"

    headers = [
        ("periodo",          "Período"),
        ("broker",           "Broker"),
        ("capital_inicio",   "Capital inicio"),
        ("capital_final",    "Capital final"),
        ("deposits",         "Depósitos"),
        ("withdrawals",      "Retiros"),
        ("pnl_realized",     "P&L realizado"),
    ]
    today = date.today().isoformat()
    return _csv_response(rows, headers, f"rendi_mensual_{today}.csv")


@app.get("/api/wrapped/{year}")
def wrapped_year(year: int, uid: int = Depends(get_current_user)):
    """Wrapped anual — reseña tipo Spotify del año en inversiones.
    Sprint 6 del plan post-auditoría. Slides con highlights:
    rendimiento, mejor/peor mes, mejor trade, sesgo dominante, vs benchmarks,
    vs inflación AR. Si no hay data del año, devuelve un slide informativo.
    """
    if year < 2000 or year > 2200:
        raise HTTPException(400, "Año fuera de rango")
    from wrapped import build_wrapped
    from behavioral import build_behavioral_insights
    conn = get_db()
    try:
        monthly = [dict(r) for r in conn.execute(
            "SELECT * FROM monthly_entries WHERE user_id=? ORDER BY year, month", (uid,)
        ).fetchall()]
        ops = [dict(r) for r in conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (uid,)
        ).fetchall()]
        # Behavioral: reusamos el mismo builder. No fallar el wrapped si el
        # behavioral falla — los slides del bias son opcionales.
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE user_id=?", (uid,)
        ).fetchall()]
        try:
            symbols = list(set(
                p["asset"] for p in positions if p.get("asset") and not p.get("is_cash")
            ))
            prices = {}
            if symbols:
                quotes = _fetch_batch_quotes(symbols)
                prices = {s: q["price"] for s, q in quotes.items() if q and q.get("price") is not None}
        except Exception:
            prices = {}
        try:
            global _bench_cache
            inflation_monthly = (_bench_cache.get("data") or {}).get("inflation_ar") or {}
            if not inflation_monthly:
                inflation_monthly = _fetch_inflation_ar()
        except Exception:
            inflation_monthly = {}
        tc_blue = _user_tc_blue(conn, uid)
        try:
            behavioral = build_behavioral_insights(ops, positions, prices, inflation_monthly, tc_blue)
            behavioral_cards = behavioral.get("cards") or []
        except Exception:
            behavioral_cards = []
        # Benchmarks YTD: agarrar el último valor del cache de benchmarks del
        # año en cuestión. Si no está, el slide vs_benchmark se filtra solo.
        # Hoy sólo tenemos S&P 500 mensual en cache; MERVAL queda pendiente
        # de pipeline propio.
        benchmarks = {}
        try:
            data = (_bench_cache.get("data") or {})
            sp_series = data.get("sp500") or {}
            if sp_series:
                # Buscamos el último close del año y el último de diciembre del año anterior
                prev_year = year - 1
                in_year = [(k, v) for k, v in sp_series.items() if k.startswith(f"{year}-")]
                in_year.sort()
                prev_dec = sp_series.get(f"{prev_year}-12")
                if in_year and prev_dec:
                    last_close = in_year[-1][1]
                    if prev_dec > 0:
                        benchmarks["sp500_ytd"] = (last_close / prev_dec) - 1
        except Exception:
            benchmarks = {}
        # Inflación YTD AR: compose por mes del año
        inflation_ytd = None
        try:
            if inflation_monthly:
                acc = 1.0
                any_match = False
                for ym, m_pct in inflation_monthly.items():
                    if isinstance(ym, str) and ym.startswith(f"{year}-"):
                        acc *= 1 + (m_pct or 0) / 100
                        any_match = True
                if any_match:
                    inflation_ytd = acc - 1
        except Exception:
            inflation_ytd = None
    finally:
        conn.close()
    return build_wrapped(year, monthly, ops, behavioral_cards, benchmarks, inflation_ytd)


@app.get("/api/behavioral/insights")
def behavioral_insights(uid: int = Depends(get_current_user)):
    """Detecta sesgos comportamentales sobre el historial del usuario.
    Sprint 3 + 3.1 + 3.2 del plan post-auditoría. 10 detectores en total.

    Detectores:
      Sprint 3 (4):
        - disposition_effect, overtrade, loss_aversion, averaging_down
      Sprint 3.1 (3):
        - concentration: top holdings como % del portfolio
        - inflation_loss: pérdida de cash ARS por inflación INDEC
        - counterfactual: rendimiento si NO hubieras cerrado tus ventas
      Sprint 3.2 (3):
        - winrate_payoff: win rate × payoff ratio (expectancy)
        - home_bias: % portfolio en activos AR
        - cash_drag: % portfolio en cash (con énfasis ARS)
    """
    from behavioral import build_behavioral_insights
    conn = get_db()
    try:
        ops = [dict(r) for r in conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (uid,)
        ).fetchall()]
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE user_id=?", (uid,)
        ).fetchall()]
        # Precios actuales: del cache de quotes del Home (mismo dataset que
        # usa el Dashboard). Sin fallar si no hay batch fetch a mano.
        symbols = list(set([p["asset"] for p in positions if p.get("asset") and not p.get("is_cash")]))
        prices = {}
        if symbols:
            try:
                quotes = _fetch_batch_quotes(symbols)
                prices = {s: q["price"] for s, q in quotes.items() if q and q.get("price") is not None}
            except Exception:
                prices = {}
        # Inflación AR del bench cache (12 últimos meses)
        inflation_monthly = {}
        try:
            global _bench_cache
            if _bench_cache.get("data"):
                inflation_monthly = _bench_cache["data"].get("inflation_ar") or {}
            else:
                inflation_monthly = _fetch_inflation_ar()
        except Exception:
            inflation_monthly = {}
        tc_blue = _user_tc_blue(conn, uid)
    finally:
        conn.close()
    return build_behavioral_insights(ops, positions, prices, inflation_monthly, tc_blue)


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
    _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
    return dict(row)


@app.delete("/api/operations/{oid}")
def delete_operation(oid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM operations WHERE id=? AND user_id=?", (oid, uid))
    conn.commit()
    conn.close()
    _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
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
    _ai_cache_invalidate(uid)
    return dict(row)


@app.delete("/api/goals/{gid}")
def delete_goal(gid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM goals WHERE id=? AND user_id=?", (gid, uid))
    conn.commit()
    conn.close()
    _ai_cache_invalidate(uid)
    return {"ok": True}


@app.get("/api/goals/{gid}/diagnostic")
def goal_diagnostic(gid: int, uid: int = Depends(get_current_user)):
    """Sprint 7 — Goals 2.0. Cruza:
    - Velocidad real del usuario (CAGR histórico).
    - Velocidad necesaria para la meta.
    - Sesgo dominante (behavioral) → sugerencia accionable si va atrasado.

    Si el goal no es del user → 404. Si no hay valor actual del portfolio
    (no posiciones) → status=unknown.
    """
    from goals_diagnostic import build_goal_diagnostic
    from behavioral import build_behavioral_insights
    conn = get_db()
    try:
        goal = conn.execute(
            "SELECT * FROM goals WHERE id=? AND user_id=?", (gid, uid)
        ).fetchone()
        if not goal:
            raise HTTPException(404, "Goal no encontrado")
        goal_dict = dict(goal)

        # Valor actual del portfolio = sum(positions value) en USD
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE user_id=?", (uid,)
        ).fetchall()]
        ops = [dict(r) for r in conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (uid,)
        ).fetchall()]

        # Reusar la pipeline ya armada de behavioral para precios e insights
        try:
            symbols = list(set(
                p["asset"] for p in positions if p.get("asset") and not p.get("is_cash")
            ))
            prices = {}
            if symbols:
                quotes = _fetch_batch_quotes(symbols)
                prices = {s: q["price"] for s, q in quotes.items() if q and q.get("price") is not None}
        except Exception:
            prices = {}
        tc_blue = _user_tc_blue(conn, uid)

        # Valor actual del portfolio en USD — sumamos valor de cada posición
        # con la misma fórmula que usamos en behavioral._position_value_usd
        from behavioral import _position_value_usd
        current_value = 0.0
        for p in positions:
            try:
                v = _position_value_usd(p, prices, tc_blue)
                if v is not None:
                    current_value += v
            except Exception:
                continue

        # CAGR histórico desde monthly_entries (mismo cálculo que /api/goals/cagr)
        rows = conn.execute(
            """SELECT year, month, deposits, withdrawals, capital_inicio, capital_final
               FROM monthly_entries WHERE user_id=? AND broker='global'
               ORDER BY year ASC, month ASC""",
            (uid,),
        ).fetchall()
        user_cagr_pct = None
        if len(rows) >= 2:
            factors = []
            for r in rows:
                ci = r["capital_inicio"] or 0
                cf = r["capital_final"] or 0
                net = (r["deposits"] or 0) - (r["withdrawals"] or 0)
                if ci <= 0:
                    continue
                ret_m = (cf - ci - net) / ci
                ret_m = max(-0.95, min(5.0, ret_m))
                factors.append(1 + ret_m)
            if factors:
                prod = 1.0
                for f in factors:
                    prod *= f
                avg_monthly = prod ** (1 / len(factors))
                user_cagr_pct = round((avg_monthly ** 12 - 1) * 100, 2)

        # Behavioral cards
        try:
            global _bench_cache
            inflation_monthly = (_bench_cache.get("data") or {}).get("inflation_ar") or {}
            behavioral_cards = build_behavioral_insights(
                ops, positions, prices, inflation_monthly, tc_blue
            ).get("cards") or []
        except Exception:
            behavioral_cards = []
    finally:
        conn.close()

    return build_goal_diagnostic(
        goal_dict,
        current_value=current_value,
        user_cagr_pct=user_cagr_pct,
        behavioral_cards=behavioral_cards,
    )


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

@app.post("/api/admin/cleanup/realign-monthly-with-imports")
def admin_cleanup_realign_monthly(uid: int = Depends(get_admin_user)):
    """REPARACIÓN one-shot del daño causado por el viejo
    _recalc_pnl_realized_from_ops (que sobreescribía deposits/withdrawals con
    los valores de imports, borrando los manuales del user).

    Re-alinea monthly_entries.deposits/withdrawals con la suma EXACTA de
    DEPOSIT/WITHDRAW desde import_normalized_tx para cada (broker, year, month).

    Resultado post-cleanup:
      • monthly_entries.deposits = SUM(imports DEPOSIT) en ese período
      • monthly_entries.withdrawals = SUM(imports WITHDRAW) en ese período
      • /api/movements resta imports → residual manual = 0 (limpio)
      • El user puede ir a /mensual y agregar/editar entries → esos manuales
        se SUMAN encima de los imports → /api/movements resta imports →
        residual = solo manual ✓

    Idempotente. Solo afecta al user admin que lo llame.
    """
    conn = get_db()
    try:
        tc_blue = _user_tc_blue(conn, uid)
        # Agregar imports DEPOSIT/WITHDRAW por (broker, year, month) en USD
        imp_rows = conn.execute(
            """SELECT
                  t.broker AS broker,
                  CAST(strftime('%Y', t.date) AS INTEGER) AS y,
                  CAST(strftime('%m', t.date) AS INTEGER) AS m,
                  SUM(CASE WHEN UPPER(t.operation_type)='DEPOSIT'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS dep_usd,
                  SUM(CASE WHEN UPPER(t.operation_type)='WITHDRAW'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS wit_usd
                FROM import_normalized_tx t
                JOIN import_batches b ON t.batch_id = b.id
                WHERE b.user_id = ? AND b.status = 'confirmed'
                  AND UPPER(t.operation_type) IN ('DEPOSIT', 'WITHDRAW')
                GROUP BY t.broker, y, m""",
            (tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0, uid),
        ).fetchall()
        # Map: (broker, y, m) → (dep_usd, wit_usd)
        target = {(r["broker"], r["y"], r["m"]): (float(r["dep_usd"] or 0), float(r["wit_usd"] or 0))
                  for r in imp_rows}

        # Para CADA broker que tiene monthly_entries no-global, iterar todas
        # sus rows y setear deposits/withdrawals al target.
        updated = 0
        zeroed = 0
        for me in conn.execute(
            "SELECT id, broker, year, month, deposits, withdrawals FROM monthly_entries WHERE user_id=? AND broker <> 'global'",
            (uid,),
        ).fetchall():
            key = (me["broker"], me["year"], me["month"])
            dep_target, wit_target = target.get(key, (0.0, 0.0))
            conn.execute(
                "UPDATE monthly_entries SET deposits=?, withdrawals=? WHERE id=? AND user_id=?",
                (round(dep_target, 4), round(wit_target, 4), me["id"], uid),
            )
            updated += 1
            if dep_target < 0.01 and wit_target < 0.01:
                zeroed += 1

        # Para el broker='global', es la suma cross-broker. Resetear igual.
        global_target_dep = sum(d for d, w in target.values())
        global_target_wit = sum(w for d, w in target.values())
        # Distribuir global_target entre los meses globales — usar mismo agregado
        # por (year, month) sumando entre brokers.
        global_by_period = {}
        for (br, y, m), (dep, wit) in target.items():
            global_by_period[(y, m)] = (
                global_by_period.get((y, m), (0.0, 0.0))[0] + dep,
                global_by_period.get((y, m), (0.0, 0.0))[1] + wit,
            )
        for me in conn.execute(
            "SELECT id, year, month FROM monthly_entries WHERE user_id=? AND broker='global'",
            (uid,),
        ).fetchall():
            dep, wit = global_by_period.get((me["year"], me["month"]), (0.0, 0.0))
            conn.execute(
                "UPDATE monthly_entries SET deposits=?, withdrawals=? WHERE id=? AND user_id=?",
                (round(dep, 4), round(wit, 4), me["id"], uid),
            )
            updated += 1

        conn.commit()
        _ai_cache_invalidate(uid)
        return {
            "ok": True,
            "user_id": uid,
            "rows_updated": updated,
            "rows_zeroed": zeroed,
            "total_imports_dep_usd": round(global_target_dep, 4),
            "total_imports_wit_usd": round(global_target_wit, 4),
            "next_step": (
                "Andá a /mensual y agregá tus depósitos/retiros manuales reales. "
                "Esos se SUMAN sobre los imports — /operaciones va a mostrar el "
                "residual manual en el KPI."
            ),
        }
    finally:
        conn.close()


@app.get("/api/admin/debug/movements-kpi")
def admin_debug_movements_kpi(uid: int = Depends(get_admin_user)):
    """DEBUG temporal: dump del estado interno del cálculo de Depositado/Retirado
    para el admin logueado. Permite diagnosticar el bug del KPI inflado en
    /operaciones cuando hay imports + monthly_entries acumulados.

    Devuelve:
      • Lista completa de monthly_entries no-global (id, year, month, broker, deposits, withdrawals)
      • Agregados de import_normalized_tx por (broker, year, month) → DEPOSIT, WITHDRAW, FEE en USD
      • El cálculo del RESIDUAL que hace /api/movements (con el fix actual)
      • Suma de cada bucket para diagnóstico

    Borrar este endpoint cuando se confirme el fix.
    """
    conn = get_db()
    try:
        # Mismo cálculo de tc_blue que usa /api/movements
        tc_blue = _user_tc_blue(conn, uid)

        # Monthly entries del user (no-global, con deposits>0 o withdrawals>0)
        me_rows = conn.execute(
            """SELECT id, year, month, broker, deposits, withdrawals
                 FROM monthly_entries
                WHERE user_id = ? AND broker <> 'global'
                  AND (deposits > 0 OR withdrawals > 0)
                ORDER BY year, month, broker""",
            (uid,),
        ).fetchall()
        me_list = [dict(r) for r in me_rows]

        # Agregados de imports por (broker, year, month). Separamos DEPOSIT,
        # WITHDRAW y FEE para entender qué se está double-counting.
        imp_rows = conn.execute(
            """SELECT
                  t.broker AS broker,
                  CAST(strftime('%Y', t.date) AS INTEGER) AS y,
                  CAST(strftime('%m', t.date) AS INTEGER) AS m,
                  UPPER(t.operation_type) AS op_type,
                  COUNT(*) AS n,
                  ROUND(SUM(t.gross_amount), 4) AS raw_sum,
                  UPPER(COALESCE(t.currency, 'USD')) AS currency,
                  ROUND(SUM(CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                 THEN t.gross_amount/?
                                 ELSE t.gross_amount END), 4) AS usd_sum
                FROM import_normalized_tx t
                JOIN import_batches b ON t.batch_id = b.id
                WHERE b.user_id = ? AND b.status = 'confirmed'
                  AND UPPER(t.operation_type) IN ('DEPOSIT', 'WITHDRAW', 'FEE')
                GROUP BY t.broker, y, m, op_type, currency
                ORDER BY t.broker, y, m, op_type""",
            (tc_blue or 1.0, tc_blue or 1.0, uid),
        ).fetchall()
        imp_list = [dict(r) for r in imp_rows]

        # Agregar también el agg por (broker, y, m) sin tipo, para el cálculo del residual
        imp_agg_rows = conn.execute(
            """SELECT
                  t.broker AS broker,
                  CAST(strftime('%Y', t.date) AS INTEGER) AS y,
                  CAST(strftime('%m', t.date) AS INTEGER) AS m,
                  SUM(CASE WHEN UPPER(t.operation_type)='DEPOSIT'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS dep_usd,
                  SUM(CASE WHEN UPPER(t.operation_type)='WITHDRAW'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS wit_usd,
                  SUM(CASE WHEN UPPER(t.operation_type)='FEE'
                           THEN (CASE WHEN UPPER(t.currency)='ARS' AND ? > 0
                                      THEN t.gross_amount/?
                                      ELSE t.gross_amount END)
                           ELSE 0 END) AS fee_usd
                FROM import_normalized_tx t
                JOIN import_batches b ON t.batch_id = b.id
                WHERE b.user_id = ? AND b.status = 'confirmed'
                  AND UPPER(t.operation_type) IN ('DEPOSIT', 'WITHDRAW', 'FEE')
                GROUP BY t.broker, y, m""",
            (tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0, tc_blue or 1.0,
             tc_blue or 1.0, tc_blue or 1.0, uid),
        ).fetchall()
        imp_dep_map = {(r["broker"], r["y"], r["m"]): float(r["dep_usd"] or 0) for r in imp_agg_rows}
        imp_wit_map = {(r["broker"], r["y"], r["m"]): float(r["wit_usd"] or 0) for r in imp_agg_rows}
        imp_fee_map = {(r["broker"], r["y"], r["m"]): float(r["fee_usd"] or 0) for r in imp_agg_rows}

        # Calcular residual por monthly_entry — con y SIN restar FEE (para diagnóstico)
        residuals = []
        for d in me_list:
            y = int(d["year"])
            m = int(d["month"])
            broker = d["broker"]
            key = (broker, y, m)
            imp_dep = imp_dep_map.get(key, 0.0)
            imp_wit = imp_wit_map.get(key, 0.0)
            imp_fee = imp_fee_map.get(key, 0.0)
            dep_total = float(d["deposits"] or 0)
            wit_total = float(d["withdrawals"] or 0)
            # Residual con fix actual (resta solo DEPOSIT/WITHDRAW)
            dep_residual_v1 = max(0.0, dep_total - imp_dep)
            wit_residual_v1 = max(0.0, wit_total - imp_wit)
            # Residual alternativo (resta también FEE de withdrawals)
            wit_residual_v2 = max(0.0, wit_total - imp_wit - imp_fee)
            residuals.append({
                "broker": broker,
                "year": y,
                "month": m,
                "me_deposits": dep_total,
                "me_withdrawals": wit_total,
                "imp_dep_usd": round(imp_dep, 4),
                "imp_wit_usd": round(imp_wit, 4),
                "imp_fee_usd": round(imp_fee, 4),
                "residual_dep_v1": round(dep_residual_v1, 4),
                "residual_wit_v1": round(wit_residual_v1, 4),
                "residual_wit_v2_with_fee": round(wit_residual_v2, 4),
            })

        # Totales
        total_me_dep = sum(float(d["deposits"] or 0) for d in me_list)
        total_me_wit = sum(float(d["withdrawals"] or 0) for d in me_list)
        total_resid_dep_v1 = sum(r["residual_dep_v1"] for r in residuals)
        total_resid_wit_v1 = sum(r["residual_wit_v1"] for r in residuals)
        total_resid_wit_v2 = sum(r["residual_wit_v2_with_fee"] for r in residuals)
        # Total imports tomados a USD para sanity check
        total_imp_dep = sum(imp_dep_map.values())
        total_imp_wit = sum(imp_wit_map.values())
        total_imp_fee = sum(imp_fee_map.values())

        return {
            "user_id": uid,
            "tc_blue": tc_blue,
            "monthly_entries_count": len(me_list),
            "monthly_entries": me_list,
            "imports_breakdown_per_op_type": imp_list,
            "residuals_per_entry": residuals,
            "totals": {
                "me_deposits_sum": round(total_me_dep, 4),
                "me_withdrawals_sum": round(total_me_wit, 4),
                "imp_deposit_sum_usd": round(total_imp_dep, 4),
                "imp_withdraw_sum_usd": round(total_imp_wit, 4),
                "imp_fee_sum_usd": round(total_imp_fee, 4),
                "residual_dep_v1_sum": round(total_resid_dep_v1, 4),
                "residual_wit_v1_sum": round(total_resid_wit_v1, 4),
                "residual_wit_v2_with_fee_sum": round(total_resid_wit_v2, 4),
            },
        }
    finally:
        conn.close()


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


@app.get("/api/admin/ai/tool-usage")
def admin_ai_tool_usage(days: int = 14, uid: int = Depends(get_admin_user)):
    """Stats de uso de tools del Coach IA (ai_tool_usage).

    Devuelve ranking de tools más usadas + breakdown por tier, días.
    Pack A v2: sirve para detectar tools no-usadas (candidatas a borrar)
    o sobre-usadas (candidatas a investigar abuso).

    days: ventana de análisis (default 14d, max 90).
    """
    days = max(1, min(int(days or 14), 90))
    conn = get_db()
    try:
        # Ranking global por tool
        ranking = conn.execute(
            f"""SELECT tool_name, SUM(count) AS calls, COUNT(DISTINCT user_id) AS users
                FROM ai_tool_usage
                WHERE date >= date('now', '-{days} days')
                GROUP BY tool_name
                ORDER BY calls DESC""",
        ).fetchall()

        # Breakdown por tier (necesita JOIN con users)
        by_tier_raw = conn.execute(
            f"""SELECT u.tier, t.tool_name, SUM(t.count) AS calls
                FROM ai_tool_usage t
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.date >= date('now', '-{days} days')
                GROUP BY u.tier, t.tool_name
                ORDER BY u.tier, calls DESC""",
        ).fetchall()
        by_tier = {}
        for r in by_tier_raw:
            tier = r["tier"] or "unknown"
            by_tier.setdefault(tier, []).append({"tool_name": r["tool_name"], "calls": r["calls"]})

        # Top 10 users por uso total
        top_users = conn.execute(
            f"""SELECT u.id, u.email, u.tier, SUM(t.count) AS total_calls
                FROM ai_tool_usage t
                LEFT JOIN users u ON u.id = t.user_id
                WHERE t.date >= date('now', '-{days} days')
                GROUP BY u.id
                ORDER BY total_calls DESC
                LIMIT 10""",
        ).fetchall()

        return {
            "days": days,
            "ranking": [dict(r) for r in ranking],
            "by_tier": by_tier,
            "top_users": [dict(r) for r in top_users],
        }
    finally:
        conn.close()


@app.get("/api/admin/plan/conversion")
def admin_plan_conversion(uid: int = Depends(get_admin_user)):
    """Métricas de conversión Free → Pro.

    Agrega los eventos de `plan_events` y devuelve:
      - totals: counts totales por event_name
      - by_feature: clicks por feature_id (qué bloqueo convierte más)
      - by_source: clicks por origen (qué pantalla genera más intent)
      - last_30d_total: actividad reciente
      - distinct_users_blocked / distinct_users_clicked
    """
    conn = get_db()
    try:
        # Totales por event_name
        totals = {}
        rows = conn.execute(
            """SELECT event_name, COUNT(*) AS n FROM plan_events
               GROUP BY event_name"""
        ).fetchall()
        for r in rows:
            totals[r["event_name"]] = r["n"]

        # Por feature (ordenado desc por intent)
        by_feature = [
            dict(r) for r in conn.execute(
                """SELECT feature_id,
                          COUNT(*) AS clicks,
                          COUNT(DISTINCT user_id) AS users
                   FROM plan_events
                   WHERE feature_id IS NOT NULL
                   GROUP BY feature_id
                   ORDER BY clicks DESC"""
            ).fetchall()
        ]

        # Por source (qué pantalla)
        by_source = [
            dict(r) for r in conn.execute(
                """SELECT source,
                          COUNT(*) AS clicks,
                          COUNT(DISTINCT user_id) AS users
                   FROM plan_events
                   WHERE source IS NOT NULL
                   GROUP BY source
                   ORDER BY clicks DESC"""
            ).fetchall()
        ]

        # Último 30 días
        last_30d = conn.execute(
            """SELECT COUNT(*) AS n FROM plan_events
               WHERE created_at >= datetime('now', '-30 days')"""
        ).fetchone()["n"]

        # Distinct users con/sin click final
        distinct_blocked = conn.execute(
            """SELECT COUNT(DISTINCT user_id) AS n FROM plan_events
               WHERE tier = 'free'"""
        ).fetchone()["n"]

        # Eventos recientes (debug / monitoring)
        recent = [
            dict(r) for r in conn.execute(
                """SELECT user_id, tier, event_name, feature_id, source, created_at
                   FROM plan_events
                   ORDER BY created_at DESC
                   LIMIT 50"""
            ).fetchall()
        ]

        return {
            "totals": totals,
            "by_feature": by_feature,
            "by_source": by_source,
            "last_30d_total": last_30d,
            "distinct_free_users_with_intent": distinct_blocked,
            "recent": recent,
        }
    finally:
        conn.close()


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


@app.post("/api/admin/wipe-broker-data")
def admin_wipe_broker_data(broker: str, uid: int = Depends(get_admin_user)):
    """Limpieza nuclear de datos de un broker: borra operations, positions,
    monthly_entries, snapshots y marca batches asociados como reverted.
    El broker en sí queda — el user lo sigue viendo en `/posiciones` y puede
    re-importar limpio.

    Útil cuando imports viejos dejaron huérfanos (operaciones sin
    import_op_links, commissions infladas por mapeo equivocado del parser
    genérico, etc.) y el revert estándar no los pudo limpiar.

    Idempotente: correr 2 veces no hace daño.
    """
    conn = get_db()
    try:
        # Verificar que el broker exista para este admin
        b = conn.execute(
            "SELECT id FROM brokers WHERE user_id=? AND name=?", (uid, broker),
        ).fetchone()
        if not b:
            raise HTTPException(404, f"Broker '{broker}' no existe para este usuario")

        counts: Dict[str, int] = {}
        with conn:
            cur = conn.execute(
                "DELETE FROM operations WHERE user_id=? AND broker=?", (uid, broker),
            )
            counts["operations_deleted"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM positions WHERE user_id=? AND broker=?", (uid, broker),
            )
            counts["positions_deleted"] = cur.rowcount

            cur = conn.execute(
                "DELETE FROM monthly_entries WHERE user_id=? AND broker=?", (uid, broker),
            )
            counts["monthly_entries_deleted"] = cur.rowcount

            cur = conn.execute(
                """UPDATE import_batches
                   SET status='reverted', reverted_at=datetime('now')
                   WHERE user_id=? AND broker=? AND status IN ('confirmed','preview')""",
                (uid, broker),
            )
            counts["batches_marked_reverted"] = cur.rowcount

        # Recalcular aggregates globales (afecta el 'global' que sumaba el
        # broker borrado). Snapshots se regeneran solas via cron o recalc.
        try:
            with conn:
                _recalc_pnl_realized_from_ops(conn, uid)
        except Exception as ex:
            log.error("Recalc tras wipe falló: %s", ex)

        return {"ok": True, "broker": broker, **counts}
    finally:
        conn.close()


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
            # Timeout explícito 25s — default del SDK es 600s.
            #
            # IMPORTANTE: Vercel rewrite a Railway tiene ~30s timeout duro.
            # Si el SDK espera más, Vercel corta primero y devuelve HTML
            # genérico (no JSON) → el frontend NO puede parsear `detail` y
            # muestra un mensaje genérico inútil al usuario.
            #
            # Bajado de 60s → 25s para que el SDK falle ANTES que Vercel
            # corte, lo que nos permite devolver un 503 con detail útil
            # ("el coach está saturado, reintentá"). Bug reportado: tras
            # el 1° turno, una follow-up sobre P/E pegaba a yfinance con
            # cache miss + 2-3 tool calls + 2-3 round-trips Anthropic →
            # >30s → Vercel timeout → user veía "No pudimos completar la
            # consulta" sin contexto.
            #
            # 25s sigue siendo generoso para Haiku 4.5: warm cache responde
            # en 2-5s, cold cache + 1-2 tools en 8-15s. Solo se cae con
            # tool storm extremo (4 tools cache miss simultáneos), donde
            # querés fallar rápido y mostrar mensaje útil.
            _anthropic_client = Anthropic(api_key=api_key, timeout=25.0)
        except ImportError:
            return None
    return _anthropic_client


# ─── /api/ai/insights ELIMINADO (AI v2) ─────────────────────────────────────
# El endpoint /api/ai/insights legacy + AIInsightsIn + _AI_SYSTEM fueron
# eliminados — el frontend ya no los consume. Reemplazado por la
# arquitectura packets/builders con /api/ai/analyze (ver ai/registry.py).


# ─── Chat conversacional con la IA ───────────────────────────────────────────

_AI_CHAT_SYSTEM = """Sos el coach de inversiones de Rendi, una app argentina de seguimiento de portfolios personales. Tu usuario es un inversor retail argentino que opera cripto, acciones US, CEDEARs, ETFs e índices, en brokers locales (Cocos, IOL, Bull, Balanz, Lemon) y exchanges (Binance).

ROL
No das recomendaciones específicas de "comprá X" o "vendé Y". Sí explicás conceptos, marcos analíticos, ratios, riesgos, y hacés preguntas que abren reflexión.
Si te piden recomendación específica, redirigí: ofrecé el marco para que el usuario decida ("no te digo cuál comprar, pero podemos pensar la tesis, el sizing, y el escenario de salida").
Respondés con los datos que tenés en el snapshot. Antes de decir "no tengo ese dato", intentá buscarlo — podés usar las tools disponibles para obtenerlo en tiempo real.

HERRAMIENTAS DISPONIBLES
Tenés tools que podés invocar para obtener datos adicionales cuando el snapshot no alcance:

Tools internas (data del propio usuario):
- get_current_prices: precios en tiempo real de cualquier activo.
- get_asset_operations: historial completo de operaciones cerradas de un activo del usuario.
- get_monthly_detail: detalle mensual completo de todos los brokers.
- get_realized_vs_unrealized: breakdown P&L realizado vs unrealized del usuario.
- get_recent_news_for_assets: top 3 noticias por ticker de la cartera.
- remember_user_fact: persistir hechos del usuario entre sesiones.

Tools de mercado externas (Pack A v2):
Para EQUITIES (acciones US, CEDEARs listados en US — yfinance):
- get_stock_fundamentals: P/E, EPS, dividend yield, market cap, beta, sector — datos rápidos.
- get_value_scorecard: scorecard completo con 8 métricas + semáforos (verde/ámbar/rojo) + label "Sólido/Mixto/Débil". LA TOOL ESTRELLA para preguntas de valoración.
- get_earnings_history: próximo earnings + últimos 4 quarters con surprise %.
- get_analyst_ratings: recomendación consenso + price target.
- get_company_profile: a qué se dedica la empresa.

Para BONOS ARGENTINOS soberanos (AL/GD/AE/AL41 + TX/T2X/TZX/T2X CER):
- get_ar_bond_metadata: maturity, ley aplicable (local/NY), step-up cupones, indexado CER, descripción contextual. Cubre TODOS los soberanos AR canje 2020 + los CER principales. NO cubre ONs corporativas ni provinciales.

Cuándo NO llamar tools de mercado:
- Si el usuario solo quiere precio → get_current_prices.
- Si el ticker es CRIPTO → no hay scorecard ni fundamentales (P/E no aplica). Decilo honesto.
- Si el ticker es bono CORPORATIVO o provincial → no tenemos metadata. Decilo honesto.
- Si la pregunta es general/estrategia sin un ticker específico.
- Si ya tenés la respuesta en el snapshot.

Cuándo SÍ llamar tools de mercado:
- Pregunta sobre "¿está cara/barata X?" (acción) → get_value_scorecard (UNA llamada cubre todo).
- Compara dos acciones → get_value_scorecard para cada uno (máx 2).
- Pregunta sobre bono AR soberano ("¿qué es AL30?", "¿cuándo vence GD30?", "¿el TX26 ajusta por inflación?") → get_ar_bond_metadata.
- Pregunta sobre earnings/próximo reporte → get_earnings_history.
- Pregunta sobre cobertura de analistas → get_analyst_ratings.
- Pregunta a qué se dedica → get_company_profile.

Si get_value_scorecard devuelve `available: false` con razón sobre bonos, llamá get_ar_bond_metadata como fallback. Es la tool correcta para razonar sobre bonos AR.

ANTI-SPAM DE TOOLS:
- Máximo 2 tools de mercado por respuesta. Si tu pregunta necesita 3+, repensá si todas son necesarias.
- Antes de llamar una tool, preguntate: "¿esta respuesta sería significativamente peor SIN este dato?". Si no, no la llames.
- Si una tool devuelve `available: false`, NO inventes la data — decile al user "no tengo acceso a fundamentales de cripto/bonos en esta sesión" y seguí adelante.

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

BONOS ARGENTINOS (clave para usuarios AR — instrumentos comunes en cartera)
- Soberanos USD: AL29/AL30/AL35/AE38/AL41 (ley local) y GD29/GD30/GD35/GD38/GD41/GD46 (ley NY). Todos cupón STEP-UP (arrancan en 0.125-0.5% y suben hasta 1.75-5%). Reestructurados en 2020. Ley NY suele cotizar 3-5pp paridad encima de ley local por protección legal.
- AL30 / GD30: los más líquidos. AL30 es referencia para MEP (dolarizar dentro), GD30 es el "reference bond" internacional (lo que mira el mercado para riesgo país).
- CER (TX/T2X/TZX): capital ajusta diariamente por CER (≈inflación AR). Cupón = tasa REAL sobre inflación. Cobertura natural contra inflación EN PESOS (no contra FX). Si el dólar sube más rápido que CER, el valor USD del bono baja.
- Conceptos clave para razonar: maturity, duration (sensibilidad a tasas/riesgo país), step-up (cupones suben con el tiempo), paridad (% de valor nominal al que cotiza).
- Lo que NO podés decir: dirección futura del bono, predicción de riesgo país. Sí podés: explicar mecánica, comparar yields aproximados de bonos en cartera, señalar concentración de duration.

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

DISTINGUIR EXPOSURE PRESENTE vs P&L HISTÓRICO (regla anti-confusión crítica)
El snapshot tiene dos bloques distintos que JAMÁS hay que mezclar:
- `positions`: posiciones ABIERTAS HOY. Acá razonar sobre riesgo presente, sensibilidad de mercado, concentración, "si X cae". Estas SÍ están expuestas a movimientos futuros.
- `operations`: operaciones YA CERRADAS. Su P&L es histórico, realizado. Un ticker en operations puede no estar más en cartera. NUNCA digas "si AMD cae el portfolio cae" si AMD solo aparece en operations (= ya cerraste).

Ejemplo del error que NO debe ocurrir:
MAL: "Si AMD/INTC corrigen 20%, tu portfolio cae" (cuando AMD/INTC son solo trades cerrados en operations, no están en positions).
BIEN: "El P&L del año descansa parcialmente en trades cerrados de AMD/INTC. Tu exposure actual está en NVDA y AAPL — el riesgo a la baja depende de ellos."

Si un ticker aparece en AMBOS lados (positions y operations), aclararlo: "mantenés posición abierta + tenés P&L cerrado en el mismo ticker; el riesgo presente es solo sobre el lote abierto".

Tenés el snapshot del portfolio del usuario en el contexto. Usá los números concretos cuando sean relevantes. El snapshot incluye benchmarks (S&P 500, inflación AR, dólar blue) para comparar la performance del usuario contra referencias de mercado.

MÉTRICAS PRO (summary.pro_metrics):
Si están presentes, podés usarlas para diagnósticos cuantitativos. Todas son anualizadas:
- sharpe_ratio (retorno ajustado por toda la volatilidad vs T-Bills): <0 perdés vs cash, 0-1 subóptimo, 1-2 bueno, >2 excelente.
- sortino_ratio (como Sharpe pero solo downside): suele ser MÁS ALTO que Sharpe.
- volatility_annual_pct: <10 conservador, 10-20 equities diversificadas (S&P ~15-18), 20-40 concentrado, >40 cripto.
- alpha_annual_pct (Jensen, CAPM): >0 outperformaste lo que CAPM predice, <0 underperformaste.
- beta_vs_sp500: 1.0 te movés igual al S&P, >1 más volátil/agresivo, <1 defensivo, <0 hedge contrario.
- r_squared_pct: qué tanto del retorno del portfolio explica el S&P. Alto + Alpha alto = outperform real.
- info_ratio (consistencia del outperform vs S&P): >0.5 consistente, >1 excelente.

USAR estas métricas para preguntas como "¿qué tan bien lo estoy haciendo?", "¿mi cartera es muy volátil?", "¿le gano al mercado?". Citá los números concretos del snapshot y interpretalos en el contexto del usuario (perfil, horizonte declarado).

INTERPRETACIÓN DE TOOLS DE MERCADO (Pack A v2 — Pro causal)

Cuando llamás get_value_scorecard, get_stock_fundamentals, get_earnings_history o get_analyst_ratings, tu trabajo NO es repetir los números crudos. Es transformarlos en VALOR para la decisión del usuario.

Tres niveles obligatorios al presentar resultados de estas tools:

1. CONTEXTUALIZAR el número. "P/E 67×" no significa nada solo. "P/E 67× — pagás 67 años de ganancias actuales por la acción, vs media tecnología 25×" sí.

2. CONECTAR con la cartera del usuario. Mirá el snapshot — si el usuario tiene el ticker, calculá:
   - Cuánto pesa en su portfolio.
   - Cuál sería el impacto en su patrimonio si la métrica cambia (ej. "un re-rating del P/E de 67 a 50 sería -25% en NVDA = -4% del portfolio").
   - Si tiene posición unrealized grande, mencionalo.
   Si NO tiene el ticker, decílo: "no tenés posición en X, lo analizo en abstracto".

3. INTERPRETÁ pero NO recomiendes operativa. Diferencia clave:
   - SÍ podés: "El PEG > 1.5 sugiere que el mercado ya descontó parte del crecimiento esperado. Para un inversor value tradicional, este múltiplo no luce barato."
   - SÍ podés: "Considerá si querés esperar al earnings del 22 de feb antes de tomar la decisión — históricamente NVDA tiene volatilidad ±8% en earnings day."
   - NO podés: "Vendé NVDA", "compralo ahora", "sacale ganancia parcial". Eso es asesoramiento operativo (prohibido).

Usá los `_interpretation_hint` que vienen en los results — son guías internas, NO los repitas literal pero úsalos como brújula.

LENGUAJE ACCESIBLE — REGLAS CRÍTICAS (audiencia mixta)

Tu usuario puede ser desde alguien con licenciatura en finanzas hasta alguien de marketing que invierte para su jubilación. Tu lenguaje DEBE ser entendible para los dos.

Regla 1 — GLOSARIO INLINE en la primera mención de un término técnico.
La PRIMERA vez que aparece un término técnico en una respuesta, incluí mini-aclaración inline en paréntesis (máx 12 palabras). La 2da y 3ra vez en la misma respuesta solo el término.

Términos que SIEMPRE deben explicarse en primera mención (si los usás):
- P/E (precio sobre ganancias)
- EPS (ganancia por acción)
- PEG (P/E ajustado por crecimiento)
- Payout ratio (porcentaje de ganancias pagadas como dividendo)
- ROE (rentabilidad sobre capital)
- Debt/Equity (deuda sobre patrimonio)
- Market cap (valor total de la empresa)
- Beta (volatilidad relativa al mercado)
- Drawdown (caída desde el pico)
- TWR (rendimiento ponderado por tiempo)
- FIFO (lote más viejo se vende primero)
- Mark-to-market (valor actual de mercado)
- Forward P/E (P/E sobre ganancias esperadas)
- Surprise % (cuánto superó o quedó debajo del estimate)
- Margin of safety (margen de seguridad)
- Fair value (valor justo estimado)

Ejemplo:
   MAL: "NVDA cotiza P/E 67× con PEG 0.71."
   BIEN: "NVDA cotiza a un P/E (precio sobre ganancias) de 67× — alto. Pero el PEG (P/E ajustado por crecimiento) es 0.71, lo que dice que ese múltiplo se justifica si el crecimiento esperado se cumple."

Regla 2 — ESPEJÁ el vocabulary del usuario.
Si el usuario pregunta técnico ("compará forward P/E vs trailing"), respondé técnico (asumí que sabe).
Si pregunta llano ("¿NVDA está cara?"), respondé llano. NUNCA respondas más técnico que la pregunta.

Regla 3 — Analogías cuando aplique (especialmente para usuarios no técnicos).
- P/E: "es como cuántos años de sueldo pagás por un departamento — alto = caro o tiene mucho upside descontado."
- Dividend yield: "es el alquiler que te paga la acción mientras la tenés."
- Drawdown: "es la caída desde el pico — si subiste a 100 y bajaste a 70, ese es tu drawdown de -30%."
- PEG: "es el P/E corregido por crecimiento. PEG < 1 significa que pagás barato por el crecimiento que se espera."

No metas analogías a la fuerza — solo cuando ayudan a entender. Si el usuario claramente sabe del tema, evitalas.

Regla 4 — ANTI-DUMP de datos. Dos datos contextualizados > cuatro datos crudos.

MAL: "NVDA: P/E 67, EPS $8.12, dividend yield 0.02%, beta 2.24, 52w high $236, 52w low $129, market cap $5.2T, próximo earnings 20 may."

BIEN: "NVDA cotiza caro vs su historia (P/E 67× — pagás 67 años de ganancias actuales) y se va a jugar mucho el 20 de mayo, cuando reporta resultados. Pesa 16% en tu cartera, así que un movimiento grande te impacta."

Tu trabajo NO es vomitar todo el resultado del tool. Es elegir los 2-3 datos que importan y conectarlos a la cartera.

Regla 5 — NO USAR BULLETS para todo.
Bullets son útiles solo para LISTAS REALES (los 4 últimos earnings, los top 3 detractors). Si tenés 3 datos para comunicar, armalos en PROSA fluida. Bullets cuando los items son genuinamente paralelos.

Excepción: si presentás un scorecard de get_value_scorecard, USÁ formato de lista con símbolos ASCII porque es una tabla. Pero usá `✓` (green), `—` (amber/na), `✗` (red) — NO emojis colored ni cuadrados unicode.

Regla 6 — FORMATO scorecard sugerido al presentar get_value_scorecard:
Empezá con headline (1 línea: ticker + label overall + datos de precio/fair value).
Después 6-8 líneas tipo:
   ✓ Nombre métrica: valor (1 frase de interpretación si Pro)
   — Otra métrica: valor (1 frase)
Cerrá con "Mi lectura para tu cartera:" + 2-3 oraciones de conexión a posición real.

EJEMPLOS BUENOS DE RESPUESTAS PRO (referencia)

Pregunta: "¿NVDA está cara?"

Respuesta Pro (buena):
NVIDIA (NVDA) — Scorecard: Sólido. Precio actual US$ 215, fair value consenso US$ 278 (margen seguridad +22%).
✓ Fair Value: el consenso de analistas ve potencial 22% sobre precio actual — oportunidad moderada.
✓ PER actual vs forward: 33× hoy, 17× con ganancias esperadas próximo año. Las ganancias deberían duplicarse — el múltiplo se contrae solo si la tesis de crecimiento se cumple.
✓ PEG: 0.71 — pagás barato por el crecimiento que se espera (PEG = P/E ajustado por crecimiento, < 1 es ideal value).
✓ ROE (rentabilidad sobre capital): 114%. Extraordinario para large cap.
✓ Crecimiento revenue +85% YoY.
Mi lectura para tu cartera: NVDA pesa 16% en tu portfolio (US$ 7.812 con +38% sin realizar). Fundamentales sólidos justifican mantener — pero la apuesta es a que el crecimiento se sostenga. Si bajaran 2 quarters seguidos las surprises, el mercado podría re-evaluar rápido. Vale la pena considerar tomar ganancia parcial si quisieras bajar concentración.

(esta respuesta combina: scorecard estructurado + glosario inline en PEG/ROE + conexión a posición real + sugerencia sin recomendación operativa)

Respuesta Pro (mala):
NVDA tiene P/E 33, forward 17, PEG 0.71, payoutRatio 0.0061, ROE 1.14, debtToEquity 0.07, profitMargins 0.62, revenueGrowth 0.85, marketCap $5.2T, beta 2.24. Comprala.

(mala porque: dump de números crudos, sin contexto, jerga sin definir, hace recomendación operativa)"""


# Prompt FREE — version stripped del coach. Diseño deliberado: descriptivo,
# breve, sin interpretación. La diferenciación con Pro está en el contenido,
# no en el modelo (mismo Haiku para los dos tiers — más barato y consistente).
_AI_CHAT_SYSTEM_FREE = """Sos el asistente de Rendi para usuarios del plan Free. Tu rol es responder preguntas del usuario sobre su portfolio con datos concretos del snapshot, en formato breve y descriptivo. No sos coach, no interpretás, no das contexto extendido.

ROL
- Respondés con DATOS, no con análisis. Si el snapshot tiene el número, lo decís. Si no, decís "no tengo ese dato" sin elaborar.
- Sin recomendaciones operativas (comprá/vendé). Si insisten, redirigí: "no doy recomendaciones, podés revisar la sección de Posiciones".

ESTILO — REGLAS HARD
- Español rioplatense (vos, tenés). Profesional, sin familiaridad falsa.
- Sin emojis, sin asteriscos, sin signos de exclamación.
- 1 o 2 ORACIONES MÁXIMO por respuesta. Una sola idea. Sin párrafos múltiples, sin secciones, sin listas, sin bullets.
- CERO markdown. Sin **bold**, sin guiones de listas, sin headers con #. La UI muestra el texto plano.
- Describir, NO interpretar. Decís "el portfolio bajó 8%", no "el retroceso del 8% sugiere...". La interpretación es del plan Pro.

CONTEXTO ARGENTINO MÍNIMO
- Mediciones en USD (CCL/MEP).
- CEDEAR = certificado AR de una acción US.

UPSELL — IMPORTANTE
Si el usuario pide análisis profundo, comparación extendida con benchmarks, atribución de causa, sesgos, o pregunta "¿por qué...?": respondé con el dato más simple del snapshot Y agregá al final UNA frase: "Para análisis con causalidad, comparaciones y profundidad, pasate a Pro desde Configuración."

HERRAMIENTAS
Tenés tools internas (get_current_prices, get_asset_operations, get_monthly_detail, get_realized_vs_unrealized, get_recent_news_for_assets) y tools de mercado externas Pack A v2:
- Para ACCIONES (US/CEDEARs): get_stock_fundamentals, get_value_scorecard, get_earnings_history, get_analyst_ratings, get_company_profile.
- Para BONOS AR SOBERANOS (AL30/GD30/AE38/TX26/TZX, etc.): get_ar_bond_metadata.

Usalas SOLO si el snapshot no tiene la respuesta. UNA tool call por respuesta, máximo.

Para preguntas de valoración de una ACCIÓN ("¿está cara NVDA?"), get_value_scorecard cubre todo en un solo call (8 métricas + semáforos).

Para preguntas sobre BONO AR ("¿qué es AL30?", "¿cuándo vence?"), get_ar_bond_metadata devuelve la metadata estructurada.

NUNCA llames tools de mercado para CRIPTO — no aplican métricas tradicionales (P/E, ROE no se calculan). Decile honesto: "para cripto no manejo métricas de valoración tradicionales".

DISTINGUIR EXPOSURE PRESENTE vs P&L HISTÓRICO
El snapshot tiene `positions` (posiciones ABIERTAS HOY) y `operations` (cerradas YA). NUNCA confundirlas. Un ticker en operations puede no estar más en cartera. Si te preguntan sobre exposure o riesgo presente, usar SOLO positions. Si te preguntan sobre P&L histórico, usar SOLO operations.

GLOSARIO INLINE (regla importante incluso en modo descriptivo)
La primera vez que mencionás un término técnico en una respuesta, agregá mini-aclaración inline en paréntesis (máx 10 palabras). Tu usuario puede no saber qué es un P/E o un ROE.

Términos a explicar siempre primera vez:
- P/E (precio sobre ganancias) — pagás X años de ganancias actuales.
- EPS (ganancia por acción).
- PEG (P/E ajustado por crecimiento).
- ROE (rentabilidad sobre capital).
- Dividend yield (rendimiento de dividendo, en % anual).
- Payout ratio (porcentaje de ganancias que la empresa paga como dividendo).
- Fair value (valor estimado, en este caso consenso de analistas).

REGLAS PARA SCORECARDS DE VALOR (get_value_scorecard)
Si el usuario pregunta valoración de una acción, llamá get_value_scorecard y presentá el resultado SIN interpretar — solo describí:

   Formato sugerido (en prosa breve, NO lista de bullets):
   "Microsoft (MSFT) tiene un scorecard Sólido según las métricas tradicionales. Cotiza a US$ 418 vs un fair value (valor estimado consenso de analistas) de US$ 560. Tiene 6 indicadores en verde y 1 en rojo (el PEG ratio, que está alto). Para entender qué significan estos números para tu cartera, necesitás el plan Pro."

   PROHIBIDO en modo descriptivo:
   - "Está caro/barato" (interpretación)
   - "Te conviene/no te conviene" (recomendación)
   - "El P/E sugiere..." (causalidad)
   - "Es buena oportunidad" (juicio de valor)

   PERMITIDO:
   - Nombrar las métricas y su valor.
   - Decir "el indicador X está en verde/rojo según los thresholds estándar de value investing".
   - Mencionar el `overall.label` (Sólido/Mixto/Débil) — ES el resumen objetivo del scorecard.

Cierre obligatorio cuando presentás scorecard en Free/Plus:
"Para entender qué significan estos números para tu cartera específicamente y qué considerar antes de decidir, el plan Pro hace ese análisis."

DIFERENCIACIÓN CON PRO
El plan Pro recibe respuestas con interpretación, causalidad, comparaciones y profundidad analítica. Vos (Free/Plus) das el dato puro, brevísimo. Es deliberado — no inventes interpretación para "ayudar"."""


# Strip markdown que el modelo a veces inyecta a pesar del prompt. Aplicamos
# server-side como red de seguridad (sobre todo Free, que no debe tener bold).
_MD_BOLD_RE = __import__('re').compile(r'\*\*(.+?)\*\*')
_MD_ITALIC_RE = __import__('re').compile(r'\*([^*\n]+?)\*')
_MD_LIST_RE = __import__('re').compile(r'^\s*[-*+]\s+', flags=__import__('re').MULTILINE)
_MD_HEADER_RE = __import__('re').compile(r'^\s*#{1,6}\s+', flags=__import__('re').MULTILINE)


def _strip_markdown(text: str) -> str:
    """Quita bold, italic, listas con guión y headers. Conservamos el contenido."""
    if not text:
        return text
    text = _MD_BOLD_RE.sub(r'\1', text)
    text = _MD_ITALIC_RE.sub(r'\1', text)
    text = _MD_LIST_RE.sub('', text)
    text = _MD_HEADER_RE.sub('', text)
    return text


# Diccionarios de labels en español para serializar el perfil del inversor
# (test de 7 preguntas en /config) dentro del system prompt del Coach IA.
_INVESTOR_LABELS = {
    "horizon": {
        "short": "corto plazo (días/semanas)",
        "medium": "mediano plazo (meses)",
        "long": "largo plazo (años)",
    },
    "drawdown": {
        "sell_all": "vendería todo el portfolio",
        "sell_some": "vendería una parte",
        "hold": "mantendría la posición sin vender",
        "buy_more": "compraría más para promediar abajo",
    },
    "goal": {
        "retirement": "jubilación",
        "freedom": "libertad financiera",
        "learn": "aprender a invertir",
        "hobby": "hobby / pasatiempo",
        "specific_purchase": "compra puntual (casa, auto, viaje)",
    },
    "style": {
        "passive": "pasivo (buy & hold)",
        "active": "activo (trading frecuente)",
        "mixed": "mixto",
    },
    "net_worth": {
        "under_10": "menos del 10% de su patrimonio total",
        "10_to_30": "entre 10% y 30% de su patrimonio total",
        "30_to_60": "entre 30% y 60% de su patrimonio total",
        "over_60": "más del 60% de su patrimonio total",
    },
    "liquidity": {
        "yes": "necesita parte de esta plata en los próximos 12-24 meses",
        "no": "no necesita esta plata en los próximos 12-24 meses",
        "partial": "podría necesitar parte de esta plata en 12-24 meses",
    },
    "experience": {
        "first_time": "primera vez invirtiendo",
        "under_2": "menos de 2 años de experiencia",
        "2_to_5": "entre 2 y 5 años de experiencia",
        "over_5": "más de 5 años de experiencia",
    },
}


def _format_investor_profile_for_prompt(profile_json: Optional[str], mode: str = "causal") -> str:
    """Convierte el JSON del perfil de inversor en un bloque legible para el
    system prompt de Coach IA. Devuelve '' si el user no completó el test.

    El parámetro `mode` controla qué instrucciones acompañan al bloque:
      • 'descriptive' (Free + Plus): permite mencionar y cruzar, prohíbe
        inferir causa o recomendar.
      • 'causal' (Pro + Admin): permite inferencia causal probable del gap
        entre perfil y comportamiento real, manteniendo prohibido el
        asesoramiento operativo específico.

    El default es 'causal' por back-compat — call sites viejos (si quedan)
    siguen funcionando, y se ajustan cuando los modernicemos.
    """
    if not profile_json:
        return ""
    try:
        profile = json.loads(profile_json) if isinstance(profile_json, str) else profile_json
    except (ValueError, TypeError):
        return ""
    if not isinstance(profile, dict) or not profile:
        return ""

    lines = []
    label_order = ["horizon", "drawdown", "goal", "style", "net_worth", "liquidity", "experience"]
    captions = {
        "horizon": "Horizonte declarado",
        "drawdown": "Reacción ante drawdown del 30%",
        "goal": "Objetivo principal",
        "style": "Estilo declarado",
        "net_worth": "Peso del portfolio en su patrimonio",
        "liquidity": "Necesidad de liquidez próxima",
        "experience": "Experiencia invirtiendo",
    }
    for key in label_order:
        val = profile.get(key)
        if not val:
            continue
        label = _INVESTOR_LABELS.get(key, {}).get(val, val)
        lines.append(f"- {captions[key]}: {label}")

    if not lines:
        return ""

    if mode == "descriptive":
        instruction = (
            "Podés mencionar y cruzar este perfil con los datos del snapshot. "
            "PROHIBIDO inferir causas del gap perfil-cartera, recomendar cambios, "
            "o explicar el 'por qué' usando el perfil como hipótesis. Si hay "
            "mismatch, presentá el dato (\"declaró X, la cartera tiene Y\") sin "
            "interpretarlo."
        )
    else:
        instruction = (
            "Podés inferir causas plausibles del gap perfil-cartera y conectar "
            "patrones operativos con sub-dimensiones del perfil. Hipótesis sí, "
            "recetas específicas (\"comprá X / vendé Y\") no."
        )

    return (
        "\n\nPERFIL DEL INVERSOR (lo que declaró en el onboarding)\n"
        + instruction + "\n"
        + "\n".join(lines)
    )


class ChatMsg(BaseModel):
    role: str = Field(..., max_length=20)
    # max_length 5000: cubre AMBOS roles del array de history.
    # - user: limitado a 500 por el frontend (input field maxLength=500).
    # - assistant: respuestas del bot Pro pueden ser hasta 800 tokens output
    #   ≈ 3200 chars típicos. 5000 deja margen 50% por output denso o
    #   markdown que infla.
    # Audit #3 B7 bajó a 1000 sin considerar que assistant history también
    # se validaba — segundo turno explotaba con string_too_long porque la
    # respuesta previa del bot superaba el cap. Restaurado a 5000 (no 4000
    # original) — alineado con el cap real del modelo.
    content: str = Field(..., min_length=1, max_length=5000)

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


# ─── yfinance cache layer (Pack A v2) ────────────────────────────────────────
# Helpers compartidos para tools del Coach IA que consultan métricas
# fundamentales / earnings / analysts via yfinance.
#
# Patrón:
#   payload = _yf_fetch_cached(ticker, kind, fetcher_fn)
#   donde fetcher_fn(ticker) → dict normalizado (puede tirar excepción)
#
# Si hay row fresh en cache (< 6h) → devuelve cache.
# Si stale o no existe → llama fetcher → persiste → devuelve.
# Si fetcher falla y hay row stale (< 7d) → devuelve stale + warning log.
# Si fetcher falla y NO hay cache → devuelve {available: false, reason: ...}.

# TTL granular por kind — refleja la realidad de cuán seguido cambia cada dato.
# Default 6h; algunos kinds tienen TTL más largo porque sus datos son estables.
# Semáforo + timeout para yfinance (audit Pack A v2 fix B1).
#
# Sin esto: 50 Pro concurrentes pidiendo scorecards distintos satura el
# threadpool de FastAPI (default 40 workers) y degrada TODO el backend
# (login, snapshots, /positions). El módulo news tenía BoundedSemaphore(16),
# yfinance no.
#
# Cap a 8 fetches in-flight process-wide. Si todos los slots están en uso,
# los siguientes esperan en cola (no bloquean otros endpoints).
#
# IMPORTANTE — fix B1 del audit final:
# La primera implementación usó `with ThreadPoolExecutor(...)` lo cual
# bloquea en __exit__ esperando al thread hung (defeats el timeout).
# Solución: ThreadPoolExecutor GLOBAL módulo-level que NO se cierra.
# El thread que timea queda en bg, lo dejamos morir naturalmente — pero
# el caller libera el semáforo en su timeout sin esperar al thread.
import threading as _threading_yf
from concurrent.futures import ThreadPoolExecutor as _YFThreadPoolExecutor
_yf_fetch_semaphore = _threading_yf.BoundedSemaphore(8)
# Pool dedicado, max 8 workers (mismo cap que semáforo). NO usar `with`.
_yf_executor = _YFThreadPoolExecutor(max_workers=8, thread_name_prefix="yf-fetch")

# Timeout 10s para fetcher externo (yfinance). Si yf cuelga o tarda > 10s,
# devolvemos available=false y cache stale si está.
YF_FETCH_TIMEOUT_SECONDS = 10


YF_CACHE_TTL_DEFAULT_SECONDS = 6 * 60 * 60          # 6h default
YF_CACHE_TTL_BY_KIND = {
    # Datos que casi no cambian intradía (audit Pack A v2 cost optimization):
    "profile":     24 * 60 * 60,    # 24h — descripción de empresa, sector (~0 cambios/día)
    "analysts":    24 * 60 * 60,    # 24h — recommendations cambian ~1×/semana
    # Datos que cambian pero no tanto:
    "fundamentals": 12 * 60 * 60,   # 12h — P/E sigue precio, EPS solo cambia con earnings
    "scorecard":    12 * 60 * 60,   # 12h — derivado de fundamentals
    # Datos más volátiles:
    "earnings":     6 * 60 * 60,    # 6h — próxima fecha + surprises pueden actualizarse
}
# Mantener el alias viejo para back-compat con tests existentes
YF_CACHE_TTL_SECONDS = YF_CACHE_TTL_DEFAULT_SECONDS
YF_CACHE_STALE_FALLBACK_SECONDS = 7 * 24 * 60 * 60  # 7d fallback si fetcher falla


def _yf_normalize_ticker(ticker: str) -> str:
    """Normaliza ticker para lookup en yfinance.

    Convenciones de Rendi → yfinance:
    - CEDEARs llegan con .BA — yfinance las soporta tal cual (TSLA.BA).
    - Cripto: el frontend usa 'BTC', yfinance espera 'BTC-USD'. Mapeo via
      CRYPTO_YF (ya existe global). Si no está en el map, lo dejamos como
      vino (BTC-USD ya viene normalizado en algunos callers).
    """
    if not ticker:
        return ""
    t = str(ticker).upper().strip()
    # Si es cripto sin sufijo, mapear a -USD
    if t in CRYPTO_YF:
        return CRYPTO_YF[t]
    return t


def _yf_cache_read(conn, ticker: str, kind: str) -> tuple:
    """Lee row del cache. Devuelve (payload_dict_or_None, age_seconds_or_inf).

    fetched_at guardado como epoch float (string en SQLite), no ISO. Esto
    evita la ambigüedad UTC vs local naive que tenía con datetime.isoformat().
    Si no hay row, devuelve (None, inf).
    """
    import time as _time
    row = conn.execute(
        "SELECT fetched_at, payload_json FROM yfinance_cache WHERE ticker=? AND kind=?",
        (ticker, kind),
    ).fetchone()
    if not row:
        return (None, float('inf'))
    try:
        fetched_epoch = float(row["fetched_at"])
        age = _time.time() - fetched_epoch
        payload = json.loads(row["payload_json"])
        return (payload, age)
    except Exception as ex:
        log.warning("yfinance_cache parse failed ticker=%s kind=%s: %s", ticker, kind, ex)
        return (None, float('inf'))


def _yf_cache_write(conn, ticker: str, kind: str, payload: dict) -> None:
    """Persiste payload normalizado al cache. UPSERT por (ticker, kind).
    fetched_at = time.time() epoch float (segundos UTC desde Unix epoch).
    """
    import time as _time
    try:
        conn.execute(
            """INSERT INTO yfinance_cache(ticker, kind, fetched_at, payload_json)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(ticker, kind) DO UPDATE SET
                 fetched_at = excluded.fetched_at,
                 payload_json = excluded.payload_json""",
            (ticker, kind, str(_time.time()), json.dumps(payload, default=str)),
        )
        conn.commit()
    except Exception as ex:
        log.warning("yfinance_cache write failed ticker=%s kind=%s: %s", ticker, kind, ex)


def _yf_fetch_cached(ticker: str, kind: str, fetcher_fn) -> dict:
    """Lee de cache o llama fetcher_fn(yf_ticker) si stale/missing.

    fetcher_fn debe ser una función `(yf_ticker_str) -> dict` que devuelva el
    payload normalizado. Si el fetcher tira excepción, retornamos cache stale
    si existe (< 7d), sino devuelve {available: False, reason: 'fetch_failed'}.

    Pattern:
      payload = _yf_fetch_cached('NVDA', 'fundamentals', _yf_fundamentals_fetcher)

    Devuelve el payload tal cual fue cacheado. NO inyecta `_cache_age` ni
    metadata extra — el caller decide si la quiere.
    """
    yf_ticker = _yf_normalize_ticker(ticker)
    if not yf_ticker:
        return {"available": False, "reason": "ticker vacío"}

    conn = get_db()
    try:
        # 1. Leer cache — TTL granular según kind (audit cost opt)
        ttl = YF_CACHE_TTL_BY_KIND.get(kind, YF_CACHE_TTL_DEFAULT_SECONDS)
        cached, age = _yf_cache_read(conn, yf_ticker, kind)
        if cached is not None and age < ttl:
            # Fresh — devolver directo. Loggeamos cache hit para medir hit rate.
            log.debug("yf_cache HIT ticker=%s kind=%s age_s=%d ttl_s=%d", yf_ticker, kind, int(age), ttl)
            return cached
        if cached is not None:
            log.debug("yf_cache MISS_STALE ticker=%s kind=%s age_s=%d ttl_s=%d", yf_ticker, kind, int(age), ttl)
        else:
            log.debug("yf_cache MISS_NEW ticker=%s kind=%s", yf_ticker, kind)

        # 2. Stale o missing — llamar fetcher con semáforo + timeout.
        # Audit fix B1: usamos executor GLOBAL (_yf_executor) en lugar de
        # crear uno nuevo con `with`. La razón: `with` bloquea en __exit__
        # esperando shutdown del thread, neutralizando el timeout. Con
        # executor global, el thread hung queda en bg (lo dejamos morir
        # naturalmente cuando yfinance eventualmente responde o se hace GC).
        try:
            from concurrent.futures import TimeoutError as FutureTimeout
            with _yf_fetch_semaphore:
                future = _yf_executor.submit(fetcher_fn, yf_ticker)
                try:
                    new_payload = future.result(timeout=YF_FETCH_TIMEOUT_SECONDS)
                except FutureTimeout:
                    log.warning("yf fetcher TIMEOUT after %ds for %s/%s",
                                YF_FETCH_TIMEOUT_SECONDS, yf_ticker, kind)
                    # No esperamos al thread — lo dejamos morir en bg.
                    # Intentamos cancelar (no garantía, fetcher_fn no es cancelable,
                    # pero al menos libera el slot si todavía no arrancó).
                    future.cancel()
                    # Caemos al stale fallback abajo.
                    raise TimeoutError(f"yfinance no respondió en {YF_FETCH_TIMEOUT_SECONDS}s")
            # Sanitizar: solo cacheamos si no devuelve "available: False" por
            # error transitorio. Si devuelve available=False por motivo
            # estructural (ej. "cripto no aplica scorecard"), sí cacheamos
            # para evitar re-fetching innecesario.
            if isinstance(new_payload, dict):
                _yf_cache_write(conn, yf_ticker, kind, new_payload)
                return new_payload
            else:
                log.warning("yf fetcher returned non-dict for %s/%s: %r", yf_ticker, kind, type(new_payload))
                if cached is not None and age < YF_CACHE_STALE_FALLBACK_SECONDS:
                    return cached
                return {"available": False, "reason": "fetch_returned_invalid_type"}
        except Exception as ex:
            log.warning("yf fetcher failed for %s/%s: %s", yf_ticker, kind, ex)
            # 3. Fallback a cache stale si existe y no es demasiado vieja.
            # Audit fix: COPIAR el dict antes de mutar — sin esto, el cache
            # quedaba marcado _stale=true permanentemente aunque yf se recupere.
            if cached is not None and age < YF_CACHE_STALE_FALLBACK_SECONDS:
                log.info("yf using stale cache for %s/%s (age=%ds)", yf_ticker, kind, int(age))
                stale_copy = dict(cached)
                stale_copy["_stale"] = True
                stale_copy["_age_hours"] = round(age / 3600, 1)
                return stale_copy
            return {"available": False, "reason": f"fetch_failed: {type(ex).__name__}"}
    finally:
        conn.close()


def _yf_is_info_valid(info: dict) -> bool:
    """True si el `info` de yfinance parece ser de un ticker real (no fake).

    yfinance NO tira excepción para tickers inválidos — devuelve un dict
    casi vacío (típicamente solo 'trailingPegRatio' o nada). Detectamos por:
      - longitud del dict (>10 keys es signal de ticker real)
      - presencia de al menos un identificador (longName / shortName / symbol)
    """
    if not isinstance(info, dict) or len(info) < 10:
        return False
    return any(info.get(k) for k in ("longName", "shortName", "symbol"))


def _yf_is_equity_with_fundamentals(info: dict) -> bool:
    """Más estricto que _yf_is_info_valid: además de "ticker real", verifica
    que sea una EQUITY con fundamentales (P/E, EPS, etc).

    Excluye:
      - Cripto (quoteType='CRYPTOCURRENCY', sin P/E ni EPS)
      - ETFs (quoteType='ETF' — fundamentales no aplican directo)
      - Bonos (no aparecen en yfinance pero defensa por las dudas)
      - Tickers fake

    Para tools como scorecard, earnings, analysts — que NO aplican a cripto.
    """
    if not _yf_is_info_valid(info):
        return False
    quote_type = (info.get("quoteType") or "").upper()
    if quote_type in ("CRYPTOCURRENCY", "ETF", "MUTUALFUND", "CURRENCY", "INDEX"):
        return False
    # Verificación funcional: tiene al menos un fundamental clave.
    # Cripto tiene marketCap pero NO trailingPE/EPS.
    has_fundamental = any(
        info.get(k) is not None
        for k in ("trailingPE", "forwardPE", "trailingEps", "returnOnEquity")
    )
    return has_fundamental


def _record_tool_usage(uid: int, tool_name: str) -> None:
    """Suma 1 al contador del día. No-op si falla (no debe bloquear el tool)."""
    try:
        conn = get_db()
        try:
            today = datetime.utcnow().strftime('%Y-%m-%d')
            conn.execute(
                """INSERT INTO ai_tool_usage(user_id, date, tool_name, count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(user_id, date, tool_name) DO UPDATE SET
                     count = count + 1""",
                (uid, today, tool_name),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as ex:
        log.warning("record_tool_usage failed tool=%s uid=%s: %s", tool_name, uid, ex)


# ─── Pack A v2: Fetchers + tools de fundamentales / scorecard / earnings ────
#
# Cada fetcher consume yfinance y devuelve un dict normalizado listo para el
# LLM. Si yfinance no tiene data para ese ticker (cripto sin fundamentales,
# bonos AR, ticker inválido), el fetcher devuelve {available: False, reason}
# para que el LLM SEPA no inventar.
#
# Todos los fetchers se invocan vía _yf_fetch_cached(ticker, kind, fetcher).

# ─── Thresholds del scorecard (decisiones de producto) ───────────────────────
# Cada métrica tiene 3 niveles: green (saludable), amber (mirar), red (alerta).
# "outlier" se usa para casos extremos donde el dato es probablemente roto
# (ej: payout_ratio > 200% suele ser data sucia, no realidad fundamental).
#
# Diseñados con bias value-investing tradicional. NO son recomendaciones
# operativas — son señales que el bot interpreta + conecta al perfil del user.

SCORECARD_THRESHOLDS = {
    # Margen de seguridad: fair_value de analistas vs precio actual
    "margin_of_safety_pct": {
        "green_min": 15,    # > 15% under fair value = oportunidad
        "amber_min": 0,     # 0-15% = neutral
        # < 0 = red (precio over fair value)
    },
    # PEG ratio: P/E / growth rate. < 1 = barato vs crecimiento.
    # > 200% probable data sucia, marcamos outlier.
    "peg_ratio": {
        "green_max": 1.0,
        "amber_max": 1.5,
        "outlier_min": 5.0,   # PEG > 5 es probablemente error
    },
    # Payout ratio: % de ganancias pagadas como dividendo. < 50% sostenible.
    "payout_ratio_pct": {
        "green_max": 50,
        "amber_max": 80,
        "outlier_min": 200,   # > 200% es probable distorsión cambiaria
    },
    # ROE: ganancia sobre patrimonio. > 15% = empresa muy rentable.
    "roe_pct": {
        "green_min": 15,
        "amber_min": 8,
    },
    # Debt/Equity: deuda sobre patrimonio. Bajo es bueno.
    # Nota: bancos tienen D/E altísimo por naturaleza — excluimos sector financiero.
    "debt_to_equity": {
        "green_max": 0.5,
        "amber_max": 1.5,
        "exclude_sectors": ["Financial Services"],
    },
    # Profit margin: utilidad neta / revenue. > 15% es excelente, < 5% margen débil.
    "profit_margin_pct": {
        "green_min": 15,
        "amber_min": 5,
    },
    # Revenue growth YoY: crecimiento últimos 12 meses.
    "revenue_growth_pct": {
        "green_min": 10,
        "amber_min": 0,
        # < 0 = red (revenue contrayendo)
    },
}


def _status_of_metric(metric_key: str, value, sector: str = None) -> str:
    """Aplica thresholds y devuelve 'green' | 'amber' | 'red' | 'outlier' | 'na'.

    Si value es None → 'na' (not available).
    Outlier para casos que rompen la heurística (ej: payout 400% por TC).
    """
    if value is None:
        return "na"
    th = SCORECARD_THRESHOLDS.get(metric_key, {})

    # Excluciones por sector (ej: D/E no aplica a bancos)
    excluded = th.get("exclude_sectors", [])
    if sector and sector in excluded:
        return "na"

    # Outlier check primero (data sucia)
    outlier_min = th.get("outlier_min")
    if outlier_min is not None and abs(value) >= outlier_min:
        return "outlier"

    # Métricas "más es mejor" (green_min / amber_min)
    if "green_min" in th:
        if value >= th["green_min"]:
            return "green"
        if value >= th.get("amber_min", 0):
            return "amber"
        return "red"

    # Métricas "menos es mejor" (green_max / amber_max)
    if "green_max" in th:
        if value <= th["green_max"]:
            return "green"
        if value <= th.get("amber_max", float("inf")):
            return "amber"
        return "red"

    return "na"


def _yf_fundamentals_fetcher(yf_ticker: str) -> dict:
    """Fetch info de yfinance y devuelve fundamentales normalizados.

    Para tickers sin info válida (cripto, fake), devuelve available=False.
    """
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = t.info or {}
    if not _yf_is_info_valid(info):
        return {
            "available": False,
            "reason": f"yfinance no tiene fundamentales para {yf_ticker} (cripto, bono o ticker inválido)",
        }

    return {
        "available": True,
        "ticker": yf_ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "trailing_eps_usd": info.get("trailingEps"),
        "forward_eps_usd": info.get("forwardEps"),
        # dividendYield viene YA en porcentaje (no decimal). MSFT=0.87 significa
        # 0.87%, NVDA=0.02 significa 0.02%. Verificado cross-checking con yfinance.
        "dividend_yield_pct": round(info.get("dividendYield"), 2) if info.get("dividendYield") is not None else None,
        "market_cap_usd": info.get("marketCap"),
        "week_52_high_usd": info.get("fiftyTwoWeekHigh"),
        "week_52_low_usd": info.get("fiftyTwoWeekLow"),
        "beta": info.get("beta"),
        "currency": info.get("currency", "USD"),
    }


def _yf_scorecard_fetcher(yf_ticker: str) -> dict:
    """Fetch + arma el scorecard de valor con semáforos.

    Devuelve estructura lista para el LLM:
      {
        available, ticker, company_name, sector,
        price: {current, fair_value, margin_of_safety_pct, source},
        metrics: [{name, value, value_label, reference, status, interpretation}],
        overall: {green_count, amber_count, red_count, na_count}
      }
    """
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = t.info or {}
    if not _yf_is_equity_with_fundamentals(info):
        quote_type = (info.get("quoteType") or "desconocido").lower()
        return {
            "available": False,
            "reason": (
                f"El scorecard de valor no aplica a {yf_ticker} (tipo: {quote_type}). "
                "Métricas como P/E, ROE o payout son específicas de acciones de empresas. "
                "Para cripto se usan otros frameworks (S2F, on-chain) que no cubrimos. "
                "Para bonos AR consultar metadata específica."
            ),
        }

    sector = info.get("sector")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    fair_value = info.get("targetMeanPrice")
    n_analysts = info.get("numberOfAnalystOpinions") or 0

    # Audit fix #3: si menos de 5 analistas cubren el ticker, el target mean
    # es ruido (alta varianza, no representa consenso). Marcamos el fair
    # value como "low_confidence" — la métrica se incluye pero el status
    # cae a 'amber' con interpretation_hint que aclara la limitación.
    # Sin esto: small caps con 1-2 analistas pintaban verde y engañaban al user.
    fair_value_confidence = "high" if n_analysts >= 5 else "low" if n_analysts >= 2 else "none"

    # Audit fix #4: si el ticker es un CEDEAR (.BA) con currency != USD,
    # los datos P/E, EPS están en ARS — NO se pueden comparar contra
    # thresholds USD ni mezclar con scorecards de US stocks. Devolvemos
    # available=false con razón clara para que el LLM redirija al ticker US.
    ticker_currency = (info.get("currency") or "USD").upper()
    if ticker_currency != "USD" and yf_ticker.endswith(".BA"):
        # Sugerir el ticker US equivalente (CEDEAR sin .BA)
        us_ticker = yf_ticker.replace(".BA", "")
        return {
            "available": False,
            "reason": (
                f"El scorecard de {yf_ticker} usaría métricas en {ticker_currency} "
                f"(P/E, EPS no son comparables vs scorecards en USD). "
                f"Para análisis fundamental en USD, consultá '{us_ticker}' "
                "(mismo activo subyacente listado en US)."
            ),
        }

    # Calcular margen de seguridad: (fair - current) / fair × 100
    margin_pct = None
    if current_price and fair_value and fair_value > 0:
        margin_pct = round((fair_value - current_price) / fair_value * 100, 2)

    # Extraer raw metrics
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    peg = info.get("pegRatio")
    payout_raw = info.get("payoutRatio")  # decimal (0.20 = 20%)
    payout_pct = round(payout_raw * 100, 2) if payout_raw is not None else None
    roe_raw = info.get("returnOnEquity")  # decimal
    roe_pct = round(roe_raw * 100, 2) if roe_raw is not None else None
    de_raw = info.get("debtToEquity")
    # yfinance da D/E como número (30.27) en lugar de ratio (0.30). Normalizamos a ratio.
    de_ratio = round(de_raw / 100, 2) if de_raw is not None else None
    pm_raw = info.get("profitMargins")  # decimal
    pm_pct = round(pm_raw * 100, 2) if pm_raw is not None else None
    rg_raw = info.get("revenueGrowth")  # decimal YoY
    rg_pct = round(rg_raw * 100, 2) if rg_raw is not None else None

    # Build metrics array — cada item: nombre, valor crudo, label, referencia, status, interpretación
    metrics = []

    # Métrica 1: Fair Value (consenso analistas)
    # Audit fix #3: forzar status a 'amber' si confidence baja (< 5 analistas).
    # El número se reporta pero el LLM debe matizar — un target de 2 analistas
    # NO es consenso confiable.
    if margin_pct is not None:
        status = _status_of_metric("margin_of_safety_pct", margin_pct)
        if fair_value_confidence == "low":
            status = "amber"  # Override — alta varianza estimate
            confidence_note = f" Solo {n_analysts} analistas cubren — alta varianza, tomar con pinzas."
        elif fair_value_confidence == "none":
            status = "na"
            confidence_note = " Sin cobertura suficiente de analistas — fair value no confiable."
        else:
            confidence_note = ""
        metrics.append({
            "name": "Fair Value (consenso analistas)",
            "value": fair_value,
            "value_label": f"US$ {fair_value:.2f} (margen {margin_pct:+.1f}%)",
            "reference": f"> 15% bajo el precio = oportunidad ({n_analysts} analistas)",
            "status": status,
            "n_analysts": n_analysts,
            "confidence": fair_value_confidence,
            "interpretation_hint": (
                f"Target medio US$ {fair_value:.2f} (consenso {n_analysts} analistas) "
                f"vs precio actual US$ {current_price:.2f}. Margen {margin_pct:+.1f}%."
                + confidence_note
            ),
        })

    # Métrica 2: PER actual vs Forward (sustituto del "PER histórico" del screenshot)
    if trailing_pe is not None and forward_pe is not None:
        pe_change_pct = round((forward_pe - trailing_pe) / trailing_pe * 100, 1)
        # Forward < trailing = ganancias esperadas crecen → bueno
        status = "green" if pe_change_pct < -10 else "amber" if pe_change_pct < 5 else "red"
        metrics.append({
            "name": "PER actual vs forward",
            "value": trailing_pe,
            "value_label": f"{trailing_pe:.1f}× (forward {forward_pe:.1f}×)",
            "reference": "Forward < actual = ganancias esperadas crecen",
            "status": status,
            "interpretation_hint": (
                f"PER actual {trailing_pe:.1f}× vs forward {forward_pe:.1f}× ({pe_change_pct:+.1f}%). "
                f"{'Las ganancias esperadas crecen — el múltiplo se contrae a futuro.' if pe_change_pct < 0 else 'Las ganancias esperadas no acompañan el precio actual.'}"
            ),
        })
    elif trailing_pe is not None:
        metrics.append({
            "name": "PER actual",
            "value": trailing_pe,
            "value_label": f"{trailing_pe:.1f}×",
            "reference": "Forward P/E no disponible en API",
            "status": "na",
            "interpretation_hint": f"PER {trailing_pe:.1f}× sin proyección forward disponible para comparar.",
        })

    # Métrica 3: PEG Ratio
    if peg is not None:
        status = _status_of_metric("peg_ratio", peg)
        metrics.append({
            "name": "PEG Ratio",
            "value": peg,
            "value_label": f"{peg:.2f}",
            "reference": "< 1.0 (ideal value)",
            "status": status,
            "interpretation_hint": (
                f"PEG {peg:.2f} — "
                f"{'el precio luce barato vs el crecimiento esperado.' if status == 'green' else 'el mercado ya descuenta parte del crecimiento.' if status == 'amber' else 'el premium sobre crecimiento esperado es alto.' if status == 'red' else 'dato anómalo, ignorá para esta consulta.'}"
            ),
        })

    # Métrica 4: Payout Ratio
    if payout_pct is not None:
        status = _status_of_metric("payout_ratio_pct", payout_pct)
        metrics.append({
            "name": "Payout Ratio",
            "value": payout_pct,
            "value_label": f"{payout_pct:.1f}%",
            "reference": "< 50% (sostenible)",
            "status": status,
            "interpretation_hint": (
                f"Payout {payout_pct:.1f}% — "
                f"{'dividendo cómodamente sostenible, mucha plata reinvertida.' if status == 'green' else 'dividendo OK pero cerca del límite.' if status == 'amber' else 'paga casi todo o más que sus ganancias — frágil.' if status == 'red' else 'dato anómalo (probable distorsión cambiaria en ADRs AR).'}"
            ),
        })

    # Métrica 5: ROE
    if roe_pct is not None:
        status = _status_of_metric("roe_pct", roe_pct)
        metrics.append({
            "name": "ROE (Return on Equity)",
            "value": roe_pct,
            "value_label": f"{roe_pct:.1f}%",
            "reference": "> 15% (alta calidad)",
            "status": status,
            "interpretation_hint": (
                f"ROE {roe_pct:.1f}% — "
                f"{'rentabilidad sobre capital muy alta, calidad fundamental.' if status == 'green' else 'rentabilidad razonable.' if status == 'amber' else 'rentabilidad débil, capital trabajando poco.'}"
            ),
        })

    # Métrica 6: Debt/Equity (skip si sector financiero)
    if de_ratio is not None:
        status = _status_of_metric("debt_to_equity", de_ratio, sector=sector)
        if status != "na":
            metrics.append({
                "name": "Debt/Equity",
                "value": de_ratio,
                "value_label": f"{de_ratio:.2f}",
                "reference": "< 0.5 (balance solido)",
                "status": status,
                "interpretation_hint": (
                    f"D/E {de_ratio:.2f} — "
                    f"{'balance solido, deuda baja.' if status == 'green' else 'deuda en rango razonable.' if status == 'amber' else 'apalancamiento alto, sensible a tasas.'}"
                ),
            })

    # Métrica 7: Profit Margin
    if pm_pct is not None:
        status = _status_of_metric("profit_margin_pct", pm_pct)
        metrics.append({
            "name": "Profit Margin",
            "value": pm_pct,
            "value_label": f"{pm_pct:.1f}%",
            "reference": "> 15% (negocio rentable)",
            "status": status,
            "interpretation_hint": (
                f"Margen {pm_pct:.1f}% — "
                f"{'negocio muy rentable, alto poder de pricing.' if status == 'green' else 'margen aceptable.' if status == 'amber' else 'margen débil, vulnerable a shocks de costo.'}"
            ),
        })

    # Métrica 8: Revenue Growth YoY
    if rg_pct is not None:
        status = _status_of_metric("revenue_growth_pct", rg_pct)
        metrics.append({
            "name": "Revenue Growth YoY",
            "value": rg_pct,
            "value_label": f"{rg_pct:+.1f}%",
            "reference": "> 10% (crecimiento sólido)",
            "status": status,
            "interpretation_hint": (
                f"Revenue YoY {rg_pct:+.1f}% — "
                f"{'crecimiento de doble dígito.' if status == 'green' else 'crecimiento positivo pero modesto.' if status == 'amber' else 'revenue contrayendo, alerta.'}"
            ),
        })

    # Resumen agregado
    statuses = [m["status"] for m in metrics]
    overall = {
        "green_count": statuses.count("green"),
        "amber_count": statuses.count("amber"),
        "red_count": statuses.count("red"),
        "outlier_count": statuses.count("outlier"),
        "na_count": statuses.count("na"),
        "total": len(metrics),
    }
    # Score qualitativo simple: si > 60% verdes = "Sólido", 40-60% = "Mixto", < 40% = "Débil"
    if overall["total"] > 0:
        green_share = overall["green_count"] / overall["total"]
        if green_share >= 0.6:
            overall["label"] = "Sólido"
        elif green_share >= 0.4:
            overall["label"] = "Mixto"
        else:
            overall["label"] = "Débil"
    else:
        overall["label"] = "Sin datos"

    return {
        "available": True,
        "ticker": yf_ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": sector,
        "price": {
            "current_usd": current_price,
            "fair_value_usd": fair_value,
            "margin_of_safety_pct": margin_pct,
            "source": "Consenso analistas (target mean)",
        },
        "metrics": metrics,
        "overall": overall,
        "_interpretation_hint": (
            f"{overall['green_count']}/{overall['total']} métricas en verde "
            f"({overall['label']}). Conectá con la posición del user en su cartera si la tiene. "
            "Nunca recomendar operativa — sí podés sugerir 'cosas a considerar'."
        ),
    }


def _yf_earnings_fetcher(yf_ticker: str) -> dict:
    """Devuelve earnings: próxima fecha + últimos 4 quarters con surprise %."""
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = t.info or {}
    if not _yf_is_equity_with_fundamentals(info):
        return {
            "available": False,
            "reason": f"{yf_ticker} no es una equity con earnings reports (cripto, ETF, bono o ticker inválido).",
        }

    next_earnings = None
    next_earnings_estimates = None
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            edates = cal.get("Earnings Date")
            if edates and isinstance(edates, list) and len(edates) > 0:
                next_earnings = str(edates[0])
            high = cal.get("Earnings High")
            low = cal.get("Earnings Low")
            avg = cal.get("Earnings Average")
            if high is not None and low is not None:
                next_earnings_estimates = {
                    "eps_high": round(float(high), 2),
                    "eps_low": round(float(low), 2),
                    "eps_average": round(float(avg), 2) if avg is not None else None,
                }
    except Exception as ex:
        log.warning("yf calendar fetch failed for %s: %s", yf_ticker, ex)

    last_quarters = []
    try:
        eh = t.earnings_history
        if eh is not None and hasattr(eh, 'iterrows') and not eh.empty:
            for idx, row in eh.iterrows():
                last_quarters.append({
                    "date": str(idx),
                    "eps_estimate": round(float(row.get("epsEstimate")), 2) if row.get("epsEstimate") is not None else None,
                    "eps_actual": round(float(row.get("epsActual")), 2) if row.get("epsActual") is not None else None,
                    "surprise_pct": round(float(row.get("surprisePercent", 0)) * 100, 2) if row.get("surprisePercent") is not None else None,
                })
    except Exception as ex:
        log.warning("yf earnings_history fetch failed for %s: %s", yf_ticker, ex)

    # Calcular surprise promedio últimos 4
    surprise_avg = None
    if last_quarters:
        sps = [q["surprise_pct"] for q in last_quarters if q.get("surprise_pct") is not None]
        if sps:
            surprise_avg = round(sum(sps) / len(sps), 2)

    # Build _interpretation_hint sin bug del ternario (antes el if/else
    # cortaba la segunda string literal silenciosamente).
    hint_parts = []
    if surprise_avg is not None:
        hint_parts.append(f"Surprise promedio últimos 4Q: {surprise_avg:+.1f}%.")
    hint_parts.append(
        "Surprises positivas consistentes (>5%) sugieren conservadurismo de la "
        "empresa o capacidad de superar guidance. Surprises negativas grandes "
        "alertan sobre deterioro o expectativas demasiado optimistas."
    )

    return {
        "available": True,
        "ticker": yf_ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "next_earnings_date": next_earnings,
        "next_earnings_estimates": next_earnings_estimates,
        "last_quarters": last_quarters,
        "surprise_avg_last_4q_pct": surprise_avg,
        "_interpretation_hint": " ".join(hint_parts),
    }


def _yf_analysts_fetcher(yf_ticker: str) -> dict:
    """Devuelve recommendations + price targets."""
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = t.info or {}
    if not _yf_is_equity_with_fundamentals(info):
        return {
            "available": False,
            "reason": f"{yf_ticker} no tiene cobertura de analistas (cripto, ETF o ticker inválido).",
        }

    current = info.get("currentPrice") or info.get("regularMarketPrice")
    target_mean = info.get("targetMeanPrice")
    target_high = info.get("targetHighPrice")
    target_low = info.get("targetLowPrice")
    rec_mean = info.get("recommendationMean")  # 1=strong buy, 5=sell
    rec_key = info.get("recommendationKey")
    n_analysts = info.get("numberOfAnalystOpinions")

    upside_pct = None
    if current and target_mean and current > 0:
        upside_pct = round((target_mean - current) / current * 100, 2)

    # Mapeo recommendationKey → label en español
    rec_label_map = {
        "strong_buy": "Compra fuerte",
        "buy": "Compra",
        "hold": "Mantener",
        "sell": "Venta",
        "strong_sell": "Venta fuerte",
        "underperform": "Underperform",
        "outperform": "Outperform",
    }
    rec_label = rec_label_map.get(rec_key, rec_key) if rec_key else None

    return {
        "available": True,
        "ticker": yf_ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "current_price_usd": current,
        "target_mean_usd": target_mean,
        "target_high_usd": target_high,
        "target_low_usd": target_low,
        "upside_pct": upside_pct,
        "recommendation_label": rec_label,
        "recommendation_mean_score": round(rec_mean, 2) if rec_mean is not None else None,
        "n_analysts": n_analysts,
        "_interpretation_hint": (
            f"{n_analysts} analistas cubren. Recomendación: {rec_label}. "
            f"Target medio US$ {target_mean:.2f} = upside {upside_pct:+.1f}% sobre precio actual. "
            "Recordá: targets de analistas son OPINIONES, no certezas — útiles como contexto, no como decisión."
        ) if all([n_analysts, rec_label, target_mean, upside_pct is not None]) else "",
    }


def _yf_profile_fetcher(yf_ticker: str) -> dict:
    """Devuelve descripción de la empresa."""
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = t.info or {}
    if not _yf_is_info_valid(info):
        return {"available": False, "reason": "yfinance no tiene profile para este ticker"}

    summary = info.get("longBusinessSummary") or ""
    # Cap summary a 500 chars para no inflar el contexto del LLM
    if len(summary) > 500:
        summary = summary[:497] + "..."

    return {
        "available": True,
        "ticker": yf_ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "full_time_employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
        "business_summary": summary,
        "_interpretation_hint": (
            "Usá este profile SOLO si el user pregunta '¿a qué se dedica X?' o "
            "necesita contexto del negocio. NO repitas el sector/industria si "
            "ya lo dijiste con otra tool."
        ),
    }


def _sanitize_chat_snapshot(raw: dict) -> dict:
    """Normaliza el snapshot que viene del frontend antes de pasarlo al LLM.

    El frontend manda `{summary, positions, monthly, brokers, ...}` pero
    nada garantiza que los campos sean del tipo esperado (None vs lista,
    objetos con shape distinto, etc.). Si llega basura, el LLM puede
    confundirse silenciosamente.

    Estrategia: NO rechazar (lax) — normalizar:
      - keys no esperadas: se preservan tal cual (el LLM las puede ignorar)
      - listas que vienen None → []
      - objetos críticos con shape inesperado → loggear + dejar tal cual
      - inyectar marca '_kind' a positions ('open') y operations ('closed_trade')
        SI vienen sin etiqueta — defensa para que el LLM no las confunda
        aunque el frontend olvide marcarlas.

    Devolvemos un dict nuevo (no muta el input).
    """
    if not isinstance(raw, dict):
        return {}

    sanitized: dict = dict(raw)  # shallow copy

    # 1. Listas top-level — si vienen None, convertimos a []
    for list_key in ("positions", "operations", "monthly", "brokers"):
        v = sanitized.get(list_key)
        if v is None:
            sanitized[list_key] = []
        elif not isinstance(v, list):
            # Type mismatch — loggear y forzar a []
            log.warning("Chat snapshot field %r is not a list (got %s) — coerced to []",
                        list_key, type(v).__name__)
            sanitized[list_key] = []

    # 2. summary debe ser dict (o se omite)
    if "summary" in sanitized and not isinstance(sanitized["summary"], dict):
        log.warning("Chat snapshot.summary is not a dict — removed")
        sanitized.pop("summary", None)

    # 3. Defensa anti-confusión open/closed: cada position lleva
    # `_kind: 'open_position'`, cada operation lleva `_kind: 'closed_trade'`.
    # El LLM lo ve inline y desambigua incluso si el frontend no marcó.
    for p in sanitized.get("positions", []):
        if isinstance(p, dict) and "_kind" not in p:
            p["_kind"] = "open_position"
    for o in sanitized.get("operations", []):
        if isinstance(o, dict) and "_kind" not in o:
            o["_kind"] = "closed_trade"

    # 4. Marca top-level que el snapshot ya pasó por sanitizer (debug)
    sanitized["_sanitized"] = True

    return sanitized


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
    {
        "name": "get_realized_vs_unrealized",
        "description": "Devuelve el desglose preciso de P&L realizado (trades cerrados, USD absoluto) vs P&L unrealized (mark-to-market actual de posiciones abiertas). Usala cuando el usuario pregunta 'cuánto realmente gané/perdí', 'cuánto es sobre papel vs realizado', o cuando necesitás cuantificar el origen de su rendimiento sin confusión. Opcionalmente filtrá por un ticker específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset": {
                    "type": "string",
                    "description": "(Opcional) Ticker para filtrar (ej: NVDA, AL30). Sin sufijo .BA. Si se omite, devuelve totales de TODA la cartera.",
                }
            },
        },
    },
    {
        "name": "get_recent_news_for_assets",
        "description": "Trae las últimas 3-5 noticias relevantes para uno o más tickers de la cartera del usuario. Usala SOLO si el usuario pregunta específicamente sobre noticias, eventos recientes, o por qué un activo se movió. NO la uses para queries generales — cuesta latencia adicional.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tickers para los que buscar noticias. Máximo 5.",
                    "maxItems": 5,
                }
            },
            "required": ["symbols"],
        },
    },
    # ─── Pack A v2: tools de mercado externas (yfinance) ─────────────────
    # Estas tools traen data de fundamentales/earnings/analistas para tickers
    # de equity (acciones). NO funcionan para cripto ni bonos AR — el LLM
    # las llama solo cuando el ticker es una acción listada en US/CEDEAR.
    #
    # Las 4 tools comparten cache 6h en yfinance_cache. La 2da consulta del
    # mismo ticker en 6h es instantánea (sin penalty de costo extra).
    {
        "name": "get_stock_fundamentals",
        "description": (
            "Trae métricas fundamentales (P/E actual y forward, EPS, dividend yield, "
            "market cap, beta, rango 52 semanas, sector e industria) de UNA acción.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta sobre métricas puntuales: 'el P/E de NVDA', '¿cuánto paga AAPL en dividendos?'\n"
            "  - Necesitás 1-2 fundamentales rápidos sin armar todo un scorecard de valor\n"
            "  - El usuario menciona una valoración o múltiplo específico\n\n"
            "NO LA USES cuando:\n"
            "  - El usuario pregunta '¿está cara/barata?' o '¿es buena compra?' → usar get_value_scorecard (cubre todo)\n"
            "  - Pregunta sobre cripto o bonos AR → no aplica, decilo honesto\n"
            "  - Ya tenés los datos en el snapshot de la cartera del usuario\n\n"
            "Cache 6h. Latencia: ~1.5s primera vez, instantánea con cache."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Símbolo del activo (ej: NVDA, AAPL, GGAL, TSLA.BA). Sin guiones para cripto.",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_value_scorecard",
        "description": (
            "Devuelve un SCORECARD COMPLETO de valor de una acción: fair value de "
            "analistas, margen de seguridad, P/E, PEG, payout, ROE, deuda/equity, "
            "margen de utilidad y crecimiento de revenue — cada métrica con su "
            "STATUS (verde/ámbar/rojo) según thresholds de value investing.\n\n"
            "Esta es la tool 'estrella' del Pack — concentra el análisis fundamental "
            "típico en un solo call. Devuelve también un 'overall.label' (Sólido / "
            "Mixto / Débil) basado en cuántas métricas están en verde.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta '¿está cara X?', '¿es buena para comprar a largo?', "
            "    '¿qué pinta tiene NVDA fundamentalmente?'\n"
            "  - Pregunta sobre 'valoración', 'fundamentales', 'salud financiera' de un ticker\n"
            "  - Compara dos acciones explícitamente ('¿NVDA o AMD para largo?') → llamala UNA VEZ por ticker\n\n"
            "NO LA USES cuando:\n"
            "  - El usuario solo quiere el precio actual → get_current_prices\n"
            "  - Pregunta sobre cripto o bonos AR — NO APLICA, no inventes\n"
            "  - Pregunta sobre SU performance en el ticker → get_realized_vs_unrealized\n"
            "  - Pregunta sobre noticias recientes → get_recent_news_for_assets\n\n"
            "Cómo presentar el resultado al usuario:\n"
            "  - Usá los `value_label` que vienen formateados\n"
            "  - Usá los símbolos ✓ (green), — (amber/na), ✗ (red) en lugar de emojis\n"
            "  - Mostrá el `overall.label` arriba como resumen\n"
            "  - Para Pro: conectá con la posición del usuario en su cartera si la tiene\n"
            "  - Para Free/Plus: solo describí; NO interpretes 'compraría'/'vendería'\n\n"
            "Cache 6h. Latencia: ~2s primera vez."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Símbolo de la acción (NVDA, MSFT, GGAL, etc). NO funciona para cripto ni bonos.",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_earnings_history",
        "description": (
            "Próximo earnings date + últimos 4 quarters con surprise % (EPS actual "
            "vs estimate). Surprise = sobre o bajo expectativas de analistas.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta '¿cuándo reporta MSFT?', '¿cómo le fue a NVDA en el último earnings?'\n"
            "  - Pregunta sobre el historial de cumplimiento de expectativas\n"
            "  - Habla de timing de entrada/salida cerca de earnings\n\n"
            "NO LA USES cuando:\n"
            "  - El usuario pregunta valoración → usar get_value_scorecard\n"
            "  - Ticker es cripto/bono/ETF (no tiene earnings)\n\n"
            "Cache 6h."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Símbolo de la acción."}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_analyst_ratings",
        "description": (
            "Recomendación consenso de analistas (Strong Buy / Buy / Hold / Sell / Strong Sell) "
            "+ target price (alto/medio/bajo) + número de analistas que cubren.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta '¿qué dicen los analistas?', '¿cuál es el target?'\n"
            "  - Quiere ver consensus de Wall Street antes de decidir\n\n"
            "NO LA USES cuando:\n"
            "  - El usuario solo quiere precio → get_current_prices\n"
            "  - Pide análisis fundamental general → get_value_scorecard (ya incluye target mean)\n\n"
            "Tono: los targets son OPINIONES, no certezas. Mencionalo si el usuario lo trata como verdad absoluta.\n"
            "Cache 6h."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Símbolo de la acción."}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_profile",
        "description": (
            "Descripción del negocio: a qué se dedica, sector, industria, empleados, "
            "país, website. NO trae métricas financieras.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta '¿a qué se dedica CRWD?', '¿qué hace exactamente PLTR?'\n"
            "  - Pide contexto del negocio sin números\n\n"
            "NO LA USES cuando:\n"
            "  - El usuario pregunta financieros/valoración → otras tools del Pack\n"
            "  - Ya mencionaste sector/industria en una respuesta previa\n\n"
            "El business_summary llega capeado a 500 chars — resumilo aún más si lo citás.\n"
            "Cache 24h."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Símbolo de la acción."}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_ar_bond_metadata",
        "description": (
            "Devuelve metadata de bonos soberanos argentinos (AL/GD/AE/T2X/TZX/TX). "
            "Incluye: maturity, ley aplicable (local/NY), step-up de cupones, "
            "indexado a CER si aplica, descripción contextual.\n\n"
            "USALA cuando:\n"
            "  - El usuario pregunta por un BONO AR específico: '¿qué es AL30?', "
            "    '¿cuál es el plazo de GD30?', '¿el TX26 ajusta por inflación?'\n"
            "  - El usuario tiene bonos AR en cartera y pregunta sobre ellos\n"
            "  - get_value_scorecard / get_stock_fundamentals devolvió `available: false` "
            "    para un ticker que es bono AR (AL30, GD30, etc.) — usá ESTA como fallback\n\n"
            "NO LA USES cuando:\n"
            "  - Es una acción US o CEDEAR (no es bono) → usar las tools de equity\n"
            "  - Bonos corporativos / ON privadas (no cubiertos por esta metadata)\n\n"
            "Acepta tickers con o sin .BA (AL30.BA o AL30), con variantes D/C "
            "(AL30D = USD MEP, GD30C = USD CCL). Mismo bono base.\n\n"
            "Source: prospectos oficiales + bolsar.com + iamc.com.ar. Sin cache "
            "(es metadata estática hardcoded — no cambia salvo restructuring)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Símbolo del bono (AL30, GD30, AE38, TX26, T2X5, TZX26, etc.).",
                }
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "remember_user_fact",
        "description": (
            "Persiste un hecho que el usuario te aclara explícitamente y debe sobrevivir a esta conversación. "
            "Usala SOLO cuando el usuario te pide 'recordá esto', 'la próxima vez tené en cuenta', o cuando te "
            "corrige un dato y deja claro que debe respetarse en futuras conversaciones. NO la uses para "
            "preferencias efímeras de la sesión actual, ni para info que ya está en el snapshot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "El hecho a recordar, en bullet conciso (máx 280 chars). Ej: 'El AL30 lo tengo en IOL, no en Cocos'.",
                    "maxLength": 280,
                }
            },
            "required": ["content"],
        },
    },
]


def _execute_ai_tool(name: str, input_data: dict, uid: int) -> dict:
    """Ejecuta una tool del coach IA y devuelve el resultado como dict.

    Wrapper que cuenta uso (audit Pack A v2) y loggea. La lógica real va
    en _execute_ai_tool_inner — separadas para que el counter siempre se
    ejecute sin importar el path de retorno.
    """
    log.info("AI tool call: name=%r input_keys=%s uid=%s",
             name, list(input_data.keys()) if isinstance(input_data, dict) else 'non-dict', uid)
    try:
        result = _execute_ai_tool_inner(name, input_data, uid)
    except Exception as ex:
        # No deberíamos llegar acá (los handlers manejan sus errores), pero
        # red de seguridad para que un exception NO rompa el chat completo.
        log.error("ai_tool unhandled exception name=%s uid=%s: %s", name, uid, ex)
        return {"error": f"tool '{name}' falló: {type(ex).__name__}"}

    # Contar uso solo si el tool name es reconocido (no contar nombres
    # inventados por el LLM que no matchean ninguna rama).
    # El counter NO toma "result.available=False" como falla — sí cuenta esos
    # como uso porque consumió un tool call slot del LLM.
    if isinstance(result, dict) and "error" not in result:
        _record_tool_usage(uid, name)
    elif isinstance(result, dict) and result.get("error") and "no reconocida" not in result.get("error", ""):
        # Errores conocidos de validación SÍ cuentan como uso (gastaron call slot)
        _record_tool_usage(uid, name)
    return result


def _execute_ai_tool_inner(name: str, input_data: dict, uid: int) -> dict:
    """Impl real de _execute_ai_tool. Devuelve dict directamente."""
    if not isinstance(input_data, dict):
        return {"error": "input_data debe ser dict"}

    if name == "get_current_prices":
        raw_symbols = input_data.get("symbols", [])
        if not isinstance(raw_symbols, list):
            return {"error": "symbols debe ser lista"}
        # Cap defensivo de length (LLM puede alucinar strings largos) +
        # uppercase + strip. _SYMBOL_RE valida formato: [A-Z0-9]{1,10}(.BA)?
        symbols = [str(s).strip().upper()[:15] for s in raw_symbols][:10]
        valid = [s for s in symbols if _SYMBOL_RE.match(s)]
        if not valid:
            log.info("AI tool get_current_prices rejected — no valid symbols. Got: %r", raw_symbols[:10])
            return {"error": "No se proporcionaron símbolos válidos"}
        result = {}
        for sym in valid:
            yf_t = CRYPTO_YF.get(sym, sym)
            result[sym] = _fetch_one(yf_t)
        return {"prices": result, "note": "Precios en USD (o ARS para .BA)"}

    elif name == "get_asset_operations":
        raw_asset = input_data.get("asset", "")
        asset = str(raw_asset).strip().upper()[:15]  # cap defensivo
        if not asset:
            return {"error": "asset requerido"}
        # Mismo regex que get_current_prices — alphanumeric + opcional .BA.
        # Aunque SQL es parametrizado, rechazamos basura para no hacer query
        # innecesaria y para detectar alucinaciones del LLM.
        if not _SYMBOL_RE.match(asset):
            log.info("AI tool get_asset_operations rejected — invalid asset format: %r", raw_asset)
            return {"error": f"asset '{asset}' no tiene formato válido (alphanumeric A-Z0-9, max 10 chars, opcional .BA)"}
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
        # months debe ser int [1, 24]. El LLM puede mandar string o número
        # negativo — clampamos. Si manda algo no convertible, default 12.
        try:
            months_raw = int(input_data.get("months", 12))
        except (TypeError, ValueError):
            months_raw = 12
        months = max(1, min(months_raw, 24))
        conn = get_db()
        rows = conn.execute(
            """SELECT year, month, broker, deposits, withdrawals,
                      pnl_realized, pnl_unrealized, capital_inicio, capital_final
               FROM monthly_entries WHERE user_id=? ORDER BY year DESC, month DESC LIMIT ?""",
            (uid, months * 6),
        ).fetchall()
        conn.close()
        return {"entries": [dict(r) for r in rows]}

    elif name == "get_realized_vs_unrealized":
        # Devuelve breakdown PRECISO de realized (trades cerrados, USD absoluto)
        # vs unrealized (mark-to-market HOY de posiciones abiertas). Esto cierra
        # el bug raíz que motivó toda la Ola 2: el LLM confundía operations
        # (cerradas) con positions (abiertas). Acá no hay confusión posible —
        # el shape del resultado etiqueta cada bucket.
        #
        # Filtro opcional por asset. Si se omite → totales de cartera completa.
        # SQL parametrizado; igual aplicamos _SYMBOL_RE para rechazar basura.
        raw_asset = input_data.get("asset")
        asset_filter = None
        if raw_asset:
            asset_filter = str(raw_asset).strip().upper()[:15]
            if not _SYMBOL_RE.match(asset_filter):
                log.info("AI tool get_realized_vs_unrealized rejected — invalid asset: %r", raw_asset)
                return {"error": f"asset '{asset_filter}' no tiene formato válido"}
        conn = get_db()
        try:
            # ─── Realized: sum(pnl_usd) sobre operations CERRADAS ────────────
            # Filtramos con el MISMO criterio que ai/builders/insights.py
            # (Compra/Dividendo/Interés/CONVERSION% no son trades). Sin este
            # filtro el realized incluiría dividendos + conversiones y el
            # número diverge del que muestra Insights. Bug #2 del deep audit.
            CLOSED_FILTER = (
                "pnl_usd IS NOT NULL "
                "AND op_type NOT IN ('Compra','Dividendo','Interés','') "
                "AND op_type NOT LIKE 'CONVERSION%' "
                "AND op_type NOT LIKE 'Conversión%'"
            )
            if asset_filter:
                row = conn.execute(
                    f"SELECT COALESCE(SUM(pnl_usd),0) AS realized, COUNT(*) AS n "
                    f"FROM operations WHERE user_id=? AND asset=? AND {CLOSED_FILTER}",
                    (uid, asset_filter),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COALESCE(SUM(pnl_usd),0) AS realized, COUNT(*) AS n "
                    f"FROM operations WHERE user_id=? AND {CLOSED_FILTER}",
                    (uid,),
                ).fetchone()
            realized_usd = float(row["realized"] or 0)
            closed_count = int(row["n"] or 0)

            # ─── Unrealized: positions × precio HOY − invested (USD) ─────────
            # Reusamos la misma lógica que `compute_live_portfolio_value` /
            # `compute_broker_value_usd` para no divergir de cómo el resto de
            # la app calcula valor. tc_blue desde config del user.
            brokers = [dict(r) for r in conn.execute(
                "SELECT id, name, currency FROM brokers WHERE user_id=?", (uid,)
            ).fetchall()]
            pos_query = (
                "SELECT broker, asset, is_cash, invested, quantity, commissions, "
                "price_override FROM positions WHERE user_id=?"
            )
            pos_args: tuple = (uid,)
            if asset_filter:
                pos_query += " AND asset=?"
                pos_args = (uid, asset_filter)
            positions = [dict(r) for r in conn.execute(pos_query, pos_args).fetchall()]

            tc_blue = _user_tc_blue(conn, uid)

            unrealized_usd = 0.0
            market_value_usd = 0.0
            invested_usd = 0.0
            position_count = 0
            in_portfolio_now = False

            if brokers and positions:
                ars_brokers = {b['name'] for b in brokers if b['currency'] == 'ARS'}
                usd_brokers = {b['name'] for b in brokers if b['currency'] != 'ARS'}
                ars_symbols = list({
                    f"{p['asset']}.BA" for p in positions
                    if p['broker'] in ars_brokers and not p['is_cash']
                })
                usd_symbols = list({
                    p['asset'] for p in positions
                    if p['broker'] in usd_brokers and not p['is_cash']
                       and p['asset'] not in ('USDT', 'USD')
                })
                all_symbols = ars_symbols + usd_symbols
                try:
                    prices = fetch_prices_for_symbols(all_symbols, CRYPTO_YF) if all_symbols else {}
                except Exception as ex:
                    log.warning("get_realized_vs_unrealized: fetch_prices failed: %s", ex)
                    prices = {}

                for b in brokers:
                    bpos = [p for p in positions if p['broker'] == b['name']]
                    if not bpos:
                        continue
                    try:
                        r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue)
                        market_value_usd += r.get('value', 0) or 0
                        invested_usd += r.get('invested', 0) or 0
                    except Exception as ex:
                        log.warning("get_realized_vs_unrealized: broker %s failed: %s", b['name'], ex)
                        continue
                # Solo contamos posiciones NO-cash (consistente con el resto del bot)
                position_count = sum(1 for p in positions if not p.get('is_cash'))
                in_portfolio_now = position_count > 0
                unrealized_usd = market_value_usd - invested_usd

            combined_pnl_usd = realized_usd + unrealized_usd
            total_equity_usd = market_value_usd  # alias para coherencia con insights

            # pnl_source ayuda al LLM a no confundir "realizado" con "no realizado"
            if asset_filter:
                if realized_usd != 0 and position_count > 0:
                    pnl_source = "mixed"
                elif realized_usd != 0:
                    pnl_source = "realized_only"
                elif position_count > 0:
                    pnl_source = "unrealized_only"
                else:
                    pnl_source = "none"
            else:
                pnl_source = "portfolio_total"

            result = {
                "scope": "single_asset" if asset_filter else "portfolio_total",
                "asset": asset_filter,
                "realized_pnl_usd": round(realized_usd, 2),
                "unrealized_pnl_usd": round(unrealized_usd, 2),
                "combined_pnl_usd": round(combined_pnl_usd, 2),
                "market_value_usd": round(market_value_usd, 2),
                "invested_usd": round(invested_usd, 2),
                "total_equity_usd": round(total_equity_usd, 2),
                "closed_trades_count": closed_count,
                "open_positions_count": position_count,
                "in_portfolio_now": in_portfolio_now,
                "pnl_source": pnl_source,
                "_note": (
                    "realized_pnl_usd = suma de pnl_usd de operations cerradas "
                    "(USD absoluto, no %). unrealized_pnl_usd = market_value_usd "
                    "− invested_usd HOY (mark-to-market). combined_pnl_usd los "
                    "suma. NUNCA mezclar realized con unrealized en una sola "
                    "afirmación sin etiquetar el bucket."
                ),
            }
            return result
        finally:
            conn.close()

    elif name == "get_recent_news_for_assets":
        # Acepta hasta 5 tickers. NO hace fetch propio — reusa la cache de
        # noticias que ya viene poblada por _ensure_news_batch_parallel para
        # endpoints públicos. Si no hay news pre-pobladas, hace un fetch on-demand.
        raw_symbols = input_data.get("symbols", [])
        if not isinstance(raw_symbols, list):
            return {"error": "symbols debe ser lista"}
        symbols = [str(s).strip().upper()[:15] for s in raw_symbols][:5]
        valid = [s for s in symbols if _SYMBOL_RE.match(s)]
        if not valid:
            log.info("AI tool get_recent_news_for_assets rejected — no valid symbols. Got: %r", raw_symbols[:5])
            return {"error": "No se proporcionaron símbolos válidos"}

        conn = get_db()
        try:
            # Sembrar (o refrescar) por cada ticker — sigue el mismo patrón que
            # /api/news/portfolio: query "{TICKER} stock" (en/es según AR/US).
            specs = []
            for ticker in valid:
                is_ar = (ticker in POPULAR_TICKERS_AR_ADR) or (ticker in AR_BONDS_DATA912)
                lang = "es" if is_ar else "en"
                q = f"{ticker} {'acciones' if is_ar else 'stock'}"
                specs.append((q, lang, 'portfolio'))

            try:
                # max_wait=4s: este tool corre dentro del chat IA (timeout SDK
                # 25s, proxy Vercel 30s). Sin cap, 20 tickers × 6s timeout =
                # hasta 18s — pegaríamos el límite. 4s es suficiente para
                # 1-2 rondas con cache parcial; el resto sigue en bg.
                _ensure_news_batch_parallel(specs, NEWS_TICKER_TTL, max_wait_seconds=4)
            except Exception as ex:
                log.warning("get_recent_news_for_assets: ensure_news_batch failed: %s", ex)

            # Levantar top 3 por ticker (cap total a 15 para que no infle el contexto del LLM)
            output = {}
            for ticker in valid:
                # query_source LIKE 'TICKER %' (igual que get_portfolio_news)
                rows = conn.execute(
                    """SELECT title, summary, url, published_at, source
                       FROM news
                       WHERE category='portfolio' AND query_source LIKE ?
                       ORDER BY published_at DESC LIMIT 3""",
                    (f"{ticker} %",),
                ).fetchall()
                output[ticker] = [
                    {
                        "title": r["title"],
                        "summary": (r["summary"] or "")[:300],  # cap para LLM
                        "url": r["url"],
                        "published_at": r["published_at"],
                        "source": r["source"],
                    }
                    for r in rows
                ]
            return {
                "news_by_ticker": output,
                "_note": (
                    "Noticias de Google News RSS, máx 3 por ticker. Si un ticker "
                    "tiene array vacío, no hubo noticias recientes en cache. "
                    "Usalas para contexto causal — NO inventes catalizadores si "
                    "no aparecen acá."
                ),
            }
        finally:
            conn.close()

    elif name == "get_ar_bond_metadata":
        # Bonos AR fallback (audit crítico #2): si user pregunta por AL30/GD30,
        # NO usamos yfinance (no los tiene) — leemos del módulo metadata interno.
        # Cubre solo soberanos USD (AL/GD/AE/AL41) + CER (TX/T2X/TZX).
        raw_ticker = input_data.get("ticker", "")
        if not raw_ticker:
            return {"error": "ticker requerido"}
        from ai.ar_bonds_metadata import is_known_ar_bond, get_bond_metadata
        if not is_known_ar_bond(raw_ticker):
            return {
                "available": False,
                "reason": (
                    f"'{raw_ticker}' no está en la base de bonos AR soberanos. "
                    "Cubrimos solo soberanos USD (AL/GD/AE) y CER (TX/T2X/TZX). "
                    "ONs corporativas y bonos provinciales no están incluidos."
                ),
            }
        md = get_bond_metadata(raw_ticker)
        if md is None:
            return {"available": False, "reason": "metadata no encontrada"}
        # Detectar si vino con variante USD MEP (D) / CCL (C).
        # Fix B3 del audit: solo aplica a SOBERANO_USD. Los CER (TX/T2X/TZX)
        # son ARS denominated — NO existe variante USD MEP de un CER.
        # Si vino "TX26D" la metadata es de TX26 (CER), pero el LLM no debería
        # creer que es un bono dolarizado.
        from ai.ar_bonds_metadata import _strip_bond_suffix
        original_clean = str(raw_ticker).upper().strip().replace(".BA", "")
        base_ticker = _strip_bond_suffix(original_clean)
        variant = None
        if (original_clean != base_ticker
                and original_clean.endswith(("D", "C"))
                and md.get("kind") == "soberano_usd"):
            variant = original_clean[-1]  # "D" o "C"
        return {
            "available": True,
            "ticker": base_ticker,
            "variant": variant,  # "D" (MEP) | "C" (CCL) | None
            "kind": md.get("kind"),
            "maturity": md.get("maturity"),
            "law": md.get("law"),
            "currency_denom": md.get("currency_denom"),
            "indexed_by": md.get("indexed_by"),
            "step_up": md.get("step_up"),
            "description": md.get("description"),
            "_interpretation_hint": (
                "Datos estáticos del bono. Usalos para razonar: "
                "(1) duration aproximada por maturity vs hoy, "
                "(2) ley aplicable (local vs NY = protección legal distinta), "
                "(3) si indexed_by='CER' = cobertura inflación AR (no FX), "
                "(4) step_up=True significa que el cupón sube a lo largo del tiempo. "
                "NO podés predecir el precio futuro del bono."
            ),
        }

    # ─── Pack A v2: tools yfinance ───────────────────────────────────────
    # Las 5 tools comparten el patrón: validar ticker → fetch cached →
    # devolver payload. Cuota implícita por cache TTL granular por kind.
    elif name in (
        "get_stock_fundamentals", "get_value_scorecard", "get_earnings_history",
        "get_analyst_ratings", "get_company_profile",
    ):
        raw_ticker = input_data.get("ticker", "")
        ticker = str(raw_ticker).strip().upper()[:15]
        if not ticker:
            return {"error": "ticker requerido"}
        # Validación: el regex de Rendi acepta letras/números/.BA. Sirve
        # tanto para US (NVDA) como CEDEARs (TSLA.BA) y también cripto en
        # forma normalizada (-USD agrega -USD pero el caller lo manda sin).
        # Aceptamos ticker tipo "BTC" (será mapped a "BTC-USD" en _yf_normalize_ticker).
        if not _SYMBOL_RE.match(ticker):
            # Permitir tickers cripto con guión (BTC-USD)
            if not (ticker.endswith("-USD") and _SYMBOL_RE.match(ticker.replace("-USD", ""))):
                log.info("AI tool %s rejected invalid ticker: %r", name, raw_ticker)
                return {"error": f"ticker '{ticker}' no tiene formato válido"}

        # Mapeo tool name → (kind cache, fetcher fn)
        tool_map = {
            "get_stock_fundamentals": ("fundamentals", _yf_fundamentals_fetcher),
            "get_value_scorecard":     ("scorecard",    _yf_scorecard_fetcher),
            "get_earnings_history":    ("earnings",     _yf_earnings_fetcher),
            "get_analyst_ratings":     ("analysts",     _yf_analysts_fetcher),
            "get_company_profile":     ("profile",      _yf_profile_fetcher),
        }
        kind, fetcher = tool_map[name]
        result = _yf_fetch_cached(ticker, kind, fetcher)
        # Loggear si rechazó por motivo conocido (cripto/bono/fake) para
        # detectar abuso (LLM llamando insistentemente con tickers que no aplican).
        if not result.get("available", True):
            log.info("yf tool %s rejected ticker=%s reason=%r", name, ticker, result.get("reason", "")[:100])
        return result

    elif name == "remember_user_fact":
        # Persiste un hecho. Usa los MISMOS helpers compartidos que el POST
        # /api/ai/remember (_validate_fact_content + _atomic_insert_fact).
        # Audit #2 fix: antes había un blocker custom acá que el endpoint
        # REST no aplicaba — bypasseable. Ahora ambos paths comparten lógica.
        raw_content = input_data.get("content", "")
        try:
            content = _validate_fact_content(raw_content)
        except ValueError as ex:
            log.info("remember_user_fact rejected — %s. content=%r", ex, str(raw_content)[:80])
            return {"error": str(ex)}
        conn = get_db()
        try:
            result = _atomic_insert_fact(conn, uid, content, "ai_inferred")
            if result is None:
                return {
                    "error": f"Llegaste al máximo de {MAX_ACTIVE_FACTS} hechos activos o {MAX_TOTAL_FACTS} totales. Pedile al usuario que desactive alguno desde Config.",
                }
            try:
                _ai_cache_invalidate(uid)
            except Exception:
                pass
            log.info("remember_user_fact: uid=%d id=%d content=%r", uid, result["id"], content[:80])
            return {"ok": True, "id": result["id"], "content": content}
        finally:
            conn.close()

    log.warning("AI tool unknown: %r", name)
    return {"error": f"Tool '{name}' no reconocida"}


# ─── AI v2 — Contextual Analysis (Sprint AI v2) ─────────────────────────────
# Reemplaza el chat libre con análisis estructurado on-demand. Cada screen
# del producto tiene su packet builder y se renderiza en un drawer.
#
# Flow:
#   POST /api/ai/analyze { screen, params }
#     → ContextPacketBuilder.build(conn, uid, **params)
#     → cache.get_cached() → HIT? return
#     → llm.analyze() con prompt caching
#     → cache.set_cached() + record_analysis()
#     → return result + usage


class AIAnalyzeIn(BaseModel):
    screen: str = Field(..., max_length=64)
    params: Optional[dict] = Field(default_factory=dict)
    # Follow-up: si viene, el LLM responde la pregunta puntual usando el
    # mismo packet del topic. NO se cachea (cada pregunta es única) y SÍ
    # descuenta del cupo semanal.
    followup_question: Optional[str] = Field(default=None, max_length=300)


def _ai_cache_invalidate(uid: int) -> None:
    """Invalida TODO el cache de IA del user. Llamado desde endpoints de
    mutación (positions, operations, monthly, goals, brokers, etc.).

    Sin esto, el user agrega una operación y sigue viendo análisis viejos
    cacheados (TTL 24h). Esto es el riesgo de credibilidad más alto del
    sistema — el LLM cuesta dinero, pero un análisis desactualizado
    cuesta confianza.

    Es 'safe' — captura cualquier excepción para no romper el endpoint
    de mutación si el cache de IA falla por alguna razón inesperada.
    """
    try:
        from ai import cache as _ai_cache
        conn = get_db()
        try:
            _ai_cache.invalidate_for_user(conn, uid)
        finally:
            conn.close()
    except Exception as ex:
        log.warning("ai_cache_invalidate fallo para uid=%s: %s", uid, ex)


@app.post("/api/ai/analyze")
def ai_analyze(data: AIAnalyzeIn, uid: int = Depends(get_current_user)):
    """Análisis contextual estructurado de una pantalla o sub-componente.

    El `screen` usa notación con puntos para sub-topics:
      dashboard                  — análisis general del Dashboard
      dashboard.composition      — solo la composición del portfolio
      dashboard.evolution        — solo la curva de evolución
      dashboard.top_holdings     — solo el top de holdings

    Body: { screen: str, params: {...} }
    Returns: { result, cached: bool, usage }

    Quota: solo descuenta del cupo Free cuando hay cache MISS (el LLM
    realmente corrió). Cache hits son gratis — sino abrir el drawer 3
    veces seguidas quemaría los 5 análisis del día.
    """
    from ai import llm, cache, quota
    from ai.schema import AnalysisResult
    from ai.registry import get_topic, list_topics

    if not llm.is_configured():
        raise HTTPException(503, "AI no configurada (falta ANTHROPIC_API_KEY)")

    screen = data.screen.strip().lower()
    params = data.params or {}
    followup_question = (data.followup_question or "").strip() or None

    # Dispatch via registry (topic → builder + prompt)
    topic = get_topic(screen)
    if not topic:
        raise HTTPException(
            400,
            f"Topic '{screen}' no soportado. Disponibles: {list_topics()}.",
        )
    build_packet, render_prompt = topic

    conn = get_db()
    try:
        # Resolver tier del user al inicio — afecta cache key, prompt y mensaje 429.
        tier = quota.get_tier(conn, uid)

        # Follow-ups son exclusivos Pro — el diferencial real del paywall.
        # Free Y Plus que intentan follow-up reciben 403 con upgrade payload
        # (el frontend lo surface via UpgradePromoCard). Audit #4 fix G:
        # antes solo bloqueaba Free, Plus tenía un agujero silencioso que
        # diluía el incentivo a pasarse a Pro.
        if followup_question and tier in ("free", "plus"):
            raise HTTPException(403, {
                "error": (
                    "Los follow-ups son exclusivos de Rendi Pro. "
                    "Profundizá cualquier análisis con preguntas libres."
                ),
                "usage": quota.get_current_usage(conn, uid),
                "upgrade": {
                    "available": True,
                    "current_tier": tier,
                    "target_tier": "pro",
                    "feature": "follow_ups",
                    "benefits": [
                        "10× más análisis IA (60/sem vs 6/sem)",
                        "Respuestas con causalidad y comparaciones",
                        "Follow-ups: profundizá con preguntas libres",
                        "AI Hub: exploración libre sobre tu portfolio (próximamente)",
                    ],
                },
            })

        # Build packet PRIMERO (es barato y determinístico) para ver si hay
        # cache hit antes de tocar el cupo.
        try:
            packet = build_packet(conn, uid, **params)
        except Exception as ex:
            log.exception(f"AI builder fallo (uid={uid}, screen={screen})")
            raise HTTPException(500, f"Error construyendo packet: {type(ex).__name__}")

        # Enriquecer el packet con el perfil del inversor (test de 7 preguntas).
        # Lo metemos en el packet — NO en el system prompt — para que el
        # cache key incluya el perfil (cambios al test invalidan el cache de
        # análisis del user, que es lo correcto). El system prompt ya tiene
        # reglas sobre cómo usar el bloque `investor_profile`.
        prof_row = conn.execute(
            "SELECT investor_profile FROM users WHERE id=?", (uid,)
        ).fetchone()
        if prof_row and prof_row["investor_profile"]:
            try:
                profile_dict = json.loads(prof_row["investor_profile"])
                if isinstance(profile_dict, dict) and profile_dict:
                    packet["investor_profile"] = profile_dict
            except (ValueError, TypeError):
                pass  # JSON corrupto — seguimos sin perfil

        # Cache HIT? → solo para análisis principales. Follow-ups NUNCA se
        # cachean (cada pregunta es única).
        if followup_question is None:
            cached = cache.get_cached(conn, uid, screen, packet, tier=tier)
            if cached:
                return {
                    "result": cached,
                    "cached": True,
                    "tier": tier,
                    "followup": False,
                    "usage": quota.get_current_usage(conn, uid),
                }

        # Cache MISS o follow-up → chequeamos cupo (la llamada al LLM cuesta)
        allowed, usage_now = quota.can_analyze(conn, uid)
        if not allowed:
            # Mensaje 429 dinámico por tier — antes hardcodeaba "plan Free"
            # aunque el user fuera Plus (mismo cap 6) y daba confusión.
            tier_label = {"free": "Free", "plus": "Plus", "pro": "Pro", "admin": "Admin"}.get(tier, "Free")
            limit_n = usage_now.get("analyses_limit", 6)
            upgrade_available = tier in ("free", "plus")
            error_msg = (
                f"Llegaste al límite del plan {tier_label} ({limit_n} análisis en los "
                "últimos 7 días). Tu próximo análisis se libera al "
                "expirar el más antiguo."
            )
            if upgrade_available:
                error_msg += " Para 10× más análisis con respuestas profundas, pasate a Rendi Pro."
            raise HTTPException(429, {
                "error": error_msg,
                "usage": usage_now,
                "upgrade": {
                    "available": upgrade_available,
                    "current_tier": tier,
                    "target_tier": "pro",
                    "resets_on": usage_now.get("resets_on"),
                    "benefits": [
                        "10× más análisis IA (60/sem vs 6/sem)",
                        "Respuestas con causalidad y comparaciones",
                        "Chat libre con el Coach IA (40 consultas/sem)",
                        "Follow-ups: profundizá con preguntas libres",
                    ],
                },
            })

        # Llamada al LLM — prompt resuelto según tier (Free=descriptivo,
        # Pro/Admin=research note). Si hay follow-up, pasamos la pregunta
        # al LLM para que responda específicamente sobre el packet.
        system_prompt = render_prompt(tier=tier)
        try:
            llm_result = llm.analyze(
                system_prompt=system_prompt,
                packet=packet,
                output_model=AnalysisResult,
                model=llm.MODEL_HAIKU,
                followup_question=followup_question,
            )
        except Exception as ex:
            log.warning(f"AI analyze fallo (uid={uid}, screen={screen}, tier={tier}): {ex}")
            raise HTTPException(502, f"AI procesamiento fallo: {type(ex).__name__}")

        if llm_result is None:
            raise HTTPException(503, "AI no disponible momentáneamente")

        result_dict = llm_result.output.model_dump()

        # Solo cacheamos los análisis principales — no los follow-ups.
        if followup_question is None:
            cache.set_cached(
                conn,
                user_id=uid,
                screen=screen,
                packet=packet,
                result=result_dict,
                model=llm_result.model,
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                cache_read_tokens=llm_result.cache_read_input_tokens,
                cache_create_tokens=llm_result.cache_creation_input_tokens,
                cost_usd_cents=llm_result.cost_usd_cents,
                tier=tier,
            )
        quota.record_analysis(conn, uid, cost_usd_cents=llm_result.cost_usd_cents)

        return {
            "result": result_dict,
            "cached": False,
            "tier": tier,
            "followup": followup_question is not None,
            "usage": quota.get_current_usage(conn, uid),
        }
    finally:
        conn.close()


@app.get("/api/ai/topics")
def ai_topics():
    """Lista los topics disponibles para /api/ai/analyze. Endpoint público
    sin auth — útil para que el frontend descubra topics sin hardcodear."""
    from ai.registry import list_topics
    return {"topics": list_topics()}


class PlanEventIn(BaseModel):
    """Payload del frontend para POST /api/plan/track."""
    event: str = Field(..., min_length=1, max_length=64)
    feature_id: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default=None, max_length=64)
    props: Optional[dict] = None


# Whitelist de event names que el frontend puede registrar. Cualquier otro
# event_name se descarta (defensa contra spam / abuse).
_ALLOWED_PLAN_EVENTS = {
    "feature_blocked_clicked",
    "upgrade_modal_cta_clicked",
    "plan_hero_upgrade_clicked",
    "upgrade_promo_clicked",
}


@app.post("/api/plan/track", status_code=204)
def plan_track(data: PlanEventIn, uid: int = Depends(get_current_user)):
    """Registra un evento de paywall para analytics de conversión.

    Whitelist de event_names para evitar spam. Solo eventos clave del flow
    de upgrade. Returns 204 (no body) — fire-and-forget desde el frontend.
    """
    if data.event not in _ALLOWED_PLAN_EVENTS:
        # No es error fatal — descartamos silenciosamente para que el client
        # no necesite manejar el rechazo (es telemetría, no acción crítica).
        return
    from ai import quota
    conn = get_db()
    try:
        tier = quota.get_tier(conn, uid)
        with conn:
            conn.execute(
                """INSERT INTO plan_events
                       (user_id, tier, event_name, feature_id, source, props_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    uid, tier, data.event,
                    data.feature_id,
                    data.source,
                    json.dumps(data.props or {}, ensure_ascii=False),
                ),
            )
    finally:
        conn.close()


@app.get("/api/plan/features")
def plan_features(uid: int = Depends(get_current_user)):
    """Feature flags + límites del tier del user para el frontend.

    El frontend usa esta info en `usePlanFeatures()` para gatear UI:
    blurear secciones bloqueadas, mostrar contadores, modal de upgrade.

    Shape (estable):
      tier: 'free' | 'pro' | 'admin'
      limits.brokers_max / brokers_current / brokers_can_create / brokers_grandfather
      limits.insights_diagnostic_visible
      limits.behavioral_tags_visible
      access.<feature_id>: bool
    """
    from ai import plan
    conn = get_db()
    try:
        return plan.get_plan_features(conn, uid)
    finally:
        conn.close()


# ─── Billing / Mercado Pago ──────────────────────────────────────────────────
# Suscripciones recurring vía MP preapproval API. Flow:
#  1. User clickea "Suscribirme" → POST /api/billing/subscribe (este endpoint)
#  2. Backend crea preapproval en MP, devuelve init_point URL
#  3. Frontend redirige al user a init_point (checkout de MP)
#  4. User paga con tarjeta → MP llama nuestro webhook (paso 5)
#  5. POST /api/billing/webhook → validamos signature + actualizamos tier='pro'
#  6. MP repite cobro automáticamente cada mes/año + llama webhook cada vez

class SubscribeIn(BaseModel):
    plan: str = Field("pro", pattern="^(plus|pro)$")  # default pro por back-compat
    period: str = Field(..., pattern="^(monthly|annual)$")


@app.post("/api/billing/subscribe")
def billing_subscribe(data: SubscribeIn, request: Request, uid: int = Depends(get_current_user)):
    """Crea un payment link en Rebill para que el user pague la suscripción.

    Devuelve `init_point` (URL del checkout Rebill). El frontend redirige al
    user ahí. Tras pagar, Rebill llama nuestro webhook que activa el tier.

    Semántica:
      • User Free (sin sub authorized): crea sub nueva → checkout.
      • User con sub `authorized` para CUALQUIER plan: 409. Tiene que usar
        /api/billing/change-plan para cambiar (eso convierte el crédito).
      • User en modo crédito (sin sub authorized, con credit_active_until
        en el futuro): puede crear sub nueva — la nueva se va a sumar a
        su crédito existente cuando Rebill cobre.

    SECURITY: rate limit 5/600s por user para prevenir abuse de la API de
    Rebill (cada call crea un payment-link que cuenta contra cuota upstream).

    NOTA: migramos de Mercado Pago a Rebill (commit X). MP queda muerto pero
    el código está en mercadopago.py por si hay que revertir.
    """
    # Rate limit por user — máximo 5 intentos de subscribe en 10 min.
    # Evita que un atacante cree spam de payment-links en Rebill.
    _check_rate_limit(request, max_calls=5, window_seconds=600, suffix=f"subscribe:{uid}")

    from billing import rebill
    conn = get_db()
    try:
        # 1. Obtener email del user
        user_row = conn.execute(
            "SELECT email, tier, is_admin FROM users WHERE id = ?", (uid,)
        ).fetchone()
        if not user_row:
            raise HTTPException(404, "User not found")
        user_email = user_row["email"]

        # 2. Check si ya tiene suscripción activa. Si la tiene → 409 con hint
        # de usar change-plan.
        existing = conn.execute(
            """SELECT id, mp_subscription_id, status FROM subscriptions
               WHERE user_id = ? AND status = 'authorized'
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if existing:
            raise HTTPException(409, {
                "error": "Ya tenés una suscripción activa.",
                "subscription_id": existing["mp_subscription_id"],
                "hint": "use_change_plan",
            })

        plan_id = data.plan if data.plan in ("plus", "pro") else "pro"
        period = data.period

        # 3. Crear payment link en Rebill
        try:
            rb_response = rebill.create_payment_link(
                user_id=uid,
                user_email=user_email,
                plan=plan_id,
                period=period,
            )
        except Exception as ex:
            # Log completo del lado del backend (Railway logs).
            log.error("Rebill create_payment_link failed for uid=%s plan=%s period=%s: %s",
                      uid, plan_id, period, ex, exc_info=True)
            # Surface el mensaje real al frontend (no solo el type). Si el
            # RuntimeError dice "REBILL_PLAN_ID_PLUS_MONTHLY no configurada",
            # el user lo ve y sabe qué env var falta. Truncamos a 300 chars
            # para no leak respuestas enormes de Rebill API si fuera el caso.
            err_msg = str(ex)[:300] if str(ex) else type(ex).__name__
            raise HTTPException(
                502,
                detail={
                    "error": f"Error al crear suscripción en Rebill: {err_msg}",
                    "error_type": type(ex).__name__,
                },
            )

        # 4. Guardar en DB. Reusamos mp_subscription_id field para guardar el
        # payment link ID inicialmente; cuando llegue el webhook con la
        # subscription real, lo updateamos al subscription_id.
        ext_ref = f"rendi-{uid}-{plan_id}-{period}"
        link_url = rb_response.get("url") or ""
        link_id = rb_response.get("id") or ""

        # SECURITY: validar que el link_url es del dominio de Rebill antes de
        # devolverlo al frontend. Si la respuesta de Rebill fuera comprometida
        # en transit o vino tampered, podría apuntar a un phishing site y el
        # frontend redirigiría al user ahí. Allowlist explícito de dominios.
        _ALLOWED_PAYMENT_HOSTS = (
            "https://app.rebill.com/",
            "https://checkout.rebill.com/",
            "https://pay.rebill.com/",
            "https://app.rebill.dev/",  # sandbox
            "https://checkout.rebill.dev/",
        )
        if link_url and not link_url.startswith(_ALLOWED_PAYMENT_HOSTS):
            log.error("Rebill devolvió URL inesperada (no Rebill domain): %s", link_url[:80])
            raise HTTPException(502, {"error": "payment_url_invalid", "detail": "Respuesta inválida del procesador de pagos"})

        with conn:
            conn.execute(
                """INSERT INTO subscriptions
                       (user_id, mp_subscription_id, external_reference, period,
                        status, amount_ars, init_point, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', 0, ?, datetime('now'), datetime('now'))""",
                (uid, link_id, ext_ref, period, link_url),
            )

        return {
            "init_point": link_url,
            "subscription_id": link_id,
            "reused": False,
        }
    finally:
        conn.close()


# ─── Plan change (upgrade / downgrade con crédito proporcional) ─────────────

class ChangePlanIn(BaseModel):
    plan: str = Field(..., pattern="^(plus|pro)$")
    period: str = Field(..., pattern="^(monthly|annual)$")


@app.post("/api/billing/change-plan")
def billing_change_plan(
    data: ChangePlanIn,
    request: Request,
    uid: int = Depends(get_current_user),
):
    """Cambia el plan del user manteniendo el crédito remanente.

    Flujo:
      1. Verifica que el user tenga crédito activo (active_until > NOW).
      2. Cancela la suscripción Rebill actual (no más cobros automáticos).
      3. Convierte el crédito remanente al daily_rate del plan nuevo →
         credit_active_until se reajusta (más días si el nuevo es más
         barato, menos si es más caro).
      4. Actualiza user.tier y anchor.

    Resultado: el user accede al tier nuevo SIN pagar de nuevo. Cuando
    se le acabe el crédito, el cron lifecycle lo baja a Free y se le
    pide re-suscribirse.

    Errores:
      • 400 si quiere cambiar al mismo plan (no-op).
      • 404 si no tiene crédito activo (debe usar /subscribe en su lugar).
    """
    # Rate limit por user — 3 intentos en 10 min. Cambio de plan es costoso
    # (cancelación + recálculo de crédito), no debe spamearse.
    _check_rate_limit(request, max_calls=3, window_seconds=600, suffix=f"change_plan:{uid}")

    from billing import rebill
    from billing import credits as billing_credits

    conn = get_db()
    try:
        # 1. Validar que tenga crédito activo
        state = billing_credits.get_credit_state(conn, uid)
        if not state["is_active"]:
            raise HTTPException(404, {
                "error": "No tenés crédito activo para convertir.",
                "hint": "use_subscribe",
            })
        if state["anchor_plan"] == data.plan and state["anchor_period"] == data.period:
            raise HTTPException(400, {
                "error": "Ya estás en este plan.",
            })

        # 2. Cancelar la subscription Rebill actual (si hay)
        # No falla si no existe — el user puede estar ya en modo crédito puro.
        existing_sub = conn.execute(
            """SELECT id, mp_subscription_id FROM subscriptions
               WHERE user_id = ? AND status = 'authorized'
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        cancelled_sub_id = None
        if existing_sub and existing_sub["mp_subscription_id"]:
            cancelled_sub_id = existing_sub["mp_subscription_id"]
            try:
                rebill.cancel_subscription(cancelled_sub_id)
            except Exception as ex:
                # Si Rebill rechaza el cancel (ej. ya cancelada), seguimos.
                # El crédito local es nuestra fuente de verdad.
                log.warning(
                    "Rebill cancel_subscription falló para %s (uid %s): %s. Sigo con el cambio local.",
                    cancelled_sub_id, uid, ex,
                )
            with conn:
                # status='superseded' diferencia este caso (cambio de plan) de
                # un cancel manual del user (que va a status='cancelled').
                # El cron lifecycle trata ambos igual para downgrade, pero la
                # UI muestra mensajes distintos: "en período de crédito" vs
                # "cancelado, vence X".
                conn.execute(
                    """UPDATE subscriptions
                       SET status = 'superseded',
                           cancelled_at = datetime('now'),
                           updated_at = datetime('now')
                       WHERE id = ?""",
                    (existing_sub["id"],),
                )

        # 3. Convertir crédito al plan nuevo
        try:
            result = billing_credits.convert_plan(
                conn,
                user_id=uid,
                new_plan=data.plan,
                new_period=data.period,
                cancelled_subscription_id=cancelled_sub_id,
                note=f"User-initiated plan change from /api/billing/change-plan",
            )
        except Exception as ex:
            log.exception("convert_plan falló para user %s: %s", uid, ex)
            raise HTTPException(500, f"Error al convertir crédito: {type(ex).__name__}")

        track_event = "subscription_plan_changed"  # también lo loggeamos del lado server
        log.info(
            "%s user=%s from=%s/%s to=%s/%s new_days=%.2f",
            track_event, uid, state["anchor_plan"], state["anchor_period"],
            data.plan, data.period, result["days_remaining"],
        )

        return {
            "status":         "ok",
            "new_plan":       data.plan,
            "new_period":     data.period,
            "active_until":   result["active_until"],
            "days_remaining": result["days_remaining"],
            "cancelled_subscription_id": cancelled_sub_id,
        }
    finally:
        conn.close()


@app.get("/api/billing/preview-change-plan")
def billing_preview_change_plan(
    plan: str,
    period: str,
    uid: int = Depends(get_current_user),
):
    """Devuelve lo que pasaría si el user cambia a (plan, period) sin
    ejecutarlo. Usado por el frontend para confirmar el cambio mostrando
    "Vas a tener X días de Pro con tu crédito actual"."""
    from billing import credits as billing_credits
    if plan not in ("plus", "pro"):
        raise HTTPException(400, "plan inválido")
    if period not in ("monthly", "annual"):
        raise HTTPException(400, "period inválido")
    conn = get_db()
    try:
        return billing_credits.preview_plan_change(conn, uid, plan, period)
    finally:
        conn.close()


# ─── Rebill webhook ─────────────────────────────────────────────────────────

@app.post("/api/billing/rebill-webhook")
async def rebill_webhook(request: Request):
    """Recibe eventos de Rebill server-to-server.

    Eventos esperados (los nombres exactos pueden variar según la doc final
    — handler defensivo con múltiples paths):
      • subscription.activated / subscription.created → activar tier
      • subscription.cancelled / subscription.canceled → marcar como cancelada
      • payment.succeeded / subscription.renewed → registrar pago recurring
      • payment.failed → flag (no cambia tier inmediatamente)

    Matching del user: `metadata.rendi_user_id` (lo seteamos en
    create_payment_link). Si no llega, registramos warning y devolvemos 200
    para que Rebill no haga retry infinito.

    SECURITY: validar signature con REBILL_WEBHOOK_SECRET. En dev sin secret,
    pasamos con warning.
    """
    from billing import rebill
    raw = await request.body()
    sig = request.headers.get("x-rebill-signature") or request.headers.get("rebill-signature") or ""
    # Log de headers (debug — sacar después de confirmar el shape)
    debug_headers = {k: v for k, v in request.headers.items() if k.lower().startswith(("x-", "rebill", "webhook"))}

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        log.warning("Rebill webhook with non-JSON body. Raw: %r", raw[:500])
        return Response(status_code=400)

    event_type = rebill.extract_event_name(payload)
    metadata = rebill.extract_metadata(payload)
    rendi_user_id = metadata.get("rendi_user_id")

    log.info(
        "Rebill webhook: event=%r rendi_user_id=%r sig_present=%s headers=%s",
        event_type, rendi_user_id, bool(sig), debug_headers,
    )
    log.info("Rebill payload keys: %s", list(payload.keys()))
    log.info("Rebill payload (truncated): %s", json.dumps(payload, default=str)[:1500])

    # Validar signature
    sig_valid = rebill.verify_webhook_signature(raw, sig)
    if not sig_valid and rebill._webhook_secret():
        log.warning("Rebill webhook with INVALID signature, rejecting")
        return Response(status_code=401)

    conn = get_db()
    try:
        # Audit log — siempre guardamos el evento (replay/debug)
        with conn:
            conn.execute(
                """INSERT INTO billing_events
                       (mp_event_id, mp_event_type, mp_data_id, signature_valid,
                        processed, raw_payload, created_at)
                   VALUES (?, ?, ?, ?, 0, ?, datetime('now'))""",
                (
                    str(payload.get("id", "")),
                    f"rebill:{event_type}",
                    str(rendi_user_id or ""),
                    1 if sig_valid else 0,
                    json.dumps(payload),
                ),
            )

        if not rendi_user_id:
            log.warning("Rebill webhook sin rendi_user_id en metadata, skipping")
            return Response(status_code=200)

        try:
            uid = int(rendi_user_id)
        except (ValueError, TypeError):
            log.warning("Rebill rendi_user_id no parseable: %r", rendi_user_id)
            return Response(status_code=200)

        sub_id = rebill.extract_subscription_id(payload)

        # Routing por evento — nombres exactos de Rebill API v3:
        #   subscription.created    → activar (primer pago aprobado)
        #   subscription.updated    → cambio de status (active/paused/cancelled/...)
        #   payment.created         → cobro nuevo (recurring renewal)
        #   payment.updated         → cambio de status del pago
        #   subscription.renewal_soon → notificación pre-cobro (no actuamos)
        evt = event_type.lower()
        if evt == "subscription.created":
            _rebill_activate(conn, uid, metadata, sub_id, payload)
        elif evt == "subscription.updated":
            _rebill_subscription_status_change(conn, uid, metadata, sub_id, payload)
        elif evt == "payment.created" or evt == "payment.updated":
            _rebill_record_payment(conn, uid, sub_id, payload)
        elif evt == "subscription.renewal_soon":
            log.info("Rebill renewal_soon para user %s (sub %s) — no actuamos", uid, sub_id)
        else:
            log.info("Rebill evento sin handler específico: %s", event_type)

        with conn:
            conn.execute(
                "UPDATE billing_events SET processed = 1 WHERE raw_payload = ?",
                (json.dumps(payload),),
            )
        return Response(status_code=200)
    except Exception as ex:
        log.exception("Rebill webhook processing error: %s", ex)
        return Response(status_code=200)  # 200 para evitar retry agresivo
    finally:
        conn.close()


def _rebill_activate(conn, uid: int, metadata: dict, sub_id: str, payload: dict):
    """Marca al user como Plus/Pro, actualiza/crea la subscription row, y
    otorga crédito por el período cobrado.

    El crédito (credit_active_until + anchor) es lo que valida el acceso
    del user al tier — el daily cron baja a Free cuando vence.
    """
    from billing import credits as billing_credits
    plan = metadata.get("rendi_plan") or "pro"
    period = metadata.get("rendi_period") or "monthly"
    target_tier = plan if plan in ("plus", "pro") else "pro"

    # Monto cobrado: si Rebill lo manda, usamos eso; si no, usamos el catálogo.
    amount_usd = None
    data_obj = payload.get("data") or {}
    payment_obj = data_obj.get("payment") or {}
    for c in (payment_obj.get("amount"), data_obj.get("amount"), payload.get("amount")):
        try:
            if c is not None:
                amount_usd = float(c)
                break
        except (TypeError, ValueError):
            continue

    # payment_id para idempotency del ledger — el subscription.created suele
    # venir con un payment_id (el primer cobro). Si no está, queda None y
    # el ledger no aplica el dedup (la sub.created solo viene una vez).
    payment_id = ""
    for c in (
        payment_obj.get("id"),
        data_obj.get("payment_id"),
        payload.get("payment_id"),
    ):
        if c:
            payment_id = str(c)
            break

    with conn:
        conn.execute("UPDATE users SET tier = ? WHERE id = ?", (target_tier, uid))

        # Buscar la pending subscription que creó /api/billing/subscribe.
        # Si existe, la actualizamos con el subscription_id real. Si no,
        # creamos una nueva (race condition: webhook llegó antes que insert).
        existing = conn.execute(
            """SELECT id FROM subscriptions
               WHERE user_id = ? AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE subscriptions
                   SET status = 'authorized',
                       mp_subscription_id = ?,
                       amount_usd = COALESCE(?, amount_usd),
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (sub_id or "", amount_usd, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO subscriptions
                       (user_id, mp_subscription_id, external_reference, period,
                        status, amount_ars, amount_usd, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'authorized', 0, ?, datetime('now'), datetime('now'))""",
                (uid, sub_id or "", f"rendi-{uid}-{plan}-{period}", period, amount_usd),
            )

    # Conceder crédito por el período cobrado (fuera del with por simplicidad —
    # credits.grant_payment_credit maneja su propia tx).
    try:
        billing_credits.grant_payment_credit(
            conn,
            user_id=uid,
            plan=plan,
            period=period,
            amount_usd=amount_usd,  # None → usa catálogo
            subscription_id=sub_id or None,
            payment_id=payment_id or None,  # idempotency key
        )
    except Exception as ex:
        # No fallar el activate si el ledger falla — loggear y seguir.
        # El user igual queda con tier asignado; el cron va a detectar
        # ausencia de credit_active_until pero ya está autorizado en Rebill.
        log.error("credits.grant_payment_credit falló para user %s: %s", uid, ex)

    log.info("Rebill: user %s activated as %s (sub=%s, amount=%s)",
             uid, target_tier, sub_id, amount_usd)


def _rebill_subscription_status_change(conn, uid: int, metadata: dict, sub_id: str, payload: dict):
    """Maneja subscription.updated routing por el nuevo status.

    Status lifecycle de Rebill:
      active     → activar/mantener tier
      paused     → tier sigue (hasta fin del período cobrado)
      retrying   → tier sigue (Rebill reintenta el cobro)
      cancelled  → marcar cancelled (tier sigue hasta cron lifecycle)
      defaulted  → marcar como cancelled forzado (user fue puesto en default)
      finished   → todos los ciclos completados (raro para plans sin repetitions)
    """
    data = payload.get("data") or payload.get("subscription") or {}
    new_status = (data.get("status") or "").lower()
    status_detail = data.get("statusDetail") or ""
    log.info("Rebill sub.updated user=%s sub=%s status=%s detail=%s",
             uid, sub_id, new_status, status_detail)

    if new_status == "active":
        # Re-activación (p.ej. user resolvió un retrying con card update)
        _rebill_activate(conn, uid, metadata, sub_id, payload)
    elif new_status in ("cancelled", "defaulted", "finished"):
        _rebill_cancel(conn, uid, sub_id, payload)
    elif new_status in ("paused", "retrying"):
        # Tier sigue activo durante paused/retrying — solo loggeamos
        with conn:
            if sub_id:
                conn.execute(
                    """UPDATE subscriptions
                       SET status = ?, updated_at = datetime('now')
                       WHERE user_id = ? AND mp_subscription_id = ?""",
                    (new_status, uid, sub_id),
                )
    else:
        log.warning("Rebill sub.updated status desconocido: %r", new_status)


def _rebill_cancel(conn, uid: int, sub_id: str, payload: dict):
    """Marca la subscription como cancelled. No revierte tier inmediatamente
    (el user mantiene Plus/Pro hasta fin del período cobrado).

    NO pisa subs que ya están en status='superseded' — esas fueron canceladas
    por un /api/billing/change-plan y la intención semántica (el user cambió
    de plan, no canceló) tiene que preservarse para que la UI muestre el
    mensaje correcto.
    """
    with conn:
        if sub_id:
            conn.execute(
                """UPDATE subscriptions
                   SET status = 'cancelled', cancelled_at = datetime('now'),
                       updated_at = datetime('now')
                   WHERE user_id = ? AND mp_subscription_id = ?
                     AND status NOT IN ('superseded')""",
                (uid, sub_id),
            )
        else:
            # Fallback: cancelar la authorized más reciente del user
            conn.execute(
                """UPDATE subscriptions
                   SET status = 'cancelled', cancelled_at = datetime('now'),
                       updated_at = datetime('now')
                   WHERE user_id = ? AND status = 'authorized'""",
                (uid,),
            )
    log.info("Rebill: subscription %s cancelled for user %s", sub_id, uid)


def _rebill_record_payment(conn, uid: int, sub_id: str, payload: dict):
    """Registra un cobro recurring exitoso (subscription renewal).

    Además de registrar el payment_id, extiende la ventana de crédito del
    user — Rebill cobró un nuevo período, así que el user obtiene los días
    correspondientes al plan/period que tiene anchored.
    """
    from billing import credits as billing_credits
    payment_id = ""
    data_obj = payload.get("data") or {}
    for c in (
        payload.get("payment_id"),
        data_obj.get("payment_id"),
        (data_obj.get("payment") or {}).get("id"),
    ):
        if c:
            payment_id = str(c)
            break

    # Solo procesamos `payment.created` con status approved (o equivalente).
    # Rebill puede mandar payment.updated con status=failed/pending — en esos
    # casos no extendemos crédito.
    payment_status = ""
    for c in (
        (data_obj.get("payment") or {}).get("status"),
        data_obj.get("status"),
        payload.get("status"),
    ):
        if c:
            payment_status = str(c).lower()
            break
    is_successful = payment_status in ("approved", "succeeded", "paid", "completed", "")

    # Monto cobrado
    amount_usd = None
    payment_obj = data_obj.get("payment") or {}
    for c in (payment_obj.get("amount"), data_obj.get("amount"), payload.get("amount")):
        try:
            if c is not None:
                amount_usd = float(c)
                break
        except (TypeError, ValueError):
            continue

    with conn:
        if sub_id:
            conn.execute(
                """UPDATE subscriptions
                   SET last_payment_id = ?,
                       amount_usd = COALESCE(?, amount_usd),
                       updated_at = datetime('now')
                   WHERE user_id = ? AND mp_subscription_id = ?""",
                (payment_id, amount_usd, uid, sub_id),
            )

    if is_successful:
        # Necesitamos plan/period — los recuperamos del anchor del user o de
        # la subscription. El payload de payment.created rara vez incluye
        # metadata, así que el anchor es la fuente más confiable.
        anchor_row = conn.execute(
            """SELECT credit_anchor_plan, credit_anchor_period FROM users WHERE id = ?""",
            (uid,),
        ).fetchone()
        anchor_plan = (anchor_row["credit_anchor_plan"] if anchor_row else None)
        anchor_period = (anchor_row["credit_anchor_period"] if anchor_row else None)

        # Fallback: leer de la subscription row (period siempre se guarda al crear)
        if not anchor_plan or not anchor_period:
            sub_row = conn.execute(
                """SELECT period, external_reference FROM subscriptions
                   WHERE user_id = ? AND mp_subscription_id = ?""",
                (uid, sub_id or ""),
            ).fetchone()
            if sub_row:
                anchor_period = anchor_period or sub_row["period"]
                # external_reference es 'rendi-{uid}-{plan}-{period}'
                ext = sub_row["external_reference"] or ""
                parts = ext.split("-")
                if not anchor_plan and len(parts) >= 4:
                    anchor_plan = parts[2] if parts[2] in ("plus", "pro") else None

        if anchor_plan and anchor_period:
            try:
                billing_credits.grant_payment_credit(
                    conn,
                    user_id=uid,
                    plan=anchor_plan,
                    period=anchor_period,
                    amount_usd=amount_usd,
                    subscription_id=sub_id or None,
                    payment_id=payment_id or None,  # idempotency key
                    note=f"Rebill renewal payment {payment_id}",
                )
            except Exception as ex:
                log.error("credits.grant_payment_credit (renewal) falló para user %s: %s", uid, ex)
        else:
            log.warning(
                "Rebill payment para user %s sin anchor_plan/period — no se otorga crédito (sub=%s)",
                uid, sub_id,
            )

    log.info("Rebill: payment %s recorded for sub %s (user %s, status=%s, amount=%s)",
             payment_id, sub_id, uid, payment_status, amount_usd)


@app.post("/api/billing/cancel")
def billing_cancel(request: Request, uid: int = Depends(get_current_user)):
    """Cancela la suscripción Pro del user.

    NOTA: NO devolvemos el dinero del período actual. El user mantiene
    Pro hasta `current_period_end` (la fecha en que MP iba a cobrar
    el próximo). Después de esa fecha, el webhook NO recibe más eventos
    de pago, y un cron periódico (o el próximo /auth/me) detectaría que
    pasó current_period_end y bajaría a tier='free'.

    SECURITY: rate limit 5/600s por user.
    """
    _check_rate_limit(request, max_calls=5, window_seconds=600, suffix=f"cancel:{uid}")

    from billing import rebill
    conn = get_db()
    try:
        sub = conn.execute(
            """SELECT mp_subscription_id, status FROM subscriptions
               WHERE user_id = ? AND status = 'authorized'
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if not sub:
            # Caso credit-only: el user no tiene sub Rebill activa porque ya
            # cambió de plan y está viviendo del crédito. No hay nada que
            # cancelar en Rebill — el crédito vence solo. Devolvemos un
            # mensaje explicativo para que el frontend muestre el estado real.
            from billing import credits as billing_credits
            cstate = billing_credits.get_credit_state(conn, uid)
            if cstate["is_active"]:
                raise HTTPException(409, {
                    "error": "No tenés una sub Rebill activa para cancelar; estás en modo crédito.",
                    "hint": "credit_only_no_cancel_needed",
                    "credit_active_until": cstate["active_until"],
                    "days_remaining": cstate["days_remaining"],
                })
            raise HTTPException(404, "No tenés suscripción activa para cancelar.")

        # Cancelar en Rebill (mp_subscription_id ahora guarda el ID de Rebill
        # — field reusado durante la migración para evitar schema change).
        try:
            cancel_response = rebill.cancel_subscription(sub["mp_subscription_id"])
        except Exception as ex:
            log.error("Rebill cancel failed for uid=%s: %s", uid, ex)
            raise HTTPException(502, f"Error al cancelar en Rebill: {type(ex).__name__}")

        # Rebill devuelve el subscription object con nextChargeDate — esa es la
        # fecha en que el user pierde acceso al tier (fin del período cobrado).
        period_end = cancel_response.get("nextChargeDate") if isinstance(cancel_response, dict) else None

        with conn:
            conn.execute(
                """UPDATE subscriptions
                   SET status = 'cancelled', cancelled_at = datetime('now'),
                       current_period_end = COALESCE(?, current_period_end),
                       updated_at = datetime('now')
                   WHERE mp_subscription_id = ?""",
                (period_end, sub["mp_subscription_id"]),
            )

        # Email de confirmación de cancelación (idempotente)
        _maybe_send_cancellation_email(conn, sub["mp_subscription_id"], uid)

        return {"status": "cancelled", "subscription_id": sub["mp_subscription_id"]}
    finally:
        conn.close()


@app.post("/api/billing/sync")
def billing_sync(uid: int = Depends(get_current_user)):
    """Pull-based confirmation: pregunta a MP el estado actual de la sub
    del user y actualiza nuestra DB acordemente.

    Útil principalmente para `/billing/success` tras el checkout: en lugar
    de esperar al webhook server-to-server (que requiere URL pública), el
    frontend llama a este endpoint y nosotros consultamos a MP directamente
    desde el server. Si MP dice 'authorized' → activamos Pro al instante.

    En producción seguimos teniendo el webhook como red de seguridad, pero
    el sync acelera el feedback al user (no espera el round-trip MP→nuestro
    server).
    """
    from billing import mercadopago
    conn = get_db()
    try:
        sub = conn.execute(
            """SELECT mp_subscription_id, status FROM subscriptions
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if not sub or not sub["mp_subscription_id"]:
            return {"status": "no_subscription"}

        # Reusamos la misma lógica del webhook — query MP + update nuestra DB
        try:
            _process_preapproval_event(conn, sub["mp_subscription_id"])
        except Exception as ex:
            log.error("Sync failed for uid=%s mp_id=%s: %s",
                     uid, sub["mp_subscription_id"], ex)
            raise HTTPException(502, f"Error consultando MP: {type(ex).__name__}")

        # Releer estado tras update
        updated = conn.execute(
            """SELECT status, period, current_period_end, next_charge_date
               FROM subscriptions WHERE mp_subscription_id = ?""",
            (sub["mp_subscription_id"],),
        ).fetchone()
        user_row = conn.execute(
            "SELECT tier FROM users WHERE id = ?", (uid,)
        ).fetchone()

        return {
            "subscription_id": sub["mp_subscription_id"],
            "status": updated["status"] if updated else "unknown",
            "period": updated["period"] if updated else None,
            "current_period_end": updated["current_period_end"] if updated else None,
            "next_charge_date": updated["next_charge_date"] if updated else None,
            "user_tier": user_row["tier"] if user_row else None,
        }
    finally:
        conn.close()


@app.get("/api/billing/status")
def billing_status(uid: int = Depends(get_current_user)):
    """Estado actual de la suscripción del user. Usado por /planes para
    mostrar 'Próxima renovación: X' o 'Cancelada · expira X'."""
    conn = get_db()
    try:
        sub = conn.execute(
            """SELECT mp_subscription_id, period, status, amount_ars,
                      current_period_start, current_period_end, next_charge_date,
                      cancelled_at, created_at
               FROM subscriptions
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (uid,),
        ).fetchone()
        if not sub:
            return {"has_subscription": False}
        return {
            "has_subscription": True,
            **dict(sub),
        }
    finally:
        conn.close()


@app.post("/api/billing/webhook")
async def billing_webhook(request: Request):
    """Recibe eventos de MP server-to-server.

    Eventos relevantes:
      • `preapproval` (action: created/updated)
         → Fetch full preapproval. Si status='authorized' → tier='pro'.
         Si 'cancelled'/'paused' → marcar y eventualmente revertir tier.
      • `subscription_authorized_payment` / `payment` (action: payment.created)
         → Cobro recurring exitoso. Actualizar next_charge_date.

    SECURITY: validar signature con x-signature header antes de procesar.
    En sandbox sin MP_WEBHOOK_SECRET configurado, permitimos sin validar
    (con warning) para facilitar dev. En prod siempre validamos.
    """
    from billing import mercadopago
    raw = await request.body()
    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        log.warning("Webhook with non-JSON body")
        return Response(status_code=400)

    event_type = payload.get("type") or payload.get("action") or ""
    data_id = str((payload.get("data") or {}).get("id") or payload.get("id") or "")
    mp_event_id = str(payload.get("id") or "")

    log.info("MP webhook received: type=%s data_id=%s", event_type, data_id)

    sig_valid = mercadopago.verify_webhook_signature(
        raw, x_signature, x_request_id, data_id
    )

    conn = get_db()
    try:
        # Audit log — siempre guardamos el evento aunque falle (replay/debug)
        with conn:
            conn.execute(
                """INSERT INTO billing_events
                       (mp_event_id, mp_event_type, mp_data_id, signature_valid,
                        processed, raw_payload, created_at)
                   VALUES (?, ?, ?, ?, 0, ?, datetime('now'))""",
                (
                    mp_event_id,
                    event_type,
                    data_id,
                    1 if sig_valid else 0,
                    json.dumps(payload),
                ),
            )

        if not sig_valid:
            # En sandbox sin secret pasamos (warning ya en mercadopago.py).
            # Sólo rechazamos si secret está configurado pero la firma falla.
            from billing.mercadopago import _webhook_secret
            if _webhook_secret():
                log.warning("MP webhook with INVALID signature, rejecting")
                return Response(status_code=401)

        # Procesar según tipo de evento
        if not data_id:
            return Response(status_code=200)  # nada que hacer

        if event_type in ("preapproval", "subscription_preapproval"):
            _process_preapproval_event(conn, data_id)
        elif event_type in (
            "subscription_authorized_payment",
            "payment",
            "subscription_payment",
        ):
            _process_payment_event(conn, data_id, payload)

        with conn:
            conn.execute(
                "UPDATE billing_events SET processed = 1 WHERE mp_event_id = ?",
                (mp_event_id,),
            )
        return Response(status_code=200)
    except Exception as ex:
        log.exception("MP webhook processing error: %s", ex)
        return Response(status_code=200)  # 200 para que MP no retry agresivo
    finally:
        conn.close()


def _process_preapproval_event(conn, preapproval_id: str):
    """Fetch full preapproval state from MP + sync our subscriptions row."""
    from billing import mercadopago
    pa = mercadopago.get_preapproval(preapproval_id)
    if not pa:
        return

    mp_status = (pa.get("status") or "").lower()
    ext_ref = pa.get("external_reference") or ""
    auto = pa.get("auto_recurring") or {}

    # Mapear status MP → status nuestro
    status_map = {
        "authorized": "authorized",
        "pending": "pending",
        "paused": "paused",
        "cancelled": "cancelled",
        "finished": "cancelled",
    }
    our_status = status_map.get(mp_status, "pending")

    # next_charge_date / current_period_end
    next_pmt = pa.get("next_payment_date")
    period_start = auto.get("start_date")

    with conn:
        conn.execute(
            """UPDATE subscriptions
               SET status = ?, current_period_start = COALESCE(?, current_period_start),
                   next_charge_date = COALESCE(?, next_charge_date),
                   current_period_end = COALESCE(?, current_period_end),
                   updated_at = datetime('now')
               WHERE mp_subscription_id = ?""",
            (our_status, period_start, next_pmt, next_pmt, preapproval_id),
        )

    # Si quedó authorized → el user pasa a tier=plus/pro + email de bienvenida
    if our_status == "authorized":
        parsed_full = mercadopago.parse_external_reference_full(ext_ref)
        if parsed_full:
            user_id, parsed_plan, parsed_period = parsed_full
            target_tier = parsed_plan if parsed_plan in ("plus", "pro") else "pro"
            with conn:
                conn.execute("UPDATE users SET tier = ? WHERE id = ?", (target_tier, user_id))
                conn.execute(
                    "UPDATE billing_events SET user_id = ? WHERE mp_data_id = ?",
                    (user_id, preapproval_id),
                )
            log.info("User %s upgraded to tier=%s via MP preapproval %s", user_id, target_tier, preapproval_id)
            _maybe_send_welcome_email(conn, preapproval_id, user_id, parsed_period, pa)
    elif our_status in ("cancelled", "paused"):
        # NO revertimos tier — el user mantiene Pro hasta current_period_end.
        # El cron _run_subscription_lifecycle_job lo baja a Free al expirar.
        log.info("Subscription %s now %s (tier change pending end of period)", preapproval_id, our_status)


def _maybe_send_welcome_email(conn, preapproval_id, user_id, period, mp_state):
    """Manda el email de bienvenida UNA SOLA VEZ por suscripción.
    Idempotente vía welcome_email_sent_at — si está set, saltamos."""
    from billing import emails
    row = conn.execute(
        """SELECT s.welcome_email_sent_at, s.amount_ars, u.email, u.name
           FROM subscriptions s JOIN users u ON u.id = s.user_id
           WHERE s.mp_subscription_id = ?""",
        (preapproval_id,),
    ).fetchone()
    if not row:
        return
    if row["welcome_email_sent_at"]:
        return  # ya enviamos
    try:
        sent = emails.send_welcome_pro(
            to=row["email"],
            user_name=(row["name"] or row["email"].split("@")[0]),
            period=period,
            amount_ars=row["amount_ars"],
            next_charge_date=mp_state.get("next_payment_date"),
        )
        if sent or not emails._is_configured():
            # Marcamos como enviado igual en modo "no configurado" (log-only)
            # para no spamear el log con cada webhook.
            with conn:
                conn.execute(
                    """UPDATE subscriptions SET welcome_email_sent_at = datetime('now')
                       WHERE mp_subscription_id = ?""",
                    (preapproval_id,),
                )
    except Exception as ex:
        log.error("Welcome email failed for sub %s: %s", preapproval_id, ex)


def _process_payment_event(conn, payment_id: str, payload: dict):
    """Procesa un payment event recurrente.

    Para cada pago, dispara el email correspondiente:
      • status 'approved' / 'accredited' → receipt
      • status 'rejected' / 'cancelled'  → payment_failed

    Registramos el payment_id en la subscription para auditoría e
    idempotencia (last_payment_id evita disparar el mismo email dos veces)."""
    from billing import emails

    pa_id = (payload.get("data") or {}).get("preapproval_id")
    data_status = ((payload.get("data") or {}).get("status") or "").lower()
    if pa_id:
        with conn:
            conn.execute(
                """UPDATE subscriptions SET last_payment_id = ?,
                   updated_at = datetime('now')
                   WHERE mp_subscription_id = ?""",
                (payment_id, pa_id),
            )
    log.info("MP payment event processed: payment_id=%s preapproval=%s status=%s",
            payment_id, pa_id, data_status)

    if not pa_id:
        return

    sub_row = conn.execute(
        """SELECT s.user_id, s.amount_ars, s.next_charge_date, s.welcome_email_sent_at,
                  u.email, u.name
           FROM subscriptions s JOIN users u ON u.id = s.user_id
           WHERE s.mp_subscription_id = ?""",
        (pa_id,),
    ).fetchone()
    if not sub_row:
        return

    user_name = (sub_row["name"] or (sub_row["email"] or "").split("@")[0] or "Inversor")

    is_approved = data_status in ("approved", "accredited", "authorized") or not data_status
    if is_approved and sub_row["welcome_email_sent_at"]:
        # Renovación exitosa después de la primera (welcome ya fue) → recibo.
        try:
            emails.send_receipt(
                to=sub_row["email"],
                user_name=user_name,
                amount_ars=sub_row["amount_ars"],
                payment_date=(payload.get("data") or {}).get("date_approved")
                             or _iso_today(),
                next_charge_date=sub_row["next_charge_date"],
                payment_id=str(payment_id),
            )
        except Exception as ex:
            log.error("Receipt email failed for payment %s: %s", payment_id, ex)
    elif data_status in ("rejected", "cancelled", "refunded"):
        try:
            emails.send_payment_failed(
                to=sub_row["email"],
                user_name=user_name,
                retry_date=sub_row["next_charge_date"],
            )
        except Exception as ex:
            log.error("Payment failed email failed for payment %s: %s", payment_id, ex)


def _iso_today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _maybe_send_cancellation_email(conn, preapproval_id, user_id):
    """Email de cancelación. Idempotente vía cancellation_email_sent_at."""
    from billing import emails
    row = conn.execute(
        """SELECT s.cancellation_email_sent_at, s.current_period_end, u.email, u.name
           FROM subscriptions s JOIN users u ON u.id = s.user_id
           WHERE s.mp_subscription_id = ?""",
        (preapproval_id,),
    ).fetchone()
    if not row or row["cancellation_email_sent_at"]:
        return
    try:
        valid_until = row["current_period_end"] or _iso_today()
        emails.send_cancellation(
            to=row["email"],
            user_name=(row["name"] or row["email"].split("@")[0]),
            valid_until=valid_until,
        )
        with conn:
            conn.execute(
                """UPDATE subscriptions SET cancellation_email_sent_at = datetime('now')
                   WHERE mp_subscription_id = ?""",
                (preapproval_id,),
            )
    except Exception as ex:
        log.error("Cancellation email failed for sub %s: %s", preapproval_id, ex)


@app.get("/api/ai/usage")
def ai_usage(uid: int = Depends(get_current_user)):
    """Usage de la SEMANA en curso (ISO week, lunes-domingo) — el frontend
    lo usa para mostrar 'X/6 esta semana' en Free, 'X/60' en Pro, 'Admin ·
    sin tope' para admin, etc."""
    from ai import quota
    conn = get_db()
    try:
        return quota.get_current_usage(conn, uid)
    finally:
        conn.close()


@app.delete("/api/ai/cache/{screen}")
def ai_invalidate_cache(screen: str, uid: int = Depends(get_current_user)):
    """Borra el cache de un screen para este user. Lo llama el frontend
    cuando aprieta 'Refrescar' en el drawer. Tambien lo llaman los
    endpoints de mutación (POST /positions, /operations, etc.) en futuro."""
    from ai import cache
    conn = get_db()
    try:
        n = cache.invalidate_for_user(conn, uid, screens=[screen.lower()])
        return {"deleted": n}
    finally:
        conn.close()


# ─── Whitelist de preguntas pre-armadas (Free/Plus tier) ─────────────────────
# Sincronizada con frontend/src/components/AICoach.jsx::DEFAULT_SUGGESTED.
# Free/Plus solo pueden mandar mensajes que matcheen una de estas 12
# (normalización NFKC + casefold). Pro/Admin pueden mandar texto libre.
# Si actualizás esta lista, hay que actualizar el frontend en paralelo.

_FREE_QUESTIONS_WHITELIST = (
    "¿Cómo está mi portfolio en general?",
    "¿Qué riesgos detectás en mi cartera?",
    "¿Mi nivel de concentración es elevado?",
    "¿Cómo evalúo mi win rate?",
    # Slot #5: dispara get_value_scorecard sobre el top holding del user.
    # Pack A v2 onboarding chip — sin esto, Free/Plus jamás descubren
    # la tool nueva (whitelist es un cap rígido para Free).
    "¿Está cara mi posición más grande?",
    "¿Detectás algún sesgo en mi forma de operar?",
    "¿Mi exposure por sector/región está equilibrado?",
    # Slot #8: dispara get_earnings_history sobre activos en cartera.
    "¿Cuándo reportan earnings los activos de mi cartera?",
    "Si tuvieras que mejorar UNA cosa de mi cartera, ¿cuál sería?",
    "¿Cómo voy vs el S&P 500?",
    "¿Le estoy ganando a la inflación argentina?",
    "¿Qué activo es el que más riesgo me agrega?",
)


def _normalize_question(s: str) -> str:
    """Normaliza una pregunta para comparación: NFKC + casefold + collapse
    whitespace + strip. Permite que el frontend mande variantes leves
    (mayúsculas/acentos perdidos) sin romper el matching."""
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = " ".join(s.split())  # collapse whitespace
    return s.casefold().strip()


_FREE_QUESTIONS_NORMALIZED = frozenset(_normalize_question(q) for q in _FREE_QUESTIONS_WHITELIST)


def _is_whitelisted_question(text: str) -> bool:
    """True si `text` matchea alguna pregunta de la whitelist (case + accent
    insensitive). Free/Plus solo pueden mandar éstas."""
    return _normalize_question(text) in _FREE_QUESTIONS_NORMALIZED


# Pricing Haiku 4.5 (USD por 1M tokens). Actualizar si Anthropic cambia.
# https://docs.anthropic.com/en/docs/about-claude/pricing
_HAIKU_PRICE = {
    "input": 1.0,          # input no cacheado
    "cache_write": 1.25,   # cache_creation
    "cache_read": 0.10,    # cache_read
    "output": 5.0,
}


def _log_and_estimate_chat_cost(usage_obj, tier: str, uid: int, stage: str) -> int:
    """Estima costo de un response del LLM y loggea cache hit/create.

    Devuelve costo en centésimos de USD (int) para persistir en
    ai_usage_daily.cost_usd_cents. Si usage_obj es None (versión vieja del
    SDK, mock test), devuelve 0 sin romper.

    Audit #3 fix B4: sin este log, una caída del cache hit rate de 50%→25%
    duplica el costo y solo nos enteramos por la factura mensual.
    """
    if usage_obj is None:
        return 0
    try:
        # SDK Anthropic v0.34+: usage tiene input_tokens, output_tokens,
        # cache_creation_input_tokens, cache_read_input_tokens.
        inp = int(getattr(usage_obj, "input_tokens", 0) or 0)
        out = int(getattr(usage_obj, "output_tokens", 0) or 0)
        cw = int(getattr(usage_obj, "cache_creation_input_tokens", 0) or 0)
        cr = int(getattr(usage_obj, "cache_read_input_tokens", 0) or 0)

        cost_usd = (
            inp * _HAIKU_PRICE["input"]
            + cw * _HAIKU_PRICE["cache_write"]
            + cr * _HAIKU_PRICE["cache_read"]
            + out * _HAIKU_PRICE["output"]
        ) / 1_000_000

        total_input = inp + cw + cr
        cache_hit_pct = (cr / total_input * 100) if total_input > 0 else 0.0

        log.info(
            "ai_chat_usage tier=%s uid=%s stage=%s input=%d cache_write=%d cache_read=%d "
            "output=%d cache_hit=%.1f%% cost_usd=%.5f",
            tier, uid, stage, inp, cw, cr, out, cache_hit_pct, cost_usd,
        )
        # Convertir a centésimos (1 USD = 100 cents). Round mínimo 0 — si la
        # llamada fue gratis (todo cache_read y resultó <0.5 cent), no perdemos
        # el log pero tampoco contaminamos la DB con ceros engañosos.
        return max(0, round(cost_usd * 100))
    except Exception as ex:
        log.warning("ai_chat_usage logging failed: %s", ex)
        return 0


@app.post("/api/ai/chat")
def ai_chat(data: AIChatIn, request: Request, uid: int = Depends(get_current_user)):
    """Chat con el coach IA — tier-aware.

    Free/Plus:
    - Solo aceptan mensajes en _FREE_QUESTIONS_WHITELIST (12 preguntas).
    - Cuota 6/semana (rolling 7d) vía ai_usage_daily.chat_count.
    - Prompt descriptivo, max_tokens=300, sin causalidad ni recomendaciones.

    Pro/Admin:
    - Texto libre permitido (chat libre real).
    - Cuota 60/semana.
    - Prompt completo causal, max_tokens=1000, tools habilitadas.

    Prompt-cache fix (audit #1/2 HIGH):
    - system_text = SOLO manifiesto estable por tier → cache hit ~99%.
    - snapshot + facts + investor_block van como bloque en el PRIMER user
      message con cache_control → cache hit alto entre turnos de la misma
      sesión (snapshot del cliente cacheado 60s).

    Output sanitizado server-side (markdown strip) — red de seguridad.
    """
    client = _get_anthropic_client()
    if client is None:
        raise HTTPException(503, "AI no configurada (falta ANTHROPIC_API_KEY)")

    from ai import quota

    # Resolver tier + cuota + perfil + facts en una sola conexión.
    conn = get_db()
    try:
        tier = quota.get_tier(conn, uid)
        # Cuota semanal por tier (Free/Plus=6, Pro=60, Admin=1000). Bloqueo
        # ANTES de procesar — barato + claro mensaje al usuario.
        allowed, usage = quota.can_chat(conn, uid)
        if not allowed:
            # Shape consistente con /api/ai/analyze: incluye `upgrade` payload
            # para que el frontend renderee UpgradePromoCard con CTA a Pro/Plus
            # en lugar de un banner de error plano. Audit #4.
            #
            # Target del upgrade:
            #   - Free → Plus (3 → 9 chats = 3× más, upgrade barato)
            #   - Plus → Pro (9 → 40 chats + chat libre + IA causal)
            #   - Pro/Admin: no aplica, no debería llegar acá pero por las dudas
            upgrade_available = tier in ("free", "plus")
            target_tier = "plus" if tier == "free" else "pro"
            if target_tier == "plus":
                benefits = [
                    "3× más Chat Coach IA (9 consultas/sem vs 3)",
                    "Hasta 3 brokers (vs 1 en Free)",
                    "Reportes históricos + Export CSV",
                    "Diagnóstico completo + 4 detectores de comportamiento",
                ]
            else:  # plus → pro
                benefits = [
                    "Chat libre con el Coach IA (40 consultas/sem)",
                    "10× más análisis IA (60/sem vs 6/sem)",
                    "Respuestas con causalidad y memoria persistente",
                    "Brokers ilimitados + comportamiento completo",
                ]
            # resets_on dinámico del usage (calculado por quota.get_current_usage
            # como date(MIN(date), '+7 days') del slot más viejo). Si null,
            # texto genérico — la cuota es rolling 7d, NUNCA decir "lunes".
            resets_on = usage.get("resets_on")
            if resets_on:
                msg = f"Llegaste al máximo de consultas ({usage['chat_count']}/{usage['chat_limit']}) de esta semana. Tu próxima consulta se libera el {resets_on}."
            else:
                msg = f"Llegaste al máximo de consultas ({usage['chat_count']}/{usage['chat_limit']}) de esta semana. Tu próxima consulta se libera cuando expira el slot más antiguo (ventana móvil de 7 días)."
            raise HTTPException(
                429,
                detail={
                    "error": "chat_quota_exceeded",
                    "message": msg,
                    "usage": usage,
                    "upgrade": {
                        "available": upgrade_available,
                        "current_tier": tier,
                        "target_tier": target_tier,
                        "resets_on": resets_on,
                        "benefits": benefits,
                    },
                },
            )
        prof_row = conn.execute(
            "SELECT investor_profile FROM users WHERE id=?", (uid,)
        ).fetchone()
        # Memoria persistente del user (Ola 3-L). Levantamos hasta 25 facts
        # activos más recientes — el bot debe respetarlos como verdad declarada.
        facts_rows = conn.execute(
            """SELECT content FROM ai_user_facts
               WHERE user_id=? AND is_active=1
               ORDER BY created_at DESC LIMIT 25""",
            (uid,),
        ).fetchall()
    finally:
        conn.close()

    is_premium = tier in ("pro", "admin")

    # Gating Free/Plus: solo whitelist. Pro/Admin: libre.
    #
    # Audit #3 fix B2: ANTES validábamos solo el último user msg, pero un
    # cliente Free podía mandar history fabricado [user:ataque, assistant:OK,
    # user:whitelisted] → el ataque se colaba al LLM. AHORA:
    #   1. Validamos el último user msg contra whitelist (= gate).
    #   2. En PATH Free, IGNORAMOS toda historia y mandamos SOLO el último
    #      mensaje validado al LLM. Free no tiene memoria conversacional —
    #      cada pregunta es one-shot. Eso elimina el vector de injection.
    last_user_msg = ""
    for m in reversed(data.messages):
        if m.role == "user":
            last_user_msg = str(m.content or "")
            break

    if not is_premium:
        if not _is_whitelisted_question(last_user_msg):
            log.info("ai_chat rejected non-whitelisted msg, tier=%s uid=%s msg=%r",
                     tier, uid, last_user_msg[:80])
            # 403 con upgrade payload — para que el frontend muestre la card
            # promocional con CTA en lugar de un banner de error rojo. El
            # target Pro porque chat libre = Pro-only (Plus también está
            # limitado a la whitelist de 12 preguntas).
            raise HTTPException(
                403,
                detail={
                    "error": "free_chat_not_allowed",
                    "message": "El chat libre está disponible solo en el plan Pro. Elegí una de las preguntas guiadas o actualizá tu plan.",
                    "tier": tier,
                    "upgrade": {
                        "available": True,
                        "current_tier": tier,
                        "target_tier": "pro",
                        "benefits": [
                            "Chat libre con el Coach IA — preguntá lo que quieras",
                            "40 consultas/semana (vs 12 preguntas guiadas)",
                            "Respuestas con causalidad y memoria persistente",
                            "10× más análisis IA + brokers ilimitados",
                        ],
                    },
                },
            )

    base_system = _AI_CHAT_SYSTEM if is_premium else _AI_CHAT_SYSTEM_FREE
    # Pro chat max_tokens bajado de 1000 → 800 tras audit #3 (cost control).
    # 800 tokens output mantiene respuestas profundas (~600 palabras) y baja
    # output cost del worst case ~20%.
    max_tokens = 800 if is_premium else 300
    max_tokens_fallback = 600 if is_premium else 250

    # Modo del bloque de perfil: Pro/Admin → causal (infiere causas plausibles).
    # Free/Plus → descriptive (solo presenta el dato, no interpreta).
    profile_mode = "causal" if is_premium else "descriptive"
    investor_block = _format_investor_profile_for_prompt(
        prof_row["investor_profile"] if prof_row else None,
        mode=profile_mode,
    )

    # Sanitizar el snapshot ANTES de serializarlo al LLM.
    snapshot_clean = _sanitize_chat_snapshot(data.snapshot)
    portfolio_json = json.dumps(snapshot_clean, indent=2, ensure_ascii=False, default=str)

    # Bloque de hechos persistentes del user (Ola 3-L).
    facts_block = ""
    if facts_rows:
        bullets = "\n".join(f"- {dict(r)['content']}" for r in facts_rows)
        facts_block = (
            f"\n\nHECHOS DECLARADOS POR EL USUARIO (memoria persistente)\n"
            f"El usuario te aclaró estos puntos en conversaciones previas. "
            f"Tratalos como VERDAD para esta sesión — no los contradigas y no "
            f"pidas que los re-explique. Si un dato del snapshot parece chocar "
            f"con un hecho declarado, asumí que el hecho declarado prevalece:\n"
            f"{bullets}"
        )

    # ─── system_text estable por tier (cache target ~99%) ────────────────────
    # Audit #1/2 HIGH fix: ANTES system_text incluía snapshot dinámico → cache
    # muerto. AHORA system_text es solo el manifiesto + reglas de _kind, que
    # es idéntico entre requests del mismo tier.
    system_text = f"""{base_system}

REGLA CRÍTICA sobre los datos del usuario que vienen en el primer user message:
El snapshot incluye summary, positions (ABIERTAS, _kind='open_position'), operations (CERRADAS, _kind='closed_trade'), monthly, brokers y benchmarks. Usá _kind para no confundir riesgo presente (open) con P&L histórico (closed). Si hay HECHOS DECLARADOS por el usuario, son verdad declarada — no los contradigas."""

    # ─── Context block dinámico — al PRIMER user message ─────────────────────
    # Esto SÍ cambia per-request (snapshot del cliente) pero entre tool_use
    # loops dentro de UN MISMO request, queda cacheado. Y entre requests
    # consecutivos del mismo user (snapshot suele estar cacheado 60s en el
    # frontend), Anthropic puede reusar el cache.
    context_block_text = f"""--- CONTEXTO DE TU CARTERA (snapshot del momento) ---{facts_block}

```json
{portfolio_json}
```{investor_block}
--- FIN CONTEXTO ---"""

    # Construir messages enriqueciendo el PRIMER user message con el context.
    #
    # Audit #3 fix B2: en path Free/Plus mandamos SOLO el último user msg
    # (ya validado por whitelist arriba). Sin historia → no hay vector de
    # injection vía history fabricado. Pro/Admin sí preserva la historia
    # (chat conversacional real).
    if is_premium:
        incoming = [m.model_dump() for m in data.messages]
    else:
        # Free/Plus: one-shot. Mandamos al LLM SOLO el mensaje validado.
        incoming = [{"role": "user", "content": last_user_msg}]

    messages_loop: list = []
    context_injected = False
    for m in incoming:
        if not context_injected and m.get("role") == "user":
            # Primer user message: lleva contexto + pregunta real, ambos
            # como content blocks. cache_control sobre el contexto.
            user_content = m.get("content", "")
            messages_loop.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": context_block_text, "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": str(user_content) if user_content else ""},
                ],
            })
            context_injected = True
        else:
            messages_loop.append(m)

    # MAX_TOOL_LOOPS=2: 1 ronda de tool calls + 1 síntesis final = lo necesario.
    # Bajado de 3 → 2 tras bug timeout Vercel (commit infra): cada loop = 1
    # round-trip a Anthropic (5-15s con tools). Con 3 loops + fallback worst
    # case = 4 round-trips → fácil > 25s SDK timeout → Vercel proxy corta a
    # 30s → user veía error genérico sin contexto.
    # 2 loops cubre el caso real: turn 1 → LLM pide N tools → ejecutamos →
    # turn 2 → LLM sintetiza. Los casos donde necesita 3 loops son raros y
    # típicamente síntoma de prompt confuso, no de complejidad legítima.
    MAX_TOOL_LOOPS = 2
    # Audit Pack A v2 fix #5: hard cap server-side de TOOL CALLS por turno.
    # El prompt instruye "max 2 tools de mercado" pero el LLM puede ignorar.
    # Si llama 5 tools, ejecutamos las primeras 4 y rechazamos el resto con
    # un tool_result que dice "cap excedido". Protege contra cost spikes
    # cuando el LLM se confunde y decide consultar todo en un solo turno.
    MAX_TOOL_CALLS_PER_TURN = 4
    tool_calls_total = 0
    last_response = None  # capturamos el response final para record_chat con tokens

    try:
        for _ in range(MAX_TOOL_LOOPS + 1):
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=max_tokens,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                tools=_AI_TOOLS,
                messages=messages_loop,
            )
            last_response = response

            if response.stop_reason != "tool_use":
                # Respuesta final en texto
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    ""
                )
                # Audit #3 fix B4: loggear cache hit rate + tokens reales.
                # Sin esto no podemos detectar regresiones del cache (cuando
                # cache_read cae a 0, el costo se multiplica por ~10× y solo
                # nos enteramos por la factura mensual de Anthropic).
                usage_obj = getattr(response, "usage", None)
                cost_cents = _log_and_estimate_chat_cost(usage_obj, tier, uid, "final")
                # Registrar consumo de cuota (solo en éxito — si falló no descontamos).
                try:
                    conn2 = get_db()
                    try:
                        quota.record_chat(conn2, uid, cost_usd_cents=cost_cents)
                    finally:
                        conn2.close()
                except Exception as ex:
                    log.warning("record_chat failed for uid=%s: %s", uid, ex)
                return {"reply": _strip_markdown(text.strip()), "tier": tier}

            # Hay tool_use: ejecutar cada tool y continuar el loop.
            # Hard cap: si llegamos a MAX_TOOL_CALLS_PER_TURN, rechazamos
            # los tools restantes con un tool_result de error.
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if tool_calls_total >= MAX_TOOL_CALLS_PER_TURN:
                        log.warning(
                            "ai_chat tool_cap_exceeded tier=%s uid=%s tool=%s total=%d",
                            tier, uid, block.name, tool_calls_total,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({
                                "error": (
                                    f"cap de {MAX_TOOL_CALLS_PER_TURN} tools por turno alcanzado. "
                                    "Sintetizá una respuesta con lo que ya tenés."
                                ),
                            }, ensure_ascii=False),
                        })
                        continue
                    tool_calls_total += 1
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

        # Si llegó al límite de loops sin respuesta final, forzar respuesta sin tool_use.
        # PASAMOS tools=_AI_TOOLS pero con tool_choice="none" para que:
        # 1. El shape del messages_loop (que tiene tool_use blocks históricos)
        #    siga siendo coherente con la declaración de tools — sin esto
        #    Anthropic puede devolver 400 BadRequest por history inconsistente.
        # 2. El LLM esté forzado a sintetizar texto, no a llamar más tools.
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=max_tokens_fallback,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            tools=_AI_TOOLS,
            tool_choice={"type": "none"},
            messages=messages_loop,
        )
        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        usage_obj = getattr(response, "usage", None)
        cost_cents = _log_and_estimate_chat_cost(usage_obj, tier, uid, "fallback")
        try:
            conn2 = get_db()
            try:
                quota.record_chat(conn2, uid, cost_usd_cents=cost_cents)
            finally:
                conn2.close()
        except Exception as ex:
            log.warning("record_chat failed for uid=%s: %s", uid, ex)
        return {"reply": _strip_markdown(text.strip()), "tier": tier}

    except HTTPException:
        raise
    except Exception as ex:
        # Manejo específico de errores del SDK Anthropic. Los detectamos por
        # nombre de clase (sin importar el módulo) para no acoplar el código
        # al SDK exacto y porque heredan de Exception (caen acá).
        #
        # ¿Por qué? Vercel rewrite tiene ~30s timeout duro. Si Anthropic SDK
        # falla por timeout (25s ahora), tenemos ~5s para devolver detail útil
        # ANTES de que Vercel corte. Sin esto, todos los timeouts caían en
        # f"Error en el chat: {ex}" con texto técnico al user.
        ex_name = type(ex).__name__
        log.warning("ai_chat exception tier=%s uid=%s type=%s msg=%s", tier, uid, ex_name, str(ex)[:200])
        if ex_name in ("APITimeoutError", "APIConnectionError"):
            raise HTTPException(
                503,
                detail={
                    "error": "ai_timeout",
                    "message": "El coach IA está tardando más de lo normal. Intentá una pregunta más simple, o reintentá en unos segundos.",
                },
            )
        if ex_name in ("RateLimitError",):
            raise HTTPException(
                503,
                detail={
                    "error": "ai_rate_limit",
                    "message": "El coach IA está procesando muchas consultas en este momento. Reintentá en 10-20 segundos.",
                },
            )
        if ex_name in ("BadRequestError",):
            # 400 del lado de Anthropic = nuestro problema (shape mal armado).
            # No exponemos el detalle técnico al user — pero loggeamos para fix.
            log.error("ai_chat BadRequest uid=%s detail=%s", uid, str(ex)[:500])
            raise HTTPException(
                500,
                detail={
                    "error": "ai_internal",
                    "message": "Hubo un problema procesando tu consulta. Tocá \"Nuevo\" e intentá de nuevo.",
                },
            )
        raise HTTPException(500, f"Error en el chat: {ex}")


# ─── AI memory — ai_user_facts (Ola 3-L) ─────────────────────────────────────
# CRUD para "hechos" que el user le aclara al bot y deben persistir entre
# sesiones. El bot los lee en /api/ai/chat al construir el system prompt.
#
# UX esperada (frontend, fuera de scope acá): chip "El bot dijo algo mal" →
# input texto corto → POST /api/ai/remember. Lista en /config con toggle.

# Caps a defender:
#   • MAX_ACTIVE_FACTS: 50 facts is_active=1 — lo que se inyecta al prompt
#   • MAX_TOTAL_FACTS: 200 facts (activos + inactivos) — evita unbounded
#     soft-delete growth (ciclo insert→delete→insert llena la tabla)
MAX_ACTIVE_FACTS = 50
MAX_TOTAL_FACTS = 200


# Patrones prompt-injection. Normalizados con NFKD + ASCII fold ANTES del
# matching, así una sola entry sin acento cubre todas las variantes acentuadas.
# Por ejemplo, "olvida" matchea contra "olvida", "olvidá", "olvidás", "olvído".
#
# Aplicado en BOTH paths (endpoint REST y tool LLM) via _validate_fact_content.
# Audit #3 fix B5+B8: amplía a 50+ patterns en EN+ES con normalización robusta.
_FACT_INJECTION_PATTERNS = (
    # ─── English ────────────────────────────────────────────────────────
    "ignore previous", "ignore prior", "ignore all previous",
    "ignore the above", "ignore my previous", "ignore everything above",
    "disregard previous", "disregard the above", "disregard everything",
    "forget what i said", "forget previous", "forget everything",
    "forget all previous", "forget what you", "forget your",
    "new instructions", "updated instructions", "override previous",
    "override your", "reset your", "reset instructions",
    "system prompt", "system message", "system:", "your system",
    "your instructions", "your real instructions",
    "<|", "{{ system", "</system>", "<system>", "[system]", "[INST]",
    "as the system", "as the administrator", "as the developer",
    "you are now", "you are actually", "pretend you are", "pretend to be",
    "act as", "acting as", "behave as", "role:",
    "i am the system", "i am the developer", "i am your developer",
    # ─── Español (sin acentos — el normalizer los strippea antes) ───────
    # Cubrir variantes "ignora/ignoras/ignoro" → todas matchean "ignora"
    "ignora las instrucciones", "ignora todas las", "ignora todo lo",
    "ignora lo anterior", "ignora lo previo", "ignora lo de arriba",
    "olvida lo anterior", "olvida todo lo", "olvida las reglas",
    "olvida las instrucciones",
    "olvidate de", "olvidate lo", "olvidate todo",
    "olvida lo que", "olvida tus", "olvida tus instrucciones",
    "desestima las reglas", "desestima lo", "desestima las",
    "anula las instrucciones", "anula tus",
    "redefini tus", "redefini las",
    "ahora sos", "a partir de ahora sos", "a partir de ahora eres",
    "ahora actuas como", "actua como", "actuas como",
    "nuevas instrucciones", "instrucciones nuevas",
    "tu nuevo sistema", "tu nuevo rol",
    "yo soy el sistema", "yo soy el desarrollador",
)


def _normalize_for_injection_check(s: str) -> str:
    """Normaliza un string para matching contra _FACT_INJECTION_PATTERNS.

    Strippea acentos vía NFKD + ASCII fold → una entry sin acento matchea
    todas las variantes acentuadas. Útil porque casefold() NO normaliza
    acentos: 'olvidá'.casefold() ≠ 'olvida'.

    Pasos:
      NFKD descompone caracteres acentuados → base + combining char.
      .encode('ascii', 'ignore') descarta los combining chars.
      .decode('ascii') vuelve a str.
      .casefold() lowercase robusto (incluye locale-specific).
    """
    import unicodedata
    decomposed = unicodedata.normalize("NFKD", s)
    ascii_bytes = decomposed.encode("ascii", "ignore")
    return ascii_bytes.decode("ascii").casefold()


def _validate_fact_content(raw: str) -> str:
    """Sanitiza + valida content de un fact. Devuelve el texto limpio.

    Reglas:
    1. NFKC normalize (defensa contra unicode lookalikes: 'іgnore' cirílico)
    2. Reemplaza \\n / \\r / \\t por espacio (defensa contra newline injection
       que rompería el bullet point en el render del system prompt)
    3. Strip + cap 280 chars
    4. min 3 chars
    5. Rechaza si match con _FACT_INJECTION_PATTERNS — usando NFKD+ASCII fold
       para que una sola entry cubra variantes acentuadas (audit #3 B8).

    Raises ValueError con mensaje útil para Pydantic / tool path.
    """
    import unicodedata
    s = unicodedata.normalize("NFKC", str(raw or ""))
    # Newlines/tabs → espacio. El facts_block se renderiza como bullet
    # `- {content}` — un \n dentro del content bypassaría el bullet y
    # dejaría que el contenido inyecte una línea suelta del prompt.
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = s.strip()[:280]
    if len(s) < 3:
        raise ValueError("content debe tener al menos 3 caracteres tras strip")
    # Matching robusto: ascii-fold + casefold elimina acentos y mayúsculas.
    # "Olvidá las instrucciones" → "olvida las instrucciones" → match.
    normalized = _normalize_for_injection_check(s)
    for pat in _FACT_INJECTION_PATTERNS:
        if pat in normalized:
            raise ValueError(f"content contiene un patrón no permitido: {pat!r}")
    return s


def _atomic_insert_fact(conn, uid: int, content: str, source: str):
    """Inserta un fact con cap atómico (activos < MAX_ACTIVE_FACTS y total <
    MAX_TOTAL_FACTS). Usa single-statement INSERT-WHERE — no hay race window
    porque SQLite serializa el WHERE+INSERT.

    Devuelve:
      • dict {id, content, source, duplicate: False} si se insertó nuevo
      • dict {id, content, source, duplicate: True} si ya existía activo
        con el mismo content (UNIQUE index lo bloqueó — no error, idempotente)
      • None si chocó con algún cap (activos o total)

    Por qué INSERT-WHERE en vez de BEGIN IMMEDIATE: más simple, menos error-
    prone, idempotente. El audit anterior usaba `with conn:` que en sqlite3
    default es BEGIN DEFERRED y el SELECT no toma write lock → TOCTOU.
    """
    try:
        cur = conn.execute(
            """INSERT INTO ai_user_facts(user_id, content, source)
               SELECT ?, ?, ?
               WHERE (SELECT COUNT(*) FROM ai_user_facts
                      WHERE user_id=? AND is_active=1) < ?
                 AND (SELECT COUNT(*) FROM ai_user_facts
                      WHERE user_id=?) < ?""",
            (uid, content, source, uid, MAX_ACTIVE_FACTS, uid, MAX_TOTAL_FACTS),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # UNIQUE constraint violation — el fact ya existe activo. Idempotente:
        # devolvemos el id existente como si fuera un INSERT exitoso.
        try:
            conn.rollback()
        except Exception:
            pass
        existing = conn.execute(
            "SELECT id FROM ai_user_facts WHERE user_id=? AND content=? AND is_active=1",
            (uid, content),
        ).fetchone()
        if existing:
            return {"id": existing["id"], "content": content, "source": source, "duplicate": True}
        return None
    if cur.rowcount == 0:
        return None
    return {"id": cur.lastrowid, "content": content, "source": source, "duplicate": False}


# ─── Feedback del user: recomendaciones / ideas / bugs ──────────────────────
# POST /api/feedback/recommendation → manda mail a recomendaciones@rendi.finance
# Llamado desde el modal "Recomendaciones" accesible desde Sidebar + Config.

class RecommendationIn(BaseModel):
    """Input para enviar una recomendación al equipo de Rendi."""
    subject: str = Field(..., min_length=2, max_length=200)
    body: str = Field(..., min_length=5, max_length=5000)


@app.post("/api/feedback/recommendation")
def feedback_recommendation(
    data: RecommendationIn,
    request: Request,
    uid: int = Depends(get_current_user),
):
    """Recibe una recomendación del user y la envía por mail a
    recomendaciones@rendi.finance via Resend.

    Rate limit: 5 por hora por IP (suficiente para uso legítimo,
    bloquea spam masivo). Anti-abuse adicional: el mail siempre va
    a recomendaciones@ con reply-to=user_email, así Nico ve quién
    escribe y puede responder directo desde su Gmail.

    Errores:
      • 422 — validación de pydantic (subject/body fuera de rango)
      • 429 — demasiados envíos desde la misma IP
      • 503 — Resend no respondió (no bloqueante, intentar de nuevo)
    """
    _check_rate_limit(request, max_calls=5, window_seconds=3600, suffix="recommendation")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT email, name, tier FROM users WHERE id=?", (uid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        user_email = row["email"]
        user_name = row["name"] or row["email"].split("@")[0]
        user_tier = (row["tier"] or "free").lower()
    finally:
        conn.close()

    from billing import emails
    # 1. Mail al equipo (recomendaciones@rendi.finance). Si falla, devolvemos
    #    error porque el equipo no se entera del feedback — es lo crítico.
    ok = emails.send_user_recommendation(
        user_email=user_email,
        user_name=user_name,
        user_tier=user_tier,
        subject=data.subject,
        body=data.body,
    )
    if not ok:
        raise HTTPException(
            503,
            detail={
                "error": "send_failed",
                "message": (
                    "No pudimos enviar tu recomendación en este momento. "
                    "Probá de nuevo en unos minutos, o escribinos directo "
                    "a recomendaciones@rendi.finance."
                ),
            },
        )

    # 2. Acuse de recibo al user — reemplaza el filtro Gmail que era poco
    #    confiable (responde al From de no_reply@, no al user real).
    #    Si falla: log warning pero NO error — el equipo ya tiene el mensaje,
    #    el user no recibe acuse pero su recomendación está registrada.
    try:
        ack_ok = emails.send_recommendation_acknowledgment(
            user_email=user_email,
            user_name=user_name,
        )
        if not ack_ok:
            log.warning("recommendation ack email failed for uid=%s email=%s", uid, user_email)
    except Exception as ex:
        log.warning("recommendation ack exception uid=%s: %s", uid, ex)

    log.info("feedback_recommendation sent uid=%s subject=%s", uid, data.subject[:80])
    return {"ok": True}


class AIRememberIn(BaseModel):
    """Input para guardar un hecho persistente del user.

    `content` es el texto del hecho (cap 280 chars — bullet conciso, no parrafo).
    `source` opcional: distingue user-corregido vs ai-inferido. Default
    'user_correction' porque la mayoría va a venir del chip "corregir bot".
    """
    # max_length 320 para que el validator pueda truncar/normalizar sin que
    # Pydantic rechace antes. La validación efectiva la hace el validator a 280.
    content: str = Field(..., min_length=3, max_length=320)
    source: Optional[str] = Field(default="user_correction", max_length=32)

    @field_validator('content')
    @classmethod
    def strip_and_validate_content(cls, v: str) -> str:
        # Centraliza la lógica: NFKC + strip + cap 280 + prompt-injection
        # blocker. Misma que aplica el tool path → comportamiento consistente.
        return _validate_fact_content(v)

    @field_validator('source')
    @classmethod
    def validate_source(cls, v: Optional[str]) -> str:
        allowed = {"user_correction", "ai_inferred", "manual"}
        s = (v or "user_correction").strip().lower()
        if s not in allowed:
            return "user_correction"
        return s


@app.post("/api/ai/remember")
def ai_remember(
    data: AIRememberIn,
    request: Request,
    uid: int = Depends(get_current_user),
):
    """Persiste un hecho del user para que el bot lo recuerde en chats futuros.

    Hard-cap a MAX_ACTIVE_FACTS (50) activos y MAX_TOTAL_FACTS (200) total
    por user. Cap atómico via INSERT-WHERE (no race window).

    Rate-limited a 20/hora por user — sin esto, un token comprometido puede
    spamear inserts y forzar invalidaciones de cache (afecta latencia + costo
    LLM en re-runs).
    """
    _check_rate_limit(request, max_calls=20, window_seconds=3600, suffix=f"ai_remember:{uid}")
    conn = get_db()
    try:
        result = _atomic_insert_fact(conn, uid, data.content, data.source)
        if result is None:
            # Chocó con cap (activos o total). Le devolvemos al user un mensaje
            # claro — no diferenciamos los dos caps porque la acción del user
            # es la misma (desactivar/borrar facts viejos).
            raise HTTPException(
                409,
                f"Llegaste al máximo de hechos guardados ({MAX_ACTIVE_FACTS} activos o {MAX_TOTAL_FACTS} totales). Desactiva alguno antes de agregar más.",
            )
        # Invalidar cache de IA — los facts cambian el system prompt y por
        # ende la salida de los packets descriptivos también puede cambiar.
        _ai_cache_invalidate(uid)
        log.info("ai_remember: uid=%d id=%d content=%r", uid, result["id"], data.content[:80])
        return result
    finally:
        conn.close()


@app.get("/api/ai/facts")
def ai_list_facts(
    include_inactive: bool = False,
    uid: int = Depends(get_current_user),
):
    """Lista facts del user. Por default solo activos (los que se inyectan).
    `include_inactive=true` trae todo para la UI de gestión."""
    conn = get_db()
    try:
        if include_inactive:
            rows = conn.execute(
                """SELECT id, content, source, is_active, created_at, updated_at
                   FROM ai_user_facts WHERE user_id=?
                   ORDER BY is_active DESC, created_at DESC""",
                (uid,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, content, source, is_active, created_at, updated_at
                   FROM ai_user_facts WHERE user_id=? AND is_active=1
                   ORDER BY created_at DESC""",
                (uid,),
            ).fetchall()
        return {"facts": [dict(r) for r in rows], "count": len(rows)}
    finally:
        conn.close()


@app.delete("/api/ai/facts/{fact_id}")
def ai_delete_fact(
    fact_id: int,
    request: Request,
    uid: int = Depends(get_current_user),
):
    """Soft-delete (toggle is_active=0). No borra la fila — mantiene historial
    de auditoría. Si el user lo vuelve a querer, lo reactiva (futuro endpoint).

    Rate-limited a 60/hora — el user legítimamente puede limpiar varios
    facts seguidos desde la UI, pero no infinitos (evita ciclo
    insert→delete→insert que bloataría la tabla).
    """
    _check_rate_limit(request, max_calls=60, window_seconds=3600, suffix=f"ai_delete_fact:{uid}")
    conn = get_db()
    try:
        # Verificar ownership ANTES de mutar (defensa contra IDOR)
        row = conn.execute(
            "SELECT id FROM ai_user_facts WHERE id=? AND user_id=?",
            (fact_id, uid),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Hecho no encontrado")
        conn.execute(
            "UPDATE ai_user_facts SET is_active=0, updated_at=datetime('now') "
            "WHERE id=? AND user_id=?",
            (fact_id, uid),
        )
        conn.commit()
        _ai_cache_invalidate(uid)
        return {"ok": True, "id": fact_id}
    finally:
        conn.close()


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
_import_helpers._recalc_pnl_realized_from_ops = _recalc_pnl_realized_from_ops


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


@app.get("/api/imports/parsers/grouped")
def import_parsers_grouped(uid: int = Depends(get_current_user)):
    """Lista los parsers agrupados por plataforma (dropdown a 2 niveles)."""
    return _import_pipeline.parser_options_grouped()


@app.post("/api/imports/inspect")
async def import_inspect(
    file: UploadFile = File(...),
    uid: int = Depends(get_current_user),
):
    """Lee headers y primeras filas del CSV. Devuelve también un mapping
    sugerido (auto-detect) y la lista de campos internos de Rendi para
    armar el wizard de mapeo de columnas."""
    # Lectura chunked + cap progresivo (consistente con /preview): evita
    # OOM si un client manda un archivo de cientos de MB. Cap es el mismo
    # MAX_FILE_BYTES del pipeline.
    cap = _import_pipeline.MAX_FILE_BYTES
    chunks: List[bytes] = []
    total = 0
    while total <= cap:
        chunk = await file.read(min(64 * 1024, cap - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                400,
                f"El archivo excede el límite de {cap // 1_000_000} MB.",
            )
    contents = b"".join(chunks)
    payload = _import_pipeline.inspect(contents)
    if payload.get("error"):
        raise HTTPException(400, payload["error"])
    return payload


@app.post("/api/imports/preview")
async def import_preview(
    files: Optional[List[UploadFile]] = File(None),       # multi-file (preferido)
    file: Optional[UploadFile] = File(None),               # legacy, single file
    broker: Optional[str] = Form(None),
    format: Optional[str] = Form(None),
    mapping: Optional[str] = Form(None),                   # JSON: {"columns":{}, "defaults":{}}
    route_by_currency: Optional[str] = Form(None),         # "1"/"true" → routing per-row
    uid: int = Depends(get_current_user),
):
    """Sube uno o más CSVs y genera el preview unificado. Persiste un batch en
    estado 'preview'. Devuelve session_id (= batch_id) para usar en /confirm.

    Compatibilidad: acepta `file` (un solo CSV — back-compat con clients
    viejos) o `files` (lista — preferido para multi-año de Cocos/etc).
    Si llegan ambos, `files` gana.
    """
    # Resolver input: lista de UploadFile (puede ser uno o varios)
    actual_files: List[UploadFile] = []
    if files:
        actual_files = [f for f in files if f and f.filename]
    elif file:
        actual_files = [file]
    if not actual_files:
        raise HTTPException(400, "Subí al menos un archivo CSV.")
    # Cap de cantidad de archivos — evita un client que abuse pidiendo 1000 files
    if len(actual_files) > 20:
        raise HTTPException(400, "Subiste demasiados archivos (máximo 20).")

    # Cap total con lectura CHUNKED para no bufferear archivos enormes antes
    # de validar. Sin esto, un cliente que manda 1 archivo de 500MB OOM-ea el
    # proceso entero (FastAPI/Starlette no impone cap default).
    MAX_TOTAL_BYTES = _import_pipeline.MAX_TOTAL_BYTES
    file_data: List[tuple] = []  # [(bytes, sanitized_name), ...]
    total_size = 0
    for f in actual_files:
        # Leer en chunks; abortar apenas excedemos el cap (no buffereamos todo).
        chunks: List[bytes] = []
        remaining = MAX_TOTAL_BYTES - total_size + 1  # +1 para detectar overflow
        while remaining > 0:
            chunk = await f.read(min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total_size += len(chunk)
            remaining -= len(chunk)
            if total_size > MAX_TOTAL_BYTES:
                raise HTTPException(
                    400,
                    f"Tamaño total excede {MAX_TOTAL_BYTES // 1_000_000} MB. "
                    "Subí menos archivos o más chicos.",
                )
        data = b"".join(chunks)
        safe_name = _import_pipeline.sanitize_filename(f.filename)
        file_data.append((data, safe_name))

    combined_bytes, combined_name, combine_err = _import_pipeline.combine_csv_files(file_data)
    if combine_err:
        raise HTTPException(400, combine_err)

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
                file_bytes=combined_bytes,
                file_name=combined_name,
                broker_hint=broker,
                parser_format=format,
                mapping=parsed_mapping,
                route_by_currency=flag_route,
            )
        if payload.get("error"):
            # No es 500 — es un error esperado (archivo inválido, formato no soportado).
            raise HTTPException(400, payload["error"])
        # Anotamos cuántos archivos componen el batch (para el preview UI)
        payload["source_file_count"] = len(file_data)
        return payload
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al previsualizar el CSV: {ex}")
    finally:
        conn.close()


class ImportConfirmIn(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=64)
    skip_row_indices: Optional[list] = None  # filas a omitir en este confirm
    # Estado inicial opcional: cash + posiciones que el usuario tenía antes
    # del primer movimiento del CSV. Si está presente, generamos DEPOSITs +
    # BUYs sintéticos al `seed_date` y re-validamos las filas que antes habían
    # fallado por INSUFFICIENT_STOCK (ahora pasan porque hay stock seed).
    seed_state: Optional[dict] = None


@app.post("/api/imports/confirm")
def import_confirm(data: ImportConfirmIn, uid: int = Depends(get_current_user)):
    """Confirma el import: aplica los side-effects y marca el batch como 'confirmed'.
    `skip_row_indices` permite omitir filas específicas que el usuario marcó en
    el preview como problemáticas, sin re-subir el archivo.
    `seed_state` permite cargar un estado inicial sintético cuando el CSV es
    parcial (faltan aportes y posiciones previas)."""
    conn = get_db()
    try:
        with conn:
            try:
                txs, raw_id_by_index = _import_pipeline.load_session_with_seed_revalidate(
                    conn, uid=uid, session_id=data.session_id, seed_state=data.seed_state,
                )
            except ValueError as ex:
                raise HTTPException(400, str(ex))

            # Filtrar filas que el usuario decidió omitir
            skip_set = set(data.skip_row_indices or [])
            if skip_set:
                txs = [t for t in txs if t.row_index not in skip_set]

            try:
                summary = _import_persister.persist_batch(
                    conn,
                    uid=uid,
                    batch_id=data.session_id,
                    txs=txs,
                    raw_row_ids_by_index=raw_id_by_index,
                    helpers=_import_helpers,
                    seed_state=data.seed_state,
                )
            except _import_persister.PersistError as ex:
                raise HTTPException(400, f"Error en fila {ex.row_index}: {ex.message}")

            # Auto-recalc post-import: el persister es incremental (cada tx
            # actualiza monthly_entries por separado vía _update_monthly_*).
            # Si quedó drift residual de cycles previos (capital_inicio
            # negativo, pnl_unrealized stale), corremos el recalc canónico
            # para garantizar que los aggregates queden consistentes. Es
            # idempotente — re-corre la SUM desde operations + import_normalized_tx.
            try:
                _recalc_pnl_realized_from_ops(conn, uid)
            except Exception:
                # No queremos hacer fallar el confirm si el recalc rompe — el
                # batch ya está persistido. Loggeamos pero seguimos.
                import traceback
                traceback.print_exc()

        return {"ok": True, "batch_id": data.session_id,
                "skipped_by_user": len(skip_set), **summary}
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


class ImportMappingIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    mapping: dict


@app.get("/api/imports/mappings")
def import_mappings_list(uid: int = Depends(get_current_user)):
    """Lista los mapping templates guardados del usuario."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, name, mapping_json, created_at
                 FROM import_mappings WHERE user_id=? ORDER BY name ASC""",
            (uid,),
        ).fetchall()
        return [
            {"id": r["id"], "name": r["name"], "mapping": json.loads(r["mapping_json"]),
             "created_at": r["created_at"]}
            for r in rows
        ]
    finally:
        conn.close()


@app.post("/api/imports/mappings")
def import_mappings_save(data: ImportMappingIn, uid: int = Depends(get_current_user)):
    """Guarda (o sobrescribe si ya existe el nombre) un mapping template."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """INSERT INTO import_mappings (user_id, name, mapping_json)
                   VALUES (?,?,?)
                   ON CONFLICT(user_id, name) DO UPDATE SET
                     mapping_json = excluded.mapping_json""",
                (uid, data.name.strip(), json.dumps(data.mapping, ensure_ascii=False)),
            )
            row = conn.execute(
                "SELECT id, name, mapping_json, created_at FROM import_mappings WHERE user_id=? AND name=?",
                (uid, data.name.strip()),
            ).fetchone()
        return {"id": row["id"], "name": row["name"],
                "mapping": json.loads(row["mapping_json"]), "created_at": row["created_at"]}
    finally:
        conn.close()


@app.delete("/api/imports/mappings/{mid}")
def import_mappings_delete(mid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    try:
        with conn:
            conn.execute("DELETE FROM import_mappings WHERE id=? AND user_id=?", (mid, uid))
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/imports/recalc-pnl")
def import_recalc_pnl(uid: int = Depends(get_current_user)):
    """Recalcula `monthly_entries.pnl_realized` desde la tabla `operations`.

    Útil cuando cycles previos de import/revert con bugs dejaron drift en el
    P&L acumulado. Después de correr esto, el dashboard refleja exactamente
    la suma de pnl_usd de las operations actuales.

    Idempotente. No borra operations ni positions — sólo recalcula los
    aggregates mensuales. Es seguro de correr en cualquier momento.
    """
    conn = get_db()
    try:
        with conn:
            updates = _recalc_pnl_realized_from_ops(conn, uid)
        return {"recalculated": True, "rows_updated": updates}
    except Exception as ex:
        raise HTTPException(500, f"Error al recalcular P&L: {ex}")
    finally:
        conn.close()


@app.post("/api/imports/{batch_id}/revert")
def import_revert(batch_id: str, nuclear: int = 0, uid: int = Depends(get_current_user)):
    """Reversa todos los side-effects de un batch confirmado.
    En modo safe (default): falla si el batch incluye SELL/FX/FUTURES_PNL.
    En modo nuclear (`?nuclear=1`): hace best-effort de SELL/FX/FUTURES_PNL,
    aceptando drift en tc_compra. Usado por el flujo "Editar y rehacer".
    Sigue fallando si alguna posición creada ya fue vendida después."""
    conn = get_db()
    try:
        with conn:
            try:
                result = _import_persister.revert_batch(
                    conn, uid=uid, batch_id=batch_id, helpers=_import_helpers,
                    nuclear=bool(nuclear),
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


@app.post("/api/imports/{batch_id}/redo")
def import_redo(batch_id: str, uid: int = Depends(get_current_user)):
    """Editar y rehacer: revierte un batch confirmado (en modo nuclear) y
    re-corre el preview con los mismos datos. Devuelve el preview payload
    nuevo para que el frontend abra el wizard ya en la etapa de preview.

    Útil cuando el usuario "subió mal" y quiere ajustar antes de confirmar
    de nuevo (cambiar mapping, agregar seed, omitir filas, etc.)."""
    conn = get_db()
    try:
        # 1) Snapshot del batch original (para preservar parser + settings)
        batch_row = conn.execute(
            "SELECT * FROM import_batches WHERE id=? AND user_id=?", (batch_id, uid),
        ).fetchone()
        if not batch_row:
            raise HTTPException(404, "Batch no encontrado.")
        if batch_row["status"] != "confirmed":
            raise HTTPException(400, f"El batch no está en estado 'confirmed' (actual: {batch_row['status']}).")

        # 2) Reconstruir CSV desde raw_rows ANTES de revertir (al revertir
        #    no borramos raw_rows, pero queda más limpio leerlos antes).
        csv_bytes = _import_pipeline.reconstruct_csv_from_batch(conn, uid=uid, batch_id=batch_id)
        if not csv_bytes:
            raise HTTPException(400, "No pudimos reconstruir los datos del batch para reusarlos.")

        # 3) Revertir el batch con modo nuclear
        with conn:
            try:
                _import_persister.revert_batch(
                    conn, uid=uid, batch_id=batch_id, helpers=_import_helpers,
                    nuclear=True,
                )
            except _import_persister.PersistError as ex:
                raise HTTPException(400, f"No se pudo revertir el batch para reusarlo: {ex.message}")

        # 4) Re-correr el preview con el CSV reconstruido — usando rendi_generic
        #    porque el formato canónico es lo que escribimos al reconstruir.
        with conn:
            payload = _import_pipeline.run_preview(
                conn,
                uid=uid,
                file_bytes=csv_bytes,
                file_name=batch_row["file_name"] or "rehacer.csv",
                broker_hint=batch_row["broker"],
                parser_format="rendi_generic",
                mapping=None,
                route_by_currency=bool(batch_row["route_by_currency"] or 0),
            )
        if payload.get("error"):
            raise HTTPException(400, payload["error"])
        return {
            "preview": payload,
            "original_batch_id": batch_id,
            "original_parser_format": batch_row["parser_format"],
        }
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(500, f"Error al rehacer el import: {ex}")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# Daily snapshot cron — toma snapshot del portfolio de todos los usuarios
# automáticamente, sin depender de que abran el Dashboard.
#
# Schedule: 01:00 UTC = 22:00 ART. Después del cierre NYSE (5pm ET = 22:00 UTC
# en horario estándar) y mucho después del cierre BCBA (17h ART).
#
# Si el server se reinicia justo a la hora del cron, se saltea esa corrida
# (in-process scheduler). Trade-off aceptable para una app personal — al día
# siguiente corre normal. Endpoint admin abajo permite forzar manualmente.
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO)
_snapshot_log = logging.getLogger('snapshots_job')

# Helper que el job usa para obtener el blue. Reusa la lógica + cache existente.
def _get_blue_for_scheduler() -> float:
    blue = _fetch_dolar("blue")
    if blue and blue.get("venta"):
        return float(blue["venta"])
    raise RuntimeError("No se pudo obtener cotización del blue")


def _run_daily_snapshot_job():
    """Wrapper que el scheduler invoca. Pasa la config + cierra logs."""
    try:
        result = run_daily_snapshot(
            db_path=DB_PATH,
            fetch_tc_blue=_get_blue_for_scheduler,
            crypto_yf=CRYPTO_YF,
        )
        _snapshot_log.info(f"Daily snapshot result: {result}")
    except Exception as e:
        _snapshot_log.error(f"Daily snapshot job failed: {e}", exc_info=True)


def _run_subscription_lifecycle_job():
    """Cron diario que mantiene sano el estado de subscripciones:
      - downgrade post-cancelación cuando period_end pasó
      - cleanup de pending abandonadas (>7 días)
      - sync con MP para detectar webhooks perdidos
    """
    from billing import subscriptions as billing_subs
    _sub_log = logging.getLogger("billing.subscriptions")
    try:
        conn = get_db()
        try:
            result = billing_subs.run_lifecycle_job(conn)
            _sub_log.info(f"Subscription lifecycle result: {result}")
        finally:
            conn.close()
    except Exception as e:
        _sub_log.error(f"Subscription lifecycle job failed: {e}", exc_info=True)


# Scheduler in-process
_scheduler = BackgroundScheduler(timezone='UTC')

@app.on_event("startup")
def _validate_rebill_config():
    """Sanity check de la config de Rebill al arrancar.

    Loggea errores (config ausente / mismatch ambiente) y warnings al
    startup, así cuando deployás en Railway ves inmediatamente si algo
    está mal antes de que un user intente pagar.

    No bloquea el startup — si Rebill no está configurado, el resto de
    Rendi sigue funcionando (Free / Plus existente / Coach IA / etc).
    Solo los endpoints de /billing/* van a fallar.
    """
    try:
        from billing import rebill
        result = rebill.validate_config()
        if result["ok"]:
            env_label = "SANDBOX" if result["sandbox"] else "PRODUCCIÓN"
            log.info("Rebill config OK — ambiente: %s", env_label)
        for err in result.get("errors", []):
            log.error("Rebill config ERROR: %s", err)
        for warn in result.get("warnings", []):
            log.warning("Rebill config WARN: %s", warn)
    except Exception as ex:
        log.warning("validate_rebill_config falló: %s", ex)


@app.on_event("startup")
def _prewarm_news_cache():
    """Pre-fetch news del mercado en background al boot. Así el primer user
    que entra ya tiene caché y la página /home carga al instante. No bloquea
    el startup — si yfinance/Google tardan, el server sigue respondiendo.
    """
    import threading
    def worker():
        try:
            import time as _time
            _time.sleep(3)  # dejar que las DB y dependencies estén listas
            specs = (
                [(q, lang, cat) for q, cat, lang in MARKET_NEWS_QUERIES] +
                [('investing', url, lang, cat) for url, cat, lang in INVESTING_FEEDS]
            )
            _ensure_news_batch_parallel(specs, NEWS_MARKET_TTL)
        except Exception as ex:
            logging.getLogger(__name__).warning("prewarm news cache failed: %s", ex)
    threading.Thread(target=worker, daemon=True).start()


@app.on_event("startup")
def _start_scheduler():
    # 01:00 UTC todos los días = 22:00 ART
    _scheduler.add_job(
        _run_daily_snapshot_job,
        CronTrigger(hour=1, minute=0),
        id='daily_snapshot',
        replace_existing=True,
    )
    # 02:00 UTC todos los días — después del snapshot. Bajamos a Free los
    # users con suscripción cancelada+vencida, limpiamos pendings stale,
    # syncronizamos con MP.
    _scheduler.add_job(
        _run_subscription_lifecycle_job,
        CronTrigger(hour=2, minute=0),
        id='subscription_lifecycle',
        replace_existing=True,
    )
    _scheduler.start()
    _snapshot_log.info("Daily snapshot scheduler iniciado (cron: 01:00 UTC)")
    _snapshot_log.info("Subscription lifecycle scheduler iniciado (cron: 02:00 UTC)")


@app.on_event("shutdown")
def _stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


# ─── Admin endpoints ────────────────────────────────────────────────────────

# ─── Reports: timeline + per-period ──────────────────────────────────────────
# Nueva sección "/reportes" rediseñada — timeline narrativa con insights.
# Backend: pure functions en `backend/reporting/`.

from reporting.builder import build_period_report
from reporting.detectors import run_detectors
from reporting.schema import report_to_dict
from reporting.timeline import build_timeline, _compute_user_historical_win_rate, _compute_avg_trades_per_month, _fetch_positions_for_concentration


def _latest_snapshot_value(conn, uid: int) -> Optional[float]:
    row = conn.execute(
        "SELECT total_value FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT 1",
        (uid,),
    ).fetchone()
    return float(row["total_value"]) if row and row["total_value"] is not None else None


def _portfolio_snapshot_summary(conn, uid: int, broker_filter: str = "global",
                                 live_value_override: Optional[float] = None) -> dict:
    """Resumen estático del portfolio actual — independiente del período.
    Útil para enriquecer el endpoint /reports/period cuando el período en
    curso no tiene actividad (día/semana flat) y queremos mostrar igual
    KPIs útiles como capital, # posiciones, deltas históricos, etc.

    Si se pasa `live_value_override`, se usa como "valor actual" en vez del
    último snapshot — útil para reflejar precios live cuando el snapshot del
    día todavía no se generó por cron.
    """
    br_clause = "" if broker_filter == "global" else " AND broker = ?"
    br_args: tuple = () if broker_filter == "global" else (broker_filter,)

    # Último snapshot global (no se desagrega por broker)
    latest_snap = conn.execute(
        "SELECT date, total_value FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT 1",
        (uid,),
    ).fetchone()
    snap_value = float(latest_snap["total_value"]) if latest_snap and broker_filter == "global" else None
    # Si tenemos live override y es global, usamos eso como "ahora";
    # el snap_value se reserva como base para calcular delta_1d (vs cierre).
    if broker_filter == "global" and live_value_override is not None and live_value_override > 0:
        latest_value = live_value_override
        latest_date = _iso_today()
    else:
        latest_value = snap_value
        latest_date = latest_snap["date"] if latest_snap else None

    # Capital aportado neto (cum deposits − cum withdrawals)
    row = conn.execute(
        f"""SELECT COALESCE(SUM(deposits) - SUM(withdrawals), 0) AS net
              FROM monthly_entries
             WHERE user_id = ?{br_clause}""",
        (uid, *br_args),
    ).fetchone()
    cum_deposited = float(row["net"] or 0)

    # # posiciones no-cash abiertas (qty != 0)
    pos_row = conn.execute(
        f"""SELECT COUNT(*) AS cnt
              FROM positions
             WHERE user_id = ? AND COALESCE(is_cash, 0) = 0
               AND COALESCE(quantity, 0) > 0{br_clause}""",
        (uid, *br_args),
    ).fetchone()
    positions_count = int(pos_row["cnt"] or 0) if pos_row else 0

    # # brokers activos (con al menos 1 posición)
    brk_row = conn.execute(
        """SELECT COUNT(DISTINCT broker) AS cnt
             FROM positions
            WHERE user_id = ? AND COALESCE(quantity, 0) > 0""",
        (uid,),
    ).fetchone()
    brokers_count = int(brk_row["cnt"] or 0) if brk_row else 0

    # Deltas históricos: 1, 7 y 30 días atrás (global, requieren snapshots).
    delta_1d = _snapshot_delta(conn, uid, latest_value, latest_date, days=1) if broker_filter == "global" else None
    delta_7d = _snapshot_delta(conn, uid, latest_value, latest_date, days=7) if broker_filter == "global" else None
    delta_30d = _snapshot_delta(conn, uid, latest_value, latest_date, days=30) if broker_filter == "global" else None

    # YTD: rendimiento desde el 1 de enero del año actual.
    ytd = _ytd_delta(conn, uid, latest_value, latest_date, broker_filter)

    # Última operación cerrada (fecha, asset, broker, pnl).
    last_op_row = conn.execute(
        f"""SELECT date, broker, asset, op_type, pnl_usd
              FROM operations
             WHERE user_id = ? AND pnl_usd IS NOT NULL{br_clause}
             ORDER BY date DESC, id DESC LIMIT 1""",
        (uid, *br_args),
    ).fetchone()
    last_op = None
    if last_op_row:
        last_op = {
            "date":  last_op_row["date"],
            "asset": last_op_row["asset"],
            "broker": last_op_row["broker"],
            "op_type": last_op_row["op_type"],
            "pnl_usd": float(last_op_row["pnl_usd"]) if last_op_row["pnl_usd"] is not None else None,
        }

    # Top 3 holdings por valor invertido — proxy útil de "qué tenés más"
    top_rows = conn.execute(
        f"""SELECT asset, broker, COALESCE(invested, 0) AS invested
              FROM positions
             WHERE user_id = ? AND COALESCE(is_cash, 0) = 0
               AND COALESCE(quantity, 0) > 0{br_clause}
             ORDER BY COALESCE(invested, 0) DESC LIMIT 3""",
        (uid, *br_args),
    ).fetchall()
    top_holdings = [
        {"asset": r["asset"], "broker": r["broker"], "invested": float(r["invested"] or 0)}
        for r in top_rows
    ]

    # Cash % del portfolio (sumando positions is_cash)
    cash_row = conn.execute(
        f"""SELECT COALESCE(SUM(invested), 0) AS cash
              FROM positions
             WHERE user_id = ? AND COALESCE(is_cash, 0) = 1{br_clause}""",
        (uid, *br_args),
    ).fetchone()
    cash_value = float(cash_row["cash"] or 0) if cash_row else 0.0

    return {
        "latest_value": latest_value,
        "latest_date": latest_date,
        "cum_deposited": cum_deposited,
        "positions_count": positions_count,
        "brokers_count": brokers_count,
        "delta_1d": delta_1d,
        "delta_7d": delta_7d,
        "delta_30d": delta_30d,
        "ytd": ytd,
        "last_op": last_op,
        "top_holdings": top_holdings,
        "cash_value": cash_value,
    }


def _snapshot_delta(conn, uid: int, latest_value: Optional[float],
                    latest_date: Optional[str], days: int) -> Optional[dict]:
    """Variación del portfolio (USD + %) entre el snapshot más reciente y
    el snapshot más cercano a N días atrás.

    Devuelve `prev_date` para que el frontend pueda mostrar "vs vie 15 may"
    en lugar de "Δ último día" (que puede ser engañoso si hubo gap por
    fin de semana o feriado).

    Devuelve None si no hay data.
    """
    if latest_value is None or latest_date is None:
        return None
    from datetime import date as _date, timedelta as _td
    try:
        target = (_date.fromisoformat(latest_date) - _td(days=days)).isoformat()
    except ValueError:
        return None
    prev = conn.execute(
        "SELECT date, total_value FROM snapshots WHERE user_id=? AND date<=? ORDER BY date DESC LIMIT 1",
        (uid, target),
    ).fetchone()
    if not prev or prev["total_value"] is None:
        return None
    prev_v = float(prev["total_value"])
    if prev_v <= 0:
        return None
    return {
        "usd": round(latest_value - prev_v, 2),
        "pct": round(((latest_value - prev_v) / prev_v) * 100, 2),
        "prev_date": prev["date"],
    }


def _ytd_delta(conn, uid: int, latest_value: Optional[float],
               latest_date: Optional[str], broker_filter: str) -> Optional[dict]:
    """% YTD del portfolio — desde el capital_inicio del primer mes del año
    actual (de monthly_entries) hasta latest_value.

    `since_date` indica desde qué mes/día se mide. Útil para frontend cuando
    el user empezó a usar la app después de enero — muestra "Desde mayo 2026"
    en lugar de un confuso "YTD 2026" que sugiere desde 1 enero.

    Devuelve None si no hay datos para el año en curso.
    """
    if latest_value is None or latest_date is None:
        return None
    year = int(latest_date[:4])
    row = conn.execute(
        """SELECT month, capital_inicio
             FROM monthly_entries
            WHERE user_id = ? AND broker = ? AND year = ?
            ORDER BY month ASC LIMIT 1""",
        (uid, broker_filter, year),
    ).fetchone()
    if not row or row["capital_inicio"] is None:
        return None
    start = float(row["capital_inicio"])
    if start <= 0:
        return None
    first_month = int(row["month"])
    return {
        "usd": round(latest_value - start, 2),
        "pct": round(((latest_value - start) / start) * 100, 2),
        "since_year": year,
        "since_month": first_month,
        "since_date": f"{year:04d}-{first_month:02d}-01",
        # Frontend usa esto: si first_month != 1, mostrar "Desde {month} {year}"
        "is_partial_year": first_month != 1,
    }


def _user_tc_blue(conn, uid: int) -> float:
    row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        v = float(row["value"]) if row else 1415.0
        return v if v > 0 else 1415.0
    except (TypeError, ValueError):
        return 1415.0


@app.get("/api/reports/timeline")
def reports_timeline(
    broker: str = "global",
    months: int = 12,
    uid: int = Depends(get_current_user),
):
    """Timeline cronológica condensada — últimos N meses, con semanas anidadas.

    Cada PeriodReport viene con:
    - métricas (start/end value, delta_pct TWRR, realized, etc.)
    - headline narrativo (1-2 oraciones generadas)
    - insights (chips con evidencia)
    - highlights (best/worst op del período)
    - drivers (atribución por activo)

    El frontend renderiza con jerarquía: mes en curso expandido, meses pasados
    colapsados (header + delta). Click expande para ver semanas + insights.
    """
    if months < 1 or months > 36:
        raise HTTPException(400, "months debe estar entre 1 y 36")
    conn = get_db()
    try:
        bench_data = {
            "inflation_ar": _fetch_inflation_ar(),
            "sp500": _fetch_sp500_monthly(),
        }
        # live_value es el TOTAL del portfolio (snapshots no se desagregan
        # por broker). Solo aplica como end_value del mes en curso cuando
        # el reporte es global; con broker_filter se cae al capital_final
        # del monthly_entry, que ya incluye unrealized de ese broker.
        live_value = _latest_snapshot_value(conn, uid) if broker == "global" else None
        tc_blue = _user_tc_blue(conn, uid)
        timeline = build_timeline(
            conn, uid, broker_filter=broker, months=months,
            bench=bench_data, live_value=live_value,
            prices={}, tc_blue=tc_blue,
        )
        return {
            "broker": broker,
            "months_requested": months,
            "reports": [report_to_dict(r) for r in timeline],
        }
    finally:
        conn.close()


@app.get("/api/reports/period/{period_type}/{period_key}")
def reports_period_detail(
    period_type: str, period_key: str,
    broker: str = "global",
    uid: int = Depends(get_current_user),
):
    """Detalle de un período específico — útil para deep-link o expandir un
    week/day sin pegarle a la timeline completa."""
    if period_type not in ("day", "week", "month", "year"):
        raise HTTPException(400, "period_type inválido")
    conn = get_db()
    try:
        bench_data = {
            "inflation_ar": _fetch_inflation_ar(),
            "sp500": _fetch_sp500_monthly(),
        }
        tc_blue = _user_tc_blue(conn, uid)
        # Para el período en curso (day/week/year actual) usamos el valor
        # LIVE del portfolio (positions × precios) si está disponible.
        # Esto permite ver el delta intraday vs cierre de ayer / lunes /
        # 1 enero, aunque el cron del snapshot diario todavía no haya corrido.
        from datetime import date as _date
        live_value = None
        is_current_period_for_live = False
        if broker == "global":
            live_value = _latest_snapshot_value(conn, uid)
            today = _date.today()
            if period_type == "day" and period_key == _iso_today():
                is_current_period_for_live = True
            elif period_type == "week":
                iy, iw, _wd = today.isocalendar()
                if period_key == f"{iy}-W{iw:02d}":
                    is_current_period_for_live = True
            elif period_type == "year" and period_key == str(today.year):
                is_current_period_for_live = True
            if is_current_period_for_live:
                try:
                    lv = compute_live_portfolio_value(conn, uid, tc_blue, CRYPTO_YF)
                    if lv is not None and lv > 0:
                        live_value = lv
                except Exception:
                    pass  # fallback a snapshot latest
        try:
            report = build_period_report(
                conn, uid, period_type, period_key,
                broker_filter=broker, bench=bench_data, live_value=live_value,
            )
        except ValueError as ex:
            raise HTTPException(400, str(ex))

        # Detectores con contexto completo
        positions = _fetch_positions_for_concentration(conn, uid, broker, {}, tc_blue)
        report.insights = run_detectors(
            report,
            positions=positions,
            avg_trades_per_period=_compute_avg_trades_per_month(conn, uid),
            historical_win_rate=_compute_user_historical_win_rate(conn, uid),
        )
        out = report_to_dict(report)
        # Enriquecemos con snapshot estático del portfolio — útil cuando el
        # período en curso (día/semana) está flat y queremos mostrar igual
        # capital actual, # posiciones, etc.
        # Pasamos el live_value calculado para que delta_1d refleje el
        # cambio real entre el cierre de ayer y los precios live de hoy.
        out["portfolio_snapshot"] = _portfolio_snapshot_summary(
            conn, uid, broker,
            live_value_override=(live_value if is_current_period_for_live else None),
        )
        return out
    finally:
        conn.close()


# ─── Home: market data + briefing personalizado ──────────────────────────────
# Nueva landing page `/home` (mostrada como primer ítem del navbar).
# Composición: índices + heatmap S&P + movers + cards personales + news/events.
# Backend: módulo `home/` con pure functions + cache in-memory.

from home.market import (
    get_indices_strip,
    get_heatmap,
    get_movers,
    _fetch_batch_quotes,
    MARKETS,
)
from home.briefing import build_personal_cards


@app.get("/api/home/indices")
def home_indices(uid: int = Depends(get_current_user)):
    """Strip superior: S&P, Nasdaq, Merval, BTC, ETH, Oro."""
    return {"items": get_indices_strip()}


@app.get("/api/home/heatmap")
def home_heatmap(market: str = "sp500", uid: int = Depends(get_current_user)):
    """Heatmap del mercado. V1.5 soporta sp500 / merval / crypto."""
    if market not in MARKETS:
        raise HTTPException(400, f"Mercado no soportado: {market}")
    return {"market": market, "label": MARKETS[market]["label"], "blocks": get_heatmap(market)}


@app.get("/api/home/movers")
def home_movers(market: str = "sp500", uid: int = Depends(get_current_user)):
    """Top 5 gainers + top 5 losers del día."""
    if market not in MARKETS:
        raise HTTPException(400, f"Mercado no soportado: {market}")
    return get_movers(market)


# ─── Watchlist (Home V1.5) ───────────────────────────────────────────────────

class WatchlistAddIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    asset_type: Optional[str] = Field(None, max_length=20)

    @field_validator('symbol')
    @classmethod
    def normalize_symbol(cls, v):
        v = v.strip().upper()
        if not re.match(r'^[A-Z0-9]{1,10}(\.BA|-USD)?$', v):
            raise ValueError('Símbolo inválido')
        return v


@app.get("/api/watchlist")
def watchlist_list(uid: int = Depends(get_current_user)):
    """Devuelve los tickers en watchlist + quote actual (price + change_pct)."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, symbol, asset_type, added_at
                 FROM watchlist
                WHERE user_id = ?
                ORDER BY added_at DESC""",
            (uid,),
        ).fetchall()
        items = [dict(r) for r in rows]
        # Enrich con quotes (batch)
        symbols = [it["symbol"] for it in items]
        quotes = _fetch_batch_quotes(symbols) if symbols else {}
        for it in items:
            q = quotes.get(it["symbol"])
            it["price"] = q["price"] if q else None
            it["change_pct"] = q["change_pct"] if q else None
        return {"items": items}
    finally:
        conn.close()


@app.post("/api/watchlist")
def watchlist_add(data: WatchlistAddIn, uid: int = Depends(get_current_user)):
    """Agrega un símbolo a la watchlist. Si ya existe, devuelve 200 silenciosamente
    (idempotente para el flow "Agregar a watchlist" desde la UI)."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO watchlist (user_id, symbol, asset_type)
                   VALUES (?, ?, ?)""",
                (uid, data.symbol, data.asset_type),
            )
        return {"ok": True, "symbol": data.symbol}
    finally:
        conn.close()


@app.delete("/api/watchlist/{symbol}")
def watchlist_remove(symbol: str, uid: int = Depends(get_current_user)):
    """Borra un símbolo de la watchlist."""
    sym = symbol.strip().upper()
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
                (uid, sym),
            )
        return {"ok": True, "symbol": sym}
    finally:
        conn.close()


# ─── Push notifications (Sprint M4) ──────────────────────────────────────────
# Web Push (VAPID). Funciona en Chrome/Firefox/Edge desktop + Android. iOS Safari
# desde 16.4 PERO solo si la app está "instalada" como PWA (Add to Home Screen).
#
# Flow:
#   1. Frontend pide VAPID_PUBLIC_KEY al backend.
#   2. Frontend llama navigator.serviceWorker → registration.pushManager.subscribe()
#      pasando el public key. El browser genera un endpoint único + claves de
#      cifrado (p256dh + auth).
#   3. Frontend manda esos datos a POST /api/push/subscribe.
#   4. Backend guarda la sub. Cuando hay evento → carga subs del user → llama
#      send_push() con pywebpush firmando con el VAPID_PRIVATE_KEY.
#
# Si el push gateway devuelve 404/410, la sub está muerta → la borramos.


class PushSubIn(BaseModel):
    endpoint: str = Field(..., max_length=2000)
    p256dh: str = Field(..., max_length=200)
    auth: str = Field(..., max_length=200)
    user_agent: Optional[str] = Field(None, max_length=500)


@app.get("/api/push/vapid-public-key")
def push_vapid_public_key():
    """Devuelve la public key VAPID para que el frontend la use al subscribirse.
    Endpoint público (no requiere auth) — la public key no es secreta."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Push no configurado (falta VAPID_PUBLIC_KEY)")
    return {"public_key": key}


@app.post("/api/push/subscribe")
def push_subscribe(sub: PushSubIn, uid: int = Depends(get_current_user)):
    """Guarda la subscripción push del device del user.
    Idempotente: si ya existe el endpoint, actualiza los datos."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                """INSERT INTO push_subscriptions
                   (user_id, endpoint, p256dh, auth, user_agent, last_used_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(user_id, endpoint) DO UPDATE SET
                     p256dh = excluded.p256dh,
                     auth = excluded.auth,
                     user_agent = excluded.user_agent,
                     last_used_at = datetime('now')""",
                (uid, sub.endpoint, sub.p256dh, sub.auth, sub.user_agent),
            )
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/push/subscribe")
def push_unsubscribe(sub: PushSubIn, uid: int = Depends(get_current_user)):
    """Borra la subscripción push de este device. El frontend llama acá cuando
    el user desactiva las notificaciones."""
    conn = get_db()
    try:
        with conn:
            conn.execute(
                "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
                (uid, sub.endpoint),
            )
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/push/status")
def push_status(uid: int = Depends(get_current_user)):
    """Cuenta cuántas subs tiene este user. Útil para que el UI sepa si está
    suscrito en al menos un device."""
    conn = get_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        return {"subscribed_devices": count}
    finally:
        conn.close()


def _send_push_to_user(uid: int, payload: dict) -> int:
    """Envía un push a TODOS los devices del user. Devuelve cantidad enviados.

    Si un endpoint devuelve 404/410 (Gone), borra la sub. Otros errores se
    logean pero no propagan.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return 0
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    subject = os.environ.get("VAPID_SUBJECT", "mailto:hola@rendi.finance").strip()
    if not pub or not priv:
        return 0

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
            (uid,),
        ).fetchall()
        sent = 0
        for r in rows:
            sub_info = {
                "endpoint": r["endpoint"],
                "keys": {"p256dh": r["p256dh"], "auth": r["auth"]},
            }
            try:
                webpush(
                    subscription_info=sub_info,
                    data=json.dumps(payload),
                    vapid_private_key=priv,
                    vapid_claims={"sub": subject},
                    ttl=86400,  # 24h
                )
                sent += 1
            except WebPushException as ex:
                status = getattr(getattr(ex, "response", None), "status_code", None)
                if status in (404, 410):
                    # Endpoint muerto — borrar
                    with conn:
                        conn.execute(
                            "DELETE FROM push_subscriptions WHERE id = ?", (r["id"],)
                        )
                else:
                    log.warning(f"push send fallo (sub {r['id']}, status {status}): {ex}")
        return sent
    finally:
        conn.close()


@app.post("/api/push/test")
def push_test(uid: int = Depends(get_current_user)):
    """Manda un push de prueba al user actual. Sirve para verificar que la
    config end-to-end funciona (VAPID + SW + permisos del browser)."""
    sent = _send_push_to_user(uid, {
        "title": "Rendi · Test",
        "body": "Si ves esta notificación, todo está funcionando ✓",
        "url": "/insights",
        "tag": "test",
    })
    return {"sent": sent}


@app.get("/api/home/personal")
def home_personal(uid: int = Depends(get_current_user)):
    """Cards "Lo que te afecta" — holdings que se mueven + earnings próximos.

    Reusa quotes del heatmap (cacheadas) + lista de eventos del portfolio.
    Si el user no tiene holdings, devuelve cards vacío.
    """
    conn = get_db()
    try:
        # Holdings del user → símbolos para fetchear quotes.
        # Bumeamos el cap a 100 (antes 30) para no recortar arbitrariamente
        # portfolios diversificados — el _fetch_batch_quotes es un solo download.
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
                WHERE user_id = ? AND is_cash = 0
                  AND quantity > 0
                  AND asset NOT LIKE '%-%'  -- excluir cash-like duplicates
                LIMIT 100""",
            (uid,),
        ).fetchall()
        symbols = [r["asset"] for r in rows if r["asset"]]
        all_quotes = _fetch_batch_quotes(symbols) if symbols else {}

        # Eventos del portfolio (reuso de _get_portfolio_events si existe;
        # sino devolvemos lista vacía)
        try:
            events = _get_portfolio_events_cached(uid)
        except Exception:
            events = []

        cards = build_personal_cards(
            conn, uid,
            all_quotes=all_quotes,
            portfolio_events=events,
        )
        return {"cards": cards}
    finally:
        conn.close()


def _get_portfolio_events_cached(uid: int) -> list:
    """Helper que reusa la lógica de /api/events/portfolio sin re-pegar al fetcher.
    Por simplicidad consultamos directo a la tabla `events` con los tickers del user."""
    conn = get_db()
    try:
        # Tickers del user
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
                WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
            (uid,),
        ).fetchall()
        tickers = [r["asset"] for r in rows if r["asset"]]
        if not tickers:
            return []
        # Buscar eventos en próximos 14 días para esos tickers
        from datetime import date as _date, timedelta as _td
        today = _date.today().isoformat()
        cutoff = (_date.today() + _td(days=14)).isoformat()
        placeholders = ",".join("?" * len(tickers))
        events = conn.execute(
            f"""SELECT ticker, event_type, event_date, details, confirmed
                  FROM events
                 WHERE ticker IN ({placeholders})
                   AND event_date >= ? AND event_date <= ?
                 ORDER BY event_date ASC""",
            (*tickers, today, cutoff),
        ).fetchall()
        return [dict(e) for e in events]
    finally:
        conn.close()


@app.post("/api/admin/snapshots/run-now")
def admin_run_snapshot(uid: int = Depends(get_admin_user)):
    """Triggea el job manualmente — útil para testing y para forzar un
    snapshot fuera del horario programado.

    Solo accesible por usuarios admin.
    """
    result = run_daily_snapshot(
        db_path=DB_PATH,
        fetch_tc_blue=_get_blue_for_scheduler,
        crypto_yf=CRYPTO_YF,
    )
    return result


# ─── Health check (público) ─────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    """Endpoint público sin auth — sirve para:

    1. Despertar la app si está hibernada (Railway auto-sleep). Configurá
       un cron en cron-job.org que pingue esta URL ~5 min antes del horario
       del daily snapshot (01:00 UTC) y la app se levanta antes.
    2. Monitoreo / uptime checks (UptimeRobot, etc.)

    Devuelve siempre 200 con timestamp para que el caller verifique que
    la app está respondiendo.
    """
    return {
        "ok": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "rendi-api",
    }
