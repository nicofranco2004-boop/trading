"""lectura_tecnica_chat — que el chat de Mervall-E entienda el análisis técnico.
═══════════════════════════════════════════════════════════════════════════
Pedido de Nico (30/10): «¿cómo viene GGAL?», «¿AAPL está en tendencia?» → que
Mervall-E conteste con la lectura técnica de ESE activo, «con el vocabulario
normal… apertura de mercado, cierre de mercado, fuerza, tendencia».

DE DÓNDE SALEN LOS NÚMEROS. De un solo lugar: `tecnico.para_la_ficha` (la misma
respuesta que dibuja la ficha) pasada a palabras por `resumen_tecnico_hechos`
(la misma función que arma el resumen de la ficha). El chat recibe esos hechos
con los indicadores nombrados por lo que significan («la fuerza del precio») y
no por su sigla (RSI). El modelo no calcula: cuenta lo que le pasa el servidor.
La serie es la de la ficha de entrada: en dólares (una acción argentina, su
precio de BYMA ÷ el MEP) salvo que la persona pida pesos o nombre un CEDEAR
(«AAPL.BA»), que es la ficha en pesos.

CÓMO HABLA. Las reglas viven en el pedido del chat (main._AI_CHAT_SYSTEM, «CÓMO
VIENE UN ACTIVO») y `problemas()` revisa la respuesta antes de que llegue: jerga
técnica, una certeza sobre lo que viene o un consejo de compra o venta → el chat
la pide de nuevo UNA vez (main._corregir_lectura_tecnica). La sigla que la
persona escribió en su pregunta («¿qué dice el RSI?») no cuenta como jerga: se
puede nombrar, siempre explicada.

Todo lo que se dice es POSIBILIDAD: un backtest de 2 años × 70 activos mostró
que los indicadores describen el pasado pero no anticipan mejor que el azar.
"""
from __future__ import annotations

import re

from ai import certezas_y_consejos

# Jerga del análisis técnico que la persona no tiene por qué saber. La lista
# del resumen de la ficha (resumen_tecnico._PROHIBIDAS) más las siglas: el
# resumen las nombra entre paréntesis (decisión del 23/10) y el chat no.
_JERGA = [
    r"rsi", r"adx", r"squeeze", r"bollinger", r"macd", r"fibonacci", r"elliott", r"estoc[áa]stico",
    r"[+−]di", r"dmi", r"ema", r"sma", r"medias? m[óo]vil(es)?", r"soportes?", r"resistencias?",
    r"sobrecompr\w*", r"sobrevend\w*", r"sobreventa", r"momentum",
    r"pullback", r"breakout", r"golden cross", r"death cross", r"cruce (dorado|de la muerte)",
    r"divergencias?", r"retrocesos?", r"consolidaci[óo]n", r"lateraliz\w*", r"velas? japonesas?",
    # Las del resumen que se colaron en la primera prueba real (30/10): «perdiendo
    # impulso» (NVIDIA), «rebotó» (MercadoLibre, Bitcoin), «el piso de junio».
    r"impulsos?", r"rebot\w*", r"pisos?", r"techos?", r"zonas?", r"tramos?",
    # Lo que Nico marcó en el resumen de GGAL (30/10): «la bajada todavía es firme,
    # pero se está cansando» → «la caída tiene fuerza aún, pero esa fuerza viene
    # bajando». «Alcista» y «bajista» NO van acá: son las palabras que él usa.
    r"firmes?", r"cansando",
]
# Los hechos traen fechas, nunca días de la semana: uno escrito por el modelo es
# inventado (MercadoLibre, 30/10: «cerró el miércoles» por el jueves 29).
# La corrección no se le cuenta a la persona: ella no pidió nada (SHIB, 30/10:
# «Tenés razón: puse un año que los datos no traen. Acá va corregida…»).
_META = [r"ten[ée]s raz[óo]n", r"corregid[ao]s?", r"corrijo", r"me equivoqu[ée]", r"perd[óo]n",
         r"disculp\w*", r"ac[áa] va (la )?(respuesta )?(de nuevo|otra vez)"]
_DIAS = [r"lunes", r"martes", r"mi[ée]rcoles", r"jueves", r"viernes", r"s[áa]bado", r"domingo"]
# Lo que viene dicho como seguro y los consejos de compra o venta (CNV: Rendi no
# asesora) viven en ai/certezas_y_consejos.py: la MISMA lista que revisa el
# resumen de la ficha (auditoría final B1+B2, 31/10: cada uno tenía la suya y
# las dos dejaban pasar «Conviene comprar» o «Es hora de salir»).


_re = certezas_y_consejos.compilar


