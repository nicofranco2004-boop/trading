# FASE 2 — El toggle honesto

Sos el chat IMPLEMENTADOR. La Fase 1 está cerrada y verificada: ningún lector publica un
porcentaje con una punta al costo. Esta fase es lo contrario: **hacer que el modo contable
empiece a publicar un número que hoy no publica**, sin reabrir lo que la Fase 1 cerró.

---

## 0 · LA DECISIÓN DEL DUEÑO (sus palabras, no las mías)

> Un **toggle en el gráfico de rendimiento vs benchmarks** donde **el usuario elige qué ver**:
> el **contable**, que Rendi reconstruye por FIFO histórico —más historial, pero aproximado y
> con riesgo de error porque no se tienen bien los datos hacia atrás—, o el **certero**, que
> toma sólo los valores realmente medidos (~2 años) —menos historial, pero el número está bien—.
> *"Si quiere ver mayor cantidad de tiempo pero con el riesgo de que tenga algún tipo de error,
> o menos cantidad de tiempo pero certero"*, y que lo vaya cambiando sobre la marcha.

**El usuario elige. No elegimos por él.** Ése es el punto de la fase.

---

## 1 · EL PROBLEMA, MEDIDO

El toggle **ya existe** y hoy **no sirve para nada**. Medido sobre los 822 usuarios de la copia
de producción, corriendo `twr.serie_medible` en los dos modos:

```
598 usuarios      ESTIMADO dibuja MÁS puntos que CERTERO   → la línea se alarga
  0 usuarios      ESTIMADO les da un `medible` que no tenían → EL NÚMERO NUNCA CAMBIA
331 usuarios      sin `medibles` en NINGUNO de los dos modos → ven "—" pongan donde pongan el toggle
822 de 822        idéntico conteo de `medibles` en los dos modos
```

O sea: hoy el toggle cambia **cuánta línea ves** y nada más. Los 331 que no pueden medir nada
ven "—" en las dos posiciones. Para ellos el toggle es decorativo.

**La Fase 2 es hacer que ESTIMADO publique el rendimiento acumulado contable.**

---

## 2 · LA REGLA — qué puede y qué no puede publicar cada modo

El criterio es uno solo: **¿el número necesita el CAMINO de los precios, o le alcanza con las
PUNTAS?** Si le alcanzan las puntas, el contable lo puede afirmar. Si necesita el camino, no.

| métrica | qué necesita | ESTIMADO | EXACTO |
|---|---|---|---|
| Rendimiento acumulado | las puntas | **sí** | sí |
| La forma de la línea | las puntas | **sí** | sí |
| Rendimiento anualizado | las puntas + tiempo | **sí** | sí |
| Drawdown · máximo histórico | **el camino** | **no** | sí |
| Pico · "tu mejor momento" | **el camino** | **no** | sí |
| Volatilidad · rachas | **el camino** | **no** | sí |

Por qué esta línea: *"Aportaste US$100.000 y figurás en US$139.570"* la contabilidad lo puede
afirmar — son sus dos puntas. *"Caíste 47% desde tu máximo"* no puede, porque **ese máximo
nunca fue un precio: nadie le pagó eso nunca**. Ésa es exactamente la fila que produjo el bug
de las once rondas.

### ⚠️ LA TENSIÓN, Y CÓMO LA RESOLVEMOS (esto es una decisión, y es revisable)

El dueño quiere el toggle **sobre el gráfico vs benchmarks**, y una lectura estricta de la regla
diría que comparar un número contable contra el S&P es el crimen de la familia.

**Mi lectura, y con la que tenés que implementar salvo que el dueño diga otra cosa: la
comparación vs benchmark SÍ va en ESTIMADO.** El crimen de la familia es restar dos
**valuaciones** medidas con reglas distintas (mercado − costo = un escalón de regla disfrazado
de rendimiento). Comparar dos **retornos** sobre la misma ventana no es eso: cada uno se calcula
entero bajo su propia regla y después se contrastan.

**Pero tiene un sesgo sistemático que hay que declarar en pantalla**: el retorno contable
**no incluye lo no realizado hasta que se realiza** (`pnl_unrealized = 0` en toda la cadena).
Una cartera que se duplicó sin vender nada muestra ~0% contable. Comparar eso contra el S&P sin
avisarlo es engañoso — no por mezclar reglas, sino porque el contable **subestima por diseño**.

Entonces, en ESTIMADO, junto al gráfico vs benchmark: decir que la curva es **recreada** y que
**no cuenta las ganancias que todavía no vendiste**. Con eso el usuario puede leer la
comparación sabiendo hacia qué lado se equivoca.

Lo que **no** entra en ESTIMADO sigue siendo drawdown, pico, volatilidad y rachas: ésos sí
necesitan el camino, y la cadena contable no es un camino de precios.

---

## 3 · LO QUE YA EXISTE — no lo reinventes

- `twr.MODO_CERTERO` / `twr.MODO_ESTIMADO` (`twr.py:1033-1034`).
- `twr.serie_medible(conn, uid, desde, hasta, modo=...)` (`twr.py:1038`), que en ESTIMADO ya
  mete la cadena contable **a la línea, con `apto=False`** (`twr.py:1078-1084`).
- El endpoint `GET /api/insights/performance?bench=...&modo=...` (`main.py:11529`, `modo` en `:11536`).
- El estado del toggle en el frontend: `modoPerf` (`Insights.jsx:244`, default `'certero'`),
  que ya viaja al endpoint (`Insights.jsx:254`).
- De la Fase 1: `esApto` / `esDibujable` (`evolution.js:31,:43`), `sinBaseMedida` /
  `ytdSinBaseMedida`, y `diagnosticoSinMedicion` / `textoSinMedicion` (el estado vacío).
  **El texto del vacío en ESTIMADO va a tener que cambiar**: hoy dice "todavía no podemos
  medirlo", y en modo contable sí vamos a poder decir algo.
