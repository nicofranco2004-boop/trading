# Propuesta: qué hacer con los snapshots ya escritos por A-1 y A-2

**Esto es una propuesta para que decidas. NO ejecuté nada contra ninguna base.**
No corrí una sola query contra producción: los criterios de abajo están derivados
de leer el código, y las queries están escritas para que las corras vos (o me
digas que las corra) cuando decidas.

Rama: `fix/snapshots-valuacion`. El fix de código ya está y no toca datos.

---

## 1. Qué quedó mal escrito, exactamente

El cron escribe una fila por usuario y día en `snapshots`
(`total_value`, `total_invested`, `net_deposited`, `fx_to_usd_blue`,
`holdings_json`, `mtm_coverage`, `source='cron'`, `base='mercado'`, `apto=1`).

Para un lote con `positions.currency='ARS'` alojado en un broker de moneda USD:

| campo | qué se escribió | factor |
|---|---|---|
| `total_invested` | el costo **en pesos** sumado como si fueran dólares | **×MEP** (~1.450) en la parte que aporta ese lote |
| `total_value` | el guard comparó USD contra pesos → descartó el precio real y cayó **al costo inflado** | **×~MEP** |
| `holdings_json` | el `value_usd` de ese activo, con el mismo error | ×~MEP |
| `mtm_coverage` | la cobertura se pondera con `_cost_usd`, que también contó el costo en pesos como dólares | peso ×MEP en la ponderación |

Dos poblaciones, que se solapan:

- **A-1** — lote en pesos en **cualquier** broker de moneda USD (incluye los
  sub-brokers `· USD`). Costo y valor inflados ~MEP×.
- **A-2** — el subconjunto que además vive en un broker USD **genuino** (Schwab,
  IBKR: sin padre AR y sin `· USD` en el nombre). A esos, además, se les pidió y
  se les guardó el precio del **instrumento equivocado** (el ADR de NYSE en vez
  de la acción local de BYMA). Es el más silencioso: el guard no lo atrapa
  porque el múltiplo cae dentro de la banda.

Un lote en pesos en un sub-broker `· USD` ya ruteaba a `.BA` (A-2 no lo tocó),
pero A-1 sí le infló el costo.

---

## 2. Cómo identificarlos

### 2.1 Qué usuarios están afectados (barato, primer corte)

```sql
-- Usuarios con al menos un lote en PESOS alojado en un broker de moneda USD.
-- No prueba que el snapshot histórico esté mal: prueba que HOY tienen la
-- configuración que lo produce.
SELECT p.user_id, b.name AS broker, b.currency AS broker_ccy,
       COUNT(*) AS lotes, SUM(COALESCE(p.invested,0)) AS costo_ars
FROM positions p
JOIN brokers b ON b.name = p.broker AND b.user_id = p.user_id
WHERE UPPER(COALESCE(p.currency,'')) = 'ARS'
  AND UPPER(COALESCE(b.currency,'')) <> 'ARS'
  AND COALESCE(p.is_cash, 0) = 0
GROUP BY p.user_id, b.name, b.currency
ORDER BY costo_ars DESC;
```

Para separar **A-2** (instrumento equivocado) de A-1 solo, filtrá los brokers que
**no** son sub-broker `· USD` ni tienen `parent_broker_id` de un padre ARS — es
la misma regla que `_broker_name_sets` / `_is_ar_usd_subbroker`.

### 2.2 Qué snapshots están mal (la señal fuerte)

La firma más limpia **no** necesita precios históricos: `total_invested` es cost
basis, y quedó inflado ~MEP× en la parte afectada. Contra `net_deposited`, que
se computa aparte y **no** tiene este bug, la desproporción salta:

```sql
-- Snapshots donde el "invertido" se despega del neto depositado por un factor
-- del orden del MEP. Ajustá el umbral: 50 es conservador (el MEP ronda 1.450).
SELECT user_id, date, total_invested, net_deposited, total_value, mtm_coverage, source
FROM snapshots
WHERE net_deposited > 0
  AND total_invested > net_deposited * 50
ORDER BY total_invested / net_deposited DESC;
```

Complemento: `holdings_json` guarda `[{asset, value_usd}]`. Un `value_usd` de
seis o siete cifras para un activo suelto es el mismo dedo acusador, y además te
dice **qué activo** lo causó. No guarda la moneda del lote, así que sirve para
detectar, no para diagnosticar solo.

