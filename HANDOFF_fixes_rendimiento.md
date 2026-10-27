# HANDOFF — fixes del rendimiento CERTERO y ESTIMADO desde el CSV

> Implementa `AUDIT_rendimiento_desde_csv_2026-10-27.md` (H1–H14). Rama:
> `claude/affectionate-wright-uvbnbl`. **Nada mergeado a `main`.** Una fase = un commit
> (Fase A son cuatro), para poder aceptar, revertir o separar cada una.
>
> Hecho en la nube, **sin la copia de producción y sin red a Yahoo/data912**: todo lo
> medido es sobre el mercado inventado del arnés (`audit/rendimiento_csv/`), donde la
> verdad se conoce exacta. Lo de producción queda con los comandos para la Mac (al final).

## ⚠️ Regresión encontrada después — NO mergear la Fase A así

Analizando la plantilla de Rendi (`AUDIT_plantilla_rendi_2026-10-27.md`, PL2) apareció
un caso que la comparación de esta rama no medía: **cuentas SIN foto de tenencia**. La
Fase A hizo que el Certero confíe en la historia reconstruida, pero sin foto nada la
verifica (la caja se compara contra `positions`, que sale del mismo archivo). Con el
archivo completo da exacto; si le falta algo, el Certero ahora publica números muy
errados donde antes no publicaba o medía sólo desde el cron:

| sin foto, al archivo le falta | código original (Certero) | esta rama (Certero) | verdad |
|---|---|---|---|
| plantilla sin depósitos | +45,5 % desde ago-26 (verdad +25,2) | **+1.841 %** desde abr-24 | +157,8 % |
| plantilla sin una venta | +33,6 % desde ago-26 (verdad +25,2) | **+193,2 %** | +141,3 % |
| Balanz sin una venta (antes del cron) | sin número | **+162,2 %** | +121,4 % |
| plantilla desde 2025 | sin número | **+43,9 %** | +87,6 % |

La comparación de abajo medía el resultado DESPUÉS de subir la foto, y por eso no lo
vio. **Arreglo propuesto (decisión del dueño):** una foto reconstruida es certera sólo
si una foto de tenencia la confirmó; sin foto, la historia va al Estimado y el Certero
mide desde el cron, como antes. Con foto se conserva toda la mejora.

## Estado

| fase | hallazgos | commit | estado |
|---|---|---|---|
| 0 | foto del ANTES (`_comparacion/antes/`) | `1e1f785` | ✅ |
| A | H1, H3, H4, H5-b, H13, H14, foto que contradice | `c458f47` → `0d4e2f6` | ✅ |
| B | H6 (decisión del dueño: precio real donde lo hay, costo donde no) | `e45f30e` | ✅ |
| C | H7 (lectores) | `a90959b` | ✅ (meses del calendario: decisión pendiente) |
| D | H8, H11, comisión IEB | `682f41b` | ✅ · H5-a, H9, H10: propuestas / falta dato |

`_comparacion/` NO se commitea (tendría `prod.json` con datos de usuarios).

## ¿Quedó más certero? Antes / después / verdad

Mismo inversor inventado (aportes en pesos y dólares, CEDEARs, acciones, un bono con
cupones, dólar MEP, ventas, un retiro), escrito en el formato real de cada broker, subido
por la pantalla de importación, con su foto de tenencia y el cron día por día.
"Verdad" = el rendimiento ponderado por tiempo calculado a mano, en la misma ventana que
mide Rendi después.

