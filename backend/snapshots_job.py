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
import re
import sqlite3
from datetime import date as date_cls, datetime
from pathlib import Path
from typing import Optional

import yfinance as yf

log = logging.getLogger('snapshots_job')


# ─── Cálculo de valuation (port de frontend/src/utils/valuation.js) ─────────
# El algoritmo replica `computeBrokerValue` exactamente para que el snapshot
# generado server-side coincida con lo que ve el usuario en el Dashboard.

# Tipos de renta fija — cotizan cerca de la par; banda estrecha en el guard.
_FIXED_INCOME_TYPES = frozenset({'BOND', 'BONO', 'ON', 'LETRA', 'LECAP'})


def _trust_mkt_value(mkt_value: float, real_cost: float, asset_type) -> bool:
    """Port de frontend `_trustMktValue` (valuation.js:125-132). Si el valor de
    mercado se va absurdamente lejos del costo, NO confiamos en el precio
    (colisión de ticker, bono cotizado ×100, CEDEAR priceado como acción US) y
    caemos a costo. Solo capea divergencias ABSURDAS — el P&L real pasa."""
    if not (real_cost and real_cost > 0) or not (mkt_value and mkt_value > 0):
        return True  # sin costo no hay con qué comparar
    mult = mkt_value / real_cost
    if (asset_type or '').upper() in _FIXED_INCOME_TYPES:
        return 0.02 <= mult <= 4
    return 0.002 <= mult <= 50


_AR_USD_SUBBROKER_RE = re.compile(r'·\s*usd$')


def _is_ar_usd_subbroker(broker_name) -> bool:
    """Sub-broker '<Padre> · USD' (CEDEARs / acciones AR comprados por dólar-MEP).
    Mirror EXACTO del frontend isArUsdBroker (/·\\s*USD$/): requiere el separador
    '·'. A diferencia de behavioral._is_usd_subbroker (que decide MONEDA y es más
    laxo), acá decidimos RESOLUCIÓN DE PRECIO (.BA vs ticker US), así que un broker
    USD genuino llamado 'Mi Broker USD' NO debe matchear (tiene acciones US, no
    CEDEARs). Esto es lo que hace el frontend para la misma decisión."""
    return bool(_AR_USD_SUBBROKER_RE.search((broker_name or '').strip().lower()))


def _broker_name_sets(brokers: list):
    """(ars_names, ar_usd_names) — para decidir si una posición se valúa por .BA."""
    ars_names = {b['name'] for b in brokers if b.get('currency') == 'ARS'}
    ar_usd_names = {b['name'] for b in brokers if _is_ar_usd_subbroker(b.get('name'))}
    return ars_names, ar_usd_names


def position_price_key(p: dict, ars_names: set, ar_usd_names: set) -> str:
    """Símbolo de precio que valúa esta posición: '<ASSET>.BA' (precio LOCAL ARS)
    si se valúa por su .BA — holdings en broker ARS, en sub-broker '· USD', o
    CEDEAR (asset_type) — si no, el ticker US. SSoT compartida por el armado de
    símbolos a fetchear, el chequeo de cobertura y la valuación, para que los tres
    nunca diverjan (raíz del bug C1: el snapshot pedía/valuaba el ticker US de un
    CEDEAR comprado por dólar-MEP → 15-100× inflado)."""
    asset = p.get('asset')
    broker = p.get('broker')
    wants_ba = (broker in ars_names or broker in ar_usd_names
                or (p.get('asset_type') or '').upper() == 'CEDEAR')
    return f"{asset}.BA" if wants_ba else asset


def build_price_symbols(positions: list, brokers: list) -> list:
    """Símbolos a fetchear para valuar (sin cash ni cash-USD). Usa
    position_price_key, así un CEDEAR/instrumento BYMA en broker USD pide su
    precio .BA (ARS), no el ticker US."""
    ars_names, ar_usd_names = _broker_name_sets(brokers)
    syms = set()
    for p in positions:
        if p.get('is_cash'):
            continue
        asset = p.get('asset')
        if not asset or asset in ('USDT', 'USD'):
            continue
        syms.add(position_price_key(p, ars_names, ar_usd_names))
    return list(syms)


