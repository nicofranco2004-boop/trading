"""tts — Rendi LEÍDA en voz alta. El único lugar que habla con OpenAI.
═══════════════════════════════════════════════════════════════════════════
Claude PIENSA la respuesta (el /api/ai/chat de siempre, con sus 16 tools y sus
guardias); este módulo sólo la LEE. Anthropic no vende API de voz a terceros,
así que la lectura la hace `gpt-4o-mini-tts` de OpenAI con la voz `fable`
—elegida escuchando las 11— y nada más: acá no se decide QUÉ se dice.

LO QUE SE MIDIÓ CONTRA LA API DE VERDAD, Y MANDA SOBRE ESTE ARCHIVO
--------------------------------------------------------------------------
Los números de acá son los que se midieron EN ESTE REPO el 2026-09-12,
cronometrando las llamadas y leyendo la duración del mp3 con `afinfo`. Donde el
plan de la etapa había anotado otra cosa, se aclara — pero manda la medición.

1. STREAMING O NADA. El primer sonido llega en 1,1-1,6 s reusando la conexión;
   el archivo entero, en 2,3-3,3 s. Esperar el mp3 completo antes de mandarlo
   duplica la espera y se siente roto. Por eso `speak()` es un generador y el
   endpoint lo reenvía a medida que llega.
   (El plan estimaba 1,35-1,43 s y 4,3-4,7 s. El primer sonido dio parecido; el
   archivo entero, más rápido. La conclusión no cambia.)
2. LA CONEXIÓN SE REUSA O SE PAGA UN SEGUNDO. Abrirla de cero costaba 2,68 s
   hasta el primer sonido contra 1,60 s con el pool caliente, mismo texto, una
   llamada detrás de la otra. Por eso el cliente httpx es uno solo por proceso
   (ver `_client()`), no uno por pedido.
3. EL CACHE NO ES UNA OPTIMIZACIÓN, ES LA FUNCIONALIDAD. La decisión de
   producto es "re-escuchar una respuesta es gratis, siempre". Eso sólo se
   sostiene si el mismo texto no se vuelve a generar nunca. Cache por hash del
   texto (+ voz + modelo + instrucciones: si cambia cualquiera, cambia la
   clave y se regenera).
4. PEDIRLE AL MODELO QUE HABLE MÁS RÁPIDO NO HACE NADA. El mismo texto con
   "ritmo ágil" y con "hablá RÁPIDO, ritmo de podcast" dio prácticamente lo
   mismo (24,2 s contra 24,4 s, medido al diseñar la etapa). La velocidad se
   controla SOLO con playbackRate en el navegador. Las instrucciones de abajo
   piden ritmo igual —ayudan al acento y a la energía, no al reloj—, pero no
   esperes que ahorren un centavo.

FORMATO: mp3, no opus. Opus pesa la mitad (220 KB contra 388 KB) y el primer
pedacito llega igual de rápido, pero Safari de iPhone no reproduce opus en
contenedor ogg — y el celular de Nico es donde esto se va a probar. Cuando el
acompañante corra sólo en escritorio, opus es mejor negocio.

COSTO: US$0,015 por minuto de audio.

🔴 EL RITMO NO ES UN NÚMERO, ES UN RANGO — Y DEPENDE DE CUÁNTAS CIFRAS TENGA EL
TEXTO. Un número leído en voz alta ocupa MUCHO más tiempo que los caracteres que
escribe: "16,8%" son 5 caracteres y se dice "dieciséis coma ocho por ciento".
Medido con estas mismas instrucciones y esta misma voz:

    205 caracteres CARGADOS DE CIFRAS  → 21,9 s →  9,4 caracteres/segundo
    228 caracteres CASI SIN CIFRAS     → 16,6 s → 13,7 caracteres/segundo

46% de diferencia entre los dos, con textos casi del mismo largo. Y las
respuestas de Rendi son del PRIMER tipo: el producto entero son cifras.

Por eso `CHARS_PER_SECOND` está en 10 y no en el promedio: es el extremo
CONSERVADOR, a propósito. Se usa para estimar costo, y un costo subestimado es
justo el que hace que nadie se entere de que el margen se fue.

⚠️ Mediciones anteriores dieron 12 (el plan) y 13,3-14,4 (las nuestras). Las dos
se hicieron con textos de pocos números y por eso salieron optimistas. Si volvés
a medir, medí con un texto REAL de Rendi, lleno de porcentajes y montos.

CUÁNTO SALE: un resumen de ~350 caracteres con cifras dura ~35 s y sale
~US$0,0087.

⚠️ EL EMPATE SE MOVIÓ Y LA CUENTA VIEJA QUEDÓ ACÁ ESCRITA MAL. Decía que el
audio empataba con la respuesta escrita a los 263 caracteres. Ese número salía
de que una consulta costaba US$0,007, que era el precio con Haiku. Desde que el
chat pasó a Sonnet (2026-09-12) una consulta cuesta **US$0,021** — medido en el
log del backend, no estimado: cost_usd=0,0202 · 0,0213 · 0,0217 · 0,0219 · 0,0225.

Con ese número el empate está en **84 segundos ≈ 840 caracteres**, no en 263.
Ni siquiera el tope DURO de 600 lo alcanza: 600 caracteres son el 71% de una
ficha. Un resumen normal de 350 sale el 41%.

La consecuencia práctica: el largo del resumen dejó de ser una restricción de
plata. Se sigue acotando por otra razón —nadie quiere escuchar 90 segundos de
resumen— pero el aviso ya no marca un límite económico.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import threading
from collections import OrderedDict
from typing import Iterator

import httpx

log = logging.getLogger("rendi.tts")

# ─── Qué voz y con qué personalidad ──────────────────────────────────────────
# El `instructions` va TEXTUAL en cada llamada. Se eligió contra la alternativa
# "tono tranquilo" escuchando las dos. No lo edites sin volver a escucharlo:
# el acento rioplatense se pierde con muy poco.
MODEL = "gpt-4o-mini-tts"
VOICE = "fable"
AUDIO_FORMAT = "mp3"
MEDIA_TYPE = "audio/mpeg"

INSTRUCTIONS = (
    "Acento: español rioplatense (argentino). Hablá RÁPIDO y con energía, "
    "ritmo de podcast ágil.\n"
    "Nada de pausas dramáticas ni tono solemne."
)

# Tope DURO del endpoint: más que esto no se canta, se rechaza. 600 caracteres
# son ~60 segundos de audio — el doble del molde, ya generoso. Es una VÁLVULA,
# no el camino normal: el aviso de que algo se está estirando salta mucho antes
# (MAX_CHARS_SOFT).
# ─── Los dos precios, en un solo lugar ──────────────────────────────────────
# Están acá y no sueltos en un comentario porque ya pasó: el empate del audio
# quedó escrito en tres lugares con el precio de Haiku, el chat pasó a Sonnet y
# los tres siguieron diciendo lo mismo. El test los lee de acá.
USD_POR_MINUTO_DE_AUDIO = 0.015     # lo que cobra OpenAI por gpt-4o-mini-tts
# Lo que nos sale UNA consulta escrita — o sea, lo que vale la ficha que se
# cobra por escuchar. MEDIDO en el log del backend con el chat en Sonnet 5
# (2026-09-13): cost_usd = 0,0202 · 0,0213 · 0,0217 · 0,0219 · 0,0225.
# Si se cambia de modelo, este número cambia: volvé a mirar el log.
USD_POR_CONSULTA_ESCRITA = 0.021


def empate_en_caracteres() -> float:
    """A partir de cuántos caracteres el audio sale más caro que la ficha que
    se cobra por escucharlo. Hoy da ~840 — ni el tope duro lo roza."""
    segundos = USD_POR_CONSULTA_ESCRITA / (USD_POR_MINUTO_DE_AUDIO / 60)
    return segundos * CHARS_PER_SECOND


MAX_CHARS = 600
# Tope BLANDO: el aviso de que los resúmenes se están estirando. No rechaza
# nada — loguea.
#
# ERA 260 y era el empate económico. Ya no: ver la nota del encabezado — con el
# chat en Sonnet el empate está en 840 caracteres y ni el tope duro lo alcanza.
# Dejarlo en 260 lo convertía en una alarma que suena siempre y por lo tanto no
# suena: desde que el resumen ofrece por dónde seguir, TODOS los reales la
# pasan (medidos: 307 · 332 · 341 · 347 · 372 · 394).
#
# 450 es lo que vigila ahora, y no es un límite de plata: es cuánto está
# dispuesto a escuchar alguien. 450 caracteres son ~45 segundos de audio para
# un resumen de tres oraciones — pasado eso ya no es un resumen. Con los reales
# entre 307 y 394, el aviso no se dispara con la salida de todos los días: se
# dispara cuando algo cambió.
MAX_CHARS_SOFT = 450

# Cuánto se lee del RESPALDO, que es otra cosa. Cuando el modelo no manda el
# resumen hablado, se lee la prosa de pantalla recortada — y eso es un plan B,
# no el camino bueno: está escrito para los ojos y suena peor. Tiene que ser
# CORTO.
#
# Este número venía compartido con MAX_CHARS_SOFT, y ahí estaba el enganche: al
# subir el aviso de 260 a 450 el respaldo se puso a leer un 73% más sin que
# nadie lo pidiera. Dos trabajos distintos, dos números.
MAX_CHARS_RESPALDO = 260

# ─── Qué le pedimos a Claude que escriba para la oreja ───────────────────────
# Va TEXTUAL dentro de los prompts de chat, y vive acá —no copiado en cada
# prompt— por la misma razón que existe ai/voz.py: el tono escrito estaba en 7
# lugares distintos y ninguno decía lo mismo. Los dos prompts de chat (Pro y
# Free/Plus) concatenan esta constante; si hay que ajustar el largo o la regla
# de los nombres, se toca UNA vez.
#
# El molde de 290 caracteres no es estético: a los 12 caracteres/segundo
# medidos son 24 segundos de audio, US$0,0061, exactamente lo que hace que
# "escuchar cuesta 1 ficha más" no pierda plata. Ver el encabezado.
SUMMARY_PROMPT = """
EL RESUMEN HABLADO (campo "voz" del bloque ---RENDI---)
Agregá al JSON un campo más, "voz": la MISMA respuesta contada en voz alta. TRES oraciones: dos de contenido y una última que ofrece por dónde seguir. Apuntá a 350 caracteres contando todo; nunca más de 600.

