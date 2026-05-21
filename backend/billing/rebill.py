"""rebill — wrapper de Rebill API para suscripciones SaaS de Rendi.
═══════════════════════════════════════════════════════════════════════════
Cubre 3 operaciones de billing:
  1. create_payment_link(user_id, email, plan, period) → crea un link
     único en Rebill con metadata del user y devuelve {id, url}.
  2. cancel_subscription(subscription_id) → cancela la suscripción.
  3. verify_webhook_signature(raw_body, signature) → valida HMAC SHA-256.

Estructura:
  • Llamadas REST directas vía httpx (sin SDK oficial).
  • Auth: header x-api-key con REBILL_API_KEY (sk_test_ sandbox o sk_live_ prod).
  • Plan IDs (test_pln_... o pln_...) en env vars REBILL_PLAN_ID_{PLAN}_{PERIOD}.

Docs:
  Payment Links: https://docs.rebill.com/api/reference/payment-links
  Webhooks:      https://docs.rebill.com/api/reference/webhooks
"""
from __future__ import annotations
import os
import hmac
import hashlib
import json
import logging
import uuid
from typing import Optional, Literal

import httpx

log = logging.getLogger("billing.rebill")

REBILL_BASE_URL = "https://api.rebill.com"

Period = Literal["monthly", "annual"]


# ─── Config (lazy desde env) ────────────────────────────────────────────────

def _api_key() -> str:
    t = (os.environ.get("REBILL_API_KEY") or "").strip()
    if not t:
        raise RuntimeError("REBILL_API_KEY no configurada — pegala en Railway env vars")
    return t


def _webhook_secret() -> str:
    return (os.environ.get("REBILL_WEBHOOK_SECRET") or "").strip()


def _plan_id(plan: str, period: str) -> str:
    """Resolve REBILL_PLAN_ID_{PLAN}_{PERIOD} desde env.
    Ej: REBILL_PLAN_ID_PLUS_MONTHLY = test_pln_xxx
    """
    var = f"REBILL_PLAN_ID_{plan.upper()}_{period.upper()}"
    val = (os.environ.get(var) or "").strip()
    if not val:
        raise RuntimeError(f"{var} no configurada en Railway")
    return val


def _frontend_base() -> str:
    base = (os.environ.get("MP_FRONTEND_BASE_URL") or "https://rendi.finance").rstrip("/")
    # Si dev/local, fallback a rendi.finance (Rebill rechaza http://localhost)
    if base.startswith("http://localhost") or "://127.0.0.1" in base:
        return "https://rendi.finance"
    return base


def is_sandbox() -> bool:
    """True si la API key parece de sandbox (sk_test_)."""
    return _api_key().startswith("sk_test_")


# ─── Crear payment link con metadata del user ────────────────────────────────

