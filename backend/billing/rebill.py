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


def is_likely_production() -> bool:
    """Best-effort detection de ambiente productivo.

    True si CUALQUIERA de estas señales aplica:
      1. RENDI_ENV=prod (explícito)
      2. RAILWAY_ENVIRONMENT=production (lo setea Railway automáticamente)
      3. REBILL_API_KEY existe Y no arranca con sk_test_

    El criterio #3 es defensivo: si tenés una key que no es explícitamente
    sandbox, asumimos prod. Sino, un deploy mal configurado (sin RENDI_ENV)
    pero con key real podría aceptar webhooks fake sin firma — exactamente
    el bug que estamos arreglando.
    """
    if (os.environ.get("RENDI_ENV") or "").lower() == "prod":
        return True
    if (os.environ.get("RAILWAY_ENVIRONMENT") or "").lower() == "production":
        return True
    api_key = (os.environ.get("REBILL_API_KEY") or "").strip()
    if api_key and not api_key.startswith("sk_test_"):
        return True
    return False


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

    # Payload según doc oficial de Rebill /v3/payment-links:
    # required: title, plan, paymentMethods
    # opcional: isSingleUse, metadata, successUrl, cancelUrl
    #
    # IMPORTANTE: paymentMethods.currency DEBE matchear la currency del
    # plan. Nuestros planes están en USD (creados en dashboard como $4/$9),
    # por eso acá va USD. Rebill rebota con "All prices must have a payment
    # method" si la currency no matchea.
    #
    # bank_transfer no aplica para USD en AR — solo card.
    #
    # successUrl / cancelUrl REMOVIDOS del payload (Rebill v3 los rechaza
    # con 400 "property successUrl should not exist"). En la API v3 actual
    # esos URLs se configuran a nivel del PLAN en el dashboard de Rebill
    # (no del payment link individual). Hay que setearlos una vez por plan
    # apuntando a /billing/success y /billing/failure de rendi.finance.
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
        "paymentMethods": [
            {"methods": ["card"], "currency": "USD"},
        ],
    }

    # Idempotency key: si el frontend hace doble-click o el request se pierde
    # y se reintenta, Rebill detecta el duplicado y devuelve el mismo link en
    # vez de crear uno nuevo. Reserved: prefix recurring_ es interno de Rebill.
    idempotency_key = f"rendi-{user_id}-{plan}-{period}-{uuid.uuid4().hex[:8]}"

    log.info(
        "Rebill create_payment_link user=%s plan=%s period=%s plan_id=%s sandbox=%s",
        user_id, plan, period, plan_id, is_sandbox(),
    )
    log.info("Rebill payload: %s", json.dumps(payload, default=str))

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
        # Loggear todo lo que dice Rebill — status + body + headers — para
        # poder debugear sin tener que adivinar
        log.error(
            "Rebill create_payment_link FAILED status=%s body=%s headers=%s",
            r.status_code, r.text, dict(r.headers),
        )
        # En lugar de raise (que pierde el body), tiramos una excepción con
        # el body para que el endpoint lo pueda surface al frontend
        raise RuntimeError(f"Rebill {r.status_code}: {r.text}")
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


