"""La sección Performance, servida entera desde un solo lugar.

Existe por una razón concreta: mientras cada pantalla arme su propia curva en JS
sobre la cadena contable, cualquier guard nuevo en Python se queda corto. Ya pasó
—`applyMtmToMonthly` descarta sintéticos (insightsModel.js:621) y se abstiene sin
borde medido (:653), y trece líneas después `buildCumulativeReturnSeries` (:106)
pisa el cierre con el valor live sin mirar `m.mtm` y desarma el guard entero— y
había TRES motores independientes produciendo el mismo acantilado:
`insightsModel.js:106`, `Insights.jsx:698-701` y `evolution.js:234/:317`.

Acá se arma la curva del usuario (vía `twr.curva_indexada`) y la del benchmark
RECORTADA AL MISMO RANGO. Ese recorte es lo que hace justa la comparación: hoy el
S&P se dibuja completo y la cartera no, así que arrancan de puntos distintos y el
usuario compara su tramo contra la historia entera del índice.
"""
import twr

# Benchmarks que vienen como VARIACIÓN mensual (%) en vez de nivel de precio.
# Se componen; los otros se rebasean contra su primer valor del rango.
BENCH_PORCENTUAL = ("inflation_ar", "plazo_fijo")

# Benchmarks cuyo precio YA ESTÁ EN PESOS. Multiplicarlos por el TC los contaría
# dos veces: el Merval cotiza en pesos y el UVA es un coeficiente en pesos. Sólo
# los índices en dólares (S&P, T-Bills, oro) se convierten para la vista en pesos.
BENCH_EN_ARS = ("merval", "uva", "plazo_fijo", "inflation_ar")


def _ym(fecha: str) -> str:
    return str(fecha)[:7]


def _es_diario(datos: dict) -> bool:
    """¿Las claves son fechas (YYYY-MM-DD) y no meses (YYYY-MM)?"""
    for k in datos:
        return len(str(k)) == 10
    return False


def _benchmark_diario(datos: dict, fechas: list) -> list:
    """El benchmark a resolución DIARIA, indexado a 1.0 en la primera fecha de la
    curva que tenga cierre.

    ⚠️ POR QUÉ EXISTE. Medido en producción (AUDIT_benchmark_2026-09-01): con el
    mapa MENSUAL, la línea del S&P sobre una curva diaria tenía 2 valores distintos
    (mediana) en 44 filas, 64 usuarios la veían plana en 0%, y contra el índice
    real entre las mismas fechas el número difería más de 1 pp en 220 de 484 —
    con el SIGNO dado vuelta en 21. El ancla era el cierre de FIN del primer mes,
    así que lo que el S&P hacía entre el primer día medido y ese fin de mes
    desaparecía de la comparación. Y nadie tiene más de tres meses medidos: un
    desfasaje de hasta un mes en el ancla ES la comparación.

    Para cada fecha: el cierre de ese día o del último hábil anterior (un fin de
    semana arrastra el viernes: eso no inventa nada). "hoy" toma el último cierre.
    Antes del primer cierre disponible el punto va con `index: None` — la línea
    no se dibuja ahí, en vez de dibujarse relativa a un valor que no es suyo.
    """
    import bisect
    claves = sorted(k for k, v in datos.items() if v is not None)
    if not claves:
        return []
    ultima = claves[-1]

    def _cierre(f):
        if f == "hoy":
            return float(datos[ultima])
        f = str(f)[:10]
        i = bisect.bisect_right(claves, f)
        if i == 0:
            return None
        try:
            v = float(datos[claves[i - 1]])
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    out, base = [], None
    for f in fechas:
        c = _cierre(f)
        if c is None:
            out.append({"date": f, "index": None})
            continue
        if base is None:
            base = c
        out.append({"date": f, "index": round(c / base, 6)})
    return out


