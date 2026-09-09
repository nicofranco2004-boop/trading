"""Extrae, para los 43 endpoints del tramo 6 (main.py 33880-38029):
   ruta, método, Depends de auth, si el prefijo está exento del header
   X-Rendi-Client-Id, y si el cuerpo del handler llama _require_advisor
   y/o _advisor_own_link. Solo lectura sobre /tmp/rendi-main."""
import re, sys

SRC = "/tmp/rendi-main/backend/main.py"
EXEMPT = ("/api/auth", "/api/billing", "/api/admin", "/api/advisor",
          "/api/me", "/api/push", "/api/plan/track", "/api/feedback")

src = open(SRC, encoding="utf-8").read().splitlines()

dec = re.compile(r'@app\.(get|post|patch|put|delete|api_route)\(\s*"([^"]+)"')
eps = []
for i, ln in enumerate(src, 1):
    m = dec.search(ln)
    if m and i >= 33880:
        eps.append([i, m.group(1), m.group(2)])

for k, e in enumerate(eps):
    start = e[0]
    end = eps[k + 1][0] - 1 if k + 1 < len(eps) else len(src)
    body = "\n".join(src[start - 1:end])
    dep = "NINGUNA"
    for d in ("get_admin_user", "get_effective_user", "get_current_user"):
        if f"Depends({d})" in body:
            dep = d
            break
    if dep == "NINGUNA" and ("X-Cron-Token" in body or "x-cron-token" in body):
        dep = "token-cron"
    path = e[2]
    exempt = any(path == p or path.startswith(p + "/") for p in EXEMPT)
    e.extend([dep, exempt, "_require_advisor" in body,
              "_advisor_own_link" in body,
              bool(re.search(r"advisor_uid\s*=\s*\?|advisor_uid=\?", body))])

print(f"total endpoints en el tramo: {len(eps)}")
print(f"{'linea':>6} {'metodo':<9} {'ruta':<46} {'auth':<20} {'exento':<7} "
      f"{'req_adv':<8} {'own_link':<9} adv_uid_en_where")
for ln, met, path, dep, ex, ra, ol, aw in eps:
    print(f"{ln:>6} {met:<9} {path:<46} {dep:<20} {str(ex):<7} {str(ra):<8} "
          f"{str(ol):<9} {aw}")

print("\n--- get_effective_user en ruta NO exenta (hereda contexto de cliente) ---")
for ln, met, path, dep, ex, ra, ol, aw in eps:
    if dep == "get_effective_user" and not ex:
        print(f"  {ln} {met.upper()} {path}")
print("\n--- SIN dependencia de auth (públicos) ---")
for ln, met, path, dep, ex, ra, ol, aw in eps:
    if dep in ("NINGUNA", "token-cron"):
        print(f"  {ln} {met.upper()} {path}  ({dep})")
print("\n--- /api/advisor/* SIN _require_advisor ---")
for ln, met, path, dep, ex, ra, ol, aw in eps:
    if path.startswith("/api/advisor") and not ra:
        print(f"  {ln} {met.upper()} {path}")
