# Paso 0 — La `SECRET_KEY` hardcodeada en `start-rendi.sh:43`

> Auditoría de seguridad · Tanda A · commit auditado `b74f450f` · verificado también contra
> `origin/main` (`897b0d63`, 11 commits adelante) y contra el working tree local.
> **Este documento no contiene ningún valor de secreto.** Los secretos se identifican por
> su huella SHA-256 truncada a 16 hex, que sirve para comparar sin revelar.

## Método

- **MEDIDO** (ejecuté y pegué la traza):
  - Recreación de la copia limpia: `git archive b74f450f` → `/tmp/rendi-main`.
    Verificado: **1.126 archivos**, `backend/main.py` con **38.029 líneas** (coincide con el handoff).
  - Huellas SHA-256 de los valores, calculadas en shell, nunca impresas en claro.
  - `git log --all -S 'export SECRET_KEY' -- start-rendi.sh` para fechar la introducción.
  - Barrido de **los 24.579 objetos** del repo (`git cat-file --batch-all-objects --batch`)
    buscando patrones de credencial. Script: `audit/_scripts/scan_secretos_historial.sh`,
    salida cruda en `audit/_scripts/_hits_historial.txt`.
  - Lectura del `backend/.env` local (no versionado) sólo para calcular huellas.
- **DEDUCIDO** (razonamiento sobre código leído): la cadena de precedencia de la variable, y
  qué puede hacer un atacante que tenga la clave.
- **NO EJECUTADO**: no firmé ni verifiqué ningún JWT, no levanté el backend, no hice ninguna
  petición a producción, no consulté la configuración de Railway ni la visibilidad del repo
  en GitHub.

---

## 1. Qué protege exactamente ese valor

`SECRET_KEY` no es "una clave más". Es la raíz de confianza de dos cosas distintas:

### a) Firma de los tokens de sesión (JWT HS256)

`backend/main.py:2680-2689` y `2692-2724`:

```
ALGORITHM = "HS256"                                   # main.py:115
TOKEN_DAYS = 7                                        # main.py:116
payload = {"sub": str(user_id), "iat": ..., "exp": ...}
return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)   # main.py:2689
payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # main.py:2704
```

HS256 es **simétrico**: la clave que verifica es la misma que firma. Quien la tiene no
"puede leer tokens": **puede fabricarlos**.

El token viaja en la cookie HttpOnly `rendi_token` (`main.py:147-158`, `secure` sólo si
`RENDI_ENV=prod`, `samesite=lax`) y, como fallback, en el header `Authorization: Bearer`
(`main.py:2696-2699`). El fallback importa: un atacante no necesita plantar una cookie en un
navegador, le alcanza con mandar el header desde `curl`.

### b) Cifrado de las credenciales de broker de los usuarios

`backend/main.py:31013-31024`:

```
digest = hashlib.sha256((SECRET_KEY or "dev-insecure").encode("utf-8")).digest()
return Fernet(base64.urlsafe_b64encode(digest))
```

La clave Fernet **se deriva determinísticamente de `SECRET_KEY` con un solo SHA-256, sin salt
y sin KDF**. Esa Fernet cifra la columna `user_broker_credentials.api_key_enc`
(`main.py:730-740`): la API key de **Wallbit** y el **refresh token de IOL**
(`main.py:31328-31340`, `PLAN_iol_sync.md:109`).

Consecuencia: `SECRET_KEY` y el contenido de esa tabla son un solo secreto. No hay separación
de dominios criptográficos — la misma clave que firma sesiones descifra credenciales de broker.

### Qué NO protege

Los tokens de reset de contraseña **no** derivan de `SECRET_KEY`: son aleatorios y viven en
la tabla `password_reset_tokens` (`main.py:2943`, `2108-2117`). Bien.

---

## 2. Qué puede hacer alguien que lo tenga

**Suplantar a cualquier usuario, sin tocar su contraseña ni su mail.**

El payload es mínimo (`sub` = id numérico del usuario). Fabricar un token válido para el
usuario 1, el 2, el 3… es un `for` de tres líneas. `get_current_user` sólo comprueba firma,
expiración y que el `id` exista en `users` (`main.py:2707-2717`).

