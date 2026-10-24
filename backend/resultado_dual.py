"""El resultado de una venta en las DOS monedas — la cuenta vive acá y en ningún otro lado.

POR QUÉ EXISTE
──────────────
`operations.pnl_pct` es el % en la MONEDA DE LA VENTA. En una venta en pesos es el %
en pesos: GGAL comprada a $4.500 y vendida a $6.900 da +53,3 % aunque el dólar haya
pasado de 1.000 a 1.500 en el medio y en dólares se haya ganado +2,2 %. Y `pnl_usd`
de esa venta es la ganancia en pesos dividida por el dólar DEL DÍA DE LA VENTA (la
regla "FX-phantom" de los motores de venta): tampoco es la ganancia en dólares.

DESDE EL 24/10/2026 (decisión de Nico) el resultado en dólares es otro: lo cobrado
al dólar de la venta menos el costo al dólar de compra DEL LOTE, el mismo con que
Cartera muestra el costo en dólares (`resultado_en_dolares`). En las cuentas v2 los
motores escriben ESO en `pnl_usd` y su % en `pnl_pct` (que pasa a ser el % en
dólares). En las v1 nada cambia hasta migrarlas.

Al lado se guarda el resultado en las dos monedas, cada punta a SU dólar:

    costo_ars / costo_usd      lo que costó el lote, al dólar del DÍA DE COMPRA
    cobrado_ars / cobrado_usd  lo que entró por la venta, al dólar del DÍA DE VENTA
    pnl_pct_ars / pnl_pct_usd  (cobrado − costo) / costo, en cada moneda
    pnl_sin_dato               por qué falta alguno de los dos (nunca se inventa)

La moneda en que se pagó cada punta no necesita dólar: el costo de un lote comprado
en pesos ES el costo en pesos. El dólar sólo hace falta para la OTRA moneda.

EL DÓLAR
────────
El de la cuenta (`fx.fx_version`): MEP de la fecha en v2, blue de la fecha en v1,
con la red histórica de `fx.fx_for_date` (MEP → blue). SIN el dólar de hoy como
respaldo: si no hay dato para esa fecha, el % de esa moneda queda vacío con su
motivo. Así recalcular da siempre lo mismo.

QUIÉN LA USA
────────────
· Los tres motores de venta FIFO (`main.sell_position_fifo`,
  `persister._persist_sell_fifo`, `rebuild._replay_asset`) llaman a
  `resultado_en_dos_monedas` con el lote que están consumiendo.
· El histórico (`corregir_tanda`, por tandas, sólo cuentas que usaron la app en los
  últimos 60 días) y la edición de una venta llaman a `resultado_de_la_fila`, que
  junta los mismos datos de la fila guardada y llama a la MISMA función.
"""
import json
from typing import Any, Dict, Optional

import fx as _fx

COLUMNAS = ("costo_ars", "costo_usd", "cobrado_ars", "cobrado_usd",
            "pnl_pct_ars", "pnl_pct_usd", "pnl_sin_dato")

# Los motivos de `pnl_sin_dato`. Uno solo por fila: el primero que impide un %.
SIN_FECHA_COMPRA = "sin_fecha_compra"   # el lote no tiene fecha de compra
SIN_DOLAR_COMPRA = "sin_dolar_compra"   # no hay dólar guardado para el día de compra
SIN_DOLAR_VENTA = "sin_dolar_venta"     # no hay dólar guardado para el día de venta
SIN_COSTO = "sin_costo"                 # el lote no tiene costo (0 o vacío)
MONEDA_DEL_LOTE = "moneda_del_lote"     # no se puede saber en qué moneda se compró
RETIRO = "retiro"                       # salida del activo a costo, no una venta


def _moneda(c) -> Optional[str]:
    """'ARS' o 'USD' (USDT y cualquier dólar → 'USD'). None si no hay moneda."""
    if c is None or str(c).strip() == "":
        return None
    return "ARS" if str(c).strip().upper() == "ARS" else "USD"


