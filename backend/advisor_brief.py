"""Brief del libro del asesor — dos entregas diarias ancladas al MERCADO.

Decisión de producto (Nico): un solo brief a la mañana temprano mostraría lo de
AYER, que el asesor ya vio. Por eso son dos, atados a la rueda argentina:

  • APERTURA (~11:00 ART, abre BYMA/CEDEARs) → EL PLAN DEL DÍA, mira adelante:
    a quién llamar hoy, quién tiene plata parada, qué eventos hay hoy de los
    activos del libro, invitaciones por vencer.

  • CIERRE (~17:15 ART, cerró BYMA) → EL RESULTADO DEL DÍA, mira atrás:
    cuánto se movió el libro hoy, mejores y peores del día, qué activo lo
    explica, y los flujos registrados.

El Δ del día del cierre NO puede salir de snapshots (el cron nocturno corre
23:59 → a las 17:15 el último snapshot es el de ayer). Se calcula valuando EN
VIVO con precios frescos y comparando contra ese último snapshot: exactamente
"cómo cerró hoy vs el cierre anterior". El fetch de precios se hace UNA vez por
corrida y se comparte entre todos los asesores (y de paso refresca
asset_last_price, que beneficia al resto de la app).
"""
from __future__ import annotations
from money_fmt import fmt_num

import logging
from datetime import datetime, timedelta

from fechas import hoy_art

log = logging.getLogger("advisor_brief")

KINDS = ("open", "close")


def _clientes(n: int) -> str:
    """'1 cliente' / '3 clientes' — nada de 'cliente(s)'."""
    n = int(n or 0)
    return f"{n} cliente" + ("" if n == 1 else "s")


def _today_art() -> str:
    """Fecha de HOY en horario argentino — los snapshots se estampan así.

    (Verificado en F3: desde que el cron sella con `fechas.hoy_art()`, esta
    premisa es cierta. Antes NO lo era y esta función construía sobre ella.)"""
    return hoy_art()


def tramo(base_iso: str, hoy_iso: str) -> dict:
    """De cuándo es la base contra la que se mide "hoy", y cómo decirlo.

    ⚠️ "HOY" SÓLO SI LA BASE ES EL CIERRE DE AYER. El Δ del cierre y las alertas
    comparan el valor en vivo contra el ÚLTIMO CIERRE MEDIDO de cada cliente, y ese
    cierre puede ser de hace varios días (el cron no lo midió, o sus fotos más
    nuevas son del import). Llamarle "hoy" a eso es publicar varios días de mercado
    como si fueran uno.

    Mismo criterio que el Dashboard del inversor (`computeDailyPnl` →
    `dayDiff`, `Dashboard.jsx`: "Hoy" / "Últimos N días"): no se descarta la base
    vieja —para un día no hace falta el borde de 5 días—, se ROTULA el tramo.

    {"dias": N, "rotulo": "hoy" | "en los últimos N días",
     "desde": "desde el cierre de ayer" | "desde el cierre de hace N días"}
    """
    from datetime import date as _date
    n = max(1, (_date.fromisoformat(str(hoy_iso)[:10])
                - _date.fromisoformat(str(base_iso)[:10])).days)
    if n == 1:
        return {"dias": 1, "rotulo": "hoy", "desde": "desde el cierre de ayer"}
    return {"dias": n, "rotulo": f"en los últimos {n} días",
            "desde": f"desde el cierre de hace {n} días"}


def aportado_vivo(conn, cid: int):
    """Aportado neto ACTUAL del cliente (misma fuente que el snapshot). None si no
    se puede calcular → en ese caso no se descuenta nada (conservador).

    Lo usan el mail de cierre y la alerta de movimiento: los dos comparan el valor
    en vivo contra el último cierre, y los dos tienen que descontar la plata que
    entró o salió en el medio. Vivía sólo en la alerta; el mail no descontaba."""
    try:
        from snapshots_job import compute_net_deposited_db
        return float(compute_net_deposited_db(conn, cid, include_baseline=True) or 0.0)
    except Exception:
        return None


def advisor_uids(conn) -> list:
    """Asesores con el plan activo (tier literal, sin el bypass de admin)."""
    try:
        rows = conn.execute(
            "SELECT id FROM users WHERE tier='advisor' AND COALESCE(managed_by,0)=0"
        ).fetchall()
        return [r["id"] for r in rows]
    except Exception:
        return []


