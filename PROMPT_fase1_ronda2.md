# FASE 1 · RONDA 2 — cerrar lo que la ronda 1 dejó abierto

Sos el chat IMPLEMENTADOR. Hiciste la ronda 1 y **estuvo bien**: el censo que reportaste es
honesto (lo reproduje: 278 cambian, 205 dejan de publicar, **0 aparecen donde no había**,
uid 452 → −0,64%), las dos suites quedaron verdes con conjuntos de fallas idénticos, no
metiste ni un NaN en las 822 series, los 185 usuarios sanos quedaron intactos, las 12
mutaciones muerden y no inventaste criterios. El arreglo de `_snapshot_delta` está confirmado
con la serie real del 452, y 46 usuarios dejaron de ver un absurdo.

La pasada adversarial encontró **dos bloqueantes**, y los dos son el mismo patrón que hizo
volver este bug once veces: **el arreglo cambió una propiedad de la que dependía otro
consumidor que nadie miró.**

---

## 0 · REGLAS (iguales que la ronda 1)

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura.
- ❌ NO construyas el toggle contable/certero: es **Fase 2**, decisión ya tomada del dueño.

### ⚠️ EL INSTRUMENTO — esto te va a hacer medir mal si no lo leés

El working tree tiene **dos trabajos superpuestos sin commitear**: las rondas 9-11 y tu Fase 1.
`git diff` los muestra **mezclados** y te va a hacer atribuirte cosas que ya estaban.

- Árbol **pre-Fase-1** reconstruido: `/private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/d11071a5-fb89-4866-98f1-e2262799901d/scratchpad/pre1`
- El diff real de tu ronda 1 es `diff -r <ese pre1> <worktree>` (excluí `.git`, `node_modules`,
  `dist`, `__pycache__`, `.pytest_cache`, `*.db*`).
- Fueron **9 archivos + 1 test nuevo, 678 líneas**. No las 1.775 que muestra `git diff`.

**Datos reales**: copia de producción en `.../scratchpad/prod-0816.db`. Series ya clasificadas
en `.../scratchpad/ab/all_series.json` (uid → filas ASC con `clase`/`base`/`apto`).
Helpers viejo y nuevo listos para A/B en `.../scratchpad/ab/{old,new}_evolution.mjs`.

⚠️ Al probar `buildEvolutionFromSnapshots`, el campo del rendimiento acumulado es **`total`**
(en `seriesUsd[].total`), no `twrr` ni `value`. Yo mismo medí 0 usuarios afectados con el campo
equivocado antes de darme cuenta.

---

## 1 · 🔴 BLOQUEANTE — `esDibujable` en una función que MIDE, no dibuja

**`frontend/src/utils/evolution.js:381`**

Cambiaste el filtro de `buildEvolutionFromSnapshots` de `apto` (pre1:244) a `esDibujable`, con
el comentario *"esto es una SERIE DIBUJADA, y filtrarla por el predicado de los bordes es la
ronda 9 otra vez"*.

**Esa función no dibuja: mide.** Su cuerpo encadena Modified Dietz entre snapshots consecutivos:

```js
period_return = pnl_t / (value_t-1 + 0.5 × flows_t)   // value_t-1 es DENOMINADOR
cum_t         = cum_t-1 × (1 + period_return)
if (value > peakValueUsd) peakValueUsd = value        // y PICO
```

Cada punto que entra es **denominador de un período y candidato a pico**. Son exactamente las
dos cosas que `esApto` protege. Y esta función **no es `curva_indexada`**: no tiene el
mecanismo que impide que un punto no-apto fije un pico — por eso el contrato de `ACEPTA_LINEA`
dice que INTRADIA entra a la línea *"y `curva_indexada` se encarga de que nunca sea pico ni
denominador"*. Acá no hay quien se encargue.

Medido sobre la copia de producción:

```
usuarios con filas INTRADIA:                    99
  ...cuyo rendimiento acumulado CAMBIA:         83
  uid 519  +5,82% → −39,53%      uid 93   +7,82% → −33,44%
  uid 427  −4,32% → +42,43%      uid 268 −83,92% → −15,07%
```

**Qué hacer**: volver a `esApto` en `:381`. Si querés que la línea conserve continuidad visual
con los puntos INTRADIA, hace falta el equivalente de `curva_indexada` — dibujar el punto sin
que participe del encadenado ni del pico. **No lo resuelvas metiéndolo al chain-link.**

Y dejá escrito en el código, arriba del filtro, **por qué esta función usa `esApto` aunque
dibuje**: es justo el lugar donde el próximo lector va a querer "corregirlo".

---

## 2 · 🔴 BLOQUEANTE — el `None` nuevo reemplaza el mensaje honesto por uno falso

**`backend/main.py:31685` → `backend/reporting/builder.py:618`**

`_latest_snapshot_value` ahora devuelve `None` cuando no hay cierre medido. Correcto. Pero:

