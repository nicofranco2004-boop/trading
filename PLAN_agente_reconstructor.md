# Plan — Agente reconstructor

*Escrito 2026-08-20. Verificado contra `origin/main` = `0f646fd3`. El código vive en main; la rama `fix/ai-stale-position` no lo tiene — usar `~/rendi-worktrees/trial-audit`.*

---

## Decisiones tomadas (Nico, 2026-08-20)

1. **El agente toca el DATO del cliente, no el PARSER.** Resuelve la ambigüedad y anota el veredicto sobre esa cuenta. Reversible, acotado, con undo. El parser se toca sólo para **marcar** (`transfer_in`, `pair_id`), nunca para reinterpretar: marcar no cambia ningún número.
2. **El fallback se bifurca por causa.**
   - *"No sé qué hizo este cliente"* (ambigüedad de datos) → **al ASESOR**, que lo conoce. El TWR sale marcado como estimado hasta que se cierre.
   - *"Este broker exporta algo que no entiendo"* (gap de parser) → **a NICO**. Eso es exactamente el Import Guardian. Los dos proyectos se unen acá: el reconstructor enruta según la causa.

---

## El reencuadre que cambia el orden

El problema no es que el traspaso **desaparezca**. Es que en tres brokers **ya se está contando como aporte**, hoy, en producción.

Verificado: cuando entra un título por transferencia, el parser emite **dos** filas — la COMPRA y un DEPÓSITO compensatorio por el mismo monto:

- [balanz_movimientos.py:429-437](backend/importing/parsers/balanz_movimientos.py:429) — `"Transferencia Externa (entrada de título)"`
- [balanz_internacional.py:232-249](backend/importing/parsers/balanz_internacional.py:232)
- [ieb.py:361-384](backend/importing/parsers/ieb.py:361) — `"(cash compensatorio)"`

Y aguas arriba, `OP_TYPE_ALIASES` ([schema.py:52-90](backend/importing/schema.py:52)) mapea `TRANSFER_IN`, `ACAT_IN`, `JOURNAL_IN` y `TRANSFERENCIA_RECIBIDA` → `OP_DEPOSIT` antes de que ningún módulo llegue a mirarlos.

Ese depósito viaja hasta `monthly_entries.deposits` → `compute_net_deposited_db` → `twr._flujo` ([twr.py:258](backend/twr.py:258)). **El TWR del asesor ya está contaminado.** No estamos llenando un agujero: estamos deshaciendo una decisión que el parser ya tomó, siempre igual, para todos.

Corolario: enchufar la pantalla del TWR antes de corregir esto es publicar un número que sabemos mal, con la firma del asesor abajo. Por eso la pantalla es la fase 6 y no la 1.

**Dos problemas que el brief mezclaba, y sólo uno entra acá:**

| | Qué rompe | Cómo se arregla | ¿Entra? |
|---|---|---|---|
| **(A)** Traspaso de **títulos** | El **valor** (v0/v1 del Dietz): falta la tenencia | Crear la tenencia con cost basis → escribir en `positions` | ❌ Fuera. El camino ya existe: la foto de tenencia ([tenencia.py](backend/importing/tenencia.py)), que es lo que el propio error de [iol.py:230](backend/importing/parsers/iol.py:230) le recomienda al usuario |
| **(B)** Transferencia de **efectivo** + el depósito compensatorio | El **flujo**: ya entró como DEPOSIT | Anotación reversible | ✅ Este plan lo cierra entero |

---

## Fase 1 — El censo y los fixes que ya son bugs hoy

**Objetivo:** saber, por broker y sobre datos reales, cuántos movimientos ambiguos hay; y cerrar las puertas por las que el agente entraría sin que nadie lo decida.

**Por qué acá:** todo lo demás se dimensiona con ese número, y estos fixes son de una línea y no mueven ningún saldo.

**Medir** — `backend/censo_flujos.py`, 100% SELECT, desglosado por broker:
- **P1 rechazadas:** `import_raw_rows JOIN import_batches` con `b.status='confirmed' AND r.status='invalid' AND errors_json LIKE '%TRANSFER%'`. Esperamos 0 — el punto es comprobarlo.
- **P2a:** `import_normalized_tx` con `excluded_at IS NULL AND transfer_out=1` (única marca estructurada que sobrevive el round-trip).
- **P2b — la que ya contamina:** `operation_type='DEPOSIT'` con `notes` matcheando los literales reales de arriba. Usar la parte estable: varios parsers truncan a `desc_raw[:120]`.
- **P2c firma numérica:** `quantity≠0 AND COALESCE(gross_amount,0)=0 AND operation_type IN ('BUY','SELL')`.
- **P3:** `ledger_replay.verificar_contra_hoy` sobre una muestra — cuántos dan `reproducible=False`.
- `GET /api/admin/censo-flujos` con `Depends(get_admin_user)`, molde de `admin_diagnose_negative_capital` ([main.py:15407](backend/main.py:15407)).