def _pos(x) -> Optional[float]:
    try:
        return float(x) if x is not None and float(x) > 0 else None
    except (TypeError, ValueError):
        return None


def riel_de_la_cuenta(conn, uid: int) -> str:
    """El dólar con que la cuenta valúa por fecha: MEP (v2) o blue (v1)."""
    return _fx.RIEL_MEP if _fx.fx_version(conn, uid) == _fx.FX_V2 else _fx.RIEL_BLUE


def _dolar(conn, fecha, riel) -> Optional[float]:
    if not fecha:
        return None
    return _pos(_fx.fx_for_date(conn, fecha, fallback=None, riel=riel))


def resultado_en_dos_monedas(conn, *, costo, moneda_costo, fecha_compra,
                             cobrado, moneda_venta, fecha_venta, riel,
                             tc_compra=None, tc_venta=None,
                             retiro: bool = False) -> Dict[str, Any]:
    """El resultado de UN pedazo de venta (un lote) en pesos y en dólares.

    `costo` va en la moneda en que se COMPRÓ el lote (`moneda_costo`), con las
    comisiones de compra; `cobrado` en la moneda de la VENTA, ya sin la comisión
    de venta.

    `tc_compra` es el dólar de compra guardado en el LOTE (`positions.tc_compra`):
    el que escribió el usuario al cargarlo o, si no, el de esa fecha. Es el MISMO
    con que Cartera muestra el costo en dólares (`costBasisRate` en
    valuation.js, `_rate_del_costo` en snapshots_job.py), así que el resultado
    que queda al vender es el que Cartera mostraba un minuto antes. Sin él, el
    dólar de la fecha de compra.

    `tc_venta` es el dólar que el usuario escribió en la venta, si lo escribió:
    es lo que de verdad le dieron y le gana a la serie.

    Devuelve un dict con las `COLUMNAS`, listo para el INSERT/UPDATE.
    """
    out: Dict[str, Any] = dict.fromkeys(COLUMNAS)
    mc, mv = _moneda(moneda_costo), _moneda(moneda_venta)
    if retiro:
        out["pnl_sin_dato"] = RETIRO
        return out
    if mc is None or mv is None:
        out["pnl_sin_dato"] = MONEDA_DEL_LOTE
        return out

    tc_c = _pos(tc_compra) or _dolar(conn, fecha_compra, riel)
    tc_v = _pos(tc_venta) or _dolar(conn, fecha_venta, riel)

    def _en_las_dos(monto, moneda, tc):
        if monto is None:
            return None, None
        monto = float(monto)
        if moneda == "ARS":
            return monto, (monto / tc if tc else None)
        return (monto * tc if tc else None), monto

    costo = float(costo) if costo is not None else None
    if costo is not None and costo > 0:
        out["costo_ars"], out["costo_usd"] = _en_las_dos(costo, mc, tc_c)
    out["cobrado_ars"], out["cobrado_usd"] = _en_las_dos(cobrado, mv, tc_v)

    for m in ("ars", "usd"):
        c, v = out[f"costo_{m}"], out[f"cobrado_{m}"]
        if c and v is not None:
            out[f"pnl_pct_{m}"] = round((v - c) / c * 100, 4)
        for k in (f"costo_{m}", f"cobrado_{m}"):
            if out[k] is not None:
                out[k] = round(out[k], 6)

    if out["pnl_pct_ars"] is None or out["pnl_pct_usd"] is None:
        if costo is None or costo <= 0:
            out["pnl_sin_dato"] = SIN_COSTO
        elif not fecha_compra and not _pos(tc_compra) and (
                out["costo_ars"] is None or out["costo_usd"] is None):
            out["pnl_sin_dato"] = SIN_FECHA_COMPRA
        elif out["costo_ars"] is None or out["costo_usd"] is None:
            out["pnl_sin_dato"] = SIN_DOLAR_COMPRA
        else:
            out["pnl_sin_dato"] = SIN_DOLAR_VENTA
    return out


