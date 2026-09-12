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

COSTO: US$0,015 por minuto de audio, y con estas instrucciones la voz va a
13,3-14,4 caracteres por segundo (medido sobre el mp3: 263 caracteres → 18,2 s;
195 → 14,9 s; 145 → 10,9 s). Un resumen de ~290 caracteres dura ~21 s y sale
~US$0,0053.

⚠️ El plan había anotado 12 caracteres/segundo y US$0,0061. La diferencia juega
A FAVOR: la regla "escuchar cuesta 1 ficha más" cierra con MÁS margen del que se
creía. El empate —donde el audio costaría lo mismo que la respuesta escrita,
US$0,007— son 28 segundos ≈ 378 caracteres. MAX_CHARS_SOFT avisa mucho antes;
su propio comentario explica en cuánto y por qué.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
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
# son ~44 segundos de audio (a 13,5 c/s) — el doble del molde, ya generoso.
MAX_CHARS = 600
# Tope BLANDO: el aviso de que los resúmenes se están estirando. No rechaza
# nada — loguea.
#
# Está en 260 y no pegado al techo económico a propósito. El empate (donde el
# audio cuesta lo mismo que la respuesta escrita, US$0,007) son 378 caracteres;
# avisar recién ahí sería avisar cuando ya no queda margen. 260 es un aviso
# TEMPRANO, calibrado con lo que el modelo escribe DE VERDAD: los resúmenes
# reales medidos en pantalla dieron 195 y 224 caracteres, bastante por debajo de
# los ~290 que pide el prompt. O sea que este umbral no se dispara con la
# salida normal: se dispara cuando algo cambió.
MAX_CHARS_SOFT = 260

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
Agregá al JSON un campo más, "voz": la MISMA respuesta contada en voz alta, en 3 oraciones, apuntá a 290 caracteres (nunca más de 600).
No es la prosa recortada — es otro texto, escrito para la OREJA:
- Montos REDONDEADOS y dichos como se dicen: "ochenta y cuatro mil dólares", no "US$ 84.210,37". Porcentajes con un decimal como mucho.
- NOMBRES de los activos, NUNCA los códigos. Decí "Bonar 2030", no "AL30"; "Nvidia", no "NVDA"; "Galicia", no "GGAL". El nombre sale del campo `name` de la posición en el snapshot — si una posición no lo trae, decí el código como palabra sólo si se puede pronunciar, y si no, evitá nombrarla.
- Nada que se lea con los ojos: sin tablas, sin listas, sin viñetas, sin paréntesis, sin flechas, sin símbolos (%, +, −, US$ se DICEN: "por ciento", "más", "menos", "dólares"), sin "como ves arriba" ni referencias a las tarjetas.
- Oraciones cortas, una idea cada una: el titular, el porqué, y lo único que hay que mirar.
- Mismo rioplatense de siempre. Si la respuesta es un saludo, una aclaración breve o cualquier paso del registro de operaciones, OMITÍ "voz" (igual que el bloque entero).
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


# Velocidad real del habla con estas instrucciones. Medida sobre el mp3, no
# estimada: ver el encabezado. Si se cambia INSTRUCTIONS, hay que re-medirla.
CHARS_PER_SECOND = 13.5


def estimated_seconds(text: str) -> float:
    """Cuánto va a durar el audio. Sirve para el log de costo sin tener que
    decodificar el mp3."""
    return round(len(text or "") / CHARS_PER_SECOND, 1)
