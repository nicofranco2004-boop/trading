"""¿El retroceso está bien? Contra `snapshots.holdings_json` del cron.

Es la referencia INDEPENDIENTE: no sale del replay del ledger ni de la foto del
broker — la estampó el cron nocturno con la composición de ese día. Si la
proyección hacia atrás está bien, coincide. Si no, el problema es nuestro, y hay
que saberlo ANTES de mostrarle nada a un asesor.

⚠️ `holdings_json` guarda {asset, value_usd}, o sea VALORES y no cantidades. Así
que esto verifica la COMPOSICIÓN (qué activos había ese día), no los nominales.
Alcanza para lo que importa: los dos veredictos peligrosos del reconcile son
"sobra un activo" (not_in_snapshot → lo cierra con una venta sintética) y "falta
un activo" (to_seed → lo crea). Los dos son de composición.

SOLO LECTURA (immutable=1).
"""
import sys, json, sqlite3
from collections import Counter, defaultdict

sys.path.insert(0, '/Users/nicolaspussetto/rendi-worktrees/import-asesor/backend')
from importing.proyeccion import proyectar   # noqa

DB = '/Users/nicolaspussetto/Downloads/trading-2026-08-16.db'
c = sqlite3.connect(f'file:{DB}?immutable=1', uri=True)
c.row_factory = sqlite3.Row
q = lambda s, p=(): c.execute(s, p).fetchall()
HOY = "2026-08-16"


def pares(uid):
    """{broker: [par]} — padre + sibling '· USD', como hace persister.broker_pair."""
    filas = q("SELECT id, name, parent_broker_id FROM brokers WHERE user_id=?", (uid,))
    porid = {r["id"]: r for r in filas}
    grupos = defaultdict(list)
    for r in filas:
        raiz = r["parent_broker_id"] or r["id"]
        grupos[raiz].append(r["name"])
    return list(grupos.values())


# Snapshots del cron con composición, de una fecha ANTERIOR a la última: si D es
# hoy el retroceso es trivial y no prueba nada.
casos = q("""SELECT user_id, date, holdings_json FROM snapshots
              WHERE source='cron' AND holdings_json IS NOT NULL AND holdings_json <> ''
                AND date < ?
              ORDER BY user_id, date""", (HOY,))
print(f"casos disponibles (cron, con holdings, fecha < {HOY}): {len(casos)}")

exacto = subconj = falla = vacio = 0
motivos = Counter()
peores = []
for r in casos:
    uid, D = r["user_id"], r["date"]
    try:
        esperado = {(_h.get("asset") or "").strip().upper()
                    for _h in json.loads(r["holdings_json"]) if _h.get("asset")}
    except (ValueError, TypeError):
        continue
    if not esperado:
        continue
    obtenido, no_rec = set(), []
    for par in pares(uid):
        qty, nr = proyectar(c, uid, pair=par, fecha=D, hoy=HOY)
        obtenido |= set(qty)
        no_rec += nr
    for x in no_rec:
        motivos[x["motivo"]] += 1
    # Lo declarado no_reconciliable no cuenta como acierto ni como error: el
    # sistema dijo "de esto no sé", que es una respuesta válida.
    dudoso = {x["ticker"] for x in no_rec}
    esp = esperado - dudoso
    obt = obtenido - dudoso
    if not esp and not obt:
        vacio += 1
    elif esp == obt:
        exacto += 1
    else:
        falta, sobra = esp - obt, obt - esp
        falla += 1
        if len(peores) < 8:
            peores.append((uid, D, sorted(falta)[:6], sorted(sobra)[:6]))

tot = exacto + falla + vacio
print(f"\nRESULTADO sobre {tot} (usuario, fecha):")
print(f"   composición EXACTA        : {exacto:5d}  ({exacto/tot*100:5.1f}%)")
print(f"   no coincide               : {falla:5d}  ({falla/tot*100:5.1f}%)")
print(f"   ambos vacíos (trivial)    : {vacio:5d}")
print(f"\n   declarados no_reconciliable: {sum(motivos.values())}  {dict(motivos)}")
if peores:
    print("\n   ejemplos que no coinciden (falta = el cron lo tenía y la proyección no):")
    for uid, D, falta, sobra in peores:
        print(f"      uid {uid:5d} {D}  falta={falta}  sobra={sobra}")