def benchmark_recortado(datos: dict, fechas: list, clave: str) -> list:
    """El benchmark indexado a 1.0 en la MISMA fecha en que arranca el usuario.

    `datos` es {YYYY-MM: valor} (nivel de precio, o % mensual si `clave` está en
    BENCH_PORCENTUAL) — o, para los índices de precio, {YYYY-MM-DD: cierre}, en
    cuyo caso resuelve por FECHA (ver `_benchmark_diario`). `fechas` son las
    fechas de la curva del usuario, en orden.

    Devuelve un punto por cada fecha del usuario — misma longitud, mismo arranque,
    mismo final. Si para un mes no hay dato del benchmark se arrastra el último
    conocido: eso NO es interpolar un valor inventado, es decir "el índice no
    publicó todavía", y el arrastre es plano y visible.
    """
    if not datos or not fechas:
        return []
    if clave not in BENCH_PORCENTUAL and _es_diario(datos):
        return _benchmark_diario(datos, fechas)
    meses = sorted(datos)
    base_ym = _ym(fechas[0])

    if clave in BENCH_PORCENTUAL:
        # % mensual → índice compuesto desde el mes base.
        idx, por_mes = 1.0, {}
        for ym in meses:
            if ym < base_ym:
                continue
            if ym > base_ym:
                try:
                    idx *= (1.0 + float(datos[ym]) / 100.0)
                except (TypeError, ValueError):
                    pass
            por_mes[ym] = idx
    else:
        # Nivel de precio → rebase contra el nivel del mes base.
        base_val = None
        for ym in meses:
            if ym <= base_ym:
                try:
                    v = float(datos[ym])
                except (TypeError, ValueError):
                    continue
                if v > 0:
                    base_val = v
        if not base_val:
            return []
        por_mes = {}
        for ym in meses:
            if ym < base_ym:
                continue
            try:
                v = float(datos[ym])
            except (TypeError, ValueError):
                continue
            if v > 0:
                por_mes[ym] = v / base_val

    out, ultimo = [], 1.0
    for f in fechas:
        ym = _ym(f) if f != "hoy" else (max(por_mes) if por_mes else base_ym)
        if ym in por_mes:
            ultimo = por_mes[ym]
        else:                       # sin dato ese mes: se arrastra, plano y visible
            anteriores = [k for k in por_mes if k <= ym]
            if anteriores:
                ultimo = por_mes[max(anteriores)]
        out.append({"date": f, "index": round(ultimo, 6)})
    return out


def _en_pesos(bench: list, fx) -> list:
    """El benchmark expresado en PESOS y re-anclado a 1,0 en su primera fecha.

    Un índice en dólares comparado contra una cartera medida en pesos no es una
    comparación: le falta la devaluación, que es justamente lo que separa las dos
    monedas. El S&P en pesos es `precio × TC` — lo que valdría en pesos la misma
    plata puesta en el índice.

    Los benchmarks PORCENTUALES (inflación, plazo fijo UVA) no pasan por acá: ya
    están en pesos por naturaleza.
    """
    out, base = [], None
    for p in bench:
        i = p.get("index")
        f = fx(p["date"]) if fx is not None else None
        if i is None or not f:
            out.append({"date": p["date"], "index": None})
            continue
        v = float(i) * float(f)
        if base is None:
            base = v
        out.append({"date": p["date"], "index": round(v / base, 6)})
    return out


