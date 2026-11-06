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
    ANTERIORES.
Hasta el 06/11/2026 eran tres copias distintas: el Histórico compacto tenía la
suya, el layout Movimientos ninguna, y la de subidas anteriores comparaba con
«<» en vez de «≤». Los mismos archivos daban un efectivo distinto subidos juntos
o de a uno.
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


def los_que_entran(saldos: List[Tuple[object, str, str]],
                   fechas_movimientos: List) -> Set:
    """De los saldos de UNA subida, `[(clave, fecha, moneda)]`, las claves de los
    que entran. Uno entra si:
      1. ningún movimiento de la subida es de ese día o de antes (`ya_contado`), y
      2. no hay otro saldo de la misma moneda con fecha ANTERIOR: ese otro abre un
         período más viejo, y todo lo que pasó entre los dos ya está contado.

    Sin la segunda, dos casos sumaban el saldo dos veces (revisión independiente
    del 06/11/2026): un período viejo sin ningún movimiento, y un segundo archivo
    que arranca antes del primer movimiento del primero. Si falta un período en
    el medio, la segunda no empeora nada: la primera ya lo descartaba.

    Dos saldos del mismo día y la misma moneda entran los dos: si fueran de la
    misma cuenta serían la misma línea, y el filtro entre archivos ya habría
    dejado uno solo; distintos, son de cuentas distintas."""
    candidatos = [(c, _dia(f), m) for c, f, m in saldos
                  if not ya_contado(f, fechas_movimientos)]
    return {c for c, dia, m in candidatos
            if not (dia and any(m2 == m and d2 and d2 < dia for _c2, d2, m2 in candidatos))}