**Fixes gratis:**
- [twr.py:89](backend/twr.py:89) **fail-closed**: `if src in _POR_SOURCE` → `if src is not None: return _POR_SOURCE.get(src, INDETERMINADO)`. Es la puerta por la que entra el agente cuando escriba `source='reconstruido'`. ⚠️ Antes de mergear, correr `SELECT DISTINCT source, COUNT(*) FROM snapshots` — no está verificado si prod tiene algún source no contemplado entrando hoy como borde legítimo.
- **`ridx + 1`** — bug de diagnóstico vivo en prod: [ppi.py:286,317,375](backend/importing/parsers/ppi.py:286), [balanz_movimientos.py:577](backend/importing/parsers/balanz_movimientos.py:577), [balanz_internacional.py:345](backend/importing/parsers/balanz_internacional.py:345), [balanz_resultados.py:293](backend/importing/parsers/balanz_resultados.py:293). `ridx` es el contador de `_emit`, o sea la **próxima** fila: el error queda pegado a una fila buena. Pasar el índice de la fila leída.
- [flujos.py:57](backend/flujos.py:57) — `r.status != 'ok'` es **siempre verdadero**: `pipeline.py:997` escribe `'valid'`/`'invalid'`, nunca `'ok'`. La query trae todas las filas crudas del usuario (3,1M de 3,4M filas) sin LIMIT. Pasa a `r.status='invalid' AND b.status='confirmed' AND UPPER(COALESCE(errors_json,'')) LIKE '%TRANSFER%'` + `LIMIT 301`. El filtro de batch además saca previews (mueren en 1h) y revertidos.
- [flujos.py:36-45](backend/flujos.py:36) — `_texto_crudo` sólo hace `.upper()`. Deacentuar reusando `iol._deaccent` / `ieb._norm_label` / `ppi._norm_header`; no escribir la cuarta.
- [flujos.py:30,34](backend/flujos.py:30) — sacar `RECEIVED`/`DELIVERED` sueltos: `"Wire Received"` de Schwab, que es **un aporte real**, matchea ENTRADA por subcadena. Anclar a `SHARES RECEIVED`/`SHARES DELIVERED`.
- [test_advisor_plan.py:2442-2456](backend/tests/test_advisor_plan.py:2442) — el fixture inserta `status='done'`/`'ok'`/`'error'`: tres strings que producción no escribe nunca. **Por eso los tests pasaban en verde sobre una cola vacía.** Reescribir a los valores reales.
- ⚠️ Anotar en `MIGRACION_POSTGRES.md:2294`: vaciar `raw_json` de imports viejos debe **exceptuar `status='invalid'`**. Es el único lugar donde viven activo, cantidad y texto del broker de una fila rechazada. Hoy no está anotado en ninguno de los dos proyectos — es la dependencia cruzada más peligrosa del plan.

**Cierre:** el endpoint devuelve `{P1,P2a,P2b,P2c,P3}` por broker sobre la base real, con la observación esperada **P1=0 y P2b>0**. Más tres tests que hoy fallan: `clasificar_fila({'source':'reconstruido', holdings}) == INDETERMINADO`; un fixture PPI con `Ingreso de Títulos` seguido de `Retiro de Fondos` deja el retiro `valid`; `direccion_por_texto('Retiro de Títulos') == 'salida'` y `('… WIRE RECEIVED') is None`.

**Entrega sola:** el tamaño del problema, medido. Y un bug menos que hoy le señala al usuario una fila correcta mientras la que falló no aparece.

**No hace:** no crea tablas, no escribe veredictos, no toca el TWR ni una pantalla.

**Esfuerzo:** S.

---

## Fase 2 — Que ningún traspaso desaparezca en silencio

**Objetivo:** todo traspaso deja una fila persistida, y ninguna toca la plata.

**Por qué acá:** hasta que la población esté completa, cualquier tasa está sesgada justo hacia los brokers donde el traspaso es más común (IOL y Schwab).

**La sombra, por el rail que el código ya tiene y nadie usa:** emitir la `RawRow` con `tipo='TRANSFER'`. [validator.py:150-154](backend/importing/validator.py:150) lo rechaza con `TRANSFER_NOT_SUPPORTED` → no entra a `valid_txs`, no se persiste `import_normalized_tx`, **cero riesgo sobre la plata**, y la fila queda en `import_raw_rows` lista para `candidatos()`.

> 🔴 **REGLA DURA en las 6 tareas de parser: la sombra lleva `monto` vacío o `'0'`, NUNCA distinto de 0.** Medido: `tipo='TRANSFER'` + `monto='1000'` → [normalizer.py:238-256](backend/importing/normalizer.py:238) lo reclasifica por signo a `OP_DEPOSIT` y **lo importa como plata nueva**. El arreglo que habilita al agente cometería, mal hecho, exactamente el bug que el agente existe para evitar.

