# FIXES — El rendimiento CERTERO y ESTIMADO desde el CSV

Sos el chat IMPLEMENTADOR. La auditoría está hecha y medida: **`AUDIT_rendimiento_desde_csv_2026-10-27.md`**
(rama `claude/modest-mccarthy-4nsncl`). Leela entera antes de tocar nada: cada hallazgo (H1–H12) tiene el
eslabón con `archivo:línea`, el mecanismo medido y el arreglo propuesto. Este prompt dice **en qué orden**, **qué
decidió el dueño** y **cómo se prueba que quedó bien**. No repite el detalle de la auditoría.

Leé también `CLAUDE.md` (raíz) y respetá sus tres reglas: arreglar en el eslabón donde nace (no donde se ve),
listar TODOS los call sites del mismo patrón, y que el test atraviese el mismo camino que producción.

---

## 0 · Dónde trabajar

- **En la Mac del dueño, no en la nube.** Acá está la copia de producción (`~/Downloads/trading-*.db`, la más
  nueva) y hay red a Yahoo/data912/argentinadatos, que H3 necesita. En la nube no hay ninguna de las dos.
- Copia propia:
  ```bash
  cd ~/Documents/trading && git fetch origin
  git worktree add -b fix/rendimiento-csv .claude/worktrees/fix-rendimiento origin/main
  cd .claude/worktrees/fix-rendimiento
  git merge origin/claude/modest-mccarthy-4nsncl   # trae el informe + audit/rendimiento_csv (sólo docs y scripts)
  ```
- ❌ No commitees a `main` ni mergees: mergear a `main` ES deployar. Un PR por fase; el dueño decide.
- La base de producción SIEMPRE en sólo lectura: `sqlite3.connect('file:<ruta>?immutable=1', uri=True)`. Para
  cualquier paso que escriba (reconstruir, estampar), trabajá sobre una COPIA dentro de tu worktree.
- Guardá avance en la rama al cerrar cada fase, con un `HANDOFF_fixes_rendimiento.md` que diga qué quedó hecho
  y qué falta, para poder retomar en otra sesión.

## 1 · Lo que decidió el dueño (2026-10-27) — no lo reabras

1. **Estimado = "precio real donde lo hay, costo donde no".** No es "sólo lo vendido". La pantalla tiene que dejar
   de decir "no cuenta lo que todavía no vendiste" y pasar a decir, en castellano simple, que es una
   reconstrucción: precio real de lo que pudimos valuar, costo de lo que no (bonos/FCI sin precio histórico), con
   el % de cobertura.
2. **Certero con un hueco en el medio de la historia = sin número, como hoy.** `twr.py:3252`
   (`publicable = len(con_legs) == 1 and not partida`) **NO se toca**. Consecuencia medida que tenés que manejar:
   arreglar H1 solo le borra el Certero a 12 de 13 escenarios de prueba y a la cuenta real Balanz A (aparecen meses
   aptos aislados antes de un hueco). Por eso H1 va junto con H3 (precio histórico de bonos), y antes de mergear se
   mide en producción cuántos usuarios ganan y cuántos pierden el número (§4).

## 2 · Instrumento de verificación (ya existe — usalo, no lo reinventes)

`audit/rendimiento_csv/` corre usuarios por el camino de producción con un mercado inventado (verdad conocida):

| script | qué hace |
|---|---|
| `correr_escenarios.py <salida> balanz ieb generico` | historia inventada × 6 discrepancias vs verdad (Certero/Estimado) |
| `lectores.py <salida> balanz:S0_completo ...` | qué publica cada lector (Métricas, Metas, Reportes, Wrapped, IA) en los dos modos |
| `tabla_parsers.py <salida>` | el mismo movimiento por la vista previa de cada parser |
| `correr_reales.py <_datos> <salida>` | los archivos reales del dueño (en `_datos/`, ver `HANDOFF_auditoria_rendimiento_csv.md`) |
| `medir_prod.py <copia prod> [salida]` | sólo lectura: cobertura por modo, Estimado−Certero, y cuántos usuarios tienen cada señal H1…H7 |

