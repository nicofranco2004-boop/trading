"""pricing.fci — auto-pricing de Fondos Comunes de Inversión (FCI) argentinos.

Fuente primaria: ArgentinaDatos (api.argentinadatos.com), capa JSON pública
sobre CAFCI. Devuelve el valor de cuotaparte diario por fondo.

IMPORTANTE — escala: el campo `vcp` de la API es el valor por 1000 cuotapartes,
NO el precio por cuotaparte. El precio unitario = vcp / 1000 (verificado: la
identidad vcp*ccp == patrimonio*1000 se cumple en todos los fondos). Guardamos
el precio YA dividido para que el resto de la app lo trate como cualquier precio.

Diseño:
  • fci_catalog: subset CURADO de fondos elegibles por el usuario (familia FIMA
    de Galicia + money market grandes de otros emisores). El nombre exacto de
    ArgentinaDatos (`ad_name`) es la única clave de match y vive en una columna
    — si CAFCI renombra un fondo, se arregla ahí, no en el código.
  • fci_prices: precio por cuotaparte por símbolo, refrescado 1x/día. get_prices
    (main.py) lee de acá para símbolos con prefijo 'FCI:'.

Las fuentes son comunitarias/no oficiales (sin SLA). Degradación con gracia: si
el fetch falla, NO se borran los precios viejos — se sirve el último bueno con
su as_of_date.
"""
from __future__ import annotations
import json
import logging
import re
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timedelta

log = logging.getLogger("pricing.fci")

FCI_PREFIX = "FCI:"
AD_BASE = "https://api.argentinadatos.com/v1/finanzas/fci"
AD_CATEGORIES = ["mercadoDinero", "rentaFija", "rentaVariable", "rentaMixta", "otros"]
_UA = {"User-Agent": "Mozilla/5.0 (Rendi FCI pricing)"}

# Clases retail que seedeamos de la familia FIMA. Las institucionales muertas
# (E/N/L/etc., con patrimonio ~0) se omiten para no ensuciar el selector.
FIMA_CLASSES = {"A", "B", "C", "P"}

# Money market de otros emisores que entran al catálogo (match por prefijo de
# nombre exacto de ArgentinaDatos). Se incluye cualquier clase disponible.
# Curado por tamaño (patrimonio) — los fondos donde el retail parkea pesos.
MM_ALLOWLIST = [
    "Mercado Fondo",               # Mercado Pago / Mercado Fondos
    "Super Ahorro $",              # Santander
    "FBA Renta Pesos",             # BBVA
    "Pionero Pesos Plus",
    "Pionero Pesos",
    "Alpha Pesos",                 # ICBC
    "Pellegrini Renta Pesos",      # Banco Nación
    "1822 Raices Ahorro Pesos",    # Banco Provincia
    "Delta Pesos",
    "Premier Renta CP en Pesos",
    "Allaria Ahorro",
    "MEGAQM Pesos",
    "Max Money Market",
]

# Fondos propietarios de brokers AR (Cocos, Balanz…) que entran por IMPORT y que
# el importador mapea desde su ticker (COCOA, COCOACCA…) — ver importing/fci_map.py.
# Separado de MM_ALLOWLIST porque NO son money market: hay rentaVariable /
# rentaFija (USD) / rentaMixta. Cada base-name acá se seedea en TODAS sus clases
# (el importador elige la clase exacta). Nombres EXACTOS de ArgentinaDatos,
# verificados 2026-06-25. Sólo se incluyen fondos confirmados con alta confianza
# (los no confirmables — p.ej. "Cocos Pesos Plus", que no figura en la fuente —
# quedan fuera y se valúan al costo, sin inventar precio).
BROKER_FCI_ALLOWLIST = [
    "Cocos Ahorro",            # mercadoDinero ARS
    "Cocos Ahorro Dólares",    # rentaFija USD
    "Cocos Dólares Plus",      # rentaFija USD
    "Cocos Rendimiento",       # rentaMixta ARS
    "Cocos Acciones",          # rentaVariable ARS
    "SBS Acciones Argentina",  # rentaVariable ARS (vía plataforma Cocos)
    "IEB Renta Fija Dólar",    # rentaFija USD (IEB) — reportado por user 2026-06-25
    "Balanz Capital Ahorro",   # rentaFija ARS (Balanz) — ticker BCAHA, confirmado 2026-07-02
    "Balanz Ahorro en Dólares",       # rentaFija USD (Balanz) — ticker BAHUSDA, VCP 1417,66 conf. 2026-07-05
    "Balanz Capital Estrategia I USD",  # rentaFija USD (Balanz) — ticker ESTRA1A, VCP 1163,54 conf. 2026-07-05
    "Balanz Capital Estrategia III USD",  # rentaFija USD (Balanz) — ticker ESTRA3A, VCP 1069,96 conf. 2026-07-10
    "Balanz Money Market USD",         # mercadoDinero USD (Balanz) — ticker BCMMUSDA, VCP 1024,74 conf. 2026-07-10
    "Balanz Acciones",         # rentaVariable ARS (Balanz) — reportado por user 2026-07-08; VCP Clase A 163.681,18 (→163,68) vs ArgentinaDatos, fecha 2026-07-08
    "Adcap Acciones",          # rentaVariable ARS (IOL) — ticker CONIOLA, VCP 193.077 confirmado 2026-07-02
]


