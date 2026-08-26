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


def _ym(fecha: str) -> str:
    return str(fecha)[:7]


def benchmark_recortado(datos: dict, fechas: list, clave: str) -> list:
    """El benchmark indexado a 1.0 en la MISMA fecha en que arranca el usuario.

    `datos` es {YYYY-MM: valor} (nivel de precio, o % mensual si `clave` está en
    BENCH_PORCENTUAL). `fechas` son las fechas de la curva del usuario, en orden.

    Devuelve un punto por cada fecha del usuario — misma longitud, mismo arranque,
    mismo final. Si para un mes no hay dato del benchmark se arrastra el último
    conocido: eso NO es interpolar un valor inventado, es decir "el índice no
    publicó todavía", y el arrastre es plano y visible.
    """
    if not datos or not fechas:
        return []
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


def performance(conn, uid: int, bench_data: dict, bench_key: str = "sp500",
                desde: str = None, hasta: str = None, valor_live: float = None,
                incluir_indeterminado: bool = False,
                modo: str = twr.MODO_CERTERO) -> dict:
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
                           valor_live=valor_live)
    fechas = [p["date"] for p in c["curva"]]
    serie_b = (bench_data or {}).get(bench_key) or {}
    bench = benchmark_recortado(serie_b, fechas, bench_key)

    return {
        "curva": c["curva"],
        "benchmark": bench,
        "benchmark_key": bench_key,
        # La banda gris: la reconstrucción CONTABLE. Se dibuja aparte, fuera del
        # índice y nunca como continuación de la línea medida.
        "contable": c["contable"],
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
        "drawdown_actual": c["drawdown_actual"],
        "drawdown_maximo": c["drawdown_maximo"],
        "drawdown_maximo_fecha": c["drawdown_maximo_fecha"],
        "drawdown_maximo_pico": c["drawdown_maximo_pico"],
        "motivo": c["motivo"],
        "motivo_texto": c["motivo_texto"],
    }
