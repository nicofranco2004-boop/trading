"""De qué canal vino cada registro (IA, X, Meta, Google…): UNA sola definición.

Por qué existe este archivo
───────────────────────────
`users.origen` guarda de dónde llegó cada persona que se registró (lo anota el
navegador, ver frontend/src/utils/origen.js). Hay dos clases de origen:

  · El código que trae el link. El de cada post (`?d=x-20261019`) o el de una
    campaña: `utm_source`, `utm_medium` y `utm_campaign` → `fuente[/medio][/campaña]`
    (`utm_source=meta-anuncios&utm_campaign=…` → `meta-anuncios/<campaña>`).
    ChatGPT agrega solo `utm_source=chatgpt.com` a sus links.
  · Lo que el navegador reconoce cuando el link no trae código:
      `clic/<marca>`            la marca que la red le agrega al link (`fbclid`
                                es de Facebook e Instagram, `gclid` de Google…),
                                cuando no se sabe de qué sitio venía
      `sitio/<sitio>[/<marca>]` el sitio de donde venía (`t.co`, `l.instagram.com`,
                                `perplexity.ai`), y la marca si el link traía una
      `app/<app>[/<marca>]`     una app de Android (`com.google.android.gm` es Gmail)

El navegador manda el nombre del sitio, de la app o de la marca TAL CUAL, sin
decidir qué es: lo decide este archivo y nadie más, y no hay dos listas que se
puedan contradecir.

Qué se guarda (`para_guardar`, al registrarse)
──────────────────────────────────────────────
Del sitio o de la app se guarda el nombre SÓLO si está en las tablas de abajo;
si no, `otro`. El nombre de un sitio cualquiera puede ser un dato de la persona:
dónde trabaja (`intranet.banco….com.ar`), cómo se llama (`juanperez.github.io`),
qué apps usa (una de citas, una de salud). Es la misma regla que la lista de lo
que se les cuenta a Google y a Meta (frontend/src/utils/rutasSensibles.js):
olvidarse de un sitio cuesta un dato de las métricas, no un dato de la persona.
Para contar un sitio nuevo, se suma a la tabla: cuenta desde ese día.

Anuncio u orgánico, en Meta
───────────────────────────
`fbclid` va en TODOS los links de Facebook e Instagram, sean de un anuncio o de
un post, y el sitio de donde venía tampoco lo dice. Un anuncio de Meta sólo se
distingue si su link lleva el código: Administrador de anuncios → Seguimiento →
Parámetros de URL: `utm_source=meta-anuncios&utm_campaign={{campaign.name}}`.
También cuenta como anuncio un código de Meta que lo dice (`ig-anuncio-1022`,
`facebook-ads/…`, `fb/paid/…`, `MetaAds`). «Tus posts» afirma algo concreto y
queda SÓLO para la forma de los códigos de Nico: la red, un guion y la fecha
(`ig-20261022`, `fb-1020`). Todo lo demás de Meta (`ig`, `instagram_story`,
`fb-share`) es «sin saber si fue anuncio».

Nunca tira: un código raro termina en «Otro link con código» o en «Otro sitio o
app», y uno vacío es «Sin dato». Lo prueba tests/test_origen_registros.py,
también con códigos al azar.
"""

import re

# (id, cómo se llama en el panel, qué entra). El orden es el del panel.
CANALES = (
    ("ia", "IA", "ChatGPT, Perplexity, Gemini, Claude, Copilot, Grok, DeepSeek…"),
    ("x", "X", "Tus posts con código (x-…), links de X sin código y anuncios de X"),
    ("meta_anuncios", "Meta (anuncios)", "Anuncios cuyo link lleva el código meta-anuncios"),
    ("meta_posts", "Meta (tus posts)", "Tus posts de Instagram o Facebook con código (ig-…, fb-…)"),
    ("meta_sin_saber", "Meta (sin saber si fue anuncio)",
     "Facebook o Instagram sin código: un post, alguien que lo compartió o un anuncio sin el código"),
    ("google", "Google", "El buscador y los anuncios de Google"),
    ("otro_codigo", "Otro link con código", "Un código que no dice de qué red es (?d=mail-…)"),
    ("otro_sitio", "Otro sitio o app", "WhatsApp, LinkedIn, el mail, otro sitio o app"),
    ("sin_dato", "Sin dato", "Escribió la dirección, usó un link guardado o la app no dijo de dónde venía"),
)