def resultado_en_dolares(resultado: Optional[Dict[str, Any]]):
    """`(pnl_usd, invested_usd)` de la venta: lo cobrado en dólares menos el costo
    en dólares, cada punta a su dólar. None si falta alguna de las dos (sin fecha
    o sin dólar de compra, retiro, sin costo): ahí el motor deja su regla vieja.

    LA REGLA (decidida por Nico el 24/10/2026). Hasta acá una venta en pesos
    anotaba `pnl_usd = ganancia en pesos ÷ dólar de la venta`: GGAL comprada con
    US$ 450 (450.000 pesos a 1.000) y vendida por US$ 460 (690.000 a 1.500)
    anotaba +US$ 160. Cartera, en dólares, mostraba +US$ 10 un minuto antes de
    vender, y el cierre del mes también: vender fabricaba US$ 150 que no existen.

    En una venta en dólares, o de un lote comprado en dólares, esto da lo mismo
    que la regla vieja; sólo cambia el lote comprado en pesos.
    """
    if not resultado:
        return None
    c, v = resultado.get("costo_usd"), resultado.get("cobrado_usd")
    if c is None or v is None or c <= 0:
        return None
    return v - c, c


# ─── Desde una fila ya guardada (histórico y edición) ─────────────────────────

def _foto_del_lote(op: Dict[str, Any]) -> Dict[str, Any]:
    """La foto del lote que guarda la venta hecha con el botón (`undo_meta_json.lot`)."""
    try:
        meta = json.loads(op.get("undo_meta_json") or "{}") or {}
    except (TypeError, ValueError):
        meta = {}
    lote = meta.get("lot") if isinstance(meta, dict) else None
    return lote if isinstance(lote, dict) else {}


def _compras_importadas(conn, uid: int, op: Dict[str, Any]):
    """Las compras importadas del activo en la fecha de compra del lote, o None si
    la venta no vino de un archivo. Es de donde salió el lote que consumió."""
    importada = conn.execute(
        "SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1", (op["id"],)).fetchone()
    if not (importada and op.get("entry_date")):
        return None
    try:
        from importing.persister import broker_pair
        from importing.schema import TX_VIVAS, OP_BUY
    except ImportError:  # pragma: no cover
        return None
    par = broker_pair(conn, uid, op["broker"])
    ph = ",".join("?" * len(par))
    return conn.execute(
        f"""SELECT n.currency, n.tc_compra FROM {TX_VIVAS}
             WHERE b.user_id=? AND n.broker IN ({ph}) AND n.asset_symbol=?
               AND n.operation_type=? AND n.date=?""",
        (uid, *par, op["asset"], OP_BUY, str(op["entry_date"])[:10])).fetchall()


def _moneda_del_lote(conn, uid: int, op: Dict[str, Any], moneda_venta: str) -> Optional[str]:
    """En qué moneda se compró el lote que consumió esta venta.

    · Venta hecha con el botón "Vender": la foto del lote.
    · Venta importada: la moneda de las COMPRAS importadas de ese activo en la
      fecha de compra del lote. Si ese día hubo compras en las dos monedas no se
      sabe cuál pagó → None (sin dato, no se adivina).
    · Sin rastro (o un lote semilla, que nace en la moneda de la venta): la de la venta.
    """
    lote = _foto_del_lote(op)
    if _moneda(lote.get("currency")):
        return _moneda(lote.get("currency"))
    compras = _compras_importadas(conn, uid, op)
    if compras:
        monedas = {_moneda(r[0]) or moneda_venta for r in compras}
        return monedas.pop() if len(monedas) == 1 else None
    return moneda_venta


