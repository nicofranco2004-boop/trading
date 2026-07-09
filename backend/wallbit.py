"""Cliente read-only de la API pública de Wallbit + mapeo a NormalizedTx.

Wallbit (https://wallbit.io) es un broker/neobanco: el usuario invierte en
acciones/ETFs/bonos de EE.UU. en USD, y además tiene una cuenta con tarjeta.
La API pública (developer.wallbit.io) autentica con una API Key en el header
`X-API-Key` y expone permisos `read` (consulta) y `trade` (operar). Rendi SOLO
usa endpoints de lectura, con una key que el usuario genera con permiso `read`.

Este módulo:
  - hace las llamadas HTTP (httpx) con manejo de errores en castellano,
  - pagina el historial de transacciones,
  - traduce cada TRADE a una `NormalizedTx` del pipeline de imports de Rendi
    (misma vía que un CSV → posiciones + P&L, reusando todo el motor existente).

NO guarda ni cifra la API key (eso vive en main.py, con la DB y SECRET_KEY).
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional

import httpx

from importing.schema import NormalizedTx, OP_BUY, OP_SELL, AT_STOCK

WALLBIT_BASE = "https://api.wallbit.io/api/public/v1"
_TIMEOUT = 20.0
_PAGE_LIMIT = 50          # máximo permitido por /transactions
_MAX_PAGES = 200          # tope de seguridad (200 × 50 = 10.000 movimientos)


class WallbitError(Exception):
    """Error de la API de Wallbit con un mensaje ya listo para el usuario."""
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def _get(path: str, api_key: str, params: Optional[dict] = None) -> Any:
    """GET autenticado a Wallbit. Levanta WallbitError con mensaje en castellano."""
    url = WALLBIT_BASE + path
    try:
        r = httpx.get(url, headers={"X-API-Key": api_key}, params=params or {}, timeout=_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — red/timeout/DNS
        raise WallbitError(0, f"No se pudo conectar con Wallbit: {e}")
    if r.status_code == 401:
        raise WallbitError(401, "La API key de Wallbit es inválida o expiró. Generá una nueva.")
    if r.status_code == 403:
        raise WallbitError(403, "La API key no tiene permiso de lectura. Generala en Wallbit con el permiso \"read\".")
    if r.status_code == 429:
        raise WallbitError(429, "Wallbit está limitando las consultas (rate limit). Probá de nuevo en unos minutos.")
    if r.status_code >= 400:
        raise WallbitError(r.status_code, f"Wallbit respondió un error ({r.status_code}).")
    try:
        return r.json()
    except Exception:
        raise WallbitError(r.status_code, "Wallbit devolvió una respuesta inesperada.")


def validate_key(api_key: str) -> Dict[str, Any]:
    """Valida la key con una llamada liviana de solo-lectura (/balance/stocks).
    Devuelve {ok, holdings} o levanta WallbitError (401 inválida, 403 sin read)."""
    data = _get("/balance/stocks", api_key)
    holdings = (data or {}).get("data") or []
    return {"ok": True, "holdings": holdings}


def fetch_stock_balances(api_key: str) -> List[Dict[str, Any]]:
    """Foto de tenencias actuales: [{symbol, shares}]. El cash aparece como
    symbol='USD'. Solo se devuelven activos con saldo positivo."""
    data = _get("/balance/stocks", api_key)
    return (data or {}).get("data") or []


def fetch_asset_price(api_key: str, symbol: str) -> Optional[float]:
    """Precio actual de un activo (GET /assets/{symbol} → price). Se usa para valuar
    las tenencias de apertura que se siembran en la reconciliación (costo = precio de
    hoy → P&L 0). Devuelve None si no se puede obtener (no rompe el sync)."""
    try:
        data = _get(f"/assets/{symbol}", api_key)
    except WallbitError:
        return None
    try:
        p = float(((data or {}).get("data") or {}).get("price"))
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_trades(api_key: str, from_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Trae TODOS los movimientos tipo TRADE (compras/ventas), paginando.
    `from_date` (YYYY-MM-DD) limita a movimientos desde esa fecha para sync
    incremental. La respuesta de /transactions viene doble-anidada en data.data."""
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= _MAX_PAGES:
        params: Dict[str, Any] = {"type": "TRADE", "limit": _PAGE_LIMIT, "page": page}
        if from_date:
            params["from_date"] = from_date
        payload = _get("/transactions", api_key, params)
        block = (payload or {}).get("data") or {}
        rows = block.get("data") or []
        out.extend(rows)
        try:
            pages = int(block.get("pages") or 1)
        except (TypeError, ValueError):
            pages = 1
        # Si Wallbit reporta MÁS páginas que el tope, cortar en silencio daría una
        # cartera incompleta (P&L mal) → fallamos con aviso claro en vez de mentir.
        if pages > _MAX_PAGES:
            raise WallbitError(0, f"Tu cuenta de Wallbit tiene más de {_MAX_PAGES * _PAGE_LIMIT} movimientos y el sync automático todavía no los cubre. Escribinos y lo resolvemos.")
        if not rows or page >= pages:
            break
        page += 1
    return out


