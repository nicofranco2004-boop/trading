"""certezas_y_consejos — lo que la IA técnica no puede decir, en UN solo lugar.
═══════════════════════════════════════════════════════════════════════════
Dos textos de la IA hablan de cómo viene un activo: el resumen de la ficha
(ai/resumen_tecnico.py) y el chat de Mervall-E cuando cuenta la lectura técnica
(ai/lectura_tecnica_chat.py). Los dos tienen la misma regla (CNV: Rendi no
asesora, y nadie sabe lo que viene):
  · nada dicho como seguro sobre lo que viene («va a subir», «probablemente
    siga subiendo»): sólo como posibilidad («podría ser una señal de que…»);
  · ningún consejo de operar («conviene comprar», «yo vendería», «es hora de
    salir», «un buen punto para entrar»).

POR QUÉ UN SOLO MÓDULO. Hasta el 31/10 cada uno tenía su lista y la auditoría
final encontró que cada una dejaba pasar lo que la otra frenaba: el chat no
veía «Conviene comprar», «Sería prudente vender», «Yo vendería», «Es hora de
salir», «buen punto para entrar», «acumular»; el resumen tampoco, ni
«probablemente siga subiendo» ni «Lo prudente sería reducir». Una frase nueva
se agrega ACÁ y la ven los dos. Cada uno suma encima lo suyo (el resumen, su
lista de jerga y su cierre neutro; el chat, su jerga y los días de la semana).

CÓMO SE ARMA UN CONSEJO. No alcanza con los verbos sueltos: «el precio salió
del canal», «mantiene la tendencia», «entró en tendencia bajista» describen y
están bien. Lo que hace un consejo es el verbo de operar en una forma que le
habla a alguien o que opina qué conviene:
  · detrás de una opinión: conviene / lo prudente (mejor, razonable…) es /
    sería prudente / es hora de / un buen punto para / deberías / recomiendo…
    + comprar, vender, entrar, salir, acumular, tomar ganancias, mantener,
    reducir, sumar, esperar…;
  · en imperativo («comprá», «vendelo», «tomá ganancias») o en condicional
    («yo vendería», «compraría»), o «que compres».
Los verbos que también nombran cosas de la app («podés entrar a la ficha»,
«podés sumarlo a tu lista», «hay que esperar al cierre para saberlo») sólo
cuentan detrás de una opinión fuerte, no de «podés» o «hay que».

ENTRAR, MANTENER Y «ENTRADA» (revisión final, 31/10). Mervall-E guía con ellos:
«Entrá a la ficha», «Mantené presionado», «está 12 % arriba de tu precio de
entrada». Eso es navegación, un gesto o un dato de la persona, no un consejo.
Cuentan sólo junto a una operación o una recomendación («entrá a la posición»,
«conviene entrar», «mantené la posición», «buen punto de entrada»). Con B3 el
chat retiene el texto hasta revisarlo: un falso positivo acá cuesta una llamada
de más al modelo y, si la repite, la respuesta entera se reemplaza.
"""
from __future__ import annotations

import re

# Lo que viene dicho como seguro. El pasado («se terminó el 6 de octubre») es un
# hecho y no se toca; «podría ser una señal de…» es la forma.
CERTEZAS = [
    r"va(n)? a (subir|bajar|seguir|caer|romper|rebotar|recuperar|explotar)",
    r"(subir|bajar|caer|seguir|rebotar|recuperar)(á|án)",
    r"se (termin|cort|confirm)(a|an|ar[áa]n?|ar[íi]an?)", r"(termin|confirm)ar[íi]an?",
    r"d(a|ar[íi]a) por terminad[ao]",
    r"sin duda", r"seguro que", r"seguramente", r"con seguridad", r"es inminente",
    r"est[áa] por (subir|bajar|explotar|caer)",
    # Las formas suaves de predecir (Nico, 30/10: «asegurate, no tiene que predecir
    # el futuro»). La única forma de hablar de lo que viene es «lo que se mira…
    # podría ser una señal de que…»: un movimiento que pierde o gana fuerza, nunca
    # un precio ni una dirección.
    r"probablemente", r"(es|lo m[áa]s) probable", r"(es|ser[íi]a) esperable", r"se espera",
    r"(podr[íi]a|puede|pueda|podr[íi]an|pueden) (subir|bajar|caer|seguir|llegar|recuperar\w*|volver|rebotar|"
    r"repuntar|dispararse|desplomarse|ir|tocar|alcanzar|irse)",
    r"deber[íi]a(n)? (subir|bajar|caer|seguir|llegar|recuperar\w*|volver|rebotar|repuntar|ir|tocar|alcanzar)",
    r"(seguir|subir|bajar|caer|recuperar)[íi]a(n)?", r"tiene (margen|espacio|lugar|recorrido) para",
    r"(pr[óo]ximo|siguiente) (objetivo|destino|nivel|precio)", r"objetivos? de precio",
    r"(camino|rumbo) a (los )?\d[\d.,]*", r"tiende a (subir|bajar|seguir)", r"anticipa", r"pron[óo]stic\w*",
    r"en los pr[óo]ximos (d[íi]as|meses|semanas)", r"la semana que viene", r"el mes que viene",
]