De ahí se sigue todo lo demás:

| capacidad | cómo | evidencia |
|---|---|---|
| Leer la cartera, operaciones, snapshots y patrimonio de cualquier usuario | token forjado con `sub` = ese uid; todos los endpoints `WHERE user_id=?` sirven esa cuenta | `main.py:2692-2717` |
| **Ser admin** | forjar `sub` = uid del admin. `get_admin_user` sólo lee `is_admin` de la DB, no re-autentica | `main.py:2720-2726` |
| Superficie admin completa | 47 endpoints bajo `/api/admin` | `grep -c '@app\.\(get\|post\|...\)("/api/admin'` → **47** |
| Escribir/borrar datos de cualquier usuario | el token forjado es indistinguible de uno legítimo | — |
| Descifrar credenciales de broker | si además consigue la DB (backup S3, volumen de Railway), la Fernet se deriva de la misma clave | `main.py:31013-31024` |
| Actuar como asesor sobre clientes ajenos | forjando `sub` de un asesor y mandando `X-Rendi-Client-Id` | `main.py:2729-2760` |

### El cambio de contraseña NO lo frena

`main.py:2713-2717`:

```
pca = payload.get("pca")
if pca and row["password_changed_at"] and pca != row["password_changed_at"]:
    raise HTTPException(401, ...)
```

La invalidación por cambio de contraseña **sólo se aplica si el token trae el claim `pca`**.
Un token forjado simplemente lo omite y pasa. Es decir: la única defensa de revocación que
tiene el sistema es opcional desde el lado del atacante.

**No hay `jti`, ni denylist, ni tabla de sesiones.** No existe forma de revocar un token
individual. La única revocación global es rotar `SECRET_KEY` — que desloguea a todos.

**Severidad: CRÍTICA**, condicionada a un solo hecho que no pude verificar (ver §6).

---

## 3. Historial de git: sí aparece, y desde cuándo

| dato | valor |
|---|---|
| Commit que la introdujo | `28d080c6` — *"Checkpoint: sub-broker USD, conversiones FX, copy polish, FX phantom fix"* |
| Fecha | **2026-05-07** |
| Commits que la modificaron después | **ninguno** (`git log --all -S 'export SECRET_KEY' -- start-rendi.sh` devuelve 1 sola línea) |
| Tiempo expuesta | **~4 meses** (2026-05-07 → hoy 2026-09-08) |
| Sigue viva en `origin/main` (`897b0d63`) | **sí** |

Huella del valor (SHA-256, 16 hex) en las cuatro refs — idéntica, o sea nunca rotó:

```
28d080c6:   bf9d0427ab8af517
b74f450f:   bf9d0427ab8af517
origin/main:bf9d0427ab8af517
HEAD:       bf9d0427ab8af517
```

### Está en DOS archivos versionados, no en uno

Este es el punto que se pierde si se arregla sólo lo que se reportó:

| archivo | línea | ¿versionado? |
|---|---|---|
| `start-rendi.sh` | 43 | sí |
| `.claude/settings.local.json` | 74 | **sí** — `.claude/` no está en `.gitignore` |

Ambos con la **misma huella `bf9d0427ab8af517`**, ambos introducidos en el mismo commit
`28d080c6`, ambos presentes hoy en `origin/main`. En `settings.local.json` el valor está
embebido dentro de una regla de permisos (`"Bash(SECRET_KEY=… python3 -m uvicorn …)"`), que
es exactamente el lugar donde nadie va a buscarlo.

Un `git rm` de la línea 43 y nada más deja el secreto publicado.

---

## 4. Qué gana cuando la env var y el archivo existen los dos

La cadena real, en orden de ejecución:

1. `start-rendi.sh:7-8` — `source ~/.zshrc` y `~/.bashrc`: entra lo que el usuario tenga exportado.
2. `start-rendi.sh:43` — `export SECRET_KEY=<hardcodeado>`: **incondicional**. No es un default
   (`${SECRET_KEY:-…}`), es una asignación. **Pisa** lo que hubiera venido del paso 1.
