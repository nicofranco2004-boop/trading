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
lee el capital_final que esta misma corrida pudo dejar en MTM). El cash ya está en
ese primer término (vía los flujos) → no se reconstruye.

Valuación = port fiel de snapshots_job.compute_broker_value_usd (live):
  - holding USD (broker USD/USDT)            → close USD histórico × qty
  - holding .BA (broker ARS / '· USD' / CEDEAR) → close .BA (ARS) ÷ MEP
  - cripto                                    → close <SYM>-USD histórico × qty
FX histórico: BLUE de fx_rates_daily (último ≤ fin de mes, sin fuga al futuro). MEP:
blue-proxy (Fase 1, sin schema nuevo; para cuentas en USD el FX ni se usa). Regla
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


def _mes_de_cache() -> str:
    """El mes (AAAA-MM) con el que se fecha cada serie guardada en `_HIST_CACHE`
    (ver `_HIST_CACHE_MES`). Clave de caché, no un día del usuario: el mes del
    servidor alcanza para saber si la serie ya trae el cierre del mes pasado."""
    return _date.today().strftime("%Y-%m")


def _fallas_yahoo() -> list:
    if not hasattr(_CORRIDA, "fallas"):
        _CORRIDA.fallas = []
    return _CORRIDA.fallas

def _es_renta_fija(base: str) -> bool:
    """¿El ticker (sin '.BA') es un bono, ON o letra del universo de data912?"""
    return (base in getattr(main, "AR_BONDS_DATA912", set())
            or main._is_data912_bond(base))


# Dónde guarda data912 las velas de cada clase de renta fija. 'bonds' está
# verificado (lo usa `main._rueda_byma` con AL30); 'corp' es el nombre del feed
# vivo de las ONs (`arg_corp`) y se prueba en segundo lugar — si no existe
# contesta 404 y el papel queda al costo, como antes.
_TIPOS_DATA912_RENTA_FIJA = ("bonds", "corp")


def _unidad_renta_fija(price_key: str):
    """El factor que lleva la cotización CRUDA de data912 a precio por 1 nominal,
    decidido por la MISMA regla que el precio vivo (`main._resolve_ar_bond_price`:
    los soberanos cotizan por 100, los CER por 1, las letras declaran la suya).
    Se aplica a toda la serie: la convención de un ticker no cambia con la fecha.
    None si no se puede decidir (sin precio vivo) → la serie no se usa."""
    es_ars = price_key.endswith(".BA")
    base = price_key[:-3] if es_ars else price_key
    crudo = (main._fetch_data912_bonds() or {}).get(base if es_ars else base + "D")
    por_uno = main._resolve_ar_bond_price(price_key)
    try:
        f = float(por_uno) / float(crudo)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    for unidad in (1.0, 0.01):
        if abs(f / unidad - 1.0) < 1e-6:
            return unidad
    return None


def _cierres_renta_fija(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM: cierre por 1 nominal}: la ÚLTIMA vela de cada mes de
    `_velas_renta_fija` (como el cierre mensual de Yahoo). Un mes sin velas no
    entra: ese mes el papel queda al costo."""
    ultimo: dict = {}
    for d, c in sorted(_velas_renta_fija(price_key, start_iso).items()):
        ultimo[d[:7]] = c
    return ultimo


def _velas_renta_fija(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM-DD: cierre por 1 nominal} de un bono/ON/letra, de las velas
    diarias de data912 — en pesos para el '.BA', en dólar MEP (especie 'D') si no.

    ⚠️ "DATA912 ES LIVE-ONLY" ERA FALSO. data912 publica las velas diarias de cada
    papel (`/historical/<tipo>/<ticker>`) y el repo ya las lee para fechar la
    rueda de BYMA (`main._rueda_byma`, con AL30) y para los cambios de ratio
    (`cambios_ratio._historia_byma`). Con los bonos siempre al costo, ningún mes
    con un bono llegaba al 90 % de cobertura y el Certero no podía usar la
    historia (auditoría 2026-10-27, H3).

    Levanta si la red falla (quien llama no lo guarda como "no hay datos")."""
    ck = ("rf", price_key, start_iso)
    _mes = _mes_de_cache()
    if ck in _HIST_CACHE and _HIST_CACHE_MES.get(ck, _mes) == _mes:
        return _HIST_CACHE[ck]
    import requests
    es_ars = price_key.endswith(".BA")
    base = price_key[:-3] if es_ars else price_key
    ticker = base if es_ars else base + "D"
    unidad = _unidad_renta_fija(price_key)
    out: dict = {}
    if unidad is not None:
        for tipo in _TIPOS_DATA912_RENTA_FIJA:
            r = requests.get(f"https://data912.com/historical/{tipo}/{ticker}", timeout=8)
            if r.status_code != 200:
                continue
            filas = r.json()
            for f in (filas if isinstance(filas, list) else []):
                try:
                    d, c = str(f.get("date"))[:10], float(f.get("c") or 0)
                except (TypeError, ValueError, AttributeError):
                    continue
                if c > 0 and len(d) == 10 and d >= start_iso:
                    out[d] = c * unidad
            if out:
                break
    _HIST_CACHE[ck] = out
    _HIST_CACHE_MES[ck] = _mes
    return out


