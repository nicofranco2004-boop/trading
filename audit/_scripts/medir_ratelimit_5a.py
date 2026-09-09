"""MEDICION 5a — comportamiento real de _check_rate_limit (replica literal de
backend/main.py:391-411) frente a tres escenarios. No toca produccion."""
import time
from collections import defaultdict

_rate_store = defaultdict(list)
_RATE_STORE_MAX_KEYS = 10_000

def _check(ip, max_calls, window_seconds, suffix=""):
    """main.py:395-411 con la IP inyectada en vez de leerla del request."""
    key = f"{ip}|{suffix}" if suffix else ip
    now = time.time()
    ts = _rate_store[key]
    _rate_store[key] = [t for t in ts if now - t < window_seconds]
    if len(_rate_store[key]) >= max_calls:
        return False           # el endpoint lanzaria 429
    _rate_store[key].append(now)
    return True

# --- A) /api/auth/resend-verification: suffix = f"resend:{data.email.lower()}"
#        (main.py:3340) SIN .strip(), mientras el lookup usa .strip().lower()
#        (main.py:3342). Un solo atacante, una sola IP.
print("A) resend-verification — 1 IP, limite 1/60s por email")
IP = "203.0.113.9"
enviados = 0
for pad in ["", " ", "  ", "   ", "\t", " \t", "    ", "\n", " a".replace("a",""), "     "]:
    variante = pad + "victima@gmail.com"          # todas normalizan al MISMO user
    if _check(IP, 1, 60, f"resend:{variante.lower()}"):
        enviados += 1
print(f"   emails enviados a la MISMA casilla en el mismo minuto: {enviados}/10")
print(f"   (el suffix no strippea; el SELECT si -> mismo user, baldes distintos)")

# --- B) el limite 'por email' del login lleva la IP en la clave (main.py:396-397)
_rate_store.clear()
print("\nB) login — 'rate limit por email' contra un ataque distribuido")
ok = 0
for i in range(200):                                # 200 IPs distintas
    if _check(f"198.51.100.{i%256}.{i}", 10, 60, "login_email:victima@gmail.com"):
        ok += 1
print(f"   intentos aceptados contra UNA cuenta en 60s desde 200 IPs: {ok}")
print("   (max_calls=10 se aplica por (IP,email), no por email)")

# --- C) todos los usuarios web comparten la IP del proxy de Vercel
_rate_store.clear()
print("\nC) si _ip_del_cliente devuelve la IP del proxy (mismo balde para todos)")
VERCEL = "76.76.21.21"
for i in range(5):
    _check(VERCEL, 5, 300, "register")              # main.py:3102
print("   tras 5 registros del atacante, un usuario legitimo:",
      "PASA" if _check(VERCEL, 5, 300, "register") else "429 (registro cerrado para todos)")
