# Backups: qué hay hoy y con qué se queda Rendi después del pasaje

> 31/10/2026. Investigado, **nada configurado**.

## Hoy (SQLite, Railway)

Lo hace `backend/scripts/backup_db.py`, que la app corre sola (`_run_backup_db_job`, `main.py`):

| | |
|---|---|
| **Cuándo** | todas las noches a las **03:45 UTC** (00:45 en Argentina) |
| **Qué copia** | el archivo de la base SQLite, con la copia «en caliente» de SQLite (`.backup`): queda entera aunque haya alguien escribiendo |
| **A dónde** | 1) **siempre** al mismo disco de Railway (`BACKUP_LOCAL_DIR`, según la memoria `/data/backups`), comprimido; 2) **sólo si están puestas** las variables `BACKUP_S3_*`, además a un depósito externo tipo S3 (Backblaze, Cloudflare R2, AWS) |
| **Cuánto guarda** | en el disco, 30 días (`BACKUP_LOCAL_KEEP_DAYS`); afuera, 90 días (`BACKUP_REMOTE_KEEP_DAYS`), y el primero de cada mes durante un año |
| **A mano** | `POST /api/admin/backup-trigger` (sólo el admin) |

⚠️ La copia en el mismo disco **no protege si se pierde el disco**: sirve contra un error
nuestro, no contra una falla de Railway. La que protege de verdad es la de afuera, y **no se
sabe si está prendida**. Se averigua mirando (paso 1 de abajo).

### 🔴 Lo que pasa el día del pasaje si nadie toca esto

El trabajo nocturno sigue copiando **el archivo de SQLite** (`run_backup(db_path=DB_PATH)`).
Después del pasaje ese archivo queda viejo: nadie más escribe en él. Cada noche el registro va a
decir «Backup OK», sobre una base congelada en el día del pasaje. **Resuelto en la rama de la
migración** (ver «Lo programado»): llega con el pasaje, no antes.

## Lo que da Supabase en el plan Pro

