"""Por qué el número de esta persona está roto — el diagnosticador del reconstructor.

Es el agente reconstructor, reapuntado. La pregunta original ("¿esta entrada de
títulos fue aporte o traslado?") se midió contra producción y resultó vacía: de
154 pares COMPRA+DEPOSITO, **cero** eran traslados internos — los 15 usuarios
tienen UNA SOLA institución en Rendi, así que los títulos entraron desde afuera
y el depósito compensatorio es correcto. "Corregirlos" habría borrado aportes
reales. La pregunta con caseload real es ésta otra: **quién ve hoy un número que
no es el suyo, y por qué.**

READ-ONLY. Diagnostica, no toca nada. La corrección vive en `flujo_resoluciones`
(ver flujos.py) y está detrás de dos interruptores.

LAS CAUSAS RAÍZ (verificadas contra prod 2026-08-16 sobre 27 cuentas rotas)
──────────────────────────────────────────────────────────────────────────
R1 CONDUCTO DÓLAR-MEP DE COCOS — la pata en PESOS rotulada USD por el parser.
   Comprar dólar MEP son dos patas del mismo bono: se compra en pesos y se
   vende en dólares (o al revés). Si las dos quedan marcadas USD, una de las
   dos está en escala peso y el motor calcula una P&L de ~1.400×.
   🔴 TIENE DOS PATAS Y HAY QUE ARREGLARLAS JUNTAS. La positiva salta a la
   vista (pnl_pct de 150.000%); la negativa sale con **pnl_pct = −100 exacto**
   —costo peso-escala, ingresos USD— y parece una pérdida total normal, así que
   ningún umbral sobre pnl_pct la encuentra. Medido en uid 358: pata positiva
   +1.211.379, negativa −2.644.736. **Arreglar sólo la positiva lo deja PEOR**
   (pico 1.436.162 → 2.643.283). Esta clase de fix a medias es exactamente el
   daño que este módulo existe para no causar.

R2 RENTA DE balanz_resultados — cupón en pesos rotulado USD por la columna
   "Moneda Venta" del Excel. NO se puede arreglar solo: la columna original no
   se guardó, así que no hay dato bueno en ninguna parte. Y no hay umbral
   limpio: conviven dividendos USD legítimos de US$3 con cupones peso-escala de
   US$600.000, con ~64 filas en la banda ambigua. Encima el formato ya está
   bloqueado (`balanz_resultados.py`, BALANZ_RESULTADOS_NO_SOPORTADO), así que
   el usuario tampoco puede re-subir el archivo.

R3 PER-100 — el motor toma el COSTO de `gross_amount` (la caja real, ya
   escalada) y los INGRESOS de `unit_price × quantity` (sin escalar), así que
   todo el error del factor 100 cae en la P&L.
   🔴 SE CREÍA QUE ERA EL CASO MÁS FÁCIL Y ES EL MÁS PELIGROSO DE LOS TRES.
   El razonamiento viejo era "el número correcto ya está en la misma fila
   (`gross_amount/quantity`), basta re-correr el rebuild". Lo que ese
   razonamiento no miraba es el CASH: la venta acreditó `unit_price × quantity`,
   o sea 100× el monto real, y el rebuild NO toca cash. Medido: 151 ventas
   per-100 acreditaron ARS 55.977.251.272 + USD 16.580.658 de caja fantasma que
   sigue entrando a `snapshots.total_value`.
   El repo YA tiene un guard deployado que se niega a reconstruir exactamente
   estas cuentas por exactamente este motivo, y le puso nombre: **el crimen
   perfecto** (`importing/fx_migrate.py:249-276`) — el rebuild "arregla" la P&L,
   borra la firma `pnl_pct` que hoy delata la cuenta, y deja el patrimonio
   inventado en pantalla sin forma de volver a encontrarlo.
   Encima las 11 cuentas son `fx_version=v1`, donde el replay dolariza al blue
   VIVO del momento de la corrida (`rebuild.py:825`), así que el ensayo y el
   apply pueden dar distinto. R3 es de DOS pasos (cash primero, después P&L),
   como R1 — no de uno.

R4 RENTA CON LA MONEDA IGNORADA — el persister convierte por `brokers.currency`
   e ignora el `gross_amount_usd` que la fila importada ya trae bien. No es de
   IOL: es la forma de `_persist_dividend_or_interest` y aparece en 8 parsers
   (ieb 40, balanz_resultados 25, rendi_generic 14, balanz_movimientos 12,
   bullmarket 11, iol 5, cocos 4, ppi 1).
   Es la única de las cinco donde el valor correcto está de verdad al lado —
   pero el selector de diagnóstico es MÁS ANCHO que el de reparación: 27 filas
   que agarra hoy están BIEN (moneda inferida, `divisa=OTHER`) y 49 tienen el
   TC sellado a 1415,00 en cuentas fx v1. Ver `r4_renta_moneda_ignorada`.

R5 FLUJO MANUAL PESO-ESCALA — `manual_deposits`/`manual_withdrawals` gigantes
   con `manual_*_native = 0`. ⚠️ En la mayoría de los casos esto es SÍNTOMA, no
   causa: la P&L inflada de R1 llena el cash y después un seed o un
   reconcile-cash bookea el retiro espejo. Se distingue con el test del espejo
   (abajo). Es causa RAÍZ sólo cuando no hay import que lo explique.

⚠️ CAVEAT QUE ACOTA CUALQUIER PROMESA DE EXACTITUD: el 52% de las filas en
pesos de la base tiene `gross_amount_usd` estampado a **1415,00 exacto** (el
propio docstring de pipeline.py lo admite: 96% de los flujos en pesos, desde
2013 hasta 2026, con el mismo TC). O sea que "el valor correcto ya está en la
base" es cierto en ORDEN DE MAGNITUD, no al centavo — salvo para filas del día.
Un rebuild hereda ese error mientras no se arregle también el FX por fecha.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Ratio de precio a partir del cual las dos patas no pueden estar en la misma
# escala. Bien por encima de cualquier movimiento real y bien por debajo del
# dólar (~1.400) y del per-100.
RATIO_ESCALA = 300.0

# Un cupón/dividendo por encima de esto, rotulado USD y sin conversión aplicada
# (gross_amount == gross_amount_usd), es escala peso. Por debajo conviven
# dividendos legítimos: NO hay corte limpio, por eso R2 no se auto-arregla.
RENTA_SOSPECHOSA_USD = 1_000.0

# Cuánto tiene que parecerse el flujo manual a la inflación medida de la misma
# cuenta para llamarlo SÍNTOMA en vez de causa (test del espejo).
ESPEJO_TOL = 0.35

# Piso de DAÑO ABSOLUTO para entrar a la cola, en USD, y ratio mínimo
# capital-declarado / cartera. El piso viejo era 1.000.000 y ordenaba por
# tamaño de cliente en vez de por tamaño del error (ver `barrido`).
CAP_MIN_USD = 1_000.0
RATIO_MIN = 10.0

_VIVO = "b.status = 'confirmed' AND n.excluded_at IS NULL"


class _Fallas:
    """Acumula las sondas que no pudieron correr.

    🔴 Sin esto, un `try/except → return []` convierte una query ROTA en
    "no encontré nada", que es indistinguible de "esta cuenta está sana". Un
    diagnosticador que falla en silencio da de alta a un enfermo: es la peor
    falla posible en este módulo. Lo que no se pudo comprobar viaja en la
    respuesta y el veredicto lo dice.
    """

    def __init__(self):
        self.items: List[str] = []

    def anotar(self, sonda: str, err: Exception):
        msg = f"{sonda}: {type(err).__name__}: {err}"
        self.items.append(msg)
        log.exception("[diagnostico] %s", msg)


def _rows(conn, sql: str, p, sonda: str = "?", fallas: "_Fallas" = None) -> List[Any]:
    try:
        return conn.execute(sql, p).fetchall()
    except Exception as e:
        if fallas is not None:
            fallas.anotar(sonda, e)
        else:
            log.exception("[diagnostico] query falló en %s", sonda)
        return []


def r1_conducto_mep(conn, uid: int, fallas: '_Fallas' = None) -> Dict[str, Any]:
    """Las dos patas del conducto dólar-MEP, juntas.

    Detección por PAREJA ESPEJO, no por umbral de plata: una SELL de un batch
    de Cocos marcada USD que tiene su BUY gemela en el mismo batch, mismo
    activo, misma cantidad, a ≤5 días, con un ratio de precio imposible. Eso es
    un hecho estructural, no una heurística sobre montos.

    🔴 EL DETECTOR ES SIMÉTRICO Y TIENE QUE SERLO. La primera versión pedía
    `s.unit_price / c.unit_price > RATIO`, o sea encontraba SÓLO las cuentas
    donde la pata en pesos era la VENTA — mientras la query de daño de acá
    abajo ya miraba las dos direcciones. Medido contra prod: 5 usuarios (92,
    456, 520, 679, 718) tienen únicamente el par recíproco, y 3 de ellos eran
    exactamente los que el barrido reportaba como "sin causa conocida" (uid 679
    con −13,9M de daño). Peor que no verlos: la `regla` es DIRECCIONAL, así que
    aplicarles "re-etiquetar la SELL" re-etiquetaba la pata sana y dejaba la
    rota. Es el mismo fix a medias que este módulo existe para no cometer, sólo
    que del lado del detector. Por eso cada par viaja con `pata_peso`.
    """
    filas = _rows(conn, f"""
        SELECT s.id sell_id, s.date, s.asset_symbol, s.quantity,
               s.unit_price up_sell, c.unit_price up_buy,
               CASE WHEN s.unit_price > c.unit_price THEN 'sell' ELSE 'buy' END pata_peso,
               MAX(s.unit_price, c.unit_price) / MIN(s.unit_price, c.unit_price) ratio
          FROM import_normalized_tx s
          JOIN import_batches b ON b.id = s.batch_id
          JOIN import_normalized_tx c
            ON c.batch_id = s.batch_id
           AND UPPER(COALESCE(c.asset_symbol,'')) = UPPER(COALESCE(s.asset_symbol,''))
           AND ABS(ABS(COALESCE(c.quantity,0)) - ABS(COALESCE(s.quantity,0))) < 1e-6
           AND c.operation_type = 'BUY' AND c.currency = 'USD'
           AND c.excluded_at IS NULL
           AND ABS(julianday(c.date) - julianday(s.date)) <= 5
         WHERE b.user_id = ? AND b.status = 'confirmed' AND s.excluded_at IS NULL
           AND b.parser_format = 'cocos'
           AND s.operation_type = 'SELL' AND s.currency = 'USD'
           AND COALESCE(c.unit_price,0) > 0 AND COALESCE(s.unit_price,0) > 0
           AND MAX(s.unit_price, c.unit_price)
             / MIN(s.unit_price, c.unit_price) > ?""",
                  (uid, RATIO_ESCALA), "R1_import", fallas)
    if not filas:
        return {}

    # El DAÑO se mide en las dos patas de `operations`, no sólo en la que salta.
    dano = _rows(conn, """
        SELECT COALESCE(SUM(pnl_usd),0) neto,
               COALESCE(SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd ELSE 0 END),0) positiva,
               COALESCE(SUM(CASE WHEN pnl_usd < 0 THEN pnl_usd ELSE 0 END),0) negativa,
               COUNT(*) ops
          FROM operations
         WHERE user_id = ? AND entry_price > 0 AND exit_price > 0
           AND (exit_price/entry_price > ? OR entry_price/exit_price > ?)""",
                 (uid, RATIO_ESCALA, RATIO_ESCALA), "R1_ops", fallas)
    d = dano[0] if dano else None
    # El par SIN daño medible no es una cuenta rota. uid 456 en prod tiene el
    # par recíproco y `capital_declarado == cartera` al centavo: el mislabel
    # existe pero nunca llegó a una operación. Hacer simétrico el detector sin
    # esta guarda lo habría dado de alta como enfermo — cambiar un falso
    # negativo por un falso positivo no es progreso.
    if not d or not d["ops"]:
        return {}

    sell_peso = sum(1 for f in filas if f["pata_peso"] == "sell")
    buy_peso = len(filas) - sell_peso
    return {
        "causa": "R1_conducto_mep_cocos",
        "filas_import": len(filas),
        "pares_sell_en_pesos": sell_peso,
        "pares_buy_en_pesos": buy_peso,
        "ops_afectadas": d["ops"],
        "pnl_pata_positiva": round(float(d["positiva"]), 2),
        "pnl_pata_negativa": round(float(d["negativa"]), 2),
        "pnl_neto": round(float(d["neto"]), 2),
        "auto_arreglable": "si_con_revision",
        "regla": ("re-etiquetar a currency='ARS' LA PATA QUE `pata_peso` señala "
                  "en cada par —no siempre es la SELL— y re-estampar "
                  "gross_amount_usd con el MEP de su fecha, después rebuild"),
        "ojo": ("LAS DOS PATAS JUNTAS: la negativa sale con pnl_pct=-100 exacto "
                "y ningún umbral la ve. Arreglar sólo la positiva EMPEORA el "
                "número (medido en uid 358: 1.436.162 → 2.643.283). Y la pata "
                "en pesos NO siempre es la venta: acá hay "
                f"{sell_peso} par(es) con la venta en pesos y {buy_peso} con la "
                "compra — aplicar la regla de memoria rompe los del otro signo."),
        "muestra": [{"date": f["date"], "asset": f["asset_symbol"],
                     "precio_venta": f["up_sell"], "precio_compra": f["up_buy"],
                     "pata_peso": f["pata_peso"],
                     "ratio": round(float(f["ratio"]), 1)}
                    for f in filas[:5]],
    }


def r2_renta_balanz(conn, uid: int, fallas: '_Fallas' = None) -> Dict[str, Any]:
    """Cupón en pesos rotulado USD. NO auto-arreglable: no hay dato bueno."""
    filas = _rows(conn, f"""
        SELECT COUNT(*) n, COALESCE(SUM(n.gross_amount),0) suma,
               COALESCE(MAX(n.gross_amount),0) mayor
          FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
         WHERE b.user_id = ? AND {_VIVO}
           AND b.parser_format = 'balanz_resultados'
           AND n.operation_type IN ('INTEREST','DIVIDEND')
           AND n.currency = 'USD'
           AND ABS(COALESCE(n.gross_amount,0) - COALESCE(n.gross_amount_usd,0)) < 0.01
           AND COALESCE(n.gross_amount,0) > ?""", (uid, RENTA_SOSPECHOSA_USD), "R2", fallas)
    r = filas[0] if filas else None
    if not r or not r["n"]:
        return {}
    return {
        "causa": "R2_renta_balanz_resultados",
        "filas": r["n"],
        "suma_declarada_usd": round(float(r["suma"]), 2),
        "fila_mayor": round(float(r["mayor"]), 2),
        "auto_arreglable": "no_hace_falta_humano",
        "regla": None,
        "ojo": ("la columna 'Moneda Venta' del Excel NO se guardó, así que el "
                "valor correcto no está en ninguna parte. Y no hay umbral "
                "limpio: conviven dividendos USD reales con cupones peso-escala. "
                "El formato además está BLOQUEADO, así que tampoco puede "
                "re-subir el archivo."),
    }


def r3_per100(conn, uid: int, fallas: '_Fallas' = None) -> Dict[str, Any]:
    """Costo escalado, ingresos sin escalar. El número correcto está en la fila.

    ⚠️ ANCLADO EN `operations`, NO EN LA FORMA DE LA FILA. La firma
    `unit_price × quantity / gross_amount ≈ 100` es la CONVENCIÓN de cotización
    per-100 de los bonos, y está igual en la fila sana y en la rota: la fila
    guarda bien el precio per-100 y bien la caja. El defecto aparece un paso
    después, cuando el motor construye la operación tomando el `unit_price`
    crudo en vez de `gross_amount/quantity`.

    Medido contra prod sobre los 12 usuarios que la firma toca: 143 de 143
    operaciones ligadas tomaron el precio CRUDO y ninguna el escalado — o sea
    que hoy la firma no tiene falsos positivos. Pero anclar en la operación es
    lo que permite (a) medir el daño en vez de contar filas, (b) sacar los
    casos sin daño —uid 733 tiene la fila y cero operaciones ligadas— y (c)
    decir el caseload de verdad: 12 usuarios, no 4. Los otros 8 caen fuera de
    la banda del barrido, no fuera de la causa.
    """
    filas = _rows(conn, f"""
        WITH p100 AS (
            SELECT n.raw_row_id, n.batch_id, n.unit_price, n.quantity,
                   n.gross_amount, n.gross_amount_usd
              FROM import_normalized_tx n JOIN import_batches b ON b.id = n.batch_id
             WHERE b.user_id = ? AND {_VIVO}
               AND COALESCE(n.quantity,0) <> 0 AND COALESCE(n.gross_amount,0) <> 0
               AND ABS(n.unit_price * n.quantity / n.gross_amount - 100) < 0.5
        ),
        afectadas AS (
            SELECT DISTINCT o.id, o.pnl_usd
              FROM p100
              -- El link se cruza por (raw_row_id, batch_id), no sólo por
              -- raw_row_id: en prod hay 34.447 raw_row_id con más de una
              -- operación ligada. Para esta familia hoy da lo mismo (medido),
              -- pero el día que no dé lo mismo el diagnóstico y la reparación
              -- tienen que contar LO MISMO o el antes/después no cierra.
              JOIN import_op_links l ON l.raw_row_id = p100.raw_row_id
                                    AND l.batch_id = p100.batch_id
              JOIN operations o ON o.id = l.operation_id
             WHERE o.user_id = ?
               AND (ABS(COALESCE(o.exit_price,0) - p100.unit_price)
                      < 0.01 * ABS(p100.unit_price)
                 OR ABS(COALESCE(o.entry_price,0) - p100.unit_price)
                      < 0.01 * ABS(p100.unit_price))
        )
        SELECT (SELECT COUNT(*) FROM p100) filas,
               (SELECT COUNT(*) FROM afectadas) ops,
               (SELECT COALESCE(SUM(pnl_usd),0) FROM afectadas) pnl,
               (SELECT COALESCE(SUM(gross_amount_usd),0) FROM p100) suma""",
                  (uid, uid), "R3", fallas)
    r = filas[0] if filas else None
    # Sin operación afectada no hay número roto que mostrarle a nadie.
    if not r or not r["ops"]:
        return {}
    return {
        "causa": "R3_per100",
        "filas": r["filas"],
        "ops_afectadas": r["ops"],
        "pnl_declarado_usd": round(float(r["pnl"]), 2),
        "suma_usd": round(float(r["suma"]), 2),
        "auto_arreglable": "si_deterministico",
        "regla": ("el precio efectivo es gross_amount/quantity — es lo que ya "
                  "hace persister.reconciled_unit_price; basta re-correr el "
                  "rebuild sobre las filas guardadas. No hay que inferir ningún TC."),
        "ojo": None,
    }


def r4_renta_moneda_ignorada(conn, uid: int, fallas: '_Fallas' = None) -> Dict[str, Any]:
    """El persister convirtió por brokers.currency ignorando el USD de la fila.

    ⚠️ SE LLAMABA "R4_renta_iol" Y ESO HACÍA CREER QUE ERA UN BUG DE UN PARSER.
    No lo es: es la forma de `_persist_dividend_or_interest`, que convierte por
    `brokers.currency`. Distribución real base-wide: ieb 40, balanz_resultados
    25, rendi_generic 14, balanz_movimientos 12, bullmarket 11, iol 5, cocos 4,
    ppi 1. Buscarle la culpa a IOL mandaba la investigación al lugar equivocado.

    🔴 EL SELECTOR NO ALCANZA PARA REPARAR. Dos cosas medidas contra prod que
    tiene que saber cualquiera que quiera escribir desde acá:

    1. 27 de estas filas HOY ESTÁN BIEN. Son dólares con `currency` rotulada
       'ARS' porque el parser ieb no supo la divisa y el normalizer cayó a ARS;
       la marca está en la propia fila (`notes LIKE '%divisa=OTHER%'`) y se
       confirma sola: reaparecen días después como acreditación en USD por el
       MISMO monto exacto. "Corregirlas" las achica ~1.200× y borra US$424 de
       renta real de uid 870.
    2. 49 de 112 filas tienen `gross_amount_usd` sellado al TC plano 1415,00, y
       las dos cuentas que las tienen (812, 870) son fx_version=v1 — o sea que
       TODOS sus flujos están al mismo sello. Poner el P&L al MEP histórico
       dejando los flujos al 1415 es migrar UNA SOLA PATA, que es el patrón que
       en este repo ya llevó un error de 1,23× a 9,1×.

    Por eso acá el veredicto es `si_deterministico` para el DIAGNÓSTICO y no una
    licencia para escribir: la reparación necesita su propio selector, más
    angosto que éste.
    """
    filas = _rows(conn, f"""
        SELECT COUNT(*) n, COALESCE(SUM(o.pnl_usd),0) declarado,
               COALESCE(SUM(n.gross_amount_usd),0) correcto,
               COALESCE(SUM(CASE WHEN UPPER(COALESCE(n.notes,''))
                                      LIKE '%DIVISA=OTHER%' THEN 1 ELSE 0 END),0) moneda_inferida,
               COALESCE(SUM(CASE WHEN ABS(n.gross_amount
                                        / NULLIF(n.gross_amount_usd,0) - 1415.0) < 0.01
                                 THEN 1 ELSE 0 END),0) sello_1415
          FROM operations o
          JOIN import_op_links l ON l.operation_id = o.id
          JOIN import_normalized_tx n ON n.raw_row_id = l.raw_row_id
                                     AND l.batch_id = n.batch_id
          JOIN import_batches b ON b.id = n.batch_id
         WHERE o.user_id = ? AND {_VIVO}
           AND n.currency = 'ARS'
           AND ABS(COALESCE(o.pnl_usd,0) - COALESCE(n.gross_amount,0)) < 0.01
           AND ABS(COALESCE(n.gross_amount,0) - COALESCE(n.gross_amount_usd,0)) > 1""",
                  (uid,), "R4", fallas)
    r = filas[0] if filas else None
    if not r or not r["n"]:
        return {}
    return {
        "causa": "R4_renta_moneda_ignorada",
        "filas": r["n"],
        "declarado_usd": round(float(r["declarado"]), 2),
        "correcto_usd": round(float(r["correcto"]), 2),
        "filas_moneda_inferida": r["moneda_inferida"],
        "filas_con_sello_1415": r["sello_1415"],
        "auto_arreglable": "si_deterministico",
        "regla": ("operations.pnl_usd := import_normalized_tx.gross_amount_usd "
                  "de la fila linkeada (el valor correcto ya está guardado ahí) "
                  "— PERO sólo sobre las filas que no están en "
                  "`filas_moneda_inferida`, que hoy están bien"),
        "ojo": (None if not (r["moneda_inferida"] or r["sello_1415"]) else
                (f"{r['moneda_inferida']} fila(s) tienen la moneda INFERIDA "
                 f"(divisa=OTHER): están bien y no se tocan. "
                 f"{r['sello_1415']} tienen el TC sellado a 1415,00: en cuenta "
                 f"fx v1 hay que dejarlas al sello, no pasarlas al MEP "
                 f"histórico, o se migra una sola pata del FX.")),
    }


def r5_manual_huerfano(conn, uid: int, inflacion_medida: float, fallas: '_Fallas' = None) -> Dict[str, Any]:
    """Flujo manual peso-escala. Distingue CAUSA de SÍNTOMA con el espejo.

    En 8 de 11 cuentas el manual gigante era el REFLEJO de la P&L inflada de
    R1: el motor llenó el cash y después un seed o un reconcile-cash bookeó el
    retiro espejo. Si el monto manual se parece a la inflación medida de la
    misma cuenta, es síntoma — arreglar R1 lo arrastra. Sólo es causa raíz
    cuando no hay import que lo explique.
    """
    filas = _rows(conn, """
        SELECT COALESCE(SUM(ABS(manual_deposits)),0) dep,
               COALESCE(SUM(ABS(manual_withdrawals)),0) wd
          FROM monthly_entries
         WHERE user_id = ? AND broker <> 'global'
           AND (ABS(COALESCE(manual_deposits,0)) > 50000
                OR ABS(COALESCE(manual_withdrawals,0)) > 50000)
           AND COALESCE(manual_deposits_native,0) = 0
           AND COALESCE(manual_withdrawals_native,0) = 0""", (uid,), "R5", fallas)
    r = filas[0] if filas else None
    if not r or (not r["dep"] and not r["wd"]):
        return {}
    monto = max(float(r["dep"]), float(r["wd"]))
    espejo = (abs(monto - abs(inflacion_medida)) / max(abs(inflacion_medida), 1)
              if inflacion_medida else None)
    es_sintoma = espejo is not None and espejo <= ESPEJO_TOL
    return {
        "causa": "R5_manual_huerfano",
        "manual_deposits": round(float(r["dep"]), 2),
        "manual_withdrawals": round(float(r["wd"]), 2),
        "espejo_vs_inflacion": round(espejo, 3) if espejo is not None else None,
        "es_sintoma_de_otra_causa": es_sintoma,
        "auto_arreglable": "si_con_revision" if es_sintoma else "no_hace_falta_humano",
        "regla": ("si es síntoma, se corrige solo al arreglar la causa de arriba; "
                  "si es raíz, NO hay verdad de referencia — hay que preguntarle "
                  "al usuario, no inferir"),
        "ojo": None,
    }


def de_usuario(conn, uid: int) -> Dict[str, Any]:
    """El diagnóstico completo de una persona. NO ESCRIBE NADA."""
    pico = conn.execute(
        "SELECT COALESCE(MAX(ABS(capital_final)),0) m FROM monthly_entries "
        "WHERE user_id=? AND broker='global'", (uid,)).fetchone()["m"]
    snap = conn.execute(
        "SELECT total_value, net_deposited, date FROM snapshots WHERE user_id=? "
        "ORDER BY date DESC LIMIT 1", (uid,)).fetchone()
    cartera = float(snap["total_value"]) if snap else 0.0

    fallas = _Fallas()
    causas = []
    for c in (r1_conducto_mep(conn, uid, fallas), r2_renta_balanz(conn, uid, fallas),
              r3_per100(conn, uid, fallas),
              r4_renta_moneda_ignorada(conn, uid, fallas)):
        if c:
            causas.append(c)
    infl = next((c["pnl_pata_positiva"] for c in causas
                 if c["causa"] == "R1_conducto_mep_cocos"), 0.0)
    m = r5_manual_huerfano(conn, uid, infl, fallas)
    if m:
        causas.append(m)

    return {
        "user_id": uid,
        "capital_declarado": round(float(pico), 2),
        "cartera_real": round(cartera, 2),
        "ratio": round(pico / cartera, 1) if cartera > 0 else None,
        "ultimo_snapshot": snap["date"] if snap else None,
        "causas": causas,
        # Lo que NO se pudo comprobar viaja al lado del resultado. Sin esto, una
        # sonda rota se lee como "esta cuenta está sana".
        "sondas_fallidas": fallas.items,
        "veredicto": _veredicto(causas, pico, cartera, fallas.items),
    }


def _veredicto(causas: List[Dict[str, Any]], pico: float, cartera: float,
               fallidas: List[str] = None) -> str:
    if fallidas:
        return (f"⚠️ DIAGNÓSTICO INCOMPLETO: {len(fallidas)} sonda(s) no pudieron "
                f"correr ({'; '.join(fallidas[:2])}). NO tomes la ausencia de "
                f"causas como que la cuenta está sana.")
    if not causas:
        return ("Sin causa conocida. Si el ratio es alto igual, hay una familia "
                "que este diagnosticador todavía no cubre — no inventes una.")
    nombres = [c["causa"] for c in causas]
    auto = [c for c in causas if c["auto_arreglable"] == "si_deterministico"]
    humano = [c for c in causas if c["auto_arreglable"] == "no_hace_falta_humano"
              and not c.get("es_sintoma_de_otra_causa")]
    partes = [f"Causas: {', '.join(nombres)}."]
    if auto:
        partes.append(f"{len(auto)} se arregla(n) solo(s): el valor correcto ya "
                      f"está guardado en la propia fila.")
    if humano:
        partes.append(f"{len(humano)} NO se puede(n) arreglar sin el usuario: no "
                      f"hay dato de referencia en ninguna parte.")
    if "R1_conducto_mep_cocos" in nombres:
        partes.append("⚠️ R1 tiene DOS patas — arreglar sólo la positiva EMPEORA "
                      "el número.")
    return " ".join(partes)


def barrido(conn, limite: int = 120, cap_min: float = None,
            ratio_min: float = None) -> Dict[str, Any]:
    """Diagnostica a todos los que tienen el capital declarado muy por encima de
    su cartera. Es la cola de trabajo del reconstructor.

    🔴 EL PISO ERA `cap > 1.000.000` Y ESO ORDENA POR PESOS ABSOLUTOS. Medido
    contra prod: dejaba afuera a 37 usuarios con ratio>10 sólo por tener la
    cartera chica — uid 859 está 2.062× mal sobre US$390, uid 718 tiene 624k de
    daño medido. En una app retail eso descarta primero justo a quien un error
    de 2.000× más desorienta. El piso ahora es de DAÑO ABSOLUTO, no de tamaño
    de cliente.

    Y las tres exclusiones dejaron de ser silenciosas: quien no se pudo rankear
    (sin snapshot, o cartera en 0 — que es síntoma, no salud) viaja en
    `no_rankeables` en vez de desaparecer. Un barrido que no dice a quién no
    miró se lee como si hubiera mirado a todos.
    """
    cap_min = CAP_MIN_USD if cap_min is None else float(cap_min)
    ratio_min = RATIO_MIN if ratio_min is None else float(ratio_min)

    pob = _rows(conn, """
        WITH mx AS (SELECT user_id uid, MAX(ABS(capital_final)) cap
                      FROM monthly_entries WHERE broker='global' GROUP BY 1),
             last AS (SELECT s.user_id uid, s.total_value tv FROM snapshots s
                       WHERE s.date = (SELECT MAX(x.date) FROM snapshots x
                                        WHERE x.user_id = s.user_id))
        SELECT mx.uid, mx.cap, last.tv
          FROM mx LEFT JOIN last ON last.uid = mx.uid""", (), "poblacion")

    en_banda, no_rank, bajo_ratio, bajo_cap = [], [], 0, 0
    for r in pob:
        cap, tv = float(r["cap"] or 0), r["tv"]
        if tv is None or float(tv) <= 0:
            no_rank.append(r["uid"])
            continue
        ratio = cap / float(tv)
        if ratio <= ratio_min:
            bajo_ratio += 1
        elif cap <= cap_min:
            bajo_cap += 1
        else:
            en_banda.append((ratio, r["uid"]))
    en_banda.sort(reverse=True)
    uids = [u for _, u in en_banda[:limite]]

    diags, por_causa, sin_causa = [], {}, []
    for u in uids:
        d = de_usuario(conn, u)
        diags.append(d)
        if not d["causas"]:
            sin_causa.append(u)
        for c in d["causas"]:
            if c.get("es_sintoma_de_otra_causa"):
                continue
            por_causa.setdefault(c["causa"], []).append(u)

    return {
        "revisados": len(uids),
        "truncado": len(en_banda) > len(uids),
        "en_banda": len(en_banda),
        "umbrales": {"cap_min_usd": cap_min, "ratio_min": ratio_min},
        "por_causa": {k: {"usuarios": len(v), "uids": v[:40]}
                      for k, v in sorted(por_causa.items(),
                                         key=lambda kv: -len(kv[1]))},
        "sin_causa_conocida": sin_causa,
        # A quién NO se miró, y por qué. Sin esto el barrido se lee como censo.
        "no_mirados": {
            "no_rankeables": {
                "usuarios": len(no_rank), "uids": no_rank[:40],
                "por_que": ("sin snapshot o cartera <= 0, así que no hay ratio "
                            "que calcular. Cartera en 0 es SÍNTOMA, no salud: "
                            "estos no están descartados, están sin diagnosticar."),
            },
            "bajo_ratio": bajo_ratio,
            "bajo_piso_de_dano": bajo_cap,
        },
        "detalle": diags[:40],
        "caveat": ("el 52% de las filas ARS tiene gross_amount_usd estampado a "
                   "1415,00 exacto: cualquier corrección hereda ese error "
                   "mientras el FX por fecha no se arregle. Orden de magnitud, "
                   "no centavos."),
    }