- [iol.py:655-658](backend/importing/parsers/iol.py:655) — hoy `parse_errors.append(...); continue` sin `raw_rows.append`. Agregar sombra con fecha, activo, cantidad y `notas=tipo_mov` (ya trae `"Transferencia de Titulos IN - (AAPL)"` → el IN/OUT viaja gratis).
- [ppi.py:284-289](backend/importing/parsers/ppi.py:284) — sombra para `Ingreso de Títulos` / `Canje` / `Traspaso`, emitida con `_emit()` para que `ridx` avance. **NO** hacer sombra del SPOT ([ppi.py:317](backend/importing/parsers/ppi.py:317)): rompe `test_ppi.py:143-146` y `161-168`.
- `schwab.py:250-252` y `257-259` — los dos `continue` silenciosos (pata OUT de `Journaled Shares` con `qnum<=0`, y las filas sin símbolo tipo `TDA TO CS&CO TRANSFER`).
- `balanz.py:236-238` — `continue` sin ni siquiera un RowError.
- `inviu.py:207-208` — el `break` de `Disponible - Instrumentos` corta el archivo entero. Registrar antes de cortar.
- **Conservar el texto crudo donde hoy se destruye**: `cocos.py:545-557` deja sólo `"Comp. NNNN"` y `bullmarket.py:426,595` sólo `"Op. N"`. Una línea cada uno. Es la materia prima del agente.
- **Marcar, no reinterpretar** — replicar el rail de `transfer_out` (parser → `normalizer.py:407` → `schema.py:257` → INSERT `pipeline.py:1008` → rehidratación `pipeline.py:1074`) para tres columnas nuevas en `import_normalized_tx`: `transfer_in`, `pair_id`, `cost_basis_pending` (hoy `schema.py:243` se calcula y se tira). Setearlas en el par COMPRA+DEPOSITO de los tres parsers, **con el mismo `pair_id` en las dos patas** — sin eso el apareo es heurístico por `(batch_id, fecha, monto)` y dos transferencias del mismo monto el mismo día se cruzan.
- ⚠️ **El ALTER va con el índice DESPUÉS y FUERA del `if`**, como `excluded_at` ([main.py:2435-2448](backend/main.py:2435)). El orden inverso ya tumbó prod 20 minutos.
- **Test de invariante** `test_sombra_traspaso.py`: por cada parser tocado, correr `normalize_rows` + `validate` sobre el dict de la sombra y afirmar `valid_txs == []`. Cubrir la **segunda puerta**: `load_session_with_seed_revalidate` ([pipeline.py:1101-1128](backend/importing/pipeline.py:1101)) re-normaliza todas las raw rows sin filtrar status.
- Actualizar `test_iol.py:174-177` (`len(res.raw_rows) == 0` → 1). Único test de parser que se rompe.
- **NO tocar** `binance_transaction.py:343`: `Transfer Between Main and Funding Wallet` es interno del mismo usuario; su `continue` es correcto.

**Cierre:** `flujos.reconciliar(conn, uid)` sobre un export IOL real deja de devolver `{'candidatos': 0, 'tasa_pct': 100.0}` — el repro exacto del problema. Y el mismo test corre el pipeline completo comparando `compute_net_deposited_db` antes/después: no se movió un centavo.

**Entrega sola:** el usuario deja de perder el traspaso en silencio — lo ve en el wizard con su motivo.

**No hace:** no cambia qué se importa, no toca `OP_TYPE_ALIASES`, no resuelve nada, no crea la tenencia faltante.

**Esfuerzo:** M.

---

## Fase 3 — `flujos.py` que funciona, y EL NÚMERO que decide el proyecto

**Objetivo:** la pasada determinística corre sobre la población correcta, puede por fin devolver `traslado_interno`, y reporta cuántos casos y **cuánta plata** quedan sin resolver.

**Por qué acá:** es la pasada barata; su tasa real decide si el agente se construye.

- **Cambiar la fuente.** El docstring de [flujos.py:23-26](backend/flujos.py:23) es falso: `pipeline.py:698` guarda el dict de **salida** del parser, y el archivo original no se persiste. La fuente correcta es `import_normalized_tx`, que trae `broker`, `date`, `asset_symbol`, `quantity`, `currency`, `transfer_out` y `notes` en la misma fila. `candidatos()` une: **A** = sombras de Fase 2; **B** = `import_normalized_tx` con `excluded_at IS NULL` y (`transfer_out=1 OR transfer_in=1 OR cost_basis_pending=1 OR` la firma numérica).
- **Eso arregla solo el cruce inalcanzable.** Hoy `candidatos()` emite `{raw_id,broker,texto,raw_json}` ([flujos.py:67-71](backend/flujos.py:67)) y `resolver()` pide `asset`/`fecha`/`cantidad` ([flujos.py:126](backend/flujos.py:126)) → el `if` es siempre falso y `cruce_entre_brokers` es código muerto. Con la fuente nueva los cuatro campos salen del SELECT.
- **Invertir la precedencia** ([flujos.py:114-140](backend/flujos.py:114)): hoy corre `direccion_por_texto` primero y **retorna incondicionalmente** mapeando entrada→`aporte`, así que nunca devuelve `traslado_interno` — la única respuesta para la que el módulo existe. Orden nuevo: (1) par COMPRA+DEPOSITO por `pair_id`; (2) `cruce_entre_brokers`; (3) el texto **sólo como desempate**, y sólo cuando el sustantivo lo permite (`Ingreso de FONDOS` = aporte; `Ingreso de TÍTULOS` = candidato a traslado); (4) `resuelto=False`.
- Partir en dos: `direccion_por_texto` devuelve dirección y nada más; `naturaleza_por_texto` mira el **complemento**, que es la palabra que decide — `Transferencia **Externa**`, `a **Schwab**`, `**Fondos**` vs `**Títulos**`.
- ⚠️ **Precedencia y vocabulario en el mismo commit, en ese orden.** Los strings del broker son direccionales por diseño: cada string nuevo agregado sin invertir la precedencia sale clasificado como aporte. Mejorar el vocabulario primero **empeora** el sistema de forma medible.
- **Vocabulario real.** Medido: de 17 notas reales de los 14 parsers, 15 devuelven `None`, y los 2 aciertos no son traspasos de títulos — hoy cubre **cero** casos producidos por un parser de broker.
  - ENTRADA: `TRANSFERENCIA DE TITULOS IN`, `INGRESO DE TITULOS`, `DEPOSITO TITULOS TRANSF`, `DEPOSITO DE TITULOS`, `TRANSFERENCIA EXTERNA`, `LIQUIDACION DE TRANSFERENCIA`, `JOURNALED SHARES`/`INTERNAL TRANSFER` con qty>0, `TRASPASO`, `CANJE`.
  - SALIDA: `TRANSFERENCIA DE TITULOS OUT`, `RETIRO DE TITULOS`, `RETIRO TITULOS TRANSF`, `JOURNALED SHARES` con qty<0, `WITHDRAW`, `SEND`.
  - NEUTRO (mismo usuario, se ignora): `TRANSFER BETWEEN MAIN AND FUNDING WALLET`, `TDA TO CS&CO TRANSFER`, `CASH MOVEMENT`, `BLOQUEO`/`DESBLOQUEO`, sweeps `DESDE BALANZ`/`A BALANZ`.
  - Cada string con un test que le pasa la nota **real** que emite su parser.
