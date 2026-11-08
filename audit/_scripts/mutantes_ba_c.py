"""Errores plantados en el cambio de BAC a su CEDEAR de la Bolsa («BA.C»,
06/11/2026): uno en cada borde de cada regla, en una COPIA del backend (nunca en
la carpeta de trabajo: ver la regla «plantá en una copia»). Para cada uno corre
las pruebas que lo tendrían que ver y anota si alguna se puso roja.

Uso (desde la raíz del repo):
  python3 audit/_scripts/mutantes_ba_c.py <carpeta vacía para la copia> > audit/_scripts/mutantes_ba_c.out

Los eligió quien escribió el cambio (ver la regla «los mutantes que elegís vos»):
la lista sale de recorrer el diff renglón por renglón, no de las pruebas.
"""
import os
import shutil
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BAC = "tests/test_bac_con_ba_c.py::BacConBaCTest::"
CARTERA = BAC + "test_la_cartera_valua_bac_con_su_cedear_de_la_bolsa"
NOCHE = BAC + "test_la_noche_guarda_ba_c_y_la_ficha_en_pesos_lo_dibuja"
MINI = BAC + "test_el_mini_grafico_de_bac_es_ba_c"
HORAS = BAC + "test_las_velas_por_hora_de_bac_en_pesos_son_el_estimado_desde_el_precio_real"
OTRO_RATIO = BAC + "test_si_ba_c_dice_otro_ratio_el_estimado_no_se_dibuja"

