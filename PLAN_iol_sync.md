# PLAN: Sync automático de IOL (read-only)

**Objetivo:** que un usuario de IOL conecte su cuenta una vez y Rendi se mantenga
actualizado solo, sin subir archivos y sin que Rendi pueda operar.

**Fuentes:** `Rendi_IOL_Analisis_Tecnico.docx` (sept 2026) + research previo del
2026-07-05 (memoria `project_iol_api_integration`) + código de Wallbit en `origin/main`.

---

## 0. Las tres verdades que ordenan todo

1. **Ningún MCP sirve.** Ni el oficial de IOL ni los comunitarios están pensados para
   que un backend sincronice miles de cuentas. El camino es la **API REST v2 de IOL**
   directo desde el backend (FastAPI, no Node como asume el informe).
2. **No existe token de solo lectura.** Auth es password grant: usuario + contraseña
   reales → bearer 15 min + refresh token. El mismo token lee Y opera. El "read-only"
   lo garantiza Rendi con código, no IOL.
3. **No hay push.** Ni webhooks ni app registrada. Actualización automática = polling
   con un token guardado. No hay forma de tener auto-update sin custodiar algo que,
   en manos equivocadas, tradea.

De (2) y (3) sale LA decisión de producto que hay que cerrar antes de codear:

| Modo | Qué guarda Rendi | Auto-update | Riesgo si roban la DB |
|---|---|---|---|
| **A. En sesión** | Nada. Pide user/pass, baja todo, descarta | ❌ El user aprieta "Actualizar" | Cero |
| **B. Refresh token** | Solo el refresh token, cifrado Fernet | ✅ Mientras el refresh viva | Pueden operar hasta que el user cambie la clave |
| **C. Contraseña** | User + pass cifrados (lo que propone el informe) | ✅ Siempre | Cuenta entera, permanente |

**Recomendación: A primero, B como opt-in explícito, C nunca.**
B depende de un dato que nadie tiene: cuánto vive el refresh token. Lo mide la Fase 0.

---

## 1. Qué ya existe y se reusa (todo en `origin/main`)

| Pieza | Dónde | Cómo se reusa |
|---|---|---|
| Patrón de integración read-only por API | `backend/wallbit.py` + `main.py:30485-30790` | Copiar la estructura: cliente httpx, `*_to_normalized_tx`, connect/sync/disconnect/status |
| Credenciales cifradas | tabla `user_broker_credentials` (`main.py:684`), `_wallbit_cipher/_encrypt/_decrypt` | Misma tabla, `broker='iol'`. Agregar columnas `refresh_token_enc`, `token_expires_at`, `last_op_number` |
| Sync que reusa el pipeline de CSV | `_wallbit_do_sync` (`main.py:30650`) | Mismo esqueleto: fetch HTTP fuera de txn → lock por uid → `store_preview_txs` → `_wallbit_apply_batch` → rebuild FIFO |
| Reconciliación contra la foto real | `_wallbit_reconcile_positions` + `importing/tenencia.py` (`TenenciaSnapshot`, `compute_reconcile`) | Foto = `/api/v2/portafolio/argentina` (+ `/estadocuenta` para cash). Siembra huecos, reduce sobrantes, ajusta cash. Es lo que cierra dividendos/transferencias aunque la API no los exponga |
| Mapeo semántico de IOL | `importing/parsers/iol.py`: `_resolve_op`, `_clean_ticker` (sufijo D/C), `_detect_iol_conduits` (dólar MEP), `_detect_iol_fci_phantoms` | Extraer a funciones puras que acepten filas dict; el parser CSV y el adaptador JSON las comparten. Ya resuelve compra/venta/FCI/dividendo/renta/amortización/depósito/retiro |
| Cron externo | `/api/snapshots/run-cron` (`main.py:32689`), header `X-Cron-Token` | `/api/iol/run-cron` con `IOL_CRON_TOKEN`, disparado por cron-job.org. Corre en thread, 200 inmediato |
| Wizard "Integración con broker" | `frontend/src/components/import/WallbitConnect.jsx`, `ImportWizard.jsx` | Segunda card: `IolConnect.jsx` |
| Dedup cross-fuente | `_import_pipeline._row_fingerprint` | ⚠️ Ver riesgo R5: el fingerprint del CSV y el del JSON no van a coincidir. Usar el **número de boleto de IOL** como clave de dedup entre fuentes |

