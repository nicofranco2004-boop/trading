"""Retorno time-weighted — el núcleo, POR USUARIO.

Este módulo no sabe qué es un asesor. Recibe una lista de user_ids y trabaja.
`advisor_twr.py` lo usa para agregar el libro; la app retail lo va a usar para
la cartera propia. Un cliente de un asesor ES un usuario: si la lógica del TWR
se escribe dos veces, terminamos con dos motores que dan distinto — que es
exactamente el problema que este trabajo viene a cerrar.

FASE 0 (lo que hay acá hoy): el semáforo de datos. Read-only. Clasifica cada
fila de `snapshots` según cómo se escribió, para poder responder una pregunta
antes de calcular nada: ¿desde cuándo la historia de esta persona es una
MEDICIÓN A MERCADO, y no contabilidad congelada ni una foto de media rueda?
"""
import json
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# ─── Cómo se distingue quién escribió cada snapshot ──────────────────────────
#
# Tres emisores, y hasta que exista la columna `source` había que deducirlo:
#
#   cron nocturno  (snapshots_job.take_snapshot_for_user)
#       → fx_to_usd_blue NOT NULL  +  holdings_json con la composición
#       ⚠️ PERO holdings excluye el cash (`if p.get('is_cash'): continue`), así
#          que un usuario TODO EN CASH deja holdings_json en NULL aunque el cron
#          haya corrido perfecto. Por eso NO alcanza con exigir la columna:
#          hay que cruzar contra si esa persona tenía posiciones que valuar.
#
#   browser        (POST /api/snapshots, lo dispara el Dashboard al cargar)
#       → nunca escribe holdings_json; fx_to_usd_blue sale del caché de dólar,
#         que con caché frío queda en NULL. Es un valor calculado en JS a media
#         rueda: sirve para que la curva del usuario no tenga huecos, NO para
#         medir un período.
#
#   importador     (persister._backfill_snapshots_from_monthly)
#       → ambas columnas en NULL, siempre a fin de mes, y total_value es
#         `capital_final` — que para meses cerrados tiene pnl_unrealized
#         forzado a 0, o sea EL COSTO. Encadenar eso no mide el mercado:
#         mide la cadena contable.
#
# La firma "ambas NULL" la comparten el importador y el browser-con-caché-frío.
# Es la misma heurística que ya usa /api/insights/mtm-audit, y acá se mantiene
# idéntica a propósito: si las dos difieren, una de las dos está mal.
#
# La regla que hace que esto sea seguro: sólo `medicion` habilita un borde de
# período. No hace falta separar perfectamente al browser del sintético, porque
# NINGUNO de los dos sirve como borde.

MEDICION = "medicion"                # cierre real a mercado — sirve de borde
RECONSTRUIDO = "reconstruido"        # tenencia histórica valuada a precio real de mercado
INTRADIA = "intradia"                # foto de media rueda escrita por un browser
SINTETICO_COSTO = "sintetico_costo"  # fabricado por el import: contabilidad, no mercado
INDETERMINADO = "indeterminado"      # no se puede afirmar cuál es — no se usa de borde

CLASES = (MEDICION, RECONSTRUIDO, INTRADIA, SINTETICO_COSTO, INDETERMINADO)

# ⚠️ DOS PREGUNTAS DISTINTAS, DOS LISTAS DISTINTAS.
#
# Confundirlas costó caro: al filtrar TODA serie con la lista de bordes, un
# usuario 100% sano —600 fotos del cron, cero imports— se quedaba con 51 puntos.
# Las columnas `holdings_json` y `source` se agregaron el 2026-07-04 y el
# 2026-08-06; TODO lo que el cron escribió antes tiene fx pero no composición, y
# la heurística lo llama INTRADIA (twr.py:100-102). Su CAGR pasaba de +13,7%
# sobre 19 meses a −56,9% sobre "1 mes".
#
# Aflojar la lista fue lo correcto; aflojar UNA SOLA lista no. `BASE_MERCADO`
# respondía a la vez "¿qué punto entra a la serie?" y "¿qué punto puede ser PICO o
# DENOMINADOR?", y meter INTRADIA ahí adentro hizo que una foto del browser fijara
# máximos: una cartera plana en 10.000 todos los cierres publicaba
# "Drawdown −33,3%" con el pico en la foto de media rueda, y el drawdown EMPEORABA
# cuantas más veces el usuario abría la app. El sesgo va en una sola dirección
# —los picos sólo suben—, así que cada foto que sobrevive lo empeora para siempre.
#
#   BASE_MERCADO — el punto es un cierre afirmable: puede ser BORDE de período,
#     PICO y DENOMINADOR. Es la exigencia máxima y es UNA sola pregunta: cerrar un
#     período contra el valor de hoy y fijar un máximo histórico piden lo mismo.
#
#   ACEPTA_LINEA — lo que entra a la serie DIBUJADA. Una foto intradía es un valor
#     de mercado (posiciones × precio, no contabilidad), así que sostiene la línea;
#     entra con `apto=False` y `curva_indexada` se encarga de que nunca sea pico ni
#     denominador. Es el mismo contrato que ya estaba escrito para INDETERMINADO.
#
# Lo que NUNCA entra en ninguna es SINTETICO_COSTO: no es una medición de nada,
# es la cadena contable copiada. Ése era el defecto original.
BASE_MERCADO = (MEDICION, RECONSTRUIDO)
ACEPTA_LINEA = BASE_MERCADO + (INTRADIA,)
# Alias explícito para los callers que preguntan por un BORDE de período. Es la
# misma tupla a propósito: son la misma exigencia.
BORDE_PERIODO = BASE_MERCADO

# Piso de cobertura para que una foto reconstruida cuente como base de mercado.
# `mtm_coverage` dice qué fracción del valor NO-CASH se pudo valuar a precio real;
# por debajo del piso la foto es mayormente costo, y presentarla como medida sería
# cambiar una mentira etiquetada (`source='import'`) por una sin etiquetar.
# ⚠️ LA COBERTURA NO ES UN UMBRAL. ES UN NÚMERO QUE SE MUESTRA.
#
# Hubo acá un piso de 0,70 y después uno de 0,995, y los dos hacían lo mismo:
# esconderle la curva entera al que no llegaba. Con 0,995, una cartera mixta
# argentina (55% de cobertura) y hasta la del propio demo (82%) no veían NADA en
# el modo que la app abre por defecto — o sea justo el usuario que este trabajo
# venía a servir. Endurecer el piso fue ir en la dirección opuesta.
#
# Lo que se pidió es: mostrar la curva SIEMPRE y DECLARAR qué parte es estimada.
# Así que la cobertura viaja como porcentaje y con nombres, y no filtra nada.
#
# Lo que distingue a los modos es OTRA COSA, y es la que importa:
#   · CERTERO (default) — todo lo que está valuado a PRECIO REAL: la foto del
#     cron, la intradía y la reconstrucción histórica. Que la reconstrucción esté
#     al 70% o al 100% no la saca de la curva: lo dice el número.
#   · ESTIMADO — además, la cadena CONTABLE (aportes + realizado, sin precio de
#     mercado). Es "un aproximado que puede estar mal, y lo sabés": nunca es el
#     default, y va etiquetado.
#
# SINTETICO_COSTO fuera del default es lo que impide que vuelva el defecto
# original (el −45% del caso 452 salía justamente de encadenar esa cadena).
#
# ⚠️ Y SON DOS PREGUNTAS, NO UNA — el módulo ya las separa para INTRADIA:
#     ¿el punto ENTRA A LA LÍNEA?     → sí, para que el usuario vea su curva.
#     ¿puede ser PICO o DENOMINADOR?  → no, si su valor sale de la contabilidad.
# Sacar el umbral significaba lo primero. Nunca lo segundo: cuando la cobertura es
# baja, `total_value` de la foto reconstruida ES EL COSTO (lo que no se pudo
# precear entra con unrealized 0), así que esa fila es contabilidad con etiqueta
# de mercado. Dejarla fijar un pico devolvió el −47,26% del caso 452 con el pico en
# una fecha que el sistema nunca midió.
COBERTURA_MEDICION = 0.90      # desde acá una reconstrucción puede ser pico/denominador

# ⚠️ EL PISO NO SALIÓ DE DATOS, Y ACÁ ESTÁN LOS DATOS. Medido el 2026-08-26 sobre la
# copia de producción del 2026-08-16, con este mismo clasificador:
#
#   · 661 usuarios con historia (≥2 snapshots con valor).
#       480 (72,6%) ven hoy un número publicado.
#       181 (27,4%) ven "—", y 172 de ésos por UN solo motivo:
#       `importado_sin_mediciones` — su historia es la cadena contable.
#   · Snapshots reconstruidos en producción: CERO. La columna `mtm_coverage` ni
#     siquiera existe en esa copia. O sea: HOY este piso no le tapa la curva a
#     NADIE. Todo su alcance es futuro, y cae entero sobre esos 172.
#   · Qué les va a pasar cuando la reconstrucción corra, estimado por la
#     composición de su tenencia no-cash (167 con tenencia valuable). Va como
#     BRACKET y no como número, porque `asset_type='OTHER'`/NULL es la mitad del
#     padrón y no afirma nada:
#       optimista (OTHER/NULL se puede precear) → 124/167 (74,3%) quedan bajo el
#         piso, cobertura mediana 0,614
#       pesimista (OTHER/NULL cae al costo)     → 163/167 (97,6%), mediana 0,122
#
# Léase: con el piso en 0,90, la reconstrucción le devuelve un NÚMERO a entre 4 y
# 43 de los 172 usuarios para los que se construyó. Los otros siguen viendo "—",
# ahora con la curva dibujada al lado. Eso no es un bug de este módulo —el piso
# hace exactamente lo que dice— pero es una decisión de producto que hasta hoy se
# estaba tomando sin el número. NO SE MUEVE ACÁ: va con el switch
# certero/estimado, y ésa es una decisión del dueño.

# Una serie PLANA es peor que un hueco: el hueco se ve, la serie plana pasa
# todos los guards. Pasa cuando `apply_last_known_prices` completa un símbolo
# delisted desde una tabla global sin TTL — el activo "tiene precio" para
# siempre y el valor no se mueve más. Con este umbral de ruedas seguidas
# idénticas se marca el tramo como degradado.
PLANO_RUEDAS = 3
PLANO_TOL = 0.0001   # 0,01% — dos cierres que difieren menos que esto son "el mismo"


def _es_fin_de_mes(fecha: str) -> bool:
    """¿La fecha ISO es el último día de su mes? El backfill del import escribe
    SIEMPRE a fin de mes; el browser escribe el día que se abrió la app."""
    from datetime import date, timedelta
    try:
        y, m, d = (int(x) for x in fecha[:10].split("-"))
        return (date(y, m, d) + timedelta(days=1)).month != m
    except (ValueError, TypeError):
        return False


# Lo que dice `source` manda: es un hecho estampado al escribir, no una
# deducción. La heurística de abajo queda sólo para las filas anteriores a esa
# columna, que nunca la van a tener.
_POR_SOURCE = {"cron": MEDICION, "browser": INTRADIA, "import": SINTETICO_COSTO,
               "mtm_backfill": RECONSTRUIDO}


def clasificar_fila(row, tenia_posiciones: bool) -> str:
    """Clasifica UN snapshot. `tenia_posiciones` responde si esa persona tenía
    algo no-cash para valuar: sin eso, un holdings_json vacío es lo correcto y
    no una señal de que la fila sea mala."""
    src = row["source"] if "source" in row.keys() else None
    if src == "mtm_backfill":
        # La reconstrucción sólo vale como base de mercado si de verdad se valuó a
        # mercado. Sin cobertura estampada no se puede afirmar → contable.
        # Con cobertura estampada es una reconstrucción a mercado; CUÁNTA parte se
        # valuó a precio real lo dice `mtm_coverage`, y quien decide qué hacer con
        # eso es el modo, y NINGUNO la usa para filtrar. Sin cobertura no se puede
        # afirmar nada → contable.
        cob = row["mtm_coverage"] if "mtm_coverage" in row.keys() else None
        try:
            return RECONSTRUIDO if cob is not None and float(cob) >= 0 else SINTETICO_COSTO
        except (TypeError, ValueError):
            return SINTETICO_COSTO
    if src in _POR_SOURCE:
        return _POR_SOURCE[src]
    tiene_holdings = bool(row["holdings_json"])
    tiene_fx = row["fx_to_usd_blue"] is not None

    if tiene_holdings:
        return MEDICION                       # composición estampada: lo escribió el cron
    if tiene_fx and not tenia_posiciones:
        # Cartera 100% cash: el cron deja holdings_json en NULL con razón, y el
        # valor (todo cash) es exacto. Es una medición válida.
        return MEDICION
    if tiene_fx:
        # Tenía posiciones pero no quedó composición → el browser.
        return INTRADIA
    if _es_fin_de_mes(row["date"]):
        return SINTETICO_COSTO                # fin de mes sin nada estampado: el import
    return INDETERMINADO


