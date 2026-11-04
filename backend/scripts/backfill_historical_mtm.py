"""Backfill one-time (CLI): valuación histórica a MERCADO de cuentas importadas.

Problema: una cuenta importada nunca capturó el mark-to-market NO REALIZADO de los
meses pasados (para meses cerrados pnl_unrealized=0 → capital_final ≈ COSTO). Por
eso el chart "Evolución" queda plano y recién "toma el % real" hoy (el salto), y el
CAGR sale bajísimo (p.ej. +2.84% vs +22.43% del broker). El ~22% es apreciación no
realizada que nunca entró en la serie histórica.

Este backfill, por cada mes CERRADO, reconstruye las tenencias a fin de mes (net
BUY−SELL del import_normalized_tx confirmado) y las valúa al precio de MERCADO
histórico, sumando esa apreciación a monthly_entries.capital_final (por-broker +
global) y re-derivando los snapshots que lee el chart.

  capital_final = (capital_inicio + deposits − withdrawals + pnl_realized)  [costo]
                +  Σ (valor_mercado − costo)  de las tenencias              [unrealized]

El primer término se RECOMPUTA de columnas estables cada corrida (idempotente — no
lee el capital_final que esta misma corrida pudo dejar en MTM). En ese primer
término la caja queda DEDUCIDA (lo que los flujos no explican con lo invertido).
Para cada broker cuya caja de hoy explican los movimientos importados, la caja de
fin de mes se MIDE en su lugar (ver "LA CAJA SE MIDE, NO SE DEDUCE").

Valuación = port fiel de snapshots_job.compute_broker_value_usd (live):
  - holding USD (broker USD/USDT)            → close USD histórico × qty
  - holding .BA (broker ARS / '· USD' / CEDEAR) → close .BA (ARS) ÷ MEP
  - bono (soberano / CER / BOPREAL)           → cierre de data912 por 1 nominal,
                                                con la escala del precio en vivo
  - cripto                                    → close <SYM>-USD histórico × qty
FX histórico: el dólar-MEP de fx_rates_daily (último ≤ fin de mes, sin fuga al
futuro; el blue antes de que haya serie de MEP), el mismo que usa el cron para la
medición de hoy; para cuentas en USD el FX ni se usa. La CAJA de cada broker sale
de los movimientos importados, en su moneda, al dólar de ese fin de mes (ver "LA
CAJA SE MIDE, NO SE DEDUCE DE LA CONTABILIDAD"). Regla
cardinal: si falta precio/FX/historia o hay split → AL COSTO (jamás infla).

NO toca: positions, operations, cash, import_normalized_tx NI monthly_entries. La
reconstruccion se persiste SOLO en `snapshots`, con `source='mtm_backfill'` y la
cobertura del mes estampada (`mtm_coverage`), por UPSERT que respeta las mediciones
reales del cron. Escribir en monthly_entries.capital_final era inutil: para todo mes
cerrado `_repair_monthly_chain` (main.py:9314-9318) lo recomputa al costo y se
dispara desde ~20 lugares de main.py, asi que el ancla se borraba sola.
Saltea cuentas sin import confirmado (manuales → no reconstruibles). El mes
calendario EN CURSO no se toca (lo maneja el flujo live).

Uso
───
    python scripts/backfill_historical_mtm.py            # DRY-RUN (sobre copia, no toca nada)
    python scripts/backfill_historical_mtm.py --apply    # aplica + commitea (por user)
    python scripts/backfill_historical_mtm.py --user 42  # una sola cuenta

⚠️  Backup antes de --apply:  python scripts/backup_db.py
"""
from __future__ import annotations

import argparse
import calendar
import math
import os
import sqlite3
import sys
import tempfile
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main                                              # noqa: E402
import snapshots_job as sj                               # noqa: E402
from importing.recompute_backfill import _clone_db                 # noqa: E402


# ─── Fetch de cierre mensual histórico por símbolo de precio ──────────────────
_HIST_CACHE: dict = {}
# Mes (AAAA-MM) en que se pidió cada serie. Una serie pedida en septiembre no
# tiene el cierre de septiembre: si el proceso sigue vivo en octubre, ese mes —ya
# cerrado— caía al costo en cada reconstrucción. Se vuelve a pedir al cambiar el
# mes. (Una entrada sin fecha —las que arman las pruebas a mano— vale como de hoy.)
_HIST_CACHE_MES: dict = {}

# Activos cuya consulta a Yahoo FALLÓ (excepción: red, límite de pedidos, timeout)
# en la corrida en curso de este hilo. No es lo mismo que "Yahoo no tiene datos"
# (un ticker que no existe devuelve vacío, sin excepción — medido con yfinance
# 1.2.0): eso es definitivo y se recuerda; una falla no.
import threading as _threading           # noqa: E402
_CORRIDA = _threading.local()


def _mes_en_curso() -> str:
    """AAAA-MM de hoy en Argentina: la vigencia de las series de `_HIST_CACHE`."""
    from fechas import hoy_art_date
    return hoy_art_date().strftime("%Y-%m")


def _fallas_yahoo() -> list:
    if not hasattr(_CORRIDA, "fallas"):
        _CORRIDA.fallas = []
    return _CORRIDA.fallas

