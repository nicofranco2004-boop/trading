"""Velas diarias guardadas: la base del análisis técnico.

QUÉ ES. Para cada activo que alguien tiene o sigue, la vela de cada rueda
(apertura, máximo, mínimo, cierre y volumen) de los últimos 5 años, en la tabla
`velas_diarias`. Con esto se calculan después la media de 200 días, el RSI, el
máximo del año, el volumen inusual y los giros para Fibonacci, sin salir a
pedirle a Yahoo cada vez que alguien abre una pantalla.

POR QUÉ 5 AÑOS. El gráfico de la ficha manda TODO lo guardado y arranca
mostrándolo entero («Todo», «Desde que lo tenés»): Nico, 29/10, «hagamos 5
años». Antes eran 3 (la ficha mostraba hasta 2 años y la media de 200 del primer
día necesitaba ~10 meses de antes). Medido el 29/10/2026: Yahoo tiene diarias de
AAPL desde 1980 y de GGAL.BA desde 2000, y con «5y» devuelve desde el mismo día
de hace 5 años (1.826 días; AAPL 1.254 velas, GGAL.BA 1.222).

POR QUÉ NO ES `asset_price_history` (price_history.py), aunque se parezcan.
Las dos guardan precios por día, pero con reglas opuestas:
  · `asset_price_history` NO PISA: un precio guardado es el hecho de esa fecha y
    sirve para valuar una cartera en el pasado.
  · Acá SÍ se pisa. Cuando una acción se divide (split 4 a 1), Yahoo reescribe
    toda la historia vieja dividida por 4. Si guardáramos lo viejo sin pisar, el
    gráfico mostraría una caída de 75% que no existió y la media de 200 diría
    "bajista" durante 10 meses. Por eso cada noche se compara lo que ya estaba
    guardado con lo que trae Yahoo: si los días que se repiten no coinciden, la
    historia cambió y se baja entera de nuevo.

QUÉ CIERRE SE GUARDA. El de Yahoo con `auto_adjust=False`: ajustado por splits
pero NO por dividendos. Es el que muestra TradingView por defecto, así los
niveles que ve el usuario en Rendi son los mismos que ve allá.

QUÉ SÍMBOLO. El de Yahoo, tal cual: 'AAPL' (Apple en dólares, en Nueva York),
'AAPL.BA' (el CEDEAR en pesos), 'GGAL.BA', 'BTC-USD'. De un CEDEAR se guardan
las dos series: la acción de afuera (en dólares, la que define la tendencia de
verdad) y el CEDEAR en pesos (para la vista "en pesos"). Qué serie se lee para
cada pantalla lo decide quien calcula los indicadores, no esta tabla.

CUÁNDO CORRE. Al final de la foto diaria (`_run_daily_snapshot_job`), que ya
dispara un cron externo todas las noches después del cierre de Nueva York y de
Buenos Aires. No hace falta otro cron. Y A PEDIDO, cuando alguien abre la ficha
de un activo que nadie sigue (desde el mapa de calor o el buscador): ver
`tickers_a_pedido` y `asegurar`, con sus frenos.
"""
import json
import logging
import math
import threading
import time
import zlib
from collections import deque
from datetime import date, datetime, timedelta, timezone

import pgsesion

log = logging.getLogger(__name__)

# Cuántos años se guardan: de acá salen lo que se baja y lo que se poda.
ANIOS_GUARDADOS = 5
# Cuánto se baja la primera vez (o cuando la historia cambió, o cada
# `DIAS_ENTRE_COMPLETAS`). Al pasar de 3 a 5 años no hizo falta una noche
# especial: la bajada completa de cada mes ya pide el período nuevo.
PERIODO_COMPLETO = f"{ANIOS_GUARDADOS}y"
# Cuánto se baja las noches siguientes: sobra para cubrir fines de semana,
# feriados largos y alguna noche que el trabajo no corrió.
PERIODO_INCREMENTAL = "1mo"
# Se borra lo más viejo que esto. Con 366 por año sobran unos días sobre lo que
# trae Yahoo (5 años de calendario = 1.826 días; esto, 1.830): la poda nunca le
# come el principio a una bajada completa recién hecha.
DIAS_GUARDADOS = ANIOS_GUARDADOS * 366
# Si un día que ya estaba guardado vuelve con un cierre distinto en más de esto,
# la historia fue reescrita (split, corrección de Yahoo) y se baja entera.
# 1,5% deja pasar el redondeo y las correcciones chicas de un cierre; un split
# mueve el precio 50% o más.
TOLERANCIA_REESCRITURA = 0.015
# Cuántos días repetidos distintos alcanzan para decir "la historia cambió". Un
# split mueve TODOS los días anteriores a él; Yahoo corrigiendo un cierre suelto
# mueve uno. No es "la mayoría": si Yahoo aplica el split dos semanas tarde, la
# mayoría de los días del último mes ya vienen después del split y son iguales.
DIAS_DISTINTOS_REESCRITURA = 3
# Cada cuánto se baja la historia entera aunque no se haya visto nada raro: la
# red de seguridad para lo que la comparación del último mes no puede ver (un
# split que Yahoo ajusta más de un mes tarde).
#
# Cada activo tiene SU día dentro de cada 30 (`dia_de_la_completa`, sale del
# nombre), como lo semanal: si no, los que se bajaron enteros la misma noche
# (la primera, o al forzar los 5 años) se volvían a bajar enteros todos juntos
# cada 30 días (auditoría final C4, 31/10: 300 de 300 la misma noche, con la
# misma `ultima_completa`). Toca en su día si pasaron al menos 15; y si pasaron
# más de 45 (su día cayó en una noche que no corrió o sin cupo), toca igual.
DIAS_ENTRE_COMPLETAS = 30
# Cuántas bajadas ENTERAS de algo que ya tiene historia entran en 20 horas
# (una noche), entre la corrida de la noche, el termómetro y las fichas: lo que
# pasa del cupo baja sólo el último mes y queda primero en la fila para la
# noche siguiente. Al forzar los 5 años (`ultima_completa` en NULL para todos)
# se reparte así: 2.500 activos en 4 noches (700 + 700 + 700 + 400), y no en
# una. 700 es lo que Yahoo bajó entero en una noche sin cortar (medido el
# 30/10/2026, audit/12_capacidad_motor_nuevo: 721 completas, 0 pausas). Lo que
# nunca anduvo (un activo nuevo, o uno que falla) no espera cupo: no tiene
# historia que mostrar.
COMPLETAS_POR_DIA = 700
HORAS_DEL_CUPO = 20
# Si una bajada entera vuelve arrancando más de esto DESPUÉS de lo que ya estaba
# guardado, vino cortada (Yahoo a veces devuelve sólo las últimas semanas) y no
# reemplaza lo guardado: borraba 81 velas para dejar 10 (auditoría final C5).
# Lo normal es que arranque a lo sumo unos días después (la poda corta en
# `DIAS_GUARDADOS`, 4 días más que los 5 años de Yahoo, más un fin de semana
# largo). Con un split (`_historia_reescrita`) sí se reemplaza aunque venga
# corta: mezclar las dos escalas sería peor que tener menos historia.
DIAS_HUECO_COMPLETA = 15
# Cuántos tickers se le piden a Yahoo por tanda, y el tope de cada tanda.
TANDA = 25
TOPE_TANDA_SEG = 120.0
# Tope de la corrida entera, pausas incluidas: lo que no entró queda para la
# noche siguiente, y va primero (ver `_orden`).
TOPE_CORRIDA_SEG = 15 * 60

# ─── Lo que Yahoo nunca va a tener, y cuando Yahoo deja de contestar ────────
# Medido el 24/10/2026 con la lista de la copia de producción (auditoría de
# capacidad) y otra vez el 30/10 sobre este motor (turnos por persona, 5 años):
# Yahoo, después de ~700-950 pedidos seguidos, deja de devolver datos SIN dar
# error. Dos corridas seguidas: la primera bajó 717 de 2.468, la segunda 75, y
# los demás se anotaban como «Yahoo no devolvió velas» aunque una hora antes
# habían andado. Y lo que de verdad no existe en Yahoo (opciones, bonos y ONs
# que no se reconocieron, fondos con el nombre entero) se pedía todas las
# noches, para siempre.
#
# Lo que falló estas noches seguidas pasa a pedirse una vez por semana (no
# todas las noches): una noche mala de Yahoo no alcanza, tres seguidas sí.
FALLAS_PARA_SEMANAL = 3
# Una tanda que vuelve ENTERA vacía con activos que la última vez andaban no es
# «no existen»: Yahoo cortó. Se espera esto y se vuelve a pedir la misma tanda,
# hasta `PAUSAS_MAX` veces por noche (y nunca pasando el tope de la corrida).
# Con al menos `CORTE_MIN_ANDABAN` que andaban: uno o dos que dejaron de cotizar
# (y caen en una tanda de los que fallan siempre) no son un corte.
#
# Con menos de esos (una tanda de lo que falló antes, o de lo nunca pedido) la
# tanda sola no alcanza para saberlo, y se le pregunta a un CANARIO: el último
# activo que trajo velas esta misma corrida (o el S&P 500, `SP500`, si anduvo
# antes). Si él también vuelve vacío, es un corte.
# Sin esto, lo que falló una vez iba al final de la fila, justo donde Yahoo ya
# había cortado, sumaba una falla cada noche y a las tres quedaba semanal siendo
# real (auditoría final C1, 31/10). Cuesta un pedido por tanda vacía, no por tanda.
#
# Y lo que no contestó a tiempo (el tope de la tanda) no es una falla: no se
# anota y queda para mañana, adelante en la fila (auditoría final C2).
PAUSA_CORTE_SEG = 120.0
PAUSAS_MAX = 3
CORTE_MIN_ANDABAN = 3
# El S&P 500 se guarda siempre, lo tenga alguien o no: es contra lo que la ficha
# compara cuánto se mueve un papel en un día normal (movimiento.py).
SP500 = "^GSPC"
# El Nasdaq COMPUESTO (el de la franja de arriba, home/market.py), también
# siempre: «Simular una cartera» de Backtesting compara contra él (Nico, 05/11).
# Un ticker que nunca anduvo baja entero (5 años) la primera noche (`periodo`).
NASDAQ = "^IXIC"
# Los índices que se guardan todas las noches, lo tenga alguien o no. El S&P 500
# primero: además es el canario de si Yahoo contesta (`vivo`, en `actualizar`).
INDICES = (SP500, NASDAQ)

# ─── Qué activos se siguen ───────────────────────────────────────────────────