_RE_JERGA, _RE_DIAS = _re(_JERGA), _re(_DIAS)
_RE_META = _re(_META)
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
# Números que el pedido usa para explicar los indicadores (la línea de 50, los
# extremos de 70 y 30, el 23 de la fuerza de la tendencia, los 200 días).
_NUMEROS_LIBRES = {0.0, 23.0, 30.0, 50.0, 70.0, 100.0, 200.0}


def _valores(token: str, tambien_json: bool) -> set:
    """«1.660» → {1660}; «0,000006» → {0.000006}; «77.800» → {77800}. Del
    contexto (JSON) también se lee «1660.4» como 1660,4 y sus redondeos, para
    que un número de la cartera escrito a la argentina no cuente como inventado."""
    t = token.rstrip(".,")
    out = set()
    a = t.replace(".", "").replace(",", ".") if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t) else t.replace(",", ".")
    try:
        out.add(float(a))
    except ValueError:
        pass
    if tambien_json and "," not in t and t.count(".") == 1:
        try:
            v = float(t)
            out |= {v, round(v), round(v, 1), round(v, 2)}
        except ValueError:
            pass
    return out


def inventados(texto: str, contexto: str) -> list:
    """Los números del texto que no están en ningún dato del turno (los hechos,
    lo que trajeron las herramientas, la cartera, la pregunta)."""
    hay = set(_NUMEROS_LIBRES)
    for x in _RE_NUMERO.findall(contexto or ""):
        hay |= _valores(x, True)
    # «el 30 de octubre del año pasado» dicho «30 oct 2025»: el año anterior al
    # de los datos no es un número inventado (SHIB, 30/10).
    hay |= {float(int(y) - 1) for y in re.findall(r"\b(20\d\d)-\d\d-\d\d", contexto or "")}
    return sorted({x.rstrip(".,") for x in _RE_NUMERO.findall(_lo_que_se_lee(texto))
                   if not (_valores(x, False) & hay)})


def _lo_que_se_lee(texto: str) -> str:
    """Sin lo que la persona no lee: el largo de una barrita del dibujo
    (`"pct": 83`, un número suelto del bloque) y los links de los botones
    (`"to": "/alertas?new=NVDA&up=13"`). En la segunda prueba real (30/10)
    eran todos los «inventados» y dos respuestas buenas terminaron en el texto
    de respaldo."""
    t = re.sub(r'"to"\s*:\s*"[^"]*"', "", texto or "")
    return re.sub(r'"\w+"\s*:\s*-?\d+(?:\.\d+)?', "", t)


# «Nadie sabe si va a subir» no predice: lo niega. Medido con la IA real (30/10):
# a «¿GGAL va a subir?» y «¿Bitcoin va a seguir bajando la semana que viene?» el
# modelo contestaba eso, y sin esta excepción las dos terminaban en el texto de
# respaldo. Tampoco cuenta repetir la pregunta («la semana que viene»).
_NEGADO = re.compile(r"(\bnadie\b|\bno se (puede )?sabe\b|\bno (lo )?s[ée]\b|\bno (te )?(puedo|podemos) (decir|saber)\b|"
                     r"\bimposible (de )?saber\b|\bsi\s*$)", re.IGNORECASE)


def _negado(texto, m) -> bool:
    antes = texto[max(0, m.start() - 45):m.start()]
    antes = re.split(r"[.!?:;]", antes)[-1]   # sólo la misma oración
    return bool(_NEGADO.search(antes))


def _no_es_prediccion(texto, m, pregunta) -> bool:
    if m.group(0).lower() in (pregunta or "").lower():
        return True
    return _negado(texto, m)


def problemas(texto: str, pregunta: str = "", contexto: str = None) -> list:
    """Lo que está mal en una respuesta del chat sobre cómo viene un activo, en
    palabras para el modelo (va en el pedido de corrección). Vacío si está bien.
    Mira la respuesta ENTERA, incluido el bloque de tarjetas y la voz: también se
    leen y se escuchan. `contexto`: todo lo que el modelo tenía a la vista en el
    turno; si viene, un número que no está ahí es inventado (como en el resumen
    de la ficha: el modelo no calcula)."""
    t = texto or ""
    dichas = {m.group(0).lower() for m in _RE_JERGA.finditer(pregunta or "")}
    out = []
    jerga = sorted({m.group(0).lower() for m in _RE_JERGA.finditer(t)} - dichas)
    if jerga:
        out.append("usaste palabras técnicas que la persona no tiene por qué saber ("
                   + ", ".join(jerga) + "): decilo con palabras de todos los días "
                   "(«la fuerza del precio», «la tendencia de fondo», «el precio más alto del año»)")
    # Repetir la pregunta exime una certeza («la semana que viene»), no un
    # consejo: «¿Conviene comprar?» → «Conviene comprar» aconseja. Negarlo
    # («no te puedo decir si conviene comprar») exime a los dos.
    out += certezas_y_consejos.avisos(t, exenta_certeza=lambda tx, m: _no_es_prediccion(tx, m, pregunta),
                                      exento_consejo=_negado)
    dias = sorted({m.group(0).lower() for m in _RE_DIAS.finditer(t)}
                  - {m.group(0).lower() for m in _RE_DIAS.finditer(pregunta or "")})
    if dias:
        out.append("nombraste un día de la semana (" + ", ".join(dias) + ") que los datos no traen: "
                   "decí la fecha («el 29 de octubre»), también en la voz")
    meta = sorted({m.group(0).lower() for m in _RE_META.finditer(t)})
    if meta:
        out.append("le hablaste de la corrección (" + ", ".join(meta) + "): la persona no pidió nada, "
                   "escribí la respuesta como si fuera la primera")
    if contexto is not None:
        malos = inventados(t, contexto + " " + (pregunta or ""))
        if malos:
            out.append("usaste números que no están en los datos (" + ", ".join(malos) + "): "
                       "copiá los números tal cual vienen, sin calcular ni redondear de nuevo")
    return out