def _fetch_monthly_close(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM: close} para un price_key ('AAPL', 'GGAL.BA', 'BTC'), desde start a
    hoy. {} (→ costo) sólo para lo que NO tiene historia: los FCI.

    Los CEDEARs y las acciones AR (.BA) SÍ tienen serie: medido, 24 de 24 meses
    para AAPL.BA, KO.BA, MELI.BA, GGAL.BA e YPFD.BA. El que cotiza en dólares se
    valúa por su subyacente — ver `_precio_por_subyacente`. La renta fija sale de
    las velas de data912 (`_cierres_renta_fija`), no de Yahoo: el '.BA' de Yahoo
    cotiza por 100 sin avisarlo (ver `snapshots_job.fetch_prices_for_symbols`)."""
    ck = (price_key, start_iso)
    _mes = _mes_de_cache()
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
    # Se saltea lo que NO tiene serie histórica: los FCI. (Los bonos/ONs también se
    # salteaban, por "data912 es live-only"; ya no: ver `_cierres_renta_fija`.)
    # El CEDEAR en dólares estaba acá por otra razón —
    # el código intentaba el camino largo (precio local ÷ CCL histórico)— y no hace
    # falta: con el ratio, 100 CEDEARs de ratio 4 son 25 acciones equivalentes, y
    # la acción SÍ tiene precio en dólares. Lo resuelve `_precio_por_subyacente`.
    # (Y `CEDEAR_USD_RATIOS` tiene exactamente un ticker: BAC.)
    renta_fija = not price_key.startswith("FCI:") and _es_renta_fija(base)
    if renta_fija:
        try:
            out = _cierres_renta_fija(price_key, start_iso)
        except Exception:
            # Igual que Yahoo: una falla de red no se guarda como "no hay datos".
            _fallas_yahoo().append(price_key)
            return {}
    elif not price_key.startswith("FCI:"):
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


# Un cierre de hace más días que esto no es "el precio de ese día" (el mismo tope
# que `price_history.MAX_DIAS_ATRAS`): el papel queda al costo.
MAX_DIAS_ATRAS = 7


def _fetch_daily_close(price_key: str, start_iso: str) -> dict:
    """{YYYY-MM-DD: close}, el diario de `_fetch_monthly_close`: misma fuente por
    clase de activo (velas de data912 para la renta fija, Yahoo para el resto,
    nada para los FCI) y misma regla ante una falla (no se guarda). Sólo lo usan
    las fotos del día anterior a un aporte grande (`backfill_user`)."""
    ck = ("1d", price_key, start_iso)
    _mes = _mes_de_cache()
    if ck in _HIST_CACHE and _HIST_CACHE_MES.get(ck, _mes) == _mes:
        return _HIST_CACHE[ck]
    if price_key in _fallas_yahoo():
        return {}
    base = price_key[:-3] if price_key.endswith(".BA") else price_key
    out: dict = {}
    if price_key.startswith("FCI:"):
        pass
    elif _es_renta_fija(base):
        try:
            return _velas_renta_fija(price_key, start_iso)
        except Exception:
            _fallas_yahoo().append(price_key)
            return {}
    else:
        yf_sym = main.CRYPTO_YF.get(base, price_key) if base in main.CRYPTO_SYMBOLS else price_key
        try:
            import yfinance as yf
            data = yf.Ticker(yf_sym).history(start=start_iso, interval="1d",
                                             auto_adjust=False, timeout=8)
            if not data.empty:
                for idx, row in data.iterrows():
                    c = row.get("Close")
                    if c is not None and not (isinstance(c, float) and math.isnan(c)):
                        out[idx.strftime("%Y-%m-%d")] = float(c)
        except Exception:
            _fallas_yahoo().append(price_key)
            return {}
    _HIST_CACHE[ck] = out
    _HIST_CACHE_MES[ck] = _mes
    return out


def _cierre_a_fecha(diario: dict, fecha: str):
    """El último cierre en o antes de `fecha`, si no tiene más de MAX_DIAS_ATRAS
    días. None si no hay."""
    from datetime import timedelta
    d = _date.fromisoformat(str(fecha)[:10])
    for k in range(MAX_DIAS_ATRAS + 1):
        c = diario.get((d - timedelta(days=k)).isoformat())
        if c is not None:
            return c
    return None


def _precio_por_subyacente(asset: str, ym: str, start_iso: str, dia: str = None):
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
        px = (_cierre_a_fecha(_fetch_daily_close(base, start_iso), dia) if dia
              else _fetch_monthly_close(base, start_iso).get(ym))
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


# ─── Lo que el reconstructor NO ve ───────────────────────────────────────────
def _no_es_un_lote(op_type) -> bool:
    """¿La fila de `operations` NO describe un lote que se tuvo?

    `operations` guarda los cierres de lote ('Venta' y los trades manuales) y,
    en la misma tabla, plata que entró o salió sin que hubiera un lote detrás:
      · los cobros de renta —'Dividendo', 'Interés', 'Renta' importados, 'Cupón'
        y 'Amortización' de la bandeja de bonos— (`cobros_bonos.es_cobro_de_renta`);
      · el interés de un plazo fijo ('Interés PF');
      · las conversiones de moneda (`realized_pnl.es_conversion`);
      · el resultado de un futuro ('Futuros') y la 'Compra' que `realized_pnl`
        ya excluye de los trades.
    Ninguna trae `entry_date` ni `entry_price` (un cobro guarda en `quantity` el
    MONTO cobrado), así que la regla de "sin fecha de entrada, se cuenta" las
    tomaba por una posición abierta de valor desconocido.

    ⚠️ ES UNA LISTA DE LO QUE NO ES UN LOTE, NO DE LO QUE SÍ. `op_type` es texto
    libre en el alta manual de Operaciones ('Venta', 'Long', 'Trade'…) y esas
    filas sí son lotes: con una lista de lo que sí, un trade manual con otro
    nombre volvería a desaparecer de la cobertura sin bajarla."""
    from cobros_bonos import es_cobro_de_renta, _norm
    from realized_pnl import es_conversion
    return (es_cobro_de_renta(op_type) or es_conversion(op_type or "")
            or _norm(op_type) in ("INTERES PF", "FUTUROS", "COMPRA"))


def _tenencia_no_vista(conn, uid: int, date_iso: str, vistos: dict):
    """(costo_usd, afirmable) de la tenencia NO-CASH a `date_iso` que
    `_lotes_por_fecha` no puede ver.

    `_lotes_por_fecha` sólo mira los lotes con fecha de compra. Un lote sin fecha
    —y antes, todo lo cargado A MANO, cuando la tenencia salía del archivo
    importado (`_holdings_asof`, reemplazada el 2026-10-27)— queda invisible.
    El problema no es que falte: es que el silencio se leía como
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
            """SELECT broker, asset, op_type, quantity, entry_price, fx_to_usd,
                      currency, entry_date, date
                 FROM operations WHERE user_id=?""",
            (uid,),
        ).fetchall():
            # ⚠️ UN COBRO NO ES UNA TENENCIA (auditoría 2026-10-27, H1). Contado
            # como lote abierto sin costo, cada dividendo en dólares de un CEDEAR
            # que vive en la cuenta en pesos —y en IEB, todo dividendo, que viene
            # sin activo— dejaba `afirmable=False` en TODOS los meses anteriores:
            # cobertura NULL y el mes afuera del Certero. Medido: Balanz A real,
            # 40 de 51 meses perdidos; IEB, 8 de 9.
            if _no_es_un_lote(r["op_type"]):
                continue
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


