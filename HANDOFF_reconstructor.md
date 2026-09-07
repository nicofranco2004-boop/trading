# Handoff — agente reconstructor (para retomar en otro chat)

Copiá todo lo de abajo como primer mensaje del chat nuevo.

---

Estoy trabajando en Rendi (app de tracking de inversiones AR, `~/Documents/trading`). Vengo de una sesión larga sobre el **"agente reconstructor"** y necesito seguir. Acá está el estado real; verificá contra el código antes de asumir nada.

## Dónde está el trabajo

- Rama **`feat/reconstructor-f1`**, worktree **`~/rendi-worktrees/reconstructor-f1`**, pusheada a `origin`.
- **NO está en `main`** — y en este repo mergear a `main` = deployar a producción (Vercel + Railway). No mergees sin que te lo pida.
- 10 commits. `git log --oneline origin/main..HEAD` los lista.
- Copia de la base de PRODUCCIÓN para medir: `~/Downloads/trading-2026-08-16.db` (890MB, 1.093 usuarios).
  🔴 Abrila SIEMPRE así, solo lectura: `sqlite3.connect('file:<path>?immutable=1', uri=True)`. Nunca escribas ni la copies.

## Los dos giros grandes (no los re-descubras, ya están medidos)

**1. La premisa original del agente está MUERTA.** El diseño decía: "resolver flujos ambiguos — ¿esta entrada de títulos fue aporte de plata nueva o traslado entre brokers?". Medido contra prod: de 154 pares COMPRA+DEPOSITO, **cero** son traslados internos. Los 15 usuarios afectados tienen **una sola institución** en Rendi (Balanz + su sub-broker USD, o IEB + el suyo), así que los títulos entraron desde afuera del perímetro y el depósito compensatorio **es correcto** — es capital nuevo aportado en títulos en vez de efectivo. "Corregirlos" habría borrado ~ARS 460M de aportes reales. Es estructural: el agente sólo puede decidir aporte-vs-traslado si el usuario trackea **las dos patas** en Rendi, y esta base de usuarios no es multi-broker. Trabajo real de esa premisa en toda la base: **~6 filas**.

**2. El proyecto se reapuntó** a la pregunta que sí tiene caseload: **quién ve hoy un número que no es el suyo, y por qué.** Barrido real: **45 usuarios, 42 con causa identificada.**

## Lo que está construido (todo con tests, todo READ-ONLY salvo donde se dice)

- **`backend/diagnostico.py`** + `GET /api/admin/diagnostico` (barrido, o `?target_uid=`). Cinco causas raíz:
  - **R1** conducto dólar-MEP de Cocos (25 usuarios) — la pata en pesos rotulada USD.
  - **R2** renta de `balanz_resultados` (9) — cupón en pesos rotulado USD. **No auto-arreglable.**
  - **R3** per-100 de IEB (4) — **auto-arreglable determinístico.**
  - **R4** renta de IOL (1) — **auto-arreglable determinístico.**
  - **R5** flujo manual peso-escala (9) — síntoma en la mayoría, raíz en 3.
- **`backend/censo_flujos.py`** + `/api/admin/censo-flujos` — mide el andamio del import.
- **`backend/censo_capital.py`** + `/api/admin/censo-capital` — mide el resultado que ve el usuario.
- **`backend/twr.py`** — 8 guardas de runtime en `verificar_tramo`, `retractar()` (append-only + trigger `BEFORE UPDATE`), meses `no_medible` que ya no desaparecen en silencio, `twr_de` que exige contigüidad.
- **`backend/flujos.py`** — tabla `flujo_resoluciones` (append-only), `registrar/aplicar/revocar/revocar_lote`, **un solo lector: `twr._flujo`**.
- `GET /api/admin/diag/flujo-contaminacion` — contrafáctico en memoria, no sella ni escribe.

**Dos interruptores, los dos APAGADOS por default:** `TWR_GUARDAS` (las guardas registran en `guardas_json` sin bloquear) y `RECONSTRUCTOR_APLICAR` (ninguna resolución toca ningún número). Son allowlist de encendido: sólo `1/true/yes/si/on` prenden.

## 🔴 EL HUECO: hoy el agente NO corrige nada, y la vía de escritura apunta al número equivocado

