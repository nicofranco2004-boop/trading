"""Quién lee la historia importada SIN descontar lo que la persona borró.

`import_normalized_tx` es el LOG de lo importado: guarda también las filas de
imports deshechos o en vista previa y las que la persona BORRÓ (con `excluded_at`,
la lápida). Lo que cuenta para calcular qué tiene o tuvo la persona sale de
`importing.schema.TX_VIVAS` / `tx_vivas()`: import confirmado y sin lápida.

El defecto que esto vigila: el reconstructor de la curva a mercado
(`_holdings_asof`) escribía su propia copia del filtro, con el import confirmado
pero SIN la lápida, y seguía valuando a mercado una compra borrada mientras la
cartera ya no la mostraba (medido en test_compra_borrada_fuera_de_la_curva.py).
Una copia del WHERE en cada consulta es como se pierde el filtro.

Este test recorre el código de producción y lista cada consulta que lee la tabla
DIRECTO (sin el fragmento). Cada una tiene que estar en `LEEN_EL_LOG` con el motivo
por el que mira el log entero. Una consulta nueva que lee directo, o una de la
lista que ya no existe, lo pone en rojo: hay que decidir de qué lado está.

(Reescrito el 2026-10-07: la versión original se perdió con el worktree de la
sesión que hizo el arreglo; la lista sale de recorrer el código con el arreglo
aplicado y de los motivos que esa sesión dejó anotados.)
"""
import ast
import functools
import os
import re
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (archivo, función) → por qué lee el log entero y no sólo las filas vivas.
LEEN_EL_LOG = {
    # El deshacer y el rehacer de un lote trabajan sobre SU lote, filas borradas incluidas.
    ("importing/persister.py", "revert_batch"): "deshacer un lote: recorre sus filas (filtra la lápida donde importa)",
    ("importing/rebuild.py", "_affected_assets"): "qué activos tocó un lote, para recalcularlos al deshacerlo",
    ("main.py", "import_confirm"): "borra filas del lote en vista previa que la persona omitió",
    # La vista previa todavía no está confirmada: filtran la lápida a mano y suman el lote en curso.
    ("ledger_replay.py", "tenencia_en"): "suma el lote en vista previa (b.id = ?); filtra la lápida a mano",
    ("ledger_replay.py", "cash_en"): "suma el lote en vista previa (b.id = ?); filtra la lápida a mano",
    ("importing/proyeccion.py", "proyectar"): "proyecta UN lote (b.id = ?); filtra la lápida a mano",
    ("importing/pipeline.py", "load_session_for_confirm"): "carga las filas de la vista previa que se va a confirmar",
    ("importing/pipeline.py", "load_session_with_seed_revalidate"): "rearma la vista previa (borra y reinserta sus filas)",
    ("importing/pipeline.py", "reconstruct_csv_from_batch"): "\"Editar y rehacer\" UN lote: sólo el NOMBRE de broker de cada fila (por si se renombró), no cantidades ni plata",
    # La huella del re-import: si no incluyera las borradas, un export que se
    # superpone las volvería a importar (resucitarían).
    ("importing/pipeline.py", "confirmed_fingerprint_counts"): "huella del re-import: lo borrado no tiene que resucitar",
    ("importing/traspasos.py", "traspasos_ya_cerrados"): "un traspaso ya cerrado no se vuelve a proponer aunque se borre",
    # Sólo metadatos del activo (nombre, tipo): no cuentan cantidades ni plata.
    ("ledger_replay.py", "valor_en"): "sólo el tipo de activo (asset_type), no cantidades",
    ("importing/maturity.py", "sweep_bond_amortizations"): "sólo nombre/tipo del activo; las cantidades salen de positions",
    ("importing/maturity.py", "sweep_matured_letras"): "sólo nombre del activo; las cantidades salen de positions",
    ("importing/recompute_backfill.py", "_classify_safe"): "sólo nombres de activos por broker",
    ("main.py", "init_db"): "migración: completa asset_type de posiciones desde el import",
    # Frenos de la migración de tipo de cambio: contar una fila borrada sólo la
    # hace frenar de más. Aflojarlos es un análisis aparte, pendiente.
    ("importing/fx_migrate.py", "_metricas"): "freno de la migración FX (contar de más sólo frena de más)",
    ("importing/fx_migrate.py", "fechas_sospechosas"): "freno de la migración FX (contar de más sólo frena de más)",
    ("importing/fx_migrate.py", "migrate_user_fx"): "freno de la migración FX (contar de más sólo frena de más)",
    # Avisos y paneles de diagnóstico: muestran el log tal cual está.
    ("importing/invariantes.py", "check_caja_concilia"): "aviso de diagnóstico del importador",
    ("main.py", "admin_commissions_debug"): "panel de diagnóstico del admin",
    ("main.py", "admin_diagnose_flujo_implausible"): "panel de diagnóstico del admin",
    ("main.py", "admin_diagnose_negative_capital"): "panel de diagnóstico del admin",
    ("main.py", "admin_diagnose_scale"): "panel de diagnóstico del admin",
    ("main.py", "admin_diagnose_sell_fx"): "panel de diagnóstico del admin",
    ("main.py", "admin_fx_aportado_breakdown"): "panel de diagnóstico del admin",
    ("main.py", "admin_fx_migrate_candidates"): "panel de diagnóstico del admin",
    # Las fotos medidas tras una compra/venta borrada: miran justamente lo BORRADO.
    ("main.py", "_evento_de_fila"): "cuándo se confirmó el lote de la fila borrada",
    ("main.py", "_eventos_de_journal_viejo"): "arma los eventos de un borrado viejo desde sus filas con lápida",
    ("main.py", "_recalcular_mediciones"): "si la fila borrada sigue existiendo (o se revirtió su import)",
    # El aportado de las fotos tras borrar un depósito/retiro importado: las fotos
    # todavía muestran la fila que se está borrando y sus gemelos borrados antes.
    ("main.py", "_entrada_de_movimiento_importado"): "los gemelos YA borrados de la fila: cada uno se llevó una capa de las fotos",
    ("main.py", "_neto_de_imports"): "el salto que muestran las fotos incluye la fila que se borra y sus gemelos borrados",
    # Scripts de reparación de una sola vez, sobre lotes puntuales.
    ("scripts/backfill_currency_fix.py", "correct_currency"): "script de reparación sobre lotes puntuales",
    ("scripts/escala_foto_bonos.py", "<módulo>"): "script de diagnóstico sobre lotes deshechos",
    # Herramienta de medición sobre una COPIA de prod (no corre en el servidor):
    # compara lo que la bandeja de dividendos calcularía con lo que el broker pagó.
    ("scripts/backtest_dividendos.py", "<módulo>"): "medición sobre una copia de prod: lee los dividendos y compras importados (filtra los lotes revertidos)",
}