# Si la respuesta corregida tampoco sirve, no se publica: esto en su lugar.
TEXTO_SIN_LECTURA = ("Esta vez no me salió contarlo bien con palabras simples. "
                     "Probá preguntarme de nuevo en un rato, o mirá la ficha del activo, "
                     "que tiene el gráfico y la lectura de hoy.")

# Para el modelo, al lado de los hechos. Corto: las reglas largas están en el
# pedido del chat, que se cobra una vez y se reusa (caché).
# La lista de palabras va ACÁ además del pedido: medido con la IA real (30/10),
# con la lista sólo en el pedido 6 de 10 primeros borradores traían «bajista»,
# «alcista», «piso» o «rebotó», y cada corrección es una llamada más.
_COMO_CONTARLO = (
    "Contá cómo viene con estos hechos y nada más: copiá los números como vienen, sin calcular "
    "(tampoco en las tarjetas ni en la voz). Palabras de todos los días: subió, bajó, cerró en, la "
    "tendencia de fondo es alcista o bajista, la caída (o la suba) tiene fuerza aún, esa fuerza viene "
    "bajando, su promedio de los últimos meses, el precio más alto o más bajo del año, volvió a subir. "
    "NUNCA: firme, se está cansando, piso, techo, zona, rebote, rebotó, impulso, soporte, resistencia, "
    "sobrecompra, ni siglas (RSI, ADX, Squeeze). Nunca nombres el día de la "
    "semana: la fecha. Lo que viene, sólo como posibilidad. Cerrá con «lo_que_se_mira» si viene. "
    "Nunca le digas que compre, venda o espere."
)


def resolver(activo: str, moneda: str = None) -> tuple | None:
    """(símbolo, moneda, local, nombre) de lo que nombró el modelo, o None.
    'GGAL' y 'GGAL.BA' son la acción argentina (BYMA); 'AAPL.BA' el CEDEAR, en
    pesos; 'BTC-USD' es Bitcoin. La moneda de entrada es la de la ficha
    (dólares), salvo un CEDEAR nombrado con «.BA» o que la persona pida pesos."""
    from accion_local import seguido, es_cedear
    from ai.asset_names import asset_name
    s = (activo or "").strip().upper()
    if not s or not re.fullmatch(r"[A-Z0-9.\-]{1,20}", s):
        return None
    base, local = seguido(s)
    if moneda in ("ars", "pesos"):
        mon = "ars"
    elif moneda in ("usd", "dolares", "dólares"):
        mon = "usd"
    else:
        mon = "ars" if s.endswith(".BA") and es_cedear(base) else "usd"
    return base, mon, local, asset_name(base) or base


def para_el_chat(ficha: dict, nombre: str) -> dict:
    """Lo que recibe el modelo (la herramienta `get_technical_reading` y el botón
    de la ficha). `ficha` = `tecnico.para_la_ficha` de esa serie."""
    from ai.resumen_tecnico_hechos import para_el_chat as hechos_del_chat
    h = hechos_del_chat(ficha, nombre)
    if not h:
        motivo = (ficha or {}).get("motivo")
        return {
            "available": False,
            "activo": nombre,
            "reason": ("no tiene gráfico de precios (un bono o un fondo se miran de otra forma)"
                       if motivo == "sin_serie" else
                       "todavía no hay precios de este activo; probá de nuevo en un rato"
                       if motivo in ("tope", "bajando") else
                       "no hay historia de precios suficiente para contar cómo viene"),
            "_como_contarlo": "Decilo en una oración, sin inventar nada, y ofrecé otra cosa que sí puedas mirar.",
        }
    return {"available": True, "activo": nombre, "hechos": h, "_como_contarlo": _COMO_CONTARLO}