# ═══════════════════════════════════════════════════════════════════════════
# LA TERCERA PREGUNTA — ¿CON QUÉ REGLA ESTÁ VALUADA ESTA FILA?
#
# El módulo ya separaba dos preguntas (¿entra a la línea? ¿puede ser pico?). Le
# faltaba la tercera, y es la que hace falta para DIBUJAR:
#
#     ¿el `total_value` de esta fila es posiciones × PRECIO REAL,
#      o sale de la CONTABILIDAD (aportes + realizado, unrealized forzado a 0)?
#
# ⚠️ POR QUÉ NO ALCANZA CON `apto`. Son cosas distintas y se cruzan:
#   · INTRADIA es una foto de media rueda: está valuada A MERCADO (posiciones ×
#     precio) pero NO es un cierre, así que no puede fijar un pico → apto=False
#     con base de MERCADO.
#   · Una reconstrucción con cobertura baja está estampada `mtm_backfill` y su
#     clase es RECONSTRUIDO, pero lo que no se pudo precear entró con unrealized
#     0: su valor ES EL COSTO → base CONTABLE aunque la clase diga mercado.
# Usar `apto` como si fuera la base une esos dos casos, que no se parecen en nada.
#
# ⚠️ Y ES LA REGLA DEL SEGMENTO, NO DEL PUNTO. Un tramo que une un punto valuado
# al costo con uno valuado a mercado no dibuja un movimiento de la cartera: dibuja
# un CAMBIO DE REGLA. El caso 452 es exactamente eso —139.571 al costo contra
# 73.604 a mercado— y la resta da el −47,26% que el usuario reportó. No hay
# etiqueta, color ni header que arregle un segmento así: hay que no dibujarlo.
#
#     UN SEGMENTO ES VÁLIDO CUANDO SUS DOS EXTREMOS ESTÁN VALUADOS CON LA MISMA
#     REGLA. Cuando la regla cambia no hay segmento: hay un corte.
VALUADO_A_MERCADO = "mercado"   # posiciones × precio real
VALUADO_AL_COSTO = "costo"      # la cadena contable copiada


def es_apto(clase: str, base: str) -> bool:
    """¿Esta fila puede ser PICO y DENOMINADOR? (la segunda de las tres preguntas)

    ⚠️ VIVE ACÁ PORQUE TIENE MÁS DE UN LECTOR. La regla estaba escrita en varios
    lados y en cada uno decía algo distinto: `serie_medible` exigía el piso de
    cobertura, `/api/snapshots` hacía sólo `clase in BASE_MERCADO`, y
    `reporting/builder.py` filtraba por `accept=BORDE_PERIODO` —o sea también por
    clase pelada—. Medido: una reconstrucción con cobertura 0,05 salía apto=False
    en la curva y apto=True en los otros dos, para LA MISMA FILA. De ahí salían el
    "Mes difícil — -47.3%" de Reportes y el −47,26% del informe del asesor.
    """
    return clase in BASE_MERCADO and base == VALUADO_A_MERCADO


# ═══════════════════════════════════════════════════════════════════════════
# LA BASE ES UN DATO ESTAMPADO, NO UN CÁLCULO DE LECTURA
#
# ⚠️ ACÁ VIVIÓ UNA MEDIANA POR SERIE Y FUE UN ERROR. Conviene saber por qué antes
# de volver a escribirla.
#
# La idea era buena en un sentido: la cobertura es un CONTINUO y el piso de 0,90 la
# vuelve un binario, así que dos meses casi idénticos (0,88 y 0,91) caían en bases
# distintas y le partían el gráfico a alguien que había ganado 30%. La mediana
# arreglaba eso. Pero rompía algo peor, y en las dos direcciones:
#
#   · ASCENDÍA filas cuyo valor ES el costo. Medido: la MISMA fila de cobertura
#     0,05 —y también una de 0,00— entra a `medibles` cuando la mediana de la serie
#     es 0,95, y queda afuera cuando es 0,20. Con eso vuelve el pico fabricado, el
#     drawdown del caso 452, el "Mes difícil — −47.3%" de Reportes y el −47,26% del
#     informe que el asesor le FIRMA al cliente.
#   · Hacía que la respuesta dependiera de QUIÉN PREGUNTA Y CUÁNDO. La mediana se
#     calcula sobre las filas que trajo la query, así que Reportes (que pide un año)
#     e Insights (que pide la serie entera) clasificaban distinto la misma fila, y
#     `/api/snapshots?days=30` contra `?days=3650` devolvía `apto` distinto — mobile
#     y desktop contradiciéndose el mismo día. Y el pasado se reescribía solo: un mes
#     nuevo movía la mediana y re-etiquetaba meses YA CERRADOS.
#
# La conclusión no fue "elegir mejor el estadístico". Fue que la base no puede ser un
# cálculo de lectura: tiene que ser un HECHO ESTAMPADO EN LA FILA, decidido UNA vez
# por quien la escribe —que es el único que conoce el contexto completo— y leído por
# todos igual. Las columnas `snapshots.base` y `snapshots.apto` son eso.
#
# El precio, dicho para que no se lea como si no existiera: con la base por fila, una
# reconstrucción cuya cobertura oscila alrededor de 0,90 vuelve a partirse en varios
# segmentos dibujados. Es una pérdida real y conocida. Pero es un problema de DIBUJO,
# y el que traía la mediana era publicar un número inventado en el informe firmado.
def base_de(clase: str, cobertura=None) -> str:
    """Con qué REGLA está valuado el `total_value` de una fila de esa clase.

    INDETERMINADO cae en contable a propósito: no se puede afirmar que su valor
    salga de un precio, y ya viajaba en la banda por la misma razón. Afirmar
    mercado sin poder probarlo es el defecto original con otra cara.
    """
    if clase in (MEDICION, INTRADIA):
        return VALUADO_A_MERCADO
    if clase == RECONSTRUIDO:
        try:
            return (VALUADO_A_MERCADO
                    if cobertura is not None and float(cobertura) >= COBERTURA_MEDICION
                    else VALUADO_AL_COSTO)
        except (TypeError, ValueError):
            return VALUADO_AL_COSTO
    return VALUADO_AL_COSTO


def primera_fecha_con_posiciones(conn, uid: int):
    """La fecha más vieja en que esta persona tuvo algo NO-CASH. None si nunca.

    ⚠️ ESTO ARREGLA UN FALSO ASCENSO. `_usuarios_con_posiciones` mira las posiciones
    de HOY. Un usuario que vendió todo esta semana da `tenia_posiciones=False`, y con
    ese False sus filas VIEJAS de browser —escritas cuando sí tenía cartera— dejan de
    ser INTRADIA y ASCIENDEN a MEDICION: pasan a habilitar bordes de período que
    nunca fueron una medición. El flag tiene que evaluarse a la fecha de CADA fila.

    "Tuvo algo no-cash en o antes de D" es monótono: una vez verdadero, verdadero
    para siempre. Así que alcanza con la fecha más temprana, y comparar contra ella.
    Se mira la tenencia abierta (`positions.entry_date`) y también la ya cerrada
    (`operations`), porque el usuario que vendió todo es justamente el caso a cubrir.
    """
    fechas = []
    for q, args in (
        ("SELECT MIN(entry_date) AS d FROM positions "
         "WHERE user_id=? AND COALESCE(is_cash,0)=0 AND entry_date IS NOT NULL", (uid,)),
        ("SELECT MIN(COALESCE(entry_date, date)) AS d FROM operations "
         "WHERE user_id=? AND COALESCE(entry_date, date) IS NOT NULL", (uid,)),
    ):
        try:
            r = conn.execute(q, args).fetchone()
        except Exception:
            continue
        if r is not None and r["d"]:
            fechas.append(str(r["d"])[:10])
    if not fechas:
        # Sin fechas utilizables, pero puede haber posiciones no-cash sin entry_date:
        # ahí lo conservador es asumir que SÍ tenía (no ascender nada).
        try:
            hay = conn.execute(
                "SELECT 1 FROM positions WHERE user_id=? AND COALESCE(is_cash,0)=0 LIMIT 1",
                (uid,)).fetchone() is not None
        except Exception:
            hay = False
        return "0000-01-01" if hay else None
    return min(fechas)


def _tenia_posiciones_en(primera, fecha) -> bool:
    """El flag que `clasificar_fila` necesita, evaluado A LA FECHA DE LA FILA."""
    return bool(primera) and str(fecha)[:10] >= primera


# Cuántas ruedas seguidas —día calendario a día calendario, sin saltar ninguno—
# hacen falta para afirmar que a esa tanda la escribió el cron y no una persona.
# El cron corre TODOS los días, incluidos sábados, domingos y feriados; el browser
# escribe salteado y sólo cuando el usuario entra. Siete días corridos sin un solo
# hueco ya es una cadencia que una persona no produce.
RACHA_CRON_MINIMA = 7


def clasificar_serie(filas, primera_pos, orden_desc: bool = False) -> list:
    """Clasifica una SERIE de snapshots. Devuelve una clase por fila, en el mismo
    orden en que vinieron.

    Hace todo lo que hace `clasificar_fila` MÁS una cosa que una fila sola no
    puede saber: la CADENCIA.

    ⚠️ POR QUÉ HACE FALTA. `clasificar_fila` mira una fila aislada y, sin
    `source` ni `holdings_json`, cae en `if tiene_fx: return INTRADIA  # el
    browser` (twr.py, más abajo). Pero las columnas `holdings_json` y `source` se
    agregaron el 2026-07-04 y el 2026-08-06: TODAS las fotos que el cron escribió
    antes tienen esa firma y quedaban etiquetadas como si las hubiera sacado una
    persona a media rueda. Con eso, o se les negaba la serie a los usuarios viejos,
    o —aflojando la lista— una foto de browser pasaba a fijar picos.

    La información para desambiguarlas SÍ existe, pero está en el vecindario, no
    en la fila: una tanda de días calendario consecutivos SIN UN SOLO HUECO la
    escribió el cron. Sólo se aplica a filas LEGACY (sin `source`): una fila que
    dice `source='browser'` se respeta siempre — lo que dice `source` manda.
    """
    filas = list(filas)
    if orden_desc:
        filas = filas[::-1]
    clases = [clasificar_fila(r, _tenia_posiciones_en(primera_pos, r["date"]))
              for r in filas]

    def _legacy(r):
        try:
            return ("source" not in r.keys()) or (r["source"] is None)
        except AttributeError:
            return r.get("source") is None

    # Rachas de días calendario consecutivos.
    ini = 0
    for i in range(1, len(filas) + 1):
        corta = (i == len(filas)) or (_dias(filas[i - 1]["date"], filas[i]["date"]) != 1)
        if not corta:
            continue
        if (i - ini) >= RACHA_CRON_MINIMA:
            for j in range(ini, i):
                if clases[j] == INTRADIA and _legacy(filas[j]):
                    clases[j] = MEDICION
        ini = i

    return clases[::-1] if orden_desc else clases


# ⚠️ LA CLASIFICACIÓN ES READ-TIME, NO ESTÁ MATERIALIZADA. Decisión explícita.
#
# Hubo acá un `backfill_source_legacy` que estampaba `source='cron'` en las filas
# legacy que la cadencia identifica. Se sacó, y conviene saber por qué antes de
# volver a escribirlo:
#
#  · Nunca se enchufó. El commit que lo agregó decía "corre en un thread daemon al
#    startup" y ese thread no existía: `git grep backfill_source` devolvía la
#    definición y sus tests, cero call-sites. Este repo ya tiene dos casos del
#    mismo patrón (`plausibility.py`, el backfill a mercado); un tercero es peor
#    que no tenerlo, porque instala la premisa falsa de que prod está
#    materializado.
#  · Materializar es IRREVERSIBLE en el sentido que importa: una fila mal
#    estampada 'cron' pierde su ambigüedad para siempre y pasa a ser
#    BORDE_PERIODO, el filtro más estricto. La cadencia acierta casi siempre, pero
#    "casi siempre" no alcanza para una escritura que no se puede deshacer.
#
# Lo que hace innecesario materializarlo HOY es `clasificar_serie` + el test de
# contrato (`tests/test_contrato_clasificacion.py`): los 7 lectores están
# obligados a devolver la misma clase sobre la misma fila, y el test falla en el
# momento en que aparece el octavo que se olvida. Ese test es la garantía; el
# backfill sería una optimización con riesgo propio.
#
# Si algún día se materializa, tiene que ir con dry-run, log de lo que tocó y una
# decisión tomada sobre qué hacer con las filas que la cadencia no puede afirmar.


def _usuarios_con_posiciones(conn, ids: list) -> set:
    """Quiénes tienen (o tuvieron) alguna posición no-cash. Se usa para no
    castigar al que está todo en pesos."""
    if not ids:
        return set()
    ph = ",".join("?" * len(ids))
    return {r["user_id"] for r in conn.execute(
        f"""SELECT DISTINCT user_id FROM positions
            WHERE user_id IN ({ph}) AND COALESCE(is_cash,0)=0""", ids).fetchall()}


def _tramos_planos(filas: list) -> list:
    """Rachas de ruedas con el valor congelado. Devuelve [(desde, hasta, n)]."""
    fuera, racha = [], []
    for f in filas:
        v = float(f["total_value"] or 0)
        if racha and v > 0 and abs(v - racha[-1][1]) <= abs(racha[-1][1]) * PLANO_TOL:
            racha.append((f["date"], v))
            continue
        if len(racha) >= PLANO_RUEDAS:
            fuera.append((racha[0][0], racha[-1][0], len(racha)))
        racha = [(f["date"], v)] if v > 0 else []
    if len(racha) >= PLANO_RUEDAS:
        fuera.append((racha[0][0], racha[-1][0], len(racha)))
    return fuera