# La marca que cada red le agrega a sus links: nombre de la marca → (de quién
# es, canal). Del link se guarda sólo el NOMBRE, nunca el valor (identifica el
# clic). MARCAS_DE_CLIC en origen.js, la lista que anota el navegador, tiene que
# ser ésta y en este orden (el orden decide cuál se anota si vienen dos): lo
# verifica tests/test_origen_registros.py.
MARCAS = {
    "fbclid": ("Facebook o Instagram", "meta_sin_saber"),
    "twclid": ("Anuncio de X", "x"),
    "gclid": ("Anuncio de Google", "google"),
    "gbraid": ("Anuncio de Google", "google"),
    "wbraid": ("Anuncio de Google", "google"),
    "ttclid": ("Anuncio de TikTok", "otro_sitio"),
    "msclkid": ("Anuncio de Microsoft", "otro_sitio"),
}

# Sitio → (cómo se llama, canal). Cuenta también para sus subdominios:
# `facebook.com` reconoce `l.facebook.com`, `lm.facebook.com` y `m.facebook.com`;
# si dos coinciden gana el más largo (`gemini.google.com` le gana al buscador).
_SITIOS = {
    # X: sus links pasan por t.co.
    "t.co": ("X", "x"),
    "x.com": ("X", "x"),
    "twitter.com": ("X", "x"),
    # Meta.
    "facebook.com": ("Facebook", "meta_sin_saber"),
    "fb.com": ("Facebook", "meta_sin_saber"),
    "fb.me": ("Facebook", "meta_sin_saber"),
    "instagram.com": ("Instagram", "meta_sin_saber"),
    "threads.net": ("Threads", "meta_sin_saber"),
    "threads.com": ("Threads", "meta_sin_saber"),
    "messenger.com": ("Messenger", "meta_sin_saber"),
    "m.me": ("Messenger", "meta_sin_saber"),
    "ig.me": ("Instagram", "meta_sin_saber"),
    # IA.
    "chatgpt.com": ("ChatGPT", "ia"),
    "chat.openai.com": ("ChatGPT", "ia"),
    "perplexity.ai": ("Perplexity", "ia"),
    "pplx.ai": ("Perplexity", "ia"),
    "gemini.google.com": ("Gemini", "ia"),
    "bard.google.com": ("Gemini", "ia"),
    "notebooklm.google.com": ("NotebookLM", "ia"),
    "aistudio.google.com": ("Google AI Studio", "ia"),
    "claude.ai": ("Claude", "ia"),
    "copilot.microsoft.com": ("Copilot", "ia"),
    "m365.cloud.microsoft": ("Copilot", "ia"),
    "grok.com": ("Grok", "ia"),
    "chat.deepseek.com": ("DeepSeek", "ia"),
    "chat.mistral.ai": ("Mistral", "ia"),
    "meta.ai": ("Meta AI", "ia"),
    # Google (el buscador de cada país va por _ES_BUSCADOR_DE_GOOGLE).
    "news.google.com": ("Google Noticias", "google"),
    "images.google.com": ("Google", "google"),
    "m.google.com": ("Google", "google"),
    "googleadservices.com": ("Anuncio de Google", "google"),
    # Otros conocidos: no tienen canal propio, pero el panel dice qué son.
    "mail.google.com": ("Gmail", "otro_sitio"),
    "whatsapp.com": ("WhatsApp", "otro_sitio"),
    "wa.me": ("WhatsApp", "otro_sitio"),
    "t.me": ("Telegram", "otro_sitio"),
    "telegram.org": ("Telegram", "otro_sitio"),
    "linkedin.com": ("LinkedIn", "otro_sitio"),
    "lnkd.in": ("LinkedIn", "otro_sitio"),
    "youtube.com": ("YouTube", "otro_sitio"),
    "reddit.com": ("Reddit", "otro_sitio"),
    "tiktok.com": ("TikTok", "otro_sitio"),
    "bing.com": ("Bing", "otro_sitio"),
    "duckduckgo.com": ("DuckDuckGo", "otro_sitio"),
    "outlook.live.com": ("Outlook", "otro_sitio"),
}

# google.com, google.com.ar, google.co.uk, google.es… (sin `www.`).
_ES_BUSCADOR_DE_GOOGLE = re.compile(r"^google\.(?:com|com\.[a-z]{2}|co\.[a-z]{2}|[a-z]{2,3})$")

