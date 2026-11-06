"""Backtesting: qué habría pasado si seguías una regla técnica al pie de la letra.

QUÉ ES. La pestaña «Backtesting» de Análisis técnico (Nico, 04/11/2026; boceto
aprobado: https://claude.ai/artifact/46cJx7aUeeH9CkVA7LAqX5). Elegís un papel,
una regla y un período, y se simula día por día qué habría pasado con US$ 100
si hacías exactamente lo que dice la regla, SIEMPRE al lado de comprar el primer
día y no tocar nada («comprar y mantener»). Se pueden comparar hasta
`MAX_REGLAS` reglas a la vez (etapa 2): todas sobre los MISMOS días, los que
todas pueden probar, y al lado de comprar y mantener esos mismos días.

LAS REGLAS. Las cuatro que ya muestra la ficha (elegidas por Nico el 04/11), con
LAS cuentas de tecnico.py, no una copia: lo que acá es «cruzó» es lo que avisa
una alerta y lo que dibuja el gráfico.
  · media200 / media50: compra cuando el precio PASA arriba de su media (cierre
    ≥ media, la regla de `tecnico.tendencia_de`); vende cuando pasa abajo. Los
    cruces salen de `tecnico.cruces`, la cuenta de las alertas.
  · rsi: compra cuando el RSI sale de abajo de 30; vende cuando sale de arriba de
    70 (las señales `rsi_sube_30` y `rsi_baja_70` de las alertas).
  · adx_squeeze: la del estudio del 28/10 (~/Documents/estrategia-trading-latino,
    reglas.md, versión A). Compra cuando el Squeeze sube saliendo de un valle
    (estuvo negativo algún día de los últimos `RUEDAS_VALLE`), el ADX gira para
    arriba después de haber bajado algún día de los `RUEDAS_ADX_BAJANDO`
    anteriores y está en la línea clave (23) o más. Vende cuando la montaña del
    Squeeze empieza a bajar con el ADX bajando, o cuando el Squeeze pasa de
    positivo a cero o negativo.

CÓMO SE SIMULA. Igual que el estudio del 28/10 (scripts/backtest.py, `simular`),
que se verificó contra TradingView:
  · la señal se mira al CIERRE de un día y se opera a la APERTURA del siguiente;
  · todo adentro o todo afuera: sin ventas en corto ni apalancamiento;
  · `COMISION` al comprar y al vender (0,5 %; el estudio usó 0,1 %);
  · afuera, la plata no gana nada (ni un fondo en dólares);
  · si al final sigue comprada, se cuenta con el último cierre (con su comisión);
  · comprar y mantener compra a la apertura del primer día y vende al último
    cierre, con la misma comisión.

QUÉ NO HACE. No cuenta dividendos: las velas son precios. No dice nada de lo que
va a pasar: acá van los números y las palabras las pone la pantalla
(frontend/src/utils/backtesting.js), que describe y nunca promete.
"""
from __future__ import annotations

import math
from datetime import date

import estructura
import tecnico
from pesado import pesado

# Las reglas, en el orden en que se ofrecen.
REGLAS = ("media200", "media50", "rsi", "adx_squeeze")
# Cuántas se comparan a la vez como máximo (Nico, 04/11: «hasta 3»).
MAX_REGLAS = 3
# Los períodos, en años. Se guardan 5 años de velas (velas_diarias.ANIOS_GUARDADOS)
# y la media de 200 necesita 200 ruedas antes para existir (unos 10 meses): con
# 4 años como máximo, las cuatro reglas tienen el período entero.
ANIOS = (1, 2, 3, 4)
# Lo que cobra el broker, de cada lado: al comprar y al vender. 0,5 %, lo de un
# broker argentino (Nico, 04/11); el estudio del 28/10 usó 0,1 % y las pruebas
# que lo comparan con él (tests/test_backtest.py) le pasan ese 0,1 %. Una regla
# que opera mucho paga esto en cada compra y en cada venta.
COMISION = 0.005
# Con menos ruedas que esto no se prueba: no da para ver nada.
MIN_RUEDAS = 60
# ADX + Squeeze (versión A del estudio): «viene de un valle» es que el Squeeze
# estuvo negativo algún día de los últimos 5 (hoy incluido); «el ADX venía
# bajando», que bajó algún día de los 5 anteriores a hoy.
RUEDAS_VALLE = 5
RUEDAS_ADX_BAJANDO = 5