| caso | broker | modo | antes | después | verdad | desde |
|---|---|---|---|---|---|---|
| S0 · historia completa | Balanz | Certero | +25,2 % (sólo desde ago-26) | **+141,4 %** | +141,3 % | ene-24 |
| S0 · historia completa | Balanz | Estimado | +135,5 % | **+141,4 %** | +141,3 % | ene-24 |
| S0 · historia completa | IEB | Certero | +25,2 % (sólo desde ago-26) | **+141,3 %** | +141,3 % | ene-24 |
| S0 · historia completa | IEB | Estimado | +123,5 % | **+141,3 %** | +141,3 % | ene-24 |
| S0 · historia completa | genérico | Certero | +25,2 % (sólo desde ago-26) | **+141,4 %** | +141,3 % | ene-24 |
| S0 · historia completa | genérico | Estimado | +135,6 % | **+141,4 %** | +141,3 % | ene-24 |
| S1 · el archivo arranca en 2025 | Balanz | Certero | +70,6 % (verdad +25,5) | **+25,2 %** | +25,2 % | ago-26 |
| S1 · el archivo arranca en 2025 | Balanz | Estimado | +82,4 % | +74,0 % | +87,6 % | ene-25 |
| S1 · el archivo arranca en 2025 | IEB | Certero | sin número | **+25,2 %** | +25,2 % | ago-26 |
| S1 · el archivo arranca en 2025 | IEB | Estimado | +25,2 % | +25,2 % | +25,2 % | ago-26 |
| S2 · falta una venta | Balanz | Certero | +25,2 % | +25,2 % | +25,2 % | ago-26 |
| S2 · falta una venta | Balanz | Estimado | +166,6 % | +131,3 % | +141,3 % | ene-24 |
| S2 · falta una venta | IEB | Certero | +25,2 % | +25,2 % | +25,2 % | ago-26 |
| S2 · falta una venta | IEB | Estimado | +147,6 % | +131,2 % ⚠️ | +141,3 % | ene-24 |
| S3 · títulos traídos de otro broker | Balanz | Certero | +24,7 % | +24,7 % | +24,7 % | ago-26 |
| S3 · títulos traídos de otro broker | Balanz | Estimado | +134,5 % | +140,4 % ⚠️ | +137,6 % | ene-24 |
| S3 · títulos traídos de otro broker | IEB | Certero | +24,7 % | +24,7 % | +24,7 % | ago-26 |
| S3 · títulos traídos de otro broker | IEB | Estimado | +122,5 % | +140,4 % ⚠️ | +137,6 % | ene-24 |
| S4 · faltan los cupones | Balanz | Certero | +25,2 % | +25,2 % | +25,2 % | ago-26 |
| S4 · faltan los cupones | Balanz | Estimado | +125,3 % | +131,4 % | +141,3 % | ene-24 |
| S4 · faltan los cupones | IEB | Certero | +25,2 % | +25,2 % | +25,2 % | ago-26 |
| S4 · faltan los cupones | IEB | Estimado | +125,3 % | +131,4 % | +141,3 % | ene-24 |
| S5 · movimientos después de la foto | Balanz | Certero | +18,9 % (sólo desde ago-26) | **+141,5 %** | +141,4 % | ene-24 |
| S5 · movimientos después de la foto | Balanz | Estimado | +131,3 % | **+141,5 %** | +141,4 % | ene-24 |
| S5 · movimientos después de la foto | IEB | Certero | +18,9 % (sólo desde ago-26) | **+141,4 %** | +141,4 % | ene-24 |
| S5 · movimientos después de la foto | IEB | Estimado | +119,5 % | **+141,4 %** | +141,4 % | ene-24 |

Script: `comparar_antes_despues.py _comparacion/antes _comparacion/despues_faseD` →
**17 mejoras, 1 regresión**. Otros instrumentos del arnés:

- **Lectores** (Métricas, Metas, Reportes del año, Wrapped, IA) coinciden en los tres casos
  y ninguno publica contable en Certero. **Wrapped 2025: Balanz 40,16 % · IEB 40,18 % ·
  verdad 40,16 %** (antes 27,2 % y 1,5 %). En S1 Certero, "—" (antes "+0,0 %").
- **Pesos relativos** (el aporte de US$39.000 del 2 de mayo, Schwab): Rendi 9,63 % vs
  verdad 9,78 % (antes 1,2 %).
- **Tabla parser × movimiento** (Cocos, IOL, PPI, Inviu, Schwab): idéntica al antes.

### Veredicto en una línea

- **Certero:** con el archivo completo mide toda la historia importada con error de
  0,0–0,1 pp (antes medía sólo desde que arrancó el cron); con un archivo incompleto
  que la foto desmiente, mide desde la foto, exacto, o no publica. **Pero sin foto,
  con un archivo incompleto, inventa** (ver la regresión de arriba).
- **Estimado:** el mismo inversor da el mismo número en los tres brokers y, con el
  archivo completo, coincide con la verdad; cuando al archivo le falta algo (una venta,
  los cupones) queda ~10 pp abajo, y con títulos traídos de otro broker ~3 pp arriba.

### Las dos cosas que el script marca, explicadas

1. **IEB · S2 · Estimado "regresión" (error 6,2 → 10,1 pp).** Antes IEB tenía dos errores
   que se compensaban (perdía dividendos en dólares y el Estimado sumaba de golpe la
   ganancia no vendida); ahora IEB da lo mismo que Balanz (131,2 vs 131,3). Los dos
   quedan 10 pp abajo por la venta que el archivo no trae (H9-a): Rendi no puede
   adivinarla. **Necesita tu OK por escrito** (regla del prompt).
