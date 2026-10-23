"""¿Cuántas veces la onda de Elliott en curso terminó dentro de su zona?

Recorre la historia guardada de cada activo DÍA POR DÍA, viendo sólo las velas
hasta ese día (como las habría visto alguien entonces):
  1. el conteo principal de ese día (`elliott.candidatos`, el primero) y la
     zona donde suele terminar su onda en curso (`elliott.zona`). Cada conteo
     cuenta UNA vez: el primer día que aparece (no 40 veces por durar 40 días);
  2. hacia adelante, el primer día en que el detector ve esa onda TERMINADA (hay
     un conteo con los mismos puntos y uno más: ese punto nuevo es donde
     terminó), o el primer día en que el precio pasa el nivel que lo invalida;
  3. si terminó: ¿adentro de la zona, antes de llegar o pasándola? Con dos
     definiciones de "dónde terminó": el PRIMER final que vio el detector (lo
     que habría visto quien miraba) y el MÁS LEJANO que llegó a ver antes de
     invalidarse o de que pase un año (una onda 3 tiene descansos adentro y el
     primero puede ser uno de ellos). La tabla imprime las dos.

Y lo compara con una zona "tonta" del mismo ancho, puesta justo delante del
precio de ese día en la dirección de la onda: si la de Fibonacci no acierta
más que esa, no agrega nada.

Corre SÓLO contra una copia de la base (con las velas ya bajadas):
    python3 scripts/medir_zonas_elliott.py --db /ruta/a/copia.db AAPL MSFT GGAL.BA BTC-USD ...
Los tickers son los de `velas_diarias` (con '.BA' para los de BYMA en pesos).
Imprime la tabla por onda y, con --json, deja el detalle de cada caso.
"""
import argparse
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(AQUI)

# Ventana para que la onda termine: un año de ruedas. Lo que no se resolvió
# en ese plazo (o porque la historia se acaba) queda "sin resolver" y no cuenta.
HORIZONTE = 250
# A favor = la onda sube en la vista (dada vuelta si es una bajada).
SUBE = {"onda_3": True, "onda_5": True, "onda_B": True, "onda_4": False, "onda_C": False}


def _real(c):
    s = -1 if c["espejo"] else 1
    vuelta = {"pico": "pozo", "pozo": "pico"}
    return tuple((p["i"], vuelta[p["tipo"]] if c["espejo"] else p["tipo"]) for p in c["pts"]), s


def _clasificar(fin, lo, hi, sube, tonta):
    if lo <= fin <= hi:
        r = "dentro"
    elif (fin < lo) == sube:
        r = "no_llego"
    else:
        r = "se_paso"
    return {"resultado": r, "tonta": bool(tonta[0] <= fin <= tonta[1])}