# ─── La foto de tenencia que contradice el archivo ────────────────────────────
# Cuánto puede tener que corregir una foto de tenencia —como fracción de lo que
# valía la cartera— antes de que la historia ANTERIOR a ella deje de ser
# afirmable.
#
# ⚠️ POR QUÉ HACE FALTA (auditoría 2026-10-27, H9). Cuando la foto no coincide con
# los movimientos, Rendi agrega lo que falta como "aporte + compra", saca lo que
# sobra "al costo" y ajusta la caja con un depósito o retiro: arregla el PRESENTE.
# El pasado reconstruido sigue describiendo el archivo, que por definición estaba
# incompleto. Mientras el Certero medía sólo desde el cron eso no se veía; con la
# historia reconstruida adentro (H1 + H3), cada escenario incompleto pasaba al
# número certero: falta una venta → sin número (la costura no cierra); faltan los
# cupones → −9,6 pp; títulos traídos de otro broker → +3,1 pp. Ninguno es un
# error de cálculo: es plata que el archivo no trae y que la foto prueba que
# existía. Lo que el Certero no puede afirmar no lo publica; el Estimado sí lo usa,
# que para eso es una estimación.
#
# 0,5 % y no cero: la foto también corrige redondeos y comisiones que el archivo
# trae distinto (medido en el arnés: Balanz US$ 0,2 y IEB US$ 34 sobre una cartera de
# ~US$ 25.000, 0,13 %). Una diferencia de ese tamaño mueve el índice acumulado en
# esa misma proporción: los cupones faltantes (3,4 %) se llevaban 9,6 pp de 141 %.
CONTRADICCION_MAX = 0.005

# Desde qué tamaño —fracción de lo que valía la cartera— un aporte o retiro lleva
# su propia foto el día anterior (ver "UNA FOTO EL DÍA ANTERIOR" en
# `backfill_user`). Con 5 %, el error de suponer que el mercado se movió parejo en
# el mes queda por debajo de una décima de punto en el mes del aporte.
FLUJO_MATERIAL = 0.05


def _correcciones_de_fotos(conn, uid: int, tenencia_en) -> list:
    """[(fecha_foto, usd)] — por cada foto de tenencia confirmada, cuánto tuvo que
    corregir en dólares: lo que abrió (compras de apertura), lo que cerró a costo
    (ventas `transfer_out`) y el ajuste de caja. El depósito que financia las
    aperturas no se cuenta aparte: es la misma plata que las compras."""
    from importing.schema import TX_VIVAS
    from importing.tenencia import TENENCIA_SEED_DEPOSIT_NOTE
    filas = conn.execute(
        f"""SELECT n.date, n.broker, n.operation_type, n.asset_symbol, n.quantity,
                   n.gross_amount, n.currency, n.notes, n.transfer_out
              FROM {TX_VIVAS}
             WHERE b.user_id = ? AND b.parser_format LIKE '%tenencia'
             ORDER BY n.date""", (uid,)).fetchall()
    try:
        live_blue = main._user_tc_blue(conn, uid)
    except Exception:
        live_blue = 1415.0
    por_fecha: dict = {}
    for r in filas:
        f = str(r["date"])[:10]
        if (r["notes"] or "").startswith(TENENCIA_SEED_DEPOSIT_NOTE):
            continue
        monto = abs(float(r["gross_amount"] or 0))
        if r["operation_type"] == "SELL" and r["transfer_out"]:
            # Cierre a costo: monto 0 en la fila. Se valúa al costo promedio que
            # tenía el lote el día anterior, el mismo que usa la reconstrucción.
            from datetime import timedelta
            antes = (_date.fromisoformat(f) - timedelta(days=1)).isoformat()
            lote = next((h for h in tenencia_en(antes)
                         if h["broker"] == r["broker"] and h["asset"] == r["asset_symbol"]), None)
            if lote and float(lote["quantity"] or 0) > 0:
                monto = (float(lote["invested"] or 0) / float(lote["quantity"])
                         * abs(float(r["quantity"] or 0)))
        moneda = (r["currency"] or "").strip().upper()
        usd = monto if moneda in ("USD", "USDT", "USDC") else monto / _hist_blue(conn, f, live_blue)
        por_fecha[f] = por_fecha.get(f, 0.0) + usd
    return sorted(por_fecha.items())


def _foto_que_contradice(conn, uid: int, valor_en, tenencia_en) -> str:
    """La fecha de la ÚLTIMA foto de tenencia cuya corrección supera
    `CONTRADICCION_MAX` de lo que valía la cartera, o None. Todo mes reconstruido
    anterior a esa fecha describe un archivo que la foto desmintió.
    `valor_en(fecha)`: el valor reconstruido (USD) más cercano antes de la foto."""
    ultima = None
    for fecha, usd in _correcciones_de_fotos(conn, uid, tenencia_en):
        base = valor_en(fecha)
        if base is None:
            continue                      # no hay historia anterior que desmentir
        if usd > CONTRADICCION_MAX * max(base, 0.0):
            ultima = fecha
    return ultima


