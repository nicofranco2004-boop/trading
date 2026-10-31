# El día del pasaje SQLite → Postgres, paso a paso (con tiempos medidos)

> Ensayo general del 31/10/2026, rama `claude/pg-rojos-viejos-ae0d95` (sobre `bb707a76`).
> Lo que acá dice «medido» salió de correrlo; lo que dice **[A MEDIR]** no se pudo medir
> en la Mac y hay que medirlo antes de fijar la fecha.
> Complementa —no reemplaza— el plan de `MIGRACION_POSTGRES.md` §1-§4 (el porqué de cada
> paso, los crons, los primeros 10 minutos). Si algo de acá choca con eso, gana lo medido
> y hay que corregir el otro.

## 0 · Qué se ensayó y con qué

- **Datos:** la copia de producción más nueva que hay en la Mac,
  `~/Downloads/trading-2026-08-16.db` (16/08/2026, 933 MB). **1.093 usuarios, 112.747
  operaciones, 2.566.597 filas en 78 tablas.** No hay ninguna más nueva en la Mac (se
  buscó en toda la carpeta personal, incluido `~/Documents/rendi-archivo/`).
- **Código:** el de la rama de la migración. Antes de copiar, ese código arrancó sobre
  la copia en SQLite (como va a estar producción ese día: con el código de hoy ya
  publicado), lo que llevó la base del esquema de agosto al de hoy (+18 tablas, +33
  columnas) y corrió las reparaciones del arranque.
- **Destino:** un Postgres 16.2 LOCAL propio (`pgserver`), no Supabase.
- **La app**, para comparar: dos procesos (uno por motor) **sin salida a internet**
  (sólo el enchufe local de la base): sin mails, sin avisos, sin precios en vivo. Lo
  que depende de la red falla igual en los dos y la comparación mide la base.

**Límites del ensayo (lo que NO dice):** los tiempos son de una Mac contra un Postgres en
la misma máquina. El día real hay red de por medio dos veces (bajar el respaldo de
Railway; copiar y verificar contra Supabase en us-west-1). Esos dos tramos son
**[A MEDIR]**.

## 1 · Tiempos medidos

| paso | tiempo | nota |
|---|---|---|
| respaldo consistente (`backup_db.dump_sqlite_consistent`) | 1,2 s | sale con byte 18 = 1 (sin WAL): pasa el guardián |
| comprimir (`compress_gzip`) | 7,2 s | 933 MB → 135 MB |
| bajarlo de Railway | **[A MEDIR]** | 135 MB por la red |
| descomprimir | 0,9 s | |
| `aplicar-esquema` | 0,2 s | 797 sentencias, 79 tablas |
| `preflight` | 7,7 s | limpio; pide **~2,5 GB libres** en el destino (pico) |
| `copiar` (copia + setval + verificación de 4 niveles) | **58,5 s y 72,3 s** (dos corridas) | la copia en sí 25,2 s y 37,6 s; el resto es la verificación |
| `copiar` contra Supabase | **[A MEDIR]** | lee y escribe 2,5 M filas por la red, y la verificación vuelve a leer TODO el destino |
| primer arranque de la app en Postgres | 1,3 s | aplica las 797 sentencias de esquema (ver §4.3) |
| arranques siguientes | 1,1 s | «esquema al día, 0 cambios» |
| 13 pantallas × 20 cuentas | ~80 s por motor | 264 pedidos, sin red |

**Ventana total en la Mac, de «mantenimiento prendido» a «verificado»: ~2 minutos** sin
contar las dos idas por la red. Con la red, **[A MEDIR]**: correr `copiar` una vez contra
un esquema APARTE de Supabase, desde la máquina que lo va a correr ese día, da el número.

## 2 · El día, en orden

**Antes del día (no el mismo día):**
- [ ] Medir los dos tramos [A MEDIR] de arriba.
- [ ] Confirmar en Railway que `SECRET_KEY` está puesta (si no, el reinicio desloguea a todos).
- [ ] Tener `RENDI_MANTENIMIENTO_TOKEN` definido (es la llave del operador para entrar con
      la app cerrada; sin él no hay forma de chequear antes de abrir).
- [ ] Las decisiones de Nico pendientes del traspaso §11.

**El día** (un domingo temprano: mercados cerrados, sin brief del asesor):

1. **Apagar los crons externos** — los TRES tokens (`MIGRACION_POSTGRES.md` §4). Primero,
   porque los mails a asesores y de cobros no se pueden desmandar.
