export const meta = {
  name: 'auditoria-rendi-tanda-c',
  description: 'Ocho conceptos más (tenencia, P&L no realizado, comisiones, cupones, variación, snapshots, bonos, CEDEAR) y el barrido sistemático de código muerto',
  phases: [
    { title: 'Conceptos', detail: 'ocho conceptos más, rastreando cada sitio de cálculo con archivo:línea' },
    { title: 'Código muerto', detail: 'barrido sistemático de huérfanos, duplicados y deuda técnica' },
  ],
}

const TREE = '/private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/8ec62656-b7d0-4338-ab44-356ae20024c9/scratchpad/rendi-main'
const PARTS = '/private/tmp/claude-501/-Users-nicolaspussetto-Documents-trading/8ec62656-b7d0-4338-ab44-356ae20024c9/scratchpad/audit_parts'

const RULES = `
Sos un AUDITOR TÉCNICO EXTERNO de "Rendi": una app de seguimiento y análisis de carteras de inversión (multi-broker, multi-cartera) para Argentina. Registra tenencias, operaciones, P&L, rendimientos ajustados por inflación, objetivos y comparaciones. Tiene planes de suscripción, período de prueba y un plan separado para asesores financieros.

## DÓNDE ESTÁ EL CÓDIGO
El código a auditar está en **${TREE}**. Es una copia limpia y de solo lectura de \`origin/main\` (el commit \`b74f450f\`, 2026-09-05) — o sea, **producción**. Trabajá SIEMPRE ahí: \`cd ${TREE}\` antes de grepear.

⚠️ NO uses \`/Users/nicolaspussetto/Documents/trading\` para leer código: ese working tree está 622 commits atrás y su \`main.py\` tiene la mitad de las líneas. Si mirás ahí vas a documentar un sistema que no existe.

## REGLAS INVIOLABLES
1. **READ-ONLY.** No modifiques, crees ni borres ningún archivo dentro de \`${TREE}\` ni dentro de \`/Users/nicolaspussetto/Documents/trading\`. Nada de git, nada de ejecutar la app, nada de correr la suite de tests.
2. El **único** lugar donde escribís es \`${PARTS}/\`. Escribí ahí tu sección con la herramienta Write.
3. **Citá siempre archivo y línea**, con la ruta **relativa a la raíz del repo** (así: \`backend/main.py:1234\`, \`frontend/src/pages/Insights.jsx:88\`). NUNCA escribas la ruta del scratchpad en el informe — el founder va a leer esto contra su repo.
4. **Verificá cada cita antes de escribirla** con \`grep -n\` o \`sed -n 'N,Mp'\`. Una cita inventada es peor que no citar.
5. Si no encontraste algo, escribí literalmente **no encontrado**. NUNCA supongas ni completes con lo que "debería" haber.
6. Distinguí SIEMPRE lo verificado de lo inferido:
   - \`[V]\` = verificado leyendo el código (y citás dónde)
   - \`[I]\` = inferencia tuya (y decís de qué te agarraste para inferirla)
7. Documentá cómo funciona **REALMENTE**, no cómo debería. Si algo es raro, contradictorio, duplicado o parece un bug: anotalo, no lo "corrijas" en la narración.
8. **Secretos**: no leas ni imprimas valores de \`.env\`. Si necesitás saber qué variables usa el código, grepeá \`os.getenv\` / \`os.environ\` / \`import.meta.env\` y nombrá SOLO la variable.
9. **Base de datos**: hay una copia de la base de desarrollo en \`${TREE}/backend/trading.db\`. Podés leer su esquema (\`sqlite3 backend/trading.db ".schema tabla"\`) como evidencia secundaria, pero **el código manda**: esa base viene de una rama vieja y puede no tener tablas nuevas. Nunca hagas SELECT de datos de usuarios.

## SALIDA
Español rioplatense (el founder es argentino), identificadores de código en su idioma original. Markdown, encabezados \`##\` y \`###\`, sin frontmatter, empezando directo por tu \`##\`. Tablas markdown donde ayuden. **Sé exhaustivo**: mejor largo y completo que corto y prolijo.
`

const READER_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string', description: 'ruta absoluta del markdown que escribiste' },
    title: { type: 'string' },
    citations: { type: 'integer' },
    unknowns: { type: 'array', items: { type: 'string' } },
    questions: { type: 'array', items: { type: 'string' } },
    deadCode: { type: 'array', items: { type: 'string' } },
    hallazgos: { type: 'array', items: { type: 'string' }, description: 'cosas notables que descubriste: bugs, riesgos, rarezas, con archivo:línea' },
  },
  required: ['file', 'title', 'citations', 'unknowns', 'questions', 'deadCode', 'hallazgos'],
}

const READERS = []

// ── 01 infra ────────────────────────────────────────────────
READERS.push({
  id: '01-stack-infra', label: 'stack+infra', title: 'Stack, estructura e infraestructura',
  prompt: `Documentá el STACK, la ESTRUCTURA de carpetas y la INFRAESTRUCTURA.

Leé: \`backend/requirements.txt\`, \`frontend/package.json\`, \`frontend/vite.config.js\`, \`frontend/vercel.json\`, \`frontend/tailwind.config.js\`, \`frontend/index.html\`, \`railway.toml\`, \`nixpacks.toml\`, \`dev.sh\`, \`start.sh\`, \`start-rendi.sh\`, \`.gitignore\`, \`backend/.env.example\`, \`MIGRACION_POSTGRES.md\`, \`frontend/scripts/\`.

Cubrí:
- Lenguajes, frameworks y **versiones exactas** (con cita). Framework web, ORM (¿hay?), cliente de base, frontend, bundler, router, estilos, gráficos.
- Cómo se levanta en dev y cómo se buildea/deploya en prod. Verificá si backend va a Railway y frontend a Vercel — no lo asumas, buscá la evidencia.
- **Árbol de carpetas** de primer y segundo nivel, UNA LÍNEA por carpeta diciendo para qué sirve REALMENTE (abrí un par de archivos de cada una antes de describirla).
- **Inventario completo de variables de entorno** que el código lee (grepeá \`os.getenv\`, \`os.environ\`, \`import.meta.env\`, \`process.env\` en backend y frontend). Tabla: variable | dónde se lee (archivo:línea) | para qué | ¿tiene default? | ¿es secreto?
- **Base de datos**: ¿SQLite o Postgres? Mirá \`backend/pgshim.py\`, \`backend/pgsesion.py\`, \`backend/dberrors.py\`, \`backend/scripts/mkschema.py\`, \`backend/scripts/copiar_a_postgres.py\`, y la función \`get_db\` de \`backend/main.py\`. **Esta es la pregunta clave**: ¿qué motor corre en producción HOY? ¿Hay una migración a medias? ¿Cómo se elige el motor (env var)? Documentá el mecanismo del shim con detalle.
- \`backend/mantenimiento.py\` y \`backend/scripts/vigilar_espacio.py\`, \`backup_db.py\`: qué hacen.
- Los \`.md\` sueltos en la raíz: qué son y si son documentación viva o restos de sesiones.

Escribí en \`${PARTS}/01-stack-infra.md\`.`,
})

// ── 02-04 modelo de datos ───────────────────────────────────
READERS.push({
  id: '02-datos-core', label: 'datos: core', title: 'Modelo de datos — núcleo de negocio',
  prompt: `Documentá el MODELO DE DATOS del núcleo de negocio.

Fuente principal: \`backend/main.py\`, función \`init_db()\` (empieza en la línea 698). Leé el bloque completo con \`sed -n '698,2700p' backend/main.py\`. Ojo: hay CREATE TABLE **condicionales** (dos variantes de la misma tabla según si la base es nueva o vieja) y migraciones ALTER TABLE dispersas. Documentá AMBAS ramas y decí cuándo corre cada una.
Complementá con \`sqlite3 backend/trading.db ".schema <tabla>"\` (evidencia secundaria: esa base es vieja, el código manda).

**Tablas que te tocan**: \`users\` (~711), \`brokers\` (~723), \`positions\` (~923 y ~940, dos variantes), \`archived_positions\` (~1585), \`operations\` (~1118 y ~1135), \`monthly_entries\` (~1044 y ~1062), \`snapshots\` (~1368), \`goals\` (~1498), \`plazos_fijos\` (~1517), \`futures_positions\` (~1551), \`watchlist\` (~1613), \`config\` (~1348 y ~1358), \`deleted_ops_journal\` (~2515).

Para CADA tabla:
- Qué representa en términos de **NEGOCIO** (no de código).
- Tabla markdown: \`campo | tipo | qué significa en negocio | quién lo escribe | quién lo lee | notas\`. Para "quién lo escribe/lee", grepeá de verdad.
- ⚠️ para los campos que NO entendés. 💀 para los que parecen NO USARSE (verificalo con \`grep -rn "campo" backend frontend/src\` antes de marcar).
- Claves, índices, FKs y constraints reales. **Prestá atención especial a si las relaciones son por ID o por NOMBRE (string)** — es un patrón conocido de este repo y tiene consecuencias.
- Migraciones/ALTER TABLE que la afectan, con línea.
- Para \`brokers\`: investigá el concepto de **broker padre / sub-broker** (\`parent_broker_id\`, el sufijo \`· USD\`) y cómo se relacionan.

Escribí en \`${PARTS}/02-datos-core.md\`.`,
})

