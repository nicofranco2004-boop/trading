# 5a · Secretos — inventario, exposición y qué rotar

> Tanda A, punto 4. Escrito directamente (sin agente) porque el barrido pesado ya se hizo en el
> Paso 0: `5a-paso0-secret-key.md`. Ese documento cubre `SECRET_KEY` en profundidad; acá está el
> resto del inventario y el veredicto de rotación.
> **Ningún valor de secreto aparece en este documento.**

## Método

- **MEDIDO**:
  - Barrido de **los 24.579 objetos** del repo (`git cat-file --batch-all-objects --batch`, o sea
    incluyendo blobs no alcanzables desde ninguna rama) contra 12 patrones de credencial real.
    Script: `audit/_scripts/scan_secretos_historial.sh`; salida cruda en
    `audit/_scripts/_hits_historial.txt`. **75 coincidencias, todas explicadas, ninguna es una
    credencial** (detalle en el Paso 0 §5).
  - Barrido del árbol de `b74f450f` buscando asignaciones a constantes largas y strings
    hex/base64 de ≥40 caracteres: 22 ubicaciones, 21 falsos positivos.
  - Inventario de env vars: `os.environ.get` / `os.getenv` / `os.environ[...]` con ambos tipos de
    comilla sobre `backend/**/*.py`. **55 variables distintas, 19 de ellas secretos.**
  - Huellas SHA-256 truncadas de los valores del `backend/.env` local y de `start-rendi.sh`,
    calculadas en shell sin imprimir los valores.
- **NO EJECUTADO**: no consulté la configuración de Railway (la consola no conectaba), no hice
  ninguna petición a la app desplegada, no verifiqué qué valor tiene cada variable en producción.
  Todo lo que dice "en prod" viene del founder o del código, y está marcado como tal.
- La **forma de comparar** los tokens compartidos (`==` vs `hmac.compare_digest`) y su rate
  limiting **no se auditan acá**: van en la Tanda B, punto 6.

---

## Resumen — qué hay que rotar

| # | secreto | severidad | ¿rotar? |
|---|---|---|---|
| S-1 | `SECRET_KEY` (prod) — es una API key de Anthropic | **ALTO-latente** | **SÍ**, con el runbook de `fix-credentials-key/` |
| S-2 | `ANTHROPIC_API_KEY` — comparte valor con S-1 desde el 2026-05-25 | **ALTO-latente** | **SÍ**, después de S-1 |
| S-3 | `SECRET_KEY` hardcodeada en el repo (2 archivos, 4 meses) | BAJO (repo privado) | no urgente; **sacarla igual de los dos** |
| — | los otros 16 secretos | — | **no**: ninguno está expuesto |

---

## Inventario completo — 19 secretos

Ninguno tiene valor por defecto hardcodeado salvo donde se indica. Todos se leen de `os.environ`.

### Autenticación y cifrado

| variable | dónde se lee | qué protege | estado |
|---|---|---|---|
| `SECRET_KEY` | `main.py:100` | **Firma de TODOS los JWT de sesión** (HS256) **y** la Fernet que cifra `user_broker_credentials` (`main.py:31019`) | 🔴 **S-1 / S-3** — ver abajo |
| `ADMIN_EMAIL_HASH` | `main.py:128` | Gate de admin por email. **Tiene default hardcodeado** (`main.py:126`) | 🟡 no es un secreto (es un hash) pero ver H-1 |

### IA

| variable | dónde se lee | qué protege | estado |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `main.py:20363`, `ai/llm.py:114` | La cuenta de API de Anthropic (costo real) | 🔴 **S-2** |

### Pagos

| variable | dónde se lee | qué protege | estado |
|---|---|---|---|
| `REBILL_API_KEY` | `billing/rebill.py` | Cuenta de Rebill: crear y cancelar suscripciones | ✅ no expuesto |
| `REBILL_WEBHOOK_SECRET` | `main.py:26824`, `billing/rebill.py` | Validación HMAC del webhook de pagos | ✅ no expuesto |
| `REBILL_WEBHOOK_TOKEN` | `billing/rebill.py:65` | Fallback: token en la URL del webhook | ✅ no expuesto |
| `MP_ACCESS_TOKEN` | `billing/mercadopago.py` | Mercado Pago — **LEGACY, migrado a Rebill** | ✅ no expuesto |
| `MP_WEBHOOK_SECRET` | `billing/mercadopago.py:81` | Idem, legacy | ✅ no expuesto |

### Tokens de cron y de servicio (protegen escrituras masivas)

