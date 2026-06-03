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


# ─── Net deposited — Single Source of Truth ─────────────────────────────────
# Fase 3 (2026-05-30): unificar las 3 implementaciones inline del audit en
# UNA función canónica. Diferentes callers tienen necesidades distintas
# (con/sin baseline, con/sin time bound, por broker), pero la lógica vive
# en un solo lugar. Eliminamos drift por copy-paste evolution.

def compute_net_deposited_db(conn, uid: int, *,
                              as_of_date: Optional[str] = None,
                              broker_filter: str = "global",
                              include_baseline: bool = True) -> float:
    """SSoT canónica para `net_deposited`.

    Σ(deposits − withdrawals) en monthly_entries para el user, opcionalmente:
      • Limitado en tiempo: hasta `as_of_date` (formato 'YYYY-MM-DD' o
        'YYYY-MM'). Si None → todo el historial.
      • Por broker: default 'global' (cross-broker en USD). Pasar nombre
        de broker para filtrar a uno.
      • Con baseline: si True (default), agrega `capital_inicio` de la
        primera row matching como "seed state" para users con historia
        parcial importada. Si False, solo suma flows.

    Devuelve float USD (snapshots conventions: todo lo de monthly_entries
    está en USD).
    """
    where = "user_id = ? AND broker = ?"
    args = [uid, broker_filter]

    if as_of_date:
        y, m = (int(x) for x in as_of_date[:7].split("-"))
        where += " AND (year < ? OR (year = ? AND month <= ?))"
        args.extend([y, y, m])

    flows_row = conn.execute(
        f"SELECT COALESCE(SUM(deposits) - SUM(withdrawals), 0) AS net "
        f"FROM monthly_entries WHERE {where}",
        tuple(args),
    ).fetchone()
    flows = float(flows_row["net"] or 0)

    if not include_baseline:
        return flows

    baseline_row = conn.execute(
        f"SELECT capital_inicio FROM monthly_entries WHERE {where} "
        f"ORDER BY year, month LIMIT 1",
        tuple(args),
    ).fetchone()
    baseline = float(baseline_row["capital_inicio"] or 0) if baseline_row else 0.0
    return baseline + flows