READERS.push({
  id: '03-datos-asesor', label: 'datos: asesor+alertas', title: 'Modelo de datos — asesor, alertas, TWR, precios',
  prompt: `Documentá el MODELO DE DATOS de asesores, alertas, TWR e histórico de precios.

Fuente: \`backend/main.py\` \`init_db()\` (leé \`sed -n '698,2700p' backend/main.py\`).

**Tablas que te tocan**: \`advisor_clients\` (~845), \`advisor_op_batches\` (~866), \`advisor_op_batch_items\` (~874), \`advisor_groups\` (~1718), \`advisor_alerts\` (~1734), \`advisor_alert_state\` (~1743), \`advisor_alert_events\` (~1750), \`advisor_brief_log\` (~1769), \`advisor_claim_tokens\` (~2125), \`advisor_link_requests\` (~2148), \`advisor_reports\` (~2171), \`advisor_profile\` (~2186), \`alerts\` (~1658), \`alert_events\` (~1685), \`alert_symbol_state\` (~1704), \`asset_price_history\` (~1788), \`price_backfill_log\` (~1802), \`twr_periods\` (~1821), \`user_broker_credentials\` (~733), \`iol_lab_runs\` (~746), \`iol_lab_token_log\` (~757), \`broadcast_send_log\` (~1937).

Para CADA tabla: qué representa en negocio; tabla \`campo | tipo | significado | quién escribe | quién lee | notas\`; ⚠️ para lo que no entendés y 💀 para lo que no se usa (verificá con grep); índices y FKs.

Prestá atención especial a:
- **\`advisor_clients\`**: cómo se modela la relación asesor↔cliente. ¿El asesor es un \`user\`? ¿El cliente es un \`user\` real o un registro fantasma? ¿Qué estados tiene el vínculo? Esto es el corazón del producto B2B2C.
- **\`user_broker_credentials\`**: ¿guarda credenciales de brokers de terceros? ¿Cifradas con qué? Citá el mecanismo. Es la tabla más sensible del sistema.
- **\`twr_periods\`**: qué representa un "período" de TWR y cómo se encadenan.
- **\`asset_price_history\`** vs \`yfinance_cache\` vs \`asset_last_price\`: tres tablas de precios — decí qué distingue a cada una.

Escribí en \`${PARTS}/03-datos-asesor.md\`.`,
})

READERS.push({
  id: '04-datos-aux', label: 'datos: aux', title: 'Modelo de datos — cache, mercado, auth, billing, importación',
  prompt: `Documentá el MODELO DE DATOS auxiliar.

Fuente: \`backend/main.py\` \`init_db()\` (\`sed -n '698,2700p'\`), más \`backend/pricing/fci.py\` (~177 y ~188).

**Tablas que te tocan**: \`fx_rates_daily\` (~1477), \`bond_indices_daily\` (~1232), \`news\` (~1252), \`financial_events\` (~1309), \`bond_cashflow_skips\` (~1330), \`push_subscriptions\` (~1629), \`ai_analyses_cache\` (~1873), \`ai_usage_daily\` (~1893), \`ai_tool_usage\` (~1918), \`ai_user_facts\` (~1997), \`yfinance_cache\` (~1956), \`asset_last_price\` (~1974), \`subscriptions\` (~2021), \`billing_events\` (~2053), \`plan_events\` (~2073), \`credit_ledger\` (~2332), \`trial_consumed\` (~2303), \`trial_email_log\` (~2313), \`email_verification_codes\` (~2094), \`password_reset_tokens\` (~2108), \`login_history\` (~2199), \`import_batches\` (~2449), \`import_raw_rows\` (~2469), \`import_normalized_tx\` (~2479), \`import_op_links\` (~2532), \`import_mappings\` (~2650), \`import_incidents\` (grepealo), \`fci_catalog\`, \`fci_prices\`.

Para CADA tabla: qué representa en negocio; tabla \`campo | tipo | significado | quién escribe | quién lee | notas\`; ⚠️ y 💀 verificados con grep; política de retención/cleanup si existe (hay comentarios sobre crons de limpieza — citalos).

Al final agregá una sección **"Cache vs. fuente de verdad"**: clasificá cada tabla de esta parte en (a) cache puro, se puede truncar sin perder nada, (b) derivada pero cara de recomputar, (c) fuente de verdad irrecuperable. Justificá cada clasificación.

Escribí en \`${PARTS}/04-datos-aux.md\`.`,
})

// ── 05 auth ─────────────────────────────────────────────────
READERS.push({
  id: '05-auth', label: 'auth+permisos', title: 'Autenticación, autorización, planes y cuotas',
  prompt: `Documentá AUTENTICACIÓN, AUTORIZACIÓN y el gating por plan.

Leé en \`backend/main.py\`: \`create_token\` (~2681) y todo lo que lo rodea — \`get_current_user\`, \`get_admin_user\`, \`_is_admin_email\`, \`set_auth_cookie\`, \`_check_rate_limit\`, y los endpoints \`/api/auth/*\` (grepealos con \`grep -n '@app.*auth' backend/main.py\`). También: \`backend/ai/quota.py\`, \`backend/ai/plan.py\`, \`backend/billing/subscriptions.py\`, \`backend/billing/trial.py\`, \`backend/billing/credits.py\`.
Frontend: \`frontend/src/contexts/AuthContext.jsx\`, \`frontend/src/contexts/AdvisorContext.jsx\`, \`frontend/src/contexts/PrivacyContext.jsx\`, \`frontend/src/hooks/usePlanFeatures.js\`, \`frontend/src/utils/api.js\`.

Cubrí:
- **Token**: ¿qué tipo? ¿firmado con qué algoritmo y con qué secreto (nombre de la env var)? ¿expiración? ¿cookie, header, o los dos? ¿flags de la cookie (HttpOnly/Secure/SameSite)? Citá.
- **Invalidación de sesión**: ¿cómo se corta una sesión activa al cambiar la contraseña? (buscá \`pw_changed_at\`).
- **Admin**: cómo se determina. ¿Emails hardcodeados? Listalos (son públicos del founder, no son secretos).
- Verificación de email, reset de password, rate limiting: límites concretos por endpoint.
- **TIERS**: enumerá TODOS los que existen (grepeá \`tier\`, \`'free'\`, \`'plus'\`, \`'pro'\`, \`asesor\`, \`advisor\`) y qué desbloquea cada uno. Tabla: feature | tier mínimo | dónde se chequea en backend | dónde en frontend | **¿coinciden?**
- **TRIAL**: \`backend/billing/trial.py\` (1200 líneas) — cuántos días, cómo se decide si venció, qué pasa al vencer, qué es \`trial_consumed\`, cómo se evita que alguien lo repita.
- **AUTORIZACIÓN DEL ASESOR** (lo más importante de esta parte): cuando un asesor pide datos de un cliente, ¿el backend verifica que ese cliente sea suyo? Encontrá la función de chequeo (grepeá \`advisor_clients\` en \`main.py\` y buscá un helper tipo \`_assert_client\` / \`_advisor_can\`), citala, y decí si TODOS los endpoints de asesor la usan o si alguno se la saltea. Si encontrás uno que se la saltea, es el hallazgo más importante del informe.
- **Vista "como cliente"**: si el asesor puede impersonar/ver la cartera de un cliente, documentá el mecanismo exacto (¿un query param \`client_id\`? ¿un header?) y dónde se valida.
- Lista de endpoints públicos vs autenticados vs admin vs asesor.

Escribí en \`${PARTS}/05-auth.md\`.`,
})

