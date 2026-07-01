"""Rebuild global de FIFO post-import — hace que el ORDEN de carga no importe.

Problema que resuelve
─────────────────────
El persister (`persist_batch`) es incremental: procesa las txs de UN batch
contra el estado actual de la DB. El FIFO (con qué compra se matchea cada venta)
se calcula al momento de importar. NO hay re-cálculo global después.

Entonces, si el usuario importa su historial en tandas y FUERA de orden
cronológico — típico: "tengo 2025, después consigo 2024" — una venta de 2025 de
algo comprado en 2024 NO encuentra su compra (todavía no se cargó). El persister,
con su política "history-as-truth", crea un lote semilla al PRECIO DE VENTA →
P&L = 0 en esa operación. Cuando después se carga la compra de 2024, entra como
un lote ABIERTO fantasma que nunca se cierra. Resultado: tenencia inflada +
ganancia realizada subestimada.

Qué hace este módulo
────────────────────
Después de cada import, por cada (broker, activo) que el batch tocó, replaya
TODAS las compras/ventas importadas de ese (broker, activo) — de todos los
batches confirmados — en orden cronológico global, y reconstruye:
  • los lotes abiertos (`positions`)
  • las ventas (`operations` con op_type='Venta') con su P&L correcto

Es exactamente equivalente a "importar todo junto en el orden correcto", que es
el caso que ya sabemos que funciona bien.

Qué NO toca (a propósito)
─────────────────────────
  • Cash / saldos de broker: los proceeds de una venta y los depósitos son
    order-independent (qty×precio no depende del cost basis). El neto de cash es
    idéntico sin importar el orden → rebuild NO ajusta cash.
  • Depósitos / retiros / dividendos / intereses / FX: no dependen del FIFO.
  • monthly_entries: se arreglan solos llamando `_recalc_pnl_realized_from_ops`
    después (recalcula pnl_realized = SUM(operations.pnl_usd) desde la fuente
    autoritativa). El caller (import_confirm) ya lo hace.

Frontera de seguridad (CRÍTICO)
───────────────────────────────
El log de eventos reproducible y sin contaminar es `import_normalized_tx`. Las
operaciones MANUALES (botón Nueva posición / Vender) NO viven ahí — mutan
positions/operations directo. Un (broker, activo) con CUALQUIER posición o venta
manual (no vinculada a un import vía `import_op_links`) se SALTEA intacto: nunca
reconstruimos sobre data que no podemos reproducir. Peor caso = comportamiento
de hoy (sin corromper nada).

Revert
──────
Reconstruimos la doble vinculación que usa el revert (`_link`):
`import_normalized_tx.created_*_id` + filas en `import_op_links`. Antes de
recrear, limpiamos la vinculación vieja de los raw rows afectados.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from datetime import date as _date

from .schema import OP_BUY, OP_SELL
from .persister import _link, broker_pair, blue_for_date
from .maturity import is_bond_like_name
from .normalizer import guess_asset_type
try:
    from ai.ar_bonds_metadata import is_known_ar_bond
except Exception:  # pragma: no cover
    def is_known_ar_bond(_t):
        return False

log = logging.getLogger(__name__)

_EPS = 1e-9


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _norm_cur(c: Optional[str]) -> Optional[str]:
    u = (c or "").upper() or None
    return "USD" if u == "USDT" else u


def _days_apart(d1: Optional[str], d2: Optional[str]) -> Optional[int]:
    """Días absolutos entre dos fechas ISO 'YYYY-MM-DD'. None si alguna no parsea."""
    try:
        a = _date.fromisoformat((d1 or "")[:10])
        b = _date.fromisoformat((d2 or "")[:10])
        return abs((a - b).days)
    except (ValueError, TypeError):
        return None


# Ventana máxima entre las dos patas de un conducto dólar-MEP (parking ~T+1; algunos
# brokers registran las patas con días de diferencia). Más allá, es un round-trip
# genuino (con P&L real), no una conversión de moneda.
_CONDUIT_WINDOW_DAYS = 7


def _cancel_conduit_pairs(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cancela pares de CONDUCTO dólar-MEP de BONOS antes del FIFO.

    Un conducto = una COMPRA y una VENTA del MISMO bono, en monedas DISTINTAS,
    MISMO nominal, cerca en el tiempo (≤ _CONDUIT_WINDOW_DAYS). Es una conversión de
    moneda (comprás X nominal en pesos y vendés X en dólares — o al revés), NO una
    tenencia: el neto del bono es 0. El parser intenta colapsarlos a FX, pero se le
    escapan (cross-día, sin etiqueta 'Dolar Mep', etc.) y llegan acá como BUY/SELL.

    Si NO se cancelan, el FIFO los trata como posiciones reales y, mezclados con una
    tenencia GENUINA del mismo bono, la INFLAN (deja la pata cross-currency como
    fantasma) o la DESTRUYEN. Reproducido: 1000 ARS genuino + 5000 USD conducto +
    venta 5000 ARS → daba 5000 USD fantasma en vez de 1000 ARS.

    Por qué no rompe tenencias genuinas dual-currency (5 ARS + 5 USD, venta 7 ARS):
    el match exige nominal IGUAL compra↔venta; una venta de 7 no matchea una compra
    de 5 → no se cancela nada, lo maneja el FIFO/spill como antes. Restringido a
    BONOS para no tocar el neteo de acciones (ya testeado en _replay_asset)."""
    if not events:
        return events
    # El grupo es un solo activo; basta con que alguna fila lo marque como bono
    # (por símbolo soberano o por nombre tipo "ON …"/"BONO …"/"Letra …").
    is_bond = any(
        is_known_ar_bond(e.get("asset_symbol") or "") or is_bond_like_name(e.get("asset_name") or "")
        for e in events
    )
    if not is_bond:
        return events

    buys = [e for e in events if e["operation_type"] == OP_BUY]
    sells = [e for e in events if e["operation_type"] == OP_SELL]
    cancelled: set = set()

    # GATE net-short por moneda (audit 2026-06-26): una venta en la moneda X solo
    # puede ser conducto si las COMPRAS en X NO alcanzan a cubrir las VENTAS en X
    # (X está "corta" del lado compra → el faltante salió de la otra moneda vía MEP).
    # Si las compras same-currency cubren las ventas same-currency, esa venta es
    # tenencia genuina (o un round-trip same-currency), NO un conducto → no cancelar.
    # Esto evita destruir una tenencia dual-currency genuina de igual nominal.
    buys_by_ccy: Dict[Optional[str], float] = {}
    sells_by_ccy: Dict[Optional[str], float] = {}
    for e in events:
        c = _norm_cur(e["currency"])
        q = _num(e["quantity"])
        if e["operation_type"] == OP_BUY:
            buys_by_ccy[c] = buys_by_ccy.get(c, 0.0) + q
        elif e["operation_type"] == OP_SELL:
            sells_by_ccy[c] = sells_by_ccy.get(c, 0.0) + q

    for s in sells:
        s_ccy = _norm_cur(s["currency"])
        s_qty = _num(s["quantity"])
        if s_qty <= _EPS:
            continue
        # Moneda no corta (compras ≥ ventas) → la venta se cubre sola → no conducto.
        if buys_by_ccy.get(s_ccy, 0.0) >= sells_by_ccy.get(s_ccy, 0.0) - _EPS:
            continue
        best = None  # (días, evento_compra)
        for b in buys:
            if id(b) in cancelled:
                continue
            if _norm_cur(b["currency"]) == s_ccy:      # misma moneda → no es conducto
                continue
            if abs(_num(b["quantity"]) - s_qty) > max(1e-6, 1e-6 * s_qty):
                continue                                # nominal distinto → tenencia genuina
            dd = _days_apart(s["date"], b["date"])
            if dd is None or dd > _CONDUIT_WINDOW_DAYS:
                continue                                # muy separados → round-trip genuino
            if best is None or dd < best[0]:
                best = (dd, b)
        if best is not None:
            cancelled.add(id(best[1]))
            cancelled.add(id(s))

    if not cancelled:
        return events
    return [e for e in events if id(e) not in cancelled]