def _user_tc_cedear(conn, uid: int, tc_blue: float) -> float:
    """dólar-MEP del user (config 'tc_mep') para valuar holdings .BA. Reusa la
    SSoT `analysis_prep.user_fx` (lazy import para evitar ciclos); cae a tc_blue
    si no hay config de MEP."""
    try:
        from analysis_prep import user_fx
        _, tc_cedear = user_fx(conn, uid)
        return tc_cedear if (tc_cedear and tc_cedear > 0) else tc_blue
    except Exception:
        return tc_blue


def compute_broker_value_usd(
    broker_positions: list,
    prices: dict,
    broker_currency: str,
    tc_blue: float,
    broker_name: str = '',
    cedear_rate: Optional[float] = None,
) -> dict:
    """Equivalente Python de frontend `computeBrokerValue` (port fiel, incluida la
    rama CEDEAR). Devuelve {value, invested} en USD. Maneja FX-phantom fix para
    brokers ARS (cost basis al blue actual, no al tc_compra histórico).

    Args:
        broker_positions: dicts con keys (asset, asset_type, is_cash, invested,
                          quantity, commissions, price_override)
        prices: dict {symbol: price_or_None}. Para holdings .BA, key = 'ASSET.BA'.
        broker_currency: 'ARS' | 'USDT' | 'USD'
        tc_blue: ARS/USD blue rate — cash en pesos y cost basis ARS.
        broker_name: nombre del broker — detecta el sub-broker '· USD'.
        cedear_rate: dólar-MEP — valúa CEDEARs / instrumentos BYMA en brokers USD
            por su precio .BA ÷ MEP (NO el ticker US, que vale 15-100× más).
            Default = tc_blue (sin regresión). Ver CORRECTNESS_AUDIT (C1).
    """
    if not cedear_rate or cedear_rate <= 0:
        cedear_rate = tc_blue
    ar_usd = _is_ar_usd_subbroker(broker_name)
    value = 0.0
    invested = 0.0

    for p in broker_positions:
        comm = p.get('commissions') or 0
        real_cost = (p.get('invested') or 0) + comm
        asset_type = p.get('asset_type')
        override = p.get('price_override')

        if broker_currency == 'ARS':
            if p.get('is_cash'):
                cash_ars = p.get('invested') or 0
                cash_usd = cash_ars / tc_blue if tc_blue > 0 else 0
                value += cash_usd
                invested += cash_usd  # cash ARS: value USD = invested USD (no FX gain)
            else:
                inv_usd = real_cost / tc_blue if tc_blue > 0 else 0
                invested += inv_usd
                # `is not None` (no `or`): un price_override=0 es válido (activo
                # marcado sin valor) y NO debe caer al precio de mercado. Mirror
                # del `??` del frontend (valuation.js:163).
                price_ars = override if override is not None else prices.get(f"{p['asset']}.BA")
                if price_ars is not None:
                    mkt_usd = (price_ars * (p.get('quantity') or 0)) / tc_blue if tc_blue > 0 else 0
                    trust = override is not None or _trust_mkt_value(mkt_usd, inv_usd, asset_type)
                    value += mkt_usd if trust else inv_usd
                else:
                    value += inv_usd  # sin precio: mostrar cost como value
        else:
            # USDT / USD — moneda base USD
            if p.get('is_cash'):
                v = p.get('invested') or 0
                value += v
                invested += v
            else:
                invested += real_cost
                # CEDEAR (o cualquier instrumento BYMA en sub-broker '· USD'): se
                # valúa por su precio LOCAL .BA (ARS) ÷ MEP, NO por el ticker US.
                # Port de valuation.js:184-193.
                if (asset_type == 'CEDEAR' or ar_usd) and override is None:
                    price_ars = prices.get(f"{p['asset']}.BA")
                    if price_ars is not None:
                        mkt_usd = (price_ars * (p.get('quantity') or 0)) / cedear_rate if cedear_rate > 0 else 0
                        value += mkt_usd if _trust_mkt_value(mkt_usd, real_cost, asset_type) else real_cost
                    else:
                        value += real_cost
                else:
                    price = override if override is not None else prices.get(p['asset'])
                    if price is not None:
                        mkt = price * (p.get('quantity') or 0)
                        trust = override is not None or _trust_mkt_value(mkt, real_cost, asset_type)
                        value += mkt if trust else real_cost
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

    # CEDEARs que las fuentes cotizan en USD (ej. BAC): fetcheamos el subyacente
    # US y devolvemos el precio en pesos (× CCL ÷ ratio), igual que main.get_prices.
    # Sin esto, el snapshot diario guardaría el valor en USD (~9) en vez de ~20.570
    # ARS → historia de portfolio subvaluada. Lazy import para evitar el ciclo
    # snapshots_job ↔ main.
    try:
        from main import (CEDEAR_USD_RATIOS as _CED_RATIOS,
                          _current_ccl as _cur_ccl, _fetch_dolar as _fd)
    except Exception:
        _CED_RATIOS, _cur_ccl, _fd = {}, (lambda: None), (lambda casa: None)
    cedear_usd = {s: s[:-3] for s in symbols
                  if s.endswith('.BA') and s[:-3] in _CED_RATIOS}
    _ccl = None
    if cedear_usd:
        _ccl = _cur_ccl()
        if not _ccl:
            _d = _fd("contadoconliqui")  # cron sin caché de dólar → fetch directo
            _ccl = (_d or {}).get("venta")

    sym_to_yf = {}
    for sym in symbols:
        if sym in cedear_usd:
            sym_to_yf[sym] = cedear_usd[sym]  # ticker US (ej. BAC)
        else:
            sym_to_yf[sym] = crypto_yf.get(sym) or sym
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

    # CEDEARs USD-cotizados: el precio fetcheado es el del subyacente US (USD) →
    # a pesos (× CCL ÷ ratio). Sin CCL los dejamos en None (no persistimos el
    # valor en USD roto; el chequeo de cobertura del snapshot decide qué hacer).
    if cedear_usd:
        for _csym, _base in cedear_usd.items():
            if result.get(_csym) is not None:
                _r = _CED_RATIOS.get(_base) or 1
                result[_csym] = round(result[_csym] * _ccl / _r, 4) if (_ccl and _ccl > 0) else None

    return result


