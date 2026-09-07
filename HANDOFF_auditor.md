# HANDOFF — el chat AUDITOR

Sos el chat **AUDITOR** de Rendi. Este documento reemplaza el contexto de dieciocho rondas.
Lo escribió el auditor anterior al quedarse sin contexto. Está medido, no recordado: cada número
viene con su consulta.

---

## 1 · QUIÉN SOS Y CÓMO TRABAJÁS

**No implementás. Auditás.** Hay otro chat (el IMPLEMENTADOR) que hace el trabajo. El dueño te
pasa lo que ese chat entrega, vos lo verificás **ejecutando**, y escribís el prompt de la ronda
siguiente. El ciclo es:

```
implementador trabaja → el dueño te pasa el informe → VOS REPRODUCÍS TODO → escribís el próximo prompt
```

**Nunca tomes un informe por cierto.** Ni el del implementador, ni el de un subagente, ni el
tuyo de hace tres rondas. En dieciocho rondas, los informes fueron honestos casi siempre — y aun
así aparecieron **tres correcciones importantes** que sólo salieron por reproducir de cero.

Las reglas que hicieron que esto funcione:

- **Medí con tu propio instrumento**, no con el del implementador. Si él midió con su script,
  escribí el tuyo. Dos veces eso destapó cosas que su script no podía ver.
- **Un número sin su consulta no existe.** Si pasás una medición, pasá la query. Un «21 alertas»
  sin query costó una ronda entera de no poder reconciliar.
- **Cerrá sus "QUÉ NO VERIFIQUÉ".** Es la sección más valiosa de cada informe. De los últimos
  cuatro informes, el auditor cerró **nueve** puntos que el implementador había dejado abiertos —
  y **dos de esos nueve eran los hallazgos más grandes de toda la sesión**.
- **Separá "el mecanismo está abierto" de "ya pasó".** Andá a los datos a ver si entró alguien.
- Los prompts que escribís llevan: qué está verificado (para que no lo rehaga), el hallazgo con
  su medición, qué NO se puede romper, las trampas de instrumento, criterio de salida, y
  **"🔴 QUÉ NO VERIFICASTE" como entregable obligatorio**.

## 2 · 🔴 LO PRIMERO QUE TENÉS QUE HACER

```bash
cd /Users/nicolaspussetto/rendi-worktrees/reportes-guard
git log --oneline -5 && git status --porcelain && git rev-parse origin/main | cut -c1-8
```

Confirmá que el árbol esté limpio y que `HEAD` sea `f50beefb`. Después leé el §4 (el estado) y
el §8 (las trampas). No empieces a medir nada antes de leer el §8: **cada una de esas diecisiete
trampas costó al menos media ronda.**

## 3 · DÓNDE ESTÁ TODO

```
Worktree del audit : /Users/nicolaspussetto/rendi-worktrees/reportes-guard
Rama               : fix/reportes-guard-benchmark   (HEAD f50beefb)
Repo principal     : /Users/nicolaspussetto/Documents/trading
Prod               : rendi.finance (Vercel) + trading-production-143b.up.railway.app (Railway)
```

**Los datos.** La copia de producción cruda está en `~/Downloads/trading-2026-08-16.db`
(933 MB). ⚠️ **Nunca la abras directamente ni en escritura**: copiala a tu scratchpad y abrila
con `sqlite3.connect("file:...?mode=ro", uri=True)`. La copia que usó el auditor anterior estaba
**estampada** (con las columnas `base`/`apto` de `twr.estampar_base`); si la necesitás así,
corré el estampado sobre tu copia.

**La app local**: `http://localhost:5199` (frontend) + `:8000` (backend),
usuario `demo.metricas@rendi.test` / `demo1234`. Es un fixture local: esas credenciales no
sirven en ningún otro lado.

**Los prompts de las 18 rondas** están en `/Users/nicolaspussetto/Documents/trading/PROMPT_*.md`.
El de la ronda que sigue es **`PROMPT_dos_eventos_un_cobro.md`**, ya escrito y listo.

