# El tope de 15 conexiones de Supabase al publicar — medido

> 02/11/2026, rama `claude/pg-rojos-viejos-ae0d95` (sobre `53a32d87`). Sólo medición y
> recomendación: no se cambió nada en Railway, en Supabase ni en el código.

## En una línea

**Con la configuración de hoy, cada publicación sobre Supabase puede tirar errores 500 a
los usuarios durante unos segundos.** Medido: con la copia vieja ocupando sus 10 conexiones,
la copia nueva consiguió 5 y **69 de 80 pedidos dieron 500**. Se arregla subiendo «Pool Size»
en Supabase de 15 a **24** (un cambio de un número, sin efecto en los usuarios hoy porque
producción todavía no usa Supabase). Alternativa sin tocar Supabase: `RENDI_PG_POOL_MAX=7`
(medido: 0 errores).

## 1 · Cuántas conexiones usa UNA copia de la app

Producción corre **un solo proceso** por copia: `CMD … exec uvicorn main:app` sin
`--workers` (`Dockerfile`), y Railway tiene una réplica.

| quién | cuántas | cuándo | ¿por el pozo? |
|---|---|---|---|
| los pedidos, los hilos de fondo, los programadores (fotos, alertas, mails) | hasta `RENDI_PG_POOL_MAX` (10) | siempre | sí |
| aplicar el esquema (`main._aplicar_esquema_pg`) | 1 | sólo al arrancar, se cierra | no |
| el candado de las reparaciones del arranque | 1 | sólo al arrancar, antes del chequeo de salud | no |
| leer el catálogo de claves (`pgshim._cargar_pks`) | 1, corta | una vez por proceso, en el primer INSERT | no |
| el respaldo nocturno (`pg_dump` con la misma `DATABASE_URL`) | 1 | mientras dura el respaldo | no |

**Medido** (Postgres local, la app levantada como en producción, sin red):
- arranque: pico de **2**;
- 120 pedidos que tocan la base, de a 40 a la vez: pico de **10** (el tope del pozo), 120 × 200;
- **en reposo quedan las 10 abiertas**: el pozo guarda las conexiones quietas hasta 5 minutos
  (`_QUIETA_MAXIMO = 300 s`). O sea que una copia que tuvo un pico **sigue ocupando** esas
  conexiones aunque no esté haciendo nada.

**Peor caso de una copia: 10 + 1 (catálogo) + 1 (respaldo) = 12.** Al arrancar suma 2 que se
sueltan antes de recibir pedidos.

## 2 · ¿La copia vieja suelta sus conexiones al recibir SIGTERM?

**Sí, enseguida, si no tiene nada en curso.** Medido tres veces: el proceso terminó en
0,2–0,4 s y las conexiones bajaron a 0 en ~0,5 s (10 → 0, 7 → 0). No las retiene los 30 s.

Lo que puede estirarlo: pedidos en curso y las corridas en fila (alertas, avisos, mails), que
`_cerrar_al_apagar` espera hasta 20 s. Mientras tanto la copia vieja sigue con sus
conexiones. Eso NO se midió (habría que simular un pedido largo en el momento del corte).

**El momento de riesgo no es el apagado: es antes.** Railway prende la copia nueva y le pasa
pedidos mientras la vieja sigue viva con sus conexiones guardadas (hasta 10, por el punto de
arriba). El apagado de la vieja recién empieza cuando la nueva ya contesta.

## 3 · Qué pasa cuando se pide la conexión 16

**Medido** con un Postgres local configurado para aceptar 15 clientes de la app y rechazar el
16º (`max_connections = 18`, 3 reservadas). Lo verifiqué antes: 15 entran, la 16ª se rechaza
en 0,001 s, igual que el pooler de Supabase (que devuelve `EMAXCONNSESSION`). En los dos casos
la app recibe un error al CONECTAR, que es el camino que importa.

**La app da 500 en el acto. No reintenta ni espera.** El pozo espera hasta 30 s sólo cuando
SUS 10 conexiones están prestadas; si la base rechaza abrir una nueva, el error sale tal cual
(`pgshim._Pozo.tomar` → `pgsesion.conectar`) y no hay ningún manejador que lo convierta.

