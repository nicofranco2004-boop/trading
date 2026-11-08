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


def en_art(instante_utc: datetime) -> datetime:
    """Un instante UTC (naive) en hora argentina, naive. Para quien necesita la
    HORA, no sólo el día (las alertas técnicas salen desde las 9 de la mañana)."""
    return instante_utc - timedelta(hours=ART_OFFSET_HORAS)


def dia_art(instante_utc: datetime) -> date:
    """El día argentino de un instante UTC (naive). Para quien ya tiene su
    "ahora" en la mano (y los tests que lo congelan)."""
    return en_art(instante_utc).date()


def dia_art_de_texto(raw) -> "str | None":
    """Una marca UTC guardada como texto ('AAAA-MM-DD HH:MM:SS', con o sin zona,
    o un `datetime`) → el día ARGENTINO 'AAAA-MM-DD'. Las escribe `datetime('now')`
    o `_ahora_utc` en UTC: de 21 a 24 hs los dos relojes son días distintos (una
    carga de las 22:30 del 4 queda guardada el 5). None si no se puede leer."""
    from datetime import timezone as _tz
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        t = raw
    else:
        txt = str(raw).strip().replace("Z", "+00:00")
        try:
            t = datetime.fromisoformat(txt)
        except ValueError:
            return None
    if t.tzinfo is not None:
        t = t.astimezone(_tz.utc).replace(tzinfo=None)
    return dia_art(t).isoformat()


MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def fecha_legible(d: date) -> str:
    """`date(2026, 9, 19)` → "19 de septiembre". Para el texto que lee una
    persona (mails, avisos): nadie lee "2026-09-19"."""
    return "%d de %s" % (d.day, MESES_ES[d.month - 1])


def inicio_dia_art_en_utc(d: date) -> str:
    """El instante en que EMPIEZA el día argentino `d`, escrito en UTC con el
    formato de las columnas `datetime('now')` (`'YYYY-MM-DD HH:MM:SS'`).

    Para cortar por día argentino una columna que se guarda en UTC: el 7/10 de
    Buenos Aires va de `'2026-10-07 03:00:00'` (incluido) a
    `'2026-10-08 03:00:00'` (excluido). Cortar por `substr(col,1,10)` mete en el
    día siguiente todo lo que pasa de 21:00 a medianoche."""
    inicio = datetime(d.year, d.month, d.day) + timedelta(hours=ART_OFFSET_HORAS)
    return inicio.strftime("%Y-%m-%d %H:%M:%S")