def _is_exchange_broker(name) -> bool:
    """¿El broker es un exchange cripto (Binance, etc.)? Import diferido de la
    SSoT en main para evitar el import circular (main importa este módulo). Si
    por algún motivo no está disponible, asumimos que NO es exchange (conserva el
    comportamiento previo: la venta a 0 bookea pérdida)."""
    try:
        from main import is_exchange_broker
        return is_exchange_broker(name)
    except Exception:
        return False


def _replay_asset(events: List[Dict[str, Any]], broker_currency: str,
                   tc_blue: float, conn=None,
                   is_exchange: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Replaya los eventos BUY/SELL (ya ordenados cronológicamente, BUY antes
    que SELL el mismo día) de UN (broker, activo) y devuelve:
      {"operations": [...], "open_lots": [...]}

    Espeja `_persist_sell_fifo` / `_persist_buy` exactamente, pero EN MEMORIA y
    SIN efectos de cash. Cada dict de salida lleva su origen (batch_id,
    raw_row_id) para re-vincular; None en lotes semilla (igual que el persister,
    que no linkea las semillas)."""
    lots: List[Dict[str, Any]] = []   # lotes abiertos, FIFO desde el frente
    operations: List[Dict[str, Any]] = []
    # Monedas en las que el activo TUVO una compra real (no seeds) en este replay.
    # Distingue una tenencia GENUINA same-currency ya vendida (no spill) de un
    # holding cross-currency-only vendido en otra moneda (sí spill, dólar-MEP).
    seen_buy_ccy: set = set()

    # ── Pass 1: presupuesto de spill cross-currency AGREGADO ───────────────────
    # El neteo dólar-MEP cierra una compra en una moneda con una venta en la OTRA.
    # La decisión per-venta de abajo (never_held_same / full_net) cubre el conducto
    # puro y el neteo total de UNA venta, pero NO el caso en que la pata cruzada se
    # consume GRADUALMENTE en muchas ventas chicas (Balanz: un ticker con decenas de
    # operaciones — la pata USD se cierra de a poco y ninguna venta sola la cancela
    # entera, así que full_net nunca dispara y queda fantasma). Para eso precomputamos
    # sobre TODO el timeline del par cuánto de la pata opuesta puede consumir cada
    # moneda de venta, y lo usamos como capacidad EXTRA de spill (tomamos el MÁXIMO
    # con la per-venta → NUNCA quitamos capacidad, solo sumamos el caso gradual; así
    # no se regresiona el neteo bidireccional/conducto que ya andaba).
    def _ccy_of(ev):
        c = _norm_cur(ev["currency"]) or broker_currency
        return c if c in ("ARS", "USD") else broker_currency
    _net_buy = {"ARS": 0.0, "USD": 0.0}
    _net_sell = {"ARS": 0.0, "USD": 0.0}
    for ev in events:
        c = _ccy_of(ev)
        if c not in _net_buy:
            continue
        if ev["operation_type"] == OP_BUY:
            _net_buy[c] += _num(ev["quantity"])
        elif ev["operation_type"] == OP_SELL:
            _net_sell[c] += _num(ev["quantity"])
    _oversell = {c: max(0.0, _net_sell[c] - _net_buy[c]) for c in _net_buy}
    _genuine_leg = {c: max(0.0, _net_buy[c] - _net_sell[c]) for c in _net_buy}
    # Presupuesto por moneda de venta C (otra moneda O). ASIMÉTRICO por la mecánica
    # dólar-MEP: vender USD de más baja PROPORCIONALMENTE el nominal ARS (spill
    # parcial — vendiste en dólares lo que compraste en pesos); vender ARS de más solo
    # cancela la pata USD si la consume ENTERA (binario), para preservar una tenencia
    # USD genuina (5 ARS + 5 USD, venta 7 ARS → no toca los 5 USD).
    budget_left = {"ARS": 0.0, "USD": 0.0}
    for _C in ("ARS", "USD"):
        _O = "USD" if _C == "ARS" else "ARS"
        if _oversell[_C] <= _EPS:
            budget_left[_C] = 0.0
        elif _net_buy[_C] <= _EPS or _C == "USD":
            # conducto puro (cualquier dirección) o venta USD oversold → spill PARCIAL
            budget_left[_C] = min(_oversell[_C], _genuine_leg[_O])
        else:
            # venta ARS oversold con compras ARS genuinas → BINARIO (full-net o nada)
            budget_left[_C] = _genuine_leg[_O] if _oversell[_C] >= _genuine_leg[_O] - _EPS else 0.0

    for ev in events:
        op = ev["operation_type"]

        if op == OP_BUY:
            qty = _num(ev["quantity"])
            unit = _num(ev["unit_price"])
            invested = _num(ev["gross_amount"]) if ev["gross_amount"] is not None else unit * qty
            fees = _num(ev["fees"])
            seen_buy_ccy.add(_norm_cur(ev["currency"]) or broker_currency)
            lots.append({
                "qty": qty,
                "invested": invested,
                "buy_price": unit if unit > 0 else None,
                "commissions": fees,
                "entry_date": ev["date"],
                "currency": _norm_cur(ev["currency"]),
                "batch_id": ev["batch_id"],
                "raw_row_id": ev["raw_row_id"],
                "is_seed": False,
                # Broker DEL LOTE (no del grupo): con el neteo cross-broker del par
                # padre↔'· USD' un mismo activo tiene lotes en distintos brokers
                # (compra dólar-MEP en el sibling). El lote sobreviviente se escribe
                # a SU broker.
                "_broker": ev["broker"],
                "_asset": ev["asset_symbol"],
                "_asset_type": ev.get("asset_type"),
            })
            continue

        if op != OP_SELL:
            continue  # defensivo: solo BUY/SELL llegan acá

        # ── Venta FIFO (espejo de _persist_sell_fifo) ──────────────────────
        sell_currency = _norm_cur(ev["currency"]) or broker_currency
        if sell_currency not in ("ARS", "USD"):
            sell_currency = broker_currency
        currency = sell_currency

        exit_price = _num(ev["unit_price"])
        sell_commissions = _num(ev["fees"])
        qty_to_sell = _num(ev["quantity"])
        op_date = ev["date"]

        total_avail = sum(l["qty"] for l in lots)

        # Lotes en la moneda de la venta vs la OTRA moneda del par.
        _same = [l for l in lots if (l["currency"] or currency) == currency]
        _other = [l for l in lots if (l["currency"] or currency) != currency]
        _same_total = sum(l["qty"] for l in _same)
        _other_total = sum(l["qty"] for l in _other)
        oversell_same = qty_to_sell - _same_total   # faltante en la moneda de la venta

        def _seed(qty):
            # Lote semilla history-as-truth al precio de venta (P&L = 0 sobre ese
            # chunk). Vive en el broker/moneda de la venta que lo necesitó.
            seed = {
                "qty": qty, "invested": qty * exit_price, "buy_price": exit_price,
                "commissions": 0.0, "entry_date": op_date,
                "currency": _norm_cur(ev["currency"]),
                "batch_id": None, "raw_row_id": None, "is_seed": True,
                "_broker": ev["broker"], "_asset": ev["asset_symbol"],
                "_asset_type": ev.get("asset_type"),
            }
            lots.append(seed)
            return seed

        # ¿Consumir la OTRA moneda del par (spill cross-currency = neteo dólar-MEP)?
        # Sí en dos casos:
        #   (a) el activo NUNCA tuvo una compra en la moneda de la venta → la venta es
        #       ENTERAMENTE cross-currency (vendió en pesos lo que compró en dólares;
        #       ej. BMA comprado 10 USD, vendido 4 ARS → consume 4 de la pata USD).
        #       OJO: "nunca tuvo" (seen_buy_ccy), NO "no tiene AHORA" — si tuvo lotes
        #       same-currency y se vendieron (split-sell), NO es conduit (audit).
        #   (b) el oversell en la moneda de la venta consume ENTERA la pata de la otra
        #       moneda — la pata USD compensa EXACTO el oversell ARS → tenencia TOTAL
        #       del activo ≈ 0 (conversión: comprado USD en el sibling, vendido de más
        #       en ARS en el padre; ej. AAPL 11 ARS + 2 USD, venta 13 ARS).
        # Si HAY lotes same-currency y el oversell es MENOR que la pata cross-currency,
        # esa pata es GENUINA (no un conduit) → NO la tocamos; el faltante se cubre con
        # un seed same-currency. Así no destruimos una tenencia dual-currency real
        # (audit 2026-06-26: 5 ARS + 5 USD, venta 7 ARS NO debe comerse la pata USD).
        full_net = (oversell_same > _EPS and _other_total > _EPS
                    and oversell_same >= _other_total - _EPS)
        never_held_same = currency not in seen_buy_ccy
        do_spill = (_same_total <= _EPS and _other_total > _EPS and never_held_same) or full_net

        # Capacidad de consumo de la OTRA moneda (spill cross-currency), como el MÁX de:
        #   - per-venta (do_spill): conducto puro o full-net de ESTA venta → toda la pata.
        #   - agregada (budget_left): el caso gradual del Pass 1.
        # Tomar el máximo nunca quita capacidad → no regresiona bidireccional/conducto.
        per_sell_cap = _other_total if do_spill else 0.0
        spill_cap = max(per_sell_cap, budget_left.get(currency, 0.0))
        spill_qty = min(max(0.0, oversell_same), _other_total, spill_cap)

        # Same-currency primero; la pata cruzada se capa a spill_qty DENTRO del loop.
        _consume_from = list(_same)
        if spill_qty > _EPS:
            _consume_from = _consume_from + _other
        seed_qty = max(0.0, oversell_same) - spill_qty
        if seed_qty > _EPS:
            _consume_from = _consume_from + [_seed(seed_qty)]

        tc_venta = tc_blue if sell_currency == "ARS" else 1.0
        remaining = qty_to_sell
        spill_taken = 0.0   # cuánto de la pata cruzada (cross-currency) ya consumimos

        for lot in _consume_from:
            if remaining <= _EPS:
                break
            pos_qty = lot["qty"]
            take = min(remaining, pos_qty)
            lot_currency = lot["currency"] or currency
            is_cross = lot_currency != currency
            if is_cross:
                # No consumir más de la pata cruzada que el presupuesto de spill.
                take = min(take, spill_qty - spill_taken)
            if take <= _EPS:
                continue
            ratio = take / pos_qty if pos_qty > 0 else 0
            pos_buy_commissions = lot["commissions"] or 0
            base_invested = (lot["invested"] or 0) + pos_buy_commissions

            # Cross-currency: valuar el invested del lote en la moneda de la venta.
            if is_cross and tc_blue:
                if lot_currency == "USD" and currency == "ARS":
                    base_invested = base_invested * tc_blue
                elif lot_currency == "ARS" and currency == "USD":
                    # Dólar-MEP: el costo USD es lo que esos pesos valían CUANDO
                    # COMPRASTE (blue de la fecha de entrada), NO el blue de hoy —
                    # sino la devaluación achica el costo e infla la ganancia.
                    # MISMA convención que el persister (persister.py:570-578);
                    # antes rebuild usaba el blue de hoy y divergía → la P&L
                    # realizada cambiaba según cuándo corría el rebuild. Sin conn
                    # cae al tc_blue actual (back-compat con callers/tests viejos).
                    _pblue = blue_for_date(conn, lot.get("entry_date"), tc_blue) if conn is not None else tc_blue
                    base_invested = base_invested / (_pblue or tc_blue)

            entry_invested = base_invested * ratio if base_invested else None
            chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0

            # EXCHANGE: una VENTA con proceeds 0 (precio 0 y monto 0) NO es una
            # venta real sino un RETIRO/transferencia del coin a una wallet (o
            # polvo→BNB) → cerramos el lote A COSTO (P&L 0), no a pérdida. Espeja
            # el `transfer_out` del persister. En brokers de acciones el heurístico
            # is_exchange NO aplica (corporate_close de Balanz sí debe bookear el
            # costo como pérdida, compensada por su Dividendo) — por eso el ajuste
            # de la foto de tenencia lleva el flag EXPLÍCITO `transfer_out` en la
            # fila (persistido en import_normalized_tx): así una reducción "a costo"
            # se distingue de un corporate_close aunque ambas sean VENTA a precio 0.
            transfer_out = ((is_exchange or bool(ev.get("transfer_out")))
                            and not exit_price and not _num(ev["gross_amount"]))
            if transfer_out:
                if currency == "ARS":
                    invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
                else:
                    invested_usd = entry_invested if entry_invested is not None else ((lot["buy_price"] or 0) * take)
                pnl_usd = 0.0
            elif currency == "ARS":
                pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission
                pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0
                invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
            else:
                cost = entry_invested if entry_invested is not None else ((lot["buy_price"] or 0) * take)
                pnl_usd = (exit_price * take) - cost - chunk_commission
                invested_usd = cost

            pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None

            operations.append({
                "date": op_date,
                "broker": ev["broker"],
                "asset": ev["asset_symbol"],
                "op_type": "Venta",
                "entry_price": lot["buy_price"],
                "exit_price": exit_price,
                "quantity": take,
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
                "entry_date": lot["entry_date"],
                "commissions": round(chunk_commission, 4),
                # origen = la VENTA (para revert / dedup de links)
                "batch_id": ev["batch_id"],
                "raw_row_id": ev["raw_row_id"],
            })

            # Consumir el lote
            if take >= pos_qty - _EPS:
                lot["qty"] = 0.0
            else:
                remaining_ratio = 1 - ratio
                lot["qty"] = pos_qty - take
                lot["invested"] = round((lot["invested"] or 0) * remaining_ratio, 6) if lot["invested"] is not None else None
                lot["commissions"] = round(pos_buy_commissions * remaining_ratio, 6)
            remaining -= take
            if is_cross:
                spill_taken += take

        # El spill cross-currency consumido descuenta del presupuesto agregado, así
        # las ventas posteriores no vuelven a cruzar de más.
        budget_left[currency] = max(0.0, budget_left.get(currency, 0.0) - spill_taken)
        # limpiar lotes agotados
        lots = [l for l in lots if l["qty"] > _EPS]

    open_lots = [l for l in lots if l["qty"] > _EPS]
    return {"operations": operations, "open_lots": open_lots}


def _affected_assets(conn, uid: int, batch_id: str) -> List[Dict[str, str]]:
    """(broker, activo) con compras/ventas en el batch recién confirmado."""
    rows = conn.execute(
        """SELECT DISTINCT broker, asset_symbol
             FROM import_normalized_tx
            WHERE batch_id = ?
              AND operation_type IN (?, ?)
              AND asset_symbol IS NOT NULL
              AND asset_symbol != ''""",
        (batch_id, OP_BUY, OP_SELL),
    ).fetchall()
    return [{"broker": r["broker"], "asset": r["asset_symbol"]} for r in rows]


def _full_events(conn, uid: int, brokers: List[str], asset: str) -> List[Dict[str, Any]]:
    """Todos los BUY/SELL confirmados del activo en los brokers del par, orden
    cronológico determinístico (fecha asc; BUY antes que SELL el mismo día; id asc).

    `brokers` es el par padre↔'· USD' (o [broker] si no tiene par): así una compra
    dólar-MEP ruteada al sibling y su venta en el padre se replayan JUNTAS y netean.

    INVARIANTE: import_normalized_tx = "lo que se aplicó". Las filas que el
    usuario marca para saltear (skip_row_indices) se BORRAN de esta tabla en
    import_confirm antes de llegar acá; si no, este replay las resucitaría."""
    _ph = ",".join("?" * len(brokers))
    rows = conn.execute(
        f"""SELECT n.id, n.batch_id, n.raw_row_id, n.date, n.broker, n.asset_symbol,
                  n.asset_name, n.operation_type, n.quantity, n.unit_price, n.gross_amount,
                  n.fees, n.currency, n.asset_type, n.transfer_out, n.created_position_id
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ?
              AND b.status = 'confirmed'
              AND n.broker IN ({_ph})
              AND n.asset_symbol = ?
              AND n.operation_type IN (?, ?)
            ORDER BY n.date ASC,
                     CASE n.operation_type WHEN ? THEN 0 ELSE 1 END ASC,
                     n.id ASC""",
        (uid, *brokers, asset, OP_BUY, OP_SELL, OP_BUY),
    ).fetchall()
    return [dict(r) for r in rows]


def _is_safe_to_rebuild(conn, uid: int, brokers: List[str], asset: str) -> bool:
    """True si TODAS las positions (lotes abiertos) y ventas actuales del activo
    en los brokers del par fueron creadas por imports (vinculadas en
    import_op_links). Si hay cualquier fila manual / sin vincular (incluye lotes
    semilla huérfanos), devolvemos False → se saltea, nunca se corrompe data no
    reproducible."""
    _ph = ",".join("?" * len(brokers))
    cur_pos = [r["id"] for r in conn.execute(
        f"SELECT id FROM positions WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND is_cash=0",
        (uid, *brokers, asset),
    ).fetchall()]
    cur_sells = [r["id"] for r in conn.execute(
        f"SELECT id FROM operations WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND op_type='Venta'",
        (uid, *brokers, asset),
    ).fetchall()]

    linked_pos = {r["position_id"] for r in conn.execute(
        """SELECT DISTINCT l.position_id
             FROM import_op_links l JOIN import_batches b ON b.id = l.batch_id
            WHERE b.user_id=? AND l.position_id IS NOT NULL""",
        (uid,),
    ).fetchall()}
    linked_ops = {r["operation_id"] for r in conn.execute(
        """SELECT DISTINCT l.operation_id
             FROM import_op_links l JOIN import_batches b ON b.id = l.batch_id
            WHERE b.user_id=? AND l.operation_id IS NOT NULL""",
        (uid,),
    ).fetchall()}

    if any(pid not in linked_pos for pid in cur_pos):
        return False
    if any(oid not in linked_ops for oid in cur_sells):
        return False
    return True


def _clear_old_state(conn, uid: int, brokers: List[str], asset: str,
                     events: List[Dict[str, Any]]) -> Dict[tuple, Optional[int]]:
    """Borra los lotes abiertos + ventas import-creadas del activo en los brokers
    del par y limpia su vinculación de revert, dejando todo listo para re-crear.

    Devuelve {(batch_id, raw_row_id): old_created_position_id} para las filas
    BUY — lo usamos para dejar un "tombstone" en las compras que el rebuild
    consume del todo (así el revert seguro sigue bloqueándose: la posición ya
    no existe = fue vendida)."""
    old_buy_pos: Dict[tuple, Optional[int]] = {}
    for ev in events:
        if ev["operation_type"] == OP_BUY:
            old_buy_pos[(ev["batch_id"], ev["raw_row_id"])] = ev.get("created_position_id")

    _ph = ",".join("?" * len(brokers))
    conn.execute(
        f"DELETE FROM positions WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND is_cash=0",
        (uid, *brokers, asset),
    )
    conn.execute(
        f"DELETE FROM operations WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND op_type='Venta'",
        (uid, *brokers, asset),
    )
    # Resetear la vinculación de cada raw row afectado (las vamos a re-linkear).
    for ev in events:
        conn.execute(
            """UPDATE import_normalized_tx
                  SET created_position_id = NULL, created_operation_id = NULL
                WHERE id = ?""",
            (ev["id"],),
        )
        conn.execute(
            "DELETE FROM import_op_links WHERE batch_id=? AND raw_row_id=?",
            (ev["batch_id"], ev["raw_row_id"]),
        )
    return old_buy_pos


def _write_buy_tombstones(conn, consumed_keys: set,
                          old_buy_pos: Dict[tuple, Optional[int]]) -> None:
    """Para cada compra que el rebuild consumió por completo (no quedó lote
    abierto), restaura un link apuntando a su position_id viejo (ya borrado;
    AUTOINCREMENT no lo reusa). Así el pre-check del revert seguro lo detecta
    como 'posición ya no existe → vendida' y bloquea, en vez de revertir y
    devolver cash de una compra que en realidad se cerró."""
    for key in consumed_keys:
        old_pid = old_buy_pos.get(key)
        if not old_pid:
            continue
        batch_id, raw_row_id = key
        conn.execute(
            """UPDATE import_normalized_tx SET created_position_id = ?
                WHERE batch_id=? AND raw_row_id=?""",
            (old_pid, batch_id, raw_row_id),
        )
        conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            (batch_id, raw_row_id, old_pid),
        )


def _write_rebuilt(conn, uid: int, replay: Dict[str, List[Dict[str, Any]]]) -> None:
    """Inserta los lotes abiertos + ventas reconstruidos y re-vincula para revert."""
    for lot in replay["open_lots"]:
        # broker/asset vienen del grupo (_broker/_asset), no del lote individual.
        # asset_type: el rebuild ANTES lo perdía (no estaba en el INSERT) → los bonos
        # quedaban sin tipo y no recibían el guard de renta fija. Lo arrastramos del
        # evento; si falta (seeds, o parsers que no lo setean como IEB), lo inferimos
        # del ticker (guess detecta bonos AR conocidos).
        at = lot.get("_asset_type")
        if not at or at == "OTHER":
            at = guess_asset_type(lot["_asset"]) or at
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price,
                   quantity, invested, tc_compra, price_override, notes, entry_date,
                   commissions, currency, asset_type)
               VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,?)""",
            (uid, lot["_broker"], lot["_asset"], lot["buy_price"], lot["qty"],
             lot["invested"], None, None, None, lot["entry_date"],
             lot["commissions"], lot["currency"], at),
        )
        position_id = cur.lastrowid
        # Lotes semilla no tienen origen → no se linkean (igual que el persister).
        if lot.get("batch_id") and lot.get("raw_row_id"):
            _link(conn, lot["batch_id"], lot["raw_row_id"], position_id=position_id)

    for o in replay["operations"]:
        cur = conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                   entry_price, exit_price, quantity, pnl_usd, pnl_pct, entry_date,
                   commissions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, o["date"], o["broker"], o["asset"], o["op_type"],
             o["entry_price"], o["exit_price"], o["quantity"], o["pnl_usd"],
             o["pnl_pct"], o["entry_date"], o["commissions"]),
        )
        op_id = cur.lastrowid
        if o.get("batch_id") and o.get("raw_row_id"):
            _link(conn, o["batch_id"], o["raw_row_id"], operation_id=op_id)