3. `backend/main.py:26-30` — `load_dotenv(_env_path, override=True)` si existe `backend/.env`.
   El `override=True` es deliberado y está comentado (`main.py:20-25`): el `.env` **gana** sobre
   todo lo anterior.
4. `backend/main.py:100` — `os.environ.get("SECRET_KEY", "")`.

**Precedencia efectiva: `backend/.env` > `export` de `start-rendi.sh` > shell del usuario.**

Respuesta directa: cuando existen los dos, **gana el archivo `.env`**, y el valor hardcodeado
del script queda sin efecto. En una máquina sin `backend/.env`, gana el hardcodeado.

En producción no interviene ninguno de los dos: el entrypoint de Railway es
`nixpacks.toml [start]` → `uvicorn main:app`, y no hay `.env` en el repo. Manda la variable
del dashboard de Railway.

---

## 5. Otros secretos en la misma situación

### En el árbol auditado: sólo este

Barrido de asignaciones a constantes largas y de strings hex/base64 de ≥40 caracteres sobre
todo `b74f450f` (excluyendo `node_modules`): 22 ubicaciones, **21 falsos positivos** (URLs,
comentarios largos, nombres de import lazy). El único real es la `SECRET_KEY`.

`_ADMIN_EMAIL_HASH` (`main.py:126`) es un hash, no un secreto — pero **el comentario de la
línea 123-124 escribe el email del admin en claro**, con lo cual el hash no oculta nada.
Es un hallazgo menor aparte (va en el informe de auth), no una credencial que rotar.

### En todo el historial: nada más

Barrido de **los 24.579 objetos** del repo (incluye blobs no alcanzables desde ninguna rama)
contra patrones de credencial real: `sk-ant-api`, `sk_live_`, `sk_test_`, `rk_live_`,
`AKIA…`, `APP_USR-`, `xoxb-`, `ghp_`, `github_pat_`, `BEGIN … PRIVATE KEY`, `re_…`, `AIza…`.

75 coincidencias, **todas explicadas y ninguna es una credencial**:

| dónde | qué es |
|---|---|
| `backend/.env.example` | plantilla con placeholders (`sk-ant-api03-…`) |
| `backend/billing/rebill.py` | comprobación de prefijo `sk_test_`/`sk_live_` para elegir sandbox vs prod |
| `backend/billing/mercadopago.py` | comentario documentando el formato `APP_USR-…` |
| `backend/tests/test_security_fixes_2026_05_31.py` | fixtures falsos |
| `audit/*`, `frontend/node_modules/*` | menciones del propio informe y coincidencias en librerías minificadas |
| 1 blob dangling (`293860db`) | parser de Bull Market, coincidencia de substring |

Nunca se commiteó un `.env`: `git log --all --diff-filter=A -- '*.env' '.env' 'backend/.env'`
no devuelve nada, y `.gitignore:23-25` los cubre.

Verificación cruzada: `SNAPSHOT_CRON_TOKEN`, `ALERTS_CRON_TOKEN`, `IOL_LAB_CRON_TOKEN`,
`RESEND_API_KEY`, `REBILL_API_KEY`, `REBILL_WEBHOOK_SECRET/TOKEN`, `BACKUP_S3_*` y los VAPID
se leen **siempre** de `os.environ`, sin default hardcodeado. Correcto.

### Pero el `.env` local tiene un problema peor, y es viejo

`backend/.env` (no versionado, en la máquina de desarrollo):

```
SECRET_KEY        len=108  sha16=b130464029fce0b9
ANTHROPIC_API_KEY len=108  sha16=b130464029fce0b9   ← misma huella
```

**`SECRET_KEY` y `ANTHROPIC_API_KEY` son literalmente el mismo valor**, y ese valor tiene
formato de API key de Anthropic (`sk-ant-api…`, 108 caracteres).

