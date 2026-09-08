# Handoff — las tandas de fix que quedan

**Arrancá por F2.** El resto del documento explica por qué, qué hay hecho y con qué método.

**Commit de referencia:** `f9fea04e` (main al 2026-09-08, con F1 y parte de F4 ya deployados).
Trabajá sobre `origin/main` actual, no sobre el commit de la auditoría — el código se movió.

---

## En una pantalla

Se auditó Rendi entera y salieron **222 hallazgos** con veredicto. Están agrupados por causa
raíz y ordenados en 7 tandas de fix en **`audit/01-calculos.md`** — ese es el documento que
tenés que leer, y es corto.

De las 7 tandas: **F1 completa y deployada**, **F4 a medias**. Quedan **F2, F3, F5, F6, F7**
más 3 ítems sueltos de F4.

| dónde | qué hay |
|---|---|
| `audit/01-calculos.md` | **el plan**: causas raíz, dependencias entre fixes, las 7 tandas, el veredicto |
| `audit/01_calculos/1a-*.md` | 8 informes de detalle — 94 divergencias con veredicto |
| `audit/01_calculos/1b-*.md` | 6 informes transversales — 128 hallazgos |
| `audit/01_calculos/1a-resumen.md` · `1b-resumen.md` | las dos tablas consolidadas |
| `audit/01_calculos/1a-evidencia.md` | qué está MEDIDO y qué DEDUCIDO, hallazgo por hallazgo |
| `audit/_fixes/F1-datos-a-limpiar.md` | los datos que quedaron mal y qué hacer con ellos |
| `audit/00-mapa-sistema.md` | el mapa del sistema, 3,4 MB — **no lo leas entero**, grepealo |

---

## Por qué F2 y no otra

**F2 es lo que sale de la app.** Cuatro hallazgos, todos publicados hacia afuera o hacia el
modelo de IA:

1. **La IA recibe el P&L de por vida duplicado ×2 exacto.** `RendiAI.jsx:170` y
   `AICoachDrawer.jsx:177` suman `pnl_realized` de todas las filas de `GET /api/monthly`, que
   incluye la fila sintética `broker='global'` **más** las por-broker. `Dashboard.jsx:243` tiene
   el `.filter(m => m.broker === 'global')` que falta, 70 líneas más arriba. Afecta también a
   `deposits_lifetime` y `withdrawals_lifetime`, así que **cualquier ratio que el modelo derive
   sale mal por partida doble**. Viaja en el contexto de CADA mensaje del chat.

2. **El prompt que rankea clientes recibe un retorno sin filtrar.** `main.py:35516` hace la
   misma lectura que `main.py:37073` pero **sin `_es_base_de_mercado`**. El propio código
   documenta el síntoma que ese filtro vino a matar («+39,6 % mientras su propia pantalla decía
   "—"»): se aplicó en un call site y no en el otro. **Es un fix de una línea, con el arreglo ya
   escrito en el mismo archivo.**

3. **El slide del Wrapped dice literalmente «Tu rendimiento TWR»** sobre una fórmula que no es
   TWR (le falta el `0,5·F` del denominador y va sobre base al costo). +10,0 % donde el motor
   mide +6,67 %; compuesto a doce meses, **+213,8 % contra +115,7 %**. `shareCard.js` lo exporta
   como PNG, o sea que **ese número sale de la app**. Si migrar el cálculo lleva tiempo, el
   RÓTULO se puede cambiar hoy sin tocar nada más.

4. **`Interés PF` se escapa de todos los filtros y de toda conversión.** No está en
   `_NATIVE_CCY_OPS` (`realized_pnl.py:78`) y nace con `fx_to_usd = NULL` (`main.py:9315`). Un
   plazo fijo de $10M a 30 días inyecta **US$328.767 falsos** en cinco pantallas y suma "una
   operación ganada" a los seis win rates. ⚠️ **Verificá primero si hay filas**: el código lo
   documenta como "hoy no muerde (0 filas)". Si sigue en 0, esto baja de urgente a estructural.

Las razones para empezar acá: **son pocos, están acotados, dos son casi de una línea, y son lo
único que se publica fuera de la app o alimenta al modelo.** Un número inflado en una pantalla
lo ve un usuario; un número inflado en el prompt le tuerce el consejo a todos.

---

## Las tandas, en orden

| tanda | nombre | estado |
|---|---|---|
| F1 | Que deje de escribir mal | ✅ **deployada** (`f9fea04e`) |
| **F2** | **Que la IA y lo que sale de la app no mientan** | **← empezá acá** |
| F3 | Un solo calendario | pendiente |
| F4 | Los guards que ya existen, en todos los lectores | 🟡 3 de 6 hechos |
| F5 | Una sola cotización, una sola política de faltantes | pendiente |
| F6 | Terminar las migraciones abiertas | pendiente |
| F7 | El modelo de datos | proyecto aparte, no es una tanda de fixes |

### Lo que quedó de F4, y por qué frené

Los tres los frené **a propósito**, no por falta de tiempo. En los tres el código contradecía al
plan, o la decisión es de producto:

- **Edad máxima del precio en `read_last_prices`.** El código dice textual: *"get_prices rellena
  huecos con el last-known SIN límite de edad (para valuar la cartera está bien; para escribir el
  costo de un lote 'de HOY' no)"*. La regla de 48 h existe a propósito sólo para escribir costos.
  **Decidir a qué edad un precio viejo deja de ser mejor que el costo es una decisión del
  founder**, no una propagación.