| variable | dónde se lee | qué protege | estado |
|---|---|---|---|
| `SNAPSHOT_CRON_TOKEN` | `main.py:33665`, `33947` | Snapshot diario: **escribe datos de todos los usuarios** | ✅ no expuesto |
| `ALERTS_CRON_TOKEN` | `main.py:33597` | Corrida de alertas de todos los usuarios | ✅ no expuesto |
| `ADVISOR_BRIEF_TOKEN` | `main.py:33946` | Brief del asesor (cae al de snapshot si falta) | ✅ no expuesto |
| `IOL_LAB_CRON_TOKEN` | `main.py:31564` | Renovación horaria de los refresh tokens de IOL | ✅ no expuesto |
| `RENDI_MANTENIMIENTO_TOKEN` | `mantenimiento.py:109` | Bypass del modo mantenimiento | ✅ no expuesto |

Los cinco se pasan por **header `X-Cron-Token` o por `?token=` en la query string**. La segunda
forma deja el secreto en los logs de acceso de Railway y en el historial del navegador; va como
hallazgo en la Tanda B.

### Notificaciones, base y backups

| variable | dónde se lee | qué protege | estado |
|---|---|---|---|
| `RESEND_API_KEY` | `emails.py` | Envío de mail transaccional desde el dominio | ✅ no expuesto |
| `VAPID_PRIVATE_KEY` | `main.py:34126` | Firma de las push notifications | ✅ no expuesto |
| `VAPID_PUBLIC_KEY` | `main.py` | Pública por diseño | ✅ n/a |
| `DATABASE_URL` | `main.py`, `dberrors.py`, `mantenimiento.py` | Credenciales del Postgres (Supabase) | ✅ no expuesto |
| `PG_DSN_COPIA` / `PG_DSN_VERIF` | `scripts/copiar_a_postgres.py`, tests | DSN de migración y de verificación | ✅ no expuesto |
| `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY` | `scripts/backup_db.py:145-149` | **El bucket con la base entera de todos los usuarios** | ✅ no expuesto (pero ver Tanda B: falta verificar que el bucket sea privado) |

**Ninguno de los 16 anteriores tiene valor hardcodeado, ni aparece en el árbol, ni en los 24.579
objetos del historial.** Ese es el hallazgo positivo del punto 4: la higiene de secretos es buena
salvo por el caso de `SECRET_KEY`.

---

## Hallazgos

### [ALTO] S-1 · `SECRET_KEY` de producción es una API key de Anthropic

**Evidencia:** DEDUCIDO del código + confirmación del founder (de memoria, no medida sobre Railway).
**Dónde:** `main.py:100` (lectura), `main.py:2689`/`2704` (firma y verificación de JWT),
`main.py:31019` (derivación de la Fernet de credenciales).

Desarrollado entero en `5a-paso0-secret-key.md` §2, §8 y §9. En una línea: la clave que firma las
sesiones de todos los usuarios es una credencial de un tercero, que circula por lugares donde una
clave de firma no debería estar nunca (consola de Anthropic, `.env` en claro, historial de shell).

**Por qué ALTO y no CRÍTICO:** no hay ninguna vía por la que un tercero la tenga hoy. Verificado:
el único endpoint que vuelca env vars expone sólo `RENDI_ENV` y `RENDI_TRUSTED_PROXY_HOPS` y está
detrás de `get_admin_user` (`main.py:15992-16003`); la key nunca se imprime ni se loguea
(`main.py:20363`, `ai/llm.py:114-116`); los errores del subsistema IA son genéricos
(`main.py:25916`, `26196`, `28288`). **La app no la filtra: el riesgo es la circulación de la key.**

**El modo de falla es silencioso, y eso es lo peor:** `SECRET_KEY` y `ANTHROPIC_API_KEY` son dos
entradas distintas en Railway que guardan el mismo string. Rotar la key en la consola de Anthropic
**no cambia `SECRET_KEY`**. Una credencial retirada —que todo el mundo trata como inofensiva una
vez revocada— seguiría siendo la llave maestra de las cuentas.

**Solución de fondo:** el problema no es el valor, es que **una sola clave hace dos trabajos**.
Ya está construido y probado el fix que los separa: `audit/05_seguridad/fix-credentials-key/`
(aplicado en la rama `fix/credentials-key`, 33/33 tests verdes, sin commitear). El runbook de
rotación está en su README y el orden de los pasos es obligatorio.