**Rama:** nueva desde `origin/main`. Esta rama (`fix/ai-stale-position`) está 722 commits atrás; no sirve de base.

---

## 2. Fases

### Fase 0: Spike con cuenta real de un TESTER (1-2 días de calendario, 10 min de su tiempo + días de espera)

Nico no tiene cuenta de IOL. Lo corre un tester. Dos caminos:
- **A (prod, el principal) — IOL Lab ✅ construido en rama `feat/iol-lab`** (worktree `~/rendi-worktrees/iol-lab`): página escondida `/lab/iol` + `POST /api/iol/lab/probe` (login + probe read-only en thread, resultado anonimizado en `iol_lab_runs` + mail al admin), opt-in que guarda SOLO el refresh token cifrado (`user_broker_credentials`, broker `iol_lab`) y `/api/iol/lab/run-cron` (cron-job.org cada hora, `X-Cron-Token`=`IOL_LAB_CRON_TOKEN`) que lo renueva y registra en `iol_lab_token_log` cuándo muere. Gate: `IOL_LAB_EMAILS` o admin. Admin lee todo en `/api/admin/iol-lab/runs`. Cliente `backend/iol_api.py` sin métodos de escritura + allowlist (`tests/test_iol_lab.py`, 6 tests). Contesta además lo que el script local no puede: si IOL acepta la IP de Railway y el rate limit real desde prod.
  Deploy: setear `IOL_LAB_EMAILS` + `IOL_LAB_CRON_TOKEN` en Railway, job horario en cron-job.org → `GET /api/iol/lab/run-cron` con header `X-Cron-Token`.
- **B (local) — `backend/scripts/iol_spike.py` + `IOL_SPIKE_README.md`**: mismo probe en la máquina del tester, para quien prefiera que su contraseña no pase por Rendi.

**Verificado 2026-09-01 contra `api.invertironline.com` (swagger v2, 48 paths, guardado en scratchpad `iol_swagger_v2.json`):**
- Activación: **confirmado** que hay que pedirla por Mensajes en IOL y aceptar TyC en Mi Cuenta → Personalización → APIs. Fricción de onboarding real (R4). El tester la pide primero; medir cuántos días tarda.
- `GET /api/v2/operaciones` filtra por `filtro.estado` (todas/pendientes/terminadas/canceladas), `filtro.fechaDesde`, `filtro.fechaHasta`, `filtro.pais`. Devuelve `numero, fechaOrden, tipo, estado, mercado, simbolo, cantidad, monto, precio, fechaOperada, cantidadOperada, precioOperado, montoOperado, plazo`. `tipo` en el detalle es enum: compra, venta, caucion, suscripcion, rescate, suscripcionPrimaria, suscripcionFCI, rescateFCI.
- `GET /api/v2/operaciones/{numero}` trae `aranceles[]`, `arancelesARS`, `arancelesUSD`, `estados[]`, `operaciones[]` (fills). Comisiones = 1 pedido extra por operación.
- `GET /api/v2/portafolio/{argentina|estados_Unidos}` → `activos[{cantidad, ppc, ultimoPrecio, valorizado, gananciaDinero, titulo{simbolo, tipo, moneda, mercado}}]`. `titulo.tipo` distingue cEDEARS / aCCIONES / titulosPublicos / fONDOSDEINVERSION / oBLIGACIONESNEGOCIABLES / letras... → resuelve `asset_type` sin heurística.
- `GET /api/v2/estadocuenta` → `cuentas[{tipo (inversion_Argentina_Pesos/Dolares, inversion_Estados_Unidos_Dolares), moneda, disponible, comprometido, saldo, titulosValorizados, saldos[]}]`.
- 🔴 **No existe endpoint de movimientos de caja para retail.** Los `cuentas-bancarias/*` que cita el informe (y el MCP comunitario) NO están en el swagger v2. El único es `POST /api/v2/Asesor/Movimientos` (rol asesor). Consecuencia: **dividendos, renta, amortización, depósitos, retiros y transferencias de títulos casi seguro NO vienen por API**; `operaciones` son solo ÓRDENES. El .xls sí los trae (`parsers/iol.py` los mapea). Se confirma con S2/S3 del spike.
- Sin paginación declarada en el spec. El spike compara anual vs suma mensual del año más cargado para detectar tope silencioso.