def diagnosticar(conn, ids: list) -> dict:
    """{user_id: diagnóstico} — desde cuándo la historia es medible, y por qué
    no antes. NO ESCRIBE NADA."""
    if not ids:
        return {}
    ids = [int(x) for x in ids]
    ph = ",".join("?" * len(ids))
    por_user = defaultdict(list)
    for r in conn.execute(
            f"""SELECT user_id, date, total_value, fx_to_usd_blue, holdings_json, source,
                       mtm_coverage
                FROM snapshots WHERE user_id IN ({ph}) AND total_value > 0
                ORDER BY user_id, date""", ids).fetchall():
        por_user[r["user_id"]].append(r)
    primera_por_user = {uid: primera_fecha_con_posiciones(conn, uid) for uid in ids}

    out = {}
    for uid in ids:
        filas = por_user.get(uid, [])
        conteo = {c: 0 for c in CLASES}
        mediciones = []
        # Por SERIE: mirando una fila legacy sola no se ve la cadencia, y este
        # diagnóstico tiene que reportar la MISMA clase que usan los otros lectores.
        for r, c in zip(filas, clasificar_serie(filas, primera_por_user.get(uid))):
            conteo[c] += 1
            if c == MEDICION:
                mediciones.append(r["date"])

        # El TWR sólo puede empezar donde hay DOS bordes medibles: con una sola
        # medición no hay tramo que medir.
        medible_desde = mediciones[0] if len(mediciones) >= 2 else None
        planos = _tramos_planos([r for r in filas if r["date"] in set(mediciones)])

        out[uid] = {
            "user_id": uid,
            "snapshots": len(filas),
            "por_clase": conteo,
            "medible_desde": medible_desde,
            "ultima_medicion": mediciones[-1] if mediciones else None,
            "motivo": _motivo(conteo, len(mediciones)),
            "tramos_planos": [{"desde": a, "hasta": b, "ruedas": n} for a, b, n in planos],
        }
    return out


def _motivo(conteo: dict, n_mediciones: int) -> str:
    """Por qué no se puede medir, en criollo. None cuando sí se puede."""
    if n_mediciones >= 2:
        return None
    total = sum(conteo.values())
    if total == 0:
        return "sin_historia"
    if conteo[SINTETICO_COSTO] and not n_mediciones:
        return "importado_sin_mediciones"
    if n_mediciones == 1:
        return "una_sola_medicion"
    return "sin_mediciones"


# Texto de cara al usuario. Vive acá y no en el frontend para que el asesor y
# el usuario final lean exactamente lo mismo.
MOTIVO_TEXTO = {
    "sin_historia": "Todavía no hay historia de esta cuenta.",
    "importado_sin_mediciones": "La historia se importó: son datos contables, "
                               "no mediciones a mercado.",
    "una_sola_medicion": "Hay una sola medición: hace falta al menos una "
                         "segunda para medir un período.",
    "sin_mediciones": "Todavía no hay mediciones a mercado de esta cuenta.",
    "sin_tramo_continuo": "Hay mediciones, pero están demasiado separadas entre sí "
                          "como para medir un tramo sin inventar el recorrido del medio.",
    "serie_partida": "La medición tiene un hueco en el medio. Los tramos de cada lado "
                     "se miden solos, pero no se pueden encadenar: no se sabe qué pasó "
                     "en el medio y suponerlo sería inventarlo.",
    "medicion_dudosa": "Entre dos fotos seguidas el valor saltó más de lo que explican "
                       "tus aportes y retiros. Hasta que se revise esa foto, los tramos "
                       "de cada lado se miden solos y no se encadenan.",
}


# ═══════════════════════════════════════════════════════════════════════════
# FASE 1 — el primitivo, el sellado y el encadenado
# ═══════════════════════════════════════════════════════════════════════════

# Un aporte que supera esta fracción del capital inicial se marca para revisar
# antes de entrar en la cadena: normalmente es un import que reescribió la
# historia, no plata que entró de verdad.
FLUJO_SOSPECHOSO = 0.5


def dietz(v0: float, v1: float, flow: float):
    """Modified Dietz de UN tramo. Es EL primitivo: si alguna pantalla calcula
    el retorno de otra forma, vuelve a haber dos motores.

        r = (v1 − v0 − flujo) / (v0 + 0,5·flujo)

    El 0,5 pondera el aporte como si hubiera entrado a mitad del tramo. Devuelve
    None cuando el denominador no da para medir (sin capital no hay retorno).

    SIN TECHO. El clamp de +50% que arrastra el lado retail trunca meses reales
    (+80% en cripto o post-devaluación es perfectamente posible) y encima NO se
    le aplica al benchmark → el sesgo es sistemático en contra del usuario y se
    compone mes a mes. El piso de −100% sí: no se puede perder más que todo.
    """
    denom = v0 + 0.5 * flow
    if denom <= 0:
        return None
    return max((v1 - v0 - flow) / denom, -1.0)


# ─── La cota de cordura de UN leg ────────────────────────────────────────────
#
# Medido sobre la copia de producción del 2026-08-16 (AUDIT_benchmark_2026-09-01):
# de los 480 usuarios que publicaban en CERTERO, 46 tenían UN leg diario entre dos
# cierres del cron con ratio ×>2 o ×<0,5 y el aportado quieto — y ese conjunto
# contenía EXACTAMENTE a los 6 de más de +100% (uid 282: +25.757%) y a los 31 de
# menos de −50% (uid 513: 16 millones → 109 → −100% absorbente). Una cartera no
# se quintuplica ni se divide por cinco en una rueda sin que entre o salga plata:
# lo que hay ahí es UNA FOTO MALA (la primera del cron sin posiciones valuadas, o
# un precio roto), no un rendimiento.
#
# Es la misma idea que el dueño ya decidió para la alerta del asesor
# (`PICO_MAX_VECES_LA_CARTERA`, main.py): fuera de la cota no se publica, y la
# cuenta va a la cola de revisión. Acá se aplica al LEG: si el flujo no lo explica
# y el ratio se sale de [1/X, X], ese leg no se encadena. Igual que el hueco de 45
# días y el desborde del denominador, corta el tramo — no arregla el dato.
#
# ⚠️ X = 3, NO 5, Y EL NÚMERO SALIÓ DE MEDIR. Con ×5 (la cota del asesor) quedaban
# publicados en CERTERO dos usuarios con +367% y +316% (uid 821, 1147: legs de ×3
# a ×4 en una rueda, sin flujo) y siete por debajo de −50%. Sensibilidad sobre los
# 480 que publicaban (AUDIT_benchmark_2026-09-01, port del pipeline):
#     ×2 → corta 46 · quedan con twr>+100%: 0 · con twr<−50%: 0
#     ×3 → corta 39 · 0 · 2
#     ×4 → corta 34 · 0 · 6
#     ×5 → corta 31 · 2 · 7
# Un ×3 en una rueda sin plata que entre o salga tampoco es una cartera: es una
# foto. ×2 cortaría también legs que una cartera cripto concentrada sí puede dar
# en un día malo; ×3 es el primer valor que no deja pasar ninguna ganancia
# fantasma y casi ninguna pérdida fantasma.
#
# `SALTO_FLUJO_TOL`: un aporte del 10% del valor no explica un ×3. Por encima de
# eso el leg puede ser un depósito grande de verdad, y el Modified Dietz ya sabe
# tratarlo (o desbordar, y ese caso lo cubre `desborde`).
SALTO_MAX_VECES = 3.0
SALTO_FLUJO_TOL = 0.10


def leg_dudoso(v0: float, v1: float, flow: float):
    """Por qué NO se puede encadenar este leg, o None si se puede.

      'desborde' — el flujo supera el doble del capital: `dietz` toca su piso de
                   −1,0 y el índice queda en CERO para siempre (el cero absorbente).
      'salto'    — sin flujo que lo explique, el valor se multiplicó o dividió
                   por más de `SALTO_MAX_VECES` entre dos fotos seguidas.
    """
    try:
        v0, v1, flow = float(v0), float(v1), float(flow or 0.0)
    except (TypeError, ValueError):
        return None
    r = dietz(v0, v1, flow)
    if r is not None and r <= -1.0 + 1e-12:
        return "desborde"
    if v0 > 0 and v1 > 0 and abs(flow) < SALTO_FLUJO_TOL * max(v0, v1):
        ratio = v1 / v0
        if ratio > SALTO_MAX_VECES or ratio < 1.0 / SALTO_MAX_VECES:
            return "salto"
    return None


def _fin_de_mes(mes: str) -> str:
    from datetime import date, timedelta
    y, m = (int(x) for x in mes.split("-"))
    return ((date(y + (m == 12), (m % 12) + 1, 1)) - timedelta(days=1)).isoformat()


def _hoy_art() -> str:
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(hours=3)).date().isoformat()


def bordes_medibles(conn, uid: int) -> list:
    """Los cierres que sirven de borde, en orden. SOLO mediciones a mercado:
    una foto intradía del browser o una fila fabricada al costo por el import
    no son un cierre, y encadenarlas mide cualquier cosa menos el mercado."""
    primera = primera_fecha_con_posiciones(conn, uid)
    filas = conn.execute(
        """SELECT id, date, total_value, fx_to_usd_blue, holdings_json, source,
                  mtm_coverage
           FROM snapshots WHERE user_id=? AND total_value > 0 ORDER BY date""",
        (uid,)).fetchall()
    return [r for r, c in zip(filas, clasificar_serie(filas, primera)) if c == MEDICION]


def _flujo(conn, uid: int, desde: str, hasta: str) -> float:
    """Aportes netos entre dos fechas. Sale de la SSoT canónica de la app
    (`compute_net_deposited_db`), no de una cuenta propia — si el TWR usara su
    propia definición de flujo, discutiría con el resto de las pantallas."""
    from snapshots_job import compute_net_deposited_db
    return (compute_net_deposited_db(conn, uid, as_of_date=hasta)
            - compute_net_deposited_db(conn, uid, as_of_date=desde))


def tramos(conn, uid: int, hasta_mes: str = None) -> list:
    """Los tramos MENSUALES medibles de un usuario, sin tocar la base.

    El cliente entra recién desde su primer mes CALENDARIO COMPLETO: el mes de
    alta no se mide. Con capital_inicio = 0 el 0,5 del Dietz infla ese mes
    (medido: 23,71% reportado contra 20,10% real), y en un libro de asesor
    TODOS los clientes nuevos tienen ese mes. Excluirlo elimina el sesgo de
    raíz en vez de estimarlo — es lo que hace GIPS.
    """
    bordes = bordes_medibles(conn, uid)
    if len(bordes) < 2:
        return []
    tope = hasta_mes or _hoy_art()[:7]

    # Último borde de cada mes: el cierre del mes.
    cierre = {}
    for b in bordes:
        cierre[b["date"][:7]] = b

    meses = sorted(cierre)
    out = []
    for i in range(1, len(meses)):
        mes = meses[i]
        if mes >= tope:            # el mes en curso no se sella: todavía no cerró
            continue
        b0, b1 = cierre[meses[i - 1]], cierre[mes]
        v0, v1 = float(b0["total_value"]), float(b1["total_value"])
        flow = _flujo(conn, uid, b0["date"], b1["date"])
        r = dietz(v0, v1, flow)
        if r is None:
            continue
        calidad = "ok"
        # ⚠️ LA MISMA COTA DE CORDURA QUE LA CURVA (`leg_dudoso`), en el motor del
        # asesor. Medido sobre la copia de producción: 34 meses sellables en 33
        # clientes tenían un leg con ratio fuera de ×3 y el aportado quieto — uid 282
        # pasaba de US$4,6 a US$1.133 entre dos cierres (+24.323 % en un mes, calidad
        # 'ok') y `twr_de` lo componía en el TWR del libro, que es el número que
        # justifica el fee. Un mes así no se compone: se marca, `twr_de` no publica
        # mientras esté en la cadena, y la cuenta va a la cola de revisión.
        if leg_dudoso(v0, v1, flow):
            calidad = "dudoso"
        elif v0 > 0 and abs(flow) > v0 * FLUJO_SOSPECHOSO:
            calidad = "flujo_sospechoso"
        elif abs(v1 - v0) <= abs(v0) * PLANO_TOL and abs(flow) <= abs(v0) * PLANO_TOL:
            calidad = "plano"
        out.append({
            "month": mes, "period_start": b0["date"], "period_end": b1["date"],
            "v0_usd": v0, "v1_usd": v1, "flow_usd": flow, "ret": r,
            "quality": calidad,
            "snap_id_start": b0["id"], "snap_id_end": b1["id"],
            "fx_basis": "mep_medio",
        })
    return out


# `quality` también: un mes que pasó de 'ok' a 'dudoso' (o al revés, si se
# corrigió la foto) cambió de sentido, y eso se registra como revisión nueva.
_CAMPOS_SELLO = ("period_start", "period_end", "v0_usd", "v1_usd", "flow_usd", "quality")