2. **S3 · Estimado 2,8 pp ARRIBA de la verdad** (criterio de salida B: nunca más de
   1 pp arriba). No es un sesgo para arriba: el archivo no trae los títulos que vinieron
   de otro broker, así que la historia mide la cartera sin ellos, y esa cartera rindió
   un poco más (+140,4 % es casi lo mismo que la verdad SIN esos títulos, +141,3 %).
   Se arregla sólo con el dato (H9-d). **Necesita tu OK.**

## Fase A — el Certero mide la historia

Causa raíz de cada uno, del síntoma al eslabón (CLAUDE.md, "arreglar el proceso"):

- **H1** — `backfill_historical_mtm._tenencia_no_vista` contaba como "lote que no veo"
  cada cobro (dividendo, cupón, amortización), conversión, interés de PF y futuro.
  Fix en el origen: `_no_es_un_lote(op_type)`, que reusa
  `cobros_bonos.es_cobro_de_renta` y `realized_pnl.es_conversion` (no una lista nueva).
- **H3** — los bonos iban siempre al costo ("data912 es live-only"). data912 tiene velas
  (`/historical/bonds/<ticker>`): `_cierres_renta_fija` / `_velas_renta_fija`, con la
  unidad (por 1 o por 100) decidida con la misma regla que el precio vivo.
- **H14 (nuevo)** — la historia valía "contabilidad + no realizado": la caja y el costo
  en pesos no se devaluaban (2025 daba +49,9 % contra +40,2 %). Ahora se valúa COMO EL
  CRON: tenencia desde los lotes (`_lotes_por_fecha`), caja por moneda reproducida y
  verificada contra la de hoy (`_caja_por_fecha`, `_verificar_caja`), pesos al MEP de la
  fecha. Si la caja no verifica y hay pesos, la foto no es afirmable (base `parcial`).
- **H4** — `twr._primer_apto` apagaba la contabilidad en la primera foto apta (podía ser
  una reconstrucción); ahora exige `MEDICION` (la primera del cron).
- **H5-b** — `costura_no_cierra` mide `1 + dietz` (antes `v1/(v0+flujo)`).
- **H13** — cada aporte pesaba como si hubiera entrado a mitad de mes: `dietz` recibe la
  ponderación por días (`flujos_fechados`, `flujo_ponderado`) en las tres cadenas de
  `curva_indexada`, y la reconstrucción escribe una foto el día antes de cada aporte
  material (≥ 5 %).
- **Foto que contradice** — lo anterior a una foto de tenencia que corrigió el archivo en
  más de 0,5 % no es certero (`_foto_que_contradice`).
- `VERSION_RECONSTRUCCION` en la huella: cada cuenta se rehace sola con la regla nueva.
- No se tocó `twr.py` `publicable = len(con_legs) == 1 and not partida` (decisión 2).

Tests: `tests/test_rendimiento_desde_el_csv.py` (camino de producción, contra la verdad);
mutaciones H1, H3, H14, H13, H13-foto, H5-b, H4 y foto → todas rojas.

## Fase B — el Estimado es una reconstrucción (H6)

- **Base nueva `parcial`** (`twr.VALUADO_PARCIAL`): reconstrucción con cobertura < 90 % o
  sin la regla del cron. La conocen los que deciden por base: `base_de`,
  `base_y_apto_para` (los 4 escritores), `bases_de_serie`, `aptos_de_serie`,
  `estampar_base`, `marcar_reconstrucciones_superadas`, `serie_medible`,
  `curva_indexada`, y en el frontend `insightsModel.js` (punta del acumulado) e
  `Insights.jsx` (resolución del gráfico). Las filas viejas se re-estampan en el worker
  de arranque (`reestampar_reconstrucciones_parciales`). `base` es texto libre:
  `schema_pg.sql` no cambia.
- **La cadena del Estimado encadena sólo puntos SEGUIDOS de la misma base** (antes: ancla
  por base, y mercado → parcial → mercado contaba el período del medio dos veces). Un
  cambio de base es un traspaso: no mide retorno, arrastra el tipo de cambio y tiene que
  cerrar (×3).
- **En Estimado el silencio de la cadena certera ya no corta la serie** si el estimado
  tiene puntos en el medio (un bono sin precio histórico). Certero, igual que antes.
- **La pantalla**: chip "Reconstruido · 71 % a precio real", KPI, toggle, leyenda e
  informe mensual (`reporting/builder.py`). `cobertura_estimado` se pondera por TIEMPO.
  "Sólo se mueve cuando vendés" queda sólo si una parte es contabilidad pura
  (`excluye_no_realizado`). El Estimado sigue sin drawdown ni pico.
