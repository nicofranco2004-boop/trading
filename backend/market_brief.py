"""Resumen del mercado del usuario — UN mail por día hábil, 11:00 ART.

Decisión de producto (Nico, 2026-09-15): uno solo, no dos. El de cierre
"duplica el costo y no agrega mucho valor". Las 11:00 son el minuto en que abre
BYMA y (en horario de verano del norte) Wall Street lleva media hora abierto,
así que el mail es EL PLAN DEL DÍA: qué se publicó desde que cerró ayer sobre
los activos que la persona tiene, y qué le pasa hoy.

Es opt-in: vive como una card más en /alertas y arranca APAGADA. El mismo mail
para todos, sin versión recortada por plan.

═══════════════════════════════════════════════════════════════════════════
EL MAIL ES UNA NARRACIÓN, NO UNA LISTA DE TITULARES.

Corrección de Nico (2026-09-15), y tiene razón: una lista de titulares no suma
nada, porque eso ya se ve en la app. Lo que sirve es que alguien lea todo y
cuente QUÉ PASÓ — la tasa de Estados Unidos, la inflación argentina, el
petróleo y por qué se movió, un conflicto que corta la oferta, y las noticias
fuertes de los activos que la persona tiene.

Eso no se puede hacer sin un modelo: resumir es justamente lo que un listado no
hace. Así que el mail lleva IA desde el día uno.

⚠️ DOS REGLAS DE DISEÑO QUE SOSTIENEN TODO ESTO:

1. **La IA narra el mercado; los números de la cartera los pone el código.**
   El modelo recibe titulares y devuelve prosa sobre el MERCADO. Los datos
   propios de la persona —qué cobra hoy, qué balance se publica— los arma
   `_events_today()` a partir del calendario y viajan aparte, sin pasar por el
   modelo. Es la frontera que evita que un resumen invente un dividendo.

2. **Si la narración falla, NO se manda el mail.** No hay degradado a lista:
   un mail que no cumple lo que promete es peor que ninguno, y entrena a la
   persona a no abrirlo. El reintento es la corrida del día siguiente.

⚠️ Y EL ORDEN NO ES NEGOCIABLE: primero se traen las noticias (bloqueando),
después se narra. El recolector de Rendi corre al arrancar el proceso y cuando
un usuario abre la app — no tiene reloj propio. Un cron que sólo redacta cuenta
el día de ayer con fecha de hoy. Ver `_refresh_news_for()`.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from fechas import hoy_art

log = logging.getLogger("market_brief")

# Cuántos tickers del usuario se consultan. Mismo cap que /api/news/portfolio
# (no martillar Google News), y a partir de ~20 activos los de más abajo no
# entran igual en el mail.
MAX_TICKERS = 20

# Cuánto material recibe el modelo. El tope POR TICKER existe para que un
# activo con mucha prensa (NVDA, AAPL) no tape a los otros diecinueve.
MAX_NEWS_PER_TICKER = 2
MAX_NEWS_TOTAL = 12
MAX_EVENTS = 6

# Titulares de contexto (tasas, inflación, dólar, petróleo, geopolítica) que se
# le pasan al modelo. Son los MISMOS para todos los usuarios, así que se leen
# una vez por corrida y se comparten — ver `run_briefs`.
MAX_CONTEXT_NEWS = 24
# Cupo POR TEMA. Sin esto, un día movido de tasas llena los 24 lugares con
# notas sobre tasas y el petróleo, la inflación argentina y el dólar quedan
# afuera justo el día que más pasa. Ver `market_context`.
MAX_CONTEXT_PER_TOPIC = 2

# Pausa entre envíos. El servicio de mail acepta un número acotado de pedidos
# por segundo y a partir de ahí rechaza. El brief del asesor manda uno tras
# otro sin pausa porque son decenas; este va a todos los que lo prendan.
SEND_GAP_SECONDS = 0.6


def _today_art() -> str:
    """Hoy en día ARGENTINO. Único calendario del backend (`fechas.hoy_art`).

    ⚠️ No usar utcnow(): entre las 21:00 ART y la medianoche el reloj universal
    ya está en el día siguiente, y el 'ya se lo mandé hoy' quedaría fechado
    mañana → el mail sale dos veces. Es el mismo bug que fechó una foto diaria
    en el futuro y pisó la del cierre real.
    """
    return hoy_art()


def _news_window_start(day_iso: str) -> str:
    """Desde cuándo miramos noticias, en ISO.

    El corte cae en la MEDIANOCHE de un día anterior, no "hace N horas": de
    martes a viernes, la medianoche de ayer (así el mail de las 11:00 abarca el
    día de ayer entero más lo que va de hoy); los LUNES, la medianoche del
    viernes, o el cierre de Wall Street del viernes y todo lo publicado el
    sábado y el domingo no aparecen nunca en ningún mail.

    Detalle de relojes, por si alguien compara a mano: `day_iso` es la fecha
    ARGENTINA y `news.published_at` viene del RSS en UTC. Son tres horas de
    desfasaje contra una ventana de uno a tres DÍAS, así que se la come la
    holgura — pero el corte es aproximado a propósito, no exacto, y no sirve
    para razonar sobre el borde minuto a minuto.
    """
    d = datetime.fromisoformat(day_iso)
    days = 3 if d.weekday() == 0 else 1
    return (d - timedelta(days=days)).isoformat()


# ─── Preferencia y anti-duplicado ────────────────────────────────────────────

def subscriber_uids(conn) -> list:
    """Usuarios que prendieron el resumen y tienen a dónde mandárselo."""
    try:
        rows = conn.execute(
            """SELECT p.user_id FROM market_brief_prefs p
               JOIN users u ON u.id = p.user_id
               WHERE p.enabled = 1 AND u.email IS NOT NULL AND u.email <> ''"""
        ).fetchall()
        return [r["user_id"] for r in rows]
    except Exception as ex:
        log.warning("market_brief: no se pudo leer la lista de suscriptos: %s", ex)
        return []


def brief_enabled(conn, uid: int) -> bool:
    """Opt-in puro: sin fila, APAGADO. Es al revés que el brief del asesor (que
    viene prendido de fábrica) porque este va a toda la base, no a un puñado de
    asesores, y un mail diario que nadie pidió es lo que te manda a la pestaña
    'Actualizaciones' de Gmail para siempre."""
    try:
        row = conn.execute(
            "SELECT enabled FROM market_brief_prefs WHERE user_id=?", (uid,)).fetchone()
        return bool(row and row["enabled"])
    except Exception:
        return False


def already_sent(conn, uid: int, day: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM market_brief_log WHERE user_id=? AND date=?",
            (uid, day)).fetchone() is not None
    except Exception:
        # Fail-CLOSED a "no se mandó": preferimos reintentar un mail antes que
        # tragarnos el único del día por un error de lectura. La PK de la tabla
        # impide el duplicado real igual.
        return False


def mark_sent(conn, uid: int, day: str, narrative: dict = None):
    """Sella el envío y guarda lo que se mandó.

    El texto queda registrado **para poder auditarlo**: un resumen escrito por
    un modelo que después nadie puede releer no es auditable, y el día que
    alguien diga "Rendi me dijo que tal cosa subió" hay que poder ir a ver qué
    le dijimos exactamente.

    (Antes esto alimentaba también el botón de la card, que mostraba el mail
    real del día. Ese botón ahora muestra un ejemplo fijo — el mail real la
    persona ya lo tiene en su casilla. Se sigue guardando igual.)
    """
    conn.execute(
        "INSERT OR IGNORE INTO market_brief_log (user_id, date, sent_at, narrative) "
        "VALUES (?,?,datetime('now'),?)",
        (uid, day, json.dumps(narrative, ensure_ascii=False) if narrative else None))


def sent_narrative(conn, uid: int, day: str):
    """Lo que se le mandó ese día, o None si no salió.

    ⚠️ SIN CALLER EN LA APP, a propósito: es el lector de auditoría de la
    columna `narrative`, para cuando haga falta revisar qué le dijimos a
    alguien. Lo usa el test que verifica que el texto se guarda. No es un
    backfill dormido ni una función olvidada — si algún día se agrega una
    pantalla de admin para revisar resúmenes, entra por acá.
    """
    try:
        row = conn.execute(
            "SELECT narrative FROM market_brief_log WHERE user_id=? AND date=?",
            (uid, day)).fetchone()
        return json.loads(row["narrative"]) if row and row["narrative"] else None
    except Exception:
        return None


# ─── Traer las noticias ANTES de redactar ────────────────────────────────────

def portfolio_tickers(conn, uid: int) -> list:
    """Activos del usuario que pueden tener prensa (sin cash, sin cripto).

    Cripto queda afuera por el mismo motivo que en /api/news/portfolio: la
    búsqueda "BTC acciones" no devuelve nada útil.
    """
    try:
        import main
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
               WHERE user_id=? AND is_cash=0 AND quantity > 0
                 AND asset NOT IN ('USDT','USD','ARS')""", (uid,)).fetchall()
        crypto = getattr(main, "CRYPTO_SYMBOLS", set())
        return [r["asset"] for r in rows if r["asset"] and r["asset"] not in crypto]
    except Exception as ex:
        log.warning("market_brief: tickers de uid=%s fallaron: %s", uid, ex)
        return []


