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
    return os.environ.get("EMAIL_FROM", "Rendi <hello@rendi.app>")


def _is_configured() -> bool:
    return _api_key() is not None


# ─── Backend de envío ────────────────────────────────────────────────────────

def _send(to: str, subject: str, html: str, text: str) -> bool:
    """Backend-agnostic send. Retorna True si se envió OK.

    Si no hay provider configurado, loguea a console (modo dev) y retorna
    False — el caller asume que el evento no se notificó pero no falla."""
    if not _is_configured():
        log.info("=== EMAIL (no provider configured, logging only) ===")
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
                "from": _from_address(),
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


def _wrap_html(body: str) -> str:
    """Wrapper HTML mínimo con styles inline (no usamos CSS externo porque
    Gmail/Outlook a veces lo strippean)."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Rendi</title></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1a1f2e;">
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f5f7fa;padding:40px 0;">
    <tr><td align="center">
      <table cellpadding="0" cellspacing="0" border="0" width="560" style="background:#ffffff;border-radius:8px;padding:36px;">
        <tr><td>
          <div style="font-size:20px;font-weight:700;color:#21D07A;margin-bottom:24px;">Rendi</div>
          {body}
          <hr style="border:none;border-top:1px solid #e5e7eb;margin:32px 0 20px;">
          <p style="font-size:11px;color:#9ca3af;line-height:1.6;margin:0;">
            Este es un email automático de Rendi. Si tenés dudas, respondé a este email
            o escribinos a hello@rendi.app.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# ─── Email #1: bienvenida Pro ───────────────────────────────────────────────

def send_welcome_pro(*, to: str, user_name: str, period: str,
                    amount_ars: int, next_charge_date: Optional[str]) -> bool:
    period_label = "mensual" if period == "monthly" else "anual"
    body_html = f"""
      <h1 style="font-size:24px;font-weight:700;margin:0 0 16px;">¡Bienvenido a Rendi Pro, {user_name}!</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Tu suscripción <b>{period_label}</b> está activa. Ya tenés acceso completo a:
      </p>
      <ul style="font-size:14px;line-height:1.8;color:#374151;padding-left:20px;margin:0 0 20px;">
        <li><b>60 análisis IA por semana</b> (10× más que Free)</li>
        <li>Respuestas con causalidad y comparaciones</li>
        <li>Follow-ups y AI Hub (próximamente)</li>
        <li>Brokers ilimitados</li>
        <li>Comportamiento + Reportes históricos completos</li>
        <li>Export CSV consolidado para tu contador</li>
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
        f"¡Bienvenido a Rendi Pro, {user_name}!\n\n"
        f"Tu suscripción {period_label} está activa.\n\n"
        f"Monto: {_fmt_ars(amount_ars)} · Próxima renovación: {_fmt_date(next_charge_date)}\n\n"
        f"Acceso completo a 60 análisis IA por semana, brokers ilimitados, "
        f"comportamiento + reportes completos, export CSV y más.\n\n"
        f"Podés cancelar cuando quieras desde Configuración → Mi plan.\n\n"
        f"— Rendi"
    )
    return _send(to, "¡Bienvenido a Rendi Pro!", _wrap_html(body_html), text)


# ─── Email #2: recibo mensual ───────────────────────────────────────────────

def send_receipt(*, to: str, user_name: str, amount_ars: int,
                payment_date: str, next_charge_date: Optional[str],
                payment_id: Optional[str] = None) -> bool:
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Recibo de pago · Rendi Pro</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 20px;">
        Hola {user_name}, registramos tu pago de la suscripción mensual.
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
        f"Recibo de pago · Rendi Pro\n\n"
        f"Hola {user_name}, registramos tu pago de la suscripción.\n\n"
        f"Monto: {_fmt_ars(amount_ars)}\n"
        f"Fecha: {_fmt_date(payment_date)}\n"
        f"Próximo cobro: {_fmt_date(next_charge_date)}\n"
        f"{f'ID: {payment_id}' if payment_id else ''}\n\n"
        f"— Rendi"
    )
    return _send(to, "Recibo · Rendi Pro", _wrap_html(body_html), text)


# ─── Email #3: pago fallido ─────────────────────────────────────────────────

