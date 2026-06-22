"""builders.profile_card — packet de UNA card del Perfil del inversor.
═══════════════════════════════════════════════════════════════════════════
Topic: profile.card

Sprint 2026-05-27: la página /perfil-inversor se unificó dentro de
/analisis?tab=perfil con 7 cards que cruzan lo declarado en el test contra
la cartera real. Este builder alimenta el "Preguntar a la IA" sobre cada
card individual.

Params:
  code: str — el código de la card (allocation, objective, horizon,
              drawdown, concentration, style, liquidity).

Builder strategy: trae el perfil declarado (investor_profile en users),
la cartera + brokers + operations, y corre la función de cruce
correspondiente. Devuelve UN dict con declared/actual/comparison para que
el LLM analice ESA card específicamente.

Shape (~0.8KB):
{
  "screen": "profile.card",
  "code": "allocation",
  "profile_declared": { horizon, drawdown, goal, style, ... },
  "card": {
    "title": str,
    "status": "ready" | "no_profile" | "no_portfolio" | "no_data",
    "declared": {...},     # lo que el user dijo en el test (formateado)
    "actual": {...},       # cómo es la cartera real
    "comparison": str,     # 'aligned' | 'mismatch_*' | 'within' | etc.
  },
  "context": {
    "total_portfolio_usd": float,
    "n_positions": int,
  }
}
"""
from __future__ import annotations
from typing import Dict, Any
import json

from behavioral import _native_ccy


def _invested_usd(p: Dict[str, Any], tc_blue: float) -> float:
    """`invested` de una position (o monto de cash) convertido a USD.

    invested está en la moneda nativa de la fila (ARS para brokers AR/CEDEAR,
    USD para brokers US / sub-broker '· USD' / cripto-USD). Sumar sin convertir
    mezcla pesos con dólares e infla el total ~tc_blue×. Resolvemos la moneda
    real con _native_ccy (respeta currency explícita > asset USDT/ARS >
    sub-broker '· USD' > broker AR) y dividimos por tc_blue cuando es ARS."""
    val = p.get("invested") or 0
    if _native_ccy(p) == "ARS" and tc_blue > 0:
        return val / tc_blue
    return val


# Mapeo code → (título humano, función a importar de profile_match.py si existiera).
# Para profileMatch.js (que es frontend), replicamos la lógica en Python aquí.
# Decisión: NO portear todo profileMatch.js a Python para no duplicar. En su
# lugar, este builder le pide al frontend que envíe el resultado de la card
# como parte del request… EXCEPTO que el endpoint /api/ai/analyze pasa solo
# `code`, no la card pre-computada. Solución: replicamos LA LÓGICA MÍNIMA
# necesaria para construir el packet — no toda la formateada, sino los datos
# crudos que el LLM necesita para razonar.

_CARD_TITLES = {
    "allocation":    "Match perfil vs cartera",
    "objective":     "Coherencia con objetivo",
    "horizon":       "Horizonte vs composición",
    "drawdown":      "Drawdown tolerado vs real",
    "concentration": "Concentración vs perfil",
    "style":         "Estilo declarado vs actividad real",
    "liquidity":     "Liquidez declarada vs cartera",
}

_VALID_CODES = set(_CARD_TITLES.keys())


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    code = (kwargs.get("code") or "").strip().lower()
    if code not in _VALID_CODES:
        raise ValueError(
            f"code '{code}' inválido. Válidos: {sorted(_VALID_CODES)}"
        )

    # ── 1) Perfil declarado (test del user) ───────────────────────────────
    row = conn.execute(
        "SELECT investor_profile FROM users WHERE id=?", (user_id,)
    ).fetchone()
    profile_raw = (row["investor_profile"] if row else None) or "{}"
    try:
        profile_declared = json.loads(profile_raw) if isinstance(profile_raw, str) else (profile_raw or {})
    except Exception:  # noqa: BLE001
        profile_declared = {}

    if not profile_declared:
        # Sin test → el LLM no puede analizar el cruce. Devolvemos packet
        # mínimo con status no_profile.
        return {
            "screen": "profile.card",
            "code": code,
            "profile_declared": {},
            "card": {
                "title": _CARD_TITLES[code],
                "status": "no_profile",
                "declared": None,
                "actual": None,
                "comparison": None,
            },
            "context": {"total_portfolio_usd": 0, "n_positions": 0},
        }

    # ── 2) Cartera + brokers + operations ─────────────────────────────────
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    brokers = [dict(r) for r in conn.execute(
        "SELECT * FROM brokers WHERE user_id=?", (user_id,)
    ).fetchall()]
    # Estampar la moneda autoritativa del broker en las posiciones con currency
    # NULL — sin esto, _native_ccy infiere por nombre y no cubre brokers AR fuera
    # de la lista de hints (Santander/Galicia/PPI…) → ARS contado como USD (1415×).
    from behavioral import stamp_positions_currency
    stamp_positions_currency(
        positions, {b.get("name"): (b.get("currency") or "") for b in brokers}
    )
    operations = [dict(r) for r in conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (user_id,)
    ).fetchall()]

    # tc_blue para convertir invested ARS→USD antes de sumar (mismo patrón que
    # los demás builders del dir). Sin esto, total_value mezcla ARS+USD.
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
    if tc_blue <= 0:
        tc_blue = 1415.0

    # Datos derivados que el LLM necesita
    total_positions = len([p for p in positions if not p.get("is_cash")])
    total_value = sum(
        _invested_usd(p, tc_blue) for p in positions if not p.get("is_cash")
    )

    # ── 3) Computar card específica (lógica mínima por code) ──────────────
    # Para cada code, calculamos los datos crudos. El LLM se encarga del
    # razonamiento, no precisamos formatear como hace profileMatch.js.
    card_data = _build_card_data(code, profile_declared, positions, brokers, operations, conn, user_id, tc_blue)

    return {
        "screen": "profile.card",
        "code": code,
        "profile_declared": profile_declared,
        "card": {
            "title": _CARD_TITLES[code],
            **card_data,
        },
        "context": {
            "total_portfolio_usd": round(total_value, 2),
            "n_positions": total_positions,
            "n_operations_total": len(operations),
        },
    }