# ─── Último precio conocido (fallback en vez de cost basis) ─────────────────
# Cuando yfinance no devuelve precio, en vez de valuar una posición a su costo
# (lo que inventa un salto fantasma en la variación diaria), la dejamos al
# último precio real que vimos. Persistido en asset_last_price (key = símbolo
# tal como se valúa: 'AAPL', 'GGAL.BA', 'BTC'). Best-effort: si la tabla no
# existe (migration pendiente) no rompe nada.

def persist_last_prices(conn, prices: dict) -> None:
    """UPSERT de los precios reales (no-None) en asset_last_price."""
    rows = []
    for sym, p in (prices or {}).items():
        try:
            if p is not None and float(p) > 0:
                rows.append((sym, float(p)))
        except (TypeError, ValueError):
            continue
    if not rows:
        return
    now = datetime.utcnow().isoformat()
    try:
        conn.executemany(
            """INSERT INTO asset_last_price (symbol, price, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET
                 price = excluded.price, updated_at = excluded.updated_at""",
            [(s, p, now) for s, p in rows],
        )
    except sqlite3.OperationalError as e:
        log.warning(f"persist_last_prices falló (migration pendiente?): {e}")


def read_last_prices(conn, symbols: list) -> dict:
    """Devuelve {symbol: price} para los símbolos con último precio guardado."""
    syms = [s for s in (symbols or []) if s]
    if not syms:
        return {}
    try:
        placeholders = ",".join("?" * len(syms))
        rows = conn.execute(
            f"SELECT symbol, price FROM asset_last_price WHERE symbol IN ({placeholders})",
            tuple(syms),
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        return {}


def apply_last_known_prices(conn, prices: dict) -> dict:
    """(1) Persiste los precios reales (no-None) de `prices` como último conocido.
    (2) Completa los símbolos en None con su último precio conocido guardado.
    Muta y devuelve `prices`. Reemplaza el fallback a cost basis: sin precio hoy
    → la posición queda al último valor real visto (no a lo que se pagó)."""
    if not prices:
        return prices
    persist_last_prices(conn, {s: p for s, p in prices.items() if p is not None})
    missing = [s for s, p in prices.items() if p is None]
    if missing:
        for s, p in read_last_prices(conn, missing).items():
            if p is not None:
                prices[s] = p
    return prices


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
        "SELECT broker, asset, asset_type, is_cash, invested, quantity, commissions, price_override "
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

    # 2. Determinar símbolos a fetchear. build_price_symbols pide '.BA' para
    # CEDEARs / instrumentos en sub-brokers '· USD' (no el ticker US → C1 fix).
    all_symbols = build_price_symbols(positions, brokers)

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

    # 2b-bis. Último precio conocido: guarda los que conseguimos y completa los
    # que siguen sin precio con su último valor real (no cost basis). Así una
    # posición sin precio hoy queda "igual que ayer" en vez de saltar a su costo.
    apply_last_known_prices(conn, prices)

    # 2c. INTEGRIDAD: no persistir un snapshot subvaluado. Si después del retry
    # sigue faltando precio para una porción grande del portfolio, esas
    # posiciones caerían a cost basis (ver compute_broker_value_usd) y el total
    # quedaría falsamente bajo → rompe la variación diaria del día siguiente
    # (ganancia/pérdida fantasma). Preferimos NO escribir ese día antes que
    # escribir un dato corrupto. Cobertura ponderada por cost basis (USD): un
    # activo sin precio yfinance que sea fracción chica no bloquea; una caída
    # masiva de cobertura (yfinance caído) sí. price_override cuenta como precio.
    broker_ccy = {b['name']: b['currency'] for b in brokers}
    _ars_names, _ar_usd_names = _broker_name_sets(brokers)

    def _cost_usd(p):
        c = (p.get('invested') or 0) + (p.get('commissions') or 0)
        ccy = broker_ccy.get(p['broker'], 'USD')
        return (c / tc_blue) if (ccy == 'ARS' and tc_blue > 0) else c

    def _has_price(p):
        if p.get('price_override') is not None:
            return True
        # Mismo símbolo con el que se valúa (CEDEAR/sub-broker '· USD' → .BA):
        # si no, la cobertura miraría el ticker US que ya no fetcheamos para esos.
        return prices.get(position_price_key(p, _ars_names, _ar_usd_names)) is not None

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
    tc_cedear = _user_tc_cedear(conn, uid, tc_blue)
    total_value = 0.0
    total_invested = 0.0
    for b in brokers:
        bpos = [p for p in positions if p['broker'] == b['name']]
        r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue,
                                     broker_name=b['name'], cedear_rate=tc_cedear)
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
        "SELECT broker, asset, asset_type, is_cash, invested, quantity, commissions, price_override "
        "FROM positions WHERE user_id=?",
        (uid,)
    ).fetchall()]
    if not brokers or not positions:
        return None

    all_symbols = build_price_symbols(positions, brokers)
    if not all_symbols:
        return None

    try:
        prices = fetch_prices_for_symbols(all_symbols, crypto_yf)
    except Exception as e:
        log.warning(f"compute_live_portfolio_value: fetch_prices failed: {e}")
        return None

    tc_cedear = _user_tc_cedear(conn, uid, tc_blue)
    total_value = 0.0
    for b in brokers:
        bpos = [p for p in positions if p['broker'] == b['name']]
        try:
            r = compute_broker_value_usd(bpos, prices, b['currency'], tc_blue,
                                         broker_name=b['name'], cedear_rate=tc_cedear)
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
