from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
import yfinance as yf

# En Railway: montá un volumen en /data y seteá DB_PATH=/data/trading.db
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "trading.db"))

app = FastAPI(title="Rendi")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        CREATE TABLE IF NOT EXISTS monthly_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            broker TEXT NOT NULL,
            deposits REAL DEFAULT 0,
            withdrawals REAL DEFAULT 0,
            pnl_realized REAL DEFAULT 0,
            pnl_unrealized REAL DEFAULT 0,
            capital_inicio REAL DEFAULT 0,
            capital_final REAL DEFAULT 0,
            UNIQUE(year, month, broker)
        );
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        INSERT OR IGNORE INTO config VALUES ('tc_mep', '1415');
        INSERT OR IGNORE INTO config VALUES ('tc_blue', '1415');
    """)
    conn.commit()
    conn.close()


init_db()

# ─── Config ──────────────────────────────────────────────────────────────────

@app.get("/api/config")
def get_config():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    return {r["key"]: float(r["value"]) for r in rows}


class ConfigUpdate(BaseModel):
    tc_mep: Optional[float] = None
    tc_blue: Optional[float] = None


@app.put("/api/config")
def update_config(data: ConfigUpdate):
    conn = get_db()
    if data.tc_mep is not None:
        conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_mep', ?)", (str(data.tc_mep),))
    if data.tc_blue is not None:
        conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_blue', ?)", (str(data.tc_blue),))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Prices ──────────────────────────────────────────────────────────────────

# Crypto mapped to yfinance Yahoo Finance tickers (more reliable than CoinGecko free tier)
CRYPTO_YF = {"BTC": "BTC-USD", "ETH": "ETH-USD", "AAVE": "AAVE-USD", "SOL": "SOL-USD", "BNB": "BNB-USD"}


@app.get("/api/prices")
def get_prices(symbols: str):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    result = {}

    crypto_syms = [s for s in sym_list if s in CRYPTO_YF]
    stock_syms = [s for s in sym_list if s not in CRYPTO_YF]

    # All tickers go through yfinance: stocks/ETFs as-is, crypto as BTC-USD etc.
    yf_tickers = stock_syms + [CRYPTO_YF[s] for s in crypto_syms]

    if yf_tickers:
        try:
            data = yf.download(
                " ".join(yf_tickers),
                period="2d",
                progress=False,
                auto_adjust=True,
            )
            close = data["Close"]
            last = close.iloc[-1]

            if len(yf_tickers) == 1:
                ticker = yf_tickers[0]
                price = float(last) if not hasattr(last, '__len__') else float(last.iloc[0])
                # Map back: crypto YF ticker → original symbol
                reverse = {v: k for k, v in CRYPTO_YF.items()}
                key = reverse.get(ticker, ticker)
                result[key] = price
            else:
                for ticker in yf_tickers:
                    try:
                        price = float(last[ticker])
                        reverse = {v: k for k, v in CRYPTO_YF.items()}
                        key = reverse.get(ticker, ticker)
                        result[key] = price
                    except Exception:
                        reverse = {v: k for k, v in CRYPTO_YF.items()}
                        key = reverse.get(ticker, ticker)
                        result[key] = None
        except Exception as e:
            for s in sym_list:
                result[s] = None

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
def get_positions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM positions ORDER BY broker, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/positions")
def create_position(p: PositionIn):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO positions (broker, asset, is_cash, buy_price, quantity, invested,
           tc_compra, price_override, notes) VALUES (?,?,?,?,?,?,?,?,?)""",
        (p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
         p.invested, p.tc_compra, p.price_override, p.notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/positions/{pid}")
def update_position(pid: int, p: PositionIn):
    conn = get_db()
    conn.execute(
        """UPDATE positions SET broker=?, asset=?, is_cash=?, buy_price=?, quantity=?,
           invested=?, tc_compra=?, price_override=?, notes=? WHERE id=?""",
        (p.broker, p.asset, int(p.is_cash), p.buy_price, p.quantity,
         p.invested, p.tc_compra, p.price_override, p.notes, pid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Not found")
    return dict(row)


@app.delete("/api/positions/{pid}")
def delete_position(pid: int):
    conn = get_db()
    conn.execute("DELETE FROM positions WHERE id=?", (pid,))
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
def get_monthly():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM monthly_entries ORDER BY year, month, broker"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/monthly")
def create_monthly(e: MonthlyIn):
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO monthly_entries (year, month, broker, deposits, withdrawals,
               pnl_realized, pnl_unrealized, capital_inicio, capital_final)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (e.year, e.month, e.broker, e.deposits, e.withdrawals,
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
def update_monthly(eid: int, e: MonthlyIn):
    conn = get_db()
    conn.execute(
        """UPDATE monthly_entries SET deposits=?, withdrawals=?, pnl_realized=?,
           pnl_unrealized=?, capital_inicio=?, capital_final=? WHERE id=?""",
        (e.deposits, e.withdrawals, e.pnl_realized, e.pnl_unrealized,
         e.capital_inicio, e.capital_final, eid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM monthly_entries WHERE id=?", (eid,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/monthly/{eid}")
def delete_monthly(eid: int):
    conn = get_db()
    conn.execute("DELETE FROM monthly_entries WHERE id=?", (eid,))
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
def get_operations():
    conn = get_db()
    rows = conn.execute("SELECT * FROM operations ORDER BY date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/operations")
def create_operation(op: OperationIn):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO operations (date, broker, asset, op_type, entry_price, exit_price,
           quantity, pnl_usd, pnl_pct) VALUES (?,?,?,?,?,?,?,?,?)""",
        (op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM operations WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(row)


@app.put("/api/operations/{oid}")
def update_operation(oid: int, op: OperationIn):
    conn = get_db()
    conn.execute(
        """UPDATE operations SET date=?, broker=?, asset=?, op_type=?, entry_price=?,
           exit_price=?, quantity=?, pnl_usd=?, pnl_pct=? WHERE id=?""",
        (op.date, op.broker, op.asset, op.op_type, op.entry_price, op.exit_price,
         op.quantity, op.pnl_usd, op.pnl_pct, oid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM operations WHERE id=?", (oid,)).fetchone()
    conn.close()
    return dict(row)


@app.delete("/api/operations/{oid}")
def delete_operation(oid: int):
    conn = get_db()
    conn.execute("DELETE FROM operations WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return {"ok": True}
