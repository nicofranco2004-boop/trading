# AUDITORÍA — El rendimiento CERTERO y ESTIMADO, desde el CSV del broker hasta la pantalla

**Fecha:** 2026-10-27 · **Rama:** `claude/modest-mccarthy-4nsncl` (no está en `main`) · **No se arregló nada.**

---

## 0 · Cómo se midió (y qué limita lo medido)

- **No hubo copia de producción.** La sesión corrió en la nube y la copia (`~/Downloads/trading-*.db`) vive en
  la Mac del dueño. Todo número "en usuarios de producción" queda **por medir** con
  `audit/rendimiento_csv/medir_prod.py` (sólo lectura, `?immutable=1`; ver §7).
- **La red a Yahoo, data912 y argentinadatos está bloqueada** en el contenedor (proxy 403). En vez de eso se armó
  un **mercado inventado** (`audit/rendimiento_csv/mercado.py`): precios diarios de CEDEARs, acciones, bonos y
  dólar **blue, MEP y CCL distintos entre sí**. Ventaja: el rendimiento VERDADERO se conoce exacto y el error de
  Rendi se mide en puntos.
- **Mismo camino que producción** (`audit/rendimiento_csv/arnes.py`): subida por HTTP
  `/api/imports/preview` → `/api/imports/confirm` (con TODO su post-proceso) → reconstrucción a mercado en su
  hilo (`backfill_user`) → foto de tenencia por `/api/imports/tenencia/preview` + confirm → **cron real**
  (`snapshots_job.take_snapshot_for_user`) día por día → lectores (`curva_indexada`, `rendimiento_publicable`,
  endpoints de Métricas, Metas, Reportes, Wrapped y los builders de la IA). Lo único reemplazado es la red.
- **Archivos usados:**
  - Los 4 reales del dueño: Balanz movimientos (2 cuentas, "A" y "B"), IEB "toda la actividad" + IEB
    "Portafolio". No se subieron al repo (datos personales).
  - Una **historia de inversor inventada** (`historia.py`, 2024-01 → 2026-08: aportes en pesos y dólares,
    CEDEARs, acciones, un bono con cupones, dólar MEP, ventas, retiro) escrita en el formato de cada broker
    (`generadores.py`) + su foto de tenencia, con **6 escenarios de discrepancia** (§2-F).
- **Verdad:** TWR diario exacto en USD (pesos valuados al MEP del día) y la "verdad contable" que el Estimado
  promete (aportes + realizado FIFO, Dietz mensual, sin no realizado).
- **Suite de backend** (`cd backend && python3 -m pytest -q`): 3 fallas, las 3 por el entorno (falta el paquete
  `pywebpush`): `test_dependencias_declaradas::…sin_declarar`, `test_ritmo_de_envio::test_el_push_tiene_tiempo_limite`,
  `test_ritmo_de_envio::test_un_dispositivo_lento_no_corta_el_push_a_los_demas`. Esta auditoría no cambió código.

Reproducir (desde `audit/rendimiento_csv/`):

```bash
python3 correr_escenarios.py salidas/escenarios.json balanz ieb generico   # matriz broker × escenario
python3 lectores.py salidas/lectores2.json balanz:S0_completo balanz:S1_ventana_desde_2025 ieb:S0_completo
python3 tabla_parsers.py salidas/tabla.json                                 # tabla parser × movimiento
python3 correr_reales.py <carpeta _datos> <salida fuera del repo>           # archivos reales del dueño
```

---

## 1 · Resumen para el dueño (una página)

**1. El Certero casi no usa la historia que se importa: mide sólo desde que arrancó el cron.** *(Certero)*
Tres cosas lo frenan a la vez: (a) **cada dividendo o cupón** que cae en la cuenta en dólares mientras el papel
está en la de pesos **anula la confiabilidad de todos los meses anteriores**; (b) los **bonos se valúan siempre al
costo** en la reconstrucción, y con un bono en la cartera ningún mes llega al 90 % de cobertura exigido;
(c) si en algún punto de la historia hay un mes no confiable, **el Certero no publica nada**, aunque los últimos
meses estén perfectos. Medido: en tu Balanz A real se pierden 40 de 51 meses (el Certero mide desde oct-2025);
en la historia inventada, 0 de 31 meses reconstruidos cuentan y el Certero mide 3 meses de 33.
Lo que sí mide, lo mide bien: **error 0,00 pp** en 5 de 6 escenarios.