- **Guard de denominador peak en el hero del Dashboard.** El guard canónico de `evolution.js` es
  para *realized %*, no para retorno total, y el Dashboard no tiene el peak a mano. Es diseño
  nuevo sobre el número titular de la app.
- **Cota de plausibilidad en el P&L realizado.** Hoy no hay ninguna (medido: +188.566 % en una
  fila). El umbral es una decisión de producto y cambia números publicados.

---

## Las divergencias sin veredicto: 72

Los inputs están partidos por concepto en `audit/01_calculos/_grupos/<slug>.md`.

**Auditables ya (29):** bonos (13), CEDEAR (8), comisiones (8). Son clases de activo o conceptos
independientes de las tandas.

**Conviene esperar (43):** snapshot (11), TIR (9), dividendos (9), caja (7), variación diaria (7).
Dependen de la cadena que las tandas modifican; auditarlas ahora produce veredictos para rehacer.

---

## Lo que está pendiente del founder, no del código

1. **Medir el alcance en producción.** Hay 13 consultas de SOLO LECTURA que devuelven únicamente
   agregados, y un script autocontenido que las corre:
   `audit/01_calculos/1a-medir-alcance.py`. Producción es **SQLite** — usá
   `1a-alcance-produccion-sqlite.sql`, NO la versión Postgres (sus casts `::numeric` hacen fallar
   8 de 13). La más importante es **Q2**: cuenta las baselines de `capital_inicio` que todavía
   sobreviven, o sea lo único que se seguía perdiendo sin recuperación.
2. **Decidir la limpieza de datos.** `audit/_fixes/F1-datos-a-limpiar.md` tiene los 7 grupos, si
   son recalculables y el riesgo de cada uno. **Las baselines borradas no están en ninguna tabla:
   sólo salen de un backup.**
3. **Los tres ítems de F4** de arriba.
4. **Las preguntas abiertas** que cada informe de 1B lista en su encabezado, sin contestar.

---

## Método — lo que funcionó, y lo que no

Las dos reglas permanentes del repo (`CLAUDE.md`) salieron de esta auditoría. Respetalas: **la
causa raíz más frecuente del proyecto es un fix correcto aplicado en un solo call site.**

Y estas, que salieron de trabajar:

- **Un commit por causa raíz**, revertible solo. Nada de un commit por tanda.
- **Cada fix trae un test que FALLA con el código viejo.** Verificalo de verdad: revertir el
  commit entero también revierte el test, y entonces no probaste nada. Revertí sólo el archivo
  de código, dejando el test nuevo.
- **Baseline de fallos ANTES de tocar nada** (`pytest tests/ -q | grep ^FAILED | sort`) y
  comparación al final. El objetivo es cero fallos NUEVOS, no cero fallos.
- **Antes de dar un fix por terminado, grep de todos los call sites del mismo patrón**, y decir
  cuáles arreglaste y cuáles no.
- **El código gana sobre el mapa.** Se verificaron 290 citas: ~53 tenían la línea corrida y **5
  afirmaciones eran falsas**. Confirmá cada cita con grep antes de apoyarte en ella.
- **Un guard defensivo no es un parche.** Un `if qty == 0: return 0` puede ser exactamente lo
  correcto. Y si hay un comentario que justifica algo, leelo antes de reportarlo como bug.
- **Antes de una validación que RECHAZA, censo de callers Y de contratos.** No alcanza con los
  callers de Python: puede haber un test que fija una tolerancia deliberada. Me pasó.

### Dos trampas concretas que me costaron

- **Ojo con dónde insertás una función en `main.py`.** Metí un helper entre el decorador
  `@app.post(...)` y su función, y FastAPI registró el helper como endpoint. `/api/positions`
  habría quedado roto en producción. **No lo cazó la suite**, lo cazó el test que estaba
  escribiendo.
- **No testees contra tu propio criterio: testeá contra el motor real.** Escribí una función de
  ponderación comparándola con lo que yo creía correcto y estaba mal en un caso (cripto). Recién
  al ejecutar `compute_broker_value_usd` de verdad sobre una matriz de casos apareció.

---

## Coordinación — importante

**El 2026-09-08 hubo dos sesiones tocando el mismo código.** La otra deployó a `main` los fixes
de snapshots (A-1, A-2 y D-4) mientras esta rama los tenía sin mergear. Se detectó al chequear
antes de mezclar: **mergear a ciegas habría pisado su solución con una peor**.

Antes de mergear cualquier cosa: `git fetch && git log --oneline <tu-base>..origin/main`. Y si
hay overlap, comparen las dos soluciones antes de resolver el conflicto — no asumas que la tuya
es la buena.

---

## Estado del repo

- `main` = `f9fea04e`. F1 completa + 3 de F4, deployado.
- `audit/mapa-sistema` — el mapa y los informes, pusheada.
- `audit/trabajo-local-2026-09-07` — prompts e informes previos, pusheada.
- `fix/f1-deje-de-escribir-mal` y `fix/f4-guards-en-todos-los-lectores` — **obsoletas**, ya
  mergeadas vía `fix/auditoria-calculo`. No las uses de base.
- `worktree-f1/` — worktree local con un fixture de prueba (`backend/scripts/seed_f1.py`,
  usuario `f1@rendi.test`). Sirve para probar F1 a mano; el `README` del fixture está en el
  propio script.