def validate_config() -> dict:
    """Sanity check de la config de Rebill al startup.

    Devuelve dict con:
      • ok: bool — config consistente
      • sandbox: bool — ambiente detectado
      • errors: list[str] — problemas que requieren acción
      • warnings: list[str] — cosas raras pero no bloqueantes

    Casos que detecta:
      1. REBILL_API_KEY ausente.
      2. REBILL_WEBHOOK_SECRET ausente (acepta webhooks sin validar).
      3. Mismatch ambiente: key sk_live_ con plan IDs test_pln_, o
         key sk_test_ con plan IDs sin prefijo test_.
      4. Plan IDs ausentes para algún plan/período.

    Llamada al startup desde main.py para que cualquier desconfig
    aparezca inmediatamente en los logs de Railway al deployar.
    """
    errors = []
    warnings = []

    # API key
    raw_key = (os.environ.get("REBILL_API_KEY") or "").strip()
    if not raw_key:
        errors.append("REBILL_API_KEY no configurada — billing no va a funcionar")
        return {"ok": False, "sandbox": None, "errors": errors, "warnings": warnings}

    sandbox = raw_key.startswith("sk_test_")
    is_live = raw_key.startswith("sk_live_")
    if not sandbox and not is_live:
        warnings.append(f"REBILL_API_KEY no tiene prefijo sk_test_ o sk_live_ (key prefix: {raw_key[:8]}...)")

    # Webhook secret — en prod debe estar configurada o rechazamos webhooks (post-fix
    # de seguridad 2026-05-31). Escalamos a ERROR si parece prod sin secret.
    if not (os.environ.get("REBILL_WEBHOOK_SECRET") or "").strip():
        if is_likely_production():
            errors.append(
                "REBILL_WEBHOOK_SECRET no configurada y parece estar en producción — "
                "los webhooks van a ser RECHAZADOS hasta que la setees. "
                "Pegá el secret del dashboard de Rebill en Railway env vars."
            )
        else:
            warnings.append(
                "REBILL_WEBHOOK_SECRET no configurada (estás en dev local, los webhooks "
                "se aceptan sin validar). En prod esto se vuelve un error crítico."
            )

    # Plan IDs: 4 combinaciones esperadas
    plan_combos = [
        ("plus", "monthly"),
        ("plus", "annual"),
        ("pro", "monthly"),
        ("pro", "annual"),
    ]
    for plan, period in plan_combos:
        var = f"REBILL_PLAN_ID_{plan.upper()}_{period.upper()}"
        val = (os.environ.get(var) or "").strip()
        if not val:
            errors.append(f"{var} ausente — no se puede crear payment link para {plan} {period}")
            continue
        # Mismatch ambiente vs prefijo del plan ID
        if sandbox and not val.startswith("test_"):
            warnings.append(
                f"{var}={val[:12]}... no tiene prefijo test_ pero la API key es sandbox. "
                "Probable que falte actualizar este plan a un test_pln_ de Rebill sandbox."
            )
        if is_live and val.startswith("test_"):
            errors.append(
                f"{var}={val[:12]}... tiene prefijo test_ pero la API key es producción (sk_live_). "
                "Mismatch crítico: Rebill va a rechazar el pago. Reemplazar por un plan ID de producción."
            )

    return {
        "ok": len(errors) == 0,
        "sandbox": sandbox,
        "errors": errors,
        "warnings": warnings,
    }


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
    """Cancela una subscription via PATCH con status=cancelled (terminal).
    Rebill NO emite refunds del período ya cobrado — el user mantiene
    Plus/Pro hasta fin de período."""
    log.info("Rebill cancel_subscription %s", subscription_id)
    r = httpx.patch(
        f"{REBILL_BASE_URL}/v3/subscriptions/{subscription_id}",
        headers={
            "x-api-key": _api_key(),
            "accept": "application/json",
            "content-type": "application/json",
        },
        json={"status": "cancelled"},
        timeout=15.0,
    )
    if r.status_code >= 400:
        log.error("Rebill cancel failed %s: %s", r.status_code, r.text)
        r.raise_for_status()
    return r.json()