**2. El Estimado no es lo que la pantalla dice que es.** *(Estimado)*
La pantalla dice "recreado, no cuenta lo que todavía no vendiste". En la práctica mezcla fotos puramente
contables con fotos que **sí** llevan el precio de mercado de lo que se pudo valuar, y como las dos llevan la
misma etiqueta, las encadena: en un solo tramo asienta **de golpe años de ganancia no vendida**. Mismo inversor,
mismo mercado: **Balanz +135 %, IEB +123 %**, cuando su propia definición daría +21,7 % (y la verdad completa es
+141,3 %). El número depende de casualidades (en qué meses hubo cobros). En el Wrapped 2025 el mismo inversor
ve **+27,2 % si es de Balanz y +1,5 % si es de IEB** (verdad: +40,2 %).

**3. Cuando el archivo no trae toda la historia (lo más común), el Certero puede inventar ganancia.** *(los dos)*
Con un export que arranca en 2025, una venta de algo comprado antes mete plata en la cuenta que la contabilidad
no registra. En la unión entre la historia reconstruida y el cron esa plata aparece como rendimiento:
**Certero +70,6 % contra +25,5 % real (+45 pp)**; Estimado +82,4 % contra +36,1 %. La guarda que existe para
esto no salta porque el aporte que agrega la foto "diluye" la cuenta.

**4. La foto de tenencia arregla el presente, no el pasado — y a veces lo empeora.** *(sobre todo Estimado)*
Cuando la foto no coincide con los movimientos, Rendi agrega lo que falta como "aporte + compra", quita lo que
sobra "al costo" y ajusta la caja con un depósito/retiro silencioso. Eso deja bien la cartera de hoy, pero:
- falta una venta → el Estimado queda **+25 pp** arriba (la ganancia de lo que ya no se tenía nunca se revierte);
- faltan los cupones → **−16 pp** (la renta entra como "aporte");
- hay movimientos **posteriores** a la fecha de la foto → el ajuste de caja compara contra la caja **de hoy** y
  crea un **aporte falso** ($1.153.898 en el caso probado);
- IEB: si la foto trae un bono (cotiza por 100 nominales), la siembra lo toma por 1 → **aporte fantasma de
  US$661.902** por un bono de US$6.619 *(probable: tu portafolio real no tiene bonos para confirmarlo)*.

**5. Las pantallas no dicen lo mismo, y en modo Certero aparecen números contables.** *(los dos)*
Métricas, Metas y la IA (dashboard) coinciden entre sí ✔. Pero: el **Wrapped en modo Certero muestra un número
contable** (3,1 % en un año sin ninguna medición real, que subió 40 %) y muestra **0,0 %** en vez de "—" cuando no
hay datos; **Reportes 2026 no muestra número en ningún modo** mientras Métricas sí; y la función central
`rendimiento_publicable` en modo Certero devuelve un número **contable** cuando el motor no mide. Además, IEB
carga los **dividendos en dólares como si fueran pesos** (tu archivo real: 22 dividendos, US$26,93).

---

## 2 · Hallazgos en detalle

Formato de cada uno: síntoma → eslabón donde nace → por qué lo anterior está bien → todos los lugares con el mismo
patrón → impacto medido por modo → arreglo en el origen → test por el camino de producción → riesgo.

### H1 · Los cobros (dividendos/cupones/amortizaciones) anulan la cobertura de los meses anteriores — CONFIRMADO

- **Síntoma.** Fotos `mtm_backfill` con `mtm_coverage = NULL` → `base='costo'`, `apto=0` en todos los meses
  anteriores a un cobro. El Certero no puede usarlas.
- **Eslabón.** `backend/scripts/backfill_historical_mtm.py:276-300` (loop sobre `operations` de
  `_tenencia_no_vista`). Los cobros se guardan en `operations` con `op_type` 'Dividendo'/'Amortización'/'Interés',
  `quantity` = el monto cobrado, y **sin `entry_date` ni `entry_price`** (Balanz A real: 68 de 146 filas). El loop
  los toma como "operación abierta" (sin `entry_date` y con `date` > mes), y como `entry_price` es NULL el costo da 0
  → `afirmable = False` (línea 300) → cobertura `None` → `twr.clasificar_fila` (`twr.py:231`) la vuelve
  `SINTETICO_COSTO`. Sólo se salva el cobro cuyo `(broker, activo)` figura entre lo valuado ese mes: el
  dividendo en dólares de un CEDEAR va al sub-broker "· USD" y el CEDEAR vive en el de pesos, así que **no** se
  salva; en IEB los dividendos no llevan activo (`ieb.py`: `activo` vacío fuera de compras/ventas) y no se salva
  **ninguno**.