El largo importa porque es tiempo de alguien escuchando, no porque falte lugar: 350 caracteres son ~35 segundos, y un resumen de más de un minuto ya no es un resumen. Si no entra, sacá un dato ENTERO del cuerpo — nunca cortes una frase por la mitad, y nunca te comas la oración de los caminos.

🔴 "voz" VA PRIMERO, apenas abrís la llave: `---RENDI---{"voz":"...","verdict":...`. No es un capricho de orden: el audio no puede empezar hasta que ese campo esté completo, y el usuario lo escucha SIN ver el JSON. Escribiéndolo último —que es lo que salía solo— el que tenía el parlante prendido se comía CINCO SEGUNDOS de silencio mirando la respuesta ya escrita en pantalla, mientras vos armabas las tarjetas. Escribiéndolo primero, empieza a hablar mientras las armás.
No es la prosa recortada — es otro texto, escrito para la OREJA:
- Montos REDONDEADOS y dichos como se dicen: "ochenta y cuatro mil dólares", no "US$ 84.210,37". Porcentajes con un decimal como mucho.
- NOMBRES de los activos, NUNCA los códigos. Decí "Bonar 2030", no "AL30"; "Nvidia", no "NVDA"; "Galicia", no "GGAL". El nombre sale del campo `name` de la posición en el snapshot — si una posición no lo trae, decí el código como palabra sólo si se puede pronunciar, y si no, evitá nombrarla.
- Nada que se lea con los ojos: sin tablas, sin listas, sin viñetas, sin paréntesis, sin flechas, sin símbolos (%, +, −, US$ se DICEN: "por ciento", "más", "menos", "dólares"), sin "como ves arriba" ni referencias a las tarjetas.
- Oraciones cortas, una idea cada una: el titular, el porqué, y lo único que hay que mirar.
- Mismo rioplatense de siempre.

