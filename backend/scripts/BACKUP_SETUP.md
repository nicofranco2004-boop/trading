# Backup automático de la SQLite — setup

## TL;DR

El cron diario ya está conectado al scheduler. Corre todos los días a las **03:45 UTC** (= 00:45 ART) y hace backup de `trading.db`.

**Sin configurar nada**, los backups quedan en `./backups/` del disco Railway. Eso protege contra bugs propios (alguien corre un script que rompe data) pero **NO** protege si Railway pierde el disco entero.

**Con env vars de S3-compatible** configuradas, además sube cada backup a un storage remoto. Eso protege contra todo.

## Activar backup remoto (recomendado)

### Opción A: Backblaze B2 (lo más barato — $0.005/GB/mes, ~$1/año para Rendi)

1. Crear cuenta en https://www.backblaze.com/cloud-storage
2. **Buckets** → **Create a Bucket** → Private. Nombre: `rendi-backups` o lo que prefieras.
3. **Application Keys** → **Add a New Application Key**:
   - Name: `rendi-backups`
   - Allow access to: `rendi-backups` bucket only
   - Type of Access: Read and Write
   - Copia `keyID` y `applicationKey` (este último solo se muestra una vez)
4. En tu bucket, mirá el endpoint. Va a ser algo como `https://s3.us-west-002.backblazeb2.com`
5. En Railway → tu proyecto → Variables, agregá:
   ```
   BACKUP_S3_BUCKET=rendi-backups
   BACKUP_S3_ENDPOINT=https://s3.us-west-002.backblazeb2.com
   BACKUP_S3_ACCESS_KEY=<tu keyID>
   BACKUP_S3_SECRET_KEY=<tu applicationKey>
   BACKUP_S3_REGION=us-west-002
   ```

### Opción B: Cloudflare R2 (también barato, $0/mes con tier gratis si <10GB)

1. Crear cuenta en https://cloudflare.com (si no tenés)
2. R2 → Create bucket → `rendi-backups`
3. Manage R2 API Tokens → Create API token con permiso "Edit" sobre tu bucket
4. Copia el `Account ID`, `Access Key ID`, `Secret Access Key`
5. Railway env vars:
   ```
   BACKUP_S3_BUCKET=rendi-backups
   BACKUP_S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
   BACKUP_S3_ACCESS_KEY=<Access Key ID>
   BACKUP_S3_SECRET_KEY=<Secret Access Key>
   BACKUP_S3_REGION=auto
   ```

### Opción C: AWS S3 (más caro pero más conocido)

1. Crear bucket en https://console.aws.amazon.com/s3
2. IAM → Users → Create user con policy `AmazonS3FullAccess` (o solo tu bucket)
3. Generar Access Key
4. Railway env vars:
   ```
   BACKUP_S3_BUCKET=rendi-backups
   # BACKUP_S3_ENDPOINT — dejarlo SIN setear (boto3 lo auto-detecta para AWS)
   BACKUP_S3_ACCESS_KEY=<AKIA...>
   BACKUP_S3_SECRET_KEY=<...>
   BACKUP_S3_REGION=sa-east-1
   ```

## Variables opcionales

```
DB_PATH=./trading.db                # path al archivo SQLite (default OK)
BACKUP_LOCAL_DIR=./backups          # dir local (default OK)
BACKUP_LOCAL_KEEP_DAYS=30           # cuántos días mantener local (default 30)
BACKUP_REMOTE_KEEP_DAYS=90          # cuántos días mantener en S3 (default 90)
BACKUP_S3_PREFIX=rendi/             # subcarpeta en el bucket (default 'rendi/')
```

**Retention especial**: el primer backup de cada mes se preserva durante 12 meses, independiente de `KEEP_DAYS`. Esto da capacidad de revertir bugs viejos sin gastar mucho storage.

## Test manual

Para correr un backup AHORA mismo (no esperar al cron):

```bash
cd backend
python -m scripts.backup_db
```

Vas a ver un log JSON con el resultado. Si hay errores aparecen ahí.

## Cómo restaurar un backup

```bash
# Bajar el .gz de S3 o copiar del disco local
gzip -d trading-2026-05-31.db.gz
# Apagar el server, reemplazar trading.db, prender de vuelta
mv trading.db trading.db.broken
mv trading-2026-05-31.db trading.db
# Reiniciar el servicio Railway
```

## Verificar que el cron corre en Railway

Después del primer deploy con esto:

1. Esperar al próximo 03:45 UTC (00:45 ART)
2. Ver logs en Railway → tu proyecto → Deployments → último deploy → Logs
3. Buscar `Backup DB scheduler iniciado` (boot) + `Backup OK` (al horario del cron)
4. Si configuraste S3, también buscar `Backup remoto OK: s3://...`

Si no aparece nada, el cron no se registró — revisar logs por errores en `_start_scheduler`.