def _refresh_news_for(tickers: list, get_db=None) -> int:
    """Sale a buscar noticias de estos tickers y ESPERA a que termine.

    ⚠️ Acá está la diferencia entre un resumen y un recorte de ayer. Las
    noticias de un ticker sólo se traen cuando alguien abre la app: no hay
    ninguna tarea programada que lo haga. Quien activa este mail es justamente
    el que NO entra todos los días, así que si el cron no las trae él mismo, su
    cartera nunca tiene prensa fresca en la base.

    Sin `max_wait_seconds` a propósito: el endpoint de la app usa un tope de 4
    segundos para que la pantalla cargue rápido y deja el resto en segundo
    plano; acá no hay nadie mirando una pantalla y sí hay un mail que depende
    del resultado, así que se espera. Todo esto corre dentro del hilo de fondo
    del cron, no a la vista del gateway.

    Devuelve cuántas noticias nuevas entraron, para el log.

    ⚠️ El conteo se mide contra la BASE, no con lo que devuelve el batch:
    `_ensure_news_batch_parallel` NO devuelve nada (sus workers persisten cada
    uno en su propia conexión y la función retorna None). Leer ese retorno daba
    un log que decía "0 noticias nuevas" mientras entraban 45 — medido en vivo
    contra Google News el 2026-09-15. Un contador que siempre dice cero es peor
    que no tenerlo: el día que el cron de verdad no traiga nada, el log va a
    decir exactamente lo mismo que cuando funciona.

    Se cuenta por `fetched_at`, que se estampa al insertar, así que mide lo que
    entró DURANTE esta corrida y no el acumulado de la tabla.
    """
    if not tickers:
        return 0
    import main
    get_db = get_db or main.get_db
    specs = [(f"{t} acciones", "es", "portfolio") for t in tickers]
    desde = datetime.utcnow().isoformat() + "Z"
    try:
        main._ensure_news_batch_parallel(specs, main.NEWS_TICKER_TTL)
    except Exception as ex:
        # El mail sale igual con lo que haya en la base. Preferimos un resumen
        # con noticias de ayer antes que ningún resumen.
        log.warning("market_brief: refresh de noticias falló: %s", ex)
        return 0
    try:
        conn = get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) c FROM news WHERE category='portfolio' "
                "AND fetched_at >= ?", (desde,)).fetchone()["c"]
        finally:
            conn.close()
    except Exception:
        return 0