def senales(velas: list, regla: str) -> dict:
    """{'compra', 'venta', 'desde'}: dos listas del largo de `velas` (¿la regla
    dice comprar / vender al cierre de ese día?) y el primer índice en que la
    regla ya puede hablar (sus cuentas existen ese día y el anterior). Antes de
    `desde` no se prueba: la regla todavía no existe."""
    n = len(velas)
    cierres = [v["close"] for v in velas]
    compra, venta = [False] * n, [False] * n
    if regla in ("media200", "media50"):
        largo = 200 if regla == "media200" else 50
        m = tecnico.media(cierres, largo)
        for i, sentido in tecnico.cruces(cierres, m):
            (compra if sentido == "arriba" else venta)[i] = True
        return {"compra": compra, "venta": venta, "desde": _desde(n, [m], 1)}
    if regla == "rsi":
        r = tecnico.rsi(cierres)
        # Los niveles y el sentido de las alertas «sale de abajo de 30» y «sale
        # de arriba de 70».
        for senal, marca in (("rsi_sube_30", compra), ("rsi_baja_70", venta)):
            nivel, hacia = tecnico._RSI[senal]
            for i, sentido in tecnico.cruces(r, nivel):
                if sentido == hacia:
                    marca[i] = True
        return {"compra": compra, "venta": venta, "desde": _desde(n, [r], 1)}
    if regla == "adx_squeeze":
        sq = tecnico.squeeze(velas)["valor"]
        ax = tecnico.adx(velas)["adx"]
        for i in range(1, n):
            if None in (sq[i], sq[i - 1], ax[i], ax[i - 1]):
                continue
            valle = any(sq[k] is not None and sq[k] < 0 for k in range(max(0, i - RUEDAS_VALLE + 1), i + 1))
            bajaba = any(ax[k] is not None and ax[k - 1] is not None and ax[k] < ax[k - 1]
                         for k in range(max(1, i - RUEDAS_ADX_BAJANDO), i))
            compra[i] = (sq[i] > sq[i - 1] and valle and ax[i] > ax[i - 1] and bajaba
                         and ax[i] >= tecnico.ADX_CLAVE)
            montana_baja = sq[i] > 0 and sq[i] < sq[i - 1]
            venta[i] = (montana_baja and ax[i] < ax[i - 1]) or (sq[i - 1] > 0 and sq[i] <= 0)
        return {"compra": compra, "venta": venta,
                "desde": _desde(n, [sq, ax], max(RUEDAS_VALLE, RUEDAS_ADX_BAJANDO + 1))}
    raise ValueError(f"regla desconocida: {regla}")


def _desde(n: int, series: list, atras: int) -> int:
    """El primer índice i en que todas las `series` tienen valor desde i − atras
    hasta i: antes, la regla no puede decir nada. `n` si nunca."""
    for i in range(atras, n):
        if all(s[k] is not None for s in series for k in range(i - atras, i + 1)):
            return i
    return n


def simular(velas: list, senal: dict, desde_i: int, hasta_i: int, comision: float = COMISION) -> dict:
    """Sigue la regla de la vela `desde_i` a la `hasta_i` (inclusive) con 1 de
    plata. {'curva': lo que vale cada día al cierre, 'operaciones', 'ruedas_comprada'}.
    Las reglas de la simulación, arriba (CÓMO SE SIMULA)."""
    ab = tecnico.aperturas(velas)
    cs = [v["close"] for v in velas]
    compra, venta = senal["compra"], senal["venta"]
    caja, cant, entrada = 1.0, 0.0, None
    ops, curva, comprada = [], [], 0
    quiere_entrar = quiere_salir = False
    for i in range(desde_i, hasta_i + 1):
        if quiere_entrar and cant == 0 and ab[i] > 0:
            entrada = (i, ab[i])
            cant, caja = caja * (1 - comision) / ab[i], 0.0
        elif quiere_salir and cant > 0:
            caja = cant * ab[i] * (1 - comision)
            ops.append(_operacion(velas, entrada, i, ab[i], comision, abierta=False))
            cant = 0.0
        quiere_entrar = quiere_salir = False
        if cant > 0:
            comprada += 1
        ultimo = i == hasta_i
        if ultimo and cant > 0:
            caja = cant * cs[i] * (1 - comision)
            ops.append(_operacion(velas, entrada, i, cs[i], comision, abierta=True))
            cant = 0.0
        curva.append(caja + cant * cs[i])
        if not ultimo:
            if cant == 0 and compra[i]:
                quiere_entrar = True
            elif cant > 0 and venta[i]:
                quiere_salir = True
    return {"curva": curva, "operaciones": ops, "ruedas_comprada": comprada}