Esto ya estaba reportado como el hallazgo **C1** del `AUDIT_REPORT_2026-05-25.md:23,37-47`
("hay que rotar"). Al **2026-09-08 sigue sin rotarse**: 3 meses y medio.

Por qué importa más que el hardcodeo del script: una API key de Anthropic circula por lugares
donde una clave de firma de sesión no debería estar nunca — se pega en consolas, aparece en
trazas de SDK, viaja a la consola de Anthropic, se comparte para debuggear. Y por
`load_dotenv(override=True)`, en esa máquina **la clave que firma los JWT de Rendi es la API
key de Anthropic**. Cualquier filtración de la API key es una filtración de la sesión de todos
los usuarios.

---

## 6. El único dato que no pude verificar, y que decide la severidad

**¿El valor que está en Railway como `SECRET_KEY` es alguno de estos dos?**

- Si Railway usa el valor hardcodeado (`bf9d0427ab8af517`) → **CRÍTICO**: cualquiera con acceso
  al repo forja sesiones de producción hoy.
- Si Railway usa el valor del `.env` local (`b130464029fce0b9`, = la API key de Anthropic) →
  **CRÍTICO por otro camino**: la clave de firma se filtra con la API key.
- Si Railway tiene un tercer valor, generado aparte → el hardcodeo es **ALTO pero no explotable
  contra producción**: compromete el entorno de desarrollo, y sobre todo compromete las
  credenciales de broker guardadas en dev.

No lo puedo determinar desde el código y no toqué producción. **Lo tiene que confirmar el
founder en el dashboard de Railway comparando huellas**, sin pegar valores:

```bash
printf %s "$SECRET_KEY" | shasum -a 256 | cut -c1-16
```

Segundo dato que no pude verificar sin salir a la red: **si el repo de GitHub
(`nicofranco2004-boop/trading`) es público o privado**. Si es público, la ventana de exposición
son 4 meses de indexación por scrapers de secretos, y la rotación es urgente e incondicional.

Tercer supuesto no verificado: que `RENDI_ENV=prod` esté efectivamente seteada en Railway.
De ella dependen el fail-closed de `SECRET_KEY` (`main.py:105-108`), la cookie `Secure`
(`main.py:148`) y varias validaciones más (`main.py:248, 278, 371, 2938`). Si no está seteada,
el backend **no falla al arrancar sin `SECRET_KEY`**: genera una efímera (`main.py:112`) y
sigue. Va como hallazgo aparte al informe de configuración.

---

## 7. Qué habría que hacer

### Rotar (urgente, y es trabajo de operaciones, no de código)

1. Generar una `SECRET_KEY` nueva e independiente (`python3 -c "import secrets;
   print(secrets.token_urlsafe(64))"`), setearla en Railway. Efecto conocido y aceptable:
   **desloguea a todos los usuarios** (los JWT viejos dejan de validar).
2. **Antes de rotar**, mirar el efecto colateral: las credenciales de broker cifradas
   (`user_broker_credentials.api_key_enc`) quedan **indescifrables**, porque la Fernet se
   deriva de `SECRET_KEY`. El código ya contempla el caso y lo loguea como
   `"dead: no se pudo descifrar el token (SECRET_KEY cambió)"` (`main.py:31434`), pero los
   usuarios de Wallbit e IOL Lab van a tener que volver a conectar. Hay que contarles.
   → Esto por sí solo justifica separar la clave de cifrado de la de firma (§ siguiente).
3. Rotar la `ANTHROPIC_API_KEY` en la consola de Anthropic (está compartida con la clave de
   firma desde hace 3 meses y medio) y poner un valor **distinto** en `SECRET_KEY` del `.env`.
4. Si el repo es público: rotar todo lo anterior asumiendo compromiso, no como precaución.

### Arreglar (código)

1. Sacar el valor de **los dos** archivos: `start-rendi.sh:43` y `.claude/settings.local.json:74`.
   Reemplazar el del script por un default no-secreto o por lectura de `backend/.env`.
   Agregar `.claude/settings.local.json` a `.gitignore` (el sufijo `.local` indica que nunca
   debió versionarse).
