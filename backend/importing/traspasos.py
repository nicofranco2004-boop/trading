"""Traspaso de títulos entre dos brokers del MISMO usuario.

Cuando alguien mueve papeles de un broker a otro (no plata: los títulos), el
broker que los RECIBE lo declara —Balanz lo manda como "Transferencia Externa
(Crédito)"— pero el que los ENTREGA muchas veces no. El export de Bull Market,
por ejemplo, es el libro de CAJA: un traspaso no mueve plata, así que no hay
ninguna fila que saque los títulos. Lo único que queda es lo que costó el
trámite ("GTOS. TRANS. TITULOS").

Resultado sin esto: las compras del broker viejo quedan abiertas para siempre y
el mismo papel figura en los DOS brokers a la vez — doble tenencia y doble
capital aportado. Medido en una cuenta real: 9 títulos duplicados y $8.493.784
de "aporte" que en realidad eran los papeles que trajo.

Lo que hace este módulo: mirar las ENTRADAS por traspaso de un import y, si el
broker de origen también está cargado en Rendi, generar los movimientos que
cierran su posición. Se generan como filas SINTÉTICAS del mismo lote, así que
el confirm las aplica y el revert las deshace sin código extra.

Se cierra AL VALOR DEL PASE (no a costo): el tramo viejo realiza su resultado en
el broker de origen y el nuevo arranca desde ese valor, así los dos tramos suman
el rendimiento completo. Y el RETIRO del origen netea contra el DEPOSITO que ya
emite el destino → el capital aportado no se cuenta dos veces. (Cuando el origen
NO está en Rendi no hay nada que emparejar y la salida cierra a costo con
`transfer_out`, que es otro camino.)

⚠️ Tres frenos, porque el error grave sería cerrarle una posición que SÍ tiene:
  1. hace falta una SEÑAL DE SALIDA en el broker de origen, ese mismo día;
  2. se cierra el MÍNIMO entre lo abierto y lo que entró;
  3. nada se aplica solo: las filas van con `[requiere-aprobacion]`.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .schema import NormalizedTx, OP_BUY, OP_SELL, OP_WITHDRAW
from .tenencia import MARCA_APROBACION
from .persister import broker_pair

# Rango propio de row_index sintético. La foto de tenencia usa -20000-i; estos
# van más abajo para que nunca colisionen (el confirm/revert mapean por índice).
_BASE_ROW_INDEX = -30000

# Cómo dice cada broker "de acá salieron títulos". Bull Market sólo deja el
# GASTO del trámite ("GTOS. TRANS. TITULOS"), que es la única marca de que ese
# día hubo un traspaso.
#
# ⚠️ Pide las DOS cosas: el texto Y que la fila sea una COMISIÓN. Un patrón de
# texto solo también matchea "TRANSFERENCIA DE TITULOS RECIBIDOS", que es una
# ENTRADA — y tomar una entrada por salida es el error grave de todo esto: le
# cerraría al usuario una posición que sí tiene. Un gasto de traspaso siempre se
# importa como comisión; una entrada de títulos, nunca.
# Sólo la forma que aparece en un export REAL. Había acá una segunda alternativa
# genérica ("TRANSFERENCIA DE TITULOS") que no salía de ningún archivo: la
# inventé "por las dudas" y matcheaba "TRANSFERENCIA DE TITULOS RECIBIDOS", que
# es una ENTRADA. Adivinar de más, justo en la condición que dispara el error
# grave, es peor que quedarse corto: si aparece otra forma, no se detecta el
# traspaso y todo sigue como hoy.
_SENAL_SALIDA = re.compile(r"(GTOS|GASTOS)\.?\s+TRANS", re.I)
_SENAL_OPS = ("FEE",)

# Prefijo con el que se firma cada cierre generado acá. Sirve para dos cosas:
# que el usuario lea el motivo, y que se pueda reconocer un cierre YA APLICADO
# para no repetirlo (ver `traspasos_ya_cerrados`).
MARCA_TRASPASO = "Traspaso a "


def destino_de(notes: Optional[str]) -> str:
    """El broker al que se fueron los títulos, sacado de la nota del cierre. Lo
    usa la pantalla para explicar POR QUÉ se cierra esa posición."""
    txt = notes or ""
    if MARCA_TRASPASO not in txt:
        return ""
    return txt.split(MARCA_TRASPASO, 1)[1].split(" el ", 1)[0].strip()


def _norm(s: Optional[str]) -> str:
    return (s or "").upper().replace("Í", "I").replace("Ó", "O")


def senales_de_salida(conn, uid: int) -> set:
    """{(broker, fecha)} donde el broker registró que salieron títulos.

    Es el freno principal: tener el mismo papel en dos brokers es de lo más
    normal, y sin esta señal no se toca nada."""
    out = set()
    for r in conn.execute(
        """SELECT DISTINCT n.broker, n.date, n.notes
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ? AND b.status = 'confirmed'
              AND COALESCE(n.notes, '') <> '' AND n.operation_type IN ('FEE')""",
        (uid,),
    ).fetchall():
        if _SENAL_SALIDA.search(_norm(r["notes"])):
            out.add((r["broker"], (r["date"] or "")[:10]))
    return out


def senales_del_lote(txs: List[NormalizedTx]) -> set:
    """{(broker, fecha)} con señal de salida dentro de ESTE lote. Es lo que
    permite reconocer el traspaso cuando el broker que entrega se importa
    después: su gasto de transferencia viene en el archivo que se está subiendo,
    no en la base."""
    return {(t.broker, (t.date or "")[:10]) for t in txs
            if t.broker and t.operation_type in _SENAL_OPS
            and _SENAL_SALIDA.search(_norm(t.notes))}


def traspasos_ya_cerrados(conn, uid: int) -> set:
    """{(broker, activo, fecha)} de los cierres por traspaso que YA se aplicaron.

    Sin esto el cruce no es idempotente: re-importar el archivo del broker de
    origen vuelve a proponer los mismos cierres y descuenta DE NUEVO lo que ya
    se había cerrado. Medido con un archivo real: Bull Market bajaba de 11
    posiciones a 9 en la segunda importación del mismo archivo."""
    return {(r["broker"], r["asset_symbol"], (r["date"] or "")[:10])
            for r in conn.execute(
                """SELECT n.broker, n.asset_symbol, n.date
                     FROM import_normalized_tx n
                     JOIN import_batches b ON b.id = n.batch_id
                    WHERE b.user_id = ? AND b.status = 'confirmed'
                      AND n.operation_type = 'SELL'
                      AND COALESCE(n.notes, '') LIKE ?""",
                (uid, f"%{MARCA_TRASPASO}%")).fetchall()
            if r["asset_symbol"]}


def entradas_ya_confirmadas(conn, uid: int, brokers_del_lote: set) -> List[dict]:
    """Entradas por traspaso que ya están importadas y confirmadas, de brokers
    DISTINTOS a los de este lote.

    Es la mitad que falta cuando el usuario importa primero el broker que RECIBE
    y después el que ENTREGA — el orden más natural, porque el broker nuevo es
    el que está usando. En ese caso la entrada no viene en el lote actual: ya
    está en la base."""
    filas = conn.execute(
        """SELECT n.broker, n.date, n.asset_symbol, n.quantity, n.gross_amount,
                  n.currency
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ? AND b.status = 'confirmed'
              AND n.transfer_in = 1 AND COALESCE(n.asset_symbol, '') <> ''
              AND COALESCE(n.quantity, 0) > 0""",
        (uid,),
    ).fetchall()
    return [dict(r) for r in filas if r["broker"] not in brokers_del_lote]


def _posiciones_que_deja_el_lote(txs: List[NormalizedTx]) -> Dict[Tuple[str, str], float]:
    """Lo que va a quedar abierto cuando este lote se confirme, por (broker,
    activo). Se usa para el sentido inverso: las posiciones del broker que
    ENTREGA todavía no existen en `positions` — las está creando este import."""
    out: Dict[Tuple[str, str], float] = {}
    for t in txs:
        if not t.asset_symbol or not t.quantity:
            continue
        if t.operation_type not in (OP_SELL, OP_BUY):
            continue
        k = (t.broker, t.asset_symbol)
        signo = -1 if t.operation_type == OP_SELL else 1
        out[k] = out.get(k, 0.0) + signo * float(t.quantity)
    return {k: v for k, v in out.items() if v > 0}


def cerrar_origen_de_traspasos(
    conn, uid: int, txs: List[NormalizedTx],
    existing_positions: Dict[Tuple[str, str], float],
) -> List[NormalizedTx]:
    """Movimientos que cierran el broker de ORIGEN de cada traspaso detectado.

    `txs` son las filas válidas del import (las del broker que RECIBE) y
    `existing_positions` es {(broker, activo): cantidad} de lo que el usuario ya
    tiene. Devuelve filas nuevas para AGREGAR al lote; lista vacía si no hay
    nada que cruzar (el caso normal)."""
    # ── Las dos direcciones ──────────────────────────────────────────────
    # El usuario puede importar los brokers en cualquier orden, y el traspaso
    # hay que reconocerlo igual:
    #   A. importa el que ENTREGA y después el que RECIBE → la entrada viene en
    #      este lote y la posición a cerrar ya está en `positions`.
    #   B. importa el que RECIBE y después el que ENTREGA (el orden natural: el
    #      broker nuevo es el que está usando) → la entrada está en un lote YA
    #      CONFIRMADO, y la posición a cerrar todavía NO EXISTE: la va a crear
    #      este mismo import.
    brokers_lote = {t.broker for t in txs if t.broker}
    entradas: List[dict] = [
        {"broker": t.broker, "date": t.date, "asset_symbol": t.asset_symbol,
         "quantity": float(t.quantity), "gross_amount": float(t.gross_amount or 0),
         "currency": t.currency}
        for t in txs
        if getattr(t, "transfer_in", False) and t.asset_symbol and (t.quantity or 0) > 0
    ]
    entradas += entradas_ya_confirmadas(conn, uid, brokers_lote)
    if not entradas:
        return []

    # La señal de salida puede estar en la base (caso A) o venir en este mismo
    # lote (caso B: el gasto de transferencia de Bull Market).
    salidas = senales_de_salida(conn, uid) | senales_del_lote(txs)
    if not salidas:
        return []

    # (broker, activo) → cuánto queda por cerrar. UNA sola bolsa para las dos
    # direcciones: lo que ya está en la base más lo que este lote va a abrir. Se
    # descuenta a medida que se usa, así dos entradas del mismo papel no cierran
    # la misma posición dos veces.
    disponible = {k: v for k, v in existing_positions.items() if v > 0}
    for k, v in _posiciones_que_deja_el_lote(txs).items():
        disponible[k] = disponible.get(k, 0.0) + v

    # Grupo de brokers de cada destino: el padre MÁS su sibling "· USD". Los dos
    # son EL MISMO broker partido por moneda, así que una entrada a "Balanz" no
    # puede cerrar la posición de "Balanz · USD" — sería cerrarle tenencia real
    # en su propia cuenta. Se cachea: `broker_pair` va a la base.
    _grupo: Dict[str, set] = {}
    def grupo_de(nombre: str) -> set:
        if nombre not in _grupo:
            _grupo[nombre] = set(broker_pair(conn, uid, nombre))
        return _grupo[nombre]
    ya_cerrados = traspasos_ya_cerrados(conn, uid)
    nuevas: List[NormalizedTx] = []

    for e in sorted(entradas, key=lambda d: (d["date"] or "", d["asset_symbol"] or "")):
        fecha = (e["date"] or "")[:10]
        for (broker, activo), abierto in sorted(disponible.items()):
            if (activo != e["asset_symbol"] or abierto <= 0
                    or broker in grupo_de(e["broker"])):
                continue
            if (broker, fecha) not in salidas:
                continue          # sin señal de salida no se toca nada
            if (broker, activo, fecha) in ya_cerrados:
                continue          # este traspaso ya se cerró: no se repite

            # El MÍNIMO de los dos. Cerrar de más le borra tenencia real; cerrar
            # de menos lo deja como está hoy. Y resuelve solo el cambio de ratio
            # (un CEDEAR puede entrar 84 donde salieron 28).
            cierra = min(abierto, float(e["quantity"]))
            if cierra <= 0:
                continue
            valor = float(e["gross_amount"] or 0) * cierra / float(e["quantity"])
            precio = (valor / cierra) if cierra else 0.0
            idx = _BASE_ROW_INDEX - len(nuevas)
            nota = (f"{MARCA_APROBACION} {MARCA_TRASPASO}{e['broker']} el {fecha} "
                    f"— se cierra la posición acá para no contarla dos veces")

            nuevas.append(NormalizedTx(
                row_index=idx, date=e["date"], broker=broker,
                operation_type=OP_SELL, asset_symbol=activo,
                quantity=cierra, unit_price=round(precio, 8),
                gross_amount=round(valor, 4), currency=e["currency"], notes=nota,
            ))
            # El RETIRO espeja el DEPOSITO que el destino ya emite por la
            # entrada: el capital aportado baja acá lo mismo que sube allá, y la
            # caja del origen no se mueve (la venta acredita, el retiro debita).
            nuevas.append(NormalizedTx(
                row_index=idx - 1, date=e["date"], broker=broker,
                operation_type=OP_WITHDRAW, gross_amount=round(valor, 4),
                currency=e["currency"],
                # ⚠️ LLEVA `asset_symbol` aunque sea un movimiento de CAJA: la
                # aprobación se pide POR TICKER, y una fila sin ticker nunca
                # queda aprobada. Sin esto se aplicaba la venta y NO el retiro
                # que la acompaña → el capital aportado no bajaba en el origen y
                # quedaba contado dos veces, que es justo lo que esto arregla.
                asset_symbol=activo,
                notes=f"{MARCA_APROBACION} {MARCA_TRASPASO}{e['broker']} el {fecha} "
                      f"— el valor se fue con los títulos",
            ))
            disponible[(broker, activo)] = abierto - cierra
            break                 # una entrada cierra un solo broker de origen

    # Re-numerar para que los índices sean únicos y consecutivos.
    for i, t in enumerate(nuevas):
        t.row_index = _BASE_ROW_INDEX - i
    return nuevas