- `TOPE_CASOS = 300` por usuario, con `COUNT(*)` **antes** de materializar nada. Y `reconciliar()` deja de ser N+1: una query para candidatos, una para todas las patas opuestas del rango, matcheo en memoria.
- El reporte crece: `{candidatos, resueltos, pendientes, por_via, por_broker, por_naturaleza, truncado, monto_usd_en_juego, meses_afectados}`. **`monto_usd_en_juego` importa más que el conteo**: 200 casos de US$3 no justifican un agente; 4 de US$40.000 sí.
- `GET /api/admin/reconciliar-flujos` (admin, read-only) con el agregado sobre N usuarios.
- **No tocar `OP_TYPE_ALIASES`**: cambiarlo reescribe el significado de todos los imports genéricos históricos. Esas filas se marcan `transfer_in=1` y caen en la cola.

**Cierre:** `test_ingreso_de_titulos_no_es_aporte` — 12 AAPL salen de Balanz el 12/4 y entran 12 en IOL el 12/4 → `naturaleza='traslado_interno'`, `via='cruce_entre_brokers'`. Hoy es imposible por partida doble. Y la observación: **tasa determinística real + monto en juego**, medidos.

> El ">50% a costo cero" del diseño original y el "US$0,23/usuario" de Opus **no están sostenidos por ningún dato**. Se miden acá y en la Fase 7; no se asumen.

**Entrega sola:** el número que decide el proyecto, y la tasa por broker que dice dónde conviene una regla determinística más — mucho más barato que un token.

**No hace:** sigue siendo 100% SELECT. No aplica nada, no llama a ningún modelo.

**Esfuerzo:** M.

---

## Fase 4 — La red de seguridad

**Objetivo:** `sellar()` deja de ser un INSERT ciego, deja de saltear meses en silencio, y un mes sellado mal se puede retractar sin pisar una fila.

**Por qué acá:** ninguna capacidad de escritura existe antes que la guarda que la vigila. Sin retracción, la primera deducción equivocada que se selle queda dentro del número que justifica el fee, para siempre.

- [twr.py:316-347](backend/twr.py:316) — hoy `sellar()` es `tramos()` → INSERT y nada más. Ocho guardas antes del INSERT:
  - **G1 identidad** — si `abs(flow) < 0.005*v0` entonces `abs(ret-(v1/v0-1)) < 1e-9`
  - **G2** re-derivar `ret == dietz(v0,v1,flow)`
  - **G3 dominio** — `ret >= -1.0`, `v0+0.5*flow > 0`
  - **G4 mes cerrado** — `t['month'] < _hoy_art()[:7]` (hoy confía ciegamente en el filtro de `tramos()`)
  - **G5 contigüidad** — `period_end` dentro de `month`, `period_start` en el mes sellado anterior
  - **G6 bordes** — re-leer por `snap_id_*` y exigir `clasificar_fila == MEDICION` en los dos
  - **G7 fx** — no sellar `quality='ok'` con `fx_basis_v0 != fx_basis_v1`
  - **G8 sensibilidad al flujo** — correr `dietz` con peso 0,25 / 0,5 / 0,75 sobre el mismo tramo; si `ret` se mueve más que un umbral → `quality='sensible_al_flujo'`. **Es la sombra de runtime de la invariante de neutralidad**, que como contrafáctico no se puede chequear sobre datos reales. Y después le dice al agente dónde gastar.
