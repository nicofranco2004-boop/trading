"""Confirmar con «Estado inicial» lee cada fila igual que la vista previa.

Con «Estado inicial» (`seed_state`), la confirmación no usa lo que guardó la
vista previa: vuelve a leer las filas crudas del lote para validarlas de nuevo
con las posiciones de antes sumadas (`load_session_with_seed_revalidate`). La
vista previa, después de normalizar, les hacía dos cosas más que ese camino no
repetía:

  - Un fondo común escrito por NOMBRE con la plantilla («Ualintec Ahorro Pesos -
    Clase A») se traduce al símbolo del catálogo (FCI:UALINTEC-AHORRO-PESOS-A),
    que es el que tiene el valor de la cuotaparte. La vista previa mostraba el
    símbolo y sugería sembrar ESE símbolo; la confirmación guardaba la venta con
    el nombre crudo. Quedaban dos activos: el fondo sembrado entero, sin la
    venta, y una venta suelta de «otro» activo con ganancia cero.
  - El «Saldo anterior» de Bull Market que ya estaba contado por una subida
    anterior volvía a entrar (encontrado el 06/11/2026 en la revisión de otra
    rama, `claude/subida-juntos-orden`).

Ahora los dos caminos pasan por `pipeline.interpretar_filas`. Las pruebas suben
por /api/imports/preview y confirman por /api/imports/confirm, como la pantalla.

Corre con: cd backend && python3 -m pytest tests/test_estado_inicial_lee_igual.py
"""
import io
import os
import tempfile
import uuid

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ.setdefault("DB_PATH", _TMP.name)

from fastapi.testclient import TestClient    # noqa: E402

import main                                  # noqa: E402
from pricing import fci                      # noqa: E402

FONDO = "FCI:UALINTEC-AHORRO-PESOS-A"
HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _catalogo():
    # El catálogo es una tabla de toda la base (sin user_id): sembrarlo dos veces
    # es inofensivo (`seed_catalog` es idempotente).
    conn = main.get_db()
    try:
        fci.ensure_tables(conn)
        fci.seed_catalog(conn, funds=[
            {"fondo": "Ualintec Ahorro Pesos - Clase A", "fecha": "2026-09-04",
             "vcp": 8506.463, "_cat": "mercadoDinero"}])
        conn.commit()
    finally:
        conn.close()


class _Cuenta:
    def __init__(self, broker=None):
        _catalogo()
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"lee-igual-{uuid.uuid4().hex[:10]}@rendi.test",),
        ).lastrowid
        if broker:
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'ARS')",
                         (self.uid, broker))
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def vista_previa(self, datos, formato, broker=None, nombre="x.csv"):
        form = {"format": formato}
        if broker:
            form["broker"] = broker
        r = self.client.post(
            "/api/imports/preview", headers=self.h,
            files=[("files", (nombre, io.BytesIO(datos), "text/csv"))], data=form)
        assert r.status_code == 200, r.text
        return r.json()

    def confirmar(self, prev, seed_state=None):
        cuerpo = {"session_id": prev["session_id"]}
        if seed_state is not None:
            cuerpo["seed_state"] = seed_state
        r = self.client.post("/api/imports/confirm", headers=self.h, json=cuerpo)
        assert r.status_code == 200, r.text

    def _filas(self, sql, *args):
        conn = main.get_db()
        try:
            return [dict(r) for r in conn.execute(sql, (self.uid,) + args)]
        finally:
            conn.close()

    def tenencias(self):
        return {r["asset"]: r["quantity"] for r in self._filas(
            "SELECT asset, quantity FROM positions WHERE user_id=? AND COALESCE(is_cash, 0)=0")}

    def efectivo(self):
        return round(sum(r["invested"] or 0 for r in self._filas(
            "SELECT invested FROM positions WHERE user_id=? AND is_cash=1 AND asset='ARS'")), 2)

    def ventas(self):
        return self._filas("SELECT asset, quantity, entry_price, exit_price FROM operations "
                           "WHERE user_id=?")

    def filas_guardadas(self, batch_id):
        """Lo que quedó de cada fila DEL ARCHIVO (row_index ≥ 0) en el lote."""
        return {r["row_index"]: r for r in self._filas(
            "SELECT r.row_index, n.operation_type, n.asset_symbol, n.asset_type, n.quantity, "
            "       n.notes FROM import_normalized_tx n "
            "JOIN import_raw_rows r ON r.id = n.raw_row_id "
            "JOIN import_batches b ON b.id = n.batch_id "
            "WHERE b.user_id=? AND n.batch_id=? AND r.row_index >= 0", batch_id)}


