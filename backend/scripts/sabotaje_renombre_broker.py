"""Sabotaje del renombre de brokers: rompe UNA pieza del arreglo y corre sus tests.

Para qué: un test en verde sólo vale si se pone rojo cuando el arreglo falta. Esto
saca una pieza por vez (en memoria, no toca ningún archivo) y dice qué tests caen.
Se corre dos veces por pieza: con el revisor de "nombre viejo guardado" prendido y
apagado (`--sin-escaneo`), para ver que la comparación de plata y tenencias detecta
el daño por su cuenta y no sólo porque el texto quedó viejo.

Uso (desde backend/):
    python3 scripts/sabotaje_renombre_broker.py            # todas las piezas
    python3 scripts/sabotaje_renombre_broker.py sin_pares  # una sola
Cada corrida usa una base temporal propia (nunca la de desarrollo).

Piezas que caen SÓLO con el escaneo prendido (hoy nadie lee ese dato, así que el
comportamiento no cambia): `sin_cuenta_pesos`.
"""
import os
import subprocess
import sys
import tempfile

PIEZAS = ("ninguno", "todo_como_antes", "sin_json", "sin_futuros", "sin_columna_del_registro",
          "sin_no_lo_cobre", "sin_pares", "sin_cuenta_pesos", "sin_anidado", "sin_claves_de_dict",
          "sin_operations", "sin_positions", "sin_archived_positions", "sin_deleted_ops_journal",
          "sin_import_batches", "sin_dividendos_reemplazados", "sin_nombres_anteriores")


def _una(pieza: str, sin_escaneo: bool) -> None:
    import unittest
    os.environ["DB_PATH"] = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    os.environ.setdefault("SEMILLAS_RENOMBRE", "1-12")
    sys.path.insert(0, os.getcwd())
    import main
    import renombre_broker as R
    import tests.test_renombre_broker_recetas as T
    import tests.test_renombre_broker_azar as A

    if sin_escaneo:
        T._apariciones = lambda uid, n: []

    recorrer, en_clave = R._recorrer, R._en_clave_de_broker

    def sin_anidado(valor, nombres):
        return (valor, False) if isinstance(valor, str) else recorrer(valor, nombres)

    def sin_claves_de_dict(valor, nombres):
        return recorrer(valor, nombres) if isinstance(valor, dict) else en_clave(valor, nombres)

    def sin_tabla(*tablas):
        main.NAME_KEYED_TABLES = tuple(t for t in main.NAME_KEYED_TABLES if t not in tablas)

    def sin_columna(tabla):
        R.COLUMNAS_JSON = tuple(x for x in R.COLUMNAS_JSON if x[0] != tabla)

    def sin_clave(*claves):
        R._CLAVES_DE_BROKER_SIN_LA_PALABRA = R._CLAVES_DE_BROKER_SIN_LA_PALABRA - set(claves)

    def sin_json():
        R.renombrar_adentro = lambda *a, **k: {}

    sabotajes = {
        "ninguno": lambda: None,
        "todo_como_antes": lambda: (sin_json(), sin_tabla("futures_positions", "deleted_ops_journal")),
        "sin_json": sin_json,
        "sin_futuros": lambda: sin_tabla("futures_positions"),
        "sin_columna_del_registro": lambda: sin_tabla("deleted_ops_journal"),
        "sin_no_lo_cobre": lambda: sin_tabla("dividendos_salteados"),
        "sin_pares": lambda: sin_clave("pair", "pairs"),
        "sin_cuenta_pesos": lambda: sin_clave("cuenta_pesos"),
        "sin_anidado": lambda: setattr(R, "_recorrer", sin_anidado),
        "sin_claves_de_dict": lambda: setattr(R, "_en_clave_de_broker", sin_claves_de_dict),
        # El anti-duplicados y "Editar y rehacer" sin saber cómo se llamaba antes el broker.
        "sin_nombres_anteriores": lambda: setattr(R, "nombres_anteriores", lambda conn, uid: {}),
    }
    for tabla in ("operations", "positions", "archived_positions", "deleted_ops_journal",
                  "import_batches", "dividendos_reemplazados"):
        sabotajes[f"sin_{tabla}"] = (lambda t: lambda: sin_columna(t))(tabla)
    sabotajes[pieza]()

    suite, cargar = unittest.TestSuite(), unittest.TestLoader()
    for cls in (T.RenombrarYDespuesBorrar, T.CadaColumnaDeBrokerSeRenombra,
                A.RenombrarEnElMedioDeCualquierCosa):
        suite.addTests(cargar.loadTestsFromTestCase(cls))
    res = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    caidos = sorted(t.id().split(".")[-1].replace("test_", "") for t, _ in res.failures + res.errors)
    azar = sum(1 for c in caidos if c.startswith("semilla_"))
    armados = [c for c in caidos if not c.startswith("semilla_")]
    print(f"{pieza:26s} {'sin escaneo' if sin_escaneo else 'con escaneo':11s} "
          f"caen {len(caidos):2d}/{res.testsRun} (al azar {azar:2d}/12): "
          f"{', '.join(armados) or '—'}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--una":
        _una(sys.argv[2], "--sin-escaneo" in sys.argv)
    else:
        for p in (sys.argv[1:] or PIEZAS):
            for extra in ([], ["--sin-escaneo"]):
                subprocess.run([sys.executable, __file__, "--una", p, *extra],
                               stderr=subprocess.DEVNULL)