2. **Mantenimiento ON sobre SQLite:** `RENDI_MANTENIMIENTO=1` y reiniciar. Desde acá nadie
   escribe. *(No poner nunca `RENDI_MANTENIMIENTO=0`: ver la memoria.)*
3. **Respaldo propio**, con el `backup_db.py` de hoy (deja el archivo sin WAL). Bajarlo
   FUERA del volumen de Railway. Anotar su tamaño y su `md5`.
   - ⚠️ **No usar un respaldo nocturno viejo:** el del 16/08 (hecho con el `backup_db.py`
     de entonces) se ensayó y **el guardián lo frena** («modo WAL y NO está su `-wal`»).
     Es el bloqueante de `MIGRACION_POSTGRES.md`, reproducido tal cual. El de hoy pasa.
   - Si en vez del respaldo se baja el archivo vivo: SIEMPRE con su `-wal`, y con la app ya
     frenada correr antes `PRAGMA wal_checkpoint(TRUNCATE)`.
4. `copiar_a_postgres.py aplicar-esquema` → `preflight`. **Si el preflight no está limpio,
   no se sigue.**
5. `copiar_a_postgres.py copiar`. Copia, adelanta las secuencias y verifica sola, en una
   conexión nueva, los cuatro niveles. **Tiene que terminar en «✅ los cuatro niveles en
   CERO hallazgos». Un hallazgo = no se sigue** (y se reintenta con `preparar-destino`).
6. **Cerrar la puerta de Supabase** (lo hace Nico, `MIGRACION_POSTGRES.md` 9-bis): Data API
   apagada, RLS en todas las tablas, Spend Cap ON, Security Advisor en 0.
7. En Railway: poner `DATABASE_URL`, **sacar `RENDI_MANTENIMIENTO`** (con `DATABASE_URL`
   puesta y sin `RENDI_PASAJE_COMPLETO`, la app arranca CERRADA sola) y reiniciar.
   - Es normal que el primer arranque diga «se aplican 797 sentencias (la base no tiene
     huella)»: el copiador no deja la huella (§4.3). Los siguientes dicen «al día».
8. **Chequear con la app cerrada**, entrando con la cabecera `x-rendi-bypass: <token>`:
   - el motor es Postgres (primero de todo: `/api/health` no toca la base);
   - los logs del arranque: las reparaciones tienen que decir **0** en todo (en el ensayo,
     las cuatro líneas — cajas USDT, cajas vacías, tokens de reseteo, tokens de asesor —
     dieron 0, igual que un segundo arranque en SQLite);
   - sin la cabecera, cualquier pantalla tiene que dar **503** (en el ensayo, dio 503);
   - las mismas pantallas de unas 20 cuentas contra lo que mostraba SQLite (los scripts
     del ensayo: `pedir_pantallas.py` + `comparar_pantallas.py`, ver §3);
   - lo de `MIGRACION_POSTGRES.md` §3 (cuenta de prueba, un import de punta a punta,
     conexiones abiertas).
9. **Abrir:** `RENDI_PASAJE_COMPLETO=1` y reiniciar.
10. Prender los crons externos, de a uno, mirando los logs.

### Cómo se vuelve atrás

- **Antes del paso 9 (app cerrada): gratis.** Sacar `DATABASE_URL` (y
  `RENDI_PASAJE_COMPLETO` si estuviera), poner `RENDI_MANTENIMIENTO=1`, reiniciar: la app
  vuelve a la SQLite, que el copiador sólo LEYÓ. Cuando esté verificada, sacar
  `RENDI_MANTENIMIENTO` para abrir sobre SQLite.
- **Después del paso 9: no se vuelve atrás.** Cada escritura de un usuario queda sólo en
  Postgres; volver es perderlas. Se arregla para adelante.

## 3 · Lo que mostró la comparación por la app (20 cuentas, 264 pantallas)

Muestra: 6 con mucha historia, 4 con cripto, 4 con bonos, 2 asesores, 1 cliente de
asesor, 3 al azar. Pantallas: Cartera (`/api/positions`), fotos (`/api/snapshots`),
mensual (`/api/monthly`), movimientos (`/api/operations`), brokers, objetivo (`/goals/cagr`),
rendimiento, cupones salteados, informes (años, línea de tiempo, julio 2026, año 2025 y
2026) y, para los asesores, su cartera de clientes y su libro.