# ─── Armado ──────────────────────────────────────────────────────────────────

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
    """Las MISMAS etiquetas que la persona ve dentro de la app. Si el mail dice
    'earnings' y la pantalla dice 'Reporte trimestral', parecen dos cosas."""
    return _EVENT_LABELS.get(t or "", t or "Evento")


def _news_for(conn, tickers: list, since_iso: str) -> list:
    """Titulares de estos tickers publicados desde `since_iso`.

    La tabla `news` NO tiene columna de ticker: el ticker vive dentro de
    `query_source` con la forma "NVDA acciones". Consultarla por una columna
    `ticker` inexistente tira una excepción que un `except` se come, y el
    resultado es un resumen vacío para siempre (ya pasó en el builder del
    briefing). Por eso el LIKE.
    """
    if not tickers:
        return []
    like = " OR ".join(["query_source LIKE ?"] * len(tickers))
    params = [f"{t} %" for t in tickers] + [since_iso]
    rows = conn.execute(
        f"""SELECT title, url, source, published_at, query_source, sentiment
             FROM news
            WHERE category = 'portfolio'
              AND ({like})
              AND published_at >= ?
            ORDER BY published_at DESC
            LIMIT 120""", params).fetchall()

    per_ticker, out = {}, []
    for r in rows:
        qs = r["query_source"] or ""
        ticker = qs.split(" ", 1)[0] if qs else None
        if not ticker:
            continue
        n = per_ticker.get(ticker, 0)
        if n >= MAX_NEWS_PER_TICKER:
            continue
        per_ticker[ticker] = n + 1
        out.append({
            "ticker": ticker,
            "title": r["title"],
            "url": r["url"],
            "source": r["source"],
            "sentiment": r["sentiment"],
            "published_at": r["published_at"],
        })
        if len(out) >= MAX_NEWS_TOTAL:
            break
    return out