- **Por qué lo anterior está bien.** El parser lee bien el cobro (monto, moneda, fecha); el ruteo al "· USD" es
  el diseño (`route_by_currency`); guardar cobros en `operations` es como la casa registra el realizado.
- **Mismo patrón.** El loop de `positions` del mismo `_tenencia_no_vista` (líneas 247-274) ya maneja el
  "sin entry_date"; el de `operations` no distingue trade de cobro. No barrí otros lectores de `operations` que
  traten una fila sin `entry_date` como lote (queda en §6).
- **Impacto medido (Certero).** Archivos reales: Balanz A 40 de 51 meses con cobertura NULL (Certero desde
  2025-10), Balanz B 36 de 38, IEB 8 de 9. Sintético: Balanz 4 de 31, IEB 30 de 31.
  **(Estimado)**: cambia qué fotos son "contables" y cuáles "reconstruidas" → ver H6 y H4.
- **Arreglo en el origen.** Que el loop de `operations` considere sólo cierres de lote (`op_type='Venta'` o filas
  con `entry_date`); un cobro nunca es tenencia abierta. Mejor aún a futuro: que un cobro no pueda confundirse con
  un lote por estructura (columna de tipo explícita que todos los lectores respeten).
- **Test.** Arnés `correr_escenarios.py balanz --esc S0`: después del confirm, ninguna foto `mtm_backfill` anterior
  al dividendo en USD del 2024-05-16 puede tener `mtm_coverage IS NULL`. Contrafáctico ya escrito:
  `arnes.contrafactico_sin_cobros`.
- **Riesgo del arreglo.** **No va solo.** Con H1 arreglado y nada más, Balanz A real y **12 de los 13 escenarios
  inventados pierden el número Certero** (meses con bonos/FCI al costo → hueco → H2), y en 11 de 13 el Estimado pasa
  de ~33 meses a 3 (H4: 135 % → 25 % en Balanz S0). H1 + H2 + H4 van en el mismo cambio.

### H2 · El Certero es todo-o-nada ante un hueco — CONFIRMADO

- **Síntoma.** `curva_indexada(modo='certero')` → `twr=None`, `motivo='serie_partida'` aunque haya un tramo
  reciente medido de punta a punta.
- **Eslabón.** `backend/twr.py:3252` `publicable = (len(con_legs) == 1 and not partida)`. El Estimado, en cambio,
  publica la ventana continua más reciente y la declara (`twr.py` ~3420-3445).
- **Por qué.** El comentario justifica que con hueco "ni el TWR ni el drawdown máximo son afirmables". Es cierto
  para el drawdown máximo; para el TWR de la ventana reciente, declarada en `ventana_desde/hasta`, no.
- **Impacto (Certero).** Balanz A real con H1 arreglado: de +0,37 % (desde oct-25) a **sin número**. Historia
  inventada con H1 arreglado: sin número.
- **Arreglo.** Publicar en Certero el TWR del último tramo continuo con su ventana (como ya hace el Estimado), y
  seguir sin publicar drawdown/pico de toda la historia cuando la serie está partida.
- **Test.** Arnés: Balanz S0 con `contrafactico_sin_cobros` → el Certero debe publicar el último tramo con
  `ventana_desde` = primera foto apta del tramo.
- **Riesgo.** Gente que hoy ve "—" pasa a ver un número de una ventana corta: la pantalla tiene que decir desde
  cuándo mide (el chip ya existe).

### H3 · Los bonos van siempre al costo en la reconstrucción; hay precio histórico que no se usa — CONFIRMADO (diseño) / PLAUSIBLE (disponibilidad)

- **Síntoma.** Con un bono en la cartera, la cobertura reconstruida queda en 53-78 % todos los meses (historia
  inventada) → `base='costo'` → nunca apta.
- **Eslabón.** `scripts/backfill_historical_mtm.py:117` saltea todo ticker que `main._is_data912_bond` reconozca
  ("data912 es live-only → costo histórico"), aunque Yahoo tenga la serie `.BA`.