def brief_enabled(conn, uid: int, kind: str) -> bool:
    """Preferencia del asesor (default: ambos activos)."""
    col = "brief_open" if kind == "open" else "brief_close"
    try:
        row = conn.execute(
            f"SELECT {col} v FROM advisor_profile WHERE advisor_uid=?", (uid,)
        ).fetchone()
        return True if not row or row["v"] is None else bool(row["v"])
    except Exception:
        return True


def already_sent(conn, uid: int, kind: str, day: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM advisor_brief_log WHERE advisor_uid=? AND kind=? AND date=?",
            (uid, kind, day),
        ).fetchone() is not None
    except Exception:
        return False


def mark_sent(conn, uid: int, kind: str, day: str):
    conn.execute(
        "INSERT OR IGNORE INTO advisor_brief_log (advisor_uid, kind, date, sent_at) "
        "VALUES (?,?,?,datetime('now'))", (uid, kind, day))


# ─── Valuación en vivo del libro (para el Δ del día del cierre) ───────────────

def live_book_values(conn, client_ids: list, price_cache: dict) -> dict:
    """{client_uid: valor_usd_ahora} valuando posiciones con precios FRESCOS.

    `price_cache` se comparte entre asesores dentro de la misma corrida: los
    símbolos ya fetcheados no se vuelven a pedir. Devuelve {} si algo falla
    (el brief se manda igual, sin la sección del delta — nunca con números
    inventados)."""
    if not client_ids:
        return {}
    try:
        import main
        from snapshots_job import (build_price_symbols, compute_broker_value_usd,
                                   fetch_prices_for_symbols, persist_last_prices,
                                   read_last_prices)
    except Exception as ex:
        log.warning("brief: import de motores falló: %s", ex)
        return {}

    ph = ",".join("?" * len(client_ids))
    positions = [dict(r) for r in conn.execute(
        f"SELECT * FROM positions WHERE user_id IN ({ph})", client_ids).fetchall()]
    brokers = [dict(r) for r in conn.execute(
        f"SELECT * FROM brokers WHERE user_id IN ({ph})", client_ids).fetchall()]
    if not positions:
        return {}

    # Los símbolos se arman POR CLIENTE: build_price_symbols mira los nombres de
    # broker sin user_id, así que con la unión un 'Balanz' ARS de un cliente
    # arrastraba al 'Balanz' USD de otro → clave de precio equivocada y una
    # caída FANTASMA (audit). Cada cliente resuelve con SUS propios brokers.
    pos_by_client, brk_by_client = {}, {}
    for p in positions:
        pos_by_client.setdefault(p["user_id"], []).append(p)
    for b in brokers:
        brk_by_client.setdefault(b["user_id"], []).append(b)
    sym_by_client = {cid: build_price_symbols(pl, brk_by_client.get(cid, []))
                     for cid, pl in pos_by_client.items()}
    symbols = sorted({s for syms in sym_by_client.values() for s in syms})
    missing = [s for s in symbols if s not in price_cache]
    if missing:
        try:
            fresh = fetch_prices_for_symbols(missing, getattr(main, "CRYPTO_YF", {})) or {}
            got = {k: v for k, v in fresh.items() if v is not None}
            if got:
                persist_last_prices(conn, got)   # beneficia al resto de la app
            # Solo los precios REALES entran al cache compartido: cachear un
            # None propagaba el hueco a los demás asesores de la corrida.
            price_cache.update(got)
        except Exception as ex:
            log.warning("brief: fetch de precios falló: %s", ex)
    prices = {s: price_cache.get(s) for s in symbols}
    # Huecos → último precio conocido (mismo criterio que el snapshot).
    try:
        known = read_last_prices(conn, [s for s in symbols if prices.get(s) is None])
        for s, p in (known or {}).items():
            if prices.get(s) is None:
                prices[s] = p
    except Exception:
        pass

    tc_blue, tc_mep = _fx(conn)
    by_broker: dict = {}
    for p in positions:
        by_broker.setdefault((p["user_id"], p.get("broker")), []).append(p)
    bmeta = {(b["user_id"], b["name"]): b for b in brokers}
    out: dict = {}
    for (cid, bname), plist in by_broker.items():
        b = bmeta.get((cid, bname)) or {}
        try:
            r = compute_broker_value_usd(plist, prices, (b.get("currency") or "ARS"),
                                         tc_blue, bname, cedear_rate=tc_mep)
            out[cid] = out.get(cid, 0.0) + float(r.get("value") or 0)
        except Exception:
            continue
    return out