def _build_card_data(
    code: str,
    profile: dict,
    positions: list,
    brokers: list,
    operations: list,
    conn,
    user_id: int,
    tc_blue: float,
) -> dict:
    """Devuelve { status, declared, actual, comparison } según el code.

    Los nombres y semánticas matchean los del módulo frontend
    `frontend/src/utils/profileMatch.js` para que el LLM razone sobre
    los mismos conceptos que ve el user en pantalla.
    """
    declared = {
        "horizon": profile.get("horizon"),
        "drawdown": profile.get("drawdown"),
        "goal": profile.get("goal"),
        "style": profile.get("style"),
        "net_worth": profile.get("net_worth"),
        "liquidity": profile.get("liquidity"),
        "experience": profile.get("experience"),
    }

    # Para cards que cruzan con cartera, computamos buckets crudos.
    # Política simplificada (no idéntica a profileMatch.js pero suficiente
    # para que el LLM razone — el LLM no necesita los %  exactos al decimal):
    #   • cripto             → alternative
    #   • bonos AR (lista hardcodeada de prefijos reales) → fixed_income
    #   • cash               → cash
    #   • el resto           → equity
    #
    # Audit fix 2026-05-27: antes el prefix "S" matcheaba CUALQUIER ticker
    # que empieza con S (SPY, SHOP, SHEL, SQ) y los marcaba como fixed_income,
    # distorsionando los buckets. Ahora usamos una función de detección que
    # exige que el sufijo tras el prefix sea dígitos (AL30, TX26, GD35D).
    ar_bond_prefixes = ("AL", "GD", "AE", "TX", "T2X", "TZX")
    crypto_set = {"BTC", "ETH", "USDT", "USDC", "SOL", "ADA", "DOT", "MATIC", "AVAX", "BNB", "XRP", "DOGE", "LINK", "AAVE"}

    def _is_ar_bond(ticker: str) -> bool:
        """Detecta tickers de bonos AR soberanos (AL30, GD35D, TX26, TZX26, etc.)
        de forma estricta: prefix conocido + dígitos al final (con opcional
        sufijo `D` para MEP o `C` para CCL). Evita falsos positivos con
        equities US que empiezan con esas letras."""
        for prefix in ar_bond_prefixes:
            if ticker.startswith(prefix):
                rest = ticker[len(prefix):]
                # Sacamos sufijo D o C opcional al final
                if rest.endswith(("D", "C")):
                    rest = rest[:-1]
                # Lo que queda debe ser solo dígitos (vacío o "30", "35", etc.)
                if rest and rest.isdigit():
                    return True
        return False

    bucket_totals = {"cash": 0, "fixed_income": 0, "equity": 0, "alternative": 0}
    for p in positions:
        if p.get("is_cash"):
            # cash en ARS (asset='ARS') se convertía a USD por error → ahora
            # _invested_usd lo divide por tc_blue si _native_ccy es ARS.
            bucket_totals["cash"] += _invested_usd(p, tc_blue)
            continue
        ticker = (p.get("asset") or "").upper().split("/")[0].split("-")[0]
        # Strip pair suffix (USDT, USD, etc.)
        for q in ("USDT", "USDC", "BUSD"):
            if ticker.endswith(q) and len(ticker) > len(q) and ticker[:-len(q)] in crypto_set:
                ticker = ticker[:-len(q)]
                break

        val = _invested_usd(p, tc_blue)
        if ticker in crypto_set:
            bucket_totals["alternative"] += val
        elif _is_ar_bond(ticker):
            bucket_totals["fixed_income"] += val
        else:
            bucket_totals["equity"] += val

    total = sum(bucket_totals.values())
    bucket_pcts = (
        {k: round(v / total * 100) for k, v in bucket_totals.items()}
        if total > 0 else
        {k: 0 for k in bucket_totals}
    )

    # ── Casos por code ──
    if code == "allocation":
        return {
            "status": "ready" if total > 0 else "no_portfolio",
            "declared": {"profile_signal": profile.get("horizon"), "drawdown_pref": profile.get("drawdown")},
            "actual": {"buckets_pct": bucket_pcts, "total_invested_usd": round(total, 2)},
            "comparison": None,
        }

    if code == "objective":
        return {
            "status": "ready" if total > 0 else "no_portfolio",
            "declared": {"goal": profile.get("goal"), "horizon": profile.get("horizon")},
            "actual": {"buckets_pct": bucket_pcts, "total_invested_usd": round(total, 2)},
            "comparison": None,
        }

    if code == "horizon":
        return {
            "status": "ready" if total > 0 else "no_portfolio",
            "declared": {"horizon": profile.get("horizon")},
            "actual": {"buckets_pct": bucket_pcts, "equity_plus_alt_pct": bucket_pcts["equity"] + bucket_pcts["alternative"]},
            "comparison": None,
        }

    if code == "drawdown":
        # Drawdown real requiere el cómputo de TWRR que vive en frontend.
        # Para el LLM le damos el preferido + un nota de que el drawdown real
        # no está en el packet (queda como limitación honesta del builder).
        return {
            "status": "ready",
            "declared": {"drawdown_preference": profile.get("drawdown")},
            "actual": {"note": "drawdown_max_pct no disponible en backend builder — el user ve el valor en pantalla"},
            "comparison": None,
        }

    if code == "concentration":
        # Top 3 por valor
        by_asset = {}
        for p in positions:
            if p.get("is_cash"):
                continue
            asset = (p.get("asset") or "").upper()
            by_asset[asset] = by_asset.get(asset, 0) + _invested_usd(p, tc_blue)
        sorted_assets = sorted(by_asset.items(), key=lambda kv: kv[1], reverse=True)
        top3 = sorted_assets[:3]
        top3_value = sum(v for _, v in top3)
        top3_pct = round(top3_value / total * 100) if total > 0 else 0
        return {
            "status": "ready" if total > 0 else "no_portfolio",
            "declared": {"profile_signal": profile.get("horizon"), "drawdown_pref": profile.get("drawdown")},
            "actual": {
                "top3_pct": top3_pct,
                "top3_assets": [a for a, _ in top3],
                "holdings_count": len(by_asset),
            },
            "comparison": None,
        }

    if code == "style":
        # Trade frequency: SELLs en los últimos 6 meses.
        # Audit fix 2026-05-27: `recent` se inicializa ANTES del try porque
        # antes lo accedíamos abajo con `'recent' in dir()` que no funciona
        # como pensábamos (dir() devuelve nombres del scope local — si recent
        # nunca se asignó por excepción, len(recent) tira NameError igual
        # antes del check). Inicializarlo arriba elimina el race.
        from datetime import datetime, timedelta
        recent = []
        trades_per_month = 0
        try:
            sells = [o for o in operations if (o.get("op_type") or "").upper() == "SELL" and o.get("date")]
            if not sells:
                return {
                    "status": "no_data",
                    "declared": {"style": profile.get("style")},
                    "actual": None,
                    "comparison": None,
                }
            sorted_sells = sorted(sells, key=lambda o: o["date"], reverse=True)
            latest = datetime.fromisoformat(sorted_sells[0]["date"][:10])
            cutoff = latest - timedelta(days=180)
            recent = [o for o in sorted_sells if datetime.fromisoformat(o["date"][:10]) >= cutoff]
            trades_per_month = round(len(recent) / 6, 1)
        except Exception:  # noqa: BLE001
            # Cualquier fecha mal formateada → trades_per_month=0, recent=[]
            # (ya inicializados arriba)
            pass
        return {
            "status": "ready",
            "declared": {"style": profile.get("style")},
            "actual": {
                "trades_per_month": trades_per_month,
                "trades_total_6m": len(recent),
            },
            "comparison": None,
        }

    if code == "liquidity":
        safe_pct = bucket_pcts["cash"] + bucket_pcts["fixed_income"]
        volatile_pct = bucket_pcts["equity"] + bucket_pcts["alternative"]
        return {
            "status": "ready" if total > 0 else "no_portfolio",
            "declared": {"liquidity_need": profile.get("liquidity")},
            "actual": {
                "safe_pct": safe_pct,
                "volatile_pct": volatile_pct,
                "buckets_pct": bucket_pcts,
            },
            "comparison": None,
        }

    # Fallback (no debería llegar — code ya validado arriba)
    return {"status": "no_data", "declared": None, "actual": None, "comparison": None}