def send_payment_failed(*, to: str, user_name: str,
                       retry_date: Optional[str] = None) -> bool:
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;color:#dc2626;">No pudimos cobrar tu suscripción</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, intentamos cobrar la renovación de tu suscripción Rendi Pro pero el pago fue rechazado por tu banco o tarjeta.
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
          ⚠️ <b>Tu cuenta sigue como Pro hasta el {_fmt_date(retry_date)}.</b> Mercado Pago va a reintentar el cobro automáticamente. Si el problema persiste, actualizá tu medio de pago.
        </p>
      </div>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        Andá a <a href="https://www.mercadopago.com.ar/subscriptions" style="color:#21D07A;text-decoration:none;">tu panel de Mercado Pago</a> para revisar.
      </p>
    """
    text = (
        f"No pudimos cobrar tu suscripción Rendi Pro\n\n"
        f"Hola {user_name}, el pago fue rechazado por tu banco o tarjeta.\n\n"
        f"Tu cuenta sigue como Pro hasta el {_fmt_date(retry_date)}. "
        f"Mercado Pago va a reintentar el cobro automáticamente.\n\n"
        f"Andá a mercadopago.com.ar/subscriptions para revisar tu medio de pago.\n\n"
        f"— Rendi"
    )
    return _send(to, "⚠️ No pudimos cobrar tu suscripción Rendi Pro",
                 _wrap_html(body_html), text)


# ─── Email #4: cancelación confirmada ──────────────────────────────────────

def send_cancellation(*, to: str, user_name: str, valid_until: str) -> bool:
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Cancelación confirmada</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, tu suscripción Rendi Pro fue cancelada.
      </p>
      <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:6px;padding:16px;margin:20px 0;">
        <p style="font-size:14px;color:#166534;margin:0;">
          ✓ Mantenés acceso completo a Pro hasta el <b>{_fmt_date(valid_until)}</b>. Después de esa fecha, tu cuenta vuelve a Free.
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
        f"Hola {user_name}, tu suscripción Rendi Pro fue cancelada.\n\n"
        f"Mantenés Pro hasta el {_fmt_date(valid_until)}. "
        f"Después de esa fecha, tu cuenta vuelve a Free.\n\n"
        f"No te vamos a cobrar más. Si cancelaste por error, contestá este email.\n\n"
        f"— Rendi"
    )
    return _send(to, "Cancelación confirmada · Rendi Pro",
                 _wrap_html(body_html), text)


# ─── Email #5: recordatorio de expiración (3 días antes) ───────────────────

def send_expiration_reminder(*, to: str, user_name: str,
                             days_left: int, expires_at: str) -> bool:
    body_html = f"""
      <h1 style="font-size:22px;font-weight:700;margin:0 0 16px;">Tu plan Pro vence en {days_left} {'día' if days_left == 1 else 'días'}</h1>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 16px;">
        Hola {user_name}, te avisamos que tu suscripción Rendi Pro va a expirar el <b>{_fmt_date(expires_at)}</b>.
      </p>
      <p style="font-size:15px;line-height:1.6;color:#374151;margin:0 0 20px;">
        Después de esa fecha, vas a perder acceso a:
      </p>
      <ul style="font-size:14px;line-height:1.8;color:#374151;padding-left:20px;margin:0 0 20px;">
        <li>60 análisis IA por semana (vas a quedar en 6)</li>
        <li>Follow-ups + AI Hub</li>
        <li>Brokers múltiples (vas a quedar con 1)</li>
        <li>Reportes históricos completos</li>
        <li>Export CSV consolidado</li>
      </ul>
      <p style="font-size:14px;color:#374151;line-height:1.6;">
        Si querés mantener Pro, volvé a suscribirte desde <a href="https://rendi.app/planes" style="color:#21D07A;text-decoration:none;">tu panel</a>.
      </p>
    """
    text = (
        f"Tu plan Rendi Pro vence en {days_left} días\n\n"
        f"Hola {user_name}, tu suscripción expira el {_fmt_date(expires_at)}.\n\n"
        f"Después vas a perder: 60 análisis IA/sem (vs 6), follow-ups, brokers "
        f"ilimitados, reportes históricos, export CSV.\n\n"
        f"Para renovar: andá a rendi.app/planes\n\n"
        f"— Rendi"
    )
    return _send(to, f"⏰ Tu Rendi Pro vence en {days_left} días",
                 _wrap_html(body_html), text)


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
      <div style="background:#f0fdf4;border:2px solid #21D07A;border-radius:8px;padding:20px;margin:20px 0;text-align:center;">
        <p style="font-size:11px;color:#166534;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:0 0 8px;">Tu código</p>
        <p style="font-family:monospace;font-size:38px;font-weight:700;color:#166534;letter-spacing:8px;margin:0;">{code}</p>
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
    return _send(to, subject, _wrap_html(body_html), text)