def compute_net_deposited(monthly_entries: list) -> float:
    """Variante in-memory de la SSoT — para callers que ya tienen los rows
    fetcheados y no quieren hacer otra query. Mismo comportamiento que
    `compute_net_deposited_db(include_baseline=True, broker_filter='global')`.

    Útil específicamente en `take_snapshot_for_user` que ya tiene el SELECT
    completo de monthly hecho para iterar valuations.
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
        # Audit follow-up (2026-05-31): fecha del snapshot = día ART, no UTC.
        # Target users son argentinos. Si el cron corre a las 02:59 UTC del
        # sábado (= 23:59 ART del viernes), la fecha debe ser "viernes",
        # no "sábado" (que es lo que utcnow().date() devolvería).
        # Conversión: UTC - 3h = ART.
        from datetime import timedelta as _td
        art_dt = datetime.utcnow() - _td(hours=3)
        target_date = art_dt.strftime('%Y-%m-%d')

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

    # 2b. Reintento de los símbolos que quedaron sin precio. yfinance es flaky
    # en batch (a veces devuelve null para algunos tickers); una segunda pasada
    # sobre los faltantes suele completar los huecos.
    missing = [s for s in all_symbols if prices.get(s) is None]
    if missing:
        retry = fetch_prices_for_symbols(missing, crypto_yf)
        for s, v in retry.items():
            if v is not None:
                prices[s] = v

    # 2c. INTEGRIDAD: no persistir un snapshot subvaluado. Si después del retry
    # sigue faltando precio para una porción grande del portfolio, esas
    # posiciones caerían a cost basis (ver compute_broker_value_usd) y el total
    # quedaría falsamente bajo → rompe la variación diaria del día siguiente
    # (ganancia/pérdida fantasma). Preferimos NO escribir ese día antes que
    # escribir un dato corrupto. Cobertura ponderada por cost basis (USD): un
    # activo sin precio yfinance que sea fracción chica no bloquea; una caída
    # masiva de cobertura (yfinance caído) sí. price_override cuenta como precio.
    broker_ccy = {b['name']: b['currency'] for b in brokers}

    def _cost_usd(p):
        c = (p.get('invested') or 0) + (p.get('commissions') or 0)
        ccy = broker_ccy.get(p['broker'], 'USD')
        return (c / tc_blue) if (ccy == 'ARS' and tc_blue > 0) else c

    def _has_price(p):
        if p.get('price_override') is not None:
            return True
        ccy = broker_ccy.get(p['broker'], 'USD')
        key = f"{p['asset']}.BA" if ccy == 'ARS' else p['asset']
        return prices.get(key) is not None

    non_cash = [p for p in positions if not p['is_cash']]
    total_cost = sum(_cost_usd(p) for p in non_cash)
    priced_cost = sum(_cost_usd(p) for p in non_cash if _has_price(p))
    coverage = (priced_cost / total_cost) if total_cost > 0 else 1.0
    MIN_COVERAGE = 0.95
    if non_cash and coverage < MIN_COVERAGE:
        log.warning(
            f"user={uid}: cobertura de precios {coverage:.0%} < {MIN_COVERAGE:.0%} "
            f"— NO escribo snapshot {target_date} (evita dato subvaluado)"
        )
        return {'ok': False, 'reason': 'low_price_coverage',
                'coverage': round(coverage, 3),
                'total_value': 0, 'total_invested': 0, 'net_deposited': 0,
                'symbols_fetched': len(all_symbols)}

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
    # Phase C: stampamos fx_to_usd_blue (= tc_blue del día) para que cuando
    # el user mire la curva en ARS, cada punto use SU PROPIO blue (no el de hoy).
    conn.execute("""
        INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            total_value = excluded.total_value,
            total_invested = excluded.total_invested,
            net_deposited = excluded.net_deposited,
            fx_to_usd_blue = COALESCE(excluded.fx_to_usd_blue, snapshots.fx_to_usd_blue)
    """, (uid, target_date, total_value, total_invested, net_deposited, tc_blue))

    return {
        'ok': True,
        'total_value': round(total_value, 2),
        'total_invested': round(total_invested, 2),
        'net_deposited': round(net_deposited, 2),
        'symbols_fetched': len(all_symbols),
        'date': target_date,
    }


# Cache in-memory para live portfolio value — TTL 60s por user.
# Evita re-fetchear yfinance en cada call del endpoint /reports/period cuando
# el user navega tabs día/semana/año rápido. Key = (uid, broker).
_LIVE_VALUE_CACHE: dict = {}
_LIVE_VALUE_TTL_SEC = 60


def compute_live_portfolio_value(
    conn: sqlite3.Connection,
    uid: int,
    tc_blue: float,
    crypto_yf: dict,
) -> Optional[float]:
    """Calcula el total_value LIVE del portfolio sumando positions × precios
    actuales — sin persistir nada. Útil cuando se necesita "valor de hoy"
    pero el snapshot del día todavía no se generó por cron.

    Cachea por 60s para evitar fetches repetidos a yfinance en navegación rápida.
    Devuelve None si no hay positions o falla el fetch de precios.
    """
    import time as _time
    cache_key = (uid, tc_blue)
    cached = _LIVE_VALUE_CACHE.get(cache_key)
    if cached is not None:
        cached_at, cached_val = cached
        if _time.time() - cached_at < _LIVE_VALUE_TTL_SEC:
            return cached_val
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, name, currency FROM brokers WHERE user_id=?", (uid,)
    ).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT broker, asset, is_cash, invested, quantity, commissions, price_override "
        "FROM positions WHERE user_id=?",
        (uid,)
    ).fetchall()]
    if not brokers or not positions:
        return None

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
    if not all_symbols:
        return None

    try:
        prices = fetch_prices_for_symbols(all_symbols, crypto_yf)
    except Exception as e:
        log.warning(f"compute_live_portfolio_value: fetch_prices failed: {e}")
        return None

    total_value = 0.0
    for b in brokers:
        bpos = [p for p in positions if p['broker'] == b['name']]
        try:
            r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue)
            total_value += r['value']
        except Exception as e:
            log.warning(f"compute_live_portfolio_value: broker {b['name']} failed: {e}")
            continue
    result = round(total_value, 2)
    _LIVE_VALUE_CACHE[cache_key] = (_time.time(), result)
    return result


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
        # Phase C: persist el blue de HOY en fx_rates_daily. Idempotent —
        # si ya existe, hace overwrite con el nuevo valor (presumiblemente
        # más actualizado). Si la tabla no existe (migration pendiente en
        # un deploy mid-rollout), capturamos el error y seguimos.
        try:
            conn.execute(
                """INSERT INTO fx_rates_daily (date, blue_venta, source)
                   VALUES (?, ?, 'snapshot_cron')
                   ON CONFLICT(date) DO UPDATE SET
                     blue_venta = excluded.blue_venta,
                     source = excluded.source,
                     fetched_at = datetime('now')""",
                (target, float(tc_blue)),
            )
            conn.commit()
        except sqlite3.OperationalError as e:
            log.warning(f"fx_rates_daily insert falló (migration pendiente?): {e}")

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