# ── HTTP ────────────────────────────────────────────────────────────────────
def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers=_UA, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_all_funds():
    """Lista de dicts {fondo, fecha, vcp, ccp, patrimonio, _cat} de las 5
    categorías. Levanta RuntimeError si NINGUNA categoría respondió."""
    out, ok = [], 0
    for cat in AD_CATEGORIES:
        try:
            rows = _http_json(f"{AD_BASE}/{cat}/ultimo")
            if isinstance(rows, list):
                for r in rows:
                    r["_cat"] = cat
                out.extend(rows)
                ok += 1
        except Exception as ex:
            log.warning("FCI fetch categoría %s falló: %s", cat, ex)
    if ok == 0:
        raise RuntimeError("ArgentinaDatos no respondió en ninguna categoría")
    return out


# ── Parsing de nombres ──────────────────────────────────────────────────────
def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))


def _base_name(name):
    """Nombre sin el sufijo de clase: 'Fima Premium - Clase A' → 'Fima Premium'."""
    return re.sub(r"\s*-\s*Clase\s+[A-Z0-9].*$", "", name or "", flags=re.I).strip()


def _parse_clase(name):
    m = re.search(r"Clase\s+([A-Z0-9]+)\s*$", name or "")
    return m.group(1) if m else None


def _parse_moneda(name):
    n = _strip_accents(name or "").lower()
    # "dolar/dolares" o el sufijo "USD"/"u$s" (algunos nombres CNV usan la sigla, ej.
    # "Balanz Capital Estrategia I USD"). Sin el "usd" un fondo dólar caía como ARS.
    return "USD" if ("dolar" in n or "usd" in n or "u$s" in n) else "ARS"


def _parse_emisor(name):
    if (name or "").lower().startswith("fima"):
        return "Galicia (FIMA)"
    return _base_name(name)


def _slug(name):
    """'Fima Premium Dólares - Clase A' → 'FIMA-PREMIUM-DOLARES-A' (sin acentos)."""
    base = re.sub(r"[^A-Z0-9]+", "-", _strip_accents(_base_name(name)).upper()).strip("-")
    clase = _parse_clase(name)
    return f"{base}-{clase}" if clase else base


# Allowlists normalizadas (sin acentos, lower) para match EXACTO por base-name.
_MM_ALLOW_NORM = {_strip_accents(p).lower() for p in MM_ALLOWLIST}
_BROKER_FCI_NORM = {_strip_accents(p).lower() for p in BROKER_FCI_ALLOWLIST}


def _is_seed_fund(name):
    """FIMA: clases retail A/B/C/P. Otros: el nombre-base debe coincidir EXACTO
    con un fondo de las allowlists (evita que 'Allaria Ahorro' arrastre
    'Allaria Ahorro Dinámico'). BROKER_FCI_ALLOWLIST suma los fondos
    propietarios que entran por import (Cocos/Balanz)."""
    low = (name or "").lower()
    if low.startswith("fima"):
        return _parse_clase(name) in FIMA_CLASSES
    base = _strip_accents(_base_name(name)).lower()
    return base in _MM_ALLOW_NORM or base in _BROKER_FCI_NORM


