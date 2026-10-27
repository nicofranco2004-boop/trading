"""¿Quedó MÁS CERTERO después del fix? Compara dos corridas de los mismos instrumentos.

    python3 comparar_antes_despues.py <carpeta_antes> <carpeta_despues>

Cada carpeta tiene lo que dejaron, sobre los MISMOS archivos de entrada:
  escenarios.json   (correr_escenarios.py)  → hay VERDAD: se compara el error contra ella.
  lectores.json     (lectores.py)           → consistencia entre pantallas.
  pesos.txt         (salida de pesos_relativos.py)
  prod.json         (medir_prod.py sobre la copia de producción) → no hay verdad: cobertura,
                    ventana, señales de cada hallazgo, y cuánto se movió cada usuario.

Regla de "más certero": en el arnés, menor |Rendi − verdad| en cada escenario y modo; un
número que aparece donde antes no había cuenta como mejora SÓLO si su error es < 1 pp; un
escenario que EMPEORA (error +0,5 pp o más, o número que desaparece) es una regresión y se
lista. En producción no hay verdad: se informa qué cambió y por qué, no se declara ganador.
"""
import json
import os
import re
import statistics
import sys

A, D = sys.argv[1], sys.argv[2]


def _load(carpeta, nombre):
    p = os.path.join(carpeta, nombre)
    return json.load(open(p)) if os.path.exists(p) else None


def _err(fila):
    if fila.get("rendi") is None or fila.get("verdad_twr") is None:
        return None
    return abs(fila["rendi"] - fila["verdad_twr"])


regresiones, mejoras = [], []

# ── 1. Arnés con verdad ───────────────────────────────────────────────────────
ea, ed = _load(A, "escenarios.json"), _load(D, "escenarios.json")
if ea and ed:
    print("ARNÉS (verdad conocida) — error absoluto en pp contra el TWR verdadero de la misma ventana")
    print(f"{'escenario':42s} {'modo':9s} {'antes':>16s} {'después':>16s}  veredicto")
    for k in sorted(set(ea) | set(ed)):
        for modo in ("certero", "estimado"):
            fa = (ea.get(k) or {}).get("final", {}).get(modo, {})
            fd = (ed.get(k) or {}).get("final", {}).get(modo, {})
            e0, e1 = _err(fa), _err(fd)
            def _s(f, e):
                if f.get("rendi") is None:
                    return "sin número"
                return f"{f['rendi']:.2f} (err {e:.2f})" if e is not None else f"{f['rendi']:.2f}"
            if e0 is None and e1 is None:
                v = "igual (sin número)" if fd.get("rendi") is None else "nuevo, sin verdad"
            elif e0 is None:
                v = "MEJOR: nuevo número" if e1 < 1 else "REGRESIÓN: número nuevo con error"
            elif e1 is None:
                v = "REGRESIÓN: perdió el número"
            elif e1 <= e0 - 0.5:
                v = "MEJOR"
            elif e1 >= e0 + 0.5:
                v = "REGRESIÓN"
            else:
                v = "igual"
            # ventana: más historia medida con el mismo o menor error también es mejora
            va, vd = (fa.get("ventana") or [None])[0], (fd.get("ventana") or [None])[0]
            if v == "igual" and va and vd and vd < va:
                v = f"MEJOR: mide desde {vd} (antes {va})"
            (regresiones if v.startswith("REGRESIÓN") else mejoras if v.startswith("MEJOR") else []).append((k, modo, v))
            print(f"{k:42s} {modo:9s} {_s(fa, e0):>16s} {_s(fd, e1):>16s}  {v}")

# ── 2. Lectores: mismo número en todas las pantallas ──────────────────────────
def _numeros_lectores(lx):
    out = {}
    for caso, r in (lx or {}).items():
        for modo in ("certero", "estimado"):
            x = r.get(modo) or {}
            out[(caso, modo)] = {
                "metricas": (x.get("metricas", {}).get("n") or {}).get("twr"),
                "metas": (x.get("metas", {}).get("n") or {}).get("total_return_pct"),
                "ia_dashboard": (x.get("ia_dashboard", {}).get("n") or {}).get("portfolio.twr_lifetime_pct"),
                "wrapped_2025": ((x.get("wrapped_2025", {}).get("crudo") or {}).get("summary") or {}).get("twr"),
                "publicable_base": (x.get("motor_publicable") or {}).get("base"),
            }
    return out


