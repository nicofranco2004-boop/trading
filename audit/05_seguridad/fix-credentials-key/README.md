# Fix — `CREDENTIALS_KEY`: separar la clave que cifra credenciales de la que firma sesiones

> Auditoría de seguridad · derivado del Paso 0 (`../5a-paso0-secret-key.md`).
> Construido y probado sobre `origin/main` = `897b0d63`.
> **✅ DEPLOYADO Y ROTACIÓN EJECUTADA 2026-09-08.** Commits `56c26782` + `4d990810` + `363db686` + `3b1cf95b`. Rotación verificada en los logs de producción; ver `../5a-paso0-secret-key.md` §11.

## El problema que resuelve

`user_broker_credentials.api_key_enc` (API key de Wallbit, refresh token de IOL) se cifra con
`Fernet(sha256(SECRET_KEY))` — la **misma** clave que firma los JWT (`main.py:31013-31026`).

Consecuencia: rotar la firma de sesiones deja **todas** las credenciales indescifrables. El
código ya lo contempla y lo loguea como `"dead: no se pudo descifrar el token (SECRET_KEY
cambió)"` (`main.py:31434`), pero no lo puede recuperar.

Por eso rotar duele, y por eso `SECRET_KEY` en producción sigue siendo una API key de Anthropic
tres meses y medio después de que el audit del 2026-05-25 dijera que había que rotarla. **La
causa raíz no es el valor: es que una sola clave hace dos trabajos.** Este fix los separa.

## Qué hace

Una clave propia, `CREDENTIALS_KEY`, y `SECRET_KEY` degradada a clave de **sólo lectura** de lo
que se cifró antes:

- `_wallbit_cipher()` pasa a devolver un **`MultiFernet([CREDENTIALS_KEY, SECRET_KEY])`**.
  La primera cifra, las dos descifran. Lo ya guardado se sigue leyendo el día 1.
- `_migrar_credenciales_a_credentials_key()` re-cifra las filas viejas **en el arranque**.
  Idempotente, barata (una fila por usuario conectado), y nunca tumba el boot.
- Imprime el **gate** que dice si ya es seguro rotar.
- **Sin `CREDENTIALS_KEY` no cambia nada**: una sola clave, comportamiento idéntico al de hoy.
  Dev y los tests no se enteran.

Corre en el arranque y no en un script a mano a propósito: la consola de Railway del founder no
conectaba el día que se escribió esto, y un paso que hay que acordarse de correr es un paso que
no se corre.

### Alcance del cambio

El cifrado es un **embudo único**: `_wallbit_cipher()` → `_wallbit_encrypt`/`_wallbit_decrypt`,
y de ahí salen **los 5 call sites que existen** (`main.py` de `origin/main`):

| línea | qué |
|---|---|
| 31259 | encrypt — `POST /api/wallbit/connect` |
| 31290 | decrypt — `POST /api/wallbit/sync` |
| 31430 | decrypt — `_iol_lab_refresh_one` |
| 31453 | encrypt — `_iol_lab_refresh_one` (rotación del refresh token) |
| 31517 | encrypt — `POST /api/iol/lab/probe` |

Ningún otro archivo del backend toca el cifrado (verificado archivo por archivo sobre
`origin/main`). **Los 5 quedan cubiertos por el cambio del embudo: no hay call site sin arreglar.**

Se mantienen los nombres `_wallbit_encrypt`/`_wallbit_decrypt` aunque hoy cifren también IOL.
Renombrarlos tocaría 5 call sites y 2 tests para un fix que tiene que salir ya; queda anotado
como limpieza cosmética.

## Archivos

| archivo | qué es |
|---|---|
| `01-main.py.patch` | el diff. Aplica limpio sobre `origin/main` (`git apply --check` ✅) |
| `02-test_credentials_key.py` | va a `backend/tests/test_credentials_key.py` |
| `../../_scripts/simular_rotacion_secret_key.sh` | simula la rotación entera, un proceso por deploy |

## Evidencia — MEDIDO

Todo lo de abajo se ejecutó sobre una copia de `origin/main` con el patch aplicado
(`/tmp/rendi-fix`). No se tocó producción ni el repo.

**1. El patch aplica limpio y el archivo compila**

```
git apply --check -p1 01-main.py.patch   → OK aplica limpio
python3 -m py_compile main.py            → OK compila
```

**2. El test nuevo pasa: 7/7**

```
$ cd backend && python3 -m pytest tests/test_credentials_key.py
======================== 7 passed, 19 warnings in 1.05s ========================
```

**3. Sin regresión en los tests que ya existían sobre este cifrado: 26/26**

```
$ python3 -m pytest tests/test_iol_lab.py tests/test_wallbit.py tests/test_reset_data.py
26 passed, 19 warnings in 1.40s
```

**4. El pipeline completo de la rotación, un proceso distinto por deploy**