# ─── LA HISTORIA SE VALÚA COMO EL CRON (auditoría 2026-10-27, H14) ───────────
#
# Hasta acá cada foto reconstruida valía "contabilidad + no realizado": los
# aportes en dólares AL TIPO DE CAMBIO DE CADA APORTE más lo que subió cada
# papel. El cron, en cambio, vale tenencia × precio + caja AL DÓLAR DEL DÍA. Las
# dos coinciden sólo si no hay pesos: la caja en pesos y el costo de lo comprado
# en pesos se DEVALÚAN, y la contabilidad no lo ve nunca (no hay nada realizado).
# Medido en el arnés (historia inventada 2024-01 → 2026-08, Balanz): el acumulado
# cerraba (+140,99 % contra +141,34 % real) sólo porque los errores se
# compensaban — 2024 +23,5 % (real +18,4 %), 2025 +49,9 % (real +40,2 %), meses
# errados hasta 5 pp, y la unión con el cron devolvía todo de golpe: −9,7 % en
# cuatro días que no existieron. Un Certero así acierta el total y miente en cada
# año que publica.
#
# Ahora la foto vale lo mismo que mediría el cron ese día:
#   · TENENCIA — los LOTES que Rendi ya guarda (`positions` abiertos con su fecha
#     de compra + `operations` cerradas con su fecha de compra y de venta). Son
#     el resultado del mismo armado que la cartera de hoy (FIFO, el bono puente
#     del dólar MEP ya cancelado, ventas borradas, ajustes de la foto): no es una
#     cuarta forma de calcular "qué tenía" (H11). `_holdings_asof`, que sumaba
#     compras − ventas por sub-cuenta, dejaba un AL30 fantasma por cada compra de
#     dólar MEP con bono puente (la compra en "Balanz", la venta en "Balanz · USD").
#   · CAJA — los movimientos del archivo, por MONEDA, con la misma regla que el
#     importador aplica a cada uno. Y se VERIFICA: la caja reproducida a hoy tiene
#     que dar la caja que la cuenta tiene hoy. Si no da (plata cargada a mano,
#     dividendos confirmados en la bandeja, un archivo incompleto), no se sabe
#     cuándo apareció la diferencia: la historia de esa cuenta se sigue
#     escribiendo con la regla vieja y NO es afirmable (no entra al Certero).
#   · TIPO DE CAMBIO — el MEP medio de esa fecha, el mismo del cron y de los
#     aportes (`fx.SQL_MEDIO_MEP`). Antes el MEP era "el blue, de proxy".
#
# La caja que se tolera sin verificar es la misma fracción que la foto de
# tenencia (`CONTRADICCION_MAX`): por debajo, la diferencia mueve el índice en
# esa proporción como mucho.

_CAJA_ENTRA = ("DEPOSIT", "DIVIDEND", "INTEREST", "SELL")
_CAJA_SALE = ("WITHDRAW", "FEE", "IMPUESTO", "BUY")


def _moneda_de_caja(moneda) -> str:
    """'ARS' o 'USD' (dólar, USDT, USDC). Otra moneda: su código (no se valúa)."""
    m = (moneda or "").strip().upper()
    if m in ("USD", "USDT", "USDC"):
        return "USD"
    return m


def _caja_por_fecha(conn, uid: int):
    """(caja_en(fecha) -> {'ARS': saldo, 'USD': saldo}, caja_de_hoy) — la caja que
    dejan los movimientos importados, por moneda, con el efecto que les da el
    importador (`importing.persister`): la compra resta su importe más la
    comisión, la venta suma lo cobrado menos la comisión, el depósito, el
    dividendo y el interés suman el importe, el retiro, la comisión suelta y el
    impuesto lo restan, la conversión mueve las dos monedas. Por moneda y no por
    sub-cuenta: el bono puente del dólar MEP compra en una y vende en la otra."""
    import bisect
    from importing.schema import TX_VIVAS
    bcur = {r["name"]: r["currency"] for r in conn.execute(
        "SELECT name, currency FROM brokers WHERE user_id=?", (uid,)).fetchall()}
    fechas, saldos = [], []
    acum = {}
    for r in conn.execute(
            f"""SELECT n.date, n.broker, n.operation_type, n.quantity, n.gross_amount,
                       n.fees, COALESCE(n.settlement_currency, n.currency) AS ccy
                  FROM {TX_VIVAS} WHERE b.user_id = ?
                 ORDER BY n.date, n.id""", (uid,)).fetchall():
        op = r["operation_type"]
        bruto = float(r["gross_amount"] or 0)
        com = float(r["fees"] or 0)
        mon = _moneda_de_caja(r["ccy"] or bcur.get(r["broker"]))
        if op == "FX_ARS_TO_USD":
            mov = {"ARS": -bruto, "USD": float(r["quantity"] or 0)}
        elif op == "FX_USD_TO_ARS":
            mov = {"USD": -float(r["quantity"] or 0), "ARS": bruto}
        elif op == "FUTURES_PNL":
            mov = {mon: bruto}
        elif bruto <= 0:
            continue                       # sin plata (cierre a costo de la foto, traspaso)
        elif op == "BUY":
            mov = {mon: -(bruto + com)}
        elif op == "SELL":
            mov = {mon: bruto - com}
        elif op in _CAJA_ENTRA:
            mov = {mon: bruto}
        elif op in _CAJA_SALE:
            mov = {mon: -bruto}
        else:
            continue
        for k, v in mov.items():
            acum[k] = acum.get(k, 0.0) + v
        f = str(r["date"])[:10]
        if fechas and fechas[-1] == f:
            saldos[-1] = dict(acum)
        else:
            fechas.append(f)
            saldos.append(dict(acum))

    def caja_en(fecha):
        i = bisect.bisect_right(fechas, str(fecha)[:10])
        return dict(saldos[i - 1]) if i else {}

    hoy = {}
    for r in conn.execute(
            "SELECT p.broker, p.invested FROM positions p WHERE p.user_id=? "
            "AND COALESCE(p.is_cash,0)=1", (uid,)).fetchall():
        k = _moneda_de_caja(bcur.get(r["broker"]))
        hoy[k] = hoy.get(k, 0.0) + float(r["invested"] or 0)
    return caja_en, hoy


