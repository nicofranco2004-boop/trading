"""¿Cuántos '.BA' trae Yahoo congelados? (06/11/2026)

El gráfico en pesos de un CEDEAR o de una acción argentina se arma con la serie
'.BA' de Yahoo (`velas_diarias`). El DISN.BA de Yahoo está clavado en 10.416 desde
el 24/05/2024 con BYMA en 16.200 (medido el 05/11, `medir_cedear_afuera.py`). Esto
mide lo mismo en TODOS los papeles en pesos de las listas de la app
(`ai.trade_tickers`: CEDEARs y acciones argentinas), con la misma lectura que la
noche (`velas_diarias._bajar` + `_velas_de`), contra la historia de BYMA de data912
(`pricing.data912.filas`, la que ya usa la lista de cambios de ratio).

«Clavado»: el mismo cierre que la rueda anterior y sin volumen, `RACHA` ruedas
seguidas o más. Puede ser de verdad (un papel que no se operó: BYMA marca lo mismo)
o un dato muerto de Yahoo (BYMA marca otro precio): se separan comparando con BYMA.

No escribe en ninguna base. Corre con (red: Yahoo y data912):
  cd backend && YF_TZ_CACHE_LOCATION=<carpeta nueva> python3 ../audit/_scripts/medir_ba_congelados.py \\
      > ../audit/_scripts/medir_ba_congelados.out
"""
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(AQUI)), "backend"))

import logging
logging.disable(logging.WARNING)

from ai import trade_tickers as tt   # noqa: E402
from fechas import hoy_art           # noqa: E402
from pricing import data912          # noqa: E402

RACHA = 5          # ruedas seguidas con el mismo cierre y sin volumen
LEJOS = 0.05       # a más de 5 % del cierre de BYMA ese día


def _byma(asset):
    # La misma regla que la valuación (`snapshots_job.simbolo_byma`) sin importar main.
    excepciones = {'BRK.B': 'BRKB', 'BRK B': 'BRKB', 'BRK-B': 'BRKB'}
    return excepciones.get(asset, asset)


def rachas(velas: dict) -> list:
    """[(desde, hasta, ruedas, cierre)] de las rachas clavadas de `RACHA` o más."""
    out, dias = [], sorted(velas)
    i = 0
    while i < len(dias):
        j = i
        while (j + 1 < len(dias) and velas[dias[j + 1]][3] == velas[dias[i]][3]
               and not velas[dias[j + 1]][4]):
            j += 1
        if j - i + 1 >= RACHA:
            out.append((dias[i], dias[j], j - i + 1, velas[dias[i]][3]))
        i = j + 1
    return out


def main_():
    import velas_diarias
    hoy = hoy_art()
    papeles = sorted({("cedears", _byma(a)) for a in tt.CEDEAR_TICKERS} |
                     {("stocks", _byma(a)) for a in tt.AR_STOCK_TICKERS})
    print(f"Medido el {hoy}: {len(papeles)} papeles en pesos de las listas de la app "
          f"(racha = {RACHA}+ ruedas iguales sin volumen; lejos = más de {int(LEJOS * 100)} % de BYMA)\n")
    filas, sin_yahoo, sin_byma = [], [], []
    for tipo, papel in papeles:
        try:
            yahoo = velas_diarias._velas_de(velas_diarias._bajar(f"{papel}.BA", "5y"), hoy)
        except Exception as ex:
            yahoo = {}
            print(f"  {papel}.BA: Yahoo falló: {ex!r}")
        if not yahoo:
            sin_yahoo.append(papel)
            continue
        try:
            crudas = data912.filas(tipo, papel, timeout=20)
        except Exception as ex:
            crudas = []
            print(f"  {papel}: data912 falló: {ex!r}")
        byma_velas = {}
        for f in crudas:
            v = velas_diarias._limpia(*(f.get(k) for k in ("o", "h", "l", "c", "v")))
            if v and f.get("date"):
                byma_velas[str(f["date"])[:10]] = v
        byma = {d: v[3] for d, v in byma_velas.items()}
        if not byma:
            sin_byma.append(papel)
        rs = rachas(yahoo)
        en_racha = {d for (a, b, _, _) in rs for d in yahoo if a <= d <= b}
        comunes = [d for d in sorted(yahoo) if d in byma]
        lejos = [d for d in comunes if abs(yahoo[d][3] / byma[d] - 1) > LEJOS]
        filas.append({
            "papel": papel, "tipo": tipo, "ruedas": len(yahoo), "comunes": len(comunes),
            "rachas": rs, "dias_en_racha": len(en_racha),
            "lejos": len(lejos), "lejos_en_racha": len([d for d in lejos if d in en_racha]),
            "clavado_hoy": bool(rs) and rs[-1][1] == max(yahoo),
            "ultimo": (max(yahoo), yahoo[max(yahoo)][3], byma.get(max(yahoo))),
            "yahoo": yahoo, "byma_velas": byma_velas,
        })
        time.sleep(0.3)

    con_rachas = [f for f in filas if f["rachas"]]
    muertos = [f for f in con_rachas if f["lejos_en_racha"]]
    print(f"Con serie en Yahoo: {len(filas)}; sin serie en Yahoo: {len(sin_yahoo)} {sin_yahoo}")
    print(f"Sin historia en data912: {len(sin_byma)} {sin_byma}\n")
    print(f"Con alguna racha clavada de {RACHA}+ ruedas: {len(con_rachas)}")
    print(f"  · de esas, con días de la racha a más de {int(LEJOS * 100)} % de BYMA (dato muerto de Yahoo): "
          f"{len(muertos)}")
    print(f"  · clavadas HOY (la última vela está en una racha): {len([f for f in con_rachas if f['clavado_hoy']])}\n")
    print("## Papeles con rachas, de la más larga a la más corta")
    for f in sorted(con_rachas, key=lambda f: -max(r[2] for r in f["rachas"])):
        larga = max(f["rachas"], key=lambda r: r[2])
        u = f["ultimo"]
        print(f"  {f['papel']:7s} ({f['tipo']}): {len(f['rachas'])} racha(s), {f['dias_en_racha']} ruedas en racha; "
              f"la más larga {larga[2]} ruedas ({larga[0]} → {larga[1]}) en {larga[3]:,.2f}; "
              f"lejos de BYMA {f['lejos']} días ({f['lejos_en_racha']} dentro de rachas) de {f['comunes']}"
              f"{' · CLAVADO HOY' if f['clavado_hoy'] else ''} · último {u[0]} Yahoo {u[1]:,.2f} BYMA "
              f"{(f'{u[2]:,.2f}' if u[2] else '—')}")
    print("\n## Sin rachas pero con días lejos de BYMA (más de 10 días)")
    print("  (No es un dato muerto: Yahoo y data912 ajustan distinto los cambios de ratio y los splits.")
    print("   La corrección no los toca: sólo cambia rachas clavadas.)")
    for f in sorted([f for f in filas if not f["rachas"] and f["lejos"] > 10], key=lambda f: -f["lejos"]):
        print(f"  {f['papel']:7s} ({f['tipo']}): {f['lejos']} de {f['comunes']} días a más de "
              f"{int(LEJOS * 100)} % de BYMA")
    con_el_arreglo(con_rachas, hoy)


