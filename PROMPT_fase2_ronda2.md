# FASE 2 · RONDA 2 — el KPI que dice "—" al lado de su propia curva

Sos el chat IMPLEMENTADOR. La Fase 2 está **auditada y bien**: verifiqué ejecutando que
`CERTERO` quedó **bit-idéntico en los 822 usuarios** (la propiedad que, de romperse, reabría
todo), que el TWR del estimado coincide con el recálculo independiente en los 655 (**0
discrepancias**), que **0 usuarios** exponen drawdown o pico en estimado, y que los tests que
tocaste quedaron **más fuertes**, no más débiles. Backend 144/0, frontend 1161/0.

Dos cosas que tu propio reporte subestima, y que medí:

- El "antes" real del estimado no era 480: era **248**. Pasaste de 248 a 655.
- Y arreglaste un defecto **preexistente que nadie había nombrado**: antes de tu ronda, el
  estimado publicaba para **232 usuarios MENOS** que el certero — al revés de lo que el modo
  promete. Ahora son **0**. Ese invariante que escribiste vale más de lo que le pusiste.

Queda una sola cosa, la que vos mismo declaraste como el hueco más grande.

---

## 1 · EL HUECO, Y LA CAUSA (la encontré, no la busques de nuevo)

Para un usuario 100% contable en ESTIMADO: la curva se dibuja, el endpoint publica `+16,86%`,
y el KPI **"Acumulado 1A · USD" dice "—"**.

Dijiste *"la clave no está en ninguna fila"*. **La fila está: el valor vive bajo otra clave.**

`frontend/src/pages/Insights.jsx:1486-1487`:

```js
return partirMedidoYEstimado(
  filas, `${userName} P/L total`, `${userName} estimado`)
```

`partirMedidoYEstimado` **parte la serie en dos claves** para poder dibujar lo no medido
punteado: lo medido queda en `${userName} P/L total`, lo no medido en `${userName} estimado`.

En un usuario 100% contable, **todos** los puntos caen en la segunda y **ninguno** en la
primera. Y el KPI (`Insights.jsx:2463`) lee:

```js
const cumulativeReturnPct = lastRow[`${userName} P/L total`] ?? null
```

→ `null` → `"—"` (`components/InsightsKpiStrip.jsx:109-110`).

Por eso tu intento de "tomar la última fila con dato" no podía funcionar.

---

## 2 · LA RESTRICCIÓN QUE HACE QUE NO SEA UN CABLEADO TRIVIAL

**No conectes `perf.twr` al KPI.** Tenías razón en revertir. El comentario de
`InsightsKpiStrip.jsx:102-108` explica por qué, y es una decisión deliberada:

> *"La ventana va EN EL TÍTULO, no en el subtítulo: «Acumulado» a secas se lee como «desde
> siempre» y en realidad es el rango visible del gráfico (12 meses por defecto), que cambia en
> silencio con los tabs 1A/2A/5A/MAX. Sin el rótulo, este número se compara mentalmente contra
> el «Rendimiento anual» del Dashboard —que sí es toda la historia— y no hay forma de darse
> cuenta de que miden cosas distintas."*

O sea: **el KPI es de la ventana visible; `perf.twr` es de la ventana declarada por el backend.**
Son dos números distintos y los dos son correctos. Cablearlos sería exactamente el crimen de
esta familia con otra ropa: presentar un número medido sobre un período como si fuera de otro.

**Lo que hay que hacer es que el KPI lea su PROPIA serie completa** —la medida y la estimada—
en vez de sólo la mitad medida.

---

## 3 · QUÉ TIENE QUE PASAR

1. Cuando la ventana visible tiene puntos estimados, el KPI publica el acumulado **de esa
   ventana**, tomándolo de la clave que corresponda.
2. **El KPI tiene que decir de qué está hecho.** Un `+16,9%` en estimado no puede verse igual
   que un `+16,9%` medido: el chip del gráfico ya dice *"Recreado de tu contabilidad · desde
   … · no cuenta lo no vendido"*, y el KPI tiene que ser coherente con eso (en el `sub`, en el
   `label`, o como te parezca — pero no puede quedar mudo).