- **Precio que existe y no se usa.** `backend/price_history.py` (tabla `asset_price_history`), escrita como "el
  prerrequisito de la reconstrucción", **no tiene ningún llamador de producción** (sólo `main.py` crea la tabla).
  `velas_diarias` guarda 3 años de velas de lo que la gente tiene y la reconstrucción no la lee. El cron guarda
  precio diario de bonos desde que el usuario existe. Y el propio CSV trae el precio de cada compra/venta.
- **Impacto (Certero).** Es la causa de que, aun sin H1, ningún mes reconstruido llegue al 90 % con bonos.
- **Arreglo.** Darle a la reconstrucción una fuente histórica para renta fija (velas guardadas / precio del cron /
  serie `.BA` de Yahoo verificada), y si no hay, interpolar desde los precios de las operaciones del propio
  usuario, marcando la cobertura como parcial.
- **No verificado:** si Yahoo tiene hoy la serie de AL30/GD30/GD38 `.BA` (sin red).

### H4 · El Estimado descarta toda la contabilidad posterior a CUALQUIER foto apta — CONFIRMADO

- **Síntoma.** Contrafáctico de H1 sobre la historia inventada: `contable_superado = 30`, Estimado de 135,5 %
  (desde 2024-01-31) a 25,2 % (desde 2026-08-04).
- **Eslabón.** `twr.py:2483` `_primer_apto = next(... for r, a in zip(filas, aptos) if a)`. Toma la primera foto
  apta, **incluida una reconstruida**; el comentario de arriba dice "la contabilidad se apaga en la primera
  MEDICIÓN REAL". El primer mes (antes de comprar el bono) queda 100 % valuado → apto → todo lo contable después
  se descarta.
- **Impacto (Estimado).** Hoy no se ve porque H1 vuelve NULL ese primer mes por casualidad. Arreglar H1 lo destapa.
- **Arreglo.** Que el corte sea la primera **medición del cron** (`clase == MEDICION`), que es lo que el
  comentario promete.
- **Test.** Arnés Balanz S0 con H1 arreglado: `contable_superado == 0` y la ventana del Estimado sigue en 2024-01-31.

### H5 · La costura reconstrucción→cron fabrica ganancia con un export parcial; la guarda no la ve — CONFIRMADO

- **Síntoma.** Escenario S1 (export desde 2025): Certero **+70,56 %** vs verdad **+25,46 %** sobre la misma ventana
  (2026-07-31 → hoy). Estimado +82,37 % vs +36,07 %.
- **Mecanismo (medido).** La venta de AAPL (comprado antes de la ventana) acredita ~US$2.800 en `positions` pero no
  entra a `capital_final`. La foto reconstruida del 31/07 vale `cost + total_unreal`
  (`backfill_historical_mtm.py:802`, contabilidad + no realizado) = US$2.777; el primer cron (04/08) vale
  posiciones × precio + caja = US$22.030; la foto sumó US$15.445 de aportes. Leg de Dietz: +36 % en 4 días.
- **Eslabón (dos).** (1) El valor de la foto reconstruida sale de la contabilidad y el del cron de las posiciones:
  sólo coinciden si `capital_final == costo de la tenencia + caja`, y una venta sin su compra rompe esa
  igualdad. (2) `twr.py:1709` `costura_no_cierra` mide `v1 / (v0 + flujo)` = 22.030 / 18.222 = **1,21 < 1,25**:
  el aporte grande de la siembra entra al denominador y diluye. Sin el aporte, el cociente es **2,37**. Como la
  foto se sube justo cuando el usuario empieza (y arranca el cron), la guarda queda ciega en su caso típico.
- **Mismo patrón.** `importing/invariantes.py` no tiene un chequeo "contabilidad = tenencia al costo + caja"; su
  `check_caja_concilia` (línea 203) sí avisa (S1, S2, S4 dieron `aviso`), pero `invariantes.correr` sólo corre desde
  un endpoint de admin (`main.py:25752`), nunca después de un import.
- **Impacto.** Certero +45 pp (Balanz). En IEB el mismo escenario quedó **sin número** (`medicion_dudosa`) por el
  ×100 del bono (H9-c), o sea que tampoco publicó lo correcto.
- **Arreglo en el origen.** (a) La venta sin compra dentro de la ventana debe registrar el aporte en especie que
  implica (el lote existía antes) para que la contabilidad cuadre con `positions`; (b) la guarda de costura debe
  medir el retorno del leg sin el flujo (`(v1 − flujo) / v0`, o el propio Dietz contra un techo por días).
