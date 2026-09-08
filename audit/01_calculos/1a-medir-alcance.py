#!/usr/bin/env python3
"""Mide el ALCANCE REAL en producción de los hallazgos urgentes de la auditoría.

SOLO LECTURA. Abre la base en modo `ro` (el motor rechaza cualquier escritura) y
corre 13 SELECT. Imprime **sólo agregados**: conteos, sumas y distintos. Ninguna
consulta devuelve user_id, email, nombre de broker ni fila individual — están
escritas así a propósito.

USO — dentro de Railway, sin que salga un solo dato de producción:

    railway ssh
    # pegar este archivo (o: cat > /tmp/medir.py <<'EOF' ... EOF)
    python3 /tmp/medir.py /ruta/a/trading.db

Si no sabés la ruta, el script la busca en DB_PATH y en los lugares habituales.
Pasame la salida entera: son ~40 números.
"""
import os
import sqlite3
import sys
import re

SQL = """-- ============================================================================
-- 1A — ALCANCE REAL EN PRODUCCIÓN de los puntos URGENTE
-- Commit auditado: b74f450f · esquema: backend/schema_pg.sql
-- ============================================================================
--
-- REGLAS DE ESTE ARCHIVO
--   · SOLO LECTURA. Únicamente SELECT/COUNT/SUM. Ningún INSERT, UPDATE, DELETE,
--     CREATE, ALTER, DROP, TRUNCATE ni transacción de escritura.
--   · Devuelve SÓLO AGREGADOS. Ninguna consulta devuelve user_id, email, nombre
--     de broker, ticker ni fila individual. Lo máximo que sale es un COUNT
--     DISTINCT y una suma.
--   · Correr con un rol de solo lectura. En Postgres, además:
--         SET default_transaction_read_only = on;
--     (eso NO es DDL: es un parámetro de sesión, y aborta cualquier escritura
--      accidental antes de tocar nada).
--
-- DIALECTO — VARIANTE SQLITE
--   Generada desde `1a-alcance-produccion.sql` (que está escrito para Postgres)
--   porque PRODUCCIÓN SIGUE EN SQLITE. Diferencias aplicadas:
--     · se quitaron los casts `::numeric` — en SQLite `ROUND()` ya opera sobre
--       el float. Eran 8 de 13 sentencias: la versión Postgres NO corre acá.
--     · los booleanos del CASE de Q1b se comparan contra 1/0.
--   `ROW_NUMBER() OVER (...)` de Q2 funciona desde SQLite 3.25 (2018).
--
--   ⚠️ Verificado que PARSEA, no que los números sean correctos: se probó contra
--   la base de DEV, que tiene 17 usuarios y le faltan columnas de versiones
--   nuevas. Los números sólo salen de producción.
--
-- POR QUÉ ESTOS FILTROS Y NO OTROS
--   Cada consulta busca la CONDICIÓN QUE DISPARA el bug (verificada leyendo el
--   código), no un síntoma que podría tener otras causas. Donde el disparador no
--   deja marca distinguible, lo digo en el comentario y explico qué mide de más.
--
-- ============================================================================


-- ────────────────────────────────────────────────────────────────────────────
-- Q1a · A-1 — Posiciones con costo EN PESOS dentro de un broker en dólares
-- ────────────────────────────────────────────────────────────────────────────
-- Es el dominio EXACTO de la rama que le falta a snapshots_job.compute_broker_
-- value_usd (la rama `costInPesos && !isAR` del canónico valuation.js).
-- Los brokers se linkean por NOMBRE, no por FK, así que el join va por
-- (user_id, name) — es como los linkea el resto del sistema.
--
-- PREOCUPANTE SI: > 0 usuarios. No hay umbral benigno: cada una de estas filas
-- se está escribiendo al snapshot inflada por el factor MEP (~1.400×). Si el
-- número de usuarios es > 20, el backfill deja de ser una corrida puntual.

SELECT
    COUNT(*)                                   AS posiciones_afectadas,
    COUNT(DISTINCT p.user_id)                  AS usuarios_afectados,
    COUNT(DISTINCT p.broker)                   AS brokers_distintos,
    ROUND(SUM(COALESCE(p.invested,0) + COALESCE(p.commissions,0)), 2)
                                               AS costo_nominal_en_pesos
FROM positions p
JOIN brokers b
  ON b.user_id = p.user_id
 AND b.name    = p.broker
WHERE COALESCE(p.is_cash, 0) = 0
  AND UPPER(COALESCE(p.currency, '')) = 'ARS'          -- el lote se pagó en pesos
  AND UPPER(COALESCE(b.currency, '')) IN ('USD','USDT') -- la cuenta es en dólares
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q1b · A-1 vs A-2 — Partir lo anterior en los dos casos, que se arreglan distinto
-- ────────────────────────────────────────────────────────────────────────────
-- A-1 = sub-broker "· USD" con PADRE argentino  → se cotiza por .BA (el precio
--       está bien, lo que rompe es el costo).
-- A-2 = broker USD GENUINO (sin padre ARS)      → además se cotiza el ticker US
--       en vez del .BA, o sea se valúa OTRO INSTRUMENTO. Es el caso peor y el
--       que el guard _trust_mkt_value no puede atrapar.
--
-- PREOCUPANTE SI: la columna A-2 es > 0. Ahí no hay factor conocido: el número
-- publicado es el precio de un instrumento distinto, y el error puede tener
-- cualquier signo y cualquier magnitud.

SELECT
    SUM(CASE WHEN parent_es_ars = 1 THEN 1 ELSE 0 END)          AS a1_subbroker_usd_de_padre_ars,
    SUM(CASE WHEN parent_es_ars = 0 THEN 1 ELSE 0 END)      AS a2_broker_usd_genuino,
    COUNT(DISTINCT CASE WHEN parent_es_ars = 0 THEN user_id END)
                                                            AS a2_usuarios
FROM (
    SELECT
        p.user_id,
        (pb.id IS NOT NULL AND UPPER(COALESCE(pb.currency,'')) = 'ARS') AS parent_es_ars
    FROM positions p
    JOIN brokers b  ON b.user_id = p.user_id AND b.name = p.broker
    LEFT JOIN brokers pb ON pb.id = b.parent_broker_id
    WHERE COALESCE(p.is_cash,0) = 0
      AND UPPER(COALESCE(p.currency,'')) = 'ARS'
      AND UPPER(COALESCE(b.currency,'')) IN ('USD','USDT')
) t
;
-- [SQLITE] los booleanos: reemplazar `parent_es_ars` por
--   (pb.id IS NOT NULL AND UPPER(COALESCE(pb.currency,'')) = 'ARS')
-- y `WHEN parent_es_ars THEN` por `WHEN parent_es_ars = 1 THEN`.


-- ────────────────────────────────────────────────────────────────────────────
-- Q1c · A-1/A-2 — Filas de snapshots que quedaron pegadas al costo
-- ────────────────────────────────────────────────────────────────────────────
-- Cuando el costo entra inflado, _trust_mkt_value rechaza el precio real y
-- escribe `value = invested`. Esa IGUALDAD EXACTA es la huella del bug: en una
-- cartera con precios buenos, value e invested coinciden al centavo sólo por
-- casualidad.
--
-- OJO — esto mide de más: una cuenta sin ningún precio disponible (yfinance
-- caído, activo sin cotización) también cae al costo legítimamente. Por eso se
-- separa por magnitud: los casos de A-1 son GRANDES, porque el costo está
-- multiplicado por el MEP.
--
-- PREOCUPANTE SI: `filas_pegadas_al_costo_grandes` > 0 con más de 3 usuarios, o
-- si `dias_distintos` es del orden de los días corridos desde que existe el bug
-- (querría decir que pasa todas las noches, no que fue un incidente puntual).

SELECT
    COUNT(*)                                        AS filas_pegadas_al_costo,
    COUNT(DISTINCT user_id)                         AS usuarios,
    COUNT(DISTINCT date)                            AS dias_distintos,
    MIN(date)                                       AS primer_dia,
    MAX(date)                                       AS ultimo_dia,
    SUM(CASE WHEN total_value > 1000000 THEN 1 ELSE 0 END)
                                                    AS filas_pegadas_al_costo_grandes,
    COUNT(DISTINCT CASE WHEN total_value > 1000000 THEN user_id END)
                                                    AS usuarios_con_filas_grandes
FROM snapshots
WHERE total_invested > 0
  AND ABS(total_value - total_invested) < 0.01      -- cayó a costo, al centavo
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q1d · A-1/A-2 — Relación valor/costo fuera de banda
-- ────────────────────────────────────────────────────────────────────────────
-- La banda de referencia es la del propio guard del sistema (_trust_mkt_value,
-- snapshots_job.py:42-55): 0,002 … 50 para no-renta-fija. Acá se aplica al TOTAL
-- del snapshot, que es más laxo todavía: una cartera entera fuera de 0,1 … 10 es
-- casi seguro un error de escala, no de mercado.
--
-- PREOCUPANTE SI: > 5 usuarios en `fuera_de_banda_amplia`. Un solo usuario puede
-- ser un caso raro legítimo (una posición castigada a cero); varios usuarios con
-- el mismo patrón es un bug sistémico.

SELECT
    COUNT(*)                                    AS filas_totales_con_costo,
    COUNT(DISTINCT user_id)                     AS usuarios_totales,
    SUM(CASE WHEN r < 0.1 OR r > 10  THEN 1 ELSE 0 END)  AS fuera_de_banda_amplia,
    COUNT(DISTINCT CASE WHEN r < 0.1 OR r > 10  THEN user_id END)
                                                AS usuarios_fuera_banda_amplia,
    SUM(CASE WHEN r < 0.002 OR r > 50 THEN 1 ELSE 0 END) AS fuera_de_banda_del_guard,
    COUNT(DISTINCT CASE WHEN r < 0.002 OR r > 50 THEN user_id END)
                                                AS usuarios_fuera_banda_guard
FROM (
    SELECT user_id, total_value / NULLIF(total_invested, 0) AS r
    FROM snapshots
    WHERE total_invested > 0
) s
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q2 · A-4 — Baselines `capital_inicio` que un recalc puede borrar
-- ────────────────────────────────────────────────────────────────────────────
-- `_recalc_pnl_realized_from_ops` (main.py:9639-9652) fuerza capital_inicio = 0
-- en el PRIMER mes de cada broker tocado, 'global' incluido. O sea: el riesgo
-- está en la fila más vieja de cada par (user, broker) que tenga capital_inicio
-- distinto de cero.
--
-- El "primer mes" se calcula por (year, month), que es como ordena el código.
--
-- PREOCUPANTE SI: > 0 usuarios. Es un dato que el usuario TIPEÓ y no se puede
-- reconstruir de ninguna otra fuente — no hay backfill posible, sólo backup.
-- Si `usuarios_en_riesgo` > 10, conviene un dump de esa columna ANTES de
-- cualquier import o borrado de broker.

SELECT
    COUNT(*)                        AS baselines_en_riesgo,
    COUNT(DISTINCT user_id)         AS usuarios_en_riesgo,
    SUM(CASE WHEN broker = 'global' THEN 1 ELSE 0 END) AS baselines_global,
    ROUND(SUM(ABS(capital_inicio)), 2)        AS monto_total_declarado
FROM (
    SELECT
        m.user_id, m.broker, m.capital_inicio,
        ROW_NUMBER() OVER (
            PARTITION BY m.user_id, m.broker
            ORDER BY m.year, m.month
        ) AS rn
    FROM monthly_entries m
) f
WHERE rn = 1
  AND COALESCE(capital_inicio, 0) <> 0
;
-- [SQLITE] ROW_NUMBER() OVER (...) funciona desde SQLite 3.25 (2018). Si la
-- versión fuera anterior, reemplazar el subquery por un join contra
--   (SELECT user_id, broker, MIN(year*12+month) AS ym FROM monthly_entries
--    GROUP BY user_id, broker)


-- ────────────────────────────────────────────────────────────────────────────
-- Q3 · A-5 — Amortizaciones manuales con el cash bruto guardado como P&L
-- ────────────────────────────────────────────────────────────────────────────
-- El insert de main.py:10478-10499 guarda `pnl_usd = net_amount` (el cash
-- ENTERO) y calcula la ganancia correcta después, sólo para la respuesta HTTP.
-- La marca de que la fila vino por ahí es `undo_meta_json` con "src":
-- "bond_cashflow". La inflación es exactamente `cost_basis_consumed`.
--
-- Se cuentan sólo las que tienen cost_basis_consumed > 0: si es NULL, el usuario
-- eligió no tocar las posiciones y no hay costo que descontar.
--
-- PREOCUPANTE SI: > 0 filas. Cada una infla `capital_final` de su mes y se
-- HEREDA hacia adelante por la cadena mensual. Si `usuarios` > 5, el backfill
-- tiene que recorrer la cadena de cada uno, no sólo la fila.

SELECT
    COUNT(*)                                        AS amortizaciones_manuales,
    COUNT(DISTINCT user_id)                         AS usuarios,
    ROUND(SUM(COALESCE(cost_basis_consumed,0)), 2)
                                                    AS sobreestimacion_total_pnl,
    ROUND(SUM(COALESCE(pnl_usd,0)), 2)     AS pnl_publicado_total,
    MIN(date) AS primera, MAX(date) AS ultima
FROM operations
WHERE op_type IN ('Amortización', 'Amortizacion')
  AND undo_meta_json LIKE '%bond_cashflow%'
  AND COALESCE(cost_basis_consumed, 0) > 0
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q4 · A-6 — Reconciliaciones de caja y con qué TC quedaron
-- ────────────────────────────────────────────────────────────────────────────
-- ⚠️ LIMITACIÓN REAL, leída en el código: `reconcile-cash` NO deja ninguna marca
-- propia. Escribe por _update_monthly_flow(is_manual=True), igual que el botón
-- de Cash. No hay forma de aislarlo con una consulta.
--
-- PERO deja una huella aritmética: llama con `native_amount` = monto en pesos y
-- `amount_usd` = monto / tc_blue, donde tc_blue es el DEFAULT 1415 porque el
-- único caller no manda el campo. Entonces, en la fila del broker:
--     manual_deposits_native / manual_deposits ≈ 1415,0 exacto
-- Un flujo cargado por el botón de Cash usaría el TC del día, que casi nunca
-- da 1415,000. La igualdad exacta con el default ES la firma del bug.
--
-- El margen de 0,5 absorbe el redondeo de acumular varios flujos en el mes.
--
-- PREOCUPANTE SI: `meses_con_firma_1415` > 0. Cada uno metió capital fantasma
-- en el denominador del rendimiento. Comparar `ratio_promedio` contra el MEP
-- real de esas fechas da el % de inflación (con MEP 1518 → +7,3 %).

SELECT
    COUNT(*)                                    AS meses_con_firma_1415,
    COUNT(DISTINCT user_id)                     AS usuarios,
    ROUND(AVG(ratio), 4)               AS ratio_promedio,
    ROUND(SUM(manual_deposits), 2)     AS usd_registrados_con_ese_tc
FROM (
    SELECT user_id, manual_deposits,
           manual_deposits_native / NULLIF(manual_deposits, 0) AS ratio
    FROM monthly_entries
    WHERE COALESCE(manual_deposits, 0) > 0
      AND COALESCE(manual_deposits_native, 0) > 0
) d
WHERE ABS(ratio - 1415.0) < 0.5
;

-- Y la contraparte, para tener el denominador (¿es raro o es lo normal?):
SELECT
    COUNT(*)                AS meses_con_flujo_manual_nativo,
    COUNT(DISTINCT user_id) AS usuarios
FROM monthly_entries
WHERE COALESCE(manual_deposits, 0) > 0
  AND COALESCE(manual_deposits_native, 0) > 0
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q5 · A-7 — Ventas en pesos estampadas con fx_to_usd = 1.0
-- ────────────────────────────────────────────────────────────────────────────
-- main.py:11310: `fx_stamp = (data.tc_venta or 1) if sell_ccy == "ARS" else None`.
-- Si el usuario borra el campo opcional "TC de venta", queda 1.0 aunque el P&L
-- se haya dividido por fx_for_date(). Una venta en pesos con fx_to_usd = 1 dice
-- que un peso vale un dólar: no existe caso legítimo.
--
-- PREOCUPANTE SI: > 0. Cada fila hace que todo lector que reconstruya el nominal
-- en pesos muestre ~1.400× mal. Si `usuarios` > 3, el campo de la UI necesita
-- dejar de ser opcional antes que el backfill.

SELECT
    COUNT(*)                                    AS ventas_ars_con_fx_1,
    COUNT(DISTINCT user_id)                     AS usuarios,
    ROUND(SUM(ABS(COALESCE(pnl_usd,0))), 2) AS pnl_nominal_afectado,
    MIN(date) AS primera, MAX(date) AS ultima
FROM operations
WHERE UPPER(COALESCE(currency, '')) = 'ARS'
  AND fx_to_usd = 1.0
  AND op_type IN ('Venta', 'Venta parcial')
;

-- Variante sin filtrar por op_type — por si el literal difiere en datos viejos.
-- Si este número es MUCHO mayor que el anterior, el filtro de arriba está corto.
SELECT
    COUNT(*)                AS filas_ars_con_fx_1_cualquier_tipo,
    COUNT(DISTINCT user_id) AS usuarios,
    COUNT(DISTINCT op_type) AS tipos_distintos
FROM operations
WHERE UPPER(COALESCE(currency, '')) = 'ARS'
  AND fx_to_usd = 1.0
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q6 · A-9 — Conversiones importadas cuyo neto no da cero
-- ────────────────────────────────────────────────────────────────────────────
-- _persist_fx (importing/persister.py:1108) saca la pata ARS valuada a
-- `ars_amount / tc_blue` (default 1415) y mete la pata USD a valor FACE
-- (`usd_amount`). Si el TC real de la conversión (unit_price) no es 1415, el
-- neto no es cero y la diferencia entra como capital nuevo.
--
--     fantasma = quantity − (gross_amount / 1415)
--
-- Sólo se cuentan las filas efectivamente persistidas y no excluidas.
--
-- PREOCUPANTE SI: `usuarios` > 0 y `fantasma_neto_usd` no es marginal frente al
-- capital del usuario. Nota del informe: estas filas se AUTODESTRUYEN — el
-- primer recalc las pisa con cero — así que el número salta solo. Si
-- `fantasma_neto_usd` es grande, explica saltos de rendimiento sin causa.

SELECT
    COUNT(*)                                        AS conversiones_persistidas,
    COUNT(DISTINCT batch_id)                        AS batches,
    SUM(CASE WHEN ABS(fantasma) > 1 THEN 1 ELSE 0 END) AS con_neto_no_cero,
    ROUND(SUM(fantasma), 2)                AS fantasma_neto_usd,
    ROUND(MAX(ABS(fantasma)), 2)           AS peor_caso_usd
FROM (
    SELECT
        t.batch_id,
        COALESCE(t.quantity,0) - (COALESCE(t.gross_amount,0) / 1415.0) AS fantasma
    FROM import_normalized_tx t
    WHERE t.operation_type IN ('FX_ARS_TO_USD', 'FX_USD_TO_ARS')
      AND t.excluded_at IS NULL
      AND (t.created_operation_id IS NOT NULL OR t.created_position_id IS NOT NULL)
) c
;
-- NOTA: import_normalized_tx no tiene user_id (se llega por batch_id →
-- import_batches). Se reporta `batches` en su lugar, que es un proxy y NO
-- identifica a nadie. Para contar usuarios haría falta el join con
-- import_batches; lo dejo afuera a propósito para no acercarme a datos de
-- usuario más de lo necesario.


-- ────────────────────────────────────────────────────────────────────────────
-- Q7 · B-4 — Operaciones "Interés PF" y cuánto suman
-- ────────────────────────────────────────────────────────────────────────────
-- main.py:9315-9320 inserta con `pnl_usd` en MONEDA NATIVA y
-- `fx = 1.0 if moneda in ('USD','USDT') else None` → en pesos nace con
-- fx_to_usd NULL. Y 'Interés PF' no está en _NATIVE_CCY_OPS (realized_pnl.py:78,
-- que sólo tiene 'Cupón' y 'Amortización'), así que ningún lector lo convierte.
--
-- El código lo documenta como "hoy no muerde (0 filas)". Esta consulta es
-- exactamente el chequeo de si esa afirmación sigue siendo cierta.
--
-- PREOCUPANTE SI: `filas_en_pesos_sin_fx` > 0. Con 0 filas, el hallazgo baja de
-- urgente a deuda estructural (el endpoint sigue vivo y las va a crear).
-- El monto en pesos leído como dólares es el error directo.

SELECT
    COUNT(*)                                            AS interes_pf_total,
    COUNT(DISTINCT user_id)                             AS usuarios,
    SUM(CASE WHEN UPPER(COALESCE(currency,'')) NOT IN ('USD','USDT')
              AND fx_to_usd IS NULL THEN 1 ELSE 0 END)  AS filas_en_pesos_sin_fx,
    ROUND(SUM(CASE WHEN UPPER(COALESCE(currency,'')) NOT IN ('USD','USDT')
                    AND fx_to_usd IS NULL
                   THEN COALESCE(pnl_usd,0) ELSE 0 END), 2)
                                                        AS monto_pesos_leido_como_usd
FROM operations
WHERE op_type = 'Interés PF'
;


-- ────────────────────────────────────────────────────────────────────────────
-- Q8 · C-1 — Usuarios con más de 12 meses de historia
-- ────────────────────────────────────────────────────────────────────────────
-- El error de /reportes (publicar el latente ACUMULADO como si fuera el del
-- mes) crece con la antigüedad de la cuenta: en un mes de vida el número está
-- casi bien, a dos años está 30× mal. Estos son los usuarios donde muerde.
--
-- Se cuenta sobre monthly_entries, que es la tabla que /reportes lee.
--
-- PREOCUPANTE SI: `mas_de_12_meses` es una fracción alta del total. Si además
-- `mas_de_24_meses` > 0, esos son los que ven el número más distorsionado y son
-- los mejores candidatos para verificar el 33× contra un caso real.

SELECT
    COUNT(*)                                                AS usuarios_con_historia,
    SUM(CASE WHEN meses > 12 THEN 1 ELSE 0 END)             AS mas_de_12_meses,
    SUM(CASE WHEN meses > 24 THEN 1 ELSE 0 END)             AS mas_de_24_meses,
    MAX(meses)                                              AS maximo_meses
FROM (
    SELECT user_id, COUNT(DISTINCT (year * 12 + month)) AS meses
    FROM monthly_entries
    GROUP BY user_id
) h
;


-- ============================================================================
-- CHEQUEO DE SEGURIDAD DEL ARCHIVO
-- ============================================================================
-- Antes de correrlo, verificá que no haya escrituras:
--
--   grep -icE '\b(insert|update|delete|drop|alter|create|truncate|replace|merge|grant|copy)\b' \
--        audit/01_calculos/1a-alcance-produccion.sql
--
-- Debe dar 0 fuera de los comentarios. (Las palabras aparecen en el texto
-- explicativo; el chequeo real es que ninguna sentencia ejecutable empiece con
-- algo que no sea SELECT.)
-- ============================================================================
"""