def _yahoo_de(asset: str, asset_type: str, en_pesos: bool, es_cripto,
              cedears_byma: frozenset = frozenset()) -> list:
    """Los tickers de Yahoo que representan este activo. [] = no tiene serie
    técnica (efectivo, bonos, letras, fondos, monedas estables).

    `cedears_byma`: los códigos en pesos que BYMA lista como CEDEAR. Sirve para
    reconocer un CEDEAR que vino sin `asset_type` (SPY importado en IOL): sin
    esto sólo se guardaba su precio en pesos y no la acción de afuera."""
    from cripto import CRIPTO_ESTABLES
    from snapshots_job import _FIXED_INCOME_TYPES, _FUND_TYPES, simbolo_byma
    from main import CEDEAR_USD_RATIOS
    a = (asset or '').strip().upper()
    tipo = (asset_type or '').strip().upper()
    if not a or a in ('USD', 'ARS') or a in CRIPTO_ESTABLES or a.startswith('FCI:'):
        return []
    # Un fondo, también por su tipo y no sólo por el prefijo «FCI:»: con su código
    # crudo (COCOSPPA) entraba a «Mi cartera de hoy» y frenaba la simulación entera,
    # y la noche se lo pedía a Yahoo todos los días (auditoría de «Una cartera», 05/11).
    if tipo in _FIXED_INCOME_TYPES or tipo in _FUND_TYPES or _es_bono(a):
        return []
    if es_cripto(a):
        return [es_cripto(a)]
    if a.endswith('.BA'):
        a, en_pesos = a[:-3], True
    pesos = simbolo_byma(a)
    # CEDEAR por su tipo, por la lista de BYMA o por la lista fija de la app
    # (`accion_local.es_cedear`, la de la pantalla): si data912 no contesta, la
    # lista de BYMA llega vacía y «AAPL.BA» se guardaba sólo en pesos, sin la
    # acción de afuera ni su par (re-test de la auditoría A, 29/10: resto de P2).
    from accion_local import es_cedear as _en_la_lista
    es_cedear = tipo == 'CEDEAR' or (en_pesos and (pesos[:-3] in cedears_byma or _en_la_lista(a)))
    if es_cedear:
        if a in CEDEAR_USD_RATIOS:
            # Su '.BA' en Yahoo cotiza en dólares y roto (BAC ≈ 9): la serie en
            # pesos se arma de la acción de afuera, como el gráfico de la ficha.
            return [ticker_de_afuera(a)]
        # La acción de afuera (dólares) y el CEDEAR en pesos. Es la ÚNICA rama
        # que devuelve dos: `_seguimiento` reconoce el par por esta forma.
        return [ticker_de_afuera(a), pesos]
    return [pesos] if en_pesos else [ticker_de_afuera(a)]


def ticker_de_afuera(a: str) -> str:
    """El nombre con que Yahoo cotiza la acción de afuera. La usa también
    `tecnico.serie` para leerla: un solo traductor.

      · Un CEDEAR cuyo código de BYMA no es el de Nueva York va con el de allá
        (DISN → DIS, BRKB → BRK-B, NOKA → NOK): la tabla de la pantalla,
        `fuera_de_horario.CEDEAR_EN_EEUU`. Con el de BYMA Yahoo no la encuentra:
        la noche pedía «DISN», que no existe, y la ficha de Disney en dólares
        era el CEDEAR en pesos ÷ el MEP, con el DISN.BA de Yahoo días enteros
        clavado en 10.416 (auditoría del backtesting, 05/11, H8). Esos códigos
        existen sólo en BYMA: se traducen sin saber de qué broker es.
      · Las acciones con clase van con guión ('BRK.B' → 'BRK-B'). Con el punto,
        Yahoo no la encuentra y la serie en dólares de Berkshire no se guardaba
        (auditoría 22/10).

    El alias de especie (SI = SID, `CEDEAR_ESPECIE_ALIAS`) NO: «SI» en Nueva
    York es otra empresa real, y acá no se sabe si el activo es un CEDEAR."""
    from fuera_de_horario import CEDEAR_EN_EEUU
    a = (a or '').strip().upper()
    a = CEDEAR_EN_EEUU.get(a, a)
    return a.replace('.', '-') if '.' in a and not a.endswith('.BA') else a


def _cedears_de_byma() -> frozenset:
    """Los códigos que BYMA lista como CEDEAR (data912 → arg_cedears, la misma
    fuente que ya cotiza los CEDEARs en pesos). Si data912 no contesta, vacío:
    los CEDEARs etiquetados se siguen igual y a los otros les falta sólo la serie
    en dólares esa noche."""
    try:
        from main import _fetch_data912_equities
        feed = _fetch_data912_equities() or {}
    except Exception as ex:
        log.warning("velas: no se pudo leer la lista de CEDEARs de BYMA: %s", ex)
        return frozenset()
    return frozenset(s for s, v in feed.items() if (v or {}).get('mercado') == 'arg_cedears')


def _es_bono(asset: str) -> bool:
    try:
        from pricing.bond_amortization import is_amortizing_bond
        return bool(is_amortizing_bond(asset))
    except Exception:
        return False


# Cuántos tickers RAROS —los que no están en las listas de la app ni en BYMA
# (`_es_de_la_app`), se bajen bien o no— puede sumar UNA persona, con los
# clientes que creó si es asesor, a la descarga de la noche, por todas las
# puertas juntas (lo que tiene, lo que sigue, sus alertas técnicas, lo que
# operó). Lo de las listas de la app entra siempre, de quien sea: se baja una
# vez para todos y un asesor con 100 clientes de verdad no puede quedar afuera
# (re-test E4, ronda 2).
#
# Lo raro cuenta aunque ya se baje bien: si no, una cuenta sumaba 100 raros por
# noche, que al bajarse pasaban a «conocidos» y se acumulaban sin fin (7.400
# acumulados: 0 de 40 activos nuevos de los demás se bajaban; re-test E4,
# ronda 3). Y dentro del cupo va primero lo que se baja bien, después lo nunca
# intentado y al final lo que falla, rotando (`_raros_que_entran`): si no, un
# asesor con más códigos que fallan que lugares los llenaba todas las noches y
# sus papeles raros de verdad no se bajaban nunca (0 de 30 en 3 noches).
# 300 alcanza para lo raro real de una persona (o de un asesor y sus clientes)
# y frena a un script.
RAROS_POR_PERSONA = 300


def simbolos_a_seguir(conn) -> list:
    """Todos los tickers de Yahoo que hacen falta: lo que alguien tiene en
    cartera, lo que alguien sigue en su watchlist, lo que alguien vigila con
    una alerta técnica y lo que alguien operó."""
    return sorted(_seguimiento(conn)[0])


def _seguimiento(conn):
    """(tickers, pares): lo de `_seguimiento_por_persona` sin el detalle de
    quién aporta qué."""
    tickers, pares, _ = _seguimiento_por_persona(conn)
    return tickers, pares


def _seguimiento_por_persona(conn):
    """(tickers, pares, de_cada_una): los tickers de Yahoo a seguir y, de cada CEDEAR, su
    par {'XLE.BA': 'XLE'} (el CEDEAR en pesos y la acción de afuera), que es
    contra lo que la lista de cambios de ratio (`cambios_ratio`) compara la
    serie en pesos.

    El par sale de saber que ES un CEDEAR (`_yahoo_de`), no de que dos tickers
    se llamen igual: AGRO.BA es Agrometal y AGRO en Nueva York es Adecoagro.

    "En pesos" se decide con la MISMA regla que la valuación
    (`snapshots_job.position_price_key`): si la posición se valúa por su '.BA',
    su serie en pesos es la del '.BA'. Reinventar esa regla acá es lo que hizo
    que un CEDEAR comprado por dólar-MEP pidiera el ticker equivocado (bug C1).

    Lo de las listas de la app entra siempre. De lo raro, cada persona (con los
    clientes que creó, si es asesor) suma hasta `RAROS_POR_PERSONA`, elegido
    por `_raros_que_entran`. Lo que pasa de ahí queda afuera (y se anota en el
    log). Las puertas, en orden: lo que tiene, lo que sigue, sus alertas
    técnicas, lo que operó. `de_cada_una`: {uid: [sus tickers, en
    ese orden]}, para repartir la noche por turnos (`_por_turnos`)."""
    from cripto import yahoo_de_cripto
    from snapshots_job import _broker_name_sets, position_price_key, simbolo_byma

    cedears = _cedears_de_byma()
    # {uid: [lista de tickers de un activo]} en el orden de las puertas.
    por_persona = {}
    # Un cliente que creó un asesor (`users.managed_by`, una cuenta sin dueño
    # que entre) suma al tope del ASESOR, no tiene uno propio: si no, cada
    # cliente creado era otra persona con 300 lugares y otro turno en la fila
    # (re-test E4, ronda 2: un asesor con 100 clientes dejó 36 de 189 activos
    # reales sin actualizar).
    dueno = {r['id']: r['managed_by'] for r in conn.execute(
        "SELECT id, managed_by FROM users WHERE managed_by IS NOT NULL").fetchall()}

    def _anotar_de(uid, ys):
        if ys:
            por_persona.setdefault(dueno.get(uid, uid), []).append(ys)
    brokers = [dict(r) for r in conn.execute(
        "SELECT id, user_id, name, currency, parent_broker_id FROM brokers").fetchall()]
    por_usuario = {}
    for b in brokers:
        por_usuario.setdefault(b['user_id'], []).append(b)
    sets = {uid: _broker_name_sets(bs) for uid, bs in por_usuario.items()}

    for r in conn.execute(
            """SELECT user_id, broker, asset, asset_type, currency, invested, quantity
               FROM positions
               WHERE COALESCE(is_cash, 0) = 0 AND COALESCE(quantity, 0) > 0""").fetchall():
        p = dict(r)
        ars, ar_usd = sets.get(p['user_id'], (set(), set()))
        clave = position_price_key(p, ars, ar_usd)
        en_pesos = str(clave).upper().endswith('.BA')
        _anotar_de(p['user_id'], _yahoo_de(p['asset'], p.get('asset_type'), en_pesos, yahoo_de_cripto, cedears))

    # Lo que se sigue, con LA regla de la pantalla (`accion_local.seguido`):
    # «GGAL» del buscador es la acción argentina, igual que «GGAL.BA» de la
    # ficha. Por el sufijo se bajaba sólo el ADR y Tu lista y la ficha (que piden
    # la de BYMA) quedaban sin serie al día (auditoría A 29/10, A1 y P4).
    from accion_local import seguido
    for r in conn.execute("SELECT user_id, symbol, asset_type FROM watchlist").fetchall():
        sym = (r['symbol'] or '').upper()
        _anotar_de(r['user_id'], _yahoo_de(sym, r['asset_type'],
                                           sym.endswith('.BA') or seguido(sym, r['asset_type'])[1],
                                           yahoo_de_cripto, cedears))

    # Las alertas técnicas (alerts_engine.evaluar_tecnicas) miran la serie de la
    # ficha: sin esto, una alerta sobre un activo que nadie tiene no avisaba
    # nunca. El activo viene pelado ('AAPL', 'GGAL'): en pesos hace falta el
    # '.BA' — el de una acción argentina, o el de un CEDEAR que BYMA lista.
    # Sólo las de un activo REAL (`es_activo_real`, la regla del alta): una
    # alerta vieja con un símbolo inventado no le pide nada a Yahoo.
    for r in conn.execute(
            "SELECT user_id, symbol, currency, accion_local FROM alerts "
            "WHERE kind = 'tecnica' AND active = 1").fetchall():
        sym = (r['symbol'] or '').upper()
        if not es_activo_real(conn, sym, r['user_id']):
            continue
        en_pesos = bool(r['accion_local']) or (
            (r['currency'] or '').upper() == 'ARS' and simbolo_byma(sym)[:-3] in cedears)
        _anotar_de(r['user_id'], _yahoo_de(sym, None, en_pesos, yahoo_de_cripto, cedears))

    # Lo que alguien VENDIÓ y compró dentro de lo que se guarda: el diario de
    # operaciones de Movimientos dice cómo estaba la tendencia el día de la
    # compra (tecnico.tendencias_en_fechas). Sin esto, un activo que ya no tenés
    # no tenía velas y toda tu historia de cerradas decía «sin dato». La
    # operación no guarda `asset_type`: un CEDEAR en pesos se reconoce por la
    # lista de BYMA (`cedears`), igual que uno importado sin tipo. Los
    # dividendos e intereses no son una compra y no entran; un cupón es de un
    # bono, que no tiene serie técnica (`_yahoo_de` devuelve []).
    from fechas import hoy_art_date
    piso = (hoy_art_date() - timedelta(days=DIAS_GUARDADOS)).isoformat()
    # GROUP BY + MAX y no DISTINCT + ORDER BY entry_date: Postgres no deja
    # ordenar un DISTINCT por una columna que no está en el SELECT, y la
    # consulta entera (y con ella la noche) se caía (re-test E4, 29/10).
    for r in conn.execute(
            """SELECT user_id, broker, asset, currency, MAX(entry_date) AS ultima FROM operations
               WHERE entry_date IS NOT NULL AND entry_date >= ?
                 AND COALESCE(op_type, '') NOT IN ('Compra', 'Dividendo', 'Interés')
               GROUP BY user_id, broker, asset, currency
               ORDER BY user_id, ultima DESC""",
            (piso,)).fetchall():
        p = dict(r)
        ars, ar_usd = sets.get(p['user_id'], (set(), set()))
        clave = position_price_key(p, ars, ar_usd)
        en_pesos = str(clave).upper().endswith('.BA')
        _anotar_de(p['user_id'], _yahoo_de(p['asset'], None, en_pesos, yahoo_de_cripto, cedears))

    es_de_la_app = _es_de_la_app()
    estado = _estado_de_cada_ticker(conn)
    tickers, pares, topados, de_cada_una = set(), {}, {}, {}
    for uid, listas in por_persona.items():
        entran = _raros_que_entran(listas, es_de_la_app, estado)
        topados_suyos = 0
        suyos, orden = set(), []
        for k, ys in enumerate(listas):
            if k not in entran:
                topados_suyos += 1
                continue
            nuevos = [y for y in ys if y and y not in suyos]
            suyos.update(nuevos)
            orden += nuevos
            if len(ys) == 2:   # la forma de un CEDEAR: [afuera, pesos]
                pares[ys[1]] = ys[0]
        if topados_suyos:
            topados[uid] = topados_suyos
        tickers |= suyos
        de_cada_una[uid] = orden
    if topados:
        log.warning("velas: %d persona(s) pasaron el tope de %d tickers raros; quedaron "
                    "afuera %d activos (uid: %s)", len(topados), RAROS_POR_PERSONA,
                    sum(topados.values()), sorted(topados)[:20])

    tickers.update(INDICES)
    tickers.discard('')
    tickers.discard(None)
    return tickers, pares, de_cada_una