// ── endpoints ───────────────────────────────────────────────
const CHUNKS = [
  [2680, 5500], [5500, 8500], [8500, 11000], [11000, 13500], [13500, 16000],
  [16000, 18500], [18500, 21000], [21000, 26000], [26000, 29000],
  [29000, 31500], [31500, 34000], [34000, 36000], [36000, 38100],
]
CHUNKS.forEach(([from, to], i) => {
  const n = String(i + 1).padStart(2, '0')
  READERS.push({
    id: `06${n}-endpoints`, label: `endpoints ${from}-${to}`,
    title: `Endpoints de API (main.py ${from}-${to})`,
    prompt: `Inventariá TODOS los endpoints HTTP de \`backend/main.py\` entre las líneas ${from} y ${to}.

Método: primero listalos con \`grep -n '^@app\\.' backend/main.py | awk -F: '$1>=${from} && $1<=${to}'\`. Después **leé el cuerpo completo de cada uno** con \`sed -n\`. No describas por el nombre de la función: leé qué hace de verdad.

Para CADA endpoint:

### \`MÉTODO /ruta\` — \`backend/main.py:LÍNEA\`
- **Qué hace** en términos de negocio (1-3 frases).
- **Quién puede llamarlo**: público / autenticado (\`Depends(get_current_user)\`) / admin / asesor. Citá el \`Depends\` o el chequeo inline. Si NO tiene ningún chequeo de auth, escribilo en negrita: **SIN AUTENTICACIÓN**.
- **Params**: query, path, body (nombrá el modelo Pydantic y sus campos).
- **Tablas que lee / escribe.**
- **Servicios externos que toca.**
- **Qué devuelve**: forma del JSON y campos clave.
- **Efectos secundarios**: background tasks, emails, recomputes, invalidación de cache, escrituras en cascada.
- **Rarezas**: lógica sorprendente, TODOs, código inalcanzable, duplicación con otro endpoint, N+1 de queries, falta de paginación.

Al final, una subsección \`### Helpers de este tramo\` con las funciones NO-endpoint definidas en el rango, una línea cada una con su número de línea y qué hace.

Escribí en \`${PARTS}/06${n}-endpoints-${from}-${to}.md\`, empezando con \`## Endpoints (main.py ${from}–${to})\`.`,
  })
})

