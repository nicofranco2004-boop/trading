"""¿Qué handlers GET escriben en la base?

Importa porque el Plan Asesor cuelga de eso: `get_effective_user` exige el permiso
`read_write` SOLO para métodos != GET (main.py). Si un GET escribe, un asesor con
permiso de solo lectura escribe en la cuenta del cliente.

La escritura casi nunca está en el cuerpo del handler: está dentro de un helper.
Por eso esto es transitivo y no un grep.

Uso: python3 audit/_scripts/5a_gets_que_escriben.py /tmp/rendi-main/backend/main.py
"""
import ast, re, sys
from collections import defaultdict

RUTA = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rendi-main/backend/main.py"
src = open(RUTA, encoding="utf-8").read()
arbol = ast.parse(src)

ESCRIBE = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+)", re.I)

def _sin_docstrings_ni_comentarios(txt, nodo):
    doc = ast.get_docstring(nodo, clean=False)
    if doc:
        txt = txt.replace(doc, "")
    return re.sub(r"#[^\n]*", "", txt)


funcs, llama, escribe_directo = {}, defaultdict(set), set()

for n in ast.walk(arbol):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        funcs[n.name] = n
        # OJO: hay que sacar docstrings y comentarios antes de buscar `.commit()`.
        # `db_abierta` NO escribe, pero su docstring menciona `conn.commit()` y sin
        # esto queda marcada como escritora, contaminando todo handler que la use.
        cuerpo = _sin_docstrings_ni_comentarios(ast.get_source_segment(src, n) or "", n)
        # literales SQL de escritura dentro de la función
        for s in ast.walk(n):
            if isinstance(s, ast.Constant) and isinstance(s.value, str) \
               and s.value != (ast.get_docstring(n, clean=False) or "\0") \
               and ESCRIBE.search(s.value):
                escribe_directo.add(n.name); break
        else:
            if re.search(r"\.commit\(\)", cuerpo):
                escribe_directo.add(n.name)
        for s in ast.walk(n):
            if isinstance(s, ast.Call):
                f = s.func
                nom = getattr(f, "id", None) or getattr(f, "attr", None)
                if nom: llama[n.name].add(nom)

# cierre transitivo: una función escribe si escribe directo o llama a una que escribe
escribe = set(escribe_directo)
for _ in range(12):
    nuevo = {f for f, cs in llama.items() if cs & escribe} - escribe
    if not nuevo: break
    escribe |= nuevo

# handlers GET
hits = []
for n in ast.walk(arbol):
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
    for d in n.decorator_list:
        if not isinstance(d, ast.Call): continue
        f = d.func
        met = getattr(f, "attr", "")
        if getattr(getattr(f, "value", None), "id", "") != "app": continue
        if met not in ("get", "api_route"): continue
        ruta = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else "?"
        if met == "api_route":
            ms = [k.value for k in d.keywords if k.arg == "methods"]
            if not (ms and any(getattr(e, "value", "") == "GET" for e in ms[0].elts)): continue
        if n.name not in escribe: continue
        dep = "get_effective_user" if "get_effective_user" in (ast.get_source_segment(src, n) or "") else \
              ("get_admin_user" if "get_admin_user" in (ast.get_source_segment(src, n) or "") else
               ("get_current_user" if "get_current_user" in (ast.get_source_segment(src, n) or "") else "SIN AUTH"))
        via = "directo" if n.name in escribe_directo else \
              ",".join(sorted((llama[n.name] & escribe))[:3])
        hits.append((n.lineno, ruta, n.name, dep, via))

print(f"handlers GET que escriben (directa o transitivamente): {len(hits)}\n")
print(f"{'linea':>6} | {'ruta':<44} | {'dependencia':<20} | escribe via")
print("-" * 118)
for l, r, fn, dep, via in sorted(hits):
    print(f"{l:>6} | {r:<44} | {dep:<20} | {via}")

exp = [h for h in hits if h[3] == "get_effective_user"]
print(f"\n>>> los que usan get_effective_user (= alcanzables por un asesor read-only): {len(exp)}")
for l, r, fn, dep, via in sorted(exp):
    print(f"    {r}  (main.py:{l})")