_LEE = re.compile(r"\b(FROM|JOIN)\s+import_normalized_tx\b", re.I)


@functools.lru_cache(maxsize=1)
def lectores_directos() -> frozenset:
    """{(archivo, función)} con una consulta que lee la tabla sin el fragmento.
    Las consultas armadas con `{TX_VIVAS}` no tienen el nombre de la tabla en el
    texto literal, así que no aparecen."""
    out = set()
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__", ".venv", "venv")]
        for a in archivos:
            if not a.endswith(".py"):
                continue
            ruta = os.path.join(raiz, a)
            rel = os.path.relpath(ruta, BACKEND).replace(os.sep, "/")
            try:
                arbol = ast.parse(open(ruta, encoding="utf-8").read())
            except SyntaxError:
                continue
            # Recorrido con la función que encierra a cada nodo (la más interna).
            pila = [(arbol, "<módulo>")]
            while pila:
                nodo, func = pila.pop()
                if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func = nodo.name
                elif (isinstance(nodo, ast.Constant) and isinstance(nodo.value, str)
                      and _LEE.search(nodo.value)):
                    out.add((rel, func))
                pila.extend((h, func) for h in ast.iter_child_nodes(nodo))
    return frozenset(out)


class LaHistoriaQueCuenta(unittest.TestCase):

    def test_el_fragmento_descuenta_lo_borrado_y_lo_no_confirmado(self):
        from importing.schema import TX_VIVAS, tx_vivas
        for frag, n, b in ((TX_VIVAS, "n", "b"), (tx_vivas("t", "ib"), "t", "ib")):
            self.assertIn(f"{n}.excluded_at IS NULL", frag)
            self.assertIn(f"{b}.status = 'confirmed'", frag)

    def test_ningun_lector_nuevo_sin_decidir(self):
        nuevos = lectores_directos() - set(LEEN_EL_LOG)
        self.assertEqual(sorted(nuevos), [], (
            "Estas consultas leen import_normalized_tx directo. Si calculan qué tiene o "
            "tuvo la persona, van con `FROM {TX_VIVAS}`; si miran el log entero a "
            "propósito, se agregan a LEEN_EL_LOG con el motivo."))

    def test_la_lista_no_queda_vieja(self):
        viejos = set(LEEN_EL_LOG) - lectores_directos()
        self.assertEqual(sorted(viejos), [],
                         "Ya no leen la tabla directo: sacarlos de LEEN_EL_LOG.")

    def test_el_reconstructor_lee_las_filas_vivas(self):
        import inspect
        import scripts.backfill_historical_mtm as bf
        self.assertNotIn(("scripts/backfill_historical_mtm.py", "_holdings_asof"),
                         lectores_directos())
        self.assertIn("TX_VIVAS", inspect.getsource(bf._holdings_asof))


if __name__ == "__main__":
    unittest.main()
