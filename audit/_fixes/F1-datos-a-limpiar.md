# F1 — datos que quedaron mal, y qué hacer con ellos

**Esto es una propuesta para que decidas. No ejecuté nada: ningún commit de esta rama toca datos.**

Rama `fix/f1-deje-de-escribir-mal`, base `da6ce759` + cherry-pick `86402f00`.
Los fixes cortan el daño **hacia adelante**. Lo ya escrito sigue como está.

---

## Resumen

| # | qué quedó mal | ¿recalculable? | riesgo de limpiar | consulta que lo dimensiona |
|---|---|---|---|---|
| 1 | `snapshots` con valuación inflada (A-1/A-2) | **Sí**, re-corriendo el job | bajo | **Q1a, Q1b, Q1c, Q1d** |
| 2 | Capital de conversiones mal atribuido por broker (A-9) | **Sí**, solo | ninguno | **Q6** |
| 3 | `manual_deposits` de reconciliaciones al TC 1415 (A-6) | **No** sin el TC real | medio | **Q4** |
| 4 | Baselines `capital_inicio` borradas (A-4) | **No. Perdidas.** | — | **Q2** |
| 5 | Ventas con `fx_to_usd = 1.0` (A-7) | **Sí**, con el TC de la fecha | bajo | **Q5** |
| 6 | Ventas retroactivas desde mobile al TC de hoy (A-8) | **No** distinguibles | alto | ninguna |
| 7 | Filas de `monthly_entries` con fecha futura | n/a — quedan | bajo | ninguna |

---

## 1 · Snapshots con valuación inflada — *el más grande, y el más limpio de arreglar*

**Qué pasó.** Todas las noches, cada lote comprado en pesos alojado en una cuenta dólar entró al snapshot con su costo en pesos contado como dólares (~1.450×), y el guard anti-distorsión, al comparar dólares contra pesos, **rechazaba el precio de mercado real** y persistía el costo inflado como si fuera valor.

**Cómo identificarlos.** `Q1c` es la más directa: las filas donde `total_value` es **exactamente igual** a `total_invested` (cayó a costo) y `total_value` es grande. Ojo — **mide de más**: una cuenta sin ningún precio disponible también cae a costo legítimamente. Por eso `Q1a`/`Q1b` primero, que dan el padrón exacto de posiciones en esa condición.

**Recalculable: sí.** `snapshots` es derivado — posiciones × precio del día. Con el motor ya arreglado, re-correr el job sobre las fechas afectadas reconstruye el valor correcto, **siempre que haya precios históricos de esas fechas**. Donde no los haya, el recálculo caería a costo otra vez: hay que decidir si se deja el hueco o se interpola.

**Riesgo: bajo.** El dato es derivado y reproducible. Ya existe una propuesta escrita para esto, sin ejecutar: `PROPUESTA_limpieza_snapshots_A1_A2.md`, que vino con el cherry-pick.

**Ojo con el orden:** limpiar snapshots antes de decidir el punto 3 mezcla dos correcciones sobre la misma serie.

---

## 2 · Capital de las conversiones mal atribuido

**Qué pasó.** El capital aportado de una conversión de moneda no se atribuía a los brokers correctos. Medido sobre el backup de producción del 16/08 (dato que viene con el commit de origen, no lo medí yo): **US$444.342 salieron de pesos a dólares y US$217.932 volvieron sin que ningún broker los acreditara**; 41 usuarios con conversiones, **12 con capital aportado negativo** en una de las dos patas. A nivel global el error casi se cancela — por eso sobrevivió catorce meses y sólo se ve en los reportes **por broker**.

**Recalculable: sí, y solo.** El fix recompone las dos patas desde `import_normalized_tx` en cada lectura, así que **se corrige sin backfill**: alcanza con que el usuario re-importe, o directamente en la próxima lectura para los que ya tienen sus batches confirmados. `Q6` dimensiona cuántas conversiones hay.

**Riesgo: ninguno.** No hay que escribir nada.

---

## 3 · Reconciliaciones de caja dolarizadas a 1415

**Qué pasó.** Cada reconciliación de caja de un broker en pesos convirtió a dólares dividiendo por 1415 — un número escrito en el código, no una cotización. Ese monto entró a `manual_deposits`, que el recalc trata como **autoritativo y no recomputa**: quedó fijo.

**Cómo identificarlos.** `Q4`, que usa la huella aritmética: `manual_deposits_native / manual_deposits ≈ 1415,0 exacto`. Un flujo cargado por el botón Cash usaría el TC del día, que casi nunca cae justo en 1415,000. **Mide de más**: un usuario que reconcilió cuando el blue estaba realmente en ~1415 es indistinguible.

**Recalculable: parcialmente.** Se puede recomputar `manual_deposits = manual_deposits_native / fx_for_date(mes bookeado)`, porque el monto en pesos **sí quedó guardado** en `manual_deposits_native`. Eso lo hace corregible sin pedirle nada al usuario. La limitación: las filas donde `manual_deposits_native` esté en NULL (la columna es más nueva que la feature) no tienen de dónde sacar el nominal.

**Riesgo: medio.** Cambia el capital aportado, o sea el **denominador del rendimiento**: el % publicado de esas cuentas se mueve. No es un cambio invisible.

---

## 4 · Baselines de `capital_inicio` borradas — *irrecuperables*