def _es_de_la_app():
    """La pregunta «¿este ticker de Yahoo está en las listas de la app o en
    BYMA?» (`_lista_de_la_app`), armada una vez para toda la noche. Lo que no,
    es «raro»: tiene cupo por persona (`RAROS_POR_PERSONA`) y va después en la
    fila (`_por_turnos`)."""
    app = _lista_de_la_app()
    return lambda t: bool(_variantes(t) & app)


def _estado_de_cada_ticker(conn) -> dict:
    return {r['symbol']: dict(r) for r in conn.execute(
        "SELECT symbol, ultima_corrida, ultima_completa, ok, fallas_seguidas FROM velas_estado").fetchall()}


def _raros_que_entran(listas: list, es_de_la_app, estado: dict) -> set:
    """Cuáles de los activos de UNA persona (`listas`: los tickers de cada
    activo, en el orden de las puertas) entran a la noche: los que no tienen
    nada raro, todos; de los que tienen, hasta `RAROS_POR_PERSONA` tickers
    raros, en este orden:
      1. los que se bajan bien (ya son de esa persona, y de verdad);
      2. los nunca intentados (un papel raro recién sumado);
      3. los que fallaron, el que hace más que no se intenta primero: cada
         noche se prueban otros, así un código mal escrito no tapa para
         siempre a los demás.
    Devuelve los índices de `listas` que entran."""
    def prioridad(y):
        e = estado.get(y)
        if e is None:
            return (1, '')
        if e.get('ok'):
            return (0, '')
        return (2, str(e.get('ultima_corrida') or ''))

    entran, con_raros, vistos = set(), [], set()
    for k, ys in enumerate(listas):
        raros = [y for y in ys if y and not es_de_la_app(y)]
        if not raros:
            entran.add(k)
        else:
            con_raros.append((max(prioridad(y) for y in raros), k, raros))
    usados = 0
    for _, k, raros in sorted(con_raros):
        nuevos = [y for y in raros if y not in vistos]
        if usados + len(nuevos) > RAROS_POR_PERSONA:
            continue
        usados += len(nuevos)
        vistos.update(nuevos)
        entran.add(k)
    return entran


def _turno(estado: dict, t: str, hoy: str) -> int:
    """Primero lo que nunca se intentó (0), después lo que necesita la historia
    entera (1), después la puesta al día (2), y AL FINAL lo que falló la última
    vez (3). Antes "lo que nunca se bajó" iba primero siempre, y un símbolo que
    nunca trae datos (inventado en una watchlist) nunca deja de ser "nunca
    bajado": con miles, se comían el tope de la noche y los activos de verdad no
    se actualizaban (auditoría de seguridad 22/10)."""
    e = estado.get(t)
    if e is None:
        return 0
    if not e.get('ok'):
        return 3
    return 1 if _toca_completa(e, hoy, t) else 2


def _orden(estado: dict, t: str, hoy: str) -> tuple:
    """El lugar en la fila: el `_turno` y, dentro del turno, lo que hace más
    DÍAS que no se pidió primero. Así lo que anoche quedó sin pedir (Yahoo cortó
    o se acabó el tiempo) hoy va adelante, y no se caen siempre los mismos: antes,
    con la fila siempre en el mismo orden, si Yahoo cortaba se perdían todas las
    noches los últimos (medido el 24/10: siempre de la S a la Z)."""
    e = estado.get(t)
    return (_turno(estado, t, hoy), str((e or {}).get('ultima_corrida') or '')[:10])


def _por_turnos(conn, de_cada_una: dict, hoy: str) -> list:
    """El orden de la noche, en tres vueltas, y en cada una por TURNOS entre
    personas (ronda 1: lo primero de cada una; ronda 2: lo segundo; …):
      1. lo de las listas de la app o BYMA (`_es_de_la_app`). Cada persona lo
         ordena por `_turno` (nunca intentado, historia entera, puesta al día,
         lo que falló);
      2. lo raro (ya dentro del cupo de cada persona) que no falló: lo nunca
         intentado, la historia entera y la puesta al día;
      3. lo raro que falló la última vez.

    Por qué: lo «nunca intentado» iba primero para todos, y una cuenta (o un
    asesor con cientos de clientes) con símbolos inventados los tiene siempre
    nunca intentados. Con 1.300 inventados, los reales salían en la última
    tanda (re-test E4); con un asesor de 100 clientes, 36 de 189 reales sin
    actualizar en una noche de 15 minutos (ronda 2). Ahora lo inventado nunca
    va delante de algo de las listas, y entre personas cada una avanza al mismo
    ritmo: los que meten mucho sólo se atrasan a sí mismos. Lo raro de UNA
    persona no tapa a lo raro nuevo de las demás (ronda 3: 7.400 raros ya
    bajados de una cuenta dejaban sin bajar los 40 nuevos de otros)."""
    estado = _estado_de_cada_ticker(conn)
    es_de_la_app = _es_de_la_app()

    def vuelta(t):
        if es_de_la_app(t):
            return 0
        return 2 if _turno(estado, t, hoy) == 3 else 1

    vueltas = ([], [], [])
    for uid in sorted(de_cada_una, key=str):
        suyos = sorted(de_cada_una[uid], key=lambda t: _orden(estado, t, hoy))   # estable: el orden de las puertas
        por_vuelta = ([], [], [])
        for t in suyos:
            por_vuelta[vuelta(t)].append(t)
        for v in range(3):
            vueltas[v].append(por_vuelta[v])
    orden, puestos = list(INDICES), set(INDICES)
    for listas in vueltas:
        for k in range(max((len(x) for x in listas), default=0)):
            for lista in listas:
                if k < len(lista) and lista[k] not in puestos:
                    puestos.add(lista[k])
                    orden.append(lista[k])
    return orden


# ─── Bajar y guardar ─────────────────────────────────────────────────────────

