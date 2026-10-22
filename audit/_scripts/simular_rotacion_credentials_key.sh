#!/bin/bash
# Simula la ROTACIÓN DE CREDENTIALS_KEY tras el incidente de Railway (2026-10-21),
# con un proceso distinto por deploy: la migración corre al importar main, así
# que cada paso es un arranque real del backend, como en Railway.
#
# Uso: bash audit/_scripts/simular_rotacion_credentials_key.sh <dir-del-backend>
set -eu
BK="${1:?falta el directorio backend}"
DB=$(mktemp -t rendisimck).db
SK_VIEJA="secret-key-filtrada-en-railway-xxxxxxxxxxxxxxxxxxxxxxxx"
SK_NUEVA="secret-key-nueva-post-incidente-zzzzzzzzzzzzzzzzzzzzzzz"
CK_VIEJA="credentials-key-filtrada-en-railway-yyyyyyyyyyyyyyyyyy"
CK_NUEVA="credentials-key-nueva-post-incidente-wwwwwwwwwwwwwwwwww"
cd "$BK"

paso () { echo; echo "── $1 ──"; }
leer='print("   se lee:", main._wallbit_decrypt(main.get_db().execute("SELECT api_key_enc FROM user_broker_credentials").fetchone()["api_key_enc"]))'

paso "0. HOY: credencial guardada bajo la CREDENTIALS_KEY filtrada"
DB_PATH="$DB" SECRET_KEY="$SK_VIEJA" CREDENTIALS_KEY="$CK_VIEJA" python3 -c "
import main
c = main.get_db()
c.execute(\"INSERT INTO users (id,email,password_hash,approved) VALUES (1,'a@t.com','H',1)\")
c.execute('INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (1,?,?)',
          ('iol_lab', main._wallbit_encrypt('REFRESH-TOKEN-DEL-USUARIO')))
c.commit(); c.close()
$leer" 2>&1 | grep -E 'credenciales:|se lee'

paso "1. DEPLOY A: SECRET_KEY nueva + CREDENTIALS_KEY_ANTERIOR = copia de la actual"
DB_PATH="$DB" SECRET_KEY="$SK_NUEVA" CREDENTIALS_KEY="$CK_VIEJA" CREDENTIALS_KEY_ANTERIOR="$CK_VIEJA" \
  python3 -c "import main; $leer" 2>&1 | grep -E 'credenciales:|se lee'

paso "2. DEPLOY B: CREDENTIALS_KEY nueva (la anterior sigue) → la migración re-cifra"
DB_PATH="$DB" SECRET_KEY="$SK_NUEVA" CREDENTIALS_KEY="$CK_NUEVA" CREDENTIALS_KEY_ANTERIOR="$CK_VIEJA" \
  python3 -c "import main; $leer" 2>&1 | grep -E 'credenciales:|se lee'

paso "3. REDEPLOY sin cambios → tiene que decir 'SEGURO borrar CREDENTIALS_KEY_ANTERIOR'"
DB_PATH="$DB" SECRET_KEY="$SK_NUEVA" CREDENTIALS_KEY="$CK_NUEVA" CREDENTIALS_KEY_ANTERIOR="$CK_VIEJA" \
  python3 -c "import main" 2>&1 | grep -E 'credenciales:'

paso "4. DEPLOY C: se borra CREDENTIALS_KEY_ANTERIOR → la credencial TIENE que sobrevivir"
DB_PATH="$DB" SECRET_KEY="$SK_NUEVA" CREDENTIALS_KEY="$CK_NUEVA" \
  python3 -c "import main; $leer" 2>&1 | grep -E 'credenciales:|se lee'

paso "5. CONTROL NEGATIVO: cambiar CREDENTIALS_KEY a secas, sin ANTERIOR"
DB2=$(mktemp -t rendisimck2).db
DB_PATH="$DB2" SECRET_KEY="$SK_VIEJA" CREDENTIALS_KEY="$CK_VIEJA" python3 -c "
import main
c = main.get_db()
c.execute(\"INSERT INTO users (id,email,password_hash,approved) VALUES (1,'a@t.com','H',1)\")
c.execute('INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (1,?,?)',
          ('iol_lab', main._wallbit_encrypt('REFRESH-TOKEN-DEL-USUARIO')))
c.commit(); c.close()" >/dev/null 2>&1
DB_PATH="$DB2" SECRET_KEY="$SK_NUEVA" CREDENTIALS_KEY="$CK_NUEVA" python3 -c "
import main
try:
    $leer
    print('   ⚠️  se leyó: el control negativo FALLÓ')
except Exception as e:
    print('   credencial PERDIDA (', type(e).__name__, ') — es lo esperado sin CREDENTIALS_KEY_ANTERIOR')
" 2>&1 | grep -E 'credenciales:|PERDIDA|FALLÓ'
rm -f "$DB" "$DB2"
echo; echo "── fin ──"
