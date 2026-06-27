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

from .schema import OP_BUY, OP_SELL
from .persister import broker_pair
from pricing.bond_amortization import is_amortizing_bond, residual_factor

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


def _bond_genuine_net(conn, uid: int, brokers: List[str], asset: str) -> float:
    """Nominal NETO GENUINO del bono (Σ BUY − Σ SELL) sobre el PAR de brokers,
    CANCELANDO los pares de conducto dólar-MEP (compra+venta del mismo bono, igual
    nominal, cruce de moneda, ≤ventana) con la misma lógica que el rebuild. Es la
    base ORIGINAL estable para amortizar: si no se cancelan los conductos, la base
    queda inflada (genuino + patas-puente) y la amortización no aplica o aplica mal.
    Idempotente (recalcula desde import_normalized_tx, que los sweeps no tocan).

    EXCLUYE las VENTAS que SON la amortización (notes ~ 'amortiz'): algunos brokers
    (Balanz "Renta y Amortización" con cantidad) ya bajan el nominal cerrando la
    cuota como una VENTA al valor de rescate — eso es CORRECTO para el P&L. Pero la
    base de este sweep tiene que ser el nominal ORIGINAL (sin descontar esa cuota),
    porque el factor residual del schedule YA modela la amortización. Si contáramos
    la VENTA-amort acá, restaríamos la amortización DOS veces: una en la base (Σ−),
    otra en el factor → doble reducción (ej. AL30 720 → 518 en vez de 720). Las
    VENTAS genuinas (sin 'amortiz') SÍ entran (reducen tu tenencia de verdad)."""
    from .rebuild import _cancel_conduit_pairs  # lazy: evita ciclo rebuild↔maturity
    _ph = ",".join("?" * len(brokers))
    rows = conn.execute(
        f"""SELECT n.asset_symbol, n.asset_name, n.operation_type, n.quantity,
                   n.currency, n.date
              FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
             WHERE b.user_id=? AND b.status='confirmed'
               AND n.broker IN ({_ph}) AND n.asset_symbol=?
               AND n.operation_type IN (?, ?)
               AND NOT (n.operation_type = ?
                        AND lower(COALESCE(n.notes,'')) LIKE '%amortiz%')
             ORDER BY n.date ASC, n.id ASC""",
        (uid, *brokers, asset, OP_BUY, OP_SELL, OP_SELL),
    ).fetchall()
    genuine = _cancel_conduit_pairs([dict(r) for r in rows])
    net = 0.0
    for e in genuine:
        q = float(e["quantity"] or 0)
        net += q if e["operation_type"] == OP_BUY else -q
    return net