def performance(conn, uid: int, bench_data: dict, bench_key: str = "sp500",
                desde: str = None, hasta: str = None, valor_live: float = None,
                incluir_indeterminado: bool = False,
                modo: str = twr.MODO_CERTERO,
                moneda: str = twr.MONEDA_USD) -> dict:
    """Todo lo que la sección Performance necesita, en una sola respuesta.

    `modo`:
      · CERTERO (default) — sólo lo valuado a PRECIO REAL. Incluye las fotos del
        cron Y la reconstrucción histórica: para un CEDEAR o una acción la
        reconstrucción es EXACTA, no una estimación. La línea divisoria no es
        "cron vs reconstrucción", es "precio real vs costo".
      · ESTIMADO — la historia completa, incluyendo lo que no tiene precio
        histórico y va al costo. La respuesta declara cuánto y de qué instrumentos.
    """
    # ACEPTA_LINEA, no BASE_MERCADO: la intradía sostiene la línea con apto=False.
    aceptar = twr.ACEPTA_LINEA + ((twr.INDETERMINADO,) if incluir_indeterminado else ())
    c = twr.curva_indexada(conn, uid, desde, hasta, modo=modo, aceptar=aceptar,
                           valor_live=valor_live, moneda=moneda)
    fechas = [p["date"] for p in c["curva"]]
    # ⚠️ DIARIO PRIMERO. `<clave>_d` es la serie por fecha que llena
    # `_benchmarks_fetch_and_cache`; el mensual queda para los porcentuales y para
    # cuando el diario no cubre ninguna fecha de la curva (historia más vieja que
    # la ventana bajada): ahí el mensual tampoco la cubre, pero se mantiene el
    # comportamiento anterior en vez de devolver una lista de None.
    bd = bench_data or {}
    bench, resolucion = [], "mensual"
    serie_d = bd.get(f"{bench_key}_d") or {}
    if serie_d and bench_key not in BENCH_PORCENTUAL and _es_diario(serie_d):
        bench = benchmark_recortado(serie_d, fechas, bench_key)
        if any(p.get("index") is not None for p in bench):
            resolucion = "diaria"
        else:
            bench = []
    if not bench:
        serie_b = bd.get(bench_key) or {}
        bench = benchmark_recortado(serie_b, fechas, bench_key)
    # En PESOS el índice de precio se pasa a pesos y se re-ancla; los porcentuales
    # (inflación, plazo fijo) ya están en pesos y no se tocan.
    if moneda == twr.MONEDA_ARS and bench and bench_key not in BENCH_EN_ARS:
        _fx_b, _ = twr.serie_fx(conn, None, hasta)
        bench = _en_pesos(bench, _fx_b)

    return {
        "curva": c["curva"],
        "benchmark": bench,
        "benchmark_key": bench_key,
        # Con qué resolución viene `benchmark`: 'diaria' cuando cada punto es el
        # cierre de SU fecha; 'mensual' cuando es el cierre del mes.
        "benchmark_resolucion": resolucion,
        # En qué MONEDA está medido todo lo de esta respuesta, y con qué riel de
        # dólar se convirtió (mep/blue). El retorno en pesos incluye la
        # devaluación; el de dólares, no. Son dos números distintos y correctos.
        "moneda": c.get("moneda", moneda),
        "riel_fx": c.get("riel_fx"),
        # La banda gris: la reconstrucción CONTABLE. Se dibuja aparte, fuera del
        # índice y nunca como continuación de la línea medida. En pesos va en
        # pesos: es un monto, y un eje en dólares al lado de una curva en pesos
        # es la misma mezcla de unidades que este trabajo viene cerrando.
        "contable": ([{**b, "value_no_medible": round(b["value_no_medible"] * _f, 2)}
                      for b in c["contable"]
                      for _f in [(twr.serie_fx(conn, None, hasta)[0](b["date"]) or 0)]
                      if _f] if moneda == twr.MONEDA_ARS else c["contable"]),
        "medido_desde": c["medido_desde"],
        "medido_hasta": c["medido_hasta"],
        "cobertura": c["cobertura"],
        "cobertura_reconstruccion": c["cobertura_reconstruccion"],
        # La cobertura como NÚMERO y con nombres, no como semáforo: "94% de tu
        # cartera valuada a precio real · el 6% restante (tus FCI) va al costo".
        "instrumentos_al_costo": c.get("instrumentos_al_costo", []),
        "modo": c.get("modo", modo),
        "por_clase": c["por_clase"],
        "tramos": len(c["tramos"]),
        # `tramos_medidos` es el que el frontend necesita para gatear: `tramos`
        # cuenta los pedazos de la serie, no cuántos produjeron un retorno. Sin
        # esto, gatear por `perf.tramos_medidos` daba undefined y no gateaba nada.
        "tramos_medidos": c.get("tramos_medidos", 0),
        "serie_partida": c.get("serie_partida", False),
        "tramos_detalle": c.get("tramos_detalle", []),
        "twr": c["twr"],
        "cagr": c["cagr"],
        # ⚠️ FASE 2 · CON QUÉ REGLA SE CALCULÓ `twr`, Y QUÉ NO CUENTA.
        # Esta respuesta es una LISTA BLANCA explícita —es el contrato del
        # endpoint—, así que un campo nuevo en `curva_indexada` no llega solo: los
        # dos de abajo salían None en el JSON mientras el motor los calculaba bien.
        # Sin ellos el frontend no puede distinguir un +16,9% reconstruido de uno
        # medido, y la pantalla no puede declarar el sesgo que el modo tiene.
        "base_del_twr": c.get("base_del_twr"),
        "excluye_no_realizado": c.get("excluye_no_realizado", False),
        # La ventana que el número REALMENTE cubre (≠ `medido_desde`, que describe
        # todos los puntos aptos). En estimado es la del tramo contable publicado.
        "ventana_desde": c.get("ventana_desde"),
        "ventana_hasta": c.get("ventana_hasta"),
        "drawdown_actual": c["drawdown_actual"],
        "drawdown_maximo": c["drawdown_maximo"],
        "drawdown_maximo_fecha": c["drawdown_maximo_fecha"],
        "drawdown_maximo_pico": c["drawdown_maximo_pico"],
        "motivo": c["motivo"],
        "motivo_texto": c["motivo_texto"],
        # Los legs que no se encadenaron por no ser creíbles (`twr.leg_dudoso`).
        "cortes_dudosos": c.get("cortes_dudosos", []),
        "contable_superado": c.get("contable_superado", 0),
        "contable_realineado": c.get("contable_realineado", 0),
    }
