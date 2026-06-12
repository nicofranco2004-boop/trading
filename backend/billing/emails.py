"""emails — transactional emails de la app.
═══════════════════════════════════════════════════════════════════════════
Aunque el módulo viva bajo `billing/`, sirve para todos los emails
transaccionales — billing + auth/verificación + futuros.

6 emails:

  1. send_welcome_pro          — al activarse la suscripción Pro
  2. send_receipt              — cada renovación mensual/anual exitosa
  3. send_payment_failed       — cuando MP no puede cobrar la recurrencia
  4. send_cancellation         — cuando el user cancela
  5. send_expiration_reminder  — 3 días antes de fin de período pago
  6. send_verification_code    — código OTP de 6 dígitos para verificar email
                                 al registrarse

Provider:
  • Resend (default) — simple, gratis hasta 3k/mes, AR-friendly.
    Configurar RESEND_API_KEY en .env para activar.
  • Sin provider: log a console (modo dev / sin setup todavía).

Idempotencia:
  Cada email tiene un check antes de enviarse para evitar duplicados.
  Ver welcome_email_sent_at, last_receipt_sent_at en subscriptions.

Estilo:
  HTML simple, sin imágenes (mejor deliverability + carga rápida).
  Versión texto plano para clientes que no renderean HTML.
"""

from __future__ import annotations
import os
import sys
import html
import logging
from typing import Optional

log = logging.getLogger("billing.emails")


def _api_key() -> Optional[str]:
    return (os.environ.get("RESEND_API_KEY") or "").strip() or None


def _from_address() -> str:
    """Default sender (fallback). Para casos específicos usar _from_noreply
    o _from_support según corresponda."""
    return os.environ.get("EMAIL_FROM", "Rendi <no_reply@rendi.finance>")


def _from_noreply() -> str:
    """Para transaccionales que NO esperan respuesta del user (recibos,
    confirmaciones, OTPs, etc.). Replies caen igual al inbox vía alias."""
    return os.environ.get(
        "EMAIL_FROM_NOREPLY",
        "Rendi <no_reply@rendi.finance>",
    )


def _from_support() -> str:
    """Para emails donde el user puede tener dudas y responder (password
    reset, login alerts, pago fallido). Replies van a soporte@ → inbox."""
    return os.environ.get(
        "EMAIL_FROM_SUPPORT",
        "Rendi Soporte <soporte@rendi.finance>",
    )


def _is_configured() -> bool:
    return _api_key() is not None


# ─── Guarda anti-envío en tests / direcciones de prueba ──────────────────────
# RFC 2606/6761: .test/.example/.invalid/.localhost están reservados y nunca
# resuelven a un buzón real. Además, durante pytest NUNCA enviamos: los tests de
# auth/verify crean usuarios reset-*/verify-*@rendi.test y, como main.py hace
# load_dotenv del backend/.env (que tiene RESEND_API_KEY), sin esta guarda
# mandaban alertas de "nuevo usuario" REALES al inbox del fundador.
_TEST_EMAIL_SUFFIXES = (".test", ".example", ".invalid", ".localhost", ".local")


def _running_under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


def _is_test_address(addr: str) -> bool:
    a = (addr or "").strip().lower()
    return a.endswith(_TEST_EMAIL_SUFFIXES)


# ─── Backend de envío ────────────────────────────────────────────────────────

