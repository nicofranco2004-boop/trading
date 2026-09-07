# LA SUITE + TRES ARREGLOS DEL TOGGLE

Sos el chat IMPLEMENTADOR. Las fases 1 y 2 están cerradas y auditadas.

Esta ronda son **dos partes independientes**:

- **PARTE A** (§1-§3) — recuperar la suite: la única herramienta que este proyecto no tuvo en
  siete rondas.
- **PARTE B** (§7) — tres cosas del gráfico que el dueño encontró **mirando la pantalla**, y
  que ningún test iba a agarrar.

Hacelas en ese orden: con la suite andando, la parte B se verifica sola.

---

## 1 · LA SUITE SÍ CORRE. Nunca fue el problema.

Durante siete rondas se dio por hecho que la suite completa *"muere en exit 144 al 23-28%"* y
toda la verificación se hizo sobre ~44 archivos de alcance. **Es falso, y la causa es tonta.**

`pytest` a secas colecta también `backend/scripts/`, donde hay **tres archivos que se llaman
`test_*.py` y NO son tests** — son scripts para correr a mano:

```
scripts/test_bot_profile_boundaries.py     ← :35  def fail(msg): ...; sys.exit(1)   (no es assert)
scripts/test_emails.py                     ← 🔴 puede MANDAR MAILS DE VERDAD
scripts/test_proration_edge_cases.py
```

Son 47 pseudo-tests: **3.756 con ellos, 3.709 sin ellos.**

**El comando correcto es `python3 -m pytest tests/` y tarda 52 segundos.**

⚠️ Y por qué nadie lo diagnosticó: todos la corrían con `| tail`, y pytest **no escribe nada
hasta terminar**; al morir no quedaba rastro del punto de caída. Escribiendo directo a archivo
con `-x`, el test asesino aparece en la primera corrida:

```bash
SECRET_KEY=x python3 -m pytest tests/ -q --tb=no > suite.log 2>&1
```

### El baseline, ya medido (conjuntos de nombres, no conteos)

```
pre-Fase-1              46 failed · 3543 passed · 93 skipped · 10 xfailed
con todo el trabajo     46 failed · 3560 passed · 93 skipped · 10 xfailed
conjuntos: 0 rotas · 0 arregladas   → las 46 son PREEXISTENTES
```

---

## 2 · LAS 46 NO SON RUIDO CONOCIDO

Se agrupan en 11 archivos, y la concentración dice algo:

```
10  test_snapshots_job.py      ← el cron que escribe los snapshots
 9  test_events.py
 7  test_news.py
 7  test_ai_builders_phase2.py
 3  test_bond_conduit.py
 3  test_billing.py            ← plata
 2  test_importer.py
 2  test_balanz_tenencia.py
 1  test_cedear_usd_price.py · test_billing_lifecycle.py · test_backfill_recompute.py
```

**Las 10 del cron son todas el mismo error, y ya lo diagnostiqué:**

```
snapshots_job.py:758: sqlite3.OperationalError: table snapshots has no column named source
```

El fixture (`tests/test_snapshots_job.py:325`) crea `snapshots` con
`id, user_id, date, total_value, total_invested, net_deposited, fx_to_usd_blue, holdings_json,
base, apto` — **y sin `source`**, que existe desde el 2026-08-06. El INSERT real del cron la
nombra, así que **el cron no puede escribir en su propio test**.

Lo irónico: ese fixture SÍ se actualizó en la ronda 11 (por eso tiene `base` y `apto`) y lleva
un ⚠️ escrito al lado que dice *"sin esto el fixture no refleja el schema real"*. Le agregaron
dos columnas y se olvidaron de una tercera que ya estaba.

**Consecuencia: el cron —el componente en el centro de todo lo que se arregló estas siete
rondas— no tiene cobertura de tests desde agosto.** Nadie lo vio porque la suite no corría.

Ésta es la TERCERA instancia de la misma familia en este proyecto: un esquema que no recibe las
columnas nuevas. Las otras dos fueron `schema_pg.sql` (sin ningún `ALTER`, ya arreglado
haciendo que `mkschema.py` emita 500 `ADD COLUMN IF NOT EXISTS`) y la migración de SQLite.

---

## 3 · QUÉ HACER

### 3.1 Sacar los scripts de la colección
Que `pytest` a secas no pueda ejecutarlos. Un `pytest.ini` con `testpaths = tests`, renombrarlos
a `check_*.py`, o lo que te parezca — pero **el criterio de salida es que correr `pytest` a
secas en este repo no pueda mandar un mail**. Verificalo ejecutando, no leyendo.

