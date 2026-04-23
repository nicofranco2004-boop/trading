"""Run once to import data from Excel into the SQLite database."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "trading.db")


def seed():
    conn = sqlite3.connect(DB_PATH)

    # Config
    conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_mep', '1415')")
    conn.execute("INSERT OR REPLACE INTO config VALUES ('tc_blue', '1415')")

    # Binance positions (USD)
    binance = [
        ("binance", "BTC",  0, 69809,  0.007162,  500.0,   None, None, None),
        ("binance", "BTC",  0, 66269,  0.003339,  221.3,   None, None, None),
        ("binance", "USDT", 1, None,   None,      1950.0,  None, None, "Cash USDT"),
    ]

    # Cocos positions (ARS) — asset, is_cash, buy_price_ars, qty, invested_ars, tc_compra
    cocos = [
        ("cocos", "INTC", 0, 12968,   41.0,       536224.0,  1455, None, None),
        ("cocos", "MSFT", 0, 19908,   44.0,       884438.0,  1450, None, None),
        ("cocos", "TSLA", 0, 41587,   10.0,       418315.0,  1440, None, None),
        ("cocos", "COIN", 0,  9110,   46.0,       423215.0,  1440, None, None),
        ("cocos", "AMZN", 0,  2151,  313.0,       679855.0,  1450, None, None),
        ("cocos", "ADBE", 0,  8705,   41.0,       356905.0,  1425, None, None),
        ("cocos", "ADBE", 0,  8030,   22.0,       177728.0,  1405, None, None),
        ("cocos", "MELI", 0, 21812,    8.985879,  196000.0,  1435, None, None),
        ("cocos", "BMA",  0,  9800,   39.0,       384000.0,  1425, None, None),
        ("cocos", "META", 0, 35600,    8.0,       284960.0,  1400, None, None),
        ("cocos", "NVDA", 0, 10940,   28.0,       306320.0,  1400, None, None),
        ("cocos", "MSFT", 0, 18654,   13.068832,  243786.0,  1425, None, None),
        ("cocos", "MELI", 0, 20339,   13.002114,  264450.0,  1425, None, None),
        ("cocos", "NFLX", 0,  2726,  280.0,       767173.0,  1455, None, None),
        ("cocos", "ARS",  1, None,    None,       290000.0,  None, None, "Cash ARS"),
    ]

    conn.executemany(
        """INSERT INTO positions
           (broker, asset, is_cash, buy_price, quantity, invested, tc_compra, price_override, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        binance + cocos,
    )

    # Monthly entries ─ Global (USD) — withdrawals stored as positive numbers
    global_m = [
        (2026, 2, "global",  370.24,   0,     0,      429.16,  5557.0,    5927.24),
        (2026, 3, "global",  659.72,  55,   -42,      429.16,  5927.24,   6489.96),
        (2026, 4, "global",  738.841, 238,    7.55,   640.14,  6489.96,   6998.35),
    ]
    # Monthly entries ─ Binance (USD)
    binance_m = [
        (2026, 2, "binance",   0,   0,     0,    44.88,  2948.0,   2948.0),
        (2026, 3, "binance",   0,  55,   -42,    44.88,  2948.0,   2851.0),
        (2026, 4, "binance",   0, 238,    7.55, 103.88,  2851.0,   2620.55),
    ]
    # Monthly entries ─ Cocos (ARS)
    cocos_m = [
        (2026, 2, "cocos",  370.24,      0, 0,  384.58,    2609.0,    2979.24),
        (2026, 3, "cocos",  659.72,      0, 0,  384.58,    2979.24,   3638.96),
        (2026, 4, "cocos",  738.841,     0, 0,  536.26,    3638.96,   4375.43),
    ]

    conn.executemany(
        """INSERT OR IGNORE INTO monthly_entries
           (year, month, broker, deposits, withdrawals, pnl_realized, pnl_unrealized,
            capital_inicio, capital_final)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        global_m + binance_m + cocos_m,
    )

    # Closed operations
    ops = [
        ("2026-03-19", "Binance", "BTC/USDT",  "LONG Futuros",  None, None, None, -20.0,  None),
        ("2026-03-22", "Binance", "BTC/USDT",  "LONG Futuros",  None, None, None, -22.0,  None),
        ("2026-04-16", "Binance", "BTC/USDT",  "LONG Futuros",  None, None, None,  59.44, None),
        ("2026-04-17", "Binance", "AAVE/USDT", "SHORT Futuros", None, None, None, -31.0,  None),
        ("2026-04-22", "Binance", "BTC/USDT",  "SHORT Futuros", None, None, None, -21.0,  None),
    ]
    conn.executemany(
        """INSERT INTO operations
           (date, broker, asset, op_type, entry_price, exit_price, quantity, pnl_usd, pnl_pct)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        ops,
    )

    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada con datos del Excel")


if __name__ == "__main__":
    seed()
