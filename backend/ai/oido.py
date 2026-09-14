"""oido — pasar a texto lo que el usuario le dice a Rendi.
═══════════════════════════════════════════════════════════════════════════
Es el espejo de `tts.py`: aquél convierte texto de Rendi en audio, éste
convierte audio del usuario en texto. Los dos son el ÚNICO lugar del backend
que le habla a OpenAI, y por el mismo motivo — si algún día se cambia de
proveedor, se cambia acá y en ningún otro lado.

POR QUÉ OPENAI Y NO EL RECONOCIMIENTO DEL NAVEGADOR

El navegador trae uno gratis (`SpeechRecognition`) y la tentación es obvia.
Tres cosas lo descartan:

  1. Manda la voz del usuario a Google (Chrome) o a Apple (Safari) — un
     tercero MÁS, que no está en nuestra política de privacidad y que el
     usuario no eligió. Con OpenAI ya hay una relación declarada y un solo
     procesador que nombrar.
  2. Firefox no lo tiene. Sería una función que aparece o no según el
     navegador, sin manera de explicárselo al usuario.
  3. Y la que más pesa: no se le puede enseñar vocabulario. Acá le pasamos
     los activos que el usuario TIENE (ver `pista_de_activos`), que es lo
     que hace que "AL30" salga "AL30" y no "a ele treinta".

CUÁNTO SALE: US$0,006 el minuto. Una pregunta dictada de diez segundos son
US$0,001 — el 5% de lo que sale la respuesta escrita (US$0,021, ver tts.py).
Por eso dictar NO gasta cuota aparte: es una forma de escribir, y cobrarla
necesitaría un tercer contador para un costo que es ruido.

LO QUE NO SE GUARDA: el audio. Entra, se manda, vuelve texto y se descarta.
No hay cache —no tendría sentido, nadie dicta dos veces lo mismo— ni queda
en disco. Lo que el usuario dijo queda sólo como el texto que él después
revisa y manda.
"""

from __future__ import annotations

import io
import logging
import os
import re
import threading
from typing import Iterable, Optional

import httpx

log = logging.getLogger("ai.oido")

# `gpt-4o-mini-transcribe` contra `whisper-1`: el mini es más barato y más
# nuevo, pero whisper-1 es el único que acepta `prompt` para sesgar el
# vocabulario — y el vocabulario es justamente lo que hace que los tickers y
# los bonos argentinos salgan bien. Sin esa pista, "AL30" sale "al 30".
MODELO = "whisper-1"

# El idioma va FIJO. Sin esto el modelo adivina, y una frase corta con un
# ticker en inglés ("¿cómo viene Apple?") la puede tomar por inglés y
# devolver la transcripción traducida.
IDIOMA = "es"

# Tope de grabación. 30 segundos es una pregunta larga dicha con comodidad;
# más que eso ya es un monólogo que además transcribe peor (el modelo pierde
# el hilo) y cuesta más. El navegador corta solo al llegar; esto es la red.
MAX_SEGUNDOS = 30
# Tope de bytes, que es el que de verdad protege al servidor: el navegador
# puede mentir sobre la duración, no sobre cuánto pesa lo que manda.
# 30 s de webm/opus a 32 kbps son ~120 KB; 4 MB deja aire para formatos
# peores (wav sin comprimir) sin abrir la puerta a que suban una película.
MAX_BYTES = 4 * 1024 * 1024

# Lo que el navegador puede mandar. MediaRecorder produce webm en Chrome y
# Firefox, y mp4/aac en Safari; los otros están porque OpenAI los acepta y no
# cuesta nada aceptarlos nosotros.
FORMATOS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/mpga": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/flac": "flac",
}

_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
# Acá no hay streaming: se manda el archivo entero y se espera el texto. 60 s
# de lectura es amplio para 30 s de audio.
_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

_shared_client: Optional[httpx.Client] = None
_client_lock = threading.Lock()


def _client() -> httpx.Client:
    """Un cliente por proceso, igual que en tts.py: abrir una conexión TLS
    nueva por pedido agrega casi un segundo, y acá el usuario está esperando
    con el dedo en el botón."""
    global _shared_client
    if _shared_client is None:
        with _client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client(timeout=_TIMEOUT)
    return _shared_client