# ── Schema ──────────────────────────────────────────────────────────────────
def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fci_catalog (
            symbol       TEXT PRIMARY KEY,
            ad_name      TEXT NOT NULL,
            display_name TEXT NOT NULL,
            emisor       TEXT,
            clase        TEXT,
            moneda       TEXT NOT NULL DEFAULT 'ARS',
            categoria    TEXT,
            activo       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS fci_prices (
            symbol     TEXT PRIMARY KEY,
            price      REAL,
            moneda     TEXT,
            as_of_date TEXT,
            fetched_at TEXT
        );
    """)


# ── Seed + refresh ──────────────────────────────────────────────────────────
def seed_catalog(conn, funds=None):
    """Puebla/actualiza fci_catalog desde ArgentinaDatos. Idempotente.
    Devuelve count de fondos en el catálogo."""
    if funds is None:
        funds = _fetch_all_funds()
    # Freshness: descartamos fondos cerrados/stale cuyo último valor quedó viejo
    # (ej. una clase discontinuada que reporta una fecha de hace meses).
    dates = [f.get("fecha") for f in funds if f.get("fecha")]
    cutoff = None
    if dates:
        try:
            cutoff = (datetime.fromisoformat(max(dates)) - timedelta(days=7)).date().isoformat()
        except Exception:
            cutoff = None
    seen, rows = set(), []
    for f in funds:
        name = (f.get("fondo") or "").strip()
        if not name or not _is_seed_fund(name):
            continue
        if cutoff and (f.get("fecha") or "") < cutoff:
            continue  # fondo stale/cerrado
        sym = FCI_PREFIX + _slug(name)
        if sym in seen:
            continue
        seen.add(sym)
        rows.append((
            sym, name, name, _parse_emisor(name), _parse_clase(name),
            _parse_moneda(name), f.get("_cat"),
        ))
    with conn:
        for r in rows:
            conn.execute("""
                INSERT INTO fci_catalog
                    (symbol, ad_name, display_name, emisor, clase, moneda, categoria, activo)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(symbol) DO UPDATE SET
                    ad_name=excluded.ad_name, display_name=excluded.display_name,
                    emisor=excluded.emisor, clase=excluded.clase,
                    moneda=excluded.moneda, categoria=excluded.categoria, activo=1
            """, r)
    log.info("FCI catalog seeded: %d fondos", len(rows))
    return len(rows)


def refresh_prices(conn, funds=None):
    """Refresca fci_prices para los símbolos activos del catálogo. Match por
    ad_name (case-insensitive). price = vcp/1000. Si el fetch falla, NO borra
    precios viejos. Devuelve dict con counts."""
    try:
        if funds is None:
            funds = _fetch_all_funds()
    except Exception as ex:
        log.error("FCI refresh abortado (fetch falló): %s", ex)
        return {"ok": False, "error": str(ex), "updated": 0, "missing": []}

    idx = {}
    for f in funds:
        nm = (f.get("fondo") or "").strip().lower()
        if nm:
            idx[nm] = f

    cat = conn.execute(
        "SELECT symbol, ad_name, moneda FROM fci_catalog WHERE activo=1"
    ).fetchall()
    updated, missing = 0, []
    with conn:
        for row in cat:
            f = idx.get((row["ad_name"] or "").strip().lower())
            vcp = f.get("vcp") if f else None
            if not isinstance(vcp, (int, float)):
                missing.append(row["symbol"])
                continue
            price = round(vcp / 1000.0, 6)
            conn.execute("""
                INSERT INTO fci_prices (symbol, price, moneda, as_of_date, fetched_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(symbol) DO UPDATE SET
                    price=excluded.price, moneda=excluded.moneda,
                    as_of_date=excluded.as_of_date, fetched_at=excluded.fetched_at
            """, (row["symbol"], price, row["moneda"], f.get("fecha")))
            updated += 1
    log.info("FCI prices refreshed: %d updated, %d missing", updated, len(missing))
    return {"ok": True, "updated": updated, "missing": missing}


def bootstrap(conn):
    """Boot: crea tablas, seedea catálogo y refresca precios en una sola pasada
    (1 fetch). Tolerante a fallos de red — nunca rompe el arranque."""
    ensure_tables(conn)
    try:
        funds = _fetch_all_funds()
    except Exception as ex:
        log.error("FCI bootstrap: fetch falló, catálogo/precios sin tocar: %s", ex)
        return {"ok": False, "error": str(ex), "seeded": 0}
    seeded = seed_catalog(conn, funds=funds)
    refresh = refresh_prices(conn, funds=funds)
    return {"ok": True, "seeded": seeded, "refresh": refresh}


# ── Lectura (consumido por get_prices y el endpoint de catálogo) ─────────────
def get_prices_for(conn, symbols):
    """{symbol: price} para símbolos FCI (prefijo FCI:). Símbolos sin precio
    conocido no aparecen en el dict."""
    syms = [s for s in symbols if (s or "").upper().startswith(FCI_PREFIX)]
    if not syms:
        return {}
    qmarks = ",".join("?" * len(syms))
    rows = conn.execute(
        f"SELECT symbol, price FROM fci_prices WHERE symbol IN ({qmarks})",
        syms,
    ).fetchall()
    return {r["symbol"]: r["price"] for r in rows if r["price"] is not None}


def list_catalog(conn):
    """Catálogo activo para el selector del frontend, con el último precio."""
    rows = conn.execute("""
        SELECT c.symbol, c.display_name, c.emisor, c.clase, c.moneda, c.categoria,
               p.price, p.as_of_date
        FROM fci_catalog c
        LEFT JOIN fci_prices p ON p.symbol = c.symbol
        WHERE c.activo = 1
        ORDER BY c.emisor ASC, c.display_name ASC
    """).fetchall()
    return [dict(r) for r in rows]