Fuente: [backups](https://supabase.com/docs/guides/platform/backups.md) y [precios](https://supabase.com/pricing).

| | Backup diario (incluido) | Recuperación a un momento puntual (PITR, opcional) |
|---|---|---|
| Qué es | una foto de la base por día | se puede volver a cualquier segundo |
| Cuánto se puede perder | hasta **un día** de datos | hasta **2 minutos** |
| Cuántos días hacia atrás | **7** | 7, 14 o 28 |
| Costo | incluido en Pro (US$ 25/mes, que trae US$ 10 de crédito: cubre la máquina Micro de hoy) | **US$ 100/mes** por cada 7 días, y exige al menos la máquina Small (US$ 15/mes; con el crédito, US$ 5 más) |
| Cómo se recupera | desde el panel, sobre el mismo proyecto. **La app queda sin base mientras tanto** («the project is inaccessible during this process»), más tiempo cuanto más grande | igual |
| Ojo | no incluye archivos subidos a Supabase Storage (Rendi no los usa) | al prenderlo, deja de hacer los diarios |

Lo que Supabase **no** cubre: los backups viven en la misma cuenta y el mismo proveedor que la
base. Si se borra el proyecto (ya pasó una vez con el de São Paulo, a propósito) o se pierde el
acceso a la cuenta, no hay de dónde volver.

## Recomendación

1. **Supabase Pro con el backup diario incluido.** Es la red de todos los días y no cuesta
   nada extra.
2. **Una copia propia, afuera de Supabase, todas las noches**: un volcado completo de la base
   (`pg_dump`), comprimido, al depósito externo tipo S3, guardado 90 días. Reemplaza al backup
   nocturno de SQLite y reusa sus mismas variables `BACKUP_S3_*`. Es la que protege contra perder
   el proyecto o la cuenta.
3. **PITR: todavía no.** Cuesta unos US$ 105 más por mes. Lo que compra es bajar lo que se puede
   perder de un día a dos minutos. **La decisión es tuya**, y la pregunta es: si mañana hubiera
   que volver al backup de anoche, ¿cuánto te cuesta que la gente pierda lo que cargó a mano ese
   día? Lo importado se recupera re-importando; lo cargado a mano, no.
4. **Una prueba de recuperación antes del pasaje.** Bajar la copia de una noche, levantarla en
   una base aparte y comprobar que la app la lee. Un backup que nunca se restauró no está
   probado.

## Lo programado (31/10/2026, en la rama de la migración)

- **Con `DATABASE_URL`, el nocturno vuelca Postgres** (`backup_db.dump_postgres`): `pg_dump`
  en formato custom del esquema de la app → `rendi-pg-AAAA-MM-DD.dump`, al mismo disco y al
  mismo depósito S3, con la misma rotación (30 días en disco, 90 afuera, el primero de cada mes
  un año). Lo deciden explícito los dos que llaman: el nocturno y el botón del admin.
- **«Backup OK» no puede mentir.** La línea dice `motor=postgres tablas=N users=N operations=N
  size=N bytes`. Los conteos salen de la MISMA foto de la base que usa el volcado
  (`pg_export_snapshot`): son lo que trae el archivo. Además se verifica que `pg_restore` lo
  pueda leer.
- **Falla fuerte** (registro en ERROR, el botón del admin contesta `ok: false`) si: no hay
  `pg_dump`; `pg_dump` es más viejo que el servidor; el esquema no tiene tablas o no tiene
  usuarios; el archivo trae menos tablas que la base. **Nunca cae a copiar el SQLite.** Y con
  SQLite, si el archivo no cambia hace más de 48 h (`BACKUP_SQLITE_CONGELADO_HORAS`), tampoco
  es «OK».
- **`pg_dump` 17** en la imagen (`nixpacks.toml`, fase `pgdump`, nixpkgs fijo `nixos-24.11`):
  `pg_dump` no vuelca servidores más nuevos que él y sí los más viejos; los proyectos nuevos de
  Supabase arrancan en 17.
- **La prueba de recuperación es automática** (`tests/test_backup_postgres.py`): el nocturno de
  verdad vuelca, el volcado se restaura en una base vacía y las filas de cada una de las 79
  tablas coinciden con el original.
- ⚠️ **No verificado:** la construcción de la imagen en Railway con la fase nueva (acá no hay
  nixpacks ni Docker). Si falla, Railway no publica y la versión anterior sigue andando. Se ve
  en el primer deploy de la rama.

## Lo que hace Nico

**Ahora, sólo mirar (un minuto):**

1. **¿Está prendida la copia de afuera?** Railway → proyecto `resplendent-stillness` → servicio
   `trading` → **Deployments** → el de arriba → **View Logs** → en el buscador escribí
   `Backup OK`.

   | si la línea dice | significa |
   |---|---|
   | `remote=OK` | la copia de afuera anda: hay que mantenerla en el pasaje |
   | `remote=skip` | sólo existe la copia en el mismo disco de Railway |
   | no aparece ninguna | el backup nocturno no está corriendo: avisale a la sesión central |

2. **¿Supabase está en Pro?** El plan es de la organización, no del proyecto: supabase.com →
   arriba a la izquierda, el nombre de tu organización → **Settings** → **Billing**. Tiene que
   decir **Pro**. Si dice Free, no hay backups diarios. (Si no encontrás el botón exacto, la
   pantalla de inicio de la organización también muestra el plan al lado del nombre.)

**Antes del pasaje:**

0. **¿Qué versión de Postgres tiene Supabase?** supabase.com → proyecto **RENDI 1** → **Project
   Settings** → **Infrastructure**: dice la versión de Postgres. Si dice 17 (o 15 o 16), está
   cubierto. Si dijera 18, avisale a la sesión central antes del pasaje.

3. **El depósito de afuera**, si en el paso 1 dio `remote=skip`. Por ejemplo, con Cloudflare:
   dash.cloudflare.com → **R2 Object Storage** → **Create bucket** → nombre `rendi-backups` →
   **Create**. Después, **Manage API tokens** → **Create API token** → permiso **Object Read &
   Write**, sólo para `rendi-backups` → **Create**. La pantalla muestra **una sola vez** tres
   datos: Access Key ID, Secret Access Key y el endpoint. **No los pegues en ningún chat**: abrí
   en otra pestaña Railway → `trading` → **Variables** y cargá cada uno ahí:
   `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY` y `BACKUP_S3_ENDPOINT`, más
   `BACKUP_S3_BUCKET` = `rendi-backups` y `BACKUP_S3_REGION` = `auto`. Railway deja los cambios
   en espera y te muestra un botón para aplicarlos (**Deploy**): al apretarlo reinicia la app,
   con el corte breve de siempre. Es normal.
4. **Si decidís PITR:** Supabase → RENDI 1 → **Project Settings** → **Add-ons** → primero
   **Compute size: Small**, después **Point in time recovery**: 7 días.

**Después del pasaje, para comprobar que el backup anda (la mañana siguiente):**

5. Railway → `trading` → **Deployments** → el de arriba → **View Logs** → buscá `Backup`.

   | si la línea dice | significa |
   |---|---|
   | `Backup OK — motor=postgres tablas=…` con `users=` parecido a tu cantidad de usuarios | anda |
   | `Backup con errores` | no hay backup de esa noche: copiá la línea y pasásela a la sesión central |
   | `motor=sqlite` | el backup está copiando la base vieja: avisale a la central **ese mismo día** |
   | no aparece | el backup no corrió: avisale a la central |