⚠️ El arnés bloquea la red a propósito (para que la verdad sea conocida). Las salidas "de antes" están en
`audit/rendimiento_csv/salidas/` — son tu línea base. **Corré `medir_prod.py` sobre la copia de prod ANTES de
cambiar nada y guardá la salida**: es el "antes" del A/B.

**Los tests nuevos van en `backend/tests/`** y tienen que pasar por el mismo camino: subida HTTP
(`/api/imports/preview` → `/confirm`), reconstrucción (`backfill_user`), cron (`take_snapshot_for_user`) y lector.
Copiá a `backend/tests/` lo que necesites de `mercado.py`/`historia.py`/`generadores.py` y parcheá la red como
ya lo hacen `tests/test_reconstruccion_sigue_a_la_contabilidad.py` y `tests/test_certero_contra_el_cron.py`. Un test
que llame al persister o a `twr` directo, salteándose el import, no cuenta.

**Gate de la suite** (`cd backend && python3 -m pytest -q`, ~13 min): compará el CONJUNTO de nombres de tests que
fallan contra `origin/main` limpio en la misma máquina. Diferencia vacía o explicada. Nunca compares conteos.

## 3 · Fases, en orden

Cada fase: arreglo en el origen → grep de todos los call sites (listalos en el PR: cuáles tocaste y por qué no los
otros) → test por el camino de producción que falle ANTES y pase DESPUÉS → mutación (revertí el arreglo y mostrá que
el test se pone rojo) → arnés → suite.

### Fase A · Certero: que la historia reconstruida cuente (H1 + H3 + H4 + costura de H5)

1. **H1** — `scripts/backfill_historical_mtm.py:276-300`: el loop de `operations` de `_tenencia_no_vista` no puede
   tomar un cobro como tenencia abierta. Antes de codear, en la copia de prod:
   `SELECT op_type, COUNT(*), SUM(entry_date IS NULL) FROM operations GROUP BY 1` — que el filtro cubra todos los
   tipos de cobro que existan, no sólo los tres que vi. Grep de otros lectores que traten una fila de
   `operations` sin `entry_date` como lote (`grep -rn "FROM operations" backend --include=*.py | grep -v tests`).
2. **H3** — darle precio histórico a la renta fija en la reconstrucción
   (`backfill_historical_mtm.py:117` hoy la saltea). Medí primero qué fuente tiene historia real: `velas_diarias`
   (¿guarda bonos?), la serie `.BA` de Yahoo (¿existe para AL30/GD30/AE38/GD38/ONs?), los precios del cron, y los
   precios de las propias operaciones del usuario. `price_history.py` existe y no lo usa nadie: decidí si es la
   pieza a usar o se borra. FCI: ¿`fci_prices` tiene historia? Lo que quede sin precio sigue al costo y baja la
   cobertura, como hoy.
3. **H4** — `twr.py:2483` `_primer_apto`: que el corte de la contabilidad sea la primera **medición del cron**
   (`clase == MEDICION`), que es lo que dice el comentario de arriba.
4. **H5-b** — `twr.py:1697` `costura_no_cierra`: el aporte de la siembra de la foto no puede diluir la guarda.
   Diseñala con tests: el caso medido (v0 = 2.777, v1 = 22.030, flujo = 15.445, 4 días) tiene que cortarse, y una
   costura sana con aporte grande (escenarios S0 y S3) tiene que pasar.
5. **Las fotos ya escritas no se arreglan solas.** `mtm_backfill` está guardado en `snapshots`: hay que volver a
   reconstruir a los usuarios (buscá el camino de admin que ya existe, p. ej. `backfill_summary`/el panel de
   reconstrucción) y verificar que ningún escritor POSTERIOR (`marcar_reconstrucciones_superadas`, el cron,
   `estampar_base`) lo pise.