def market_context(conn, since_iso: str) -> list:
    """Titulares de CONTEXTO: tasas, inflación, dólar, petróleo, geopolítica.

    Esto es lo que convierte el mail en un resumen de lo que pasó y no en una
    lista de noticias sueltas de la cartera. Son las categorías 'market' y
    'macro', que el recolector ya venía trayendo con sus doce búsquedas fijas
    (Fed, Treasuries, CPI, Merval, bonos argentinos, INDEC, dólar, BCRA,
    petróleo, geopolítica) y que la primera versión de este mail ignoraba.

    Es el MISMO material para todos: se lee una vez por corrida.

    ⚠️ SE REPARTE POR TEMA, no se toman los 25 más recientes. `query_source` es
    la búsqueda que trajo la noticia, o sea EL TEMA ("US Treasury yields",
    "precio del petróleo Brent WTI", "inflación Argentina INDEC"). Tomar los 25
    más nuevos a secas parece razonable y es un agujero: un día movido de tasas
    genera veinte notas sobre tasas y **el petróleo, la inflación argentina y
    el dólar no entran ni una vez**. El resumen quedaría monotemático justo los
    días en que más pasa. Con un cupo por tema, cada uno mete lo suyo.
    """
    rows = conn.execute(
        """SELECT title, source, category, query_source, published_at
             FROM news
            WHERE category IN ('market','macro')
              AND published_at >= ?
            ORDER BY published_at DESC
            LIMIT 200""", (since_iso,)).fetchall()

    por_tema, out = {}, []
    for r in rows:
        tema = r["query_source"] or "?"
        n = por_tema.get(tema, 0)
        if n >= MAX_CONTEXT_PER_TOPIC:
            continue
        por_tema[tema] = n + 1
        out.append({"title": r["title"], "source": r["source"],
                    "category": r["category"], "tema": tema})
        if len(out) >= MAX_CONTEXT_NEWS:
            break
    return out


def _events_today(conn, tickers: list, day: str) -> list:
    """Lo que le pasa HOY a los activos que tiene."""
    if not tickers:
        return []
    try:
        ph = ",".join("?" * len(tickers))
        rows = conn.execute(
            f"""SELECT ticker, event_type FROM financial_events
                 WHERE ticker IN ({ph}) AND event_date = ?
                 ORDER BY ticker LIMIT ?""",
            list(tickers) + [day, MAX_EVENTS]).fetchall()
        return [{"ticker": r["ticker"], "label": _event_label(r["event_type"])}
                for r in rows]
    except Exception as ex:
        log.warning("market_brief: eventos del día fallaron: %s", ex)
        return []


# ─── La narración ────────────────────────────────────────────────────────────