Preguntas que contesta el script (`probe` en 5-10 min, `watch` en días):

| # | Pregunta | Decide |
|---|---|---|
| S1 | ¿Cuánto vive el refresh token? ¿Rota al usarlo? (`watch`: renueva cada hora hasta que falle) | Si muere en <24h → **Fase 2 inviable sin contraseña → queda solo Fase 1** |
| S2 | ¿Qué `tipo`/`estado` aparecen en `operaciones`? ¿Dividendos, depósitos, retiros? | Qué lee el sync y qué queda para la reconciliación contra la foto |
| S3 | ¿`Asesor/Movimientos` responde para una cuenta retail? | Única chance de tener flujos de caja por API |
| S4 | Estructura de `aranceles` en el detalle | Costo con comisión exacta; pedidos por sync |
| S5 | Ráfaga de 150 GET: ¿a qué velocidad aparece el primer 429? | Frecuencia de polling y lotes |
| S6 | Anual vs mensual: ¿tope silencioso? ¿`fechaDesde` 2010 funciona? | Carga histórica |
| S7 | ¿`numero` de la API = "Nro. de Boleto" del .xls? (tester manda el .xls) | Dedup cross-fuente (R5) |
| S8 | Sandbox `api-sandbox.invertironline.com`: cuenta separada, se evalúa después | Tests de integración |

Salida: el tester manda el `.zip` anonimizado + `iol_spike_watch.log` + su .xls → `AUDIT_iol_api_<fecha>.md`.
En paralelo: mail a IOL preguntando por límites, movimientos de caja por API para retail y programa de terceros.

**Consecuencia ya visible para el diseño:** si S2/S3 confirman que no hay flujos de caja, el modelo es
**API para órdenes + foto (portafolio + estadocuenta) para reconciliar cantidades y cash + .xls opcional
para el detalle de dividendos/depósitos**. La reconciliación deja de ser "red de seguridad" y pasa a ser
la pieza que hace cerrar el cash. Es exactamente el mecanismo de Wallbit (`_wallbit_reconcile_positions`).

### Fase 1: "Conectá tu IOL" en sesión (1-2 semanas). Shippea valor sola.

**✅ CONSTRUIDA 2026-09-02 (nocturno) en `feat/iol-lab`, SIN deployar.** Diseño distinto al planeado, más barato y más seguro:
la API se traduce al MISMO CSV que exporta IOL ("Movimientos históricos") y entra por `parsers/iol.py` +
`run_preview(parser_format='iol')` + el `ImportWizard` con `initialPreview`. Cero mapeo nuevo IOL→Rendi:
sufijo D/C, FCI, moneda, dedup por fingerprint y confirm son los de siempre.
- `iol_api.py`: `to_movimientos_csv()`, `fetch_operaciones()` (ventanas anuales), `fetch_historial()` (+1 pedido por
  operación para moneda/aranceles, capeado 800, `_TokenBox` renueva el bearer en memoria si vence a mitad del fetch).
- `main.py`: tabla `iol_lab_imports`; `POST /api/iol/lab/import-start` (login → thread) + `GET /api/iol/lab/import-status`
  (devuelve el preview con `session_id`); el confirm es el normal `/api/imports/confirm`.