**Criterio de salida A** (arnés, mercado inventado): en Balanz S0 e IEB S0 ninguna foto `mtm_backfill` queda con
`mtm_coverage` NULL por un cobro; con H3, el Certero mide desde 2024-01-31 con error < 1 pp contra la verdad; en S1 el
Certero da error < 1 pp **o** no publica (nunca +45 pp). **En prod** (sobre una copia reconstruida con el código
nuevo; si son demasiados usuarios para Yahoo, una muestra de 100 al azar + los peores): cuántos usuarios tienen
Certero antes/después, y cuántos meses mide cada uno. **Si alguien pierde el número, listalos con su motivo y
mostráselos al dueño antes de abrir el PR.**

### Fase B · Estimado: una sola regla, la que eligió el dueño (H6 + H4 en su lado)

1. Hoy `twr.base_de` (`twr.py:343`) llama `'costo'` a dos cosas distintas: la foto contable pura (realineada a
   `capital_final`, `twr.py:2547`) y la reconstrucción con cobertura < 0,90, cuyo valor
   (`backfill_historical_mtm.py:802`, `cost + total_unreal`) ya lleva precio de mercado. La cadena del Estimado
   encadena por base (`twr.py:3113`) y por eso un leg resta una valuación de una regla contra otra (IEB S0: +36 % en
   un trimestre).
2. Con la decisión del dueño, la reconstrucción parcial es **"mercado donde hay precio, costo donde no"** y tiene
   que ser su propia base (o sea: una cadena que nunca se resta contra la contabilidad pura); el paso de una base a
   otra es un traspaso que no mide retorno, como ya hace el código. La foto contable pura sólo queda para quien no
   tiene reconstrucción.
3. Todos los que deciden por base: `base_y_apto_para` (los 4 escritores), `estampar_base` (las filas viejas hay que
   re-estamparlas, no sólo las faltantes), `clasificar_fila`, `serie_medible`, `curva_indexada`, y los lectores que
   leen `base`/`base_del_twr`/`excluye_no_realizado` (grep en `backend/` y `frontend/src/`). `schema_pg.sql` es
   GENERADO por `scripts/mkschema.py`: si hay un CHECK sobre `base`, cambiá el generador.
4. El texto de pantalla del Estimado (frontend: buscá dónde se arma "no cuenta lo no realizado" /
   `excluye_no_realizado`) pasa a la definición nueva, con la cobertura. Seguí `frontend/CLAUDE.md`.
5. Lo que el Estimado nunca publica sigue igual: drawdown, pico, volatilidad, rachas (`PROMPT_fase2_toggle.md` §2).

**Criterio de salida B** (arnés): mismo inversor en Balanz, IEB y genérico → mismo Estimado ±1 pp en S0; el Estimado
nunca queda arriba del TWR verdadero (+1 pp de tolerancia) en S0–S5 (hoy S2 da +25 pp); ningún leg de la cadena une dos
fotos de reglas distintas (testealo sobre los legs, no sobre el total); Wrapped 2025 igual entre brokers ±1 pp.

### Fase C · Lectores que no dicen lo mismo (H7)

1. `twr.py:814`: en modo Certero, `rendimiento_publicable` no cae a la contabilidad — sin número y con motivo. Lo
   usan Wrapped, `reporting/builder.py` y los builders de la IA (`ai/builders/insights.py`, `reports.py`,
   `insights_evolution.py`, `dashboard.py`): revisá qué muestra cada uno cuando no hay número.
2. Wrapped: nunca 0,0 % cuando no hubo legs (escenario S1, 2025).
3. Reportes del año (`/api/reports/period/year/2026`): hoy `basis_incomparable` y sin número en los dos modos
   mientras Métricas publica 2026. Encontrá por qué y que publique lo que el motor mide para esa ventana (o diga
   por qué no).
4. Pendiente conocido: `ai/builders/reports.py:136/182` (`vs_sp500_pp`) compara la contabilidad mensual contra el
   S&P con fórmula propia → que use `performance.bench_pct_entre` sobre la ventana del número.