class OidoUnavailable(RuntimeError):
    """No hay API key de OpenAI — el endpoint responde 503, igual que la voz."""


def _api_key() -> str:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise OidoUnavailable("OPENAI_API_KEY no está configurada")
    return key


def enabled() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


# ─── La pista de vocabulario ─────────────────────────────────────────────────
# El `prompt` de whisper NO es una instrucción: es un texto de ejemplo que
# sesga qué palabras espera oír. Sirve para nombres propios y códigos, que es
# exactamente donde falla solo.
#
# 🔴 Y TIENE UN TOPE DE 224 TOKENS. Mandarle los 509 activos del catálogo
# hace que ignore el final de la lista — o sea, justo lo que uno creía estar
# enseñándole. Por eso se mandan SÓLO los que el usuario tiene: son entre 4 y
# 20, entran cómodos, y son los únicos que va a nombrar. Un usuario que no
# tiene Nvidia no va a preguntar por Nvidia.
#
# LA PISTA TAMBIÉN MARCA EL ESTILO, no sólo el vocabulario. Whisper imita la
# forma del texto que le das: si la pista escribe los montos como se escriben
# acá, los devuelve así. MEDIDO: sin la frase de ejemplo, "sesenta y cinco
# mil" volvía como "$65,000" —con la coma de los miles en inglés, que acá se
# lee como sesenta y cinco con cero— y eso en un registro de operación se
# carga en la cartera y queda.
_PISTA_BASE = (
    "Consulta sobre inversiones en Argentina, en español rioplatense. "
    "Se habla de dólares, pesos, MEP, CEDEAR, plazo fijo, bonos, FCI, "
    "acciones, cartera, rendimiento y comisiones. "
    "Ejemplos: compré 100 dólares a 65.000; deposité 600.000 pesos; "
    "vendí 20 acciones a 490 dólares."
)
# Cuántos activos entran. 24 tickers con su nombre son ~120 tokens; sumado a
# la base queda bien debajo del tope, con margen para nombres largos.
_MAX_ACTIVOS_EN_LA_PISTA = 24
# Nadie opera con más de esta cantidad de casas a la vez, y cada nombre es
# corto, así que no aprietan el presupuesto del prompt.
_MAX_BROKERS_EN_LA_PISTA = 8
_TICKER_OK = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


# Los nombres de broker son marcas inventadas y el modelo las lleva a la
# palabra común más parecida si no las conoce. MEDIDO: "Balanz" volvía
# "Balance". Por eso los brokers del usuario también entran en la pista.
_BROKER_OK = re.compile(r"^[\w .&\-áéíóúüñÁÉÍÓÚÜÑ]{2,32}$")


def pista(tickers: Optional[Iterable[str]] = None,
          brokers: Optional[Iterable[str]] = None) -> str:
    """El texto que se le pasa a whisper para que reconozca lo propio del
    usuario: sus activos y sus brokers.

    De cada activo van el CÓDIGO y el NOMBRE ("NVDA, Nvidia") porque el
    usuario dice cualquiera de los dos y los dos tienen que salir bien.

    Lo que no pasa el filtro se descarta en silencio: esto termina en un
    proveedor externo, y un "ticker" o un "broker" con texto libre adentro
    sería una forma de escribirle a OpenAI lo que uno quiera.
    """
    from .asset_names import asset_name

    activos = []
    vistos = set()
    for t in (tickers or []):
        code = str(t or "").strip().upper()
        if not code or code in vistos or not _TICKER_OK.match(code):
            continue
        vistos.add(code)
        nombre = asset_name(code)
        activos.append("%s, %s" % (code, nombre) if nombre else code)
        if len(activos) >= _MAX_ACTIVOS_EN_LA_PISTA:
            break

    casas = []
    vistas = set()
    for b in (brokers or []):
        n = " ".join(str(b or "").split())
        if not n or n.lower() in vistas or not _BROKER_OK.match(n):
            continue
        vistas.add(n.lower())
        casas.append(n)
        if len(casas) >= _MAX_BROKERS_EN_LA_PISTA:
            break

    out = _PISTA_BASE
    if activos:
        out += " Activos de la cartera: %s." % "; ".join(activos)
    if casas:
        out += " Brokers: %s." % ", ".join(casas)
    return out