// ── backend módulos ─────────────────────────────────────────
READERS.push(
  {
    id: '07-retorno', label: 'motores de retorno', title: 'Motores de retorno: TWR, performance, P&L realizado, flujos',
    prompt: `Documentá los MOTORES DE RETORNO. Es la parte más crítica del sistema: son los números que justifican el producto.

Archivos: \`backend/twr.py\` (2213 líneas), \`backend/performance.py\`, \`backend/realized_pnl.py\`, \`backend/flujos.py\`, \`backend/ledger_replay.py\`, \`backend/advisor_twr.py\`, \`backend/analysis_prep.py\`.

Para CADA módulo:
- Qué calcula, con qué metodología (TWR / MWR / simple / dietz), y cuál es su **output de negocio**.
- La **fórmula literal** tal como está en el código, con archivo:línea.
- Qué datos consume (tablas, precios, FX) y qué pasa cuando falta un dato.
- Quién lo llama (grepeá los importadores).
- Manejo de casos borde: capital cero o negativo, períodos sin datos, traspasos entre brokers, cambios de moneda.

Después, secciones transversales:
- **\`twr.py\`**: mapeá su estructura interna (¿cómo se parten los períodos? ¿qué es un "período" en \`twr_periods\`? ¿cómo se encadenan los sub-retornos? ¿qué pasa con un flujo de fondos intra-período?).
- **\`ledger_replay.py\`**: qué es "reproducir el ledger", cuándo corre, y qué relación tiene con el rebuild del importador.
- **\`realized_pnl.py\`**: cómo se matchea una venta contra el costo. ¿FIFO? ¿pool único o por broker? ¿qué pasa con ventas cross-currency?
- **\`flujos.py\`**: qué es un "flujo" (aporte/retiro), cómo se distingue un aporte real de un movimiento interno, y cómo se trata una conversión de moneda.
- **CLAMPS / cotas**: buscá los límites de plausibilidad que se aplican a los retornos (grepeá \`clamp\`, \`cap\`, \`max(\`, \`min(\`, umbrales tipo \`3\` o \`100\`). Documentá cada cota, su umbral y qué pasa cuando se activa.
- **⚠️ DUPLICACIÓN**: si dos motores calculan el mismo retorno de forma distinta, es el hallazgo más valioso que podés reportar. Buscalo activamente y mostrá las dos fórmulas lado a lado.

Escribí en \`${PARTS}/07-retorno.md\`.`,
  },
  {
    id: '08-importing-a', label: 'import: pipeline', title: 'Importación — pipeline, persistencia y reconstrucción',
    prompt: `Documentá el núcleo del subsistema de IMPORTACIÓN.

Archivos: \`backend/importing/pipeline.py\` (1354), \`persister.py\` (1705), \`normalizer.py\`, \`mapper.py\`, \`validator.py\`, \`invariantes.py\`, \`rebuild.py\` (991), \`recompute_backfill.py\` (725), \`tenencia.py\` (1999), \`seed.py\`, \`schema.py\`, \`preview.py\`, \`excel.py\`, \`cash_sim.py\`, \`fci_map.py\`, \`maturity.py\`, \`fx_migrate.py\`, \`sections.py\`, \`proyeccion.py\`, \`tickers_cd.py\`. Más \`backend/sim_import.py\`.

Cubrí:
- **Pipeline end-to-end**: de un archivo subido hasta filas en \`positions\`/\`operations\`. Pasos numerados en orden, con función y línea de cada uno.
- **Esquema normalizado**: qué campos tiene una transacción normalizada (\`schema.py\`), con cita. Es el contrato interno más importante del sistema.
- **Persistencia**: cómo se crean/actualizan posiciones y operaciones, dedupe, idempotencia, qué pasa al re-importar el mismo archivo.
- **⚠️ Rebuild / recompute**: qué es, cuándo corre, **qué pisa**. Identificá TODOS los escritores posteriores que puedan sobrescribir lo que dejó el persister — un fix aplicado en el persister que después el rebuild pisa es un patrón conocido y grave de este repo. Hacé una lista explícita del orden de escritura.
- **\`tenencia.py\`** (1999 líneas): el modo "foto" de tenencia. Qué brokers lo soportan, qué hace con los activos ausentes de la foto (¿los cierra?), cómo convive una foto con el historial de movimientos, y qué es un "cierre sintético".
- **\`invariantes.py\`** y **\`validator.py\`**: qué chequean, con qué tolerancia, y **si están vivos** (grepeá quién los llama). Si están dormidos, decilo.
- **\`fx_migrate.py\`**: qué migra y cuándo se dispara.
- **\`cash_sim.py\`**: la simulación/reconciliación de caja.
- **Incidentes**: cómo se registran los errores y dónde los ve el usuario.
- **\`sim_import.py\`** y \`proyeccion.py\`: qué son y si están en uso.

Escribí en \`${PARTS}/08-importing-pipeline.md\`.`,
  },
  {
    id: '09-importing-b', label: 'import: parsers', title: 'Importación — parsers por broker',
    prompt: `Documentá los PARSERS de brokers: \`backend/importing/parsers/\` completo.

Archivos: \`registry.py\`, \`base.py\`, \`balanz.py\`, \`balanz_internacional.py\`, \`balanz_movimientos.py\`, \`balanz_resultados.py\`, \`binance.py\`, \`binance_futures.py\`, \`binance_transaction.py\`, \`bullmarket.py\`, \`cocos.py\`, \`generic.py\`, \`ieb.py\`, \`inviu.py\`, \`iol.py\` (787), \`ppi.py\`, \`schwab.py\`.

Cubrí:
- **El registry**: cómo se elige el parser para un archivo (¿por nombre? ¿por sniffing de encabezados?). Citá la función de detección. ¿Qué pasa si dos parsers matchean?
- **\`base.py\`**: el contrato que todo parser cumple.
- **Tabla maestra**: broker | archivo | formatos/hojas que acepta | cómo se detecta | tipos de movimiento que reconoce | ¿trae precios? ¿trae comisiones? ¿trae FX? | limitaciones conocidas.
- Para CADA parser, una ficha con: qué export del broker consume (nombre del archivo/reporte tal como lo baja el usuario), cómo determina la **dirección** del movimiento (compra vs venta — varios usan tokens o signos, y ahí hay bugs históricos), cómo mapea el ticker, cómo trata la moneda, y los TODOs/comentarios que revelen limitaciones.
- **Casos especiales que valen la pena mirar de cerca**: bonos per-100 vs per-1, CEDEARs y su pata en dólares, FCIs, cauciones, transferencias, dólar MEP comprado vía bonos, cripto.
- **Duplicación entre parsers**: lógica copiada de uno a otro. Marcala.
- Parsers que parecen incompletos o abandonados.

Escribí en \`${PARTS}/09-importing-parsers.md\`.`,
  },
  {
    id: '10-ai', label: 'ai', title: 'Subsistema de IA',
    prompt: `Documentá el subsistema de IA: \`backend/ai/\` completo.

Archivos: \`llm.py\`, \`prompts.py\` (1687), \`registry.py\`, \`schema.py\`, \`cache.py\`, \`quota.py\`, \`plan.py\`, \`trade_tickers.py\`, \`ar_bonds_metadata.py\`, y los ~35 de \`builders/\`.

Cubrí:
- **Proveedor y modelos**: qué API, qué model ids exactos, con qué parámetros (temperature, max_tokens). Citá el/los model id literales. ¿Hay más de un modelo según el tier?
- **Registry**: cómo se registra un builder, cuál es el contrato. **Tabla maestra**: builder | archivo | qué analiza | qué datos consume | qué endpoint lo expone | dónde se muestra en el front.
- **Prompts**: estructura de \`prompts.py\`, qué prompts existen, y **qué contexto de la cartera se le manda al modelo**. Enumerá los datos del usuario que salen del sistema hacia el proveedor del LLM (montos, tickers, email, nombre). Es información sensible: sé preciso.
- **Cache**: clave, TTL, invalidación. ¿La clave incluye el user_id? (si no, es un leak entre usuarios — verificalo con cuidado).
- **Cuota**: límites por tier, cómo se cuentan (\`ai_usage_daily\`, \`ai_tool_usage\`), qué pasa al pasarse, si se puede evadir.
- **⚠️ Tools / function calling**: si el modelo puede **ejecutar acciones** (registrar operaciones por chat, etc.), listá CADA tool, qué escribe en la DB, y qué validación hay entre la salida del modelo y el INSERT. Un LLM escribiendo en la base financiera del usuario merece un análisis detallado: ¿hay confirmación humana? ¿se puede deshacer?
- **Streaming**: si hay SSE, dónde y cómo.
- **\`ai_user_facts\`**: qué "hechos" del usuario se persisten, quién los escribe, si el usuario los ve.
- Builders muertos: registrados pero que ningún endpoint expone, o al revés.

Escribí en \`${PARTS}/10-ai.md\`.`,
  },
  {
    id: '11-billing', label: 'billing', title: 'Facturación, suscripciones, trial y planes',
    prompt: `Documentá el subsistema de FACTURACIÓN: \`backend/billing/\` completo (\`subscriptions.py\`, \`trial.py\` 1200 líneas, \`rebill.py\`, \`mercadopago.py\`, \`pricing.py\`, \`credits.py\`, \`emails.py\` 1676 líneas).

Cubrí:
- **Procesadores de pago**: cuáles hay (Rebill, MercadoPago), cuál está activo hoy, cómo se elige (env var / flag). Citá.
- **Catálogo de planes y precios** exacto tal como está en \`pricing.py\`: tabla plan | precio | moneda | período | qué incluye.
- **Ciclo de vida de una suscripción**: máquina de estados con los valores reales del campo \`status\`. Alta → pago → renovación → falla → downgrade → cancelación. Diagramá las transiciones y decí qué las dispara.
- **⚠️ Webhooks**: qué endpoints reciben webhooks, **¿se valida la firma?** Citá el código de validación o escribí **no encontrado**. ¿Son idempotentes? ¿Un webhook repetido acredita dos veces? Buscá la protección y citala.
- **Créditos y prorrateo**: cómo se calcula el crédito al cambiar de plan, cómo se asienta en \`credit_ledger\`, cómo se consume.
- **Trial** (\`trial.py\`): duración, cómo se decide el vencimiento, qué pasa al vencer, \`trial_consumed\` y \`trial_email_log\`, y cómo se evita que un usuario lo repita.
- **Emails transaccionales** (\`emails.py\`): inventario completo — email | cuándo se dispara | archivo:línea | proveedor. Incluí los del trial y los de billing.
- **Herramientas de admin**: regalar plan, cambiar tier, otorgar crédito. A qué endpoint pegan.
- **Plan asesor**: cómo se cobra (¿por cliente? ¿flat?), si tiene un flujo distinto.

Escribí en \`${PARTS}/11-billing.md\`.`,
  },
  {
    id: '12-asesor', label: 'asesor', title: 'Producto asesor (B2B2C)',
    prompt: `Documentá el PRODUCTO ASESOR completo. El founder dice que hay "un plan separado para asesores financieros" — documentá qué hay realmente.

Backend: \`backend/advisor_twr.py\`, \`advisor_brief.py\`, \`advisor_groups.py\`, \`advisor_alerts.py\`, más todos los endpoints \`/api/advisor*\` de \`main.py\` (grepealos) y las tablas \`advisor_*\`.
Frontend: \`frontend/src/pages/AdvisorDashboard.jsx\` (1113), \`AdvisorClients.jsx\` (999), \`AdvisorNovedades.jsx\`, \`AdvisorAccessRequest.jsx\`, \`ClaimAccount.jsx\`, \`frontend/src/components/advisor/\` (8 componentes), \`frontend/src/contexts/AdvisorContext.jsx\`, \`frontend/src/utils/bookComposition.js\`.

Cubrí:
- **Modelo de la relación asesor↔cliente**: cómo se representa, qué estados tiene, cómo se crea y cómo se revoca.
- **Los tres caminos de alta de un cliente** (verificá cuáles existen realmente): (a) el asesor crea la cuenta del cliente, (b) invitación a alguien que ya tiene Rendi → pedido de acceso, (c) el cliente reclama una cuenta que le armó el asesor (\`ClaimAccount.jsx\`, \`advisor_claim_tokens\`). Documentá cada flujo end-to-end con citas.
- **⚠️ Autorización**: cuando el asesor pide datos de un cliente, ¿dónde se verifica que sea suyo? ¿Es un chequeo en el backend o solo un filtro en el front? Revisá **cada** endpoint de asesor y decí cuáles validan y cuáles no. Este es el punto más importante de la sección.
- **El "libro"**: qué es, cómo se agrega la cartera de todos los clientes, y qué métricas se calculan a nivel libro (TWR del libro, composición, alertas cross-cliente).
- **Grupos** (\`advisor_groups\`): para qué sirven.
- **Brief / informe del período** (\`advisor_brief.py\`, \`advisor_reports\`): qué genera, con qué frecuencia, cómo se entrega (¿email? ¿link público? mirá \`ReportPublic.jsx\` — si hay un informe accesible sin login, documentá cómo se protege el link).
- **Alertas de asesor** (\`advisor_alerts.py\`): qué dispara una alerta, cómo se notifica.
- **Operaciones en lote** (\`advisor_op_batches\`): el asesor cargando operaciones para varios clientes.
- Qué está implementado, qué está a medias, y qué diferencias hay con el producto retail.

Escribí en \`${PARTS}/12-asesor.md\`.`,
  },
  {
    id: '13-analitica', label: 'analítica', title: 'Motores de análisis: reporting, behavioral, wrapped, objetivos',
    prompt: `Documentá los MOTORES DE ANÁLISIS.

Archivos: \`backend/reporting/\` (\`builder.py\` 2141 líneas, \`detectors.py\`, \`timeline.py\`, \`schema.py\`), \`backend/behavioral.py\` (1880), \`backend/wrapped.py\`, \`backend/goals_diagnostic.py\`, \`backend/home/briefing.py\`, \`backend/home/market.py\`.

Para cada motor: qué produce, qué endpoint/pantalla lo consume, qué datos usa, y las fórmulas concretas con su línea.

En detalle:
- **\`reporting/builder.py\`** (2141 líneas): qué es un "reporte de período", cómo se arma. Mapeá sus secciones internas. Cómo se calculan los números del período (capital inicial, final, aportes, retiros, resultado). Prestá atención a la distinción **"certero" vs "estimado"** si aparece: qué la determina y qué se le muestra al usuario en cada caso.
- **\`reporting/detectors.py\`**: listá CADA detector, qué detecta, con qué umbral, y qué frase genera.
- **\`reporting/timeline.py\`**: cómo se construye el eje temporal, qué pasa con meses sin datos.
- **\`behavioral.py\`** (1880 líneas): mapeá sus secciones y qué métrica de comportamiento calcula cada una (sesgos, timing, rotación, concentración...). Tabla: métrica | función:línea | fórmula | qué le dice al usuario.
- **\`goals_diagnostic.py\`**: cómo se evalúa el progreso de un objetivo.
- **\`wrapped.py\`**: el resumen anual — ¿está vivo o es estacional? ¿qué endpoint lo expone?
- **\`home/briefing.py\`** y **\`home/market.py\`**: qué arman para la home.
- **⚠️ Duplicación**: si dos motores calculan la misma métrica de forma distinta, buscalo activamente y mostrá las dos versiones. Comparalos también contra \`backend/twr.py\` y \`performance.py\`.

Escribí en \`${PARTS}/13-analitica.md\`.`,
  },
  {
    id: '14-precios-fx', label: 'precios+fx', title: 'Capa de precios y tipos de cambio',
    prompt: `Documentá la CAPA DE PRECIOS y de TIPOS DE CAMBIO.

Archivos: \`backend/fx.py\`, \`backend/price_history.py\`, \`backend/pricing/fci.py\`, \`backend/pricing/bond_amortization.py\`, y las funciones de precio de \`backend/main.py\` (grepeá \`_fetch_one\`, \`_fetch_prev_close\`, \`data912\`, \`_resolve_ar_bond_price\`, \`_prices_cache\`, \`_fill_last_known\`, \`crypto_broker_factor\`, \`_current_ccl\`, \`_current_cedear_rate\`, \`_current_cripto_rate\`, \`_display_blue\`, \`_display_ccl\`, \`_fetch_dolar\`).

Cubrí:
- **Tabla maestra de precios**: tipo de activo (acción US / CEDEAR / acción .BA / bono AR / bono USD / cripto / FCI / plazo fijo / futuro / efectivo) → fuente primaria | función:línea | fallback 1 | fallback 2 | cache y TTL | unidad (per-1 o per-100) | moneda del precio.
- **Qué pasa cuando no hay precio**: ¿se muestra "—"? ¿se usa el último conocido? ¿se excluye del total? Citá. Y decí cómo eso afecta el valor total de la cartera.
- **⚠️ Dólares**: enumerá TODOS los tipos de cambio que maneja el sistema (blue, MEP, CCL, cripto, CEDEAR, oficial, tarjeta, mayorista...). Para cada uno: de dónde sale, con qué frecuencia se actualiza, dónde se persiste, y **para qué se usa exactamente**. Después hacé una tabla de decisión: contexto (valuar un CEDEAR, valuar cripto en un broker AR, convertir un aporte en pesos, mostrar el total en pesos...) → qué dólar se usa → dónde está esa decisión en el código.
- **Override manual del usuario**: si el usuario puede fijar un TC en \`/config\`, documentá dónde se aplica y dónde se ignora.
- **\`fx_rates_daily\`**: cómo se puebla, qué pasa con los días faltantes (¿se interpola? ¿se usa el anterior?), y qué se hace con una fecha futura.
- **Bonos**: la escala per-100, la paridad, y \`bond_amortization.py\` (amortización = devolución de capital, no renta).
- **FCIs**: \`pricing/fci.py\` — de dónde sale el precio, el vcp/1000.
- **\`price_history.py\`** y \`asset_price_history\`: el histórico de precios, cómo se rellena (backfill) y para qué se usa.

Escribí en \`${PARTS}/14-precios-fx.md\`.`,
  },
  {
    id: '15-jobs', label: 'jobs+alertas', title: 'Jobs, tareas programadas, alertas y procesos en segundo plano',
    prompt: `Documentá los JOBS y PROCESOS EN SEGUNDO PLANO.

Archivos: \`backend/snapshots_job.py\` (1049), \`backend/alerts_engine.py\`, \`backend/mantenimiento.py\`, \`backend/scripts/\` completo (backfills, backup, mkschema, copiar_a_postgres, verificar_*, base_sintetica, escala_foto_bonos, seed_cuenta_unificada, vigilar_espacio, pg_type_audit), y el scheduler de \`main.py\` (grepeá \`BackgroundScheduler\`, \`CronTrigger\`, \`add_job\`, \`BackgroundTasks\`, \`ThreadPoolExecutor\`, \`threading.Thread\`).

Cubrí:
- **Inventario de jobs programados**: tabla nombre | archivo:línea | schedule (cron exacto + zona horaria) | qué hace | qué escribe | cuánto tarda (si hay pistas).
- **¿Dónde corre el scheduler?** ¿In-process con el server web? ¿Qué pasa con múltiples réplicas o con un restart de Railway? Buscá comentarios sobre esto — es un problema conocido del repo. Documentá el mecanismo actual y su fragilidad.
- **Trabajo disparado por request**: cada \`BackgroundTasks\`, thread o executor, con qué lo dispara y qué riesgo tiene.
- **\`snapshots_job.py\`** (1049 líneas): qué es un snapshot, qué campos guarda, a qué hora corre, qué dólar usa, **qué pasa si un día no corrió** (¿se rellena después? ¿queda un hueco?), y cómo eso afecta la variación diaria que ve el usuario.
- **\`alerts_engine.py\`**: qué tipos de alerta existen (precio, variación %), cómo se evalúan, cada cuánto, cómo se notifica (push / email), qué es \`alert_symbol_state\`, y cómo se evita repetir la misma alerta.
- **Backfills**: cada script — qué recomputa, qué pisa, si es idempotente, si se corre a mano o automático. Especial atención a \`backfill_historical_mtm.py\` y \`recompute_backfill\`.
- **Push notifications**: si están vivas, con qué servicio.
- **\`backend/scripts/test_*.py\`**: ¿son tests o scripts sueltos? ¿los corre alguien?
- **Migración a Postgres**: \`mkschema.py\`, \`copiar_a_postgres.py\`, \`verificar_copia.py\`, \`pg_type_audit.py\` — en qué estado está.

Escribí en \`${PARTS}/15-jobs.md\`.`,
  },
  {
    id: '16-externos', label: 'servicios externos', title: 'Servicios externos y APIs de terceros',
    prompt: `Inventariá TODOS los SERVICIOS EXTERNOS y APIs de terceros.

Método: grepeá en \`backend/\` y \`frontend/src/\` por \`http://\`, \`https://\`, \`requests.\`, \`httpx\`, \`urlopen\`, \`fetch(\`, \`yfinance\`, \`yf.\`, e imports de SDKs. Revisá también \`backend/iol_api.py\` y \`backend/wallbit.py\`.

Para CADA servicio, una ficha:
### Nombre
- **Para qué se usa** (en negocio).
- **Endpoints concretos** que se llaman, con archivo:línea.
- **Autenticación**: solo el NOMBRE de la env var (nunca el valor).
- **Manejo de fallas**: timeout, retry, fallback. **Qué ve el usuario si el servicio se cae.**
- **Cache**: dónde y por cuánto.
- **Criticidad**: qué deja de funcionar si se cae.
- **Estado**: ¿integración viva, dormida, o spike a medio hacer?

Servicios a cubrir como mínimo (verificá y agregá los que falten): yfinance, data912, argentinadatos (inflación/CER/UVA/dólar), dolarapi, CAFCI (FCIs), Google News RSS, Investing RSS, Anthropic (LLM), Resend (email), MercadoPago, Rebill, IOL API (\`iol_api.py\`), Wallbit (\`wallbit.py\`), push/web-push.

**Integraciones de brokers en particular** (\`iol_api.py\`, \`wallbit.py\`): ¿están vivas en producción o son experimentos? ¿Guardan credenciales del usuario? ¿Qué permisos piden (solo lectura o pueden operar)? Esto es lo más sensible: sé exhaustivo. Mirá también \`user_broker_credentials\` y \`frontend/src/pages/IolLab.jsx\`.

**Frontend**: \`frontend/src/utils/analytics.js\`, \`metaPixel.js\`, \`track.js\`, \`autoUpdate.js\`, \`frontend/index.html\` — qué scripts de terceros se cargan y qué datos del usuario mandan.

Cerrá con una tabla resumen: servicio | criticidad | qué se rompe si se cae | ¿tiene fallback?

Escribí en \`${PARTS}/16-externos.md\`.`,
  },
)

