#!/usr/bin/env bash
# La suite completa contra el Supabase nuevo, corrida desde un servicio temporal
# de Railway en US West (ver railway.suite.toml y
# audit/SUITE_SUPABASE_DESDE_RAILWAY.md). También sirve en cualquier máquina
# cerca de us-west-1 con DATABASE_URL puesta.
#
# Qué hace, en orden:
#   1. Mide la latencia hasta la base (abrir una conexión, 20 consultas) y la
#      escribe en el registro: es el número que decide si la app aguanta en esa
#      región, además de cuánto va a tardar esto.
#   2. Corre la suite entera. Si la base tiene datos de personas, la suite NO
#      arranca (tests/_candado_base_con_datos.py).
#   3. Escribe el resumen y termina.
#
# Ajustes (variables del servicio, todas opcionales):
#   SUITE_TIMEOUT       segundos por prueba (600). A 90 s la corrida del 30/10
#                       se cortó al 70 % por latencia.
#   RENDI_PG_POOL_MAX   conexiones del pozo por proceso (8). El pooler en modo
#                       sesión de Supabase Micro tiene un cupo de 15 conexiones
#                       en total; el resto de las 15 queda para las conexiones
#                       propias de las pruebas (limpieza, candados, hilos).
#   SUITE_DESDE         si se pone (ej. tests/test_plan_b_con_transaccion_abortada.py),
#                       corre ese archivo y los que le siguen, para retomar.
set -u
cd "$(dirname "$0")/../backend"

# Sin espacios ni saltos de línea en los bordes, igual que `main.DATABASE_URL`. El
# 31/10 la conexión llegó con un Enter al final (`pbcopy < ~/.rendi-supabase-url`
# copia el salto de línea del archivo) y Supabase contestó «database "postgres\n"
# does not exist». Se limpia acá una vez para todo lo que corre después.
DATABASE_URL="$(printf '%s' "${DATABASE_URL:-}" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
export DATABASE_URL

# Railway le pone RAILWAY_ENVIRONMENT=production (y otras RAILWAY_*) a todo lo que
# corre ahí, también a este servicio de prueba. La app lo lee como «esto es
# producción» y, por ejemplo, rechaza los avisos de cobro sin clave: el 31/10 eso
# dio 20 fallas que en la Mac no existen. La suite tiene que ver lo mismo que en
# la Mac, así que se sacan antes de correrla.
for v in $(env | sed -n 's/^\(RAILWAY_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done

if [ -z "${DATABASE_URL:-}" ]; then
  echo "🔴 Falta la variable DATABASE_URL en este servicio (la conexión a Supabase)."
  exit 2
fi
. /opt/venv/bin/activate 2>/dev/null || true
# La imagen de la app no trae pytest: las mismas versiones que en la Mac.
pip install -q 'pytest==8.4.2' 'pytest-timeout==2.4.0'

export SECRET_KEY="${SECRET_KEY:-suite-$(date +%s)}"
export RENDI_PG_POOL_MAX="${RENDI_PG_POOL_MAX:-8}"

python3 - <<'EOF'
import os, statistics, time
import psycopg
t = time.monotonic()
c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
abrir = time.monotonic() - t
vueltas = []
for _ in range(20):
    t = time.monotonic()
    c.execute("SELECT 1").fetchone()
    vueltas.append(time.monotonic() - t)
c.close()
print(f"=== LATENCIA hasta la base: abrir {abrir*1000:.0f} ms · consulta mediana "
      f"{statistics.median(vueltas)*1000:.1f} ms (mín {min(vueltas)*1000:.1f}, "
      f"máx {max(vueltas)*1000:.1f}) ===", flush=True)
EOF

ARCHIVOS="tests"
if [ -n "${SUITE_DESDE:-}" ]; then
  ARCHIVOS=$(ls tests/test_*.py | sort | awk -v d="$SUITE_DESDE" '$0 >= d')
fi

echo "=== SUITE: empieza $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="
# --tb=short: el traceback largo parsea main.py entero (46k líneas) y en la
# corrida del 30/10 el reloj de pytest saltó MIENTRAS lo armaba (INTERNALERROR).
python3 -m pytest -p no:randomly --timeout="${SUITE_TIMEOUT:-600}" --tb=short -q -rfE $ARCHIVOS
codigo=$?
echo "=== SUITE: terminó $(date -u '+%Y-%m-%d %H:%M:%S UTC') con código $codigo ==="
exit $codigo
