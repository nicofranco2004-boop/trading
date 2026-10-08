"""Plata que cambia de sub-cuenta dentro del MISMO broker: no es ganancia ni retiro.

PPI y Balanz tienen una sub-cuenta por moneda y por tipo de dólar (pesos, dólar
"CV 7.000"/MEP, dólar "CV 10.000"/cable). Cuando la plata pasa de una a otra
—para pagar una compra en cable, para unificar saldos, por una compensación de
monedas— el export lo muestra como DOS filas "Movimiento Manual": una que sale
de la sub-cuenta A y otra que entra en la B, por el mismo monto. En Rendi esas
sub-cuentas son el MISMO bolsillo (todos los dólares van al broker '· USD').

Los parsers leían cada fila por su signo: la que entra como INTERÉS (ganancia
realizada) y la que sale como COMISIÓN. Y la comisión ni siquiera compensaba: el
recálculo de la contabilidad (`_recalc_pnl_realized_from_ops`) arma los retiros
sólo con las filas RETIRO, así que la que salía desaparecía y la que entraba
quedaba como ganancia. Medido en la copia de producción del 2026-08-16: 622 pares
en 52 cuentas, US$ 324.000 de intereses que nadie cobró (uid 1078: US$ 58.600
sobre US$ 7.500 aportados). El efectivo, en cambio, cuadraba: +X y −X.

LA REGLA, para todos los formatos (este módulo corre en `pipeline.run_preview`
sobre la salida de CUALQUIER parser, incluido el genérico que arma la IA):

  · fila de movimiento interno CON su contraparte (mismo día, mismo broker,
    misma moneda, mismo monto, signo opuesto) → las DOS se descartan. Es la
    misma plata: no cambia el efectivo, ni el aportado, ni la ganancia.
  · fila de movimiento interno SIN contraparte → flujo de caja: la que entra es
    DEPÓSITO y la que sale RETIRO. Nunca interés ni comisión. Si la otra mitad
    no vino en el archivo, la plata sí entró (o salió) de lo que Rendi ve.

Medido sobre la misma copia: los 622 pares tienen contraparte (0 sueltos), y 621
son dólar contra dólar en el mismo broker.

Qué cuenta como movimiento interno sale de los exports reales (descripciones
vistas en la copia de producción, siempre con su par). Lo que NO está acá y
también empieza con "Movimiento Manual" es plata de verdad y se deja como venga:
acreencias de MatbaRofex, intereses corridos, notas de crédito por renta, premios
por canje, retenciones, gastos.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .normalizer import _coerce_op_type, _norm_currency, parse_date, parse_number
from .schema import (OP_DEPOSIT, OP_DIVIDEND, OP_FEE, OP_INTEREST, OP_TAX,
                     OP_WITHDRAW, RawRow)

# Sobre el texto normalizado (minúsculas, sin acentos, espacios simples).
_INTERNO = re.compile(
    r"^(?:"
    r"movimiento manual / (?:"
    r"rentas? cv\b"                                   # Renta CV 7.000 a Cable / Rentas CV … su conversión
    r"|conversion\b"                                  # Conversión CV 7.000 a CV 10.000 / a Dólar Cable / de Moneda
    r"|debito/credito - (?:compensacion de monedas|retiro ppi global|transferencia ppi global)"
    r"|canje de monedas\b"
    r"|unificacion saldos\b"
    r"|vencimiento plazo comunicacion\b"
    r"|nota de credito - acreditacion de dolar\b"
    r"|nota de debito - dolar\b"
    r")"
    r"|debito/credito de monedas\b"                   # PPI, sin el prefijo
    r")")

_ENTRA = {OP_INTEREST, OP_DIVIDEND, OP_DEPOSIT}
_SALE = {OP_FEE, OP_TAX, OP_WITHDRAW}


def _texto(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().lower()


def es_movimiento_interno(descripcion: Optional[str]) -> bool:
    """¿La descripción del broker dice que la plata sólo cambió de sub-cuenta?"""
    return bool(_INTERNO.match(_texto(descripcion)))


def _clave(d: Dict) -> Optional[Tuple[str, str, str, float]]:
    fecha = parse_date(str(d.get("fecha") or ""))
    monto = parse_number(d.get("monto") or d.get("monto_usd") or "")
    if not fecha or monto is None:
        return None
    return (fecha, _texto(d.get("broker")), _norm_currency(d.get("moneda")) or "",
            round(abs(monto), 2))


def neutralizar(raw_rows: List[RawRow]) -> List[RawRow]:
    """Las filas de un import, sin los movimientos internos apareados y con los
    sueltos pasados a depósito/retiro (ver el docstring del módulo)."""
    entra: Dict[tuple, List[int]] = defaultdict(list)
    sale: Dict[tuple, List[int]] = defaultdict(list)
    tipo: Dict[int, str] = {}
    for i, r in enumerate(raw_rows):
        d = r.data or {}
        if not es_movimiento_interno(d.get("notas")):
            continue
        op = _coerce_op_type(str(d.get("tipo") or ""))
        k = _clave(d)
        if k is None or (op not in _ENTRA and op not in _SALE):
            continue
        (entra if op in _ENTRA else sale)[k].append(i)
        tipo[i] = op
    descartar, a_flujo = set(), {}
    for k in set(entra) | set(sale):
        e, s = entra.get(k, []), sale.get(k, [])
        n = min(len(e), len(s))
        descartar.update(e[:n] + s[:n])
        for i in e[n:]:
            a_flujo[i] = "DEPOSITO"
        for i in s[n:]:
            a_flujo[i] = "RETIRO"
    out = []
    for i, r in enumerate(raw_rows):
        if i in descartar:
            continue
        if i in a_flujo:
            r = RawRow(row_index=r.row_index, data={**r.data, "tipo": a_flujo[i]})
        out.append(r)
    return out