| simulación de una publicación (vieja con su pozo lleno + nueva arrancando y atendiendo) | copia vieja | copia nueva | pico |
|---|---|---|---|
| `RENDI_PG_POOL_MAX=10` | 80 × 200 | **69 × 500**, 11 × 200 | 14 |
| `RENDI_PG_POOL_MAX=7` | 80 × 200 | 80 × 200 | 14 |

Y un detalle que empeora el primer caso: **la copia nueva pasa el chequeo de salud igual**
(arrancar le pide sólo 2 conexiones), así que Railway la da por buena y le manda los usuarios.

## 4 · Hasta dónde se puede subir «Pool Size» en Supabase

Leído en Supabase con UNA conexión corta (2,7 s), el 02/11:
- `max_connections` = **60**, `superuser_reserved_connections` = **3** (Postgres 17.11);
- clientes de Supabase mismo: **7** (`pgbouncer` 3, `supabase_admin` 2, `authenticator` 2; este
  último es la Data API, o sea que **hoy está prendida**). El resto de lo listado son procesos
  de fondo que no cuentan.

La regla de Supabase ([Supavisor FAQ](https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI),
[Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk)): con la Data API
en uso, no pasar del **40 %** de `max_connections` (= 24); sin ella, hasta el **80 %** (= 48). En
modo sesión, «Pool Size» ES el tope de clientes a la vez de la app. Y es **por combinación de
usuario + base + modo**: la app usa una sola.

**24 entra con margen:** 24 del pool + 7 de Supabase + 3 reservadas = 34 de 60; quedan 26 para
la consola SQL, un respaldo directo o una herramienta de diagnóstico.

## 5 · Recomendación

**Subir «Pool Size» de 15 a 24, y dejar `RENDI_PG_POOL_MAX` en 10.**
- Peor caso al publicar: vieja 10 (+1 si justo corre el respaldo) + nueva 10 + 1 de catálogo
  = **22 ≤ 24**.
- Hoy es gratis: producción todavía no usa Supabase, así que el cambio no lo ve ningún usuario.
- Si después del pasaje se apaga la Data API (está en el plan, paso 9-bis), la regla pasa al
  80 % y podría subirse más. No hace falta.

**Alternativa si no se quiere tocar Supabase:** `RENDI_PG_POOL_MAX=7` en Railway. Medido sin
errores (pico 14 de 15). Margen justo: 7 + 7 + 1 de catálogo = 15. Con el respaldo corriendo
en el mismo momento sería 16, así que conviene 6. El costo: con 7 (o 6) pedidos pesados a la
vez, el 8º espera a que se libere una (hasta 30 s), en vez de correr en paralelo.

**Propuesta aparte, en código, sin hacer** (`pgshim` es pieza compartida, necesita OK de la
central): que `_Pozo.tomar`, si la base RECHAZA la conexión por tope, espere y reintente unos
segundos en vez de devolver 500. Con eso, un tope que se toca por un instante se vuelve una
demora y no un error.

### Los clicks (para Nico)

**Antes de empezar:** no se pierde nada ni se corta nada para los usuarios: producción hoy no
usa Supabase. Conviene hacerlo cuando la sesión central NO esté corriendo pruebas contra
Supabase (preguntale), por si el pooler se reinicia unos segundos al guardar.

1. Entrá a [supabase.com](https://supabase.com) → tu proyecto **RENDI 1**.
2. Menú de la izquierda → **Database** → **Settings** (en algunas versiones de la pantalla
   está en **Project Settings → Database**).
3. Buscá el recuadro **Connection pooling configuration**. Ahí dice **Pool Size** y hoy tiene
   **15**.
4. Cambiá el número a **24** → **Save**.
5. **Para confirmar, mirando:** volvé a abrir esa pantalla. ¿El campo **Pool Size** dice
   **24**?
   - Si dice 24 → listo, avisale a la sesión central.
   - Si no te deja poner 24 o muestra un aviso de límite → no insistas, sacale una captura y
     pasásela a la central.
   - Si no encontrás el recuadro → decile a la central en qué pantalla quedaste.

## Cómo se midió (para repetirlo)

Scripts en la carpeta compartida de la central (`ensayo-pasaje/`): `servidor.py` (la app como en
producción, sin red), `medir_conexiones.py` (cuenta en `pg_stat_activity` cada 50 ms y simula la
publicación con `copias=2`), `leer_supabase.py` (la lectura corta). Postgres local 16.2 propio,
apagado y borrado al terminar.
