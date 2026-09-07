# Handoff — auditoría del mapa del sistema

Paquete para trabajar sobre la auditoría **sin leer los 3,4 MB** de `audit/00-mapa-sistema.md`.

## Qué hay acá

| archivo | para qué |
|---|---|
| `audit/00-mapa-sistema.md` | el informe completo (28.586 líneas). Leerlo por tramos con `sed -n`, ver el índice más abajo |
| `audit/_listas/divergencias.md` | **166** casos donde el mismo concepto se calcula de más de una forma. **Empezá por acá** |
| `audit/_listas/hallazgos.md` | **659** hallazgos con severidad, área y cita |
| `audit/_listas/conceptos.md` | los **24** conceptos de negocio: 16 mapeados, 8 pendientes |
| `audit/_listas/preguntas-abiertas.md` | **328** preguntas para el founder, agrupadas por área |
| `audit/_listas/zonas-grises.md` | **289** cosas que se leyeron y no se pudieron explicar |
| `audit/_partes/` | las 51 partes crudas + los scripts de los workflows |

Los cinco archivos de `_listas/` son autocontenidos: no hace falta abrir el mapa grande para usarlos.

---

## El commit auditado

```
b74f450f2badf1a2b84e657551115a0595110e45
```

`origin/main` al 2026-09-05 11:30:24 -0300 — *"chore: sacar del repo los dos .md de análisis de la rama"*.

**Esto es producción**, no la copia de trabajo. Al momento de auditar, la rama checkouteada (`fix/fase0-broker-unificado`) estaba **622 commits atrás**: su `backend/main.py` tenía 18.539 líneas contra las 38.029 de producción, y encima convivían archivos untracked de septiembre —que sí existen en `origin/main`— con un backend de junio. Auditar eso habría documentado un sistema que nunca existió.

> ⚠️ **`origin/main` ya se movió.** Al 2026-09-07 apunta a `82fad6a0bce8144eeab0b74d7bfe91fae41b195f`, 1 commit adelante (*"feat(fci): los fondos de Ualá no estaban porque se llaman «Ualintec»"*, toca `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx` y agrega `backend/tests/test_fci_uala.py`). Todo lo que diga esta auditoría sobre esos tres archivos puede estar desactualizado. Antes de seguir, comprobá cuánto se movió:
>
> ```bash
> git fetch && git rev-list --count b74f450f..origin/main
> ```

### Recrear la copia limpia de solo lectura

Es la que leyeron todos los agentes. Se arma con `git archive`, que **no toca el working tree, el índice ni `.git`** — a diferencia de `git worktree add`:

```bash
DEST=/tmp/rendi-main && rm -rf "$DEST" && mkdir -p "$DEST" && git -C /Users/nicolaspussetto/Documents/trading archive b74f450f | tar -x -C "$DEST"
```

Verificación de que quedó idéntica: **1.126 archivos** y `backend/main.py` con **38.029 líneas**.

```bash
find /tmp/rendi-main -type f | wc -l && wc -l < /tmp/rendi-main/backend/main.py
```

**Path usado durante la auditoría** (scratchpad de la sesión, se purga):

```
/private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/8ec62656-b7d0-4338-ab44-356ae20024c9/scratchpad/rendi-main
```

Para leer el esquema de la base se copió ahí `backend/trading.db` (base de desarrollo, no versionada). Ojo: **esa base viene de una rama vieja** y le faltan tablas y columnas que el código de `b74f450f` sí crea. Como evidencia vale el código, no la base.

---

## Reglas de presupuesto

Salieron de medir cuatro corridas: 114 agentes, ~16,3 M tokens, tres límites de sesión agotados. Son instrucciones, no observaciones.

### 1. Presupuestá 350–500k tokens por agente, y no pases de 8 por corrida

El costo no lo marca la cantidad de agentes sino cuánto código lee cada uno. Medido en este repo:

| corrida | agentes | tokens | por agente | resultado |
|---|---:|---:|---:|---|
| inicial | 81 | 5,5 M | — | 17 terminados, límite agotado a los 41 min |
| tanda A | 16 | 5,4 M | ~340 k | 11 + 4 rescatados del disco |
| tanda B | 8 | 2,6 M | ~323 k | 8/8 |
| tanda C | 9 | 2,7 M | ~302 k | 8/9 |

**16 agentes consumen lo mismo que 81**: los dos casos agotan la ventana. Con 8 entra cómodo y queda margen para ensamblar.

> Una estimación de ~70k por agente —que es lo que parece razonable a priori— se equivoca por 5×. Si vas a lanzar N agentes sobre este repo, calculá `N × 400k` y comparalo con lo que te queda de ventana.

### 2. Que cada agente escriba su archivo a disco ANTES de devolver nada

Poné esto textual en el prompt:

> Escribí tu archivo markdown con la herramienta Write **antes** de devolver el objeto estructurado. Si te quedás sin tiempo, es preferible un archivo completo y una respuesta corta que al revés: el archivo es el entregable.

En la tanda A, 4 de los 5 agentes que el workflow reportó como *failed* ya tenían el archivo entero en disco. Sin esta instrucción se perdían. **Un agente que muere devolviendo no perdió el trabajo; uno que muere escribiendo, sí.**

Corolario: cuando un workflow reporte fallas, **mirá el disco antes de darlo por perdido**.

```bash
ls audit/_partes/
```

### 3. Nada de fase de verificación separada

El diseño original tenía una quinta fase donde 61 agentes a `effort: 'high'` releían cada documento y abrían 70 citas cada uno. Eso era **~45% del presupuesto total para producir cero contenido nuevo**, y se lo llevó puesto el primer límite.