2. Reescribir el historial (`git filter-repo`) sólo si el repo es público o tuvo colaboradores
   externos. Si es privado y de un solo dueño, rotar alcanza y reescribir 24.579 objetos con
   tres sesiones trabajando en paralelo es más riesgo que beneficio.
3. **Separar dominios criptográficos**: una `CREDENTIALS_KEY` propia para la Fernet de
   `user_broker_credentials`, independiente de la de firma. Hoy no se puede rotar la firma sin
   romper las credenciales de broker, y eso es lo que hace que "rotar" duela y por lo tanto no
   se haga. La causa de fondo del hallazgo no es el hardcodeo: es que hay **una sola clave para
   dos trabajos distintos**.
4. Cerrar el bypass de `pca` (`main.py:2713`): exigir el claim en vez de tratarlo como opcional,
   o mejor, agregar `jti` + denylist para poder revocar una sesión sin deslogear a todos.
5. Que el fail-closed de `SECRET_KEY` no dependa de `RENDI_ENV`: si no hay clave y no es un
   entorno de test declarado, no bootear.

### Parche vs causa

`start-rendi.sh:42` tiene el comentario *"SECRET_KEY fija (para que los tokens sobrevivan
reinicios del backend)"*. Es un **PARCHE**: el problema real que resolvía era que sin
`SECRET_KEY` el backend genera una efímera por proceso (`main.py:112`) y cada reinicio
desloguea. La solución correcta para eso era poner la clave en `backend/.env` — que ya está
gitignoreado y que ya existe en esa máquina. Hardcodearla en un script versionado resolvió la
molestia y creó el problema. La causa real sigue viva en `main.py:100-113`: el sistema
**acepta arrancar sin clave** en cualquier entorno que no se declare `prod`.

---

## 8. ACTUALIZACIÓN 2026-09-08 — el founder confirma cuál es el valor de producción

**Fuente: el founder, de memoria** (la consola de Railway no conectaba; la pestaña
`Variables` quedó sin mirar). Textual: *"la clave que tiene railway recuerdo que es la que
generé en la plataforma de api de antropic"*.

Es decir: **en producción, `SECRET_KEY` es una API key de Anthropic.** Coincide con lo que
ya se midió en el `backend/.env` local (`SECRET_KEY` y `ANTHROPIC_API_KEY` con la misma
huella `b130464029fce0b9`, formato `sk-ant-api…`, 108 caracteres) y con el hallazgo **C1** del
`AUDIT_REPORT_2026-05-25.md`, abierto desde el 2026-05-25.

**Severidad: CRÍTICA.** La clave que firma las sesiones de todos los usuarios de producción
es una credencial de un tercero.

### Verificación adicional: ¿la app filtra esa key por sí sola?

Comprobado, y la respuesta es **no** — la exposición viene de la circulación de la key, no de
un bug de Rendi:

| vía | resultado | evidencia |
|---|---|---|
| Endpoint que vuelca env vars | existe uno, pero **sólo expone `RENDI_ENV` y `RENDI_TRUSTED_PROXY_HOPS`**, y está detrás de `get_admin_user` | `main.py:15992-16003` |
| La key en respuestas o logs | nunca se imprime; se lee y se pasa al SDK | `main.py:20363`, `ai/llm.py:114-116` |
| Mensajes de error del subsistema IA | genéricos (`"AI no configurada (falta ANTHROPIC_API_KEY)"`) | `main.py:25916, 26196, 28288` |
| `str(e)` de excepciones al usuario | 0 coincidencias del patrón directo (hay 173 `except Exception as e` sin revisar uno por uno → queda para el punto 10 de la Tanda B) | grep |

### Por qué esto es peor que un secreto hardcodeado normal

1. **Una API key circula por donde una clave de firma no debería estar nunca**: la consola de
   Anthropic (visible y copiable para cualquiera con acceso a esa cuenta), el `.env` en claro
   del portátil, el historial del shell, cualquier script o CI donde se haya pegado. Cada uno
   de esos lugares es hoy, además, la capacidad de firmar sesiones de cualquier usuario de Rendi.
