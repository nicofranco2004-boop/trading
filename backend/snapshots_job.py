"""
snapshots_job.py — Cron job que toma snapshot diario del portfolio de cada
usuario, sin depender de que abran la app.

Resuelve el gap actual donde los snapshots solo se crean cuando el usuario
visita el Dashboard. Esto rompía el banner 'variación diaria' en /posiciones
y la consistencia del YTD en /reportes cuando el usuario se ausentaba varios
días.

Schedule: diario a las 01:00 UTC (= 22:00 ART), después del cierre NYSE (5pm
ET = 22:00 UTC en horario estándar) y mucho después del cierre BCBA (17h ART).

Módulo separado de main.py para que la lógica del snapshot sea testeable
sin levantar la app entera.
"""

import logging
import math
import sqlite3
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Optional

import yfinance as yf

log = logging.getLogger('snapshots_job')


# ─── Cálculo de valuation (port de frontend/src/utils/valuation.js) ─────────
# El algoritmo replica `computeBrokerValue` exactamente para que el snapshot
# generado server-side coincida con lo que ve el usuario en el Dashboard.

def compute_broker_value_usd(
    broker_positions: list,
    prices: dict,
    broker_currency: str,
    tc_blue: float,
) -> dict:
    """Equivalente Python de frontend `computeBrokerValue`. Devuelve
    {value, invested} en USD. Maneja FX-phantom fix para brokers ARS
    (cost basis al blue actual, no al tc_compra histórico).

    Args:
        broker_positions: lista de dicts con keys (asset, is_cash, invested,
                          quantity, commissions, price_override)
        prices: dict {symbol: price_or_None}. Para ARS, key = 'ASSET.BA'.
        broker_currency: 'ARS' | 'USDT' | 'USD'
        tc_blue: ARS/USD blue rate actual
    """
    value = 0.0
    invested = 0.0

    for p in broker_positions:
        comm = p.get('commissions') or 0
        real_cost = (p.get('invested') or 0) + comm

        if broker_currency == 'ARS':
            if p.get('is_cash'):
                cash_ars = p.get('invested') or 0
                cash_usd = cash_ars / tc_blue if tc_blue > 0 else 0
                value += cash_usd
                invested += cash_usd  # cash ARS: value USD = invested USD (no FX gain)
            else:
                inv_usd = real_cost / tc_blue if tc_blue > 0 else 0
                invested += inv_usd
                price_ars = p.get('price_override') or prices.get(f"{p['asset']}.BA")
                if price_ars is not None:
                    mkt_ars = price_ars * (p.get('quantity') or 0)
                    value += mkt_ars / tc_blue if tc_blue > 0 else 0
                else:
                    value += inv_usd  # sin precio: mostrar cost como value
        else:
            # USDT / USD — moneda base USD, sin conversión
            if p.get('is_cash'):
                v = p.get('invested') or 0
                value += v
                invested += v
            else:
                invested += real_cost
                price = p.get('price_override') or prices.get(p['asset'])
                if price is not None:
                    value += price * (p.get('quantity') or 0)
                else:
                    value += real_cost

    return {'value': value, 'invested': invested}


# ─── Net deposited (port de Dashboard.jsx netDeposited useMemo) ─────────────

def compute_net_deposited(monthly_entries: list) -> float:
    """capital_inicio del primer mes 'global' + sum(deposits - withdrawals).
    Sin esto el % de retorno se infla porque divide por un base falso.
    """
    globals_entries = [m for m in monthly_entries if m['broker'] == 'global']
    if not globals_entries:
        return 0.0
    globals_sorted = sorted(globals_entries, key=lambda m: (m['year'], m['month']))
    baseline = globals_sorted[0].get('capital_inicio') or 0
    flows = sum((m.get('deposits') or 0) - (m.get('withdrawals') or 0) for m in globals_sorted)
    return baseline + flows


# ─── Fetch de precios (extrae lógica de get_prices) ─────────────────────────

def fetch_prices_for_symbols(symbols: list, crypto_yf: dict) -> dict:
    """Bulk fetch de precios via yfinance. Devuelve {symbol: price_or_None}.
    `crypto_yf` mapea {TICKER: 'TICKER-USD'} para criptos (mismo dict que
    main.py para no duplicar).
    """
    if not symbols:
        return {}

    sym_to_yf = {sym: (crypto_yf.get(sym) or sym) for sym in symbols}
    yf_tickers = list(set(sym_to_yf.values()))
    result = {sym: None for sym in symbols}

    if not yf_tickers:
        return result

    try:
        tickers_str = " ".join(yf_tickers)
        data = yf.download(tickers_str, period="1mo", progress=False, auto_adjust=True)
        if not data.empty:
            close = data.get("Close") if hasattr(data, 'get') else (
                data["Close"] if "Close" in data.columns else None
            )
            if close is not None and not (hasattr(close, 'empty') and close.empty):
                last = close.dropna(how='all').iloc[-1] if len(close.dropna(how='all')) > 0 else None
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
    except Exception as e:
        log.warning(f"yf.download failed for batch: {e}")

    return result


# ─── Snapshot por usuario ───────────────────────────────────────────────────