- **Test.** Arnés `correr_escenarios.py balanz --esc S1`: `|certero − verdad| < 1 pp`, o sin número con motivo.

### H6 · `base='costo'` mezcla dos reglas y el Estimado las encadena — CONFIRMADO

- **Síntoma.** Mismo inversor: Estimado Balanz 135,47 % / IEB 123,46 % / genérico 135,57 %; verdad contable 21,65 %;
  TWR real 141,34 %. En IEB, el tramo 2026-04-30 (15.265, contable) → 2026-07-31 (20.821, casi mercado) suma **+36 % en
  un trimestre**.
- **Eslabón.** `twr.py:343` `base_de`: una RECONSTRUIDA con cobertura < 0,90 → `'costo'`. Pero su `total_value`
  (`backfill_historical_mtm.py:802`, `new_cf = cost + total_unreal`) **incluye el no realizado** de lo que tuvo
  precio. Las fotos con cobertura NULL (H1), en cambio, son `SINTETICO_COSTO` y en Estimado se realinean al
  `capital_final` (`twr.py:2547`). Las dos comparten `base='costo'` y la cadena del Estimado encadena por base
  (`twr.py:3113`) → resta una valuación al costo de una casi a mercado: el "escalón de regla" que la Fase 1 prohibió.
- **Impacto (Estimado).** −18 a +25 pp contra el TWR real y +100 pp contra su propia definición en los 13 casos
  inventados. Wrapped 2025 (usa la misma cadena): Balanz 27,2 %, IEB 1,5 %, verdad 40,2 %.
- **Arreglo.** Una de dos, decidida con el dueño: (a) la reconstrucción con cobertura < 0,90 se escribe **al costo
  puro** (u = 0 en todo) y queda contable de verdad; o (b) se admite que el Estimado es "mercado donde hay precio,
  costo donde no", y entonces la pantalla deja de decir "no cuenta lo no realizado". Hoy no es ninguna de las dos.
- **Test.** Arnés: en S0 los tres brokers deben dar el mismo Estimado (±1 pp); y con (a), cerca de 21,65 %.

### H7 · En modo Certero aparecen números contables; lectores que no coinciden — CONFIRMADO

- **`twr.rendimiento_publicable(modo='certero')`** (`twr.py:814`) cae a `_contable_publicable` cuando el motor no
  mide y devuelve `base='contable'` (S0 antes del cron: 32,06 %, 12 meses, sin ventana). Lo usan Wrapped, IA
  (`ai/builders/insights.py:190`, `reports.py:91`, `insights_evolution.py:78`, `dashboard.py:202`) y
  `reporting/builder.py`.
- **Wrapped 2025** (`/api/wrapped/2025`): Certero 3,08 % en un año sin ninguna medición real (verdad 40,16 %); en el
  escenario S1 publica **0,0 %** (no "—").
- **Reportes 2026** (`/api/reports/period/year/2026`): `basis_incomparable: True`, sin número en los dos modos,
  mientras Métricas y Metas publican 2026.
- **Coinciden ✔:** Métricas (`/api/insights/performance`), Metas (`/api/goals/cagr`) y la IA del dashboard
  (`twr_lifetime_pct`) dan el mismo número y la misma ventana en los dos modos y en los tres casos probados.
- **Arreglo.** En Certero, `rendimiento_publicable` no debe caer a la contabilidad (sin número + motivo). El
  Wrapped no debe publicar 0,0 cuando no hay legs.
- **Pendiente ya conocido, sigue vigente:** `ai/builders/reports.py:136/182` (`vs_sp500_pp`) promedia la
  contabilidad mensual contra el S&P con fórmula propia. No pude medir benchmarks (sin red, el S&P vino vacío).

### H8 · El ajuste de caja de la foto compara contra la caja de HOY — CONFIRMADO

- **Síntoma.** S5 (foto del 03/08 y movimientos hasta el 01/09): DEPÓSITO sintético "Ajuste de cash" de
  **$1.153.898** (Balanz) / **$1.109.000** (IEB) fechado 03/08, que no existió.
- **Eslabón.** `main.py:42908` `_cur_cash` lee la caja actual de `positions` y `main.py:42936` la compara con la caja
  de la foto. Las tenencias sí se proyectan a la fecha de la foto (`_qty_a_fecha`, ~`main.py:42575`); la caja no.
- **Impacto.** La caja de hoy queda mal desde ahí (el cron la valúa: Certero 18,90 % vs 19,53 % real en la ventana
  siguiente) y el aportado queda inflado. Estimado −10 pp (131,3 vs 141,4).