// ── frontend ────────────────────────────────────────────────
const FRONT_FMT = `
Para CADA pantalla usá esta ficha:

### \`/ruta\` → \`frontend/src/pages/Archivo.jsx\`
- **Qué muestra**: los bloques/secciones de la UI, en términos de negocio.
- **De dónde saca los datos**: TODAS las llamadas a la API con el endpoint exacto y la línea. Distinguí lo que viene del backend de lo que se calcula en el browser.
- **⚠️ Cálculos hechos en el cliente**: qué números NO vienen del backend sino que los computa el navegador. Fórmula y línea. Esto es clave para entender dónde puede divergir un número entre pantallas.
- **Estado/contexto** que consume (AuthContext, CurrencyContext, AdvisorContext, AlertsContext, PrivacyContext, ThemeContext, CoachDrawerContext).
- **Gating por plan**: qué se le oculta o bloquea a un usuario free/trial.
- **Variante mobile**: si existe otra implementación de la misma pantalla, decí **en qué divergen** (no alcanza con decir que existe).
- **Rarezas**: código comentado, features detrás de flag, TODOs, imports sin usar, estado que se recalcula de más.
`

READERS.push(
  {
    id: '17-front-cartera', label: 'front: cartera', title: 'Frontend — Home, Cartera, Posiciones',
    prompt: `Documentá las pantallas de CARTERA y HOME.

Archivos: \`frontend/src/pages/Home.jsx\`, \`HomeMobile.jsx\`, \`Dashboard.jsx\` (1550), \`Cartera.jsx\`, \`Positions.jsx\` (4484), \`PositionsMobile.jsx\` (2972), \`PositionDetailMobile.jsx\`, \`MobileSearch.jsx\`, \`AssetDetail.jsx\`. Componentes: \`components/home/\` (11 archivos), \`RentaFijaSections.jsx\`, \`PlazosFijosGroup.jsx\`, \`FuturosGroup.jsx\`, \`CurrencyRail.jsx\`, \`CurrencySwitcher.jsx\`, \`StalePricesNotice.jsx\`, \`TcMissingBadge.jsx\`, \`ModoRendimiento.jsx\`, \`ReturnFxHint.jsx\`, \`BondDetail.jsx\`. Y \`frontend/src/App.jsx\` para las rutas.
${FRONT_FMT}
Prestá atención especial a:
- **\`Positions.jsx\` (4484 líneas) y \`PositionsMobile.jsx\` (2972)**: no los describas por arriba — mapeá sus secciones internas y sus tabs. Y decí explícitamente en qué divergen desktop y mobile.
- La relación entre \`Cartera.jsx\`, \`Positions.jsx\` y \`Dashboard.jsx\`: mirá las rutas en \`App.jsx\` (hay redirects con \`?tab=\`) y decí **qué componente se monta realmente** en cada ruta y cuál quedó huérfano.
- **El número grande**: cuál es exactamente el cálculo del "valor de mi cartera" que ve el usuario arriba de todo, y en qué archivo:línea se computa.
- **El toggle de moneda** (USD/pesos): dónde vive, cómo se propaga, y qué convierte y qué no.
- \`StalePricesNotice\` y \`TcMissingBadge\`: qué condición los dispara — revelan cómo el sistema admite que un dato falta.

Escribí en \`${PARTS}/17-front-cartera.md\`.`,
  },
  {
    id: '18-front-analisis', label: 'front: análisis', title: 'Frontend — Análisis, Insights, Reportes, Comportamiento, Perfil',
    prompt: `Documentá las pantallas de ANÁLISIS.

Archivos: \`frontend/src/pages/Analisis.jsx\`, \`Insights.jsx\` (4783 — la más grande del repo), \`Reports.jsx\` (913), \`Behavioral.jsx\`, \`Monthly.jsx\`, \`Fundamentals.jsx\`, \`Goals.jsx\`, \`Wrapped.jsx\`, \`PerfilInversor.jsx\`, \`FirstInsight.jsx\`, \`ReportPublic.jsx\`. Componentes: \`components/reports/\` (8), \`components/fundamentals/\` (13), \`components/profile/\` (11), \`components/diagnostico/\` (3), \`MonthlySummary.jsx\`, \`InsightsKpiStrip.jsx\`, \`BenchmarksLine.jsx\`, \`CompositionDonut.jsx\`, \`CompositionByRisk.jsx\`, \`ArAlternativesVerdict.jsx\`, \`RecommendationsModal.jsx\`.
${FRONT_FMT}
Prestá atención especial a:
- **\`Insights.jsx\` (4783 líneas)**: mapeá sus tabs y secciones internas una por una. Es la pantalla más compleja del producto.
- Las rutas \`/insights\`, \`/comportamiento\`, \`/reportes\` redirigen a \`/analisis?tab=…\`: decí qué se monta en cada tab y qué quedó huérfano.
- **El benchmark contra S&P / inflación**: dónde se arma la serie. ¿La construye el frontend o la trae el backend? Si el frontend la arma, es un hallazgo importante — documentá la fórmula y el anclaje temporal (¿mensual? ¿fin de mes?).
- **El modo "certero" vs "estimado"** (si aparece): qué lo determina, qué ve el usuario en cada uno, y dónde está el umbral.
- **\`ReportPublic.jsx\`**: ¿es un informe accesible sin login? ¿Cómo se protege el link? ¿Qué datos expone?
- Los cálculos financieros hechos en el browser: rendimiento, drawdown, atribución, CAGR. Documentá cada fórmula con su línea.

Escribí en \`${PARTS}/18-front-analisis.md\`.`,
  },
  {
    id: '19-front-ops', label: 'front: operaciones', title: 'Frontend — Operaciones, Importación, Novedades, Alertas',
    prompt: `Documentá las pantallas OPERATIVAS.

Archivos: \`frontend/src/pages/Operations.jsx\` (1409), \`Novedades.jsx\`, \`Events.jsx\` (1058), \`News.jsx\`, \`Imports.jsx\` (685), \`Alertas.jsx\`, \`More.jsx\`, \`RendiAI.jsx\`. Componentes: \`components/import/\` (ImportWizard.jsx 2980, BrokerInstructions, TenenciaUpload, WallbitConnect), \`components/operations/\` (5), \`components/alerts/AlertsManager.jsx\`, \`components/ai/\` (11), \`AddPositionFlow.jsx\` (944), \`PfFormModal.jsx\`, \`BondCashflowModal.jsx\`, \`PendingCashflowsBanner.jsx\`, \`SplitRatioBanner.jsx\`, \`UpcomingEventsCard.jsx\`, \`TopNewsCard.jsx\`, \`BrokerManager.jsx\`, \`TickerSearch.jsx\`, \`AICoach.jsx\`.
${FRONT_FMT}
Prestá atención especial a:
- **\`ImportWizard.jsx\` (2980 líneas)**: mapeá el flujo completo paso por paso, qué endpoint llama en cada paso, cómo se muestra el preview, cómo se confirma, y cómo se presentan los errores e incidentes al usuario.
- **\`TenenciaUpload.jsx\`**: el flujo de la "foto" de tenencia y qué le advierte al usuario sobre pisar datos.
- **\`AddPositionFlow.jsx\`**: alta manual — qué campos pide, qué valida en el cliente, a qué endpoint postea, y qué se recalcula después.
- **\`AICoach.jsx\` + \`components/ai/\`**: el chat. Cómo se manda el contexto de la cartera, si hay streaming, y **si el chat puede registrar operaciones** (buscá la confirmación humana antes de escribir en la base).
- **\`Alertas.jsx\` + \`AlertsManager.jsx\`**: cómo se crea una alerta, qué tipos hay, cómo se notifica.
- \`/eventos\` y \`/noticias\` redirigen a \`/novedades?tab=…\`: decí qué se monta y qué quedó huérfano.

Escribí en \`${PARTS}/19-front-ops.md\`.`,
  },
  {
    id: '20-front-cuenta', label: 'front: cuenta+admin', title: 'Frontend — Cuenta, config, admin, planes, onboarding, público',
    prompt: `Documentá las pantallas de CUENTA, ADMIN y PÚBLICAS.

Archivos: \`frontend/src/pages/Login.jsx\`, \`ResetPassword.jsx\`, \`VerifyEmail.jsx\`, \`Onboarding.jsx\`, \`Config.jsx\` (1573), \`Admin.jsx\` (3265), \`Planes.jsx\` (1075), \`BillingReturn.jsx\`, \`IolLab.jsx\`, \`Landing.jsx\` (1560), \`Blog.jsx\` + \`pages/blog/\`, \`Guia.jsx\` + \`pages/guia/\`, \`pages/keywords/\`, \`Terminos.jsx\`, \`Privacidad.jsx\`, \`Reembolso.jsx\`. Componentes: \`components/onboarding/\`, \`components/landing/\`, \`components/guide/\`, \`components/plan/\`, \`Sidebar.jsx\`, \`components/mobile/\`, \`ShareCardModal.jsx\`, \`InvestorProfileForm.jsx\`, \`ErrorBoundary.jsx\`.
${FRONT_FMT}
Prestá atención especial a:
- **\`Admin.jsx\` (3265 líneas)**: es la superficie más sensible. Enumerá **TODAS** las acciones de admin disponibles y a qué endpoint pega cada una. Tabla: acción | endpoint | qué modifica | ¿es reversible?
- **\`Config.jsx\` (1573)**: todas las preferencias del usuario, dónde se guardan, y marcá cuáles **afectan cálculos financieros** (TC manual, moneda de valuación, modo de rendimiento). Una preferencia que cambia un número mostrado merece cita explícita.
- **\`Planes.jsx\`**: ¿los precios están hardcodeados en el front o vienen del backend? Comparalos contra \`backend/billing/pricing.py\`. **Si divergen, es un hallazgo.**
- **\`Onboarding.jsx\`**: el flujo de alta paso por paso.
- **\`IolLab.jsx\`**: el laboratorio de IOL — qué hace, quién puede entrar, si pide credenciales del broker.
- **Navegación**: \`Sidebar.jsx\` + \`components/mobile/MobileTabBar.jsx\` — el mapa real del menú. Si hay ítems que apuntan a rutas inexistentes o rutas sin ítem de menú, decilo.
- Páginas de marketing/SEO: panorama general, cuáles son estáticas y cuáles consumen datos.

Escribí en \`${PARTS}/20-front-cuenta.md\`.`,
  },
  {
    id: '21-front-nucleo', label: 'front: núcleo', title: 'Frontend — utils, hooks, contexts, capa de datos',
    prompt: `Documentá el NÚCLEO del frontend: la capa de datos y las librerías de cálculo del cliente. Es donde vive mucha lógica financiera que uno esperaría en el backend.

Archivos: todo \`frontend/src/utils/\`, \`frontend/src/hooks/\` (18), \`frontend/src/contexts/\` (8), \`frontend/src/App.jsx\`.

Cubrí:
- **\`utils/api.js\`**: base URL, credenciales, manejo de 401, reintentos (\`apiRetry\`, \`gatewayRetry\`), y qué pasa cuando el backend está frío (Railway cold start).
- **Inventario completo de utils**: tabla \`archivo | qué hace | exports | quién lo usa | ¿tiene .test.js?\`. Marcá 💀 los que no importa nadie (verificá con grep por cada export).
- **Los utils con lógica FINANCIERA** merecen una ficha propia con la **fórmula y su línea**: \`valuation.js\` (945), \`valuationGuards.js\`, \`insightsModel.js\` (1087), \`insightsMetrics.js\`, \`insights.js\`, \`evolution.js\`, \`diagnostics.js\` (1010), \`diagnosticsRotation.js\`, \`assetPnl.js\`, \`assetClass.js\`, \`assetSector.js\`, \`tradeStats.js\`, \`bondPricing.js\`, \`bondSchedule.js\`, \`bondSchedulesAR.js\`, \`bondCashflowFx.js\`, \`bondMeta.js\`, \`fx.js\`, \`fxPanel.js\`, \`crypto.js\`, \`benchmarkSim.js\`, \`bookComposition.js\`, \`brokerAccounts.js\`, \`pendingCashflows.js\`, \`upcomingEvents.js\`, \`profileMatch.js\`, \`profileAllocations.js\`, \`profileDashboard.js\`, \`fundamentalsCompare.js\`, \`sections.js\`, \`positionsDiscovered.js\`, \`tickers.js\`, \`format.js\`.
- **Hooks**: qué trae cada uno, de qué endpoint, con qué cache/estado.
- **Contexts**: \`AuthContext\`, \`AdvisorContext\` (el contexto de "estoy viendo a mi cliente X"), \`CurrencyContext\` (el toggle global — cómo se propaga y qué convierte), \`AlertsContext\`, \`PrivacyContext\` (¿modo privacidad que oculta montos?), \`ThemeContext\`, \`CoachDrawerContext\`.
- **\`utils/demo.js\` (3223 líneas)**: qué es el modo demo, con qué datos, cómo se activa, y **si puede filtrarse a un usuario real**.
- **\`utils/tickers.js\` (629)**: el allowlist de tickers — cómo funciona y qué pasa con uno que no está.
- **\`utils/autoUpdate.js\`**: el mecanismo de recarga a un bundle nuevo.
- **\`utils/safeUrl.js\`**: para qué se creó (suele indicar que hubo un problema de seguridad).

Escribí en \`${PARTS}/21-front-nucleo.md\`.`,
  },
  {
    id: '22-tests', label: 'tests', title: 'Suite de tests y cobertura real',
    prompt: `Documentá la SUITE DE TESTS. **No corras nada**, solo leé.

Fuentes: \`backend/tests/\` (241 archivos), \`backend/tests/fixtures/\`, \`backend/scripts/test_*.py\`, y los \`*.test.js\`/\`*.test.jsx\` de \`frontend/src/\`.

Cubrí:
- **Cómo se corren**: comando exacto para backend y frontend (mirá \`frontend/package.json\`, y buscá \`pytest.ini\`, \`pyproject.toml\`, \`setup.cfg\`, \`conftest.py\`). Si un \`pytest\` pelado colecta cosas que no debería (p.ej. \`scripts/test_*.py\`), decilo.
- **Inventario backend agrupado por subsistema**: importación, cálculo, billing, auth, asesor, IA, reporting. Tabla: archivo | qué cubre | tests aprox.
- **Inventario frontend**: idem.
- **Agujeros de cobertura**: cruzá contra los subsistemas críticos y nombrá los concretos. ¿Está testeado el TWR? ¿El FIFO? ¿La autorización del asesor? ¿Los webhooks de pago?
- **⚠️ Tests que no atraviesan la ruta real**: buscá tests que llamen directo a una función interna salteándose el pipeline completo — por ejemplo un test del persister que no pasa por el rebuild posterior. Un test verde que no refleja producción es un hallazgo importante: nombralo con archivo y línea.
- **Fixtures**: \`backend/tests/fixtures/\`, si se usa una DB real, en memoria o temporal, y si algún test puede tocar la base de desarrollo.
- **CI**: buscá \`.github/\`, \`.gitlab-ci.yml\`, etc. Si no hay, escribí **no encontrado**.
- Tests skippeados, marcados como xfail, o comentados.

Escribí en \`${PARTS}/22-tests.md\`.`,
  },
  {
    id: '23-muerto', label: 'código muerto', title: 'Código muerto, duplicado y abandonado',
    prompt: `Buscá sistemáticamente CÓDIGO MUERTO, DUPLICADO y ABANDONADO. Sé metódico, no impresionista.

1. **Endpoints huérfanos**: listá todas las rutas (\`grep -n '^@app\\.' backend/main.py\`) y para cada una grepeá si el frontend la llama (\`grep -rn "la/ruta" frontend/src\`). Ojo con las rutas construidas dinámicamente — verificá antes de declarar huérfano.
2. **Páginas y componentes huérfanos**: para cada archivo de \`frontend/src/pages/\` y \`frontend/src/components/\`, grepeá si alguien lo importa.
3. **Módulos backend sin importadores**: revisá \`backend/*.py\` de raíz uno por uno (\`sim_import.py\`, \`seed.py\`, \`wallbit.py\`, \`iol_api.py\`, \`mantenimiento.py\`, \`price_history.py\`, \`ledger_replay.py\`, \`flujos.py\`, \`performance.py\`…) y decí quién los importa.
4. **Utils frontend sin importadores.**
5. **⚠️ Duplicación** (lo más valioso): buscá la MISMA lógica implementada dos veces. Pistas concretas: (a) motores de rendimiento backend vs frontend, (b) valuación de cartera calculada en más de un lugar, (c) conversión FX repetida, (d) mobile vs desktop de la misma pantalla que divergieron, (e) parsers con lógica copiada, (f) \`twr.py\` vs \`performance.py\` vs \`reporting/builder.py\`. Para cada duplicación mostrá las dos implementaciones con sus líneas y decí en qué difieren.
6. **Feature flags apagados**: grepeá \`ENABLED\`, \`FEATURE_\`, \`if False\`, \`return\` temprano, código detrás de env vars que nadie setea.
7. **Bloques comentados** de más de 5 líneas.
8. **TODO / FIXME / HACK / XXX / DEPRECATED / OJO**: inventario completo agrupado por subsistema. Es el mapa de deuda técnica.
9. **Integraciones a medias**: IOL, Wallbit, Postgres/Supabase, push notifications, futuros, WhatsApp. Para cada una: ¿viva, dormida o spike?
10. **Archivos sospechosos**: \`backend/seed.py\` vs \`backend/importing/seed.py\`, los \`.md\` de la raíz, \`test-files/\`.

Para cada hallazgo: archivo:línea, por qué creés que está muerto, y \`[V]\` (verificado con grep) o \`[I]\` (inferido). **Si algo PARECE muerto pero verificaste que sí se usa, decilo también** — evita que alguien lo borre por error.

Escribí en \`${PARTS}/23-muerto.md\`.`,
  },
  {
    id: '24-flujos', label: 'flujos e2e', title: 'Flujos end-to-end',
    prompt: `Trazá los FLUJOS END-TO-END del sistema, cruzando frontend → API → motor → DB. Cada paso con su cita.

Para cada flujo: pasos numerados, cada uno con \`archivo:línea\`, marcando dónde se toman las decisiones importantes y dónde hay bifurcaciones (documentá las dos ramas).

1. **Alta de usuario**: registro → verificación de email → onboarding → primera cartera cargada.
2. **Importar un archivo de broker**: subida → detección de parser → normalización → preview → confirmación → persistencia → rebuild → lo que ve en Cartera. **Marcá cada punto donde algo puede pisar lo anterior.**
3. **Subir una "foto" de tenencia** y cómo convive con el historial de movimientos.
4. **Alta manual de una compra** y todo lo que se recalcula.
5. **Ver la cartera**: qué pide el front, cómo se resuelve el precio de cada activo, qué se calcula en el browser, y cuál es exactamente el número final de "valor de mi cartera".
6. **Vender un activo**: matcheo FIFO contra el costo, qué P&L realizado se asienta y dónde queda.
7. **Un día de mercado**: qué corre el cron nocturno, qué snapshot queda, y cómo eso produce la variación diaria del día siguiente.
8. **Suscribirse a un plan**: checkout → webhook → tier actualizado → features desbloqueadas.
9. **Pedirle un análisis a la IA**: click → builder → armado del contexto → LLM → cache → render.
10. **Un asesor da de alta a un cliente y mira su cartera**: los tres caminos de alta, y el chequeo de permisos en cada request.
11. **Borrar algo** (una operación, un broker, un activo): qué cascada se dispara, qué se recomputa, y qué queda huérfano.

Escribí en \`${PARTS}/24-flujos.md\`.`,
  },
)

