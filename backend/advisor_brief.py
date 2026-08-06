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

import logging
from datetime import datetime, timedelta

log = logging.getLogger("advisor_brief")

KINDS = ("open", "close")


def _clientes(n: int) -> str:
    """'1 cliente' / '3 clientes' — nada de 'cliente(s)'."""
    n = int(n or 0)
    return f"{n} cliente" + ("" if n == 1 else "s")


def _today_art() -> str:
    """Fecha de HOY en horario argentino (UTC-3) — los snapshots se estampan así."""
    return (datetime.utcnow() - timedelta(hours=3)).date().isoformat()


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
    venir solo-blue (cron nocturno) → se busca la última CON mep."""
    try:
        import main
        _live = main._current_cedear_rate()   # medio, misma fuente que el snapshot
        if _live and float(_live) > 0:
            fx0 = conn.execute(
                "SELECT blue_venta FROM fx_rates_daily ORDER BY date DESC LIMIT 1").fetchone()
            return (float(fx0["blue_venta"]) if fx0 and fx0["blue_venta"] else 1415.0,
                    float(_live))
    except Exception:
        pass
    fx = conn.execute(
        "SELECT blue_venta, mep_venta FROM fx_rates_daily ORDER BY date DESC LIMIT 1"
    ).fetchone()
    tc_blue = float(fx["blue_venta"]) if fx and fx["blue_venta"] else 1415.0
    tc_mep = float(fx["mep_venta"]) if fx and fx["mep_venta"] else None
    if tc_mep is None:
        r = conn.execute("SELECT mep_venta FROM fx_rates_daily WHERE mep_venta IS NOT NULL "
                         "ORDER BY date DESC LIMIT 1").fetchone()
        tc_mep = float(r["mep_venta"]) if r else tc_blue
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


def build_brief(conn, uid: int, kind: str, price_cache: dict = None) -> dict:
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
                f"""SELECT s.user_id, s.date, s.total_value FROM snapshots s
                    WHERE s.user_id IN ({ph}) AND s.date < ?
                      AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                    WHERE s2.user_id = s.user_id AND s2.date < ?)""",
                ids + [_hoy, _hoy]).fetchall()}
            # Solo clientes con base: comparar vivo contra su último cierre.
            per = []
            for cid, now_v in live.items():
                s = snaps.get(cid)
                base = float(s["total_value"] or 0) if s else 0.0
                if base <= 0:
                    continue
                per.append({"cid": cid, "label": labels.get(cid), "now": now_v,
                            "delta": now_v - base, "pct": (now_v - base) / base * 100})
            if per:
                tot_now = sum(p["now"] for p in per)
                tot_delta = sum(p["delta"] for p in per)
                tot_base = tot_now - tot_delta
                out["day"] = {
                    "delta_usd": round(tot_delta, 2),
                    "pct": round(tot_delta / tot_base * 100, 2) if tot_base > 0 else None,
                    "clients_n": len(per),
                    "as_of_base": max((str(snaps[p["cid"]]["date"]) for p in per), default=None),
                }
                movers = sorted(per, key=lambda p: -p["pct"])
                _best, _worst = movers[0], movers[-1]
                _items = [{"label": _best["label"],
                           "detail": ("el mejor del día" if _best["pct"] >= 0
                                      else "el que menos cayó") + f": {_best['pct']:+.1f}%"}]
                if len(movers) > 1:
                    # Si nadie cerró en rojo, "el que más cayó" sería mentira.
                    _items.append({"label": _worst["label"],
                                   "detail": ("el que más cayó" if _worst["pct"] < 0
                                              else "el que menos subió") + f": {_worst['pct']:+.1f}%"})
                out["sections"].append({"title": "Cómo cerraron tus clientes", "items": _items})
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
                           "detail": f"US$ {flows['net_deposited_usd']:,.0f}".replace(",", ".")}]})

    if not out["sections"] and not out.get("day"):
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
        for uid in uids:
            try:
                if not brief_enabled(conn, uid, kind) or already_sent(conn, uid, kind, day):
                    skipped += 1
                    continue
                data = build_brief(conn, uid, kind, price_cache)
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
