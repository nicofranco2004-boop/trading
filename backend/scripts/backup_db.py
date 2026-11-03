"""
backup_db.py — Backup automático de la base de Rendi.

Con `DATABASE_URL` (Postgres), un volcado `pg_dump` en formato custom
(`rendi-pg-AAAA-MM-DD.dump`, se restaura con `pg_restore`); sin ella, la copia
del SQLite (`trading-AAAA-MM-DD.db.gz`). Mismos destinos y misma rotación para
los dos. Ver `dump_postgres` y `run_backup`.
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
import re
import shutil
import sqlite3
import subprocess
import sys
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

def dump_sqlite_consistent(db_path: str, dest_path: str) -> dict:
    """Hace una copia consistente del archivo SQLite.

    Usa `sqlite3.Connection.backup()` (Python 3.7+) que es el método oficial
    para hacer backups en caliente — soporta writers concurrentes sin
    corromper el output.

    ⚠️ **La copia sale en modo WAL, y por eso hay que sacarla de ahí antes de
    archivarla.** `backup()` se lleva el journal_mode del origen, y producción
    corre en WAL (`main.py:351`). El archivo resultante queda entonces "en WAL y
    sin `-wal`" — porque el `-wal` de la copia recién hecha se cierra vacío y el
    gzip de arriba comprime SÓLO el `.db`. Ese estado tiene dos consecuencias
    caras, las dos medidas:

      · `sqlite3.connect("file:copia.db?mode=ro", uri=True)` falla con
        `unable to open database file` — un mensaje que no dice nada, y que es
        justo el que empuja al operador a sacarle el `mode=ro` "para ver si es
        eso". Ahí abre y lee de menos, en silencio.
      · El guardián de `scripts/copiar_a_postgres.py:75` **rechaza el archivo**
        diciendo que "se copió a medias". Es un falso positivo: la copia está
        COMPLETA. Y el remedio que sugiere el mensaje —"copiá los dos
        archivos"— es imposible, porque ese `-wal` nunca existió.

    Sin este PRAGMA, el día del pasaje a Postgres el copiador se niega a leer el
    backup de producción y el mensaje culpa al archivo equivocado.

    Se arregla acá, en el PRODUCTOR, y no en el guardián: la firma "WAL sin
    `-wal`" es idéntica a la de una copia truncada de verdad, así que aflojar el
    guardián lo dejaría ciego justo ante el error que existe para atajar. Un
    archivo de backup no necesita WAL.

    Args:
        db_path: path al archivo source (.db)
        dest_path: path donde escribir el dump (debe NO existir)

    Devuelve {tablas, filas: {users, operations}} contados EN LA COPIA, para que
    el registro diga qué trae el archivo y no qué tenía la base.
    """
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            # backup() copia páginas en chunks de 100 con un callback opcional;
            # acá usamos el modo simple (todo de una).
            src.backup(dst)
            # Ver el ⚠️ del docstring: deja el archivo legible con mode=ro y
            # aceptable para el copiador. No toca la base de producción.
            dst.execute("PRAGMA journal_mode=DELETE")
            info = {"tablas": dst.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'").fetchone()[0], "filas": {}}
            for t in ("users", "operations"):
                try:
                    info["filas"][t] = dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except sqlite3.Error:
                    info["filas"][t] = None
            return info
        finally:
            dst.close()
    finally:
        src.close()


# ─── Step 1b: Volcado de Postgres (pg_dump) ─────────────────────────────────
#
# 🔴 POR QUÉ. Con `DATABASE_URL` la app escribe en Postgres y el archivo SQLite
# queda congelado el día del pasaje. Hasta el 31/10/2026 este backup copiaba
# SIEMPRE el SQLite: después del pasaje habría seguido diciendo «Backup OK» cada
# noche sobre una base que ya no usa nadie (tests/test_escritores_solo_sqlite.py).
#
# Qué hace: `pg_dump` en formato custom (ya viene comprimido; se restaura con
# `pg_restore`) del esquema de la app, con la MISMA foto de la base que usa para
# contar las filas de cada tabla (`pg_export_snapshot`): lo que dice el registro
# es exactamente lo que trae el archivo. Después verifica que `pg_restore` lo
# pueda leer. Si falta `pg_dump`, o es más viejo que el servidor, falla con un
# mensaje claro: nunca copia el SQLite en su lugar.

class BackupFallido(Exception):
    """El backup no se hizo, o salió de una forma que no se puede llamar «OK»."""


def _herramientas_pg() -> tuple:
    """(pg_dump, pg_restore) de esta máquina. `BACKUP_PG_BIN` es la carpeta donde
    están (las pruebas usan las del Postgres local); si no, se buscan en el PATH
    (en Railway las instala el `Dockerfile` de la raíz)."""
    carpeta = os.environ.get("BACKUP_PG_BIN")

    def buscar(nombre):
        if carpeta:
            ruta = os.path.join(carpeta, nombre)
            return ruta if os.path.isfile(ruta) else None
        return shutil.which(nombre)
    dump, restore = buscar("pg_dump"), buscar("pg_restore")
    if not dump or not restore:
        raise BackupFallido(
            "pg_dump/pg_restore no están instalados en esta máquina: NO se hizo el backup de "
            "Postgres. Van en el `Dockerfile` (postgresql-client-17). No se copia el SQLite en su "
            "lugar: con DATABASE_URL puesta está congelado.")
    return dump, restore


def version_de_pg_dump(exe: str) -> str:
    """LA lectura de la versión de `pg_dump`: `pg_dump (PostgreSQL) 17.11 (Debian
    17.11-1.pgdg12+2)` → `17.11`. La usan el backup (para comparar contra el servidor) y
    el registro del arranque (`main._imagen_del_proceso`): una sola función, para que no
    puedan leer cosas distintas de la misma salida. Levanta `BackupFallido` si no la
    entiende."""
    salida = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True,
                            timeout=10).stdout
    m = re.search(r"\)\s*(\d+(?:\.\d+)*)", salida)
    if not m:
        raise BackupFallido(f"no entiendo la versión de {exe}: {salida.strip()!r}")
    return m.group(1)


def _version_mayor(exe: str) -> int:
    """`pg_dump (PostgreSQL) 17.2` → 17."""
    return int(version_de_pg_dump(exe).split(".")[0])


def dump_postgres(dsn: str, dest_path: str) -> dict:
    """Vuelca el esquema de la app a `dest_path` (formato custom de pg_dump).

    Devuelve {esquema, servidor, cliente, tablas, conteos: {tabla: filas},
    tablas_en_el_archivo}. Los conteos salen de la misma foto que el volcado.
    Levanta `BackupFallido` con el motivo si algo no da."""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend not in sys.path:
        sys.path.insert(0, backend)
    import pgsesion
    dump_exe, restore_exe = _herramientas_pg()
    cliente = _version_mayor(dump_exe)
    with pgsesion.conectar(dsn, autocommit=True) as c:
        servidor = int(c.execute("SHOW server_version_num").fetchone()[0]) // 10000
        if cliente < servidor:
            # pg_dump se niega a volcar un servidor más nuevo que él (docs de pg_dump).
            raise BackupFallido(f"pg_dump es {cliente} y el servidor es {servidor}: hay que "
                                f"subir la versión en el `Dockerfile` (postgresql-client-NN).")
        esquema = c.execute("SELECT current_schema()").fetchone()[0]
        c.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        foto = c.execute("SELECT pg_export_snapshot()").fetchone()[0]
        tablas = [r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY 1",
            (esquema,)).fetchall()]
        conteos = {t: c.execute(f'SELECT count(*) FROM "{esquema}"."{t}"').fetchone()[0]
                   for t in tablas}
        # Con la conexión (y la foto) todavía abierta: pg_dump la importa.
        p = subprocess.run(
            [dump_exe, "--format=custom", "--no-owner", "--no-privileges",
             f"--schema={esquema}", f"--snapshot={foto}", "--file", dest_path,
             "--dbname", dsn],
            capture_output=True, text=True)
        c.execute("COMMIT")
    if p.returncode != 0:
        raise BackupFallido(f"pg_dump falló (código {p.returncode}): {p.stderr.strip()[-600:]}")
    lista = subprocess.run([restore_exe, "--list", dest_path], capture_output=True, text=True)
    if lista.returncode != 0:
        raise BackupFallido(f"pg_restore no puede leer el volcado: {lista.stderr.strip()[-600:]}")
    en_el_archivo = sum(1 for l in lista.stdout.splitlines() if " TABLE DATA " in l)
    return {"esquema": esquema, "servidor": servidor, "cliente": cliente,
            "tablas": len(tablas), "conteos": conteos, "tablas_en_el_archivo": en_el_archivo}


def _por_que_no_es_ok(info: dict) -> list:
    """Lo que hace que un volcado que pg_dump dio por bueno NO sea un backup."""
    malo = []
    if not info["tablas"]:
        malo.append(f"volcado vacío: el esquema {info['esquema']!r} no tiene tablas")
    elif not info["conteos"].get("users"):
        malo.append(f"el esquema {info['esquema']!r} no tiene usuarios: ¿es la base de la app?")
    if info["tablas_en_el_archivo"] < info["tablas"]:
        malo.append(f"el archivo trae datos de {info['tablas_en_el_archivo']} tablas y la base "
                    f"tiene {info['tablas']}")
    return malo


def _horas_sin_cambios(db_path: str) -> float:
    """Horas desde la última escritura en el SQLite (el archivo o su `-wal`)."""
    ultima = max(os.path.getmtime(p) for p in (db_path, db_path + "-wal") if os.path.exists(p))
    return (datetime.now(timezone.utc).timestamp() - ultima) / 3600.0


# ─── Step 2: Compresión gzip ─────────────────────────────────────────────────

def compress_gzip(src_path: str, dest_gz_path: str) -> int:
    """Comprime src → dest_gz. Devuelve el tamaño final en bytes."""
    with open(src_path, 'rb') as f_in, gzip.open(dest_gz_path, 'wb', compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out)
    return os.path.getsize(dest_gz_path)


# ─── Step 3a: Upload S3-compatible (B2/R2/AWS/MinIO) ─────────────────────────

def _make_s3_client():
    """Crea un cliente boto3 S3 con la config de env vars.
    Devuelve (client, reason) — si client es None, reason explica por qué
    (env var faltante, boto3 ausente, etc.) para reportar en stats.
    """
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    access = os.environ.get('BACKUP_S3_ACCESS_KEY')
    secret = os.environ.get('BACKUP_S3_SECRET_KEY')
    missing = []
    if not bucket: missing.append('BACKUP_S3_BUCKET')
    if not access: missing.append('BACKUP_S3_ACCESS_KEY')
    if not secret: missing.append('BACKUP_S3_SECRET_KEY')
    if missing:
        return None, f"env vars faltantes: {', '.join(missing)}"
    try:
        import boto3
    except ImportError:
        return None, "boto3 no instalado (agregalo a requirements.txt)"
    try:
        client = boto3.client(
            's3',
            endpoint_url=os.environ.get('BACKUP_S3_ENDPOINT'),
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name=os.environ.get('BACKUP_S3_REGION', 'us-east-1'),
        )
        return client, None
    except Exception as e:
        return None, f"boto3.client init falló: {type(e).__name__}: {e}"


def upload_to_s3(local_path: str, key: str) -> tuple:
    """Sube un archivo al bucket configurado.
    Returns: (success: bool, error_msg: str or None)
    """
    client, reason = _make_s3_client()
    if client is None:
        return False, reason
    bucket = os.environ.get('BACKUP_S3_BUCKET')
    try:
        client.upload_file(local_path, bucket, key)
        log.info(f"Backup remoto OK: s3://{bucket}/{key}")
        return True, None
    except Exception as e:
        msg = f"upload_file falló: {type(e).__name__}: {e}"
        log.error(msg)
        return False, msg


def list_s3_backups(prefix: str) -> list:
    """Lista las keys del bucket bajo el prefix dado. Devuelve [] si falla."""
    client, _ = _make_s3_client()
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
    client, _ = _make_s3_client()
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

PREFIJO_PG, EXT_PG = "rendi-pg-", ".dump"


def _fecha_del_nombre(nombre: str) -> datetime:
    """`trading-2026-10-31.db.gz` o `rendi-pg-2026-10-31.dump` → esa fecha (UTC).
    ValueError si el nombre no trae fecha."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", nombre)
    if not m:
        raise ValueError(nombre)
    return datetime.strptime(m.group(1), '%Y-%m-%d').replace(tzinfo=timezone.utc)


