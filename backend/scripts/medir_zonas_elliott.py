"""¿Cuántas veces la onda de Elliott en curso terminó dentro de su zona?

Recorre la historia guardada de cada activo DÍA POR DÍA, viendo sólo las velas
hasta ese día (como las habría visto alguien entonces):
  1. el conteo principal de ese día (`elliott.candidatos`, el primero) y la
     zona donde suele terminar su onda en curso (`elliott.zona`). Cada conteo
     cuenta UNA vez: el primer día que aparece (no 40 veces por durar 40 días);
  2. hacia adelante, el primer día en que el detector ve esa onda TERMINADA (hay
     un conteo con los mismos puntos y uno más: ese punto nuevo es donde
     terminó), o el primer día en que el precio pasa el nivel que lo invalida;
  3. si terminó: ¿adentro de la zona, antes de llegar o pasándola? "Dónde
     terminó" es el PRIMER final que vio el detector: lo que habría visto
     quien miraba ese día. (Se probó también "el final más lejano antes de
     invalidarse", y se sacó: para una onda 3 ese punto puede ser el techo de
     la 5 —un conteo 0-1-2 + un punto más vale con cualquier final—, y mezclaba
     ondas: auditoría 23/10.)
  El conteo se da por invalidado si el precio pasa CUALQUIERA de sus dos
  límites (el que invalida y el otro, del otro lado: `elliott._limites`).

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
    import estructura
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
        # Los dos niveles que cortan el conteo, en la vista (sin la regla del
        # final de la onda, que es sobre dónde termina y no sobre el camino).
        corta = [(c["invalida"], c["invalida_lado"])] + ([(c["otro"][0], c["otro"][2])] if c.get("otro") else [])
        hoy = velas[t - 1]["close"] * s
        ancho = hi - lo
        tonta = (hoy, hoy + ancho) if sube else (hoy - ancho, hoy)
        caso = {"fecha": velas[t - 1]["date"], "ahora": c["ahora"], "dir": c["dir"],
                "zona": [lo * s, hi * s], "resultado": "sin_resolver"}
        for t2 in range(t + 1, min(t + HORIZONTE, n) + 1):
            v = velas[t2 - 1]
            # El mismo máximo y mínimo que usa el detector (una vela rota usa
            # apertura y cierre: `estructura._alto/_bajo`).
            alto, bajo = estructura._alto(v), estructura._bajo(v)
            if s < 0:
                alto, bajo = -bajo, -alto
            if any((bajo <= x) if lado == "debajo" else (alto >= x) for x, lado in corta):
                caso.update(resultado="invalidado", fecha_fin=v["date"])
                break
            fin = None
            for c2 in por_dia[t2]:
                p2, s2 = _real(c2)
                if len(p2) == len(pts) + 1 and p2[:len(pts)] == pts:
                    fin = s2 * c2["pts"][-1]["precio"] * s     # en la vista de este caso
                    break
            if fin is not None:
                caso.update(_clasificar(fin, lo, hi, sube, tonta), fin=fin * s, fecha_fin=v["date"])
                break
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
    import estructura
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
    if a.json:
        json.dump({"resumen": resumen, "casos": todos}, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
