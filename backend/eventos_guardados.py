"""Los eventos YA GUARDADOS (`financial_events`) de una lista de tickers, de hoy
(Argentina) a `dias` días. UNA sola lectura para todo lo que muestra o cuenta
"lo que se viene":

  · main.py  /api/events/portfolio, /api/events/popular, el radar del asesor,
             `_has_events_for_tickers` y `_get_portfolio_events_cached` (las
             tarjetas "Lo que te afecta" del inicio).
  · ai/builders/home.py, events.py, dashboard_events.py (lo que lee Rendi AI).

Por qué existe (2026-10-01): eran siete copias de la misma consulta.
  · Una leía la tabla `events`, que no existe: las tarjetas "Earnings de X" /
    "Dividendo de X" del inicio no aparecieron nunca desde que se crearon.
  · Las tres de Rendi AI contaban "hoy" con `date.today()`, que en el servidor
    (UTC) ya es mañana de 21 a 24 h de Buenos Aires: la pantalla mostraba el
    evento de hoy y la IA no lo veía (ver la memoria "IA = número de la pantalla").

Los mails (advisor_brief, market_brief) preguntan otra cosa —los eventos de UN
día— y ya usan `fechas.hoy_art`; no pasan por acá.

Para leer: este módulo. Para traerlos de Yahoo: `main._eventos_al_dia`.
"""

import json
from datetime import date, timedelta
from typing import Iterable, List, Optional

from fechas import hoy_art_date


def eventos_guardados(conn, tickers: Iterable[str], dias: int, *,
                      hoy: Optional[date] = None,
                      limite: Optional[int] = None) -> List[dict]:
    """Eventos de `tickers` con fecha entre hoy y hoy + `dias` (ambos
    inclusive), ordenados por fecha. Cada uno:

        {ticker, event_type, event_date ('YYYY-MM-DD'), details (dict),
         confirmed (bool), source}

    `hoy`: el día desde el que se cuenta (default: hoy en Argentina). Quien
    después calcula "faltan N días" pasa el MISMO `hoy`, para que la ventana y
    la cuenta no puedan caer en días distintos justo a la medianoche.
    `limite`: para preguntar "¿hay alguno?" sin traerlos todos."""
    tickers = [t for t in dict.fromkeys(tickers or []) if t]
    if not tickers:
        return []
    hoy = hoy or hoy_art_date()
    hasta = hoy + timedelta(days=dias)
    placeholders = ",".join("?" * len(tickers))
    sql = (f"""SELECT ticker, event_type, event_date, details, confirmed, source
                 FROM financial_events
                WHERE ticker IN ({placeholders})
                  AND event_date >= ? AND event_date <= ?
                ORDER BY event_date ASC""")
    params = [*tickers, hoy.isoformat(), hasta.isoformat()]
    if limite is not None:
        sql += " LIMIT ?"
        params.append(int(limite))
    out = []
    for r in conn.execute(sql, params).fetchall():
        try:
            details = json.loads(r["details"]) if r["details"] else {}
        except (TypeError, ValueError):
            details = {}
        out.append({
            "ticker": r["ticker"],
            "event_type": r["event_type"],
            "event_date": str(r["event_date"])[:10],
            "details": details if isinstance(details, dict) else {},
            "confirmed": bool(r["confirmed"]),
            "source": r["source"],
        })
    return out
