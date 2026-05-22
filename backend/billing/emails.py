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


# ─── Backend de envío ────────────────────────────────────────────────────────

def _send(to: str, subject: str, html: str, text: str,
          from_addr: Optional[str] = None) -> bool:
    """Backend-agnostic send. Retorna True si se envió OK.

    from_addr opcional: si no se pasa, usa _from_address() (default).
    Pasar _from_noreply() o _from_support() según el tipo de email.

    Si no hay provider configurado, loguea a console (modo dev) y retorna
    False — el caller asume que el evento no se notificó pero no falla."""
    sender = from_addr or _from_address()
    text = (
        f"{text}\n\n"
        f"---\n"
        f"¿Dudas? Escribinos por WhatsApp: +54 9 2914 37-3695\n"
        f"({SUPPORT_WHATSAPP_URL})"
    )
    if not _is_configured():
        log.info("=== EMAIL (no provider configured, logging only) ===")
        log.info("  FROM:    %s", sender)
        log.info("  TO:      %s", to)
        log.info("  SUBJECT: %s", subject)
        log.info("  TEXT:    %s", text[:400] + ("..." if len(text) > 400 else ""))
        log.info("================================================")
        return False

    import httpx
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "from": sender,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
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