def _fx(conn):
    """(blue, mep) con la MISMA tasa que usa el snapshot nocturno: el MEP MEDIO
    ((compra+venta)/2, vía _val_rate), no la punta de venta — si no, el valor
    vivo y el snapshot se valúan con dólares distintos y aparece una pérdida
    fantasma de ~0,7% todos los días (audit). Fallback: la fila más nueva puede
    venir solo-blue (cron nocturno) → se busca la última CON mep.

    ⚠️ Este docstring decía esto desde antes, y el camino de arriba ya usaba el
    medio — pero los DOS fallbacks de abajo seguían leyendo la punta de venta de
    `fx_rates_daily`, que era la única que había guardada. Con la punta compradora
    en la tabla, los tres caminos derivan el mismo medio (`fx.SQL_MEDIO_*`).

    El alias del módulo se llama `_fxmod` y no `_fx` a propósito: `_fx` es el
    nombre de ESTA función."""
    import fx as _fxmod          # afuera del try: los fallbacks de abajo lo usan
    try:
        import main
        _live = main._current_cedear_rate()   # medio, misma fuente que el snapshot
        if _live and float(_live) > 0:
            # El PUNTO MEDIO, con la expresión compartida: `_current_cedear_rate`
            # de arriba ya devuelve el medio, y leer acá la punta de venta ponía
            # las dos patas del brief en bases distintas.
            fx0 = conn.execute(
                f"SELECT {_fxmod.SQL_MEDIO_BLUE} AS blue FROM fx_rates_daily "
                "ORDER BY date DESC LIMIT 1").fetchone()
            return (float(fx0["blue"]) if fx0 and fx0["blue"] else 1415.0,
                    float(_live))
    except Exception:
        pass
    fx = conn.execute(
        f"SELECT {_fxmod.SQL_MEDIO_BLUE} AS blue, {_fxmod.SQL_MEDIO_MEP} AS mep "
        "FROM fx_rates_daily ORDER BY date DESC LIMIT 1"
    ).fetchone()
    tc_blue = float(fx["blue"]) if fx and fx["blue"] else 1415.0
    tc_mep = float(fx["mep"]) if fx and fx["mep"] else None
    if tc_mep is None:
        r = conn.execute(f"SELECT {_fxmod.SQL_MEDIO_MEP} AS mep FROM fx_rates_daily "
                         "WHERE mep_venta IS NOT NULL "
                         "ORDER BY date DESC LIMIT 1").fetchone()
        tc_mep = float(r["mep"]) if r else tc_blue
    return tc_blue, tc_mep


# ─── Armado del brief ─────────────────────────────────────────────────────────

_EVENT_LABELS = {
    "earnings": "Reporte trimestral",
    "ex_dividend": "Ex-dividendo",
    "payment_date": "Pago de dividendo",
    "split": "Split de acciones",
    "bond_coupon": "Cupón de bono",
    "bond_amort": "Amortización",
    "bond_coupon_amort": "Cupón + amortización",
    "bond_maturity": "Vencimiento de bono",
}


def _event_label(t: str) -> str:
    """Mismas etiquetas que ve el usuario en la app (upcomingEvents.js)."""
    return _EVENT_LABELS.get(t or "", t or "Evento")