def _numero(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _velas_de(df, hoy: str) -> dict:
    """{fecha: (o, h, l, c, v)} de una tabla de Yahoo. Se descartan:
      · las filas sin cierre válido: yfinance devuelve ruedas de '.BA' con
        volumen pero precios en NaN, y eso no es una rueda;
      · la vela de HOY (fecha UTC): a la hora del cron, la de una cripto es de
        3 horas y todavía se mueve. La noche siguiente entra completa."""
    out = {}
    if df is None or getattr(df, 'empty', True):
        return out
    for idx, row in df.iterrows():
        f = idx.date().isoformat()
        if f >= hoy:
            continue
        c = _numero(row.get('Close'))
        if c is None or c <= 0:
            continue
        o, h, l = (_numero(row.get(k)) for k in ('Open', 'High', 'Low'))
        vol = _numero(row.get('Volume'))
        # Una vela con máximo/mínimo roto se guarda igual, pero sólo con cierre:
        # un máximo de 0 arruinaría el "máximo del año" y los giros de Fibonacci.
        if not (h and l and h >= c >= l > 0):
            h = l = None
        out[f] = (o if o and o > 0 else None, h, l, c, vol if vol and vol >= 0 else None)
    return out


def _bajar(ticker: str, periodo: str):
    from pricing import yahoo as _yahoo
    return _yahoo._historia(ticker, periodo, '1d', False, 10.0)


def _dormir(seg: float) -> None:
    # Aparte para que las pruebas no esperen de verdad los minutos de la pausa.
    time.sleep(seg)


def es_ticker(t: str) -> bool:
    """¿Tiene forma de ticker? El MISMO filtro que la ficha le aplica al símbolo
    que le piden (`main._SYMBOL_RE`, el de GET /api/tecnico): lo que la ficha no
    aceptaría nunca va a tener velas. Un fondo con el nombre entero
    («LIQUIDACIÓN-DE-SUSCRIPCIÓN-/-…») o un nombre con espacios no se le pide a
    Yahoo. Los índices de Yahoo empiezan con «^» (el S&P 500 y el Nasdaq,
    `INDICES`, que se guardan todas las noches): la ficha no los abre, pero son
    tickers."""
    from main import _SYMBOL_RE
    return bool(t) and bool(_SYMBOL_RE.match(t[1:] if t.startswith("^") else t))


def dia_de_la_semana(ticker: str) -> int:
    """El día (0 = lunes) en que toca lo semanal de este ticker. Sale del nombre,
    no de cuándo se pidió por primera vez: así lo semanal se reparte entre los 7
    días y no cae todo la misma noche."""
    return zlib.crc32(ticker.encode()) % 7


def _toca_semanal(ticker: str, ultima: str, hoy: str) -> bool:
    """Lo que se pide una vez por semana: ¿toca hoy? Toca el día del ticker
    (`dia_de_la_semana`) si no se pidió ya hoy, o si pasó más de una semana
    (una noche que no corrió no lo deja dos semanas sin pedir)."""
    if not ultima:
        return True
    d = date.fromisoformat(hoy)
    dias = (d - date.fromisoformat(str(ultima)[:10])).days
    return dias > 7 or (dias >= 1 and d.weekday() == dia_de_la_semana(ticker))


def _vino_cortada(conn, ticker: str, velas: dict) -> bool:
    """¿Esta bajada entera arranca bastante DESPUÉS de lo ya guardado
    (`DIAS_HUECO_COMPLETA`) sin que la historia haya cambiado (split)? Entonces
    Yahoo la mandó cortada, y reemplazar borraría la historia que sí teníamos."""
    if not velas:
        return False
    r = conn.execute("SELECT MIN(date) AS d FROM velas_diarias WHERE symbol=?", (ticker,)).fetchone()
    guardada = r["d"] if r else None
    if not guardada:
        return False
    limite = (date.fromisoformat(str(guardada)[:10]) + timedelta(days=DIAS_HUECO_COMPLETA)).isoformat()
    return min(velas) > limite and not _historia_reescrita(conn, ticker, velas)


def _guardar(conn, ticker: str, velas: dict, *, completa: bool) -> tuple:
    """Devuelve (velas guardadas, si fue de verdad una bajada entera).

    Una bajada COMPLETA reemplaza todo lo del ticker (si Yahoo reescribió la
    historia, no puede quedar ningún día viejo); una incremental pisa sus días.
    Una completa que vino cortada (`_vino_cortada`) se guarda como incremental:
    no borra lo que ya estaba, y no cuenta como bajada entera (quien llama no
    renueva `ultima_completa`, así se vuelve a intentar).

    Todas las velas en UNA operación (`executemany`), no una consulta por vela:
    en Postgres cada consulta es un viaje por la red, y un activo bajado entero
    (5 años, ~1.260 velas) eran ~1.260 viajes; así son 3 (borrar, guardar,
    anotar). Medido en la auditoría de capacidad (24/10/2026): la primera noche
    de 100 activos pasó de 12,4 s a 1,7 s en Postgres local."""
    if completa and _vino_cortada(conn, ticker, velas):
        log.warning("velas: la bajada entera de %s vino cortada (desde %s): no reemplaza lo guardado",
                    ticker, min(velas))
        completa = False
    if completa:
        conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (ticker,))
    if velas:
        conn.executemany(
            """INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(symbol, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume,
                 fetched_at=datetime('now')""",
            [(ticker, f, o, h, l, c, v) for f, (o, h, l, c, v) in velas.items()])
    return len(velas), completa


def _historia_reescrita(conn, ticker: str, velas: dict) -> bool:
    """¿Los días que ya teníamos vuelven con otro cierre? Entonces Yahoo
    reescribió la historia (split) y lo guardado no sirve más.

    Alcanzan `DIAS_DISTINTOS_REESCRITURA` días distintos (o todos, si se
    repiten menos): un split mueve todos los días anteriores a él, mientras que
    Yahoo corrigiendo un cierre suelto mueve uno, y eso alcanza con pisarlo."""
    if not velas:
        return False
    fechas = sorted(velas)
    rows = conn.execute(
        "SELECT date, close FROM velas_diarias WHERE symbol=? AND date>=? AND date<=?",
        (ticker, fechas[0], fechas[-1])).fetchall()
    comparados = distintos = 0
    for r in rows:
        nueva = velas.get(r['date'])
        if nueva and r['close']:
            comparados += 1
            if abs(nueva[3] / r['close'] - 1) > TOLERANCIA_REESCRITURA:
                distintos += 1
    return distintos >= DIAS_DISTINTOS_REESCRITURA or (0 < comparados == distintos)


def _anotar(conn, ticker: str, *, completa: bool, ok: bool, filas: int = 0, error: str = None):
    """`fallas_seguidas`: cuántas veces seguidas falló (0 al andar). Con
    `FALLAS_PARA_SEMANAL` la noche lo pide una vez por semana."""
    # `CASE WHEN ?=1`, no `CASE WHEN ?`: SQLite acepta un entero como condición,
    # Postgres exige un booleano. La hora sale de `_ahora_utc` (UTC, el mismo
    # formato que datetime('now')): es el reloj con que se leen después
    # (`_necesita`, la poda, el cupo de completas) y las pruebas lo pueden fijar.
    ahora = _ahora_utc().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        """INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok, filas, error,
                                     fallas_seguidas)
           VALUES (?, ?, CASE WHEN ?=1 THEN ? END, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
             ultima_corrida=excluded.ultima_corrida,
             ultima_completa=CASE WHEN ?=1 THEN excluded.ultima_corrida ELSE velas_estado.ultima_completa END,
             ok=excluded.ok, filas=excluded.filas, error=excluded.error,
             fallas_seguidas=CASE WHEN ?=1 THEN 0 ELSE COALESCE(velas_estado.fallas_seguidas, 0) + 1 END""",
        (ticker, ahora, 1 if completa else 0, ahora, 1 if ok else 0, filas, error, 0 if ok else 1,
         1 if completa else 0, 1 if ok else 0))


def dia_de_la_completa(ticker: str) -> int:
    """El día (0 a `DIAS_ENTRE_COMPLETAS` − 1, contado sobre el calendario) en
    que le toca a este ticker la bajada entera de cada mes. Sale del nombre, con
    otra semilla que `dia_de_la_semana` (si no, los de un mismo día de la semana
    caerían juntos también acá)."""
    return zlib.crc32(b"completa " + ticker.encode()) % DIAS_ENTRE_COMPLETAS


def _toca_completa(est: dict, hoy: str, ticker: str = None) -> bool:
    """¿Toca bajarlo entero? Si nunca se bajó entero, sí. Si no, en SU día
    (`dia_de_la_completa`) pasados al menos la mitad de `DIAS_ENTRE_COMPLETAS`,
    o pasado uno y medio aunque no sea su día (una noche que no corrió, o sin
    cupo, no lo deja dos meses sin la red de seguridad). Así, aunque todos
    tengan la misma `ultima_completa` (la primera noche, o al forzar los 5
    años), cada uno vuelve a bajarse entero en su día y no todos juntos."""
    ultima = (est or {}).get('ultima_completa')
    if not ultima:
        return True
    d = date.fromisoformat(hoy)
    dias = (d - date.fromisoformat(str(ultima)[:10])).days
    if dias > DIAS_ENTRE_COMPLETAS * 3 // 2:
        return True
    return (ticker is not None and dias >= DIAS_ENTRE_COMPLETAS // 2
            and d.toordinal() % DIAS_ENTRE_COMPLETAS == dia_de_la_completa(ticker))


def _cupo_de_completas(conn) -> int:
    """Cuántas bajadas enteras más entran hoy (`COMPLETAS_POR_DIA` menos las
    hechas en las últimas `HORAS_DEL_CUPO`). Se cuentan en la base y no por
    corrida: la noche, el termómetro, el botón de /admin y las fichas comparten
    el mismo cupo."""
    desde = (_ahora_utc() - timedelta(hours=HORAS_DEL_CUPO)).strftime('%Y-%m-%d %H:%M:%S')
    r = conn.execute("SELECT COUNT(*) AS n FROM velas_estado WHERE ultima_completa >= ?",
                     (desde,)).fetchone()
    return max(COMPLETAS_POR_DIA - int((r["n"] if r else 0) or 0), 0)