2. **`SECRET_KEY` y `ANTHROPIC_API_KEY` son dos entradas distintas en Railway que casualmente
   guardan el mismo string.** Rotar la key en la consola de Anthropic **no cambia `SECRET_KEY`**.
   Resultado: una credencial retirada —que todo el mundo trata como inofensiva una vez
   revocada— sigue siendo indefinidamente la llave maestra de las cuentas de los usuarios.
   Es el peor estado posible: un secreto vivo disfrazado de secreto muerto.
3. **Los detectores de secretos filtrados no van a avisar de lo que importa.** Si esa key
   aparece en un scraper, la alerta va a decir "API key de Anthropic expuesta" y el reflejo va
   a ser "revoco y listo". Nadie va a leer eso como "acceso total a las carteras de 1.084
   usuarios", que es lo que es.

### Plan de rotación en orden, con el efecto colateral que hay que manejar antes

El orden importa: rotar `SECRET_KEY` a ciegas rompe credenciales de broker sin aviso.

1. **Antes de tocar nada**, contar a quién le va a doler:
   `SELECT broker, COUNT(*) FROM user_broker_credentials GROUP BY broker;`
   Son las conexiones de **Wallbit** e **IOL Lab**. Al cambiar `SECRET_KEY`, la Fernet que las
   descifra deja de funcionar y esas filas quedan muertas — el código lo detecta y lo loguea
   (`main.py:31434`) pero no lo puede recuperar. Esos usuarios tienen que reconectar.
2. Generar una `SECRET_KEY` **nueva e independiente** y setearla en Railway
   (`python3 -c "import secrets; print(secrets.token_urlsafe(64))"`). Efecto conocido:
   **desloguea a todos**. Es el precio, y es correcto pagarlo.
3. Recién ahí, rotar la API key en la consola de Anthropic y actualizar `ANTHROPIC_API_KEY`
   en Railway y en el `.env` local. A partir del paso 2 son dos secretos independientes y esto
   ya no afecta las sesiones.
4. Sacar las dos copias hardcodeadas del repo (`start-rendi.sh:43`,
   `.claude/settings.local.json:74`) y agregar `.claude/settings.local.json` al `.gitignore`.
5. **El fix de fondo** (§7): una `CREDENTIALS_KEY` separada para la Fernet de
   `user_broker_credentials`. Mientras rotar la firma implique romper las credenciales de
   broker, rotar va a doler, y lo que duele no se hace. Si esto se hace ANTES del paso 2, el
   paso 1 deja de ser una pérdida: se re-cifran las filas con la clave nueva y nadie reconecta
   nada.

### Lo que sigue sin verificarse

- La confirmación es **de memoria, no medida**. Falta el chequeo de 10 segundos: pestaña
  `Variables` → `SECRET_KEY` → ícono del ojo → ¿empieza con `sk-ant-`?
  Importa porque el paso 2 desloguea a todos: conviene estar seguro antes.
- Si el repo de GitHub es público o privado.
- Si `RENDI_ENV=prod` está seteada en Railway.

---

## 9. Cierre del Paso 0 — respuestas del founder y re-calificación

Respuestas del 2026-09-08:

| pregunta | respuesta | efecto |
|---|---|---|
| Repo en GitHub | **privado** | baja mucho la exposición del valor hardcodeado |
| `RENDI_ENV` en Railway | **`prod`** | fail-closed y cookie `Secure` activos ✅ |
| ¿El `.env` está en prod? | *"no sé"* | resuelto abajo por análisis estructural |
| `SECRET_KEY` de prod | la API key de Anthropic (de memoria) | **CRÍTICO**, sin cambios |

### 9.1 ¿Hay un `backend/.env` dentro del contenedor de producción? — No

**ESTRUCTURAL.** Cinco condiciones tendrían que fallar a la vez para que exista, y ninguna falla:

1. **No está en el repo.** `.gitignore:23` lo excluye y nunca se commiteó — verificado sobre
   los 24.579 objetos del historial (`git log --all --diff-filter=A -- '*.env'` vacío).