- **Arreglo.** Proyectar también la caja a la fecha de la foto antes de comparar.
- **Test.** Arnés `--esc S5`: no debe existir un "Ajuste de cash" si la foto coincide con la historia a su fecha.

### H9 · La foto corrige el presente pero no el pasado

- **(a) Falta una venta (S2) — CONFIRMADO.** La foto reduce GGAL 400 "a costo" (`transfer_out`, sin flujo) y
  deposita $1.939.974 de caja. La historia reconstruida conserva 2 años de ganancia de 400 GGAL que ya no estaban, y
  el traspaso a la base de mercado no mide retorno → **Estimado +25,21 pp** (Balanz), +6,24 pp (IEB). Certero sin
  error (sólo mide después de la foto).
- **(b) Faltan los cupones (S4) — CONFIRMADO.** El ajuste de caja entra como DEPÓSITO US$850 (aporte) → la renta
  desaparece del rendimiento: **Estimado −16,07 pp** (Balanz) / −15,99 (IEB).
- **(c) IEB, bono en la foto — PLAUSIBLE.** `importing/tenencia.py:1752` siembra al PPP como precio **por 1**. Con el
  bono cotizado por 100 VN (como en la actividad de IEB, causa R3), la siembra del GD38 fue **US$661.902** (real
  US$6.619). El motor lo detectó (`medicion_dudosa`) pero la cartera queda inflada ×100. Tu portafolio real no
  tiene bonos: falta confirmar el formato real.
- **(d) Títulos traídos de otro broker (S3).** Se siembran al precio de la foto; se pierde su rendimiento previo
  (−3,15 pp Estimado). Esperable sin el dato.
- **(e) Siembra al PPP en IEB** (costo del broker en vez de mercado): **no** mueve el % (cae en el traspaso, que no
  se mide); sí cambia el aportado y la "ganancia en $". Descartado como hallazgo de rendimiento.

### H10 · IEB carga los dividendos en dólares como pesos — CONFIRMADO (archivo real)

- **Eslabón.** `importing/parsers/ieb.py:431`: con `Divisa='OTHER'` (el monto viene en la columna "Importe ARS") el
  dividendo queda en ARS. Archivo real: **22 filas, US$26,93** ($0,27 en vez de US$0,27). El propio portafolio de
  IEB muestra esos US$26,93 como "DOLARUSA".
- **Impacto.** ≈0,2 pp en 9 meses en esa cuenta; en la historia inventada, IEB pierde el dividendo y la foto lo
  "repone" como aporte. HANDOFF_reconstructor (uid 870) dice que para otros usuarios 'OTHER' sí es pesos: la regla
  necesita mirar el monto contra la tenencia, no un valor fijo.

### H11 · Dos implementaciones de "qué tenía en tal fecha" — CONFIRMADO (sin medir diferencia)

`ledger_replay.tenencia_en/cash_en/valor_en` no tiene ningún llamador de producción (sólo tests; mención en
`importing/proyeccion.py:12`). La reconstrucción usa `scripts/backfill_historical_mtm.py:307` `_holdings_asof`
(BUY−SELL de `import_normalized_tx`, costo PROMEDIO de todas las compras) y la foto usa `importing/proyeccion`.
Tres caminos para la misma pregunta. No medí si dan distinto.

### H12 · Lo que HANDOFF_reconstructor da por construido no está en `main`

`diagnostico.py`, `censo_flujos.py`, `censo_capital.py` y `flujos.py` (resoluciones) no existen en `main`: viven en
la rama `feat/reconstructor-f1`, nunca mergeada. Estado de sus causas raíz con lo probado acá:
**R1** (conducto MEP de Cocos) — con "Compra/Venta Dolar Mep" y el ticker entre paréntesis, Cocos produce
COMPRA ARS + VENTA USD correctas; con el instrumento sin paréntesis la fila **se descarta con error**. No se
reprodujo R1 (no tengo un export real de Cocos). **R3** (per-100 de IEB) — en la *actividad* está resuelto (GD38 a
0,4391 por 1); en la *foto* vuelve (H9-c). **R4** (renta de IOL) — `Pago de Renta(GD38)` en Cuenta Dólares entra como
DIVIDENDO USD 42,5 ✔. **R2** y **R5** no probados.

---

## 3 · Cobertura por modo