def build_brief(conn, uid: int, kind: str, price_cache: dict = None,
                market_ctx: list = None) -> dict:
    """Contenido del brief. Devuelve {} si el asesor no tiene nada que contar
    (sin clientes) — el caller no manda email vacío."""
    import main
    if kind not in KINDS:
        raise ValueError("kind inválido")

    links = conn.execute(
        """SELECT ac.client_uid, ac.label, u.name FROM advisor_clients ac
           JOIN users u ON u.id = ac.client_uid
           WHERE ac.advisor_uid=? AND ac.status='active'""", (uid,)).fetchall()
    if not links:
        return {}
    labels = {r["client_uid"]: (r["label"] or r["name"] or f"Cliente {r['client_uid']}")
              for r in links}
    ids = list(labels)

    try:
        book = main.advisor_book(uid=uid) or {}
    except Exception as ex:
        log.warning("brief: advisor_book uid=%s falló: %s", uid, ex)
        book = {}
    aum = (book.get("aum") or {})
    out = {"kind": kind, "date": _today_art(), "clients_n": len(ids),
           "aum_total_usd": aum.get("total_usd"), "sections": []}

    if kind == "open":
        # 0. EL MERCADO. Va arriba de todo y es lo primero que se lee.
        #
        # Decisión de producto (Nico, 2026-09-15): el resumen de mercado vive
        # ACÁ ADENTRO y no en un mail aparte. El asesor ya recibe este mail a
        # las 11:00 en punto, que es la misma hora del resumen del inversor:
        # mandarle dos mails de Rendi en el mismo minuto, los dos sobre la
        # mañana, es la forma más rápida de que deje de abrir los dos.
        #
        # Y el orden importa: primero el mercado, después a quién llamar. Al
        # revés la llamada llega sin tema de conversación, y cruzar la noticia
        # con el cliente a mano es justamente el trabajo que el mail le tiene
        # que ahorrar.
        try:
            import market_brief
            holders = main._advisor_ticker_holders(conn, uid) or {}
            desde = market_brief._news_window_start(out["date"])
            # El contexto de mercado es el MISMO para todos: si la corrida ya
            # lo leyó, llega por parámetro y no se vuelve a consultar.
            ctx = (market_ctx if market_ctx is not None
                   else market_brief.market_context(conn, desde))
            # ⚠️ ORDENADOS POR CUÁNTOS CLIENTES LO TIENEN, no alfabéticamente.
            # El corte a 20 no es teórico: un asesor con 50 activos en el libro
            # pierde 30, y con orden alfabético pierde SIEMPRE los mismos —los
            # del final del abecedario— mientras que los de la A entran todos
            # los días. Lo que le importa es el activo que toca a más clientes,
            # que es el que va a tener que explicar en más llamadas.
            tickers = sorted(holders, key=lambda t: (-len(holders.get(t) or []), t)
                             )[:market_brief.MAX_TICKERS]
            news = market_brief._news_for(conn, tickers, desde) if tickers else []
            if ctx:
                nar = market_brief.narrate(ctx, news, tickers, holders=holders)
                if nar:
                    out["narrative"] = {
                        "titular": nar.titular,
                        "mercado": list(nar.mercado),
                        "tu_cartera": list(nar.tu_cartera),
                    }
        except Exception as ex:
            # El brief sale igual sin la parte de mercado: lo de abajo —a quién
            # llamar, los eventos del día— es lo que el asesor no puede
            # conseguir en ningún otro lado.
            log.warning("brief mercado uid=%s: %s", uid, ex)

        # 1. A quién llamar hoy (las colas del libro, ya en criollo)
        queues = (book.get("queues") or [])[:5]
        if queues:
            out["sections"].append({
                "title": "Para llamar hoy",
                "items": [{"label": q.get("label"),
                           "detail": "; ".join(r.get("detail", "") for r in (q.get("reasons") or [])[:2]),
                           "client_uid": q.get("client_uid"), "phone": q.get("phone")}
                          for q in queues]})
        # 2. Eventos de HOY de activos que tienen sus clientes
        try:
            holders = main._advisor_ticker_holders(conn, uid) or {}
            if holders:
                tph = ",".join("?" * len(holders))
                evs = conn.execute(
                    f"""SELECT ticker, event_type, event_date FROM financial_events
                        WHERE ticker IN ({tph}) AND event_date = ?
                        ORDER BY ticker LIMIT 6""",
                    list(holders.keys()) + [out["date"]]).fetchall()
                if evs:
                    out["sections"].append({
                        "title": "Eventos de hoy",
                        "items": [{"label": e["ticker"],
                                   "detail": f"{_event_label(e['event_type'])} · lo "
                                             f"{'tiene' if len(holders.get(e['ticker']) or []) == 1 else 'tienen'} "
                                             f"{_clientes(len(holders.get(e['ticker']) or []))}"}
                                  for e in evs]})
        except Exception as ex:
            log.warning("brief eventos uid=%s: %s", uid, ex)
        # 3. Invitaciones por vencer (≤2 días)
        try:
            pend = conn.execute(
                f"""SELECT user_id, email, expires_at FROM advisor_claim_tokens
                    WHERE advisor_uid=? AND used_at IS NULL
                      AND expires_at > datetime('now')
                      AND expires_at <= datetime('now', '+2 days')""", (uid,)).fetchall()
            if pend:
                out["sections"].append({
                    "title": "Invitaciones por vencer",
                    "items": [{"label": labels.get(p["user_id"], "Cliente"),
                               "detail": f"el link a {p['email']} vence en menos de 2 días"}
                              for p in pend[:5]]})
        except Exception:
            pass

    else:  # close
        # Δ del día: valuación EN VIVO vs el último snapshot de cada cliente.
        cache = price_cache if price_cache is not None else {}
        live = live_book_values(conn, ids, cache)
        if live:
            ph = ",".join("?" * len(ids))
            # Se excluye HOY: el snapshot intradiario que escribe el browser
            # haría que "cómo cerró hoy" se compare contra un valor de hoy.
            _hoy = _today_art()
            snaps = {r["user_id"]: r for r in conn.execute(
                f"""SELECT s.user_id, s.date, s.total_value, s.net_deposited FROM snapshots s
                    WHERE s.user_id IN ({ph}) AND s.date < ?
                      AND COALESCE(s.apto, CASE WHEN COALESCE(s.source,'') IN ('import','mtm_backfill') THEN 0 ELSE 1 END) = 1
                    -- ⚠️ POR LA COLUMNA `apto`, NO POR EL STRING `source` (ronda 11).
                    -- El filtro por string se equivocaba en las DOS direcciones sobre
                    -- la misma fila: (a) una fila LEGACY del import —source NULL, fin
                    -- de mes, valuada al costo— pasaba igual, y (b) una reconstrucción
                    -- BUENA de cobertura 0,99 era rechazada. `apto` lo estampa quien
                    -- escribe la fila y es el mismo dato que usan la curva y Reportes.
                    -- El COALESCE cubre la ventana de un deploy donde el código llega
                    -- antes de que la migración estampe: ahí cae a la heurística vieja,
                    -- que es el lado seguro del error.
                    -- ⚠️ NI LA CADENA CONTABLE NI LA RECONSTRUCCIÓN. Esta base se
                    -- resta contra el valor VIVO (mercado), así que si sale de una
                    -- fila fabricada al costo por el import —o de una foto de fin de
                    -- mes reconstruida— el "%%" no mide el día: mide la brecha entre
                    -- dos formas de medir. Es el mismo defecto que publicaba −47,26%
                    -- en el informe firmado (ronda 10, A-2), en otra superficie del
                    -- asesor. Es el criterio `mtm_only=True` que ya usan los otros
                    -- lectores que comparan contra un live (main.py:17330).
                      AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                    WHERE s2.user_id = s.user_id AND s2.date < ?
                                      AND COALESCE(s2.apto, CASE WHEN COALESCE(s2.source,'') IN ('import','mtm_backfill') THEN 0 ELSE 1 END) = 1)""",
                ids + [_hoy, _hoy]).fetchall()}
            # Solo clientes con base: comparar vivo contra su último cierre.
            # ⚠️ LA COTA DE CORDURA DEL MOTOR, QUE ACÁ FALTABA (F6).
            #
            # Los filtros de arriba cuidan la CALIDAD DE LA FOTO (`apto`, ni import
            # ni reconstrucción) pero ninguno mira el NÚMERO que sale. Un valor vivo
            # que salta ×5 contra la última foto —un precio roto, un activo que se
            # duplicó por un split mal leído— publicaba ese salto como el % del día.
            #
            # Y acá el error se amplifica: `movers` ORDENA por `pct`, así que el
            # cliente con el dato roto sale primero y el mail del asesor lo anuncia
            # como «el mejor del día». El informe de la auditoría lo marca como el
            # caso más caro de los once: en el informe firmado el guard SÍ existe
            # (`_cortes_adentro`), y en este mail no.
            #
            # ⚠️ LOS DEPÓSITOS SE DESCUENTAN, igual que en la alerta de movimiento
            # (`advisor_alerts.evaluate`). Sin esto, un cliente que depositó 10.000
            # salía "el mejor del día: +105%": la plata que entró no es el mercado.
            # Con una base de varios días el error crece, porque entran los
            # depósitos de todos esos días.
            # Es la MISMA función del motor, importada y no copiada.
            from twr import leg_dudoso as _leg_dudoso_brief
            per = []
            for cid, now_v in live.items():
                s = snaps.get(cid)
                base = float(s["total_value"] or 0) if s else 0.0
                if base <= 0:
                    continue
                _nd_now = aportado_vivo(conn, cid)
                flow = (_nd_now - float(s["net_deposited"] or 0)) if _nd_now is not None else 0.0
                if _leg_dudoso_brief(base, now_v, flow):
                    continue
                delta = (now_v - flow) - base
                per.append({"cid": cid, "label": labels.get(cid), "now": now_v,
                            "base": base, "delta": delta, "pct": delta / base * 100,
                            "base_date": str(s["date"])[:10],
                            **tramo(str(s["date"]), _hoy)})
            # ⚠️ EL TOTAL ES DE LOS CLIENTES QUE COMPARTEN EL TRAMO MÁS CORTO. El Δ se
            # mide contra el último cierre de cada cliente, y ese cierre puede ser de
            # hace días (el cron no lo pudo valuar, o sus fotos nuevas son del
            # import). Sumar todo en un solo número obliga a rotularlo con el tramo
            # más largo: un solo cliente frenado 40 días convertía el "hoy" de todo el
            # libro en "en los últimos 40 días", con el 98% del número de un día.
            # Los que se miden contra un cierre más viejo van aparte, cada uno con
            # SU rótulo — no se esconden, pero tampoco le cambian el nombre al total.
            _corto = min((p["dias"] for p in per), default=None)
            viejos = [p for p in per if p["dias"] != _corto]
            per = [p for p in per if p["dias"] == _corto]
            if per:
                tot_delta = sum(p["delta"] for p in per)
                tot_base = sum(p["base"] for p in per)
                _t = tramo(per[0]["base_date"], _hoy)
                out["day"] = {
                    "delta_usd": round(tot_delta, 2),
                    "pct": round(tot_delta / tot_base * 100, 2) if tot_base > 0 else None,
                    "clients_n": len(per),
                    # La base de todos los que entran al total (comparten tramo).
                    "as_of_base": per[0]["base_date"],
                    "dias": _t["dias"],
                    "rotulo": _t["rotulo"],
                    "clients_otro_tramo": len(viejos),
                }
                movers = sorted(per, key=lambda p: -p["pct"])
                _best, _worst = movers[0], movers[-1]

                def _mover(p, mejor: bool) -> str:
                    # Cada cliente con SU tramo: "del día" sólo si su base es el
                    # cierre de ayer. Un cliente medido contra hace 3 días no fue
                    # "el mejor del día", fue el mejor de sus 3 días.
                    un_dia = p["dias"] == 1
                    if mejor:
                        q = (("el mejor del día" if un_dia else "el mejor")
                             if p["pct"] >= 0 else "el que menos cayó")
                    else:
                        # Si nadie cerró en rojo, "el que más cayó" sería mentira.
                        q = "el que más cayó" if p["pct"] < 0 else "el que menos subió"
                    return (f"{q}: {fmt_num(p['pct'], 1, signed=True)}%"
                            + ("" if un_dia else f" {p['rotulo']}"))

                _items = [{"label": _best["label"], "detail": _mover(_best, True)}]
                if len(movers) > 1:
                    _items.append({"label": _worst["label"], "detail": _mover(_worst, False)})
                out["sections"].append({"title": "Cómo cerraron tus clientes", "items": _items})
            if viejos:
                # Los mayores movimientos primero: es a quién conviene mirar.
                viejos.sort(key=lambda p: -abs(p["pct"]))
                out["sections"].append({
                    "title": "Comparados contra un cierre más viejo",
                    "items": [{"label": p["label"],
                               "detail": f"{fmt_num(p['pct'], 1, signed=True)}% {p['rotulo']}"
                                         f" (su último cierre a precio de mercado es de hace {p['dias']} días)"}
                              for p in viejos[:5]]})
        # Qué activo pesa hoy en el libro (motor estrella — P&L acumulado)
        star = (book.get("star") or {})
        losers = (star.get("losers") or [])[:2]
        winners = (star.get("winners") or [])[:2]
        items = []
        for w in winners:
            items.append({"label": w.get("asset"),
                          "detail": f"en verde en {_clientes(w.get('clients_green') or w.get('clients') or 0)}"})
        for l in losers:
            items.append({"label": l.get("asset"),
                          "detail": f"en rojo en {_clientes(l.get('clients_red') or l.get('clients') or 0)}"})
        if items:
            out["sections"].append({"title": "Los activos que mandan en tu libro",
                                    "items": items})
        flows = (book.get("flows_month") or {})
        if flows.get("net_deposited_usd"):
            out["sections"].append({
                "title": "Movimientos de plata (este mes)",
                "items": [{"label": "Aportes − retiros",
                           "detail": f"US$ {fmt_num(flows['net_deposited_usd'], 0)}"}]})

    # Nunca un mail vacío. ⚠️ `narrative` ENTRA EN LA CUENTA desde que el de
    # apertura lleva resumen de mercado: sin esto, un asesor sin nadie a quien
    # llamar y sin eventos hoy se quedaba sin el mail entero, aunque el resumen
    # del mercado —que es la parte que SIEMPRE tiene contenido— estuviera
    # escrito y pago. Es el guard que decide si el mail sale, y agregarle una
    # sección al mail sin tocarlo lo deja mintiendo sobre qué es "vacío".
    if not out["sections"] and not out.get("day") and not out.get("narrative"):
        return {}
    return out