# (nombre, archivo, lo que está, lo que se planta, pruebas que lo tienen que ver)
MUTANTES = [
    ("precio: el feed por el símbolo y no por el código de la Bolsa", "main.py",
     "row = (_fetch_data912_equities() or {}).get(codigo_en_byma(symbol))",
     "row = (_fetch_data912_equities() or {}).get(base)", [CARTERA]),
    ("precio: BAC vuelve a saltearse la Bolsa", "main.py",
     "    if base in CRYPTO_SYMBOLS:\n        return None\n    row = (_fetch_data912_equities() or {}).get(codigo_en_byma(symbol))",
     "    if base in CRYPTO_SYMBOLS or base in CEDEAR_USD_RATIOS:\n        return None\n"
     "    row = (_fetch_data912_equities() or {}).get(codigo_en_byma(symbol))", [CARTERA]),
    ("precio: lo que vino de la Bolsa pasa por la cuenta del estimado", "main.py",
     "if result.get(_csym) is not None and px_src.get(_csym) == 'yf':",
     "if result.get(_csym) is not None:",
     [BAC + "test_si_el_feed_se_renueva_en_el_medio_ba_c_no_pasa_por_la_cuenta_del_estimado"]),
    ("cierre anterior: lo resuelto por la Bolsa entra al estimado", "main.py",
     "s[:-3] in CEDEAR_USD_RATIOS and s not in _de_data912}", "s[:-3] in CEDEAR_USD_RATIOS}", [CARTERA]),
    ("cierre anterior: el estimado toma el precio de la Bolsa como último", "main.py",
     "                                      and sym not in cedear_usd\n", "",
     [BAC + "test_el_estimado_del_cierre_anterior_no_mezcla_el_precio_de_la_bolsa"]),
    ("cierre anterior: el feed por el símbolo", "main.py",
     "row = (_fetch_data912_equities() or {}).get(codigo_en_byma(sym))",
     "row = (_fetch_data912_equities() or {}).get(base)", [CARTERA]),
    ("¿operó hoy?: se le pregunta al otro papel", "main.py",
     "clave = codigo_en_byma(symbol)       # BAC.BA → 'BA.C', su CEDEAR en pesos",
     "clave = symbol[:-3]",
     ["tests/test_variacion_una_fuente.py::test_bac_se_mide_con_su_cedear_de_la_bolsa_y_si_hoy_no_opero_no_dice_hoy"]),
    ("mini-gráfico: sin la serie de la Bolsa", "main.py",
     "    if solo_en_byma(sym):\n        points = _mini_grafico_de_byma(sym, period)",
     "    if False:\n        points = _mini_grafico_de_byma(sym, period)", [MINI]),
    ("mini-gráfico: la vela semanal con el primer cierre de la semana", "main.py",
     "semanas[(f - timedelta(days=f.weekday())).isoformat()] = c",
     "semanas.setdefault((f - timedelta(days=f.weekday())).isoformat(), c)", [MINI]),
    ("mini-gráfico: sin el corte del período", "main.py",
     "cierres = sorted((d, v[3]) for d, v in historia.items() if d >= desde)",
     "cierres = sorted((d, v[3]) for d, v in historia.items())", [MINI]),
    ("la noche: BAC vuelve a seguirse sólo en dólares", "velas_diarias.py",
     "    if es_cedear:\n        # La acción de afuera",
     "    if es_cedear:\n        if a == 'BAC':\n            return [ticker_de_afuera(a)]\n        # La acción de afuera",
     [NOCHE]),
    ("la noche: BAC.BA se le pide a Yahoo", "velas_diarias.py",
     "    if solo_en_byma(ticker):\n        return _de_la_bolsa(ticker, periodo, TOPE_BYMA_SEG)\n", "", [NOCHE]),
    ("la historia de la Bolsa por el código de la app", "velas_diarias.py",
     "for f in data912.filas(tipo, codigo, restante):", "for f in data912.filas(tipo, papel, restante):",
     [NOCHE]),
    ("la noche: lo de la Bolsa tapa un corte de Yahoo", "velas_diarias.py",
     "de_yahoo = [t for t in tanda if not solo_en_byma(t)]", "de_yahoo = list(tanda)",
     ["tests/test_velas_diarias.py::VelasDiariasTest::test_lo_que_sale_de_la_bolsa_no_tapa_un_corte_de_yahoo"]),
    ("la vela de hoy: a Yahoo", "velas_diarias.py",
     "            if solo_en_byma(ticker):\n                # La Bolsa: su historia diaria",
     "            if False:\n                # La Bolsa: su historia diaria",
     [BAC + "test_la_vela_de_hoy_de_bac_sale_de_la_bolsa"]),
    ("1 y 4 horas: la serie de la Bolsa (Yahoo no tiene sus horas)", "tecnico.py",
     "if byma and afuera and para_horas and solo_en_byma(simbolo_byma(a)):", "if False:", [HORAS]),
    ("1 y 4 horas: no la piden `para_horas`", "velas_horarias.py",
     "s = tecnico.serie(conn, asset, moneda, local, para_horas=True)",
     "s = tecnico.serie(conn, asset, moneda, local)", [HORAS]),
    # Con BA.C a otro ratio, el otro papel (7,29) TAMBIÉN da «no cierra»: lo ve el
    # respaldo con BA.C normal, donde el otro papel apagaría el gráfico en pesos.
    ("la escala del estimado: la Bolsa por el símbolo", "tecnico.py",
     "return (main._data912_en_memoria() or {}).get(codigo_en_byma(codigo))",
     "return (main._data912_en_memoria() or {}).get(codigo)",
     [OTRO_RATIO, BAC + "test_sin_la_serie_de_la_bolsa_el_grafico_en_pesos_es_el_estimado"]),
    ("la escala del estimado: BAC vuelve a saltearse", "tecnico.py",
     "    if not en_pesos or b.get(\"mercado\") != \"arg_cedears\":",
     "    if not en_pesos or codigo == \"BAC\" or b.get(\"mercado\") != \"arg_cedears\":", [OTRO_RATIO]),
    ("liquidez: el otro papel", "liquidez.py",
     "codigo = codigo_en_byma(p) if p else p", "codigo = p",
     [BAC + "test_la_liquidez_de_bac_es_la_de_su_cedear_en_pesos"]),
    ("liquidez: sin la Bolsa, le cree a Yahoo", "liquidez.py",
     "if not hist and not solo_en_byma(f\"{p}.BA\"):", "if not hist:",
     [BAC + "test_la_liquidez_sin_la_historia_de_la_bolsa_no_le_cree_a_yahoo"]),
    ("cambios de ratio: los splits del otro papel se piden", "cambios_ratio.py",
     "    if solo_en_byma(f\"{c}.BA\"):\n        return (afuera[c],) if tiene_afuera else ()\n", "", [NOCHE]),
    ("cambios de ratio: los splits guardados del otro papel cuentan", "cambios_ratio.py",
     "return consulta(t) if t in tickers else []", "return consulta(t)", [NOCHE]),
    ("el traductor: sin BA.C", "snapshots_job.py",
     "    return EN_DATA912.get(base, base)", "    return base", [CARTERA, NOCHE]),
    ("solo_en_byma: nadie", "snapshots_job.py",
     "    return BYMA_EXCEPCIONES.get(base, base) in EN_DATA912", "    return False", [NOCHE, MINI]),
]


def main():
    destino = sys.argv[1]
    copia = os.path.join(destino, "backend")
    if os.path.exists(copia):
        sys.exit(f"{copia} ya existe: dame una carpeta vacía")
    shutil.copytree(os.path.join(RAIZ, "backend"), copia,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.db"))
    vistos = 0
    for nombre, archivo, esta, planta, pruebas in MUTANTES:
        ruta = os.path.join(copia, archivo)
        original = open(ruta, encoding="utf-8").read()
        if original.count(esta) != 1:
            print(f"✗ NO SE PUDO PLANTAR ({original.count(esta)} lugares): {nombre}")
            continue
        open(ruta, "w", encoding="utf-8").write(original.replace(esta, planta))
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", *pruebas, "-q", "-x", "--tb=no",
                                "-p", "no:cacheprovider", "-W", "ignore"],
                               cwd=copia, capture_output=True, text=True, timeout=600)
        finally:
            open(ruta, "w", encoding="utf-8").write(original)
        rojo = r.returncode != 0
        vistos += rojo
        ultima = (r.stdout.strip().splitlines() or ["?"])[-1]
        print(f"{'✓ visto ' if rojo else '✗ NO VISTO'}  {nombre}  ({archivo}; {ultima})")
    print(f"\n{vistos} de {len(MUTANTES)} errores plantados los ve alguna prueba.")


if __name__ == "__main__":
    main()