# App de Android → (cómo se llama, canal). Llegan como `android-app://<app>/`; el
# nombre es el de su página en Google Play.
_APPS = {
    "com.twitter.android": ("X", "x"),
    "com.facebook.katana": ("Facebook", "meta_sin_saber"),
    "com.facebook.lite": ("Facebook", "meta_sin_saber"),
    "com.instagram.android": ("Instagram", "meta_sin_saber"),
    "com.instagram.barcelona": ("Threads", "meta_sin_saber"),
    "com.facebook.orca": ("Messenger", "meta_sin_saber"),
    "com.openai.chatgpt": ("ChatGPT", "ia"),
    "ai.perplexity.app.android": ("Perplexity", "ia"),
    "com.google.android.apps.bard": ("Gemini", "ia"),
    "com.anthropic.claude": ("Claude", "ia"),
    "com.microsoft.copilot": ("Copilot", "ia"),
    "ai.x.grok": ("Grok", "ia"),
    "com.deepseek.chat": ("DeepSeek", "ia"),
    "com.google.android.googlequicksearchbox": ("Google", "google"),
    "com.google.android.apps.magazines": ("Google Noticias", "google"),
    "com.google.android.gm": ("Gmail", "otro_sitio"),
    "com.whatsapp": ("WhatsApp", "otro_sitio"),
    "com.whatsapp.w4b": ("WhatsApp Business", "otro_sitio"),
    "org.telegram.messenger": ("Telegram", "otro_sitio"),
    "com.linkedin.android": ("LinkedIn", "otro_sitio"),
    "com.google.android.youtube": ("YouTube", "otro_sitio"),
    "com.reddit.frontpage": ("Reddit", "otro_sitio"),
    "com.zhiliaoapp.musically": ("TikTok", "otro_sitio"),
    "com.microsoft.office.outlook": ("Outlook", "otro_sitio"),
}

# En un código puesto en el link, la red sale de la primera palabra:
# `x-20261019` y `x/post-1019` son X; `perplexity` (utm sin punto) es IA.
# `msg` y `an` son Messenger y Audience Network en el {{site_source_name}} que
# arma el Administrador de anuncios.
_REDES_EN_CODIGOS = {
    "x": "x", "twitter": "x", "tw": "x",
    "ig": "meta", "instagram": "meta", "insta": "meta", "fb": "meta", "facebook": "meta",
    "face": "meta", "threads": "meta", "meta": "meta", "msg": "meta", "messenger": "meta", "an": "meta",
    "google": "google",
    "chatgpt": "ia", "openai": "ia", "perplexity": "ia", "gemini": "ia",
    "claude": "ia", "copilot": "ia", "grok": "ia", "deepseek": "ia",
}

# `meta-anuncios/<campaña>` (el código que lleva el link de un anuncio de Meta),
# y lo mismo todo junto o con otra red: `metaads`, `fbads`, `meta_ads2026`.
_ES_ANUNCIO_DE_META = re.compile(r"^(?:meta|fb|facebook|ig|instagram|insta)[-_]?(?:ads?|anuncios?)\d*(?:$|[-_./])")
# Las palabras que dicen «anuncio» en un código de Meta (con o sin números
# pegados atrás: `ads2026`). Incluye los `utm_medium` de pago (`paid`, `cpc`).
_PALABRAS_DE_ANUNCIO = frozenset({
    "ad", "ads", "anuncio", "anuncios", "pauta", "publicidad", "pago", "paid", "cpc", "cpm",
    "ppc", "retargeting", "remarketing", "sponsored", "patrocinado"})

# Los canales que son una red con nombre propio. Si el sitio de donde venía es
# de una de éstas y la marca dice otra (`fbclid` llegando desde t.co), ganó el
# sitio: alguien copió la dirección de la barra —Rendi deja la marca ahí para
# Google y Meta— y la compartió en otra red.
_CANALES_DE_RED = frozenset({"ia", "x", "meta_sin_saber", "google"})

_AUTOMATICOS = ("sitio/", "app/", "clic/")
_IDS = frozenset(c for c, _, _ in CANALES)


def _sitio(nombre):
    """(cómo se llama, canal) de un sitio, o None si no está en la tabla."""
    host = nombre[4:] if nombre.startswith("www.") else nombre
    if _ES_BUSCADOR_DE_GOOGLE.match(host):
        return ("Google", "google")
    mejor = None
    for dominio, dato in _SITIOS.items():
        if (host == dominio or host.endswith("." + dominio)) and (mejor is None or len(dominio) > len(mejor[0])):
            mejor = (dominio, dato)
    return mejor[1] if mejor else None