### 3.2 Arreglar el fixture del cron y ver qué queda abajo
Agregarle `source` al fixture de `test_snapshots_job.py:325`. **Después de eso, esos 10 tests
van a empezar a correr de verdad por primera vez desde agosto: puede que pasen, puede que
encuentren un bug real del cron.** Reportá cuál de las dos, con la salida.

⚠️ Revisá si hay OTROS fixtures con el mismo drift. `grep -rn "CREATE TABLE snapshots"
backend/tests/` y compará columna por columna contra el `CREATE TABLE` real de `init_db()`
(`main.py:~649`) y contra lo que nombra el INSERT del cron (`snapshots_job.py:758`).
Un fixture que no refleja el schema real no prueba nada — y no lo va a decir.

### 3.3 Triar las otras 36
Para cada archivo: ¿el test está podrido (fixture viejo, API que cambió, red externa) o está
encontrando un bug real? **No los arregles todos.** Lo que hace falta es la clasificación, con
evidencia, para que el dueño decida. Mirá primero:
- `test_billing.py` / `test_billing_lifecycle.py` (4) — es plata, y da `502 != 200`
- `test_events.py` / `test_news.py` (16) — huelen a red externa; si es eso, decilo y punto

### 3.4 Fijar el baseline para que no crezca en silencio
El objetivo es que la próxima ronda no tenga que redescubrir nada: que una falla NUEVA se note.
Un archivo con la lista de fallas conocidas y un test que compare conjuntos, o marcarlas
`xfail` con el motivo, o lo que sostengas. **Lo que NO sirve es un conteo** — la suite tiene
variación entre entornos y un número no distingue "se arregló una y se rompió otra".

---

## 4 · REGLAS

```
Worktree: /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama:     fix/reportes-guard-benchmark
```

- ❌ NO commitees, NO pushees. Pushear a `main` ES DEPLOYAR A PRODUCCIÓN.
- ❌ NO uses `git stash`. NO abras ninguna `.db` en escritura (copiala).
- ❌ NO toques `schema_pg.sql`, `scripts/mkschema.py`, `scripts/verificar_copia.py` ni el hook
  de `estampar_base` en `main.py`: los editó el auditor y están verificados contra PostgreSQL real.
- ⚠️ **Antes de correr cualquier cosa que escriba, respaldá.** Hay **siete rondas sin commitear**
  (46 archivos, 3.774 líneas). A mí `mkschema.py` me sobrescribió un archivo sin aviso y lo
  recuperé del respaldo.

### Instrumento — seis trampas que ya cobraron en este proyecto

1. `| tail` esconde por qué murió pytest. Escribí a archivo.
2. **`timeout` NO existe en macOS** — el comando falla y devuelve exit 0 sin correr nada.
3. `git diff` mezcla capas sin commitear. Árboles de referencia en `.../scratchpad/`:
   `pre1` (pre-Fase-1), `r1tree`, `pre2`, `pre2r2`.
4. `which` no es el inventario: hay PostgreSQL real vía el paquete pip **`pgserver`**.
5. Copiá el harness a un directorio tuyo antes de usarlo.
6. Compará **CONJUNTOS de nombres**, nunca conteos.

**Datos**: copia de producción ya estampada en `.../scratchpad/pico.db`.

---

## 5 · CRITERIO DE SALIDA

**Parte A**
1. `python3 -m pytest tests/` corre entero y no puede mandar un mail.
2. El fixture del cron refleja el schema real, y está dicho si los 10 tests pasan o encontraron
   un bug.
3. Las 46 están clasificadas: podrido vs bug real, con evidencia por archivo.
4. Una falla nueva se nota sin que nadie tenga que acordarse de comparar a mano.
5. El conjunto de fallas conocidas no creció.

**Parte B**
6. El toggle queda en el MISMO lugar en los dos modos, y nada se sale de la tarjeta.
7. En estimado ninguna serie se llama "total" si no lo es.
8. El chip dice **"sólo cuenta lo que ya vendiste"** y se entiende en una lectura.
9. **Capturas del browser de los dos modos** — este bloque se juzga mirando, no leyendo.

## 6 · QUÉ ENTREGAR

1. Los cambios (**sin commitear**), con `file:line`.
2. El conjunto de fallas antes y después, y su diferencia.
3. La tabla de triaje de las 46.
4. 🔴 **"QUÉ NO VERIFIQUÉ"** al final, explícito y sin maquillar.

---