- El contrato de forma de la ronda 10: `serie_medible` devuelve `medibles` / `no_medibles` /
  `tramos`, **y no `puntos`** a propósito, para que el que se olvide de elegir se coma un
  `KeyError` en vez de publicar un número mezclado. Respetalo.

---

## 4 · LAS DOS MITADES VAN JUNTAS O NO VAN

Ésta es la trampa de esta fase, y es la misma que hizo volver el bug once veces.

1. **ESTIMADO tiene que EMPEZAR a publicar** el rendimiento acumulado contable (hoy publica
   `—` para 331 usuarios y no cambia el número para ninguno).
2. **ESTIMADO tiene que DEJAR de exponer** drawdown, pico, máximo histórico, volatilidad y
   rachas — que hoy llegan a la IA y a otras superficies **aunque la pantalla los tape**.

**Publicar el acumulado sin cortar el drawdown reabre el bug.** Si sólo hacés (1), le das a
331 usuarios una curva contable de la que el motor de drawdown va a sacar un pico que nunca fue
un precio, y volvemos a *"Su ganancia cayó 167% desde el mejor momento"*.

Sitios conocidos donde eso se publica hoy por debajo (verificados en el audit de la Fase 1):
`reporting/detectors.py:178` (`BEAT_BENCHMARK` dispara sobre `basis='contable'`),
`detectors.py:241` (`STREAK`, y `detect_reversal` en el mismo archivo),
`reporting/builder.py:1374` (la narrativa *"Quedaste X puntos por encima del S&P"*).
Barré vos si hay más — no asumas que ésos son todos.

---

## 5 · DÓNDE TRABAJÁS Y QUÉ NO PODÉS HACER

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala primero).
- ❌ NO toques lo que está en curso por otra vía: el camino de upgrade de `schema_pg.sql`, el
  preflight de `verificar_copia.py`, el reintento del hook de `estampar_base` y el clamp de
  plausibilidad. Eso lo está haciendo el auditor. Si tu cambio los roza, decilo y pará.

### ⚠️ Instrumento — cuatro trampas que ya cobraron

1. **El árbol tiene varias capas sin commitear.** `git diff` las muestra mezcladas y te va a
   hacer atribuirte trabajo ajeno. Los árboles de referencia están en
   `.../scratchpad/pre1` (pre-Fase-1) y `.../scratchpad/r1tree` (post-ronda-1).
2. **Copiá el harness a un directorio tuyo.** En la ronda 2 pisaste `scratchpad/ab/new_evolution.mjs`,
   que era la línea base del auditor, y eso hizo que una medición comparara R2 contra R2.
3. **El campo del rendimiento acumulado en `buildEvolutionFromSnapshots` es `total`**
   (`seriesUsd[].total`), no `twrr` ni `value`.
4. **`which` no es el inventario del entorno.** Hay PostgreSQL de verdad disponible vía el
   paquete pip **`pgserver`** (0.1.4) + `psycopg`. Si necesitás probar algo en Postgres, se
   puede: `import pgserver; srv = pgserver.get_server(pathlib.Path(dir)); srv.get_uri()`.

### Datos reales

- Copia de producción: `.../scratchpad/prod-0816.db` (822 usuarios, 40.717 filas).
- **Ya estampada** (columnas + `estampar_base` corrido): `.../scratchpad/pico.db` — usá ésta
  para cualquier cosa que dependa de `base`/`apto`, que en la copia cruda no existen.
- Series clasificadas: `.../scratchpad/ab/all_series.json`.

---

## 6 · CRITERIO DE SALIDA

1. **Los dos modos dicen cosas distintas y verdaderas.** Hoy dicen el mismo número con distinto
   largo de línea. Al terminar, ESTIMADO publica el acumulado contable y EXACTO no.
2. **La pantalla declara las limitaciones del exacto**: desde cuándo mide y qué porcentaje de
   la cartera cubre.
3. **La pantalla declara lo que el estimado no cuenta**: que es recreado y que no incluye lo no
   realizado.
4. **Ningún drawdown, pico, volatilidad ni racha sale de una serie contable** — ni en pantalla,
   ni por mail, ni dentro del prompt del LLM.
5. **Lo viste en el browser**, con un usuario de los 331 y con uno sano, en las dos posiciones
   del toggle.

---

## 7 · CÓMO VERIFICAR

- **Ejecutando, nunca leyendo.** Cada afirmación con su comando y su salida real.
- **Tu fixture tiene que PODER fallar.** Para esta fase: un usuario 100% contable (de los 331),
  uno mixto y uno 100% medido, y mostrar qué publica cada modo en los tres.
- **A/B contra producción**: cuántos usuarios ganan un número en ESTIMADO que hoy no tienen.
  Hoy son 0 y deberían ser ~331. Ése es el número que dice si la fase funcionó.
- **La suite no es determinista** y la completa muere en exit 144 al 23-28%. Compará
  **CONJUNTOS de nombres de tests**, nunca conteos.
- **Mutá**: revertí cada guard nuevo y confirmá que algo se pone rojo.
- El importador y el reconstructor **sólo escriben fin de mes** — un fixture con una fila
  `import` o `mtm_backfill` a mitad de mes no es producible.

## 8 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line`.
2. Repro antes/después de cada punto, con salida real.
3. Los conjuntos de tests que fallan, antes y después, y su diferencia.
4. Capturas del browser de los dos modos, con un usuario contable y uno medido.
5. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito y sin maquillar. En las dos rondas anteriores
   lo hiciste bien y fue lo que permitió encontrar rápido lo que faltaba.