## 4 · EL ESTADO — qué está en producción y qué no

### ✅ Deployado y verificado (2026-08-30)

Los tres commits de Insights (`971c7522`, `c1fe78f0`, `8245b0e0`) están en `origin/main` y
sirviéndose. Verificado leyendo el bundle real de rendi.finance: el chunk pasó de
`Insights-sler9Kwu.js` a `Insights-ConqRBNx.js` y contiene las tres frases nuevas.

### ⛔ SIN pushear — tres commits del cobro

```
f50beefb  fix(billing): cerrar la traba de duplicados del credito   ← toca PRODUCCIÓN
a1eda91a  test(billing): payment.created y subscription.updated
623563e4  test(billing): cubrir la ruta del dinero — 29 → 25 fallas
```

**No están pusheados a propósito**, no por miedo: el octavo bug (§6) sigue abierto y el dueño y
el auditor coincidieron en tocar la ruta del dinero **una sola vez, completa**.

### 🔴 HAY OTRO CHAT TRABAJANDO EN PARALELO — esto es nuevo

Mientras esta sesión trabajaba, **otro chat pusheó 17 commits a `main`** (rediseño mobile,
Cartera en cards, fixes de valuación, landing). Ese flujo **mergeó los 3 commits de Insights**
en `163ad1bd`.

```
origin/main       dde8ee55   (17 commits adelante de tu HEAD)
merge-base        8245b0e0   (= tu último commit pusheado)
```

Medido hoy, y es la buena noticia: **el otro flujo NO tocó `backend/main.py`, `backend/billing/`
ni `backend/tests/`** (41 archivos cambiados, ninguno de esos), y el ensayo de merge
(`git merge-tree`) **da limpio**. La rama del cobro se puede mergear sin conflicto — hoy.

⚠️ **Verificalo de nuevo antes de mergear**: el otro chat sigue pusheando.

## 5 · LAS DOS FAMILIAS

### A · El % con una punta al costo — **CERRADA**

Once rondas persiguiendo un bug: comparar un valor medido **a precio de mercado** contra uno
calculado **al costo** (la cadena contable, donde `pnl_unrealized = 0`) y publicar la diferencia
como rendimiento. Un usuario real reportó «−63,37% / −US$127.486» sin haber vendido nada.

Está cerrada y deployada. Lo que dejó, y que **no se puede romper**:

- **La distinción que no se puede volver a colapsar**: *¿este punto se puede DIBUJAR?* (por
  SERIE, `clase ∈ ACEPTA_LINEA`) vs *¿puede ser PICO o DENOMINADOR?* (por FILA, `apto`).
  Colapsarlas es lo que hizo volver el bug tres veces. Vive en `backend/twr.py` y
  `frontend/src/utils/evolution.js` (`esApto` vs `esDibujable`).
- **El certero es bit-idéntico** en los 822 usuarios. Es la propiedad que sostiene todo.
- **El estimado ⊇ certero**: el estimado publica para 655 usuarios donde antes 248.
- **El clamp de plausibilidad**: las alertas del asesor pasaron de 95 a 71; las 71 son un
  subconjunto exacto de las 95.
- **El eje temporal** del gráfico (`type="number"` + `scale="time"`).

Contexto que conviene tener: **nadie tiene más de tres meses de historial medido.** Ninguno de
los 649. Las filas valuadas a mercado existen recién desde el **2026-05-31**, cuando el cron
empezó a estampar `fx_to_usd_blue`. La feature no está mal hecha: nació hace poco.

### B · La ruta del cobro — **ABIERTA, y es plata**

Empezó porque la suite se recuperó y destapó que **la ruta de pago no tenía cobertura desde que
migraron de MercadoPago a Rebill**. Tres rondas después hay 40 tests del webhook, un arreglo de
producción, y **ocho bugs conocidos**.

## 6 · LOS OCHO BUGS — la triage

Ordenados por daño, con el estado real:

| # | Bug | Estado | Daño |
|---|---|---|---|
| **8** | **Cada alta acredita DOS veces**: `subscription.created` y el `first_subscription_payment` del mismo cobro entran por handlers distintos y cada uno da un período | 🔴 **ABIERTO** | **Ya costó: 3 clientes reales, 90 días** |
| 1 | `payment.created` perdía el `subscription_id` → el dedup del crédito nunca se activaba | ✅ **ARREGLADO** (`f50beefb`, sin deployar) | Regalaba 30 días por reintento |
| 3 | `subscription.created` repetido duplicaba la fila `authorized` y el crédito | ✅ **ARREGLADO** (mismo commit) | Rompía el 409 de `/subscribe` |
| 2 | `/api/billing/subscribe` no reusa la sub `pending` (`main.py:26032` sólo mira `authorized`) | 🔴 abierto | Basura, no plata. Hoy hay **0 filas pending** en prod |
| 4 | `_sync_authorized_with_mp` es código muerto: sólo lo llaman 3 tests, `run_lifecycle_job` no | 🔴 abierto | Sin red de seguridad + 3 tests dan confianza falsa |
| 5 | Idempotencia del crédito sin `user_id` (`credits.py:186`) | 🔴 abierto | Baja probabilidad; le sacaría lo pagado |
| 6 | Sin dedup a nivel webhook; `billing_events.mp_event_id` viene **vacío en las 52 filas** | 🔴 abierto | Es la causa raíz de 1 y 3 |
| 7 | El docstring del webhook promete 7 eventos; el router atiende 1 de esa lista | 🟢 inocuo | **Medido: esos nombres no llegan nunca** |

### El bug 8, con su medición

```
payment.created · data.payment.paymentType
   first_subscription_payment       27   ← uno por cada subscription.created
   recurring_subscription_payment   23
```

En el ledger de producción, con segundos de diferencia:

```
pares de créditos al mismo user a ≤120s : 6
usuarios                                : 4
días acreditados dos veces              : 180
```

⚠️ **Pero 3 de esos 6 pares son el uid 1** (la cuenta del dueño, ids `test_sub_*`/`test_pay_*` =
sandbox). **Los clientes reales son 3 (127, 285, 700): 90 días.** Decilo así siempre.

El prompt de esa ronda ya está escrito: **`PROMPT_dos_eventos_un_cobro.md`**.

## 7 · LOS NÚMEROS QUE VALEN — con sus consultas

**Baselines de la suite** (reproducilos antes de creerle a nadie):

```bash
cd backend && python3 -m pytest tests/          # 25 fallas / 3.745 pasan / 11 xfail · ~55 s
cd frontend && npx vitest run && npx vite build # 50 archivos / 1.351 pasan · build limpio
```

El conjunto de fallas conocidas vive en `backend/tests/fallas_conocidas.txt` (25 ids) y
`tests/conftest.py` avisa si aparece una nueva. **Extraé el conjunto así**:

```bash
grep -E "^FAILED " salida.txt | sed 's/^FAILED //; s/ - .*//' | sort -u
```

**Los 92 webhooks reales** — la fuente que destrabó toda la familia B:

```sql
-- sobre la copia de producción, mode=ro
SELECT raw_payload FROM billing_events WHERE raw_payload IS NOT NULL AND raw_payload <> '';
-- 92 filas:  payment.created 52 · subscription.created 27 · subscription.updated 10 · 3 de la era MP
```

**El estado del dedup antes del arreglo**:

```sql
SELECT COUNT(*) FROM credit_ledger WHERE kind='payment'
  AND payment_id IS NOT NULL AND payment_id <> ''
  AND source_subscription_id IS NOT NULL AND source_subscription_id <> '';
-- 0 de 34.  La traba de duplicados no se activó NUNCA en producción.
```

**Formas reales de los payloads** (esto no está en ningún docstring correcto):