def save_local_backup(gz_source_path: str, dest_dir: str, today_iso: str,
                      nombre: Optional[str] = None) -> str:
    """Copia el backup al directorio local de backups (por defecto con el nombre
    del de SQLite; el de Postgres pasa el suyo). Returns: path final del backup.
    """
    Path(dest_dir).mkdir(parents=True, exist_ok=True)
    final_path = os.path.join(dest_dir, nombre or f"trading-{today_iso}.db.gz")
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
    # Los dos tipos: el de SQLite y el volcado de Postgres (comparten la rotación).
    files = sorted(list(Path(dest_dir).glob("trading-*.db.gz"))
                   + list(Path(dest_dir).glob(f"{PREFIJO_PG}*{EXT_PG}")))
    # Identificar el primer backup de cada mes en el último año (preservarlos)
    preserved_keys = set()
    seen_months = {}
    for f in files:
        try:
            d = _fecha_del_nombre(f.name)
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
            d = _fecha_del_nombre(b['key'].rsplit('/', 1)[-1])
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

def _dsn_de_la_app() -> str:
    """La base de la app, de la MISMA fuente y con la misma regla que
    `main.DATABASE_URL` / `main.USANDO_PG`: `DATABASE_URL` del entorno, sin
    espacios. Vacía = la app usa SQLite."""
    return os.environ.get("DATABASE_URL", "").strip()