Si querés verificar, hacelo **sobre las afirmaciones que sostienen una decisión concreta**, no sobre cada cita de cada documento. Entre cubrir el 100% sin verificar y el 50% verificado, gana la cobertura: una cita floja se chequea con un `grep` en diez segundos, una sección ausente no se chequea con nada.

### Y una que no es de presupuesto: ensamblá con `cat`, no con un agente

Concatenar markdown no necesita un LLM. Todo `audit/00-mapa-sistema.md` se arma con un `cat` de `audit/_partes/` en orden. Ojo en zsh: `for c in $ORD` no separa en palabras si `ORD` es un string — usá un array (`ORD=(a b c)`).

---

## Advertencias de confiabilidad

### Las citas no tuvieron verificación independiente

**Ninguna de las ~10.000 citas `archivo:línea` de este informe pasó por una segunda lectura.** Cada agente verificó las suyas al escribirlas (la regla del prompt era abrir la línea con `grep -n` o `sed -n` antes de citarla), pero eso no es lo mismo que una revisión adversarial: no hubo nadie que abriera la línea citada y comprobara que dice lo que el informe afirma, ni que intentara refutar las conclusiones.

**Cómo usarlas:** sirven para orientarte y encontrar el lugar. Antes de tomar una decisión —o de reportar un bug— confirmá con un `grep` en el commit auditado:

```bash
git show b74f450f:backend/main.py | sed -n '11149,11160p'
```

Esto vale especialmente para las 166 divergencias: son la lista más accionable y también la más costosa si una está mal.

### Hay 289 zonas grises

`audit/_listas/zonas-grises.md`. No son bugs: son lugares donde el código no alcanzó para decidir qué pasa, o donde hacía falta un dato de producción que la auditoría no tocó (la regla era read-only estricto: **no se hizo ningún SELECT sobre datos de usuarios**).

Si una conclusión del informe se apoya en una zona gris, el informe lo dice con `[I]` (inferido) en vez de `[V]` (verificado). **Respetá esa distinción**: un `[I]` es una hipótesis del auditor, no un hallazgo.

### Lo que falta

| qué | dónde retomarlo |
|---|---|
| **Sección 23 — barrido sistemático de código muerto** | falló tres veces por límite de sesión. Hay 254 candidatos incidentales en el mapa, pero recogidos de paso, sin método. El prompt está en `workflow.js`, id `23-muerto` |
| **8 conceptos de negocio** | inflación/UVA/CER, benchmark, objetivos, perfil, planes y cuotas, libro del asesor, brokers y sub-brokers, alertas. Ver `audit/_listas/conceptos.md` |
| **Verificación de citas** | no corrió sobre ninguna sección |

Para correr lo pendiente: copiá el patrón de `audit/_partes/workflow_C.js` cambiando el set `ELEGIDOS`. Los prompts completos de los 24 lectores y los 24 conceptos están en `audit/_partes/workflow.js`.

---

## Índice de `audit/00-mapa-sistema.md`

28.586 líneas. Las tres secciones de nivel 1 son `Rendi — Mapa del sistema` (1–21789), `Conceptos de negocio` (21790–26848) y `Material transversal` (26849–28587).

La columna **sub-bloques** dice cuántos encabezados de nivel 3 hay adentro — en los tramos de endpoints, uno por endpoint.