def medir(velas, elliott, desde=60):
    n = len(velas)
    por_dia = {}
    for t in range(desde, n + 1):
        por_dia[t] = elliott.candidatos(velas[:t])
    vistos, casos = set(), []
    for t in range(desde, n + 1):
        lista = por_dia[t]
        if not lista:
            continue
        c = lista[0]
        z = elliott.zona(c)
        if z is None:
            continue
        pts, s = _real(c)
        clave = (pts, c["ahora"])
        if clave in vistos:
            continue
        vistos.add(clave)
        lo, hi = sorted(z)                     # en la vista
        sube = SUBE[c["ahora"]]
        inv = c["invalida"]                    # en la vista
        # El nivel que invalida, en la vista: "debajo" en la vista = más bajo.
        inv_debajo = c["invalida_lado"] == "debajo"
        hoy = velas[t - 1]["close"] * s
        ancho = hi - lo
        tonta = (hoy, hoy + ancho) if sube else (hoy - ancho, hoy)
        caso = {"fecha": velas[t - 1]["date"], "ahora": c["ahora"], "dir": c["dir"],
                "zona": [lo * s, hi * s], "resultado": "sin_resolver"}
        for t2 in range(t + 1, min(t + HORIZONTE, n) + 1):
            v = velas[t2 - 1]
            alto, bajo = (v["high"] if v.get("high") is not None else v["close"]), \
                         (v["low"] if v.get("low") is not None else v["close"])
            if s < 0:
                alto, bajo = -bajo, -alto
            if (bajo <= inv) if inv_debajo else (alto >= inv):
                if "fin" not in caso:
                    caso.update(resultado="invalidado", fecha_fin=v["date"])
                break
            for c2 in por_dia[t2]:
                p2, s2 = _real(c2)
                if len(p2) == len(pts) + 1 and p2[:len(pts)] == pts:
                    fin = s2 * c2["pts"][-1]["precio"] * s     # en la vista de este caso
                    if "fin" not in caso:
                        # El PRIMER final que vio el detector: lo que habría
                        # visto quien miraba ese día.
                        caso.update(_clasificar(fin, lo, hi, sube, tonta), fin=fin * s, fecha_fin=v["date"])
                    # El final MÁS LEJANO (en la dirección de la onda) que llegó a
                    # ver antes de invalidarse o de que pase el año: una onda 3
                    # tiene descansos adentro, y el primer final puede ser uno.
                    previo = caso.get("_lejano")
                    if previo is None or (fin > previo if sube else fin < previo):
                        caso["_lejano"] = fin
                    break
        if "_lejano" in caso:
            lejos = _clasificar(caso.pop("_lejano"), lo, hi, sube, tonta)
            caso.update(lejano=lejos["resultado"], tonta_lejano=lejos["tonta"])
        casos.append(caso)
    return casos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--json")
    ap.add_argument("tickers", nargs="+")
    a = ap.parse_args()
    db = os.path.abspath(a.db)
    if os.path.realpath(db) == os.path.realpath(os.path.join(BACKEND, "trading.db")):
        sys.exit("Esto se corre contra una COPIA de la base, nunca contra backend/trading.db.")
    os.environ["DB_PATH"] = db
    sys.path.insert(0, BACKEND)
    # Por la puerta de siempre (`get_db`, que decide el motor), no con sqlite3
    # directo (tests/test_escritores_solo_sqlite.py). Sólo lee.
    import main
    import elliott
    import velas_diarias
    if os.path.realpath(main.DB_PATH) != os.path.realpath(db):
        sys.exit(f"La base abierta no es la pedida: {main.DB_PATH}")
    todos = {}
    with main.db_abierta() as conn:
        for tk in a.tickers:
            velas = [v for v in velas_diarias.serie(conn, tk) if v.get("close")]
            todos[tk] = medir(velas, elliott)
            print(f"{tk}: {len(velas)} ruedas, {len(todos[tk])} conteos con zona", flush=True)
    resumen = {}
    for casos in todos.values():
        for c in casos:
            d = resumen.setdefault(c["ahora"], {"dentro": 0, "no_llego": 0, "se_paso": 0,
                                                "invalidado": 0, "sin_resolver": 0, "tonta": 0})
            d[c["resultado"]] += 1
            d["tonta"] += 1 if c.get("tonta") else 0
    print("\nonda | terminó dentro | no llegó | se pasó | se invalidó | sin resolver | zona tonta dentro")
    tot = {}
    for k in ("onda_3", "onda_4", "onda_5", "onda_B", "onda_C"):
        d = resumen.get(k)
        if not d:
            continue
        for x, y in d.items():
            tot[x] = tot.get(x, 0) + y
        term = d["dentro"] + d["no_llego"] + d["se_paso"]
        print(f"{k} | {d['dentro']}/{term} | {d['no_llego']} | {d['se_paso']} | {d['invalidado']} | "
              f"{d['sin_resolver']} | {d['tonta']}/{term}")
    term = tot["dentro"] + tot["no_llego"] + tot["se_paso"]
    print(f"total | {tot['dentro']}/{term} | {tot['no_llego']} | {tot['se_paso']} | {tot['invalidado']} | "
          f"{tot['sin_resolver']} | {tot['tonta']}/{term}")
    print("\nCon el final MÁS LEJANO: onda | dentro/terminadas | zona tonta dentro")
    for k in ("onda_3", "onda_4", "onda_5", "onda_B", "onda_C"):
        cs = [c for casos in todos.values() for c in casos if c["ahora"] == k and "lejano" in c]
        if cs:
            print(f"{k} | {sum(c['lejano'] == 'dentro' for c in cs)}/{len(cs)} | {sum(c['tonta_lejano'] for c in cs)}/{len(cs)}")
    if a.json:
        json.dump({"resumen": resumen, "casos": todos}, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