**Criterio de salida C:** `lectores.py` sobre Balanz S0, Balanz S1 e IEB S0: Métricas, Metas, Reportes del año, Wrapped
y la IA publican el mismo número sobre la misma ventana, o "—" con motivo; ninguno publica contable en modo Certero.

### Fase D · El import y la foto de tenencia

1. **H8** — `main.py:42908/42936`: el ajuste de caja de la foto compara contra la caja de HOY. Proyectala a la fecha
   de la foto, igual que ya se proyectan las tenencias (`_qty_a_fecha` / `importing/proyeccion`). Hay tres
   implementaciones de "qué tenía en tal fecha" (`ledger_replay`, `_holdings_asof`, `proyeccion`, H11): no agregues
   una cuarta; medí si dan distinto y usá una.
   Criterio: escenario S5 sin "Ajuste de cash" cuando la foto coincide con la historia a su fecha.
2. **H5-a** — una venta cuyo lote se compró antes de la ventana del export mete plata en `positions` sin pasar por
   `capital_final`. Medí primero en la copia de prod cuántos usuarios tienen ventas sin compra previa. Proponé al
   dueño cómo registrar el aporte en especie que eso implica antes de tocar la contabilidad (es una tabla de plata:
   patrón `admin_repair_*` con `apply=False` por defecto si hay que reparar lo existente).
3. **H10** — IEB, `importing/parsers/ieb.py:431`: dividendo con `Divisa='OTHER'`. En el archivo real son dólares
   (22 filas, US$26,93); el HANDOFF_reconstructor dice que para el uid 870 son pesos. Medí en prod la distribución
   antes de elegir la regla; nada de un umbral fijo en dólares sobre una columna en pesos.
4. **IEB comisión** — el parser arma el importe con cantidad × precio y pierde la comisión que trae "Importe ARS"
   (archivo real: STNE 23 × 8.660 = 199.180 vs importe 199.300,5). Después la foto la repone como RETIRO.
5. **H9-c** — foto de IEB con bonos: `importing/tenencia.py:1752` siembra al PPP como si fuera por 1 VN. **Pedile al
   dueño un portafolio real de IEB que tenga bonos** antes de tocarlo; si se confirma que viene por 100, normalizalo
   en el parser de la foto con el mismo criterio que la actividad.
6. **H9-a/b** (venta o cupones que el archivo no trae): Rendi no puede adivinarlos; hoy la foto los convierte en
   silencio en "aporte". No lo arregles por tu cuenta: proponé al dueño qué mostrarle al usuario ("faltan $X en tu
   caja: ¿aporte o cobro?").

## 4 · A/B contra producción (obligatorio antes de cada PR)

- `medir_prod.py` sobre la copia cruda (antes) y sobre la copia reconstruida/estampada con el código nuevo
  (después). Reportá: usuarios con número por modo (antes/después) y por motivo; meses que mide el Certero
  (mediana y peor caso); Estimado − Certero sobre la misma ventana; y los conteos H1/H4/H5/H6/H7, que tienen que
  bajar a 0 o explicarse uno por uno.
- Por cada cambio que mueva el número de alguien: mediana y peor caso de la diferencia en pp, con un uid de ejemplo.
- 🔴 Nunca sumes plata entre monedas; reportá el máximo de una fila al lado de cualquier suma.

## 5 · Qué entregar

1. Un PR por fase contra `main` (sin mergear), cada uno con: archivos y líneas, la lista de call sites, el test por
   el camino de producción + su mutación, la salida del arnés antes/después, el A/B de prod y el conjunto de tests
   que fallan antes/después.
2. La auditoría actualizada: en `AUDIT_rendimiento_desde_csv_2026-10-27.md`, cada hallazgo marcado arreglado / no
   arreglado / decidido no arreglar, con el PR.
3. 🔴 **"QUÉ NO VERIFIQUÉ"** al final de cada PR, sin maquillar.
