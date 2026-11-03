# Auditoría final antes del pasaje a Postgres (Supabase)

> 03/11/2026 · rama auditada `claude/migracion-pg-oct`, punta `453af0f3`, contra `origin/main`
> (`dd99cb0d`). Sesión de auditoría nueva: no escribió nada de lo que audita. **No se tocó
> código de la app, ni Railway, ni Supabase. Sin push.** Todas las mediciones son contra el
> Postgres local de pruebas o contra la copia de producción del 16/08 abierta en sólo lectura.

## Veredicto

**Se puede pasar después de tres cosas, y ninguna es un error de plata en el código.**
Las tres son del procedimiento del día o de una medición de un minuto en Supabase:

1. **Medir en Supabase si su intermediario de conexiones suelta los candados de una conexión
   que se cortó** (hallazgo P1, abajo). Si no los suelta, un arranque cortado a la mitad deja
   trabados todos los arranques siguientes: la app no vuelve a levantar hasta que alguien
   intervenga. Es una prueba de un minuto que sólo puede hacer la sesión central (a mí me está
   prohibido conectarme a Supabase). Si da mal, el arreglo es de una línea y va antes.
2. **El paso 3 del día («hacé un respaldo y bajalo fuera de Railway») no se puede hacer tal
   como está escrito** (hallazgo P2): con la app cerrada, el único botón que hace el respaldo
   está detrás de la puerta cerrada, y el documento no dice cómo bajarlo.
3. **El paso 8 («comparar las pantallas de 20 cuentas») no se puede repetir el día real como se
   hizo en el ensayo** (hallazgo P3): el ensayo comparó dos copias de la app sin internet; el día
   real una de las dos tiene precios en vivo, y la llave para entrar con la app cerrada no puede
   pasar por el chat.

Lo que **sí** quedó probado y está bien: el arreglo del «bug del mes» (5.B) está en el código;
una transacción rota ya no puede contestar «guardado» sin guardar (la guarda del `commit`);
todas las puertas que escriben plata piden el turno de la cuenta (lo vigila un censo);
el modo mantenimiento arranca cerrado solo; el respaldo con `pg_dump` se recupera entero; y la
copia desde SQLite no puede tocar la base vieja (la abre en sólo lectura). La vuelta atrás antes
de abrir funciona de verdad.

### Qué está en riesgo y qué no

- **Hoy los usuarios no corren ningún riesgo:** producción sigue en SQLite y nada de esto está
  publicado.
- **El día del pasaje, la plata de los usuarios no corre riesgo por lo que encontré:** ningún
  hallazgo pierde ni cambia un número guardado. Lo peor medido es una espera de 30 segundos
  (hallazgo D1) y lo peor sin medir es que la app no levante después de un corte (P1), que es
  visible y no toca datos.
- **Después de abrir (paso 9) no hay vuelta atrás sin perder lo que la gente cargue.** Eso ya lo
  dice el paso a paso y es una decisión, no un error; está repetido acá porque es lo único
  irreversible de todo el día.

---

## Tabla de hallazgos

Gravedad: **bloquea** = no se pasa sin resolverlo · **antes** = arreglar antes del día, no
cambia el veredicto si se hace · **después** = puede esperar al pasaje.