_SYSTEM = """Sos el que le cuenta a un inversor argentino qué pasó en el mercado, \
en un mail que recibe a las 11 de la mañana, cuando abre la rueda local.

QUÉ TENÉS QUE ESCRIBIR
Una NARRACIÓN, no una lista. La persona ya puede ver los titulares sueltos en la \
app: el mail sirve si le contás la historia que los conecta. Qué movió a los \
mercados y por qué, con el hilo causal explícito ("el crudo subió porque X, y eso \
presiona la inflación").

LOS TEMAS QUE IMPORTAN, cuando el material los tenga:
- Tasas: la Fed, los bonos del Tesoro de Estados Unidos, la tasa del BCRA.
- Inflación argentina y dólar (oficial, MEP, blue, contado con liqui), riesgo país.
- Petróleo y materias primas, y qué las movió.
- Conflictos, sanciones o aranceles que estén moviendo precios.
- Las noticias fuertes de los activos que la persona tiene.

REGLAS QUE NO SE NEGOCIAN
1. SÓLO podés usar los titulares que te paso abajo. Nada de lo que sepas por tu \
cuenta: no tenés forma de saber si sigue siendo cierto hoy.
2. NINGÚN número que no esté escrito en un titular. Ni precios ni porcentajes. \
Si un titular dice "el rendimiento superó el 5%", podés decir eso; si no dice el \
número, no lo pongas.
2.b ⚠️ LAS FECHAS QUE APARECEN DENTRO DE UN TITULAR NO SON CONFIABLES y no se \
mencionan nunca. Muchos medios tienen notas "EN VIVO" que actualizan y vuelven a \
publicar durante días: llegan con fecha de ayer y el título sigue diciendo "hoy \
miércoles 8". Nunca digas qué día es a partir de un titular, ni escribas "el \
lunes pasado" o "ayer" apoyándote en uno. El día de hoy te lo paso aparte, en \
el campo `hoy`. Un día de la semana sólo se puede nombrar si el titular habla \
del FUTURO ("la Fed decide el miércoles").
3. Un tema del que no haya material NO se menciona. Preferí tres frases ciertas a \
seis con relleno. No escribas "no hubo novedades sobre X".
4. Nada de pronósticos, recomendaciones ni consejos: ni "conviene", ni "es buen \
momento", ni "se espera que". Contás lo que pasó, no lo que va a pasar.
5. Si varios titulares se contradicen, decilo ("hay lecturas opuestas sobre la \
próxima decisión de tasas") en vez de elegir uno.

CÓMO ESCRIBIR
- Castellano rioplatense, vos y no tú. Para alguien que invierte pero no opera \
todo el día y no vive de esto.
- Sin jerga sin explicar. Si un término técnico es inevitable, explicalo en la \
misma oración: "el riesgo país (lo que el mercado cobra de más por prestarle a \
la Argentina) subió".
- Sin signos de exclamación, sin metáforas de guerra, de deporte ni de altura \
("tasas al cielo", "se derrumbó"), sin "los mercados amanecieron nerviosos". \
Literal: "la tasa subió", "el índice cayó".
- Nunca menciones los titulares como objetos ("según una nota de Reuters"). \
Contá el hecho.

EL RITMO — COPIÁ ESTE, ES LA REGLA QUE MÁS CAMBIA CÓMO SE LEE EL MAIL

Así SÍ (mirá el largo de cada oración, no el contenido):
  "El rendimiento del bono estadounidense a diez años superó el 5%. Es su nivel \
más alto desde 2007. Cuando la deuda de Estados Unidos paga tanto, el dinero se \
va de las acciones hacia los bonos. Las tecnológicas son las que más sufren: \
valen por lo que van a ganar dentro de muchos años."

Así NO:
  "El rendimiento superó el 5%, alcanzando su nivel más alto desde 2007, lo que \
genera presión sobre las valoraciones de empresas de crecimiento como las \
tecnológicas, reflejando una combinación de inflación persistente y expectativas \
de que la Fed podría subir tasas esta semana."

Las dos dicen lo mismo. La primera lo dice en cuatro oraciones y se entiende de \
una; la segunda encadena todo con comas, "lo que" y gerundios, y hay que leerla \
dos veces. Escribí siempre como la primera: cuando sientas que la oración sigue, \
poné el punto.

EL FORMATO, Y LA FRONTERA ENTRE LAS DOS PARTES
- titular: UNA oración, máximo 12 palabras, con lo que mandó. Sin dos puntos.

- mercado: 2 párrafos de 2 a 3 oraciones. El CONTEXTO: tasas, inflación, dólar, \
petróleo, riesgo país, conflictos. ⚠️ NO nombres acá ningún activo de la persona, \
ni siquiera de paso. Su lugar es el bloque de abajo, y decirlo dos veces hace un \
mail el doble de largo que no dice nada nuevo.

- tu_cartera: 1 o 2 párrafos, y **SÓLO podés nombrar los activos que están en la \
lista `activos_con_noticias`**. Ningún otro, por ningún motivo. Si un activo no \
está en esa lista, no tenés noticias suyas: no digas que subió, que cayó, que se \
beneficia ni que sufre, ni siquiera deduciéndolo del contexto. Esa deducción suena \
razonable y es exactamente cómo se afirma un hecho falso. Si la lista viene vacía, \
devolvé lista vacía y listo — no rellenes con generalidades del mercado.
  ⚠️ NO repitas acá lo que ya explicaste en "mercado": si la tasa ya quedó contada \
arriba, acá se da por sabida.

Si un mismo hecho toca las dos partes (por ejemplo, el BCRA cambia los encajes y \
la persona tiene un banco), el hecho va en "mercado" y el efecto sobre su activo \
va en "tu_cartera", en una sola oración y sin volver a explicar el hecho.
"""


