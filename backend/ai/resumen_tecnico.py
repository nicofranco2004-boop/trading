"""resumen_tecnico — el resumen de Mervall-E en la ficha del activo, a pedido y compartido.
═══════════════════════════════════════════════════════════════════════════
QUÉ ES. Un párrafo de 4 o 5 oraciones que cuenta cómo viene el precio de un
activo «como si te lo explicara un amigo». Lo escribe Claude Sonnet 5.5 (effort
low) con el pedido de `resumen_tecnico_pedido.txt` y los hechos que arma Rendi
(`resumen_tecnico_hechos.py`).

A PEDIDO Y UNO SOLO PARA TODOS (decisión de Nico, 22/10):
  · la clave es serie + moneda + fecha de la última vela ('NVDA', 'usd',
    '2026-10-21'). La serie es el ticker que lee el gráfico ('GGAL.BA' en
    dólares es Galicia de BYMA ÷ MEP; 'GGAL' sería el ADR): dos series
    distintas, dos resúmenes;
  · si ya existe, se muestra solo y no cuesta nada; si no, la ficha ofrece el
    botón y el PRIMERO que lo toca lo genera. Lo ven todos hasta que llega la
    vela siguiente (otra clave → vuelve el botón);
  · dos pedidos a la vez generan UNO: el primero reclama la fila (INSERT que
    choca con la clave) y el segundo espera a que termine;
  · tope diario entre todos (`TOPE_DIARIO`) y por persona (`TOPE_POR_PERSONA`):
    un resumen es de todos, pero el que lo pide puede pedir muchos activos.
  · NO descuenta el cupo Free de IA (ai/quota.py): no es un análisis personal.
    Cada fila guarda su costo y /admin (velas) muestra cuántos y cuánto por día.

NADA DEL USUARIO. Los hechos salen de la serie del activo; tu precio, tus
compras y tu resultado no viajan a la IA (no son parte del pedido).

LAS CUENTAS LAS HACE RENDI (resumen_tecnico_hechos.py): proporciones, precios
redondeados y fechas llegan ya escritos, y el pedido le prohíbe calcular.
`problemas()` revisa la respuesta: un número que no está en los datos, una
palabra prohibida, un salto de línea o un largo de más → se pide de nuevo UNA
vez diciéndole qué estuvo mal. Si la segunda trae un dato inventado, no se
publica (falla limpio y el botón vuelve).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from ai import certezas_y_consejos

log = logging.getLogger("ai.resumen_tecnico")

# Cuántos resúmenes NUEVOS por día (argentino) entre todos. Medido el 22/10:
# ~US$ 0,006 cada uno, así que 300 son ~US$ 1,80 por día como techo.
TOPE_DIARIO = int(os.environ.get("RESUMEN_TECNICO_TOPE_DIARIO", "300"))
# Cuántos resúmenes nuevos puede disparar una misma persona por día.
TOPE_POR_PERSONA = int(os.environ.get("RESUMEN_TECNICO_TOPE_PERSONA", "15"))
# Un activo cuyo resumen falló tantas veces (llamadas al modelo) no se reintenta
# ese día: algo de sus datos confunde al modelo y cada intento cuesta.
MAX_LLAMADAS_POR_CLAVE = 4
# Si el que estaba generando no terminó en este tiempo (el proceso se cayó), otro
# puede tomar la fila.
SEGUNDOS_GENERANDO = 90
# Cuánto espera el segundo pedido a que el primero termine.
SEGUNDOS_ESPERA = 30
# Con velas más viejas que esto (los precios no se pudieron actualizar) no se
# ofrece el resumen: contaría como actual algo de hace semanas.
DIAS_VELA_VIEJA = 7

# Largo (decisiones de Nico, 23/10): el tope es 120 palabras, y 130 cuando
# viene la frase del ADX + Squeeze, que va entera y es larga (con 120, 4 de 11
# de esos se rehacían). Es un TOPE, no una meta: el pedido dice que use las que
# hagan falta y ni una más. Un texto de más del tope, con un salto de línea o
# fuera de 3–6 oraciones se pide de nuevo UNA vez. En el segundo intento se
# tolera un poco más (13/12 del tope: 130 y 141): mejor un poco largo que
# ningún resumen.
PALABRAS_MAX = 120
PALABRAS_MAX_CON_FUERZA = 130
TOLERANCIA_SEGUNDA = 13 / 12
ORACIONES = (3, 6)
ORACIONES_SEGUNDA = (3, 7)
FRASE_DE_FUERZA = "fuerza_del_movimiento"

# Con effort low el modelo igual puede razonar antes de escribir (Pampa, 23/10:
# 1.280 tokens en el segundo intento). Con 2.000 una vez se quedó sin lugar y el
# texto vino vacío. Sólo se paga lo que se usa.
MAX_TOKENS = 4000

# El pedido vive en su propio archivo para que se pueda reemplazar sin tocar el
# código (lo escribe y lo mide la sesión de redacción). Va junto con los hechos
# de `resumen_tecnico_hechos.py`: nombra sus claves.
SISTEMA = (Path(__file__).with_name("resumen_tecnico_pedido.txt")).read_text(encoding="utf-8").strip()

# Palabras que no pueden salir: la lista prohibida del pedido (jerga que Nico
# no entiende), fechas relativas (el texto se lee otro día), una corrección a
# la vista y, más estricto que el chat, cualquier mención de comprar, vender o
# esperar y la primera persona: el cierre es neutro, «Lo que se mira es…»
# (decisión de Nico, 23/10); «yo miraría» suena a consejo.
# Las certezas sobre lo que viene y los consejos de operar NO van acá: son la
# lista común con el chat (ai/certezas_y_consejos.py, auditoría final B1+B2,
# 31/10), que `problemas` revisa además de ésta.
_PROHIBIDAS = [
    r"devolvi[óo]", r"retroceso", r"recorte", r"correcci[óo]n", r"corrijo", r"lateral", r"de costado",
    r"consolidaci[óo]n", r"impulso", r"momentum", r"tracci[óo]n", r"zonas?", r"soportes?", r"resistencias?",
    r"techos?", r"pisos?", r"firmes?", r"cansando", r"media m[óo]vil",
    # Las siglas (Nico, 30/10: «nada de RSI, ADX, Squeeze»). «Alcista» y «bajista»
    # salieron de la lista: son las palabras que él usa para la tendencia.
    r"rsi", r"adx", r"squeeze", r"sobrecompra", r"sobreventa",
    r"rebot[eóa]", r"tramos?", r"nivel(es)?", r"fibonacci", r"ruedas?", r"volatilidad", r"recalentad[oa]",
    r"hoy", r"ayer", r"mañana",
    r"compr[áa](r|lo|la)?", r"vend[ée](r|lo|la)?", r"recomend\w*", r"oportunidad",
    r"esper(ar|á)", r"deber[íi]as?",
    r"yo", r"mirar[íi]as?", r"(te )?conviene", r"sugi?er\w*", r"aconsej\w*", r"te diría",
]
_RE_PROHIBIDAS = re.compile(r"\b(" + "|".join(_PROHIBIDAS) + r")\b", re.IGNORECASE)
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
# Números que el modelo puede usar aunque no estén en los hechos: los que
# definen los indicadores en el pedido.
_NUMEROS_LIBRES = {"200", "50", "23", "12", "0", "100", "30", "70"}


def _normal(n: str) -> str:
    """'1.855' y '1855' son el mismo número; '13,45' queda '13,45'."""
    n = n.rstrip(".,")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", n):
        return n.replace(".", "")
    return n


def numeros_de(texto: str) -> set:
    return {_normal(x) for x in _RE_NUMERO.findall(texto or "")}


def pedido_de(hechos: dict) -> str:
    """El mensaje con los datos, tal cual lo midió la redacción (vuelta 8)."""
    return "Datos del activo:\n" + json.dumps(hechos, ensure_ascii=False, indent=1)


def problemas(texto: str, hechos: dict, segunda: bool = False) -> tuple[list, list]:
    """(graves, de_largo). Graves: un número que no está en los hechos o una
    palabra prohibida (no se publica). De largo: se pide de nuevo, y en el
    segundo intento se tolera un poco más."""
    graves, largo = [], []
    t = (texto or "").strip()
    if not t:
        return ["vino vacío"], []
    permitidos = numeros_de(json.dumps(hechos, ensure_ascii=False)) | _NUMEROS_LIBRES
    inventados = sorted(numeros_de(t) - permitidos)
    if inventados:
        graves.append("usaste números que no están en los datos ("
                      + ", ".join(inventados) + "): copiá los números tal cual, sin calcular")
    malas = sorted({m.group(0).lower() for m in _RE_PROHIBIDAS.finditer(t)})
    if malas:
        graves.append("usaste palabras prohibidas (" + ", ".join(malas) + ")")
    # Lo que viene como seguro y los consejos: la lista común con el chat.
    graves += certezas_y_consejos.avisos(t)
    palabras = len(t.split())
    con_fuerza = FRASE_DE_FUERZA in (hechos.get("indicador_que_suma") or {})
    pedido = PALABRAS_MAX_CON_FUERZA if con_fuerza else PALABRAS_MAX
    tope = round(pedido * TOLERANCIA_SEGUNDA) if segunda else pedido
    if palabras > tope:
        # Con la frase de la fuerza, lo que se achica es la oración 2: el aviso
        # decía «sacá la oración 4» y el modelo borraba justo esa frase (Pampa, 23/10).
        largo.append(f"tiene {palabras} palabras y el tope es {pedido}: acortá la oración 2 (el movimiento)"
                     + (", pero la frase de la fuerza del movimiento va entera, sin recortarla" if con_fuerza
                        else " o sacá la oración 4"))
    lo, hi = ORACIONES_SEGUNDA if segunda else ORACIONES
    oraciones = len([o for o in re.split(r"(?<=[.!?])\s+", t) if o.strip()])
    if not lo <= oraciones <= hi:
        largo.append(f"tiene {oraciones} oraciones: tienen que ser 4 o 5")
    if "\n" in t or t.startswith(("-", "•", "*", "#")):
        largo.append("tiene que ser un solo párrafo, sin títulos, viñetas ni correcciones a la vista")
    return graves, largo


class NoSePudo(Exception):
    """El modelo no dio un texto publicable. Lleva lo gastado igual."""
    def __init__(self, motivo: str, gasto: dict):
        super().__init__(motivo)
        self.gasto = gasto


def generar(hechos: dict) -> dict:
    """Llama al modelo (hasta 2 veces) y devuelve
    {texto, model, input_tokens, output_tokens, cost_usd_cents, llamadas, palabras}.
    None si la IA no está configurada. NoSePudo si no hubo texto publicable.

    Texto plano, sin salida estructurada ni caché: es el pedido tal como lo midió
    la redacción, y con uno por activo y por día el caché de 1 h (que cuesta el
    doble escribirlo) casi nunca se volvería a leer."""
    from ai import llm

    cliente = llm._get_anthropic_client()
    if cliente is None:
        return None
    gasto = {"model": llm.MODEL_SONNET, "input_tokens": 0, "output_tokens": 0,
             "cost_usd_cents": 0, "llamadas": 0}
    mensajes = [{"role": "user", "content": pedido_de(hechos)}]
    for intento in (1, 2):
        try:
            resp = cliente.messages.create(model=llm.MODEL_SONNET, max_tokens=MAX_TOKENS, system=SISTEMA,
                                           messages=mensajes, extra_body={"output_config": {"effort": "low"}})
        except Exception as ex:
            raise NoSePudo(f"el modelo falló: {type(ex).__name__}", gasto) from ex
        u = resp.usage
        ent, sal = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
        gasto["llamadas"] += 1
        gasto["input_tokens"] += ent
        gasto["output_tokens"] += sal
        gasto["cost_usd_cents"] += llm._calc_cost_cents(llm.MODEL_SONNET, ent, sal, 0, 0)
        crudo = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        graves, largo = problemas(crudo, hechos, segunda=intento == 2)
        if not graves and not largo:
            return {**gasto, "texto": crudo, "palabras": len(crudo.split())}
        log.info("Resumen técnico de %s, intento %d: %s", hechos.get("activo"), intento, graves + largo)
        if intento == 2:
            raise NoSePudo("; ".join(graves + largo), gasto)
        # Se le muestra lo que escribió y qué estuvo mal: así corrige ESE texto.
        mensajes = mensajes + [
            {"role": "assistant", "content": crudo},
            {"role": "user", "content": "Ese párrafo no sirve: " + "; ".join(graves + largo)
             + ". Escribí de nuevo sólo el párrafo final, corregido, con los mismos datos."}]


# ─── Guardado compartido ─────────────────────────────────────────────────────

def _ahora() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def clave_de(ficha: dict) -> tuple | None:
    """(serie, moneda, fecha de la última vela) de una respuesta de la ficha."""
    if not ficha or not ficha.get("disponible"):
        return None
    fecha = (ficha.get("lectura") or {}).get("fecha")
    if not (ficha.get("ticker") and fecha):
        return None
    return (ficha["ticker"], ficha.get("moneda") or "usd", fecha)


def _fila(conn, clave):
    r = conn.execute(
        """SELECT estado, texto, llamadas, empezado_at FROM resumenes_tecnicos
            WHERE ticker = ? AND moneda = ? AND fecha_vela = ?""", clave).fetchone()
    return dict(r) if r else None


def _vela_vieja(fecha_vela: str) -> bool:
    from fechas import hoy_art_date
    from datetime import date
    return (hoy_art_date() - date.fromisoformat(fecha_vela)).days > DIAS_VELA_VIEJA


def estado_para_la_ficha(conn, ficha: dict) -> dict | None:
    """Lo que la ficha necesita saber del resumen, sin generar nada:
    {estado: 'listo', texto, fecha} · {estado: 'no_hay'} (botón) ·
    {estado: 'generando'} · None (no se ofrece: sin IA, velas viejas, sin datos)."""
    from ai import llm
    clave = clave_de(ficha)
    if not clave:
        return None
    try:
        f = _fila(conn, clave)
    except Exception:
        # La tabla todavía no existe en una base vieja, o la base falló: la
        # ficha se ve igual, sin el resumen.
        log.exception("No se pudo leer el resumen técnico")
        return None
    if f and f["estado"] == "listo":
        return {"estado": "listo", "texto": f["texto"], "fecha": clave[2]}
    if _vela_vieja(clave[2]) or not llm.is_configured():
        return None
    if f and f["estado"] == "generando" and not _vencida(f):
        return {"estado": "generando", "fecha": clave[2]}
    if f and f["estado"] == "fallo" and (f["llamadas"] or 0) >= MAX_LLAMADAS_POR_CLAVE:
        return None
    return {"estado": "no_hay", "fecha": clave[2]}


def _vencida(f: dict) -> bool:
    try:
        return datetime.fromisoformat(f["empezado_at"]) < datetime.utcnow() - timedelta(seconds=SEGUNDOS_GENERANDO)
    except Exception:
        return True


def _esperar(abrir, clave) -> dict:
    """El segundo pedido: espera a que el primero termine (lee con conexiones
    nuevas, para ver lo que el otro confirmó)."""
    fin = time.monotonic() + SEGUNDOS_ESPERA
    while time.monotonic() < fin:
        time.sleep(0.5)
        with abrir() as conn:
            f = _fila(conn, clave)
        if not f or f["estado"] == "fallo":
            return {"estado": "error"}
        if f["estado"] == "listo":
            return {"estado": "listo", "texto": f["texto"], "fecha": clave[2]}
    return {"estado": "generando", "fecha": clave[2]}


def pedir(abrir, ficha: dict, nombre: str, uid: int) -> dict:
    """El botón «✦ Resumen de Mervall-E». `abrir` abre una conexión que se
    cierra sola (main.db_abierta): el modelo tarda 2-3 segundos y la base no
    puede quedar tomada mientras tanto.

    Devuelve {estado: 'listo', texto, fecha} · {estado: 'generando'} (el otro
    pedido sigue) · {estado: 'tope'} · {estado: 'tope_persona'} ·
    {estado: 'no_disponible'} · {estado: 'error'}."""
    from ai import llm
    from ai.resumen_tecnico_hechos import para_el_resumen
    from fechas import hoy_art

    clave = clave_de(ficha)
    hechos = para_el_resumen(ficha, nombre)
    if not clave or not hechos or _vela_vieja(clave[2]) or not llm.is_configured():
        return {"estado": "no_disponible"}
    hoy = hoy_art()
    with abrir() as conn:
        f = _fila(conn, clave)
        if f and f["estado"] == "listo":
            return {"estado": "listo", "texto": f["texto"], "fecha": clave[2]}
        if f and f["estado"] == "generando" and not _vencida(f):
            esperar = True
        else:
            esperar = False
            if f and f["estado"] == "fallo" and (f["llamadas"] or 0) >= MAX_LLAMADAS_POR_CLAVE:
                return {"estado": "no_disponible"}
            # Los topes cuentan resúmenes empezados hoy (salgan bien o mal: los
            # dos cuestan). Dos pedidos justo en el borde pueden pasar los dos:
            # es un techo de gasto, no una cuenta exacta.
            total = conn.execute("SELECT COUNT(*) FROM resumenes_tecnicos WHERE dia = ?", (hoy,)).fetchone()[0]
            if total >= TOPE_DIARIO:
                return {"estado": "tope"}
            mios = conn.execute("SELECT COUNT(*) FROM resumenes_tecnicos WHERE dia = ? AND pedido_por = ?",
                                (hoy, uid)).fetchone()[0]
            if mios >= TOPE_POR_PERSONA:
                return {"estado": "tope_persona"}
            # El reclamo: la primera escritura decide quién genera. El que
            # choca con la clave espera al otro.
            ahora = _ahora()
            with conn:
                cur = conn.execute(
                    """INSERT INTO resumenes_tecnicos
                         (ticker, moneda, fecha_vela, estado, pedido_por, dia, empezado_at, hechos_json)
                       VALUES (?, ?, ?, 'generando', ?, ?, ?, ?)
                       ON CONFLICT (ticker, moneda, fecha_vela) DO NOTHING""",
                    (*clave, uid, hoy, ahora, json.dumps(hechos, ensure_ascii=False)))
                mio = cur.rowcount == 1
                if not mio:
                    # La fila ya estaba: se puede tomar si falló o si el que
                    # generaba se colgó. El UPDATE con la condición es el reclamo.
                    vencido = (datetime.utcnow() - timedelta(seconds=SEGUNDOS_GENERANDO)).isoformat(timespec="seconds")
                    cur = conn.execute(
                        """UPDATE resumenes_tecnicos
                              SET estado = 'generando', empezado_at = ?, pedido_por = ?, dia = ?, hechos_json = ?
                            WHERE ticker = ? AND moneda = ? AND fecha_vela = ?
                              AND (estado = 'fallo' OR (estado = 'generando' AND empezado_at < ?))""",
                        (ahora, uid, hoy, json.dumps(hechos, ensure_ascii=False), *clave, vencido))
                    mio = cur.rowcount == 1
            esperar = not mio
    if esperar:
        return _esperar(abrir, clave)

    try:
        res = generar(hechos)
        gasto, error = (res or {}), (None if res else "IA sin configurar")
    except NoSePudo as ex:
        res, gasto, error = None, ex.gasto, str(ex)
    except Exception as ex:  # nada de lo de arriba tiene que dejar la fila tomada
        log.exception("Resumen técnico falló")
        res, gasto, error = None, {}, type(ex).__name__
    with abrir() as conn:
        with conn:
            conn.execute(
                """UPDATE resumenes_tecnicos
                      SET estado = ?, texto = ?, error = ?, model = COALESCE(?, model),
                          llamadas = COALESCE(llamadas, 0) + ?,
                          input_tokens = COALESCE(input_tokens, 0) + ?,
                          output_tokens = COALESCE(output_tokens, 0) + ?,
                          cost_usd_cents = COALESCE(cost_usd_cents, 0) + ?,
                          palabras = ?, terminado_at = ?
                    WHERE ticker = ? AND moneda = ? AND fecha_vela = ?""",
                ("listo" if res else "fallo", res and res["texto"], error, gasto.get("model"),
                 gasto.get("llamadas", 0), gasto.get("input_tokens", 0), gasto.get("output_tokens", 0),
                 gasto.get("cost_usd_cents", 0), res and res["palabras"], _ahora(), *clave))
    if res:
        return {"estado": "listo", "texto": res["texto"], "fecha": clave[2]}
    return {"estado": "error"}


def para_admin(conn, dias: int = 14) -> dict:
    """Cuántos resúmenes por día y cuánto costaron (US$), para /admin."""
    from fechas import hoy_art_date
    desde = (hoy_art_date() - timedelta(days=dias - 1)).isoformat()
    filas = conn.execute(
        """SELECT dia, SUM(CASE WHEN estado = 'listo' THEN 1 ELSE 0 END) AS listos,
                  SUM(CASE WHEN estado = 'fallo' THEN 1 ELSE 0 END) AS fallidos,
                  COALESCE(SUM(llamadas), 0) AS llamadas,
                  COALESCE(SUM(cost_usd_cents), 0) AS costo
             FROM resumenes_tecnicos WHERE dia >= ? GROUP BY dia ORDER BY dia DESC""",
        (desde,)).fetchall()
    # cost_usd_cents: la unidad de ai/llm._calc_cost_cents (1 = US$ 0,0001).
    return {
        "tope_diario": TOPE_DIARIO, "tope_por_persona": TOPE_POR_PERSONA,
        "por_dia": [{"dia": r["dia"], "listos": r["listos"], "fallidos": r["fallidos"],
                     "llamadas": r["llamadas"], "costo_usd": round(r["costo"] / 10000, 4)}
                    for r in filas],
    }
