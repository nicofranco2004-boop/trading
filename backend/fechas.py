"""El calendario de Rendi: UNA sola definición de "hoy".

Por qué existe este archivo
───────────────────────────
Hasta la tanda F3 convivían tres relojes dentro del mismo endpoint:

  · ART   `utcnow() - 3h`   — nueve copias de la misma resta, escritas por separado
  · UTC   `utcnow()`        — el cron de snapshots, `is_period_current`, el rollover
  · local `date.today()`    — 77 call sites; en Railway es UTC, en una Mac argentina
                              es ART, o sea que dev y prod medían días distintos

Ninguno de los tres está mal en sí mismo. Lo que estaba mal es que convivían, y que
varios llevaban un comentario afirmando estar alineados con otro cuando no lo estaban
(`reporting/builder.py` decía "UTC para consistencia con `_iso_today()`", y
`_iso_today()` es ART).

**El "hoy" de Rendi es el día calendario argentino.** Los usuarios son argentinos, el
cron de snapshots corre a las 02:59 UTC *justamente porque* eso es 23:59 ART, y el
resto del producto ya estaba escrito sobre esa premisa. Este módulo la vuelve
verificable en un solo lugar en vez de repetirla nueve veces.

Argentina no tiene horario de verano desde 2009, así que el offset fijo de −3 es
exacto. Si algún día vuelve el DST, se cambia acá y en ningún otro lado — que es
precisamente el punto.

Regla: en código de producción nadie escribe `utcnow() - timedelta(hours=3)` a mano.
`tests/test_un_solo_calendario.py` lo verifica leyendo el código.
"""

from datetime import date, datetime, timedelta

# Argentina = UTC−3 todo el año (sin horario de verano desde 2009).
ART_OFFSET_HORAS = 3


def ahora_art() -> datetime:
    """El instante actual en hora argentina, como `datetime` naive."""
    return datetime.utcnow() - timedelta(hours=ART_OFFSET_HORAS)


def hoy_art() -> str:
    """Hoy en Argentina, `'YYYY-MM-DD'`.

    Es la fecha con la que se estampan los snapshots y contra la que se cortan
    todos los períodos. A las 22:00 de Buenos Aires devuelve el día de HOY, no el
    de mañana — que es lo que devolvía `utcnow()` y lo que corría la serie entera
    un día adelante.
    """
    return ahora_art().date().isoformat()


def hoy_art_date() -> date:
    """Igual que `hoy_art()` pero como objeto `date`, para hacer aritmética."""
    return ahora_art().date()
