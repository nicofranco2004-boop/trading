"""whatsapp — la puerta de WhatsApp a Rendi (API oficial de Meta, «Cloud API»).
═══════════════════════════════════════════════════════════════════════════
El bot de WhatsApp NO es una inteligencia artificial nueva: es otra puerta al
MISMO chat que la app ya tiene (`main._ai_chat_core`), el que lee la cartera y
anota compras, ventas y depósitos con confirmación. Lo único que vive acá es lo
que WhatsApp tiene de distinto:

  · cómo se comprueba que un aviso vino de verdad de Meta (la firma);
  · cómo se lee el aviso (qué número escribió, qué dijo, de qué tipo);
  · cómo se le contesta (texto, botones Sí/No) y hasta qué largo;
  · el código con el que una persona vincula su número a su cuenta.

Nada de esto toca la base ni la IA: son funciones puras más el cliente HTTP a
Meta, para poder probarlas sin servidor. Quién atiende cada mensaje (busca la
cuenta, arma la foto, llama al chat) está en main.py («WhatsApp: el bot»).

POR QUÉ DIRECTO A META Y NO POR UN INTERMEDIARIO (Twilio, 360dialog)
Cobran por mensaje encima de Meta y son una empresa más que lee el contenido.
Lo que dan (panel, alta más fácil) no hace falta: el panel es la app.

LA REGLA DE META QUE IMPORTA (desde el 15/01/2026): prohibidos los bots de IA
«de uso general». El de Rendi habla de TU cartera y del mercado; las
instrucciones del chat ya lo acotan y acá se refuerza (`SISTEMA_WHATSAPP`).

CUÁNTO SALE: contestarle a quien escribió, dentro de las 24 h, es gratis en
Meta. Lo que se paga es la IA, igual que en la app (~US$ 0,02 por respuesta),
y descuenta del MISMO cupo semanal del plan.

Variables de entorno (ver .env.example, bloque WhatsApp):
  WHATSAPP_TOKEN            token permanente del usuario de sistema de Meta
  WHATSAPP_PHONE_NUMBER_ID  el id del número del bot (no el número)
  WHATSAPP_APP_SECRET       «App Secret» de la app de Meta: firma los avisos
  WHATSAPP_VERIFY_TOKEN     la palabra que Meta manda al dar de alta el webhook
  WHATSAPP_NUMERO           el número del bot con código de país, sólo dígitos
                            (para el link wa.me que abre la app)
  WHATSAPP_GRAPH_VERSION    opcional: la versión de la API de Meta (ver `graph()`)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger(__name__)

# El interruptor de /admin (tabla `interruptores`). Sin fila = apagado: el bot
# sale publicado a oscuras y se prende sin deploy.
INTERRUPTOR = "bot_whatsapp"

# La función del plan que lo habilita (ai/plan.py). Decisión de Nico 26/11/2026:
# sólo Pro (y admin). Se llama `ai.…` porque ES la IA: la regla de la casa es que
# el Plus iguala al Pro en todo lo que no es IA (tests/test_plus_sin_ia.py).
FEATURE = "ai.whatsapp"

# La versión de la API de Meta. Cada versión vive ~2 años y después Meta la
# apaga (v21.0 muere el 21/01/2027). Se puede adelantar o atrasar sin deploy
# con WHATSAPP_GRAPH_VERSION si una versión nueva rompe algo.
GRAPH_VERSION_DEFAULT = "v26.0"


def graph() -> str:
    v = (os.environ.get("WHATSAPP_GRAPH_VERSION") or "").strip() or GRAPH_VERSION_DEFAULT
    return f"https://graph.facebook.com/{v}"


TIMEOUT = 10.0

# Meta corta los textos a 4096 caracteres. Se parte antes para que no se pierda
# el final de una respuesta larga.
MAX_TEXTO = 4000

# Cuánto vive un código de vinculación sin usarse.
CODIGO_MINUTOS = 15

# Alfabeto sin letras y números que se confunden (0/O, 1/I/L).
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# «RENDI ABC123» en cualquier parte del mensaje, o el mensaje que ES el código
# a secas. NO cualquier palabra de 6 letras: «VENTAS» o «CUANTO» tienen la
# forma de un código y harían que una pregunta normal se tome por un intento
# de vincular (y a un número sin cuenta le diría «código inválido» en vez de
# explicarle cómo conectarse).
_CODIGO_CON_RENDI_RE = re.compile(r"RENDI[\s:\-]*([" + _ALFABETO + r"]{6})\b")
_CODIGO_SOLO_RE = re.compile(r"^[^A-Z0-9]*([" + _ALFABETO + r"]{6})[^A-Z0-9]*$")

# Mismo delimitador tolerante que main._RENDI_DELIM_RE y que el navegador
# (utils/aiStructured.js): el modelo a veces escribe "--- RENDI ---".
RENDI_DELIM_RE = re.compile(r"-{3,}\s*RENDI\s*-{3,}")

# Los ids de los botones Sí/No. Al tocarlos, Meta manda el id; se traduce a la
# palabra que el chat ya entiende (`main._confirm_word`).
BOTON_SI = "wa_si"
BOTON_NO = "wa_no"
PALABRA_DEL_BOTON = {BOTON_SI: "sí", BOTON_NO: "no"}

# ── Lo que se le suma al manifiesto del chat cuando el canal es WhatsApp ────
# Va como un bloque MÁS del sistema (no adentro del manifiesto): el manifiesto
# es idéntico para todos los pedidos y Anthropic lo cobra una vez; un bloque
# aparte se cachea solo y no rompe el del resto.
SISTEMA_WHATSAPP = (
    "CANAL: esta conversación es por WhatsApp, no por la app. Cambia el FORMATO, "
    "no la voz. Respuestas cortas: hasta 600 caracteres salvo que te pidan detalle. "
    "El número que importa va PRIMERO, en la primera oración. Sin títulos, sin "
    "tablas, sin listas largas; si hace falta enumerar, una línea por ítem con un "
    "guion. Sin negritas ni asteriscos: texto plano (el servidor los quita igual). "
    "Los links van completos, empezando por "
    "https://rendi.finance. NO escribas el bloque ---RENDI--- ni el campo \"voz\": "
    "acá no hay tarjetas ni audio; terminá en la última oración de la respuesta. "
    "Si te preguntan algo que no es de su cartera, de sus operaciones ni del "
    "mercado, contestá en una línea que eso no es lo tuyo y que te pregunte por su "
    "cartera o por el mercado. No contestes recetas, deportes, tareas ni pedidos "
    "de redactar textos."
)


# ── Configuración ───────────────────────────────────────────────────────────

def _env(nombre: str) -> str:
    return (os.environ.get(nombre) or "").strip()


def token() -> str:
    return _env("WHATSAPP_TOKEN")


def phone_number_id() -> str:
    return _env("WHATSAPP_PHONE_NUMBER_ID")


def app_secret() -> str:
    return _env("WHATSAPP_APP_SECRET")


def verify_token() -> str:
    return _env("WHATSAPP_VERIFY_TOKEN")


def numero_del_bot() -> str:
    """Sólo dígitos, con código de país (549…). Vacío si no está configurado."""
    return re.sub(r"\D", "", _env("WHATSAPP_NUMERO"))


def configurado() -> bool:
    """¿Se puede MANDAR? Hace falta el token y el id del número."""
    return bool(token() and phone_number_id())


def _bajo_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


# ── La firma del aviso ──────────────────────────────────────────────────────
# Meta firma el cuerpo crudo con HMAC-SHA256 y el App Secret, y lo manda en el
# header X-Hub-Signature-256 como "sha256=<hex>". Sin esto, cualquiera podría
# decirle al servidor «el número tal compró 1.000 BTC».

def firma_valida(cuerpo: bytes, header: Optional[str], secreto: Optional[str] = None) -> bool:
    secreto = app_secret() if secreto is None else secreto
    if not secreto or not header:
        return False
    recibida = header.strip()
    if recibida.lower().startswith("sha256="):
        recibida = recibida[7:]
    esperada = hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, recibida.lower())


def exige_firma() -> bool:
    """En producción un aviso sin firma válida se rechaza SIEMPRE. En desarrollo,
    sin App Secret configurado, se deja pasar (para probar con curl)."""
    if app_secret():
        return True
    try:
        from billing.rebill import is_likely_production
        return bool(is_likely_production())
    except Exception:
        return True


# ── Leer el aviso ───────────────────────────────────────────────────────────

@dataclass
class Mensaje:
    wa_id: str            # id único de Meta: la llave contra duplicados
    telefono: str         # sólo dígitos, con código de país
    tipo: str             # 'texto' | 'boton' | 'audio' | 'imagen' | 'documento' | 'otro'
    texto: str            # lo que dijo (o la palabra del botón)
    nombre: str = ""      # el nombre del perfil, si vino
    media_id: str = ""    # audio/imagen/documento: para bajarlo después
    boton_id: str = ""


def mensajes_del_aviso(payload: dict) -> list:
    """Los mensajes ENTRANTES de un aviso de Meta, ya aplanados.

    Un aviso trae entry[] → changes[] → value.messages[]; también trae
    `statuses` (entregado, leído) que acá no interesan. Lo que no se entiende
    se devuelve como tipo 'otro' para poder contestar «por ahora leo texto».
    """
    out = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            nombres = {}
            for c in value.get("contacts") or []:
                try:
                    nombres[str(c.get("wa_id"))] = str((c.get("profile") or {}).get("name") or "")
                except Exception:
                    pass
            for m in value.get("messages") or []:
                if not isinstance(m, dict) or not m.get("id") or not m.get("from"):
                    continue
                tel = re.sub(r"\D", "", str(m["from"]))
                tipo_meta = str(m.get("type") or "")
                msg = Mensaje(wa_id=str(m["id"]), telefono=tel, tipo="otro", texto="",
                              nombre=nombres.get(tel, ""))
                if tipo_meta == "text":
                    msg.tipo = "texto"
                    msg.texto = str((m.get("text") or {}).get("body") or "").strip()
                elif tipo_meta == "interactive":
                    inter = m.get("interactive") or {}
                    br = inter.get("button_reply") or inter.get("list_reply") or {}
                    msg.tipo = "boton"
                    msg.boton_id = str(br.get("id") or "")
                    msg.texto = PALABRA_DEL_BOTON.get(msg.boton_id, str(br.get("title") or "")).strip()
                elif tipo_meta == "button":
                    # Botones de plantilla (otro formato de Meta).
                    msg.tipo = "boton"
                    msg.texto = str((m.get("button") or {}).get("text") or "").strip()
                elif tipo_meta in ("audio", "voice"):
                    msg.tipo = "audio"
                    msg.media_id = str((m.get("audio") or {}).get("id") or "")
                elif tipo_meta == "image":
                    msg.tipo = "imagen"
                    msg.media_id = str((m.get("image") or {}).get("id") or "")
                elif tipo_meta == "document":
                    msg.tipo = "documento"
                    msg.media_id = str((m.get("document") or {}).get("id") or "")
                out.append(msg)
    return out


# ── El código de vinculación ────────────────────────────────────────────────
# La app muestra «RENDI ABC123» y abre WhatsApp con ese texto ya escrito. Que el
# código llegue desde un WhatsApp prueba las dos cosas a la vez: quien lo manda
# entró a la cuenta (vio el código) y tiene ese teléfono (Meta garantiza el
# número de origen). Pedirle que tipee su número no probaría ninguna.

def codigo_nuevo() -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(6))


def codigo_del_texto(texto: str) -> Optional[str]:
    """El código adentro de lo que escribió («hola, RENDI ABC123», «abc123» a
    secas). None si no hay nada con esa forma. Una palabra de 6 letras suelta en
    una frase («cuánto tengo en VENTAS») NO es un código."""
    if not texto:
        return None
    t = texto.upper().strip()
    m = _CODIGO_CON_RENDI_RE.search(t) or _CODIGO_SOLO_RE.match(t)
    return m.group(1) if m else None


def texto_de_vinculacion(codigo: str) -> str:
    return f"RENDI {codigo}"


def link_para_vincular(codigo: str, numero: Optional[str] = None) -> str:
    """El link que abre WhatsApp con el código ya escrito. Vacío si el número del
    bot no está configurado (la app entonces muestra el código a secas)."""
    numero = numero_del_bot() if numero is None else numero
    if not numero:
        return ""
    from urllib.parse import quote
    return f"https://wa.me/{numero}?text={quote(texto_de_vinculacion(codigo))}"


# ── Formato de la respuesta ─────────────────────────────────────────────────

def texto_para_whatsapp(reply: str) -> str:
    """Lo que escribió el chat, listo para WhatsApp: sin el bloque técnico
    ---RENDI--- (es para las tarjetas de la app) y sin espacios de más. La
    negrita doble de markdown se pasa a la simple de WhatsApp por si llegara —
    en la práctica `main._strip_markdown` ya la sacó antes de llegar acá."""
    t = reply or ""
    m = RENDI_DELIM_RE.search(t)
    if m:
        t = t[:m.start()]
    # Negrita de markdown (**x**) → negrita de WhatsApp (*x*).
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", t)
    # Más de dos saltos seguidos, a dos.
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def partir(texto: str, maximo: int = MAX_TEXTO) -> list:
    """Parte un texto largo en mensajes de hasta `maximo` caracteres, cortando
    en un salto de línea o un espacio cuando se puede."""
    texto = texto or ""
    if len(texto) <= maximo:
        return [texto] if texto else []
    partes = []
    while len(texto) > maximo:
        corte = texto.rfind("\n", 0, maximo)
        if corte < maximo // 2:
            corte = texto.rfind(" ", 0, maximo)
        if corte < maximo // 2:
            corte = maximo
        partes.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip()
    if texto:
        partes.append(texto)
    return partes


# ── Mandar ──────────────────────────────────────────────────────────────────
# Bajo pytest NUNCA se sale a la red: lo mandado queda en ENVIADOS para que las
# pruebas lo lean (mismo criterio que billing/emails._pedir_a_resend).

ENVIADOS: list = []


def _post(payload: dict) -> Optional[str]:
    """Manda un mensaje a Meta. Devuelve el id del mensaje de Meta, o None si no
    se pudo. Nunca levanta: el bot no se cae porque Meta tosió."""
    if _bajo_pytest():
        ENVIADOS.append(payload)
        return f"test:{len(ENVIADOS)}"
    if not configurado():
        log.warning("whatsapp: sin WHATSAPP_TOKEN / PHONE_NUMBER_ID, no se manda")
        return None
    try:
        r = httpx.post(
            f"{graph()}/{phone_number_id()}/messages",
            headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
            json=payload, timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            log.error("whatsapp: Meta rechazó el envío %s: %s", r.status_code, r.text[:300])
            return None
        try:
            return str(((r.json().get("messages") or [{}])[0]).get("id") or "")
        except Exception:
            return ""
    except Exception as ex:
        log.error("whatsapp: no se pudo mandar: %s", ex)
        return None


def enviar_texto(telefono: str, texto: str) -> list:
    """Manda `texto` (partido si es largo). Devuelve los ids de Meta."""
    ids = []
    for parte in partir(texto):
        mid = _post({"messaging_product": "whatsapp", "to": telefono,
                     "type": "text", "text": {"preview_url": False, "body": parte}})
        if mid is not None:
            ids.append(mid)
    return ids


def enviar_con_botones(telefono: str, texto: str, botones: list) -> list:
    """Texto con hasta 3 botones [(id, título ≤ 20 caracteres)]. El cuerpo de un
    mensaje con botones tiene tope 1024: si el texto es más largo, se manda el
    texto aparte y los botones con una pregunta corta."""
    ids = []
    cuerpo = texto
    if len(cuerpo) > 1000:
        ids += enviar_texto(telefono, texto)
        cuerpo = "¿Confirmás?"
    mid = _post({
        "messaging_product": "whatsapp", "to": telefono, "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": cuerpo},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid, "title": titulo[:20]}}
                for bid, titulo in botones[:3]
            ]},
        },
    })
    if mid is not None:
        ids.append(mid)
    return ids


def marcar_leido(wa_id: str) -> None:
    """Los dos tildes azules: le dice a la persona que el mensaje llegó, mientras
    la IA piensa (tarda de 5 a 15 segundos)."""
    _post({"messaging_product": "whatsapp", "status": "read", "message_id": wa_id})


# ── Textos fijos del bot ────────────────────────────────────────────────────

def texto_no_vinculado() -> str:
    return ("Hola 👋 Soy Rendi. Este número todavía no está conectado a ninguna "
            "cuenta.\n\nPara conectarlo: entrá a https://rendi.finance → Configuración "
            "→ WhatsApp y mandame el código que te muestra ahí.")


def texto_vinculado(nombre: str = "") -> str:
    saludo = f"Listo, {nombre}" if nombre else "Listo"
    return (f"{saludo}: tu WhatsApp quedó conectado a tu cuenta de Rendi ✅\n\n"
            "Podés preguntarme cómo viene tu cartera o dictarme una operación, "
            "por ejemplo: «compré 10 GGAL a 8.500 en Cocos». Antes de anotar "
            "nada te pido que confirmes, y siempre podés decirme «deshacé».")


def texto_codigo_invalido() -> str:
    return ("Ese código no me sirve: puede estar vencido (dura 15 minutos) o mal "
            "copiado. Generá uno nuevo en https://rendi.finance → Configuración → WhatsApp.")


def texto_solo_pro() -> str:
    return ("El bot de WhatsApp es parte del plan Pro. Podés cambiar de plan en "
            "https://rendi.finance/planes.")


def texto_en_pausa() -> str:
    return ("Tu cuenta de Rendi está en pausa hasta que elijas un plan. Elegilo en "
            "https://rendi.finance/planes y volvé a escribirme.")


def texto_apagado() -> str:
    return "El bot de WhatsApp está en mantenimiento. Mientras tanto, te espero en https://rendi.finance."


def texto_no_leo_eso(tipo: str) -> str:
    if tipo == "audio":
        return "Por ahora leo texto, no audios. Escribime lo mismo y te contesto."
    if tipo in ("imagen", "documento"):
        return ("Por ahora leo texto. Si es el archivo de tu broker, subilo desde "
                "https://rendi.finance → Importar.")
    return "Por ahora leo texto. Escribime y te contesto."


def texto_error() -> str:
    return "No pude contestarte ahora. Probá de nuevo en un momento."