# ─── Webhook signature verification ─────────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Valida HMAC-SHA256 del body usando REBILL_WEBHOOK_SECRET.

    SECURITY: si parece que estamos en prod (ver is_likely_production)
    SIN secret configurado, FALLAMOS cerrado (return False). En dev local
    permitimos saltear con warning.

    Antes del fix (2026-05-31): el chequeo era `if RENDI_ENV == 'prod'`,
    pero Nicolas no tenía esa env var seteada en Railway → en producción
    real con API key live, el código aceptaba CUALQUIER webhook sin firma.
    Vulnerabilidad: atacante podía gatillar `subscription.activated` fake
    y dar tier Pro gratis a sí mismo. Ahora is_likely_production() detecta
    prod via múltiples señales (RAILWAY_ENVIRONMENT, API key no-test_, etc).

    FORMATO INCIERTO: la doc pública de Rebill v3 no expone el formato exacto
    del header de signature. Probamos múltiples formatos comunes en LATAM
    payment processors:

      1. Hex puro:        `<hex_sha256>`
      2. Stripe-style:    `t=<ts>,v1=<hex>` (MP Argentina usa este)
      3. Prefijo schema:  `sha256=<hex>` (GitHub-style)
      4. Base64:          `<base64_sha256>`

    Si CUALQUIERA matchea con HMAC-SHA256(secret, body) → OK.
    Si NINGUNO matchea, loguea el formato recibido para debug y devuelve False.
    """
    import base64
    secret = _webhook_secret()
    if not secret:
        if is_likely_production():
            log.error(
                "REBILL_WEBHOOK_SECRET no configurada en producción — webhook rechazado. "
                "Configurá la env var en Railway con el secret del dashboard de Rebill. "
                "Esto NO debería pasar si estás en prod — los webhooks NO se aplican."
            )
            return False
        log.warning("REBILL_WEBHOOK_SECRET no configurada — saltando validación (dev local only)")
        return True

    if not signature_header:
        log.warning("Rebill webhook sin signature header")
        return False

    header = signature_header.strip()

    try:
        secret_bytes = secret.encode("utf-8")

        # Formato 1: hex puro del HMAC del body
        hex_expected = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(hex_expected, header):
            return True

        # Formato 2: prefijo "sha256=" (GitHub-style)
        if header.startswith("sha256="):
            received = header.split("=", 1)[1]
            if hmac.compare_digest(hex_expected, received):
                return True

        # Formato 3: Stripe/MP-style "t=<ts>,v1=<hex>" — el body firmado
        # podría ser `{ts}.{body}` (Stripe) o solo `{body}` (algunos otros).
        if "v1=" in header or "t=" in header:
            try:
                parts = {}
                for chunk in header.split(","):
                    if "=" in chunk:
                        k, v = chunk.split("=", 1)
                        parts[k.strip()] = v.strip()
                ts = parts.get("t", "")
                received_v1 = parts.get("v1", "")
                if received_v1:
                    # Probar con body solo
                    if hmac.compare_digest(hex_expected, received_v1):
                        return True
                    # Probar con timestamp + body (Stripe-style manifest)
                    if ts:
                        manifest = f"{ts}.{raw_body.decode('utf-8', errors='replace')}".encode("utf-8")
                        ts_hex = hmac.new(secret_bytes, manifest, hashlib.sha256).hexdigest()
                        if hmac.compare_digest(ts_hex, received_v1):
                            return True
            except Exception:
                pass

        # Formato 4: base64 del HMAC
        try:
            b64_expected = base64.b64encode(
                hmac.new(secret_bytes, raw_body, hashlib.sha256).digest()
            ).decode("ascii")
            if hmac.compare_digest(b64_expected, header):
                return True
        except Exception:
            pass

        # No matcheó ningún formato — logear chunk del header para debug.
        # Truncamos a 60 chars para no log full secrets.
        log.warning(
            "Rebill signature verify FAILED — formato no reconocido. "
            "header_prefix=%r expected_hex_prefix=%s",
            header[:60], hex_expected[:12] + "...",
        )
        return False
    except Exception as ex:
        log.error("Rebill signature verify error: %s", ex)
        return False


# ─── Utils ─────────────────────────────────────────────────────────────────

def extract_event_name(payload: dict) -> str:
    """Extrae el event name del webhook. Rebill lo envía en `webhook.event`
    (anidado), NO en el top-level del payload.
    """
    candidates = [
        (payload.get("webhook") or {}).get("event"),
        payload.get("event"),
        payload.get("type"),
        payload.get("eventType"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c
    return ""


def extract_subscription_id(payload: dict) -> str:
    """Extrae el subscription_id del webhook payload de Rebill.

    Estructura real observada en sandbox:
      • subscription.* → payload.data.subscription.id
      • payment.*      → payload.data.payment.id (es payment_id, no sub_id)
                         + payload.data.payment puede tener subscriptionId al lado
    """
    data = payload.get("data") or {}
    sub = data.get("subscription") or {}
    pay = data.get("payment") or {}
    candidates = [
        sub.get("id"),                          # subscription.* events
        pay.get("subscriptionId"),              # payment.* events
        data.get("subscription_id"),
        data.get("id"),
        payload.get("subscription_id"),
        payload.get("id"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c
    return ""


def extract_metadata(payload: dict) -> dict:
    """Extrae el metadata del webhook payload de Rebill.

    Estructura real observada en sandbox:
      • subscription.* → payload.data.subscription.metadata
      • payment.*      → payload.data.payment.metadata

    Ambos contienen el merged metadata (plan-level + paymentLink-level),
    incluyendo nuestro rendi_user_id.
    """
    data = payload.get("data") or {}
    candidates = [
        (data.get("subscription") or {}).get("metadata"),
        (data.get("payment") or {}).get("metadata"),
        data.get("metadata"),
        payload.get("metadata"),
        (payload.get("subscription") or {}).get("metadata"),
    ]
    for c in candidates:
        if c and isinstance(c, dict):
            return c
    return {}