la, ld = _numeros_lectores(_load(A, "lectores.json")), _numeros_lectores(_load(D, "lectores.json"))
if la or ld:
    print("\nLECTORES — en Certero ninguno puede publicar base 'contable'; Métricas = Metas = IA")
    for k in sorted(set(la) | set(ld)):
        a, d = la.get(k, {}), ld.get(k, {})
        def _ok(x):
            m = x.get("metricas")
            iguales = all(abs((v or 0) / (100 if n == "metas" else 1) - (m or 0)) < 0.0005
                          for n, v in x.items() if n in ("metas", "ia_dashboard") and v is not None and m is not None)
            contable_en_certero = k[1] == "certero" and x.get("publicable_base") == "contable"
            return iguales and not contable_en_certero
        print(f"  {k[0]:28s} {k[1]:9s} antes {'OK ' if a and _ok(a) else 'MAL'} {a.get('wrapped_2025')!s:>8s} | "
              f"después {'OK ' if d and _ok(d) else 'MAL'} {d.get('wrapped_2025')!s:>8s}  (último: Wrapped 2025)")
        if a and d and _ok(a) and not _ok(d):
            regresiones.append((k[0], k[1], "lectores dejaron de coincidir"))

# ── 3. Aporte a mitad de mes (pesos_relativos.py) ─────────────────────────────
for nombre, carpeta in (("antes", A), ("después", D)):
    p = os.path.join(carpeta, "pesos.txt")
    if os.path.exists(p):
        for ln in open(p):
            if re.match(r"^(certero|estimado)\s", ln):
                print(f"PESOS {nombre:8s} {ln.strip()}")

# ── 4. Producción (sin verdad) ───────────────────────────────────────────────
pa, pd = _load(A, "prod.json"), _load(D, "prod.json")
if pa and pd:
    ia, idd = {f["uid"]: f for f in pa}, {f["uid"]: f for f in pd}
    print(f"\nPRODUCCIÓN — {len(ia)} usuarios antes, {len(idd)} después (sin verdad: se informa, no se declara ganador)")
    for modo in ("certero", "estimado"):
        ca = {u for u, f in ia.items() if (f.get(modo) or {}).get("pct") is not None}
        cd = {u for u, f in idd.items() if (f.get(modo) or {}).get("pct") is not None}
        print(f"  [{modo}] con número: {len(ca)} → {len(cd)} · ganan {len(cd - ca)} · PIERDEN {len(ca - cd)}")
        perdidos = sorted(ca - cd)[:20]
        if perdidos:
            print("     pierden (uid → motivo nuevo):", [(u, (idd.get(u, {}).get(modo) or {}).get("motivo")) for u in perdidos])
            regresiones.append(("prod", modo, f"{len(ca - cd)} usuarios pierden el número"))
        movs = []
        for u in ca & cd:
            x0, x1 = ia[u][modo], idd[u][modo]
            movs.append((abs(x1["pct"] - x0["pct"]), u, x0["pct"], x1["pct"], x0.get("desde"), x1.get("desde")))
        if movs:
            movs.sort(reverse=True)
            print(f"     se movieron: mediana {statistics.median(m[0] for m in movs):.2f} pp · peor {movs[0][0]:.2f} pp")
            for m in movs[:10]:
                print(f"       uid {m[1]}: {m[2]} % desde {m[4]} → {m[3]} % desde {m[5]}")
    for s in ("h4_contable_descartada", "h5_guarda_ciega", "h6_mezcla", "h7_certero_publica_contable"):
        print(f"  {s}: {sum(1 for f in pa if f.get(s))} → {sum(1 for f in pd if f.get(s))}")

print("\nRESUMEN")
print(f"  mejoras: {len(mejoras)} · regresiones: {len(regresiones)}")
for r in regresiones:
    print("  ⚠️ REGRESIÓN:", r)
sys.exit(1 if regresiones else 0)