def _lotes_por_fecha(conn, uid: int):
    """tenencia_en(fecha) -> [{broker, asset, asset_type, currency, quantity,
    invested}] — lo que la cuenta TENÍA esa fecha, armado con los lotes que Rendi
    ya guarda: los abiertos (`positions`, comprados en o antes de la fecha) y los
    cerrados (`operations`, comprados en o antes y vendidos DESPUÉS de la fecha).
    `invested` es el costo de esas unidades en la moneda del lote.

    Un lote sin fecha de compra no entra: no se sabe desde cuándo estaba. Lo
    cuenta `_tenencia_no_vista`, al costo, como siempre."""
    from importing.schema import TX_VIVAS
    meta = {}                                # (broker, asset) -> (moneda, tipo)
    for r in conn.execute(
            f"""SELECT n.broker, n.asset_symbol AS asset,
                       MAX(CASE WHEN COALESCE(n.currency,'') <> '' THEN UPPER(n.currency) END) AS cur,
                       MAX(n.asset_type) AS tipo
                  FROM {TX_VIVAS} WHERE b.user_id=? AND n.operation_type='BUY'
                   AND n.asset_symbol IS NOT NULL
                 GROUP BY n.broker, n.asset_symbol""", (uid,)).fetchall():
        meta[(r["broker"], r["asset"])] = (r["cur"], r["tipo"])
    lotes = []                               # (desde, hasta|None, fila)
    for r in conn.execute(
            """SELECT broker, asset, asset_type, currency, quantity, invested, entry_date
                 FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0
                  AND entry_date IS NOT NULL""", (uid,)).fetchall():
        q = float(r["quantity"] or 0)
        if q <= 0:
            continue
        meta.setdefault((r["broker"], r["asset"]), (r["currency"], r["asset_type"]))
        lotes.append((str(r["entry_date"])[:10], None, {
            "broker": r["broker"], "asset": r["asset"], "asset_type": r["asset_type"],
            "currency": (r["currency"] or None), "quantity": q,
            "invested": float(r["invested"] or 0)}))
    for r in conn.execute(
            """SELECT broker, asset, op_type, quantity, entry_price, exit_price,
                      entry_date, date
                 FROM operations WHERE user_id=? AND entry_date IS NOT NULL
                  AND date IS NOT NULL""", (uid,)).fetchall():
        if _no_es_un_lote(r["op_type"]):
            continue
        q = float(r["quantity"] or 0)
        if q <= 0:
            continue
        cur, tipo = meta.get((r["broker"], r["asset"]), (None, None))
        desde, hasta = str(r["entry_date"])[:10], str(r["date"])[:10]
        # ⚠️ EL LOTE SEMILLA YA ESTABA ANTES DEL ARCHIVO (H5-a). Cuando el archivo
        # trae una venta de algo que no muestra comprado, el importador cierra un
        # lote "semilla" al precio de la venta, fechado el día de la venta
        # (`rebuild._replay_asset._seed`, `persister._persist_sell_fifo`). Ese lote
        # existía desde ANTES de la ventana del archivo —si no, no se podía
        # vender—: si se lo contara sólo el día de la venta, la plata cobrada
        # aparecía de la nada en la caja y la historia la leía como ganancia
        # (medido: export desde 2025 con una venta de AAPL comprado en 2024 →
        # Estimado +264 % contra +69 % real). Se cuenta desde el principio de la
        # historia, valuado a su precio de cada mes.
        try:
            semilla = (desde == hasta and r["exit_price"] is not None
                       and abs(float(r["entry_price"] or 0) - float(r["exit_price"]))
                       <= 1e-6 * max(1.0, abs(float(r["exit_price"]))))
        except (TypeError, ValueError):
            semilla = False
        lotes.append(("0000-01-01" if semilla else desde, hasta, {
            "broker": r["broker"], "asset": r["asset"], "asset_type": tipo,
            "currency": cur, "quantity": q,
            "invested": q * float(r["entry_price"] or 0)}))

    def tenencia_en(fecha):
        f = str(fecha)[:10]
        out = {}
        for desde, hasta, l in lotes:
            if desde > f or (hasta is not None and hasta <= f):
                continue
            k = (l["broker"], l["asset"], (l["currency"] or "").upper())
            if k not in out:
                out[k] = dict(l, quantity=0.0, invested=0.0)
            out[k]["quantity"] += l["quantity"]
            out[k]["invested"] += l["invested"]
        return [h for h in out.values() if h["quantity"] > 1e-9]
    return tenencia_en


def _verificar_caja(conn, uid: int, today: _date, caja_en, caja_hoy: dict,
                    por_mes: dict) -> dict:
    """¿La caja que dejan los movimientos importados, llevada a hoy, da la caja
    que la cuenta tiene hoy? Por moneda, en dólares al MEP de hoy, contra
    `CONTRADICCION_MAX` del valor de la cartera (la última foto valuada como el
    cron). Devuelve {verificada, diferencia_usd, base_usd, por_moneda}."""
    try:
        live_blue = main._user_tc_blue(conn, uid)
    except Exception:
        live_blue = 1415.0
    hoy_iso = today.isoformat()
    mep = _hist_mep(conn, hoy_iso, _hist_blue(conn, hoy_iso, live_blue))
    reproducida = caja_en("9999-12-31")
    por_moneda, dif = {}, 0.0
    rara = False
    for k in set(reproducida) | set(caja_hoy):
        a, b = reproducida.get(k, 0.0), caja_hoy.get(k, 0.0)
        por_moneda[k] = {"reproducida": round(a, 2), "hoy": round(b, 2)}
        if k == "ARS":
            dif += abs(a - b) / mep
        elif k == "USD":
            dif += abs(a - b)
        elif abs(a - b) > 0.005 or abs(a) > 0.005:
            rara = True                   # otra moneda: no se sabe valuarla
    valores = [i["valor_posiciones"] for i in por_mes.values()
               if i.get("valor_posiciones") is not None]
    base = valores[-1] if valores else 0.0
    ok = (not rara) and base > 0 and dif <= CONTRADICCION_MAX * base
    return {"verificada": ok, "diferencia_usd": round(dif, 2), "base_usd": round(base, 2),
            "por_moneda": por_moneda}


def _hist_mep(conn, fecha_iso: str, fallback: float) -> float:
    """El MEP MEDIO de la fecha (último ≤ fecha), con la expresión compartida de
    `fx.py` — el mismo con el que el cron valúa y el importador sella los aportes
    en pesos. Sin MEP guardado, `fallback`."""
    try:
        import fx as _fxmod
    except ImportError:  # pragma: no cover
        from .. import fx as _fxmod
    try:
        row = conn.execute(
            f"SELECT {_fxmod.SQL_MEDIO_MEP} AS mep FROM fx_rates_daily "
            "WHERE date <= ? AND mep_venta IS NOT NULL ORDER BY date DESC LIMIT 1",
            (fecha_iso,)).fetchone()
        v = float(row["mep"]) if row and row["mep"] is not None else None
        return v if (v and v > 0) else fallback
    except Exception:
        return fallback


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

# ⚠️ YA NO HAY PISO DE COBERTURA. La cobertura se estampa y SE MUESTRA; no filtra
# nada. Un piso —fuera 0,70 o 0,995— esconde la curva entera al que no llega, que
# es exactamente lo contrario de lo que hace falta: ver el número y saber qué parte
# es estimada. Se deja la constante sólo porque hay tests que la referencian como
# valor de ejemplo.
COBERTURA_REFERENCIA = 0.70