def _tc_compra_del_lote(conn, uid: int, op: Dict[str, Any]) -> Optional[float]:
    """El dólar de compra que tenía el LOTE (`positions.tc_compra`), el que usaba
    Cartera para mostrar su costo en dólares:
    · venta con el botón: el de la foto del lote;
    · venta importada: el que el archivo trajo en la compra de esa fecha (el rebuild
      lo pasa igual al lote). Si las compras de ese día traen dólares distintos,
      ninguno.
    None → se usa el dólar de la fecha de compra, que es con lo que el alta y el
    rebuild completan un lote que no lo trae."""
    lote = _foto_del_lote(op)
    if _pos(lote.get("tc_compra")):
        return _pos(lote.get("tc_compra"))
    compras = _compras_importadas(conn, uid, op)
    if compras:
        tcs = {_pos(r[1]) for r in compras}
        if len(tcs) == 1:
            return tcs.pop()
    return None


def es_venta_de_un_lote(op: Dict[str, Any]) -> bool:
    """Las filas que escriben los motores de venta FIFO: 'Venta' con precio y cantidad."""
    return ((op.get("op_type") or "").strip() == "Venta"
            and op.get("exit_price") is not None
            and (op.get("quantity") or 0) > 0)


def _sin_dato(motivo: str) -> Dict[str, Any]:
    out = dict.fromkeys(COLUMNAS)
    out["pnl_sin_dato"] = motivo
    return out