**En producción: por medir** (`medir_prod.py`, §7). En los usuarios del arnés (3 reales + 13 inventados):

| | usuarios | con número | sin número (motivo) |
|---|---|---|---|
| Certero | 16 | 15 | 1 (`medicion_dudosa`, IEB S1 por el ×100) |
| Estimado | 16 | 16 | 0 |

Pero "con número" en Certero = **sólo la ventana del cron** en los 13 inventados (≈3 meses de 33) y casi sólo eso en
los 3 reales (Balanz A ≈12 meses de 52; Balanz B ≈3 de 39; IEB ≈3 de 12).

| mejora | qué gana (medido en el arnés) |
|---|---|
| H1 solo | Balanz B real: Certero de 3 meses (+9,1 %) a 21 meses (+39,7 %); IEB real: de 3 a 7 meses. Pero Balanz A real y **12 de los 13 inventados PIERDEN el Certero** (`serie_partida`, H2), y en 11 de 13 el Estimado se achica de ~33 meses a 3 (H4). Salida: `salidas/escenarios.json`, campo `cf_sin_cobros`. |
| H1 + H2 | el Certero publica el último tramo continuo en todos (no lo corrí junto: es la combinación propuesta). |
| H3 (bonos con precio) | los 31 meses inventados pasarían a cobertura ≥ 0,9 (sin bonos al costo la cobertura es 1,0). No corrido. |

---

## 4 · Tabla parser × tipo de movimiento (ejecutada por `/api/imports/preview`)

Mismo movimiento económico en cada formato. ✔ = tipo, moneda y monto correctos; ✗ = mal o descartado;
— = no probado o no aplica a ese broker. Fuente:
`salidas/tabla.json` y `salidas/escenarios.json`. *SUP.* = formato supuesto (no hay ejemplo real en el repo).

| movimiento | Balanz mov. | IEB | Genérico | Cocos | IOL | PPI | Inviu | Schwab |
|---|---|---|---|---|---|---|---|---|
| Aporte en pesos | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — |
| Aporte en dólares | ✔ (· USD) | ✔ (· USD) | ✔ | ✔ (mismo broker) | ✔ | ✔ | ✔ | ✔ |
| Retiro | ✔ | ✔ | ✔ | ✔ | ✔ *SUP.* | ✗ "Egreso de Fondos" no reconocido *SUP.* | ✔ *SUP.* | ✔ |
| Compra en pesos | ✔ | ✔ | ✔ | ✔ (comisión aparte) | ✔ (comisión en precio) | ✔ (comisión en monto) | ✔ (comisión aparte) | — |
| Compra con dólares | ✔ | ✔ | ✔ | ✔ | ✔ (AAPLD) | ✔ | ✔ | ✔ |
| Venta | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Dividendo en pesos | ✔ | ✔ | ✔ | ✔ (sin activo) | ✔ | ✔ | ✔ | — |
| Dividendo en dólares | ✔ (· USD) | **✗ queda en pesos (H10)** | ✔ | ✔ (sin activo) | ✔ | ✔ | ✔ | ✔ |
| Cupón de bono (USD) | ✔ | ✔ *SUP.* | ✔ | ✔ *SUP.* | ✔ | ✔ *SUP.* | ✔ *SUP.* | — |
| Amortización | — | — | — | — | ✔ (como dividendo) | — | ✔ (como dividendo) | — |
| Dólar MEP (bono puente) | compra ARS + venta USD | compra ARS + venta USD | conversión FX | compra ARS + venta USD (✗ si el instrumento no trae "(AL30)") | compra ARS + venta USD | compra ARS + venta USD | — | — |
| Comisión en el importe | ✔ | **✗ se pierde** (0,06 % real; la foto la repone como *retiro*) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Interés de la cuenta | — | — | — | — | ✔ ("Crédito") | — | — | ✗ "Bank Interest" rechazado |
| Títulos que entran | — | ✔ (DEPOSITO TITULOS) | — | — | — | — | — | pendiente de costo en el asistente |

Diferencia de forma entre parsers (no de número): la comisión viaja aparte en Cocos/Inviu/Schwab y dentro del
precio/monto en IOL/PPI. El costo final coincide en los casos probados.

---

## 5 · Estimado vs Certero en los que tienen los dos

- **Sobre la MISMA ventana** (la del Certero = la del cron) la diferencia fue **0,00 pp en los 16 usuarios del
  arnés**: en esa ventana las dos cadenas usan los mismos puntos del cron.