def sellar(conn, uid: int, hasta_mes: str = None) -> dict:
    """Sella los meses cerrados. Idempotente: recalcular no cambia nada si el
    input no cambió. Si SÍ cambió (un import reescribió la historia, un deploy
    corrió el hook que recalcula el aportado hacia atrás), se escribe
    revision+1 — nunca se pisa la revisión vieja. Que la historia haya cambiado
    es justamente lo que el asesor tiene que poder ver."""
    nuevos = revisados = 0
    for t in tramos(conn, uid, hasta_mes):
        prev = conn.execute(
            "SELECT * FROM twr_periods WHERE user_id=? AND month=? "
            "ORDER BY revision DESC LIMIT 1", (uid, t["month"])).fetchone()
        if prev is not None:
            igual = all(
                (abs(float(prev[c]) - float(t[c])) < 0.005) if isinstance(t[c], float)
                else prev[c] == t[c]
                for c in _CAMPOS_SELLO)
            if igual:
                continue
            rev = int(prev["revision"]) + 1
            revisados += 1
        else:
            rev = 1
            nuevos += 1
        conn.execute(
            """INSERT INTO twr_periods
               (user_id, period_start, period_end, month, v0_usd, v1_usd,
                flow_usd, ret, quality, snap_id_start, snap_id_end, fx_basis, revision)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, t["period_start"], t["period_end"], t["month"], t["v0_usd"],
             t["v1_usd"], t["flow_usd"], t["ret"], t["quality"],
             t["snap_id_start"], t["snap_id_end"], t["fx_basis"], rev))
    return {"sellados": nuevos, "revisados": revisados}


def sellados(conn, uid: int, desde_mes: str = None, hasta_mes: str = None) -> list:
    """La revisión VIGENTE de cada mes sellado, en orden."""
    q = ["SELECT * FROM twr_periods t WHERE t.user_id=?",
         "AND t.revision = (SELECT MAX(t2.revision) FROM twr_periods t2 "
         "WHERE t2.user_id=t.user_id AND t2.month=t.month)"]
    p = [uid]
    if desde_mes:
        q.append("AND t.month >= ?"); p.append(desde_mes)
    if hasta_mes:
        q.append("AND t.month <= ?"); p.append(hasta_mes)
    q.append("ORDER BY t.month")
    return conn.execute(" ".join(q), p).fetchall()


def twr_de(conn, uid: int, desde_mes: str = None, hasta_mes: str = None) -> dict:
    """El TWR encadenado de un usuario, sobre lo SELLADO.

        TWR = Π(1 + r_mes) − 1

    Devuelve siempre la cobertura pegada al número: un retorno sin decir sobre
    cuántos meses se midió es exactamente el dato que después hay que salir a
    explicar. Si la cobertura no alcanza, no se devuelve porcentaje: se
    devuelve el motivo.
    """
    filas = sellados(conn, uid, desde_mes, hasta_mes)
    if not filas:
        return {"twr": None, "meses": 0, "motivo": "sin_periodos_sellados"}

    revisados = [f["month"] for f in filas if int(f["revision"]) > 1]
    degradados = [f["month"] for f in filas if f["quality"] != "ok"]
    dudosos = [f["month"] for f in filas if f["quality"] == "dudoso"]
    if dudosos:
        # ⚠️ NO SE COMPONE POR ENCIMA DE UN MES DUDOSO. Componer un ×243 "y avisar
        # en `meses_degradados`" publica igual el +24.323 %: la etiqueta no le
        # saca el número al informe. Sin número, con el motivo — igual que la
        # curva. Los meses siguen sellados: cuando la foto se corrija, `sellar`
        # los revisa y el número vuelve solo.
        return {
            "twr": None,
            "meses": len(filas),
            "desde": filas[0]["month"],
            "hasta": filas[-1]["month"],
            "meses_revisados": revisados,
            "meses_degradados": degradados,
            "meses_dudosos": dudosos,
            "motivo": "medicion_dudosa",
        }

    idx = 1.0
    for f in filas:
        idx *= (1.0 + float(f["ret"]))

    return {
        "twr": idx - 1.0,
        "meses": len(filas),
        "desde": filas[0]["month"],
        "hasta": filas[-1]["month"],
        "meses_revisados": revisados,     # a estos les cambió la historia
        "meses_degradados": degradados,
        "meses_dudosos": [],
        "motivo": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# FASE 2 — LA SERIE CANÓNICA
#
# Todo lo que dibuje una curva de performance o publique un drawdown tiene que
# salir de acá. Mientras cada pantalla arme su propia serie sobre la cadena
# contable, cualquier guard nuevo en Python se queda corto — que es literalmente
# lo que ya pasó: `applyMtmToMonthly` descarta sintéticos y se abstiene sin borde
# medido (insightsModel.js:621 y :653), y trece líneas después
# `buildCumulativeReturnSeries` (insightsModel.js:106) pisa el cierre con el
# valor live sin mirar `m.mtm` y desarma el guard entero.
# ═══════════════════════════════════════════════════════════════════════════

# Cuántos días de silencio parten la serie en dos tramos. Más que esto y unir los
# dos puntos con una recta es inventar el recorrido del medio.
MAX_HUECO_DIAS = 45
# ⚠️ EL HUECO CONTABLE NO ES SILENCIO DE MERCADO. La cadena contable es un SALDO
# MENSUAL: sus puntos están a ~31 días entre sí por construcción, y un mes que
# falta en `monthly_entries` deja un leg de 59 días que la regla de los 45 partía
# como si fueran dos meses sin medir el mercado. Medido en producción (modo
# estimado): 10.295 legs contable→contable, mediana 31 días, 744 por encima de 45
# —meses faltantes, no huecos—, y con eso 535 de 670 usuarios veían su estimado
# partido en dos o más pedazos y 300 en tres o más. El mercado, en cambio, no
# tiene un solo hueco (19.203 legs mercado→mercado, máximo 14 días).
#
# Los flujos de esos meses se conocen igual (el aportado canónico sale de
# `monthly_entries`), así que el Dietz entre dos saldos contables separados por un
# mes faltante mide lo mismo que entre dos consecutivos: el modo ya se declara
# aproximado. Lo que sí sigue partiendo es un año entero perdido: pasado este
# tope, la recta ya no es una aproximación, es una invención.
MAX_HUECO_CONTABLE_DIAS = 400


def _dias(a: str, b: str) -> int:
    from datetime import date
    ya, ma, da = (int(x) for x in str(a)[:10].split("-"))
    yb, mb, db = (int(x) for x in str(b)[:10].split("-"))
    return abs((date(yb, mb, db) - date(ya, ma, da)).days)


def netdep_canonico(conn, uid: int):
    """date → net_deposited, calculado AHORA desde `monthly_entries`.

    ⚠️ POR QUÉ NO SE USA LA COLUMNA ESTAMPADA. `snapshots.net_deposited` no es un
    hecho del día: es una MEDICIÓN que el escritor hizo sobre `monthly_entries` EN
    EL MOMENTO de escribir la fila (snapshots_job.py:752). Un import reescribe
    `monthly_entries` hacia atrás y NO re-estampa las fotos viejas, así que en la
    misma serie conviven estampas de dos momentos distintos. Restarlas para sacar
    "el flujo de la ventana" no mide un flujo: mide cuánto cambió la contabilidad
    entre los dos momentos en que se escribió cada foto.

    Medido: julio plano en 110.000, cero aportes en julio, cron diario sano, y un
    import del historial 2025 el 16/7 → el mes cerrado publicaba −US$50.000 /
    −37,04% y Diagnóstico el mismo −37,04% de drawdown. Y un mes cerrado NO SE
    AUTOCURA NUNCA. El par mezclado está GARANTIZADO, no es mala suerte: el
    reconstructor estampa desde el `monthly_entries` actual y saltea las fotos del
    cron a propósito.

    Las dos puntas salen de la MISMA lectura, así que la resta vuelve a ser un
    flujo. Es la convención canónica —filas 'global' + baseline— la misma que
    estampan el cron (`compute_net_deposited`) y `_recompute_snapshots_netdep_for_user`.
    """
    filas = conn.execute(
        "SELECT year, month, capital_inicio, deposits, withdrawals FROM monthly_entries "
        "WHERE user_id=? AND broker='global' ORDER BY year, month", (uid,)).fetchall()
    if not filas:
        # Sin contabilidad no hay nada que afirmar: devolver 0 para todo convertiría
        # cualquier aporte en ganancia. El caller se queda con lo estampado.
        return None
    baseline = float(filas[0]["capital_inicio"] or 0)
    acum, cum = [], 0.0
    for r in filas:
        cum += float(r["deposits"] or 0) - float(r["withdrawals"] or 0)
        acum.append((f"{int(r['year']):04d}-{int(r['month']):02d}", baseline + cum))

    def _en(fecha):
        ym = str(fecha)[:7]
        # ⚠️ ANTES DE LA PRIMERA FILA VALE EL BASELINE, NO CERO — y acá se aparta a
        # propósito de lo que estampa `compute_net_deposited_db`.
        # El baseline (`capital_inicio` de la primera fila) es un STOCK: la plata
        # que ya estaba cuando arranca la contabilidad. La convención estampada lo
        # atribuye al primer mes, y eso está bien para "cuánto puso en total" pero
        # es veneno para una RESTA: el borde anterior daba 0 y el posterior daba el
        # baseline entero, así que un año entero publicaba −62,3% porque el primer
        # tramo leía el baseline como un aporte de enero. Un stock tiene que
        # aparecer a los DOS lados de la resta para cancelarse.
        v = baseline
        for k, val in acum:
            if k <= ym:
                v = val
            else:
                break
        return v
    return _en


def _instrumentos_al_costo(row) -> list:
    """Qué instrumentos de esa foto NO se pudieron valuar a precio y quedaron al
    costo. Sale de `holdings_json`, donde el reconstructor los marca. Sirve para
    poder decir "el 6% restante son tus FCI" en vez de un porcentaje pelado."""
    try:
        raw = row["holdings_json"]
    except (KeyError, IndexError, TypeError):
        return []
    if not raw:
        return []
    try:
        import json as _json
        data = _json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return sorted({h.get("asset") for h in data
                   if isinstance(h, dict) and h.get("al_costo") and h.get("asset")})


def _aportado_por_punto(conn, uid: int, filas):
    """Devuelve fila → aportado acumulado, con el borde de mes ANCLADO al canónico
    y el día dentro del mes decidido por la estampa.

        aportado(d) = clamp( canon(M) − (estampa(rn) − estampa(d)),
                             min(canon(M−1), canon(M)),
                             max(canon(M−1), canon(M)) )        rn = última fila de M

    ⚠️ POR QUÉ ASÍ, DESPUÉS DE DOS INTENTOS FALLIDOS.

    · Sólo la ESTAMPA: tiene resolución diaria de verdad, pero un import reescribe
      la contabilidad hacia atrás sin re-estampar las fotos viejas. Conviven
      estampas de dos momentos y el escalón entre unas y otras se lee como un
      flujo: −37,04% de drawdown en un mes PLANO (ronda 4).

    · Sólo el CANÓNICO: es consistente, pero tiene resolución MENSUAL —los flujos
      manuales viven en `monthly_entries.manual_*` sin fecha—, así que el día 1 ya
      trae el depósito del mes adentro. Si la serie ARRANCA dentro de ese mes, el
      ancla ya lo incluye, el flujo del día en que la plata entra da CERO, y el
      salto de valor se encadena como rendimiento: un depósito de US$200.000 con
      el mercado plano publicaba +200,00% (ronda 5).

    Las dos puntas de cada mes caen SIEMPRE en el canónico, así que la suma
    telescopia exacto y ningún flujo cruza el borde de mes — eso mata el artefacto
    del canónico puro. Y el corredor entre canon(M−1) y canon(M) impide que una
    estampa stale se filtre: cuando el mes no tuvo flujo el corredor colapsa a un
    punto, que es exactamente el caso del import a mitad de mes.

    (El ideal sigue siendo reconstruir el aportado desde las FECHAS REALES de los
    movimientos. Esto NO lo reemplaza — pero tampoco hacía falta esperar a eso.)
    """
    canon = netdep_canonico(conn, uid)
    if canon is None:                      # sin contabilidad: sólo queda la estampa
        return lambda r: float(r["net_deposited"] or 0)

    ultimo_del_mes = {}
    for r in filas:
        ym = str(r["date"])[:7]
        prev = ultimo_del_mes.get(ym)
        if prev is None or str(r["date"]) > str(prev["date"]):
            ultimo_del_mes[ym] = r

    def _mes_anterior(ym):
        y, m = int(ym[:4]), int(ym[5:7])
        return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"

    def _en(r):
        ym = str(r["date"])[:7]
        c_m = canon(f"{ym}-01")
        c_prev = canon(f"{_mes_anterior(ym)}-01")
        rn = ultimo_del_mes.get(ym)
        if rn is None:
            return c_m
        v = c_m - (float(rn["net_deposited"] or 0) - float(r["net_deposited"] or 0))
        lo, hi = (c_prev, c_m) if c_prev <= c_m else (c_m, c_prev)
        return max(lo, min(hi, v))
    return _en


def valor_para_dibujar(p) -> float:
    """El valor crudo de un punto, MIDA O NO. La única puerta al número de un punto
    que no mide, y tiene nombre largo a propósito.

    Sirve para DIBUJAR y nada más: la posición vertical de un punto en un gráfico.
    Si lo que estás por hacer es publicar un porcentaje, un delta o un pico, este
    no es el dato — `serie_medible()["medibles"]` lo es.
    """
    return float(p["value"] if p.get("apto") else p["value_no_medible"])


def _tiene_columna(conn, tabla: str, col: str) -> bool:
    """¿Existe la columna? Pedirla a secas ata este módulo a que la migración de
    startup ya haya corrido — y un deploy donde el código llega antes que su columna
    es exactamente cómo se cayó producción el 2026-08-02."""
    try:
        return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({tabla})"))
    except Exception:
        return False


def _sel_estampo(conn) -> str:
    """El fragmento SELECT de `base`/`apto`, o NULLs si la migración no corrió."""
    b = "base" if _tiene_columna(conn, "snapshots", "base") else "NULL AS base"
    a = "apto" if _tiene_columna(conn, "snapshots", "apto") else "NULL AS apto"
    return f"{b}, {a}"


def _col(row, nombre):
    """El valor de una columna que puede no existir en esta fila/consulta."""
    try:
        return row[nombre]
    except (KeyError, IndexError, TypeError):
        return None


def bases_de_serie(filas, clases) -> list:
    """La base de CADA fila, EN ORDEN. Prefiere el ESTAMPO; si no hay, la deduce.

    ⚠️ EL ESTAMPO MANDA. `snapshots.base` lo escribe quien crea la fila, que es el
    único que conoce el contexto completo (el reconstructor sabe la cobertura del
    mes que está escribiendo). Leerlo en vez de recalcularlo es lo que garantiza las
    tres cosas que once rondas no pudieron:
      · la MISMA fila tiene la MISMA base para todos los lectores,
      · en TODA ventana —`?days=30` y `?days=3650` responden igual—,
      · y no cambia cuando llega un mes nuevo ni cuando se importa historia vieja.

    La deducción es sólo para las filas que todavía no pasaron por `estampar_base`
    (un deploy donde el código llega antes que la migración, o una fila escrita por
    código viejo). Es POR FILA a propósito: cualquier estadístico de serie hace que
    la respuesta dependa de qué filas trajo la query, que es el defecto que se sacó.
    """
    out = []
    for r, c in zip(filas, clases):
        estampada = _col(r, "base")
        if estampada in (VALUADO_A_MERCADO, VALUADO_AL_COSTO):
            out.append(estampada)
        else:
            out.append(base_de(c, _col(r, "mtm_coverage")))
    return out


def aptos_de_serie(filas, clases, bases=None) -> list:
    """Si cada fila puede ser PICO y DENOMINADOR. Prefiere el estampo, igual que la base."""
    bases = bases if bases is not None else bases_de_serie(filas, clases)
    out = []
    for r, c, b in zip(filas, clases, bases):
        estampado = _col(r, "apto")
        if estampado is not None and _col(r, "base") in (VALUADO_A_MERCADO, VALUADO_AL_COSTO):
            out.append(bool(estampado))
        else:
            out.append(es_apto(c, b))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# EL ESTAMPADO
# ═══════════════════════════════════════════════════════════════════════════

def base_y_apto_para(clase: str, cobertura=None):
    """(base, apto) de una fila de esa clase. LA función que usan los escritores.

    Existe para que los cuatro que escriben snapshots —el cron, el browser, el
    import y el reconstructor— no cada uno su versión. El que agregue un quinto
    escritor tiene que pasar por acá.
    """
    b = base_de(clase, cobertura)
    return b, (1 if es_apto(clase, b) else 0)


def estampar_base(conn, uids=None, solo_faltantes: bool = True) -> dict:
    """Estampa `base` y `apto` en las filas que no los tienen. Devuelve el conteo.

    ⚠️ `solo_faltantes=True` NO ES UNA OPTIMIZACIÓN, ES EL CONTRATO. Una vez que una
    fila tiene su base estampada, NADIE la vuelve a tocar: es lo que hace que un mes
    YA CERRADO no se pueda reescribir porque el usuario importó historia de otro año.
    Con la base calculada en lectura eso pasaba solo, y un mes cerrado no se autocura
    nunca.

    ⚠️ Y CLASIFICA POR SERIE, no fila por fila. La CLASE sí necesita el vecindario:
    las fotos que el cron escribió antes de que existiera la columna `source` sólo se
    distinguen de una del browser por la cadencia diaria (`clasificar_serie`). Las
    filas legacy NO se excluyen — excluirlas fue la trampa de la ronda 3.
    """
    n_filas = n_users = 0
    if not (_tiene_columna(conn, "snapshots", "base")
            and _tiene_columna(conn, "snapshots", "apto")):
        return {"filas": 0, "usuarios": 0, "motivo": "sin_columnas"}
    q = ["SELECT id, user_id, date, total_value, fx_to_usd_blue, holdings_json, "
         "source, mtm_coverage, base, apto FROM snapshots"]
    args = []
    if uids:
        q.append("WHERE user_id IN (%s)" % ",".join("?" * len(uids)))
        args = [int(x) for x in uids]
    q.append("ORDER BY user_id, date")
    por_user = defaultdict(list)
    for r in conn.execute(" ".join(q), args).fetchall():
        por_user[r["user_id"]].append(r)

    for uid, filas in por_user.items():
        pendientes = [r for r in filas
                      if not solo_faltantes or _col(r, "base") not in
                      (VALUADO_A_MERCADO, VALUADO_AL_COSTO)]
        if not pendientes:
            continue
        clases = clasificar_serie(filas, primera_fecha_con_posiciones(conn, uid))
        pend_ids = {r["id"] for r in pendientes}
        tocadas = 0
        for r, c in zip(filas, clases):
            if r["id"] not in pend_ids:
                continue
            b, a = base_y_apto_para(c, _col(r, "mtm_coverage"))
            conn.execute("UPDATE snapshots SET base=?, apto=? WHERE id=?", (b, a, r["id"]))
            tocadas += 1
        if tocadas:
            n_filas += tocadas
            n_users += 1
    return {"filas": n_filas, "usuarios": n_users}


MODO_CERTERO = "certero"
MODO_ESTIMADO = "estimado"


def serie_medible(conn, uid: int, desde: str = None, hasta: str = None, *,
                  modo: str = MODO_CERTERO,
                  aceptar: tuple = ACEPTA_LINEA,
                  max_hueco_dias: int = MAX_HUECO_DIAS) -> dict:
    """Los puntos de la serie que SE PUEDEN usar, partidos donde hay huecos.

    `aceptar` es el nivel de exigencia:
      · ACEPTA_LINEA (default) — lo que ENTRA a la serie dibujada: base de mercado
        MÁS las fotos intradía. ⚠️ NO es lo mismo que base de mercado: los puntos
        intradía vienen con `apto=False` y no pueden ser pico ni denominador. Un
        consumidor que asuma "lo que me devolvieron ya es base de mercado" se
        equivoca — para eso está el flag por punto.
      · BASE_MERCADO + (INDETERMINADO,) — afloja para no borrarle la línea a los
        usuarios cuyas filas son anteriores a la columna `source`. Esas filas
        entran marcadas con `apto=False`: pueden sostener UNA LÍNEA, nunca ser un
        pico ni un denominador. La regla se aplica en `curva_indexada`, no queda
        librada al criterio del que consuma esto.

    LOS HUECOS NO SE RELLENAN. Un hueco visible es información; uno interpolado es
    exactamente el mismo crimen que el snapshot sintético — un número que el
    sistema inventó y que el usuario lee como si lo hubiera vivido.

    Devuelve también `contable`: lo que quedó AFUERA. No se tira, porque el
    usuario importó esa historia y tiene derecho a verla — pero va por separado,
    para dibujarse como banda y nunca como continuación de la línea medida.
    """
    q = [f"""SELECT date, total_value, total_invested, net_deposited,
                    fx_to_usd_blue, holdings_json, source, mtm_coverage,
                    {_sel_estampo(conn)}
               FROM snapshots WHERE user_id=? AND total_value > 0"""]
    args = [uid]
    if desde:
        q.append("AND date >= ?"); args.append(desde)
    if hasta:
        q.append("AND date <= ?"); args.append(hasta)
    q.append("ORDER BY date")
    filas = conn.execute(" ".join(q), args).fetchall()

    primera_pos = primera_fecha_con_posiciones(conn, uid)
    # Por SERIE, no fila por fila: la cadencia diaria es lo único que distingue una
    # foto vieja del cron de una del browser, y eso no se ve en una fila sola.
    # En ESTIMADO entra también la cadena contable — A LA LÍNEA, con apto=False.
    # Forzarla a apta hacía que una fila fabricada por el import fijara el pico: una
    # cartera PLANA en 100.000 todo junio publicaba −44,44% desde un máximo que
    # puso el sistema. Y quedaba la inversión absurda de que la foto INTRADIA
    # —posiciones × precio, un valor de mercado real— no midiera y la fabricada al
    # costo sí.
    if modo == MODO_ESTIMADO:
        aceptar = tuple(set(aceptar) | {SINTETICO_COSTO, INDETERMINADO})
    clases = clasificar_serie(filas, primera_pos)
    # ⚠️ LA BASE SALE DEL ESTAMPO DE LA FILA, no de un cálculo sobre esta ventana.
    # Es lo que hace que `?days=30` y `?days=3650` respondan lo mismo sobre la misma
    # fila, y que un mes nuevo no re-etiquete los viejos.
    bases = bases_de_serie(filas, clases)
    aptos = aptos_de_serie(filas, clases, bases)
    _nd = _aportado_por_punto(conn, uid, filas)
    # ⚠️ LA CONTABILIDAD SE APAGA EN LA PRIMERA MEDICIÓN REAL (sólo estimado). Desde
    # que hay un cierre a mercado, la reconstrucción contable de esa misma fecha
    # es información estrictamente peor, y encadenarla en paralelo contaba el
    # mismo mes dos veces (medido: 12 usuarios con fotos contables fechadas
    # después de su primera medición; en la cuenta demo, la del 31/07 en medio de
    # las mediciones diarias de julio, que partía la línea en tres). Esas filas
    # siguen en la banda gris `contable`; no entran a la línea ni al número.
    _primer_apto = next((str(r["date"])[:10] for r, a in zip(filas, aptos) if a), None)
    contable_superado = 0
    puntos, contable, conteo = [], [], {c: 0 for c in CLASES}
    for r, c, _base, _apto in zip(filas, clases, bases, aptos):
        conteo[c] += 1
        d = str(r["date"])[:10]
        _cob = (float(r["mtm_coverage"])
                if r["mtm_coverage"] is not None else None)
        _superada = (modo == MODO_ESTIMADO and _base == VALUADO_AL_COSTO
                     and _primer_apto is not None and d >= _primer_apto)
        if _superada:
            contable_superado += 1
        if c in aceptar and not _superada:
            # TODO ENTRA A LA LÍNEA — el usuario ve su curva. Lo que se decide acá
            # es OTRA cosa: quién puede ser pico y denominador. Mismo contrato que
            # INTRADIA, que entra pero no mide.
            # ⚠️ `value` SÓLO EN LOS QUE MIDEN. En los demás el número viaja bajo
            # `value_no_medible`, y no es cosmética: `p["value"]` sobre un punto al
            # costo levanta KeyError, así que el uso inseguro NO SE PUEDE ESCRIBIR
            # por descuido. Nueve rondas arreglaron lector por lector porque el
            # dato dejaba, y `apto`/`base` eran campos ignorables.
            _val = float(r["total_value"])
            puntos.append({
                "date": d,
                ("value" if _apto else "value_no_medible"): _val,
                "net_deposited": _nd(r),
                "clase": c, "apto": _apto, "cobertura": _cob,
                # Con qué regla se valuó. `curva_indexada` NO encadena un segmento
                # que cruce un cambio de base: no sería un movimiento de la
                # cartera, sería el escalón entre dos formas de medir.
                "base": _base,
                "al_costo": _instrumentos_al_costo(r),
            })
        # ⚠️ La banda gris NO se vacía cuando esas filas entran a la línea. Es la
        # separación visual que existe para que nadie saque un pico de ahí; perderla
        # justo cuando sus filas se meten en la serie es lo peor de los dos mundos.
        #
        # ⚠️ Y LA BANDA ES POR BASE, NO POR CLASE. Con `c not in BASE_MERCADO` la
        # banda decía dos cosas falsas a la vez, en las dos direcciones:
        #   · la reconstrucción con cobertura 0,05 NO entraba —su clase es
        #     RECONSTRUIDO— y el usuario del caso 452 abría el panel de la banda y
        #     lo encontraba VACÍO, con sus 4 fotos dibujadas en la línea medida
        #     como una caída del 47%;
        #   · la foto INTRADIA SÍ entraba, y es posiciones × precio real: mezclarla
        #     con la cadena contable hace que la propia banda una dos bases.
        if _base == VALUADO_AL_COSTO:
            # ⚠️ `value_no_medible`, NO `value` — misma disciplina que los puntos.
            # La banda seguía exponiendo el número crudo bajo `value`, así que un
            # `.get("value")` devolvía el valor contable sin romper nada: el error
            # quedaba perfectamente escribible justo en la colección que existe
            # PARA lo que no mide.
            contable.append({"date": d, "value_no_medible": float(r["total_value"]),
                             "clase": c, "base": _base})

    # Partir donde el silencio es demasiado largo — y donde el flujo DESBORDA el
    # denominador.
    #
    # ⚠️ EL CERO ABSORBENTE. `dietz` tiene piso en −1,0 (twr.py: "no se puede
    # perder más que todo"), y cuando lo toca, `idx *= (1.0 + ret)` deja el índice
    # en CERO — y el cero no se recupera con ninguna multiplicación posterior.
    # Alguien con US$5.000 que deposita US$20.000 y después gana 21,55% real
    # publicaba −100% PARA SIEMPRE. Pero un flujo de 2× la cartera no significa que
    # el usuario perdió todo: significa que el denominador de Modified Dietz no da
    # para medir ese tramo. Eso no es una pérdida, es una medición imposible — y lo
    # que corresponde con una medición imposible ya está resuelto acá: cortar,
    # igual que con un hueco.
    # ⚠️ EL HUECO SE MIDE ENTRE PUNTOS APTOS, que es por donde corre la cadena.
    # Midiéndolo entre puntos consecutivos cualesquiera, un punto NO-APTO —una foto
    # intradía, o una reconstrucción mayormente al costo— hacía de puente y evitaba
    # el corte: la serie quedaba entera y el índice se encadenaba por encima de un
    # silencio de dos meses.
    # ⚠️ EL SILENCIO SE MIDE SIEMPRE CONTRA EL PUNTO ANTERIOR, mida o no.
    #
    # Las dos ramas exigían `ultimo_apto is not None`, y `ultimo_apto` arranca en
    # None y se resetea en cada corte. Resultado: todo hueco ANTERIOR al primer
    # punto apto de un tramo quedaba sin medir. Con una sola foto de browser el 5
    # de enero y el cron desde el 1 de agosto, los cinco meses de silencio
    # desaparecían y la serie quedaba entera. Un silencio es un silencio aunque el
    # punto que lo abre no sirva para medir.
    #
    # El desborde del denominador sí se mide entre puntos APTOS, que es por donde
    # corre la cadena.
    # ⚠️ Y DONDE UN LEG NO ES CREÍBLE (`leg_dudoso`): el desborde de antes, más el
    # salto sin flujo que lo explique. Se mide por donde corre cada cadena que
    # PUBLICA un número: apto→apto (el certero) y, en ESTIMADO, contable→contable
    # (la cadena del `idx_est`, que encadena las filas al costo entre sí). La cadena
    # de DIBUJO no corta el tramo: parte el segmento, en `curva_indexada`.
    tramos, actual, ultimo_apto = [], [], None
    ultimo_costo = None            # última fila CONTABLE del tramo (cadena del estimado)
    cortes_dudosos = []
    for p in puntos:
        corta = False
        motivo_corte = None
        # Entre dos saldos contables el tope es el contable (ver
        # MAX_HUECO_CONTABLE_DIAS); en cualquier otro par —mercado→mercado, o el
        # traspaso contable→mercado, donde no se puede medir el medio— rige el de
        # mercado.
        _tope = (MAX_HUECO_CONTABLE_DIAS
                 if (actual and actual[-1]["base"] == VALUADO_AL_COSTO
                     and p["base"] == VALUADO_AL_COSTO)
                 else max_hueco_dias)
        if actual and _dias(actual[-1]["date"], p["date"]) > _tope:
            corta = True
        elif actual and p["apto"] and ultimo_apto is not None:
            if _dias(ultimo_apto["date"], p["date"]) > max_hueco_dias:
                corta = True
            else:
                _flow = p["net_deposited"] - ultimo_apto["net_deposited"]
                motivo_corte = leg_dudoso(ultimo_apto["value"], valor_para_dibujar(p), _flow)
                if motivo_corte:
                    corta = True
                    cortes_dudosos.append({
                        "desde": ultimo_apto["date"], "hasta": p["date"], "motivo": motivo_corte,
                        "v0": ultimo_apto["value"], "v1": valor_para_dibujar(p),
                        "flujo": _flow, "cadena": "mercado"})
        elif (actual and modo == MODO_ESTIMADO and p["base"] == VALUADO_AL_COSTO
              and ultimo_costo is not None):
            _flow = p["net_deposited"] - ultimo_costo["net_deposited"]
            motivo_corte = leg_dudoso(valor_para_dibujar(ultimo_costo),
                                      valor_para_dibujar(p), _flow)
            if motivo_corte:
                corta = True
                cortes_dudosos.append({
                    "desde": ultimo_costo["date"], "hasta": p["date"], "motivo": motivo_corte,
                    "v0": valor_para_dibujar(ultimo_costo), "v1": valor_para_dibujar(p),
                    "flujo": _flow, "cadena": "contable"})
        if corta:
            tramos.append(actual); actual = []; ultimo_apto = None; ultimo_costo = None
        actual.append(p)
        if p["apto"]:
            ultimo_apto = p
        if p["base"] == VALUADO_AL_COSTO:
            ultimo_costo = p
    if actual:
        tramos.append(actual)

    aptos = [p for p in puntos if p["apto"]]
    total = len(filas)
    cobertura = (len(aptos) / total) if total else 0.0
    # Cobertura media de lo reconstruido: un tramo reconstruido al 71% pasa el
    # piso pero NO es lo mismo que una foto del cron, y el usuario tiene que
    # poder verlo en el tooltip.
    cobs = [p["cobertura"] for p in puntos
            if p["clase"] == RECONSTRUIDO and p["cobertura"] is not None]
    al_costo = sorted({a for p in puntos for a in (p.get("al_costo") or [])})

    return {
        # ⚠️ NO HAY `puntos`. Es el cambio de forma de la ronda 10, y es el punto
        # entero: mientras existiera UNA lista mezclada, se podía recorrer entera
        # sin decidir nada, y `apto`/`base` eran dos campos que se podían no mirar.
        # Nueve rondas encontraron un lector nuevo cada vez —Reportes, el informe
        # del asesor, /api/goals/cagr y los tres builders de IA seguían publicando
        # el −47,26% del caso 452 con la pantalla diciendo "—"— porque el arreglo
        # era siempre en el lector y nunca en el dato. Ahora hay que elegir:
        #   · `medibles`    — los que pueden medir. Traen `value`.
        #   · `no_medibles` — el resto. NO traen `value`: traen `value_no_medible`.
        # El que quiera el número crudo tiene que nombrarlo, y el que se olvide se
        # come un KeyError en vez de publicar un número inventado.
        "medibles": [q for q in puntos if q["apto"]],
        "no_medibles": [q for q in puntos if not q["apto"]],
        # La serie ORDENADA y partida, para DIBUJAR. Es anidada a propósito: no se
        # puede recorrer de corrido sin haber decidido antes qué hacer con cada
        # tramo, y sus puntos respetan la misma regla de `value`.
        "tramos": tramos,
        "contable": contable,
        "por_clase": conteo,
        "cobertura": round(cobertura, 4),
        "cobertura_reconstruccion": (round(sum(cobs) / len(cobs), 4) if cobs else None),
        # Qué instrumentos quedaron al costo, por nombre. Un porcentaje pelado no
        # le dice al usuario qué hacer; "tus FCI" sí.
        "instrumentos_al_costo": al_costo,
        "modo": modo,
        # Los legs que NO se encadenaron por no ser creíbles (`leg_dudoso`). Cada
        # uno parte la serie en dos tramos; la cola de revisión del admin los lee.
        "cortes_dudosos": cortes_dudosos,
        # Filas contables fechadas en o después de la primera medición real, que
        # en estimado quedan fuera de la línea (siguen en `contable`).
        "contable_superado": contable_superado,
        "medido_desde": (aptos[0]["date"] if aptos else None),
        "medido_hasta": (aptos[-1]["date"] if aptos else None),
        "motivo": _motivo(conteo, len(aptos)),
        "motivo_texto": MOTIVO_TEXTO.get(_motivo(conteo, len(aptos))),
    }


def curva_indexada(conn, uid: int, desde: str = None, hasta: str = None, *,
                   modo: str = MODO_CERTERO,
                   aceptar: tuple = ACEPTA_LINEA,
                   max_hueco_dias: int = MAX_HUECO_DIAS,
                   valor_live: float = None) -> dict:
    """La curva indexada + drawdown + CAGR, encadenando `dietz` sobre `serie_medible`.

    SIN CLAMPS ASIMÉTRICOS. El techo de +50% por mes que aplica el lado retail
    (`Insights.jsx:683`, `evolution.js:317`) trunca meses reales y —el punto— NO se
    le aplica al benchmark, así que el sesgo va sistemáticamente en contra del
    usuario y se compone mes a mes. Sólo queda el piso de −100% de `dietz`: no se
    puede perder más que todo.

    LAS DOS REGLAS QUE NO SE NEGOCIAN:
      · un punto no-apto (INDETERMINADO) nunca es DENOMINADOR: si el arranque de
        un tramo no es base de mercado, ese tramo no produce retorno.
      · un punto no-apto nunca es PICO: el drawdown se mide contra máximos que de
        verdad se alcanzaron, no contra un valor que el sistema no puede afirmar.
        Es exactamente el defecto que reportó el usuario ("yo nunca llegué tan
        arriba"): el pico lo había puesto el sistema.
    """
    s = serie_medible(conn, uid, desde, hasta, modo=modo, aceptar=aceptar,
                      max_hueco_dias=max_hueco_dias)
    if not s["tramos"]:
        # La forma de la respuesta NO cambia cuando no hay datos: si faltaran
        # claves, cada consumidor tendría que adivinar — y el estado vacío es
        # justamente el que más se lee mal.
        # ⚠️ TODAS las claves, también las nuevas. Ya pasó una vez con
        # `drawdown_maximo_fecha`: un consumidor que gatea por `serie_partida` o
        # `tramos_medidos` recibía undefined y no gateaba nada. El estado vacío es
        # justamente el que más se lee mal, así que la forma no puede cambiar.
        return {**s, "curva": [], "twr": None, "cagr": None,
                "drawdown_actual": None, "drawdown_maximo": None,
                "drawdown_maximo_fecha": None, "drawdown_maximo_pico": None,
                "tramos_medidos": 0, "tramos_detalle": [], "serie_partida": False,
                "ventana_desde": None, "ventana_hasta": None,
                # FASE 2 · y éstas también, por el mismo motivo que dice el
                # comentario de arriba: `base_del_twr` es lo que un lector nuevo usa
                # para saber si el número que tiene enfrente sirve para pico o
                # drawdown. Faltando en el estado vacío llega `undefined`, y un
                # gate por `!== 'contable'` deja pasar exactamente lo que vino a
                # frenar. Es el mismo defecto que `drawdown_maximo_fecha` ya causó.
                "base_del_twr": ("contable" if modo == MODO_ESTIMADO else "mercado"),
                "excluye_no_realizado": (modo == MODO_ESTIMADO)}

    # ⚠️ EL ÍNDICE Y EL PICO SE REINICIAN EN CADA TRAMO.
    #
    # `serie_medible` parte la serie donde hubo más de `max_hueco_dias` de
    # silencio, y ese corte existe porque NO SE SABE qué pasó adentro del hueco.
    # Si el índice se arrastrara de un tramo al siguiente, el derrumbe que ocurrió
    # dentro del hueco desaparece y el tramo 2 compone encima del tramo 1.
    # Medido: 10.000 → 12.000 · [hueco con caída a 6.000] · 6.000 → 6.600
    # devolvía +32% cuando punta a punta es −34%. Y no es un caso de laboratorio:
    # el backfill escribe un punto por mes, así que basta con que UN mes caiga
    # bajo el piso de cobertura para que el hueco pase de 30 a ~60 días y parta
    # la cadena — cruzar el umbral recableaba la curva entera en silencio.
    # ⚠️ ACÁ HUBO UN FILTRO QUE DEJABA UNA SOLA BASE EN LA CURVA, Y BORRABA HISTORIA.
    #
    # La intención era buena: dos bases en el mismo eje, cada una rebaseada en 1,0,
    # hacen que una cadena contable terminada en −40% y una primera medición
    # dibujada en 0% se lean como una recuperación que nadie vivió. Pero el filtro
    # cobraba un precio mucho peor: con cobertura 0,61 —la mediana real del padrón—
    # los 12 meses reconstruidos DESAPARECÍAN del gráfico en cuanto el usuario
    # tuviera además una foto del cron, incluso en el modo que el botón llama
    # "Historia completa". Eso es exactamente lo que la ronda 7 vino a ganar.
    #
    # Los dos problemas son reales, pero se resuelven en lugares distintos: la
    # historia se DIBUJA (acá), y lo que impide leer el salto es que las dos series
    # no se toquen —cada base tiene su propia cadena, su propio id de `segmento`, y
    # el frontend corta entre segmentos y NO puentea a través de un cambio de base
    # (`partirMedidoYEstimado`, insightsModel.js)—. Esconder puntos nunca fue la
    # respuesta: es la ronda 7 al revés.
    curva = []
    tramos_info = []       # {desde, hasta, twr, dd_max, dd_actual, legs} por tramo
    idx_ultimo_tramo = 1.0
    # El SEGMENTO DIBUJADO. Es más fino que el tramo: un tramo se parte también
    # donde cambia la BASE, porque ahí la línea no puede seguir de largo. Viaja por
    # punto para que el frontend corte donde el índice se reinicia — sin eso el
    # corte existe en el número y no en el dibujo, que es el bug de esta ronda.
    segmento = -1

    for tramo in s["tramos"]:
        # Los ids de segmento se asignan por BASE, más abajo. No hace falta abrir
        # uno acá: `seg_por_base` arranca vacío en cada tramo, así que un tramo
        # nuevo ya fuerza ids nuevos.
        idx = 1.0
        legs_t = 0
        dd_actual_t = None
        pico = None
        pico_fecha = None
        dd_max_t, dd_max_fecha_t, dd_max_pico_t = 0.0, None, None
        ancla = None       # último punto APTO: el único que puede ser denominador
        # ⚠️ EL ANCLA DEL DIBUJO ES POR BASE, NO "EL PUNTO ANTERIOR".
        #
        # Regresión de la ronda 9, y contradecía su propia regla: si un segmento
        # vale cuando sus DOS extremos comparten la regla, entonces dos puntos a
        # mercado separados por uno al costo SÍ forman un segmento válido —el del
        # medio no es parte de él, es de otra serie—. Con `ancla_dib` = el anterior,
        # ese punto al costo reseteaba el índice y BORRABA del gráfico el
        # rendimiento ya medido: medido, una cartera que iba +5% volvía a 0,0000 en
        # el punto siguiente. La cadena de dibujo saltea lo de otra base, igual que
        # `idx` saltea lo no-apto.
        ancla_por_base = {}   # base -> último punto DE ESA BASE
        idx_por_base = {}     # base -> índice dibujado DE ESA BASE
        seg_por_base = {}     # base -> id del segmento dibujado
        ultimo_idx_dib = 1.0  # el último índice dibujado del tramo, de cualquier base
        idx_dib_ultimo_apto = 1.0   # el índice dibujado en el último punto APTO del tramo
        # ── FASE 2 · la cadena del modo ESTIMADO ────────────────────────────
        # ⚠️ ES UN TERCER ÍNDICE, Y HAY QUE SABER POR QUÉ NO ALCANZABA CON LOS DOS.
        #   `idx`     — el número del modo CERTERO: sólo apto→apto.
        #   `idx_dib` — la FORMA: encadena todo, incluida la intradía.
        #   `idx_est` — el número del modo ESTIMADO: apto MÁS la cadena contable,
        #               y NADA más.
        #
        # No es `idx_dib`: ése encadena también la foto INTRADIA, que es media
        # rueda. Cuatro cierres planos en 10.000 con una foto del browser de 15.000
        # en el medio devolvían +50% (ronda 9). Un número publicado no puede
        # depender de a qué hora el usuario abrió la app.
        #
        # No es `idx`: ése exige `apto`, o sea base de mercado, y por eso el modo
        # ESTIMADO no cambiaba NINGÚN número — medido sobre los 822 de producción:
        # 598 usuarios veían más LÍNEA y 0 veían un `medible` nuevo.
        #
        # ⚠️ Y ENCADENA POR BASE, IGUAL QUE EL DIBUJO. Es lo único que impide que
        # esto reabra la Fase 1: `dietz(v0, v1, flujo)` RESTA dos valuaciones, y si
        # v0 sale de la cadena contable y v1 de una medición, esa resta es el
        # escalón entre dos reglas — el −65,82% del caso 452, exactamente. Con el
        # ancla por base, la cadena contable se encadena contra sí misma y la de
        # mercado contra sí misma; lo que las une es el PRODUCTO de dos retornos,
        # que es otra cosa: cada tramo se midió entero bajo su propia regla.
        ancla_est = {}        # base -> último punto que puede encadenar en ESTIMADO
        idx_est = 1.0
        legs_est = 0
        for i, p in enumerate(tramo):
            # ⚠️ UN PUNTO NO-APTO NO TOCA EL ÍNDICE, NI COMO v0 NI COMO v1.
            #
            # Antes sólo se le negaba ser DENOMINADOR (v0). Pero la pata que ENTRABA
            # a la foto intradía sí se encadenaba, y eso mueve el índice para
            # siempre: cuatro cierres planos en 10.000 con una foto del browser de
            # 15.000 en el medio devolvían twr=+50%. Y con flujos el encadenado
            # dejaba de telescopiar — el mismo mes plano daba +3,45% o −3,41% según
            # de qué lado de la foto cayera el depósito.
            #
            # La cadena avanza de punto APTO a punto APTO, salteando lo que no lo
            # es. El no-apto se dibuja (sostiene la línea, que es para lo que entró)
            # arrastrando el índice vigente, sin retorno propio.
            _arranque_medible = False
            if not p["apto"]:
                ret = None
            elif ancla is None:
                ret = None                       # arranque medible del tramo
                _arranque_medible = True
            else:
                flow = p["net_deposited"] - ancla["net_deposited"]
                ret = dietz(ancla["value"], p["value"], flow)
            # ⚠️ DOS ÍNDICES, PORQUE SON DOS PREGUNTAS.
            #   `idx_dib` — la FORMA de la historia: encadena TODOS los puntos, así
            #     el usuario ve su curva aunque ninguno sirva para medir. Sin esto,
            #     un usuario con la cartera al 55% al costo veía una recta en 0,0%
            #     — que es peor que no ver nada, porque se lee tranquilizador.
            #   `idx`     — el número PUBLICADO: avanza sólo de apto a apto, y es el
            #     único que alimenta pico, drawdown, TWR y CAGR.
            # El chip declara desde cuándo está medido y con qué cobertura, así que
            # la línea puede mostrar más historia que la que el número cubre.
            # Un punto no-apto que arrastra el índice vigente sale dibujado en el
            # mismo % que el anterior: la línea queda plana justo donde el usuario
            # necesita ver su historia, y un 0,0% que no midió nada se lee
            # tranquilizador. Se le calcula una posición desde el último punto
            # medido —su valor es real, sólo que no confiable para fijar un
            # máximo— y `idx` NO se toca: el índice publicado sigue avanzando
            # únicamente de punto apto a punto apto.
            #
            # ⚠️ EL SEGMENTO ES LA UNIDAD, NO EL PUNTO. La cadena de dibujo
            # encadenaba TODOS los puntos del tramo, incluidos los que cruzan un
            # CAMBIO DE BASE — y ese segmento no dibuja un movimiento de la cartera,
            # dibuja el escalón entre dos formas de medir. Es el caso 452 reimpreso
            # en el gráfico: 4 fotos al costo en 139.571 y una medición a mercado en
            # 73.604 daban una línea continua de −47,26% mientras el header decía
            # "—", porque `dietz` y `serie_medible` sí respetaban la regla y el
            # dibujo no.
            #
            # Un segmento vale cuando sus dos extremos están valuados con la MISMA
            # regla. Cada base lleva su propia cadena y su propio id de segmento;
            # lo de otra base no la corta, la saltea.
            _b = p["base"]
            if _b not in seg_por_base:
                if modo == MODO_ESTIMADO and seg_por_base:
                    # ⚠️ EN ESTIMADO EL CAMBIO DE REGLA NO CORTA LA LÍNEA: LA ENCADENA.
                    # El crimen de la Fase 1 era RESTAR dos valuaciones de reglas
                    # distintas (139.571 al costo contra 73.604 a mercado = −47 %).
                    # Acá no se resta nada: la cadena nueva arranca donde quedó el
                    # índice de la anterior y multiplica sólo sus propios legs — el
                    # mismo producto que `idx_est` ya publica como `twr`. Con el
                    # reinicio a 1,0 el gráfico mostraba la contabilidad terminando
                    # en +16 % y la medición arrancando en 0 % con un hueco entre
                    # las dos, y el número del chip no aparecía en ningún lado.
                    seg_por_base[_b] = segmento
                    idx_por_base[_b] = ultimo_idx_dib
                else:
                    segmento += 1
                    seg_por_base[_b] = segmento
                    idx_por_base[_b] = 1.0
            else:
                _prev = ancla_por_base[_b]
                _flow_dib = p["net_deposited"] - _prev["net_deposited"]
                # ⚠️ LA LÍNEA TAMBIÉN TIENE COTA DE CORDURA. Un leg que no es creíble
                # entre dos puntos de la misma base (típicamente una foto intradía
                # rota: uid 745, US$3.329 → US$22.746 en un día sin flujo) no se
                # dibuja como movimiento: abre un segmento nuevo y la línea se corta
                # ahí. El NÚMERO no se toca — los legs que publican ya se cortaron
                # en `serie_medible`; éste es sólo el dibujo, y era por acá que el
                # KPI leía +642,9% donde el twr decía +6,6%.
                if leg_dudoso(valor_para_dibujar(_prev), valor_para_dibujar(p), _flow_dib):
                    segmento += 1
                    seg_por_base[_b] = segmento
                    idx_por_base[_b] = 1.0
                else:
                    _rp = dietz(valor_para_dibujar(_prev), valor_para_dibujar(p), _flow_dib)
                    if _rp is not None:
                        idx_por_base[_b] *= (1.0 + _rp)
            # FASE 2 · la cadena del ESTIMADO. Entra el punto APTO (cierre a
            # mercado) y el punto de la cadena CONTABLE. NO entra la intradía ni el
            # INDETERMINADO: son los dos que no se pueden afirmar ni siquiera como
            # punta contable —la intradía es media rueda, el indeterminado no se
            # sabe qué es—, y meterlos sería cambiar "aproximado" por "cualquiera".
            if modo == MODO_ESTIMADO and (p["apto"] or _b == VALUADO_AL_COSTO):
                _prev_est = ancla_est.get(_b)
                if _prev_est is not None:
                    _re = dietz(valor_para_dibujar(_prev_est), valor_para_dibujar(p),
                                p["net_deposited"] - _prev_est["net_deposited"])
                    if _re is not None:
                        idx_est *= (1.0 + _re)
                        legs_est += 1
                ancla_est[_b] = p
            ancla_por_base[_b] = p
            idx_dib = idx_por_base[_b]
            if p["apto"]:
                ancla = p
            if ret is not None:
                idx *= (1.0 + ret)
                legs_t += 1
            idx_dibujo = idx_dib
            ultimo_idx_dib = idx_dib
            if p["apto"]:
                idx_dib_ultimo_apto = idx_dib
            punto = {"date": p["date"], "index": round(idx_dibujo, 6),
                     # ⚠️ EL ÍNDICE PUBLICADO, POR PUNTO. `index` es la FORMA (encadena
                     # todo, incluida la intradía); `idx` es el número que este módulo
                     # afirma (apto→apto). El KPI "Acumulado" leía `index` y publicaba
                     # +642,9% donde `twr` decía +6,6% (uid 745). Con esto el lector
                     # puede rebasear entre dos puntos aptos SIN pasar por el dibujo.
                     # En ESTIMADO la cadena que publica es `idx_est` (contable +
                     # apto, por producto); el KPI tiene que leer ESA, no la del
                     # certero, para decir lo mismo que el chip.
                     "index_publicado": round(idx_est if modo == MODO_ESTIMADO else idx, 6),
                     # Misma disciplina que en `serie_medible`: el número crudo de
                     # un punto que no mide no se llama `value`.
                     ("value" if p["apto"] else "value_no_medible"):
                         valor_para_dibujar(p),
                     "clase": p["clase"],
                     "apto": p["apto"], "ret": ret,
                     # A qué TRAMO pertenece. Sin esto el punto sale con el índice
                     # reiniciado a 1,0 y sin ninguna marca, y el chart lo dibuja
                     # como continuación: la línea "se recupera" a breakeven
                     # mientras la cartera iba de 8.000 a 6.000. El hueco lo
                     # rellenaba el reinicio del índice en vez de una interpolación,
                     # que es el mismo crimen con otra cara.
                     "tramo": len(tramos_info),
                     "arranque_tramo": i == 0,
                     # Con qué regla está valuado, y a qué SEGMENTO DIBUJADO
                     # pertenece. El segmento se corta donde cambia la base: sin
                     # esto el frontend une dos reglas con una recta.
                     "base": p["base"],
                     "segmento": seg_por_base[p["base"]],
                     # `estimado`: el SEGMENTO que llega a este punto no se midió.
                     # ⚠️ ES DEL SEGMENTO, NO DEL PUNTO. Con `ret is None and i > 0`
                     # la medición REAL del cron salía marcada estimada sólo porque
                     # era el primer punto apto del tramo y el tramo anterior no
                     # medía: que el tramo no se pueda medir no convierte la foto en
                     # estimada. Un arranque medible es una medición, no una
                     # estimación; lo que sí queda marcado es el punto no-apto y el
                     # apto cuyo segmento de entrada no se pudo medir.
                     "estimado": ((not p["apto"])
                                  or (ret is None and not _arranque_medible))}
            if p["apto"]:
                # Sólo los aptos mueven el pico, y con el índice REAL.
                if pico is None or idx > pico:
                    pico, pico_fecha = idx, p["date"]
                dd = (idx / pico) - 1.0 if pico and pico > 0 else 0.0
                dd_actual_t = dd
                if dd < dd_max_t:
                    dd_max_t, dd_max_fecha_t, dd_max_pico_t = dd, p["date"], pico_fecha
                punto["drawdown"] = round(dd, 6)
            curva.append(punto)
        # ⚠️ `desde`/`hasta` son del primer y último punto APTO del tramo, no del
        # primero y último que HAY. `ventana_desde` es el dato con el que
        # `reporting/builder.py` decide si el % anual cubre el período: tomándolo
        # de un punto no-apto, decía que la medición arrancaba meses antes de
        # donde de verdad arranca.
        _aptos_t = [q for q in tramo if q["apto"]]
        tramos_info.append({
            "desde": (_aptos_t[0]["date"] if _aptos_t else tramo[0]["date"]),
            "hasta": (_aptos_t[-1]["date"] if _aptos_t else tramo[-1]["date"]),
            "legs": legs_t, "twr": (idx - 1.0) if legs_t > 0 else None,
            # FASE 2 · el mismo tramo medido con la regla del ESTIMADO. Va aparte y
            # no pisa a `twr`: el que quiera el número contable tiene que nombrarlo.
            "legs_est": legs_est,
            "twr_est": (idx_est - 1.0) if legs_est > 0 else None,
            # La ventana que el número del ESTIMADO cubre: arranca en el primer
            # punto que ENCADENA, que no es el primer apto.
            "desde_est": (tramo[0]["date"] if tramo else None),
            "drawdown_maximo": round(dd_max_t, 6) if legs_t > 0 else None,
            # ⚠️ POR TRAMO, no "el último que vi". `dd_actual` era una sola
            # variable que se pisaba en cada punto apto de CUALQUIER tramo: con un
            # punto suelto al final (hueco > max_hueco_dias), el último valor
            # escrito era el de ese punto — cuyo índice arranca en 1,0 — y el
            # drawdown daba 0,0% con el usuario 36% abajo de su pico. Misma
            # familia que el bug que este trabajo vino a cerrar, introducida por
            # el fix de la serie partida.
            "drawdown_actual": round(dd_actual_t, 6) if (legs_t > 0 and dd_actual_t is not None) else None,
            "drawdown_maximo_fecha": dd_max_fecha_t,
            "drawdown_maximo_pico": dd_max_pico_t,
        })
        idx_ultimo_tramo = idx

    # Sólo se puede publicar UN número punta a punta si toda la medición cabe en
    # UN tramo continuo. Con la serie partida, ni el TWR ni el drawdown máximo son
    # afirmables: el peor momento puede haber estado adentro del hueco, y publicar
    # el máximo de los tramos medidos sería dar una COTA INFERIOR con nombre de
    # máximo — subestimar el riesgo con autoridad.
    con_legs = [t for t in tramos_info if t["legs"] > 0]
    legs = sum(t["legs"] for t in tramos_info)
    # ⚠️ CUALQUIER hueco parte la serie, tenga o no legs el otro lado.
    # Contar sólo los tramos CON legs dejaba invisible al tramo huérfano de UN
    # punto: `partida` quedaba False, `motivo` None, y con eso el cierre live
    # componía por encima del hueco (devolvía +32% donde punta a punta era −34%)
    # y `medido_hasta` se estiraba hasta el otro lado, con lo cual el guard del
    # año daba por cubierto un período que sólo se midió dos meses.
    partida = len(s["tramos"]) > 1
    publicable = (len(con_legs) == 1 and not partida)
    # La ventana que el número REALMENTE cubre. `medido_desde`/`medido_hasta` de
    # `serie_medible` describen TODOS los puntos aptos; el TWR sólo cubre el tramo
    # publicado. Quien tenga que probar cobertura (reporting/builder.py) debe
    # mirar esto, no aquéllos.
    _tp = con_legs[0] if publicable else None
    ventana_desde = _tp["desde"] if _tp else None
    ventana_hasta = _tp["hasta"] if _tp else None

    if publicable:
        _t = con_legs[0]
        idx = 1.0 + _t["twr"]
        pico = max(1.0, idx)
        dd_max = _t["drawdown_maximo"]
        dd_max_fecha = _t["drawdown_maximo_fecha"]
        dd_max_pico_fecha = _t["drawdown_maximo_pico"]
        dd_actual = _t["drawdown_actual"]
        # `pico` sólo se usa de acá en adelante para el cierre live. El HWM del
        # tramo es el índice más alto que alcanzó; se recalcula desde la curva
        # para no depender de en qué punto quedó `idx`.
        _idxs = [c["index"] for c in curva if c.get("apto")]
        pico = max(_idxs) if _idxs else 1.0
        pico_fecha = next((c["date"] for c in curva
                           if c.get("apto") and c["index"] == pico), None)
    else:
        # ⚠️ Sin ningún tramo medido (o con la serie partida) el índice se quedó
        # en 1.0 — y devolver eso como `twr: 0.0` / `drawdown: 0.0` es publicar
        # "el período fue plano" sin haber medido nada. `drawdown_maximo` es el
        # que faltaba: `twr` y `drawdown_actual` ya tenían su guard y éste no,
        # así que el 452 iba a leer "peak histórico 0,0%" en el mismo lugar donde
        # leía −45%, y con `drawdown_maximo_fecha` en None: se contradecía solo.
        idx, pico, pico_fecha = 1.0, None, None
        dd_actual = dd_max = dd_max_fecha = dd_max_pico_fecha = None

    # El valor live cierra la curva SOLO si la serie es UN tramo continuo y su
    # último punto es base de mercado. Antes `ultimo_apto` se buscaba sobre
    # la serie ENTERA: con un punto huérfano del otro lado del hueco, la pata
    # live se componía encima del índice del tramo 1 y el hueco desaparecía.
    ultimo_apto = None
    # FASE 2 · la pata live, si se aplica, tiene que cerrar TAMBIÉN la cadena del
    # estimado. Se inicializa acá para que el bloque de más abajo no dependa de que
    # el `if` de la pata live haya entrado.
    _r_live_est = None
    # ⚠️ UNA FOTO INTRADÍA AL FINAL NO APAGA EL CIERRE LIVE. Antes se exigía que el
    # ÚLTIMO punto del tramo fuera apto; pero el Dashboard escribe una foto de
    # media rueda cada vez que se abre, así que durante el día TODO usuario activo
    # termina en una intradía y el "hoy" no se agregaba: el número se quedaba en
    # el cierre de anoche mientras la línea seguía hasta la foto de hoy (medido en
    # la demo: chip y KPI +14,9 % con la línea terminando en +5,5 %). La pata
    # live va del último punto APTO al valor de hoy, y la intradía del medio no
    # participa: es dibujo, no número.
    _tramo_hoy = s["tramos"][-1]
    _hoy_ok = publicable
    if modo == MODO_ESTIMADO and tramos_info and (tramos_info[-1].get("legs_est") or 0) > 0:
        _hoy_ok = True            # el estimado publica el último tramo con legs
    if _hoy_ok:
        ultimo_apto = next((p for p in reversed(_tramo_hoy) if p["apto"]), None)
    if (_hoy_ok and valor_live and valor_live > 0
            and ultimo_apto is not None and curva):
        # ⚠️ EL FLUJO NO ES CERO. Todo lo que entró o salió DESPUÉS del último
        # snapshot medido —el depósito de hoy, antes de que el cron nocturno
        # escriba la foto— se computaba entero como rendimiento: un usuario con el
        # mercado plano que depositaba US$20.000 leía "+20,00%" al lado de "US$0"
        # de P&L. Se pregunta a la SSoT canónica, la misma que usa `_flujo`.
        _flujo_live = 0.0
        try:
            from snapshots_job import compute_net_deposited_db
            _flujo_live = (compute_net_deposited_db(conn, uid)
                           - float(ultimo_apto["net_deposited"] or 0))
        except Exception:
            log.exception("flujo live uid=%s", uid)
            _flujo_live = 0.0
        r = dietz(ultimo_apto["value"], float(valor_live), _flujo_live)
        if r is not None:
            idx *= (1.0 + r)
            # FASE 2 · la pata live también cierra la cadena del ESTIMADO. Es la
            # MISMA pata —dos puntas a mercado— así que no mezcla nada; dejarla
            # afuera haría que el ESTIMADO ignore el último tramo de mercado y
            # publique un número más viejo que el del CERTERO, que es al revés de
            # lo que el modo promete.
            _r_live_est = r
            legs += 1
            if pico is None or idx > pico:
                pico, pico_fecha = idx, "hoy"
            dd_actual = (idx / pico) - 1.0 if pico and pico > 0 else 0.0
            if dd_max is None or dd_actual < dd_max:
                dd_max, dd_max_fecha, dd_max_pico_fecha = dd_actual, "hoy", pico_fecha
            # ⚠️ CON `base` Y `segmento`. Sin ellos el corte no lo puede frenar:
            # `cortarPorTramo` exige que las DOS puntas traigan el campo, así que un
            # punto sin `segmento` se pega a lo que venga antes. Hoy eso siempre es
            # un punto de mercado (el cierre live sólo corre si la serie es
            # publicable y su último punto es apto), pero que el invariante valga
            # por suerte y no por construcción es cómo empezaron las nueve rondas.
            # ⚠️ EN ESTIMADO EL "HOY" CONTINÚA LA LÍNEA. `idx` es la cadena del
            # certero (arranca en 1,0 en la primera medición); pegarle ese índice
            # al último punto de una línea que venía encadenada desde la
            # contabilidad dibujaba un escalón al final (medido en la demo:
            # 1,149 → 0,913 en un día con el mercado −8 %). El punto "hoy" es un
            # leg más de la cadena dibujada, y su publicado es el de `idx_est`.
            # `idx_dib_ultimo_apto`, no `curva[-1]["index"]`: si el último punto es
            # una intradía, su índice ya trae el leg apto→intradía y multiplicarlo
            # por (1+r) contaría la caída de hoy dos veces.
            _idx_hoy = (idx_dib_ultimo_apto * (1.0 + r)) if modo == MODO_ESTIMADO else idx
            _ip_hoy = (idx_est * (1.0 + r)) if modo == MODO_ESTIMADO else idx
            curva.append({"date": "hoy", "index": round(_idx_hoy, 6),
                          "index_publicado": round(_ip_hoy, 6),
                          "value": float(valor_live), "clase": MEDICION,
                          "apto": True, "ret": r, "estimado": False,
                          "base": VALUADO_A_MERCADO,
                          "segmento": curva[-1].get("segmento") if curva else 0,
                          "drawdown": round(dd_actual, 6)})

    # ═══════════════════════════════════════════════════════════════════════
    # FASE 2 · LO QUE EL MODO ESTIMADO PUBLICA — Y LO QUE NO
    #
    # La regla es una sola: ¿el número necesita el CAMINO de los precios, o le
    # alcanza con las PUNTAS?
    #   · Rendimiento acumulado y anualizado → le alcanzan las puntas. La
    #     contabilidad PUEDE afirmarlo: "aportaste 100.000 y figurás en 139.570"
    #     son sus dos puntas, y las dos son suyas.
    #   · Drawdown, pico, "tu mejor momento" → necesitan el camino. La cadena
    #     contable NO es un camino de precios: es un saldo mensual. Su máximo
    #     NUNCA FUE UN PRECIO — nadie le pagó eso nunca —, y publicar una caída
    #     contra él es, literalmente, el bug de las once rondas.
    #
    # Por eso acá el ESTIMADO gana `twr`/`cagr` y PIERDE drawdown y pico. Las dos
    # mitades van juntas: publicar el acumulado sin cortar el drawdown le da a los
    # 331 usuarios sin mediciones una curva contable de la que el motor de
    # drawdown saca un pico fabricado, y vuelve "Su ganancia cayó 167% desde el
    # mejor momento".
    # ⚠️ EL HUECO NO SE PUENTEA, PERO TAMPOCO PUEDE COSTARLE EL NÚMERO AL USUARIO.
    #
    # Primera versión de esto exigía UN solo tramo, igual que el CERTERO, y el
    # resultado fue exactamente al revés de lo que el modo promete: **232 usuarios
    # PERDÍAN** el número que el CERTERO sí les daba. El motivo es que la historia
    # extra ABRE un hueco que en CERTERO no existía — las filas del import llegan
    # hasta un fin de mes y el cron arranca semanas después, así que sumarlas parte
    # la serie en dos (medido: uid 2 → tramo contable de 3 legs y tramo de mercado
    # de 59, con 45+ días de silencio en el medio).
    #
    # Puentear ese hueco está descartado: no sabemos qué pasó adentro, y componer
    # por encima es inventar. Lo que se hace es publicar la ventana continua MÁS
    # RECIENTE —la que contiene lo último que el usuario vivió— y DECLARARLA en
    # `ventana_desde`/`ventana_hasta`, que es el mismo contrato que ya usa el
    # CERTERO. La serie sigue viajando con `serie_partida: True` para que la
    # pantalla pueda decir que hay historia antes del corte.
    #
    # Invariante que esto sostiene: **el ESTIMADO nunca publica para menos gente
    # que el CERTERO.** Si se rompe, el toggle le está sacando algo al usuario.
    est_con_legs = [t for t in tramos_info if (t.get("legs_est") or 0) > 0]
    est_con_legs = sorted(est_con_legs, key=lambda t: (t["hasta"] or ""))
    est_publicable = (modo == MODO_ESTIMADO and len(est_con_legs) >= 1)
    if modo == MODO_ESTIMADO:
        if est_publicable:
            est_con_legs = [est_con_legs[-1]]      # la ventana continua más reciente
            _idx_est = 1.0 + est_con_legs[0]["twr_est"]
            if _r_live_est is not None:
                _idx_est *= (1.0 + _r_live_est)
            idx = _idx_est
            legs = est_con_legs[0]["legs_est"] + (1 if _r_live_est is not None else 0)
            publicable = True
            ventana_desde = est_con_legs[0].get("desde_est") or ventana_desde
            ventana_hasta = est_con_legs[0]["hasta"]
            if curva and curva[-1]["date"] == "hoy":
                ventana_hasta = curva[-1]["date"]
        else:
            publicable = False
        # ⚠️ SIEMPRE, publique o no: el ESTIMADO no tiene camino de precios.
        dd_actual = dd_max = dd_max_fecha = dd_max_pico_fecha = None
        pico = pico_fecha = None

    # El CAGR se anualiza sobre la ventana QUE EL ÍNDICE MIDIÓ, no sobre las
    # fechas extremas de la curva. Tomándolas de `curva[0]`/`curva[-1]` —que
    # pueden ser tramos huérfanos— se publicaba −16,32% anual para una medición
    # de 28 días, esquivando el propio piso de medio año de dos líneas más abajo.
    cagr = None
    if publicable and legs > 0 and idx > 0 and ventana_desde:
        _c1 = ventana_hasta
        if curva and curva[-1]["date"] == "hoy":
            _c1 = _hoy_art()
        años = _dias(ventana_desde, _c1) / 365.25
        if años >= 0.5:                # bajo medio año, anualizar es propaganda
            cagr = idx ** (1.0 / años) - 1.0

    _motivo = s["motivo"]
    if not _motivo:
        if partida and s.get("cortes_dudosos"):
            _motivo = "medicion_dudosa"
        elif partida:
            _motivo = "serie_partida"
        elif legs == 0:
            _motivo = "sin_tramo_continuo"

    return {
        **s,
        "curva": curva,
        "twr": (idx - 1.0) if (publicable and legs > 0) else None,
        # ⚠️ CON QUÉ REGLA SE CALCULÓ EL NÚMERO DE ARRIBA. Es lo que le permite a
        # un lector nuevo gatear sin haber leído este archivo: `base_del_twr ==
        # 'contable'` significa "esto no es una medición de mercado, y no sirve
        # para pico, drawdown, volatilidad ni rachas".
        "base_del_twr": ("contable" if modo == MODO_ESTIMADO else "mercado"),
        # El sesgo declarado: la cadena contable fuerza `pnl_unrealized = 0`, así
        # que NO cuenta lo que todavía no vendiste. Una cartera que se duplicó sin
        # vender nada muestra ~0%. Subestima POR DISEÑO, y siempre para el mismo
        # lado — por eso viaja al frontend y no se queda en un comentario.
        "excluye_no_realizado": (modo == MODO_ESTIMADO),
        "tramos_medidos": legs,
        "tramos_detalle": tramos_info,
        "serie_partida": partida,
        # La ventana que el TWR publicado cubre de verdad (None si no se publica).
        "ventana_desde": ventana_desde,
        "ventana_hasta": ventana_hasta,
        "motivo": _motivo,
        "motivo_texto": (MOTIVO_TEXTO.get(_motivo) if _motivo else None),
        "drawdown_actual": (round(dd_actual, 6) if dd_actual is not None else None),
        "drawdown_maximo": (round(dd_max, 6) if dd_max is not None else None),
        "drawdown_maximo_fecha": dd_max_fecha,
        "drawdown_maximo_pico": dd_max_pico_fecha,
        "cagr": cagr,
    }
