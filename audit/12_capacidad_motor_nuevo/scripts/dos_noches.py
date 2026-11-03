"""Dos corridas nocturnas seguidas (velas_diarias.correr: la de verdad, con el orden por persona,
el termómetro y los cambios de ratio) contra Yahoo REAL, sobre una COPIA descartable de prod
(DB_PATH). Uso: DB_PATH=<copia> python3 dos_noches.py salida.json"""
import json, sys, time
import main  # noqa
import velas_diarias
def corto(v):
    if isinstance(v, list): return len(v)
    if isinstance(v, dict): return {k: corto(x) for k, x in v.items()}
    return v
out = {}
for noche in ("primera", "segunda"):
    with main.db_abierta() as conn:
        t0 = time.perf_counter()
        r = velas_diarias.correr(conn)
        out[noche] = {"seg_reloj": round(time.perf_counter() - t0, 1), **corto(r)}
        print(noche, json.dumps(out[noche], ensure_ascii=False), flush=True)
with main.db_abierta() as conn:
    out["con_velas"] = conn.execute("select count(distinct symbol) from velas_diarias").fetchone()[0]
    out["ok"] = conn.execute("select count(*) from velas_estado where ok=1").fetchone()[0]
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(json.dumps(out, ensure_ascii=False))