def take_snapshot_for_user(
    conn: sqlite3.Connection,
    uid: int,
    tc_blue: float,
    crypto_yf: dict,
    target_date: Optional[str] = None,
) -> dict:
    """Computa y persiste el snapshot del portfolio del usuario `uid` para
    la fecha `target_date` (default: hoy UTC). Idempotente vía UPSERT.

    Devuelve dict con resultado: {ok, total_value, total_invested,
    net_deposited, symbols_fetched, errors}.
    """
    if target_date is None:
        target_date = datetime.utcnow().strftime('%Y-%m-%d')

    # 1. Cargar brokers, positions y monthly del user
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, name, currency FROM brokers WHERE user_id=?", (uid,)
    ).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT broker, asset, is_cash, invested, quantity, commissions, price_override "
        "FROM positions WHERE user_id=?",
        (uid,)
    ).fetchall()]
    monthly = [dict(r) for r in conn.execute(
        "SELECT broker, year, month, capital_inicio, deposits, withdrawals "
        "FROM monthly_entries WHERE user_id=?",
        (uid,)
    ).fetchall()]

    if not brokers or not positions:
        log.info(f"user={uid}: sin brokers/positions, skipping snapshot")
        return {'ok': False, 'reason': 'no_data', 'total_value': 0,
                'total_invested': 0, 'net_deposited': 0, 'symbols_fetched': 0}

    # 2. Determinar símbolos a fetchear (excluyendo cash + USDT cash)
    ars_brokers = {b['name'] for b in brokers if b['currency'] == 'ARS'}
    usd_brokers = {b['name'] for b in brokers if b['currency'] != 'ARS'}

    ars_symbols = list({
        f"{p['asset']}.BA"
        for p in positions
        if p['broker'] in ars_brokers and not p['is_cash']
    })
    usd_symbols = list({
        p['asset']
        for p in positions
        if p['broker'] in usd_brokers and not p['is_cash'] and p['asset'] not in ('USDT', 'USD')
    })
    all_symbols = ars_symbols + usd_symbols

    prices = fetch_prices_for_symbols(all_symbols, crypto_yf) if all_symbols else {}

    # 3. Calcular total_value e invested por broker, sumar
    total_value = 0.0
    total_invested = 0.0
    for b in brokers:
        bpos = [p for p in positions if p['broker'] == b['name']]
        r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue)
        total_value += r['value']
        total_invested += r['invested']

    # 4. Calcular net_deposited desde monthly_entries
    net_deposited = compute_net_deposited(monthly)

    # 5. UPSERT en snapshots
    # SQLite UPSERT syntax: INSERT...ON CONFLICT(user_id, date) DO UPDATE
    conn.execute("""
        INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            total_value = excluded.total_value,
            total_invested = excluded.total_invested,
            net_deposited = excluded.net_deposited
    """, (uid, target_date, total_value, total_invested, net_deposited))

    return {
        'ok': True,
        'total_value': round(total_value, 2),
        'total_invested': round(total_invested, 2),
        'net_deposited': round(net_deposited, 2),
        'symbols_fetched': len(all_symbols),
        'date': target_date,
    }


# ─── Job runner: itera todos los usuarios activos ────────────────────────────

def run_daily_snapshot(
    db_path: str,
    fetch_tc_blue,
    crypto_yf: dict,
    target_date: Optional[str] = None,
) -> dict:
    """Función entry-point del scheduler. Itera todos los usuarios activos y
    toma snapshot para cada uno. Manejo de errores per-user — si uno falla,
    los demás siguen.

    Args:
        db_path: path al SQLite file
        fetch_tc_blue: callable que devuelve el blue rate actual (float)
        crypto_yf: dict {ticker: 'ticker-USD'} para mapping
        target_date: fecha YYYY-MM-DD (default: hoy UTC)

    Returns:
        dict resumen: {users_processed, ok, failed, target_date, errors}
    """
    target = target_date or datetime.utcnow().strftime('%Y-%m-%d')
    log.info(f"Iniciando daily snapshot job para fecha={target}")

    tc_blue = None
    try:
        tc_blue = fetch_tc_blue()
    except Exception as e:
        log.error(f"Falló fetch del blue, abortando job: {e}")
        return {'ok': False, 'reason': 'blue_fetch_failed', 'error': str(e)}

    if not tc_blue or tc_blue <= 0:
        log.error(f"Blue rate inválido ({tc_blue}), abortando job")
        return {'ok': False, 'reason': 'invalid_blue', 'tc_blue': tc_blue}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        user_ids = [r[0] for r in conn.execute(
            "SELECT id FROM users WHERE id IS NOT NULL"
        ).fetchall()]
        log.info(f"Procesando {len(user_ids)} usuarios con blue={tc_blue}")

        ok_count = 0
        failed_count = 0
        errors = []
        with conn:
            for uid in user_ids:
                try:
                    result = take_snapshot_for_user(conn, uid, tc_blue, crypto_yf, target)
                    if result['ok']:
                        ok_count += 1
                        log.info(f"user={uid}: snapshot ok — value=${result['total_value']}")
                    else:
                        log.info(f"user={uid}: skipped ({result.get('reason')})")
                except Exception as e:
                    failed_count += 1
                    errors.append({'user_id': uid, 'error': str(e)})
                    log.error(f"user={uid}: snapshot falló — {e}")

        log.info(f"Job terminado: ok={ok_count}, failed={failed_count}")
        return {
            'ok': True,
            'target_date': target,
            'users_processed': len(user_ids),
            'snapshots_ok': ok_count,
            'snapshots_failed': failed_count,
            'tc_blue': tc_blue,
            'errors': errors,
        }
    finally:
        conn.close()