def _lugar(tipo, nombre):
    """(cómo se llama, canal) de un sitio (`tipo` = 'sitio') o de una app de
    Android ('app'), o None si no está en las tablas."""
    return _APPS.get(nombre) if tipo == "app" else _sitio(nombre)


def _canal_del_codigo(codigo):
    """(canal, cómo se llama) de un código puesto en el link (`d` o utm)."""
    if _ES_ANUNCIO_DE_META.match(codigo):
        return "meta_anuncios", None
    cabeza = codigo.split("/", 1)[0]
    # Un utm con forma de sitio (`chatgpt.com`, `t.co`) se lee como el sitio.
    if "." in cabeza:
        sitio = _sitio(cabeza)
        if sitio:
            return sitio[1], sitio[0]
    red = re.split(r"[-_.]", cabeza, maxsplit=1)[0]
    canal = _REDES_EN_CODIGOS.get(red)
    if canal == "meta":
        palabras = {re.sub(r"\d+$", "", p) for p in re.split(r"[-_./]", codigo)}
        if palabras & _PALABRAS_DE_ANUNCIO:
            return "meta_anuncios", None
        # Sólo la forma de los códigos de Nico: la red, un guion y la fecha.
        resto = cabeza[len(red):]
        es_post = len(resto) >= 2 and resto[0] in "-_" and resto[1].isdigit()
        return ("meta_posts" if es_post else "meta_sin_saber"), None
    return (canal or "otro_codigo"), None


def _clasificar(codigo):
    """(canal, fuente) de un código ya en minúsculas, sin el control final."""
    tipo, _, resto = codigo.partition("/")
    if tipo == "clic" and resto:
        marca = MARCAS.get(resto.split("/", 1)[0])
        return (marca[1], marca[0]) if marca else ("otro_sitio", None)
    if tipo in ("sitio", "app") and resto:
        nombre, _, nombre_marca = resto.partition("/")
        lugar = _lugar(tipo, nombre)
        marca = MARCAS.get(nombre_marca)
        # El sitio dice mejor de dónde: «Instagram» y no «Facebook o Instagram».
        fuente = lugar[0] if lugar else (marca[0] if marca else None)
        if marca and lugar and lugar[1] != marca[1] and lugar[1] in _CANALES_DE_RED:
            return lugar[1], fuente
        # Si no, la marca le gana al sitio: `gclid` desde Gmail es un anuncio de
        # Google en Gmail; `fbclid` desde Linktree, un link de Instagram que pasó
        # por ahí.
        if marca:
            return marca[1], fuente
        return (lugar[1] if lugar else "otro_sitio"), fuente
    return _canal_del_codigo(codigo)


def canal_del_origen(codigo):
    """De qué canal es un origen guardado en `users.origen`.

    Devuelve (canal, fuente): `canal` es SIEMPRE un id de CANALES (una fila mal
    escrita en una tabla no puede tumbar el panel); `fuente`, cómo se llama el
    sitio, la app o la marca cuando se conoce («Instagram», «Gmail»), para que
    el panel lo diga; si no, None."""
    if not isinstance(codigo, str) or not codigo.strip():
        return "sin_dato", None
    codigo = codigo.strip().lower()
    canal, fuente = _clasificar(codigo)
    if canal not in _IDS:
        canal = "otro_sitio" if codigo.startswith(_AUTOMATICOS) else "otro_codigo"
    return canal, fuente


def para_guardar(codigo):
    """Lo que se guarda en `users.origen` de lo que mandó el navegador (ya
    limpio): lo mismo, salvo el nombre de un sitio o de una app que no está en
    las tablas, que pasa a `otro` (ver «Qué se guarda» arriba), y una marca que
    no es de la lista, que se saca. Los códigos puestos en el link quedan como
    vinieron: los eligió quien armó el link."""
    if not isinstance(codigo, str) or not codigo.startswith(_AUTOMATICOS):
        return codigo
    tipo, _, resto = codigo.partition("/")
    if tipo == "clic":
        return codigo if resto in MARCAS else "clic/otra"
    nombre, _, nombre_marca = resto.partition("/")
    if not _lugar(tipo, nombre):
        nombre = "otro"
    return f"{tipo}/{nombre}" + (f"/{nombre_marca}" if nombre_marca in MARCAS else "")
