"""Modo mantenimiento: cerrar la app al público sin apagarla.

EL AGUJERO QUE TAPA. Hoy "chequear" y "abrir" son el MISMO momento: apenas se
deploya con `DATABASE_URL`, los 1.084 usuarios ya están adentro. Y los chequeos de
los primeros diez minutos del pasaje incluyen un import de punta a punta, o sea
escrituras. **Se cruza el punto de no retorno mientras todavía estás decidiendo si
la copia sirve** — y el chequeo de totales contra el snapshot de anoche deja de ser
confiable si alguien operó en el medio.

Lo que garantiza, en una línea: **que ninguna escritura de usuario llegue a la base
nueva antes de que vos digas que sí.**

═══ LAS TRES DECISIONES, y por qué cada una ═══

**1. NO TOCA LA BASE. Ni para leer un flag.**
Un modo mantenimiento que consulta una tabla se cae junto con la base de la que te
protege — y el día que lo necesitás es justamente el día en que la base puede estar
rara. Todo sale del entorno, que ya está en memoria cuando arranca el proceso.

**2. EL DEFAULT ES CERRADO, y es lo que más importa.**
Si el mantenimiento fuera un flag que hay que acordarse de prender, sería una **red
opt-in — y una red opt-in no es una red**: es la forma exacta de los errores que
este proyecto ya pagó (ver la regla de la fuente equivocada). Así que arrancar
contra un motor nuevo IMPLICA mantenimiento: con `DATABASE_URL` puesta y sin la
marca explícita de "el pasaje terminó", la app levanta cerrada.

**Las dos fallas no cuestan lo mismo, y por eso el sesgo:**

    trabado en mantenimiento  →  nadie entra, todos ven el mensaje de
                                 "actualización en curso". Molesto y VISIBLE.
                                 Se sale sacando una variable y reiniciando: 30s.

    abierto de más            →  usuarios operando mientras verificás. El punto de
                                 no retorno se cruza SOLO, y es SILENCIOSO: nadie
                                 ve un error, y el chequeo contra el snapshot de
                                 anoche queda contaminado.

Un mecanismo que puede fallar de dos formas tiene que estar sesgado hacia la barata.

**3. DEVUELVE 503, no 500, y el bypass va por HEADER.**
Con 500 el usuario vería un error crudo. Con 503, `frontend/src/utils/api.js`
reintenta con backoff (~8,3 s en total, `:193-194`) y recién después muestra el
mensaje — o sea que **una ventana de mantenimiento corta ni se ve**.

⚠️ **Y acá había un error MÍO, que corrijo porque es la forma de siempre.** Escribí
que "el frontend ya sabe mostrar este mensaje lindo", mirando el código de
reintentos. Miré la fuente equivocada: `buildHttpError` (`:141-152`) arma el mensaje
del 503 con el genérico de gateway y **sólo lo pisa si el cuerpo trae `detail`** —
y el cuerpo de acá traía `error`, que nunca se lee. El usuario iba a ver el mensaje
genérico, no el nuestro.
Por eso el cuerpo ahora va bajo `detail`, que es lo que ese código lee (y además es
la convención de FastAPI). Verificado contra `buildHttpError`, no contra el
mecanismo de reintentos.
El bypass va por header y no por query param porque un token en la URL queda en los
logs del proxy, en el historial del navegador y en el `Referer`. Se compara con
`hmac.compare_digest`, que no filtra información por el tiempo que tarda.

═══ LO QUE **NO** GARANTIZA, y hay que saberlo ═══

  · No frena los crons EXTERNOS: eso lo hace el paso 1 del día, borrando los tres
    tokens.
  · No frena los requests que ya estaban en vuelo cuando se prendió.
  · No frena los seis escritores del arranque (punto 0b del plan), que siguen
    siendo un problema aparte y abierto.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

# Rutas que pasan SIEMPRE. Es una lista corta a propósito: cada excepción es una
# puerta, y `/api/health` tiene que contestar o Railway mata el contenedor y no
# llegás ni a hacer los chequeos.
RUTAS_LIBRES = ("/api/health",)

CABECERA_BYPASS = "x-rendi-bypass"


def _marca(nombre: str) -> Optional[str]:
    v = os.environ.get(nombre)
    return v.strip() if v and v.strip() else None


def en_mantenimiento() -> bool:
    """¿Está cerrado al público?

    El orden importa: lo explícito manda, y **el silencio cierra**.
    """
    explicito = _marca("RENDI_MANTENIMIENTO")
    if explicito == "1":
        return True
    if explicito == "0":
        return False
    # Nadie dijo nada. Si estamos arrancando contra Postgres y todavía no está la
    # marca de que el pasaje terminó, se cierra. Ver la decisión 2 del docstring:
    # olvidarse esta variable te deja afuera a VOS (visible, 30 segundos), y
    # olvidarse al revés deja entrar a 1.084 personas a una base sin verificar.
    return bool(_marca("DATABASE_URL")) and not _marca("RENDI_PASAJE_COMPLETO")


def bypass_valido(valor: Optional[str]) -> bool:
    """¿El request trae el token que deja pasar al operador?

    Sin `RENDI_MANTENIMIENTO_TOKEN` configurado NO hay bypass posible: es
    preferible quedarse afuera —visible, se arregla poniendo la variable— a que un
    token vacío coincida con un header vacío y abra la puerta a cualquiera.
    """
    esperado = _marca("RENDI_MANTENIMIENTO_TOKEN")
    if not esperado or not valor:
        return False
    return hmac.compare_digest(valor, esperado)


def deja_pasar(ruta: str, cabecera_bypass: Optional[str]) -> bool:
    """La decisión completa, sin FastAPI de por medio para poder testearla sola."""
    if not en_mantenimiento():
        return True
    if ruta in RUTAS_LIBRES:
        return True
    return bypass_valido(cabecera_bypass)


# La forma la dicta `buildHttpError` del frontend: lee `payload.detail`, y si es un
# objeto toma `.error`. Cualquier otra forma cae en el mensaje genérico de gateway.
CUERPO_503 = {
    "detail": {
        "error": "Estamos mudando la base de datos. Volvemos en unos minutos.",
        "mantenimiento": True,
    }
}


def instalar(app) -> None:
    """Engancha el middleware. **Va PRIMERO en la cadena.**

    En FastAPI el último `@app.middleware("http")` registrado es el más externo, o
    sea el primero en ver el request. Por eso `instalar()` se llama DESPUÉS de los
    otros middlewares: para quedar arriba de todos y cortar antes de que nada más
    toque el request.
    """
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def _mantenimiento(request, call_next):
        if deja_pasar(request.url.path, request.headers.get(CABECERA_BYPASS)):
            return await call_next(request)
        return JSONResponse(status_code=503, content=CUERPO_503,
                            headers={"Retry-After": "120"})