# Compatibilidad hacia atrás con el nombre viejo, por si quedó algún llamador.
def pista_de_activos(tickers: Optional[Iterable[str]] = None) -> str:
    return pista(tickers)


# ─── Pasar el audio a texto ──────────────────────────────────────────────────

class AudioInvalido(ValueError):
    """Lo que llegó no se puede mandar: vacío, pesado de más o de un formato
    que no aceptamos. Nunca llega a OpenAI."""


def extension_de(content_type: str) -> str:
    """El formato, o revienta. OpenAI decide cómo decodificar por el NOMBRE
    del archivo, así que mandar el sufijo equivocado hace que rechace un
    audio perfectamente válido."""
    base = (content_type or "").split(";")[0].strip().lower()
    ext = FORMATOS.get(base)
    if not ext:
        raise AudioInvalido("Formato de audio no soportado: %r" % base)
    return ext


def escuchar(audio: bytes, content_type: str, pista: str = "",
             tickers: Optional[Iterable[str]] = None,
             brokers: Optional[Iterable[str]] = None) -> str:
    """Devuelve lo que se dijo, en texto. Cadena vacía si no se escuchó nada.

    `pista` es el vocabulario esperado (ver `pista`), que va ANTES de
    transcribir. `tickers` y `brokers` son el mismo vocabulario usado DESPUÉS,
    para corregir los homófonos que la pista no alcanza a ganar (ver
    corregir_con_lo_del_usuario). Los dos son opcionales: sin ellos transcribe
    igual, sólo que los nombres propios salen peor.
    """
    if not audio:
        raise AudioInvalido("No llegó audio")
    if len(audio) > MAX_BYTES:
        raise AudioInvalido("El audio pesa %d bytes, el tope es %d" % (len(audio), MAX_BYTES))
    ext = extension_de(content_type)

    data = {"model": MODELO, "language": IDIOMA, "response_format": "json"}
    if pista:
        data["prompt"] = pista
    resp = _client().post(
        _OPENAI_URL,
        headers={"Authorization": "Bearer %s" % _api_key()},
        data=data,
        files={"file": ("dictado.%s" % ext, io.BytesIO(audio), content_type)},
    )
    if resp.status_code != 200:
        # El cuerpo del error puede nombrar la cuenta: va al log, nunca al
        # usuario. Mismo criterio que tts.py.
        log.error("OpenAI transcripción %s: %s", resp.status_code, resp.text[:300])
        raise RuntimeError("OpenAI devolvió %s" % resp.status_code)
    texto = (resp.json().get("text") or "").strip()
    texto = corregir_con_lo_del_usuario(texto, tickers, brokers)
    return limpiar(texto)


# ─── Corregir con lo que el usuario TIENE ────────────────────────────────────
# La pista mete la palabra en el vocabulario, pero no gana contra un homófono
# común. MEDIDO, y las dos veces con la pista puesta:
#     "¿Está cara Nvidia hoy?"      -> "¿Está cara envidia hoy?"
#     "…pesos en Balanz"            -> "…pesos en Balance"
# En rioplatense suenan casi igual, así que el modelo elige la palabra de
# diccionario. Es razonable de su parte: no sabe que este usuario tiene Nvidia.
#
# Nosotros sí. Por eso acá se compara cada palabra de la transcripción contra
# los nombres propios de ESTE usuario y se cambia sólo cuando la diferencia es
# mínima. Es angosto a propósito:
#   · sólo contra SUS activos y SUS brokers — nunca contra un catálogo general,
#     porque ahí empezaría a "corregir" palabras normales hacia tickers que no
#     tiene;
#   · sólo palabras de 5 letras o más, que abajo de eso todo se parece a todo;
#   · y con una diferencia de 1 o 2 letras como mucho.
#
# ⚠️ Y TIENE UN COSTO, medido: "tengo envidia de lo que ganaste" sale "tengo
# NVIDIA de lo que ganaste". Es el precio de acertar el caso frecuente. Se
# acepta por dos razones: en un chat sobre plata, "Nvidia" es muchísimo más
# probable que "envidia"; y el texto NO se manda solo — el usuario lo lee en el
# cuadro y lo corrige de un toque. Esa pantalla de revisión es justo lo que
# permite que esta corrección sea agresiva sin ser peligrosa. Si algún día el
# texto se mandara solo, esto hay que apagarlo.
#
# Cada cambio queda en el log: si empieza a aparecer sobre palabras normales,
# el dato está para subir el umbral.
_MIN_LARGO_PARA_CORREGIR = 5