# Los verbos de operar, en infinitivo y con su pronombre («comprarlo»). Los que
# también nombran cosas de la app o del gráfico («entrar a la ficha», «sumarlo a
# tu lista», «salir del canal», «esperar al cierre») van sólo en `_OPERAR_TODOS`,
# que se usa detrás de una opinión fuerte.
_CLITICO = r"(l[oae]s?|se|te|me)?"
_OPERAR = (r"(comprar|vender|acumular|invertir|desarmar|reducir|rotar|desprenderse|deshacerse|posicionarse)"
           + _CLITICO + r"|tomar ganancias|hacer toma de ganancias")
# Entrar a un lugar de la app y mantener apretado no son operar (ver arriba).
_NO_ES_OPERAR = (r"(?! (?:a|al|en|de) (?:la |el |tu |su |esta |esa )?(?:ficha|cartera|pesta[ñn]a|secci[óo]n|app|"
                 r"aplicaci[óo]n|men[úu]|configuraci[óo]n|lista|watchlist|gr[áa]fico|alertas?|novedades|panorama|"
                 r"p[áa]gina|link|enlace|perfil|cuenta|ver)\b)(?! presionad|apretad)")
_OPERAR_TODOS = (_OPERAR + r"|(entrar|salir|mantener|sumar|esperar|cerrar|aumentar|cubrirse|apostar)" + _CLITICO
                 + _NO_ES_OPERAR + r"|quedarse afuera|quedarte afuera")
# El imperativo de entrar y mantener sólo con algo que se opera: «entrá a la
# posición», «mantené la posición», «mantenelo».
_LO_QUE_SE_OPERA = (r"(?:la |tu |esa |una )?(?:posici[óo]n|tenencia|acci[óo]n|papel|activo|compra|cedear|bono)"
                    r"|(?:el |ese |este )(?:activo|papel|bono|cedear)|largo|comprado")
# Lo que puede ir entre la opinión y el verbo: «conviene YA vender», «lo mejor es
# NO comprar», «sería prudente EMPEZAR A reducir».
_ENTRE = r"(?:(?:ya|ahora|no|directamente|empezar a|ir) )?"

# Una opinión sobre qué conviene hacer, delante del verbo.
_OPINION_FUERTE = (
    r"(te |le |les |nos )?(conviene|convendr[íi]a|convenga)( m[áa]s)?",
    r"(es|ser[íi]a|parece|parecer[íi]a|resulta|resultar[íi]a) (m[áa]s )?(prudente|mejor|conveniente|aconsejable|"
    r"recomendable|razonable|oportuno|sensato|l[óo]gico|ideal|buena idea|momento de|el momento de)",
    r"lo (m[áa]s )?(prudente|mejor|razonable|ideal|conveniente|aconsejable|recomendable|sensato|l[óo]gico|"
    r"indicado|correcto|inteligente) (es|ser[íi]a|parece|parecer[íi]a)",
    r"(es|ser[íi]a|lleg[óo] la|ya es) (la )?hora de",
    r"(buen|mejor|gran|el) (punto|momento|nivel|precio|lugar) (para|de)",
    r"mejor", r"(deber[íi]as|tendr[íi]as que|deber[íi]an|tendr[íi]an que)",
    r"(recomiendo|sugiero|aconsejo|recomendar[íi]a|sugerir[íi]a|aconsejar[íi]a)",
    r"aprovech(á|ar|ar[íi]a|en|es) (para|a)",
)
# Una sugerencia más floja: sólo con los verbos que no nombran otra cosa.
_OPINION_FLOJA = (
    r"(pod[ée]s|podr[íi]as|ten[ée]s que|hay que|habr[íi]a que|vale la pena|val[íi]a la pena)",
)

