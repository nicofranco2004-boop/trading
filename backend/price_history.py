"""Precios HISTÓRICOS por símbolo y fecha.

Hasta acá la app sólo guardaba `asset_last_price`: una fila por símbolo con el
último precio. Alcanza para valuar HOY y para nada más. Sin serie histórica no
se puede reconstruir cuánto valía una cartera el 31 de enero, y sin eso el TWR
sólo puede medir desde que el cron nocturno empezó a sacar fotos.

Este módulo es el prerrequisito de la reconstrucción: con el ledger sabemos QUÉ
tenía cada persona en cada fecha, y con esta tabla sabemos CUÁNTO VALÍA.

Es compartido: no sabe qué es un asesor ni qué es un usuario. Recibe símbolos.
"""
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

# Un precio de hace demasiados días NO es "el precio de ese día". Los mercados
# cierran findes y feriados, así que buscar hacia atrás es correcto — pero con
# un techo, o un ticker que dejó de cotizar en 2023 "tendría precio" en 2026.
# Es la misma clase de bug que `apply_last_known_prices`, que completa desde una
# tabla global sin TTL y deja la serie PLANA (peor que un hueco: el hueco se ve).
MAX_DIAS_ATRAS = 7

# Tope de símbolos por corrida del backfill. El cuello de botella real de la
# reconstrucción no son los tokens: son las llamadas a yfinance/data912 y sus
# rate limits. Se hace resumible y se corre de a tandas.
LOTE_DEFAULT = 25


def guardar(conn, symbol: str, serie: dict, source: str = "yfinance") -> int:
    """Persiste {fecha_iso: precio}. Idempotente y NO PISA: un precio ya
    guardado es un hecho de esa fecha; si una fuente devuelve otro valor
    después, el que vale es el primero que se registró. Devuelve cuántos entró.
    """
    n = 0
    for f, p in (serie or {}).items():
        if p is None:
            continue
        try:
            precio = float(p)
        except (TypeError, ValueError):
            continue
        if precio <= 0:
            continue
        cur = conn.execute(
            """INSERT INTO asset_price_history (symbol, date, price, source)
               VALUES (?,?,?,?) ON CONFLICT(symbol, date) DO NOTHING""",
            (symbol, str(f)[:10], precio, source))
        n += cur.rowcount
    return n


def precio_en(conn, symbol: str, fecha: str):
    """Precio de `symbol` en `fecha`, o el último anterior dentro de la
    ventana. None si no hay — y None significa NO SE PUEDE VALUAR, nunca 0."""
    piso = (date.fromisoformat(str(fecha)[:10]) - timedelta(days=MAX_DIAS_ATRAS)).isoformat()
    r = conn.execute(
        """SELECT price, date FROM asset_price_history
           WHERE symbol=? AND date <= ? AND date >= ?
           ORDER BY date DESC LIMIT 1""", (symbol, str(fecha)[:10], piso)).fetchone()
    return float(r["price"]) if r else None


def precios_en(conn, symbols: list, fecha: str) -> dict:
    """{symbol: precio} para una fecha. Los que no resuelven NO aparecen en el
    dict: el que consume tiene que decidir qué hacer con la ausencia, no
    comerse un 0 silencioso."""
    return {s: p for s in set(symbols or [])
            if (p := precio_en(conn, s, fecha)) is not None}


def cobertura(conn, symbols: list, fecha: str) -> dict:
    """Cuántos de estos símbolos se pueden valuar en esa fecha. El que arma un
    borde reconstruido necesita saber esto ANTES de publicar un valor: con un
    símbolo sin precio el total no es el total."""
    syms = sorted(set(symbols or []))
    hay = precios_en(conn, syms, fecha)
    faltan = [s for s in syms if s not in hay]
    return {
        "total": len(syms),
        "con_precio": len(hay),
        "faltan": faltan,
        "pct": round(len(hay) / len(syms) * 100, 1) if syms else 100.0,
    }


def _fetch_yfinance(symbol: str, desde: str) -> dict:
    """Serie diaria de cierres. Aislado a propósito: los tests inyectan otro
    fetcher y no tocan la red."""
    import yfinance as yf
    hist = yf.Ticker(symbol).history(start=desde, interval="1d", auto_adjust=True)
    out = {}
    for idx, row in hist.iterrows():
        cierre = row.get("Close")
        # yfinance devuelve ruedas de '.BA' con volumen pero OHLC en NaN — si
        # eso entra a la tabla, después se sirve como si fuera un cierre real.
        if cierre is None or cierre != cierre or float(cierre) <= 0:
            continue
        out[idx.date().isoformat()] = float(cierre)
    return out


def backfill(conn, symbols: list, desde: str, *, fetcher=None,
             lote: int = LOTE_DEFAULT) -> dict:
    """Trae la serie de cada símbolo que no la tenga y la persiste.

    Resumible: se salta lo que ya está cubierto, así correrlo de nuevo continúa
    en vez de empezar de cero. Un símbolo que falla NO frena la tanda — queda
    registrado y se reintenta en la próxima.
    """
    fetcher = fetcher or _fetch_yfinance
    pendientes, ok, fallados, filas = [], 0, [], 0

    for s in sorted(set(symbols or [])):
        if not s:
            continue
        r = conn.execute(
            "SELECT desde FROM price_backfill_log WHERE symbol=? AND ok=1",
            (s,)).fetchone()
        if r and r["desde"] <= desde:
            continue                      # ya se pidió desde al menos esa fecha
        pendientes.append(s)

    for s in pendientes[:lote]:
        try:
            serie = fetcher(s, desde)
        except Exception as ex:
            log.warning("price_history %s: %s", s, ex)
            fallados.append(s)
            continue
        if not serie:
            # Sin serie: queda registrado como intento fallido para que el
            # próximo lote lo reintente en vez de darlo por cubierto.
            conn.execute("INSERT INTO price_backfill_log (symbol, desde, ok) "
                         "VALUES (?,?,0) ON CONFLICT(symbol) DO UPDATE SET "
                         "ok=0, fetched_at=datetime('now')", (s, desde))
            fallados.append(s)
            continue
        filas += guardar(conn, s, serie)
        conn.execute("INSERT INTO price_backfill_log (symbol, desde, ok) "
                     "VALUES (?,?,1) ON CONFLICT(symbol) DO UPDATE SET "
                     "desde=MIN(price_backfill_log.desde, excluded.desde), "
                     "ok=1, fetched_at=datetime('now')", (s, desde))
        ok += 1

    return {
        "pedidos": len(pendientes), "resueltos": ok, "filas": filas,
        "sin_serie": fallados,
        "faltan": max(0, len(pendientes) - lote),   # cuántos quedan para la próxima
    }


def simbolos_de(conn, uid: int) -> list:
    """Los símbolos que hacen falta para valuar a este usuario, con la MISMA
    resolución que usa el snapshot (`position_price_key`). Reinventarla es lo
    que hizo que un CEDEAR comprado por dólar-MEP pidiera su ticker US y
    quedara 15-100× inflado."""
    from snapshots_job import build_price_symbols
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, user_id, name, currency, parent_broker_id FROM brokers WHERE user_id=?",
        (uid,)).fetchall()]
    positions = [dict(r) for r in conn.execute(
        """SELECT user_id, broker, asset, asset_type, is_cash, invested, quantity,
                  commissions, price_override, currency
           FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0""", (uid,)).fetchall()]
    if not brokers or not positions:
        return []
    return build_price_symbols(positions, brokers)
