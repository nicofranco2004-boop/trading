"""El «Saldo anterior» de Bull Market: cuándo ya está contado.

Bull Market manda la historia partida en archivos por período, y cada uno abre
con el saldo que la cuenta traía de antes (`S.ANTERIOR`). El del período más
viejo es plata real; el de los siguientes es el cierre del anterior, que ya
está contado movimiento por movimiento. Cargarlo dos veces infla el efectivo y
el capital aportado.

Una sola regla para los tres lugares que lo deciden:
  - el layout Movimientos / Histórico (`bullmarket._parse_movimientos`) y el
    Histórico compacto por mail (`bullmarket._parse_historico_compacto`), con
    los demás archivos de la MISMA subida;
  - `pipeline.drop_saldo_anterior_ya_contado`, con lo importado en subidas
    ANTERIORES, en la vista previa y al confirmar con «Estado inicial» (que
    vuelve a leer las filas crudas del lote).
Hasta el 06/11/2026 eran copias distintas: el Histórico compacto tenía la suya,
el layout Movimientos ninguna, la de subidas anteriores comparaba con «<» en vez
de «≤», y confirmar con «Estado inicial» no pasaba por ninguna. Los mismos
archivos daban un efectivo distinto subidos juntos, de a uno o con «Estado
inicial».
"""
from __future__ import annotations

import re
from typing import Iterable, List, Set, Tuple

# Una fecha que el lector entendió: ISO, con o sin hora atrás.
_ES_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _dia(f) -> str:
    """La fecha como "AAAA-MM-DD", o "" si no se entiende. Acepta lo que viene
    de la base (en Postgres puede ser un objeto fecha, no un texto)."""
    s = str(f or "")[:10]
    return s if _ES_ISO.match(s) else ""


def ya_contado(fecha_saldo, fechas_movimientos: Iterable) -> bool:
    """¿Hay algún movimiento de ese día o de antes? El saldo es el de AL CIERRE
    de su día, así que un movimiento de ese mismo día ya está adentro.

    Sólo decide con fechas que se entienden: una que el lector no pudo leer
    queda como texto crudo, y «19/01/2023 10:00» comparado como texto con
    «2022-12-31» da «anterior» (auditoría del 06/11/2026: el saldo de un archivo
    subido SOLO se descartaba). Ante la duda, el saldo entra."""
    dia = _dia(fecha_saldo)
    if not dia:
        return False
    return any(d and d <= dia for d in (_dia(f) for f in fechas_movimientos))


def los_que_entran(saldos: List[Tuple[object, str, str, float]],
                   fechas_movimientos: List) -> Set:
    """De los saldos de UNA subida, `[(clave, fecha, moneda, monto)]`, las claves
    de los que entran. Uno entra si:
      1. ningún movimiento de la subida es de ese día o de antes (`ya_contado`), y
      2. no hay otro saldo de la misma moneda, con fecha ANTERIOR y el MISMO
         monto.

    La 2 cubre dos casos que sumaban el saldo dos veces (revisión independiente
    del 06/11/2026): un período viejo sin ningún movimiento, y un segundo archivo
    que arranca antes del primer movimiento del primero. Si la 1 no lo sacó, es
    que entre los dos saldos no hubo ningún movimiento: de la misma cuenta, el
    más nuevo tiene que ser IGUAL al más viejo, y entra el más viejo. Distintos
    son de cuentas distintas (dos comitentes subidos juntos) y entran los dos:
    «sólo el más viejo» a secas tiraba el de la segunda cuenta (2ª pasada de la
    revisión). Ante la duda, el saldo entra."""
    candidatos = [(c, _dia(f), m, float(monto or 0)) for c, f, m, monto in saldos
                  if not ya_contado(f, fechas_movimientos)]
    return {c for c, dia, m, monto in candidatos
            if not (dia and any(m2 == m and d2 and d2 < dia and abs(monto2 - monto) < 0.005
                                for _c2, d2, m2, monto2 in candidatos))}