2. **El build no lo copia.** `nixpacks.toml` sólo hace venv + `pip install -r
   backend/requirements.txt`. No hay `COPY` de nada fuera del checkout de git.
3. **Nada lo escribe en runtime.** Las únicas menciones de `.env` en el backend son las dos
   lecturas (`main.py:28`, `scripts/test_emails.py:22`). Ningún `open(..., 'w')`.
4. **El filesystem del contenedor es efímero.** Un archivo creado a mano por la consola muere
   en el deploy siguiente, y hay un deploy ACTIVE de hace 1 hora (captura del dashboard).
5. **El volumen no monta ahí.** `load_dotenv` mira `/app/backend/.env`
   (`os.path.dirname(__file__)` con el `cd backend` del `[start]` de nixpacks). El volumen
   `trading-volume` monta en `/data` — así lo documenta `backend/.env.example:30`
   (*"En Railway: /data/trading.db (volume)"*). Un volumen montado en `/app/backend` taparía
   el código de la app y el deploy no arrancaría.

**Conclusión: en producción manda el dashboard de Railway.** Rotar ahí surte efecto.

Confirmación opcional de 5 segundos, si se quiere cerrar del todo: pestaña `Settings` del
servicio → sección del volumen → el *mount path* tiene que decir `/data`.

### 9.2 Re-calificación del secreto hardcodeado: de CRÍTICO a BAJO

Con el repo privado y con prod usando otro valor, el `bf9d0427ab8af517` de `start-rendi.sh:43`
y `.claude/settings.local.json:74` **no abre nada de producción**. Y en la máquina del founder
tampoco firma nada, porque `backend/.env` le gana por `override=True` (§4).

Queda como **BAJO**: sólo aplica a una máquina que clone el repo y levante el backend **sin**
`backend/.env`. Ahí, las credenciales de broker que se guarden en esa instancia quedan cifradas
bajo una clave que cualquiera con acceso al repo conoce. Hay que sacarlo igual —de los **dos**
archivos— pero no es una emergencia y **no justifica reescribir el historial**.

### 9.3 Lo único CRÍTICO que queda del Paso 0

`SECRET_KEY` de producción = una API key de Anthropic. Todo lo de §2 y §8 sigue en pie sin
cambios: quien tenga esa key forja sesiones de cualquier usuario, incluido el admin.

### 9.4 Radio de la explosión al rotar — cómo medirlo

Al cambiar `SECRET_KEY` se pierden las filas de `user_broker_credentials` (§8). Para contarlas
hace falta la base, y **no hay endpoint que lo haga**: todas las consultas a esa tabla son
`WHERE user_id=?` (`main.py:31065, 31224, 31285, 31362, 31425, 31475`). Tampoco existe un
endpoint admin de SQL libre — lo cual, dicho sea de paso, está bien.

Tres vías para el conteo, en orden de comodidad:
1. El explorador **`Files`** del panel de consola de Railway → abrir `/data/trading.db`.
2. La pestaña **`Backups`** del servicio → restaurar una copia y consultarla fuera de prod.
3. **Estimar y avisar después**: `iol_lab` está detrás de la allowlist `IOL_LAB_EMAILS`
   (`main.py:31339`), que según las notas del proyecto nunca se seteó en Railway → sólo admins,
   probablemente 0 o 1 fila. El radio real son los usuarios de **Wallbit**.

### 9.5 Estado

Tanda A **no lanzada** — el founder pidió esperar.


---

## 10. CONFIRMADO 2026-09-08 — el valor de producción

El founder verificó el valor en la pestaña `Variables` del servicio en Railway (ícono del ojo):
**`SECRET_KEY` empieza con `sk-ant-`**.

Queda confirmado por el dueño de la cuenta, sobre el dashboard real, lo que hasta ahora era un
recuerdo: **la clave que firma las sesiones de todos los usuarios de producción es una API key de
Anthropic.** Todo lo de §8 y §9.3 pasa de "confirmación de memoria" a verificado.

