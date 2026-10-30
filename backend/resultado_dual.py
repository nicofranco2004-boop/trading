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
dólares). EN LAS v1 NO SE ESCRIBE NADA (ni la regla ni las columnas): una v1 que
vendiera con la regla vieja y las columnas llenas quedaría con un `pnl_usd` de una
regla y un % de otra, y al migrarla a v2 nada la marcaría como pendiente. Al migrar
a v2, sus ventas quedan con las columnas vacías y las toma la corrección.

Al lado se guarda el resultado en las dos monedas, cada punta a SU dólar:

    costo_ars / costo_usd      lo que costó el lote, al dólar del DÍA DE COMPRA
    cobrado_ars / cobrado_usd  lo que entró por la venta, al dólar del DÍA DE VENTA
    pnl_pct_ars / pnl_pct_usd  (cobrado − costo) / costo, en cada moneda
    pnl_sin_dato               por qué falta alguno de los dos (nunca se inventa)

La moneda en que se pagó cada punta no necesita dólar: el costo de un lote comprado
en pesos ES el costo en pesos. El dólar sólo hace falta para la OTRA moneda.

EL DÓLAR
────────
MEP de la fecha (cuentas v2) por `fx.fx_for_date`, con su red histórica MEP → blue.
SIN el dólar de hoy como respaldo: si no hay dato para esa fecha, el % de esa moneda
queda vacío con su motivo. Así recalcular da siempre lo mismo.

QUIÉN LA USA
────────────
· Los tres motores de venta FIFO (`main.sell_position_fifo`,
  `persister._persist_sell_fifo`, `rebuild._replay_asset`) llaman a
  `resultado_en_dos_monedas` con el lote que están consumiendo.
· El histórico (`corregir_tanda`, por tandas, sólo cuentas que usaron la app en los
  últimos 60 días) llama a `resultado_de_la_fila`, que junta los datos de la fila
  guardada y llama a la MISMA función. Una fila editada o cargada a mano NO se
  reconstruye nunca: sus números son los que escribió el usuario (`MANUAL`).

LO QUE LA CORRECCIÓN DEL HISTÓRICO NO HACE
──────────────────────────────────────────
Reconstruir el costo del lote desde la fila es una inferencia. Se acepta sólo si
cierra: con la foto del lote (ventas con el botón desde el 9/10) el costo es exacto;
sin ella, el costo despejado del par (pnl_usd, pnl_pct) tiene que cerrar con el par
y con precio × cantidad. Si no cierra la fila queda como estaba y con su motivo
(`NO_CIERRA`, `MONEDA_DEL_LOTE`, `IMPLAUSIBLE`): un `pnl_usd` reescrito con un costo
inventado es peor que dejar la regla vieja.
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
# Marcas que NO dicen "falta un dato" sino "esta fila no se toca":
MANUAL = "manual"                       # cargada o editada a mano: los números son los del usuario
NO_CIERRA = "no_cierra"                 # los números de la fila no cierran entre sí
IMPLAUSIBLE = "implausible"             # el resultado nuevo es de otro orden de magnitud

# Cuánto puede diferir el costo despejado de precio × cantidad (comisiones, redondeos).
_BANDA_COSTO = (0.8, 1.25)
# Cuánto puede diferir el dólar estampado en la fila del de su fecha (MEP y blue llegan a
# separarse 25 %; el TC vacío estampaba 1,0 y el del import, el dólar vivo).
_BANDA_DOLAR = (0.75, 1.34)
# Tope del % en dólares que se acepta al corregir una fila vieja (un 153.233 % es un error).
_MAX_PCT = 10000.0


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


def es_cuenta_v2(conn, uid: int) -> bool:
    """¿La cuenta valúa por el dólar de cada fecha (v2)? Sólo LEE: `fx.fx_version`
    persiste la versión de una cuenta virgen, y un GET o un ensayo no pueden escribir."""
    return _fx.fx_version_lectura(conn, uid) == _fx.FX_V2