# ─── Corrida (la dispara el cron externo) ────────────────────────────────────

def run_briefs(kind: str, get_db, only_uid: int = None) -> dict:
    """Arma y manda el brief a todos los asesores que lo tengan activo.
    Idempotente por (asesor, tipo, día): re-correr el cron no duplica emails."""
    if kind not in KINDS:
        raise ValueError("kind inválido")
    day = _today_art()
    price_cache: dict = {}
    sent = skipped = failed = 0
    conn = get_db()
    try:
        uids = [only_uid] if only_uid else advisor_uids(conn)
        # El contexto de mercado es el MISMO para todos los asesores: se lee una
        # vez por corrida, igual que el price_cache. Sólo para el de apertura,
        # que es el único que lleva resumen de mercado.
        market_ctx = None
        if kind == "open" and uids:
            try:
                import main as _main
                import market_brief
                # ⚠️ PRIMERO SE TRAEN LAS NOTICIAS, DESPUÉS SE LEEN. El brief del
                # asesor sólo LEÍA, apoyado en que el cron del inversor las
                # traía — y ese cron se va temprano si nadie tiene el resumen
                # prendido, que es el estado de fábrica. El asesor terminaba
                # recibiendo un «resumen del mercado» armado con lo que quedó de
                # la última vez que alguien abrió la app.
                market_brief.refresh_market_news()
                # Y los activos de TODOS los libros, en una sola pasada: dos
                # asesores con GGAL lo buscan una vez.
                union = set()
                for uid in uids:
                    union |= set(_main._advisor_ticker_holders(conn, uid) or {})
                if union:
                    market_brief._refresh_news_for(sorted(union), get_db)
                market_ctx = market_brief.market_context(
                    conn, market_brief._news_window_start(day))
            except Exception as ex:
                log.warning("brief: contexto de mercado no disponible: %s", ex)
        for uid in uids:
            try:
                if not brief_enabled(conn, uid, kind) or already_sent(conn, uid, kind, day):
                    skipped += 1
                    continue
                data = build_brief(conn, uid, kind, price_cache, market_ctx)
                if not data:
                    skipped += 1
                    continue
                row = conn.execute("SELECT email, name FROM users WHERE id=?", (uid,)).fetchone()
                if not row or not row["email"]:
                    skipped += 1
                    continue
                from billing import emails
                ok = emails.send_advisor_brief(to=row["email"], user_name=(row["name"] or ""),
                                               brief=data)
                if ok:
                    mark_sent(conn, uid, kind, day)
                    conn.commit()
                    sent += 1
                else:
                    failed += 1
            except Exception as ex:
                failed += 1
                log.error("brief %s uid=%s falló: %s", kind, uid, ex)
        return {"kind": kind, "date": day, "sent": sent, "skipped": skipped, "failed": failed}
    finally:
        conn.close()