La severidad **no cambia** (ALTO-latente): sigue sin haber ninguna vía conocida por la que un
tercero la tenga. Lo que cambia es que ya no hay razón para dudar antes de ejecutar el runbook de
rotación de `fix-credentials-key/README.md` — y el paso que desloguea a todos los usuarios estaba
esperando exactamente esta confirmación.

También confirmado en la misma revisión: **no existe ninguna variable `MP_` en Railway**, lo que
cierra el hallazgo del webhook de Mercado Pago (ver `5a-resumen.md` §Corrección 3).

---

## 11. CERRADO 2026-09-08 — la rotación se ejecutó y está verificada

Estado final, **MEDIDO** sobre los logs de arranque de producción (deploy `140c753d`, 21:46:50):

```
config al arrancar: SECRET_KEY=[86 chars, no-anthropic] | ANTHROPIC_API_KEY=[108 chars,
parece-clave-de-anthropic] | CREDENTIALS_KEY=[86 chars, no-anthropic] | RENDI_ENV=prod
```

| qué | antes | ahora |
|---|---|---|
| `SECRET_KEY` | una API key de Anthropic | `token_urlsafe(64)` propio, sin relación con nada |
| `ANTHROPIC_API_KEY` | el mismo valor | intacta, sigue siendo la de Anthropic |
| `CREDENTIALS_KEY` | no existía | clave propia para las credenciales de broker |

Confirmación funcional: el founder **fue deslogueado** al aplicarse el cambio (es la señal
esperada) y las **2 credenciales de broker** habían migrado antes, con el gate en verde
(`2 ya bajo CREDENTIALS_KEY, 0 migradas ahora, 0 ilegibles`).

**El hallazgo C1 del `AUDIT_REPORT_2026-05-25` queda cerrado**, 3 meses y medio después.

### Lo que costó, y por qué vale anotarlo

El fix de código estuvo bien a la primera; **lo que falló tres veces fue el semáforo que lo
reporta**, y cada falla se comió una ronda entera:

1. El aviso salía por `print()`. El start de nixpacks no fuerza salida sin buffer → nunca
   apareció en Railway. Arreglado en `4d990810`.
2. El aviso pasó a `logging`, pero la rama "todo en orden" quedó en INFO. La función corre a
   nivel de módulo, **antes** del `logging.basicConfig(level=INFO)` que está ~1000 líneas más
   abajo del mismo archivo → los INFO se descartan en silencio. Justo la rama que autorizaba a
   seguir era la invisible. Arreglado en `363db686`.
3. Ni siquiera así se podía saber qué variables tenía el proceso, porque la pantalla de Railway
   las muestra enmascaradas. Se agregó un diagnóstico de arranque que loguea **largo y forma, sin
   valores** (`3b1cf95b`). **Ese renglón cerró el tema en un intento** después de cuatro rondas
   de deducción por descarte.

**La lección:** en un procedimiento manual guiado por un mensaje, *el mensaje es parte del
mecanismo*. Un gate que no se ve no es un gate — y el test que escribí para cubrir el punto 1
usaba `assertLogs(level="INFO")`, que fuerza el nivel del logger y por lo tanto **certificaba en
verde algo que en producción no pasaba**. Es exactamente el error de método que la regla del
`CLAUDE.md` describe para el recalc, cometido dentro de la auditoría que lo cita.

### Pendientes que deja este cierre

1. **Sacar el diagnóstico temporal** `_log_config_arranque()` (`3b1cf95b`) cuando ya no haga falta.
2. **Rotar `ALERTS_CRON_TOKEN`**: se filtró en claro al pegar logs en un chat, porque los tokens
   de cron viajan en la query string. Ver `5a-resumen.md`, RC-1.
3. **`REBILL_API_KEY` asoma en los logs de cada arranque**: `rebill.py` escribe sus primeros 8
   caracteres en un warning. Hallazgo nuevo, va a la Tanda B (pagos).
4. **Sacar la `SECRET_KEY` hardcodeada** de `start-rendi.sh:43` y `.claude/settings.local.json:74`
   (severidad BAJA, el repo es privado y ese valor ya no es el de producción).