## 7 · PARTE B — tres cosas del gráfico, encontradas mirando la pantalla

El dueño abrió el local y encontró esto en cinco minutos. Los tres salen del mismo lugar:
**Análisis → Métricas → Performance**, con el toggle en Estimado.

Entorno listo: `http://localhost:5199`, usuario `demo.metricas@rendi.test` / `demo1234`
(backend en 8000 contra el `demo.db` de demo). La cuenta tiene 11 filas contables
(sep-2025 → jul-2026) + 45 medidas (jul → ago-2026): el caso mixto.

### 7.1 · El chip empuja el toggle fuera de la tarjeta

Medido en el browser, ventana de 840px:

```
ESTIMADO   chip de 404px  →  borde derecho del toggle en 813px   (se sale de la tarjeta)
CERTERO    chip más corto →  borde derecho en 744px
```

El chip y el toggle comparten renglón, y **como el texto cambia de largo según el modo, el
toggle se corre 69px al cambiarlo**. Un control que se mueve solo cuando lo tocás.

El chip tiene que ir en su propio renglón (o debajo del título) para que el toggle quede fijo
en los dos modos. `Insights.jsx:937-945` arma el chip; el toggle está en `:2602`.

### 7.2 · 🔴 En estimado, la línea "P/L total" NO es un total

Éste es el de fondo, y lo encontró el dueño razonando, no leyendo código.

El gráfico dibuja `Demo P/L total` y `Demo P/L realizado` como dos series. **En modo estimado
son casi la misma línea** (paths de 460 y 475 caracteres que comparten casi todo el trazado),
porque la cadena contable fuerza `pnl_unrealized = 0`: lo que se rotula "total" es realizado
con otro nombre.

Medido en la cuenta demo:

```
Σ realizado      =   +2.640     ← lo único que el estimado tiene
Σ no realizado   =  −54.147     ← afuera
TWR publicado    =  +16,25%
```

O sea: publica +16,25% en una cuenta que arrastra 54 mil de pérdida no realizada, y llama
"total" a un número que no lo es.

**El arreglo es de rótulo, no de cálculo**: en estimado, esa serie es el P/L **realizado**.
Renombrala y evaluá si la segunda línea sigue teniendo sentido o es redundante.

### 7.3 · El texto del chip tiene un doble negativo

Hoy dice **"no cuenta lo no vendido"** — dos negaciones en cuatro palabras. El dueño, que
escribió el producto, lo leyó como "no cuenta lo vendido" en la primera pasada. Es una
advertencia: si se puede leer al revés, no sirve.

**Texto elegido: "sólo cuenta lo que ya vendiste".** Es positivo, se entiende de una, y de
paso **acorta el chip**, que ayuda con §7.1. Aplicalo en los dos lugares:
`Insights.jsx:944` y `InsightsKpiStrip.jsx:128`.

### ⚠️ 7.4 · LO QUE NO HAY QUE HACER — y la pregunta que lo motiva

La pregunta natural al leer §7.2 es *"¿y por qué no sumamos el no realizado y listo?"*.
**No se puede, y no es una decisión de diseño: el dato no existe.** Medido en producción:

```
monthly_entries          : 34.032 filas
con pnl_unrealized != 0  :     84  (0,2 %)
y las 84 son de          : 2026-08  ← el mes en curso, escrito por `sync-unrealized`
```

Para saber el no-realizado de enero 2026 hace falta saber **qué tenía esa persona ese día** y
**a qué precio cotizaba ese día**. Eso es la **Fase 3** (la reconstrucción) y la **Fase 4**
(precios históricos de bonos y FCI), y es el problema de fondo de todo este proyecto.

**NO intentes calcularlo, estimarlo ni interpolarlo en esta ronda.** Un no-realizado inventado
para el pasado es exactamente el bug que las once rondas anteriores vinieron a matar: un
número que parece medido y no lo es.

## 8 · FUERA DE ALCANCE

- **El clamp de plausibilidad** — 21 de 95 alertas del asesor con un pico ≥5× la cartera.
  Espera decisión del dueño.
- **ARS** — la rama en pesos está guardada correctamente por la Fase 1 (`Insights.jsx:878`,
  por el hecho `_lastArs.mtm`), pero no se puede completar sin **snapshots por broker**, que
  hoy no existen: la tabla `snapshots` no tiene columna de broker y `arsMonthly` es un
  subconjunto. Afecta a **758 de 854 usuarios**, y es un cambio de modelo de datos, no una ronda.
- Fases 3 y 4 del plan original.