```python
month_is_current = live_value is not None and is_period_current(period_type, period_start, period_end)
```

Con `None`, `month_is_current` queda **False** y el mes en curso **cae al camino del mes
CERRADO**, calculándose con `capital_inicio`/`capital_final` de `monthly_entries` — la cadena
contable. Medido sobre los 182 usuarios con valor real y sin ninguna fila medible:

```
PRE  (tu ronda 1) :  175 × "Mes sin base para medir el rendimiento."
POST              :  180 × "Mes sin grandes movimientos."   ← y 2 que ahora publican un %
```

**Convertiste una confesión honesta en una afirmación falsa.** Tu propio docstring lo predijo:
*"el llamador tiene que saber mostrarlo como un vacío explicado y no como un 0"* — el llamador
no sabe.

⚠️ El peor call-site es **`ai/builders/monthly.py:100`**: no tiene el fallback a
`compute_live_portfolio_value` que sí tiene el endpoint de la timeline, así que el packet que
va al prompt del LLM es exactamente ese "Mes sin grandes movimientos".

**Qué hacer**: separar "no hay valor de cierre" de "el período no es el actual". Son dos
preguntas distintas y hoy las decide un solo `is not None`. El mes en curso sigue siendo el mes
en curso aunque no haya con qué medirlo — y ahí es donde tiene que salir el vacío explicado
(punto 5), no el camino del mes cerrado.

---

## 3 · El `> 0` de §4.4 sigue vivo, en la misma función que tocaste

**`frontend/src/utils/evolution.js:434`**

```js
const baselineUsd = (s.net_deposited && s.net_deposited > 0) ? s.net_deposited : s.total_invested
```

Arreglaste `netDepositedOf` en `:228` (bien, y el comentario es correcto) y dejaste **esta copia
inline sin tocar**, dentro de `buildEvolutionFromSnapshots`. Alimenta `flows` del chain-link, o
sea que la base contable vuelve a entrar por la ventana en el mismo cálculo del punto 1.

Son 4.744 filas en 192 usuarios con `net_deposited < 0`. Aplicá el mismo criterio: **ausente
(`0`) ≠ negativo**. Y si podés, unificá — dos copias de la misma regla en un archivo es
exactamente el defecto de fondo de este proyecto.

---

## 4 · El borde de CIERRE no tiene control de frescura

**`backend/reporting/builder.py:270`**

`fetch_latest_measured_snapshot` delega en `fetch_snapshot_at_or_before` con `when='9999-12-31'`
y hereda dos cosas que sólo tienen sentido en el borde de **apertura**:

1. **El filtro `total_value > 0`.** En la punta, una cartera legítimamente vacía **no es
   "no hay medición": es una medición de cero.** El usuario que vendió todo tiene un cierre
   válido en 0, y hoy se lo saltea.
2. **No aplica `_border_is_fresh`**, que sí usan `_ytd_delta` (`main.py:31972`) y
   `bordes_mercado_periodo` (`builder.py:437/452`).

Resultado medido: el cierre salta hasta 57 días para atrás buscando una fila con valor > 0.

```
uid 330 → publica "+8,76%" entre 2026-06-25 y 2026-06-30, como variación del último cierre
lag del borde de cierre vs 2026-08-16:  0-7 días: 457 · 8-30: 26 · 31-90: 5
```

Y la fila que eligió para uid 330 tiene `total_value == total_invested == net_deposited` y
`holdings_json` NULL — la firma de la cadena contable. O sea el borde "medido" es una fila al
costo, por la puerta de la vista.

---

## 5 · 🔴 EL ESTADO VACÍO — la mitad de producto que quedó sin empezar

Éste es el criterio §5 de la ronda 1 y **no se cumplió**. El diff real lo confirma sin
ambigüedad: **`Dashboard.jsx` y `HomeMobile.jsx` no fueron tocados.** Arreglaste el cálculo y no
tocaste ninguna de las dos pantallas que lo muestran.

Medido sobre los 822:

```
sparkline 30d en null                            174
  ...de esos, con ≥2 snapshots → MENSAJE FALSO   168
KpiCell "P&L Mes" y "P&L Día" = "—"              338
chip del Dashboard desaparece sin decir nada     173
```

Los tres sitios:

| file:line | qué pasa hoy |
|---|---|
| `Dashboard.jsx:914` | `.filter(Boolean)` → la card "Este mes" **desaparece en silencio** |
| `Dashboard.jsx:962` | `periodChange && (...)` → el chip se borra sin explicación |
| `HomeMobile.jsx:372` | 🔴 dice *"Cargá tus snapshots diarios para ver la evolución 30d"* — **para estos 168 usuarios es FALSO**: `uid 107` tiene **57 snapshots**. Le pedimos que haga lo que ya hizo |
| `HomeMobile.jsx` KpiCell | `"—"` pelado |

