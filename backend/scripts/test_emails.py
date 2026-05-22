"""Test rápido: manda 3 emails reales a la dirección que pases como argumento.

Usado para validar que Resend funciona con el dominio rendi.finance y que los
alias no_reply@ / soporte@ se ven bien en el inbox del user.

Uso:
    python3 backend/scripts/test_emails.py nicofranco2004@gmail.com

Requiere RESEND_API_KEY seteada en backend/.env (ya lo tenés).
"""
import sys
import os

# Path setup para que el script encuentre el módulo `billing` sin importar
# desde dónde se ejecute.
_here = os.path.dirname(os.path.abspath(__file__))
_backend = os.path.dirname(_here)
sys.path.insert(0, _backend)

# Carga .env desde backend/.env
from dotenv import load_dotenv
load_dotenv(os.path.join(_backend, ".env"), override=True)

from billing import emails  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 backend/scripts/test_emails.py <email_destino>")
        sys.exit(1)

    to = sys.argv[1]
    print(f"Mandando 3 emails de prueba a: {to}\n")

    # ─── Test 1: noreply — código de verificación (OTP) ─────────────────────
    print("1/3 — Código de verificación (desde no_reply@)... ", end="", flush=True)
    ok = emails.send_verification_code(
        to=to,
        user_name="Nico",
        code="123456",
        expires_minutes=15,
    )
    print("OK ✓" if ok else "FALLÓ ✗ (revisá los logs arriba)")

    # ─── Test 2: support — reset de contraseña ──────────────────────────────
    print("2/3 — Reset de contraseña (desde soporte@)... ", end="", flush=True)
    ok = emails.send_password_reset(
        to=to,
        user_name="Nico",
        reset_url="https://rendi.finance/reset-password?token=test123",
        expires_minutes=30,
    )
    print("OK ✓" if ok else "FALLÓ ✗")

    # ─── Test 3: support — alerta de nuevo login ────────────────────────────
    print("3/3 — Alerta de nuevo login (desde soporte@)... ", end="", flush=True)
    ok = emails.send_new_login_alert(
        to=to,
        user_name="Nico",
        device="Chrome 130 / macOS",
        ip="190.123.45.67",
        when="19/05/2026 22:35 UTC",
    )
    print("OK ✓" if ok else "FALLÓ ✗")

    print("\nListo. Chequeá tu inbox (puede tardar unos segundos) — y la carpeta de Spam por las dudas.")
    print(f"Senders esperados:")
    print(f"  • Test 1: {emails._from_noreply()}")
    print(f"  • Tests 2 y 3: {emails._from_support()}")


if __name__ == "__main__":
    main()
