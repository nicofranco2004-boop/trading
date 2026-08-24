"""¿La foto reporta NOMINAL o RESIDUAL? Sin usar el ledger.

    ratio = positions_a_la_fecha_D / foto
       ≈ rf(D)  -> la foto trae NOMINAL
       ≈ 1      -> la foto trae RESIDUAL
       ni uno   -> ruido (venta parcial u otra cosa)

Usa SOLO la proyección (anclada en `positions`, verificada al 98,6% contra los
snapshots del cron) y la foto. Cero ledger — el intento anterior sacaba `N` de
una suma ingenua de BUY−SELL, que es justo el instrumento que no es confiable, y
así el razonamiento se mordía la cola.

🔴 MUESTRA: batches de foto REVERTIDOS. Los confirmados contaminaron `positions`
con su propio seed —metieron la diferencia como compra— así que proyectar hacia
atrás incluye lo que queremos medir. Los revertidos no tocaron nada: la
proyección a D da la tenencia REAL de ese día.

    foto = positions_a_D + gap        (el seed llevó una a la otra)
    ratio = positions_a_D / (positions_a_D + gap)

SOLO LECTURA.
"""
import sys, sqlite3
from collections import defaultdict

sys.path.insert(0, '/Users/nicolaspussetto/rendi-worktrees/import-asesor/backend')
from pricing.bond_amortization import is_amortizing_bond, residual_factor  # noqa
from importing.proyeccion import proyectar  # noqa

c = sqlite3.connect('file:/Users/nicolaspussetto/Downloads/trading-2026-08-16.db?immutable=1', uri=True)
c.row_factory = sqlite3.Row
q = lambda s, p=(): c.execute(s, p).fetchall()
HOY = "2026-08-16"


def par_de(uid, broker):
    row = q("SELECT id, parent_broker_id FROM brokers WHERE user_id=? AND name=?",
            (uid, broker))
    if not row:
        return [broker]
    raiz = row[0]["parent_broker_id"] or row[0]["id"]
    return [r["name"] for r in q(
        "SELECT name FROM brokers WHERE user_id=? AND (id=? OR parent_broker_id=?)",
        (uid, raiz, raiz))] or [broker]


seeds = [r for r in q("""SELECT b.id bid, b.user_id u, b.parser_format pf, b.broker br,
                                n.asset_symbol a, n.quantity gap, n.date d
                           FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id
                          WHERE b.parser_format LIKE '%tenencia%' AND b.status='reverted'
                            AND n.operation_type='BUY'
                            AND n.notes LIKE 'Tenencia — apertura%'
                            AND n.asset_symbol IS NOT NULL""")
         if is_amortizing_bond(r["a"])]

print(f"muestra limpia (seeds de bono en batches REVERTIDOS): {len(seeds)}")
print()
print(f"{'parser':22s} {'tick':6s} {'fecha':11s} {'pos_D':>10s} {'gap':>10s} "
      f"{'foto':>10s} {'ratio':>7s} {'rf(D)':>7s} {'lectura':>10s}")

grupos = defaultdict(lambda: defaultdict(int))
for r in sorted(seeds, key=lambda x: (x["pf"], x["d"])):
    pair = par_de(r["u"], r["br"])
    try:
        qty, _ = proyectar(c, r["u"], pair=pair, fecha=r["d"], hoy=HOY)
    except Exception as ex:
        print(f"   {r['pf']:22s} {r['a']:6s} {r['d']:11s}  (proyección falló: {ex})")
        continue
    pos = float(qty.get(r["a"].upper(), 0.0))
    gap = float(r["gap"] or 0)
    foto = pos + gap
    if foto <= 0:
        grupos[r["pf"]]["sin_base"] += 1
        continue
    ratio = pos / foto
    rf = residual_factor(r["a"], r["d"])
    if abs(ratio - rf) <= 0.05:
        lectura, k = "NOMINAL", "nominal"
    elif abs(ratio - 1.0) <= 0.05:
        lectura, k = "residual", "residual"
    else:
        lectura, k = "?", "inexplicado"
    grupos[r["pf"]][k] += 1
    print(f"{r['pf']:22s} {r['a']:6s} {r['d']:11s} {pos:10,.1f} {gap:10,.1f} "
          f"{foto:10,.1f} {ratio:7.3f} {rf:7.3f} {lectura:>10s}")

print()
print("TRES GRUPOS, POR BROKER (si un broker mezcla, aparece en dos):")
for pf in sorted(grupos):
    d = grupos[pf]
    tot = sum(d.values())
    print(f"   {pf:24s} n={tot:3d}  " + "  ".join(f"{k}={v}" for k, v in sorted(d.items())))