def _packet_para_narrar(contexto: list, news: list, tickers: list) -> dict:
    """Lo único que ve el modelo.

    Sin datos de plata: ni cantidades, ni valuaciones, ni cuánto pesa cada
    posición.

    ⚠️ Y SIN LA LISTA COMPLETA DE ACTIVOS — sólo los que tienen titular. Esto
    empezó pasando `tickers` entero "para que sepa de qué activos hablar", y el
    resultado fue peor que un hueco: con una cartera de siete activos y
    titulares de sólo dos, el modelo habló de LOS SIETE. Escribió "el petróleo
    en alza beneficia a YPFD y PAMP: sus acciones subieron" sin tener una sola
    noticia de ninguna de las dos. Medido contra material real el 2026-09-15.

    Un modelo que ve una lista de siete nombres siente que tiene que cubrirlos,
    y lo que no sabe lo deduce del contexto y lo escribe como hecho. La
    prohibición en el prompt no alcanzaba: hay que sacarle el dato que habilita
    el relleno. Si de PAMP no hay noticia, PAMP no entra al packet.
    """
    con_material = sorted({n["ticker"] for n in news if n.get("ticker")})
    return {
        "hoy": _today_art(),
        "titulares_de_mercado": [
            {"t": c["title"], "tipo": c["category"]} for c in contexto],
        "titulares_de_sus_activos": [
            {"activo": n["ticker"], "t": n["title"]} for n in news],
        # Los únicos activos de los que se puede hablar en `tu_cartera`.
        "activos_con_noticias": con_material,
    }


def narrate(contexto: list, news: list, tickers: list):
    """Escribe la narración. Devuelve el objeto validado, o None.

    None significa "no se manda el mail": sin IA no hay resumen, y un listado
    de titulares —que es lo único que se puede armar sin modelo— ya se descartó
    por no aportar nada sobre lo que la app muestra. Ver la cabecera.
    """
    if not contexto and not news:
        return None
    try:
        from ai import llm
        from ai.schemas_market_brief import MarketNarrative
    except Exception as ex:
        log.warning("market_brief: no se pudo importar el motor de IA: %s", ex)
        return None
    if not llm.is_configured():
        log.warning("market_brief: IA no configurada — no se manda el resumen")
        return None
    try:
        res = llm.analyze(
            system_prompt=_SYSTEM,
            packet=_packet_para_narrar(contexto, news, tickers),
            output_model=MarketNarrative,
            model=llm.MODEL_HAIKU,   # resumir es donde Haiku empata con Sonnet
            max_tokens=1200,
        )
        return res.output if res else None
    except Exception as ex:
        log.error("market_brief: la narración falló: %s", ex)
        return None


def build_brief(conn, uid: int, day: str = None, contexto: list = None,
                narrar: bool = True) -> dict:
    """Contenido del mail. Devuelve {} si no hay NADA que contar.

    Un mail vacío es peor que ningún mail: entrena a la persona a no abrirlo, y
    el día que sí tenga algo importante ya no lo mira. Sin narración tampoco se
    manda (ver la cabecera del módulo).

    `contexto` se pasa desde `run_briefs` porque los titulares de mercado son
    los MISMOS para todos: leerlos una vez por corrida en vez de una por
    persona. Si no viene, se leen acá (es el camino de la vista previa).

    `narrar=False` arma todo menos la llamada al modelo. Lo usa la vista previa
    de la card para mostrar qué material entraría hoy sin gastar una llamada
    cada vez que alguien aprieta el botón.
    """
    day = day or _today_art()
    tickers = portfolio_tickers(conn, uid)[:MAX_TICKERS]
    if not tickers:
        return {}

    desde = _news_window_start(day)
    if contexto is None:
        contexto = market_context(conn, desde)
    news = _news_for(conn, tickers, desde)
    events = _events_today(conn, tickers, day)

    # Sin material no hay nada que narrar. Los eventos SOLOS no alcanzan: "hoy
    # AAPL presenta balance" es una línea de calendario, no un resumen del
    # mercado, y no justifica un mail.
    if not contexto and not news:
        return {}

    out = {
        "date": day,
        "tickers_n": len(tickers),
        "events": events,
        # Se guardan para la vista previa y para poder auditar después con qué
        # material se escribió lo que se mandó. NO van en el cuerpo del mail.
        "news": news,
        "context_n": len(contexto),
    }
    if not narrar:
        return out

    narrativa = narrate(contexto, news, tickers)
    if narrativa is None:
        return {}
    out["narrative"] = {
        "titular": narrativa.titular,
        "mercado": list(narrativa.mercado),
        "tu_cartera": list(narrativa.tu_cartera),
    }
    return out