def actualizar(conn, tickers: list, *, bajar=None, hoy: str = None,
               tope_seg: float = None, tope_tanda: float = None,
               podar: bool = True, en_orden: bool = False, semanal: bool = False,
               soltar_la_base: bool = False) -> dict:
    """Pone al día las velas de estos tickers. Idempotente: correrlo dos veces
    seguidas no cambia nada.

    Los que nunca se bajaron (o se bajaron mal) van primero: con el tope de
    tiempo, una noche lenta deja sin actualizar a los que ya tenían su historia, no
    a los que no tienen nada. Dentro de eso, lo que hace más días que no se pidió
    (`_orden`).

    No se le pide a Yahoo lo que no tiene forma de ticker (`es_ticker`). Con
    `semanal` (la noche), lo que falló `FALLAS_PARA_SEMANAL` veces seguidas se
    pide sólo el día de la semana que le toca (`_toca_semanal`); la ficha a
    pedido no espera (tiene sus propios frenos).

    Si Yahoo corta (una tanda vuelve ENTERA vacía con activos que andaban, o
    vacía y con el canario vacío también: `yahoo_contesta`), se espera `PAUSA_CORTE_SEG`
    y se pide la misma tanda de nuevo. Lo que quedó sin pedir por el corte, y lo
    que no contestó a tiempo, NO se anota como falla: no es que no exista.

    Las bajadas enteras de lo que ya tiene historia tienen cupo
    (`_cupo_de_completas`): lo que no entra baja el último mes. Si la bajada
    entera vuelve vacía de algo que tiene velas guardadas, se pide el último mes
    en el mismo paso: la vela no se congela por una bajada larga que Yahoo no da.

    Nunca se espera a Yahoo con una escritura abierta: cada tanda baja todo,
    escribe y confirma; los que hay que rebajar enteros (split) se piden DESPUÉS
    de confirmar. En SQLite una escritura abierta traba a todos los demás que
    quieren escribir, y Yahoo puede tardar 30 s en contestar.

    `soltar_la_base`: tampoco se espera con la conexión en la mano: antes de cada
    espera se suelta (`pgsesion.soltar`; en Postgres hay 10 por copia de la app)
    y la próxima consulta pide otra. Lo pide la ficha a pedido (`asegurar`): una
    persona esperando a Yahoo no le quita el lugar a las demás. La noche y el
    termómetro NO: un trabajo de fondo que suelta y vuelve a pedir en cada tanda
    (unas 80 por noche) se cortaría entero si en una vuelta el pozo sigue lleno
    30 s (`pgshim.PozoAgotado`), y quedarse con su lugar es 1 de 10 (auditoría
    del 05/11).

    `tope_seg`, `tope_tanda`: el tope de la corrida y cuánto se espera a Yahoo
    por tanda (sin decir: `TOPE_CORRIDA_SEG` y `TOPE_TANDA_SEG`; la ficha a
    pedido espera poco). `podar`: borrar lo que quedó más viejo que
    `DIAS_GUARDADOS`; la ficha a pedido no lo hace (es un borrado de toda la
    tabla y lo hace la corrida de la noche). `en_orden`: respetar el orden de
    `tickers` (la noche lo trae repartido por personas, `_por_turnos`) en vez de
    ordenar por `_orden`."""
    from fechas import hoy_art
    from pricing import yahoo as _yahoo
    bajar = bajar or _bajar
    tope_seg = TOPE_CORRIDA_SEG if tope_seg is None else tope_seg
    tope_tanda = TOPE_TANDA_SEG if tope_tanda is None else tope_tanda

    def antes_de_esperar():
        if soltar_la_base:
            pgsesion.soltar(conn)
    # El día argentino. Corriendo a cualquier hora deja afuera la vela que
    # todavía se mueve: la de una acción en plena rueda y la de una cripto, que
    # a partir de las 21:00 de acá ya está fechada "mañana" (UTC).
    hoy = hoy or hoy_art()
    fin = time.monotonic() + tope_seg

    estado = _estado_de_cada_ticker(conn)
    pedidos_hoy = list(dict.fromkeys(t for t in (tickers or []) if t))
    no_tickers = [t for t in pedidos_hoy if not es_ticker(t)]
    en_espera = [t for t in pedidos_hoy if semanal and es_ticker(t) and t in estado
                 and (estado[t].get('fallas_seguidas') or 0) >= FALLAS_PARA_SEMANAL
                 and not _toca_semanal(t, estado[t].get('ultima_corrida'), hoy)]
    afuera = set(no_tickers) | set(en_espera)
    if en_orden:
        # El orden ya viene decidido (la noche: `_por_turnos`).
        pendientes = [t for t in pedidos_hoy if t not in afuera]
    else:
        pendientes = sorted((t for t in pedidos_hoy if t not in afuera), key=lambda t: (*_orden(estado, t, hoy), t))

    res = {"pedidos": len(pendientes), "bajados": 0, "completas": 0, "incrementales": 0,
           "reescritas": [], "sin_datos": [], "cortados_por_yahoo": 0, "pausas": 0,
           "no_son_tickers": len(no_tickers), "en_espera_semanal": len(en_espera),
           "sin_tiempo": 0, "filas": 0, "demorados": [], "canarios": 0,
           "completas_sin_cupo": 0, "completas_por_el_mes": [], "completas_cortadas": []}

    cupo = _cupo_de_completas(conn) if any(_toca_completa(estado.get(t), hoy, t) for t in pendientes) else 0
    periodo_de = {}

    def periodo(t):
        # Una vez por ticker y por corrida: la tanda que se repite tras una
        # pausa no gasta cupo dos veces.
        nonlocal cupo
        if t not in periodo_de:
            e = estado.get(t)
            if not _toca_completa(e, hoy, t):
                periodo_de[t] = PERIODO_INCREMENTAL
            elif not (e or {}).get('ok'):
                periodo_de[t] = PERIODO_COMPLETO      # nunca anduvo: no tiene historia que mostrar
            elif cupo > 0:
                cupo -= 1
                periodo_de[t] = PERIODO_COMPLETO
            else:
                res["completas_sin_cupo"] += 1
                periodo_de[t] = PERIODO_INCREMENTAL
        return periodo_de[t]

    vivo = [SP500] if (estado.get(SP500) or {}).get('ok') else []

    def yahoo_contesta(tanda, velas_de) -> bool:
        """El canario: ¿Yahoo le da velas AHORA a algo que se sabe que anda? Es
        el último que trajo velas en esta corrida (o el S&P 500, si anduvo
        antes). Sin ninguno no se puede saber: se decide como sin canario."""
        if not vivo:
            return True
        canario = vivo[-1]
        if canario in tanda:
            return bool(velas_de.get(canario))
        res["canarios"] += 1
        antes_de_esperar()
        r, _ = _yahoo.varios(lambda t: bajar(t, PERIODO_INCREMENTAL), [canario],
                             tope=max(min(tope_tanda, fin - time.monotonic()), 1.0),
                             que="velas diarias (canario)")
        return bool(_velas_de(r.get(canario), hoy))

    i = 0
    while i < len(pendientes):
        if time.monotonic() >= fin:
            res["sin_tiempo"] = len(pendientes) - i
            break
        tanda = pendientes[i:i + TANDA]
        pedidos = {t: periodo(t) for t in tanda}
        antes_de_esperar()
        bajadas, sin_respuesta = _yahoo.varios(lambda t: bajar(t, pedidos[t]), tanda,
                                               tope=tope_tanda, que="velas diarias")
        demorados = set(sin_respuesta)
        velas_de = {t: _velas_de(bajadas.get(t), hoy) for t in tanda}
        vacios = [t for t in tanda if t not in demorados and not velas_de[t]]
        con_datos = [t for t in tanda if velas_de[t]]
        if con_datos:
            vivo[:] = [con_datos[-1]]
        andaban = [t for t in tanda if (estado.get(t) or {}).get('ok')]
        if not any(velas_de.values()) and (
                len(andaban) >= CORTE_MIN_ANDABAN or (vacios and not yahoo_contesta(tanda, velas_de))):
            # Yahoo cortó. Se espera y se pide la MISMA tanda (no se avanza).
            if res["pausas"] < PAUSAS_MAX and fin - time.monotonic() > PAUSA_CORTE_SEG:
                res["pausas"] += 1
                log.warning("velas: Yahoo devolvió vacía una tanda entera (%d que andaban, %s…): "
                            "pausa %d de %d, %.0f s", len(andaban), ", ".join(tanda[:5]),
                            res["pausas"], PAUSAS_MAX, PAUSA_CORTE_SEG)
                antes_de_esperar()
                _dormir(PAUSA_CORTE_SEG)
                continue
            # Sin más pausas ni tiempo: lo que falta queda para mañana, sin
            # anotarlo como falla (y adelante en la fila, por no haberse pedido).
            res["cortados_por_yahoo"] = len(pendientes) - i
            log.warning("velas: Yahoo sigue sin contestar; %d quedan para mañana",
                        res["cortados_por_yahoo"])
            break
        i += len(tanda)

        # La bajada entera vino vacía de algo que ya tiene velas: el último mes,
        # en el mismo paso (antes fallaba 3 noches y quedaba semanal, con la vela
        # congelada). Sólo de lo que tiene velas: lo que nunca existió en Yahoo
        # no gasta un segundo pedido cada noche.
        enteras_vacias = [t for t in vacios if pedidos[t] == PERIODO_COMPLETO]
        por_el_mes = set()
        if enteras_vacias:
            marcas = ",".join("?" * len(enteras_vacias))
            con_velas = [r["symbol"] for r in conn.execute(
                f"SELECT DISTINCT symbol FROM velas_diarias WHERE symbol IN ({marcas})",
                tuple(enteras_vacias)).fetchall()]
            conn.commit()   # sin la lectura abierta mientras se espera a Yahoo (Postgres)
            if con_velas:
                antes_de_esperar()
                del_mes, sin_mes = _yahoo.varios(lambda t: bajar(t, PERIODO_INCREMENTAL), con_velas,
                                                 tope=tope_tanda, que="velas diarias (el último mes)")
                demorados |= set(sin_mes)
                for t in con_velas:
                    v = _velas_de(del_mes.get(t), hoy)
                    if v:
                        velas_de[t] = v
                        por_el_mes.add(t)
                        res["completas_por_el_mes"].append(t)

        a_rebajar = []
        for t in tanda:
            velas = velas_de[t]
            completa = pedidos[t] == PERIODO_COMPLETO and t not in por_el_mes
            if not velas:
                if t in demorados:
                    # No contestó a tiempo: no es que no exista. Queda para
                    # mañana sin anotarse (y adelante, por no haberse pedido).
                    res["demorados"].append(t)
                    continue
                _anotar(conn, t, completa=False, ok=False, error="Yahoo no devolvió velas")
                res["sin_datos"].append(t)
                continue
            if not completa and _historia_reescrita(conn, t, velas):
                a_rebajar.append(t)
                continue
            n, entera = _guardar(conn, t, velas, completa=completa)
            if completa and not entera:
                res["completas_cortadas"].append(t)
            _anotar(conn, t, completa=entera, ok=True, filas=n)
            res["filas"] += n
            res["completas" if entera else "incrementales"] += 1
        conn.commit()

        if a_rebajar:
            # Con la tanda ya confirmada: acá no hay ninguna escritura abierta.
            antes_de_esperar()
            rebajadas, sin_rebajar = _yahoo.varios(lambda t: bajar(t, PERIODO_COMPLETO), a_rebajar,
                                                   tope=tope_tanda, que="velas diarias (historia cambiada)")
            for t in a_rebajar:
                velas = _velas_de(rebajadas.get(t), hoy)
                if not velas:
                    if t in sin_rebajar:
                        # No contestó a tiempo: mañana se vuelve a detectar.
                        res["demorados"].append(t)
                        continue
                    # Lo viejo queda como estaba (mejor que borrarlo sin reemplazo)
                    # y la noche siguiente se vuelve a detectar y a intentar.
                    _anotar(conn, t, completa=False, ok=False,
                            error="La historia cambió y no se pudo bajar de nuevo")
                    res["sin_datos"].append(t)
                    continue
                n, entera = _guardar(conn, t, velas, completa=True)
                _anotar(conn, t, completa=entera, ok=True, filas=n)
                res["filas"] += n
                res["completas"] += 1
                res["reescritas"].append(t)
            conn.commit()

    res["bajados"] = res["completas"] + res["incrementales"]
    if podar:
        piso = (date.fromisoformat(hoy) - timedelta(days=DIAS_GUARDADOS)).isoformat()
        conn.execute("DELETE FROM velas_diarias WHERE date < ?", (piso,))
        conn.commit()
    return res


