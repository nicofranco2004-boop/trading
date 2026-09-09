"""Alcance real en producción de los hallazgos de la auditoría de cálculo.

SOLO LECTURA, y sólo agregados: ninguna consulta devuelve un user_id, un email,
un nombre de broker ni una fila individual. Lo máximo que sale es un COUNT
DISTINCT y una suma. Está escrito así a propósito y hay un guard que lo verifica
antes de ejecutar nada (`_verificar_solo_lectura`).

⚠️ EL SQL VIVE EN UN SOLO LUGAR: `audit/01_calculos/1a-alcance-produccion-sqlite.sql`.
Este módulo lo LEE, no lo copia. Cuando había dos copias —el .sql y una embebida
en `1a-medir-alcance.py`— ya habían divergido, en un comentario, sin que nadie lo
notara. Ese es el patrón que la auditoría entera persigue; no lo repetimos acá.

Además del dato crudo, este módulo traduce cada número a una pregunta en
castellano y le pone un veredicto (`ok` / `mirar` / `urgente`) según el umbral que
el propio .sql documenta en su línea "PREOCUPANTE SI". Quien lee el panel de admin
no tiene por qué saber qué es `filas_en_pesos_sin_fx`.
"""
from __future__ import annotations

import os
import re

_AQUI = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(
    os.path.dirname(_AQUI), "audit", "01_calculos", "1a-alcance-produccion-sqlite.sql")

# Palabras que NO pueden aparecer en una consulta de este archivo. El guard corre
# antes de ejecutar: si alguien agrega un UPDATE al .sql, esto se niega a correr
# en vez de tocar producción.
_PROHIBIDO = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|merge|grant|"
    r"attach|pragma|vacuum|begin|commit)\b", re.I)


def _sql_crudo() -> str:
    with open(SQL_PATH, encoding="utf-8") as f:
        return f.read()


def secciones(sql: str = None):
    """[(id, titulo, sentencia)] — parte el .sql por sus encabezados `-- Qn · …`."""
    sql = sql if sql is not None else _sql_crudo()
    fuera, actual, acc = [], None, []

    def cerrar():
        if actual is None:
            return
        for trozo in " ".join(" ".join(acc).split()).split(";"):
            t = trozo.strip()
            if t:
                fuera.append((actual[0], actual[1], t))

    for linea in sql.splitlines():
        m = re.match(r"--\s*(Q\w+)\s*·\s*(.+)", linea.strip())
        if m:
            cerrar()
            actual, acc = (m.group(1), m.group(2).strip()), []
            continue
        # ⚠️ TAMBIÉN EL COMENTARIO AL FINAL DE LA LÍNEA. Las líneas se unen con
        # espacios en una sola, y un `-- ...` inline se tragaba TODO lo que venía
        # después. En Q1a eso borraba el filtro "la cuenta es en dólares" y el
        # botón publicó 679 usuarios / 29.820 posiciones — eran todas las
        # posiciones en pesos, no el hallazgo. El número real es ~20 usuarios.
        linea = linea.split("--", 1)[0]
        if not linea.strip():
            continue
        if actual is not None:
            acc.append(linea)
    cerrar()
    return fuera


def _verificar_solo_lectura(consultas):
    """Se niega a correr si alguna consulta no es un SELECT limpio."""
    for sid, _titulo, sentencia in consultas:
        if not sentencia.lstrip().upper().startswith(("SELECT", "WITH")):
            raise ValueError(f"{sid}: la consulta no empieza con SELECT/WITH")
        # `WITH` puede traer un CTE; lo que no puede haber es una escritura.
        sin_strings = re.sub(r"'[^']*'", "''", sentencia)
        mala = _PROHIBIDO.search(sin_strings)
        if mala:
            raise ValueError(f"{sid}: la consulta contiene `{mala.group(0)}`")


# ─── La traducción: de nombre de columna a pregunta que se entiende ──────────
#
# `columna` es el número que manda; `umbral(v)` decide el veredicto siguiendo la
# línea "PREOCUPANTE SI" del .sql. `detalle` son las otras columnas de la misma
# consulta, que se muestran chiquitas al lado.
_URGENTE = "urgente"
_MIRAR = "mirar"
_OK = "ok"


def _mayor_a(n, nivel=_MIRAR):
    return lambda v: nivel if (v or 0) > n else _OK


