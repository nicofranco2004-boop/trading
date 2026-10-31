# Correr la suite contra el Supabase nuevo, desde cerca de él

> 31/10/2026. Preparado, **no ejecutado**: no se creó ningún servicio ni se subió nada.

## Por qué no desde la Mac

El Supabase nuevo («RENDI 1», `us-west-1`, Norte de California) está a 276 ms por consulta y
1,69 s por conexión desde la Mac. La suite hace millones de consultas: serían días. Hay que
correrla desde una máquina que esté al lado.

## Dónde: tres opciones

| | Railway, servicio temporal (**recomendada**) | GitHub Actions | Sesión de Claude en la nube |
|---|---|---|---|
| Dónde corre | **California** (`us-west2`, «US West Metal», [docs](https://docs.railway.com/reference/regions)): la misma zona que Supabase `us-west-1` | no se puede elegir: «multi-cloud compute pool» ([docs](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)) | no está publicado |
| Latencia | pocos ms (a medir: el guion la escribe primero) | desconocida, puede ser de costa este | desconocida |
| Lo que además mide | **la latencia real app → base de producción**, que es la que decide si la app aguanta en esa región | nada útil para el pasaje | nada |
| Cómo llega el código | `railway up` desde la Mac (sube la carpeta, **sin push**) | hay que subir la rama a GitHub (push) | hay que subir la rama |
| Dónde va la clave de Supabase | variable del servicio en Railway, pegada en el formulario de Railway | secreto del repositorio, pegado en GitHub | variable del entorno, **visible para quien edita el entorno**: no hay guardado de secretos ([docs](https://code.claude.com/docs/en/cloud-environments)) |
| Costo | centavos: US$ 0,000463 por vCPU-minuto + US$ 0,000231 por GB-minuto ([precios](https://docs.railway.com/reference/pricing/plans)); 3 h con 1 vCPU y 1 GB ≈ US$ 0,13 | gratis dentro de los minutos del plan | dentro del plan de Claude |
| Riesgo | está en el mismo proyecto que producción: el servicio NO debe recibir las variables de la app (ver paso 4) | límite de tiempo por trabajo | sin región ni secreto propio |

## Los ajustes de la corrida (ya puestos en `scripts/suite_contra_supabase.sh`)

- **`--timeout=600`** por prueba. A 90 s, la corrida del 30/10 se cortó al 70 %: el reloj saltó
  mientras pytest armaba un error larguísimo. Además `--tb=short`, que lo achica.
- **Un solo proceso.** El pooler de Supabase en modo sesión, en el tamaño Micro, tiene un cupo de
  **15 conexiones** en total («Default Pool Size», [docs](https://supabase.com/docs/guides/platform/compute-and-disk)).
  Fue el `EMAXCONNSESSION` del 30/10. La suite no tiene instalado nada para correr en paralelo, y
  dos procesos con su pozo lleno ya superan el cupo.
- **`RENDI_PG_POOL_MAX=8`**: 8 conexiones del pozo, y el resto de las 15 queda para las conexiones
  propias de las pruebas (limpieza, candados, hilos).
- **El candado**: si la base tiene datos de personas, la suite no arranca
  (`tests/_candado_base_con_datos.py`). Supabase tiene que estar vacío, como está hoy.
- Para retomar si se corta: variable `SUITE_DESDE=tests/<archivo>.py`.

## Paso a paso para Nico

**Antes de empezar:** esto NO toca la app ni sus datos. Crea un servicio aparte, que corre las
pruebas una vez y se apaga. Al final lo borrás.

1. **Instalar la herramienta de Railway en la Mac** (una vez). En la Terminal:
   ```bash
   brew install railway
   ```
   Después `railway login`: se abre el navegador, aceptás, y la Terminal dice que entraste.
2. **Crear el servicio vacío.** railway.com → proyecto `resplendent-stillness` → botón
   **+ Create** → **Empty Service**. Nombralo `suite-supabase`.
3. **Configurarlo.** En `suite-supabase` → pestaña **Settings**:
   - **Region**: `US West (California)`.
   - **Config-as-code** → **Railway Config File** → escribí `railway.suite.toml`.
   - No le agregues volumen.
4. **La conexión a Supabase, sin pegarla en ningún chat.** En la Terminal de la Mac:
   ```bash
   pbcopy < ~/.rendi-supabase-url
   ```
   Eso copia la conexión al portapapeles **sin mostrarla en pantalla**. Después, en
   `suite-supabase` → pestaña **Variables** → **New Variable**: nombre `DATABASE_URL`, valor:
   pegás (⌘V). Guardar. Si Railway muestra un botón para aplicar los cambios (**Deploy**), da
   igual apretarlo o no: el servicio todavía no tiene código, y el paso 5 lo pone en marcha.
   **Ninguna otra variable**: si ves que Railway te ofrece «shared
   variables» o las de `trading`, no las agregues. En particular, nada de claves de mail.
5. **Subir el código y largar.** En la Terminal, parado en la carpeta del proyecto que tenga la
   rama de la migración (la sesión central te dice cuál):
   ```bash
   railway link
   ```
   Elegís el proyecto `resplendent-stillness` y el entorno `production`. Después:
   ```bash
   railway up --service suite-supabase --detach
   ```
   Sube la carpeta (no hace push a GitHub ni toca `trading`) y empieza a construir.
6. **Mirar.** `suite-supabase` → **Deployments** → el de arriba → **View Logs**. Qué vas a ver, en orden:
   - unos minutos de construcción (normal: es la misma imagen que la app);
   - una línea `=== LATENCIA hasta la base: … ===`: **pasale ese renglón a la sesión central**;
   - puntitos durante un rato largo (cada punto es una prueba que pasó; una `F` es una que falló);
   - al final `=== SUITE: terminó … con código N ===`.

   | si dice | qué hacés |
   |---|---|
   | `código 0` | terminó todo bien: avisale a la sesión central |
   | `código 1` | terminó con fallas: copiá desde la línea `short test summary info` hasta el final y pasáselo a la central |
   | `LA SUITE NO ARRANCA` | Supabase tiene datos: no sigas y avisale a la central |
   | se cortó sin la línea final | avisale a la central con la última línea que ves |

   Que el deployment quede como «Crashed» o «Completed» cuando termina es normal: el servicio
   no es una app que quede prendida.
7. **Borrar el servicio.** `suite-supabase` → **Settings** → abajo de todo → **Delete Service**.
   Desde ahí deja de cobrar.

## Qué deja en Supabase

Las pruebas trabajan en esquemas propios (`t<número>_…`) y los borran al terminar. El arranque
deja en `public` las tablas **vacías** del esquema y la tabla `esquema_aplicado`; la copia del
pasaje no las cuenta (`scripts/verificar_copia.py`).
