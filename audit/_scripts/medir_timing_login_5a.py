"""MEDICION 5a — oraculo de timing en /api/auth/login (usuario existe vs no existe).
Replica el camino real de main.py:3193-3198 sin levantar el servidor:
  no existe -> pwd_ctx.dummy_verify()
  existe    -> pwd_ctx.verify(password_mala, hash_real)
"""
import time, statistics
from passlib.context import CryptContext
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
row_hash = pwd_ctx.hash("password-real-del-user")
N = 30
a = []
for _ in range(N):
    t = time.perf_counter(); pwd_ctx.dummy_verify(); a.append((time.perf_counter()-t)*1000)
b = []
for _ in range(N):
    t = time.perf_counter(); pwd_ctx.verify("mala", row_hash); b.append((time.perf_counter()-t)*1000)
print("n=%d" % N)
print("email NO existe (dummy_verify): mediana %.1f ms  min %.1f  max %.1f" % (statistics.median(a), min(a), max(a)))
print("email SI existe (verify real) : mediana %.1f ms  min %.1f  max %.1f" % (statistics.median(b), min(b), max(b)))
print("delta mediana: %+.1f ms" % (statistics.median(b) - statistics.median(a)))