Esto es lo más importante de todo el handoff. Verificalo vos, son tres greps:

1. **`diagnostico.py` tiene CERO `INSERT/UPDATE/DELETE`.** Diagnostica y nada más.
2. **El único lector de `flujo_resoluciones` es `twr._flujo`**, que alimenta `dietz(v0,v1,flow)` — o sea que una resolución aplicada **sólo mueve el TWR**. Y `/api/advisor/twr` tiene **0 consumidores en el frontend** (`grep -rn "advisor/twr" frontend/src` → vacío). Hoy una corrección cambiaría un número que ninguna pantalla muestra.
3. **Lo que los 45 usuarios VEN roto está en otro lado**: el "capital declarado" de US$44M de `uid 613` es `monthly_entries.capital_final`, derivado de `operations.pnl_usd`. `flujo_resoluciones` no toca ninguna de las dos — y no por olvido, sino por el principio duro original ("la IA nunca escribe tablas de plata").

**Consecuencia:** la vía de escritura de la Fase 5 sirve para corregir **FLUJOS** (encaja con R5). Las causas diagnosticadas R1/R3/R4 son **P&L**, y no encajan ahí.

**El camino correcto ya está en el repo y no lo usé:** hay tres endpoints `admin_repair_*` en `main.py` (`admin_repair_user_history` ~15276, `admin_repair_snapshots_all` ~15309, `admin_repair_comisiones` ~17157), **todos con `apply: bool = False`** — dry-run por default, con sus tests (`tests/test_repair_comisiones.py`, `tests/test_repair_user_history.py`). Ése es el patrón de la casa para tocar tablas de plata de forma segura, y es donde tienen que vivir las correcciones de R1/R3/R4.

## Qué sigue (mi recomendación, no ejecutada)

0. **Decidí primero dónde vive la corrección de P&L.** Lo natural es un `admin_repair_pnl_escala` calcado de `admin_repair_comisiones`: `apply=False` por default, reporta qué tocaría, y recién con `apply=true` reescribe. NO metas esto en `flujo_resoluciones` — esa tabla es para flujos.

0-bis. **DOS BLOQUEANTES ANTES DE ESCRIBIR UNA LÍNEA DE REPARACIÓN.** Sin estos, el repair es inverificable e invisible:
   - **Los snapshots no se reparan.** `_backfill_snapshots_from_monthly` es `INSERT … ON CONFLICT DO NOTHING`, y los de fin de mes son copia literal del `capital_final` corrupto. Reparás `monthly_entries` y el Dashboard **sigue mostrando el número viejo**, igual que el gráfico de Evolución. El repair tiene que refrescar los snapshots que invalida.
   - **El criterio de éxito se rompe solo**: `ratio = pico/cartera` divide por un denominador que el repair no toca (hay cuentas con cartera 0 o negativa). Hace falta un criterio que no dependa de eso. *(Ojo: el barrido de hoy NO revienta — verificado, 81 revisados, cero inf/NaN. Es una trampa del diseño del repair, no un bug vivo.)*

1. 🔴 **R3 NO es el estreno de bajo riesgo — es el MÁS PELIGROSO.** Esta línea decía lo contrario y estaba mal; un panel adversarial de 4 lentes convergió en lo opuesto:
   - **El repo YA se niega a hacerlo**: `fx_migrate.py:249-276` rechaza (`ok: False`) cualquier cuenta con filas per-100 y explica que el rebuild "les arreglaría el P&L pero el CASH quedaría inflado ×100 sin la firma que hoy lo delata — el «crimen perfecto»".
   - **El cash fantasma está medido**: las 151 ventas per-100 acreditaron ARS 55.977.251.272 + USD 16.580.658 que siguen entrando a `snapshots.total_value`. El rebuild no toca cash.
   - **No es determinístico**: 11/11 usuarios de R3 son `fx_version=v1`, y en v1 el replay dolariza al blue vivo → el ensayo y el apply pueden dar distinto.
   - **Sin vuelta atrás, radio 4,5× la causa**: `_clear_old_state` borra `positions` y `operations` y re-inserta sin `undo_meta_json` (674 ventas reescritas, 530 sanas que nadie pidió tocar).
   → **R3 es de dos pasos: el procedimiento de cash PRIMERO.** Ese orden ya lo fijó el guard de `fx_migrate`.