def _send(to: str, subject: str, html: str, text: str,
          from_addr: Optional[str] = None,
          reply_to: Optional[str] = None,
          append_footer: bool = True) -> bool:
    """Backend-agnostic send. Retorna True si se envió OK.

    from_addr opcional: si no se pasa, usa _from_address() (default).
    Pasar _from_noreply() o _from_support() según el tipo de email.

    reply_to opcional: si se pasa, Resend setea ese mail como destino
    cuando el receptor le da "Responder". Útil para feedback del user
    (recomendaciones, soporte) — el equipo de Rendi recibe el mail con
    el From de no_reply@ pero al apretar Reply en su cliente, escribe
    directo al user. Sin reply_to, las respuestas caen en no_reply@ y
    son ignoradas.

    append_footer: por default agregamos el footer con WhatsApp. Para
    feedback interno (que viene al equipo, no al user) lo deshabilitamos.

    Si no hay provider configurado, loguea a console (modo dev) y retorna
    False — el caller asume que el evento no se notificó pero no falla."""
    # Guarda dura: nunca enviar de verdad bajo pytest ni a direcciones de dominio
    # reservado (.test/.example/etc). Evita que la suite spamee el inbox real
    # cuando RESEND_API_KEY está cargada desde backend/.env.
    if _running_under_pytest() or _is_test_address(to):
        log.info("EMAIL skip (test): to=%s subject=%s", to, subject)
        return False
    sender = from_addr or _from_address()
    if append_footer:
        text = (
            f"{text}\n\n"
            f"---\n"
            f"¿Dudas? Escribinos por WhatsApp: +54 9 2914 37-3695\n"
            f"({SUPPORT_WHATSAPP_URL})"
        )
    if not _is_configured():
        log.info("=== EMAIL (no provider configured, logging only) ===")
        log.info("  FROM:     %s", sender)
        log.info("  TO:       %s", to)
        log.info("  REPLY_TO: %s", reply_to or "(none)")
        log.info("  SUBJECT:  %s", subject)
        log.info("  TEXT:     %s", text[:400] + ("..." if len(text) > 400 else ""))
        log.info("================================================")
        return False

    import httpx
    payload = {
        "from": sender,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        if r.status_code >= 400:
            log.error("Resend send failed %s for %s: %s", r.status_code, to, r.text)
            return False
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as ex:
        log.error("Resend send error for %s: %s", to, ex)
        return False


# ─── Helpers de formato ─────────────────────────────────────────────────────

def _fmt_ars(n: int | float) -> str:
    """ARS 12.100 con separador de miles."""
    return f"ARS {int(n):,}".replace(",", ".")


def _fmt_date(iso_str: Optional[str]) -> str:
    """ISO date → 'DD/MM/YYYY' (formato AR)."""
    if not iso_str:
        return "—"
    try:
        from datetime import datetime
        d = datetime.fromisoformat(iso_str.replace("Z", "").split(".")[0])
        return d.strftime("%d/%m/%Y")
    except Exception:
        return iso_str


SUPPORT_WHATSAPP_NUMBER = "542914373695"
SUPPORT_WHATSAPP_DISPLAY = "+54 9 2914 37-3695"
SUPPORT_WHATSAPP_URL = (
    f"https://wa.me/{SUPPORT_WHATSAPP_NUMBER}"
    "?text=Hola%2C%20quer%C3%ADa%20hacer%20una%20consulta%20acerca%20de%20Rendi."
)
SUPPORT_EMAIL = "soporte@rendi.finance"
APP_URL = "https://rendi.finance"


def _wrap_html(body: str) -> str:
    """Wrapper HTML mínimo con styles inline (no usamos CSS externo porque
    Gmail/Outlook a veces lo strippean).

    Header dark con el logo R sobre fondo casi-negro (#0A0B0E) — matchea el
    branding dark-mode de la app. El logo es el PNG en el CDN de Vercel."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rendi</title></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1f2e;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f5f7fa;padding:40px 0;">
    <tr><td align="center">
      <table cellpadding="0" cellspacing="0" border="0" width="560" style="background:#ffffff;border-radius:8px;overflow:hidden;">
        <tr>
          <td style="background:#0A0B0E;padding:28px 36px;text-align:left;">
            <img src="https://rendi.finance/brand/rendi-mark-email.png" alt="Rendi" width="48" height="48" style="display:inline-block;vertical-align:middle;border:0;">
            <span style="display:inline-block;vertical-align:middle;margin-left:12px;font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.02em;">Rendi</span>
          </td>
        </tr>
        <tr><td style="padding:36px;">
          {body}
          <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0 20px;">
          <p style="font-size:12px;color:#4b5563;line-height:1.6;margin:0 0 10px 0;">
            ¿Dudas o problemas? Escribinos por
            <a href="{SUPPORT_WHATSAPP_URL}" style="color:#25D366;font-weight:600;text-decoration:none;">WhatsApp ({SUPPORT_WHATSAPP_DISPLAY})</a>
            — te respondemos enseguida.
          </p>
          <p style="font-size:11px;color:#9ca3af;line-height:1.6;margin:0;">
            Este es un email automático de Rendi. Si preferís email, escribinos a
            soporte@rendi.finance.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# ─── Plan helpers (Plus / Pro) ─────────────────────────────────────────────

def _plan_label(plan: str) -> str:
    """'plus' → 'Plus', anything else → 'Pro'."""
    return "Plus" if plan == "plus" else "Pro"


def _plan_features_html(plan: str) -> str:
    """Bulleted list HTML de features incluidas en cada plan."""
    if plan == "plus":
        return """
        <li>Hasta <b>3 brokers</b></li>
        <li><b>Insights diagnóstico completo</b> (6 observaciones)</li>
        <li><b>4 análisis de comportamiento</b></li>
        <li><b>Distribución por activo</b></li>
        <li><b>Reportes históricos completos</b> (todos los meses)</li>
        <li>Export CSV consolidado para tu contador</li>
        """
    return """
        <li><b>60 análisis IA por semana</b> (10× más que Free)</li>
        <li>Respuestas con causalidad y comparaciones</li>
        <li>Follow-ups y AI Hub (próximamente)</li>
        <li>Brokers ilimitados</li>
        <li>Comportamiento + Reportes históricos completos</li>
        <li>Export CSV consolidado para tu contador</li>
    """


def _plan_features_text(plan: str) -> str:
    """Versión text plano de las features (para el cuerpo plain-text del email)."""
    if plan == "plus":
        return ("hasta 3 brokers, insights completo, 4 análisis de comportamiento, "
                "distribución por activo, reportes históricos y export CSV")
    return ("60 análisis IA por semana, brokers ilimitados, comportamiento + "
            "reportes completos, export CSV y más")


def _plan_loss_html(plan: str) -> str:
    """Lista HTML de features que se pierden al expirar/cancelar el plan."""
    if plan == "plus":
        return """
        <li>3 brokers (vas a quedar con 1)</li>
        <li>Insights diagnóstico completo (vas a quedar con 3 observaciones)</li>
        <li>4 análisis de comportamiento (vas a quedar con 1)</li>
        <li>Distribución por activo</li>
        <li>Reportes históricos completos</li>
        <li>Export CSV consolidado</li>
        """
    return """
        <li>60 análisis IA por semana (vas a quedar en 6)</li>
        <li>Follow-ups + AI Hub</li>
        <li>Brokers múltiples (vas a quedar con 1)</li>
        <li>Reportes históricos completos</li>
        <li>Export CSV consolidado</li>
    """


def _plan_loss_text(plan: str) -> str:
    if plan == "plus":
        return ("3 brokers (queda 1), insights (queda 3 obs), comportamiento (queda 1), "
                "distribución por activo, reportes históricos, export CSV")
    return ("60 análisis IA/sem (vs 6), follow-ups, brokers ilimitados, "
            "reportes históricos, export CSV")


# ─── Email #1: bienvenida (Plus / Pro) ──────────────────────────────────────

def send_welcome_pro(*, to: str, user_name: str, period: str,
                    amount_ars: int, next_charge_date: Optional[str],
                    plan: str = "pro") -> bool:
    """Email de bienvenida al activarse Plus o Pro.

    El nombre histórico es `send_welcome_pro` por back-compat con callers
    existentes — soporta los 2 planes con el param `plan`.
    """
    period_label = "mensual" if period == "monthly" else "anual"
    plan_label = _plan_label(plan)
    body_html = f"""
      <h1 style="font-size:24px;font-weight:700;margin:0 0 16px;">¡Bienvenido a Rendi {plan_label}, {user_name}!</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Tu suscripción <b>{period_label}</b> está activa. Ya tenés acceso a:
      </p>
      <ul style="font-size:14px;line-height:1.8;color:#374151;padding-left:20px;margin:0 0 20px;">
        {_plan_features_html(plan)}
      </ul>
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:16px;margin:20px 0;">
        <p style="font-size:13px;color:#6b7280;margin:0 0 4px;">Detalle de tu suscripción</p>
        <p style="font-size:14px;color:#1a1f2e;margin:0;">
          <b>{_fmt_ars(amount_ars)}</b> {period_label} · Próxima renovación: <b>{_fmt_date(next_charge_date)}</b>
        </p>
      </div>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        Podés cancelar cuando quieras desde Configuración → Mi plan.
      </p>
    """
    text = (
        f"¡Bienvenido a Rendi {plan_label}, {user_name}!\n\n"
        f"Tu suscripción {period_label} está activa.\n\n"
        f"Monto: {_fmt_ars(amount_ars)} · Próxima renovación: {_fmt_date(next_charge_date)}\n\n"
        f"Acceso a {_plan_features_text(plan)}.\n\n"
        f"Podés cancelar cuando quieras desde Configuración → Mi plan.\n\n"
        f"— Rendi"
    )
    return _send(to, f"¡Bienvenido a Rendi {plan_label}!", _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #2: recibo mensual ───────────────────────────────────────────────

def send_receipt(*, to: str, user_name: str, amount_ars: int,
                payment_date: str, next_charge_date: Optional[str],
                payment_id: Optional[str] = None,
                plan: str = "pro") -> bool:
    plan_label = _plan_label(plan)
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Recibo de pago · Rendi {plan_label}</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 20px;">
        Hola {user_name}, registramos tu pago de la suscripción.
      </p>
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:20px;margin:20px 0;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="font-size:14px;">
          <tr><td style="color:#6b7280;padding:4px 0;">Monto cobrado</td><td style="text-align:right;color:#1a1f2e;font-weight:600;">{_fmt_ars(amount_ars)}</td></tr>
          <tr><td style="color:#6b7280;padding:4px 0;">Fecha del cobro</td><td style="text-align:right;color:#1a1f2e;">{_fmt_date(payment_date)}</td></tr>
          <tr><td style="color:#6b7280;padding:4px 0;">Próximo cobro</td><td style="text-align:right;color:#1a1f2e;">{_fmt_date(next_charge_date)}</td></tr>
          {f'<tr><td style="color:#6b7280;padding:4px 0;">ID del pago</td><td style="text-align:right;color:#9ca3af;font-family:monospace;font-size:11px;">{payment_id}</td></tr>' if payment_id else ''}
        </table>
      </div>
      <p style="font-size:13px;color:#6b7280;line-height:1.6;">
        Para descargar tu factura formal, andá a Configuración → Mi plan.
      </p>
    """
    text = (
        f"Recibo de pago · Rendi {plan_label}\n\n"
        f"Hola {user_name}, registramos tu pago de la suscripción.\n\n"
        f"Monto: {_fmt_ars(amount_ars)}\n"
        f"Fecha: {_fmt_date(payment_date)}\n"
        f"Próximo cobro: {_fmt_date(next_charge_date)}\n"
        f"{f'ID: {payment_id}' if payment_id else ''}\n\n"
        f"— Rendi"
    )
    return _send(to, f"Recibo · Rendi {plan_label}", _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #3: pago fallido ─────────────────────────────────────────────────

def send_payment_failed(*, to: str, user_name: str,
                       retry_date: Optional[str] = None,
                       plan: str = "pro") -> bool:
    plan_label = _plan_label(plan)
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;color:#dc2626;">No pudimos cobrar tu suscripción</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, intentamos cobrar la renovación de tu suscripción Rendi {plan_label} pero el pago fue rechazado por tu banco o tarjeta.
      </p>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Causas frecuentes:
      </p>
      <ul style="font-size:14px;line-height:1.8;color:#374151;padding-left:20px;margin:0 0 20px;">
        <li>Tarjeta vencida o bloqueada</li>
        <li>Saldo insuficiente</li>
        <li>Límite de compras online alcanzado</li>
      </ul>
      <div style="background:#fef3c7;border:1px solid #fbbf24;border-radius:6px;padding:14px;margin:20px 0;">
        <p style="font-size:14px;color:#92400e;margin:0;">
          ⚠️ <b>Tu cuenta sigue como {plan_label} hasta el {_fmt_date(retry_date)}.</b> Mercado Pago va a reintentar el cobro automáticamente. Si el problema persiste, actualizá tu medio de pago.
        </p>
      </div>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        Andá a <a href="https://www.mercadopago.com.ar/subscriptions" style="color:#8B7BFF;text-decoration:none;">tu panel de Mercado Pago</a> para revisar.
      </p>
    """
    text = (
        f"No pudimos cobrar tu suscripción Rendi {plan_label}\n\n"
        f"Hola {user_name}, el pago fue rechazado por tu banco o tarjeta.\n\n"
        f"Tu cuenta sigue como {plan_label} hasta el {_fmt_date(retry_date)}. "
        f"Mercado Pago va a reintentar el cobro automáticamente.\n\n"
        f"Andá a mercadopago.com.ar/subscriptions para revisar tu medio de pago.\n\n"
        f"— Rendi"
    )
    return _send(to, f"⚠️ No pudimos cobrar tu suscripción Rendi {plan_label}",
                 _wrap_html(body_html), text,
                 from_addr=_from_support())


# ─── Email #4: cancelación confirmada ──────────────────────────────────────

def send_cancellation(*, to: str, user_name: str, valid_until: str,
                     plan: str = "pro") -> bool:
    plan_label = _plan_label(plan)
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Cancelación confirmada</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, tu suscripción Rendi {plan_label} fue cancelada.
      </p>
      <div style="background:#f5f3ff;border:1px solid #c4b5fd;border-radius:6px;padding:16px;margin:20px 0;">
        <p style="font-size:14px;color:#5b21b6;margin:0;">
          ✓ Mantenés acceso completo a {plan_label} hasta el <b>{_fmt_date(valid_until)}</b>. Después de esa fecha, tu cuenta vuelve a Free.
        </p>
      </div>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        No te vamos a cobrar más. Tus datos quedan intactos y siempre podés volver a suscribirte cuando quieras.
      </p>
      <p style="font-size:13px;color:#6b7280;line-height:1.6;margin-top:24px;">
        Si cancelaste por error o tuviste algún problema, contestá este email y te ayudamos.
      </p>
    """
    text = (
        f"Cancelación confirmada\n\n"
        f"Hola {user_name}, tu suscripción Rendi {plan_label} fue cancelada.\n\n"
        f"Mantenés {plan_label} hasta el {_fmt_date(valid_until)}. "
        f"Después de esa fecha, tu cuenta vuelve a Free.\n\n"
        f"No te vamos a cobrar más. Si cancelaste por error, contestá este email.\n\n"
        f"— Rendi"
    )
    return _send(to, f"Cancelación confirmada · Rendi {plan_label}",
                 _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #5: recordatorio de expiración (3 días antes) ───────────────────

def send_expiration_reminder(*, to: str, user_name: str,
                             days_left: int, expires_at: str,
                             plan: str = "pro") -> bool:
    plan_label = _plan_label(plan)
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Tu plan {plan_label} vence en {days_left} {'día' if days_left == 1 else 'días'}</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, te avisamos que tu suscripción Rendi {plan_label} va a expirar el <b>{_fmt_date(expires_at)}</b>.
      </p>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 20px;">
        Después de esa fecha, vas a perder acceso a:
      </p>
      <ul style="font-size:14px;line-height:1.8;color:#374151;padding-left:20px;margin:0 0 20px;">
        {_plan_loss_html(plan)}
      </ul>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        Si querés mantener {plan_label}, volvé a suscribirte desde <a href="https://rendi.finance/planes" style="color:#8B7BFF;text-decoration:none;">tu panel</a>.
      </p>
    """
    text = (
        f"Tu plan Rendi {plan_label} vence en {days_left} días\n\n"
        f"Hola {user_name}, tu suscripción expira el {_fmt_date(expires_at)}.\n\n"
        f"Después vas a perder: {_plan_loss_text(plan)}.\n\n"
        f"Para renovar: andá a rendi.finance/planes\n\n"
        f"— Rendi"
    )
    return _send(to, f"⏰ Tu Rendi {plan_label} vence en {days_left} {'día' if days_left == 1 else 'días'}",
                 _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #6: código de verificación post-register ─────────────────────────

def send_verification_code(*, to: str, user_name: str, code: str,
                           expires_minutes: int = 15) -> bool:
    """Manda el OTP de 6 dígitos al user para que confirme su email."""
    # Subject con el código adentro — se ve en notificaciones del celular
    # antes de que el user abra el email (UX más rápido).
    subject = f"Tu código de Rendi: {code}"
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Confirmá tu cuenta</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 20px;">
        Hola {user_name}, ingresá este código en Rendi para terminar de crear tu cuenta:
      </p>
      <div style="background:#f5f3ff;border:2px solid #8B7BFF;border-radius:8px;padding:20px;margin:20px 0;text-align:center;">
        <p style="font-size:11px;color:#5b21b6;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:0 0 8px;">Tu código</p>
        <p style="font-family:monospace;font-size:38px;font-weight:700;color:#5b21b6;letter-spacing:8px;margin:0;">{code}</p>
      </div>
      <p style="font-size:13px;color:#6b7280;line-height:1.6;margin:12px 0;">
        Vence en <b>{expires_minutes} minutos</b>. Si no fuiste vos quien intentó registrarse,
        ignorá este email — nadie va a poder acceder sin el código.
      </p>
    """
    text = (
        f"Confirmá tu cuenta en Rendi\n\n"
        f"Hola {user_name}, ingresá este código para terminar de crear tu cuenta:\n\n"
        f"   {code}\n\n"
        f"Vence en {expires_minutes} minutos.\n\n"
        f"Si no fuiste vos, ignorá este email — nadie podrá acceder sin el código.\n\n"
        f"— Rendi"
    )
    return _send(to, subject, _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #6b: bienvenida post-verificación (registro completado, plan Free) ─

def send_welcome_free(*, to: str, user_name: str) -> bool:
    """Se manda una vez, cuando el user verifica su email (= completa el
    registro). Lo orienta al Home (mini guía de cómo funciona) e invita a
    consultas/recomendaciones. Replies → soporte@ (usamos _from_support)."""
    subject = "Completaste tu registro en Rendi"
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Tu cuenta está lista</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, completaste tu registro en Rendi. Ya podés cargar tu primer broker
        y ver tu portfolio consolidado en dólares.
      </p>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 24px;">
        En la sección <b>Home</b> tenés una mini guía de cómo funciona. Empezá por ahí.
      </p>
      <div style="text-align:center;margin:24px 0;">
        <a href="{APP_URL}" style="display:inline-block;background:#8B7BFF;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:600;font-size:15px;">
          Entrar a Rendi
        </a>
      </div>
      <p style="font-size:14px;line-height:1.6;color:#374151;margin:16px 0 0;">
        Cualquier consulta o recomendación, no dudes en escribirnos a
        <a href="mailto:{SUPPORT_EMAIL}" style="color:#8B7BFF;text-decoration:none;font-weight:600;">{SUPPORT_EMAIL}</a>
        o por <a href="{SUPPORT_WHATSAPP_URL}" style="color:#25D366;text-decoration:none;font-weight:600;">WhatsApp ({SUPPORT_WHATSAPP_DISPLAY})</a>.
        Leemos todo.
      </p>
    """
    text = (
        "Tu cuenta está lista\n\n"
        f"Hola {user_name}, completaste tu registro en Rendi. Ya podés cargar tu primer "
        "broker y ver tu portfolio consolidado en dólares.\n\n"
        "En la sección Home tenés una mini guía de cómo funciona. Empezá por ahí.\n\n"
        f"Entrá a Rendi: {APP_URL}\n\n"
        f"Cualquier consulta o recomendación, escribinos a {SUPPORT_EMAIL} o por "
        f"WhatsApp ({SUPPORT_WHATSAPP_DISPLAY}). Leemos todo.\n\n"
        "— Rendi"
    )
    return _send(to, subject, _wrap_html(body_html), text,
                 from_addr=_from_support())


def send_reengagement(*, to: str, user_name: str = "") -> bool:
    """Re-engagement para usuarios verificados que se registraron pero casi no
    cargaron nada (≤1 operación). Tono lite, sin presión. Replies → soporte@.

    Formato deliberadamente PLANO — sin header con logo, sin botón grande, un
    solo link de texto, alto ratio texto/markup — para caer en la pestaña
    Principal de Gmail y no en Promociones. Los mails con pinta de "mailing"
    (banner de imagen + CTA de color) tabulan a Promociones; un mail que parece
    escrito 1-a-1 entra a Principal. Por eso NO usamos _wrap_html acá (ese
    wrapper agrega el header dark con logo + footer = señales de promo).

    El link apunta a la home (APP_URL), no a una sub-ruta: es la entrada más
    confiable para un click "en frío" (no logueado) y un dominio pelado se lee
    menos spammy que un deep-link."""
    safe_name = html.escape((user_name or "").strip())
    greeting_html = f"Hola {safe_name}," if safe_name else "Hola,"
    greeting_text = f"Hola {(user_name or '').strip()}," if (user_name or "").strip() else "Hola,"
    subject = "Tu historial en Rendi, cuando quieras"
    body_html = (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:#1a1f2e;">'
        f'<p style="margin:0 0 14px;">{greeting_html} vimos que todavía no importaste '
        'tu historial — sin apuro, sabemos que esas cosas quedan para después.</p>'
        '<p style="margin:0 0 14px;">Por si no lo sabías: no hace falta cargar operación '
        'por operación. Subís el CSV de movimientos de tu broker (Cocos, IOL, Binance, '
        'Schwab) y Rendi te reconstruye la cartera entera en segundos. Recién ahí se ve '
        'lo bueno — tu P&amp;L real en dólares y cómo viene todo, junto.</p>'
        f'<p style="margin:0 0 14px;">Cuando tengas un rato, entrás en '
        f'<a href="{APP_URL}" style="color:#5b4ddb;">rendi.finance</a> y lo importás.</p>'
        '<p style="margin:0 0 14px;">Y si te trabás en algo, respondé este mail y te '
        'damos una mano.</p>'
        '<p style="margin:18px 0 0;">— Rendi</p>'
        '</div>'
    )
    text = (
        f"{greeting_text} vimos que todavía no importaste tu historial — sin apuro, "
        "sabemos que esas cosas quedan para después.\n\n"
        "Por si no lo sabías: no hace falta cargar operación por operación. Subís el "
        "CSV de movimientos de tu broker (Cocos, IOL, Binance, Schwab) y Rendi te "
        "reconstruye la cartera entera en segundos. Recién ahí se ve lo bueno — tu "
        "P&L real en dólares y cómo viene todo, junto.\n\n"
        f"Cuando tengas un rato, entrás en {APP_URL} y lo importás.\n\n"
        "Y si te trabás en algo, respondé este mail y te damos una mano.\n\n"
        "— Rendi"
    )
    return _send(to, subject, body_html, text, from_addr=_from_support())


# ─── Email interno: alerta al equipo por cada signup real (primeros N) ───────

def send_new_signup_admin(*, to: str, new_user_email: str,
                          new_user_name: Optional[str], count: int) -> bool:
    """Aviso INTERNO al equipo cuando un usuario nuevo completa el registro
    (verifica su email). Pensado para los primeros usuarios — reachout temprano.
    Best-effort, no afecta el flujo del user.

    SECURITY: name/email son user-controlled → se escapan antes de ir al HTML
    para evitar inyección de markup en el inbox del admin."""
    # El `to` es el admin (real), pero si el usuario nuevo es de un dominio de
    # prueba (reset-*/verify-*@rendi.test), no avisamos: es data de test, no un
    # signup real. (El guard de _send no lo cubre porque `to` no es de test.)
    if _is_test_address(new_user_email):
        return False
    name = new_user_name or new_user_email.split("@")[0]
    safe_name = html.escape(name)
    safe_email = html.escape(new_user_email)
    subject = f"Rendi · nuevo usuario #{count}: {new_user_email}"
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Nuevo registro #{count}</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Un usuario nuevo se registró y verificó su email en Rendi.
      </p>
      <table cellpadding="0" cellspacing="0" border="0" style="width:100%;font-size:14px;color:#374151;margin:0 0 20px;">
        <tr><td style="padding:6px 0;color:#6b7280;width:90px;">Nombre</td><td style="padding:6px 0;font-weight:600;">{safe_name}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Email</td><td style="padding:6px 0;font-weight:600;">{safe_email}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Número</td><td style="padding:6px 0;font-weight:600;">#{count}</td></tr>
      </table>
      <p style="font-size:14px;line-height:1.6;color:#6b7280;margin:0;">
        Buen momento para un saludo o pedirle feedback.
      </p>
    """
    text = (
        f"Nuevo registro #{count} en Rendi\n\n"
        f"Nombre: {name}\n"
        f"Email:  {new_user_email}\n"
        f"Número: #{count}\n\n"
        "Buen momento para un saludo o pedirle feedback.\n"
    )
    return _send(to, subject, _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email interno: alerta al admin por cada CAMBIO DE PLAN ──────────────────

def _tier_label(tier: Optional[str]) -> str:
    """Normaliza el tier a una etiqueta legible. NULL / '' / 'free' / cualquier
    valor desconocido → 'Free' (es el estado por defecto del usuario).

    OJO: distinto de _plan_label (más arriba), que asume plus/pro y devuelve
    'Pro' por defecto. Acá necesitamos manejar 'free'/None → 'Free'."""
    t = (tier or "").strip().lower()
    return {"plus": "Plus", "pro": "Pro"}.get(t, "Free")


# Etiqueta legible del origen del cambio (lo que disparó la transición).
_PLAN_CHANGE_SOURCES = {
    "payment":              "Pago (Rebill)",
    "plan_change":          "Cambio de plan",
    "credit_expired":       "Vencimiento de crédito",
    "cancellation_expired": "Cancelación · fin de período",
    "admin_grant":          "Otorgado por admin",
    "admin_restore":        "Restaurado por admin",
}


def send_plan_change_admin(*, user_email: str, old_plan: Optional[str],
                           new_plan: Optional[str], source: str,
                           user_name: Optional[str] = None,
                           amount_usd: Optional[float] = None) -> bool:
    """Aviso INTERNO al admin cuando un usuario CAMBIA de plan (free/plus/pro).

    Cubre todas las transiciones: pago de Plus/Pro (free→pago), upgrade/downgrade
    plus↔pro, baja a Free (vencimiento de crédito o fin de período por
    cancelación) y cambios hechos por el admin (grant/restore).

    Destinatario: ADMIN_NOTIFY_EMAIL (el mismo que el aviso de nuevo signup).

    Idempotencia barata: si old==new (normalizados a etiqueta) NO manda. Esto
    deduplica reintentos del webhook de Rebill — en el 2º intento el tier ya
    quedó cambiado, así que old==new y no se reenvía.

    SECURITY: email/name son user-controlled → html.escape antes del HTML, para
    evitar inyección de markup en el inbox del admin. Best-effort: no afecta
    ningún flujo de billing.
    """
    old_label = _tier_label(old_plan)
    new_label = _tier_label(new_plan)
    if old_label == new_label:
        return False  # no hubo cambio real de tier (o reintento de webhook)
    # No avisar por usuarios de dominio de prueba (reset-*/verify-*@rendi.test).
    # Igual que send_new_signup_admin: el guard de _send no lo cubre porque el
    # `to` (admin) no es de test.
    if _is_test_address(user_email):
        return False
    to = (os.environ.get("ADMIN_NOTIFY_EMAIL") or "").strip()
    if not to:
        return False

    safe_name = html.escape(user_name or user_email.split("@")[0])
    safe_email = html.escape(user_email)
    source_label = _PLAN_CHANGE_SOURCES.get(source, source)
    safe_source = html.escape(source_label)

    amount_row = ""
    amount_text = ""
    if amount_usd:
        try:
            safe_amount = html.escape(f"USD {float(amount_usd):,.2f}")
            amount_row = (
                f'<tr><td style="padding:6px 0;color:#6b7280;">Monto</td>'
                f'<td style="padding:6px 0;font-weight:600;">{safe_amount}</td></tr>'
            )
            amount_text = f"Monto:  USD {float(amount_usd):,.2f}\n"
        except (TypeError, ValueError):
            pass

    subject = f"Rendi · cambio de plan: {old_label} → {new_label} ({user_email})"
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Cambio de plan</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Un usuario cambió de plan en Rendi: <strong>{old_label} → {new_label}</strong>.
      </p>
      <table cellpadding="0" cellspacing="0" border="0" style="width:100%;font-size:14px;color:#374151;margin:0 0 20px;">
        <tr><td style="padding:6px 0;color:#6b7280;width:90px;">Usuario</td><td style="padding:6px 0;font-weight:600;">{safe_name}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Email</td><td style="padding:6px 0;font-weight:600;">{safe_email}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Cambio</td><td style="padding:6px 0;font-weight:600;">{old_label} → {new_label}</td></tr>
        <tr><td style="padding:6px 0;color:#6b7280;">Origen</td><td style="padding:6px 0;font-weight:600;">{safe_source}</td></tr>
        {amount_row}
      </table>
    """
    text = (
        f"Cambio de plan en Rendi\n\n"
        f"Usuario: {user_name or user_email.split('@')[0]}\n"
        f"Email:   {user_email}\n"
        f"Cambio:  {old_label} -> {new_label}\n"
        f"Origen:  {source_label}\n"
        f"{amount_text}"
    )
    return _send(to, subject, _wrap_html(body_html), text,
                 from_addr=_from_noreply())


# ─── Email #7: reset de contraseña (magic link) ─────────────────────────────

def send_password_reset(*, to: str, user_name: str, reset_url: str,
                       expires_minutes: int = 30) -> bool:
    """Envía un email con un magic link para restablecer la contraseña.

    El reset_url contiene el token en la query string. El frontend abre
    una pantalla con form de nueva contraseña que postea al endpoint
    /api/auth/reset-password con el token."""
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Restablecé tu contraseña</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, recibimos una solicitud para restablecer tu contraseña en Rendi.
      </p>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 24px;">
        Hacé click en el botón de abajo para crear una nueva contraseña:
      </p>
      <div style="text-align:center;margin:28px 0;">
        <a href="{reset_url}" style="display:inline-block;background:#8B7BFF;color:#ffffff;text-decoration:none;padding:14px 32px;border-radius:8px;font-weight:600;font-size:15px;">
          Restablecer contraseña
        </a>
      </div>
      <p style="font-size:13px;color:#6b7280;line-height:1.6;margin:0 0 8px;">
        O copiá y pegá este link en tu navegador:
      </p>
      <p style="font-size:11px;color:#8B7BFF;word-break:break-all;font-family:monospace;background:#f9fafb;padding:10px;border-radius:4px;margin:0 0 20px;">
        {reset_url}
      </p>
      <p style="font-size:13px;color:#6b7280;line-height:1.6;">
        El link vence en <b>{expires_minutes} minutos</b>. Si no pediste cambiar tu
        contraseña, ignorá este email — nadie va a poder cambiarla sin acceso al link.
      </p>
    """
    text = (
        f"Restablecé tu contraseña en Rendi\n\n"
        f"Hola {user_name}, recibimos una solicitud para restablecer tu contraseña.\n\n"
        f"Para crear una nueva, abrí este link en tu navegador:\n"
        f"{reset_url}\n\n"
        f"El link vence en {expires_minutes} minutos.\n\n"
        f"Si no fuiste vos, ignorá este email — nadie podrá cambiar tu contraseña sin el link.\n\n"
        f"— Rendi"
    )
    return _send(to, "Restablecé tu contraseña · Rendi",
                 _wrap_html(body_html), text,
                 from_addr=_from_support())


def send_new_login_alert(*, to: str, user_name: str, device: str,
                         ip: str, when: str) -> bool:
    """Avisa al usuario que se detectó un inicio de sesión desde un
    dispositivo nuevo (ua_hash no visto antes). NO se manda en el primer
    login (esperable, ruido). Si el user no reconoce el dispositivo, debe
    cambiar la contraseña inmediatamente — eso invalida sesiones viejas."""
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Nuevo inicio de sesión</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, detectamos un inicio de sesión en tu cuenta de Rendi
        desde un dispositivo que no habíamos visto antes.
      </p>
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:18px;margin:18px 0;">
        <table cellpadding="0" cellspacing="0" border="0" width="100%" style="font-size:14px;">
          <tr><td style="color:#6b7280;padding:4px 0;">Dispositivo</td><td style="text-align:right;color:#1a1f2e;font-weight:600;">{device}</td></tr>
          <tr><td style="color:#6b7280;padding:4px 0;">IP</td><td style="text-align:right;color:#1a1f2e;font-family:monospace;">{ip}</td></tr>
          <tr><td style="color:#6b7280;padding:4px 0;">Fecha</td><td style="text-align:right;color:#1a1f2e;">{when}</td></tr>
        </table>
      </div>
      <p style="font-size:14px;line-height:1.6;color:#374151;margin:0 0 8px;">
        <b>¿Fuiste vos?</b> Listo, podés ignorar este email.
      </p>
      <p style="font-size:14px;line-height:1.6;color:#374151;margin:0;">
        <b>¿No fuiste vos?</b> Cambiá tu contraseña inmediatamente desde
        Configuración → Contraseña. Eso invalida todas las sesiones abiertas.
      </p>
    """
    text = (
        f"Nuevo inicio de sesión en tu cuenta de Rendi\n\n"
        f"Hola {user_name}, registramos un login desde un dispositivo nuevo:\n\n"
        f"  Dispositivo: {device}\n"
        f"  IP:          {ip}\n"
        f"  Fecha:       {when}\n\n"
        f"¿Fuiste vos? Listo, ignorá este email.\n"
        f"¿No fuiste vos? Cambiá tu contraseña inmediatamente desde\n"
        f"Configuración → Contraseña. Eso invalida sesiones abiertas.\n\n"
        f"— Rendi"
    )
    return _send(to, "Nuevo inicio de sesión · Rendi",
                 _wrap_html(body_html), text,
                 from_addr=_from_support())



# ─── User feedback (recomendaciones, ideas, bugs) ──────────────────────────
# Mail que llega al equipo de Rendi (recomendaciones@rendi.finance) cuando un
# user manda una recomendación desde el modal in-app. NO es transaccional al
# user — es feedback hacia adentro. Por eso:
#   • From: no_reply@ (el equipo no tiene que responder a "Rendi")
#   • Reply-To: email del user → cuando Nico apreta Reply en su Gmail,
#     escribe directo al user. Sin esto, los replies van al limbo.
#   • Sin footer de WhatsApp (es interno, no consumer-facing).
#   • Body incluye user info (mail, name, tier) para contexto al leerlo.

def send_user_recommendation(
    user_email: str,
    user_name: str,
    user_tier: str,
    subject: str,
    body: str,
) -> bool:
    """Envía un mail al inbox de recomendaciones@rendi.finance con el
    feedback del user. Sanitiza subject + body por seguridad.

    SECURITY: TODOS los campos user-controlled (name, email, subject, body,
    tier) pasan por html.escape antes de interpolar en el HTML, para
    prevenir HTML/script injection en el inbox del equipo. Un user con
    nombre `<img src=x onerror="...">` o body con `</p><script>...</script>`
    no puede inyectar JS en el inbox.
    """
    from html import escape

    # Sanitización básica del subject (evitar header injection)
    safe_subject = (subject or "").strip().replace("\n", " ").replace("\r", " ")
    if len(safe_subject) > 200:
        safe_subject = safe_subject[:197] + "..."
    if not safe_subject:
        safe_subject = "(sin asunto)"

    safe_body = (body or "").strip()
    if len(safe_body) > 5000:
        safe_body = safe_body[:5000] + "\n\n[... truncado ...]"

    # Escape para HTML del email (Gmail/Outlook etc). text version queda tal cual.
    esc_name = escape(user_name or "")
    esc_email = escape(user_email or "")
    esc_tier = escape((user_tier or "free").upper())
    esc_subject = escape(safe_subject)
    esc_body = escape(safe_body)

    # HTML del mail — formato chat-like para que se lea cómodo en el inbox.
    html_body = f"""
      <h2 style="font-size:18px;margin:0 0 16px;color:#1a1f2e;">
        Nueva recomendación desde Rendi
      </h2>
      <table cellpadding="0" cellspacing="0" border="0" width="100%"
             style="background:#f5f7fa;border-radius:6px;padding:14px;margin-bottom:18px;">
        <tr><td style="font-size:14px;line-height:1.7;color:#374151;">
          <b style="color:#1a1f2e;">De:</b> {esc_name} &lt;{esc_email}&gt;<br>
          <b style="color:#1a1f2e;">Plan:</b> {esc_tier}<br>
          <b style="color:#1a1f2e;">Asunto:</b> {esc_subject}
        </td></tr>
      </table>
      <p style="font-size:14px;line-height:1.7;color:#374151;white-space:pre-wrap;
                background:#ffffff;border-left:3px solid #8b7dff;padding:12px 16px;
                margin:0 0 18px;border-radius:0 4px 4px 0;">
{esc_body}
      </p>
      <p style="font-size:12px;color:#6b7280;margin:0;">
        Para responder, apretá Reply — la respuesta va directo a {esc_email}.
      </p>
    """
    text = (
        f"Nueva recomendación desde Rendi\n"
        f"================================\n\n"
        f"De:     {user_name} <{user_email}>\n"
        f"Plan:   {user_tier.upper()}\n"
        f"Asunto: {safe_subject}\n\n"
        f"--- Mensaje ---\n"
        f"{safe_body}\n"
        f"---\n\n"
        f"Reply va directo a {user_email}."
    )
    return _send(
        to="recomendaciones@rendi.finance",
        subject=f"[Recomendación] {safe_subject}",
        html=_wrap_html(html_body),
        text=text,
        from_addr=_from_noreply(),
        reply_to=user_email,
        append_footer=False,  # interno, no consumer
    )


def send_recommendation_acknowledgment(user_email: str, user_name: str) -> bool:
    """Acuse de recibo automático al user después de mandar una recomendación.

    Se llama desde el endpoint POST /api/feedback/recommendation después de
    enviar el mail al equipo. Reemplaza el filtro de Gmail (que era poco
    confiable porque respondía al From de no_reply@, no al user real).

    Tono: cálido pero no efusivo. Confirma recepción + plazo de respuesta
    (48hs si requiere) + agradecimiento por el feedback.
    """
    safe_name = (user_name or "").strip() or "Hola"
    body_html = f"""
      <p style="font-size:16px;line-height:1.7;margin:0 0 16px;">{safe_name},</p>
      <p style="font-size:14px;line-height:1.7;color:#374151;margin:0 0 16px;">
        Gracias por tomarte el tiempo de mandarnos esta recomendación.
        La leemos personalmente — si hace falta una respuesta, te contestamos
        en un plazo máximo de <b>48 horas hábiles</b>.
      </p>
      <p style="font-size:14px;line-height:1.7;color:#374151;margin:0 0 16px;">
        Las ideas y feedback de los users son lo que más nos sirve para mejorar
        Rendi. Gracias por ayudarnos a hacerlo mejor.
      </p>
      <p style="font-size:14px;line-height:1.7;color:#374151;margin:0 0 8px;">
        Un abrazo,<br>
        Equipo Rendi
      </p>
      <p style="font-size:12px;color:#9ca3af;margin:24px 0 0 0;">
        Este es un mensaje automático. No respondas a este mail — alguien
        del equipo te va a contestar pronto si tu recomendación lo requiere.
      </p>
    """
    text = (
        f"{safe_name},\n\n"
        f"Gracias por tomarte el tiempo de mandarnos esta recomendación.\n"
        f"La leemos personalmente — si hace falta una respuesta, te contestamos\n"
        f"en un plazo máximo de 48 horas hábiles.\n\n"
        f"Las ideas y feedback de los users son lo que más nos sirve para\n"
        f"mejorar Rendi. Gracias por ayudarnos a hacerlo mejor.\n\n"
        f"Un abrazo,\n"
        f"Equipo Rendi\n\n"
        f"---\n"
        f"Este es un mensaje automático. No respondas a este mail."
    )
    return _send(
        to=user_email,
        subject="Recibimos tu recomendación — Rendi",
        html=_wrap_html(body_html),
        text=text,
        from_addr=_from_noreply(),
        append_footer=False,  # ya tiene su propio cierre, sin WhatsApp
    )
