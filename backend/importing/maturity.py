"""Cierre de posiciones de LETRAS/LECAPs al vencer (post-import).

Problema
────────
Las Letras/LECAPs del Tesoro son zero-coupon: se compran y al vencimiento el
broker las rescata por su valor de capitalización. En Cocos ese rescate llega
como "Renta Y Amortizacion" / "...en especie" (cash) SIN una venta explícita del
papel. El parser ya toma ese cash como ingreso (DIVIDENDO), pero la posición de
la letra quedaría ABIERTA para siempre → tenencia FANTASMA de millones de
unidades de una letra que ya no existe (ej. S31O5 12,1M, T17O5 4,3M…).

Solución
────────
Después del import, cerramos las posiciones de letras cuyo vencimiento ya pasó
DENTRO de la ventana de datos importada (la fecha de la última transacción del
usuario). El cash del rescate ya entró por el dividendo, así que cerrar el papel
deja la cartera correcta: total = cash_rescatado − costo (que se va con el papel).

La fecha de vencimiento se decodifica del ticker estándar argentino, donde el
símbolo es [letra][día][código-mes][dígito-año]:
    S31O5 → 31/oct/2025 · T17O5 → 17/oct/2025 · S14F5 → 14/feb/2025
Los CEDEARs/acciones/bonos largos (AL30, GGAL, T2X5, COCORMA…) NO matchean el
patrón, así que nunca se tocan.

Para letras que Cocos exporta SIN ticker entre paréntesis ("LT REP ARGENTINA
CAP V11/11/24 $ CG"), el parser sintetiza un ticker decodable desde la fecha del
nombre (synth_letra_ticker) — así no se mergean en un activo vacío y el sweep
las puede cerrar igual.

Seguridad
─────────
Solo cierra posiciones creadas por imports (vinculadas en import_op_links).
Cualquier posición manual / no vinculada se saltea intacta. NO toca cash (ya
entró por el dividendo del rescate) ni monthly_entries.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Código de mes de los tickers de letras AR (la inicial del mes, con desempate:
# Marzo=M, Mayo=Y; Junio=J, Julio=L).
_MONTH_CODE = {
    "E": 1, "F": 2, "M": 3, "A": 4, "Y": 5, "J": 6,
    "L": 7, "G": 8, "S": 9, "O": 10, "N": 11, "D": 12,
}
_CODE_BY_MONTH = {v: k for k, v in _MONTH_CODE.items()}

# Símbolo de letra/LECAP: una letra inicial + día (1-2 díg) + código-mes + año (1 díg).
_LETRA_RX = re.compile(r"^([A-Z])(\d{1,2})([EFMAYJLGSOND])(\d)$")

# Fecha de vencimiento en el NOMBRE del instrumento. Dos regex:
#  - con prefijo "V"/"V." ("V11/11/24", "V.14/02/25") = marca explícita de venc.
#  - suelta ("14/02/25") como fallback cuando el nombre no usa "V".
# day/month/year (year de 2 o 4 dígitos).
_VENC_DATE_RX = re.compile(r"V\.?\s?(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_BARE_DATE_RX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")

# Palabras que delatan una letra/bono corto del Tesoro (para el fallback del parser).
_BOND_NAME_HINTS = ("letra", "lt rep", "lete", "lecap", "bono tesoro", "bono del tesoro",
                    "bonte", "boncap", "bono tesoro naci")


def letra_maturity(symbol: Optional[str]) -> Optional[str]:
    """Decodifica el vencimiento (ISO 'YYYY-MM-DD') de un ticker de letra/LECAP
    estándar argentino. None si el símbolo no es una letra.

    >>> letra_maturity('S31O5')   # 31/octubre/2025
    '2025-10-31'
    >>> letra_maturity('T17O5')
    '2025-10-17'
    >>> letra_maturity('GGAL') is None
    True
    """
    if not symbol:
        return None
    m = _LETRA_RX.match(symbol.strip().upper())
    if not m:
        return None
    _prefix, dd, mcode, yy = m.groups()
    month = _MONTH_CODE.get(mcode)
    if not month:
        return None
    try:
        d = date(2020 + int(yy), month, int(dd))
    except ValueError:
        return None  # día inválido para el mes (ej. 31 de febrero) → no es letra válida
    return d.isoformat()


def maturity_from_name(name: Optional[str]) -> Optional[str]:
    """Extrae el vencimiento (ISO) de la fecha embebida en el nombre de un bono/
    letra ("LT REP ARGENTINA CAP V11/11/24 $ CG" → '2024-11-11'). None si no hay.

    Como el sweep BORRA posiciones, somos cuidadosos para no cerrar por una fecha
    que NO sea el vencimiento (ej. una fecha de emisión/amortización en el nombre):
      1. Preferimos fechas con prefijo "V"/"V." (la marca explícita de vencimiento
         en los nombres AR), y de ésas la ÚLTIMA.
      2. Si no hay ninguna con "V", caemos a la ÚLTIMA fecha suelta del nombre
         (el vencimiento suele ir al final; ej. "LETRAS DEL TESORO CAP $ 14/02/25").
    """
    if not name:
        return None
    v_matches = _VENC_DATE_RX.findall(name)          # con prefijo V — explícitas
    matches = v_matches or _BARE_DATE_RX.findall(name)
    if not matches:
        return None
    dd, mm, yy = matches[-1]
    year = int(yy)
    if year < 100:
        year += 2000
    try:
        return date(year, int(mm), int(dd)).isoformat()
    except ValueError:
        return None


def is_bond_like_name(name: Optional[str]) -> bool:
    """True si el nombre del instrumento parece una letra/LECAP/bono corto del
    Tesoro (para decidir si sintetizar un ticker cuando no trae paréntesis)."""
    if not name:
        return False
    low = name.lower()
    return any(h in low for h in _BOND_NAME_HINTS)


def synth_letra_ticker(maturity_iso: str) -> Optional[str]:
    """Arma un ticker SINTÉTICO decodable por letra_maturity desde una fecha de
    vencimiento, para letras que Cocos exporta sin ticker. Prefijo 'X' (no usado
    por tickers reales). '2024-11-11' → 'X11N4'."""
    try:
        y, m, d = maturity_iso.split("-")
        code = _CODE_BY_MONTH.get(int(m))
        if not code:
            return None
        return f"X{int(d)}{code}{int(y) % 10}"
    except (ValueError, AttributeError):
        return None


def _max_import_date(conn, uid: int) -> Optional[str]:
    """Fecha (ISO) de la última transacción importada y confirmada del usuario.
    Es la 'foto' temporal: solo cerramos letras vencidas dentro de esta ventana
    (si la data del usuario no llega al vencimiento, la letra sigue viva)."""
    row = conn.execute(
        """SELECT MAX(n.date) AS d
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ? AND b.status = 'confirmed'""",
        (uid,),
    ).fetchone()
    return row["d"] if row and row["d"] else None


def _import_linked_position_ids(conn, uid: int) -> set:
    """ids de positions creadas por imports (vinculadas vía import_op_links).
    Solo estas son seguras de cerrar; cualquier posición manual se respeta."""
    return {
        r["position_id"]
        for r in conn.execute(
            """SELECT DISTINCT l.position_id
                 FROM import_op_links l JOIN import_batches b ON b.id = l.batch_id
                WHERE b.user_id = ? AND l.position_id IS NOT NULL""",
            (uid,),
        ).fetchall()
    }


def sweep_matured_letras(conn, uid: int, *, ref_date: Optional[str] = None) -> Dict[str, Any]:
    """Cierra las posiciones de letras/LECAPs cuyo vencimiento ya pasó dentro de
    la ventana de datos importada. Idempotente y seguro (no toca cash, monthly,
    ni posiciones manuales). Devuelve {'swept': [...], 'ref_date': ...}.

    El cash del rescate ya entró por la "Renta Y Amortizacion" (→ DIVIDENDO);
    borrar el papel deja el total correcto. Se deja intacto el link de
    import_op_links como 'tombstone' → el revert seguro detecta 'posición ya no
    existe' (igual que un papel vendido) y pide revert nuclear.
    """
    if ref_date is None:
        ref_date = _max_import_date(conn, uid)
    if not ref_date:
        return {"swept": [], "ref_date": None}

    linked = _import_linked_position_ids(conn, uid)
    swept: List[Dict[str, Any]] = []

    # Mapa (broker, activo) → nombre del instrumento importado, para derivar el
    # vencimiento de BONOS cuyo ticker no lo codifica (ej. T2X5 Boncer, RCCPO):
    # el nombre trae "V.14/02/25" y maturity_from_name lo parsea.
    name_map: Dict[tuple, str] = {}
    for r in conn.execute(
        """SELECT DISTINCT n.broker, n.asset_symbol, n.asset_name
             FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ? AND n.asset_name IS NOT NULL AND n.asset_symbol != ''""",
        (uid,),
    ).fetchall():
        key = (r["broker"], r["asset_symbol"])
        # Preferimos el nombre que SÍ codifica un vencimiento: el mismo ticker
        # puede venir con dos nombres en imports distintos (ej. T2X5 como "BONO
        # DEL TESORO (T2X5)" sin fecha y "BONO TESORO ... V.14/02/25 (T2X5)" con
        # fecha). setdefault se quedaba con el primero (a veces el sin fecha) →
        # no cerraba el bono. Acá ganamos el que rinde un vencimiento parseable.
        if key not in name_map or (maturity_from_name(r["asset_name"]) and not maturity_from_name(name_map[key])):
            name_map[key] = r["asset_name"]

    rows = conn.execute(
        "SELECT id, broker, asset, quantity FROM positions "
        "WHERE user_id=? AND is_cash=0",
        (uid,),
    ).fetchall()

    for p in rows:
        # Vencimiento por ticker (letra estándar) o, si no, por el nombre del
        # instrumento (bonos/Boncer/ON que codifican la fecha en el nombre).
        mat = letra_maturity(p["asset"]) or maturity_from_name(name_map.get((p["broker"], p["asset"])))
        if not mat:
            continue                       # ni letra ni bono con vencimiento → no tocar
        if mat > ref_date:
            continue                       # todavía no venció dentro de la ventana
        if p["id"] not in linked:
            continue                       # posición manual / no vinculada → respetar
        conn.execute(
            "DELETE FROM positions WHERE id=? AND user_id=? AND is_cash=0",
            (p["id"], uid),
        )
        swept.append({
            "broker": p["broker"], "asset": p["asset"],
            "quantity": p["quantity"], "maturity": mat,
        })

    if swept:
        log.info("sweep_matured_letras user=%s cerró %d posiciones (ref_date=%s): %s",
                 uid, len(swept), ref_date, [s["asset"] for s in swept])
    return {"swept": swept, "ref_date": ref_date}