CONSEJOS = [
    r"(" + "|".join(_OPINION_FUERTE) + r") " + _ENTRE + r"(" + _OPERAR_TODOS + r")",
    r"(" + "|".join(_OPINION_FLOJA) + r") " + _ENTRE + r"(" + _OPERAR + r")",
    # Imperativo (voseo), con o sin pronombre.
    r"(comprá|vendé|acumulá|invertí|desarmá|reducí|aprovechá)(l[oa]s?|le)?",
    r"entrá(le)? (?:a |al |en )?(?:" + _LO_QUE_SE_OPERA + r")", r"mantené (?:" + _LO_QUE_SE_OPERA + r")",
    r"(compral|vendel|acumulal|mantenel|reducil|desarmal)[oa]s?",
    r"tom[áa] (las )?ganancias",
    # Condicional («yo vendería», «compraría»).
    r"(comprar|vender|esperar|entrar|invertir|acumular|reducir|desarmar)[íi]a(s|n|mos)?",
    r"(saldr|mantendr)[íi]a(s|n|mos)?",
    # «Te diría que compres», «es momento de que vendas».
    r"que (compres|vendas|entres|salgas|acumules|mantengas|reduzcas|inviertas|esperes|desarmes|tomes ganancias)"
    + _NO_ES_OPERAR,
    r"yo( no)? (compro|vendo|entro|salgo|acumulo|mantengo|reduzco|espero|me quedo)",
    r"yo que vos", r"en tu lugar",
    r"(sumar|comprar|acumular) en (las )?bajas", r"antes de (comprar|vender|invertir|acumular)",
    # «Tu precio de entrada» es un dato de la persona, no un consejo.
    r"(?<!tu )(?<!su )(?<!tus )(?<!sus )(punto|precio|nivel|momento) de (entrada|salida)",
    r"te (conviene|recomiendo|sugiero|aconsejo)", r"(es|ser[íi]a) (un )?buen momento",
    r"momento (justo )?(de|para) (comprar|vender|entrar|salir)",
    r"(es|ser[íi]a) una (buena |gran )?oportunidad",
]


def compilar(lista: list) -> re.Pattern:
    """Una lista de frases → una búsqueda que no corta palabras («desarmar» no
    encuentra «armar»; «−DI» no es «DI»)."""
    return re.compile(r"(?<![\w+−-])(" + "|".join(lista) + r")(?!\w)", re.IGNORECASE)


RE_CERTEZAS, RE_CONSEJOS = compilar(CERTEZAS), compilar(CONSEJOS)


def encontradas(regex: re.Pattern, texto: str, exenta=None) -> list:
    """Las frases que encontró, en minúsculas y sin repetir. `exenta(texto, m)`
    deja pasar una (el chat: «nadie sabe si va a subir» no predice, lo niega)."""
    t = texto or ""
    return sorted({m.group(0).lower() for m in regex.finditer(t) if not (exenta and exenta(t, m))})


def avisos(texto: str, exenta_certeza=None, exento_consejo=None) -> list:
    """Lo que está mal, en palabras para el modelo (va en el pedido de
    corrección). Vacío si no dijo nada seguro ni dio un consejo."""
    out = []
    cert = encontradas(RE_CERTEZAS, texto, exenta_certeza)
    if cert:
        out.append("dijiste como seguro lo que viene (" + ", ".join(cert) + "): nadie lo sabe, "
                   "decilo como posibilidad («podría ser una señal de que…»)")
    cons = encontradas(RE_CONSEJOS, texto, exento_consejo)
    if cons:
        out.append("le dijiste qué hacer (" + ", ".join(cons) + "): Rendi no recomienda comprar ni "
                   "vender; contá cómo viene y qué es lo que se mira")
    return out