```
payment.created      → data.payment.id · data.subscriptionId (HERMANO, camelCase) · data.payment.paymentType
subscription.created → data.subscription.id · data.customer · data.card   ← NO hay objeto `payment` (0 de 27)
subscription.updated → data.id · data.status · data.lastStatus · data.metadata.rendi_user_id
```

**Otros que se usaron seguido**:

```
usuarios con broker en pesos      : 758 de 854 (89%)
… y sin ninguna fila apta         : 184        ← ven el estado vacío
usuarios con historial medido ≥1 año : 0 de 649
subscriptions en prod             : 45 filas (13 authorized, 0 pending, 1 grupo duplicado)
```

## 8 · 🔴 LAS DIECISIETE TRAMPAS DE INSTRUMENTO

Cada una costó tiempo real. **Leelas antes de medir nada.**

1. **No saques conclusiones de una salida truncada.** El auditor imprimió las primeras 28 claves
   de un payload, no vio `data.subscriptionId` y escribió «no viene». Venía, en 50 de 52, y el
   hallazgo salió mal orientado. Si cortás la salida, decilo en la conclusión.
2. **Un repro viejo prueba el mundo viejo.** El auditor corrió su script de la ronda 15 contra el
   código arreglado, dio 🔴, y casi reporta que el arreglo no servía: su payload llevaba un
   objeto que **no existe en ningún caso real**. Cuando un repro contradiga un arreglo, revisá
   primero si el repro sigue describiendo la realidad.
3. **`timeout` NO existe en macOS**: falla y devuelve **exit 0 sin correr nada**. El auditor casi
   reporta «la suite pasa» con la suite sin correr.
4. `| tail` esconde por qué murió pytest. Escribí a archivo.
5. **Extraé las fallas con `^FAILED ` anclado.** El log tiene líneas propias que empiezan con
   `ERROR ` (`ERROR billing.subscriptions:…`) y dan 43 donde hay 29.
6. **Compará CONJUNTOS de nombres, nunca conteos.**
7. `git diff --stat` mide contra HEAD, no contra el estado previo a la ronda.
8. **NUNCA copies archivos de un sandbox al worktree para "aplicar" un merge.** El auditor lo
   hizo: el sandbox había mergeado contra refs distintas, pisó `main.py`, se llevó funciones de
   producción y **commiteó marcas de conflicto con el build roto**. Se detectó por 79 tests
   nuevos en rojo. Resolvé SIEMPRE en el lugar.
9. **Verificá ANTES de commitear.** El mismo desastre ocurrió porque un script imprimió «queda 1
   archivo con marcas» y siguió igual.
10. **El panel del browser no sirve para capturas.** Confirmado cuatro veces en dos chats: pinta
    una vez tras `navigate` y después el input muere con *"the Browser pane is currently
    hidden"*. `javascript_tool` para leer el DOM **sí** funciona siempre.
11. **Con el panel oculto, `getBoundingClientRect` devuelve CEROS.** `window.innerWidth === 0` es
    la señal de que tu medición de layout no vale nada. **`resize_window` fuerza un viewport
    medible aunque el panel esté escondido** — así se midieron los 375 px.
12. **Midiendo el gráfico por DOM los dos chats se equivocaron siete veces**: selector que mezcla
    dos `.recharts-wrapper`, sesión expirada tomada por bug, contar `M`/`L` cuando Recharts
    dibuja con `C`, contar `dots`, contar un solo path, adivinar nombres de claves. Lo que
    funciona: leer `chartData` del fiber de React, o los ticks **acotados al primer wrapper**.
13. El Fast Refresh devuelve geometría vieja con props nuevas. Recargá duro entre builds.
14. **Un número sin su consulta no es reproducible.**
15. `which` no es el inventario del entorno: hay PostgreSQL real vía el paquete pip **`pgserver`**
    (el auditor declaró Postgres inverificable **dos veces al dueño** antes de descubrirlo). Y al
    revés: **`coverage` NO está instalado**, aunque suene a que tiene que estar.
16. **Contar menciones no es medir cobertura.** Sostuvo cinco rondas una frase a medias
    («la ruta de cobro no tiene tests»). Abrí los archivos.
