"""tts — Rendi LEÍDA en voz alta. El único lugar que habla con OpenAI.
═══════════════════════════════════════════════════════════════════════════
Claude PIENSA la respuesta (el /api/ai/chat de siempre, con sus 16 tools y sus
guardias); este módulo sólo la LEE. Anthropic no vende API de voz a terceros,
así que la lectura la hace `gpt-4o-mini-tts` de OpenAI con la voz `fable`
—elegida escuchando las 11— y nada más: acá no se decide QUÉ se dice.

TRES COSAS QUE SE MIDIERON CON LA API DE VERDAD (2026-09-11/12) Y MANDAN SOBRE
EL DISEÑO DE ESTE ARCHIVO
--------------------------------------------------------------------------
1. STREAMING O NADA. El primer pedacito de audio llega en 1,35-1,43 s; el
   archivo entero, en 4,3-4,7 s. Esperar el mp3 completo antes de mandarlo
   sube la espera total de ~4 s a ~9 s y se siente roto. Por eso `speak()` es
   un generador y el endpoint lo reenvía a medida que llega.
2. EL CACHE NO ES UNA OPTIMIZACIÓN, ES LA FUNCIONALIDAD. La decisión de
   producto es "re-escuchar una respuesta es gratis, siempre". Eso sólo se
   sostiene si el mismo texto no se vuelve a generar nunca. Cache por hash del
   texto (+ voz + modelo + instrucciones: si cambia cualquiera, cambia la
   clave y se regenera).
3. PEDIRLE AL MODELO QUE HABLE MÁS RÁPIDO NO HACE NADA. El mismo texto con
   "ritmo ágil" dio 24,2 s y con "hablá RÁPIDO, ritmo de podcast" dio 24,4 s.
   La velocidad se controla SOLO con playbackRate en el navegador. Las
   instrucciones de abajo piden ritmo igual —ayudan al acento y a la energía,
   no al reloj—, pero no esperes que ahorren un centavo.

FORMATO: mp3, no opus. Opus pesa la mitad (220 KB vs 388 KB) y el primer
pedacito llega igual de rápido, pero Safari de iPhone no reproduce opus en
contenedor ogg — y el celular de Nico es donde esto se va a probar. Cuando el
acompañante corra sólo en escritorio, opus es mejor negocio.

COSTO: US$0,015 por minuto de audio, y con las instrucciones de acá la voz va
a 13,3-14,4 caracteres por segundo (MEDIDO el 2026-09-12 sobre el mp3 que
devuelve la API: 263 caracteres → 18,2 s; 145 → 10,9 s). Un resumen de ~290
caracteres dura ~21 s y sale ~US$0,0053.

⚠️ El plan de la etapa había anotado 12 caracteres/segundo y US$0,0061. La
diferencia juega A FAVOR: la regla "escuchar cuesta 1 ficha más" cierra con más
margen del que se creía, no con menos. El punto donde el audio empataría con lo
que cuesta la respuesta escrita (US$0,007) son 28 segundos ≈ 378 caracteres —
por eso MAX_CHARS_SOFT está en 340: avisa ANTES de llegar ahí.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
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
# Tope BLANDO: el aviso ANTES de que la cuenta se ponga fea. A 13,5 c/s, 340
# caracteres son ~25 s = US$0,0063, todavía por debajo de los US$0,007 que
# cuesta la respuesta escrita. No rechaza nada: loguea, para que se note si el
# prompt derivó y los resúmenes empezaron a estirarse.
MAX_CHARS_SOFT = 340

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