def _operacion(velas: list, entrada: tuple, i_salida: int, precio_salida: float,
               comision: float, abierta: bool) -> dict:
    """Una compra y su venta. `resultado` ya descuenta la comisión de los dos
    lados; `ruedas`: los días que estuvo comprada (el de la venta no: se vende a
    la apertura; si seguía comprada al final, el último sí)."""
    i_entrada, precio_entrada = entrada
    return {
        "compra": velas[i_entrada]["date"], "precio_compra": precio_entrada,
        "venta": velas[i_salida]["date"], "precio_venta": precio_salida,
        "resultado": precio_salida * (1 - comision) * (1 - comision) / precio_entrada - 1,
        "ruedas": i_salida - i_entrada + (1 if abierta else 0),
        "abierta": abierta,
    }


def mantener(velas: list, desde_i: int, hasta_i: int, comision: float = COMISION) -> list:
    """Comprar a la apertura de `desde_i` y no tocar nada: lo que vale cada día al
    cierre, con 1 de plata. El último día ya descuenta la comisión de vender."""
    entrada = tecnico.aperturas(velas)[desde_i]
    curva = [v["close"] / entrada * (1 - comision) for v in velas[desde_i:hasta_i + 1]]
    curva[-1] *= 1 - comision
    return curva


def peor_caida(curva: list) -> float:
    """Lo máximo que llegó a caer desde su mejor momento: −0,38 = −38 %."""
    tope, peor = None, 0.0
    for x in curva:
        tope = x if tope is None or x > tope else tope
        peor = min(peor, x / tope - 1)
    return peor


def sin_la_mejor(ops: list):
    """Si una sola compra explica el resultado: la mejor y lo que habría dado la
    regla sin ella. None con menos de 2 compras (sin la única no hay regla)."""
    if len(ops) < 2:
        return None
    mejor = max(range(len(ops)), key=lambda k: ops[k]["resultado"])
    total = 1.0
    for k, o in enumerate(ops):
        if k != mejor:
            total *= 1 + o["resultado"]
    return {"compra": ops[mejor]["compra"], "resultado": ops[mejor]["resultado"] * 100,
            "sin_ella": (total - 1) * 100}


def ventana(velas: list, anios: int, desde_regla: int) -> dict:
    """De qué vela a qué vela se prueba: los últimos `anios` años contados por
    CALENDARIO desde la última vela (`tecnico.primer_dia`, LA regla de la ficha,
    Comparar y «Una cartera»), y nunca antes de que la regla exista
    (`desde_regla`). {'desde_i', 'hasta_i', 'pedido_i', 'pedido_desde',
    'recortado'}: `recortado` si arranca después de lo pedido porque la regla
    necesita días antes que el papel no tiene (toda regla necesita al menos uno:
    un papel con menos historia que el período también cae acá)."""
    hasta_i = len(velas) - 1
    pedido_desde = tecnico.primer_dia(velas[-1]["date"], anios * tecnico.DIAS_ANIO)
    pedido_i = next((i for i, v in enumerate(velas) if v["date"] >= pedido_desde), hasta_i)
    desde_i = max(pedido_i, desde_regla)
    return {"desde_i": desde_i, "hasta_i": hasta_i, "pedido_i": pedido_i,
            "pedido_desde": pedido_desde, "recortado": desde_i > pedido_i}


def _resumen(curva: list) -> dict:
    """Resultado y peor caída en %, y en qué terminaron US$ 100. La peor caída se
    cuenta desde los US$ 100 del principio (el 1 de antes del primer día): el
    estudio la contaba desde el primer cierre, y a comprar y mantener le
    escondía lo que perdía el primer día (auditoría 04/11, H3)."""
    return {"resultado": (curva[-1] - 1) * 100, "peor_caida": peor_caida([1.0] + list(curva)) * 100,
            "final": curva[-1] * 100}


