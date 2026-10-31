# Railway sin `railway.toml`: qué pasa el 1/12 y con qué se reemplaza

> 31/10/2026. Investigado y preparado en la rama `claude/pg-turno-pendientes-254ad4`.
> **No se tocó Railway ni se publicó nada.**

## 1. Qué dice la documentación oficial

- **El 1/12 el archivo deja de leerse.** «Config as Code is still read from your service
  repository during deploy for existing (legacy) services, and it overrides dashboard values
  for that service. New services cannot opt into Config as Code. Existing Config as Code files
  stop being read on **2026-12-01** (hard cutoff).»
  ([Infrastructure as Code](https://docs.railway.com/infrastructure-as-code)).
  La documentación **no dice** si el build falla ni si los ajustes se copian solos al panel.
  Lo que sí se deduce de la frase: desde ese día **mandan los valores del panel**.
- **Constructores.** Hoy figuran sólo `RAILPACK` (el de por defecto) y `DOCKERFILE`
  ([Config as Code](https://docs.railway.com/reference/config-as-code)); Nixpacks ya no aparece
  en la documentación de builds ([Build Configuration](https://docs.railway.com/builds/build-configuration)).
- **Railpack no lee `nixpacks.toml`.** Se configura con variables o con su propio archivo
  (`railpack.json`) ([Build Configuration](https://docs.railway.com/builds/build-configuration)).
  Que ignore `nixpacks.toml` lo dicen respuestas del foro de Railway, no una página oficial; lo
  vimos en la caja de prueba: armó con Railpack, detectó `start.sh` y lo corrió en bucle.
- **Un `Dockerfile` en la raíz lo usa siempre.** «When building a service, Railway will look for
  and use a `Dockerfile` at the root of the source directory»
  ([Dockerfiles](https://docs.railway.com/builds/dockerfiles)).
- **El reemplazo oficial** es `.railway/railway.ts`, que **no se lee al publicar**: lo aplica a
  mano la herramienta de Railway (`railway config apply`). En un solo archivo, «omitting a
  resource means deleting it». Su referencia **no documenta** cómo elegir el constructor ni el
  Dockerfile, ni la política de reinicio, ni `drainingSeconds`
  ([referencia](https://docs.railway.com/infrastructure-as-code/reference)).

**Qué le pasaría a producción el 1/12 si nadie hace nada:** la próxima publicación de `main`
se armaría con Railpack, sin `nixpacks.toml`. Lo más probable, por lo que vimos en la caja de
prueba: detecta `start.sh` y la app no levanta.

## 2. Por qué la caja de prueba (`suite-supabase`) ignoró `railway.suite.toml`

Dos motivos, y el primero solo ya alcanza (los dos, de la documentación):

1. **Era un servicio nuevo, y los servicios nuevos ya no pueden usar estos archivos**: «New
   services cannot opt into Config as Code».
2. **La ruta tenía que ser absoluta desde la raíz del repositorio, con barra**: «You have to
   specify the absolute path for the `railway.json` or `railway.toml` file, for example:
   `/backend/railway.toml`» ([Build Configuration](https://docs.railway.com/builds/build-configuration)).
   Se cargó `railway.suite.toml`, sin barra.

**No verificado:** si `railway up` respeta esa ruta. La documentación no lo dice, y con el
motivo 1 no hace falta saberlo. `railway.suite.toml` quedó sin uso (el servicio usa
`Dockerfile.suite`).

## 3. Las tres opciones para producción

| | **`Dockerfile` en la raíz (elegida)** | `.railway/railway.ts` | Todo a mano en el panel |
|---|---|---|---|
| Arma la imagen | sí, igual en cualquier lado | no: no documenta el constructor; igual hace falta un Dockerfile o configurar Railpack | Railpack + comandos a mano |
| Queda en el repo, revisable y con prueba | sí | sí | no |
| Se aplica solo al publicar | sí | no: `railway config apply` a mano cada vez | sí |
| Riesgo propio | la imagen pasa de Nix a Debian: hay que verificar el primer deploy | si el archivo no nombra un recurso, lo borra (el volumen, otro servicio) | Railpack no encuentra Python en la raíz (está en `backend/`) y hay que conseguirle `pg_dump` 17 |
| `healthcheck`, `drainingSeconds`, reinicio | en el panel / variables | sólo `healthcheck` documentado | en el panel / variables |

**Recomendación: el `Dockerfile`.** Es la única que deja la imagen igual en cualquier lado, sin
depender de qué detecte Railway ni de qué archivo de configuración lea. Los cinco ajustes de
`[deploy]` van al panel o a las variables del servicio, que existen antes y después del 1/12.

## 4. Qué conserva el `Dockerfile` (lo fija `backend/tests/test_imagen_de_produccion.py`)

| hoy (Nixpacks) | con el `Dockerfile` |
|---|---|
| `python311` | `python:3.11-slim-bookworm` |
| `gcc` + `stdenv.cc.cc.lib` (libstdc++) | `gcc`; libstdc++ viene en la imagen |
| venv en `/opt/venv`, `pip<26`, `backend/requirements.txt` | igual |
| `postgresql_17` (fase `pgdump`) | `postgresql-client-17` del repositorio oficial de PostgreSQL |
| arranque `. venv && cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT` | el mismo, con `exec` |

**Una diferencia, a propósito: `exec`.** Así uvicorn recibe él la señal de apagado que manda
Railway y corre el apagado ordenado dentro de `drainingSeconds`. Con un shell en el medio
(probable en Nixpacks, **no verificado**), la señal puede no llegarle.

La imagen copia sólo `backend/`: la app no lee nada de afuera mientras corre. Y
`.dockerignore` deja afuera las bases locales y los backups con datos reales.

## 5. Cada ajuste de `railway.toml` y dónde vive después del 1/12

| ajuste | valor | después del 1/12 | lo hace Nico |
|---|---|---|---|
| `builder` / `dockerfilePath` | `DOCKERFILE` | el `Dockerfile` de la raíz, que Railway usa siempre | nada |
| `restartPolicyType` | `on_failure` | el valor por defecto de Railway es «On Failure», 10 reintentos ([docs](https://docs.railway.com/deployments/restart-policy)) | sólo mirar que diga eso |
| `healthcheckPath` | `/api/health` | panel: **Settings → Healthcheck Path** | escribirlo |
| `healthcheckTimeout` | `300` | variable `RAILWAY_HEALTHCHECK_TIMEOUT_SEC` = `300` ([docs](https://docs.railway.com/deployments/healthchecks)) | crearla |
| `drainingSeconds` | `30` | variable `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` = `30` ([docs](https://docs.railway.com/reference/deployments)) | crearla |

Mientras `railway.toml` se lea, pisa al panel y los valores son los mismos: cargarlos antes no
cambia nada. **Hay que cargarlos antes del 1/12.**

## 6. El riesgo de la transición

- **El primer deploy con el `Dockerfile` cambia la imagen**: de Nix a Debian. La app y sus
  dependencias son las mismas (mismo `requirements.txt`), pero cambian el sistema y,
  posiblemente, la versión menor de Python (3.11.x). **No pude armar la imagen acá** (no hay
  Docker en la Mac).
- **Con el volumen de hoy, un deploy roto es un corte**: Railway apaga la copia vieja antes de
  prender la nueva. Por eso el paso 3 de abajo dice cómo volver atrás en un minuto.
- **⏰ El plazo no depende de la migración.** Si la mudanza a Postgres se publica después del
  1/12, producción (`main`) llega a esa fecha con `builder = "nixpacks"`. **Recomiendo publicar
  el `Dockerfile` aparte, desde `main`, antes del 15/11**, con margen para un segundo intento.
  Lleva 4 cosas: `Dockerfile`, `.dockerignore`, el `builder` de `railway.toml` y la línea de
  arranque que dice con qué imagen corre (`main._imagen_del_proceso`).

## 7. Paso a paso para Nico, el día que se publique

**Antes de publicar (cuando quieras, no cambia nada todavía):**

1. Railway → proyecto `resplendent-stillness` → servicio `trading` → pestaña **Settings** →
   buscá **Healthcheck Path** → escribí `/api/health`. Más abajo, **Restart Policy**: tiene que
   decir «On Failure». Si Railway muestra un botón para aplicar los cambios, apretalo: la app
   se reinicia, con el corte breve de siempre.
2. En el mismo servicio → pestaña **Variables** → **New Variable**, dos veces:
   `RAILWAY_HEALTHCHECK_TIMEOUT_SEC` = `300` y `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` = `30`.
   No son claves: los números se pueden ver y pegar sin problema.

**Después de publicar (la sesión central te avisa cuándo):**

3. Railway → `trading` → **Deployments** → el de arriba → **Build Logs**: tiene que mencionar
   **Dockerfile**, no «Nixpacks» ni «Railpack». Después **Deploy Logs** → buscá `imagen:`.

   | si la línea dice | qué hacés |
   |---|---|
   | `imagen: Python 3.11.… · pg_dump 17.…` | salió bien: seguí al paso 4 |
   | `pg_dump FALTA` | la app anda, pero el backup con Postgres no: avisale a la central |
   | `Python 3.12` u otra versión que no sea 3.11 | avisale a la central antes de seguir |
   | no aparece la línea, o el deploy dice **Failed** | volvé atrás con el paso 5 y avisale a la central |

4. Abrí `https://rendi.finance/api/health`. Tiene que mostrar `"ok": true`. Entrá a la app con
   tu cuenta: si ves tu cartera, anda.
5. **Si algo salió mal, volver atrás:** **Deployments** → el deploy anterior, el que funcionaba
   → los tres puntitos al final de esa fila → **Rollback** → confirmar. Railway vuelve a poner la
   imagen y las variables de ese deploy ([docs](https://docs.railway.com/deployments/deployment-actions)).
   Va a haber un corte de unos segundos mientras cambia.

**El 1/12 o después:**

6. Nada que hacer si los pasos 1 y 2 están hechos. La primera publicación después de esa
   fecha: repetí el paso 3.