- [twr.py:296-297](backend/twr.py:296) — `if r is None: continue` hace desaparecer del historial, sin rastro, todo mes cuyo denominador no dé, y la cadena se cierra sobre el agujero. Emitir el tramo con `quality='no_medible'`. *"Nunca saltear un mes en silencio"* es regla del diseño y hoy se viola sin test que lo cubra.
- [twr.py:364-390](backend/twr.py:364) — `twr_de()` multiplica **todas** las filas y usa `quality` sólo para armar `meses_degradados`: `flujo_sospechoso` y `plano` entran al número igual. Al producto entran sólo `estado='vigente' AND quality='ok'`; un mes degradado o retractado **rompe** la cadena → se devuelve la racha contigua más larga + `meses_excluidos` + `motivo='cadena_interrumpida'`.
- [twr.py:313](backend/twr.py:313) — `_CAMPOS_SELLO` suma `ret`, `quality`, `fx_basis_v0/v1`, `metodo`, `flow_source`. Hoy `ret` es función pura de tres campos; deja de serlo el día que el agente cambie el método con los mismos inputs, y ese cambio no generaría revisión.
- [twr.py:308](backend/twr.py:308) — `"fx_basis": "mep_medio"` es un literal hardcodeado igual para todos, que nadie lee, que puede ser **falso incluso para el cron** (`_user_tc_cedear` cae a `tc_blue` sin config de MEP) y que choca con `ledger_replay.FX_BASIS='mep_venta'`. **Propagar** la base de cada borde. Va antes de que el primer valor reconstruido toque `twr_periods`: el spread (~0,7%) se compone mes a mes y después es indistinguible del rendimiento.
- Migración aditiva sobre `twr_periods` (la tabla está prácticamente vacía en prod): `estado DEFAULT 'vigente'`, `retract_reason`, `retract_ref`, `retracted_at`, `metodo DEFAULT 'medido'`, `flow_source`, `confianza`, `fx_basis_v0`, `fx_basis_v1`, `guardas_json`. **Índice después del ALTER y fuera del `if`.**
- `twr.retractar(conn, uid, mes, motivo, ref)` = INSERT `revision+1` con `estado='retractado'`, nunca UPDATE. Con `retract_ref`, retractar una corrida entera es un loop de INSERTs.
- Trigger `BEFORE UPDATE ON twr_periods` → `RAISE(ABORT)`. **Sólo sobre UPDATE** — `twr_periods` está en `_RESET_PORTFOLIO_TABLES` y el reset hace DELETE; dejar test de que "empezar de cero" sigue funcionando.
- 🔴 **Sacar el sellado del GET.** [advisor_twr.py:92-98](backend/advisor_twr.py:92) corre `twr.sellar` cliente por cliente dentro del `with conn:` del endpoint: una transacción de **escritura** sobre todo el libro, en el hilo del request, sin rate limit ni lock, con un `except → log.warning` que se come cualquier IntegrityError. Pasar `sellar_primero=False` por default y mover a `POST /api/twr/sellar-cron` con `X-Cron-Token` + lock + thread daemon, calcando `main.py:31237-31268`. **Commit por cliente**, nunca una transacción que abarque el libro. Tabla `twr_seal_log` con `sellados/revisados/rechazados/motivos_json`.
- [ledger_replay.py:109-146](backend/ledger_replay.py:109) `verificar_contra_hoy` — taparle los dos agujeros antes de usarla como gate: **(a)** no ve el CASH (`cash_en()` está justo al lado sin usarse) → hoy un ledger corto por todo el saldo en pesos sale `reproducible: True`; **(b)** no ve los CERRADOS (los dos lados descartan ceros) → una venta fantasma pasa muda.
- Arrancar con `TWR_GUARDAS=0`: cada guarda registra en `guardas_json` sin bloquear, se mide cuántos meses rechazaría sobre datos reales, y recién ahí se prende.

**Cierre:** cinco tests que hoy fallan — `test_un_mes_degradado_no_entra_al_producto`, `test_un_mes_no_medible_no_desaparece`, `test_no_se_sella_un_borde_que_no_es_medicion`, `test_retractar_no_pisa_la_revision_vieja`, `test_no_se_puede_UPDATE_twr_periods`. Las 12 invariantes siguen verdes.

**Entrega sola:** el único punto de escritura del número que justifica el fee pasa de desguarnecido a verificable y reversible.

**No hace:** no cambia ningún número visible — hoy ninguna pantalla llama a `/api/advisor/twr`.

**Esfuerzo:** L.

---

## Fase 5 — La vía de escritura, con interruptor

**Objetivo:** un veredicto tiene dónde vivir y **un solo** camino al TWR, apagable por env var, sin tocar ninguna tabla de plata; y la determinística ya corrige el número.

- Tabla `flujo_resoluciones`, append-only, copiando los dos patrones maduros del repo (`revision+1` de `twr_periods` y `token`/`undone_at`-como-lock de `deleted_ops_journal`): `(id, user_id, scope_tipo ['tx'|'raw'|'par'], scope_id, batch_id, fecha, broker, activo, monto_usd, naturaleza, confianza, via, evidencia_json, modelo, revision, aplicado DEFAULT 0, aprobado_por, aprobado_at, revocado_at, batch_ref, created_at, UNIQUE(user_id, scope_tipo, scope_id, revision))`.
- **Un solo lector: `twr._flujo`** ([twr.py:258-264](backend/twr.py:258)), que le resta el neto de las resoluciones `aplicado=1 AND revocado_at IS NULL AND naturaleza='traslado_interno'` en `(desde, hasta]`.

**Por qué NO los otros candidatos:**

| Candidato | Por qué no |
|---|---|
| `compute_net_deposited_db` | 6 call sites de producción — `twr._flujo` (×2), `advisor_alerts.py:105`, `main.py:30416` y `:30454` (recómputo de `snapshots.net_deposited` = curva y Total Return del Dashboard **retail**), y `reporting/builder.py:178,313,412`. Un veredicto equivocado saldría en cinco pantallas, para el cliente final, congelado en filas históricas |
| `monthly_entries` | Se **regenera**: `_recalc_pnl_realized_from_ops` hace `UPDATE ... SET deposits=?` y tiene 52 call sites. La única columna pegajosa es `manual_deposits`, y usarla sería la IA escribiendo un depósito manual indistinguible del que cargó el usuario |
| `excluded_at` | Es un tombstone de **existencia**, no de naturaleza. Lo respetan `_import_flows_for_period`, `_recalc._seed`, `rebuild._full_events` (el replay FIFO) y `persister.revert_batch`, y el path que lo setea además revierte el cash y borra las `operations`. Un traslado interno **sí pasó** y sí movió el saldo |