def run_backup(db_path: Optional[str] = None) -> dict:
    """Pipeline completo: copia → guardar local → subir remoto → prune.
    Devuelve un dict con stats del run para logging.

    EL MOTOR LO DECIDE ACÁ ADENTRO, mirando lo mismo que mira la app
    (`_dsn_de_la_app`): con `DATABASE_URL`, volcado de Postgres; sin ella, la
    copia del SQLite de `db_path`. NO es un parámetro: la primera versión
    (`972e6e4c`) recibía `dsn=None`, y quien llamara sin pasarlo copiaba el SQLite
    congelado y decía «OK» — una red que se apaga sola
    (tests/test_verificacion_no_es_opt_in.py). Y si el volcado falla, NO cae al
    SQLite.

    `stats['errors']` no vacío = el backup NO está bien, aunque haya archivo.
    """
    dsn = _dsn_de_la_app()
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
        'motor': 'postgres' if dsn else 'sqlite',
        'db_path': None if dsn else db_path,   # la DATABASE_URL lleva la clave: no va al registro
        'local_path': None,
        'remote_key': None,
        'remote_skip_reason': None,  # explica por qué remote_uploaded=False
        'size_bytes': None,
        'tablas': None,
        'filas': {},                 # users / operations: lo que trae la copia
        'conteos': None,             # Postgres: filas por tabla (de la misma foto)
        'local_pruned': 0,
        'remote_pruned': 0,
        'remote_uploaded': False,
        'errors': [],
    }

    if not dsn and not os.path.isfile(db_path):
        stats['errors'].append(f"db_path no existe: {db_path}")
        return stats

    # Temp workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        if dsn:
            nombre = f"{PREFIJO_PG}{today}{EXT_PG}"
            listo = os.path.join(tmpdir, nombre)
            try:
                info = dump_postgres(dsn, listo)
            except Exception as e:
                stats['errors'].append(f"volcado de Postgres falló: {e}")
                return stats
            stats['size_bytes'] = os.path.getsize(listo)
            stats['tablas'] = info['tablas']
            stats['conteos'] = info['conteos']
            stats['filas'] = {t: info['conteos'].get(t) for t in ('users', 'operations')}
            stats['errors'].extend(_por_que_no_es_ok(info))
        else:
            nombre = f"trading-{today}.db.gz"
            dump_path = os.path.join(tmpdir, f"trading-{today}.db")
            listo = dump_path + '.gz'
            try:
                info = dump_sqlite_consistent(db_path, dump_path)
            except Exception as e:
                stats['errors'].append(f"dump falló: {e}")
                return stats
            stats['tablas'], stats['filas'] = info['tablas'], info['filas']
            try:
                stats['size_bytes'] = compress_gzip(dump_path, listo)
            except Exception as e:
                stats['errors'].append(f"gzip falló: {e}")
                return stats
            # Un SQLite que no cambia hace días: la app escribe en otra base (o no
            # escribe). Se guarda igual, pero no es «OK».
            horas = _horas_sin_cambios(db_path)
            tope = _env_int('BACKUP_SQLITE_CONGELADO_HORAS', 48)
            if horas > tope:
                stats['errors'].append(
                    f"el SQLite no cambia hace {horas:.0f} h (tope {tope} h): ¿la app escribe en "
                    f"otra base? Con DATABASE_URL puesta, el backup es el volcado de Postgres.")

        # Local copy (siempre)
        try:
            stats['local_path'] = save_local_backup(listo, local_dir, today, nombre)
        except Exception as e:
            stats['errors'].append(f"local save falló: {e}")

        # Remote upload (opcional)
        try:
            remote_key = f"{remote_prefix}{nombre}"
            success, err_reason = upload_to_s3(listo, remote_key)
            if success:
                stats['remote_uploaded'] = True
                stats['remote_key'] = remote_key
            else:
                # No-throw: skip silencioso (env vars faltantes) ó error real
                # se reportan en remote_skip_reason para que el caller sepa.
                stats['remote_skip_reason'] = err_reason
        except Exception as e:
            stats['errors'].append(f"remote upload falló: {e}")
            stats['remote_skip_reason'] = str(e)

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


def resumen(stats: dict) -> str:
    """La línea del registro: qué motor, cuántas tablas y filas, cuánto pesa."""
    filas = stats.get('filas') or {}
    return (f"motor={stats.get('motor')} tablas={stats.get('tablas')} "
            f"users={filas.get('users')} operations={filas.get('operations')} "
            f"size={stats.get('size_bytes')} bytes local={stats.get('local_path')} "
            f"remote={'OK' if stats.get('remote_uploaded') else 'skip'} "
            f"pruned local={stats.get('local_pruned')} remote={stats.get('remote_pruned')}")


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