- `IolLab.jsx`: botón "Traer mi historial para importar (beta)" + sección 4 + wizard en paso preview.
- Tests (`test_iol_lab.py`, 13): adaptador parsea con `IolParser` real, e2e import-start → preview → confirm → GGAL=130
  (120 pesos + 10 pata dólar), segunda vuelta = 5 duplicadas omitidas, renovación en 401.
- ⚠️ 5 supuestos a validar con el historial real del tester (comentario `A1..A5` en `iol_api.py`): casing de `tipo`,
  `montoOperado` bruto vs neto (heurística 1 %), moneda por detalle, cauciones/no-terminadas salteadas, conducto MEP
  sin residual (las dos patas entran como trades y las netea el rebuild cross-currency).
- Pendiente de esta fase: foto (`portafolio` + `estadocuenta`) para reconciliar, card en el wizard de Importar
  (hoy vive en `/lab/iol`), copy de producto. Se hace después de ver datos reales.

Plan original de la fase (referencia):

Sin custodia de nada. Reemplaza el bajar-el-.xls por ingresar user/pass una vez por import.

- `backend/iol_api.py`: cliente httpx. **Solo métodos GET. No existe `comprar`, `vender`, `suscribir`, `rescatar`, `extraer` en el archivo.** Allowlist dura de paths permitidos; cualquier otro path levanta excepción. Test que lo verifica.
- `iol_api.operacion_to_normalized_tx` reusando las funciones extraídas de `parsers/iol.py`. Mismos tests de conducto MEP y FCI fantasma corriendo sobre filas JSON.
- Endpoint `POST /api/iol/import-session`: recibe user+pass, obtiene token, baja historial completo por ventanas de fecha, foto de portafolio y estado de cuenta, **descarta credenciales y tokens al terminar la request**. Devuelve un preview con el mismo contrato que el import CSV (el wizard existente confirma).
- Reconciliación contra la foto al confirmar (mismo mecanismo que Wallbit).
- Frontend: card "IOL" en Integración con broker. Copy honesto: "Rendi no guarda tu contraseña. Cada vez que quieras actualizar, la volvés a ingresar."
- Rate limit en el endpoint. Nunca loguear user/pass/token.
- Tests: `tests/test_iol_api.py` con respuestas grabadas del spike (fixtures anonimizados).

Criterio de salida: un usuario real de IOL importa por API y el resultado es equivalente al import del .xls del mismo período (misma cantidad de posiciones, mismo cash, diff de P&L < redondeo).

### Fase 2: Auto-sync opt-in con refresh token (1-2 semanas). Solo si S1 lo permite.

- Al conectar, checkbox apagado por default: "Mantener actualizado automáticamente". Texto claro de qué se guarda y del riesgo. Botón "Desconectar" que borra todo al instante y sugiere cambiar la clave en IOL.
- Se guarda **solo `refresh_token_enc`** (Fernet, clave derivada de `SECRET_KEY` como Wallbit). Contraseña jamás. Bearer nunca persiste.
- `POST /api/iol/sync` (manual) + `GET/POST /api/iol/run-cron` (cron-job.org, cada 30-60 min en horario BYMA, 1×/día fuera). Cron itera cuentas con `broker='iol' AND refresh_token_enc IS NOT NULL`, renueva token, sync incremental desde `last_sync_at` menos 3 días de solapamiento (las operaciones pendientes cambian de estado), reconcilia contra la foto.
- Idempotencia por número de operación (S7). Operación que cambia de estado = update, no fila nueva. Cancelada = se guarda cancelada, no cuenta.
- Si el refresh falla (user cambió la clave): `last_sync_status='reauth'`, se borra el token, aviso en la UI. Nunca se reintenta con contraseña porque no la hay.
- Lock por uid en proceso (single-process en Railway, igual que Wallbit). Cada cuenta se procesa independiente: un error no frena a las demás.
- Auditoría: cada sync deja fila en una tabla `broker_sync_runs(user_id, broker, started, finished, status, fetched, new, seeded, reduced, error)`. Sin tokens.

