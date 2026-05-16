"""cache — capa de cache de análisis IA (SQLite, TTL 24h).
═══════════════════════════════════════════════════════════════════════════
Por qué cachear:
  • 90%+ de los "Analizar" son repeticiones del mismo packet en <24h
    (el user abre la app, mira el análisis, lo cierra, vuelve).
  • Pre-generación nocturna también escribe acá → al abrir la app el
    user ve análisis instant sin gastar tokens.

Llave del cache:
  packet_hash = sha256(json.dumps(packet, sort_keys=True))
  cache_key = sha256(f"{user_id}:{screen}:{packet_hash}")
  → si el packet cambia (ej. agregaste una posición), miss automático
  → sin riesgo de cross-user contamination

Invalidación:
  • TTL natural (24h)
  • invalidate_for_user(uid, screens=[...]) cuando hay mutaciones
    (positions, operations, monthly entries, etc.)
"""

from __future__ import annotations
import json
import hashlib

import logging
from typing import Optional, List
from datetime import datetime, timedelta

log = logging.getLogger("ai.cache")

CACHE_TTL_SECONDS = 24 * 3600  # 24h


def _compute_keys(user_id: int, screen: str, packet: dict, tier: str = "pro") -> tuple[str, str]:
    """Devuelve (packet_hash, cache_key). Ambos sha256 hex strings.

    packet_hash es solo del JSON ordenado del packet (sin user_id) —
    sirve para detectar si el packet cambió. cache_key incluye user_id +
    screen + tier para aislar cuentas Y tiers (Free y Pro tienen
    respuestas distintas para el mismo packet — el tier separa pools).
    """
    packet_json = json.dumps(packet, sort_keys=True, ensure_ascii=False)
    packet_hash = hashlib.sha256(packet_json.encode("utf-8")).hexdigest()
    cache_key = hashlib.sha256(
        f"{user_id}:{screen}:{tier}:{packet_hash}".encode("utf-8")
    ).hexdigest()
    return packet_hash, cache_key


def get_cached(conn, user_id: int, screen: str, packet: dict,
               tier: str = "pro") -> Optional[dict]:
    """Devuelve el result_json cacheado si existe + está fresco. None si miss.

    El tier afecta la cache_key — Free y Pro no comparten respuesta porque
    la calidad/tono del análisis es distinto."""
    _, cache_key = _compute_keys(user_id, screen, packet, tier)
    row = conn.execute(
        """SELECT result_json, expires_at FROM ai_analyses_cache
           WHERE cache_key = ? AND user_id = ?""",
        (cache_key, user_id),
    ).fetchone()
    if not row:
        return None
    # Verificar expiración (TTL declarativo)
    try:
        expires = datetime.fromisoformat(row["expires_at"])
        if expires < datetime.utcnow():
            return None
    except Exception:
        return None
    try:
        return json.loads(row["result_json"])
    except Exception:
        log.warning("cache row corrupto, ignoramos: %s", cache_key[:12])
        return None


def set_cached(
    conn,
    *,
    user_id: int,
    screen: str,
    packet: dict,
    result: dict,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_create_tokens: int = 0,
    cost_usd_cents: int = 0,
    tier: str = "pro",
) -> None:
    """Guarda un análisis en cache + registra costo para auditing.

    `tier` se mezcla en la cache_key — un análisis Free y uno Pro del
    mismo packet quedan en filas independientes."""
    packet_hash, cache_key = _compute_keys(user_id, screen, packet, tier)
    expires_at = (datetime.utcnow() + timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
    with conn:
        conn.execute(
            """INSERT INTO ai_analyses_cache
                 (cache_key, user_id, screen, result_json, expires_at, packet_hash,
                  model, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens,
                  cost_usd_cents, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(cache_key) DO UPDATE SET
                 result_json = excluded.result_json,
                 expires_at = excluded.expires_at,
                 model = excluded.model,
                 input_tokens = excluded.input_tokens,
                 output_tokens = excluded.output_tokens,
                 cache_read_tokens = excluded.cache_read_tokens,
                 cache_create_tokens = excluded.cache_create_tokens,
                 cost_usd_cents = excluded.cost_usd_cents,
                 created_at = datetime('now')""",
            (cache_key, user_id, screen, json.dumps(result, ensure_ascii=False),
             expires_at, packet_hash, model, input_tokens, output_tokens,
             cache_read_tokens, cache_create_tokens, cost_usd_cents),
        )


def invalidate_for_user(conn, user_id: int, screens: Optional[List[str]] = None) -> int:
    """Borra cache de un user. Si `screens` viene, solo esos screens.
    Devuelve cantidad de filas borradas.

    Llamado desde endpoints de mutación: cuando el user agrega una posición,
    invalidamos 'dashboard' y 'position' (su packet cambió).
    """
    with conn:
        if screens:
            placeholders = ",".join("?" * len(screens))
            cur = conn.execute(
                f"DELETE FROM ai_analyses_cache WHERE user_id = ? AND screen IN ({placeholders})",
                (user_id, *screens),
            )
        else:
            cur = conn.execute(
                "DELETE FROM ai_analyses_cache WHERE user_id = ?",
                (user_id,),
            )
    return cur.rowcount


def cleanup_expired(conn) -> int:
    """Borra entries con expires_at < ahora. Para cron nocturno. Devuelve filas."""
    with conn:
        cur = conn.execute(
            "DELETE FROM ai_analyses_cache WHERE expires_at < datetime('now')"
        )
    return cur.rowcount