- 🔴 **El interruptor, obligatorio:** env `RECONSTRUCTOR_APLICAR` (default 0) + la columna `aplicado`. Sin esto, la primera carga de la pantalla del asesor sella los meses con el flujo ya corregido, sin ningún paso explícito de "aplicar", y quedan como **revisión 1** — la que el asesor va a leer como "el número original".
- `flujos.aplicar(conn, uid)` escribe con `aplicado=1` **sólo** lo resuelto por `via in ('par_compra_deposito','cruce_entre_brokers')` con confianza 1,0. Nada resuelto sólo por texto se aplica automático.
- Guarda de ambigüedad: si para un mismo `(batch_id, fecha, monto)` hay más de un candidato y no hay `pair_id`, **no se resuelve**.
- `GET /api/admin/diag/flujo-contaminacion?uid=` — read-only: por cliente y por mes, `aportado_ssot`, `ajuste_usd`, `pct_contaminado`, y el TWR contrafáctico (`twr_actual` vs `twr_con_ajuste`) en memoria, sin sellar.

**Cierre:** `test_un_traslado_interno_no_infla_el_flujo` — el TWR cambia y **`monthly_entries` no se movió** (eso es lo que hace el cambio reversible). `test_con_aplicar_en_0_el_twr_es_bit_a_bit_identico`. `test_revocar_dispara_revision_nueva`: revocar mueve `flow_usd`, que está en `_CAMPOS_SELLO`, así que sellar escribe `revision+1` y `sellados()` toma la máxima — se auto-corrige sin borrar historia.

**Entrega sola:** el primer número duro del proyecto — cuántos dólares del capital aportado de cada cliente **no son plata nueva** — y la corrección aplicada, sin gastar un token.

**No hace:** no muestra nada en pantalla, no toca el retail, no hay agente.

**Esfuerzo:** M.

---

## Fase 6 — La superficie del asesor: el producto completo, sin agente

**Objetivo:** el asesor ve el rendimiento real por cliente, ve los casos que la determinística no cerró, los cierra a mano en lote, y puede deshacer el lote entero.

**Por qué acá:** recién ahora el número que se publica está corregido. Y si la Fase 3 midió una tasa determinística alta, **esta fase puede ser el final del proyecto**.

- Chip del TWR en `AdvisorClients.jsx` ClientCard, al lado del `chipSalud` que ya existe (`:293-299`), con un segundo `api.get('/advisor/twr')` con `.catch(() => null)` — mismo patrón que el fetch de `/advisor/data-health` de `:55`. `motivo === 'pocos_meses'` → "Faltan meses medidos".
- Card del TWR en `AdvisorDashboard.jsx` entre `BookHero` y `BookEvolution` (`:122-131`), con **la cobertura pegada al número**: meses medidos, `meses_revisados`, `meses_degradados`, `meses_excluidos`, `metodo_mix`. Cuánto del número lo construyó una corrección es parte del número, no una nota al pie.
- 🔴 **Resolver la colisión de dos retornos antes de shippear.** El botón "Informe del período" de esa misma pantalla (`AdvisorDashboard.jsx:84-91` → `main.py:33118`) calcula `ret_pct` con **Dietz simple de una sola ventana** (`main.py:32886-32895`), no con el Dietz encadenado de `twr.py` — y ese informe se le manda al cliente final por WhatsApp con link público. O el informe pasa a leer `twr_periods`, o la card lleva etiqueta que los distinga, pero no se shippea sin decidirlo.
- Tabla `reconstructor_casos` `(user_id, advisor_uid, origen, ancla_id, fecha, broker, activo, cantidad, monto_usd, propuesta_json, confianza, via, estado ['pendiente'|'aprobado'|'rechazado'|'auto'], resuelto_por, resuelto_at, batch_ref)`.
  - ⚠️ **No puede vivir en `advisor_alert_events`:** `purge_old()` ([advisor_alerts.py:91-97](backend/advisor_alerts.py:91)) borra todo lo mayor a 3 días y se llama en **cada** `history()` y en **cada** `evaluate()`. Los casos de Juan desaparecerían sin haberse resuelto, con el TWR publicado sobre datos que nadie cerró.
- **El aviso sí reusa las alertas:** `kind='reconstructor_pendiente'` en `advisor_alerts.py:289-294`. Sale gratis el push, el email, el badge del sidebar y el tope de 1/día. La cola persiste, el aviso se purga: exactamente como está diseñado. ⚠️ **Ojo `AdvisorAlerts.jsx:91`**: colorea el puntito con `(ev.pct ?? 0) >= 0` → un evento sin `pct` sale **verde**, como buena noticia. Ramificar por `kind` antes de emitir el primero.
- **La bifurcación del fallback (decisión 2):** el caso se enruta por causa. `origen='ambiguedad'` → cola del asesor. `origen='gap_parser'` (un código de error que ningún parser supo mapear) → **al Import Guardian**, mail a Nico. Es el punto donde los dos proyectos se encuentran.
- Sección nueva en `AdvisorDashboard.jsx` debajo de `CallQueue` (`:577-628`), que ya es "Clientes que necesitan tu atención" con chips por `kind` y el mismo shape.
- Wizard calcado de `GroupOpModal` (`AdvisorClients.jsx:587+`): propuesta **prellenada y editable fila por fila**, con **la evidencia al lado de cada fila** —no sólo el veredicto—, y preservando lo tipeado al volver de paso (`:645`: *"perder 15 cantidades cargadas era el bug del review"*).
- `POST /api/reconstructor/aplicar` → escribe N filas con `batch_ref` y devuelve `{aplicados, skipped:[{caso, reason}]}` con la razón **en castellano**. "Deshacer lote completo" → `POST /api/reconstructor/lote/{ref}/undo` con claim atómico (`UPDATE ... WHERE batch_ref=? AND undone_at IS NULL`, si `rowcount != 1` se aborta) + `flujo_resoluciones.revocar` + `twr.retractar_lote`.
  - **No reusar `advisor_op_batches`**: su `op_kind` se escribe siempre `'buy'` (`main.py:33434`) y su undo sólo sabe borrar posiciones y re-acreditar cash.
