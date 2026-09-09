#!/usr/bin/env python3
"""Auditoría 5a-autorizacion tramo 3 — escáner estático sobre la copia congelada.

Uso:  python3 audit/_scripts/5a_autorizacion_3_scan.py [/tmp/rendi-main/backend/main.py]

Imprime, para cada endpoint del tramo (líneas 15040..19696):
  línea | método | ruta | dependencia de auth | mutaciones dentro del cuerpo real
y después dos chequeos globales:
  (a) rutas /api/admin que NO dependen de get_admin_user
  (b) rutas sin ninguna dependencia de auth
NO toca la base ni hace peticiones a nada. Solo lee el archivo.
"""
import re
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rendi-main/backend/main.py"
LO, HI = 15040, 19696
L = open(PATH).read().split("\n")


def endpoints():
    out = []
    for i, line in enumerate(L, start=1):
        m = re.match(r'@app\.(get|post|put|delete|patch)\("([^"]+)"', line)
        if not m:
            continue
        j = i
        while j <= len(L) and not re.match(r"(async )?def ", L[j - 1]):
            j += 1
        sig, k = [], j
        while k <= len(L) and k - j <= 12:
            sig.append(L[k - 1])
            if L[k - 1].rstrip().endswith(":"):
                break
            k += 1
        out.append((i, m.group(1).upper(), m.group(2), "\n".join(sig), j))
    return out


def body_end(defline):
    k = defline + 1
    while k <= len(L):
        s = L[k - 1]
        if s and not s[0].isspace() and not s.startswith((")", "]")):
            return k
        k += 1
    return k


def dep(sig):
    for d in ("get_admin_user", "get_effective_user", "get_current_user"):
        if d in sig:
            return d
    return "NINGUNA"


eps = endpoints()
print(f"=== TRAMO {LO}-{HI} ===")
n = 0
for ln, meth, route, sig, defln in eps:
    if not (LO <= ln <= HI):
        continue
    n += 1
    body = "\n".join(L[ln - 1:body_end(defln) - 1])
    muts = [f"{kw.strip()}x{body.count(kw)}"
            for kw in ("INSERT ", "UPDATE ", "DELETE FROM", "commit()")
            if body.count(kw)]
    print(f"{ln:>6} {meth:6} {route:44} {dep(sig):18} {' '.join(muts)}")
print(f"total endpoints en el tramo: {n}")

print("\n=== /api/admin SIN get_admin_user (global) ===")
bad = [(ln, meth, route) for ln, meth, route, sig, _ in eps
       if route.startswith("/api/admin") and "get_admin_user" not in sig]
print(bad or "ninguno")
print("rutas /api/admin totales:",
      sum(1 for e in eps if e[2].startswith("/api/admin")))

print("\n=== rutas SIN ninguna dependencia de auth (global) ===")
for ln, meth, route, sig, _ in eps:
    if dep(sig) == "NINGUNA":
        print(f"{ln:>6} {meth:6} {route}")