// ── conceptos ───────────────────────────────────────────────
const CONCEPTOS = [
  ['c01','tenencia','Tenencia / posición / holding','positions, archived_positions, quantity, cantidad, holdings, tenencia, qty, nominales'],
  ['c02','costo','Costo de adquisición, costo promedio y lotes FIFO','cost_basis, costBasis, entry_price, avg_price, precio_promedio, FIFO, lots, lotes, pool, spill, aggregateLots'],
  ['c03','pnl-realizado','P&L realizado','realized, realizado, pnl, sell, venta, exit_price, resultado, realized_pnl'],
  ['c04','pnl-no-realizado','P&L no realizado / ganancia latente','unrealized, no_realizado, latente, mark_to_market, mtm, gain, plusvalia'],
  ['c05','valuacion','Valuación de cartera / valor de mercado','market_value, mktValue, trustMktValue, valuation, valuacion, computeBrokerValue, patrimonio, total'],
  ['c06','rendimiento','Rendimiento / retorno (simple, TWR, anualizado, CAGR)','return, retorno, rendimiento, twr, time_weighted, annualized, anualizado, cagr, performance'],
  ['c07','tir','TIR / IRR / XIRR / retorno ponderado por dinero','irr, xirr, tir, money_weighted, mwr, npv, dietz'],
  ['c08','capital-aportado','Capital aportado, flujos de fondos, depósitos y retiros','capital_aportado, aportado, capital_inicial, capital_final, deposit, deposito, withdrawal, retiro, flujo, aporte, transfer, traspaso'],
  ['c09','fx','Tipo de cambio (blue, MEP, CCL, cripto) y conversión de moneda','blue, mep, ccl, contadoconliqui, tc_compra, tc_mep, fx_rate, dolar, currency, moneda, cripto_rate, cedear_rate'],
  ['c10','inflacion','Inflación, UVA, CER y ajuste por inflación','inflation, inflacion, uva, cer, ipc, real_return, ajustado, argentinadatos'],
  ['c11','comisiones','Comisiones, impuestos y costos de transacción','commission, comision, fee, tax, impuesto, iva, derechos, arancel, gross_amount, net_amount'],
  ['c12','dividendos','Dividendos, cupones, rentas y amortizaciones','dividend, dividendo, coupon, cupon, renta, amortizacion, amortization, interest, payout, cashflow'],
  ['c13','caja','Caja / cash / saldo disponible','cash, caja, saldo, balance, is_cash, disponible, liquidez, sweep, cash_sim'],
  ['c14','benchmark','Benchmarks y comparación contra índices','benchmark, sp500, spy, merval, gld, shv, indice, alpha, comparacion'],
  ['c15','variacion','Variación diaria / periódica y evolución','variacion, variation, change, daily, diaria, delta, evolution, evolucion, prev_close, priceCoverage'],
  ['c16','snapshot','Snapshot / foto histórica de la cartera','snapshot, foto, historical, historico, capital_final, backfill, mtm'],
  ['c17','bonos','Bonos: escala per-100, paridad, vencimiento y flujos','bond, bono, per100, per_100, nominal, vto, maturity, paridad, data912, amortization'],
  ['c18','cedear','CEDEAR: ratio, split, valuación y pata en dólares','cedear, ratio, split, .BA, isArStock, ccl, subyacente, adr'],
  ['c19','objetivos','Objetivos / metas de inversión','goal, objetivo, meta, target, progress, goals_diagnostic'],
  ['c20','perfil','Perfil de inversor, diversificación, concentración y riesgo','profile, perfil, risk, riesgo, allocation, diversif, concentracion, assetClass, assetSector, profileMatch'],
  ['c21','plan','Plan, tier, trial y cuotas','tier, plan, free, plus, pro, trial, quota, cuota, limit, gating, usePlanFeatures'],
  ['c22','libro','Libro del asesor y métricas cross-cliente','libro, book, bookComposition, advisor, cross, cliente, aum'],
  ['c23','broker','Broker, sub-broker y cuenta unificada','broker, parent_broker_id, broker_pair, sub-broker, cuenta, unificad, · USD'],
  ['c24','alertas','Alertas de precio y de variación','alert, alerta, threshold, umbral, trigger, notificacion, push'],
]

