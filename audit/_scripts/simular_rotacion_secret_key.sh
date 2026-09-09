#!/bin/bash
# Simula el PIPELINE COMPLETO de la rotación, con un proceso distinto por paso
# (SECRET_KEY se lee al importar main: en un solo proceso no se puede simular
# un redeploy). Cada paso es un arranque real del backend.
#
# Uso: bash audit/_scripts/simular_rotacion_secret_key.sh <dir-del-backend-parcheado>
set -eu
BK="${1:?falta el directorio backend}"
DB=$(mktemp -t rendisim).db
VIEJA="secret-key-vieja-simulando-la-de-anthropic-xxxxxxxxxxxx"
NUEVA_CREDS="credentials-key-propia-generada-aparte-yyyyyyyyyyyy"
ROTADA="secret-key-nueva-post-rotacion-zzzzzzzzzzzzzzzzzzzzzz"
cd "$BK"

paso () { echo; echo "── $1 ──"; }

paso "1. ANTES: se guarda una credencial con el código viejo (sin CREDENTIALS_KEY)"
DB_PATH="$DB" SECRET_KEY="$VIEJA" python3 -c "
import main
c = main.get_db()
c.execute(\"INSERT INTO users (id,email,password_hash,approved) VALUES (1,'a@t.com','H',1)\")
c.execute('INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (1,?,?)',
          ('wallbit', main._wallbit_encrypt('LA-API-KEY-DEL-USUARIO')))
c.commit(); c.close()
print('   guardada. se lee:', main._wallbit_decrypt(
    main.get_db().execute('SELECT api_key_enc FROM user_broker_credentials').fetchone()['api_key_enc']))
" 2>&1 | grep -v Warning

paso "2. DEPLOY con CREDENTIALS_KEY seteada → la migración corre sola en el arranque"
DB_PATH="$DB" SECRET_KEY="$VIEJA" CREDENTIALS_KEY="$NUEVA_CREDS" python3 -c "
import main
print('   se sigue leyendo:', main._wallbit_decrypt(
    main.get_db().execute('SELECT api_key_enc FROM user_broker_credentials').fetchone()['api_key_enc']))
" 2>&1 | grep -E 'credenciales:|se sigue leyendo'

paso "3. REDEPLOY sin cambios → el gate tiene que decir '0 migradas ahora'"
DB_PATH="$DB" SECRET_KEY="$VIEJA" CREDENTIALS_KEY="$NUEVA_CREDS" python3 -c "import main" 2>&1 | grep -E 'credenciales:'

paso "4. ROTACIÓN de SECRET_KEY → la credencial TIENE que sobrevivir"
DB_PATH="$DB" SECRET_KEY="$ROTADA" CREDENTIALS_KEY="$NUEVA_CREDS" python3 -c "
import main
print('   tras rotar, se lee:', main._wallbit_decrypt(
    main.get_db().execute('SELECT api_key_enc FROM user_broker_credentials').fetchone()['api_key_enc']))
" 2>&1 | grep -E 'credenciales:|tras rotar'

paso "5. CONTROL NEGATIVO: la misma rotación SIN haber seteado CREDENTIALS_KEY"
DB2=$(mktemp -t rendisim2).db
DB_PATH="$DB2" SECRET_KEY="$VIEJA" python3 -c "
import main
c = main.get_db()
c.execute(\"INSERT INTO users (id,email,password_hash,approved) VALUES (1,'a@t.com','H',1)\")
c.execute('INSERT INTO user_broker_credentials (user_id,broker,api_key_enc) VALUES (1,?,?)',
          ('wallbit', main._wallbit_encrypt('LA-API-KEY-DEL-USUARIO')))
c.commit(); c.close()" 2>&1 | grep -v Warning
DB_PATH="$DB2" SECRET_KEY="$ROTADA" python3 -c "
import main
try:
    main._wallbit_decrypt(main.get_db().execute('SELECT api_key_enc FROM user_broker_credentials').fetchone()['api_key_enc'])
    print('   ⚠️  se leyó: el control negativo FALLÓ')
except Exception as e:
    print('   credencial PERDIDA (', type(e).__name__, ') — es lo esperado sin CREDENTIALS_KEY')
" 2>&1 | grep -E 'PERDIDA|FALLÓ'
rm -f "$DB" "$DB2"
echo; echo "── fin ──"