| # | qué pasa, dicho por su efecto | gravedad | prueba | arreglo propuesto |
|---|---|---|---|---|
| P1 | Si un arranque de la app se corta a mitad (un reinicio encima de otro, falta de memoria), puede dejar puesto el candado que ordena los arranques; el siguiente lo espera **para siempre** y Railway marca la publicación como fallida a los 300 s. Pasa sólo si el intermediario de Supabase (Supavisor) reusa la conexión cortada sin limpiarla. | **bloquea hasta medirlo** | La parte del código está verificada: `main.py:1478-1480` pide `pg_advisory_lock` sin tope de espera, y la conexión del candado no fija `lock_timeout` (`pgsesion.conectar`, `pgsesion.py:65-80`). Que Supavisor reusa las conexiones del servidor después de que el cliente se va está medido (memoria `reference_supavisor_limites`, punto 4). **Lo que NO está medido** es si al reusarla suelta los candados: no pude probarlo (me está prohibido conectarme a Supabase). | Medirlo (receta abajo, un minuto). Si el candado queda puesto: en `_de_a_un_arranque_por_vez`, `SET lock_timeout = '120s'` en la conexión del candado antes del `pg_advisory_lock`, así un candado huérfano da un error claro en el registro en vez de un arranque colgado. |
| P2 | **El paso 3 del día no se puede ejecutar como está escrito.** Con el mantenimiento prendido, el único disparador del respaldo (`POST /api/admin/backup-trigger`) devuelve 503 desde el navegador, porque sólo pasa quien manda la cabecera secreta. Y el paso a paso no dice cómo se baja el archivo fuera del volumen de Railway. | **bloquea** (procedimiento) | `mantenimiento.py:115-122` (`deja_pasar`: sólo `/api/health` o la cabecera); `main.py:27350` (el disparador escribe en el volumen y, si está configurado, sube a R2). `PASAJE_PASO_A_PASO.md` §2 paso 3 no nombra ni el disparador ni la bajada. Además, el aviso ⚠ del volumen de Railway **sigue sin leerse** (`HANDOFF` §12, punto 5): si el disco está lleno, el respaldo falla en el peor momento. | Escribir el paso 3 a nivel de click: hacer el respaldo **antes** de prender el mantenimiento no sirve (queda viejo), así que: (a) la sesión central lo dispara con la cabecera desde una terminal, con la llave leída de un archivo de Nico, nunca del chat; (b) Nico lo baja desde Cloudflare R2 (memoria `project_backup_externo_r2`: el respaldo ya sube ahí) y anota tamaño y `md5`. Y leer el aviso del volumen antes de fijar la fecha. |
| P3 | **El paso 8 (comparar pantallas) no se puede repetir como en el ensayo.** El ensayo comparó dos copias de la app sin internet. El día real, la de Postgres es producción con precios en vivo: la Cartera va a dar distinto aunque la copia esté perfecta, y alguien puede leer eso como una falla (o peor, acostumbrarse a ignorar diferencias). Levantar una segunda copia local contra Supabase para comparar tampoco sirve: correría el arranque y los programadores (fotos, mails) contra la base nueva. | **bloquea** (procedimiento) | `PASAJE_PASO_A_PASO.md` §0 («sin salida a internet… la comparación mide la base») y §2 paso 8. `HANDOFF` §5.F: «`import main` corre `init_db()` + reparaciones… contra la base». Los programadores internos arrancan con la app (`main.py:46861-46918`). | Decidir antes qué se compara el día: (a) la verificación de 4 niveles del copiador (base contra base, sin precios: ya da el «cero hallazgos» que importa); (b) en pantallas, sólo lo que no depende del precio (movimientos, mensual, fotos guardadas); (c) quién tiene la llave del modo mantenimiento sin pasarla por el chat (Nico la carga en un archivo, como hizo con `~/.rendi-supabase-url`). |
| A1 | **No hay forma directa de preguntarle a la app «¿estás en Postgres?».** El paso 8 dice «el motor es Postgres, primero de todo», pero `/api/health` no lo dice. La revisión del plan de agosto (`MIGRACION_POSTGRES.md:1468`, «falta un chequeo 0») lo pidió y no se hizo. | antes | `main.py:49504-49535`: devuelve `ok`, `timestamp`, `service`, `commit`; nada del motor. Hoy se puede deducir del registro (`esquema de Postgres: se aplican 797 sentencias`, `main.py:1431`) o de que todo dé 503 (sólo pasa con `DATABASE_URL` puesta y sin `RENDI_PASAJE_COMPLETO`). Funciona, pero es una deducción, y la regla es preferir la prueba directa. | Una línea, en `health_check`: `"motor": "postgres" if USANDO_PG else "sqlite",` (diff abajo). No toca la base; decir el motor no expone nada. |
| A2 | Los trabajos internos de la app (fotos de las 23:59, bajas de plan y mails de las 00:30, avisos del mediodía) **no los frena el modo mantenimiento**: sólo cierra la puerta web. Si la ventana del día cae en esos horarios, salen mails desde una base que todavía se está verificando, y si después se vuelve atrás, salen otra vez desde la SQLite. | antes (elegir la hora) | `mantenimiento.py:60-65` sólo nombra los crons externos y los escritores del arranque; los horarios en `main.py:46871-46923`: 02:59, 03:30, 03:45, 12:10, 15:00 UTC y renovación de tokens de IOL a los :07 de cada hora. Ninguno consulta el mantenimiento (`grep -n mantenimiento main.py`: sólo `:524-537`). | Elegir la ventana **fuera** de 02:45-04:00 y 14:55-15:10 UTC (en Argentina: fuera de 23:45-01:00 y 11:55-12:10). Un domingo 8-10 h de Argentina cumple. |
| D1 | **Diez escrituras a la vez (diez depósitos, altas o borrados de distintas personas) esperan 30 segundos cada una.** Casi todos los caminos que escriben piden una segunda conexión con la primera todavía en la mano (para borrar la memoria de la IA); con el pozo de 10 lleno, ninguna vuelve y todas esperan el máximo. Al final se guardan bien (200), pero algunas cuentas quedan con el análisis de la IA viejo. | después | **Medido** en el Postgres local con una prueba temporal (no commiteada) que pasa por la puerta real `/api/cash/flow`: 4 a la vez → 0,0 s; **10 a la vez → 5,1 s = el tope de espera configurado en la prueba (en producción es 30 s)**, 10×200, 2-3 cuentas con la memoria de la IA sin borrar. Una sonda sobre 4 archivos de pruebas (155 pruebas) encontró **18 lugares** que piden la segunda conexión; el 95 % por `_ai_cache_invalidate` (`main.py:37090`). La pantalla no reintenta escrituras (`frontend/src/utils/api.js:149-151`), así que no se duplica nada. | Que `_ai_cache_invalidate` use la conexión que ya tiene el que llama (o corra después de cerrarla). Con 1.100 usuarios, diez escrituras en el mismo segundo es raro; por eso es «después». **Corrige una recomendación:** la alternativa `RENDI_PG_POOL_MAX=7` de `TOPE_CONEXIONES_SUPABASE.md` §5 hace este caso más probable; con Pool Size 24 ya puesto, no usarla. |
| D2 | El respaldo nocturno usa **2** conexiones, no 1 como dice `TOPE_CONEXIONES_SUPABASE.md` §1. | después (sólo el documento) | `scripts/backup_db.py:206-226`: una conexión guarda la foto y `pg_dump` abre la suya. Peor caso de una copia de la app: 10 + 1 + 2 + 2 al arrancar = 15 ≤ 24. No cambia nada. | Corregir la tabla del documento. |
| D3 | **No hay un instructivo para recuperar la base desde un respaldo.** La prueba automática demuestra que el archivo se puede restaurar; no hay un paso a paso para el día que haga falta. | después (antes del primer susto) | `audit/BACKUPS_CON_POSTGRES.md` cubre hacer y comprobar el respaldo, no volver a él. | Escribirlo: de dónde se baja el archivo (R2), con qué comando se restaura y qué pasa con la app mientras tanto. |