LECTURA = [
    # (id, columna que manda, pregunta, umbral, qué significa)
    ("Q2", "usuarios_en_riesgo",
     "¿A cuántos usuarios se les borró el capital inicial que habían tipeado a mano?",
     _mayor_a(0, _URGENTE),
     "Es el único dato que no se puede recalcular: si se perdió, sólo vuelve de una copia "
     "de seguridad, y las copias se van pisando. Ya no se borra más, pero lo perdido "
     "sigue perdido."),
    ("Q1a", "usuarios_afectados",
     "¿A cuántos usuarios se les guardó un costo en pesos dentro de una cuenta en dólares?",
     _mayor_a(0, _URGENTE),
     "Cada una de esas posiciones muestra una pérdida enorme que no existe: el costo está "
     "en pesos y se lee como si fueran dólares."),
    ("Q1b", "a2_broker_usd_genuino",
     "…y de ésas, ¿cuántas están en una cuenta en dólares de verdad?",
     _mayor_a(0, _URGENTE),
     "Éstas son las difíciles: no hay un tipo de cambio conocido con el que arreglarlas "
     "automáticamente. Las otras sí."),
    ("Q1c", "usuarios_con_filas_grandes",
     "¿A cuántos usuarios les quedaron fotos diarias de la cartera pegadas al costo?",
     _mayor_a(3),
     "Son días en que la foto guardó el costo en vez del valor de mercado. Ensucian el "
     "gráfico de evolución y el rendimiento."),
    ("Q1d", "usuarios_fuera_banda_amplia",
     "¿A cuántos usuarios les quedó una relación valor/costo imposible?",
     _mayor_a(5),
     "Un usuario suelto puede tener una razón real; muchos a la vez es el mismo problema "
     "del costo en pesos, visto desde otro lado."),
    ("Q3", "amortizaciones_manuales",
     "¿Cuántas amortizaciones de bono se cargaron contando la devolución del capital como ganancia?",
     _mayor_a(0),
     "Cuando un bono devuelve capital eso NO es ganancia. Cada una infla el resultado de "
     "su mes y queda inflado para siempre."),
    ("Q4", "meses_con_firma_1415",
     "¿Cuántos meses quedaron con caja reconciliada a un dólar fijo de 1415?",
     _mayor_a(0),
     "Ese número estaba escrito a mano en el código. Cada mes así metió capital que nunca "
     "existió (~7 % de más)."),
    ("Q5", "ventas_ars_con_fx_1",
     "¿Cuántas ventas en pesos quedaron guardadas como si el dólar valiera 1?",
     _mayor_a(0),
     "La fila dice que la venta fue en pesos pero sella un dólar de 1, así que cualquier "
     "pantalla que reconstruya el monto original da un número absurdo."),
    ("Q6", "con_neto_no_cero",
     "¿Cuántas conversiones de moneda importadas dejaron plata fantasma?",
     _mayor_a(0),
     "Cambiar pesos por dólares no crea ni destruye capital. Cuando el neto no da cero, "
     "aparece o desaparece plata que nadie depositó."),
    ("Q7", "filas_en_pesos_sin_fx",
     "¿Cuántos intereses de plazo fijo en pesos se están leyendo como dólares?",
     _mayor_a(0),
     "Un plazo fijo de $10.000.000 a 30 días entra como US$328.767 de ganancia. Si acá "
     "dice 0, este problema era teórico y ya quedó cerrado hacia adelante."),
    ("Q8", "mas_de_12_meses",
     "¿Cuántos usuarios tienen más de un año de historia cargada?",
     lambda v: _OK,
     "No es un problema: es el tamaño del grupo donde más se notan los errores de "
     "rendimiento acumulado. Sirve para saber a quiénes conviene mirar primero."),
]


def informe(conn) -> dict:
    """Corre las 13 consultas y devuelve el resultado ya traducido.

    Shape:
      { "hallazgos": [ {pregunta, numero, veredicto, que_significa, detalle{}} ],
        "resumen": {urgentes, a_mirar, ok},
        "crudo": { "Q2": [{...}], ... } }
    """
    consultas = secciones()
    _verificar_solo_lectura(consultas)

    crudo: dict = {}
    for sid, _titulo, sentencia in consultas:
        filas = [dict(r) for r in conn.execute(sentencia).fetchall()]
        crudo.setdefault(sid, []).extend(filas)

    hallazgos = []
    for sid, columna, pregunta, umbral, significa in LECTURA:
        fila = next((f for f in crudo.get(sid, []) if columna in f), None)
        if fila is None:
            hallazgos.append({"id": sid, "pregunta": pregunta, "numero": None,
                              "veredicto": "sin_dato", "que_significa": significa,
                              "detalle": {}})
            continue
        # ⚠️ NULL NO ES "SIN DATO". Un `SUM(CASE …)` sobre cero filas devuelve NULL en
        # SQLite, y eso significa cero, no "no se pudo medir". Mostrarlo como "—"
        # deja al lector sin saber si el problema no existe o si la consulta falló.
        valor = fila.get(columna)
        if valor is None:
            valor = 0
        hallazgos.append({
            "id": sid,
            "pregunta": pregunta,
            "numero": valor,
            "veredicto": umbral(valor),
            "que_significa": significa,
            "detalle": {k: v for k, v in fila.items() if k != columna},
        })

    return {
        "hallazgos": hallazgos,
        "resumen": {
            "urgentes": sum(1 for h in hallazgos if h["veredicto"] == _URGENTE),
            "a_mirar": sum(1 for h in hallazgos if h["veredicto"] == _MIRAR),
            "ok": sum(1 for h in hallazgos if h["veredicto"] == _OK),
        },
        "crudo": crudo,
    }