**Cuidado con el falso positivo:** un usuario con capital aportado mal cargado
(o `net_deposited` en cero) dispara la query 2.2 sin tener este bug. Cruzá
siempre contra 2.1: si el usuario no tiene ningún lote en pesos en cuenta USD,
no es A-1/A-2 — es otro hallazgo.

---

## 3. ¿Se pueden recalcular?

**Depende del campo. Uno sí, el otro solo en parte.**

### `total_invested` — sí, con buena fidelidad
Es cost basis: no depende de precios de mercado. Solo hace falta el MEP de esa
fecha, y `fx_rates_daily` tiene la serie histórica. La única incertidumbre es que
las posiciones de HOY no son las de esa fecha (si el usuario borró, editó o
re-importó desde entonces), y eso se resuelve con el replay que ya existe.

### `total_value` — no exactamente, y hay que decirlo
El propio código lo admite, en el detector de snapshots corruptos que ya existe
(`main.py:15413`):

> *"no podemos recomputarlo porque dependería de precios históricos que no
> almacenamos"*

Eso es cierto para el día a día. Pero **no** es toda la verdad: el backfill
`backfill_historical_mtm.py` ya trae closes históricos de yfinance y dice haber
medido cobertura de **24 de 24 meses** para `AAPL.BA`, `KO.BA`, `MELI.BA`,
`GGAL.BA`, `YPFD.BA`. O sea: **mensual sí; diario no.**

Y hay un dato que juega a favor: ese backfill **llama a las funciones reales**
(`sj.compute_broker_value_usd` en la línea 520 y `sj.position_price_key` en la
501), no las reimplementa. Con el fix de esta rama aplicado, **el backfill queda
arreglado solo**. No hay que portar nada dos veces.

Contracara del mismo hecho: **si el backfill ya se corrió alguna vez, escribió
snapshots con `source='mtm_backfill'` que arrastran este mismo bug.** Esos
también entran en la población a limpiar:

```sql
SELECT source, COUNT(*) FROM snapshots GROUP BY source ORDER BY 2 DESC;
```

---

## 4. Las tres opciones, con lo que cuesta cada una

| | qué hace | recupera el número | riesgo |
|---|---|---|---|
| **A. Borrar** | eliminar las filas afectadas, como ya hace `_detect_and_remove_corrupt_snapshots` | no | **irreversible**, y borra mediciones reales de días que quizás estaban bien |
| **B. Recomputar mensual** | correr el backfill MtM ya arreglado sobre los meses cerrados afectados | aproximado (cierre de mes, MEP proxy) | pisa mediciones reales del cron con reconstrucciones |
| **C. No tocar nada** | el fix corta la sangría hacia adelante | no | el histórico sigue mintiéndole al chart, al CAGR, al benchmark y a la IA |

**Mi recomendación: B acotado, y solo después de medir.** En este orden:

1. Correr 2.1 y 2.2 **en modo lectura** para saber de cuántos usuarios y cuántas
   filas hablamos. Puede ser un puñado — y entonces la decisión es barata.
2. Correr el backfill en su **DRY-RUN** (ya lo tiene: sin argumentos trabaja
   sobre una copia y no toca nada) y comparar lo reconstruido contra lo guardado.
3. Recién ahí decidir, con los dos números a la vista.

No arrancaría por A: borrar es lo único de esta lista que no tiene vuelta atrás.

---

## 5. Riesgos que quiero dejar escritos

- **Un snapshot es una MEDICIÓN.** Reemplazarlo por una reconstrucción cambia su
  naturaleza. El backfill al menos lo estampa (`source='mtm_backfill'`,
  `mtm_coverage`) en vez de disfrazarlo de cron.
- **El MEP histórico es un proxy del blue** en el backfill. En períodos de brecha
  ancha eso mete error propio.
- **Las posiciones de hoy no son las de esa fecha.** Todo replay hereda esa
  incertidumbre.
- **Solo importan las fechas PASADAS.** La de hoy la reescribe el cron en su
  próxima corrida, ya con el fix — y que el cron pise al browser está documentado
  como intencional (`snapshots_job.py:838-839`), así que no hay nada que hacer ahí.
- **Nada de esto es urgente en el sentido de "se sigue rompiendo".** Con el fix
  mergeado, deja de escribirse basura nueva. La limpieza es una decisión sobre el
  pasado, y se puede tomar con calma.