### Los diffs de una línea

A1 — el chequeo del motor (`backend/main.py`, `health_check`):

```diff
         "service": "rendi-api",
+        "motor": "postgres" if USANDO_PG else "sqlite",
```

P1 — sólo si la medición da mal (`backend/main.py`, `_de_a_un_arranque_por_vez`):

```diff
     with pgsesion.conectar(DATABASE_URL, autocommit=True) as candado:
         clave = (pgsesion.TURNO_ARRANQUE,)
+        candado.execute("SET lock_timeout = '120s'")
         candado.execute("SELECT pg_advisory_lock(%s, hashtext(current_schema()))", clave)
```

(120 s y no 3 s: un arranque normal que espera a otro tarda segundos; el tope sólo tiene que
cortar el caso del candado huérfano antes de los 300 s del chequeo de salud.)

### Receta de la medición P1 (para la sesión central, contra Supabase, un minuto)

1. Abrir una conexión A por el pooler con la `DATABASE_URL` de producción y correr
   `SELECT pg_advisory_lock(424242)`.
2. Matar el proceso de A sin soltar nada (`kill -9`), no cerrarla con cuidado.
3. Abrir una conexión B nueva y correr `SELECT pg_try_advisory_lock(424242)`.

| si B dice | significa | qué hacer |
|---|---|---|
| `true` | Supavisor limpia la conexión: P1 no existe | soltar el candado de B y nada más |
| `false` | el candado quedó huérfano en una conexión reusada | aplicar el diff P1 antes del pasaje; esperar a que Supavisor corte la conexión vieja (o reiniciar el pooler) para limpiar la prueba |

---

## Lo que revisé y está bien (con su prueba)