def _semilla(prev, precio):
    """El «Estado inicial» tal como lo arma la pantalla: los activos que sugirió
    la vista previa, con el símbolo que sugirió (no se puede escribir otro)."""
    sug = prev["seed_suggestions"]
    return {"seed_date": sug["seed_date"], "brokers": [
        {"broker": b["broker"], "cash": {}, "assets": [
            {"symbol": a["symbol"], "qty": a["min_qty"] * 3, "cost_basis_unit": precio}
            for a in b["assets"]]}
        for b in sug["brokers"]]}


# ── Fondo común escrito por nombre ──────────────────────────────────────────

def test_fondo_por_nombre_con_estado_inicial_queda_un_solo_fondo_con_su_venta():
    """Rescate de 100 cuotapartes de un fondo que el archivo no muestra cómo se
    compró. La vista previa sugiere sembrar FCI:UALINTEC-AHORRO-PESOS-A; con
    300 sembradas a $7.000, quedan 200 y el rescate gana $1.000 por cuotaparte.
    Antes: el fondo quedaba en 300 (la venta no lo tocaba) y la venta iba a otro
    activo, «UALINTEC-AHORRO-PESOS---CLASE-A», comprado y vendido a $8.000."""
    cuenta = _Cuenta("Uala")
    prev = cuenta.vista_previa(
        (HDR + "2026-03-10,VENTA,Uala,Ualintec Ahorro Pesos - Clase A,100,8000,,,,,ARS,rescate\n")
        .encode(), "rendi_generic", broker="Uala")
    assert [a["symbol"] for b in prev["seed_suggestions"]["brokers"] for a in b["assets"]] == [FONDO]

    cuenta.confirmar(prev, _semilla(prev, 7000))

    assert cuenta.tenencias() == {FONDO: 200}
    assert [(v["asset"], v["quantity"], v["entry_price"], v["exit_price"])
            for v in cuenta.ventas()] == [(FONDO, 100, 7000, 8000)]
    assert cuenta.efectivo() == 800000.0


def test_con_o_sin_estado_inicial_cada_fila_se_guarda_como_la_mostro_la_vista_previa():
    """La regla general, no el caso: lo que la confirmación con «Estado inicial»
    guarda de cada fila del archivo es lo que la vista previa le mostró a la
    persona (activo, tipo de activo, operación, cantidad, nota)."""
    archivo = (HDR
               + "2026-03-01,DEPOSITO,Uala,,,,900000,,,,ARS,\n"
               + "2026-03-02,COMPRA,Uala,Ualintec Ahorro Pesos - Clase A,50,7500,,,,,ARS,\n"
               + "2026-03-10,VENTA,Uala,Ualintec Ahorro Pesos - Clase A,100,8000,,,,,ARS,\n"
               + "2026-03-11,COMPRA,Uala,GGAL,10,5000,,,,,ARS,\n").encode()
    cuenta = _Cuenta("Uala")
    prev = cuenta.vista_previa(archivo, "rendi_generic", broker="Uala")
    mostradas = {r["row_index"]: r for r in prev["rows_preview"]}
    assert {r["asset_symbol"] for r in mostradas.values()} == {None, FONDO, "GGAL"}
    # Los dos caminos usan la misma función: la comparación de abajo no ve un
    # error ADENTRO de ella. Esto sí (el fondo traducido pasa a ser un fondo).
    assert {r["asset_type"] for r in mostradas.values() if r["asset_symbol"] == FONDO} == {"FUND"}

    cuenta.confirmar(prev, _semilla(prev, 7000))

    guardadas = cuenta.filas_guardadas(prev["session_id"])
    assert sorted(guardadas) == sorted(mostradas)
    for i, vista in mostradas.items():
        for campo in ("operation_type", "asset_symbol", "asset_type", "quantity", "notes"):
            assert guardadas[i][campo] == vista[campo], (i, campo, guardadas[i][campo], vista[campo])