def create_payment_link(
    user_id: int,
    user_email: str,
    plan: str,
    period: Period,
) -> dict:
    """Crea un payment link en Rebill con metadata del user.

    El webhook va a recibir esa metadata cuando el user pague —
    `metadata.rendi_user_id` es el identificador crítico para matchearlo.

    Devuelve dict con `id` (payment link ID) y `url` (URL del checkout).
    """
    plan_id = _plan_id(plan, period)
    plan_label = "Plus" if plan == "plus" else "Pro"
    title = f"Rendi {plan_label} · {period}"

    payload = {
        "title": [{"language": "es", "text": title}],
        "plan": {"id": plan_id},
        "isSingleUse": True,
        "metadata": {
            "rendi_user_id": str(user_id),
            "rendi_user_email": user_email,
            "rendi_plan": plan,
            "rendi_period": period,
        },
        # Métodos de pago aceptados (ARS para AR; agregar más currencies si
        # se ofrecen los planes en otras monedas)
        "paymentMethods": [
            {"methods": ["card", "bank_transfer"], "currency": "ARS"},
            {"methods": ["card"], "currency": "USD"},
        ],
        # Redirect URLs después del pago (Rebill las soporta como query params
        # o en config del plan/link)
        "successUrl": f"{_frontend_base()}/billing/success?provider=rebill",
        "cancelUrl": f"{_frontend_base()}/planes?cancelled=1",
    }

    # Idempotency key: si el frontend hace doble-click o el request se pierde
    # y se reintenta, Rebill detecta el duplicado y devuelve el mismo link en
    # vez de crear uno nuevo. Reserved: prefix recurring_ es interno de Rebill.
    idempotency_key = f"rendi-{user_id}-{plan}-{period}-{uuid.uuid4().hex[:8]}"

    log.info(
        "Rebill create_payment_link user=%s plan=%s period=%s plan_id=%s sandbox=%s",
        user_id, plan, period, plan_id, is_sandbox(),
    )
    log.debug("Rebill payload: %s", json.dumps(payload, default=str))

    r = httpx.post(
        f"{REBILL_BASE_URL}/v3/payment-links",
        headers={
            "x-api-key": _api_key(),
            "x-idempotency-key": idempotency_key,
            "accept": "application/json",
            "content-type": "application/json",
        },
        json=payload,
        timeout=15.0,
    )
    if r.status_code >= 400:
        log.error("Rebill create_payment_link failed %s: %s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()


def verify_api_key() -> Optional[dict]:
    """Llama a GET /v3/organizations/me para verificar que la API key está
    bien cargada y devuelve los datos de la org. Devuelve None si falla.

    Útil como diagnóstico: si arranca Rendi y este llamado falla, sabemos
    que la API key está mal configurada antes de que un user intente pagar.
    """
    try:
        r = httpx.get(
            f"{REBILL_BASE_URL}/v3/organizations/me",
            headers={"x-api-key": _api_key()},
            timeout=10.0,
        )
        if r.status_code == 200:
            return r.json()
        log.error("Rebill verify_api_key failed %s: %s", r.status_code, r.text)
        return None
    except Exception as ex:
        log.error("Rebill verify_api_key error: %s", ex)
        return None


# ─── Get + cancel subscription ──────────────────────────────────────────────

def get_subscription(subscription_id: str) -> dict:
    """GET state actual de una subscription."""
    r = httpx.get(
        f"{REBILL_BASE_URL}/v3/subscriptions/{subscription_id}",
        headers={"x-api-key": _api_key()},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()


def cancel_subscription(subscription_id: str) -> dict:
    """Cancela una subscription. Rebill NO emite refunds del período ya
    cobrado — el user mantiene Plus/Pro hasta fin de período."""
    log.info("Rebill cancel_subscription %s", subscription_id)
    # Endpoint según docs: POST /v3/subscriptions/{id}/cancel
    # (ajustar si la doc final dice otra cosa)
    r = httpx.post(
        f"{REBILL_BASE_URL}/v3/subscriptions/{subscription_id}/cancel",
        headers={"x-api-key": _api_key()},
        timeout=15.0,
    )
    if r.status_code >= 400:
        log.error("Rebill cancel failed %s: %s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()


# ─── Webhook signature verification ─────────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Valida HMAC-SHA256 del body usando REBILL_WEBHOOK_SECRET.

    Asumimos signature_header es el hex del HMAC del body crudo.
    (Si Rebill usa formato `t=...,v1=...` como MP, ajustar el parsing.)

    En dev sin secret configurado, dejamos pasar con warning. En prod
    siempre validamos.
    """
    secret = _webhook_secret()
    if not secret:
        log.warning("REBILL_WEBHOOK_SECRET no configurada — saltando validación (UNSAFE)")
        return True

    if not signature_header:
        return False

    try:
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header.strip())
    except Exception as ex:
        log.error("Rebill signature verify error: %s", ex)
        return False


# ─── Utils ─────────────────────────────────────────────────────────────────

def extract_subscription_id(payload: dict) -> str:
    """Extrae el subscription_id del webhook payload de Rebill.
    Probamos múltiples paths posibles (la estructura puede variar por evento).
    """
    candidates = [
        payload.get("subscription_id"),
        (payload.get("data") or {}).get("subscription_id"),
        (payload.get("data") or {}).get("id"),
        (payload.get("subscription") or {}).get("id"),
        payload.get("id"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c
    return ""


def extract_metadata(payload: dict) -> dict:
    """Extrae el metadata del webhook payload (lugar puede variar)."""
    candidates = [
        payload.get("metadata"),
        (payload.get("data") or {}).get("metadata"),
        (payload.get("subscription") or {}).get("metadata"),
    ]
    for c in candidates:
        if c and isinstance(c, dict):
            return c
    return {}