| qué | cómo lo comprobé |
|---|---|
| El bug del mes (5.B): dos operaciones a la vez, primeras del mes, ya no pierden el pedido | `_update_monthly_pnl_realized` tiene `ON CONFLICT (user_id, year, month, broker)` (`main.py:14498-14505`) |
| Una transacción rota no puede confirmarse en silencio | `pgshim.Connection.commit` y `__exit__` pasan por `_no_confirmar_lo_descartado` (`pgshim.py:1315-1344`) |
| El turno de la cuenta en todas las puertas que escriben plata (5.C) | `_tomar_turno_de_la_puerta` (`main.py:1558`) y su censo `tests/test_turno_en_todas_las_puertas.py` |
| El mantenimiento arranca cerrado solo con `DATABASE_URL` | `mantenimiento.en_mantenimiento` (`mantenimiento.py:85-100`) + `tests/test_mantenimiento.py` |
| El arranque: esquema con huella, reintentos con tope, salud en 503 hasta terminar | `tests/test_arranque_sin_trabar.py`, `test_turno_reconstruccion_y_arranque.py` |
| El respaldo con `pg_dump` se restaura entero, tabla por tabla | `tests/test_backup_postgres.py` |
| El pozo nunca abre más de su tope y devuelve las conexiones limpias | `tests/test_pgshim_pozo.py` |
| **Las cinco de arriba, corridas hoy en esta punta** | Postgres local: **52 pasaron / 0 fallaron en 20,6 s** |
| La copia y su verificación de 4 niveles | modo SQLite con `PG_DSN_VERIF` en una base aparte creada y borrada para esto: **71 pasaron / 0 en 2,6 s** (`test_copiar_a_postgres.py`, `test_verificar_copia.py`) |
| El empate del mismo día (§4.2 del paso a paso) | `orden_estable.py` en uso (`main.py:100`); `test_orden_mismodia.py` + `test_orden_con_desempate.py`: 2 pasaron, 2 «falla esperada» documentadas, en 4 s |
| La copia no puede tocar la SQLite de origen | `scripts/copiar_a_postgres.py:139`: la abre con `mode=ro` |
| **Ordenar con columnas vacías** (SQLite las pone primero, Postgres al final): ¿cambia algún resultado? | Revisé las 57 columnas que aparecen en un `ORDER BY` del backend contra la copia de producción del 16/08 (sólo lectura). Las que tienen vacíos y se usan para ordenar (`positions.entry_date`, `import_batches.confirmed_at`, `users.trial_ends_at`, …): **0 casos donde el orden cambie** (los grupos de lotes con un lote sin fecha y otro con fecha: 0; lotes confirmados sin fecha: 0; las de prueba gratis filtran los vacíos antes). Riesgo latente, no actual. |
| ¿Hace falta que el pozo reintente cuando Supabase rechaza por tope, antes del pasaje? | **No.** El volumen de Railway sigue montado después del pasaje (los respaldos locales y la SQLite de la vuelta atrás viven ahí), y con volumen Railway no superpone la copia vieja con la nueva (`turno-pendientes.md` en la carpeta compartida, docs de Railway). Peor caso de una sola copia: 15 de 24. Es una mejora para el día que se saque el volumen. |
| La vuelta atrás antes del paso 9 | Es real: la SQLite del volumen no la toca nadie (la copia se hace sobre el archivo bajado, en sólo lectura), y lo que los trabajos internos escriban en Postgres con la app cerrada son precios y fotos que se rehacen. Ver A2 para elegir la hora. |
| Lo que se escribe durante la copia | Nada de usuarios: todo pedido web da 503 desde el paso 2. Los cobros que lleguen en la ventana reciben 503; Rebill re-entrega eventos (lo documenta `main.py:1501`), así que no se pierden. Mercado Pago no lo verifiqué. |

---

## Lo que NO revisé

- **Nada contra Supabase** (prohibido): ni P1, ni latencias, ni la restauración real allá.
- **Los 14 del barrido de los 24 y los 21 de las 7 lentes** (`HANDOFF` §5.C-D): no los
  re-verifiqué uno por uno; confié en el censo de puertas y en las corridas de la central.
- **La suite completa:** corrí sólo 13 archivos (de 437) por las reglas de la tarea.
- **Los ~22 lugares «intento escribir → si falla, sigo → confirmo»** (`HANDOFF` §5.B,
  propagación): verifiqué que la guarda del `commit` los vuelve un error visible en vez de un
  «guardado» falso; no revisé uno por uno si alguno debería seguir de largo.
- **Mercado Pago:** si reintenta los avisos de pago que reciben 503 durante la ventana.
- **La renovación de tokens de IOL** (a los :07 de cada hora): si corre entre el respaldo y la
  apertura, la cuenta del laboratorio (0-3 personas) puede quedar con un token vencido. No
  medí si IOL invalida el token anterior.
- **El frontend** más allá de cómo reintenta (`api.js`).
- **El `Dockerfile`** sólo leído: ya lo probó la central en Railway (`HANDOFF` §12).

## Un error mío durante la auditoría

Un comando con un patrón de archivo que no encontró nada lanzó la **suite entera** contra el
Postgres local durante ~2 minutos; lo corté y borré su esquema (`t47477_suite`). No había otra
sesión corriendo pruebas en ese momento (lo miré antes: 0 conexiones ajenas). Para que no se
repita: nombrar los archivos de prueba explícitos, nunca con `$(ls patrón)`.