⚠️ Y el campo que inventaste para esto **no lo lee nadie**: `sinBaseMedida` / `ytdSinBaseMedida`
(`useMonthlyData.js:618`) sólo aparecen en el hook y en su test. El comentario dice *"es lo que
la UI usa para explicar POR QUÉ no hay número, en vez de un '—' mudo"*. Ese consumidor no existe.

**Qué hacer**: que cada superficie diga **por qué** no hay número, con las palabras del caso
("todavía no tenemos mediciones a precio real de tu cartera antes de tal fecha", o lo que
corresponda). No un "—", no un 0, no un mensaje que le pida algo que ya hizo.
**No construyas el toggle**: eso es Fase 2 y va a reemplazar este vacío.

---

## 6 · Además — dos cosas chicas y verificadas

- **7 usuarios publican "0,00%" con un monto en dólares no nulo.** `evolution.js:308`
  (`if (!prev || !prev.total_value)`) deja pasar un `total_value` **negativo**, y `:317`
  (`prevValue > 0 ? usd/prevValue : 0`) cae al cero. La línea es preexistente, pero tu filtro
  cambió **quién** cae ahí. Un cero falso es peor que un vacío: parece un dato.
  ```
  uid   1 | +US$2.026,35 | 0,00% | base 2026-06-04 (−11,92) | 84 días
  uid 492 |   −US$173,88 | 0,00% | base 2026-07-31          | 27 días   (+5 más)
  ```
- **El test `'CONSISTENCIA'`** (`useMonthlyData.test.js:281`) conservó el nombre pero perdió su
  único assert (`expect(sumOfDeltas).toBeCloseTo(yr.ytdUsd, 1)`) sin reemplazo. El invariante
  que protegía —que la suma de los deltas mensuales dé el YTD— vuelve a ser violable.
  O restaurá un equivalente, o renombrá el test para que no prometa lo que ya no verifica.

---

## 7 · ⛔ FUERA DE ALCANCE de esta ronda (anotado, no lo toques)

- **El pico del asesor** (`main.py:35634`). Tu fix lo apuntó a `snapshots_medibles`, pero la
  vista usa un `ELSE 1` que acepta las filas legacy que `clasificar_serie` llama
  `sintetico_costo`: **la vista y el clasificador se contradicen sobre la misma fila**. Medido:
  alertas de drawdown 171 → **169**, con pico contable 83 → **81**. Sigue publicando *"Su
  ganancia cayó 492.864% desde el mejor momento"*. Es más profundo que esta ronda (hay que
  decidir cuál de los dos criterios manda) y va aparte.
- **`uid 329` publica −9.346.280%**: `net_deposited = 1.699.812.606` contra `total_value =
  18.323`, en filas **medidas**. Es corrupción de datos preexistente (familia de
  `project_negative_capital_corruption`), no de esta familia. Ticket propio.
- **Postgres**: no hay motor en esta máquina (`docker`, `psql`, `pg_ctl`, `postgres`: ninguno).
  Tu "cero ejecución" no fue pereza. Queda como riesgo abierto del día del pasaje.
  Sí anotá, sin arreglarlo ahora: `schema_pg.sql` lo editaste **a mano** en vez de regenerarlo
  con el `mkschema.py` que acababas de arreglar, y quedan 6 columnas faltantes (4 de `users`).
- **Fase 2**: drawdown / pico / vs-benchmark / rachas en modo contable, y el toggle.

---

## 8 · CÓMO VERIFICAR

- **Ejecutando, nunca leyendo.** Cada afirmación con el comando y su salida real.
- **Tu fixture tiene que PODER fallar.** Para el punto 1, tu caso de prueba tiene que tener
  filas INTRADIA reales y demostrar que el TWRR cambia; para el punto 2, un usuario sin ninguna
  fila medible y el headline literal antes y después.
- **La suite no es determinista y la completa muere en exit 144 al 23-28%.** Compará
  **CONJUNTOS de nombres de tests**, nunca conteos. Tu comparación de la ronda 1 (43 archivos
  del alcance) estuvo bien hecha: repetila.
- **Mutá para comprobar que el guard muerde**: revertí cada fix y confirmá que algo se pone
  rojo. En la ronda 1 lo hiciste y sirvió — 12 mutaciones, 12 rojos.
- **A/B contra producción**: el censo de la ronda 1 es el patrón a repetir. En particular,
  después del punto 1 volvé a correr `buildEvolutionFromSnapshots` sobre los 99 usuarios con
  INTRADIA y mostrá que el acumulado vuelve a lo que era.

## 9 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line` de cada uno.
2. Repro **antes** y **después** de cada punto, con salida real.
3. Conjuntos de tests que fallan, antes y después, y su diferencia.
4. **Capturas del browser** del punto 5 — es el único que se juzga mirando la pantalla.
5. 🔴 **"QUÉ NO VERIFIQUÉ"** al final. En la ronda 1 lo hiciste bien y fue lo que hizo que el
   audit encontrara los dos bloqueantes rápido. No lo maquilles.