# ─── Corrida (la dispara el cron externo) ────────────────────────────────────

def run_briefs(get_db, only_uid: int = None) -> dict:
    """Trae las noticias de todos los suscriptos y les manda el resumen.

    Idempotente por (usuario, día): re-correr el cron no duplica mails.

    El fetch de noticias se hace UNA vez para la UNIÓN de los activos de todos
    —dos personas con GGAL lo buscan una sola vez— y de paso deja la base
    fresca para la pantalla de Novedades del resto de la app.
    """
    day = _today_art()
    sent = skipped = failed = 0
    conn = get_db()
    try:
        uids = [only_uid] if only_uid else subscriber_uids(conn)

        # 1) A quién le toca hoy. Se resuelve ANTES de salir a la red para no
        #    buscar noticias de carteras a las que no les vamos a escribir.
        pending, tickers_by_uid = [], {}
        for uid in uids:
            if only_uid is None and (not brief_enabled(conn, uid)
                                     or already_sent(conn, uid, day)):
                skipped += 1
                continue
            t = portfolio_tickers(conn, uid)[:MAX_TICKERS]
            if not t:
                skipped += 1
                continue
            pending.append(uid)
            tickers_by_uid[uid] = t

        if not pending:
            return {"date": day, "sent": 0, "skipped": skipped, "failed": 0,
                    "news_fetched": 0}

        # 2) LA RED, con la base sin transacción abierta. Sostener el candado
        #    de escritura durante llamadas a internet le tira "database is
        #    locked" a toda la app — ya pasó dos veces en este repo.
        union = sorted({t for ts in tickers_by_uid.values() for t in ts})
        fetched = _refresh_news_for(union, get_db)

        # 3) El contexto de mercado es el MISMO para todos: se lee una vez.
        #    (La narración sí es por persona — cada uno tiene otros activos.)
        contexto = market_context(conn, _news_window_start(day))
        log.info("market_brief: %d tickers, %d noticias nuevas, %d titulares "
                 "de contexto", len(union), fetched, len(contexto))

        # 4) Recién ahora se narra y se manda.
        from billing import emails
        for i, uid in enumerate(pending):
            try:
                data = build_brief(conn, uid, day, contexto=contexto)
                if not data:
                    skipped += 1
                    continue
                row = conn.execute("SELECT email, name FROM users WHERE id=?",
                                   (uid,)).fetchone()
                if not row or not row["email"]:
                    skipped += 1
                    continue

                if i:
                    time.sleep(SEND_GAP_SECONDS)
                ok = emails.send_market_brief(to=row["email"],
                                              user_name=(row["name"] or ""),
                                              brief=data)
                if ok:
                    # Se sella DESPUÉS del envío y se confirma en el acto: si
                    # el servicio de mail rechazó, esta persona NO puede quedar
                    # marcada como enviada o se queda sin su resumen y nadie se
                    # entera. El reintento lo da la próxima corrida del cron.
                    mark_sent(conn, uid, day, data.get("narrative"))
                    conn.commit()
                    sent += 1
                else:
                    failed += 1
            except Exception as ex:
                failed += 1
                log.error("market_brief uid=%s falló: %s", uid, ex)

        return {"date": day, "sent": sent, "skipped": skipped, "failed": failed,
                "news_fetched": fetched}
    finally:
        conn.close()