**Qué pasó.** El recalc borraba el `capital_inicio` que el usuario tipeó para declarar lo que ya tenía. Se disparaba con el primer import, revert, borrado de broker o cierre de futuro.

**Recalculable: NO.** Ese número no vive en `operations`, ni en los imports, ni en ninguna otra tabla. **No hay de dónde sacarlo.**

**Qué se puede hacer, en orden de preferencia:**
1. **Backup.** Si hay un dump anterior a la primera vez que cada usuario recalculó, el valor está ahí. Es la única recuperación real.
2. **Preguntarle al usuario.** Un aviso en `/mensual` a los afectados: "declaraste un capital inicial y se perdió, volvé a cargarlo".
3. **Nada.** Los afectados ven su rendimiento con el denominador incompleto.

`Q2` cuenta **cuántas baselines sobreviven hoy** — las que el fix acaba de proteger. **Corré esa consulta antes que ninguna otra**: mide lo que todavía se puede perder, no lo perdido.

⚠️ **Bug adyacente, no arreglado:** un usuario que tipea **solo** una baseline, sin movimientos ese mes, pierde la fila entera en el `DELETE` de filas todo-en-cero, porque la condición no mira `capital_inicio`. Es preexistente y sigue vivo.

---

## 5 · Ventas con `fx_to_usd = 1.0`

**Qué pasó.** Cuando el usuario dejaba vacío el campo opcional "TC de venta", la fila quedaba sellada con `fx_to_usd = 1.0` mientras su `pnl_usd` estaba dividido por el TC de la fecha (~1.400). Y `monthly_entries.pnl_realized` del broker recibió el P&L **en pesos** como si fueran dólares.

**Cómo identificarlos.** `Q5`: `currency = 'ARS'` y `fx_to_usd = 1.0`. Es un identificador **limpio**: una venta en pesos con fx = 1 dice que un peso vale un dólar, y no existe caso legítimo. Corré también la variante sin filtro de `op_type` que trae la consulta: si da mucho más, el filtro se quedó corto.

**Recalculable: sí.** El `pnl_usd` de la fila **ya está bien** (se dividió por el TC correcto); lo que está mal es el sello. Se repara con `fx_to_usd = fx_for_date(date)`. La parte mensual sí necesita recomputar `pnl_realized` y volver a correr `_repair_monthly_chain`.

**Riesgo: bajo** para el sello, **medio** para el mensual — mueve `capital_final` hacia adelante.

---

## 6 · Ventas retroactivas desde mobile — *el más incómodo*

**Qué pasó.** Una venta con fecha pasada hecha desde el celular usó el MEP de hoy en vez del de la fecha.

**Cómo identificarlos: no se puede con certeza.** La fila resultante es **indistinguible** de una venta donde el usuario tipeó ese TC a propósito. No hay marca de origen (mobile/desktop) en `operations`.

**Riesgo: alto.** Cualquier corrección masiva pisaría también ventas legítimas. **Recomiendo no tocar**: dejarlo, y que se corrija solo a medida que los usuarios editen o re-importen.

Lo dimensionable es la exposición futura, ya cerrada por el fix.

---

## 7 · Filas de `monthly_entries` con fecha futura

Quedan donde están, y el fix hace que dejen de congelar el calendario. **No propongo borrarlas**: son dato del usuario y algunas pueden ser legítimas.

**Pendiente que no entró en F1:** no hay validación de fecha futura al escribir. `POST /api/operations` sigue aceptando `date=2030-06-15`. Agregarla es una validación que **rechaza**, y en este repo eso exige antes el censo de todos los callers — `normalize_rows` es el embudo de 18 parsers. No lo hice sin ese censo.

---

## Qué correr, y en qué orden

Todas están en `audit/01_calculos/1a-alcance-produccion.sql`. **19 sentencias, las 19 `SELECT`.** Sugerido:

1. **Q2** — baselines que todavía sobreviven. Es lo único que mide algo **que aún se puede perder**.
2. **Q1a / Q1b** — padrón exacto de posiciones con costo en pesos en cuenta dólar.
3. **Q1c / Q1d** — cuántas filas de `snapshots` quedaron pegadas al costo, y desde cuándo.
4. **Q5** — ventas con `fx_to_usd = 1.0`.
5. **Q4** — reconciliaciones con la firma del 1415.
6. **Q6** — conversiones importadas.

Con eso alcanza para decidir qué se limpia y qué se deja. Decime cuáles corrés y te armo el plan de limpieza con los números reales.

---

## Lo que quedó fuera de F1

- **A-5 (amortización manual).** La auditoría lo ubicó en el escritor; **el código dice otra cosa.** El esquema documenta el contrato (`main.py:1283-1285`): `pnl_usd` = cash bruto y el lector resta `cost_basis_consumed`. `Positions.jsx:540-551` **ya lo implementa así**. Quien no resta es `realized_pnl.py`, que es el lector. O sea: **el fix va en el lector, no en el escritor**, y cambia números publicados en Dashboard, Reportes y packets de IA. Además hay que verificar si `cost_basis_consumed` está en la misma moneda que `pnl_usd`, que no es obvio. No entra en "que deje de escribir mal".
- **D-5** (dos escritores de `snapshots.total_invested` con convención opuesta): es una decisión de producto sobre qué significa "invertido", no un bug mecánico.
- **Conversión manual** (`POST /api/conversions`): no pasa por `import_normalized_tx`, así que quedó asimétrica con la importada. No inventa capital, pero no atribuye por broker.