def resultado_de_la_fila(conn, uid: int, op: Dict[str, Any], *, riel: str,
                         antes: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """El resultado en las dos monedas de una venta YA GUARDADA. None si la fila no
    es la venta de un lote (dividendos, cupones, futuros, conversiones, plazos fijos:
    no tienen un costo del que medir un %).

    No hay otra cuenta: junta de la fila lo que el motor tenía en la mano —costo
    del lote en su moneda, dólar de compra, fechas, lo cobrado— y llama a
    `resultado_en_dos_monedas`.

    DE DÓNDE SALE EL COSTO DEL LOTE
    · Si la fila ya lo tiene (la escribió un motor con esta cuenta), de ahí; `antes`
      es la fila antes de una edición, para escalarlo si cambió la cantidad.
    · Si es una venta VIEJA, del par que dejó el motor de entonces: su `pnl_pct` es
      ganancia / costo en la moneda de la venta, así que costo = cobrado ÷ (1 +
      pnl_pct/100). El dólar de la venta se cancela en ese cociente, por eso sirve
      incluso en las filas que quedaron estampadas con un dólar equivocado.
      ⚠️ Vale sólo para filas con la regla vieja: en una escrita con la nueva,
      `pnl_pct` es el % en dólares. Por eso la nueva siempre trae el costo.
    """
    if not es_venta_de_un_lote(op):
        return None
    moneda_venta = _moneda(op.get("currency"))
    if moneda_venta is None:
        # Filas anteriores a que se guardara la moneda: los motores de entonces
        # vendían en la moneda del broker.
        br = conn.execute("SELECT currency FROM brokers WHERE user_id=? AND name=?",
                          (uid, op["broker"])).fetchone()
        moneda_venta = _moneda(br[0]) if br else None
    if moneda_venta is None:
        return _sin_dato(MONEDA_DEL_LOTE)

    cobrado = float(op["exit_price"]) * float(op["quantity"]) - float(op.get("commissions") or 0)
    fx_fila = _pos(op.get("fx_to_usd"))
    entry_date = op.get("entry_date")
    # El dólar de la venta: en una cuenta v2 el que quedó estampado en la fila es el
    # de la fecha (o el que escribió el usuario). En v1 el estampado puede ser el
    # dólar del día del import, así que se busca el de la fecha.
    tc_venta = fx_fila if (moneda_venta == "ARS" and riel == _fx.RIEL_MEP) else None

    # Una salida a costo (retiro de un exchange, transferencia): sin cobro y sin resultado.
    if not op["exit_price"] and not op.get("pnl_usd"):
        return _sin_dato(RETIRO)

    moneda_lote = _moneda_del_lote(conn, uid, op, moneda_venta)
    if moneda_lote is None:
        return _sin_dato(MONEDA_DEL_LOTE)

    # ── Fila escrita con esta cuenta: el costo y el dólar de compra ya están ──
    base = antes if (antes and (antes.get("costo_ars") is not None
                                or antes.get("costo_usd") is not None)) else op
    guardado = base.get("costo_ars") if moneda_lote == "ARS" else base.get("costo_usd")
    if guardado is not None:
        q0, q1 = float(base.get("quantity") or 0), float(op["quantity"])
        costo = float(guardado) * (q1 / q0 if q0 else 1)
        tc_c = (float(base["costo_ars"]) / float(base["costo_usd"])
                if _pos(base.get("costo_ars")) and _pos(base.get("costo_usd")) else None)
        return resultado_en_dos_monedas(conn, costo=costo, moneda_costo=moneda_lote,
                                        fecha_compra=entry_date, cobrado=cobrado,
                                        moneda_venta=moneda_venta, fecha_venta=op["date"],
                                        riel=riel, tc_compra=tc_c, tc_venta=tc_venta)

    # ── Fila vieja: el costo se despeja del par (pnl_usd, pnl_pct) ──
    pct = op.get("pnl_pct")
    costo_venta = None   # el costo del lote, en la moneda de la VENTA
    if pct is not None and abs(float(pct) + 100) > 1e-9:
        costo_venta = cobrado / (1 + float(pct) / 100)
    elif pct is not None and op.get("pnl_usd") is not None:
        # −100 %: la fórmula de arriba divide por cero; el costo es lo cobrado − el
        # resultado, con el resultado llevado de vuelta a la moneda de la venta.
        if moneda_venta == "USD":
            costo_venta = cobrado - float(op["pnl_usd"])
        elif fx_fila:
            costo_venta = cobrado - float(op["pnl_usd"]) * fx_fila

    # El motor llevó el costo del lote a la moneda de la venta (`fx.costo_en_moneda_de_venta`).
    # Se deshace esa conversión con el mismo dólar que usó para volver a la moneda del lote.
    costo = costo_venta
    if costo is not None and moneda_lote != moneda_venta:
        if moneda_lote == "USD":      # lote en dólares vendido en pesos: al dólar de la venta
            if not fx_fila:
                return _sin_dato(SIN_DOLAR_VENTA)
            costo = costo / fx_fila
        else:                         # lote en pesos vendido en dólares: al dólar de la fecha de compra
            tc_c = _dolar(conn, entry_date, riel)
            if not tc_c:
                return _sin_dato(SIN_FECHA_COMPRA if not entry_date else SIN_DOLAR_COMPRA)
            costo = costo * tc_c

    return resultado_en_dos_monedas(conn, costo=costo, moneda_costo=moneda_lote,
                                    fecha_compra=entry_date, cobrado=cobrado,
                                    moneda_venta=moneda_venta, fecha_venta=op["date"],
                                    riel=riel, tc_compra=_tc_compra_del_lote(conn, uid, op),
                                    tc_venta=tc_venta)


def guardar(conn, uid: int, op_id: int, resultado: Optional[Dict[str, Any]]) -> None:
    """Escribe las columnas del resultado en la fila (o las vacía si es None)."""
    r = resultado or dict.fromkeys(COLUMNAS)
    conn.execute(
        f"UPDATE operations SET {', '.join(c + '=?' for c in COLUMNAS)} "
        "WHERE id=? AND user_id=?",
        (*[r.get(c) for c in COLUMNAS], op_id, uid))


def recalcular_fila(conn, uid: int, op_id: int, antes: Optional[Dict[str, Any]] = None) -> None:
    """Re-deriva las columnas de una fila desde lo que tiene guardado (alta a mano y
    edición). No toca `pnl_usd` ni `pnl_pct`: en la edición son los que escribió
    el usuario."""
    row = conn.execute("SELECT * FROM operations WHERE id=? AND user_id=?",
                       (op_id, uid)).fetchone()
    if row:
        guardar(conn, uid, op_id, resultado_de_la_fila(conn, uid, dict(row),
                                                       riel=riel_de_la_cuenta(conn, uid),
                                                       antes=antes))


# ─── La corrección del histórico, por tandas ─────────────────────────────────

def usuarios_activos(conn, dias: int) -> list:
    """Quiénes usaron la app en los últimos `dias` días: cualquier rastro de uso
    (`uso_diario`, la definición de "usó la app" de /admin/uso), un ingreso
    (`login_history`, `users.last_login_at`) o ser cliente de un asesor que la usó
    (el asesor mira y opera la cuenta del cliente).

    Sin try/except a propósito: en Postgres una consulta que falla deja la
    transacción abortada y todo lo que sigue revienta; las tres tablas existen en
    los dos esquemas."""
    from datetime import timedelta
    from fechas import hoy_art_date
    # El día ARGENTINO (fechas.py): con el reloj crudo, de 21 a 24 el corte ya era mañana.
    desde = (hoy_art_date() - timedelta(days=int(dias))).isoformat()
    activos = set()
    for sql in ("SELECT DISTINCT user_id FROM uso_diario WHERE dia >= ?",
                "SELECT DISTINCT user_id FROM login_history WHERE created_at >= ?",
                "SELECT id FROM users WHERE last_login_at >= ?"):
        activos |= {r[0] for r in conn.execute(sql, (desde,)).fetchall()}
    for r in conn.execute("SELECT advisor_uid, client_uid FROM advisor_clients "
                          "WHERE status='active'").fetchall():
        if r[0] in activos:
            activos.add(r[1])
    return sorted(u for u in activos if u is not None)


_PENDIENTE = ("op_type='Venta' AND pnl_pct_ars IS NULL AND pnl_pct_usd IS NULL "
              "AND pnl_sin_dato IS NULL")


def corregir_usuario(conn, uid: int, *, apply: bool, muestra: int = 5) -> Dict[str, Any]:
    """Completa y corrige las ventas viejas de UNA cuenta v2.

    · Las columnas del resultado en pesos y en dólares.
    · `pnl_usd` y `pnl_pct` a la regla de cada punta a su dólar
      (`resultado_en_dolares`), si la venta tiene los dos dólares; si no, quedan
      como están (y `pnl_sin_dato` dice por qué).

    Una cuenta v1 NO se toca: los motores no le aplican la regla (fx.py,
    "Versionado por usuario") y, si se le llenaran sólo las columnas, dejaría de
    figurar como pendiente y al migrarla a v2 sus ventas a mano quedarían con la
    regla vieja para siempre. Después de migrarla, se corre esto con su user_id.

    Sólo toca ventas con las columnas vacías: nunca una que escribió un motor con
    esta cuenta, y apretarlo dos veces no hace nada la segunda. No commitea ni
    recalcula los meses: eso lo hace el que llama, en la misma transacción.
    """
    riel = riel_de_la_cuenta(conn, uid)
    v2 = riel == _fx.RIEL_MEP
    rep = {"user_id": uid, "fx_version": "v2" if v2 else "v1", "ventas": 0,
           "con_los_dos": 0, "sin_dato": {}, "realizado_antes": 0.0, "realizado_despues": 0.0,
           "cambian_de_signo": 0, "ejemplos": []}
    if not v2:
        rep["omitida"] = "cuenta v1: se corrige después de migrarla al dólar por fecha"
        return rep
    filas = conn.execute(f"SELECT * FROM operations WHERE user_id=? AND {_PENDIENTE} "
                         "ORDER BY date, id", (uid,)).fetchall()
    for f in filas:
        op = dict(f)
        res = resultado_de_la_fila(conn, uid, op, riel=riel)
        if res is None:
            continue
        rep["ventas"] += 1
        if res["pnl_sin_dato"]:
            rep["sin_dato"][res["pnl_sin_dato"]] = rep["sin_dato"].get(res["pnl_sin_dato"], 0) + 1
        else:
            rep["con_los_dos"] += 1
        antes_usd, antes_pct = op.get("pnl_usd"), op.get("pnl_pct")
        nuevo_usd, nuevo_pct = antes_usd, antes_pct
        en_usd = resultado_en_dolares(res)
        if en_usd:
            nuevo_usd = round(en_usd[0], 2)
            nuevo_pct = round(en_usd[0] / en_usd[1] * 100, 4)
        rep["realizado_antes"] += float(antes_usd or 0)
        rep["realizado_despues"] += float(nuevo_usd or 0)
        if (antes_usd or 0) * (nuevo_usd or 0) < 0:
            rep["cambian_de_signo"] += 1
        if len(rep["ejemplos"]) < muestra and nuevo_usd != antes_usd:
            rep["ejemplos"].append({
                "id": op["id"], "fecha": op["date"], "activo": op["asset"],
                "moneda": op.get("currency"), "pnl_usd_antes": antes_usd,
                "pnl_usd_despues": nuevo_usd, "pnl_pct_ars": res["pnl_pct_ars"],
                "pnl_pct_usd": res["pnl_pct_usd"]})
        if apply:
            guardar(conn, uid, op["id"], res)
            if nuevo_usd != antes_usd or nuevo_pct != antes_pct:
                conn.execute("UPDATE operations SET pnl_usd=?, pnl_pct=? WHERE id=? AND user_id=?",
                             (nuevo_usd, nuevo_pct, op["id"], uid))
    rep["realizado_antes"] = round(rep["realizado_antes"], 2)
    rep["realizado_despues"] = round(rep["realizado_despues"], 2)
    return rep


def corregir_tanda(conn, *, recalcular_meses, apply: bool = False, tanda: int = 10,
                   dias_activo: int = 60, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Una TANDA de la corrección: las próximas `tanda` cuentas que usaron la app en
    los últimos `dias_activo` días y todavía tienen ventas sin corregir.

    Cada cuenta va en SU transacción: sus ventas + `recalcular_meses(conn, uid)`
    (el recálculo de siempre, `_recalc_pnl_realized_from_ops`, que reescribe el
    realizado de cada mes desde las operaciones y repara la cadena). Si una falla,
    se deshace sólo esa y sigue la próxima. `apply=False` no escribe nada.
    """
    activos = [user_id] if user_id is not None else usuarios_activos(conn, dias_activo)
    pendientes, v1 = [], []
    for u in activos:
        if conn.execute(f"SELECT 1 FROM operations WHERE user_id=? AND {_PENDIENTE} LIMIT 1",
                        (u,)).fetchone():
            (pendientes if riel_de_la_cuenta(conn, u) == _fx.RIEL_MEP else v1).append(u)
    lote, cuentas, errores = pendientes[:max(1, int(tanda))], [], []
    for u in lote:
        try:
            rep = corregir_usuario(conn, u, apply=apply)
            if apply:
                recalcular_meses(conn, u)
                conn.commit()
            cuentas.append(rep)
        except Exception as ex:  # una cuenta rota no frena la tanda
            conn.rollback()
            errores.append({"user_id": u, "error": f"{type(ex).__name__}: {ex}"})
    return {
        "applied": bool(apply), "dias_activo": int(dias_activo),
        "activos": len(activos), "con_ventas_pendientes": len(pendientes),
        "v1_esperan_migracion": len(v1),
        "en_esta_tanda": len(lote),
        "quedan_despues": max(0, len(pendientes) - (len(lote) if apply else 0)),
        "ventas": sum(c["ventas"] for c in cuentas),
        "realizado_antes": round(sum(c["realizado_antes"] for c in cuentas), 2),
        "realizado_despues": round(sum(c["realizado_despues"] for c in cuentas), 2),
        "cuentas": cuentas, "errores": errores,
    }