def _rend(velas: dict, hasta: str):
    """Cuánto cambió el cierre en el año que termina en `hasta`, en %."""
    from datetime import date, timedelta
    piso = (date.fromisoformat(hasta) - timedelta(days=365)).isoformat()
    base = [d for d in sorted(velas) if d <= piso]
    fin = [d for d in sorted(velas) if d <= hasta]
    return (velas[fin[-1]][3] / velas[base[-1]][3] - 1) * 100 if base and fin else None


def con_el_arreglo(con_rachas: list, hoy: str):
    """Lo que hace `velas_diarias._corregir_con_byma` (la noche nueva, con la historia
    entera y sin nada guardado antes) sobre cada papel con rachas, y lo que cambia en
    la lista de cambios de ratio (`cambios_ratio.clasificar`, con la acción de afuera
    de cada CEDEAR). Se corrige sólo la racha que sigue clavada hoy
    (`_rachas_a_corregir`); con el primer diseño, que corregía también las viejas, ver
    medir_ba_congelados_todas_las_rachas.out (AMD pasaba de x20 a x19)."""
    import cambios_ratio
    import velas_diarias
    print("\n## Con el arreglo: la historia entera corregida con BYMA (`_corregir_con_byma`: sólo la racha que sigue clavada)")
    print("   «1 año» = el último año en pesos: Yahoo antes · después · BYMA")
    for f in sorted(con_rachas, key=lambda f: -f["dias_en_racha"]):
        yahoo, byma = f["yahoo"], f["byma_velas"]
        nuevas, n, _ = velas_diarias._corregir_con_byma(yahoo, byma) if byma else (yahoo, 0, False)
        rs = velas_diarias._rachas_clavadas(yahoo)
        corregidas = [r for r in rs if any(nuevas[d] != yahoo[d] for d in yahoo if r[0] <= d <= r[1])]
        hasta = max(yahoo)
        rb = _rend({d: v for d, v in byma.items()}, hasta) if byma else None
        print(f"  {f['papel']:7s}: {len(corregidas)} de {len(rs)} rachas corregidas, {n} días cambiados · "
              f"1 año {_f(_rend(yahoo, hasta))} → {_f(_rend(nuevas, hasta))} (BYMA {_f(rb)})"
              f"{'' if byma else ' · sin historia en data912: queda como está'}")
        if f["tipo"] != "cedears":
            ny = {}
        else:
            afuera = velas_diarias.ticker_de_afuera(f["papel"])
            try:
                ny = {d: v[3] for d, v in velas_diarias._velas_de(velas_diarias._bajar(afuera, "5y"), hoy).items()}
            except Exception:
                ny = {}
            time.sleep(0.3)
        antes = cambios_ratio.clasificar({d: v[3] for d, v in yahoo.items()}, ny, [], [], [])
        despues = cambios_ratio.clasificar({d: v[3] for d, v in nuevas.items()}, ny, [], [], [])

        def corto(filas):
            return [(x["fecha"], x["tipo"], x["estado"], x["factor"] or x["factor_medido"], x["en_la_serie"])
                    for x in filas]
        if corto(antes) != corto(despues):
            print(f"           cambios de ratio antes:   {corto(antes) or 'nada'}")
            print(f"           cambios de ratio después: {corto(despues) or 'nada'}")


def _f(x):
    return "—" if x is None else f"{x:+.1f} %"


if __name__ == "__main__":
    main_()