3. **En CERTERO no cambia nada.** Es la propiedad que más me importa de esta ronda: verificá
   que el KPI del modo certero da exactamente lo mismo antes y después, usuario por usuario.
4. Si la ventana visible **no** tiene ningún punto —ni medido ni estimado—, sigue el `"—"`,
   que ahí es correcto.

⚠️ **Ojo con el caso mixto.** Un usuario con tramo contable viejo + tramo medido nuevo tiene
puntos en las DOS claves dentro de la misma ventana. El acumulado de la ventana no es "el
último valor de una de las dos": tenés que decidir —y escribir en el código— cómo se compone,
y esa composición no puede encadenar contra el corte de regla (que es lo que la Fase 1 y tu
propio `idx_est` ya resuelven encadenando por base). Si el número honesto para ese caso es
"desde el último corte", decilo en pantalla.

---

## 4 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura.
- ❌ NO toques `schema_pg.sql`, `scripts/verificar_copia.py` ni el hook de `estampar_base` en
  `main.py`: es trabajo del auditor, ya verificado contra PostgreSQL real.
- **Copiá el harness a un directorio tuyo** antes de empezar (en la ronda anterior lo hiciste
  bien; en la Fase 1 se pisó la línea base del auditor y una medición comparó R2 contra R2).

### Instrumento — cinco trampas que ya cobraron en este proyecto

1. `git diff` mezcla varias capas sin commitear. Árboles de referencia:
   `.../scratchpad/pre1`, `.../scratchpad/r1tree`, `.../scratchpad/pre2`.
2. El campo del acumulado en `buildEvolutionFromSnapshots` es **`total`**, no `twrr` ni `value`.
3. `curva_indexada` publica el TWR **de la ventana declarada** (`ventana_desde`/`ventana_hasta`),
   no de todos los tramos: multiplicar todos da un número distinto y no es un bug.
   *(Yo medí "77 usuarios con el número mal" por esto. Eran 0.)*
4. `which` no es el inventario del entorno: hay PostgreSQL real vía el paquete pip **`pgserver`**.
5. Verificá los modos por **enumeración de call-sites**, no por grep de `modo=`.

### Datos

- Copia de producción **ya estampada**: `.../scratchpad/pico.db` (usá ésta — la cruda no tiene
  `base`/`apto`).
- Series clasificadas: `.../scratchpad/ab/all_series.json`.
- Usuarios testigo: **100% contable** → uid 12, 45, 107, 110. **Mixto** → uid 452.
  **100% medido** → cualquiera de los 185 con todas las filas aptas.

---

## 5 · CRITERIO DE SALIDA

1. El usuario 100% contable ve un número en ESTIMADO, **rotulado por lo que es**.
2. El KPI de CERTERO es idéntico al de antes, verificado usuario por usuario.
3. El caso mixto publica algo defendible y la pantalla dice sobre qué período.
4. Ninguna superficie publica un acumulado que encadene a través de un corte de regla.
5. **Lo viste en el browser**, en los dos modos, con un usuario contable y uno medido.

## 6 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line`.
2. Repro antes/después con salida real, y el A/B de CERTERO mostrando 0 diferencias.
3. Conjuntos de tests que fallan, antes y después, y su diferencia.
4. Capturas del browser de los dos modos.
5. 🔴 **"QUÉ NO VERIFIQUÉ"** al final. En las tres rondas anteriores lo hiciste bien y es lo que
   permitió encontrar rápido lo que faltaba — incluido este hueco, que señalaste vos.

---

## 7 · FUERA DE ALCANCE (anotado, no lo toques)

- El **clamp de plausibilidad** (uid 54 tiene un pico de US$5.704.671,93 sobre una cartera de
  US$9.334, en una fila que el clasificador acepta como medición). Es decisión de producto del
  dueño y no se arregla con un filtro de `apto`.
- Las **6 columnas** que `schema_pg.sql` todavía no tiene, y la regeneración con `mkschema.py`.
- El toggle en **ARS** (hoy `currency === 'USD'` lo gatea).
- El fixture de ronda 7 con una fila `import` a mitad de mes: es preexistente y no es producible,
  pero no lo arregles en esta ronda.