- Tests: `tests/test_estimado_desde_el_csv.py` (bono sin velas en data912) con 5
  mutaciones; frontend `insightsModel.test.js` e `InsightsKpiStrip.render.test.jsx` con 2.
  Vitest: 231 archivos / 3.737 tests en verde (+2 pendientes, como antes).
- Ejemplo del bono sin precio histórico: Estimado +103 % contra +141 % de verdad, con
  "71 % a precio real" en pantalla: la diferencia es la suba del bono, que quedó al costo.
  Es exactamente la regla elegida; el Certero no publica (hueco en el medio).

## Fase C — los lectores (H7)

- `rendimiento_publicable` en Certero no cae a la contabilidad (Wrapped, IA).
- `rendimientos_mensuales` (mejor/peor mes de la IA y del Wrapped): ídem.
- El año arranca en el cierre del año anterior: `reporting.builder.inicio_de_ventana`,
  la regla que Reportes ya usaba, ahora en un solo lugar para Reportes, Wrapped e IA de
  Reportes. Era la causa del Wrapped 2025 en 29 % con la verdad en 40,2 %.
- Reportes del año en Certero (vista "todos los brokers"): sin la composición contable;
  si el motor midió una parte, lo dice ("a precio real lo medimos desde el dd/mm/aaaa").
- IA de Reportes: `vs_sp500_pp` = año − S&P en la misma ventana (`bench_pct_entre`).
- Tests: `tests/test_lectores_desde_el_csv.py` con 5 mutaciones. Los tests que fijaban
  la composición contable del año pasan a modo Estimado con la aserción de Certero al
  lado (14 archivos; ver el commit).

**Decisión pendiente (no la tomé):** en Certero, los **meses** del calendario de Reportes
y la vista **por broker** siguen mostrando la contabilidad etiquetada. Esconderla es
coherente con el modo, pero el propio código mide que en julio sólo 12 de 670 usuarios
tenían los dos bordes a mercado: casi todos se quedarían sin calendario en Certero.
Medilo con la copia de prod antes de decidir.

## Fase D — el import y la foto

- **H8** — la foto compara la caja a SU fecha: la de hoy menos lo que movieron, en ese
  par de brokers y moneda, las filas posteriores. S5: ajuste $1.153.898 → $258 (Balanz),
  $1.108.538 → $262 (IEB) (lo que queda es el redondeo de la foto, igual que en S0).
- **H11** — había dos copias de las reglas de caja; ahora una:
  `ledger_replay.movimientos_de_caja` (venta = cantidad × precio reconciliado −
  comisión, como el importador). La usan `cash_en`, la reconstrucción y la foto. Un test
  verifica que el replay da exactamente la caja que dejó el importador (Balanz e IEB).
- **IEB comisión** — la comisión de una venta viene adentro del importe; el parser la
  pasa en `comisiones` (sólo si cantidad × precio ≈ importe; con un bono por 100 no).
- Tests: `tests/test_import_y_foto_desde_el_csv.py` con 3 mutaciones.

**Propuestas (no implementadas, decisión tuya o falta un dato):**

- **H5-a** — una venta de algo comprado antes del export mete plata sin pasar por el
  capital. Propuesta: registrarlo como "aporte en especie" fechado el día de la venta
  (o el primer día del archivo), con un `admin_repair_aportes_en_especie(apply=False)`
  para lo existente. Primero medí cuántos son (SQL abajo).
- **H9-a/b** — una venta o cupones que el archivo no trae: hoy la foto los vuelve un
  "aporte" en silencio. Propuesta de pantalla al confirmar la foto: "Faltan $X en tu caja
  respecto de tus movimientos: ¿es un aporte que no cargaste, o un cobro/venta que el
  archivo no trae?" — y según la respuesta, DEPÓSITO o DIVIDENDO/VENTA.
- **H9-c** — foto de IEB con bonos: **necesito un portafolio real de IEB que tenga
  bonos** para confirmar si viene por 100 VN antes de tocar `importing/tenencia.py`.
- **H10** — dividendos de IEB con `Divisa='OTHER'`: en tu archivo son dólares; según el
  HANDOFF_reconstructor, para el uid 870 son pesos. Medí la distribución (SQL abajo)
  antes de elegir la regla.

## Lugares con el mismo cálculo (regla de propagación)

