# HANDOFF — fixes del rendimiento CERTERO y ESTIMADO desde el CSV

> Implementa `AUDIT_rendimiento_desde_csv_2026-10-27.md` (H1–H14). Rama de trabajo:
> `claude/affectionate-wright-uvbnbl`. **Nada mergeado a `main`.** Cada fase es un
> commit (o un grupo) separable para que el dueño decida PR por PR.
>
> Corrido en la nube, **sin la copia de producción ni red a Yahoo/data912**: todo lo
> medido es sobre el mercado inventado del arnés (`audit/rendimiento_csv/`), donde la
> verdad se conoce exacta. Lo de producción queda con los comandos para la Mac (§ Para
> correr en la Mac).

## Estado por fase

| fase | qué | estado |
|---|---|---|
| 0 | foto del ANTES (`_comparacion/antes/`, commit `1e1f785`) | ✅ |
| A | H1, H3, H4, H5-b, H13, H14, foto que contradice | ✅ commits `c458f47` → `0d4e2f6` |
| B | H6: Estimado = precio real donde lo hay, costo donde no | ✅ (ver abajo) |
| C | H7: lectores | en curso |
| D | H8, H10, comisión IEB; H5-a / H9 propuestas | pendiente |

`_comparacion/` NO se commitea (tendría `prod.json` con datos de usuarios).

## Fase A — el Certero mide la historia

**Causa raíz, eslabón por eslabón** (de la pantalla al importador):

- **H1** — `backfill_historical_mtm._tenencia_no_vista` contaba como "lote que no veo"
  cada cobro (dividendo, cupón, amortización), conversión, interés de PF y futuro. Un
  dividendo en dólares de un CEDEAR que vive en la cuenta en pesos dejaba sin cobertura
  TODOS los meses anteriores. Fix en el origen: `_no_es_un_lote(op_type)` (reusa
  `cobros_bonos.es_cobro_de_renta` y `realized_pnl.es_conversion`, no una lista nueva).
- **H3** — la reconstrucción mandaba los bonos siempre al costo ("data912 es
  live-only"). data912 tiene velas históricas (`/historical/bonds/<ticker>`). Fix:
  `_cierres_renta_fija` / `_velas_renta_fija`, con la unidad (por 1 o por 100) decidida
  con la misma regla que el precio vivo.
- **H14 (nuevo, encontrado al arreglar H1+H3)** — la historia valía "contabilidad + no
  realizado": la caja y el costo en pesos no se devaluaban. 2025 daba +49,9 % contra
  +40,2 % real. Fix: la historia se valúa COMO EL CRON — tenencia desde los lotes de
  `positions`/`operations` (`_lotes_por_fecha`), caja por moneda reproducida y
  verificada contra la caja de hoy (`_caja_por_fecha`, `_verificar_caja`), pesos al
  MEP de la fecha. Si la caja no verifica y hay pesos, la foto no es afirmable.
- **H4** — `twr._primer_apto` apagaba la contabilidad en la primera foto apta, que
  podía ser una reconstrucción. Ahora exige `MEDICION` (la primera del cron).
- **H5-b** — `costura_no_cierra` medía `v1/(v0+flujo)` (flujo entero al principio).
  Ahora `1 + dietz`.
- **H13** — cada aporte pesaba como si hubiera entrado a mitad de mes. Ahora
  `dietz(..., ponderado)` con los flujos fechados (`flujos_fechados`,
  `flujo_ponderado`) en las 3 cadenas de `curva_indexada`, y la reconstrucción escribe
  una foto el día anterior a cada aporte material (≥ 5 %).
- **Foto que contradice** — lo anterior a una foto de tenencia que tuvo que corregir el
  archivo en más de 0,5 % no es certero (`_foto_que_contradice`).
- `VERSION_RECONSTRUCCION` en la huella: toda cuenta se rehace con la regla nueva la
  próxima vez que el worker de huellas la mire (no hace falta un backfill a mano).

Call sites de "qué tenía en tal fecha" (H11): la reconstrucción ya no usa
`_holdings_asof` (borrado); usa los lotes, como el cron. `ledger_replay` e
`importing/proyeccion` siguen existiendo — ver Fase D.

## Fase B — el Estimado es una reconstrucción (H6)

Decisión del dueño (no se reabre): **precio real donde lo hay, costo donde no**, y la
pantalla dice el % a precio real en vez de "no cuenta lo que todavía no vendiste".

- **Base nueva `parcial`** (`twr.VALUADO_PARCIAL`): una reconstrucción con cobertura
  < 90 % (o con la regla del cron sin verificar la caja) ya no se mezcla con la
  contabilidad pura en `costo`. `base_de`, `base_y_apto_para`, `bases_de_serie`,
  `aptos_de_serie`, `estampar_base` y `marcar_reconstrucciones_superadas` la conocen;
  `reestampar_reconstrucciones_parciales` re-estampa las filas viejas
  (`mtm_backfill` + costo + con cobertura) en el worker de arranque
  (`main._migrate_estampar_base`). La columna `base` es texto libre: `schema_pg.sql`
  no cambia.
- **La cadena del Estimado encadena sólo puntos SEGUIDOS de la misma base**
  (`curva_indexada` y `serie_medible`). Con el ancla por base, mercado → parcial →
  mercado medía el leg mercado→mercado por ENCIMA del tramo parcial, que también
  encadenaba: el mismo período dos veces. Un cambio de base es un traspaso (no mide
  retorno; sí arrastra el tipo de cambio) y tiene que cerrar (×3).
- **En Estimado, el silencio de la cadena certera ya no corta la serie** si el
  estimado tiene puntos en el medio: con un bono sin precio histórico la cadena certera
  queda vacía años, pero el estimado tiene un punto por mes. En Certero el corte queda
  igual (decisión 2: `twr.py` `publicable = len(con_legs) == 1 and not partida` no se
  tocó).
- **Qué dice la pantalla**: `cobertura_estimado` (ponderada por TIEMPO, no por punto) y
  `excluye_no_realizado` sólo cuando parte del número es contabilidad pura. Chip
  "Reconstruido · 72 % a precio real", KPI, toggle, leyenda y la frase del informe
  mensual (`reporting/builder.py`, nuevo `metrics.excluye_no_realizado`).
- El Estimado sigue sin publicar drawdown ni pico.

<!-- números de la fase B: ver "Antes / después" -->

## Para correr en la Mac (lo que la nube no pudo)

```bash
# copia de prod SIEMPRE en sólo lectura
python3 audit/rendimiento_csv/medir_prod.py ~/Downloads/trading-<fecha>.db _comparacion/despues/prod.json
python3 audit/rendimiento_csv/correr_reales.py
python3 audit/rendimiento_csv/comparar_antes_despues.py _comparacion/antes _comparacion/despues
sqlite3 'file:<ruta>?immutable=1' "SELECT op_type, COUNT(*), SUM(entry_date IS NULL) FROM operations GROUP BY 1"
```
