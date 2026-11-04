"""Guarda la conexión a Supabase en esta Mac sin que la contraseña pase por ningún chat.

Uso (lo corre Nico en su Terminal):  python3 scripts/conectar_supabase.py

1. Pide la cadena de conexión tal como la muestra Supabase (botón «Connect» →
   «Session pooler»), con el texto [YOUR-PASSWORD] adentro. Esa cadena no es secreta.
2. Pide la contraseña de la base SIN mostrarla en pantalla.
3. Se conecta de verdad, mide cuánto tarda una consulta, y recién ahí guarda la
   conexión en ~/.rendi-supabase-url, que sólo puede leer este usuario de la Mac y
   vive fuera del repo (nunca se sube a ningún lado).
"""
import getpass
import os
import sys
import time
from urllib.parse import quote

DESTINO = os.path.expanduser("~/.rendi-supabase-url")
MARCA = "[YOUR-PASSWORD]"


def main():
    print("Pegá la cadena de conexión de Supabase (la que tiene [YOUR-PASSWORD]) y apretá Enter:")
    cadena = input("> ").strip()
    if MARCA not in cadena:
        sys.exit("✋ La cadena no tiene [YOUR-PASSWORD]. Copiá la de «Session pooler» sin "
                 "reemplazar nada y volvé a correr el comando. No se guardó nada.")
    clave = getpass.getpass("Contraseña de la base (no se ve mientras escribís): ")
    if not clave:
        sys.exit("✋ Contraseña vacía. No se guardó nada.")
    dsn = cadena.replace(MARCA, quote(clave, safe=""))

    import psycopg
    print("Probando la conexión…")
    t0 = time.monotonic()
    try:
        c = psycopg.connect(dsn, autocommit=True, connect_timeout=15)
    except Exception as e:  # noqa: BLE001
        texto = str(e).replace(clave, "***")
        sys.exit(f"❌ No se pudo conectar: {texto}\nNo se guardó nada.")
    abrir = time.monotonic() - t0
    vueltas = []
    for _ in range(20):
        t = time.monotonic()
        c.execute("SELECT 1").fetchone()
        vueltas.append(time.monotonic() - t)
    tablas = c.execute("SELECT count(*) FROM information_schema.tables "
                       "WHERE table_schema='public'").fetchone()[0]
    c.close()
    vueltas.sort()

    with open(os.open(DESTINO, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(dsn)   # sin salto de línea: `pbcopy` lo copiaría y Railway lo guarda tal cual
    os.chmod(DESTINO, 0o600)

    print()
    print("✅ LISTO: la conexión anda y quedó guardada en esta Mac.")
    print(f"   abrir la conexión: {abrir:.2f} s")
    print(f"   una consulta, ida y vuelta: {vueltas[len(vueltas) // 2] * 1000:.0f} ms (mediana de 20)")
    print(f"   tablas en public: {tablas}")


if __name__ == "__main__":
    main()
