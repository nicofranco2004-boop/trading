"""
backup_db.py — Backup automático de la SQLite de Rendi.
═══════════════════════════════════════════════════════════════════════════

Doble destino (configurable via env vars):

  1. **Local siempre** — copia + gzip a `BACKUP_LOCAL_DIR` (default `./backups/`)
     dentro del mismo disco Railway. Útil para recovery rápido si un bug
     nuestro corrompe data (ej. una migración mal). NO protege si Railway
     pierde el disco entero.

  2. **Remoto opcional** — si están seteadas las env vars de S3-compatible
     (Backblaze B2, Cloudflare R2, AWS S3, MinIO), también sube la copia
     ahí. Esto sí protege contra pérdida total del disco.

Usa SQLite `.backup` API — consistente aunque haya writes en curso (no es
un simple file copy). El archivo backup queda íntegro, no a medio escribir.

Retention:
  - Local: últimos 30 días (configurable con BACKUP_LOCAL_KEEP_DAYS).
  - Remoto: últimos 90 días (configurable con BACKUP_REMOTE_KEEP_DAYS).
  - Mensual: además se preserva el primer backup de cada mes durante 1 año.

Uso manual:
    python -m backend.scripts.backup_db        # corre 1 vez ahora

Uso automático: registrado en el scheduler de main.py para correr diario
a las 03:45 UTC (después del snapshot job + lifecycle, para no pisar).

Env vars (todas opcionales):
    DB_PATH                  — path al archivo SQLite (default: trading.db)
    BACKUP_LOCAL_DIR         — dir local de backups (default: ./backups/)
    BACKUP_LOCAL_KEEP_DAYS   — retención local (default: 30)
    BACKUP_REMOTE_KEEP_DAYS  — retención remota (default: 90)
    BACKUP_S3_BUCKET         — nombre del bucket S3
    BACKUP_S3_ENDPOINT       — endpoint URL (B2/R2/MinIO; AWS auto-detectado)
    BACKUP_S3_ACCESS_KEY     — access key ID
    BACKUP_S3_SECRET_KEY     — secret access key
    BACKUP_S3_REGION         — región (default us-east-1)
    BACKUP_S3_PREFIX         — prefijo de keys (default: 'rendi/')
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ─── Config helpers ──────────────────────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


# ─── Step 1: Dump consistente vía SQLite .backup API ─────────────────────────

def dump_sqlite_consistent(db_path: str, dest_path: str) -> None:
    """Hace una copia consistente del archivo SQLite.

    Usa `sqlite3.Connection.backup()` (Python 3.7+) que es el método oficial
    para hacer backups en caliente — soporta writers concurrentes sin
    corromper el output.

    Args:
        db_path: path al archivo source (.db)
        dest_path: path donde escribir el dump (debe NO existir)
    """
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            # backup() copia páginas en chunks de 100 con un callback opcional;
            # acá usamos el modo simple (todo de una).
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


# ─── Step 2: Compresión gzip ─────────────────────────────────────────────────

def compress_gzip(src_path: str, dest_gz_path: str) -> int:
    """Comprime src → dest_gz. Devuelve el tamaño final en bytes."""
    with open(src_path, 'rb') as f_in, gzip.open(dest_gz_path, 'wb', compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    return os.path.getsize(dest_gz_path)


# ─── Step 3a: Upload S3-compatible (B2/R2/AWS/MinIO) ─────────────────────────

def _make_s3_client():
    """Crea un cliente boto3 S3 con la config de env vars.
    Devuelve None si la config no está completa o boto3 no está instalado.
    """
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    access = os.environ.get('BACKUP_S3_ACCESS_KEY')
    secret = os.environ.get('BACKUP_S3_SECRET_KEY')
    if not (bucket and access and secret):
        return None
    try:
        import boto3
    except ImportError:
        log.warning("boto3 no instalado; skip upload remoto. Agregalo a requirements.txt si querés backups remotos.")
        return None
    return boto3.client(
        's3',
        endpoint_url=os.environ.get('BACKUP_S3_ENDPOINT'),
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=os.environ.get('BACKUP_S3_REGION', 'us-east-1'),
    )


def upload_to_s3(local_path: str, key: str) -> bool:
    """Sube un archivo al bucket configurado. Devuelve True si OK."""
    client = _make_s3_client()
    if client is None:
        return False
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    try:
        client.upload_file(local_path, bucket, key)
        log.info(f"Backup remoto OK: s3://{bucket}/{key}")
        return True
    except Exception as e:
        log.error(f"Upload remoto falló: {e}")
        return False


def list_s3_backups(prefix: str) -> list:
    """Lista las keys del bucket bajo el prefix dado. Devuelve [] si falla."""
    client = _make_s3_client()
    if client is None:
        return []
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    try:
        out = []
        paginator = client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                out.append({'key': obj['Key'], 'modified': obj['LastModified']})
        return out
    except Exception as e:
        log.error(f"List S3 falló: {e}")
        return []


def delete_s3_key(key: str) -> bool:
    client = _make_s3_client()
    if client is None:
        return False
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    try:
        client.delete_object(Bucket=bucket, Key=key)
        log.info(f"Backup remoto eliminado: s3://{bucket}/{key}")
        return True
    except Exception as e:
        log.error(f"Delete remoto falló: {e}")
        return False


# ─── Step 3b: Local backup ───────────────────────────────────────────────────

def save_local_backup(gz_source_path: str, dest_dir: str, today_iso: str) -> str:
    """Copia el .gz comprimido al directorio local de backups.
    Returns: path final del backup.
    """
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    final_path = os.path.join(dest_dir, f"trading-{today_iso}.db.gz")
    shutil.copyfile(gz_source_path, final_path)
    return final_path


def prune_local_backups(dest_dir: str, keep_days: int) -> int:
    """Borra backups locales más viejos que keep_days. Preserva siempre el
    primero de cada mes durante 12 meses (para recovery de bugs viejos).
    Returns: cantidad de archivos eliminados.
    """
    if not os.path.isdir(dest_dir):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    monthly_cutoff = datetime.now(timezone.utc) - timedelta(days=365)
    files = sorted(Path(dest_dir).glob("trading-*.db.gz"))
    # Identificar el primer backup de cada mes en el último año (preservarlos)
    preserved_keys = set()
    seen_months = {}
    for f in files:
        try:
            # Extraer fecha YYYY-MM-DD del nombre
            stem = f.stem.replace('trading-', '').replace('.db', '')
            d = datetime.strptime(stem[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if d < monthly_cutoff:
                continue
            mkey = d.strftime('%Y-%m')
            if mkey not in seen_months or d < seen_months[mkey][0]:
                seen_months[mkey] = (d, f)
        except (ValueError, IndexError):
            continue
    preserved_keys = {str(t[1]) for t in seen_months.values()}

    deleted = 0
    for f in files:
        if str(f) in preserved_keys:
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception as e:
            log.warning(f"No pude borrar {f}: {e}")
    return deleted


def prune_remote_backups(prefix: str, keep_days: int) -> int:
    """Borra backups remotos más viejos que keep_days, preservando el primero
    de cada mes durante 12 meses."""
    backups = list_s3_backups(prefix)
    if not backups:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    monthly_cutoff = datetime.now(timezone.utc) - timedelta(days=365)

    # Identificar primeros de cada mes
    seen_months = {}
    for b in backups:
        try:
            # extraer fecha del key (esperamos formato: <prefix>YYYY-MM-DD.db.gz)
            fname = b['key'].rsplit('/', 1)[-1]
            stem = fname.replace('trading-', '').replace('.db.gz', '')
            d = datetime.strptime(stem[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if d < monthly_cutoff:
                continue
            mkey = d.strftime('%Y-%m')
            if mkey not in seen_months or d < seen_months[mkey][0]:
                seen_months[mkey] = (d, b['key'])
        except (ValueError, IndexError):
            continue
    preserved = {t[1] for t in seen_months.values()}

    deleted = 0
    for b in backups:
        if b['key'] in preserved:
            continue
        if b['modified'].replace(tzinfo=timezone.utc) < cutoff:
            if delete_s3_key(b['key']):
                deleted += 1
    return deleted


# ─── Orchestrator: el job que el scheduler invoca ────────────────────────────

def run_backup(db_path: Optional[str] = None) -> dict:
    """Pipeline completo: dump → comprimir → guardar local → subir remoto → prune.
    Devuelve un dict con stats del run para logging.
    """
    db_path = db_path or os.environ.get('DB_PATH') or 'trading.db'
    today = _today_utc()
    ts = _timestamp_utc()
    local_dir = os.environ.get('BACKUP_LOCAL_DIR', './backups')
    local_keep = _env_int('BACKUP_LOCAL_KEEP_DAYS', 30)
    remote_keep = _env_int('BACKUP_REMOTE_KEEP_DAYS', 90)
    remote_prefix = os.environ.get('BACKUP_S3_PREFIX', 'rendi/')
    if not remote_prefix.endswith('/'):
        remote_prefix += '/'

    stats = {
        'started_at': ts,
        'db_path': db_path,
        'local_path': None,
        'remote_key': None,
        'size_bytes': None,
        'local_pruned': 0,
        'remote_pruned': 0,
        'remote_uploaded': False,
        'errors': [],
    }

    if not os.path.isfile(db_path):
        stats['errors'].append(f"db_path no existe: {db_path}")
        return stats

    # Temp workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        dump_path = os.path.join(tmpdir, f"trading-{today}.db")
        gz_path = dump_path + '.gz'

        try:
            dump_sqlite_consistent(db_path, dump_path)
        except Exception as e:
            stats['errors'].append(f"dump falló: {e}")
            return stats

        try:
            size = compress_gzip(dump_path, gz_path)
            stats['size_bytes'] = size
        except Exception as e:
            stats['errors'].append(f"gzip falló: {e}")
            return stats

        # Local copy (siempre)
        try:
            local_final = save_local_backup(gz_path, local_dir, today)
            stats['local_path'] = local_final
        except Exception as e:
            stats['errors'].append(f"local save falló: {e}")

        # Remote upload (opcional)
        try:
            remote_key = f"{remote_prefix}trading-{today}.db.gz"
            if upload_to_s3(gz_path, remote_key):
                stats['remote_uploaded'] = True
                stats['remote_key'] = remote_key
        except Exception as e:
            stats['errors'].append(f"remote upload falló: {e}")

    # Prune (siempre, independiente de errores arriba)
    try:
        stats['local_pruned'] = prune_local_backups(local_dir, local_keep)
    except Exception as e:
        stats['errors'].append(f"local prune falló: {e}")

    try:
        stats['remote_pruned'] = prune_remote_backups(remote_prefix, remote_keep)
    except Exception as e:
        stats['errors'].append(f"remote prune falló: {e}")

    return stats


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    log.info("Iniciando backup manual…")
    stats = run_backup()
    log.info(f"Backup result: {stats}")
    return 0 if not stats.get('errors') else 1


if __name__ == '__main__':
    raise SystemExit(main())