def _numero(x):
    """El número si es un precio que sirve (finito y mayor a 0); si no, None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def velas_que_sirven(velas: list) -> list:
    """Las velas con un cierre que sirve; a la apertura, el máximo o el mínimo que
    no sirve (0, vacío, infinito) se lo saca, y las cuentas lo completan como
    siempre (`tecnico.aperturas`, `tecnico._velas_completas`). Las que se guardan
    ya vienen así (`velas_diarias._velas_de`): esto es para que una vela rota
    nunca tire la ruta abajo con una división por cero (auditoría 04/11)."""
    out = []
    for v in velas:
        c = _numero(v.get("close"))
        if c is None:
            continue
        out.append({**v, "close": c, **{k: _numero(v.get(k)) for k in ("open", "high", "low")}})
    return out


def probar(velas: list, reglas: list, anios: int, comision: float = COMISION, *, hoy: date) -> dict:
    """La prueba entera sobre `velas` (sin base de datos: la usan la pantalla y
    las pruebas), de 1 a `MAX_REGLAS` reglas en el orden pedido. Todas sobre los
    MISMOS días: desde que existe la que más historia necesita (`recorte_por`, si
    eso corrió el principio), así se comparan entre ellas y con comprar y
    mantener en el mismo período. Una regla da lo mismo sola que comparada si el
    período no se corre. {'disponible': False, 'motivo': 'poca_historia', ...} si
    no da para probar, y 'vieja' si no tiene precios de la última semana contada
    desde `hoy` (`tecnico.es_vieja`: un papel que dejó de cotizar se probaba en
    «los últimos 2 años» terminados hace meses, sin avisar; auditoría de «Una
    cartera» 05/11, H9). `variacion_precio`: cuánto se movió el precio en el
    período (de la apertura del primer día al último cierre), sin comisiones: lo
    que la pantalla dice que «subió» o «bajó» el papel."""
    reglas = list(reglas)
    velas = velas_que_sirven(velas)
    if not velas:
        return {"reglas": reglas, "anios": anios, "disponible": False, "motivo": "poca_historia"}
    if tecnico.es_vieja(velas[-1]["date"], hoy):
        return {"reglas": reglas, "anios": anios, "disponible": False, "motivo": "vieja",
                "hasta": velas[-1]["date"]}
    s = {r: senales(velas, r) for r in reglas}
    limita = max(reglas, key=lambda r: s[r]["desde"])
    v = ventana(velas, anios, s[limita]["desde"])
    base = {"reglas": reglas, "anios": anios, "primera_vela": velas[0]["date"],
            "pedido_desde": v["pedido_desde"], "recortado": v["recortado"],
            "recorte_por": limita if v["desde_i"] > v["pedido_i"] else None}
    if v["hasta_i"] - v["desde_i"] + 1 < MIN_RUEDAS:
        return {**base, "disponible": False, "motivo": "poca_historia"}
    sims = {r: simular(velas, s[r], v["desde_i"], v["hasta_i"], comision) for r in reglas}
    m = mantener(velas, v["desde_i"], v["hasta_i"], comision)
    fechas = [x["date"] for x in velas[v["desde_i"]:v["hasta_i"] + 1]]
    return {
        **base,
        "disponible": True,
        "desde": fechas[0],
        "hasta": fechas[-1],
        "ruedas": len(fechas),
        "comision": comision * 100,
        "variacion_precio": (velas[v["hasta_i"]]["close"] / tecnico.aperturas(velas)[v["desde_i"]] - 1) * 100,
        "resultados": [_resultado(r, sims[r]) for r in reglas],
        "mantener": _resumen(m),
        "curva": [{"d": d, "mantener": round(m[k] * 100, 2),
                   **{r: round(sims[r]["curva"][k] * 100, 2) for r in reglas}} for k, d in enumerate(fechas)],
    }


def _resultado(regla: str, sim: dict) -> dict:
    """Lo de UNA regla: el resumen, sus compras y cada operación (en %)."""
    ops = sim["operaciones"]
    return {
        "regla": regla,
        **_resumen(sim["curva"]),
        "compras": len(ops),
        "ganadoras": sum(1 for o in ops if o["resultado"] > 0),
        "ruedas_comprada": sim["ruedas_comprada"],
        "sin_la_mejor": sin_la_mejor(ops),
        # Los precios con LA regla de la pantalla (`estructura.precio_redondo`):
        # con 4 decimales fijos, una cripto de fracciones de centavo (SHIB, PEPE)
        # llegaba «US$ 0 → US$ 0» (auditoría 04/11; la misma de la ficha, 22/10).
        "operaciones": [{**o, "resultado": o["resultado"] * 100,
                         "precio_compra": estructura.precio_redondo(o["precio_compra"]),
                         "precio_venta": estructura.precio_redondo(o["precio_venta"])} for o in ops],
    }


@pesado
def para_la_pantalla(conn, asset: str, reglas: list, anios: int, local: bool = False, *,
                     hoy: date) -> dict:
    """La prueba de `asset` con la serie en dólares de la ficha (`tecnico.serie`:
    la acción de afuera de un CEDEAR; una acción argentina, `local`, con su precio
    de BYMA ÷ el MEP de cada día). {'disponible': False} sin velas. `hoy`: el día
    argentino."""
    s = tecnico.serie(conn, asset, "usd", local)
    out = {"asset": (asset or "").upper(), "moneda": "usd", "reglas": list(reglas), "anios": anios}
    if not s["velas"]:
        return {**out, "disponible": False}
    return {**out, "ticker": s["ticker"], "convertida": s["convertida"],
            **probar(s["velas"], reglas, anios, hoy=hoy)}