17. **Heredar de `TestCase` en una clase base re-corre los tests del padre en cada hija** — dio
    62 donde había 37. Usá un mixin que no herede de `TestCase`.

Y dos del entorno que no son de medición pero cuestan igual:

- **`mkschema.py` reescribe `schema_pg.sql` EN EL LUGAR sin aviso** (se llevó tres ediciones a
  mano del auditor).
- **`scripts/test_emails.py` manda 3 mails REALES** y su import hace `load_dotenv(override=True)`:
  con sólo colectarlo, las credenciales de producción pisan el entorno de toda la corrida.
  `pytest.ini` lo bloquea con `testpaths` **y** `norecursedirs` — hacen falta las dos.
  **Corré siempre `python3 -m pytest tests/`**, nunca `pytest .` ni `pytest -k algo`.

## 9 · LO QUE EL AUDITOR ANTERIOR HIZO MAL

No para flagelarse: porque el patrón se repite y conviene reconocerlo temprano.

- **Cinco veces afirmó cosas sobre datos que no había mirado.** «La ruta de cobro no tiene
  tests» (tenía, a medias), «`payment.created` no trae subscriptionId» (lo traía, en 50 de 52),
  «el contable nunca baja» (baja: 11,4% de los meses), «~2 años de historial» (nunca hubo más de
  3 meses), «Postgres es inverificable» (estaba instalado). **El patrón es siempre el mismo:
  afirmar desde la inferencia en vez de desde la consulta.**
- **Casi reporta un desastre inexistente y casi tapa uno real.** Reportó un merge como
  «9 marcas de conflicto» cuando había una; y midió «0 usuarios afectados» donde había 83, por
  probar el nombre de campo equivocado.
- **Lo que sí funcionó**: reproducir de cero con un script propio. Los tres hallazgos más grandes
  de la sesión —el mes regalado, el dedup que nunca se activó, y los 92 payloads reales— salieron
  todos de escribir un script independiente en vez de leer el informe.

## 10 · REGLAS DURAS

- 🔴 **Pushear a `main` ES DEPLOYAR A PRODUCCIÓN** (Vercel + Railway). Nunca sin autorización
  explícita del dueño, en ese mensaje, para ese push.
- 🔴 **Nunca abras un `.db` en escritura.** Copialo primero; abrilo con `mode=ro`.
- ❌ **Nunca uses `git stash`** en este worktree.
- ✅ **Respaldá antes de dejar que un agente toque el árbol**, y decile explícito: no modifica,
  no commitea, no pushea, no stashea.
- ⚠️ **Antes de mergear `main`**: `git merge-tree` primero, y **resolvé en el lugar** (trampa 8).
- ⚠️ **Nada de arreglar bugs en una ronda de cobertura.** Los ocho bugs se reportan; qué se toca
  en la ruta del dinero lo decide el dueño.

## 11 · QUÉ SIGUE

1. **`PROMPT_dos_eventos_un_cobro.md`** — el bug 8, el único que ya costó plata. Está escrito.
2. Después: mergear `main` (hoy limpio) y deployar la ruta del dinero **completa**, de una vez.
3. Backlog anotado y sin tocar: los bugs 2, 4, 5, 6; `payment.updated` sin cobertura; los 2
   `payment.created` sin `rendi_user_id`; el fallback de `_rebill_activate` con el ledger caído;
   el camino HMAC válido sin test; `test_bond_conduit.py` (640 donde se espera 720).
4. Fuera del cobro: snapshots por broker (habilitaría el modo estimado en pesos, donde está el
   89% de los usuarios), Postgres dormido, Fases 3 y 4 del plan original.

**Y lo único que nadie pudo cerrar en cuatro rondas**: nadie miró las pantallas de Insights con
los ojos. Todo se verificó por DOM porque el panel del browser no pinta. Ya está deployado, así
que ahora se puede mirar en rendi.finance — pedíselo al dueño, es su ventaja sobre vos.
