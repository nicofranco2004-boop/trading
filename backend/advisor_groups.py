"""Grupos de clientes del asesor — filtros guardados, DINÁMICOS.

Un grupo NO es una lista congelada: es una regla. Si mañana un cliente compra
Amazon entra solo a "Los de Amazon"; si vende, sale. Cero mantenimiento (la
idea de Nico: "un grupo con todos los que tengan Amazon / más de 20.000 / 30%
en liquidez / 30% en acciones argentinas").

Condiciones soportadas (todas opcionales, se combinan con Y):
  has_asset      → tiene ese ticker en cartera (cualquier broker)
  aum_min/max    → tamaño de la cartera en USD
  cash_pct_min   → % sin invertir (cash de cualquier moneda, a USD)
  class          → clase de activo + class_pct_min: 'ar_stock' | 'cedear' |
                   'bond' | 'fund' | 'crypto' | 'us_stock'
  losing         → los que están abajo del aportado

`excluded` permite sacar a mano a alguien puntual del resultado ("todos los de
Amazon menos Juan, que ya me dijo que no") sin romper el filtro.

La clasificación de activos NO inventa listas nuevas: reusa los universos que
ya usa el registro por chat (ai/trade_tickers.py) + el asset_type que persiste
el importador. Un activo que no cae en ninguno queda 'otro' y NO suma a ninguna
clase (mejor no clasificar que clasificar mal — el % tiene que ser defendible).
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("advisor_groups")

CLASSES = ("ar_stock", "cedear", "bond", "fund", "crypto", "us_stock")
CLASS_LABEL = {
    "ar_stock": "acciones argentinas", "cedear": "CEDEARs", "bond": "bonos",
    "fund": "fondos (FCI)", "crypto": "cripto", "us_stock": "acciones de EE.UU.",
}
MAX_GROUPS = 30


def classify(asset: str, asset_type: str = None) -> str:
    """Clase de un activo. El asset_type del importador manda cuando es
    inequívoco; si no, se resuelve por los universos de tickers conocidos."""
    a = (asset or "").upper().strip()
    if not a:
        return "otro"
    if a.startswith("FCI:"):
        return "fund"
    t = (asset_type or "").upper()
    if t == "CEDEAR":
        return "cedear"
    if t in ("BOND", "LETRA", "ON"):
        return "bond"
    if t in ("FUND", "FCI"):
        return "fund"
    if t == "CRYPTO":
        return "crypto"
    base = a[:-3] if a.endswith(".BA") else a
    try:
        from ai.trade_tickers import (AR_STOCK_TICKERS, CEDEAR_TICKERS,
                                      CRYPTO_TICKERS, US_TICKERS)
    except Exception:
        return "otro"
    if base in CRYPTO_TICKERS:
        return "crypto"
    if base in AR_STOCK_TICKERS:
        return "ar_stock"
    if base in CEDEAR_TICKERS and a.endswith(".BA"):
        return "cedear"
    if base in US_TICKERS:
        return "us_stock"
    if base in CEDEAR_TICKERS:
        return "cedear"
    return "otro"


# ─── Persistencia ─────────────────────────────────────────────────────────────

def list_groups(conn, uid: int) -> list:
    rows = conn.execute(
        "SELECT id, name, rules, excluded, created_at FROM advisor_groups "
        "WHERE advisor_uid=? ORDER BY created_at ASC", (uid,)).fetchall()
    out = []
    for r in rows:
        try:
            rules = json.loads(r["rules"] or "{}")
        except Exception:
            rules = {}
        try:
            excl = json.loads(r["excluded"] or "[]")
        except Exception:
            excl = []
        out.append({"id": r["id"], "name": r["name"], "rules": rules,
                    "excluded": excl, "created_at": r["created_at"]})
    return out


def get_group(conn, uid: int, gid: int):
    for g in list_groups(conn, uid):
        if g["id"] == gid:
            return g
    return None


def normalize_rules(raw: dict) -> dict:
    """Deja SOLO condiciones conocidas y con valores usables. Un grupo sin
    ninguna condición válida no se guarda (sería 'todos', que ya es el roster)."""
    r = raw or {}
    out = {}
    a = (r.get("has_asset") or "").strip().upper()
    if a:
        out["has_asset"] = a[:24]
    for k in ("aum_min", "aum_max", "cash_pct_min", "class_pct_min"):
        v = r.get(k)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[k] = v
    cls = (r.get("class") or "").strip().lower()
    if cls in CLASSES:
        out["class"] = cls
        out.setdefault("class_pct_min", 1.0)   # "tiene algo de" si no dio %
    elif "class_pct_min" in out:
        out.pop("class_pct_min")               # % sin clase no significa nada
    if r.get("losing"):
        out["losing"] = True
    return out


def describe(rules: dict) -> str:
    """La regla en criollo — el asesor tiene que entender qué mira el grupo."""
    r = rules or {}
    bits = []
    if r.get("has_asset"):
        bits.append(f"tienen {r['has_asset']}")
    if r.get("aum_min"):
        bits.append(f"tienen más de US$ {r['aum_min']:,.0f}".replace(",", "."))
    if r.get("aum_max"):
        bits.append(f"tienen menos de US$ {r['aum_max']:,.0f}".replace(",", "."))
    if r.get("cash_pct_min"):
        bits.append(f"tienen {r['cash_pct_min']:.0f}% o más sin invertir")
    if r.get("class"):
        bits.append(f"tienen {r.get('class_pct_min', 1):.0f}% o más en {CLASS_LABEL[r['class']]}")
    if r.get("losing"):
        bits.append("están perdiendo")
    return "Clientes que " + " y ".join(bits) if bits else "Todos tus clientes"


# ─── Evaluación ───────────────────────────────────────────────────────────────

def client_profiles(conn, uid: int, price_cache: dict = None) -> dict:
    """{client_uid: perfil} con lo que necesitan las condiciones: valor total,
    cash, y cuánto pesa cada clase de activo. Usa la MISMA valuación que el
    libro para que los % no discutan con el resto de la app."""
    import advisor_brief
    links = conn.execute(
        """SELECT ac.client_uid, ac.label, ac.phone, u.name FROM advisor_clients ac
           JOIN users u ON u.id = ac.client_uid
           WHERE ac.advisor_uid=? AND ac.status='active'""", (uid,)).fetchall()
    if not links:
        return {}
    labels = {r["client_uid"]: (r["label"] or r["name"] or f"Cliente {r['client_uid']}")
              for r in links}
    ids = list(labels)
    ph = ",".join("?" * len(ids))

    tc_blue, tc_mep = advisor_brief._fx(conn)
    try:
        import main
        valued, _sk = main._advisor_positions_valued(conn, ids, tc_blue, tc_mep)
    except Exception as ex:
        log.warning("groups: valuación falló: %s", ex)
        valued = []

    prof = {cid: {"client_uid": cid, "label": labels[cid], "phone": None,
                  "holdings": 0.0, "cash_usd": 0.0, "assets": set(),
                  "by_class": {c: 0.0 for c in CLASSES}} for cid in ids}
    for r in links:
        prof[r["client_uid"]]["phone"] = r["phone"]

    # Valor a mercado cuando lo hay. OJO: el motor del libro EXCLUYE las
    # posiciones sin precio conocido (correcto para el P&L), pero para AGRUPAR
    # eso haría desaparecer a un cliente entero por un ticker raro → acá el
    # costo es el PISO: una cartera vale al menos lo que costó.
    # El motor devuelve UNA FILA POR LOTE (positions tiene una fila por lote
    # abierto: así lo escribe el rebuild del importador, y el mismo activo en
    # dos brokers son dos filas más). Por eso se casa LOTE A LOTE y no por
    # activo: agregar por (cliente, activo) y después sumar ese agregado en
    # cada fila multiplicaba la cartera por la cantidad de lotes — con 3
    # compras de AAPL, US$ 15.000 se leían como US$ 45.000 y el cliente
    # entraba a un grupo "más de US$ 20.000" que no le corresponde.
    mkt = {}
    for v in valued:
        cid = v.get("client_uid")
        asset = (v.get("asset") or "").upper()
        if cid is not None and asset:
            mkt.setdefault((cid, asset, v.get("broker")), []).append(
                float(v.get("value_usd") or 0))

    for r in conn.execute(
            f"""SELECT p.user_id u, p.broker, p.asset, p.asset_type, p.invested,
                       p.commissions, COALESCE(b.currency,'ARS') bc
                FROM positions p LEFT JOIN brokers b
                  ON b.user_id=p.user_id AND b.name=p.broker
                WHERE p.user_id IN ({ph}) AND COALESCE(p.is_cash,0)=0""", ids).fetchall():
        cid = r["u"]
        p = prof.get(cid)
        if not p:
            continue
        asset = (r["asset"] or "").upper()
        if not asset:
            continue
        # Cada fila consume UN valor de mercado. Las que no tienen (el motor
        # excluye lo que no puede valuar) caen al costo, que es el piso.
        lots = mkt.get((cid, asset, r["broker"]))
        if lots:
            val = lots.pop()
        else:
            cost = float(r["invested"] or 0) + float(r["commissions"] or 0)
            val = cost / tc_mep if (r["bc"] == "ARS" and tc_mep) else cost
        p["holdings"] += val
        p["assets"].add(asset[:-3] if asset.endswith(".BA") else asset)
        cls = classify(asset, r["asset_type"])
        if cls in p["by_class"]:
            p["by_class"][cls] += val

    # Cash (cualquier moneda → USD al MEP) y el aportado para "están perdiendo".
    for r in conn.execute(
            f"""SELECT p.user_id u, p.invested inv, COALESCE(b.currency,'ARS') c
                FROM positions p LEFT JOIN brokers b
                  ON b.user_id=p.user_id AND b.name=p.broker
                WHERE p.user_id IN ({ph}) AND p.is_cash=1""", ids).fetchall():
        amt = float(r["inv"] or 0)
        usd = amt / tc_mep if (r["c"] == "ARS" and tc_mep) else amt
        if usd > 0 and r["u"] in prof:
            prof[r["u"]]["cash_usd"] += usd
    for r in conn.execute(
            f"""SELECT s.user_id, s.total_value, s.net_deposited FROM snapshots s
                WHERE s.user_id IN ({ph})
                  AND s.date = (SELECT MAX(s2.date) FROM snapshots s2
                                WHERE s2.user_id = s.user_id)""", ids).fetchall():
        if r["user_id"] in prof:
            prof[r["user_id"]]["snap_value"] = float(r["total_value"] or 0)
            prof[r["user_id"]]["net_deposited"] = float(r["net_deposited"] or 0)

    for p in prof.values():
        p["total_usd"] = p["holdings"] + p["cash_usd"]
        p["cash_pct"] = (p["cash_usd"] / p["total_usd"] * 100) if p["total_usd"] > 0 else 0.0
        p["class_pct"] = {c: (v / p["total_usd"] * 100 if p["total_usd"] > 0 else 0.0)
                          for c, v in p["by_class"].items()}
    return prof


def matches(profile: dict, rules: dict) -> bool:
    """¿Este cliente cumple TODAS las condiciones? Sin datos suficientes → NO
    entra (mejor un grupo corto que uno con clientes que no corresponden)."""
    r = rules or {}
    total = profile.get("total_usd") or 0.0
    if r.get("has_asset") and r["has_asset"] not in profile.get("assets", set()):
        return False
    if r.get("aum_min") is not None and not (total >= r["aum_min"]):
        return False
    if r.get("aum_max") is not None and not (0 < total <= r["aum_max"]):
        return False
    if r.get("cash_pct_min") is not None:
        if total <= 0 or profile.get("cash_pct", 0) < r["cash_pct_min"]:
            return False
    if r.get("class"):
        if total <= 0:
            return False
        if profile.get("class_pct", {}).get(r["class"], 0) < r.get("class_pct_min", 1):
            return False
    if r.get("losing"):
        nd = profile.get("net_deposited")
        sv = profile.get("snap_value")
        if nd is None or sv is None or nd <= 0 or sv >= nd:
            return False
    return True


def evaluate(conn, uid: int, rules: dict, excluded=None) -> list:
    """Clientes que caen en el grupo, con el dato que lo justifica."""
    prof = client_profiles(conn, uid)
    excl = set(excluded or [])
    out = []
    for cid, p in prof.items():
        if cid in excl or not matches(p, rules):
            continue
        out.append({
            "client_uid": cid, "label": p["label"], "phone": p.get("phone"),
            "total_usd": round(p["total_usd"]),
            "cash_pct": round(p["cash_pct"]),
            "class_pct": {c: round(v) for c, v in p["class_pct"].items() if v >= 1},
        })
    out.sort(key=lambda r: -r["total_usd"])
    return out