def correr(conn) -> dict:
    """La corrida nocturna completa: qué seguir, ponerlo al día y, con las velas
    ya guardadas, la lista única de cambios de ratio (`cambios_ratio`), a la que
    se le pasa de cada CEDEAR cuál es su acción de afuera. Un error de la lista
    no toca las velas."""
    from fechas import hoy_art
    t0 = time.monotonic()
    tickers, pares, de_cada_una = _seguimiento_por_persona(conn)
    # Los splits de Yahoo para la lista de cambios de ratio, ANTES de las velas:
    # después de ~2.000 pedidos de velas Yahoo ya no contesta (30/10: 863 de 868
    # sin respuesta). Con tope (`cambios_ratio.MAX_SPLITS_ANTES`): lo que más
    # importa son las velas. Un error acá no frena las velas.
    import cambios_ratio
    pares_cedear = {ba[:-3]: afuera for ba, afuera in pares.items()}
    try:
        splits_antes = cambios_ratio.adelantar_splits(conn, pares_cedear)
    except Exception as ex:
        log.error("velas: los splits de antes de las velas fallaron: %r", ex, exc_info=True)
        splits_antes = {"error": repr(ex)}
    res = actualizar(conn, _por_turnos(conn, de_cada_una, hoy_art()), en_orden=True, semanal=True)
    res["splits_antes"] = splits_antes
    # El universo del termómetro (termometro.py) lo baja su propio trabajo, no
    # esta corrida; igual no es «basura a pedido»: no se poda.
    import termometro
    res["podados_a_pedido"] = _podar_a_pedido(conn, set(tickers) | set(termometro.tickers_yahoo()))
    # Cuándo corrió la NOCHE, aparte de cada activo: las fichas abiertas a pedido
    # también anotan su `ultima_corrida`, y /admin no tiene que confundirlas.
    _anotar(conn, MARCA_CORRIDA_NOCHE, completa=False, ok=True, filas=res["filas"])
    conn.commit()
    try:
        res["cambios_ratio"] = cambios_ratio.correr(conn, pares_cedear)
    except Exception as ex:
        log.error("velas: la lista de cambios de ratio falló: %r", ex, exc_info=True)
        res["cambios_ratio"] = {"error": repr(ex)}
    res["seg"] = round(time.monotonic() - t0, 1)
    _guardar_corrida(conn, resumen(res))
    return res


# Cuántas corridas guardadas se conservan (una por noche, más las de /admin).
CORRIDAS_GUARDADAS = 60