- ⚠️ **Nada de estado en memoria:** `_GROUP_DRAFT`/`_LAST_GROUP_BATCH` (`main.py:21888-21889`) son dicts de proceso con TTL 900s; Railway redeploya seguido y con más de un worker el claim por `dict.pop` deja de serlo.
- Decir en la UI que el TWR del asesor y el "Capital aportado" del Dashboard del cliente pueden diferir mientras la corrección viva sólo en el TWR.

**Cierre:** e2e — el asesor abre `/dashboard`, ve N casos con su propuesta, aprueba un lote, el TWR del cliente se mueve, y "Deshacer lote completo" lo devuelve **exactamente** al valor anterior. Más: los casos siguen ahí después de 4 días (no se los comió `purge_old`), y el segundo POST al mismo `batch_ref` devuelve 409.

**Entrega sola:** es el producto completo aunque el agente no exista nunca.

**No hace:** no auto-aplica nada por umbral, no toca el retail, no crea una 5ª pantalla en el sidebar.

**Esfuerzo:** L.

---

## Fase 7 — El agente, sólo sobre el residuo medido y en sombra primero

**Objetivo:** lo que la determinística no cerró se resuelve con modelo, con la obsesión puesta en saber cuándo **no** está seguro.

> 🚪 **GATE DE ENTRADA, escrito:** esta fase sólo se construye si la Fase 3 midió un residuo que la justifique. Si la tasa determinística ≥95% y el `monto_usd_en_juego` del residuo es <1% del AUM del libro, **no se hace**: se cierra a mano por la Fase 6. Si el residuo está concentrado en pocos brokers, primero va la regla determinística de ese broker.

- `backend/reconstructor.py`, calcando `advisor_brief.run_briefs` ([advisor_brief.py:352-389](backend/advisor_brief.py:352)): itera, `try/except` **por cliente**, idempotencia por tabla de log, devuelve `{resueltos, no_se, saltados, fallados}`, acepta `only_uid`. **`conn.commit()` ANTES de llamar al modelo** — `advisor_alerts.py:181` ya pagó esa lección con un push, y una llamada a Opus es mucho más larga.
- **Gate por usuario:** `verificar_contra_hoy` (ya con cash y cerrados, Fase 4). Si `reproducible=False`, el ledger no puede recrear el presente, así que tampoco enero: no se llama al modelo. Y su lista `diferencias` es **mejor fuente de candidatos** que `flujos.candidatos()` — los 12 AAPL aparecen como `{broker:'IOL', asset:'AAPL', replay:0, real:12}`. Limitación a dejar escrita: es una prueba en presente usada como proxy del pasado. Necesaria, no suficiente.
- **Contexto que ve:** la tx, ±`DIAS_CRUCE` del mismo broker, los otros brokers de esa persona en esas fechas, el efectivo (`ledger_replay.cash_en`), y el resultado de `flujos.resolver()` con su evidencia, para que sepa qué ya se descartó.
- ⚠️ **Corrección al diseño original:** *"la fila cruda del export"* no existe. `raw_json` es el dict de salida del parser y el archivo original no se persiste. El texto del broker sólo sobrevive en `notas`, y sólo donde el parser lo copió — por eso la Fase 2 toca Cocos y Bull Market.
- Salida obligada `{naturaleza, confianza 0..1, evidencia, no_se}`. **Regla dura en código, no en el prompt:** `confianza < UMBRAL` (arrancar en 0,85, env) → se fuerza `no_se` y el caso va a la cola humana.
- **Priorizar con G8:** gastar Opus sólo donde mover el flujo mueve el retorno. Es la diferencia entre correr sobre 300 casos y sobre los 40 que importan.
- Topes con corte duro y log: 300 casos por usuario, tope por **libro** (hoy ni `advisor_book` ni `advisor_twr` capean clientes), tope de USD por corrida. Tabla `reconstructor_runs` con tokens y costo.
- `POST /api/reconstructor/run-cron` con `RECONSTRUCTOR_CRON_TOKEN` (**sin env var → 503, apagado por default**), lock, thread daemon.
- **Sombra primero:** escribe siempre `aplicado=0`, `via='agente'`, `flow_source='agente'`, `batch_ref=<run_id>`. Nunca `positions`, nunca `monthly_entries`, nunca `import_normalized_tx`.
- **Backtest con dos métricas, no una:** tomar los pares con `pair_id` exacto (verdad conocida), ocultarle la evidencia estructural, y medir (1) tasa de acierto y (2) **tasa de "no sé" correcta**. La segunda decide si se le abre una pantalla. Al reportar, decir que el backtest corre sobre los casos que la determinística **sí** pudo resolver — o sea los fáciles: es un techo optimista.

**Cierre:** `test_el_agente_nunca_escribe_aplicado_1`, `test_confianza_baja_se_convierte_en_no_se`, `test_gate_no_reproducible_no_llama_al_modelo` (mock con 0 llamadas). Y el backtest sobre ≥30 casos: de los que dio confianza >0,9, **cero** equivocados. Si no se cumple, se apaga con la env var y queda la Fase 6, que funciona sola.

**Entrega sola:** la respuesta que hoy no se puede dar con datos: ¿acierta, y sabe cuándo no sabe?

