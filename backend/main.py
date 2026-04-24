from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import sqlite3, os
import yfinance as yf
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta

SECRET_KEY = os.environ.get("SECRET_KEY", "rendi-dev-secret-change-in-prod")
ALGORITHM = "HS256"
TOKEN_DAYS = 30

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "trading.db"))

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer()

app = FastAPI(title="Rendi")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_cols(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def init_db():
    conn = get_db()

    # Users and brokers are always new tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS brokers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USDT',
            UNIQUE(user_id, name)
        );
    """)
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
    conn.commit()
    conn.close()


init_db()


# ─── Auth ────────────────────────────────────────────────────────────────────

def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.utcnow() + timedelta(days=TOKEN_DAYS)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Token inválido")


ARS_BROKER_NAMES = {'cocos', 'iol', 'bull', 'balanz', 'lemon', 'naranja', 'pppi', 'invertironline'}


class RegisterIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def register(data: RegisterIn):
    conn = get_db()
    try:
        h = pwd_ctx.hash(data.password)
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash) VALUES (?,?,?)",
            (data.email.lower().strip(), data.name, h),
        )
        uid = cur.lastrowid

        # First user claims all legacy data (user_id=0) and gets auto-brokers
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 1:
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

        # Default config (only insert if not already present after migration)
        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_mep', '1415', ?)", (uid,))
        conn.execute("INSERT OR IGNORE INTO config VALUES ('tc_blue', '1415', ?)", (uid,))

        conn.commit()
        conn.close()
        return {"token": create_token(uid), "name": data.name or data.email}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Email ya registrado")


@app.post("/api/auth/login")
def login(data: LoginIn):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=?", (data.email.lower().strip(),)).fetchone()
    conn.close()
    if not row or not pwd_ctx.verify(data.password, row["password_hash"]):
        raise HTTPException(401, "Credenciales inválidas")
    return {"token": create_token(row["id"]), "name": row["name"] or row["email"]}


@app.get("/api/auth/me")
def me(uid: int = Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT id, email, name FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return dict(row)


# ─── Brokers ─────────────────────────────────────────────────────────────────

class BrokerIn(BaseModel):
    name: str
    currency: str = 'USDT'


@app.get("/api/brokers")
def get_brokers(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM brokers WHERE user_id=? ORDER BY name", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/brokers")
def create_broker(data: BrokerIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (uid, data.name, data.currency),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM brokers WHERE id=?", (cur.lastrowid,)).fetchone()
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
    row = conn.execute("SELECT * FROM brokers WHERE id=?", (bid,)).fetchone()
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
    tc_mep: Optional[float] = None
    tc_blue: Optional[float] = None


@app.get("/api/config")
def get_config(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    cfg = {r["key"]: float(r["value"]) for r in rows}
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


# ─── Prices ──────────────────────────────────────────────────────────────────

import math

# All symbols that should be fetched as SYMBOL-USD on Yahoo Finance
CRYPTO_SYMBOLS = {
    # Large-cap
    'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOGE', 'TRX', 'DOT',
    'MATIC', 'POL', 'LINK', 'LTC', 'BCH', 'NEAR', 'UNI', 'ATOM', 'XLM', 'ETC',
    # Mid-cap / DeFi
    'APT', 'ARB', 'OP', 'AAVE', 'MKR', 'SNX', 'CRV', 'COMP', 'SUSHI', 'YFI',
    '1INCH', 'BAL', 'DYDX', 'GMX', 'BLUR', 'GRT', 'LRC', 'ZRX', 'BAT', 'REN',
    # Layer-1 / Alt
    'ALGO', 'VET', 'EGLD', 'FTM', 'FLOW', 'HBAR', 'THETA', 'XTZ', 'EOS', 'WAVES',
    'ZIL', 'NEO', 'QTUM', 'ICX', 'ONT', 'IOTA', 'ZEC', 'DASH', 'XMR', 'KAVA',
    # NFT / Gaming / Metaverse
    'SAND', 'MANA', 'AXS', 'ENJ', 'IMX', 'FLOW', 'CHZ', 'GALA', 'GODS', 'ILV',
    # Meme
    'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'DEGEN',
    # New / trending
    'SUI', 'SEI', 'TIA', 'INJ', 'JTO', 'PYTH', 'STRK', 'WLD', 'MANTA', 'ALT',
    'ORDI', 'RUNE', 'FIL', 'STX', 'CORE', 'CFX', 'BLUR', 'ID', 'ARKM', 'CYBER',
    'RDNT', 'GMX', 'APE', 'LDO', 'RPL', 'FXS', 'CVX', 'FRAX', 'PENDLE', 'SSV',
    # Stablecoins adjacent / wrapped (usually need price for tracking)
    'WBTC', 'STETH',
}

CRYPTO_YF = {sym: f"{sym}-USD" for sym in CRYPTO_SYMBOLS}


def _fetch_one(yf_ticker: str):
    try:
        hist = yf.Ticker(yf_ticker).history(period="5d")
        if hist.empty:
            return None
        val = float(hist["Close"].dropna().iloc[-1])
        return val if not math.isnan(val) and val > 0 else None
    except Exception:
        return None


@app.get("/api/prices")
def get_prices(symbols: str, uid: int = Depends(get_current_user)):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {}

    # Build mapping: original symbol → yfinance ticker
    sym_to_yf = {}
    for sym in sym_list:
        sym_to_yf[sym] = CRYPTO_YF[sym] if sym in CRYPTO_YF else sym

    yf_tickers = list(set(sym_to_yf.values()))
    result = {sym: None for sym in sym_list}

    # --- Batch download (fast path) ---
    try:
        tickers_str = " ".join(yf_tickers)
        data = yf.download(tickers_str, period="5d", progress=False, auto_adjust=True)

        if not data.empty:
            close = data.get("Close") if hasattr(data, 'get') else (data["Close"] if "Close" in data.columns else None)

            if close is not None and not (hasattr(close, 'empty') and close.empty):
                # Drop rows that are all NaN, get last valid row
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

    # --- Individual fallback for anything that failed ---
    for sym in [s for s in sym_list if result[s] is None]:
        yf_t = sym_to_yf[sym]
        price = _fetch_one(yf_t)

        # If not found and not a .BA stock, try as crypto (SYMBOL-USD)
        if price is None and not sym.endswith('.BA') and sym not in CRYPTO_YF:
            price = _fetch_one(f"{sym}-USD")

        result[sym] = price

    return result


# ─── Positions ───────────────────────────────────────────────────────────────

class PositionIn(BaseModel):
    broker: str
    asset: str
    is_cash: bool = False
    buy_price: Optional[float] = None
    quantity: Optional[float] = None
    invested: Optional[float] = None
    tc_compra: Optional[float] = None
    price_override: Optional[float] = None
    notes: Optional[str] = None


@app.get("/api/positions")
def get_positions(uid: int = Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM positions WHERE user_id=? ORDER BY broker, id", (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/positions")
def create_position(p: PositionIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
           invested, tc_compra, price_override, notes) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (uid, p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
         p.invested, p.tc_compra, p.price_override, p.notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/positions/{pid}")
def update_position(pid: int, p: PositionIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        """UPDATE positions SET broker=?, asset=?, is_cash=?, buy_price=?, quantity=?,
           invested=?, tc_compra=?, price_override=?, notes=? WHERE id=? AND user_id=?""",
        (p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
         p.invested, p.tc_compra, p.price_override, p.notes, pid, uid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
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


# ─── Monthly ─────────────────────────────────────────────────────────────────

class MonthlyIn(BaseModel):
    year: int
    month: int
    broker: str
    deposits: float = 0
    withdrawals: float = 0
    pnl_realized: float = 0
    pnl_unrealized: float = 0
    capital_inicio: float = 0
    capital_final: float = 0


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
    try:
        cur = conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker, deposits, withdrawals,
               pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (uid, e.year, e.month, e.broker, e.deposits, e.withdrawals,
             e.pnl_realized, e.pnl_unrealized, e.capital_inicio, e.capital_final),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM monthly_entries WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Ya existe una entrada para ese mes/broker")


@app.put("/api/monthly/{eid}")
def update_monthly(eid: int, e: MonthlyIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        """UPDATE monthly_entries SET deposits=?, withdrawals=?, pnl_realized=?,
           pnl_unrealized=?, capital_inicio=?, capital_final=? WHERE id=? AND user_id=?""",
        (e.deposits, e.withdrawals, e.pnl_realized, e.pnl_unrealized,
         e.capital_inicio, e.capital_final, eid, uid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM monthly_entries WHERE id=?", (eid,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/monthly/{eid}")
def delete_monthly(eid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM monthly_entries WHERE id=? AND user_id=?", (eid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Operations ──────────────────────────────────────────────────────────────

class OperationIn(BaseModel):
    date: str
    broker: str
    asset: str
    op_type: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    quantity: Optional[float] = None
    pnl_usd: float = 0
    pnl_pct: Optional[float] = None


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
           quantity, pnl_usd, pnl_pct) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (uid, op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM operations WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/operations/{oid}")
def update_operation(oid: int, op: OperationIn, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute(
        """UPDATE operations SET date=?, broker=?, asset=?, op_type=?, entry_price=?,
           exit_price=?, quantity=?, pnl_usd=?, pnl_pct=? WHERE id=? AND user_id=?""",
        (op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct, oid, uid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/operations/{oid}")
def delete_operation(oid: int, uid: int = Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM operations WHERE id=? AND user_id=?", (oid, uid))
    conn.commit()
    conn.close()
    return {"ok": True}
