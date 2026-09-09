"""MEDICION 5a — comportamiento real de pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
Replica exacta de backend/main.py:136 con las versiones de backend/requirements.txt.
NO toca produccion: solo hashea strings en memoria.
"""
import time, passlib, bcrypt
from passlib.context import CryptContext

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
print("passlib", passlib.__version__, "| bcrypt", bcrypt.__version__)

h = pwd_ctx.hash("contrasena-de-prueba-1234")
print("hash prefix/coste :", h[:7], "| len:", len(h))
print("rounds efectivos  :", pwd_ctx.handler().using().rounds if hasattr(pwd_ctx.handler(), 'using') else '?')

# 1) truncacion a 72 bytes: silenciosa o error?
base = "A" * 72
p_ok   = base                      # 72 bytes
p_long = base + "ZZZZZZZZZZZZZZZZ" # 88 bytes, difiere SOLO despues del byte 72
try:
    hh = pwd_ctx.hash(p_long)
    print("hash de 88 bytes  : OK (no lanza)")
except Exception as e:
    print("hash de 88 bytes  : LANZA ->", type(e).__name__, e)

hh = pwd_ctx.hash(p_long)
print("verify(72 bytes  , hash de 88 bytes) ->", pwd_ctx.verify(p_ok, hh))
print("verify(88 bytes  , hash de 88 bytes) ->", pwd_ctx.verify(p_long, hh))
print("verify(otro >72  , hash de 88 bytes) ->", pwd_ctx.verify(base + "QQQQQQQQQQ", hh))

# 2) multibyte: 128 CARACTERES (max_length del modelo) pueden ser >72 BYTES
p_utf = "ñ" * 40            # 80 bytes en utf-8, 40 chars -> pasa max_length=128
print("40 x 'n-tilde' = ", len(p_utf), "chars /", len(p_utf.encode()), "bytes")

# 3) coste real (tiempo por hash) — proxy del work factor
t0 = time.time(); [pwd_ctx.hash("x"*20) for _ in range(5)]; t1 = time.time()
print("tiempo medio hash : %.0f ms" % ((t1-t0)/5*1000))

# 4) dummy_verify: cuanto tarda vs un verify real (oraculo de timing en login)
row_hash = pwd_ctx.hash("password-real-del-user")
t0 = time.time(); [pwd_ctx.dummy_verify() for _ in range(5)]; t1 = time.time()
dv = (t1-t0)/5*1000
t0 = time.time(); [pwd_ctx.verify("mala", row_hash) for _ in range(5)]; t1 = time.time()
vr = (t1-t0)/5*1000
print("dummy_verify      : %.0f ms | verify real: %.0f ms | delta: %.0f ms" % (dv, vr, vr-dv))