def _sin_tildes(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _distancia(a: str, b: str) -> int:
    """Cuántas letras hay que cambiar para pasar de una palabra a la otra."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 99
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previa[j] + 1, actual[j - 1] + 1,
                              previa[j - 1] + (ca != cb)))
        previa = actual
    return previa[-1]


def corregir_con_lo_del_usuario(texto: str,
                                tickers: Optional[Iterable[str]] = None,
                                brokers: Optional[Iterable[str]] = None) -> str:
    """Devuelve el texto con los nombres propios del usuario restituidos."""
    from .asset_names import asset_name

    if not texto:
        return texto
    # El vocabulario: el nombre hablable de cada activo y cada broker.
    propios = []
    for t in (tickers or []):
        code = str(t or "").strip().upper()
        if _TICKER_OK.match(code or ""):
            n = asset_name(code)
            if n and len(n) >= _MIN_LARGO_PARA_CORREGIR and " " not in n:
                propios.append(n)
    for b in (brokers or []):
        n = " ".join(str(b or "").split())
        if _BROKER_OK.match(n or "") and len(n) >= _MIN_LARGO_PARA_CORREGIR and " " not in n:
            propios.append(n)
    if not propios:
        return texto

    def reemplazo(m):
        palabra = m.group(0)
        if len(palabra) < _MIN_LARGO_PARA_CORREGIR:
            return palabra
        plana = _sin_tildes(palabra)
        mejor, mejor_d = None, 99
        for p in propios:
            if plana == _sin_tildes(p):
                return palabra          # ya está bien escrita
            d = _distancia(plana, _sin_tildes(p))
            if d < mejor_d:
                mejor, mejor_d = p, d
        if mejor is not None and 1 <= mejor_d <= 2:
            log.info("oido: %r -> %r (es de la cartera del usuario)", palabra, mejor)
            return mejor
        return palabra

    return re.sub(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", reemplazo, texto)


# ─── Limpiar lo que vuelve ───────────────────────────────────────────────────
# Whisper devuelve, sobre silencio o ruido, una de un puñado de frases que
# aprendió de los subtítulos con los que se entrenó: "Subtítulos realizados
# por la comunidad de Amara.org", "¡Gracias por ver el video!" y parientes.
# No son transcripciones: son alucinaciones conocidas, y aparecen justo
# cuando el usuario tocó el micrófono sin querer. Mandarlas al chat como si
# las hubiera dicho él es peor que no devolver nada.
_ALUCINACIONES = re.compile(
    r"(amara\.?org|subt[ií]tulos?\s+(realizados?|por)|gracias\s+por\s+ver|"
    r"suscr[ií]b[aei]te|www\.|\.com\b)",
    re.IGNORECASE)
# Debajo de esto no hay una pregunta: es un carraspeo o una palabra suelta.
MINIMO_CARACTERES = 2


def limpiar(texto: str) -> str:
    """El texto listo para poner en el cuadro, o cadena vacía si no hay nada.

    Vacío significa "no se escuchó nada" y el frontend muestra ese aviso —
    que es la verdad, y deja al usuario probar de nuevo o escribir.
    """
    t = " ".join((texto or "").split())
    if len(t) < MINIMO_CARACTERES:
        return ""
    if _ALUCINACIONES.search(t):
        log.info("oido: descartada una alucinación de silencio: %r", t[:80])
        return ""
    return t
