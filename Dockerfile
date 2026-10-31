# La imagen de PRODUCCIÓN (servicio `trading` de Railway).
#
# 🔴 POR QUÉ UN DOCKERFILE. Hasta acá la armaba Nixpacks, por `railway.toml`
# (`builder`) + `nixpacks.toml`. Railway deja de leer esos archivos de
# configuración el 2026-12-01 («Existing Config as Code files stop being read on
# 2026-12-01 (hard cutoff)», docs.railway.com/infrastructure-as-code), Nixpacks ya
# no figura entre los constructores y Railpack —el de por defecto— no lee
# `nixpacks.toml`. Sin esto, la publicación siguiente al corte la arma Railpack con
# lo que detecte: al servicio de prueba `suite-supabase` le detectó `start.sh` (el
# arranque LOCAL) y lo corrió en bucle sin Python. Un `Dockerfile` en la raíz lo
# usa Railway siempre (docs.railway.com/builds/dockerfiles) y no depende de ningún
# archivo de configuración.
#
# QUÉ CONSERVA, uno por uno contra `nixpacks.toml` (lo fija
# backend/tests/test_imagen_de_produccion.py):
#   · Python 3.11 y gcc (bcrypt/cryptography compilan si no hay wheel); libstdc++
#     viene en la imagen base (en Nix hacía falta `nixLibs`);
#   · un venv en /opt/venv, `pip<26` (el resolver de pip 26.1.1 no encontraba
#     fastapi) y `backend/requirements.txt`;
#   · `pg_dump` / `pg_restore` 17 para el backup nocturno con Postgres
#     (backend/scripts/backup_db.py): pg_dump no vuelca un servidor más nuevo que
#     él, y Supabase arranca los proyectos nuevos en 17. Debian bookworm trae el 15:
#     el 17 sale del repositorio oficial de PostgreSQL (postgresql.org/download/linux/debian);
#   · el mismo arranque: uvicorn `main:app` desde `backend/`, en 0.0.0.0:$PORT.
#
# UNA DIFERENCIA, a propósito: `exec`. uvicorn queda como el proceso principal y
# recibe él la señal de apagado (SIGTERM) que Railway manda a la copia vieja; así
# corre su apagado ordenado dentro de `drainingSeconds`. Con un shell en el medio,
# la señal puede no llegarle.
FROM python:3.11-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-17 \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv --copies /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --upgrade 'pip<26' \
 && pip install --no-cache-dir -r backend/requirements.txt

# Sólo `backend/`: la app no lee nada de fuera de esa carpeta mientras corre.
COPY backend/ backend/

WORKDIR /app/backend
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
