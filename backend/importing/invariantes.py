"""Chequeos de INVARIANTES sobre los datos ya escritos, después de un import.

POR QUÉ ESTO Y NO UN VIGILANTE DE ERRORES
-----------------------------------------
Los tres bugs reales que aparecieron el 03/09/2026 —el broker de Balanz naciendo
en dólares, el CEDEAR tratado como bono, el '150.000' leído como 150— tenían algo
en común: **el import terminó sin un solo error**. Un bot que mira el log de
errores no caza ninguno de los tres. La familia que más duele es justamente
"salió limpio, con el número equivocado".

Lo que sí los cazó fue preguntarle a los DATOS si se contradicen. Por eso esto no
adivina nada ni tiene umbrales: cada chequeo es una afirmación que o se cumple o
no. Esa es la regla de diseño y el motivo por el que se puede confiar en el
resultado — un chequeo con falsos positivos deja de mirarse a la semana.

CÓMO AGREGAR UNO
----------------
Sumá una función `_check_*(conn, uid)` que devuelva List[Violacion] y agregala a
CHEQUEOS. Si el chequeo puede marcar algo legítimo, va con severidad "aviso", no
"error". Ante la duda: aviso.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Monedas que representan 1 dólar. `brokers.currency` usa las dos: 'USD' para
# brokers tradicionales y 'USDT' para exchanges cripto (ver BrokerIn).
_DOLAR = ("USD", "USDT")


class Violacion(dict):
    """Una violación concreta, con lo necesario para ir a arreglarla."""

    def __init__(self, *, chequeo: str, severidad: str, user_id: Optional[int],
                 que_pasa: str, detalle: Dict[str, Any]):
        super().__init__(chequeo=chequeo, severidad=severidad, user_id=user_id,
                         que_pasa=que_pasa, detalle=detalle)


def _rows(conn, sql: str, params=()) -> List[Any]:
    return conn.execute(sql, params).fetchall()


def _scope(uid: Optional[int], col: str = "p.user_id"):
    """Filtro opcional por usuario. Sin uid, corre sobre toda la base."""
    return (f" AND {col}=?", (uid,)) if uid is not None else ("", ())


# ─────────────────────────────────────────────────────────────────────────────
# 1. La moneda de la posición contra la de su broker
# ─────────────────────────────────────────────────────────────────────────────
def check_moneda_posicion_vs_broker(conn, uid: Optional[int] = None) -> List[Violacion]:
    """Una posición EN PESOS no puede vivir en un broker marcado en dólares.

    Este es EL chequeo que habría cazado el bug reportado el primer día: el
    export de Balanz que el wizard recomienda no anclaba la moneda del broker
    (su format_id no estaba en FORMAT_BASE_CURRENCY), así que el broker se
    auto-creaba en USD y los pesos del usuario quedaban adentro. Medido antes del
    fix: 505 posiciones de ~20 usuarios.

    Al revés (una posición en dólares dentro de un broker ARS) NO es un error:
    el modelo admite same-broker dual-currency y hay lotes viejos con la moneda
    en NULL. Va como aviso.
    """
    filtro, params = _scope(uid)
    out = []
    for r in _rows(conn, f"""
        SELECT p.id, p.user_id, p.broker, p.asset, p.currency pc, b.currency bc, p.quantity
          FROM positions p JOIN brokers b ON b.user_id=p.user_id AND b.name=p.broker
         WHERE p.is_cash=0 AND COALESCE(p.quantity,0)>0
           AND UPPER(COALESCE(p.currency,''))='ARS'
           AND UPPER(COALESCE(b.currency,'')) IN ('USD','USDT'){filtro}""", params):
        out.append(Violacion(
            chequeo="moneda_posicion_vs_broker", severidad="error", user_id=r["user_id"],
            que_pasa=(f"'{r['asset']}' está en PESOS pero su broker '{r['broker']}' está "
                      f"marcado en {r['bc']}. La valuación, el cost basis y el gate de "
                      f"splits lo van a tratar como si fuera un activo en dólares."),
            detalle={"position_id": r["id"], "broker": r["broker"], "asset": r["asset"],
                     "moneda_posicion": r["pc"], "moneda_broker": r["bc"]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. Posiciones cuyo broker no existe
# ─────────────────────────────────────────────────────────────────────────────
def check_broker_inexistente(conn, uid: Optional[int] = None) -> List[Violacion]:
    """Los brokers se linkean por NOMBRE, no por foreign key.

    Si la fila de `brokers` no está, todo lo que consulte la moneda del broker
    cae a un default. En el persister ese default es 'USDT'
    (`broker_currency = br["currency"] if br else "USDT"`), o sea que una cuenta
    en pesos se interpreta entera en dólares.
    """
    filtro, params = _scope(uid)
    out = []
    for r in _rows(conn, f"""
        SELECT p.id, p.user_id, p.broker, COUNT(*) n
          FROM positions p
          LEFT JOIN brokers b ON b.user_id=p.user_id AND b.name=p.broker
         WHERE b.id IS NULL AND COALESCE(p.quantity,0)>0{filtro}
         GROUP BY p.user_id, p.broker""", params):
        out.append(Violacion(
            chequeo="broker_inexistente", severidad="error", user_id=r["user_id"],
            que_pasa=(f"{r['n']} posición(es) apuntan al broker '{r['broker']}', que no "
                      f"existe en la tabla `brokers`. Sin esa fila la moneda cae al "
                      f"default 'USDT' y la cuenta se lee en dólares."),
            detalle={"broker": r["broker"], "posiciones": r["n"]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Costo no positivo con tenencia positiva
# ─────────────────────────────────────────────────────────────────────────────
def check_costo_no_positivo(conn, uid: Optional[int] = None) -> List[Violacion]:
    """Tener el activo y no haber puesto plata es imposible.

    Un `invested` en cero o negativo hace que el P&L de esa fila sea el valor de
    mercado ENTERO (o más), y el rendimiento de la cuenta se dispara. Es el modo
    de falla de "capital negativo" y el que produce un COMPRA con monto negativo
    en el CSV genérico.
    """
    filtro, params = _scope(uid)
    out = []
    for r in _rows(conn, f"""
        SELECT p.id, p.user_id, p.broker, p.asset, p.invested, p.quantity
          FROM positions p
         WHERE p.is_cash=0 AND COALESCE(p.quantity,0)>0
           AND COALESCE(p.invested,0)<=0{filtro}""", params):
        out.append(Violacion(
            chequeo="costo_no_positivo", severidad="error", user_id=r["user_id"],
            que_pasa=(f"'{r['asset']}' en '{r['broker']}' tiene {r['quantity']} unidades "
                      f"con un costo de {r['invested']}. El P&L de esa fila va a ser el "
                      f"valor de mercado entero."),
            detalle={"position_id": r["id"], "broker": r["broker"], "asset": r["asset"],
                     "invested": r["invested"], "quantity": r["quantity"]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 4. El sub-broker dólar y su padre
# ─────────────────────────────────────────────────────────────────────────────
def check_subbroker_usd_bien_formado(conn, uid: Optional[int] = None) -> List[Violacion]:
    """Un '<Padre> · USD' tiene que colgar de su padre y estar en dólares.

    El ruteo ARS/USD del import escribe en la pata que encuentra por
    `parent_broker_id`. Un sibling suelto (sin padre) o marcado en pesos rompe
    el ruteo en silencio: las compras en dólares vuelven a caer en el padre.
    """
    filtro, params = _scope(uid, "b.user_id")
    out = []
    for r in _rows(conn, f"""
        SELECT b.id, b.user_id, b.name, b.currency, b.parent_broker_id
          FROM brokers b
         WHERE b.name LIKE '%· USD'{filtro}""", params):
        problemas = []
        if r["parent_broker_id"] is None:
            problemas.append("no cuelga de ningún broker padre")
        if (r["currency"] or "").upper() not in _DOLAR:
            problemas.append(f"está marcado en {r['currency']} en vez de USD/USDT")
        if problemas:
            out.append(Violacion(
                chequeo="subbroker_usd_bien_formado", severidad="error", user_id=r["user_id"],
                que_pasa=f"El sub-broker '{r['name']}' {' y '.join(problemas)}.",
                detalle={"broker_id": r["id"], "broker": r["name"],
                         "currency": r["currency"], "parent_broker_id": r["parent_broker_id"]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cash con moneda que no es la de su broker
# ─────────────────────────────────────────────────────────────────────────────
def check_cash_moneda(conn, uid: Optional[int] = None) -> List[Violacion]:
    """El efectivo de un broker dólar no puede ser pesos, ni al revés.

    A diferencia de los activos —donde un broker ARS puede tener tenencias en
    dólares— la caja SÍ vive separada por pata: por eso existe el sibling. Un
    cash cruzado es plata contada en la moneda equivocada.
    """
    filtro, params = _scope(uid)
    out = []
    for r in _rows(conn, f"""
        SELECT p.id, p.user_id, p.broker, p.asset, b.currency bc
          FROM positions p JOIN brokers b ON b.user_id=p.user_id AND b.name=p.broker
         WHERE p.is_cash=1 AND UPPER(COALESCE(p.asset,'')) IN ('ARS','USD','USDT')
           AND ((UPPER(p.asset)='ARS' AND UPPER(COALESCE(b.currency,'')) IN ('USD','USDT'))
             OR (UPPER(p.asset) IN ('USD','USDT') AND UPPER(COALESCE(b.currency,''))='ARS'))
           AND ABS(COALESCE(p.quantity,0))>0.005{filtro}""", params):
        out.append(Violacion(
            chequeo="cash_moneda", severidad="aviso", user_id=r["user_id"],
            que_pasa=(f"El broker '{r['broker']}' está en {r['bc']} pero tiene caja en "
                      f"{r['asset']}. Si no hay un sub-broker para esa pata, esa plata "
                      f"se está sumando en la moneda equivocada."),
            detalle={"position_id": r["id"], "broker": r["broker"],
                     "cash": r["asset"], "moneda_broker": r["bc"]}))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 6. La caja contra el resumen del broker
# ─────────────────────────────────────────────────────────────────────────────
def check_caja_concilia(conn, uid: Optional[int] = None,
                        piso_ars: float = 50_000.0,
                        piso_usd: float = 50.0) -> List[Violacion]:
    """Cuánto tuvo que corregir la foto el efectivo que calcularon los movimientos.

    Cuando entra una foto de tenencia, el sistema compara el efectivo que
    reconstruyó desde los movimientos contra el saldo que declara el resumen del
    broker, y ajusta al valor de la foto con un DEPOSITO/RETIRO sintético
    (`build_cash_trueup_txs`). Ese ajuste ES la discrepancia, y queda en la base.
    Hasta ahora sólo se escribía en un log —el comentario del código dice
    textualmente "para detección interna de bugs del parser"— y nadie lo leía.

    POR QUÉ ESTO IMPORTA MÁS QUE VIGILAR ERRORES: una fila que el parser descarta
    en silencio no deja ningún error, pero SÍ deja rastro acá, porque la plata no
    aparece. Este chequeo caza pérdida silenciosa de filas sin importar la causa
    —tipo de operación nuevo, export cambiado, `continue` pelado, signo dado
    vuelta— y sin necesidad de saber de antemano qué buscar.

    VA COMO AVISO, NO COMO ERROR, y es a propósito: un ajuste grande también se
    explica si el usuario subió un rango de fechas parcial (los movimientos
    arrancan después de que abrió la cuenta). Con los datos que hay no se puede
    separar ese caso de un bug del parser, y un "error" con falsos positivos deja
    de mirarse a la semana. Es una lista para revisar, ordenada por monto: arriba
    de todo es donde viven los bugs.

    Medido en la base: 215 ajustes de 129 usuarios en cuentas que SÍ tienen
    movimientos, con un ajuste promedio de ARS 1,28 M.
    """
    filtro, params = _scope(uid, "b.user_id")
    try:
        filas = _rows(conn, f"""
            SELECT b.user_id, n.broker, n.currency, n.gross_amount amt, b.id bid
              FROM import_normalized_tx n
              JOIN import_batches b ON b.id = n.batch_id
             WHERE n.notes LIKE 'Ajuste de cash a Estado de Cuenta%'
               AND b.status='confirmed'{filtro}
             ORDER BY n.gross_amount DESC""", params)
    except Exception:
        return []      # base sin tablas de import (tests de otras áreas)
    out = []
    for r in filas:
        ccy = (r["currency"] or "").upper()
        piso = piso_ars if ccy == "ARS" else piso_usd
        amt = float(r["amt"] or 0)
        if amt < piso:
            continue
        # ¿La cuenta tiene movimientos propios, o el usuario subió sólo la foto?
        # Sin movimientos NO hay nada que conciliar y el ajuste es esperable.
        movs = conn.execute("""
            SELECT COUNT(*) c FROM import_normalized_tx m
              JOIN import_batches mb ON mb.id = m.batch_id
             WHERE mb.user_id=? AND mb.status='confirmed' AND mb.id<>?
               AND m.broker=?
               AND COALESCE(m.notes,'') NOT LIKE 'Tenencia%'
               AND COALESCE(m.notes,'') NOT LIKE 'Ajuste de cash%'""",
            (r["user_id"], r["bid"], r["broker"])).fetchone()["c"]
        if not movs:
            continue
        out.append(Violacion(
            chequeo="caja_concilia", severidad="aviso", user_id=r["user_id"],
            que_pasa=(f"En '{r['broker']}' la foto tuvo que corregir el efectivo en "
                      f"{ccy} {amt:,.2f}. Los movimientos reconstruyeron un saldo y el "
                      f"resumen del broker decía otro. Puede ser una fila que el parser "
                      f"perdió en silencio, o que el rango de fechas subido no cubra "
                      f"toda la vida de la cuenta — hay que mirarlo."),
            detalle={"broker": r["broker"], "currency": ccy,
                     "ajuste": round(amt, 2), "movimientos_en_la_cuenta": movs}))
    return out


CHEQUEOS = (
    check_moneda_posicion_vs_broker,
    check_broker_inexistente,
    check_costo_no_positivo,
    check_subbroker_usd_bien_formado,
    check_cash_moneda,
    check_caja_concilia,
)


def correr(conn, uid: Optional[int] = None, limite_por_chequeo: int = 200) -> Dict[str, Any]:
    """Corre todos los chequeos. SOLO LECTURA — no escribe nada.

    Con `uid` mira una cuenta (el uso después de un import). Sin `uid`, toda la
    base (el uso de admin, para ver si algo se está filtrando).
    """
    muestra, por_chequeo, rotos = [], {}, {}
    n_err = n_avi = 0
    usuarios = set()
    truncados = {}
    for fn in CHEQUEOS:
        try:
            v = fn(conn, uid)
        except Exception as e:                      # un chequeo roto no puede
            rotos[fn.__name__] = f"{type(e).__name__}: {e}"   # tumbar a los demás
            por_chequeo[fn.__name__] = None
            continue
        por_chequeo[fn.__name__] = len(v)
        # Los totales se cuentan sobre TODO, no sobre la muestra. Un tope que
        # además achica el número reportado hace leer "409 problemas" donde hay
        # 1.271, y eso es peor que no tener el chequeo.
        n_err += sum(1 for x in v if x["severidad"] == "error")
        n_avi += sum(1 for x in v if x["severidad"] != "error")
        usuarios.update(x["user_id"] for x in v if x["user_id"])
        if len(v) > limite_por_chequeo:
            truncados[fn.__name__] = len(v) - limite_por_chequeo
        muestra.extend(v[:limite_por_chequeo])
    return {
        "ok": n_err == 0 and not rotos,
        "errores": n_err,
        "avisos": n_avi,
        "usuarios_afectados": len(usuarios),
        "por_chequeo": por_chequeo,
        "chequeos_rotos": rotos,
        "violaciones": muestra,
        "no_listadas": truncados,
        "nota": (f"`violaciones` trae hasta {limite_por_chequeo} por chequeo; "
                 f"`errores`/`avisos` cuentan TODO." if truncados else None),
    }