| sección | líneas | `sed -n` | sub-bloques |
|---|---|---|---:|
| **Rendi — Mapa del sistema** | 1–21789 | `sed -n '1,21789p' audit/00-mapa-sistema.md` | 791 |
| &nbsp;&nbsp;Advertencia previa: la copia de trabajo no es el sistema | 13–28 | `sed -n '13,28p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Cómo leer las marcas | 29–43 | `sed -n '29,43p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Estado de la auditoría | 44–93 | `sed -n '44,93p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;Índice | 94–104 | `sed -n '94,104p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;1. Stack, estructura e infraestructura | 105–573 | `sed -n '105,573p' audit/00-mapa-sistema.md` | 10 |
| &nbsp;&nbsp;Modelo de datos — núcleo de negocio | 574–1205 | `sed -n '574,1205p' audit/00-mapa-sistema.md` | 16 |
| &nbsp;&nbsp;Modelo de datos — asesor, alertas, TWR, precios | 1206–1218 | `sed -n '1206,1218p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;1. El corazón del B2B2C: `advisor_clients` | 1219–1299 | `sed -n '1219,1299p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;2. `user_broker_credentials` — la tabla más sensible | 1300–1350 | `sed -n '1300,1350p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;3. IOL Lab: `iol_lab_runs` y `iol_lab_token_log` | 1351–1387 | `sed -n '1351,1387p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;4. Operación grupal (block trade): `advisor_op_batches` + `advisor_op_batch_items` | 1388–1422 | `sed -n '1388,1422p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;5. Alertas del usuario retail: `alerts`, `alert_events`, `alert_symbol_state` | 1423–1489 | `sed -n '1423,1489p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;6. Alertas y brief del asesor: `advisor_groups`, `advisor_alerts`, `advisor_alert_state`, `advisor_alert_events`, `advisor_brief_log` | 1490–1567 | `sed -n '1490,1567p' audit/00-mapa-sistema.md` | 5 |
| &nbsp;&nbsp;7. Claim, link-requests, informes y marca: `advisor_claim_tokens`, `advisor_link_requests`, `advisor_reports`, `advisor_profile` | 1568–1652 | `sed -n '1568,1652p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;8. TWR: `twr_periods` | 1653–1710 | `sed -n '1653,1710p' audit/00-mapa-sistema.md` | 5 |
| &nbsp;&nbsp;9. Precios: `asset_price_history` vs `yfinance_cache` vs `asset_last_price` | 1711–1798 | `sed -n '1711,1798p' audit/00-mapa-sistema.md` | 5 |
| &nbsp;&nbsp;10. `broadcast_send_log` (`backend/main.py:1937-1942`) | 1799–1818 | `sed -n '1799,1818p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;11. Hallazgos transversales | 1819–1908 | `sed -n '1819,1908p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;12. Resumen de índices y claves (referencia rápida) | 1909–1941 | `sed -n '1909,1941p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;13. Lo que NO pude verificar | 1942–1952 | `sed -n '1942,1952p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Modelo de datos auxiliar: cache, mercado, auth, billing e importación | 1953–3049 | `sed -n '1953,3049p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;5. Autenticación, autorización, planes y cuotas | 3050–3642 | `sed -n '3050,3642p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;6. Endpoints de la API | 3643–3646 | `sed -n '3643,3646p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Endpoints (main.py 2680–5500) | 3647–4106 | `sed -n '3647,4106p' audit/00-mapa-sistema.md` | 27 |
| &nbsp;&nbsp;Endpoints (main.py 5500–8500) | 4107–4525 | `sed -n '4107,4525p' audit/00-mapa-sistema.md` | 16 |
| &nbsp;&nbsp;Endpoints (main.py 8500–11000) | 4526–4565 | `sed -n '4526,4565p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;Familia 1 — Posiciones | 4566–4756 | `sed -n '4566,4756p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Familia 2 — Plazos fijos | 4757–4967 | `sed -n '4757,4967p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;Familia 3 — Plata que se mueve | 4968–5327 | `sed -n '4968,5327p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;Endpoints (main.py 11000–13500) | 5328–5786 | `sed -n '5328,5786p' audit/00-mapa-sistema.md` | 24 |
| &nbsp;&nbsp;Endpoints (main.py 13500–16000) | 5787–6198 | `sed -n '5787,6198p' audit/00-mapa-sistema.md` | 24 |
| &nbsp;&nbsp;Endpoints (main.py 16000–18500) | 6199–6649 | `sed -n '6199,6649p' audit/00-mapa-sistema.md` | 19 |
| &nbsp;&nbsp;Endpoints (main.py 18500–21000) | 6650–7108 | `sed -n '6650,7108p' audit/00-mapa-sistema.md` | 23 |
| &nbsp;&nbsp;Endpoints (main.py 21000–26000) | 7109–7123 | `sed -n '7109,7123p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;El endpoint | 7124–7214 | `sed -n '7124,7214p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;Helpers de este tramo | 7215–7376 | `sed -n '7215,7376p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;Endpoints (main.py 26000–29000) | 7377–7863 | `sed -n '7377,7863p' audit/00-mapa-sistema.md` | 24 |
| &nbsp;&nbsp;Endpoints (main.py 29000–31500) | 7864–8312 | `sed -n '7864,8312p' audit/00-mapa-sistema.md` | 20 |
| &nbsp;&nbsp;Endpoints (main.py 31500–34000) | 8313–8935 | `sed -n '8313,8935p' audit/00-mapa-sistema.md` | 49 |
| &nbsp;&nbsp;Endpoints (main.py 34000–36000) | 8936–9495 | `sed -n '8936,9495p' audit/00-mapa-sistema.md` | 31 |
| &nbsp;&nbsp;Endpoints (main.py 36000–38100) | 9496–9787 | `sed -n '9496,9787p' audit/00-mapa-sistema.md` | 12 |
| &nbsp;&nbsp;07 · Motores de retorno: TWR, performance, P&L realizado, flujos | 9788–9803 | `sed -n '9788,9803p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;1 · `backend/twr.py` — el núcleo (2213 líneas) | 9804–10029 | `sed -n '9804,10029p' audit/00-mapa-sistema.md` | 8 |
| &nbsp;&nbsp;2 · `backend/performance.py` (285 líneas) | 10030–10049 | `sed -n '10030,10049p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;3 · `backend/realized_pnl.py` (141 líneas) | 10050–10115 | `sed -n '10050,10115p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;4 · `backend/flujos.py` (169 líneas) — ⚠️ CÓDIGO MUERTO | 10116–10139 | `sed -n '10116,10139p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;5 · `backend/ledger_replay.py` (314 líneas) — ⚠️ CÓDIGO MUERTO EN PRODUCCIÓN | 10140–10175 | `sed -n '10140,10175p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;6 · `backend/advisor_twr.py` (124 líneas) | 10176–10199 | `sed -n '10176,10199p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;7 · `backend/analysis_prep.py` (102 líneas) | 10200–10216 | `sed -n '10200,10216p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;8 · CLAMPS Y COTAS — inventario completo | 10217–10278 | `sed -n '10217,10278p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;9 · ⚠️ DUPLICACIÓN — el hallazgo principal | 10279–10412 | `sed -n '10279,10412p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;10 · Hallazgos ordenados por gravedad | 10413–10439 | `sed -n '10413,10439p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;11 · Cadena de llamadas — quién consume qué | 10440–10489 | `sed -n '10440,10489p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;12 · Evidencia secundaria: la base de desarrollo | 10490–10502 | `sed -n '10490,10502p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;13 · Lo que NO encontré (dicho explícitamente) | 10503–10513 | `sed -n '10503,10513p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Importación — pipeline, persistencia y reconstrucción | 10514–11081 | `sed -n '10514,11081p' audit/00-mapa-sistema.md` | 13 |
| &nbsp;&nbsp;9. Importación — parsers por broker (`backend/importing/parsers/`) | 11082–11596 | `sed -n '11082,11596p' audit/00-mapa-sistema.md` | 10 |
| &nbsp;&nbsp;Subsistema de IA | 11597–12141 | `sed -n '11597,12141p' audit/00-mapa-sistema.md` | 11 |
| &nbsp;&nbsp;11 · Facturación, suscripciones, trial y planes | 12142–12991 | `sed -n '12142,12991p' audit/00-mapa-sistema.md` | 15 |
| &nbsp;&nbsp;Producto Asesor (B2B2C) — "Plan Asesor" | 12992–13020 | `sed -n '12992,13020p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;1. El modelo de la relación asesor ↔ cliente | 13021–13122 | `sed -n '13021,13122p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;2. Los tres caminos de alta — los tres existen | 13123–13268 | `sed -n '13123,13268p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;3. ⚠️ Autorización — dónde se verifica que el cliente sea suyo | 13269–13439 | `sed -n '13269,13439p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;4. El "libro" | 13440–13551 | `sed -n '13440,13551p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;5. Grupos (`advisor_groups`) | 13552–13599 | `sed -n '13552,13599p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;6. Alertas de asesor (`advisor_alerts.py`) | 13600–13643 | `sed -n '13600,13643p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;7. Brief e Informe del período — son dos cosas distintas | 13644–13772 | `sed -n '13644,13772p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;8. Operaciones en lote (`advisor_op_batches`) | 13773–13849 | `sed -n '13773,13849p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;9. IA del libro (book-mode) | 13850–13882 | `sed -n '13850,13882p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;10. Cómo se ve la app cuando sos asesor | 13883–13908 | `sed -n '13883,13908p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;11. Diferencias con el producto retail | 13909–13927 | `sed -n '13909,13927p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;12. Qué está implementado, qué a medias, qué no está | 13928–14004 | `sed -n '13928,14004p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;13. Otras observaciones de código | 14005–14043 | `sed -n '14005,14043p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;14. Variables de entorno que toca el producto asesor | 14044–14059 | `sed -n '14044,14059p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Motores de análisis: reporting, behavioral, wrapped, objetivos, home | 14060–14092 | `sed -n '14060,14092p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;1. `reporting/builder.py` — el reporte de período | 14093–14320 | `sed -n '14093,14320p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;2. `reporting/detectors.py` — catálogo completo | 14321–14355 | `sed -n '14321,14355p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;3. `reporting/timeline.py` — el eje temporal | 14356–14407 | `sed -n '14356,14407p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;4. `behavioral.py` — los 12 detectores de comportamiento | 14408–14476 | `sed -n '14408,14476p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;5. `wrapped.py` — el resumen anual | 14477–14547 | `sed -n '14477,14547p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;6. `goals_diagnostic.py` — el progreso de un objetivo | 14548–14619 | `sed -n '14548,14619p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;7. `home/briefing.py` y `home/market.py` | 14620–14685 | `sed -n '14620,14685p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;8. ⚠️ Duplicación: la misma métrica calculada de más de una forma | 14686–14772 | `sed -n '14686,14772p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;9. Otros hallazgos verificados | 14773–14850 | `sed -n '14773,14850p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;10. Código muerto / sin callers | 14851–14870 | `sed -n '14851,14870p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;11. Lo que no encontré | 14871–14888 | `sed -n '14871,14888p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;14. Capa de precios y tipos de cambio | 14889–15626 | `sed -n '14889,15626p' audit/00-mapa-sistema.md` | 14 |
| &nbsp;&nbsp;Jobs, tareas programadas, alertas y procesos en segundo plano | 15627–16291 | `sed -n '15627,16291p' audit/00-mapa-sistema.md` | 17 |
| &nbsp;&nbsp;Servicios externos y APIs de terceros | 16292–16319 | `sed -n '16292,16319p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;Datos de mercado | 16320–16439 | `sed -n '16320,16439p' audit/00-mapa-sistema.md` | 5 |
| &nbsp;&nbsp;Noticias | 16440–16467 | `sed -n '16440,16467p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;IA | 16468–16500 | `sed -n '16468,16500p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;Pagos | 16501–16547 | `sed -n '16501,16547p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;Email y notificaciones | 16548–16574 | `sed -n '16548,16574p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;Integraciones de brokers ← lo más sensible | 16575–16641 | `sed -n '16575,16641p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;Frontend: scripts de terceros | 16642–16697 | `sed -n '16642,16697p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;Infraestructura (terceros que no son APIs de datos) | 16698–16743 | `sed -n '16698,16743p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Tabla resumen | 16744–16771 | `sed -n '16744,16771p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Lo que más me llamó la atención | 16772–16795 | `sed -n '16772,16795p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Frontend — Home, Cartera, Posiciones | 16796–16801 | `sed -n '16796,16801p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;0. Mapa de rutas: qué se monta REALMENTE en cada URL | 16802–16828 | `sed -n '16802,16828p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/` → `frontend/src/pages/Home.jsx` (desktop) | 16829–16851 | `sed -n '16829,16851p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/` (mobile) → `frontend/src/pages/HomeMobile.jsx` | 16852–16891 | `sed -n '16852,16891p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/posiciones` → `frontend/src/pages/Cartera.jsx` | 16892–16907 | `sed -n '16892,16907p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Tab "Posiciones" (desktop) → `frontend/src/pages/Positions.jsx` (4.484 líneas) | 16908–17023 | `sed -n '16908,17023p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;Tab "Posiciones" (mobile) → `frontend/src/pages/PositionsMobile.jsx` (2.972 líneas) | 17024–17094 | `sed -n '17024,17094p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;`/dashboard` → `frontend/src/pages/Dashboard.jsx` (1.550 líneas) | 17095–17162 | `sed -n '17095,17162p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/posiciones/:id` → `frontend/src/pages/PositionDetailMobile.jsx` | 17163–17175 | `sed -n '17163,17175p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/activo/:ticker` → `frontend/src/pages/AssetDetail.jsx` | 17176–17188 | `sed -n '17176,17188p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/buscar` → `frontend/src/pages/MobileSearch.jsx` | 17189–17201 | `sed -n '17189,17201p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;El número grande: cuál es exactamente y dónde se computa | 17202–17222 | `sed -n '17202,17222p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;El toggle de moneda: dónde vive, cómo se propaga, qué convierte | 17223–17259 | `sed -n '17223,17259p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;`StalePricesNotice` y `TcMissingBadge`: dónde el sistema admite que le falta un dato | 17260–17285 | `sed -n '17260,17285p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;Componentes de `components/home/` (11 archivos) | 17286–17307 | `sed -n '17286,17307p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Componentes de Cartera | 17308–17324 | `sed -n '17308,17324p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;Hallazgos, en orden de qué tan caro es cada uno | 17325–17347 | `sed -n '17325,17347p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Lo que no pude cerrar | 17348–17357 | `sed -n '17348,17357p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Frontend — Análisis: Métricas, Comportamiento, Reportes, Perfil, Objetivos | 17358–17405 | `sed -n '17358,17405p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;`/analisis` → `frontend/src/pages/Analisis.jsx` (129 líneas) | 17406–17431 | `sed -n '17406,17431p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/analisis?tab=diagnostico` → `frontend/src/pages/Insights.jsx` (4783 líneas) | 17432–17754 | `sed -n '17432,17754p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;`/analisis?tab=comportamiento` → `frontend/src/pages/Behavioral.jsx` (860 líneas) | 17755–17796 | `sed -n '17755,17796p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/analisis?tab=reportes` → `frontend/src/pages/Reports.jsx` (913 líneas) | 17797–17919 | `sed -n '17797,17919p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;`/perfil-inversor` → `frontend/src/pages/PerfilInversor.jsx` (28 líneas) | 17920–17959 | `sed -n '17920,17959p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/fundamentals` → `frontend/src/pages/Fundamentals.jsx` (170 líneas) | 17960–17986 | `sed -n '17960,17986p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/posiciones?tab=objetivos` → `frontend/src/pages/Goals.jsx` (677 líneas) | 17987–18017 | `sed -n '17987,18017p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/mensual` → `frontend/src/pages/Monthly.jsx` (9 líneas) → `MonthlySummary.jsx` (894) | 18018–18041 | `sed -n '18018,18041p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/wrapped` → `frontend/src/pages/Wrapped.jsx` (604 líneas) | 18042–18057 | `sed -n '18042,18057p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/bienvenida` → `frontend/src/pages/FirstInsight.jsx` (331 líneas) | 18058–18076 | `sed -n '18058,18076p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;`/i/:token` → `frontend/src/pages/ReportPublic.jsx` (286 líneas) | 18077–18119 | `sed -n '18077,18119p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Componentes compartidos — notas sueltas | 18120–18158 | `sed -n '18120,18158p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Resumen de hallazgos (prioridad descendente) | 18159–18184 | `sed -n '18159,18184p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Frontend — Operaciones, Importación, Novedades, Alertas | 18185–18212 | `sed -n '18185,18212p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;`/operaciones` → `frontend/src/pages/Operations.jsx` (1409 líneas) | 18213–18335 | `sed -n '18213,18335p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;`/imports` → `frontend/src/pages/Imports.jsx` (685 líneas) | 18336–18547 | `sed -n '18336,18547p' audit/00-mapa-sistema.md` | 12 |
| &nbsp;&nbsp;`/novedades` → `frontend/src/pages/Novedades.jsx` (121 líneas) | 18548–18671 | `sed -n '18548,18671p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;`/alertas` → `frontend/src/pages/Alertas.jsx` (50 líneas) + `components/alerts/AlertsManager.jsx` (481) | 18672–18729 | `sed -n '18672,18729p' audit/00-mapa-sistema.md` | 8 |
| &nbsp;&nbsp;`/mas` → `frontend/src/pages/More.jsx` (328 líneas) | 18730–18761 | `sed -n '18730,18761p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;`/ai` → `frontend/src/pages/RendiAI.jsx` (183) + `components/AICoach.jsx` (675) + `components/ai/` (11 archivos) | 18762–18824 | `sed -n '18762,18824p' audit/00-mapa-sistema.md` | 8 |
| &nbsp;&nbsp;Componentes sueltos del alcance | 18825–18902 | `sed -n '18825,18902p' audit/00-mapa-sistema.md` | 8 |
| &nbsp;&nbsp;Tabla resumen — endpoints por pantalla | 18903–18921 | `sed -n '18903,18921p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Hallazgos consolidados (lo notable, ordenado por gravedad) | 18922–18950 | `sed -n '18922,18950p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Frontend — Cuenta, config, admin, planes, onboarding, público | 18951–18972 | `sed -n '18951,18972p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;AUTENTICACIÓN | 18973–19018 | `sed -n '18973,19018p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;ONBOARDING | 19019–19043 | `sed -n '19019,19043p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;CONFIGURACIÓN | 19044–19123 | `sed -n '19044,19123p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;PLANES Y BILLING | 19124–19221 | `sed -n '19124,19221p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;ADMIN | 19222–19291 | `sed -n '19222,19291p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;LABORATORIO IOL | 19292–19307 | `sed -n '19292,19307p' audit/00-mapa-sistema.md` | 1 |
| &nbsp;&nbsp;NAVEGACIÓN | 19308–19357 | `sed -n '19308,19357p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;PÁGINAS PÚBLICAS (marketing, SEO, legales) | 19358–19410 | `sed -n '19358,19410p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;OTROS COMPONENTES DEL ALCANCE | 19411–19430 | `sed -n '19411,19430p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;Resumen de hallazgos de esta sección | 19431–19467 | `sed -n '19431,19467p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Frontend — el núcleo: `utils/`, `hooks/`, `contexts/`, `App.jsx` | 19468–19475 | `sed -n '19468,19475p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;1. `utils/api.js` — el único cliente HTTP | 19476–19548 | `sed -n '19476,19548p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;2. Inventario completo de `utils/` | 19549–19609 | `sed -n '19549,19609p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;3. Fichas de los utils con lógica financiera | 19610–19807 | `sed -n '19610,19807p' audit/00-mapa-sistema.md` | 16 |
| &nbsp;&nbsp;4. Hooks (`frontend/src/hooks/`) | 19808–19834 | `sed -n '19808,19834p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;5. Contexts (`frontend/src/contexts/`) | 19835–19891 | `sed -n '19835,19891p' audit/00-mapa-sistema.md` | 7 |
| &nbsp;&nbsp;6. `App.jsx` (416) y `main.jsx` | 19892–19903 | `sed -n '19892,19903p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;7. `utils/demo.js` (3223) — el modo demo | 19904–19944 | `sed -n '19904,19944p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;8. `utils/tickers.js` (629) — el catálogo | 19945–19978 | `sed -n '19945,19978p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;9. `utils/autoUpdate.js` (227) — recarga a bundle nuevo | 19979–20000 | `sed -n '19979,20000p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;10. `utils/safeUrl.js` (52) — para qué se creó | 20001–20011 | `sed -n '20001,20011p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;11. Hallazgos, rarezas y contradicciones | 20012–20054 | `sed -n '20012,20054p' audit/00-mapa-sistema.md` | 13 |
| &nbsp;&nbsp;12. Código muerto verificado | 20055–20079 | `sed -n '20055,20079p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;13. Cobertura de tests | 20080–20087 | `sed -n '20080,20087p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;14. Lo que no encontré | 20088–20097 | `sed -n '20088,20097p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Suite de tests y cobertura real | 20098–21080 | `sed -n '20098,21080p' audit/00-mapa-sistema.md` | 12 |
| &nbsp;&nbsp;Flujos end-to-end | 21081–21095 | `sed -n '21081,21095p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;1. Alta de usuario: registro → verificación → onboarding → primera cartera | 21096–21133 | `sed -n '21096,21133p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;2. Importar un archivo de broker | 21134–21232 | `sed -n '21134,21232p' audit/00-mapa-sistema.md` | 9 |
| &nbsp;&nbsp;3. Subir una "foto" de tenencia y cómo convive con el historial | 21233–21271 | `sed -n '21233,21271p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;4. Alta manual de una compra y todo lo que se recalcula | 21272–21309 | `sed -n '21272,21309p' audit/00-mapa-sistema.md` | 2 |
| &nbsp;&nbsp;5. Ver la cartera | 21310–21384 | `sed -n '21310,21384p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;6. Vender un activo | 21385–21427 | `sed -n '21385,21427p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;7. Un día de mercado | 21428–21497 | `sed -n '21428,21497p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;8. Suscribirse a un plan | 21498–21549 | `sed -n '21498,21549p' audit/00-mapa-sistema.md` | 5 |
| &nbsp;&nbsp;9. Pedirle un análisis a la IA | 21550–21591 | `sed -n '21550,21591p' audit/00-mapa-sistema.md` | 4 |
| &nbsp;&nbsp;10. Un asesor da de alta a un cliente y mira su cartera | 21592–21658 | `sed -n '21592,21658p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;11. Borrar algo | 21659–21773 | `sed -n '21659,21773p' audit/00-mapa-sistema.md` | 8 |
| &nbsp;&nbsp;Anexo: contradicciones y rarezas que crucé al trazar | 21774–21789 | `sed -n '21774,21789p' audit/00-mapa-sistema.md` |  |
| **Conceptos de negocio** | 21790–26848 | `sed -n '21790,26848p' audit/00-mapa-sistema.md` | 96 |
| &nbsp;&nbsp;Tenencia / posición / holding | 21814–22124 | `sed -n '21814,22124p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Costo de adquisición, costo promedio y lotes FIFO | 22125–22377 | `sed -n '22125,22377p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Valuación de cartera / valor de mercado | 22378–22710 | `sed -n '22378,22710p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;P&L realizado | 22711–23045 | `sed -n '22711,23045p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;P&L no realizado / ganancia latente | 23046–23307 | `sed -n '23046,23307p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Rendimiento / retorno (simple, TWR, anualizado, CAGR) | 23308–23637 | `sed -n '23308,23637p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;TIR / IRR / XIRR / retorno ponderado por dinero | 23638–23955 | `sed -n '23638,23955p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Capital aportado, flujos de fondos, depósitos y retiros | 23956–24283 | `sed -n '23956,24283p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Caja / cash / saldo disponible | 24284–24588 | `sed -n '24284,24588p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Tipo de cambio (blue, MEP, CCL, cripto) y conversión de moneda | 24589–24944 | `sed -n '24589,24944p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Comisiones, impuestos y costos de transacción | 24945–25231 | `sed -n '24945,25231p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Dividendos, cupones, rentas y amortizaciones | 25232–25551 | `sed -n '25232,25551p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Variación diaria / periódica y evolución | 25552–25877 | `sed -n '25552,25877p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Snapshot / foto histórica de la cartera | 25878–26233 | `sed -n '25878,26233p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;Bonos: escala per-100, paridad, vencimiento y flujos | 26234–26559 | `sed -n '26234,26559p' audit/00-mapa-sistema.md` | 6 |
| &nbsp;&nbsp;CEDEAR: ratio, split, valuación y pata en dólares | 26560–26848 | `sed -n '26560,26848p' audit/00-mapa-sistema.md` | 6 |
| **Material transversal** | 26849–28587 | `sed -n '26849,28587p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;Implementaciones divergentes | 26851–27024 | `sed -n '26851,27024p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Hallazgos transversales | 27025–27698 | `sed -n '27025,27698p' audit/00-mapa-sistema.md` | 3 |
| &nbsp;&nbsp;Código posiblemente muerto | 27699–27958 | `sed -n '27699,27958p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Zonas grises — lo que no se pudo explicar | 27959–28251 | `sed -n '27959,28251p' audit/00-mapa-sistema.md` |  |
| &nbsp;&nbsp;Preguntas abiertas | 28252–28587 | `sed -n '28252,28587p' audit/00-mapa-sistema.md` |  |

---

## Índice de `audit/_partes/`

Las partes crudas, tal como las escribió cada agente, antes de concatenarlas. Útiles para leer un subsistema entero sin abrir el mapa.

| archivo | líneas | contenido |
|---|---:|---|
| `01-stack-infra.md` | 466 | Stack, frameworks y versiones; build y deploy (Railway/Vercel); árbol de carpetas; inventario de variables de entorno; motor de base y el shim de Postgres; scripts de arranque y mantenimiento |
| `02-datos-core.md` | 629 | Tablas del núcleo de negocio: users, brokers, positions, archived_positions, operations, monthly_entries, snapshots, goals, plazos_fijos, futures_positions, config, deleted_ops_journal |
| `03-datos-asesor.md` | 744 | Las 22 tablas advisor_*, alerts/alert_events/alert_symbol_state, twr_periods, asset_price_history, user_broker_credentials, iol_lab_*, broadcast_send_log |
| `04-datos-aux.md` | 1094 | Tablas auxiliares: cache de precios y noticias, FX, billing, trial, verificación de email, importación (import_*), FCI. Incluye la clasificación cache vs. fuente de verdad |
| `05-auth.md` | 590 | Tokens y cookies, invalidación de sesión, admin, rate limiting, los tiers y qué desbloquea cada uno, trial, y la autorización asesor↔cliente |
| `0601-endpoints-2680-5500.md` | 457 | Endpoints de `backend/main.py` líneas 2680–5500: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0602-endpoints-5500-8500.md` | 416 | Endpoints de `backend/main.py` líneas 5500–8500: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0603-endpoints-8500-11000.md` | 799 | Endpoints de `backend/main.py` líneas 8500–11000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0604-endpoints-11000-13500.md` | 456 | Endpoints de `backend/main.py` líneas 11000–13500: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0605-endpoints-13500-16000.md` | 409 | Endpoints de `backend/main.py` líneas 13500–16000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0606-endpoints-16000-18500.md` | 448 | Endpoints de `backend/main.py` líneas 16000–18500: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0607-endpoints-18500-21000.md` | 456 | Endpoints de `backend/main.py` líneas 18500–21000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0608-endpoints-21000-26000.md` | 265 | Endpoints de `backend/main.py` líneas 21000–26000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0609-endpoints-26000-29000.md` | 484 | Endpoints de `backend/main.py` líneas 26000–29000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0610-endpoints-29000-31500.md` | 446 | Endpoints de `backend/main.py` líneas 29000–31500: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0611-endpoints-31500-34000.md` | 620 | Endpoints de `backend/main.py` líneas 31500–34000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0612-endpoints-34000-36000.md` | 557 | Endpoints de `backend/main.py` líneas 34000–36000: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `0613-endpoints-36000-38100.md` | 289 | Endpoints de `backend/main.py` líneas 36000–38100: ficha por endpoint (auth, params, tablas, efectos) + helpers del tramo |
| `07-retorno.md` | 723 | Motores de retorno: twr.py, performance.py, realized_pnl.py, flujos.py, ledger_replay.py, advisor_twr.py. Fórmulas, clamps de plausibilidad y duplicación entre motores |
| `08-importing-pipeline.md` | 565 | Pipeline de importación end-to-end, esquema normalizado, persistencia e idempotencia, rebuild/recompute y qué pisa a qué, tenencia (modo foto), invariantes y validator |
| `09-importing-parsers.md` | 512 | Los 17 parsers de broker: registry y detección, tabla maestra por broker, dirección del movimiento, monedas, y la duplicación de helpers entre parsers |
| `10-ai.md` | 542 | Proveedor y model ids, registry de builders, prompts y qué datos del usuario salen hacia el LLM, cache, cuota, y las tools con las que el modelo escribe en la base |
| `11-billing.md` | 847 | Procesadores (Rebill, MercadoPago), catálogo de planes, ciclo de vida de la suscripción, webhooks y su validación, créditos y prorrateo, trial, emails transaccionales |
| `12-asesor.md` | 1065 | Producto asesor B2B2C: relación asesor↔cliente, los tres caminos de alta, autorización por endpoint, el libro, grupos, brief e informes, operaciones en lote |
| `13-analitica.md` | 826 | reporting/builder.py, detectors, timeline, behavioral.py, wrapped, goals_diagnostic, home/briefing y home/market |
| `14-precios-fx.md` | 735 | Fuente de precio por tipo de activo con fallbacks y TTL; todos los dólares del sistema y la tabla de decisión de cuál se usa en cada contexto; bonos per-100; FCIs |
| `15-jobs.md` | 662 | Jobs programados y su schedule, dónde corre el scheduler, trabajo en background por request, snapshots_job, alerts_engine, backfills y estado de la migración a Postgres |
| `16-externos.md` | 501 | Ficha por servicio externo (yfinance, data912, argentinadatos, dolarapi, CAFCI, RSS, Anthropic, Resend, MercadoPago, Rebill, IOL, Wallbit) con criticidad y fallback |
| `17-front-cartera.md` | 559 | Home, HomeMobile, Dashboard, Cartera, Positions, PositionsMobile, PositionDetailMobile, AssetDetail: qué muestran, de dónde y qué calcula el browser |
| `18-front-analisis.md` | 824 | Analisis, Insights, Reports, Behavioral, Monthly, Fundamentals, Goals, Wrapped, PerfilInversor, ReportPublic y los componentes de reportes/perfil/diagnóstico |
| `19-front-ops.md` | 763 | Operations, Novedades, Events, News, Imports, Alertas, RendiAI; ImportWizard paso a paso, alta manual, plazos fijos, cupones y el chat de IA |
| `20-front-cuenta.md` | 514 | Login, onboarding, Config, Admin (todas las acciones), Planes, BillingReturn, IolLab, navegación (Sidebar y tab bar) y las páginas públicas de marketing |
| `21-front-nucleo.md` | 627 | utils/ con la lógica financiera del cliente (valuation, insightsModel, diagnostics, bondSchedule, fx…), hooks, contexts, api.js, modo demo y allowlist de tickers |
| `22-tests.md` | 980 | Cómo se corre la suite, inventario de los 241 tests de backend y 55 de frontend, agujeros de cobertura, tests que no atraviesan la ruta real, fixtures y ausencia de CI |
| `24-flujos.md` | 706 | Los 11 flujos end-to-end trazados frontend→API→motor→DB, con cita en cada paso y las bifurcaciones importantes |
| `30-concepto-bonos.md` | 323 | Concepto **bonos**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-caja.md` | 302 | Concepto **caja**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-capital-aportado.md` | 325 | Concepto **capital-aportado**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-cedear.md` | 286 | Concepto **cedear**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-comisiones.md` | 284 | Concepto **comisiones**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-costo.md` | 250 | Concepto **costo**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-dividendos.md` | 317 | Concepto **dividendos**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-fx.md` | 353 | Concepto **fx**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-pnl-no-realizado.md` | 259 | Concepto **pnl-no-realizado**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-pnl-realizado.md` | 332 | Concepto **pnl-realizado**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-rendimiento.md` | 327 | Concepto **rendimiento**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-snapshot.md` | 353 | Concepto **snapshot**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-tenencia.md` | 308 | Concepto **tenencia**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-tir.md` | 315 | Concepto **tir**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-valuacion.md` | 330 | Concepto **valuacion**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `30-concepto-variacion.md` | 323 | Concepto **variacion**: definición según el código, todos los sitios de cálculo con la fórmula literal, dónde se lee y se persiste, implementaciones divergentes |
| `repo_meta.txt` | 19 | Metadatos del repo al momento de auditar: commit, conteo de commits por mes, ramas, autores |
| `wf_deadCode.dedup.txt` | 254 | Lista cruda acumulada y deduplicada de deadCode (insumo de `audit/_listas/`) |
| `wf_deadCode.txt` | 138 | Lista cruda de deadCode sin deduplicar (superseded por la .dedup) |
| `wf_definiciones.txt` | 16 | Lista cruda de definiciones sin deduplicar (superseded por la .dedup) |
| `wf_divergencias.txt` | 166 | Lista cruda de divergencias sin deduplicar (superseded por la .dedup) |
| `wf_hallazgos.dedup.txt` | 659 | Lista cruda acumulada y deduplicada de hallazgos (insumo de `audit/_listas/`) |
| `wf_hallazgos.txt` | 409 | Lista cruda de hallazgos sin deduplicar (superseded por la .dedup) |
| `wf_preguntas.dedup.txt` | 328 | Lista cruda acumulada y deduplicada de preguntas (insumo de `audit/_listas/`) |
| `wf_preguntas.txt` | 129 | Lista cruda de preguntas sin deduplicar (superseded por la .dedup) |
| `wf_unknowns.dedup.txt` | 289 | Lista cruda acumulada y deduplicada de unknowns (insumo de `audit/_listas/`) |
| `wf_unknowns.txt` | 116 | Lista cruda de unknowns sin deduplicar (superseded por la .dedup) |
| `workflow.js` | 769 | Script maestro del workflow: los 24 lectores y los 24 conceptos con sus prompts completos y sus pistas de vocabulario. Es la fuente para correr lo que falta |
| `workflow_A.js` | 621 | Tanda A — cómo filtrar los lectores pendientes por id (patrón a copiar) |
| `workflow_B.js` | 649 | Tanda B — cómo filtrar conceptos por slug (patrón a copiar) |
| `workflow_C.js` | 670 | Tanda C — conceptos + un lector suelto en la misma corrida (patrón a copiar) |

---

_Auditoría corrida el 2026-09-06/07 contra `b74f450f`. 20 de 21 secciones de lectura y 16 de 24 conceptos._
