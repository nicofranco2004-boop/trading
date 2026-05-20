"""mercadopago — wrapper del SDK + helpers para Rendi.
═══════════════════════════════════════════════════════════════════════════
Cubre 3 operaciones de billing:
  1. create_preapproval(user, period) → crea suscripción recurrente en MP
     y devuelve init_point URL para redirigir al user al checkout.
  2. cancel_preapproval(mp_subscription_id) → cancela la suscripción.
  3. verify_webhook(payload, signature, request_id) → valida que un
     webhook recibido viene realmente de MP (no spoof).

Estructura:
  • Usamos httpx para llamadas REST directas a MP (sin SDK oficial — más
    control + menos dependencias).
  • Sandbox vs producción se diferencia por el access_token (TEST-... vs
    APP_USR-...) — la URL base es la misma.

Docs:
  Preapproval API:
    https://www.mercadopago.com.ar/developers/es/reference/subscriptions/_preapproval/post
  Webhooks signature:
    https://www.mercadopago.com.ar/developers/es/docs/your-integrations/notifications/webhooks
"""

from __future__ import annotations
import os
import hmac
import hashlib
import json
import logging
from typing import Optional, Literal
from datetime import datetime, timedelta

import httpx

from billing import pricing

log = logging.getLogger("billing.mp")

MP_BASE_URL = "https://api.mercadopago.com"

# ─── Config (lazy desde env) ────────────────────────────────────────────────

def _access_token() -> str:
    t = (os.environ.get("MP_ACCESS_TOKEN") or "").strip()
    if not t:
        raise RuntimeError("MP_ACCESS_TOKEN no configurada — pegá el token en .env")
    return t


def _frontend_base() -> str:
    """Base URL para back_urls del checkout MP.

    MP RECHAZA back_urls con localhost / 127.0.0.1 con error 400
    'Invalid value for back_url, must be a valid URL'. Necesita HTTPS
    + dominio público.

    MP_BACK_URL_BASE override: si está seteada, gana sobre MP_FRONTEND_BASE_URL.
    Útil cuando MP rechaza el dominio del frontend (TLD nuevo, dominio no
    whitelisted en la app) y necesitamos usar otro dominio público
    (ej. la auto-URL de Vercel xxx.vercel.app) solo para los back_urls."""
    override = (os.environ.get("MP_BACK_URL_BASE") or "").strip().rstrip("/")
    if override:
        return override
    base = (os.environ.get("MP_FRONTEND_BASE_URL") or "http://localhost:5173").rstrip("/")
    if base.startswith("http://localhost") or "://127.0.0.1" in base or base.startswith("http://0.0.0.0"):
        return "https://rendi.finance"
    return base


def _is_local_dev() -> bool:
    """True cuando estamos corriendo contra localhost — afecta back_urls."""
    base = (os.environ.get("MP_FRONTEND_BASE_URL") or "").lower()
    return (
        base.startswith("http://localhost")
        or "://127.0.0.1" in base
        or base.startswith("http://0.0.0.0")
        or not base
    )


def _webhook_secret() -> str:
    return (os.environ.get("MP_WEBHOOK_SECRET") or "").strip()


def is_sandbox() -> bool:
    return _access_token().startswith("TEST-")


# ─── Crear preapproval (suscripción) ────────────────────────────────────────

Period = Literal["monthly", "annual"]


