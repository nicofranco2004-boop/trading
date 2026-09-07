# Prompt — Vista de cuenta unificada (broker padre + sub-broker "· USD")

Copiá todo lo que sigue como primer mensaje del chat nuevo.

---

Vas a implementar la **vista de cuenta unificada** en Rendi: que el usuario entre a "Cocos" y vea
su cuenta en pesos y su sub-cuenta en dólares como UNA sola cuenta, como se la muestra el broker
real, en vez de dos tarjetas separadas.

## ⛔ REGLA CERO — hacé esto ANTES de escribir una sola línea

La sesión anterior perdió medio día de trabajo por saltearse este paso. Trabajó sobre una rama que
estaba **753 commits atrás de producción**, y de 8 fixes que hizo, 3 ya estaban resueltos en `main`
—uno de ellos mejor de lo que él lo hizo— y otro no aplicaba porque el archivo se había reescrito.

Corré esto y no sigas hasta que dé lo esperado:

```bash
cd /Users/nicolaspussetto/Documents/trading
git fetch origin
git rev-list --left-right --count origin/main...HEAD
```

- El **primer número** (commits que `origin/main` tiene y vos no) **tiene que ser 0**.
- Si no es 0, estás sobre una base vieja. Creá un worktree fresco y trabajá ahí:

```bash
git worktree add -b feat/cuenta-unificada ~/rendi-worktrees/cuenta-unificada origin/main
ln -s /Users/nicolaspussetto/Documents/trading/frontend/node_modules ~/rendi-worktrees/cuenta-unificada/frontend/node_modules
```

**No confíes en `main` local**: suele estar cientos de commits atrás de `origin/main`. La referencia
es siempre `origin/main` recién fetcheada.

Y antes de "arreglar" cualquier cosa, **verificá que el bug exista en `origin/main`**, no en tu
working tree:

```bash
git show origin/main:frontend/src/pages/Positions.jsx > /tmp/prod_Positions.jsx
```

Un `grep` que da 0 puede significar "ya está arreglado" **o** "el código se reestructuró y el bug
está en otro lado". Distinguí esos dos casos antes de tocar nada.

---

## El modelo de datos

- Tabla `brokers` con `(id, user_id, name, currency, parent_broker_id)`.
- Cuando un broker argentino opera en las dos monedas, el importador crea un **sub-broker**
  llamado `"<Padre> · USD"` (el separador es U+00B7), con `currency='USDT'` y `parent_broker_id`
  apuntando al padre. Lo crea `_ensure_usd_sibling` en `backend/main.py`.
- **CRÍTICO**: `positions`, `operations` y `monthly_entries` referencian al broker por **NOMBRE**
  (string), no por FK. El `parent_broker_id` sólo existe en la tabla `brokers`.

## La decisión de diseño, ya tomada

Hay un análisis completo en `ANALISIS_broker_unificado_2026-09-04.md`. El veredicto, resumido:

**NO fusiones las filas por ticker.** Fusionar lotes comprados en pesos con lotes comprados por
dólar-MEP produce un precio promedio sin unidad. Con 100 GGAL a ARS 1.000 y 50 GGAL a US$0,80, el
promedio fusionado da `100.040 / 150 = 666,93` — un número que no corresponde a ninguna compra que
el usuario haya hecho, y que además se imprime con un literal de moneda hardcodeado.

**Hacé la vista jerárquica**: UNA tarjeta por cuenta, un solo header, un solo total, y las filas
adentro **en su moneda nativa** con un chip `$` / `US$`. Pie de tabla con tres líneas:

```
Subtotal ARS      ARS 100.000
Subtotal USD      US$ 40
TOTAL             US$ 108,97   (o en pesos según el toggle)
```

Esto entrega el 90% de lo que el usuario pide ("entro y veo todo junto") **y conserva algo que él
creía que había que resacrificar: las filas siguen siendo editables**, porque cada una mantiene un
`p.broker` real y unívoco. No hace falta el modo de solo-lectura que él proponía.

Contraargumento por si aparece: ningún broker real muestra un renglón único tampoco — Cocos te
muestra AL30 y AL30D como dos líneas.

**Dato que refuerza la elección**: en la base de datos hay **cero casos** del mismo ticker presente
en las dos patas. La fila "mixta" es un caso teórico que hay que cubrir, no uno instanciado.

## Lo que ya existe y podés reusar

- `sortBrokersForDisplay` en `Positions.jsx` ya arma la relación padre→hijo y renderiza el
  sub-broker indentado bajo el padre. La tarjeta unificada es colapsar esas dos secciones en una.
- `computeBrokerValue` ya devuelve las dos monedas a la vez para un broker ARS. **Ojo**: en un
  broker USD, `valueArs`/`invArs` quedan en **0** (la rama USD no los toca), así que sumar el
  `valueArs` del padre con el del sibling da un total al que le falta la pata dólar entera. Vas a
  necesitar campos aditivos nuevos, o sumar en USD y convertir una sola vez al final.
- `broker_pair` en `backend/importing/persister.py` devuelve el par (padre + siblings). Es el
  helper canónico: usalo en vez de inventar una segunda definición de "qué es el par".
- El precedente de UI: la fila agregada multi-lote (`isAgg`) ya existe, con su toggle
  "Ver lotes / Ver agregado" y su menú recortado. El usuario ya conoce ese patrón.

## Los dos temas de FX que hay que resolver SÍ o SÍ

No los dejes para el final, porque definen la arquitectura:

1. **Qué tipo de cambio usa el total.** Las tenencias se valúan al **MEP** (`computeBrokerValue`),
   pero el toggle global de moneda de la app convierte al **BLUE**
   (`contexts/CurrencyContext.jsx`). Hoy no choca porque nadie suma las dos patas. En una tarjeta
   unificada vas a mostrar un total convertido y filas convertidas por otro criterio, y **no van a
   cerrar en la misma pantalla**. Unificá el criterio antes de dibujar nada.

2. **El costo mezcla dos convenciones.** La pata ARS aporta pesos nominales históricos; la pata USD
   aporta dólares reconvertidos al MEP de hoy (decisión deliberada del "FX-phantom fix": costo y
   valor se convierten al MISMO rate para que no aparezca P&L cambiario fantasma). Restar esos dos
   da un número que sirve para **mostrar un total**, no para un P&L contable. Decidilo explícitamente
   y documentalo.

## Bugs vivos en producción que tocan esto

Verificados contra `origin/main`. Ninguno lo introduce la unificación, pero todos se vuelven camino
principal con ella. Ordenados por relación costo/beneficio:

| bug | dónde | tamaño |
|---|---|---|
| La cuota del plan cuenta los sub-brokers como brokers reales | `backend/ai/plan.py`, dos `COUNT(*)` | **2 líneas** |
| La key de expansión de lotes no incluye el broker → expandir AL30 en IOL expande el de Balanz | `Positions.jsx`, `aggregateAndSort` | 1 línea |
| Borrar el broker padre tira `FOREIGN KEY constraint failed` y lo deja indeleteable | `backend/main.py`, `delete_broker` | acotado |
| Los reportes filtran por nombre exacto → el reporte de "IOL" deja afuera todo "IOL · USD" | `reporting/builder.py`, `timeline.py`, `main.py` | 16 sitios |

**El de la cuota es el más urgente en relación al esfuerzo**: un usuario Plus con 2 brokers reales
cuenta 4 (porque los siblings suman) y **no puede crear el tercer broker que pagó**.

Los detalles de los cuatro, con las trampas de cada uno, están en `HANDOFF_fase0_06.md`.

## Lo que YA se arregló — no lo rehagas

- **La suma de las filas ≠ el TOTAL del broker** (commit `ef4c05d0`, ya en producción). La fila
  agregada ahora suma sus lotes en vez de re-valuarse como una posición sola.
- **El toggle "Ver lotes" por fila** — producción ya usa `rowKey`.
- **Los símbolos `.BA` del sub-broker** — producción ya tiene `buildPriceSymbols(pos, bkrs)`, un
  helper compartido. Si te tienta escribir el patrón inline, usá ese.

## Una deuda que vas a chocar

`Positions.jsx` tiene sus propias `calcUSDT`/`calcARS` mientras `valuation.js` exporta
`valuePositionLot`, que es la que usa `computeBrokerValue` para el total. **Son dos
implementaciones paralelas de las mismas reglas**, sincronizadas a mano. Es el origen del
"P&L Dashboard ≠ Cartera" que viene mordiendo hace meses.

Si la tarjeta unificada va a sumar totales de dos cuentas, esta deuda te va a morder. Evaluá hacer
que las filas usen `valuePositionLot` **antes** de construir encima. No es obligatorio para la
feature, pero sí es la diferencia entre "esta vez los números coinciden" y "no pueden diferir".

## Cómo verificar (y tres formas de engañarte a vos mismo)

- **Tests**: `cd frontend && npx vitest run` (≈1433 pasando hoy) y `npx vite build`. Backend:
  `cd backend && python3 -m pytest tests/ -q -p no:randomly --timeout=120`. La suite tiene ~25
  fallas preexistentes, la mayoría `database is locked` bajo carga. **Guardá la lista de fallas
  ANTES de tocar nada** y compará conjuntos, no totales.

- **No hagas DDL sobre la base de tests.** Es una sola para toda la sesión (`tests/conftest.py`).
  Reconstruir una tabla por test dispara `database is locked` en archivos que no tienen nada que
  ver. Si hace falta, una vez por clase y revertido en `tearDownClass`.

- **No verifiques un test de regresión con `git stash`** si el fix ya está commiteado: no hay nada
  que stashear, `stash` devuelve 0 igual, y parece que revirtió cuando no revirtió nada. Revertí el
  archivo a mano y confirmá que el test **falla** antes de creerle.

- **No corras dos suites de tests a la vez.** Compiten por CPU y los `database is locked` se
  disparan; vas a comparar contra un baseline contaminado.

- **El preview del agente no puede levantar el backend** (el sandbox no lee las dependencias de
  Python: `PermissionError` con uvloop/h11). Hay configs `fase0-backend` / `fase0-frontend` en
  `.claude/launch.json` apuntando a 8005/5216 — el 8000 lo ocupa otro worktree. Si necesitás verlo
  corriendo, pedile al usuario que las levante él.

## Alcance

Empezá por **la tarjeta unificada en el desktop** (`Positions.jsx`), detrás de un flag de build
para poder apagarla sin revertir código. Mobile y la propagación al resto de las pantallas
(Dashboard, Insights, Reportes) son fases siguientes: si el total unificado vive sólo en Cartera,
el resto va a seguir mostrando las cuentas separadas y el usuario va a ver dos números distintos
para lo mismo. Decidí explícitamente qué hacés con eso y decíselo al usuario.

Antes de escribir código, mostrale el plan por fases y confirmá el alcance.
