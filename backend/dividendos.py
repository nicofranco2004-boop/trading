"""Dividendos de las empresas: lo que pagaron y el cobro que el usuario confirma.

POR QUÉ EXISTE (análisis del 2026-10-09). Rendi sabía cuándo pagaba cada empresa
—Novedades lo anuncia— pero nunca anotaba el cobro: un dividendo sólo entraba si
el usuario importaba el archivo de su broker, y el 72 % de las cuentas de broker
se importaron UNA sola vez. En la copia de producción del 16/08, de 2.122
tenencias que pagan dividendo desde antes del 16/04, el 35 % no tenía ninguno
registrado. Esa plata entraba al efectivo del broker sin explicación (el
Dashboard la mostraba como "Dividendos e intereses": ganancia sin clasificar).

Ahora Rendi PROPONE el cobro y el usuario lo confirma o lo corrige:

  · El frontend (`utils/dividendosPendientes.js`) cruza las tenencias del día de
    corte con lo que pagó cada empresa (`historial`) y arma la tarjeta. Vive allá
    porque la equivalencia CEDEAR → acción (`utils/cedearRatio.js`) vive allá, y
    tiene que haber UNA sola.
  · Las REGLAS de descuento viven acá (`REGLAS`) y viajan con el historial: el
    frontend no tiene su propia copia de los porcentajes.
  · El cobro confirmado entra por `registrar_cobro` y se deshace por
    `deshacer_efectivo`, que usan también el borrado desde Movimientos y el
    importador cuando trae el mismo dividendo (el dato del broker reemplaza al
    confirmado, no se suma).

Decisiones de producto (Nico, 2026-10-09):
  · El dividendo es GANANCIA REALIZADA. No es un depósito (no toca el capital
    aportado) ni ganancia no realizada (la de la acción sigue siendo sólo por
    precio).
  · El impuesto y las comisiones RESTAN de esa ganancia. No son retiros.
  · Lo confirmado va al efectivo del broker: los dólares a la cuenta en dólares,
    la comisión en pesos a la cuenta en pesos.

Las reglas están MEDIDAS, no supuestas (`scripts/backtest_dividendos.py`, contra
7.566 dividendos reales importados de IOL, Balanz, Bull Market, PPI e Inviu,
2023-2026):
  · a la cuenta llega ~65 % del dividendo en acciones de EE.UU. vía CEDEAR
    (30 % de retención de EE.UU. + ~5 % más que no identificamos de dónde sale)
    y ~70 % en ETFs (sólo el 30 %). Igual en todos los brokers y en todos los años.
  · el mismo día, IOL y Balanz cobran un cargo chico EN PESOS (mediana 0,72 % y
    0,42 % de lo que llegó en dólares). Los demás brokers casi nunca.
  · el broker acredita ~21 días después del día de corte.
Las empresas que no son de EE.UU. (ADRs de Brasil, Taiwán, Países Bajos…) tienen
otras retenciones y quedan FUERA hasta medirlas: sin regla, no se propone monto.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException

import efectivo
import fx as _fx
from fechas import hoy_art

log = logging.getLogger(__name__)


# ─── Reglas (las únicas; el frontend las recibe con el historial) ────────────
REGLAS = {
    # Retención de impuestos de EE.UU. sobre dividendos.
    "impuesto_eeuu": 0.30,
    # Lo que además falta en las ACCIONES (no en los ETFs). Medido; origen sin
    # identificar, por eso la tarjeta lo llama "Otros descuentos".
    "otros_accion": 0.05,
    # Cargo en PESOS del broker, como fracción de lo que llegó en dólares. La
    # clave se busca dentro del nombre del broker en minúscula.
    "comision_pesos": {"balanz": 0.0042, "iol": 0.0072},
    # Días entre el corte y la acreditación en un broker argentino (mediana).
    "dias_hasta_el_pago": 21,
    # Hasta cuántos días atrás se buscan cortes. Más viejo que esto, el usuario
    # probablemente ya no tiene a mano con qué compararlo.
    "dias_hacia_atras": 120,
    # Por empresa, sólo el ÚLTIMO pago ya acreditado (decisión de Nico,
    # 2026-10-09): quien nunca anotó dividendos no ve tres o cuatro tarjetas de la
    # misma empresa al entrar. Si ese último ya está anotado o lo marcó "No lo
    # cobré", no se vuelve a uno más viejo.
    "solo_ultimo_pago": True,
    # Un dividendo ya registrado (importado o confirmado) cuenta como ESTE cobro
    # si su fecha cae entre el corte y esta cantidad de días después.
    "ventana_ya_registrado": 45,
    # Para dividendos importados SIN activo (Cocos no dice de qué empresa es):
    # cuentan como este cobro si el monto se parece así de cerca.
    "tolerancia_monto_sin_activo": 0.20,
    # Países con regla medida. Lo demás, sin monto.
    "paises_con_regla": ["United States"],
}

DIAS_FRESCO_HISTORIAL = 0.5     # el historial se vuelve a pedir cada 12 h
DIAS_FRESCO_EMISOR = 30         # país y tipo casi no cambian

SRC = "dividendo_bandeja"       # marca en `undo_meta_json` de lo confirmado acá


# ─── Tablas ──────────────────────────────────────────────────────────────────
def crear_tablas(conn) -> None:
    """Las tres tablas. `dividendos_pagados` y `dividendos_emisor` son caché
    COMPARTIDA (sin user_id, como `financial_events`); `dividendos_salteados` es
    de cada usuario (los "No lo cobré")."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS dividendos_pagados (
            ticker TEXT NOT NULL,
            ex_date TEXT NOT NULL,           -- día de corte
            por_accion REAL NOT NULL,        -- lo que pagó la empresa por acción
            PRIMARY KEY (ticker, ex_date)
        );
        CREATE TABLE IF NOT EXISTS dividendos_emisor (
            ticker TEXT PRIMARY KEY,
            pais TEXT,                       -- 'United States', 'Brazil'… (Yahoo)
            tipo TEXT,                       -- 'EQUITY' | 'ETF' (Yahoo quoteType)
            consultado_at TEXT NOT NULL      -- cuándo se pidió el historial
        );
        CREATE TABLE IF NOT EXISTS dividendos_salteados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            broker TEXT NOT NULL,
            asset TEXT NOT NULL,
            ex_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, broker, asset, ex_date)
        );
        CREATE INDEX IF NOT EXISTS idx_div_salteados_user ON dividendos_salteados(user_id);
    """)


# ─── Historial de pagos (Yahoo, con caché) ───────────────────────────────────
def _consultar_yahoo(pedido: tuple) -> dict:
    """Lo que pagó el ticker (dividendos ya pagados, por día de corte) y, si
    `con_emisor`, su país y tipo (es el pedido lento de Yahoo: sólo cuando no los
    tenemos). Corre en el pool de `pricing.yahoo` (con tope): nunca llamarla
    suelta desde un pedido."""
    import yfinance as yf
    ticker, con_emisor = pedido
    t = yf.Ticker(ticker)
    pagos = []
    serie = t.dividends
    if serie is not None and len(serie):
        for idx, monto in serie.items():
            try:
                v = float(monto)
            except (TypeError, ValueError):
                continue
            if v > 0:
                pagos.append((idx.strftime("%Y-%m-%d"), round(v, 6)))
    pais = tipo = None
    if con_emisor:
        try:
            info = t.info or {}
            pais = info.get("country")
            tipo = info.get("quoteType")
        except Exception:
            pass
    return {"pagos": pagos, "pais": pais, "tipo": tipo}


def _guardar(conn, ticker: str, datos: dict) -> None:
    for ex_date, monto in datos.get("pagos") or []:
        conn.execute(
            "INSERT INTO dividendos_pagados (ticker, ex_date, por_accion) VALUES (?,?,?) "
            "ON CONFLICT(ticker, ex_date) DO UPDATE SET por_accion=excluded.por_accion",
            (ticker, ex_date, monto))
    conn.execute(
        "INSERT INTO dividendos_emisor (ticker, pais, tipo, consultado_at) VALUES (?,?,?,?) "
        "ON CONFLICT(ticker) DO UPDATE SET "
        "  pais=COALESCE(excluded.pais, dividendos_emisor.pais), "
        "  tipo=COALESCE(excluded.tipo, dividendos_emisor.tipo), "
        "  consultado_at=excluded.consultado_at",
        (ticker, datos.get("pais"), datos.get("tipo"),
         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))


def _vencidos(conn, tickers: list) -> list:
    """Los tickers que nunca se pidieron o que se pidieron hace más de 12 h."""
    limite = (datetime.utcnow() - timedelta(days=DIAS_FRESCO_HISTORIAL)).strftime("%Y-%m-%d %H:%M:%S")
    frescos = set()
    if tickers:
        ph = ",".join("?" * len(tickers))
        for r in conn.execute(
                f"SELECT ticker FROM dividendos_emisor WHERE ticker IN ({ph}) AND consultado_at > ?",
                (*tickers, limite)):
            frescos.add(r[0])
    return [t for t in tickers if t not in frescos]


def actualizar(conn, tickers: list, tope: float) -> list:
    """Pide a Yahoo los vencidos, con UN tope para todos. Devuelve los que no
    llegaron a tiempo (quedan con lo que había en caché)."""
    from pricing import yahoo
    pedir = _vencidos(conn, tickers)
    if not pedir:
        return []
    limite = (datetime.utcnow() - timedelta(days=DIAS_FRESCO_EMISOR)).strftime("%Y-%m-%d %H:%M:%S")
    ph = ",".join("?" * len(pedir))
    conocidos = {r[0] for r in conn.execute(
        f"SELECT ticker FROM dividendos_emisor WHERE ticker IN ({ph}) "
        f"AND tipo IS NOT NULL AND consultado_at > ?", (*pedir, limite))}
    pedidos = [(t, t not in conocidos) for t in pedir]
    resultados, sin_respuesta = yahoo.varios(_consultar_yahoo, pedidos, tope=tope, que="dividendos")
    for (t, _), datos in (resultados or {}).items():
        if isinstance(datos, dict):
            _guardar(conn, t, datos)
    conn.commit()
    return [t for (t, _) in (sin_respuesta or [])]


def historial(conn, tickers: list, desde: str) -> dict:
    """{ticker: {pais, tipo, pagos: [{ex_date, por_accion}]}} desde `desde`, de la caché."""
    out = {t: {"pais": None, "tipo": None, "pagos": []} for t in tickers}
    if not tickers:
        return out
    ph = ",".join("?" * len(tickers))
    for r in conn.execute(f"SELECT ticker, pais, tipo FROM dividendos_emisor WHERE ticker IN ({ph})",
                          tickers):
        out[r[0]]["pais"], out[r[0]]["tipo"] = r[1], r[2]
    for r in conn.execute(
            f"SELECT ticker, ex_date, por_accion FROM dividendos_pagados "
            f"WHERE ticker IN ({ph}) AND ex_date >= ? ORDER BY ex_date",
            (*tickers, desde)):
        out[r[0]]["pagos"].append({"ex_date": r[1], "por_accion": r[2]})
    return out


# ─── El cobro ────────────────────────────────────────────────────────────────
def _cuenta_en_dolares(conn, uid: int, broker: str) -> str:
    """Adónde entran los dólares de un CEDEAR: la regla única del importador
    (`cash_broker_for`). Si el broker no tiene cuenta en dólares, es él mismo."""
    from importing.persister import cash_broker_for
    return cash_broker_for(conn, uid, broker, "USD", "CEDEAR")


def _cuenta_en_pesos(conn, uid: int, broker: str) -> Optional[str]:
    """La cuenta en pesos del mismo broker (el padre del par), o None."""
    from importing.persister import broker_pair
    for nombre in broker_pair(conn, uid, broker):
        r = conn.execute("SELECT currency FROM brokers WHERE user_id=? AND name=?",
                         (uid, nombre)).fetchone()
        if r and (r["currency"] or "").upper() == "ARS":
            return nombre
    return None


def _moneda(conn, uid: int, broker: str) -> str:
    r = conn.execute("SELECT currency FROM brokers WHERE user_id=? AND name=?",
                     (uid, broker)).fetchone()
    return (r["currency"] or "").upper() if r else ""


def _ventana(ex_date: str) -> tuple:
    d = date.fromisoformat(ex_date[:10])
    return (d.isoformat(), (d + timedelta(days=REGLAS["ventana_ya_registrado"])).isoformat())


def ya_registrado(conn, uid: int, broker: str, asset: str, ex_date: str,
                  neto_usd: Optional[float] = None):
    """La fila de `operations` que ya cuenta como el dividendo de este corte, o None.

    MISMA regla que el frontend usa para no mostrar la tarjeta
    (`dividendosPendientes.js · yaRegistrado`): un 'Dividendo' del mismo activo en
    el par de cuentas del broker, fechado entre el corte y 45 días después; o uno
    SIN activo (Cocos no lo dice) con un monto parecido."""
    from importing.persister import broker_pair
    par = broker_pair(conn, uid, broker)
    ph = ",".join("?" * len(par))
    desde, hasta = _ventana(ex_date)
    # Un confirmado desde la bandeja trae su día de corte: cuenta por eso, sin
    # importar la fecha con que se anotó (la prueba al azar encontró dos
    # confirmados del mismo corte cuando el primero tenía la fecha fuera de la
    # ventana).
    for f in conn.execute(
            f"""SELECT id, date, asset, pnl_usd, undo_meta_json FROM operations
                 WHERE user_id=? AND broker IN ({ph}) AND op_type='Dividendo'
                   AND undo_meta_json LIKE ?""",
            (uid, *par, f'%"src": "{SRC}"%')).fetchall():
        try:
            meta = json.loads(f["undo_meta_json"])
        except (TypeError, ValueError):
            continue
        if meta.get("ex_date") == ex_date[:10] and (f["asset"] or "").upper() == asset.upper():
            return f
    filas = conn.execute(
        f"""SELECT id, date, asset, pnl_usd FROM operations
             WHERE user_id=? AND broker IN ({ph}) AND op_type='Dividendo'
               AND date >= ? AND date <= ?""",
        (uid, *par, desde, hasta)).fetchall()
    for f in filas:
        if (f["asset"] or "").upper() == asset.upper():
            return f
    if neto_usd:
        tol = REGLAS["tolerancia_monto_sin_activo"]
        for f in filas:
            if (f["asset"] or "").strip() in ("", "—") and f["pnl_usd"]:
                if abs(float(f["pnl_usd"]) - neto_usd) <= tol * neto_usd:
                    return f
    return None


def registrar_cobro(conn, uid: int, *, broker: str, asset: str, ex_date: str,
                    fecha: str, bruto: float, impuesto: float, otros: float,
                    comision_pesos: float, cedears: Optional[float] = None) -> dict:
    """Anota un dividendo cobrado. Todo en la transacción del que llama.

    Qué escribe:
      · una fila 'Dividendo' en `operations`, en la cuenta en dólares del broker,
        con `pnl_usd` = lo que llegó − la comisión en pesos (en dólares): la
        ganancia realizada. Así la suma el recálculo mensual.
      · el efectivo: + lo que llegó en la cuenta en dólares, − la comisión en la
        cuenta en pesos.
      · `undo_meta_json` con TODO lo que movió, para deshacerlo exacto.
    NO toca depósitos ni retiros: el capital aportado queda igual."""
    asset = (asset or "").strip().upper()
    if not asset:
        raise HTTPException(400, "Falta el activo.")
    if not conn.execute("SELECT 1 FROM brokers WHERE user_id=? AND name=?",
                        (uid, broker)).fetchone():
        raise HTTPException(404, f"Broker '{broker}' no encontrado")
    for nombre, v in (("dividendo", bruto), ("impuesto", impuesto), ("otros descuentos", otros),
                      ("comisión en pesos", comision_pesos)):
        if v is None or v < 0:
            raise HTTPException(400, f"El {nombre} no puede ser negativo.")
    fecha = fecha[:10]
    if fecha > hoy_art():
        raise HTTPException(400, "La fecha del cobro no puede ser futura: se anota cuando ya llegó.")
    if ex_date[:10] > fecha:
        raise HTTPException(400, "El cobro no puede ser anterior al día de corte.")
    # La misma ventana con que se reconoce un dividendo ya anotado (acá, en el
    # import y en la bandeja): un cobro fechado fuera de ella no lo encontraría
    # nadie y la tarjeta volvería a aparecer.
    if fecha > _ventana(ex_date)[1]:
        raise HTTPException(400, f"La fecha del cobro tiene que estar dentro de los "
                                 f"{REGLAS['ventana_ya_registrado']} días del corte.")
    neto = round(bruto - impuesto - otros, 2)
    if neto <= 0:
        raise HTTPException(400, "Lo que te llega tiene que ser mayor a cero. "
                                 "Revisá el impuesto y los descuentos.")

    cuenta_usd = _cuenta_en_dolares(conn, uid, broker)
    cuenta_ars = _cuenta_en_pesos(conn, uid, broker) if comision_pesos > 0 else None
    if comision_pesos > 0 and not cuenta_ars:
        raise HTTPException(400, f"{broker} no tiene una cuenta en pesos para cobrar la comisión. "
                                 "Dejala en cero o cargala en dólares en «otros descuentos».")

    # El dólar del día del cobro: para pasar la comisión a dólares (la ganancia es
    # en dólares) y, si el broker no tiene cuenta en dólares, para acreditar pesos.
    tc, tc_fuente = _fx.fx_for_date_detail(conn, fecha)
    cuenta_en_pesos = _moneda(conn, uid, cuenta_usd) == "ARS"
    if (comision_pesos > 0 or cuenta_en_pesos) and not tc:
        raise HTTPException(400, "No hay cotización del dólar para esa fecha. Probá con otra fecha.")
    comision_usd = round(comision_pesos / tc, 4) if comision_pesos > 0 else 0.0
    ganancia = round(neto - comision_usd, 4)

    if ya_registrado(conn, uid, broker, asset, ex_date, neto_usd=neto):
        raise HTTPException(409, f"Ya hay un dividendo de {asset} anotado para el corte del "
                                 f"{_ddmm(ex_date)}. Fijate en Movimientos.")

    if cuenta_en_pesos:
        moneda, fx_fila, efectivo_nativo = "ARS", tc, round(neto * tc, 2)
    else:
        moneda, fx_fila, efectivo_nativo = "USD", 1.0, neto
    # `commissions` en la moneda de la fila (Movimientos la divide por el TC sellado).
    comisiones_fila = round((otros + comision_usd) * fx_fila, 4)

    meta = {
        "src": SRC, "ex_date": ex_date[:10], "broker_tenencia": broker,
        "cash": efectivo_nativo, "cash_broker": cuenta_usd,
        "comision_pesos": round(comision_pesos, 2), "cuenta_pesos": cuenta_ars,
        "bruto": round(bruto, 2), "impuesto": round(impuesto, 2), "otros": round(otros, 2),
        "neto": neto, "tc": tc, "tc_fuente": tc_fuente, "cedears": cedears,
    }
    notas = (f"Bruto US$ {_num(bruto)} · impuesto EE.UU. US$ {_num(impuesto)}"
             + (f" · otros descuentos US$ {_num(otros)}" if otros > 0 else "")
             + (f" · comisión $ {_num(comision_pesos)}" if comision_pesos > 0 else "")
             + f" · corte {_ddmm(ex_date)}")
    cur = conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type, quantity,
               pnl_usd, commissions, notes, currency, fx_to_usd, undo_meta_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (uid, fecha, cuenta_usd, asset, "Dividendo", efectivo_nativo,
         ganancia, comisiones_fila, notas, moneda, fx_fila, json.dumps(meta)))
    efectivo.mover(conn, uid, cuenta_usd, efectivo_nativo)
    if comision_pesos > 0:
        efectivo.mover(conn, uid, cuenta_ars, -round(comision_pesos, 2))
    return {"operation_id": cur.lastrowid, "cuenta": cuenta_usd, "cuenta_pesos": cuenta_ars,
            "neto": neto, "efectivo": efectivo_nativo, "moneda": moneda,
            "comision_pesos": round(comision_pesos, 2), "ganancia_usd": round(ganancia, 2)}


def movimientos_de_efectivo(meta: dict) -> list:
    """Lo que el cobro le hizo al efectivo, como [(cuenta, monto nativo)]."""
    out = []
    if meta.get("cash"):
        out.append((meta.get("cash_broker"), float(meta["cash"])))
    if meta.get("comision_pesos") and meta.get("cuenta_pesos"):
        out.append((meta["cuenta_pesos"], -float(meta["comision_pesos"])))
    return out


def deshacer_efectivo(conn, uid: int, meta: dict) -> list:
    """Devuelve el efectivo que movió un cobro confirmado. La usan el borrado
    desde Movimientos y el importador. Devuelve lo que aplicó [(cuenta, monto)]."""
    hecho = []
    for cuenta, monto in movimientos_de_efectivo(meta):
        if cuenta and monto:
            efectivo.mover(conn, uid, cuenta, -monto)
            hecho.append((cuenta, -monto))
    return hecho


def reemplazar_por_importado(conn, uid: int, broker: str, asset: Optional[str], fecha: str,
                             monto_usd: float) -> Optional[int]:
    """El importador trae un dividendo que el usuario ya había confirmado desde la
    bandeja: el dato del broker manda. Borra el confirmado y devuelve su efectivo,
    para que el importado entre solo y no se cuente dos veces. Devuelve el id
    borrado, o None.

    Empareja con la MISMA ventana que `ya_registrado`, mirada desde el otro lado:
    el confirmado tiene su día de corte en `undo_meta_json`, y el importado cae
    entre ese corte y 45 días después. Mismo activo, o —si el archivo no dice el
    activo (Cocos)— monto parecido."""
    from importing.persister import broker_pair
    par = broker_pair(conn, uid, broker)
    ph = ",".join("?" * len(par))
    asset = (asset or "").strip().upper()
    filas = conn.execute(
        f"""SELECT id, asset, pnl_usd, undo_meta_json FROM operations
             WHERE user_id=? AND broker IN ({ph}) AND op_type='Dividendo'
               AND undo_meta_json LIKE ?""",
        (uid, *par, f'%"src": "{SRC}"%')).fetchall()
    tol = REGLAS["tolerancia_monto_sin_activo"]
    for f in filas:
        try:
            meta = json.loads(f["undo_meta_json"])
        except (TypeError, ValueError):
            continue
        desde, hasta = _ventana(meta.get("ex_date") or "1900-01-01")
        if not (desde <= fecha[:10] <= hasta):
            continue
        if asset and asset not in ("—",):
            if (f["asset"] or "").upper() != asset:
                continue
        else:
            neto = float(meta.get("neto") or 0)
            if not neto or abs(monto_usd - neto) > tol * neto:
                continue
        deshacer_efectivo(conn, uid, meta)
        conn.execute("DELETE FROM operations WHERE id=? AND user_id=?", (f["id"], uid))
        log.info("dividendos: el import reemplazó el cobro confirmado %s (%s)", f["id"], f["asset"])
        return f["id"]
    return None


# ─── "No lo cobré" ───────────────────────────────────────────────────────────
def saltear(conn, uid: int, broker: str, asset: str, ex_date: str) -> None:
    conn.execute(
        "INSERT INTO dividendos_salteados (user_id, broker, asset, ex_date, created_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(user_id, broker, asset, ex_date) DO NOTHING",
        (uid, broker, asset.upper(), ex_date[:10],
         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))


def quitar_salteado(conn, uid: int, broker: str, asset: str, ex_date: str) -> int:
    return conn.execute(
        "DELETE FROM dividendos_salteados WHERE user_id=? AND broker=? AND asset=? AND ex_date=?",
        (uid, broker, asset.upper(), ex_date[:10])).rowcount


def salteados(conn, uid: int) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT broker, asset, ex_date FROM dividendos_salteados WHERE user_id=?", (uid,))]


# ─── formato ─────────────────────────────────────────────────────────────────
def _num(v: float) -> str:
    return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ddmm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"