- **La diferencia está en la ventana**, no en el número: el Estimado se estira 2-3 años con la cadena mezclada de
  H6. Ahí, contra la verdad:

| caso | Estimado | verdad TWR (misma ventana) | verdad contable | explicado por "no realizado"? |
|---|---|---|---|---|
| Balanz S0 | 135,47 | 141,34 | 21,65 | **No**: debería estar cerca de 21,65 y está cerca de 141 |
| IEB S0 | 123,46 | 141,34 | 21,65 | No (H6) |
| Balanz S2 | 166,55 | 141,34 | 21,65 | No: **arriba** del TWR real (contra el diseño) — H9-a |
| Balanz S1 | 82,37 | 36,07 | 8,69 | No: arriba del real — H5 |
| IEB S2 | 147,58 | 141,34 | 21,65 | No: arriba del real |

- En producción la distribución la da `medir_prod.py` (cuenta además los casos con Estimado > Certero + 1 pp).

---

## 6 · 🔴 QUÉ NO VERIFIQUÉ

1. **Nada contra producción.** No hubo copia de la base: ningún número de este informe es "de N usuarios de
   prod". Los conteos por hallazgo, la tabla de cobertura real y la distribución Estimado−Certero salen de
   `medir_prod.py`, que **probé sólo sobre las bases del arnés**.
2. **Precios reales.** Todo el mercado es inventado; en los archivos reales los precios son interpolados de las
   propias operaciones del archivo. Los % de las cuentas reales sirven para ver el mecanismo, no como el
   rendimiento real de esas cuentas.
3. **Benchmarks** (S&P, inflación): sin red vinieron vacíos; no medí `bench_pct_entre` ni `vs_sp500_pp`.
4. **Brokers sin prueba de punta a punta:** Cocos, IOL, PPI, Inviu, Schwab, Bull Market, Balanz Resultados,
   Balanz Internacional, Binance. Para los primeros cinco sólo la vista previa (tabla §4), con varios formatos
   *supuestos*. Ninguna foto de tenencia de esos brokers.
5. **Foto de IEB con bonos:** el ×100 (H9-c) sale de mi formato de foto; tu portafolio real no trae bonos.
6. **Extracción de PDF:** la foto de Balanz se generó como PDF desde texto; no probé PDFs reales del broker.
7. **FCI:** sin `fci_prices`; quedaron al costo. **Splits, canjes, cambios de ratio, letras que vencen,
   amortizaciones que bajan el nominal:** no ejercitados.
8. **Migración FX v1→v2** (`_auto_migrar_fx_post_import`): corrió en el confirm pero no medí su efecto.
9. **H11:** no comparé `_holdings_asof` contra `ledger_replay.tenencia_en` ni contra `proyeccion`.
10. **Otros lectores de `operations`** que puedan tomar un cobro sin `entry_date` como lote (H1): no barridos.
11. **El frontend** (`insightsModel.js`: `acumuladoPublicado`, `acumuladoDeVentana`, `benchDelAcumuladoEstimado`) y
    el browser: comparé los endpoints que lo alimentan, no lo que dibuja la pantalla.
12. **H1+H2+H4 juntos** (el arreglo propuesto) no lo corrí como contrafáctico combinado.
13. **El cron "de verdad" arranca cuando el usuario se registra;** en el arnés arranca después del último
    movimiento o de la foto. Con usuarios que ya tenían cron antes de importar, la costura (H5) cae en otro lugar.
14. La red bloqueada también cortó `api.argentinadatos.com/v1/finanzas/letras` y `/indices/uva` durante el
    confirm/lectores: lo que dependa de eso (vencimiento de letras, UVA) corrió en su rama de falla.

---

## 7 · Para medir en producción (en tu Mac)

```bash
cd ~/Documents/trading && git fetch origin claude/modest-mccarthy-4nsncl
git worktree add .claude/worktrees/audit-csv origin/claude/modest-mccarthy-4nsncl
cd .claude/worktrees/audit-csv/backend
python3 ../audit/rendimiento_csv/medir_prod.py ~/Downloads/<copia-más-nueva>.db /tmp/medicion.json
```

Imprime: usuarios con número por modo y por motivo; Estimado − Certero sobre la misma ventana (mediana, p10,
p90, extremos, y cuántos con el Estimado arriba); y cuántos usuarios tienen la señal de H1, H2, H4, H5, H6 y H7.
Abre la base con `?immutable=1`: no puede escribir.