def test_fondo_por_nombre_sin_estado_inicial_sigue_igual():
    """El camino de siempre (sin «Estado inicial») ya traducía el nombre: no
    cambia."""
    cuenta = _Cuenta("Uala")
    prev = cuenta.vista_previa(
        (HDR + "2026-03-01,DEPOSITO,Uala,,,,900000,,,,ARS,\n"
         + "2026-03-02,COMPRA,Uala,Ualintec Ahorro Pesos - Clase A,100,7500,,,,,ARS,\n").encode(),
        "rendi_generic", broker="Uala")
    cuenta.confirmar(prev)
    assert cuenta.tenencias() == {FONDO: 100}


# ── «Saldo anterior» de Bull Market ya contado ──────────────────────────────
# El mismo caso que `test_confirmar_con_estado_inicial_no_trae_de_vuelta_el_saldo`
# de la rama `claude/subida-juntos-orden`: acá prueba que el paso vive en el
# lugar compartido, no en una copia.

BM_HDR = "Liquida;Cpbt.;Numero;Importe;Saldo;Especie;Referencia/Cantidad/Precio\n"
BM_PIE = (";;;;;COBA;RECIBO DE COBRO\n"
          ";;;;;CPRA;COMPRA\n")
# 2022: abre con $1.000, entra un cobro de $100.000 y compra GGAL por $40.000.
# Cierra con $61.000 (en este layout el signo va invertido: negativo = plata).
BM_2022 = (BM_HDR
           + "31/12/21;Ant.;;-1000;-1000;;S.ANTERIOR\n"
           + "19/01/22;COBA;53066;-100000;-101000;;CREDITO CTA. CTE.\n"
           + "24/01/22;CPRA;251989;40000;-61000;GGAL;100                       400.0000\n"
           + BM_PIE + ";Total;;-61000;;;\n").encode()
# 2023: abre con el cierre de 2022 ($61.000) y entra otro cobro de $20.000.
BM_2023 = (BM_HDR
           + "31/12/22;Ant.;;-61000;-61000;;S.ANTERIOR\n"
           + "10/02/23;COBA;60001;-20000;-81000;;CREDITO CTA. CTE.\n"
           + BM_PIE + ";Total;;-81000;;;\n").encode()


def test_bull_market_con_estado_inicial_no_trae_de_vuelta_el_saldo_ya_contado():
    """2022 ya subido; 2023 se confirma con «Estado inicial». Su saldo de
    apertura ($61.000) es el cierre de 2022, contado movimiento por movimiento:
    la vista previa lo saca, y la confirmación no lo tiene que traer de vuelta
    (daba $142.000 en vez de $81.000)."""
    cuenta = _Cuenta()
    cuenta.confirmar(cuenta.vista_previa(BM_2022, "bullmarket", nombre="bm-2022.csv"))
    prev = cuenta.vista_previa(BM_2023, "bullmarket", nombre="bm-2023.csv")
    assert "Saldo anterior" not in {r["notes"] for r in prev["rows_preview"]}
    cuenta.confirmar(prev, {"seed_date": "2022-12-30", "brokers": []})
    assert cuenta.efectivo() == 81000.0