### [ALTO] S-2 · `ANTHROPIC_API_KEY` comparte valor con la clave de firma

**Evidencia:** MEDIDO — huellas SHA-256 del `backend/.env` local: `SECRET_KEY` y
`ANTHROPIC_API_KEY` tienen la **misma huella** y 108 caracteres, formato `sk-ant-api…`.

Es el hallazgo **C1 del `AUDIT_REPORT_2026-05-25.md:23,37-47`**, que decía "hay que rotar".
**Sigue abierto 3 meses y medio después.** Rotar S-1 primero lo desactiva; después hay que rotar
la key de Anthropic por higiene, ya sin consecuencias sobre las sesiones.

### [BAJO] S-3 · `SECRET_KEY` hardcodeada en dos archivos versionados

**Evidencia:** MEDIDO — misma huella en `start-rendi.sh:43` y `.claude/settings.local.json:74`,
en las cuatro refs (`28d080c6`, `b74f450f`, `origin/main`, `HEAD`).
Introducida en `28d080c6` el **2026-05-07**, **nunca modificada** (`git log --all -S` devuelve un
solo commit). **4 meses en el repo.**

**Por qué BAJO:** el repo es privado, y ese valor **no es el de producción** (prod usa el de S-1).
En la máquina del founder tampoco firma nada, porque `backend/.env` le gana por `override=True`
(`main.py:26-30`). Sólo aplica a una máquina que clone el repo y levante el backend **sin** `.env`:
ahí las credenciales de broker de esa instancia quedan cifradas bajo una clave que cualquiera con
acceso al repo conoce.

**Qué hacer:** sacarla de **los dos** archivos —arreglar sólo `start-rendi.sh` deja el secreto
publicado en el otro— y agregar `.claude/settings.local.json` al `.gitignore` (el sufijo `.local`
indica que nunca debió versionarse). **No justifica reescribir el historial** con el repo privado.

**PARCHE:** el comentario de `start-rendi.sh:42` dice *"SECRET_KEY fija (para que los tokens
sobrevivan reinicios del backend)"*. El problema real que resolvía es que `main.py:100-113`
**acepta arrancar sin clave** en cualquier entorno que no se declare `RENDI_ENV=prod`, generando
una efímera por proceso. La solución correcta era poner la clave en `backend/.env`, que ya existe
y ya está ignorado. La causa sigue viva en `main.py:100-113`.

### [MEDIO] H-1 · El hash del email admin no oculta nada

**Evidencia:** ESTRUCTURAL — `main.py:123-126`.

`_ADMIN_EMAIL_HASH` es un SHA-256 hardcodeado, comparado con `hmac.compare_digest`
(`main.py:134`) explícitamente "para evitar timing attacks de enumeración del email admin".
Pero **el comentario de la línea 123-124 escribe el email del admin en claro**, dos líneas arriba
del hash. La defensa y su anulación conviven en el mismo bloque.

Además `main.py:3098` hace `is_admin_signup = _is_admin_email(data.email)`: registrarse con ese
email otorga admin. Hoy no es explotable porque la cuenta ya existe y el registro rechaza emails
duplicados — **pero eso hay que confirmarlo, y lo está haciendo el agente del tramo 1** de la
revisión de endpoints.

**Solución de fondo:** el gate de admin ya vive en la columna `users.is_admin`
(`get_admin_user`, `main.py:2720`). El camino por email es una segunda fuente de verdad para lo
mismo — una divergencia, no una defensa. Sacarlo, o al menos sacar el email del comentario.

---

## Lo que NO pude verificar

1. **Qué valor tiene cada variable en Railway.** La consola del servicio no conectaba y la pestaña
   `Variables` no se llegó a mirar. Todo lo que dice "en prod" sobre `SECRET_KEY` viene del
   founder, de memoria. La confirmación pendiente es de 10 segundos: `Variables` → `SECRET_KEY` →
   ícono del ojo → ¿empieza con `sk-ant-`?
2. **Si el bucket de backups es privado.** El código sube ahí la base entera; que el bucket no sea
   público es la única cosa que separa eso de una filtración total. Va en la Tanda B, punto 9.
3. **Si existen secretos fuera del repo y de Railway** (en un CI, en un Zapier, en cron-job.org).
   `cron-job.org` aparece citado en `main.py:31562` como el disparador del cron de IOL: los tokens
   de cron están configurados ahí, fuera del alcance de esta auditoría.
4. **Cómo se comparan los cinco tokens de cron** y si tienen rate limiting. Es la Tanda B, punto 6.