def trade_to_normalized_tx(trade: Dict[str, Any], broker: str, row_index: int) -> Optional[NormalizedTx]:
    """Traduce un movimiento TRADE de Wallbit a una NormalizedTx (BUY/SELL).

    Regla de montos (para que costo y proceeds sean EXACTOS en Rendi):
      - COMPRA: source=USD, dest=activo → cantidad = dest_amount, USD gastado =
        source_amount (incluye la comisión embebida). El persister usa gross_amount
        como `invested` → costo real.
      - VENTA: source=activo, dest=USD → cantidad = source_amount, USD recibido =
        dest_amount. El persister usa unit_price×cantidad para los proceeds, así
        que usamos precio all-in = gross/cantidad → proceeds = dest_amount exacto.

    Devuelve None si el movimiento no es un TRADE COMPLETED válido (se saltea).
    """
    if (trade.get("type") or "").upper() != "TRADE":
        return None
    if (trade.get("status") or "").upper() != "COMPLETED":
        return None
    ti = trade.get("trade_info") or {}
    direction = (ti.get("direction") or "").upper()
    symbol = (ti.get("symbol") or "").strip().upper()
    if not symbol or direction not in ("BUY", "SELL"):
        return None

    try:
        src = float(trade.get("source_amount") or 0)
        dst = float(trade.get("dest_amount") or 0)
    except (TypeError, ValueError):
        return None

    if direction == "BUY":
        qty, gross, op = dst, src, OP_BUY          # dest=acciones, source=USD gastado
    else:
        qty, gross, op = src, dst, OP_SELL         # source=acciones, dest=USD recibido

    if not (qty > 0) or not (gross > 0):
        return None

    unit = gross / qty                             # precio all-in (comisión embebida)
    created = (trade.get("created_at") or "")
    date = created[:10] if len(created) >= 10 else created
    uuid = trade.get("uuid") or ""

    return NormalizedTx(
        row_index=row_index,
        date=date,
        broker=broker,
        operation_type=op,
        asset_symbol=symbol,
        asset_name=symbol,
        asset_type=AT_STOCK,
        quantity=qty,
        unit_price=unit,
        gross_amount=gross,
        fees=0.0,
        taxes=0.0,
        currency="USD",
        settlement_currency="USD",
        notes=f"Wallbit · {uuid}" if uuid else "Wallbit",
    )


def trades_to_normalized(trades: List[Dict[str, Any]], broker: str) -> List[NormalizedTx]:
    """Mapea una lista de TRADEs a NormalizedTx, salteando los inválidos.
    Ordena cronológicamente (el rebuild FIFO igual reordena, pero llegamos limpios)."""
    txs: List[NormalizedTx] = []
    idx = 1
    for t in trades:
        tx = trade_to_normalized_tx(t, broker, idx)
        if tx is not None:
            txs.append(tx)
            idx += 1
    txs.sort(key=lambda t: (t.date or "", t.row_index))
    for i, t in enumerate(txs, start=1):
        t.row_index = i
    return txs