def sweep_bond_amortizations(conn, uid: int, *, ref_date: Optional[str] = None) -> Dict[str, Any]:
    """Baja el nominal de los bonos AR amortizantes (AL30/GD30/…) a su valor
    RESIDUAL = (comprado − vendido) × factor_residual(ref_date). Idempotente y
    seguro. Devuelve {'adjusted': [...], 'ref_date': ...}.

    Por qué: un bono que amortiza devuelve capital en cuotas; el mercado lo cotiza
    por nominal RESIDUAL, pero Rendi guarda el nominal ORIGINAL (la amortización se
    importa como dividendo = solo cash). Sin esto la tenencia y la valuación quedan
    sobrevaluadas, y un bono 100% amortizado sigue figurando como posición activa.

    - ref_date = HOY por default: la amortización ocurre en tiempo calendario, no
      depende de la ventana del export (a diferencia del sweep de letras).
    - NO toca cash (ya entró por el dividendo) ni monthly_entries.
    - Solo reduce lotes import-linked; respeta posiciones manuales.
    - Reduce quantity + invested + commissions proporcional (mantiene el costo
      unitario del residual).
    """
    if ref_date is None:
        ref_date = date.today().isoformat()

    linked = _import_linked_position_ids(conn, uid)
    adjusted: List[Dict[str, Any]] = []

    # nombre por (broker, activo): fallback para resolver el schedule por nombre si
    # el ticker no matchea (defensivo; las posiciones de bono ya traen el ticker).
    name_map: Dict[tuple, str] = {}
    for r in conn.execute(
        """SELECT DISTINCT n.broker, n.asset_symbol, n.asset_name
             FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id=? AND n.asset_symbol != ''""",
        (uid,),
    ).fetchall():
        name_map.setdefault((r["broker"], r["asset_symbol"]), r["asset_name"] or "")

    # Lotes agrupados por (PAR de brokers, activo), FIFO (entry_date asc, id asc).
    # Agrupamos por el PAR padre↔'· USD' porque un bono-conducto reparte sus lotes
    # genuinos entre los dos brokers; la amortización tiene que verlos juntos.
    pair_cache: Dict[str, tuple] = {}
    groups: Dict[tuple, List[Any]] = {}
    for p in conn.execute(
        "SELECT id, broker, asset, quantity, invested, commissions, entry_date "
        "FROM positions WHERE user_id=? AND is_cash=0 AND quantity > 0 "
        "ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC",
        (uid,),
    ).fetchall():
        if p["broker"] not in pair_cache:
            pair_cache[p["broker"]] = tuple(broker_pair(conn, uid, p["broker"]))
        groups.setdefault((pair_cache[p["broker"]], p["asset"]), []).append(p)

    for (pair, asset), lots in groups.items():
        # Resolver el schedule por ticker o, si no, por nombre (cualquiera del par).
        name = next((name_map.get((b, asset), "") for b in pair if name_map.get((b, asset))), "")
        if is_amortizing_bond(asset):
            key = asset
        elif is_amortizing_bond(name):
            key = name
        else:
            continue
        r = residual_factor(key, ref_date)
        if r >= 1.0 - 1e-9:
            continue  # todavía no amortizó nada → no-op

        # Base = nominal GENUINO sobre el par (conductos cancelados) — no inflada.
        original = _bond_genuine_net(conn, uid, list(pair), asset)
        if original <= 1e-9:
            continue
        target = original * r
        # Solo los lotes import-linked se amortizan (los manuales se respetan).
        linked_lots = [l for l in lots if l["id"] in linked]
        current = sum((l["quantity"] or 0) for l in linked_lots)
        if current <= 1e-9:
            continue
        # Reducción PROPORCIONAL (no FIFO): la amortización baja TODOS los lotes por el
        # mismo factor — correcto para una amortización (cada lámina amortiza igual) y
        # currency-aware (un bono con tenencia genuina en ARS y USD escala cada moneda
        # por sí misma; el FIFO consumía una sola → audit 2026-06-26). factor =
        # target/current: si ya está en el residual, factor≈1 → no-op (idempotente,
        # target es estable desde import_normalized_tx).
        factor = target / current
        if factor >= 1.0 - 1e-9:
            continue  # ya está en el residual o por debajo
        reduced = 0.0
        for l in linked_lots:
            lot_qty = l["quantity"] or 0
            new_qty = lot_qty * factor
            new_inv = (l["invested"] or 0) * factor
            new_com = (l["commissions"] or 0) * factor
            if new_qty <= 1e-9:
                conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (l["id"], uid))
            else:
                conn.execute(
                    "UPDATE positions SET quantity=?, invested=?, commissions=? "
                    "WHERE id=? AND user_id=?",
                    (round(new_qty, 6), round(new_inv, 6), round(new_com, 6), l["id"], uid),
                )
            reduced += lot_qty - new_qty

        if reduced > 1e-9:
            adjusted.append({
                "broker": pair[0] if len(pair) == 1 else "+".join(pair), "asset": asset,
                "residual_factor": round(r, 6), "reduced": round(reduced, 6),
            })

    if adjusted:
        log.info("sweep_bond_amortizations user=%s ajustó %d bonos (ref_date=%s): %s",
                 uid, len(adjusted), ref_date, [a["asset"] for a in adjusted])
    return {"adjusted": adjusted, "ref_date": ref_date}