def create_preapproval(
    user_id: int,
    user_email: str,
    period: Period = "monthly",
    plan: str = "pro",
    *,
    reason: Optional[str] = None,
) -> dict:
    """Crea un preapproval en MP. Devuelve {id, init_point, ...}.

    El init_point es la URL del checkout — el frontend la usa para redirigir
    al user. Tras pagar, MP nos llama vía webhook (preapproval_authorized).

    `external_reference` es CRÍTICO: lo usamos en el webhook para identificar
    al user de Rendi. Encodeamos `user_id:plan:period` así no necesitamos
    lookup extra cuando llega el evento (compat: 'rendi-{uid}-{period}' viejo
    todavía resuelve a plan=pro).
    """
    p = pricing.get_pricing(plan, period)
    amount = p["total_ars"]
    plan_label = "Plus" if plan == "plus" else "Pro"

    # Frecuencia MP: 'months' con frequency=1 para mensual, frequency=12 anual.
    # OJO: MP NO tiene type='years' nativo — se simula con months × 12.
    frequency = 1 if period == "monthly" else 12
    payload = {
        "reason": reason or f"Rendi {plan_label} · {period}",
        "external_reference": f"rendi-{user_id}-{plan}-{period}",
        "payer_email": user_email,
        "auto_recurring": {
            "frequency": frequency,
            "frequency_type": "months",
            "transaction_amount": amount,
            "currency_id": "ARS",
            "start_date": _iso_now(),
            # No seteamos end_date → suscripción indefinida hasta cancelar
        },
        "back_url": f"{_frontend_base()}/billing/success",
        "status": "pending",  # se autoriza tras el pago exitoso
    }

    log.info("MP create_preapproval user=%s plan=%s period=%s amount=%s", user_id, plan, period, amount)
    log.info("MP create_preapproval payload: %s", json.dumps(payload, default=str))
    r = httpx.post(
        f"{MP_BASE_URL}/preapproval",
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15.0,
    )
    if r.status_code >= 400:
        log.error("MP create_preapproval failed %s: %s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()


def cancel_preapproval(mp_subscription_id: str) -> dict:
    """Cancela un preapproval. MP NO emite refunds automáticos del período
    ya cobrado — el user mantiene Pro hasta fin de período."""
    log.info("MP cancel_preapproval %s", mp_subscription_id)
    r = httpx.put(
        f"{MP_BASE_URL}/preapproval/{mp_subscription_id}",
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
        },
        json={"status": "cancelled"},
        timeout=15.0,
    )
    if r.status_code >= 400:
        log.error("MP cancel failed %s: %s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()


def get_preapproval(mp_subscription_id: str) -> dict:
    """GET el estado actual de un preapproval (para sync periodico)."""
    r = httpx.get(
        f"{MP_BASE_URL}/preapproval/{mp_subscription_id}",
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()


# ─── Webhook signature verification ─────────────────────────────────────────

def verify_webhook_signature(
    raw_body: bytes,
    x_signature: str,
    x_request_id: str,
    data_id: str,
) -> bool:
    """Valida la signature `x-signature` que MP manda en cada webhook.

    Formato del header:
      x-signature: ts=1234567890,v1=hex_signature

    Para validar:
      manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
      expected = HMAC-SHA256(MP_WEBHOOK_SECRET, manifest)
      compare(expected, v1) constant-time
    """
    secret = _webhook_secret()
    if not secret:
        log.warning("MP_WEBHOOK_SECRET no configurada — saltando validación (UNSAFE)")
        return True   # En dev, sin secret, dejamos pasar. En prod, configurar.

    try:
        parts = dict(p.split("=", 1) for p in x_signature.split(","))
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            return False

        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
        expected = hmac.new(
            secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception as ex:
        log.error("MP signature verify error: %s", ex)
        return False


# ─── Utils ─────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    """ISO 8601 con TZ — formato que espera MP.

    Agregamos 2 minutos al "now" porque MP rechaza start_dates en el pasado.
    Por el round-trip entre creación de preapproval y procesamiento server-side,
    sin este margen MP devuelve 400 'cannot be a past date'."""
    return (datetime.utcnow() + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_external_reference(ref: str) -> Optional[tuple[int, Period]]:
    """Decodifica el external_reference. Soporta 2 formatos:
      • 'rendi-{uid}-{period}'        (legacy, plan implícito='pro')
      • 'rendi-{uid}-{plan}-{period}' (multi-plan: plan ∈ {plus, pro})

    Devuelve (uid, period). El plan se infiere con `parse_external_reference_full`
    si el caller lo necesita; este helper queda para back-compat.
    """
    full = parse_external_reference_full(ref)
    if full is None:
        return None
    uid, _plan, period = full
    return uid, period


def parse_external_reference_full(ref: str) -> Optional[tuple[int, str, Period]]:
    """Decodifica el external_reference completo. Devuelve (uid, plan, period).
    Plan default = 'pro' para el formato legacy de 3 partes."""
    try:
        parts = ref.split("-")
        if parts[0] != "rendi":
            return None
        if len(parts) == 3:
            # Legacy: rendi-{uid}-{period}
            uid = int(parts[1])
            period = parts[2]
            if period not in ("monthly", "annual"):
                return None
            return uid, "pro", period  # type: ignore[return-value]
        if len(parts) == 4:
            # Multi-plan: rendi-{uid}-{plan}-{period}
            uid = int(parts[1])
            plan = parts[2]
            period = parts[3]
            if plan not in ("plus", "pro"):
                return None
            if period not in ("monthly", "annual"):
                return None
            return uid, plan, period  # type: ignore[return-value]
        return None
    except (ValueError, AttributeError):
        return None
