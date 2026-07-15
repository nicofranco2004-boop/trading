"""builders.profile_summary — packet de la LECTURA PERSONALIZADA del Perfil.
═══════════════════════════════════════════════════════════════════════════
Topic: profile.summary

A diferencia de profile.card (zoom sobre UNA card), este junta TODOS los
cruces del test↔cartera (allocation, objective, horizon, drawdown,
concentration, style, liquidity) + el perfil declarado completo, para que el
LLM arme una SÍNTESIS holística: qué importa MÁS para ESTE user y por qué,
conectando ejes en vez de listar card por card.

Reusa la lógica de cruce de profile_card (misma semántica que ve el user en
pantalla). NO computa el retorno real (vive en el TWR del frontend) → así el
"retorno fantasma" (−64.9%, backlog C1/TWR) NUNCA entra en el packet.

Shape (~1.5KB):
{
  "screen": "profile.summary",
  "profile_declared": {...},        # las respuestas del test (incl. return_expectation)
  "crosses": {                       # todos los cruces declarado-vs-cartera-real
    "allocation": {title, status, declared, actual},
    "objective": {...}, "horizon": {...}, "drawdown": {...},
    "concentration": {...}, "style": {...}, "liquidity": {...}
  },
  "context": { total_portfolio_usd, n_positions, n_operations_total }
}
"""
from __future__ import annotations
from typing import Dict, Any
import json

from behavioral import stamp_positions_currency, stamp_byma
from .profile_card import _build_card_data, _CARD_TITLES, _invested_usd


def _tc(conn, user_id: int, key: str, default: float) -> float:
    row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    try:
        v = float(row["value"]) if row and row["value"] else default
    except (TypeError, ValueError):
        v = default
    return v if v > 0 else default


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # ── 1) Perfil declarado (test del user) ───────────────────────────────
    row = conn.execute(
        "SELECT investor_profile FROM users WHERE id=?", (user_id,)
    ).fetchone()
    profile_raw = (row["investor_profile"] if row else None) or "{}"
    try:
        profile = json.loads(profile_raw) if isinstance(profile_raw, str) else (profile_raw or {})
    except Exception:  # noqa: BLE001
        profile = {}

    if not profile:
        # Sin test → no hay nada que sintetizar. Packet mínimo con status
        # no_profile (el prompt sabe pedir que complete el test).
        return {
            "screen": "profile.summary",
            "profile_declared": {},
            "crosses": {},
            "context": {"total_portfolio_usd": 0, "n_positions": 0, "n_operations_total": 0},
        }

    # ── 2) Cartera + brokers + operations + tc (mismo patrón que profile_card) ─
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    brokers = [dict(r) for r in conn.execute(
        "SELECT * FROM brokers WHERE user_id=?", (user_id,)
    ).fetchall()]
    # Estampar moneda autoritativa del broker antes de sumar (sin esto, ARS
    # fuera de la lista de hints se cuenta como USD → ×1415).
    stamp_positions_currency(
        positions, {b.get("name"): (b.get("currency") or "") for b in brokers}
    )
    stamp_byma(positions, brokers)
    operations = [dict(r) for r in conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (user_id,)
    ).fetchall()]

    tc_blue = _tc(conn, user_id, "tc_blue", 1415.0)
    tc_mep = _tc(conn, user_id, "tc_mep", tc_blue)

    total_positions = len([p for p in positions if not p.get("is_cash")])
    total_value = sum(
        _invested_usd(p, tc_blue, tc_mep) for p in positions if not p.get("is_cash")
    )

    # ── 3) TODOS los cruces (misma lógica que las cards en pantalla) ───────
    crosses: Dict[str, Any] = {}
    for code in _CARD_TITLES:
        card_data = _build_card_data(
            code, profile, positions, brokers, operations, conn, user_id, tc_blue, tc_mep
        )
        crosses[code] = {"title": _CARD_TITLES[code], **card_data}

    return {
        "screen": "profile.summary",
        "profile_declared": profile,
        "crosses": crosses,
        "context": {
            "total_portfolio_usd": round(total_value, 2),
            "n_positions": total_positions,
            "n_operations_total": len(operations),
        },
    }