def _twr_base_apto(coverage, contradicha=False, regla_del_cron=True):
    """(base, apto) de una foto reconstruida con ESA cobertura. Una sola fuente:
    `twr.base_y_apto_para`, la misma que usan los otros tres escritores y la
    migración. Si acá se escribiera la regla a mano, habría dos."""
    import twr as _twr
    return _twr.base_y_apto_para(_twr.RECONSTRUIDO, coverage, contradicha=contradicha,
                                 regla_del_cron=regla_del_cron)


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
        # La REGLA es la del cron si la foto se valuó como el cron (caja verificada)
        # o si no tiene nada en pesos: sin pesos, "contabilidad + no realizado" da
        # lo mismo que el cron (el dólar no se devalúa contra sí mismo), y una
        # cuenta en dólares con un aporte cargado a mano —que la caja reproducida no
        # ve— no tiene por qué perder su historia. Si no, es una reconstrucción
        # parcial. Y lo que una foto de tenencia desmintió nunca es apto.
        _regla_del_cron = (info.get("caja_verificada", True)
                           or not info.get("con_pesos", False))
        _base, _apto = _twr_base_apto(info["coverage"], info.get("contradicha", False),
                                      _regla_del_cron)
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


# ⚠️ LA VERSIÓN DE LA REGLA ENTRA A LA HUELLA. La huella decide si una cuenta
# se vuelve a reconstruir (`main._cuentas_que_cambiaron`), y sólo miraba la
# CONTABILIDAD: un cambio en CÓMO se reconstruye (qué es un lote, con qué precio
# se valúa un bono) dejaba escritas para siempre las fotos de la regla vieja,
# porque la contabilidad de nadie cambió. Con la versión adentro, el deploy que
# la sube hace que cada cuenta se rehaga en su próximo pedido que guarda (o con
# el botón de reconstrucción del admin, para todas a la vez).
# Subila cada vez que cambie lo que `backfill_user` escribe con la misma entrada.
#   2026-10-27 — los cobros no son tenencia (H1); renta fija con precio
#                histórico (H3) — auditoría del rendimiento desde el CSV.
VERSION_RECONSTRUCCION = "2026-10-27"


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
    partes = [f"regla:{VERSION_RECONSTRUCCION}"]

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
    # TODOS los movimientos importados, de todos los tipos y hasta hoy: la caja de
    # cada foto sale de reproducirlos (`_caja_por_fecha`) y se verifica contra la
    # caja de HOY, así que un movimiento del mes en curso también la cambia.
    _agregado(("n.id", "n.date", "n.broker", "n.asset_symbol", "n.asset_type",
               "n.operation_type", "n.quantity", "n.gross_amount", "n.unit_price",
               "n.fees", "n.currency", "n.settlement_currency",
               "CASE WHEN n.excluded_at IS NULL THEN 1 ELSE 0 END"),
              "import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
              "WHERE b.user_id=? AND b.status='confirmed'",
              "n.id", uid)
    # Lo que corrigió cada foto de tenencia (incluido su ajuste de caja, que no es
    # compra ni venta): decide qué meses son afirmables (`_foto_que_contradice`).
    _agregado(("n.id", "n.date", "n.operation_type", "n.gross_amount", "n.currency",
               "CASE WHEN n.excluded_at IS NULL THEN 1 ELSE 0 END"),
              "import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id "
              "WHERE b.user_id=? AND b.status='confirmed' AND b.parser_format LIKE '%tenencia'",
              "n.id", uid)
    _agregado(("id", "broker", "asset", "asset_type", "quantity", "invested", "currency",
               "entry_date"),
              "positions WHERE user_id=? AND COALESCE(is_cash,0)=0 "
              "AND (entry_date IS NULL OR entry_date < ?)", "id", uid, hoy)
    # La caja de HOY: contra ella se verifica la caja reproducida (`_verificar_caja`).
    _agregado(("id", "broker", "invested"),
              "positions WHERE user_id=? AND COALESCE(is_cash,0)=1", "id", uid)
    _agregado(("s.asset",),
              "(SELECT DISTINCT asset FROM positions WHERE user_id=? "
              "AND split_adjusted_through IS NOT NULL) s", "s.asset", uid)
    # TODAS las operaciones, sin filtro de fecha: `_tenencia_no_vista` cuenta una
    # operación sin `entry_date` en todos los meses cerrados anteriores a su cierre
    # —aunque se haya cargado hoy—. Un filtro propio acá la dejaba afuera (medido
    # por la auditoría: cobertura 1,0 guardada contra 0,40 real). La regla vive en
    # un solo lugar: lo que mira la reconstrucción entra entero.
    # `op_type` entra porque decide si la fila es un lote (`_no_es_un_lote`).
    _agregado(("id", "broker", "asset", "op_type", "quantity", "entry_price", "fx_to_usd",
               "currency", "entry_date", "date"), "operations WHERE user_id=?", "id", uid)
    _agregado(("name", "currency"), "brokers WHERE user_id=?", "name", uid)
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
    `_lotes_por_fecha` a su fecha, como en cualquier otro mes.

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
    # Lo que la cuenta tenía y la caja que dejaron los movimientos, a cualquier
    # fecha (ver "LA HISTORIA SE VALÚA COMO EL CRON").
    tenencia_en = _lotes_por_fecha(conn, uid)
    caja_en, caja_hoy = _caja_por_fecha(conn, uid)

    try:
        live_blue = main._user_tc_blue(conn, uid)
    except Exception:
        live_blue = 1415.0

    def _valuar(d, precio_de):
        """La foto de la fecha `d`: cada lote a precio real (o al costo, con las
        guardas), lo que el reconstructor no ve al costo, y la caja. `precio_de(h,
        pkey)` -> (precio, precio_por_subyacente): el cierre del mes o el del día."""
        blue = _hist_blue(conn, d, live_blue)
        # El MEP de la fecha, el del cron y el de los aportes. Sin MEP guardado
        # para esa fecha, el blue (lo que se usaba siempre, de proxy).
        mep = _hist_mep(conn, d, blue)
        hold = tenencia_en(d)
        # Unrealized por broker (valor_mercado − costo), con guardas → costo.
        # `val_mkt`/`val_costo` miden la COBERTURA del mes: cuanto del valor
        # no-cash salio de un precio real y cuanto cayo al costo. Sin ese numero
        # un mes casi enteramente al costo se publicaria como medido.
        unreal_by_broker: dict = {}
        val_mkt = val_costo = 0.0
        val_tenencia = 0.0                      # lo no-cash, a mercado o al costo
        by_asset: dict = {}
        assets_al_costo: set = set()
        valor_conocido = True                   # ¿se sabe cuánto vale cada lote?
        con_pesos = False                       # ¿algo de la foto está en pesos?
        for h in hold:
            b = h["broker"]
            btype = bcur.get(b, "USDT")
            # Con la moneda del lote, como el cron: un lote de costo en pesos que
            # vive en una cuenta dólar se valúa por su '.BA' (`_cost_in_pesos`).
            pkey = sj.position_price_key(
                {"asset": h["asset"], "broker": b, "asset_type": h["asset_type"],
                 "currency": h.get("currency")},
                ars_names, ar_usd_names)
            if pkey.endswith(".BA") or (h.get("currency") or "").upper() == "ARS":
                con_pesos = True
            # precio histórico (None si no hay / split → costo)
            price = None
            _px_sub = None
            if h["asset"] not in split_assets:
                # Primero el camino corto: si es un CEDEAR que cotiza en dólares,
                # se valúa por su subyacente y no hace falta el CCL histórico.
                price, _px_sub = precio_de(h, pkey)
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
            val_tenencia += efectivo
            by_asset[h["asset"]] = by_asset.get(h["asset"], 0.0) + efectivo
            if price is None or not trusted:
                res["cost_fallbacks"] += 1
                val_costo += efectivo
                # Por NOMBRE, no sólo el conteo: un porcentaje pelado no le dice al
                # usuario qué hacer; "tus FCI" sí.
                assets_al_costo.add(h["asset"])
                # Un lote que se tiene, sin precio Y sin costo (recibido gratis, una
                # semilla en cero) no vale cero: no se sabe cuánto vale. Contarlo en
                # cero da cobertura 1,0 sobre una cartera que no se pudo valuar —
                # el mismo veredicto optimista que `_tenencia_no_vista` prohíbe para
                # lo que no se ve.
                if inv <= 0 and float(h["quantity"] or 0) > 0:
                    valor_conocido = False
            else:
                val_mkt += efectivo

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
        if not (_afirmable and valor_conocido):
            cobertura = None          # hay tenencia que no veo y no se cuanto vale
        elif base_cob > 0:
            cobertura = val_mkt / base_cob
        else:
            # Cero base Y nada invisible: se puede AFIRMAR que no habia nada
            # no-cash que valuar. Recien ahi 1,0 es un hecho y no un supuesto.
            cobertura = 1.0
        # La misma foto valuada como el cron: tenencia + la caja de esa fecha al
        # MEP de esa fecha. Se usa sólo si la caja reproducida da la de hoy (ver
        # más abajo, "LA CAJA SE VERIFICA"). Lo que no se ve (`_no_visto`) baja la
        # cobertura pero NO entra al valor, igual que en la regla de siempre: un
        # lote sin fecha no se sabe si estaba, y una operación cerrada cargada a
        # mano sin mover el efectivo es sólo un resultado anotado, no plata ni
        # títulos de la cuenta (el cron tampoco la ve).
        _caja = caja_en(d)
        _caja_rara = any(abs(v) > 0.005 for k, v in _caja.items() if k not in ("ARS", "USD"))
        return {
            "total_unreal": sum(unreal_by_broker.values()),
            "con_pesos": con_pesos or abs(_caja.get("ARS", 0.0)) > 0.005,
            "cobertura": round(cobertura, 4) if cobertura is not None else None,
            "valor_posiciones": (None if _caja_rara else
                                 val_tenencia
                                 + _caja.get("ARS", 0.0) / mep + _caja.get("USD", 0.0)),
            "holdings": [{"asset": a, "value_usd": round(v, 2),
                          "al_costo": a in assets_al_costo}
                         for a, v in by_asset.items()],
        }

    # El mes en curso (y cualquier fila futura) no se toca: lo maneja el flujo live.
    for y, m, fila, propia in _meses_a_reconstruir(huella, today):
        d = _month_end(y, m)
        ym = f"{y}-{m:02d}"

        def _precio_del_mes(h, pkey, _ym=ym):
            sub = _precio_por_subyacente(h["asset"], _ym, start_iso)
            if sub is not None:
                return None, sub
            return _fetch_monthly_close(pkey, start_iso).get(_ym), None
        v = _valuar(d, _precio_del_mes)
        total_unreal = v["total_unreal"]

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
        new_cf = cost + total_unreal
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
        res["months"].append({"ym": ym, "before": before_global, "after": after_global,
                              "coverage": v["cobertura"], "sin_fila": not propia})
        por_mes[ym] = {"date": d, "value": after_global, "cost": cost,
                       "valor_contable": after_global,
                       "valor_posiciones": v["valor_posiciones"],
                       "con_pesos": v["con_pesos"],
                       "net_dep": net_dep, "coverage": v["cobertura"],
                       "holdings": v["holdings"]}

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

    # ⚠️ LA CAJA SE VERIFICA (ver "LA HISTORIA SE VALÚA COMO EL CRON"). La caja que
    # dejan los movimientos importados, llevada a hoy, tiene que dar la caja que la
    # cuenta tiene hoy. Si da, cada foto vale lo que mediría el cron ese día. Si no
    # da, no se sabe CUÁNDO apareció la diferencia: la foto se escribe con la regla
    # de antes (contabilidad + no realizado, la mejor estimación que hay) y no es
    # afirmable.
    res["caja"] = _verificar_caja(conn, uid, today, caja_en, caja_hoy, por_mes)
    _caja_ok = res["caja"]["verificada"]
    for _info in por_mes.values():
        _vp = _info.get("valor_posiciones")
        _info["caja_verificada"] = bool(_caja_ok and _vp is not None and _vp > 0)
        if _info["caja_verificada"]:
            _info["value"] = _vp
    for _m in res["months"]:
        _i = por_mes.get(_m["ym"], {})
        _m["after"] = _i.get("value", _m["after"])
        _m["valuacion"] = "posiciones" if _i.get("caja_verificada") else "contable"

    # ⚠️ UNA FOTO EL DÍA ANTERIOR A CADA APORTE O RETIRO GRANDE (H13). El tramo
    # mensual pondera cada aporte por los días que estuvo invertido
    # (`twr.flujo_ponderado`), pero sigue suponiendo que el mercado se movió parejo
    # dentro del mes: con un aporte del tamaño de la cartera, el error de esa
    # suposición se lleva puntos (medido: US$ 4.000 sobre US$ 6.600 el 14 de
    # febrero → el mes daba 3,12 % contra 3,71 %, y compuesto, −1,5 pp sobre el
    # acumulado de dos años y medio). Con una foto valuada el día anterior, el
    # tramo que lleva el aporte arranca con él: ningún tramo cruza un aporte grande.
    # Sólo con la caja verificada: el valor del día sale de tenencia × precio +
    # caja (la contabilidad es mensual y no sabe valuar un día del medio).
    res["fotos_por_aporte"] = 0
    if _caja_ok and _canon is not None:
        import twr as _twr_f
        from datetime import timedelta as _td
        _primero_en_curso = _date(today.year, today.month, 1).isoformat()
        _fines = sorted(i["date"] for i in por_mes.values())
        _flujos = _twr_f.flujos_fechados(conn, uid)
        _ya = set(_fines)
        for _f, _usd in _flujos:
            _dia = (_date.fromisoformat(_f) - _td(days=1)).isoformat()
            if _dia in _ya or _f >= _primero_en_curso or not _fines or _dia < _fines[0]:
                continue
            _prev = [i for i in por_mes.values() if i["date"] < _f]
            _base = _prev[-1]["value"] if _prev else 0.0
            if _base <= 0 or abs(_usd) < FLUJO_MATERIAL * _base:
                continue

            _fin_anterior = max(f for f in _fines if f < _f) if any(f < _f for f in _fines) else None

            def _coherente(diario, mensual_de):
                """¿La serie diaria describe lo mismo que la mensual que valuó los
                cierres? Su cierre en el último fin de mes tiene que dar el cierre
                mensual de ese mes (±1 %). Si no (otro ticker, otro ajuste), la foto
                del medio sería un escalón entre dos fuentes."""
                if not _fin_anterior:
                    return False
                m = mensual_de(_fin_anterior[:7])
                dd = _cierre_a_fecha(diario, _fin_anterior)
                return bool(m and dd and abs(dd / m - 1.0) <= 0.01)

            def _precio_del_dia(h, pkey, _x=_dia):
                base = h["asset"][:-3] if str(h["asset"]).endswith(".BA") else h["asset"]
                sub = _precio_por_subyacente(h["asset"], _x[:7], start_iso, dia=_x)
                if sub is not None:
                    # Se compara la serie del SUBYACENTE, que es de donde sale.
                    if not _coherente(_fetch_daily_close(base, start_iso),
                                      lambda ym: _fetch_monthly_close(base, start_iso).get(ym)):
                        return None, None
                    return None, sub
                diario = _fetch_daily_close(pkey, start_iso)
                if not _coherente(diario, lambda ym: _fetch_monthly_close(pkey, start_iso).get(ym)):
                    return None, None
                return _cierre_a_fecha(diario, _x), None
            _v = _valuar(_dia, _precio_del_dia)
            # Sólo la foto que puede ser borde: cobertura de medición (lo que no
            # tuvo precio del día cae al costo y la baja). Sin cobertura (hay
            # tenencia que no se sabe cuánto vale), el Estimado realinea los cierres
            # a la contabilidad y una foto valuada a mercado en el medio sería un
            # escalón de regla.
            import twr as _twr_c
            if (_v["valor_posiciones"] is None or _v["valor_posiciones"] <= 0
                    or _v["cobertura"] is None
                    or _v["cobertura"] < _twr_c.COBERTURA_MEDICION):
                continue
            # El aportado de ESE día: el del cierre de su mes menos lo que entró
            # después en el mismo mes (el canónico es mensual; `_aportado_por_punto`
            # lo ancla y deja que la estampa diga el día).
            _fin_mes = _month_end(int(_dia[:4]), int(_dia[5:7]))
            _despues = sum(v for f, v in _flujos if _dia < f <= _fin_mes)
            _mes = por_mes.get(_dia[:7]) or {}
            por_mes[_dia] = {"date": _dia, "value": _v["valor_posiciones"],
                             "cost": _mes.get("cost", 0.0),
                             "valor_contable": None,
                             "valor_posiciones": _v["valor_posiciones"],
                             "net_dep": _canon(_fin_mes) - _despues,
                             "coverage": _v["cobertura"], "holdings": _v["holdings"],
                             "caja_verificada": True, "por_aporte": True}
            _ya.add(_dia)
            res["fotos_por_aporte"] += 1
        # `por_mes` queda en orden de fecha (lo recorren la foto de tenencia y el
        # persistidor; una foto del medio del mes va entre sus dos cierres).
        por_mes = dict(sorted(por_mes.items(), key=lambda kv: kv[1]["date"]))

    # ⚠️ LO QUE LA FOTO DE TENENCIA DESMINTIÓ NO ES CERTERO (ver CONTRADICCION_MAX).
    # Los meses anteriores a una foto que tuvo que corregir el archivo se escriben
    # igual —son la mejor estimación que hay, y el Estimado las usa—, pero sin
    # poder ser borde del Certero.
    def _valor_antes_de(fecha):
        previos = [i["value"] for i in por_mes.values() if i["date"] < fecha]
        return previos[-1] if previos else None
    _desmentida = _foto_que_contradice(conn, uid, _valor_antes_de, tenencia_en)
    res["foto_que_contradice"] = _desmentida
    for _info in por_mes.values():
        _info["contradicha"] = bool(_desmentida and _info["date"] < _desmentida)
    for _m in res["months"]:
        _m["contradicha"] = por_mes.get(_m["ym"], {}).get("contradicha", False)

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
    # La foto del día anterior a un aporte grande (que no es de fin de mes) se
    # rehace en cada corrida: si esta corrida no la produjo —el aporte se borró, o
    # la caja dejó de verificar— ya no describe nada y se borra aunque su mes
    # tenga contabilidad.
    from datetime import timedelta as _td_b
    for _r in conn.execute(
            "SELECT date FROM snapshots WHERE user_id=? AND source=? AND date < ?",
            (uid, MTM_SOURCE, _primero_mes_en_curso)).fetchall():
        _f = str(_r["date"])[:10]
        _es_fin = (_date.fromisoformat(_f) + _td_b(days=1)).day == 1
        if _r["date"] not in _vigentes and (_r["date"][:7] not in _con_fila or not _es_fin):
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