| qué | resultado |
|---|---|
| estados HTTP | **idénticos**: 228 × 200 y 36 × 403 en los dos (los 403 son informes que el plan de la cuenta no incluye) |
| Cartera, fotos | **idénticas en las 20 cuentas** |
| mensual | **idéntico** por broker y mes en las 20 (2.238 filas). Sólo difiere el `id` de 184 filas que la pantalla CREA al completar los meses hasta hoy |
| movimientos | **las mismas filas con los mismos valores, en otro orden** en 17 de 20 cuentas: los empates de fecha (§4.2) |
| cupones salteados | mismas filas, otro orden, en 1 cuenta |
| valor del informe «al día de hoy» | difiere hasta 5,3 × 10⁻⁵ en 5 cuentas, **pero dos corridas del MISMO motor difieren más** (hasta 2,4 × 10⁻⁴, también sobre copias frescas): depende del reloj, no del motor |
| redondeo de punto flotante | 19 valores, ≤ 4 × 10⁻¹⁰ |

## 4 · Lo que el ensayo encontró

### 4.1 🔴 ARREGLADO — Postgres reusaba ids de filas borradas
SQLite (`AUTOINCREMENT`) sigue numerando desde el mayor id que EXISTIÓ
(`sqlite_sequence`); el copiador adelantaba cada secuencia sólo hasta el mayor que
EXISTE. En la copia del 16/08: **394 ids reusables en 4 tablas** (fotos 149, eventos 142,
tokens de reseteo 64 —con la tabla vacía, volvían a 1—, noticias 39). Importa porque
`medicion_original.snapshot_id` decide «este original es de esta foto» por el id. En las
tablas de la plata (operaciones, posiciones, mensual) no había ninguno.
- `verificar_copia.secuencias_que_reusarian`: el nivel 3 lo ve ahora (dio rojo en las 4
  tablas sobre la copia hecha antes del arreglo).
- `copiar_a_postgres.correr_setval(destino, origen)`: adelanta hasta `sqlite_sequence`.
  Copia nueva: **0 hallazgos, 0 tablas que reusarían**. Prueba nueva en
  `test_copiar_a_postgres.py` (roja con el copiador viejo).

### 4.2 ⚠️ ABIERTO — 35 consultas ordenan sólo por fecha
Sin desempate (`ORDER BY date` sin `, id`), los empates salen en el orden de carga en
SQLite y en uno no garantizado en Postgres (que además puede cambiar con el tiempo).
Medido: cambia el orden visible de los movimientos del mismo día. **No medido:** si
alguna de las 35 decide un número (hay candidatas: `_ultimo_total_de_foto`,
`_recompute_snapshots_netdep_for_user`, `_repair_interes_pf`). La reconstrucción FIFO ya
desempata bien (`fecha, tipo, id`). Lista completa en la nota de la sesión.

### 4.3 Menor — el copiador no deja la huella del esquema
`aplicar-esquema` crea las tablas pero no escribe la huella que usa el arranque, así que
el primer arranque vuelve a correr las 797 sentencias. Con la app cerrada no molesta
(1,3 s en local); queda anotado para que nadie se asuste al leerlo en los logs.

### 4.4 Menor — un test de la verificación llevaba meses viejo sin que nadie lo viera
`test_verificar_copia.py` exigía 60 tablas (hoy son 78). Se saltea sin `PG_DSN_VERIF`, y
la suite no la pone. Corregido el número (los tipos, que es lo que protege, siguen siendo
3). **Propuesta:** que la corrida de **SQLite** de la suite ponga `PG_DSN_VERIF` apuntando a
una base Postgres aparte. En la de Postgres no se puede: con `DATABASE_URL` puesta, la
guarda del copiador («`copiar` escribe y hay una `DATABASE_URL`») frena sus 8 pruebas a
propósito. Medido: modo SQLite + `PG_DSN_VERIF`, los 6 archivos de copia/verificación,
96 pasan / 0 fallan.

### 4.5 Las reparaciones del arranque
Con el código de hoy sobre los datos del 16/08 en SQLite, el primer arranque: 13
bienvenidas previas marcadas (sin mandar nada), 7 notas de compras por chat renombradas,
35 cajas «USDT» → «USD», 9 cajas vacías limpiadas, 0 tokens. El segundo arranque en
SQLite y el primero en Postgres: **0 en todo**. Hacen lo mismo en los dos motores.