def _fetch_monthly_close(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM: close} para un price_key ('AAPL', 'GGAL.BA', 'BTC'), desde start a
    hoy. {} (→ costo) para lo que no tiene historia: los FCI, y los bonos que
    data912 no guarda (ONs y letras). Los bonos que sí guarda salen de ahí, por 1
    nominal — ver `_cierres_bono_data912`.

    Los CEDEARs y las acciones AR (.BA) SÍ tienen serie: medido, 24 de 24 meses
    para AAPL.BA, KO.BA, MELI.BA, GGAL.BA e YPFD.BA. El que cotiza en dólares se
    valúa por su subyacente — ver `_precio_por_subyacente`."""
    ck = (price_key, start_iso)
    _mes = _mes_en_curso()
    if ck in _HIST_CACHE and _HIST_CACHE_MES.get(ck, _mes) == _mes:
        return _HIST_CACHE[ck]
    if price_key in _fallas_yahoo():
        # Ya falló en ESTA corrida: no se le vuelve a preguntar en cada mes. Sin
        # esto, la cuenta más grande de la copia de prod hacía 1.537 consultas por
        # corrida con Yahoo caído (159 activos), justo cuando Yahoo está limitando.
        return {}
    base = price_key[:-3] if price_key.endswith(".BA") else price_key
    out: dict = {}
    # ⚠️ EL CEDEAR COTIZADO EN USD YA NO SE SALTEA.
    # Se saltea lo que NO tiene serie histórica: los FCI. El CEDEAR en dólares
    # estaba acá por otra razón —
    # el código intentaba el camino largo (precio local ÷ CCL histórico)— y no hace
    # falta: con el ratio, 100 CEDEARs de ratio 4 son 25 acciones equivalentes, y
    # la acción SÍ tiene precio en dólares. Lo resuelve `_precio_por_subyacente`.
    # (Y `CEDEAR_USD_RATIOS` tiene exactamente un ticker: BAC.)
    skip = price_key.startswith("FCI:")
    es_bono = not skip and (
        base in getattr(main, "AR_BONDS_DATA912", set())
        or main._is_data912_bond(base))
    if es_bono and _DATA912_CAIDO in _fallas_yahoo():
        # data912 ya no contestó en ESTA corrida: no se espera su tope de tiempo
        # una vez por bono. Queda anotado igual, así la corrida pide reintento.
        _fallas_yahoo().append(price_key)
        return {}
    if es_bono:
        # ⚠️ EL BONO YA NO QUEDA AL COSTO. Se lo salteaba porque "data912 es
        # live-only", y no lo es: guarda una vela por rueda desde 2021. Al costo,
        # un AL35 comprado a 1.220 pesos que a fin de octubre valía 1.059 dejaba
        # la foto US$ 706 arriba de la cartera real, y la caída aparecía de golpe
        # entre la última foto y hoy. Yahoo no sirve para esto: da el '.BA' por
        # cada 100 nominales y para la mitad de los bonos ni lo tiene.
        try:
            out = _cierres_bono_data912(price_key)
        except Exception:
            # Misma regla que Yahoo (abajo): una falla no se guarda.
            _fallas_yahoo().extend((price_key, _DATA912_CAIDO))
            return {}
    elif not skip:
        yf_sym = main.CRYPTO_YF.get(base, price_key) if base in main.CRYPTO_SYMBOLS else price_key
        try:
            import yfinance as yf
            # timeout acotado: una consulta que se cuelga (Yahoo rate-limit) degrada
            # al costo en vez de colgar todo el request de la tanda. Ver el panel de
            # Admin (MtmBackfillPanel) que además reintenta las tandas lentas.
            data = yf.Ticker(yf_sym).history(start=start_iso, interval="1mo", auto_adjust=False, timeout=8)
            if not data.empty:
                for idx, row in data.iterrows():
                    c = row.get("Close")
                    if c is not None and not (isinstance(c, float) and math.isnan(c)):
                        out[idx.strftime("%Y-%m")] = float(c)
        except Exception:
            # ⚠️ UNA FALLA NO SE GUARDA. Antes se guardaba `{}` como si Yahoo no
            # tuviera datos, y el activo quedaba al costo en TODAS las corridas
            # hasta el próximo reinicio: una caída de Yahoo justo después de un
            # deploy pisaba al costo una historia que estaba bien a mercado.
            _fallas_yahoo().append(price_key)
            return {}
    _HIST_CACHE[ck] = out
    _HIST_CACHE_MES[ck] = _mes
    return out


# Marca en `_fallas_yahoo` de que la historia de data912 no contestó en esta
# corrida (ver `_fetch_monthly_close`). No es un activo: `yahoo_fallo` la lista
# sólo como señal de reintento.
_DATA912_CAIDO = "data912:historia"

# Bonos con los que se mide cuántos pesos vale un dólar en una rueda, igual que
# en vivo (`main._data912_peso_per_usd`): el mismo bono en pesos y en dólares.
_REFS_PESO_POR_USD = ("AL30", "GD30")


def _serie_data912(papel: str) -> list:
    """[(fecha, cierre)] ordenado, de la historia de bonos de data912. Cacheada
    por proceso con la misma vigencia que el resto (`_HIST_CACHE_MES`). Una falla
    de red sube como excepción y no se guarda."""
    from pricing import data912
    ck = ("data912:" + papel, "diario")
    _mes = _mes_en_curso()
    if ck in _HIST_CACHE and _HIST_CACHE_MES.get(ck, _mes) == _mes:
        return _HIST_CACHE[ck]
    serie = sorted(data912.cierres("bonds", papel).items())
    _HIST_CACHE[ck] = serie
    _HIST_CACHE_MES[ck] = _mes
    return serie


def _cierre_al(serie: list, fecha: str):
    """El último cierre de `serie` con fecha ≤ `fecha` (sin mirar el futuro)."""
    import bisect
    i = bisect.bisect_right(serie, (fecha, float("inf")))
    return serie[i - 1][1] if i else None


def _cierres_bono_data912(price_key: str) -> dict:
    """{YYYY-MM: precio por 1 nominal} de un bono, con el último cierre de cada
    mes en data912. {} si data912 no guarda ese bono (ONs, letras).

    El papel que se pide es el MISMO que en vivo (`main._resolve_ar_bond_price`):
    'AL35.BA' (cuenta en pesos) → AL35, en pesos; 'AL35' (cuenta en dólares) →
    AL35D, en dólar-MEP. Y la escala también: `main._escala_bono`, con los pesos
    por dólar de esa misma rueda en vez de los de hoy."""
    is_ars = price_key.endswith(".BA")
    base = price_key[:-3] if is_ars else price_key
    serie = _serie_data912(base if is_ars else base + "D")
    ultimo_del_mes: dict = {}
    for fecha, c in serie:
        ultimo_del_mes[fecha[:7]] = (fecha, c)

    def _peso_por_usd(fecha):
        def _f():
            precios = {}
            for ref in _REFS_PESO_POR_USD:
                for papel in (ref, ref + "D"):
                    px = _cierre_al(_serie_data912(papel), fecha)
                    if px is not None:
                        precios[papel] = px
                if ref in precios and ref + "D" in precios:
                    break               # con un par alcanza, como en vivo
            return main._data912_peso_per_usd(precios)
        return _f

    out = {}
    for ym, (fecha, c) in ultimo_del_mes.items():
        px = main._escala_bono(base, c, is_ars, _peso_por_usd(fecha))
        if px is not None:
            out[ym] = px
    return out


def _precio_por_subyacente(asset: str, ym: str, start_iso: str):
    """Precio en USD de UN CEDEAR que cotiza en dólares, vía su SUBYACENTE.

    Un CEDEAR con ratio 4 es 1/4 de acción: 100 CEDEARs = 25 acciones
    equivalentes. La acción tiene precio histórico en dólares, así que no hace
    falta ni el precio local ni el CCL histórico — que es el camino largo por el
    que este caso terminaba salteado y valuado al costo.

    None si el activo no es un CEDEAR-USD o si el subyacente no tiene precio.
    """
    ratios = getattr(main, "CEDEAR_USD_RATIOS", {}) or {}
    base = asset[:-3] if str(asset).endswith(".BA") else str(asset)
    ratio = ratios.get(base)
    if not ratio:
        return None
    try:
        px = _fetch_monthly_close(base, start_iso).get(ym)
    except Exception:
        return None
    if px is None:
        return None
    try:
        return float(px) / float(ratio)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ─── FX histórico — el BLUE de fx_rates_daily (último ≤ fin de mes) ──────────
def _hist_blue(conn, month_end_iso: str, fallback: float) -> float:
    """El punto MEDIO del blue, con la expresión compartida de `fx.py`.

    Esto valúa a mercado los meses cerrados (`capital_final`), o sea que escribe
    en la misma cadena que después lee el resto de la app. Leer acá la punta de
    venta mientras todo lo demás usa el medio es exactamente la mezcla de bases
    que fabrica retorno de la nada — ver el límite 2 de `ledger_replay`.
    """
    try:
        import fx as _fxmod
    except ImportError:  # pragma: no cover — según cómo se cargue el paquete
        from .. import fx as _fxmod
    row = conn.execute(
        f"SELECT {_fxmod.SQL_MEDIO_BLUE} AS blue FROM fx_rates_daily "
        "WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (month_end_iso,),
    ).fetchone()
    try:
        v = float(row["blue"]) if row and row["blue"] is not None else None
        return v if (v and v > 0) else fallback
    except (TypeError, ValueError):
        return fallback


def _hist_mep(conn, month_end_iso: str, fallback: float) -> float:
    """El dólar-MEP (punto medio) del último día ≤ fin de mes; el blue si no hay."""
    try:
        import fx as _fxmod
    except ImportError:  # pragma: no cover — según cómo se cargue el paquete
        from .. import fx as _fxmod
    v = _fxmod.fx_for_date(conn, month_end_iso, fallback=fallback)
    return v if (v and v > 0) else fallback


# ─── Lo que el reconstructor NO ve ───────────────────────────────────────────
def _tenencia_no_vista(conn, uid: int, date_iso: str, vistos: dict):
    """(costo_usd, afirmable) de la tenencia NO-CASH a `date_iso` que
    `_holdings_asof` no puede ver.

    `_holdings_asof` sólo mira `import_normalized_tx` de batches confirmados. Todo
    lo cargado A MANO —y cualquier mes anterior a la primera compra importada—
    queda invisible. El problema no es que falte: es que el silencio se leía como
    "no había nada que valuar" y de ahí salía cobertura 1,0. El código NO PUEDE
    DISTINGUIR "no había nada" de "no vi lo que había", así que tiene que
    preguntarlo en otro lado antes de dar el veredicto optimista.

    `vistos` es {(broker, asset): cantidad} de lo que el reconstructor SÍ valuó.

    ⚠️ TRES AGUJEROS QUE ESTA VERSIÓN CIERRA, todos medidos:
      · `entry_date IS NOT NULL` hacía desaparecer la tenencia sin bajar
        `afirmable`. Y NULL no es teórico: la columna se agregó por ALTER TABLE
        (main.py:892) y el alta manual de Operaciones no la estampa. La foto
        contable volvía a salir con cobertura 1,0 y a fijar el pico.
      · comparaba SÓLO el nombre del activo. Alcanzaba con que el import viera UNA
        unidad de AAPL en IBKR para declarar "ya vistas" 500 unidades de AAPL
        cargadas a mano en Cocos. Los homónimos cross-broker son la norma acá:
        el mismo AL30/GGAL vive en Cocos, Balanz e IOL a la vez.
      · la moneda. `val_mkt`/`val_costo` están en USD; acá se sumaba
        `positions.invested` CRUDO (está en la moneda nativa del lote, main.py:903)
        y `q*pe*fx` MULTIPLICANDO por el TC cuando la convención del repo es
        `usd = nativa / fx_to_usd` (main.py:10026). Error de fx² = 1.562.500×:
        una sola venta en pesos abierta cruzando fin de mes hundía la cobertura
        de 99,68% a 0,02% y borraba el mes entero de la serie.
    """
    costo = 0.0
    afirmable = True

    def _a_usd(monto, moneda, fx=None):
        """`invested`/`entry_price` vienen en la moneda NATIVA del lote."""
        m = (moneda or "").strip().upper()
        if not m or m in ("USD", "USDT", "USDC"):
            return monto
        try:
            tc = float(fx) if fx else None
        except (TypeError, ValueError):
            tc = None
        if not tc or tc <= 0:
            try:
                import main as _m
                tc = float(_m._user_tc_blue(conn, uid))
            except Exception:
                tc = None
        if not tc or tc <= 0:
            return None                    # no se puede afirmar el costo en USD
        return monto / tc

    try:
        for r in conn.execute(
            """SELECT broker, asset, invested, quantity, currency, entry_date
                 FROM positions
                WHERE user_id=? AND COALESCE(is_cash,0)=0""",
            (uid,),
        ).fetchall():
            # Sin entry_date NO se puede afirmar que no estuviera: se cuenta.
            if r["entry_date"] and str(r["entry_date"])[:10] > date_iso:
                continue
            qty_vista = vistos.get((r["broker"], r["asset"]))
            qty = float(r["quantity"] or 0)
            if qty_vista is not None and qty > 0 and qty_vista >= qty - 1e-9:
                continue                   # el import ya valuó al menos esta cantidad
            inv = float(r["invested"] or 0)
            if qty_vista is not None and qty > 0:
                # visto PARCIAL: sólo la fracción no vista queda al costo.
                inv = inv * max(0.0, (qty - qty_vista)) / qty
            usd = _a_usd(inv, r["currency"]) if inv > 0 else 0.0
            if usd is None:
                afirmable = False
            elif usd > 0:
                costo += usd
            elif not r["entry_date"]:
                afirmable = False          # hay algo, sin fecha y sin costo
    except Exception:
        afirmable = False
    try:
        for r in conn.execute(
            """SELECT broker, asset, quantity, entry_price, fx_to_usd, currency,
                      entry_date, date
                 FROM operations WHERE user_id=?""",
            (uid,),
        ).fetchall():
            ed = str(r["entry_date"])[:10] if r["entry_date"] else None
            sd = str(r["date"])[:10] if r["date"] else None
            if ed and ed > date_iso:
                continue                   # se abrió después
            if sd and sd <= date_iso:
                continue                   # ya estaba cerrada
            if not ed and not sd:
                continue
            if (r["broker"], r["asset"]) in vistos:
                continue
            q = float(r["quantity"] or 0)
            pe = float(r["entry_price"] or 0)
            usd = _a_usd(q * pe, r["currency"], r["fx_to_usd"]) if (q and pe) else 0.0
            if usd is None:
                afirmable = False
            elif usd > 0:
                costo += usd
            else:
                afirmable = False
    except Exception:
        afirmable = False
    return costo, afirmable


# ─── La caja de cada broker, medida y al dólar de su fecha ───────────────────
# ⚠️ LA CAJA SE MIDE, NO SE DEDUCE DE LA CONTABILIDAD.
# La foto era "costo + no realizado": la caja quedaba implícita, como lo que la
# contabilidad (aportes − retiros + realizado, en dólares) no explica con lo
# invertido. Eso falla de dos maneras, y las dos se midieron en la misma cuenta
# (4 brokers, 44 operaciones desde 03/2024, Cocos e IOL en pesos):
#   · EN PESOS, LA DEVALUACIÓN NO ENTRABA NUNCA EN EL PASADO. Cada aporte en pesos
#     está en la contabilidad al dólar de SU fecha (`f76c7bdb`), pero lo que hay en
#     la cuenta a fin de mes son PESOS, y valen lo que dice el dólar de ESE fin de
#     mes. La pérdida por devaluación del efectivo y del costo en pesos aparecía
#     de golpe en la primera medición del cron: foto del 31/10/2026 US$ 72.606
#     contra US$ 67.199 de tenencia más caja a su fecha → «Últimos 3 días −9,3 %»
#     y «Noviembre −US$ 6.766» en el Dashboard de una cartera que se había movido
#     −US$ 347. El error crecía con el tiempo (US$ 1.523 en 12/2024, 5.407 en
#     10/2026): era la devaluación acumulada.
#   · EN DÓLARES, LA VENTA PARCIAL. El realizado de la contabilidad sale del lote
#     vendido (FIFO) y la tenencia de acá, del costo promedio: con una venta
#     parcial de NVDA a dos precios de compra, la caja deducida quedaba US$ 81
#     arriba de la real.
#
# El arreglo: la caja de fin de mes de cada broker sale de los movimientos
# importados (`ledger_replay.cash_en`, en la moneda del broker) y se valúa con el
# MISMO motor y el MISMO dólar que la tenencia de ese mes, igual que hace el cron
# con la caja anotada. Sólo si los movimientos explican la caja de HOY (la prueba
# de `verificar_contra_hoy`): si hubo plata cargada a mano o algo que el archivo
# no trae, la caja del pasado no se puede afirmar y ese broker queda como antes,
# deducido, anotado en `cajas_sin_medir`.
_MONEDAS_DE_CAJA = {"ARS": ("ARS",)}
_MONEDAS_DOLAR = ("USD", "USDT")


def _monedas_de_caja(moneda_broker) -> tuple:
    return _MONEDAS_DE_CAJA.get((moneda_broker or "USDT").upper(), _MONEDAS_DOLAR)


def _caja_del_replay(saldos: dict, broker: str, moneda_broker) -> float:
    return sum(saldos.get((broker, mon), 0.0) for mon in _monedas_de_caja(moneda_broker))


def _cajas_explicadas(conn, uid: int, bcur: dict, tc_hoy: float, today: _date) -> set:
    """Brokers cuya caja de HOY la reproducen los movimientos importados."""
    import ledger_replay as _lr
    if not bcur:
        return set()
    replay = _lr.cash_en(conn, uid, today.isoformat())
    real: dict = {}
    for r in conn.execute(
            "SELECT broker, asset, invested FROM positions "
            "WHERE user_id=? AND COALESCE(is_cash,0)=1", (uid,)).fetchall():
        b = r["broker"]
        if b in bcur and (r["asset"] or "").upper() in _monedas_de_caja(bcur[b]):
            real[b] = real.get(b, 0.0) + float(r["invested"] or 0)
    # ⚠️ QUE LA CAJA DE HOY COINCIDA NO ALCANZA: LA CONTABILIDAD TAMBIÉN TIENE QUE
    # SALIR DEL ARCHIVO. Una operación cerrada cargada a mano sin mover el efectivo
    # (sólo el resultado) deja la caja igual, pero suma su ganancia a la
    # contabilidad desde su fecha. Medir la caja la borraba del pasado:
    # tests/test_reconstruccion_sigue_a_la_contabilidad.py (US$ 300 de junio).
    # Con algo cargado a mano —una operación sin lote importado o un aporte a
    # mano— el broker queda con la caja deducida, como antes.
    a_mano = {r["broker"] for r in conn.execute(
        "SELECT DISTINCT o.broker FROM operations o WHERE o.user_id=? AND NOT EXISTS "
        "(SELECT 1 FROM import_op_links l WHERE l.operation_id = o.id)", (uid,)).fetchall()}
    try:
        a_mano |= {r["broker"] for r in conn.execute(
            "SELECT DISTINCT broker FROM monthly_entries WHERE user_id=? AND broker<>'global' "
            "AND (ABS(COALESCE(manual_deposits,0)) > 0.005 "
            "OR ABS(COALESCE(manual_withdrawals,0)) > 0.005)", (uid,)).fetchall()}
    except Exception:           # base vieja sin las columnas manual_*
        if getattr(main, "USANDO_PG", False):
            conn.rollback()
        return set()
    explicados = set()
    for b, mon in bcur.items():
        if b in a_mano:
            continue
        a, z = _caja_del_replay(replay, b, mon), real.get(b, 0.0)
        # Un dólar de diferencia, o el 1 % de la caja: redondeos de comisiones.
        un_dolar = (tc_hoy or 1.0) if (mon or "").upper() == "ARS" else 1.0
        if abs(a - z) <= max(abs(z) * 0.01, un_dolar):
            explicados.add(b)
    return explicados


def _costo_por_broker(conn, uid: int) -> dict:
    """{broker: [(year, month, costo)]} de la contabilidad POR BROKER, en orden."""
    out: dict = {}
    for r in conn.execute(
            "SELECT broker, year, month, capital_inicio, deposits, withdrawals, pnl_realized "
            "FROM monthly_entries WHERE user_id=? AND broker <> 'global' "
            "ORDER BY broker, year, month", (uid,)).fetchall():
        costo = ((r["capital_inicio"] or 0) + (r["deposits"] or 0)
                 - (r["withdrawals"] or 0) + (r["pnl_realized"] or 0))
        out.setdefault(r["broker"], []).append((r["year"], r["month"], costo))
    return out


def _costo_del_broker_en(filas: list, y: int, m: int) -> float:
    """El costo del broker en el mes: su fila, o la del último mes que tuvo (en el
    mes sin fila la contabilidad no se movió, igual que en `_meses_a_reconstruir`)."""
    costo = 0.0
    for (yy, mm, c) in filas or ():
        if (yy, mm) > (y, m):
            break
        costo = c
    return costo


# ─── Tenencias a fin de mes (net BUY−SELL + costo promedio) ───────────────────
def _holdings_asof(conn, uid: int, date_iso: str) -> list:
    """[{broker, asset, asset_type, quantity, invested(costo)}] tenidas a date_iso.
    qty = Σ BUY − Σ SELL; costo = precio promedio de compra × qty tenida.

    ⚠️ Lee de `TX_VIVAS`: sólo imports confirmados y SIN las filas que la persona
    borró. Antes filtraba el lote confirmado pero no la lápida (`excluded_at`), y
    una compra borrada seguía en la foto valuada a mercado: con MSFT de 100 a 150,
    la curva publicaba +US$ 500 de una suba que la persona ya no tenía, mientras
    `positions` (el rebuild sí filtra) mostraba bien la cartera."""
    from importing.schema import TX_VIVAS
    rows = conn.execute(
        f"""SELECT n.broker AS broker, n.asset_symbol AS asset, n.asset_type AS asset_type,
                  MAX(CASE WHEN n.operation_type='BUY' AND COALESCE(n.currency,'') <> ''
                           THEN UPPER(n.currency) END) AS currency,
                  SUM(CASE n.operation_type WHEN 'BUY'  THEN COALESCE(n.quantity,0)
                                            WHEN 'SELL' THEN -COALESCE(n.quantity,0)
                                            ELSE 0 END) AS qty,
                  SUM(CASE n.operation_type WHEN 'BUY'
                        THEN COALESCE(n.gross_amount, COALESCE(n.quantity,0)*COALESCE(n.unit_price,0))
                        ELSE 0 END) AS buy_amt,
                  SUM(CASE n.operation_type WHEN 'BUY' THEN COALESCE(n.quantity,0) ELSE 0 END) AS buy_qty
             FROM {TX_VIVAS}
            WHERE b.user_id = ?
              AND n.asset_symbol IS NOT NULL AND n.asset_symbol != ''
              AND n.operation_type IN ('BUY','SELL')
              AND n.date <= ?
            GROUP BY n.broker, n.asset_symbol, n.asset_type""",
        (uid, date_iso),
    ).fetchall()
    out = []
    for r in rows:
        qty = r["qty"] or 0
        if qty <= 1e-9:        # cerrada / sobre-vendida → no es tenencia
            continue
        buy_qty = r["buy_qty"] or 0
        avg_cost = (r["buy_amt"] / buy_qty) if buy_qty > 0 else 0
        # currency: para que compute_broker_value_usd respete el costo USD (sin ÷MEP)
        # de bonos/ONs/FCI-USD/CEDEAR-MEP en un broker ARS. Se TAGEA desde las patas de
        # COMPRA (no se particiona el GROUP BY): una VENTA de reducción sin cash (rescate
        # parcial / reducción de capital / canje) llega con moneda vacía→'ARS' y, si
        # particionáramos, caería en otro bucket y NO restaría la cantidad (qty inflada).
        # MAX prioriza 'USD' si alguna compra fue en dólares (el caso "costo en dólares").
        out.append({
            "broker": r["broker"], "asset": r["asset"], "asset_type": r["asset_type"],
            "currency": (r["currency"] or None), "quantity": qty, "invested": avg_cost * qty,
        })
    return out


def _month_end(year: int, month: int) -> str:
    return _date(year, month, calendar.monthrange(year, month)[1]).isoformat()


# ─── Persistencia: el snapshot RECONSTRUIDO ──────────────────────────────────
#
# Por que el backfill NO escribe mas en `monthly_entries.capital_final`:
# `_repair_monthly_chain` (main.py:9314-9318) recomputa, para TODO mes cerrado,
#     capital_final = capital_inicio + deposits - withdrawals + pnl_realized
# o sea EL COSTO, y se dispara desde ~20 lugares de main.py (cualquier alta,
# edicion o borrado de una operacion). El MtM que este script dejaba ahi se
# borraba solo en la siguiente pasada: el ancla se autodestruia. Ahora el
# resultado vive donde nadie lo recalcula al costo — en `snapshots`, con su
# propio `source` — y `monthly_entries` queda intacto (sigue siendo la
# contabilidad, que es lo que tiene que ser).
MTM_SOURCE = "mtm_backfill"
# Entra en `huella_de_entrada`. Subirlo cuando cambia lo que la foto vale para la
# MISMA contabilidad. 2 = la caja medida y al dólar-MEP de su fecha. 3 = los
# bonos al cierre de su mes en data912 (antes, al costo).
MOTOR_VERSION = 3

# ⚠️ YA NO HAY PISO DE COBERTURA. La cobertura se estampa y SE MUESTRA; no filtra
# nada. Un piso —fuera 0,70 o 0,995— esconde la curva entera al que no llega, que
# es exactamente lo contrario de lo que hace falta: ver el número y saber qué parte
# es estimada. Se deja la constante sólo porque hay tests que la referencian como
# valor de ejemplo.
COBERTURA_REFERENCIA = 0.70


def _twr_base_apto(coverage):
    """(base, apto) de una foto reconstruida con ESA cobertura. Una sola fuente:
    `twr.base_y_apto_para`, la misma que usan los otros tres escritores y la
    migración. Si acá se escribiera la regla a mano, habría dos."""
    import twr as _twr
    return _twr.base_y_apto_para(_twr.RECONSTRUIDO, coverage)


def _persist_mtm_snapshots(conn, uid: int, por_mes: dict) -> int:
    """UPSERT de las fotos reconstruidas. Devuelve cuantas escribio.

    Dos defectos del camino viejo que esto cierra:
      · `_backfill_snapshots_from_monthly` estampa source='import'
        (persister.py:1290) → el trabajo a mercado salia disfrazado de contable
        y cualquier filtro que se escriba despues lo descarta.
      · usaba `ON CONFLICT DO NOTHING` (persister.py:1291) → no pisaba ni
        siquiera la fila sintetica que el propio import habia dejado antes, asi
        que reconstruir no cambiaba nada de lo que el grafico ya mostraba.

    Lo que SI se respeta: una MEDICION real del cron nunca se pisa. El criterio
    no se re-escribe aca, se le pregunta a `twr.clasificar_fila` — si dos
    modulos deciden distinto que fila es una medicion, uno de los dos esta mal.
    """
    if not por_mes:
        return 0
    import json as _json
    from twr import clasificar_serie, MEDICION, netdep_canonico

    # ⚠️ EL APORTADO ES EL DE `twr.netdep_canonico` (baseline + flujos de las filas
    # 'global'), la misma cuenta que estampa el cron y que ancla la curva. Acá
    # vivía una TERCERA copia de esa cuenta (la del persister se unificó el
    # 2026-10-02): primero sin el baseline —un mes real de +US$2.000 salía "Mes
    # difícil −61,2% · Aportaste US$100.000 de capital nuevo"— y después con un
    # `get(mes, 0.0)` que estampaba CERO cuando el mes ya no estaba en la
    # contabilidad.
    # Cada foto trae su `net_dep` de `backfill_user`, medido en el mismo instante
    # que su valor (ver ahí por qué). El canónico de acá abajo es sólo para quien
    # llama esta función con fotos armadas a mano.
    _canon = None

    # ⚠️ El flag va POR FECHA, igual que en twr. Con "¿tiene posiciones HOY?" este
    # módulo y `twr` clasificaban distinto la misma fila: una foto REAL del cron de
    # cuando la persona estaba 100% cash (fx sí, holdings NULL) es MEDICION para
    # twr e INTRADIA acá — y entraba al UPSERT, reemplazando la medición de mercado
    # por la cadena contable, con source='mtm_backfill'. Destructivo y no
    # reversible, y rompía la promesa escrita en el docstring de esta función.
    from twr import primera_fecha_con_posiciones
    primera_pos = primera_fecha_con_posiciones(conn, uid)
    # ⚠️ `clasificar_serie`, NO fila por fila. Éste era el QUINTO lector, y el
    # test de contrato lo encontró: mirando una fila legacy sola no se distingue
    # una foto del cron de una del browser, así que este UPSERT pisaba mediciones
    # reales que los otros cuatro lectores ya veían como tales.
    _filas = conn.execute(
        "SELECT date, total_value, fx_to_usd_blue, holdings_json, source, mtm_coverage "
        "FROM snapshots WHERE user_id=? ORDER BY date", (uid,)).fetchall()
    _clases = clasificar_serie(_filas, primera_pos)
    existentes = {r["date"]: c for r, c in zip(_filas, _clases)}

    escritos = 0
    for ym, info in sorted(por_mes.items()):
        d = info["date"]
        if existentes.get(d) == MEDICION:
            continue                      # foto real del cron: manda ella
        net_dep = info.get("net_dep")
        if net_dep is None:
            if _canon is None:
                # Sin ninguna fila en la contabilidad no hay aportado que afirmar:
                # 0 es como la columna escribe "no lo tengo" (NOT NULL DEFAULT 0).
                _canon = netdep_canonico(conn, uid) or (lambda _fecha: 0.0)
            net_dep = _canon(d)
        # ⚠️ EL ESTAMPO SALE DE LA COBERTURA DE **ESTA** FOTO (ronda 11). El
        # reconstructor es el único que sabe qué fracción del valor de ESE mes se
        # pudo valuar a precio real, así que es el que tiene que decidir la base —
        # una vez, cuando escribe. Deducirla después, en lectura, es lo que hizo que
        # la misma fila recibiera respuestas distintas según quién preguntaba y
        # cuándo. Con cobertura baja el `total_value` de la foto ES el costo (lo que
        # no se pudo precear entra con unrealized 0): base contable, y nunca apta.
        _base, _apto = _twr_base_apto(info["coverage"])
        conn.execute(
            """INSERT INTO snapshots
                 (user_id, date, total_value, total_invested, net_deposited,
                  holdings_json, source, mtm_coverage, base, apto)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 total_value   = excluded.total_value,
                 net_deposited = excluded.net_deposited,
                 holdings_json = excluded.holdings_json,
                 source        = excluded.source,
                 mtm_coverage  = excluded.mtm_coverage,
                 base          = excluded.base,
                 apto          = excluded.apto
               -- Candado contra la carrera: la clase se leyó al empezar la corrida
               -- (minutos antes, por Yahoo). Si en el medio un "deshacer" devolvió
               -- la medición del cron a esta fecha, no se pisa (auditoría 4: la
               -- medición se perdía para siempre).
               WHERE COALESCE(snapshots.source, '') <> 'cron'
                 AND NOT (snapshots.source IS NULL
                          AND COALESCE(snapshots.holdings_json, '') <> '')""",
            (uid, d, info["value"], info["cost"], net_dep,
             _json.dumps(info["holdings"]) if info["holdings"] else None,
             MTM_SOURCE, info["coverage"], _base, _apto),
        )
        escritos += 1
    return escritos


# ─── Backfill de un usuario ───────────────────────────────────────────────────
# Cuántas pasadas se intentan si la contabilidad cambia mientras se reconstruye.
# La primera tarda (Yahoo); las siguientes reusan `_HIST_CACHE` y son de
# milisegundos, así que tres cambios seguidos sólo pasan si algo la está
# reescribiendo sin parar — y ahí no hay una contabilidad que describir.
_PASADAS = 3


def _huella_contable(conn, uid: int) -> list:
    """Las filas 'global' de la contabilidad de las que salen el valor (costo) y el
    aportado de cada foto. Si cambian durante la corrida, las fotos ya valuadas
    describen otra contabilidad que la que se va a leer al escribir."""
    return [(r["year"], r["month"], r["capital_inicio"], r["deposits"],
             r["withdrawals"], r["pnl_realized"])
            for r in conn.execute(
                "SELECT year, month, capital_inicio, deposits, withdrawals, pnl_realized "
                "FROM monthly_entries WHERE user_id=? AND broker='global' "
                "ORDER BY year, month", (uid,)).fetchall()]


def huella_de_entrada(conn, uid: int, today: _date) -> str:
    """Resumen de TODO lo que `backfill_user` lee para los meses cerrados.

    Si no cambió, una reconstrucción nueva escribiría exactamente las mismas fotos
    (con los mismos precios), así que no hace falta correrla. Existe porque el
    Dashboard manda cada 90 s un aviso que pasa por `_repair_monthly_chain` aunque
    no cambie nada: sin esta comparación, cada refresco de cada persona era una
    reconstrucción entera —y después de un reinicio, una pasada por Yahoo—.

    Lo que lee la reconstrucción, y entra acá: las filas 'global' de la
    contabilidad, los lotes confirmados, las compras y ventas importadas (con su
    lápida `excluded_at`), las posiciones y operaciones que mira
    `_tenencia_no_vista`, los activos con split y los brokers. Lo del mes en curso
    no entra (ese mes no se reconstruye). Afuera queda lo que no es de la cuenta:
    precios y dólar histórico."""
    import hashlib
    hoy = _date(today.year, today.month, 1).isoformat()
    ym_hoy = today.year * 100 + today.month
    pg = bool(getattr(main, "USANDO_PG", False))
    partes = []

    # ⚠️ EL TEXTO LO ARMA LA BASE, NO PYTHON. Convertir miles de filas en tuplas de
    # Python retiene el turno del intérprete (GIL) fila por fila: medido por la
    # auditoría con las 10 cuentas más grandes pidiendo a la vez, la mediana de un
    # POST pasaba de 126 a 814 ms. Armado del lado de la base: 180 ms, y la misma
    # sensibilidad. Una variante por motor: `group_concat` no existe en Postgres.
    def _agregado(cols, desde, orden, *args):
        texto = "||','||".join(f"COALESCE(CAST({c} AS TEXT), '~')" for c in cols)
        if pg:
            sql = f"SELECT count(*), string_agg({texto}, '|' ORDER BY {orden}) FROM {desde}"
        else:
            # El orden lo fija la consulta de adentro (SQLite < 3.44 no admite
            # ORDER BY dentro de group_concat).
            sql = (f"SELECT count(*), group_concat(t, '|') FROM "
                   f"(SELECT {texto} AS t FROM {desde} ORDER BY {orden})")
        try:
            r = conn.execute(sql, args).fetchone()
            partes.append(f"{r[0]}:{r[1] or ''}")
        except Exception as ex:          # columna que no existe en una base vieja
            partes.append(repr(type(ex)))
            if pg:                       # en Postgres el error aborta la transacción
                try:
                    conn.rollback()
                except Exception:
                    pass

    _agregado(("year", "month", "capital_inicio", "deposits", "withdrawals", "pnl_realized"),
              "monthly_entries WHERE user_id=? AND broker='global' AND year*100+month < ?",
              "year, month", uid, ym_hoy)
    _agregado(("id",), "import_batches WHERE user_id=? AND status='confirmed'", "id", uid)
    _agregado(("n.id", "n.date", "n.broker", "n.asset_symbol", "n.asset_type",
               "n.operation_type", "n.quantity", "n.gross_amount", "n.unit_price",
               "n.currency", "CASE WHEN n.excluded_at IS NULL THEN 1 ELSE 0 END"),
              "import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
              "WHERE b.user_id=? AND b.status='confirmed' "
              "AND n.operation_type IN ('BUY','SELL') AND n.date < ?",
              "n.id", uid, hoy)
    _agregado(("id", "broker", "asset", "quantity", "invested", "currency", "entry_date"),
              "positions WHERE user_id=? AND COALESCE(is_cash,0)=0 "
              "AND (entry_date IS NULL OR entry_date < ?)", "id", uid, hoy)
    _agregado(("s.asset",),
              "(SELECT DISTINCT asset FROM positions WHERE user_id=? "
              "AND split_adjusted_through IS NOT NULL) s", "s.asset", uid)
    # TODAS las operaciones, sin filtro de fecha: `_tenencia_no_vista` cuenta una
    # operación sin `entry_date` en todos los meses cerrados anteriores a su cierre
    # —aunque se haya cargado hoy—. Un filtro propio acá la dejaba afuera (medido
    # por la auditoría: cobertura 1,0 guardada contra 0,40 real). La regla vive en
    # un solo lugar: lo que mira la reconstrucción entra entero.
    _agregado(("id", "broker", "asset", "quantity", "entry_price", "fx_to_usd", "currency",
               "entry_date", "date"), "operations WHERE user_id=?", "id", uid)
    _agregado(("name", "currency"), "brokers WHERE user_id=?", "name", uid)
    # La caja de cada broker (`_cajas_explicadas`): los
    # movimientos que la mueven —de cualquier fecha: la prueba se hace contra la
    # caja de HOY—, la caja anotada y la contabilidad por broker que se descuenta.
    _agregado(("n.id", "n.date", "n.broker", "n.operation_type", "n.gross_amount",
               "n.quantity", "n.fees", "n.taxes", "n.currency", "n.settlement_currency",
               "CASE WHEN n.excluded_at IS NULL THEN 1 ELSE 0 END"),
              "import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
              "WHERE b.user_id=? AND b.status='confirmed' "
              "AND n.operation_type NOT IN ('BUY','SELL')", "n.id", uid)
    _agregado(("broker", "asset", "invested"),
              "positions WHERE user_id=? AND COALESCE(is_cash,0)=1", "broker, asset", uid)
    _agregado(("operation_id",),
              "import_op_links WHERE operation_id IS NOT NULL AND batch_id IN "
              "(SELECT id FROM import_batches WHERE user_id=?)", "operation_id", uid)
    _agregado(("broker", "year", "month", "capital_inicio", "deposits", "withdrawals",
               "pnl_realized"),
              "monthly_entries WHERE user_id=? AND broker<>'global' AND year*100+month < ?",
              "broker, year, month", uid, ym_hoy)
    # Cambiar CÓMO se valúa también deja vieja la historia escrita: con esto, al
    # publicar un cambio del motor cada cuenta se reconstruye una vez.
    partes.append(f"motor:{MOTOR_VERSION}")
    return hashlib.sha256("\n".join(partes).encode()).hexdigest()


def _meses_a_reconstruir(huella: list, today: _date) -> list:
    """[(year, month, fila, propia)]: TODOS los meses cerrados desde el primero de
    la contabilidad, cada uno con la fila 'global' que lo rige — la suya
    (`propia=True`) o, si no tiene, la del último mes que tuvo.

    ⚠️ LA CONTABILIDAD NO TIENE FILA PARA TODOS LOS MESES, Y LA CURVA SÍ LA NECESITA.
    `monthly_entries` sólo crea la fila del mes con depósitos, retiros o ventas
    (`importing/rebuild.py::_ensure_monthly_rows` y los flujos). Un mes con sólo
    compras, o sin nada, no la tiene. Antes se reconstruía únicamente sobre esas
    filas, así que esos meses quedaban sin foto, y con un solo mes faltante dos
    fotos quedaban a ~60 días: más que `twr.MAX_HUECO_DIAS` (45), la serie se
    parte y el rendimiento desaparece (`serie_partida`). Medido: depósito de
    10.000 + 40 AAPL en enero y 100 por mes hasta octubre → +16,95 %; sacando
    sólo el depósito de junio → sin número. El inversor que compra y mantiene
    —que no deposita todos los meses— era el que se quedaba sin curva.

    El mes sin fila no es un mes sin contabilidad: es un mes en el que la
    contabilidad NO SE MOVIÓ. `_repair_monthly_chain` encadena por encima del
    hueco (`capital_inicio` del mes siguiente = `capital_final` del anterior que
    tiene fila), así que su costo es exactamente el del último mes con fila, con
    flujos y realizado en cero. Las tenencias sí cambian (compras) y salen de
    `_holdings_asof` a su fecha, como en cualquier otro mes.

    Llega hasta el último mes CERRADO y no hasta la última fila: después de su
    último depósito la persona sigue teniendo la cartera, y la foto de ese último
    mes con flujo quedaba a meses de la primera medición del cron — el mismo corte.
    """
    if not huella:
        return []
    por_ym = {(f[0], f[1]): f for f in huella}
    y, m = huella[0][0], huella[0][1]
    out, rige = [], None
    while (y, m) < (today.year, today.month):
        propia = (y, m) in por_ym
        if propia:
            rige = por_ym[(y, m)]
        out.append((y, m, rige, propia))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def backfill_user(conn, uid: int, today: _date, _pasada: int = 1) -> dict:
    """Devuelve {uid, skipped, reason, months:[{ym, before, after}], cost_fallbacks,
    cash_warning}. NO commitea (lo hace el caller). Idempotente."""
    import twr as _twr
    res = {"uid": uid, "skipped": False, "reason": None, "months": [],
           "cost_fallbacks": 0, "cash_warning": False, "snapshots_escritos": 0}
    if _pasada == 1:
        _fallas_yahoo().clear()
    # Lo que describen las fotos de esta corrida; se compara al final.
    res["huella"] = entrada = huella_de_entrada(conn, uid, today)

    # Cuenta reconstruible solo si hay import confirmado.
    has_import = conn.execute(
        "SELECT 1 FROM import_batches WHERE user_id=? AND status='confirmed' LIMIT 1", (uid,),
    ).fetchone()
    if not has_import:
        # Si ya no hay import (se revirtió el único), las fotos reconstruidas que
        # quedaron —p. ej. de meses con movimientos cargados a mano antes del
        # import, que el revert no borra— describen una cuenta que ya no existe.
        res["snapshots_borrados"] = conn.execute(
            "DELETE FROM snapshots WHERE user_id=? AND source=?", (uid, MTM_SOURCE)).rowcount
        res.update(skipped=True, reason="sin import confirmado (cuenta manual)")
        return res

    # Valor (costo) y aportado de cada foto salen de UNA lectura de la
    # contabilidad, hecha acá: la huella de abajo verifica al final que siga
    # siendo la misma.
    huella = _huella_contable(conn, uid)
    if not huella:
        # Sin contabilidad no hay nada que las fotos reconstruidas puedan describir.
        res["snapshots_borrados"] = conn.execute(
            "DELETE FROM snapshots WHERE user_id=? AND source=?", (uid, MTM_SOURCE)).rowcount
        res.update(skipped=True, reason="sin monthly_entries")
        return res
    _canon = _twr.netdep_canonico(conn, uid)
    # Sólo para el "antes" del resumen: lo que la cadena contable mostraba.
    _cf_contable = {(r["year"], r["month"]): r["capital_final"] for r in conn.execute(
        "SELECT year, month, capital_final FROM monthly_entries "
        "WHERE user_id=? AND broker='global'", (uid,)).fetchall()}

    brokers = [dict(r) for r in conn.execute(
        "SELECT name, currency FROM brokers WHERE user_id=?", (uid,)).fetchall()]
    ars_names, ar_usd_names = sj._broker_name_sets(brokers)
    bcur = {b["name"]: (b["currency"] or "USDT") for b in brokers}

    # Activos con split aplicado → costo (qty actual post-split × precio histórico
    # pre-split inflaría). Conservador: cualquier asset con split_adjusted_through.
    split_assets = set()
    try:
        for r in conn.execute(
            "SELECT DISTINCT asset FROM positions WHERE user_id=? AND split_adjusted_through IS NOT NULL", (uid,)):
            split_assets.add(r["asset"])
    except Exception:
        pass

    por_mes: dict = {}                         # {ym: foto reconstruida}
    start_iso = f"{huella[0][0]:04d}-{huella[0][1]:02d}-01"

    # La caja de cada broker, medida y al dólar de cada fin de mes (ver "LA CAJA
    # SE MIDE, NO SE DEDUCE DE LA CONTABILIDAD").
    import ledger_replay as _lr
    try:
        _tc_hoy = main._user_tc_blue(conn, uid)
    except Exception:
        _tc_hoy = 1415.0
    cajas_ok = _cajas_explicadas(conn, uid, bcur, _tc_hoy, today)
    res["cajas_sin_medir"] = sorted(set(bcur) - cajas_ok)
    costo_broker = _costo_por_broker(conn, uid) if cajas_ok else {}

    # El mes en curso (y cualquier fila futura) no se toca: lo maneja el flujo live.
    for y, m, fila, propia in _meses_a_reconstruir(huella, today):
        d = _month_end(y, m)
        ym = f"{y}-{m:02d}"
        hold = _holdings_asof(conn, uid, d)
        try:
            live_blue = main._user_tc_blue(conn, uid)
        except Exception:
            live_blue = 1415.0
        blue = _hist_blue(conn, d, live_blue)
        # ⚠️ AL MEP, COMO EL CRON. La medición de hoy valúa todo lo que está en
        # pesos al dólar-MEP (`take_snapshot_for_user`, "CONVENCIÓN DE
        # VALUACIÓN"); acá se usaba el blue como si fuera el MEP. La foto del
        # último fin de mes y la de hoy quedaban con dos dólares distintos, y la
        # resta fabricaba la brecha como movimiento: 31/10/2026 blue 1.555 contra
        # MEP 1.575, −1,3 % de toda la parte en pesos. Mismo dólar que el resto de
        # la app (`fx.fx_for_date`: el MEP de la fecha y, antes de que haya serie
        # de MEP, el blue).
        mep = _hist_mep(conn, d, blue)

        # Unrealized por broker (valor_mercado − costo), con guardas → costo.
        # `val_mkt`/`val_costo` miden la COBERTURA del mes: cuanto del valor
        # no-cash salio de un precio real y cuanto cayo al costo. Sin ese numero
        # un mes casi enteramente al costo se publicaria como medido.
        unreal_by_broker: dict = {}
        efectivo_by_broker: dict = {}
        val_mkt = val_costo = 0.0
        by_asset: dict = {}
        assets_al_costo: set = set()
        for h in hold:
            b = h["broker"]
            btype = bcur.get(b, "USDT")
            pkey = sj.position_price_key(
                {"asset": h["asset"], "broker": b, "asset_type": h["asset_type"]},
                ars_names, ar_usd_names)
            # precio histórico del mes (None si no hay / split → costo)
            price = None
            _px_sub = None
            if h["asset"] not in split_assets:
                # Primero el camino corto: si es un CEDEAR que cotiza en dólares,
                # se valúa por su subyacente y no hace falta el CCL histórico.
                _px_sub = _precio_por_subyacente(h["asset"], ym, start_iso)
                if _px_sub is None:
                    hist = _fetch_monthly_close(pkey, start_iso)
                    price = hist.get(ym)
            if _px_sub is not None:
                val = _px_sub * float(h["quantity"] or 0)
                inv = float(h["invested"] or 0)
                price = _px_sub                 # hubo precio real: no es fallback
            else:
                prices = {pkey: price} if price is not None else {}
                r = sj.compute_broker_value_usd(
                    [h], prices, btype, blue, broker_name=b, cedear_rate=mep)
                val = r.get("value", 0) or 0
                inv = r.get("invested", 0) or 0
            u = val - inv
            # ── Guard anti-distorsión (espejo de trustMktValue del front) ─────────
            # Si el valor a mercado se va absurdamente lejos del costo, NO lo
            # confiamos → degradamos a costo (u=0). Atrapa precios per-100 de bonos,
            # colisiones de ticker, y cross-currency mal valuado que si no metían un
            # capital_final NEGATIVO gigante (ej: 485 → -592.944). Renta fija cotiza
            # cerca de par → banda estrecha [0.02×, 4×]; el resto permite multibaggers
            # reales → [0.002×, 50×]. Un valor ≤ 0 con costo > 0 es siempre bug.
            trusted = True
            if val < 0:
                trusted = False                 # valor de mercado < 0 = SIEMPRE bug
                                                # (incluso con costo 0 → free lots)
            elif inv > 0:
                _fixed = (h.get("asset_type") or "").upper() in (
                    "BOND", "BONO", "ON", "LETRA", "LECAP")
                _mult = val / inv
                _lo, _hi = (0.02, 4.0) if _fixed else (0.002, 50.0)
                if _mult < _lo or _mult > _hi:
                    trusted = False
            if not trusted:
                u = 0.0                         # precio no confiable → costo
            unreal_by_broker[b] = unreal_by_broker.get(b, 0.0) + u
            # Valor EFECTIVO del holding en la foto: a mercado si el precio se
            # pudo usar, al costo si degrado (ahi u quedo en 0).
            efectivo = inv + u
            by_asset[h["asset"]] = by_asset.get(h["asset"], 0.0) + efectivo
            efectivo_by_broker[b] = efectivo_by_broker.get(b, 0.0) + efectivo
            if price is None or not trusted:
                res["cost_fallbacks"] += 1
                val_costo += efectivo
                # Por NOMBRE, no sólo el conteo: un porcentaje pelado no le dice al
                # usuario qué hacer; "tus FCI" sí.
                assets_al_costo.add(h["asset"])
            else:
                val_mkt += efectivo

        total_unreal = sum(unreal_by_broker.values())

        # ⚠️ LA TENENCIA QUE EL RECONSTRUCTOR NO VE CUENTA COMO COSTO, NO DESAPARECE.
        #
        # Antes, `base_cob == 0` se leia como "cartera 100% cash → la foto es
        # exacta → cobertura 1,0". El razonamiento vale para una cartera de verdad
        # toda en cash, pero el codigo no podia distinguir ESE caso de "no vi lo
        # que habia", y elegia el veredicto optimista. Resultado medido: un import
        # que solo traia un DEPOSIT (la tenencia real vivia en `positions`)
        # persistia 3 fotos con `mtm_coverage=1,0` y CERO precios consultados,
        # etiquetadas 'mtm_backfill' — o sea la cadena contable, que es lo que este
        # trabajo viene a sacar de la curva, ahora con etiqueta de mercado.
        # Antes mentia CON la etiqueta puesta (source='import') y todos los filtros
        # la descartaban; asi era estrictamente peor.
        _vistos = {(h["broker"], h["asset"]): float(h["quantity"] or 0) for h in hold}
        _no_visto, _afirmable = _tenencia_no_vista(conn, uid, d, _vistos)
        val_costo += _no_visto
        if _no_visto > 0:
            res["cost_fallbacks"] += 1
        base_cob = val_mkt + val_costo
        if not _afirmable:
            cobertura = None          # hay tenencia que no veo y no se cuanto vale
        elif base_cob > 0:
            cobertura = val_mkt / base_cob
        else:
            # Cero base Y nada invisible: se puede AFIRMAR que no habia nada
            # no-cash que valuar. Recien ahi 1,0 es un hecho y no un supuesto.
            cobertura = 1.0

        # Valor de la foto = costo(recomputado de columnas estables) + unrealized.
        # Se calcula SOLO para el global y NO se escribe en monthly_entries: ver el
        # comentario de MTM_SOURCE — `_repair_monthly_chain` lo recomputaria al costo.
        # El mes sin fila toma la del último mes que tuvo (ver `_meses_a_reconstruir`):
        # mismo costo, porque en ese mes no hubo flujos ni ventas.
        _, _, ci, dep, wd, pnl = fila
        cost = (ci or 0) + (dep or 0) - (wd or 0) + (pnl or 0)
        # El aportado sale de la MISMA lectura que el costo (la del principio), y
        # no al escribir: así valor y aportado describen siempre la misma
        # contabilidad (ver la huella al final de esta función). En el mes sin
        # fila el canónico ARRASTRA el último aportado; nunca da 0.
        net_dep = _canon(d) if _canon is not None else 0.0
        # Broker con la caja medida: su parte de la foto pasa de "costo + no
        # realizado" (la caja deducida) a tenencia + caja de ESTE fin de mes. Sólo
        # si la contabilidad por broker suma la global: si no, sacar la parte de
        # un broker de la global podría llevarse plata de otro.
        ajuste_caja = 0.0
        if cajas_ok:
            _por_b = {b: _costo_del_broker_en(f, y, m) for b, f in costo_broker.items()}
            if abs(sum(_por_b.values()) - cost) <= max(1.0, abs(cost) * 0.005):
                _saldos = _lr.cash_en(conn, uid, d)
                for b in sorted(cajas_ok):
                    _mon = _monedas_de_caja(bcur.get(b))[0]
                    caja = sj.compute_broker_value_usd(
                        [{"asset": _mon, "broker": b, "asset_type": None, "is_cash": 1,
                          "quantity": 0.0, "invested": _caja_del_replay(_saldos, b, bcur.get(b)),
                          "commissions": 0.0, "price_override": None, "currency": _mon}],
                        {}, bcur.get(b, "USDT"), blue, broker_name=b, cedear_rate=mep)
                    ajuste_caja += ((float(caja.get("value", 0) or 0)
                                     + efectivo_by_broker.get(b, 0.0))
                                    - (_por_b.get(b, 0.0) + unreal_by_broker.get(b, 0.0)))
            else:
                res["meses_con_caja_deducida"] = res.get("meses_con_caja_deducida", 0) + 1
        new_cf = cost + total_unreal + ajuste_caja
        # Clamp definitivo: el MTM NUNCA debe DEJAR un capital_final negativo por
        # culpa de la valuación, ni EMPEORAR uno que ya venía negativo.
        #   • costo sano (≥0) que el unrealized flipearía a negativo → al costo
        #     (ej #417: 485 → -592k → 485; cross-currency / free lots mal valuados).
        #   • costo YA negativo (corrupción vieja de pnl_realized, ej #725/#791): el
        #     MTM no puede empeorarlo → nos quedamos en el MENOS negativo entre costo
        #     y resultado (max). Si el unrealized lo MEJORA (lo acerca a 0 o lo cruza
        #     a positivo), eso sí se respeta.
        # Los corruptos siguen rotos: el costo en sí está mal → es otro fix.
        if new_cf < 0:
            new_cf = max(cost, new_cf)
        # "Antes" es lo que la curva MOSTRABA: la foto que ya estaba, y solo si no
        # habia ninguna, la cadena contable (que en el mes sin fila es el costo
        # arrastrado).
        prev_snap = conn.execute(
            "SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
            (uid, d)).fetchone()
        if prev_snap is not None:
            before_global = prev_snap["total_value"]
        elif propia:
            before_global = _cf_contable.get((y, m)) or 0
        else:
            before_global = cost
        after_global = new_cf
        cost_global = cost
        _cob = round(cobertura, 4) if cobertura is not None else None
        res["months"].append({"ym": ym, "before": before_global, "after": after_global,
                              "coverage": _cob, "sin_fila": not propia})
        por_mes[ym] = {"date": d, "value": after_global, "cost": cost_global,
                       "net_dep": net_dep, "coverage": _cob,
                       "holdings": [{"asset": a, "value_usd": round(v, 2),
                                     "al_costo": a in assets_al_costo}
                                    for a, v in by_asset.items()]}

    # ⚠️ SI LA CONTABILIDAD CAMBIÓ DURANTE LA CORRIDA, SE VUELVE A EMPEZAR.
    # Entre la primera lectura y acá pasan minutos (Yahoo, 8 s de tope por activo),
    # y es justo cuando la persona acaba de importar y mira lo que cargó: borrar un
    # depósito repetido en ese rato es el uso normal, no un caso raro. Medido
    # (tests/test_reconstruccion_aportado_canonico.py), escribiendo lo que había:
    #   · el mes que desaparecía antes de valuarlo quedaba con una foto que VALÍA 0;
    #   · el aportado se leía al final con la copia vieja, que estampaba 0 para el
    #     mes que ya no estaba y, para el que seguía, el aportado de DESPUÉS sobre
    #     el valor de ANTES: +US$ 5.800 y −4.600 en meses que ganaron 800 y 400;
    #   · aun leyendo valor y aportado juntos, la foto describe la contabilidad
    #     VIEJA y la base del libro del asesor (el mayor aportado) guardaba el
    #     depósito borrado: 12 % → 8 %.
    #   · borrar una COMPRA en ese rato no toca la contabilidad, pero sí la
    #     tenencia: los meses ya valuados la seguían teniendo a mercado
    #     (tests/test_compra_borrada_fuera_de_la_curva.py).
    # No se escribe nada que describa una contabilidad que ya no existe.
    # Por eso se compara la huella COMPLETA (`huella_de_entrada`: incluye las
    # compras y ventas con su lápida), no sólo las filas 'global': una compra
    # borrada o un promedio editado en Cartera a mitad de corrida no tocan esas
    # filas (medido por la auditoría: marzo escrito en 10.000 cuando ya era 11.000).
    if (_huella_contable(conn, uid) != huella
            or huella_de_entrada(conn, uid, today) != entrada):
        if _pasada < _PASADAS:
            return backfill_user(conn, uid, today, _pasada + 1)
        res.update(skipped=True, reintentar=True,
                   reason=f"la contabilidad cambió durante {_PASADAS} pasadas seguidas")
        return res

    # ⚠️ SI YAHOO FALLÓ, SE ESCRIBE IGUAL Y SE PIDE OTRA CORRIDA.
    # Lo que falló cayó al costo, y la foto lo dice (su cobertura baja y deja de
    # ser apta). No escribir dejaría la historia de ANTES, que con la contabilidad
    # recién cambiada es justamente el error que esto vino a sacar (valor con el
    # depósito borrado adentro y aportado sin él: +US$ 5.800 falsos). Con
    # `reintentar`, quien llama anota la cuenta para volver a correrla en el
    # próximo pedido de la persona —el Dashboard manda uno cada 90 s—, y como la
    # falla no quedó en `_HIST_CACHE`, ahí se le vuelve a preguntar a Yahoo.
    if _fallas_yahoo():
        res["reintentar"] = True
        res["yahoo_fallo"] = sorted(set(_fallas_yahoo()))

    # ⚠️ LA FOTO DE UN MES QUE YA NO TIENE CONTABILIDAD SE BORRA.
    # La reconstrucción arma todos los meses cerrados desde la PRIMERA fila de la
    # contabilidad (`_meses_a_reconstruir`). Si la persona borra el primer
    # movimiento de todos (o revierte el import que traía los primeros meses), los
    # meses anteriores a la nueva primera fila dejan de producirse; el UPSERT de
    # abajo no los toca, y su foto quedaba para siempre con el valor de ANTES del
    # borrado. (Antes de reconstruir los meses sin fila pasaba también con un mes
    # del medio: medido, borrar el único retiro de septiembre dejaba esa foto con
    # los US$ 1.000 adentro y la ganancia total en 703, real 1.703.)
    # Tres condiciones, las tres: la escribió este reconstructor (una medición del
    # cron no se toca), es de un mes cerrado, y su mes NO tiene fila 'global'. La
    # tercera es a propósito: "no lo produje" solo no alcanza — si mañana alguien
    # agrega un salteo al bucle de arriba, esto se volvería un borrado silencioso
    # de fotos de meses que sí tienen contabilidad.
    _primero_mes_en_curso = _date(today.year, today.month, 1).isoformat()
    _vigentes = {info["date"] for info in por_mes.values()}
    _con_fila = {f"{r['year']}-{r['month']:02d}" for r in conn.execute(
        "SELECT year, month FROM monthly_entries WHERE user_id=? AND broker='global'",
        (uid,)).fetchall()}
    for _r in conn.execute(
            "SELECT date FROM snapshots WHERE user_id=? AND source=? AND date < ?",
            (uid, MTM_SOURCE, _primero_mes_en_curso)).fetchall():
        if _r["date"] not in _vigentes and _r["date"][:7] not in _con_fila:
            conn.execute("DELETE FROM snapshots WHERE user_id=? AND date=? AND source=?",
                         (uid, _r["date"], MTM_SOURCE))
            res["snapshots_borrados"] = res.get("snapshots_borrados", 0) + 1

    # La reconstruccion se persiste como foto propia (source='mtm_backfill'), no
    # como una fila 'import' derivada de la cadena contable.
    res["snapshots_escritos"] = _persist_mtm_snapshots(conn, uid, por_mes)
    # ⚠️ RESPETAR LA FECHA EXACTA DE UNA MEDICIÓN NO ALCANZA. El cron no corrió un
    # 30/6, la reconstrucción de junio cayó entre el 29/6 y el 1/7 medidos, y como
    # las dos valúan cosas distintas (ver "LA COSTURA" en twr.py) la curva publicaba
    # −65 % y +189 % en dos días (uid 783). La foto se escribe igual —es la
    # historia de la cuenta y la banda contable la muestra— pero no como cierre.
    # El UPSERT de arriba la re-estampa por su cobertura; esto la vuelve a marcar.
    res["reconstrucciones_superadas"] = _twr.marcar_reconstrucciones_superadas(conn, uid)
    return res


# ─── Engine para el endpoint admin (resumen estructurado) ────────────────────
def backfill_summary(real_conn, users, today, apply: bool) -> dict:
    """Corre el backfill MTM sobre `users` y devuelve un resumen estructurado para el
    panel de Admin. apply=False → sobre una COPIA del DB (la real NO se toca);
    apply=True → commitea por user. Espeja recompute_backfill.run_backfill/dry_run."""
    def _loop(conn):
        out = {"users_changed": 0, "skipped": 0, "changes": [], "errors": [],
               "fotos_borradas": 0}
        for uid in users:
            try:
                s = backfill_user(conn, uid, today)
            except Exception as ex:
                conn.rollback()
                out["errors"].append({"uid": uid, "error": str(ex)})
                continue
            # Fotos de meses (o cuentas) que la contabilidad ya no tiene: el ensayo
            # tiene que decir cuántas borraría el apply.
            out["fotos_borradas"] += s.get("snapshots_borrados", 0)
            if s["skipped"]:
                out["skipped"] += 1
                if apply and s.get("snapshots_borrados"):
                    conn.commit()
                continue
            changed = [m for m in s["months"] if abs(m["after"] - m["before"]) > 0.01]
            if changed:
                out["users_changed"] += 1
                first, last = changed[0], changed[-1]
                out["changes"].append({
                    "uid": uid, "months_changed": len(changed),
                    "first_ym": first["ym"], "first_before": round(first["before"], 2), "first_after": round(first["after"], 2),
                    "last_ym": last["ym"], "last_before": round(last["before"], 2), "last_after": round(last["after"], 2),
                    "cost_fallbacks": s["cost_fallbacks"],
                })
            if apply:
                conn.commit()
        return out

    if apply:
        return _loop(real_conn)
    with _clone_db(real_conn) as clone:
        return _loop(clone)


# ─── Runner CLI (dry-run sobre copia / --apply commitea por user) ──────────────
def _run_on(conn, users, today, apply):
    summaries = []
    for uid in users:
        try:
            s = backfill_user(conn, uid, today)
            summaries.append(s)
            if apply and not s["skipped"]:
                conn.commit()
        except Exception as ex:
            conn.rollback()
            summaries.append({"uid": uid, "skipped": True, "reason": f"ERROR {ex}",
                              "months": [], "cost_fallbacks": 0, "cash_warning": False})
    return summaries


def _print(summaries, apply):
    changed = 0
    for s in summaries:
        if s["skipped"]:
            print(f"  uid={s['uid']:<5} SKIP — {s['reason']}")
            continue
        months = [m for m in s["months"] if abs(m["after"] - m["before"]) > 0.01]
        if not months:
            print(f"  uid={s['uid']:<5} sin cambios ({s['cost_fallbacks']} holding-meses al costo)")
            continue
        changed += 1
        first, last = s["months"][0], s["months"][-1]
        print(f"  uid={s['uid']:<5} {len(months)} meses con MTM · "
              f"global {first['ym']}: {first['before']:,.0f}→{first['after']:,.0f} … "
              f"{last['ym']}: {last['before']:,.0f}→{last['after']:,.0f} "
              f"({s['cost_fallbacks']} holding-meses al costo)")
    print(f"\n== {'Aplicado' if apply else 'Simulado (copia)'}: {changed} usuarios con MTM histórico ==")
    if not apply and changed:
        print("   Revisá y re-corré con --apply. Backup antes: python scripts/backup_db.py")


def run(apply: bool, only_uid=None) -> int:
    from fechas import hoy_art_date
    today = hoy_art_date()      # el día argentino, como `_reconstruir_mtm`
    real = main.get_db()
    try:
        if only_uid is not None:
            users = [only_uid]
        else:
            users = [r["id"] for r in real.execute("SELECT id FROM users ORDER BY id")]
        mode = "APLICANDO (commit por user)" if apply else "DRY-RUN (sobre copia — no toca nada)"
        print(f"== Backfill MTM histórico · {mode} · {len(users)} usuarios ==\n")
        if apply:
            summaries = _run_on(real, users, today, apply=True)
        else:
            with _clone_db(real) as clone:
                summaries = _run_on(clone, users, today, apply=False)
        _print(summaries, apply)
    finally:
        real.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill: valuación histórica a mercado (MTM) sin re-import.")
    ap.add_argument("--apply", action="store_true", help="aplica y commitea (default: dry-run sobre copia)")
    ap.add_argument("--user", type=int, default=None, help="solo este user_id")
    args = ap.parse_args()
    sys.exit(run(args.apply, args.user))