🔴 TERMINA OFRECIENDO POR DÓNDE SEGUIR, igual que la prosa. Una última oración corta con DOS caminos, dichos como se dicen: "Si querés puedo mirar si está cara, o qué le pasaría a tu cartera si corrige." Esto se venía olvidando —la prosa cerraba con las puertas y el audio se cortaba antes— y el que sólo escucha, manejando o caminando, se quedaba sin enterarse de que podía seguir preguntando. No repitas la frase de la prosa palabra por palabra: son los mismos dos caminos dichos para la oreja, sin signos ni códigos.

🔴 "voz" VA EN TODA RESPUESTA CON CONTENIDO, TAMBIÉN EN LAS REPREGUNTAS. No depende de que haya tarjetas.
Si estás contestando algo real pero no hay nada visual que mostrar —una repregunta tipo "¿y qué hago con eso?", "¿vos qué harías?", una explicación, un consejo— igual mandá el bloque, con SÓLO el campo "voz" adentro: `---RENDI---{"voz":"..."}`. El usuario no ve nada de más (sin stats ni blocks no se dibuja ninguna tarjeta) y la conversación no se queda muda a mitad.
POR QUÉ IMPORTA: si la primera respuesta se escucha y la segunda no, el usuario se queda esperando una voz que nunca llega y no entiende por qué. Una conversación hablada se habla ENTERA.
ÚNICAS excepciones, donde no va ni el bloque ni "voz": saludos de una línea ("hola", "gracias"), y TODO el flujo de registro de operaciones (confirmaciones, resultado, undo).
"""

# ─── El respaldo: convertir un texto de PANTALLA en uno que se pueda decir ───
# El resumen hablado lo escribe Claude en el campo "voz". A veces se lo olvida
# —es un campo más adentro de un JSON que el usuario no ve, y lo que no se ve no
# se reclama—. Sin respaldo, esa respuesta simplemente no tiene audio y el
# usuario toca el parlante y no pasa nada.
#
# El respaldo usa el titular del bloque, que SÍ está casi siempre. Pero está
# escrito para los OJOS: "Cartera de USD 30k: +64% sin realizar" leído tal cual
# suena a fórmula. Esto lo traduce a algo pronunciable.
#
# Es un plan B a propósito modesto: no reescribe ni resume, sólo destraba los
# símbolos. Un titular leído siempre va a sonar peor que un resumen escrito para
# la oreja — por eso además se LOGUEA cada vez que se usa: si empieza a aparecer
# seguido, el problema está en el prompt, no acá.
_HABLABLE = [
    (re.compile(r"(?:US\$|USD)\s*([\d.,]+)\s*(?:k|K)\b"), r"\1 mil dólares"),
    (re.compile(r"(?:US\$|USD)\s*([\d.,]+)"), r"\1 dólares"),
    (re.compile(r"(?:AR\$|ARS)\s*([\d.,]+)"), r"\1 pesos"),
    (re.compile(r"(\d)\s*(?:k|K)\b"), r"\1 mil"),
    (re.compile(r"\s*%"), " por ciento"),
    (re.compile(r"(?<![\w])\+(?=\d)"), "más "),
    (re.compile(r"(?<![\w])[-−–](?=\d)"), "menos "),
    (re.compile(r"\bpp\b"), "puntos"),
    (re.compile(r"[()\[\]]"), " "),      # los paréntesis se leen "paréntesis"
    (re.compile(r"\s*[·•→←|]+\s*"), ". "),
    (re.compile(r"\s{2,}"), " "),
]


def hablable(texto: str) -> str:
    """Deja un texto de pantalla en condiciones de ser leído en voz alta."""
    out = texto or ""
    for rx, rep in _HABLABLE:
        out = rx.sub(rep, out)
    return out.strip(" .;,").strip()


# ─── Último respaldo: leer la PROSA, quitándole lo que sólo se ve ────────────
# Orden de preferencia para el texto hablado:
#   1. el campo "voz" (escrito para la oreja) — lo mejor
#   2. el titular del bloque, destrabado
#   3. ESTO: la prosa misma, limpiada
#
# El nivel 3 existe porque los niveles 1 y 2 dependen de que el modelo emita el
# bloque, y MEDIDO: con historial largo deja de emitirlo en las repreguntas. El
# resultado era que la primera respuesta sonaba y la segunda no — el usuario se
# queda esperando una voz que nunca llega. Entre una prosa imperfecta y el
# silencio, gana la prosa: una conversación hablada se habla entera.
#
# Lo que se saca son las oraciones que sólo tienen sentido MIRANDO ("te dejo los
# números en pantalla", "como ves arriba", "mirá la tabla"), que leídas en voz
# alta son absurdas. Es la objeción concreta que había contra leer la prosa, y
# es la que esta función responde.
_MIRAR = re.compile(
    r"(en pantalla|en la pantalla|como ves|ves arriba|acá arriba|más arriba|acá abajo|"
    r"más abajo|la tabla|el gráfico|las tarjetas|la tarjeta|el cuadro|te dejo los|"
    r"fijate arriba|mirá (?:la|el|arriba|abajo)|revisá (?:la|el) (?:tabla|gráfico))",
    re.IGNORECASE)
# Corta en el punto que cierra oración, sin partir "US$ 1.850,00" ni "S&P 500".
_ORACION = re.compile(r"(?<=[.!?])\s+")


def prosa_hablable(texto: str, max_chars: int = None) -> str:
    """La prosa de pantalla, lista para decirse: sin las oraciones que sólo
    tienen sentido mirando, sin símbolos, y cortada en oración completa."""
    tope = max_chars or MAX_CHARS
    limpio = []
    for oracion in _ORACION.split((texto or "").strip()):
        o = oracion.strip()
        if not o or _MIRAR.search(o):
            continue
        limpio.append(o)
    out = ""
    for o in limpio:
        cand = (out + " " + o).strip()
        if len(hablable(cand)) > tope:
            break
        out = cand
    if not out and limpio:          # la primera ya se pasa: se corta a mano
        out = limpio[0][:tope]
    return hablable(out)


_OPENAI_URL = "https://api.openai.com/v1/audio/speech"
# La primera llamada del día a OpenAI puede tardar más que las siguientes; el
# read timeout es por CHUNK, no por respuesta completa, así que 30 s es amplio.
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# UN cliente para todo el proceso, no uno por pedido. MEDIDO acá el 2026-09-12
# con la API de verdad: abrir la conexión de cero cuesta ~1 segundo entero del
# tiempo hasta el primer sonido (2,68 s en frío contra 1,60 s reusando la
# conexión, mismo texto, una llamada después de la otra). Reusar el pool es la
# diferencia entre "arranca casi al toque" y "tarda". httpx.Client es seguro
# entre hilos, que es como uvicorn corre los endpoints sincrónicos.
_client_lock = threading.Lock()
_shared_client = None


def _client():
    global _shared_client
    if _shared_client is None:
        with _client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client(timeout=_TIMEOUT)
    return _shared_client


class TTSUnavailable(RuntimeError):
    """No hay API key de OpenAI configurada — el endpoint responde 503."""


def _api_key() -> str:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise TTSUnavailable("OPENAI_API_KEY no está configurada")
    return key


def enabled() -> bool:
    """¿Está la voz configurada en este entorno? El frontend lo consulta para
    no mostrar el parlante en un deploy sin la clave (Railway antes de que se
    cargue la variable)."""
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


# ─── La firma: el endpoint sólo lee lo que Rendi escribió ────────────────────
# Sin esto, cualquiera con una cuenta usa /api/ai/voz como servicio de voz
# gratis a costa nuestra: manda el texto que quiera y se lo cantamos. Con esto,
# el backend FIRMA el resumen hablado en el mismo turno en que Claude lo genera
# y el endpoint sólo acepta texto que traiga su propia firma.
#
# ⚠️ NO se firma con SECRET_KEY. En este deploy esa clave es, además de la que
# firma los JWT, la API key de Anthropic y la que cifra las credenciales de
# brokers (hallazgo abierto). Preferimos VOZ_SIGNING_KEY, una variable propia
# que se puede rotar sin echar a nadie de su sesión; si no está, derivamos una
# SUBCLAVE por HKDF-SHA256 — el HMAC nunca expone la clave madre y la
# derivación agrega separación de dominio, pero es el plan B, no el plan.
_SIG_LEN = 32          # 16 bytes en hex — suficiente contra fuerza bruta online
_HKDF_INFO = b"rendi.voz.v1"


def _signing_key() -> bytes:
    own = (os.environ.get("VOZ_SIGNING_KEY") or "").strip()
    if own:
        return own.encode("utf-8")
    parent = (os.environ.get("SECRET_KEY") or "").encode("utf-8")
    if not parent:
        # Sin ninguna de las dos (tests, arranque en seco): clave de proceso.
        # Las firmas no sobreviven un reinicio, que es exactamente lo que
        # queremos en un entorno sin configurar.
        global _EPHEMERAL
        if _EPHEMERAL is None:
            _EPHEMERAL = os.urandom(32)
        return _EPHEMERAL
    return hmac.new(parent, _HKDF_INFO, hashlib.sha256).digest()


_EPHEMERAL: bytes | None = None


def sign(text: str) -> str:
    """Firma el texto hablado. El resultado viaja al frontend junto al texto y
    vuelve en el pedido de audio."""
    return hmac.new(_signing_key(), (text or "").encode("utf-8"),
                    hashlib.sha256).hexdigest()[:_SIG_LEN]


def verify(text: str, sig: str) -> bool:
    """¿Este texto lo escribió Rendi? Comparación en tiempo constante
    (`compare_digest`): con `==` el tiempo de respuesta filtra cuántos
    caracteres de la firma acertó quien prueba."""
    if not isinstance(sig, str) or not sig:
        return False
    return hmac.compare_digest(sign(text), sig.strip())


# ─── Cache por texto ─────────────────────────────────────────────────────────
# En memoria del proceso, con tope en BYTES (no en cantidad de entradas: un mp3
# de 24 s pesa ~390 KB y uno de 50 s casi el doble — contar entradas dejaría el
# techo de RAM librado al azar). LRU: la que hace más que nadie la pide se va
# primera. Railway corre un solo uvicorn, así que un dict de proceso alcanza;
# el día que haya más de una réplica esto degrada a "cada réplica su cache"
# —más llamadas a OpenAI, nunca un audio equivocado.
_CACHE_MAX_BYTES = 32 * 1024 * 1024
_cache: "OrderedDict[str, bytes]" = OrderedDict()
_cache_bytes = 0
_cache_lock = threading.Lock()


def cache_key(text: str) -> str:
    """Hash del texto Y de todo lo que cambia cómo suena. Si mañana se cambia
    la voz o las instrucciones, la clave cambia sola y nadie escucha un audio
    viejo con la voz nueva."""
    h = hashlib.sha256()
    for part in (MODEL, VOICE, AUDIO_FORMAT, INSTRUCTIONS, text or ""):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def cache_get(key: str) -> bytes | None:
    with _cache_lock:
        buf = _cache.get(key)
        if buf is not None:
            _cache.move_to_end(key)      # recién usada → última en irse
        return buf


def cache_put(key: str, buf: bytes) -> None:
    global _cache_bytes
    if not buf:
        return
    with _cache_lock:
        if key in _cache:
            _cache_bytes -= len(_cache.pop(key))
        _cache[key] = buf
        _cache_bytes += len(buf)
        while _cache_bytes > _CACHE_MAX_BYTES and _cache:
            _, old = _cache.popitem(last=False)
            _cache_bytes -= len(old)


def cache_stats() -> dict:
    with _cache_lock:
        return {"entries": len(_cache), "bytes": _cache_bytes, "texts": len(_texts)}


def cache_clear() -> None:
    """Sólo para los tests — producción no vacía el cache a mano."""
    global _cache_bytes
    with _cache_lock:
        _cache.clear()
        _cache_bytes = 0
        _texts.clear()
    with _inflight_lock:
        for ev in _inflight.values():
            ev.set()
        _inflight.clear()
    with _pagos_lock:
        _pagos.clear()


# ─── Un solo generador por texto ─────────────────────────────────────────────
# El cache resuelve la segunda escucha, pero no la SIMULTÁNEA: dos pedidos del
# mismo audio que llegan antes de que el primero termine encuentran el cache
# vacío los dos, y entonces los dos llaman a OpenAI y los dos cobran cuota. El
# usuario paga dos veces por un audio que va a escuchar una.
#
# No es un caso raro de laboratorio: pasa con un doble toque en play, con dos
# pestañas abiertas, y sobre todo porque un reproductor de audio del navegador
# puede pedir el mismo archivo más de una vez (reintentos, pedidos por rango).
#
# La guarda: el primero que llega SE QUEDA con la clave; los demás esperan a que
# termine y se sirven del cache, sin pagar nada. Si el primero falla, el
# siguiente puede reclamarla e intentar.
_INFLIGHT_WAIT = 25.0        # segundos; generar tarda 2-5 s, esto es el techo
_inflight = {}               # clave → Event que se prende al terminar
_inflight_lock = threading.Lock()


def claim(key: str) -> bool:
    """¿Me toca generar a mí? True = sí, y quedás obligado a llamar a `finish`.
    False = ya lo está generando otro; esperalo con `wait_for`."""
    with _inflight_lock:
        if key in _inflight:
            return False
        _inflight[key] = threading.Event()
        return True


def wait_for(key: str, timeout: float = _INFLIGHT_WAIT) -> bool:
    """Espera a que el que tenía la clave termine. Devuelve True si terminó
    (entonces mirá el cache; puede estar vacío si al otro le fue mal)."""
    with _inflight_lock:
        ev = _inflight.get(key)
    if ev is None:
        return True          # terminó entre que preguntamos y ahora
    return ev.wait(timeout)


def finish(key: str) -> None:
    """Suelta la clave y despierta a los que estaban esperando. Va SIEMPRE en un
    finally: si se olvida en un camino de error, los que esperan se quedan
    colgados hasta el timeout."""
    with _inflight_lock:
        ev = _inflight.pop(key, None)
    if ev is not None:
        ev.set()


# ─── Quién ya pagó este audio ────────────────────────────────────────────────
# 🔴 EL CASO QUE SE COBRABA DOS VECES, y es el más común de todos en un celular.
#
# El audio se cobra al empezar a generarlo y se guarda en el cache al
# terminarlo. Entre esas dos cosas está el viaje, y el viaje se corta: se va la
# señal, el usuario navega, o el propio reproductor del navegador abre y cierra
# el pedido (lo hace solo, para leer la duración). Ese corte llega como
# GeneratorExit, que NO lo atrapa un `except Exception` — así que no se guarda
# nada en el cache y tampoco se devuelve la ficha.
#
# Resultado: el segundo intento no encuentra nada cacheado y COBRA DE NUEVO.
# Para un Free, que tiene UNA escucha por semana, la primera conexión floja le
# quema la semana entera sin haber oído la respuesta completa.
#
# Acá se anota quién ya pagó qué. Si vuelve el mismo usuario por el mismo audio,
# no se le cobra otra vez: es exactamente la regla de producto que ya estaba
# escrita —"re-escuchar es gratis"—, que hasta ahora sólo valía si el primer
# intento había llegado hasta el final.
#
# Se olvida sola a la media hora y tiene tope de entradas: es una marca para
# cubrir un reintento, no un registro contable.
_PAGOS_TTL = 1800.0
_PAGOS_MAX = 5000
# 🔴 CUÁNTAS VECES SE PERDONA, y por qué tiene que haber un número.
#
# Perdonar el reintento le saca al pedido del audio su ÚNICO freno: ese endpoint
# no tiene límite por minuto propio, y hasta ahora lo frenaba la cuota, que se
# descontaba en cada generación. Con el perdón puesto sin tope, alguien que pide
# el audio y corta, una y otra vez, hace que le generemos el mp3 en OpenAI todas
# las veces que quiera habiendo pagado UNA.
#
# Tres alcanza de sobra para lo que esto existe: un corte de señal se reintenta
# una o dos veces. A la cuarta ya no es un corte, y vuelve a cobrarse.
_PERDONES_MAX = 3
_pagos = {}                  # (uid, clave) → [cuándo se pagó, perdones usados]
_pagos_lock = threading.Lock()


def marcar_pago(uid: int, key: str) -> None:
    """Este usuario ya pagó este audio."""
    ahora = time.time()
    with _pagos_lock:
        if len(_pagos) >= _PAGOS_MAX:
            corte = ahora - _PAGOS_TTL
            for k in [k for k, v in _pagos.items() if v[0] < corte]:
                del _pagos[k]
            if len(_pagos) >= _PAGOS_MAX:
                _pagos.clear()
        # Un pago nuevo reinicia los perdones: pagó de nuevo, empieza de cero.
        _pagos[(uid, key)] = [ahora, 0]


def ya_pago(uid: int, key: str, consumir: bool = False) -> bool:
    """¿Ya pagó este audio y se le cortó? Entonces el reintento es gratis.

    `consumir=True` va SÓLO donde el perdón se usa de verdad, o sea donde se
    iba a generar el audio. El otro llamador —el paso que dice dónde está el
    archivo— pregunta sin gastar: si consumiera, cada reintento gastaría dos
    perdones en vez de uno y el tope sería la mitad de lo que dice.
    """
    with _pagos_lock:
        v = _pagos.get((uid, key))
        if v is None:
            return False
        cuando, perdones = v
        if time.time() - cuando > _PAGOS_TTL:
            del _pagos[(uid, key)]
            return False
        if perdones >= _PERDONES_MAX:
            return False
        if consumir:
            v[1] = perdones + 1
        return True


def olvidar_pago(uid: int, key: str) -> None:
    """Se le devolvió la ficha (no escuchó nada): la marca se borra, si no el
    próximo intento saldría gratis sin haber pagado ninguno."""
    with _pagos_lock:
        _pagos.pop((uid, key), None)


def inflight_count() -> int:
    """Cuántas generaciones hay en curso. Sólo para tests y diagnóstico."""
    with _inflight_lock:
        return len(_inflight)


# ─── El texto guardado por clave ─────────────────────────────────────────────
# POR QUÉ EXISTE ESTA SEGUNDA TABLITA (y no alcanza con el cache de audio):
# el navegador reproduce el audio con un `<audio src="…">`, que es un GET — la
# única forma de que empiece a sonar apenas llegan los primeros bytes SIN
# librerías raras, y la única que anda en el Safari del iPhone. Un GET no
# lleva cuerpo, y el texto hablado NO puede ir en la dirección: son los números
# de la cartera del usuario, y las direcciones quedan en registros y en el
# historial del navegador.
#
# Solución: el navegador manda el texto UNA vez por POST, el servidor se lo
# guarda bajo su hash, y el `<audio>` pide después /api/ai/voz/<hash>.mp3 — una
# dirección que no dice nada de nadie.
#
# Tabla aparte del audio a propósito: los textos pesan nada (600 bytes) y
# sobreviven a que el audio se caiga del cache por tamaño. Si se perdiera el
# texto, no habría con qué regenerar y el usuario vería un audio roto.
_TEXTS_MAX = 2000
_texts: "OrderedDict[str, str]" = OrderedDict()


def remember(text: str) -> str:
    """Guarda el texto y devuelve la clave con la que pedirlo. Idempotente:
    el mismo texto da siempre la misma clave."""
    key = cache_key(text)
    with _cache_lock:
        if key in _texts:
            _texts.move_to_end(key)
        else:
            _texts[key] = text
            while len(_texts) > _TEXTS_MAX:
                _texts.popitem(last=False)
    return key


def recall(key: str) -> str | None:
    """El texto guardado bajo esa clave, o None si nunca se guardó o ya se
    cayó de la tabla (reinicio del proceso). El endpoint responde 404 y el
    navegador vuelve a mandar el texto — no hay pérdida visible."""
    with _cache_lock:
        text = _texts.get(key)
        if text is not None:
            _texts.move_to_end(key)
        return text


# ─── Generar el audio ────────────────────────────────────────────────────────

def speak(text: str) -> Iterator[bytes]:
    """Devuelve el mp3 en pedazos, a medida que OpenAI lo genera.

    Es un GENERADOR a propósito: el primer pedazo llega en ~1,4 s y el archivo
    entero en ~4,5 s. Materializar todo antes de devolver (`.read()`) triplica
    la espera que siente el usuario. Ver la nota 1 de arriba.

    No cachea: el que consume decide si guarda (necesita el buffer completo, y
    sólo debe guardarlo si el stream terminó bien).
    """
    body = {
        "model": MODEL,
        "voice": VOICE,
        "input": text,
        "instructions": INSTRUCTIONS,
        "response_format": AUDIO_FORMAT,
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    with _client().stream("POST", _OPENAI_URL, json=body, headers=headers) as resp:
        if resp.status_code != 200:
            # El cuerpo del error de OpenAI es JSON chiquito; lo leemos para el
            # log (nunca va al usuario: puede nombrar la cuenta).
            detail = resp.read().decode("utf-8", "replace")[:300]
            log.error("OpenAI TTS %s: %s", resp.status_code, detail)
            raise RuntimeError("OpenAI TTS devolvió %s" % resp.status_code)
        for chunk in resp.iter_bytes():
            if chunk:
                yield chunk


# Caracteres por segundo de audio. NO es el promedio medido (9,4-13,7 según
# cuántas cifras tenga el texto): es el extremo CONSERVADOR, redondeado hacia
# abajo. Se usa para estimar el costo, y de los dos errores posibles el caro es
# subestimar — un costo que da más bajo de lo real es el que hace que nadie se
# entere de que el margen se fue. Ver el encabezado para las dos mediciones.
# Si se cambia INSTRUCTIONS, hay que volver a medir CON UN TEXTO LLENO DE CIFRAS.
CHARS_PER_SECOND = 10


def estimated_seconds(text: str) -> float:
    """Cuánto va a durar el audio. Sirve para el log de costo sin tener que
    decodificar el mp3."""
    return round(len(text or "") / CHARS_PER_SECOND, 1)