def secciones():
    """(id, titulo, sentencia) por cada SELECT, etiquetado con su encabezado."""
    titulo, out = ("?", "?"), []
    buf = []
    for linea in SQL.splitlines():
        m = re.match(r"--\s*(Q\w+)\s*·\s*(.+)", linea.strip())
        if m:
            titulo = (m.group(1), m.group(2).strip())
        if linea.strip().startswith("--"):
            continue
        buf.append((titulo, linea))
    actual, acc = None, []
    for t, l in buf:
        if l.strip():
            if actual is None:
                actual = t
            acc.append(l)
        if ";" in l:
            txt = " ".join(" ".join(acc).split()).rstrip(";").strip()
            if txt.upper().startswith("SELECT"):
                out.append((actual[0], actual[1], txt))
            actual, acc = None, []
    return out


def base():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in (os.environ.get("DB_PATH"), "backend/trading.db", "trading.db",
              "/app/backend/trading.db", "/app/trading.db", "/data/trading.db"):
        if c and os.path.exists(c):
            return c
    sys.exit("No encontré la base. Pasala como argumento: python3 medir.py /ruta/trading.db")


def main():
    ruta = base()
    print(f"base: {ruta}  ({os.path.getsize(ruta) / 1e6:.1f} MB)\n")
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ultimo = None
    for qid, titulo, s in secciones():
        if qid != ultimo:
            print(f"\n{'=' * 72}\n{qid} · {titulo}\n{'=' * 72}")
            ultimo = qid
        try:
            for fila in con.execute(s).fetchall():
                for k in fila.keys():
                    v = fila[k]
                    print(f"  {k:38s} {v if v is not None else '—'}")
        except Exception as ex:
            print(f"  ⚠️ falló: {ex}")
    con.close()
    print("\nListo. Nada de esto identifica a ningún usuario.")


if __name__ == "__main__":
    main()