**No hace:** no aplica nada, no manda un solo mail (⚠️ `backend/.env` tiene `RESEND_API_KEY`: correr esto fuera de pytest manda mails de verdad), no crea tenencia faltante, no abre a retail.

**Esfuerzo:** L.

---

## El mapa

| Fase | Objetivo | Esfuerzo | Entrega |
|---|---|---|---|
| 1. Censo + fixes gratis | Saber el tamaño; cerrar el fail-open y el `ridx+1` | S | El número que dimensiona todo, y un bug de plata menos |
| 2. Que nada desaparezca | Todo traspaso deja fila; `transfer_in`/`pair_id` marcados | M | El usuario deja de perder el traspaso en silencio |
| 3. `flujos.py` de verdad | Precedencia, cruce alcanzable, vocabulario real | M | **La tasa determinística y el monto en juego → el gate del proyecto** |
| 4. Red de seguridad | 8 guardas, retracción, fx propagado, sellado fuera del GET | L | El punto de escritura del número deja de estar desguarnecido |
| 5. Vía de escritura | `flujo_resoluciones` + un lector + interruptor | M | Cuánto del capital aportado no es plata nueva, corregido |
| 6. Superficie del asesor | TWR en pantalla + cola persistente + deshacer lote | L | **El producto completo, aunque el agente nunca exista** |
| 7. El agente | Sólo el residuo, en sombra, con umbral y presupuesto | L | Cierra lo que ningún SQL podía — si el gate lo justifica |

---

## Lo que puede salir mal

1. **La sombra con monto convierte el traspaso en un depósito importado.** Es el bug que el proyecto existe para evitar, cometido por el arreglo que lo habilita. *Mitigación:* la regla dura de Fase 2 y el test de invariante sobre `normalize+validate` —no sobre el parser—, cubriendo también `load_session_with_seed_revalidate`.
2. **Se sellan meses con veredictos que nadie revisó.** `/api/advisor/twr` **no es código muerto: es código vivo que escribe** — con `sellar_primero=True` la primera carga sella todo el libro, y esas filas quedan como revisión 1. *Mitigación:* Fase 4 saca el sellado del GET; Fase 5 agrega `RECONSTRUCTOR_APLICAR` + `aplicado`.
3. **El agente deduce mal con confianza.** Se ve perfectamente razonable, igual que el per-100, el blue-vs-MEP y el cost-basis-vs-MtM. *Mitigación:* gate de reproducibilidad, umbral duro, escritura siempre `aplicado=0`, backtest de la tasa de "no sé" correcta, undo por lote y retracción dirigida.
4. **El asesor ve dos retornos distintos en la misma pantalla.** La card del TWR y el "Informe del período" que va al cliente por WhatsApp con link público. *Mitigación:* bloqueante declarado de la Fase 6. Complicación: hay informes congelados con el número viejo, y `POST /advisor/reports/{id}/revoke` existe.
5. 🔴 **La migración a Postgres mata la cola.** `MIGRACION_POSTGRES.md:2294` planea vaciar `raw_json` de los imports viejos — el único lugar donde viven activo, cantidad y texto del broker de una fila rechazada. *Mitigación:* anotado en Fase 1, exceptuando `status='invalid'`. **Hoy no está anotado en ninguno de los dos proyectos.**

---

## Decisiones que quedan abiertas

| # | Pregunta | Recomendación |
|---|---|---|
| 1 | ¿El ajuste llega al retail? | **No por ahora.** Un lector contra 6 call sites. La divergencia entre el TWR del asesor y el Capital aportado del cliente es deliberada — **decirla en la UI**, no dejar que se descubra |
| 2 | ¿Se corrige hacia atrás? | **Sí**, es todo el punto: esas filas ya están sumadas. Pero el TWR de todos los clientes con Balanz o IEB cambia el día que se prende el interruptor → se anuncia, no se deploya en silencio |
| 3 | ¿El traspaso de TÍTULOS entra? | **No.** Es un agujero en el VALOR; se cierra por la foto de tenencia, que ya existe |
| 4 | ¿Se toca `OP_TYPE_ALIASES`? | **No.** Reescribe el significado de todos los imports genéricos históricos |
| 5 | ¿Mes degradado → racha parcial o `None`? | **Racha contigua más larga + `cadena_interrumpida` + `meses_excluidos`.** Un número parcial y honesto sirve más que ninguno; lo prohibido es multiplicar salteando el agujero |
| 6 | ¿Las determinísticas exactas se auto-aplican? | **Sí, sólo `pair_id` y `cruce_entre_brokers` con confianza 1,0.** El texto nunca decide solo. Lo del agente, nunca automático |
| 7 | ¿Umbral del agente? | No se puede fijar antes de la Fase 3 y el backtest. Queda como env, no como constante elegida de antemano. **No** auto-aplicar por antigüedad: un caso pendiente para siempre es más honesto que uno aplicado por cansancio |
| 8 | ¿El roster del TWR es el de hoy o el vigente mes a mes? | **Mes a mes.** `_clientes_vigentes` ([advisor_twr.py:16-29](backend/advisor_twr.py:16)) usa el roster de hoy y su propio docstring lo advierte: el cliente revocado desaparece de toda la historia y el retorno del año pasado mejora solo |
| 9 | ¿Qué pasa con la cola de un asesor cuyo tier venció? | Sus casos quedan inaccesibles pero sus resoluciones aplicadas siguen dentro del número. Sin recomendación fuerte; decidirlo antes de la Fase 6 |