### Fase 3: Reconciliación visible y panel (1 semana)

- Estado por cuenta: "conciliada" / "con diferencias" / "error de conexión" / "reautenticar". Se muestra en la card y en Cartera. La promesa de marketing es "sincronizo y te aviso si algo no cierra", no "réplica exacta".
- Reconciliación completa semanal: vuelve a traer el historial entero y compara contra lo guardado. Es lo único que detecta correcciones de IOL sobre operaciones viejas. Nunca borra: marca "no confirmada por la fuente".
- Panel admin (patrón `ReengagementPanel`): cuentas conectadas, últimas corridas, cuántas conciliadas, cuántas con diferencias, cuántas fallando y por qué.
- Enganchar el Import Guardian: un tipo de operación desconocido en el JSON crea incidente igual que un `UNKNOWN_OP_TYPE`.

### Fase 4 (después, según crecimiento): escala

Caché de cotizaciones (el precio ya lo trae Rendi de sus fuentes, no pedirlo a IOL por usuario), priorización por actividad reciente, evaluar WebSocket solo si el polling duele. No antes.

---

## 3. Riesgos y qué los desarma

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Refresh token corto → Fase 2 imposible sin contraseña | S1 lo mide en la Fase 0. Si es corto, Fase 1 sola ya elimina el archivo y da historia completa. **No pasar a guardar contraseña.** |
| R2 | Dividendos / depósitos / transferencias de títulos no vienen por API (muy probable: no hay endpoint de movimientos retail en el swagger) | La reconciliación contra la foto cierra cantidades y cash aunque falte el evento. La cuenta queda "con diferencias" con explicación, no con un número falso. El user puede subir el .xls para completar. |
| R3 | Token tradea por bug propio | Cliente sin métodos de escritura + allowlist de paths + test que falla si aparece un path fuera de la lista. |
| R4 | Fricción de onboarding: IOL exige activar la API | Verificar en Fase 0. Si sigue, instrucciones paso a paso en el wizard y medir cuántos abandonan ahí. |
| R5 | Doble conteo si el user usa API y CSV en el mismo broker | Dedup por número de boleto/operación de IOL, común a ambas fuentes (S7). Si no coincide, bloquear mezclar fuentes en el mismo broker (como hace Wallbit con la colisión de nombre). |
| R6 | Rate limits no documentados aparecen al escalar | S5 en Fase 0; polling con margen; backoff exponencial; cron escalonado. |
| R7 | Cron in-process se saltea (cold start Railway) | Cron externo desde el día uno, ya probado con snapshots. |
| R8 | Dependencia de IOL sin SLA ni canal de soporte | Mail a IOL en Fase 0; monitoreo de fallas en el panel de Fase 3; el import CSV sigue existiendo como plan B. |

---

## 4. Orden de ejecución y checkpoints

1. **Hoy:** mandarle al tester `iol_spike.py` + `IOL_SPIKE_README.md`; que pida la activación de APIs en IOL. Mandar el mail a IOL.
2. **Fase 0** → `AUDIT_iol_api_*.md`. **Checkpoint: decidir Fase 2 sí/no según S1.**
3. **Fase 1** en rama nueva desde `origin/main`. Deploy opt-in (nadie lo ve hasta conectar).
4. **Checkpoint:** un usuario real confirma que el import por API coincide con su .xls.
5. **Fase 2** solo si S1 dio verde. Deploy con cron apagado; activar el cron en cron-job.org después de 2-3 syncs manuales OK en prod.
6. **Fase 3.**

Estimación total con Nico + Claude: 4-6 semanas hasta Fase 3, contra las 10-13 del informe, porque el 60% de la infraestructura (credenciales, pipeline, reconciliación, cron, wizard) ya está construida y probada con Wallbit.