def riel_de_la_cuenta(conn, uid: int) -> str:
    """El dólar con que la cuenta valúa por fecha: MEP (v2) o blue (v1)."""
    return _fx.RIEL_MEP if es_cuenta_v2(conn, uid) else _fx.RIEL_BLUE


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

    En una venta en dólares de un lote en dólares, o de un lote en dólares vendido
    en pesos, esto da lo mismo que la regla vieja. Cambia el lote comprado en pesos
    (también el dólar-MEP, si el usuario escribió un `tc_compra` distinto del dólar
    de la fecha: antes el costo se llevaba al dólar de la fecha, ahora al del lote,
    que es el que muestra Cartera).
    """
    if not resultado:
        return None
    c, v = resultado.get("costo_usd"), resultado.get("cobrado_usd")
    if c is None or v is None or c <= 0:
        return None
    return v - c, c




def pcts_de_la_venta(op: Dict[str, Any], moneda_venta: Optional[str]):
    """`(pct_en_pesos, pct_en_dolares)` de una venta, para los lectores que los sacan
    a un tercero (CSV del contador, paquetes de IA).

    · Fila con sus dos monedas guardadas: las columnas.
    · Fila sin ellas (cuenta v1, venta vieja sin corregir, o cargada/editada a mano —
      `MANUAL`): su `pnl_pct`, que es el % en la moneda de la VENTA (la regla vieja o lo
      que escribió el usuario) y va a la columna de esa moneda; la otra queda vacía.
    Misma regla que `pctEnMoneda` del frontend (components/operations/shared.js)."""
    sd = op.get("pnl_sin_dato")
    tiene = (op.get("pnl_pct_ars") is not None or op.get("pnl_pct_usd") is not None
             or (sd is not None and sd != MANUAL))
    if tiene:
        return op.get("pnl_pct_ars"), op.get("pnl_pct_usd")
    pct = op.get("pnl_pct")
    if moneda_venta == "ARS":
        return pct, None
    if moneda_venta == "USD":
        return None, pct
    return None, None


# ─── Desde una fila ya guardada (histórico) ───────────────────────────────────

def moneda_de_la_venta(conn, uid: int, op: Dict[str, Any]) -> Optional[str]:
    """La moneda en que se vendió: la de la fila y, si falta (las ventas anteriores
    al 28/7 la tienen NULL), la del broker — era la regla de los motores de entonces.
    Una sola definición para todo lector (`insights/gap-month` la usa también)."""
    m = _moneda(op.get("currency"))
    if m:
        return m
    br = conn.execute("SELECT currency FROM brokers WHERE user_id=? AND name=?",
                      (uid, op.get("broker"))).fetchone()
    return _moneda(br[0]) if br else None


def _foto_del_lote(op: Dict[str, Any]) -> Dict[str, Any]:
    """La foto del lote que guarda la venta hecha con el botón (`undo_meta_json.lot`)."""
    try:
        meta = json.loads(op.get("undo_meta_json") or "{}") or {}
    except (TypeError, ValueError):
        meta = {}
    lote = meta.get("lot") if isinstance(meta, dict) else None
    return lote if isinstance(lote, dict) else {}


def _es_importada(conn, op: Dict[str, Any]) -> bool:
    return conn.execute("SELECT 1 FROM import_op_links WHERE operation_id=? LIMIT 1",
                        (op["id"],)).fetchone() is not None


def _compras_importadas(conn, uid: int, op: Dict[str, Any]):
    """Las compras importadas del activo en la fecha de compra del lote, o None si
    la venta no vino de un archivo. Es de donde salió el lote que consumió."""
    if not (op.get("entry_date") and _es_importada(conn, op)):
        return None
    try:
        from importing.persister import broker_pair
        from importing.schema import TX_VIVAS, OP_BUY
    except ImportError:  # pragma: no cover
        return None
    par = broker_pair(conn, uid, op["broker"])
    ph = ",".join("?" * len(par))
    return conn.execute(
        f"""SELECT n.currency, n.tc_compra, n.quantity, n.gross_amount, n.fees FROM {TX_VIVAS}
             WHERE b.user_id=? AND n.broker IN ({ph}) AND n.asset_symbol=?
               AND n.operation_type=? AND n.date=?""",
        (uid, *par, op["asset"], OP_BUY, str(op["entry_date"])[:10])).fetchall()


def _costo_unitario_importado(compras):
    """El costo por unidad, CON la comisión de compra, de las compras importadas de ese día:
    (Σ bruto + Σ comisión) ÷ Σ cantidad — lo mismo que arma el rebuild (invested = bruto,
    commissions = fees). Es el "nominal" exacto contra el que se valida el costo despejado
    (con precio × cantidad solo, la comisión confundía el dólar de compra). None si el
    archivo no trae montos."""
    if len({(_moneda(r[0]) or "") for r in compras}) > 1:
        return None                      # compras en monedas distintas el mismo día: no se suman
    try:
        q = sum(float(r[2] or 0) for r in compras)
        g = sum(float(r[3] or 0) for r in compras)
        f = sum(float(r[4] or 0) for r in compras)
    except (TypeError, ValueError, IndexError):
        return None
    return (g + f) / q if q > 0 and g > 0 else None


def _costo_de_la_foto(foto: Dict[str, Any], moneda_venta: str):
    """`(costo, moneda_del_lote, tc_compra)` EXACTOS de una venta hecha con el botón,
    desde la foto del lote que dejó el motor: la misma cuenta que hizo entonces
    (`costo_del_lote` + comisión de compra, prorrateado por lo consumido). No depende
    de nada que el usuario pueda editar. None si la foto está incompleta."""
    try:
        q, consumido = float(foto.get("quantity") or 0), float(foto.get("consumed") or 0)
        if q <= 0 or consumido <= 0:
            return None
        base = ((_fx.costo_del_lote(foto.get("invested"), foto.get("buy_price"), q) or 0)
                + float(foto.get("commissions") or 0))
    except (TypeError, ValueError):
        return None
    return base * consumido / q, (_moneda(foto.get("currency")) or moneda_venta), _pos(foto.get("tc_compra"))


def _pnl_viejo_esperado(cobrado, costo_lote, moneda_lote, moneda_venta, fx_fila):
    """El `pnl_usd` que habría escrito el motor VIEJO con este lote exacto, o None si
    no se puede saber (lote en pesos vendido en dólares: depende del riel de entonces)."""
    if moneda_venta == "USD":
        return cobrado - costo_lote if moneda_lote == "USD" else None
    if not fx_fila:
        return None
    costo_venta = costo_lote * fx_fila if moneda_lote == "USD" else costo_lote
    return (cobrado - costo_venta) / fx_fila


def _cierra_con_la_foto(conn, op, cobrado, costo_lote, moneda_lote, moneda_venta, fx_fila, entry_date):
    """¿Los números guardados en la fila son los que escribió el motor viejo con este lote
    exacto? Compara pnl_usd Y pnl_pct. Un lote en pesos vendido en dólares depende del dólar de
    compra con que costeó el motor de entonces (MEP en v2, blue en v1): se aceptan los dos."""
    pnl, pct = op.get("pnl_usd"), op.get("pnl_pct")
    candidatos = []     # (pnl_usd esperado, costo en la moneda de la venta)
    if moneda_venta == "USD":
        if moneda_lote == "USD":
            candidatos.append((cobrado - costo_lote, costo_lote))
        else:
            for riel in (_fx.RIEL_MEP, _fx.RIEL_BLUE):
                tc = _dolar(conn, entry_date, riel)
                if tc:
                    candidatos.append((cobrado - costo_lote / tc, costo_lote / tc))
    elif fx_fila:
        costo_venta = costo_lote * fx_fila if moneda_lote == "USD" else costo_lote
        candidatos.append(((cobrado - costo_venta) / fx_fila, costo_venta / fx_fila))
    if not candidatos or (pnl is None and pct is None):
        return True                 # no hay con qué comparar: se confía en la foto
    for esperado, costo_usd in candidatos:
        ok = pnl is None or abs(float(pnl) - esperado) <= 0.02 + 1e-3 * abs(esperado)
        if ok and pct is not None and costo_usd > 0:
            ok = abs(float(pct) - esperado / costo_usd * 100) <= 0.02 + 1e-3 * abs(esperado / costo_usd * 100)
        if ok:
            return True
    return False


def _costo_del_par(conn, op, *, cobrado, moneda_venta, fx_fila, entry_date, permitidas,
                   unitario_exacto=None):
    """Sin foto del lote: `(moneda_del_lote, costo_en_esa_moneda, None)` despejado del
    par que dejó el motor viejo, o `(None, None, motivo)` si no cierra.

    El motor viejo escribió `pnl_pct` = ganancia / costo en la moneda de la VENTA, así
    que costo_venta = cobrado ÷ (1 + pnl_pct/100). Eso sólo vale si la fila no se
    tocó, y la moneda del lote no está escrita en ningún lado, así que se valida:
      1. IDENTIDAD: el costo que implican (pnl_usd, pnl_pct) tiene que ser el mismo que
         el que implica lo cobrado. Una fila editada a mano, o con un dólar estampado
         que no fue el que se usó, no cierra.
      2. NOMINAL: el costo, en la moneda del lote, tiene que parecerse a precio de
         entrada × cantidad (con holgura por comisiones). Se prueban las monedas
         posibles del lote (la misma de la venta, dólares vendidos en pesos, pesos
         vendidos en dólares con el MEP o con el blue de entonces) y gana la que
         cierra; si ninguna cierra, no se adivina.
    """
    pct = op.get("pnl_pct")
    if pct is None:
        return None, None, SIN_COSTO
    pct = float(pct)
    pnl = op.get("pnl_usd")
    fx_s = fx_fila if moneda_venta == "ARS" else 1.0
    if pct <= -100 + 1e-9:
        if pnl is None or not fx_s:
            return None, None, SIN_COSTO
        costo_venta = cobrado - float(pnl) * fx_s
    else:
        costo_venta = cobrado / (1 + pct / 100)
        if pnl is not None and abs(pct) > 1e-9 and fx_s:
            implicito = float(pnl) * fx_s / (pct / 100)
            tol = 0.01 * abs(costo_venta) + 0.006 * fx_s / (abs(pct) / 100)
            if abs(implicito - costo_venta) > tol:
                return None, None, NO_CIERRA
    if costo_venta <= 0:
        return None, None, SIN_COSTO

    hipotesis = [(moneda_venta, costo_venta)]
    if moneda_venta == "ARS" and fx_fila:
        hipotesis.append(("USD", costo_venta / fx_fila))
    if moneda_venta == "USD" and entry_date:
        for riel in (_fx.RIEL_MEP, _fx.RIEL_BLUE):
            tc = _dolar(conn, entry_date, riel)
            if tc:
                hipotesis.append(("ARS", costo_venta * tc))
    if permitidas:
        hipotesis = [h for h in hipotesis if h[0] in permitidas]
    # El nominal: con las compras importadas es EXACTO (incluye la comisión de compra); sin
    # ellas es precio de entrada × cantidad, que la deja afuera.
    try:
        if unitario_exacto:
            nominal = float(unitario_exacto) * float(op.get("quantity"))
        else:
            nominal = float(op.get("entry_price")) * float(op.get("quantity"))
    except (TypeError, ValueError):
        nominal = 0.0
    if nominal <= 0:
        # Sin precio de entrada no hay con qué validar: sólo se acepta si el archivo
        # importado dijo en qué moneda se compró.
        if permitidas and len(permitidas) == 1 and hipotesis:
            return hipotesis[0][0], hipotesis[0][1], None
        return None, None, MONEDA_DEL_LOTE
    validas = [(abs(c / nominal - 1), m, c) for m, c in hipotesis
               if _BANDA_COSTO[0] <= c / nominal <= _BANDA_COSTO[1]]
    if not validas:
        return None, None, (NO_CIERRA if permitidas or entry_date else MONEDA_DEL_LOTE)
    validas.sort(key=lambda t: t[0])
    mejor = validas[0]
    # No se elige por cercanía entre candidatos que SIGUEN siendo distintos: con el nominal
    # inexacto (sin las compras importadas, la comisión no está en ningún lado) el MEP y el
    # blue de ese día —o la misma venta leída como lote en pesos o en dólares cuando el dólar
    # estampado es 1,0— caían los dos en la banda y ganaba el equivocado (una pérdida pasaba a
    # ganancia). Si hay dos candidatos que difieren más de 0,5 %, no se adivina.
    if len(validas) > 1 and any(
            (m != mejor[1] or abs(c / mejor[2] - 1) > 0.005) for _d, m, c in validas[1:]):
        if not unitario_exacto or mejor[0] > 0.01:
            return None, None, NO_CIERRA
    elif unitario_exacto and mejor[0] > 0.01:
        return None, None, NO_CIERRA
    return mejor[1], mejor[2], None


def _tc_compra_del_lote(conn, uid: int, op: Dict[str, Any], foto: Dict[str, Any]) -> Optional[float]:
    """El dólar de compra que tenía el LOTE (`positions.tc_compra`), el que usaba
    Cartera para mostrar su costo en dólares:
    · venta con el botón: el de la foto del lote;
    · venta importada: el que el archivo trajo en la compra de esa fecha (el rebuild
      lo pasa igual al lote). Si las compras de ese día traen dólares distintos,
      ninguno.
    None → se usa el dólar de la fecha de compra, que es con lo que el alta y el
    rebuild completan un lote que no lo trae."""
    if _pos(foto.get("tc_compra")):
        return _pos(foto.get("tc_compra"))
    compras = _compras_importadas(conn, uid, op)
    if compras:
        tcs = {_pos(r[1]) for r in compras} - {None}      # las compras en otra moneda no traen
        if len(tcs) == 1:
            return tcs.pop()
    return None


def _dolar_de_venta_creible(conn, op, moneda_venta, riel, fx_fila):
    """El dólar de la venta estampado en la fila, SÓLO si es creíble: cerca del de su
    fecha. El motor viejo estampaba 1,0 cuando el campo TC quedaba vacío, o el dólar
    vivo del día del import, y tomarlos como "el dólar de la venta" fabricaba ganancias
    de cientos de miles de dólares. None → `resultado_en_dos_monedas` usa el de la fecha."""
    if moneda_venta != "ARS" or not fx_fila:
        return None
    fecha = _dolar(conn, op.get("date"), riel)
    if fecha and _BANDA_DOLAR[0] <= fx_fila / fecha <= _BANDA_DOLAR[1]:
        return fx_fila
    return None


def es_venta_de_un_lote(op: Dict[str, Any]) -> bool:
    """Las filas que escriben los motores de venta FIFO: 'Venta' con precio y cantidad.
    `_PENDIENTE` lo repite en SQL: tienen que decir lo mismo."""
    return ((op.get("op_type") or "").strip() == "Venta"
            and op.get("exit_price") is not None
            and (op.get("quantity") or 0) > 0)


def _sin_dato(motivo: str) -> Dict[str, Any]:
    out = dict.fromkeys(COLUMNAS)
    out["pnl_sin_dato"] = motivo
    return out


def resultado_de_la_fila(conn, uid: int, op: Dict[str, Any], *, riel: str) -> Optional[Dict[str, Any]]:
    """El resultado en las dos monedas de una venta YA GUARDADA con la regla vieja.
    None si la fila no es la venta de un lote (dividendos, cupones, futuros,
    conversiones, plazos fijos: no tienen un costo del que medir un %).

    No hay otra cuenta: junta de la fila lo que el motor tenía en la mano —costo del
    lote en su moneda, dólar de compra, fechas, lo cobrado— y llama a
    `resultado_en_dos_monedas`. De dónde sale el costo, ver el docstring del módulo
    y `_costo_del_par`. Si la fila no cierra, devuelve el motivo y NO se toca.
    """
    if not es_venta_de_un_lote(op):
        return None
    moneda_venta = moneda_de_la_venta(conn, uid, op)
    if moneda_venta is None:
        return _sin_dato(MONEDA_DEL_LOTE)
    # Una salida a costo (retiro de un exchange, transferencia): sin cobro y sin resultado.
    if not op["exit_price"] and not op.get("pnl_usd"):
        return _sin_dato(RETIRO)

    cobrado = float(op["exit_price"]) * float(op["quantity"]) - float(op.get("commissions") or 0)
    fx_fila = _pos(op.get("fx_to_usd")) if moneda_venta == "ARS" else None
    entry_date = op.get("entry_date")
    foto = _foto_del_lote(op)
    if not foto and not entry_date and not _es_importada(conn, op):
        # Sin lote de dónde sacar el costo ni fecha de compra: la cargó el usuario a mano.
        return _sin_dato(MANUAL)

    costo_foto = _costo_de_la_foto(foto, moneda_venta) if foto else None
    if costo_foto:
        costo_lote, moneda_lote, _tc = costo_foto
        # Una edición de la CANTIDAD deja la foto con lo consumido originalmente.
        try:
            if abs(float(foto.get("consumed") or 0) - float(op["quantity"])) > 1e-6 * max(1.0, float(op["quantity"])):
                return _sin_dato(NO_CIERRA)
        except (TypeError, ValueError):
            return _sin_dato(NO_CIERRA)
        if not _cierra_con_la_foto(conn, op, cobrado, costo_lote, moneda_lote, moneda_venta,
                                   fx_fila, entry_date):
            return _sin_dato(NO_CIERRA)      # la editó el usuario: sus números no son los del motor
    else:
        compras = _compras_importadas(conn, uid, op)
        permitidas = ({(_moneda(r[0]) or moneda_venta) for r in compras} if compras else None)
        moneda_lote, costo_lote, motivo = _costo_del_par(
            conn, op, cobrado=cobrado, moneda_venta=moneda_venta, fx_fila=fx_fila,
            entry_date=entry_date, permitidas=permitidas,
            unitario_exacto=(_costo_unitario_importado(compras) if compras else None))
        if motivo:
            return _sin_dato(motivo)

    return resultado_en_dos_monedas(
        conn, costo=costo_lote, moneda_costo=moneda_lote, fecha_compra=entry_date,
        cobrado=cobrado, moneda_venta=moneda_venta, fecha_venta=op["date"], riel=riel,
        tc_compra=_tc_compra_del_lote(conn, uid, op, foto),
        tc_venta=_dolar_de_venta_creible(conn, op, moneda_venta, riel, fx_fila))


def guardar(conn, uid: int, op_id: int, resultado: Optional[Dict[str, Any]]) -> None:
    """Escribe las columnas del resultado en la fila (o las vacía si es None)."""
    r = resultado or dict.fromkeys(COLUMNAS)
    conn.execute(
        f"UPDATE operations SET {', '.join(c + '=?' for c in COLUMNAS)} "
        "WHERE id=? AND user_id=?",
        (*[r.get(c) for c in COLUMNAS], op_id, uid))


# ─── Cargar o editar a mano ──────────────────────────────────────────────────
# Una venta que el usuario tipea o edita lleva SUS números (pnl_usd, pnl_pct, precios):
# no hay lote del que sacar un costo exacto y reconstruirlo desde un % redondeado
# inventa un costo. La marca `MANUAL` la saca de la cola de la corrección (nunca se le
# pisa lo que escribió) y las pantallas leen sus números tal cual (`pctEnMoneda`,
# `pnlAt` caen a pnl_pct / pnl_usd × dólar).

def _cambio_economico(antes: Dict[str, Any], despues: Dict[str, Any]) -> bool:
    """¿La edición cambió algo que mueve el resultado? Con holgura para lo que el
    formulario redondea al devolver los números como texto."""
    def _n(x):
        try:
            return float(x) if x is not None and x != "" else None
        except (TypeError, ValueError):
            return None

    def _igual(a, b, tol_abs, tol_rel=0.0):
        a, b = _n(a), _n(b)
        if a is None or b is None:
            return a is None and b is None
        return abs(a - b) <= max(tol_abs, tol_rel * max(abs(a), abs(b)))

    if str(antes.get("date") or "")[:10] != str(despues.get("date") or "")[:10]:
        return True
    if (_moneda(antes.get("currency")) or "") != (_moneda(despues.get("currency")) or ""):
        return True
    return not (_igual(antes.get("exit_price"), despues.get("exit_price"), 0, 1e-4)
                and _igual(antes.get("entry_price"), despues.get("entry_price"), 0, 1e-4)
                and _igual(antes.get("quantity"), despues.get("quantity"), 0, 1e-4)
                and _igual(antes.get("commissions") or 0, despues.get("commissions") or 0, 0.01)
                and _igual(antes.get("fx_to_usd"), despues.get("fx_to_usd"), 0, 1e-4)
                and _igual(antes.get("pnl_usd"), despues.get("pnl_usd"), 0.011)
                and _igual(antes.get("pnl_pct"), despues.get("pnl_pct"), 0.011))


def al_cargar_a_mano(conn, uid: int, op_id: int, op: Dict[str, Any]) -> None:
    """Una venta tipeada en «Nueva operación»: sus números son los que escribió."""
    if es_venta_de_un_lote(op):
        guardar(conn, uid, op_id, _sin_dato(MANUAL))


def al_editar(conn, uid: int, op_id: int, antes: Optional[Dict[str, Any]],
              despues: Dict[str, Any]) -> None:
    """Después de editar una operación. Si no cambió nada que mueva el resultado (un
    «guardar» sin tocar, o sólo la nota), la fila queda como estaba: sigue pendiente si
    lo era. Si cambió, pasa a ser del usuario (`MANUAL`) y sus columnas se vacían; si
    ya no es la venta de un lote, se vacían sin más."""
    if antes is not None and not _moneda(antes.get("currency")):
        # Las ventas anteriores al 28/7 tienen currency NULL y `update_operation` escribe la
        # moneda resuelta por el broker: sin esto un «guardar» sin tocar contaba como cambio.
        antes = {**antes, "currency": moneda_de_la_venta(conn, uid, antes)}
    if antes is not None and not _cambio_economico(antes, despues):
        return
    guardar(conn, uid, op_id, _sin_dato(MANUAL) if es_venta_de_un_lote(despues) else None)


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


# Lo mismo que `es_venta_de_un_lote`, en SQL: una venta SIN precio o cantidad (sólo
# el P&L, que el formulario permite) no se puede corregir y no puede quedar en la cola.
_PENDIENTE = ("op_type='Venta' AND exit_price IS NOT NULL AND quantity IS NOT NULL "
              "AND quantity > 0 AND pnl_pct_ars IS NULL AND pnl_pct_usd IS NULL "
              "AND pnl_sin_dato IS NULL")


def corregir_usuario(conn, uid: int, *, apply: bool, aplicar_a_los_meses=None,
                     muestra: int = 5) -> Dict[str, Any]:
    """Completa y corrige las ventas viejas de UNA cuenta v2.

    · Las columnas del resultado en pesos y en dólares.
    · `pnl_usd` y `pnl_pct` a la regla de cada punta a su dólar
      (`resultado_en_dolares`), si la venta tiene los dos dólares y el resultado es
      plausible; si no, quedan como están (y `pnl_sin_dato` dice por qué).
    · Los meses: cada pnl_realized se mueve por la DIFERENCIA de las ventas que
      cambiaron (`aplicar_a_los_meses`), no se recalcula entero: el recálculo completo
      reescribe cada mes desde las operaciones y borra el P&L realizado que el
      usuario cargó a mano en /mensual.

    Una cuenta v1 NO se toca (ver el docstring del módulo): sus ventas quedan con las
    columnas vacías y, migrada a v2, las toma la corrección. Sólo toca ventas con las
    columnas vacías: apretarlo dos veces no hace nada la segunda. No commitea: eso lo
    hace el que llama, en la misma transacción.
    """
    v2 = es_cuenta_v2(conn, uid)
    rep = {"user_id": uid, "fx_version": "v2" if v2 else "v1", "ventas": 0,
           "con_los_dos": 0, "sin_dato": {}, "realizado_antes": 0.0, "realizado_despues": 0.0,
           "cambian_de_signo": 0, "ejemplos": []}
    if not v2:
        rep["omitida"] = "cuenta v1: se corrige después de migrarla al dólar por fecha"
        return rep
    riel = _fx.RIEL_MEP
    deltas: Dict[Any, float] = {}
    filas = conn.execute(f"SELECT * FROM operations WHERE user_id=? AND {_PENDIENTE} "
                         "ORDER BY date, id", (uid,)).fetchall()
    for f in filas:
        op = dict(f)
        res = resultado_de_la_fila(conn, uid, op, riel=riel)
        if res is None:                      # no debería: `_PENDIENTE` filtra lo mismo
            res = _sin_dato(MANUAL)
        en_usd = resultado_en_dolares(res)
        if en_usd and abs(en_usd[0] / en_usd[1] * 100) > _MAX_PCT:
            res, en_usd = _sin_dato(IMPLAUSIBLE), None
        rep["ventas"] += 1
        if res["pnl_sin_dato"]:
            rep["sin_dato"][res["pnl_sin_dato"]] = rep["sin_dato"].get(res["pnl_sin_dato"], 0) + 1
        else:
            rep["con_los_dos"] += 1
        antes_usd, antes_pct = op.get("pnl_usd"), op.get("pnl_pct")
        nuevo_usd, nuevo_pct = antes_usd, antes_pct
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
                try:
                    clave = (op["broker"], int(str(op["date"])[:4]), int(str(op["date"])[5:7]))
                    deltas[clave] = deltas.get(clave, 0.0) + (float(nuevo_usd or 0) - float(antes_usd or 0))
                except (TypeError, ValueError):
                    pass
    if apply and deltas and aplicar_a_los_meses is not None:
        aplicar_a_los_meses(conn, uid, deltas)
    rep["realizado_antes"] = round(rep["realizado_antes"], 2)
    rep["realizado_despues"] = round(rep["realizado_despues"], 2)
    return rep


def corregir_tanda(conn, *, aplicar_a_los_meses, apply: bool = False, tanda: int = 10,
                   dias_activo: int = 60, user_id: Optional[int] = None,
                   saltear=()) -> Dict[str, Any]:
    """Una TANDA de la corrección: las próximas `tanda` cuentas que usaron la app en
    los últimos `dias_activo` días y todavía tienen ventas sin corregir.

    Cada cuenta va en SU transacción: sus ventas + el movimiento de sus meses
    (`aplicar_a_los_meses`). Si una falla, se deshace sólo esa y sigue la próxima.
    Una cuenta que falla sigue pendiente y volvería a ser la primera de la cola:
    `saltear` (los user_id que ya fallaron) garantiza que la tanda siguiente avance.
    Se cuenta lo HECHO, no lo intentado. `apply=False` no escribe nada.
    """
    saltear = {int(u) for u in (saltear or ())}
    activos = [user_id] if user_id is not None else usuarios_activos(conn, dias_activo)
    pendientes, v1 = [], []
    for u in activos:
        if u in saltear:
            continue
        if conn.execute(f"SELECT 1 FROM operations WHERE user_id=? AND {_PENDIENTE} LIMIT 1",
                        (u,)).fetchone():
            (pendientes if es_cuenta_v2(conn, u) else v1).append(u)
    lote = pendientes[:max(1, int(tanda))]
    cuentas, errores = [], []
    for u in lote:
        try:
            rep = corregir_usuario(conn, u, apply=apply, aplicar_a_los_meses=aplicar_a_los_meses)
            if apply:
                conn.commit()
            cuentas.append(rep)
        except Exception as ex:  # una cuenta rota no frena la tanda
            conn.rollback()
            errores.append({"user_id": u, "error": f"{type(ex).__name__}: {ex}"})
    hechas = len(cuentas) if apply else 0
    return {
        "applied": bool(apply), "dias_activo": int(dias_activo),
        "activos": len(activos), "con_ventas_pendientes": len(pendientes),
        "v1_esperan_migracion": len(v1), "salteadas": len(saltear),
        "en_esta_tanda": len(lote),                 # las que se intentaron
        "corregidas": hechas, "con_error": len(errores),
        "quedan_despues": max(0, len(pendientes) - hechas),
        "ventas": sum(c["ventas"] for c in cuentas),
        "realizado_antes": round(sum(c["realizado_antes"] for c in cuentas), 2),
        "realizado_despues": round(sum(c["realizado_despues"] for c in cuentas), 2),
        "cuentas": cuentas, "errores": errores,
    }