const CONCEPT_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    concepto: { type: 'string' },
    definicionCorta: { type: 'string' },
    sitios: { type: 'integer' },
    implementacionesDivergentes: { type: 'array', items: { type: 'string' } },
    unknowns: { type: 'array', items: { type: 'string' } },
    questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['file', 'concepto', 'definicionCorta', 'sitios', 'implementacionesDivergentes', 'unknowns', 'questions'],
}

// ── EJECUCIÓN — TANDA B: los 8 conceptos que sostienen los números ─
const ELEGIDOS = new Set([
  'tenencia', 'pnl-no-realizado', 'comisiones', 'dividendos',
  'variacion', 'snapshot', 'bonos', 'cedear',
])
const TANDA = CONCEPTOS.filter(([id, slug]) => ELEGIDOS.has(slug))

const MUERTO = READERS.find(r => r.id === '23-muerto')

phase('Conceptos')
log(`Tanda C — ${TANDA.length} conceptos (${TANDA.map(c => c[1]).join(', ')}) + el barrido de código muerto`)

const conceptos = (await parallel(TANDA.map(([id, slug, nombre, pistas]) => () =>
  agent(`${RULES}

---

# TU TAREA: rastreo exhaustivo del concepto «${nombre}»

Sos responsable de UN solo concepto: **${nombre}**. Encontrá **TODOS** los lugares del código donde se **calcula**, se **persiste** o se **lee** — backend y frontend — y documentá cómo se define REALMENTE en cada uno.

Método obligatorio (multi-modal: no te quedes con un solo grep):
1. Grepeá por estas pistas de vocabulario y por las variantes que se te ocurran (inglés y español, camelCase y snake_case): \`${pistas}\`
2. Buscá por la **fórmula**, no solo por el nombre: si el concepto es una resta, un cociente o una acumulación, grepeá el patrón aritmético.
3. Mirá las columnas de la base que lo materializan.
4. Mirá los **tests** (\`backend/tests/\`, \`frontend/src/**/*.test.js\`): un test suele revelar la definición canónica y los casos borde que el autor tenía en mente.
5. Chequeá si hay versión backend **y** frontend, y versión mobile **y** desktop.

Escribí una sección con esta estructura exacta:

## ${nombre}

### Definición según el código
Qué significa en Rendi, en términos de negocio, tal como lo implementa el código — no como lo definiría un libro de finanzas. Si el código lo define de forma no estándar, decilo explícitamente.

### Dónde se calcula
| # | archivo:línea | función/componente | qué hace | fórmula literal del código | ¿fuente o consumidor? |

Copiá la **expresión literal** del código en la columna de fórmula. Ordená poniendo primero lo que parece canónico.

### Dónde se lee / se muestra
| archivo:línea | quién lo consume | cómo se llama en la UI |

### Dónde se persiste
Tabla y columna donde vive, si vive en algún lado. Si siempre se calcula al vuelo, decilo.

### ⚠️ Implementaciones divergentes
**La parte más importante.** Si el mismo concepto se calcula de más de una manera, poné las variantes lado a lado, mostrá en qué difieren y decí qué pantalla ve cuál. Si convergen, escribí explícitamente "verificado: una sola implementación".

### Zonas grises
Lo que no entendiste, lo que parece un bug, lo que contradice otra parte del sistema.

Sé exhaustivo: mejor 40 sitios que 5. Pero cada cita verificada.

Escribí el archivo en \`${PARTS}/30-concepto-${slug}.md\` con la herramienta Write **antes** de devolver nada. Si te quedás corto de tiempo, priorizá tener el archivo completo por sobre una respuesta larga: el archivo es el entregable. Después devolvé el objeto estructurado.`,
    { label: `concepto:${slug}`, phase: 'Conceptos', schema: CONCEPT_SCHEMA })
))).filter(Boolean)

const muerto = await agent(`${RULES}

---

# TU TAREA: ${MUERTO.title}

${MUERTO.prompt}

## Contexto: lo que ya se auditó
El resto del sistema ya está documentado en \`${PARTS}/\` (43 archivos markdown). Si te sirve para decidir si algo está vivo o muerto, consultalos — pero **la fuente de verdad es el código**, no esos documentos.

## IMPORTANTE
Escribí tu archivo con Write **antes** de devolver nada. El archivo es el entregable.`,
  { label: 'código muerto', phase: 'Código muerto', schema: READER_SCHEMA })

return {
  tanda: 'C',
  muerto: muerto ? muerto.file : null,
  deadCode: muerto ? (muerto.deadCode || []) : [],
  hallazgosMuerto: muerto ? (muerto.hallazgos || []) : [],
  pedidos: TANDA.length,
  completados: conceptos.length,
  partes: conceptos.map(c => c.file),
  divergencias: conceptos.flatMap(c => c.implementacionesDivergentes || []),
  unknowns: conceptos.flatMap(c => c.unknowns || []),
  preguntas: conceptos.flatMap(c => c.questions || []),
  definiciones: conceptos.map(c => `${c.concepto}: ${c.definicionCorta} (${c.sitios} sitios)`),
}