| qué | dónde vive | arreglado |
|---|---|---|
| base y apto de una foto | `twr.base_y_apto_para` ← cron, reconstrucción, import, migración | los 4 (una función) |
| cadena del Estimado | `twr.curva_indexada` (número) y `twr.serie_medible` (guardas) | los 2 |
| rendimiento acumulado | `twr.rendimiento_publicable` ← Wrapped, IA ×5 | todos (una función) |
| rendimiento de cada mes | `twr.rendimientos_mensuales` ← Wrapped, IA ×4 | todos (una función) |
| arranque de un período | `reporting.builder.inicio_de_ventana` ← Reportes año, Wrapped, IA Reportes | los 3. **No**: IA de insights/dashboard/evolución (ventanas móviles de 30 días / N meses, las mismas que pide Métricas) |
| reglas de caja | `ledger_replay.movimientos_de_caja` ← `cash_en`, reconstrucción, foto | los 3. El productor sigue siendo el importador (`persister`, `rebuild`): si cambia su regla, el test del replay se pone rojo |
| texto "no cuenta lo no vendido" | chip, KPI, 2 toggles, leyenda, informe mensual, prompt IA | todos. **No**: `frontend/src/utils/fixtures/compraYMantieneArs.json` (fixture de test con narrativas viejas) |
| comisión dentro del importe | parser de IEB | sólo IEB: la tabla §4 no la pierde en otros |

## Suite de tests (conjuntos de fallas, no conteos)

- **Antes** (`1e1f785`): 3 fallas — `test_dependencias_declaradas` (falta `pywebpush`
  en esta máquina) y dos de `test_ritmo_de_envio` (ídem).
- **Después de cada fase**: el mismo conjunto. Además `test_velas_diarias::
  test_sin_datos_queda_anotado_y_va_primero_la_noche_siguiente` falla a veces: también
  en la base sin cambios (1 de 3 corridas), no lo causa este trabajo.
- Frontend (vitest): todo verde.

## 🔴 QUÉ NO VERIFIQUÉ

1. **Nada contra producción** (no hay copia en la nube): ni cuántos usuarios ganan o
   pierden número en cada modo, ni cuánto se mueve cada uno. Es la condición del prompt
   para mergear — correlo en la Mac (abajo).
2. **Red real**: Yahoo, data912 (incluido si `/historical/corp/` existe para ONs) y
   argentinadatos. Todo vino del mercado inventado.
3. **Archivos reales** (`correr_reales.py`): no los tengo; la comisión de IEB la probé
   con un archivo armado igual al real, no con el tuyo.
4. **El re-estampado de las filas viejas a `parcial`** corre en el worker de arranque;
   lo probé en tests, no sobre una base grande.
5. **La pantalla en el browser**: probé los componentes y la lógica (vitest), no el
   dibujo real del chip ni del gráfico.
6. **Brokers sin prueba de punta a punta**: los mismos que la auditoría (Cocos, IOL, PPI,
   Inviu, Schwab, Bull Market, Binance…).
7. **Meses del calendario de Reportes y vista por broker en Certero**: dejados como
   estaban a propósito (decisión pendiente).

## Para correr en la Mac

```bash
cd ~/Documents/trading && git fetch origin claude/affectionate-wright-uvbnbl
git worktree add .claude/worktrees/fixes-rend origin/claude/affectionate-wright-uvbnbl
cd .claude/worktrees/fixes-rend/backend
# copia de prod SIEMPRE en sólo lectura (medir_prod la abre con ?immutable=1)
python3 ../audit/rendimiento_csv/medir_prod.py ~/Downloads/trading-<fecha>.db ../../_comparacion/despues/prod.json
python3 ../audit/rendimiento_csv/correr_reales.py <carpeta-con-tus-exports-reales> ../../_comparacion/despues/reales.json
python3 ../audit/rendimiento_csv/comparar_antes_despues.py ../../_comparacion/antes ../../_comparacion/despues
# H5-a: ventas sin compra previa
sqlite3 'file:<ruta>?immutable=1' "SELECT op_type, COUNT(*), SUM(entry_date IS NULL) FROM operations GROUP BY 1"
# H10: dividendos de IEB con divisa OTHER, por usuario
sqlite3 'file:<ruta>?immutable=1' "SELECT b.user_id, COUNT(*), ROUND(SUM(n.gross_amount),2), ROUND(AVG(n.gross_amount),2) FROM import_normalized_tx n JOIN import_batches b ON b.id=n.batch_id WHERE b.status='confirmed' AND n.notes LIKE '%divisa=OTHER%' GROUP BY 1"
```
Para el "antes" de producción, la misma corrida sobre `1e1f785`
(`.claude/worktrees/antes`). Cuando termines: `git worktree remove` de las dos copias.
