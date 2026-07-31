"""Migrador FX v1 → v2: pasa UNA cuenta al TC histórico, con las DOS patas juntas.

POR QUÉ EXISTE (el problema de la migración a mitad de camino)
──────────────────────────────────────────────────────────────
El motor gateado por `fx_version` garantiza que el deploy no le cambia el número a
nadie. Pero migrar una cuenta exige tocar DOS patas a la vez:

  · las VENTAS: se re-derivan replayando (rebuild) con `fx_for_date`
  · los FLUJOS: `import_normalized_tx.gross_amount_usd` está estampado con el
    dólar del día del import (medido en prod: 80.868 de 84.123 al mismo 1415,
    desde 2013) y NADA lo re-deriva — hay que re-estamparlo acá

Si se migra una sola pata, los dos errores dejan de cancelarse en el cociente del
Total Return: medido, el error pasa de 1,23× a 9,1×. Por eso este módulo hace
re-estampado + rebuild + recalc + snapshots + `fx_version=v2` en UNA transacción:
o sale todo, o no sale nada.

QUÉ NO HACE (a propósito)
─────────────────────────
  · NO llama a `_remove_trajectory_outlier_snapshots` ni a repair-snapshots-all:
    esa rutina se ancla al capital_final y puede borrar la curva diaria real.
  · NO toca cash (`positions is_cash=1`): el rebuild no lo recompone y este
    migrador tampoco — el cash per-100 es un problema aparte con dos poblaciones
    de signo opuesto (ver project_sell_scale_per100).
  · NO toca operaciones manuales: los pares (broker, activo) con data manual los
    saltea el rebuild (`_is_safe_to_rebuild`) y quedan reportados en
    `pares_salteados` — esas ventas conservan su TC viejo y se miran a mano.

DAÑO COLATERAL DEL REBUILD, MITIGADO ACÁ
────────────────────────────────────────
El rebuild reinserta las positions con `tc_compra`, `price_override` y `notes` en
NULL (rebuild.py `_write_rebuilt`). Este migrador los captura ANTES por
(broker, activo, currency) y los restaura DESPUÉS cuando el valor viejo era único
para ese grupo; los ambiguos (dos lotes del mismo activo con overrides distintos)
se reportan en `overrides_ambiguos` en vez de adivinarse.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

try:
    from fx import fx_for_date, fx_version, set_fx_version, FX_V1, FX_V2
except ImportError:  # pragma: no cover
    from ..fx import fx_for_date, fx_version, set_fx_version, FX_V1, FX_V2

from . import rebuild as _rebuild
from . import persister as _persister

log = logging.getLogger(__name__)


def _metricas(conn, uid: int) -> Dict[str, Any]:
    """La foto contra la que se mide el antes/después. Todo agregados, sin PII."""
    ops = conn.execute(
        "SELECT COUNT(*) n, ROUND(COALESCE(SUM(pnl_usd),0),2) s "
        "FROM operations WHERE user_id=? AND op_type='Venta'", (uid,)).fetchone()
    mon = conn.execute(
        "SELECT ROUND(COALESCE(SUM(deposits),0),2) dep, "
        "       ROUND(COALESCE(SUM(withdrawals),0),2) ret, "
        "       ROUND(COALESCE(SUM(pnl_realized),0),2) pnl "
        "FROM monthly_entries WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    cap = conn.execute(
        "SELECT capital_final FROM monthly_entries "
        "WHERE user_id=? AND broker='global' ORDER BY year DESC, month DESC LIMIT 1",
        (uid,)).fetchone()
    tcs = conn.execute(
        "SELECT COUNT(DISTINCT ROUND(gross_amount/gross_amount_usd, 0)) n "
        "FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id "
        "WHERE b.user_id=? AND b.status='confirmed' "
        "  AND UPPER(COALESCE(n.currency,''))='ARS' "
        "  AND n.gross_amount_usd IS NOT NULL AND n.gross_amount_usd<>0", (uid,)).fetchone()
    # ── EL NÚMERO QUE VE EL USUARIO ───────────────────────────────────────────
    # El "rendimiento" del Dashboard es UN solo número, calculado client-side:
    #   (totalValue − netDeposited) / netDeposited        (Dashboard.jsx:234-235)
    # y su denominador es `capital_inicio` del PRIMER mes de 'global' (baseline)
    # + Σ(deposits − withdrawals) de todos los meses (Dashboard.jsx:191-201) —
    # la misma fórmula que `snapshots_job.compute_net_deposited_db(broker_filter=
    # 'global', include_baseline=True)`. Se replica acá para poder mostrar en el
    # panel EXACTAMENTE lo que el usuario va a ver, sin entrar a su cuenta.
    #
    # El NUMERADOR no lo toca la migración: `positions.invested` se guarda en
    # moneda nativa y la valuación lo dolariza al MEP de HOY, así que el rebuild
    # lo reescribe con el mismo número (verificado: positions byte-idénticas,
    # valor 703,45 → 703,45). Migrar mueve el DENOMINADOR, y sólo el denominador.
    # Por eso alcanza con el último snapshot como valor de cartera: es la misma
    # medición antes y después, y es la que ya alimentan el gráfico y el CAGR.
    base = conn.execute(
        "SELECT capital_inicio FROM monthly_entries WHERE user_id=? AND broker='global' "
        "ORDER BY year, month LIMIT 1", (uid,)).fetchone()
    baseline = float(base["capital_inicio"] or 0) if base and base["capital_inicio"] is not None else 0.0
    aportado = baseline + float(mon["dep"] or 0) - float(mon["ret"] or 0)
    snap = conn.execute(
        "SELECT total_value FROM snapshots WHERE user_id=? ORDER BY date DESC LIMIT 1",
        (uid,)).fetchone()
    valor = float(snap["total_value"]) if snap and snap["total_value"] is not None else None
    return {
        "ventas": ops["n"], "pnl_ventas_usd": ops["s"],
        "deposits_usd": mon["dep"], "withdrawals_usd": mon["ret"],
        "pnl_realized_usd": mon["pnl"],
        "capital_final": round(cap["capital_final"], 2) if cap and cap["capital_final"] is not None else None,
        "tcs_distintos_en_flujos": tcs["n"],
        "baseline_usd": round(baseline, 2),
        "aportado_dashboard_usd": round(aportado, 2),
        "valor_cartera_usd": round(valor, 2) if valor is not None else None,
        "rendimiento_pct": (round(((valor - aportado) / aportado) * 100, 1)
                            if valor is not None and aportado > 0 else None),
    }


def denominador_roto(valor, ap_antes, ap_despues, rend_despues, rend_antes=None):
    """El único freno del aportado que NO es cuestión de criterio, sino aritmética.

    La MAGNITUD del salto del aportado no distingue reparación de daño (un flujo
    de 2013 dolarizado a 1415 y re-derivado a ~5 se multiplica ×280, y está bien).
    Pero hay dos estados en los que el rendimiento del Dashboard deja de ser un
    número, y esos no dependen de la época de los flujos de nadie:

      · aportado ≤ 0 con cartera > 0 → el % no existe. El strip "Rendimiento"
        esconde la card (Dashboard.jsx:566-568 exige netDeposited > 0) pero el
        pill del hero NO está gateado (Dashboard.jsx:703-708): sigue mostrando
        "Ganancia total" en dólares —inflada, porque restar un negativo suma—
        con "+0,0%" al lado.
      · aportado positivo pero minúsculo frente a la cartera → el % explota. No
        hay clamp: `pctSigned` sólo filtra null/NaN (format.js:113-118), así que
        US$ 1 de aportado con US$ 50.000 de cartera imprime "+5.000.000,0%".

    Devuelve el motivo (str) o None. Nadie puede mirar 503 cuentas para cazar
    esto a ojo — por eso frena solo.
    """
    if valor is None or valor <= 1:
        return None
    if ap_despues <= 0 < ap_antes:
        return (f"el aportado queda en US$ {round(ap_despues, 2)} (venía de "
                f"US$ {round(ap_antes, 2)}) con una cartera de US$ {round(valor, 2)}: "
                "el % del Dashboard deja de tener sentido")
    if rend_despues is not None and abs(rend_despues) > 100_000:
        return (f"el rendimiento queda en {rend_despues}% (aportado "
                f"US$ {round(ap_despues, 2)} contra una cartera de US$ {round(valor, 2)}): "
                "el denominador quedó casi en cero")
    return None


def cae_de_ganar_a_perder_todo(rend_antes, rend_despues):
    """ADVERTENCIA, no freno: la cuenta pasaría de ganar a perder >80%.

    Es un heurístico de COMPORTAMIENTO, no una prueba de que el dato esté mal:
    perder el 80% de lo aportado es perfectamente posible. La fixture de
    `test_migracion_mueve_las_dos_patas` da exactamente este salto (+2,0% →
    −89,1%) con datos sanos, y frenarla estaría mal. Por eso se muestra en el
    panel para que se mire, y quien frena de verdad es `fechas_sospechosas`,
    que sí tiene una firma específica de dato roto.
    """
    return (rend_antes is not None and rend_despues is not None
            and rend_antes > 0 > -80 > rend_despues)


def fechas_sospechosas(conn, uid, ratio=50.0, ratio_aviso=10.0, min_filas=3):
    """Depósitos en pesos que NO pueden ser del año que dicen. Esto sí frena.

    En Argentina los montos nominales en pesos sólo crecen: un depósito típico
    de 2019 tiene que ser MUCHO más chico que uno de 2024. Cuando pasa al revés,
    esas filas no son de ese año — es una fecha mal parseada.

    Medido en prod (2026-07-30), #324: 9 "depósitos" de 14,6 M de pesos fechados
    en 2019, contra 73 mil por depósito en 2020 y 5 M en 2026. La serie
    2020→2026 crece prolija con la inflación y 2019 se sale 200×. Al dólar de
    2019 (42,3) esos 131 M dan US$ 3,1 M = el 92% del aportado de la cuenta.
    Con el dólar de hoy el error era invisible (131 M / 1415 = 92 mil, un número
    plausible); el TC histórico lo amplifica ×33. Misma firma en #595, donde los
    RETIROS del mismo 2019 son de 11.700 pesos: nadie deposita siete millones y
    retira once mil.

    Se usa la MEDIANA y se exige `min_filas` en el año viejo para no marcar al
    que hizo UN depósito grande (una herencia, la venta de un auto) y después
    siguió con montos chicos. Devuelve el motivo (str) o None.
    """
    try:
        filas = conn.execute(
            """SELECT substr(n.date,1,4) anio, n.gross_amount monto
                 FROM import_normalized_tx n
                 JOIN import_batches b ON b.id = n.batch_id
                WHERE b.user_id=? AND b.status='confirmed'
                  AND UPPER(COALESCE(n.currency,''))='ARS'
                  AND n.operation_type='DEPOSIT'
                  AND n.gross_amount IS NOT NULL AND n.gross_amount > 0
                  AND n.fingerprint IS NOT NULL
                  AND COALESCE(n.notes,'') NOT LIKE 'Estado inicial%'""",
            (uid,)).fetchall()
    except Exception:
        return None

    por_anio: Dict[str, list] = {}
    for r in filas:
        if r["anio"]:
            por_anio.setdefault(r["anio"], []).append(float(r["monto"]))
    if len(por_anio) < 2:
        return None

    def _mediana(xs):
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    med = {a: _mediana(v) for a, v in por_anio.items()}
    anios = sorted(med)
    peor = None
    for i, viejo in enumerate(anios):
        if len(por_anio[viejo]) < min_filas or med[viejo] <= 0:
            continue
        for nuevo in anios[i + 1:]:
            if med[nuevo] <= 0:
                continue
            r = med[viejo] / med[nuevo]
            # Se captura desde el umbral de AVISO; `ratio` (más alto) decide
            # después si además frena.
            if r > ratio_aviso and (peor is None or r > peor[2]):
                peor = (viejo, nuevo, r)
    if not peor:
        return None
    viejo, nuevo, r = peor
    txt = (f"{len(por_anio[viejo])} depósito(s) fechados en {viejo} son {round(r)}× más "
           f"grandes EN PESOS que los de {nuevo} — con la inflación tendría que ser al revés")
    if r > ratio:
        return {"frena": True, "viejo": viejo, "nuevo": nuevo, "ratio": round(r, 1),
                "motivo": txt + (f". Un múltiplo así no lo explica ningún cambio de hábito: "
                                 f"esas filas no son de {viejo}, y el TC histórico las "
                                 "amplifica en vez de corregirlas. Mirá el desglose del "
                                 "aportado por año antes de migrar esta cuenta")}
    return {"frena": False, "viejo": viejo, "nuevo": nuevo, "ratio": round(r, 1),
            "motivo": txt + (". Puede ser fecha mal parseada o simplemente que aportaba más "
                             "antes — con este múltiplo no se distingue, así que no frena")}


def migrate_user_fx(conn, uid: int, helpers, *, recalc, backfill_snapshots,
                    recompute_netdep, force: bool = False) -> Dict[str, Any]:
    """Migra la cuenta `uid` a FX v2. NO commitea ni rollbackea: el caller decide
    (así el dry-run corre esta MISMA función sobre una copia de la base y el apply
    la corre sobre la real — un solo código, cero divergencia dry-run/apply).

    `force=True` deja pasar una cuenta que la verificación frenó (delta de P&L o
    de aportado implausible, cash tocado, ventas con el TC mal). Es para el caso
    entendido y revisado a mano; el default es NO migrarla.
    """
    version = fx_version(conn, uid)
    if version == FX_V2:
        return {"ok": False, "motivo": "la cuenta ya está en v2", "user_id": uid}

    # ── GUARD: cuentas con el bug de ESCALA (per-100) no se migran por acá ────
    # El rebuild de la migración les "arreglaría" el P&L de escala de paso (el
    # guard de reconciled_unit_price corre en el replay), pero el CASH quedaría
    # inflado ×100 sin la firma pnl_pct que hoy lo delata — el "crimen perfecto"
    # documentado en project_sell_scale_per100. Esas ~25 cuentas necesitan su
    # procedimiento propio (cash + foto de tenencia) ANTES de migrar FX.
    # El chequeo va sobre las columnas FUENTE (import_normalized_tx), no sobre
    # operations: cualquier rebuild posterior al deploy del guard de escala
    # "limpia" el exit_price de operations y borra la firma, pero el CASH sigue
    # inflado. La fuente es inmutable — la firma no se puede borrar de ahí.
    escala_rota = conn.execute(
        """SELECT COUNT(*) n FROM import_normalized_tx n2
             JOIN import_batches b ON b.id = n2.batch_id
            WHERE b.user_id=? AND b.status='confirmed'
              AND n2.operation_type IN ('BUY','SELL')
              AND n2.unit_price IS NOT NULL AND n2.unit_price <> 0
              AND n2.quantity IS NOT NULL AND n2.quantity <> 0
              AND n2.gross_amount IS NOT NULL AND n2.gross_amount <> 0
              AND ((n2.unit_price * n2.quantity) / n2.gross_amount > 5
                   OR (n2.unit_price * n2.quantity) / n2.gross_amount < 0.2)""",
        (uid,)).fetchone()["n"]
    if escala_rota:
        return {"ok": False, "user_id": uid,
                "motivo": (f"la cuenta tiene {escala_rota} fila(s) importada(s) con el bug de "
                           "ESCALA (per-100). Migrarla ahora dejaría el cash inflado "
                           "sin la firma que lo detecta. Primero el procedimiento de "
                           "escala (ver /api/admin/diagnose-scale), después el FX."),
                "ventas_con_escala_rota": escala_rota}

    antes = _metricas(conn, uid)
    resultado: Dict[str, Any] = {"ok": True, "user_id": uid, "antes": antes}
    cash_antes = {r["broker"]: round(r["c"] or 0, 4) for r in conn.execute(
        "SELECT broker, SUM(invested) c FROM positions "
        "WHERE user_id=? AND is_cash=1 GROUP BY broker", (uid,))}

    # ── PATA 1: re-estampar los flujos con el TC de la fecha de cada uno ──────
    # Se re-estampa TODA fila ARS con gross_amount (no solo DEPOSIT/WITHDRAW):
    # gross_amount_usd lo leen también el recalc de monthly y /api/movements.
    #
    # ⛔ MENOS LAS SINTÉTICAS DEL "ESTADO INICIAL". El wizard, cuando el archivo
    # deja el cash en negativo (un export de ÓRDENES no trae ningún depósito, así
    # que TODAS las compras sobregiran), le pregunta al usuario "¿cuánto efectivo
    # tenés HOY?" y emite un depósito sintético por la diferencia — pero lo fecha
    # UN DÍA ANTES del primer movimiento del archivo (seed.py `_minus_one_day`).
    # O sea: monto en pesos de HOY, fecha la más VIEJA de la cuenta. Con el dólar
    # de hoy eso era consistente y daba un número correcto; con el TC histórico se
    # divide por el dólar de 2019 y se multiplica ×33.
    #
    # Medido en prod, cuenta #324: una sola fila de 130.667.268 pesos fechada
    # 2019-07-21 —un DOMINGO, la firma de "earliest − 1 día"— daba US$ 3.090.522
    # migrados, el 92% del aportado de la cuenta. Los otros 217 depósitos del
    # mismo archivo van de 800 mil a 15 millones de pesos.
    #
    # Estas filas se reconocen porque el INSERT del seed (persister.py) OMITE la
    # columna `fingerprint`, mientras que toda fila parseada la lleva
    # (pipeline.py). Se agrega el match por `notes` como red: excluir de más es
    # el lado seguro — la fila se queda con el dólar de hoy, que es exactamente
    # la moneda en la que el usuario tipeó el monto.
    filas = conn.execute(
        """SELECT n.id, n.date, n.gross_amount
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id=? AND b.status='confirmed'
              AND UPPER(COALESCE(n.currency,''))='ARS'
              AND n.gross_amount IS NOT NULL
              AND n.fingerprint IS NOT NULL
              AND COALESCE(n.notes,'') NOT LIKE 'Estado inicial%'""", (uid,)).fetchall()
    sinteticas = conn.execute(
        """SELECT COUNT(*) n, ROUND(COALESCE(SUM(n2.gross_amount_usd),0),2) usd
             FROM import_normalized_tx n2
             JOIN import_batches b ON b.id = n2.batch_id
            WHERE b.user_id=? AND b.status='confirmed'
              AND UPPER(COALESCE(n2.currency,''))='ARS'
              AND n2.gross_amount IS NOT NULL
              AND (n2.fingerprint IS NULL
                   OR COALESCE(n2.notes,'') LIKE 'Estado inicial%')""", (uid,)).fetchone()
    cache: Dict[str, Optional[float]] = {}
    sin_tc = 0
    restamped = 0
    for f in filas:
        d = (f["date"] or "")[:10]
        if d not in cache:
            cache[d] = fx_for_date(conn, d)
        tc = cache[d]
        if not tc or tc <= 0:
            sin_tc += 1        # fecha fuera de la serie: se deja el stamp viejo
            continue
        conn.execute(
            "UPDATE import_normalized_tx SET gross_amount_usd = ? WHERE id = ?",
            (float(f["gross_amount"]) / tc, f["id"]))
        restamped += 1
    resultado["flujos"] = {"ars_totales": len(filas), "re_estampados": restamped,
                           "sin_tc_en_serie": sin_tc,
                           # Las del "Estado inicial" quedan al dólar de hoy A
                           # PROPÓSITO: su monto lo tipeó el usuario en pesos de hoy.
                           "sinteticas_no_re_estampadas": sinteticas["n"] if sinteticas else 0,
                           "sinteticas_usd": sinteticas["usd"] if sinteticas else 0}

    # ── Capturar overrides que el rebuild pisa ────────────────────────────────
    # Se capturan TODAS las filas de los grupos que tienen ALGÚN override —
    # incluidas las que no lo tienen. Si un grupo mezcla un lote con tc_compra y
    # otro sin, restaurar "el único valor" contagiaría el override al lote que
    # nunca lo tuvo (reproducido en el audit): grupo mixto ⇒ ambiguo ⇒ se reporta.
    overrides = conn.execute(
        """SELECT broker, asset, COALESCE(currency,'') ccy,
                  price_override, tc_compra, notes
             FROM positions
            WHERE user_id=? AND is_cash=0
              AND (broker, asset, COALESCE(currency,'')) IN (
                  SELECT broker, asset, COALESCE(currency,'')
                    FROM positions
                   WHERE user_id=? AND is_cash=0
                     AND (price_override IS NOT NULL OR tc_compra IS NOT NULL
                          OR notes IS NOT NULL))""", (uid, uid)).fetchall()
    por_grupo: Dict[tuple, list] = {}
    for o in overrides:
        por_grupo.setdefault((o["broker"], o["asset"], o["ccy"]), []).append(o)

    # ── Marcar v2 ANTES del rebuild: el rebuild lee fx_version de la cuenta ──
    set_fx_version(conn, uid, FX_V2)

    # ── PATA 2: replayar todas las ventas importadas con el TC histórico ─────
    batches = [r["id"] for r in conn.execute(
        "SELECT id FROM import_batches WHERE user_id=? AND status='confirmed' "
        "ORDER BY confirmed_at", (uid,))]
    tc_fallback = _persister._read_tc_blue(conn, uid=uid)
    salteados: list = []
    errores: list = []
    reconstruidos = 0
    for bid in batches:
        r = _rebuild.rebuild_fifo_after_import(conn, uid, bid, tc_blue=tc_fallback)
        reconstruidos += len(r.get("rebuilt") or [])
        for s in (r.get("skipped_manual") or []):
            if s not in salteados:
                salteados.append(s)
        errores.extend(r.get("errors") or [])
    resultado["rebuild"] = {"batches": len(batches), "grupos_reconstruidos": reconstruidos,
                            "pares_salteados": salteados, "errores": errores}
    if errores:
        # "O sale todo, o no sale nada" — un activo que el rebuild no pudo replayar
        # dejaría sus ventas al TC viejo con la cuenta marcada v2 y SIN camino de
        # reintento (la segunda corrida diría "ya está en v2"). ok=False hace que
        # el endpoint haga rollback y el operador vea el motivo.
        resultado["ok"] = False
        resultado["motivo"] = (f"el rebuild falló en {len(errores)} activo(s) — "
                               "la migración se revierte entera para no dejar la "
                               "cuenta a medias. Detalle en rebuild.errores.")
        return resultado

    # ── Restaurar overrides no ambiguos ───────────────────────────────────────
    restaurados, ambiguos = 0, []
    for (broker, asset, ccy), lst in por_grupo.items():
        vals = {(o["price_override"], o["tc_compra"], o["notes"]) for o in lst}
        if len(vals) != 1:
            ambiguos.append({"broker": broker, "asset": asset,
                             "valores_distintos": len(vals)})
            continue
        po, tcc, nt = next(iter(vals))
        cur = conn.execute(
            """UPDATE positions
                  SET price_override = COALESCE(price_override, ?),
                      tc_compra      = COALESCE(tc_compra, ?),
                      notes          = COALESCE(notes, ?)
                WHERE user_id=? AND broker=? AND asset=? AND is_cash=0
                  AND COALESCE(currency,'')=?""",
            (po, tcc, nt, uid, broker, asset, ccy))
        restaurados += cur.rowcount
    resultado["overrides"] = {"restaurados": restaurados, "overrides_ambiguos": ambiguos}

    # ── tc_compra de lotes ARS que quedaron sin TC ────────────────────────────
    # Solo 6 de 15 parsers emiten el TC de compra: la mayoría de los lotes
    # importados tienen tc_compra NULL y la vista "Costo en dólares de la compra"
    # no tiene con qué calcular. Acá se completa con el dólar de la FECHA DE
    # COMPRA real — solo lotes linkeados a un BUY importado de un batch que NO es
    # foto de tenencia: los lotes de foto tienen entry_date FALSA (la fecha de la
    # foto), y un TC falso-preciso es peor que un NULL honesto. Solo rellena el
    # hueco: un tc_compra existente (del parser o restaurado arriba) manda.
    lotes_sin_tc = conn.execute(
        """SELECT DISTINCT p.id, p.entry_date
             FROM positions p
             JOIN import_op_links l ON l.position_id = p.id
             JOIN import_batches b ON b.id = l.batch_id
            WHERE p.user_id=? AND p.is_cash=0 AND p.tc_compra IS NULL
              AND UPPER(COALESCE(p.currency,''))='ARS'
              AND p.entry_date IS NOT NULL
              AND b.parser_format NOT LIKE '%tenencia%'""", (uid,)).fetchall()
    tc_completados = 0
    for lote in lotes_sin_tc:
        d = (lote["entry_date"] or "")[:10]
        if d not in cache:
            cache[d] = fx_for_date(conn, d)
        tc = cache[d]
        if tc and tc > 0:
            conn.execute("UPDATE positions SET tc_compra=? WHERE id=?",
                         (round(tc, 4), lote["id"]))
            tc_completados += 1
    resultado["tc_compra_completados"] = tc_completados

    # ── Sincronizar la cadena y los snapshots (sin el borrador de outliers) ───
    recalc(conn, uid)
    backfill_snapshots(conn, uid)
    recompute_netdep(conn, uid)

    # ── VERIFICACIÓN: la prueba de que quedó bien, no solo de que corrió ──────
    # Tres invariantes chequeables desde la base, sin fe:
    #  1. cada venta ARS importada quedó estampada con el TC de SU fecha
    #  2. los flujos dejaron de estar todos al mismo TC (la firma del bug era UN
    #     solo TC para años de depósitos; ahora tiene que haber muchos)
    #  3. el cash NO se movió (el migrador no lo toca; si cambió, algo anda mal)
    # Las ventas de los pares SALTEADOS (data manual) conservan su TC viejo a
    # propósito: excluirlas del conteo o el x/y mezcla "quedó mal" con "quedó
    # como debía" y el operador aprende a ignorar el semáforo. Ídem las fechas
    # fuera de la serie FX: van a su propio contador, no a mal_tc.
    _skip_pairs = {(sp.get("broker"), sp.get("asset")) for sp in salteados}
    ventas_chk = conn.execute(
        """SELECT o.date, o.broker, o.asset, o.fx_to_usd FROM operations o
             JOIN import_op_links l ON l.operation_id = o.id
            WHERE o.user_id=? AND o.op_type='Venta'
              AND o.fx_to_usd IS NOT NULL AND o.fx_to_usd > 1""", (uid,)).fetchall()
    ok_tc, mal_tc = 0, []
    en_pares_salteados, sin_serie_fx = 0, 0
    total_chk = 0
    _vcache: Dict[str, Optional[float]] = {}
    for v in ventas_chk:
        if (v["broker"], v["asset"]) in _skip_pairs:
            en_pares_salteados += 1
            continue
        d = (v["date"] or "")[:10]
        if d not in _vcache:
            _vcache[d] = fx_for_date(conn, d)
        esperado = _vcache[d]
        if not esperado:
            sin_serie_fx += 1
            continue
        total_chk += 1
        if abs(float(v["fx_to_usd"]) / esperado - 1) <= 0.01:
            ok_tc += 1
        else:
            mal_tc.append({"fecha": d, "fx_estampado": round(float(v["fx_to_usd"]), 2),
                           "fx_de_la_fecha": round(esperado, 2)})
    # Flujos MANUALES (botón Depositar/Retirar): viven agregados por mes en
    # monthly_entries.manual_deposits/withdrawals, YA en USD y sin el monto ARS
    # original — NO SE PUEDEN re-derivar. Se declaran para que el operador sepa
    # que esa parte del aportado conserva el TC del momento de la carga.
    despues = _metricas(conn, uid)
    _man = conn.execute(
        "SELECT ROUND(COALESCE(SUM(manual_deposits),0)+COALESCE(SUM(manual_withdrawals),0),2) t "
        "FROM monthly_entries WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    flujos_manuales_usd = float(_man["t"] or 0) if _man else 0.0
    # ── PLAUSIBILIDAD: la migración MULTIPLICA el P&L por el TC histórico ─────
    # En una cuenta sana eso mueve centavos por venta. En una con el P&L ya
    # corrupto (pesos guardados como dólares) lo multiplica por ~8: no la
    # arregla, la empeora. Medido sobre 400 cuentas reales, la separación es
    # tajante — sanas: US$ 0-378 por venta (incluso con 4.350 ventas); corruptas:
    # US$ 2.888-347.527. Se pide magnitud absoluta Y por venta para no marcar a
    # una cuenta chica con un delta grande legítimo.
    _n_ventas = max(int(antes.get("ventas") or 0), 1)
    _d_pnl = abs(float(despues["pnl_ventas_usd"] or 0) - float(antes["pnl_ventas_usd"] or 0))
    # El umbral era `>100k Y >1000/venta`, y el "Y" dejaba pasar lo peor: medido
    # en el dry-run masivo, una cuenta con 1.203 ventas y Δ P&L de US$ 339.593
    # (282/venta) salía en VERDE. Ahora alcanza con CUALQUIERA de los dos: una
    # magnitud absoluta grande, o un delta por venta fuera del rango sano
    # (medido: cuentas sanas 0-378/venta incluso con miles de ventas).
    _implausible = _d_pnl > 100_000 or ((_d_pnl / _n_ventas) > 1_000 and _d_pnl > 10_000)

    # ── El APORTADO se MIDE y se muestra, pero NO frena ───────────────────────
    # El aportado es el denominador del rendimiento, así que moverlo le cambia el
    # retorno al usuario. La tentación es frenar cuando salta mucho — pero un
    # salto grande es justamente LA FIRMA DE LA REPARACIÓN, no del daño: un flujo
    # en pesos de 2013 estampado al dólar de hoy (1415) y re-derivado al de su
    # fecha (~5) multiplica el aportado por ~280, y está bien. La fixture de
    # `test_tc_compra_de_lotes_importados_se_completa` es exactamente ese caso
    # (+835%) y es el comportamiento correcto.
    # No hay umbral —ni absoluto ni relativo ni de dirección— que separe
    # reparación de daño sin conocer la ÉPOCA de los flujos de esa cuenta. Así
    # que esto se reporta con el "antes" al lado, para que el operador lo juzgue,
    # y el freno queda para las señales que sí tienen separación medida.
    _ap_antes = float(antes.get("deposits_usd") or 0) - float(antes.get("withdrawals_usd") or 0)
    _ap_despues = float(despues.get("deposits_usd") or 0) - float(despues.get("withdrawals_usd") or 0)
    _d_ap = abs(_ap_despues - _ap_antes)
    _d_ap_pct = (_d_ap / abs(_ap_antes)) if abs(_ap_antes) > 1 else None

    # ── EL DENOMINADOR SÍ FRENA (esto no es juicio, es aritmética) ─────────────
    # Lo de arriba dice que la MAGNITUD del salto no distingue reparación de daño.
    # Pero hay un caso que no depende de la época de los flujos ni del criterio de
    # nadie: si el aportado queda en CERO o NEGATIVO con cartera positiva, el
    # rendimiento del Dashboard deja de existir como número. Y si queda positivo
    # pero minúsculo frente a la cartera, explota: no hay clamp en el frontend
    # (`pctSigned` sólo filtra null/NaN, format.js:113-118), así que un aportado de
    # US$ 1 con US$ 50.000 de cartera imprime "+5.000.000,0%" en el hero.
    # Peor todavía con aportado ≤ 0: el strip "Rendimiento" esconde la card
    # (Dashboard.jsx:566-568 exige netDeposited > 0) pero el pill del hero NO está
    # gateado (Dashboard.jsx:703-708) y sigue mostrando "Ganancia total" en dólares
    # —inflada, porque restar un aportado negativo suma— con "+0,0%" al lado.
    # Nadie puede mirar 503 cuentas para cazar esto: se frena solo.
    _val = despues.get("valor_cartera_usd")
    _ap_dash_antes = float(antes.get("aportado_dashboard_usd") or 0)
    _ap_dash_despues = float(despues.get("aportado_dashboard_usd") or 0)
    _rend_antes = antes.get("rendimiento_pct")
    _rend_despues = despues.get("rendimiento_pct")
    _denominador_roto = denominador_roto(_val, _ap_dash_antes, _ap_dash_despues, _rend_despues)
    _fechas = fechas_sospechosas(conn, uid)
    _fechas_mal = _fechas["motivo"] if (_fechas and _fechas["frena"]) else None
    _fechas_aviso = _fechas["motivo"] if (_fechas and not _fechas["frena"]) else None
    _cae_fuerte = cae_de_ganar_a_perder_todo(_rend_antes, _rend_despues)

    resultado["verificacion"] = {
        "ventas_al_tc_de_su_fecha": f"{ok_tc}/{total_chk}",
        "delta_pnl_implausible": _implausible,
        "delta_pnl_por_venta": round(_d_pnl / _n_ventas, 2),
        # El panel necesita el aportado ANTES para poder juzgar: "+3.320.849" no
        # dice nada sin saber si la cuenta tenía 3 millones o 20 mil.
        "aportado_antes_usd": round(_ap_antes, 2),
        "aportado_despues_usd": round(_ap_despues, 2),
        "aportado_delta_pct": round(_d_ap_pct * 100, 1) if _d_ap_pct is not None else None,
        # Lo que el usuario va a ver en el hero del Dashboard, antes y después.
        # Es LA razón de ser del panel: verificar sin entrar a la cuenta ajena.
        "valor_cartera_usd": _val,
        "aportado_dashboard_antes_usd": round(_ap_dash_antes, 2),
        "aportado_dashboard_despues_usd": round(_ap_dash_despues, 2),
        "rendimiento_antes_pct": _rend_antes,
        "rendimiento_despues_pct": _rend_despues,
        "denominador_roto": _denominador_roto,
        "fechas_sospechosas": _fechas_mal,
        "fechas_aviso": _fechas_aviso,
        "cae_de_ganar_a_perder_todo": _cae_fuerte,
        # El recalc pone en CERO el capital_inicio del primer mes de todo broker
        # con actividad (main.py, _repair_monthly_chain). Si el usuario había
        # cargado a mano "empecé con US$ X" en /mensual, migrar se lo borra y el
        # aportado baja por esa vía ADEMÁS de moverse por el FX. No lo restauro
        # —restaurarlo podría duplicar capital que los flujos ya explican— pero
        # se reporta para que se vea cuánto se fue por ahí.
        "baseline_borrada_usd": (round(float(antes.get("baseline_usd") or 0), 2)
                                 if float(antes.get("baseline_usd") or 0) != 0
                                 and float(despues.get("baseline_usd") or 0) == 0 else 0),
        "en_pares_salteados": en_pares_salteados,
        "sin_serie_fx": sin_serie_fx,
        "flujos_manuales_usd_no_migrables": round(flujos_manuales_usd, 2),
        "ventas_con_tc_distinto": mal_tc[:5],
        "tcs_distintos_en_flujos": {"antes": antes["tcs_distintos_en_flujos"],
                                    "despues": _metricas(conn, uid)["tcs_distintos_en_flujos"]},
        "cash_intacto": cash_antes == {r["broker"]: round(r["c"] or 0, 4) for r in conn.execute(
            "SELECT broker, SUM(invested) c FROM positions "
            "WHERE user_id=? AND is_cash=1 GROUP BY broker", (uid,))},
        "nota": "antes los flujos estaban TODOS al mismo TC (la firma del bug); "
                "después tiene que haber un TC por fecha. `cash_intacto` tiene que "
                "ser true. `en_pares_salteados` y `sin_serie_fx` quedan al TC viejo "
                "A PROPÓSITO (no son fallas). `flujos_manuales_usd_no_migrables` es "
                "la parte del aportado que no se puede re-derivar (se guardó en USD "
                "sin el monto original en pesos).",
    }

    resultado["despues"] = despues
    # capital_final NO entra al delta: el recalc resetea el pnl_unrealized del
    # mes abierto (lo repone el sync del dashboard en la próxima visita), así que
    # su antes/después mezcla el efecto FX con ese artefacto y confunde la
    # decisión. Queda visible en antes/despues, con esta nota.
    resultado["delta"] = {
        k: round((despues[k] or 0) - (antes[k] or 0), 2)
        for k in ("pnl_ventas_usd", "deposits_usd", "withdrawals_usd",
                  "pnl_realized_usd")
        if isinstance(antes.get(k), (int, float)) or isinstance(despues.get(k), (int, float))
    }
    resultado["nota_capital"] = ("capital_final se excluye del delta: el recalc "
                                 "resetea el MtM del mes abierto y contaminaría la "
                                 "lectura; se repone solo en la próxima visita del "
                                 "usuario al dashboard.")

    # ── GATE SERVER-SIDE: la verificación FRENA, no solo informa ──────────────
    # Hasta acá `ok` seguía en True aunque la verificación saliera en rojo: el
    # único freno era que el operador viera el semáforo y destildara la fila a
    # mano. Con el apply masivo eso no alcanza (se puede aplicar sin simular, y
    # el server aceptaba lo que le mandaran). Ahora las mismas señales que se
    # reportan DECIDEN, y el endpoint hace rollback.
    #
    # Medido sobre las ~400 cuentas del dry-run masivo (2026-07-29), estos son
    # los tres motivos con evidencia:
    #   · cash tocado             → invariante duro, nunca debería pasar
    #   · alguna venta con TC ≠ el de su fecha → la migración no logró su objetivo
    #   · delta implausible       → el P&L ya estaba corrupto y migrar lo multiplica
    _frenos = []
    if not resultado["verificacion"]["cash_intacto"]:
        _frenos.append("el cash cambió (tiene que quedar intacto)")
    if mal_tc:
        _frenos.append(f"{len(mal_tc)} venta(s) quedaron con un TC distinto al de su fecha")
    if _denominador_roto:
        _frenos.append(_denominador_roto)
    if _fechas_mal:
        _frenos.append(_fechas_mal)
    if _implausible:
        _frenos.append(f"Δ P&L implausible (US$ {round(_d_pnl / _n_ventas, 2)}/venta sobre "
                       f"US$ {round(_d_pnl, 2)} totales): el P&L ya estaba corrupto y "
                       "migrar lo multiplica")
    if _frenos and not force:
        resultado["ok"] = False
        resultado["motivo"] = ("la verificación no pasó: " + " · ".join(_frenos)
                               + ". La migración se revierte. Si es un caso conocido "
                               "y querés forzarla igual, re-corré con force=true.")
        resultado["frenos"] = _frenos
    elif _frenos:
        resultado["forzado"] = _frenos

    return resultado