2. **R4 es el pilot, y sobre `uid 54` únicamente.** El selector de DIAGNÓSTICO es más ancho que el de REPARACIÓN: `uid 870` tiene 27 filas con la moneda inferida por el parser (`notes LIKE '%divisa=OTHER%'`) que **están bien hoy** — "corregirlas" las achica ~1.200× y borra US$424 de renta real. Y `uid 812` tiene 9 filas selladas a 1415, donde pasar el P&L al MEP histórico dejando los flujos al sello es migrar **una sola pata** del FX. `uid 54` es el único limpio en las dos dimensiones: 5 filas, TC per-fecha reales, `616× → 1,27`.
2. **R1** (25 usuarios) — 🔴 **tiene DOS patas y hay que arreglarlas juntas.** La positiva salta a la vista (`pnl_pct` de 150.000%); la negativa sale con **`pnl_pct = −100` exacto** y ningún umbral la ve. En `uid 358`: +1.211.379 vs **−2.644.736** → arreglar sólo la positiva deja el pico **peor** (1.436.162 → 2.643.283).
3. **R2** (9) — no se puede sin el usuario: la columna "Moneda Venta" del Excel no se guardó, no hay umbral limpio (dividendos USD de US$3 conviven con cupones peso-escala de US$600k) y el formato ya está bloqueado.

## Reglas duras que costaron tiempo esta sesión

- 🔴 **El gate de tests no es "verde".** La suite tiene **47 fallas preexistentes**. El gate es comparar el *conjunto* de fallas contra `origin/main` limpio y exigir diff vacío:
  ```
  cd <worktree>/backend && python3 -m pytest tests/ -q -p no:randomly --tb=no | grep "^FAILED" | sed 's/ - .*//' | sort
  ```
  (Ojo: `test_events.py` tiene un evento hardcodeado al `2026-08-20` con ventana de 365 días — es date-dependent, no regresión.)
- 🔴 **Nunca sumes plata entre monedas.** Siempre `GROUP BY currency`. Y reportá el **máximo de una fila** al lado de la suma: una suma enorme puede ser UNA fila corrupta (pasó: "el 97,5% del capital aportado es sintético" era **una** fila).
- 🔴 **Un umbral en dólares sobre una columna en pesos da basura** (1M ARS ≈ US$700). Pasó tres veces.
- 🔴 **`_table_cols()` en `main.py` tiene una ALLOWLIST silenciosa**: una tabla que no esté ahí devuelve `set()` → el `if` no entra → **la migración nunca corre, sin error ni log**. Rompió dos veces. Hay test estructural en `test_advisor_schema_migration.py`.
- 🔴 **`backend/schema_pg.sql` es GENERADO** por `backend/scripts/mkschema.py`. No lo edites a mano — se pisa solo. Y **no traduce triggers**.
- 🔴 **`try/except → return []` en un diagnosticador da de alta a un enfermo**: una query rota se lee igual que "esta cuenta está sana".
- ⚠️ **`backend/.env` tiene `RESEND_API_KEY`**: correr la app fuera de pytest **manda mails de verdad**.
- ⚠️ **Caveat que acota cualquier promesa de exactitud**: el **52% de las filas ARS** tiene `gross_amount_usd` estampado a **1415,00 exacto**. "El valor correcto ya está en la base" es cierto en orden de magnitud, no al centavo.
- Los índices van **después** del `ALTER` y **fuera** del `if` (un orden invertido ya tumbó prod 20 minutos).

## Cosas que decidí NO hacer (no las retomes salvo que te lo pida)

- El fix del `ridx+1` a producción (bug de diagnóstico vivo, arreglado en la rama).
- El arreglo manual de `uid 329` (cartera US$18.324, capital declarado US$1.700M).

## Contexto extra

`PLAN_agente_reconstructor.md` en la raíz tiene el plan original de 7 fases — **ojo, la Fase 2 y parte de la 3 quedaron obsoletas** por el giro #1. Las memorias `project_agente_reconstructor` y `project_import_guardian` están actualizadas.

**Arrancá leyendo `backend/diagnostico.py` y corriendo el barrido contra la copia de prod.** Después decime qué ves antes de escribir código.