`SECRET_KEY` se lee al importar `main`, así que un redeploy sólo se puede simular con procesos
separados. Salida real:

```
── 1. ANTES: se guarda una credencial con el código viejo (sin CREDENTIALS_KEY) ──
   guardada. se lee: LA-API-KEY-DEL-USUARIO

── 2. DEPLOY con CREDENTIALS_KEY seteada → la migración corre sola en el arranque ──
credenciales: 0 ya bajo CREDENTIALS_KEY, 1 migradas ahora, 0 ilegibles. NO rotes SECRET_KEY todavía: redeployá y confirmá '0 migradas ahora'
   se sigue leyendo: LA-API-KEY-DEL-USUARIO

── 3. REDEPLOY sin cambios → el gate tiene que decir '0 migradas ahora' ──
credenciales: 1 ya bajo CREDENTIALS_KEY, 0 migradas ahora, 0 ilegibles. SEGURO rotar SECRET_KEY

── 4. ROTACIÓN de SECRET_KEY → la credencial TIENE que sobrevivir ──
credenciales: 1 ya bajo CREDENTIALS_KEY, 0 migradas ahora, 0 ilegibles. SEGURO rotar SECRET_KEY
   tras rotar, se lee: LA-API-KEY-DEL-USUARIO

── 5. CONTROL NEGATIVO: la misma rotación SIN haber seteado CREDENTIALS_KEY ──
   credencial PERDIDA ( InvalidToken ) — es lo esperado sin CREDENTIALS_KEY
```

El paso 5 es el que justifica que el orden sea obligatorio: sin el fix, esa rotación pierde la
credencial. Con el fix y el gate en verde, no.

**5. Semántica de `MultiFernet`, comprobada y no asumida**

```
cryptography 46.0.7
descifra lo viejo con MultiFernet: b'api-key-de-wallbit'
cifra con la PRIMARIA: sí (nueva la abre)
  la vieja no la abre: correcto
```

---

## Runbook — el orden es obligatorio

> Si se saltea un paso, las credenciales de Wallbit e IOL de los usuarios se pierden y hay que
> reconectarlas a mano. El gate del paso 3 existe para que eso no dependa de la memoria de nadie.

**1. Generar la clave nueva** (que NO sea la de Anthropic, ni la de firma, ni ninguna otra):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

**2. Setearla en Railway** → servicio `trading` → pestaña `Variables` → nueva variable
`CREDENTIALS_KEY`. **No toques `SECRET_KEY` todavía.**

**3. Deployar el patch y mirar los logs.** Buscá la línea `credenciales:`.
Va a decir `N migradas ahora`. **Redeployá (o esperá el próximo deploy) hasta que diga
`0 migradas ahora` y `SEGURO rotar SECRET_KEY`.** Ese es el gate.

**4. Recién ahí, rotar `SECRET_KEY`**: generar otra con el mismo comando y reemplazarla en
Railway. Efecto esperado y correcto: **desloguea a todos los usuarios**. Las credenciales de
broker **no** se pierden — eso es lo que se probó arriba.

**5. Después de rotar**, ya son dos secretos independientes: recién entonces rotar la
`ANTHROPIC_API_KEY` en la consola de Anthropic y actualizarla en Railway y en el `.env` local,
que es lo que había que hacer desde mayo.

**6. Verificar**: entrar a la app (te va a pedir login de nuevo) y, si tenés Wallbit conectado,
que `POST /api/wallbit/sync` siga funcionando sin reconectar.

### Si algo sale mal en el paso 3

La migración está envuelta en un `try/except` que nunca tumba el arranque. Si loguea
`⚠️ credenciales: la migración a CREDENTIALS_KEY falló`, las credenciales **siguen legibles con
`SECRET_KEY`** (nada se perdió) — el único efecto es que no se puede avanzar al paso 4. Sacar
`CREDENTIALS_KEY` de Railway te devuelve exactamente al estado de hoy.

---

## Lo que este fix NO hace

- **No rota nada.** Sólo hace que rotar sea barato. La rotación es el runbook de arriba y la
  ejecuta el founder.
- **No saca el `SECRET_KEY` hardcodeado** de `start-rendi.sh:43` ni de
  `.claude/settings.local.json:74`. Con el repo privado eso quedó calificado BAJO
  (`../5a-paso0-secret-key.md` §9.2), pero hay que sacarlo de los **dos** archivos.
- **No arregla el bypass del claim `pca`** (`main.py:2713`) ni la falta de `jti`/denylist: sigue
  sin poder revocarse una sesión sin deslogear a todos. Va como hallazgo aparte de la Tanda A.
- **No pinea `cryptography`** en `requirements.txt` — hoy entra transitivamente por
  `python-jose[cryptography]==3.3.0`. Es pre-existente (el código ya usaba Fernet) y pinearlo
  puede mover la versión resuelta del build; queda como recomendación, no como parte del patch.