def resumen(res: dict) -> dict:
    """Lo que dicen el renglón «Velas diarias:» del registro y /admin: números,
    no listas de mil nombres. De cada lista, cuántos y los primeros 10."""
    out = {}
    for k, v in res.items():
        if isinstance(v, list):
            out[k] = len(v)
            if v:
                out[f"{k}_ej"] = v[:10]
        elif isinstance(v, dict):
            out[k] = {kk: (len(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()}
        else:
            out[k] = v
    return out


def _guardar_corrida(conn, res_corto: dict) -> None:
    """Anota la corrida en `velas_corridas` (lo lee /admin: cuántos se bajaron,
    cuántos cortó Yahoo, cuántos no eran tickers). Un error acá no tira la
    corrida: las velas ya están guardadas."""
    try:
        conn.execute("INSERT INTO velas_corridas (cuando, resumen) VALUES (datetime('now'), ?) "
                     "ON CONFLICT(cuando) DO UPDATE SET resumen=excluded.resumen",
                     (json.dumps(res_corto, ensure_ascii=False),))
        conn.execute("DELETE FROM velas_corridas WHERE cuando NOT IN "
                     "(SELECT cuando FROM velas_corridas ORDER BY cuando DESC LIMIT ?)",
                     (CORRIDAS_GUARDADAS,))
        conn.commit()
    except Exception as ex:
        log.error("velas: no se pudo anotar la corrida: %r", ex, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass


def ultima_noche(conn):
    """El resumen de la última corrida de la noche (`resumen`) con su hora (UTC), o None."""
    r = conn.execute("SELECT cuando, resumen FROM velas_corridas ORDER BY cuando DESC LIMIT 1").fetchone()
    if not r:
        return None
    try:
        return {"cuando": r["cuando"], **json.loads(r["resumen"])}
    except (TypeError, ValueError):
        return None


# ─── A pedido: la ficha de un activo que nadie sigue ─────────────────────────
# La ficha del activo se abre desde el mapa de calor, el buscador y la watchlist,
# también para un activo que nadie tiene ni sigue: la corrida de la noche no lo
# baja. Entonces se baja en el momento en que alguien abre su ficha, con frenos
# para que nadie pueda usar la ficha para disparar descargas sin límite:
#   · sólo activos que la app conoce (`se_puede_pedir`): los de los buscadores,
#     el mapa de calor, BYMA, o los que la persona tiene o sigue. Un símbolo
#     inventado, o miles de símbolos reales de cualquier bolsa, no entran;
#   · cuántos activos nuevos por hora y por día, por persona, y por hora entre
#     todos;
#   · lo que ya se intentó hoy no se vuelve a pedir (la vela de hoy no entra
#     hasta mañana: otra descarga no puede traer nada nuevo), ni lo que falló
#     en las últimas horas;
#   · a Yahoo se lo espera poco, y si otra persona ya lo está bajando no se
#     espera: la ficha dice "trayendo la historia" y vuelve a pedir;
#   · lo que nadie sigue ni volvió a mirar en `A_PEDIDO_DIAS_SIN_USO` días se
#     borra de noche (`_podar_a_pedido`): no se acumula basura.
A_PEDIDO_POR_PERSONA_HORA = 30
A_PEDIDO_POR_PERSONA_DIA = 100
A_PEDIDO_TODOS_HORA = 200
A_PEDIDO_TOPE_SEG = 10.0
A_PEDIDO_REINTENTO_HORAS = 6
A_PEDIDO_DIAS_SIN_USO = 45
# La fila de `velas_estado` donde la corrida de la noche anota que corrió. No es
# un ticker (`~` no pasa la validación de símbolos de la API): no choca con nada.
MARCA_CORRIDA_NOCHE = '~corrida_noche'

_a_pedido_cond = threading.Condition()
_a_pedido_en_curso = set()
_a_pedido_hechos = deque()   # (momento, uid) de cada ticker bajado a pedido


def _variantes(asset: str) -> set:
    """Las formas de escribir el mismo papel: con o sin '.BA', una cripto con
    o sin '-USD', y una acción con clase con punto o guión (BRK.B / BRK-B)."""
    a = (asset or '').strip().upper()
    base = a[:-3] if a.endswith('.BA') else a
    for suf in ('-USD', '-USDT', '-USDC'):
        if base.endswith(suf):
            base = base[:-len(suf)]
    return {a, base, base.replace('.', '-'), base.replace('-', '.')}


def _lista_de_la_app() -> set:
    """Las listas de la app: lo que ofrecen los buscadores y lo que se puede
    tocar en Mercado (`ai.trade_tickers`, `home.market`) y lo que cotiza en BYMA
    (data912), con todas sus variantes (`_variantes`)."""
    from ai import trade_tickers as tt
    from home import market as mk
    out = set(tt.CRYPTO_TICKERS | tt.US_TICKERS | tt.CEDEAR_TICKERS | tt.AR_STOCK_TICKERS)
    out |= {x for lista in (mk.SP500_TOP_50, mk.MERVAL_TOP_25, mk.CRYPTO_TOP_30)
            for s in lista for x in _variantes(s)}
    try:
        from main import _fetch_data912_equities
        out |= set((_fetch_data912_equities() or {}).keys())
    except Exception:
        pass
    return out


def _lo_conoce_la_app(v: set) -> bool:
    """¿Está en las listas de la app (`_lista_de_la_app`)? `v`: las variantes
    del activo (`_variantes`)."""
    return bool(v & _lista_de_la_app())


def _lo_tiene(conn, v: set, uid, tablas) -> bool:
    marcas = ",".join("?" * len(v))
    for tabla, col in tablas:
        if conn.execute(f"SELECT 1 FROM {tabla} WHERE user_id=? AND UPPER({col}) IN ({marcas}) LIMIT 1",
                        (uid, *v)).fetchone():
            return True
    return False


def se_puede_pedir(conn, asset: str, uid) -> bool:
    """¿Se BAJA a pedido? Lo que la app conoce (`_lo_conoce_la_app`) y lo que la
    persona tiene, operó o sigue. Lo demás no se baja a pedido: sin esto,
    cualquier cuenta podía llenar la base pidiendo, de a 30 por hora, las
    decenas de miles de tickers reales que existen (auditoría 22/10).

    NO es la regla de qué se puede GUARDAR (una tesis, un dibujo, una alerta):
    ésa es `es_activo_real`. La lista de seguimiento acepta cualquier texto con
    forma de ticker, y si «lo sigo» bastara para guardar, cualquier símbolo
    inventado pasaba por esa puerta (re-test E4, 29/10)."""
    v = _variantes(asset)
    return _lo_conoce_la_app(v) or _lo_tiene(
        conn, v, uid, (("positions", "asset"), ("operations", "asset"), ("watchlist", "symbol")))


def es_activo_real(conn, asset: str, *uids) -> bool:
    """¿Existe este activo, para guardarle algo encima (una tesis, un dibujo,
    una alerta técnica)? LA regla, una sola:
      · lo conoce la app (`_lo_conoce_la_app`), o
      · tiene velas guardadas: lo bajó la noche o la ficha de alguien, o sea
        que Yahoo lo conoce y la ficha lo muestra con su gráfico. «Lo que la
        ficha muestra se puede dibujar, avisar y comentar»: YPF, SMCI o ARM no
        están en las listas de la app, y sin esto no se podían dibujar aunque
        el gráfico estuviera a la vista (re-test E3, 29/10), o
      · alguna de estas personas lo tiene o lo operó (un fondo no tiene
        velas, y su tesis igual vale).
    La lista de seguimiento NO alcanza: acepta cualquier texto, y un símbolo
    real que alguien sigue ya tiene velas (lo baja la noche, o su ficha).
    `uids`: de quién puede ser (los dibujos son del asesor que los hace, sobre
    el activo del cliente que mira)."""
    v = {x for x in _variantes(asset) if x}
    if not v:
        return False
    if _lo_conoce_la_app(v):
        return True
    yahoo = v | {x + '.BA' for x in v} | {x + '-USD' for x in v}
    marcas = ",".join("?" * len(yahoo))
    if conn.execute(f"SELECT 1 FROM velas_diarias WHERE symbol IN ({marcas}) LIMIT 1",
                    tuple(yahoo)).fetchone():
        return True
    return any(u and _lo_tiene(conn, v, u, (("positions", "asset"), ("operations", "asset")))
               for u in uids)


def tickers_a_pedido(asset: str, local: bool = False, cedears=None) -> list:
    """Los tickers de Yahoo que la ficha de `asset` necesita y se pueden bajar
    en el momento. La misma traducción que la corrida de la noche (`_yahoo_de`),
    con una excepción: de un CEDEAR se baja SÓLO la acción de afuera. Su serie
    en pesos se corrige con la lista de cambios de ratio (`cambios_ratio`), que
    se arma de noche y sólo para lo que alguien sigue; sin ella, el gráfico en
    pesos mostraría caídas que no existieron (XLE.BA −50 % el 05/12/2025). En
    pesos, la ficha usa la de afuera × el MEP de cada día (`tecnico.serie`).

    `local`: la ficha dice que es una acción argentina (su serie es la de BYMA).
    Un '.BA' necesita la lista de CEDEARs de BYMA para saber qué es: si data912
    no contesta, sólo se baja si es una acción argentina conocida (`local` lo
    manda la pantalla, pero también se puede escribir a mano). Mejor sin gráfico
    que uno equivocado guardado para todos."""
    from ai.trade_tickers import AR_STOCK_TICKERS
    from cripto import yahoo_de_cripto
    a = (asset or '').strip().upper()
    en_pesos = a.endswith('.BA') or bool(local)
    if cedears is None:
        cedears = _cedears_de_byma() if en_pesos else frozenset()
    ys = _yahoo_de(a, None, en_pesos, yahoo_de_cripto, cedears)
    if len(ys) == 2:          # la forma de un CEDEAR: [afuera, pesos]
        return [ys[0]]
    base = a[:-3] if a.endswith('.BA') else a
    if not cedears and any(t.endswith('.BA') for t in ys) and base not in AR_STOCK_TICKERS:
        return []
    return ys


def _ahora_utc() -> datetime:
    # `velas_estado.ultima_corrida` se guarda con datetime('now'): UTC, sin zona.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _necesita(conn, ticker: str, hoy: str, ahora: datetime) -> bool:
    """¿Hay que bajarlo? No, si:
      · su última vela es de ayer (la de hoy no entra hasta mañana: `_velas_de`);
      · ya se intentó HOY (día argentino), salga bien o mal: otra descarga hoy
        no puede traer nada nuevo. Un domingo, un lunes antes del cierre o el
        día después de un feriado, la última vela es de hace 2-4 días y antes
        eso se leía como "vieja": cada ficha volvía a bajar lo mismo y gastaba
        el cupo (auditoría 22/10);
      · se intentó hace menos de `A_PEDIDO_REINTENTO_HORAS`.
    Lo que sigue la corrida de la noche ya se intentó hoy: no se vuelve a pedir."""
    r = conn.execute("SELECT MAX(date) AS d FROM velas_diarias WHERE symbol=?", (ticker,)).fetchone()
    if r and r["d"] and (date.fromisoformat(hoy) - date.fromisoformat(str(r["d"])[:10])).days <= 1:
        return False
    e = conn.execute("SELECT ultima_corrida FROM velas_estado WHERE symbol=?", (ticker,)).fetchone()
    if e and e["ultima_corrida"]:
        try:
            cuando = datetime.fromisoformat(str(e["ultima_corrida"])[:19])
        except ValueError:
            return True
        from fechas import dia_art   # el día argentino de un instante UTC (regla única)
        if (dia_art(cuando) >= date.fromisoformat(hoy)
                or ahora - cuando < timedelta(hours=A_PEDIDO_REINTENTO_HORAS)):
            return False
    return True


def _hay_cupo(uid, n: int) -> bool:
    """¿Entran `n` tickers más en la última hora y en el último día para esta
    persona, y en la última hora para todos? Si entran, quedan anotados. Se
    llama con `_a_pedido_cond` tomado."""
    ahora = time.monotonic()
    while _a_pedido_hechos and ahora - _a_pedido_hechos[0][0] > 86400:
        _a_pedido_hechos.popleft()
    hora = [u for t, u in _a_pedido_hechos if ahora - t <= 3600]
    de_el_hora = sum(1 for u in hora if u == uid)
    de_el_dia = sum(1 for _, u in _a_pedido_hechos if u == uid)
    if (len(hora) + n > A_PEDIDO_TODOS_HORA or de_el_hora + n > A_PEDIDO_POR_PERSONA_HORA
            or de_el_dia + n > A_PEDIDO_POR_PERSONA_DIA):
        return False
    _a_pedido_hechos.extend((ahora, uid) for _ in range(n))
    return True


def asegurar(conn, tickers: list, uid, *, bajar=None, hoy: str = None):
    """Baja en el momento las velas de `tickers` que falten o estén viejas (ver
    `_necesita`), con los frenos de arriba. Devuelve None (listo, o no hacía
    falta), 'tope' (se llegó al cupo) o 'bajando' (otra persona lo está bajando
    ahora mismo: la ficha vuelve a pedir en unos segundos, sin dejar un hilo del
    servidor esperando)."""
    from fechas import hoy_art
    hoy = hoy or hoy_art()
    tickers = [t for t in dict.fromkeys(tickers or []) if t]
    faltan = [t for t in tickers if _necesita(conn, t, hoy, _ahora_utc())]
    if not faltan:
        return None
    # Una acción argentina que no tenía nada: su lista de cambios de cantidad
    # (YPFD 10 a 1) se arma después de bajarla, o el gráfico de hoy mostraría
    # el salto falso hasta la noche.
    nuevos_ba = [t for t in faltan if t.endswith('.BA') and not conn.execute(
        "SELECT 1 FROM velas_diarias WHERE symbol=? LIMIT 1", (t,)).fetchone()]
    with _a_pedido_cond:
        if set(faltan) & _a_pedido_en_curso:
            return "bajando"
        if not _hay_cupo(uid, len(faltan)):
            log.warning("velas a pedido: cupo lleno (uid=%s, %s)", uid, faltan)
            return "tope"
        _a_pedido_en_curso.update(faltan)
    try:
        # Se cierra la lectura antes de esperar a Yahoo: en Postgres quedaba una
        # transacción abierta los 10 s de la espera. Y se espera sin la conexión
        # en la mano (`soltar_la_base`): es una persona esperando en su pantalla.
        conn.commit()
        actualizar(conn, faltan, bajar=bajar, hoy=hoy, tope_seg=A_PEDIDO_TOPE_SEG,
                   tope_tanda=A_PEDIDO_TOPE_SEG, podar=False, soltar_la_base=True)
        bajados = [t for t in nuevos_ba if conn.execute(
            "SELECT 1 FROM velas_diarias WHERE symbol=? LIMIT 1", (t,)).fetchone()]
        if bajados:
            import cambios_ratio
            # Sin `pares`: a pedido nunca se baja la serie en pesos de un CEDEAR
            # (`tickers_a_pedido`), así que un '.BA' bajado acá es una acción argentina.
            cambios_ratio.recalcular(conn, [t[:-3] for t in bajados], tope_seg=A_PEDIDO_TOPE_SEG,
                                     soltar_la_base=True)
    finally:
        with _a_pedido_cond:
            _a_pedido_en_curso.difference_update(faltan)
            _a_pedido_cond.notify_all()
    return None


def poner_al_dia(conn, tickers: list, *, bajar=None, hoy: str = None) -> dict:
    """Baja de `tickers` sólo lo que no esté al día (`_necesita`: lo que ya
    bajó la corrida de la noche, o ya se intentó hoy, no se vuelve a pedir), sin
    cupos por persona: lo usa un trabajo del servidor con una lista fija (el
    termómetro), no una pantalla. Sin podar (eso lo hace la noche)."""
    from fechas import hoy_art
    hoy = hoy or hoy_art()
    ahora = _ahora_utc()
    faltan = [t for t in dict.fromkeys(tickers or []) if t and _necesita(conn, t, hoy, ahora)]
    # Se cierra la lectura antes de esperar a Yahoo (en Postgres quedaba abierta).
    conn.commit()
    if not faltan:
        return {"pedidos": 0, "completas": 0, "incrementales": 0, "sin_datos": [], "filas": 0}
    return actualizar(conn, faltan, bajar=bajar, hoy=hoy, podar=False)


def anotar_marca(conn, marca: str, filas: int = 0) -> None:
    """Anota en `velas_estado` que un trabajo corrió ahora (como
    `MARCA_CORRIDA_NOCHE`). La marca empieza con `~`: no es un ticker."""
    _anotar(conn, marca, completa=False, ok=True, filas=filas)


def _podar_a_pedido(conn, seguidos) -> int:
    """Borra las velas de lo que nadie sigue y nadie miró en los últimos
    `A_PEDIDO_DIAS_SIN_USO` días (lo bajado a pedido, o lo que alguien dejó de
    tener). Lo que se mira se vuelve a bajar a pedido cuando está viejo, y eso
    renueva su `ultima_corrida`: lo que se usa no se borra."""
    limite = (_ahora_utc() - timedelta(days=A_PEDIDO_DIAS_SIN_USO)).strftime('%Y-%m-%d %H:%M:%S')
    seguidos = set(seguidos or [])
    viejos = [r["symbol"] for r in conn.execute(
        "SELECT symbol FROM velas_estado WHERE ultima_corrida < ?", (limite,)).fetchall()
        if r["symbol"] not in seguidos]
    for t in viejos:
        conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (t,))
        conn.execute("DELETE FROM velas_estado WHERE symbol=?", (t,))
    conn.commit()
    return len(viejos)


# ─── Leer ────────────────────────────────────────────────────────────────────

def _crudas(conn, ticker: str, desde: str = None) -> list:
    """Las velas tal como las dio Yahoo, sin empalmar. Las lee `serie`; quien
    necesita lo crudo (la lista de cambios de ratio, la evidencia de un lote)
    lee la tabla con su propia consulta."""
    q = "SELECT date, open, high, low, close, volume FROM velas_diarias WHERE symbol=?"
    args = [ticker]
    if desde:
        q += " AND date >= ?"
        args.append(str(desde)[:10])
    return [dict(r) for r in conn.execute(q + " ORDER BY date", args).fetchall()]


def _empalmar(velas: list, g: dict) -> list:
    """Las velas en pesos con lo que dice la lista única de cambios de ratio
    (`cambios_ratio.para_el_grafico`):
      · escalones [(fecha, factor)]: lo ANTERIOR a `fecha` se lleva a la escala
        nueva (el precio ÷ factor; el volumen, en cantidad de CEDEARs, × factor).
        Cambios de ratio, escisiones (DuPont 03/11/2025) y precios rotos de nivel;
        sólo los que la serie guardada muestra (lo que Yahoo ya corrigió, no).
      · rotos: días que saltan y vuelven (ETHA 06/10/2026): se sacan.
      · pendientes: un salto de los últimos días que todavía no se sabe si se
        queda: se esconde desde ese día (no se reescala la historia por algo que
        puede ser un precio roto). La noche que haya 5 ruedas, se decide."""
    escalones = [(d, f) for d, f in (g.get("escalones") or []) if f and f > 0]
    rotos = set(g.get("rotos") or [])
    pendiente = min(g.get("pendientes") or [None], key=lambda d: d or "9999")
    if not escalones and not rotos and not pendiente:
        return velas
    out = []
    for v in velas:
        if v["date"] in rotos or (pendiente and v["date"] >= pendiente):
            continue
        f = 1.0
        for desde, factor in escalones:
            if v["date"] < desde:
                f *= factor
        if f != 1.0:
            v = {**v, **{k: (v[k] / f if v.get(k) is not None else None)
                         for k in ("open", "high", "low", "close")},
                 "volume": (v["volume"] * f if v.get("volume") is not None else None)}
        out.append(v)
    return out


def serie(conn, ticker: str, desde: str = None) -> list:
    """Las velas guardadas de un ticker, de la más vieja a la más nueva:
    [{date, open, high, low, close, volume}]. Las de una serie en pesos ('.BA')
    vienen empalmadas con la lista única de cambios de ratio (`cambios_ratio`):
    Yahoo no corrige los cambios de ratio de los CEDEAR en la especie en pesos
    (XLE.BA cae 50 % el 05/12/2025 sin que nada pase), y esa caída falsa dejaba
    la media de 200 en pesos diciendo "bajista" diez meses. [] si no hay: quien
    la usa tiene que decir "sin datos", nunca inventar. Es LA puerta para leer
    velas en un gráfico o una lectura: no leer la tabla a mano."""
    velas = _crudas(conn, ticker, desde)
    if not velas or not str(ticker).upper().endswith('.BA'):
        return velas
    import cambios_ratio
    return _empalmar(velas, cambios_ratio.para_el_grafico(conn, ticker))


def ultima_vela(conn, ticker: str):
    """La última vela de `ticker` por la puerta de `serie` (si la última vino
    rota, la anterior). None si no hay."""
    row = conn.execute("SELECT MAX(date) AS d FROM velas_diarias WHERE symbol=?", (ticker,)).fetchone()
    if not row or not row["d"]:
        return None
    desde = (date.fromisoformat(row["d"]) - timedelta(days=15)).isoformat()
    velas = serie(conn, ticker, desde)
    return velas[-1] if velas else None


# ─── La vela de HOY, mientras se mueve ──────────────────────────────────────
# Todo lo de arriba guarda ruedas CERRADAS, una vez por noche, y la de hoy se
# tira (`_velas_de`). La ficha igual quiere ver la rueda que se está moviendo:
# se le pide a Yahoo en el momento y NO se guarda en la tabla (mañana a la
# noche entra completa por la puerta de siempre). Se piden las ruedas de los
# últimos días, no sólo la de hoy: entre las 21 y la corrida de la noche, el día
# de una cripto (UTC) ya es «mañana» y la de «hoy» todavía no se guardó; sin
# ella, la de mañana quedaba pegada a la de anteayer (auditoría 30/10).
#
# Una tanda por ticker, en memoria 60 s y compartida entre todos: si 200
# personas miran Apple, Yahoo recibe un pedido por minuto. Es el mismo plazo que
# los precios (`_PRICE_CACHE` en main.py, `_QUOTE_CACHE` en home/market.py):
# pedir más seguido no trae nada más nuevo. Y si 100 personas piden a la vez
# justo cuando venció, sale UN pedido y los demás esperan su respuesta
# (`_en_curso_bajando`): antes salían 100.
VELA_EN_CURSO_TTL_S = 60
# Lo máximo que un pedido espera a otro que está bajando el mismo ticker (el que
# baja tiene tope de 8 s por Yahoo, dos veces con el plan B de las horas).
ESPERA_OTRO_SEG = 20.0
# Cuántos minutos tarda en llegar por Yahoo el precio de cada rueda. BYMA: el
# 30/10 el primer dato de la rueda (11:00 a 11:05) apareció a las 11:20, y
# TradingView gratis la da igual (`delayed_streaming_1200`). La pantalla lo dice
# (la hora del pedido no es la del precio) y `en_rueda` la cuenta. Es LA demora:
# las velas de 1 y 4 horas (velas_horarias) y la ficha (tecnico) la importan de acá.
DEMORA_MIN = {"byma": 20}
# Algunos días Nueva York cierra a las 13:00 (el viernes después de Acción de
# Gracias, el 24/12, a veces el 3/7) y el horario de Rendi
# (alerts_engine.rueda_en_horario) no lo sabe: la vela de las 12:30 seguía «en
# curso» hasta las 13:30 y la pantalla pedía cada minuto hasta las 16:00. Desde
# esta hora (de Nueva York) se le pregunta a Yahoo si la rueda sigue abierta.
CIERRE_TEMPRANO_NY = 13 * 60
# Los estados de Yahoo (`marketState`) de DESPUÉS del cierre. Un PRE no
# cuenta: no es «ya cerró».
_YA_CERRO = ("POST", "POSTPOST", "CLOSED")
_en_curso: dict = {}          # ticker → (time.time() de la respuesta, tanda | None)
_en_curso_bajando: dict = {}  # ticker → threading.Event mientras alguien lo baja
_en_curso_lock = threading.Lock()


def _ny_cerro_antes(reloj: datetime) -> bool:
    """¿Nueva York ya cerró aunque por el reloj la rueda siga (un día de cierre
    temprano)? Antes de las 13:00 de allá no puede haber cerrado y no se
    pregunta. Después lo dice el `marketState` de SPY que ya pide
    fuera_de_horario para el pre y el post (lo que Yahoo sabe, con sus feriados
    y cierres tempranos; guardado 60 s para toda la app), no un calendario
    nuestro. Sin respuesta, False: queda como sin esto (a lo sumo media hora de
    más «en curso»)."""
    try:
        from zoneinfo import ZoneInfo
        ny = reloj.astimezone(ZoneInfo("America/New_York"))
        if ny.hour * 60 + ny.minute < CIERRE_TEMPRANO_NY:
            return False
        import fuera_de_horario
        spy = fuera_de_horario._cotizaciones(["SPY"]).get("SPY") or {}
    except Exception:
        return False
    return (spy.get("marketState") or "").upper() in _YA_CERRO


def en_rueda_de(mercado: str, ahora: datetime = None) -> bool:
    """¿La rueda de `mercado` ('us', 'byma', 'cripto') todavía manda precios
    nuevos? En horario (`alerts_engine.rueda_en_horario`, LA definición del
    horario) contando la demora con que llegan (`DEMORA_MIN`): BYMA cierra a las
    17, pero lo de 16:40 a 17 llega hasta las 17:20. Y un día de cierre temprano
    de Nueva York (`_ny_cerro_antes`), hasta que cerró.

    Es LA cuenta para todo lo que depende de eso: si la vela diaria de hoy sigue
    en curso y la pantalla sigue pidiendo (`tecnico`), si se arma con las de 1
    hora (`_bajar_en_curso`) y si la de 1 o 4 horas está en curso
    (`velas_horarias`). Antes eran dos relojes: el de las horas sabía del cierre
    temprano y el de la vela diaria no (auditoría final B4, 31/10)."""
    from alerts_engine import rueda_en_horario
    ahora = ahora or _ahora_utc().replace(tzinfo=timezone.utc)
    if ahora.tzinfo is None:
        ahora = ahora.replace(tzinfo=timezone.utc)
    reloj = ahora - timedelta(minutes=DEMORA_MIN.get(mercado, 0))
    if not rueda_en_horario(mercado, reloj):
        return False
    return not (mercado == "us" and _ny_cerro_antes(reloj))


def en_rueda(ticker: str, ahora: datetime = None) -> bool:
    """`en_rueda_de` para el mercado de `ticker` (`home.market.mercado_de`)."""
    from home.market import mercado_de
    return en_rueda_de(mercado_de(ticker), ahora)


def _ohlcv(row):
    o, h, l, c = (_numero(row.get(k)) for k in ('Open', 'High', 'Low', 'Close'))
    v = _numero(row.get('Volume'))
    return o if o and o > 0 else None, h, l, c, v if v and v >= 0 else None


def _sana(h, l, c) -> bool:
    # La misma regla que `_velas_de`, pero acá sin rebaja: una vela en curso con
    # el máximo roto no se dibuja (no hay noche siguiente que la complete).
    return bool(c and h and l and h >= c >= l > 0)


def _vela(fecha, o, h, l, c, v) -> dict:
    return {"date": fecha, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _diarias(df) -> list:
    """Las ruedas sanas de una tabla diaria de Yahoo, de la más vieja a la más
    nueva. La fecha es la del mercado: el índice viene con su zona horaria."""
    if df is None or getattr(df, 'empty', True):
        return []
    out = {}
    for idx, row in df.iterrows():
        o, h, l, c, v = _ohlcv(row)
        if _sana(h, l, c):
            f = idx.date().isoformat()
            out[f] = _vela(f, o, h, l, c, v)
    return [out[f] for f in sorted(out)]


def _de_las_horas(df, hoy: str):
    """La vela del día armada con las de 1 hora: la apertura de la primera, el
    máximo y el mínimo de todas, el cierre de la última, el volumen sumado. Es
    el plan B cuando la diaria viene vacía: con los '.BA' pasa (04/08: la barra
    del día con volumen y los cuatro precios en NaN), y la de cada hora vino
    bien (medido 30/10 con AAPL.BA y GGAL.BA)."""
    if df is None or getattr(df, 'empty', True):
        return None
    horas = [f for f in (_ohlcv(row) for idx, row in df.iterrows() if idx.date().isoformat() == hoy)
             if _sana(f[1], f[2], f[3])]
    if not horas:
        return None
    vols = [f[4] for f in horas if f[4] is not None]
    return _vela(hoy, horas[0][0], max(f[1] for f in horas), min(f[2] for f in horas),
                 horas[-1][3], sum(vols) if vols else None)


def _bajar_en_curso(ticker: str):
    from pricing import yahoo as _yahoo
    from home.market import session_today
    hoy = session_today(ticker)

    def bajar(intervalo):
        try:
            return _yahoo.con_tope(_yahoo._historia, ticker, '5d', intervalo, False, 8.0,
                                   que=f"vela en curso {ticker} {intervalo}")
        except Exception as ex:
            log.info("vela en curso de %s (%s): %s", ticker, intervalo, ex)
            return None

    ruedas = [r for r in _diarias(bajar('1d')) if r["date"] <= hoy]
    # Las de 1 hora sólo con la rueda mandando precios: antes de la apertura
    # no hay ninguna de hoy, y serían dos pedidos por minuto para nada.
    if (not ruedas or ruedas[-1]["date"] != hoy) and en_rueda(ticker):
        armada = _de_las_horas(bajar('1h'), hoy)
        if armada:
            ruedas.append(armada)
    if not ruedas:
        return None
    return {"hoy": hoy, "ruedas": ruedas,
            "actualizada": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def ruedas_recientes(ticker: str):
    """Las ruedas de los últimos días de `ticker` (el de Yahoo, como en la
    tabla), con la de HOY mientras se mueve: {hoy, ruedas: [{date, open, high,
    low, close, volume}], actualizada} o None (Yahoo sin dato). `hoy` es el día
    de SU mercado (`home.market.session_today`: el UTC para una cripto). Quien
    las dibuja decide cuáles ya están guardadas. Nunca se guardan en
    `velas_diarias`, y lo que devuelve es compartido: no se modifica."""
    t = (ticker or '').strip().upper()
    if not t:
        return None
    with _en_curso_lock:
        e = _en_curso.get(t)
        if e and time.time() - e[0] < VELA_EN_CURSO_TTL_S:
            return e[1]
        bajando = _en_curso_bajando.get(t)
        if bajando is None:
            bajando = _en_curso_bajando[t] = threading.Event()
            soy_yo = True
        else:
            soy_yo = False
    if not soy_yo:
        bajando.wait(ESPERA_OTRO_SEG)
        with _en_curso_lock:
            e = _en_curso.get(t)
        return e[1] if e else None
    tanda = None
    try:
        tanda = _bajar_en_curso(t)
    finally:
        with _en_curso_lock:
            _en_curso[t] = (time.time(), tanda)
            _en_curso_bajando.pop(t, None)
        bajando.set()
    return tanda