def _ensure_monthly_rows(conn, uid: int, operations: List[Dict[str, Any]]) -> None:
    """Garantiza que exista la fila de monthly_entries (broker + 'global') del
    mes de cada venta reconstruida.

    Por qué: `_recalc_pnl_realized_from_ops` recalcula pnl_realized SOLO para
    los (broker, año, mes) que YA tienen fila en monthly_entries. Si las ventas
    se importaron primero fuera de orden, su P&L era 0 (lote semilla) y el
    recalc borró esas filas "todo en 0". Tras reconstruir el P&L correcto, sin
    esta garantía no habría fila donde sumarlo y el monthly quedaría en 0.
    INSERT OR IGNORE crea la fila con ceros; el recalc posterior la rellena."""
    seen = set()
    for o in operations:
        d = o.get("date") or ""
        if len(d) < 7:
            continue
        try:
            y, m = int(d[:4]), int(d[5:7])
        except ValueError:
            continue
        for broker in (o["broker"], "global"):
            key = (broker, y, m)
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                """INSERT OR IGNORE INTO monthly_entries (user_id, year, month, broker)
                   VALUES (?,?,?,?)""",
                (uid, y, m, broker),
            )


def rebuild_fifo_after_import(conn, uid: int, batch_id: str, *,
                              tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Reconstruye el FIFO (lotes abiertos + ventas) de cada (broker, activo) que
    el batch tocó, replayando todo su historial importado en orden cronológico.

    Idempotente: si los datos ya estaban en orden, reproduce el mismo estado.
    Seguro: saltea (broker, activo) con data manual no reproducible.

    Devuelve {"rebuilt": [...], "skipped_manual": [...], "skipped_no_sell": [...]}.
    El caller debe correr `_recalc_pnl_realized_from_ops` después para sincronizar
    monthly_entries desde las operations corregidas.
    """
    rebuilt: List[Dict[str, Any]] = []
    skipped_manual: List[Dict[str, Any]] = []
    skipped_no_sell: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    seen_groups: set = set()
    for i, ba in enumerate(_affected_assets(conn, uid, batch_id)):
        broker, asset = ba["broker"], ba["asset"]
        # NETEO CROSS-BROKER: procesamos el PAR padre↔'· USD' como UN grupo, así
        # una compra dólar-MEP ruteada al sibling y su venta en pesos en el padre
        # se replayan juntas y netean (el fantasma de tenencia en el sibling no
        # sobrevive). Dedup: cada (par, activo) se procesa una sola vez aunque el
        # batch toque ambos brokers del par.
        pair = broker_pair(conn, uid, broker)
        gkey = (tuple(pair), asset)
        if gkey in seen_groups:
            continue
        seen_groups.add(gkey)

        events = _full_events(conn, uid, pair, asset)
        if not events:
            continue
        # Sin ventas → el orden FIFO no afecta nada (solo compras abiertas).
        if not any(e["operation_type"] == OP_SELL for e in events):
            skipped_no_sell.append(ba)
            continue
        # Frontera de seguridad: data manual no reproducible → no tocar.
        if not _is_safe_to_rebuild(conn, uid, pair, asset):
            skipped_manual.append(ba)
            log.info("rebuild_fifo: skip %s/%s (ops manuales no vinculadas)",
                     "+".join(pair), asset)
            continue

        # Moneda de referencia del grupo (fallback para ventas sin moneda
        # explícita). Usamos el broker PADRE del par (sin parent_broker_id); cada
        # evento igual trae su propia moneda, así que esto casi nunca aplica.
        _ph_pair = ",".join("?" * len(pair))
        br = conn.execute(
            f"""SELECT currency FROM brokers
                 WHERE user_id=? AND name IN ({_ph_pair}) AND parent_broker_id IS NULL
                 ORDER BY id ASC LIMIT 1""",
            (uid, *pair),
        ).fetchone()
        broker_currency = (br["currency"] if br else "USDT")
        if broker_currency == "USDT":
            broker_currency = "USD"
        if broker_currency not in ("ARS", "USD"):
            broker_currency = "USD"

        # Cancelamos los pares de conducto dólar-MEP de bonos (compra+venta del
        # mismo bono, igual nominal, cruce de moneda, ≤ventana) ANTES del FIFO: son
        # conversión de moneda, no tenencia. Si no, inflan/destruyen la tenencia
        # genuina del bono. `events` completo se usa para _clear_old_state (resetea
        # todos los links); el replay corre sobre los eventos sin conductos.
        grp_is_exchange = any(_is_exchange_broker(b) for b in pair)
        replay = _replay_asset(_cancel_conduit_pairs(events), broker_currency, tc_blue,
                               conn=conn, is_exchange=grp_is_exchange)
        # Los lotes/ops ya cargan su _broker desde el evento (neteo cross-broker):
        # un lote comprado en el sibling se reescribe al sibling, uno del padre al
        # padre. NO sobreescribimos con un broker de grupo.

        # Atomicidad por activo: SAVEPOINT. Si la reconstrucción de UN activo
        # falla a mitad (borró las ops viejas pero no escribió las nuevas), se
        # revierte SOLO ese activo a su estado previo y el resto del rebuild
        # sigue. Nunca dejamos un activo a medias.
        sp = f"rebuild_{i}"
        conn.execute(f"SAVEPOINT {sp}")
        try:
            old_buy_pos = _clear_old_state(conn, uid, pair, asset, events)
            _write_rebuilt(conn, uid, replay)
            _ensure_monthly_rows(conn, uid, replay["operations"])

            # Tombstones: compras consumidas del todo (sin lote abierto
            # sobreviviente) → dejar link a la posición vieja para que el revert
            # seguro siga bloqueando ("ya se vendió"). Las compras con lote
            # sobreviviente ya quedaron re-linkeadas por _write_rebuilt; si
            # quedaron con menos qty que la original, el pre-check de revert las
            # bloquea por el quantity-check.
            surviving_buys = {
                (l["batch_id"], l["raw_row_id"])
                for l in replay["open_lots"]
                if l.get("batch_id") and l.get("raw_row_id")
            }
            consumed = set(old_buy_pos.keys()) - surviving_buys
            if consumed:
                _write_buy_tombstones(conn, consumed, old_buy_pos)

            conn.execute(f"RELEASE {sp}")
            rebuilt.append({
                "broker": broker, "asset": asset,
                "open_lots": len(replay["open_lots"]),
                "sells": len(replay["operations"]),
            })
        except Exception as ex:
            conn.execute(f"ROLLBACK TO {sp}")
            conn.execute(f"RELEASE {sp}")
            log.warning("rebuild_fifo: %s/%s falló, se deja como estaba: %s",
                        broker, asset, ex)
            errors.append({"broker": broker, "asset": asset, "error": str(ex)})

    if rebuilt or errors:
        log.info("rebuild_fifo user=%s rebuilt=%d skipped_manual=%d errors=%d",
                 uid, len(rebuilt), len(skipped_manual), len(errors))
    return {
        "rebuilt": rebuilt,
        "skipped_manual": skipped_manual,
        "skipped_no_sell": skipped_no_sell,
        "errors": errors,
    }
