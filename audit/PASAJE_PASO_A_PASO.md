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
| `copiar` contra Supabase | **625 s** (medido 04/11/2026 desde la Mac, respaldo de esa noche: 1,2 GB, 4.856.199 filas) | la copia en sí 295,5 s; el resto es la verificación. **0 hallazgos.** `aplicar-esquema` 217 s, `preflight` 24 s. Se hizo en un esquema aparte (`ensayo_copia`) y se borró al terminar |
| primer arranque de la app en Postgres | 1,3 s | aplica las 797 sentencias de esquema (ver §4.3) |
| arranques siguientes | 1,1 s | «esquema al día, 0 cambios» |
| 13 pantallas × 20 cuentas | ~80 s por motor | 264 pedidos, sin red |

**Ventana total en la Mac, de «mantenimiento prendido» a «verificado»: ~2 minutos** sin
contar las dos idas por la red. **Con la red, medido el 04/11/2026: ~15 minutos** (esquema 3,6 min
+ preflight 0,4 + copia y verificación 10,4) para los pasos 4 y 5. Con bajar el respaldo, las
comparaciones y los pasos de Railway, el día entero cabe en **1 a 2 horas**.

## 2 · El día, en orden

> 🆕 **03/11/2026 — se reescribieron los pasos 0, 2b, 3 y 8** (y se sumó el aviso antes del 9) para
> resolver los hallazgos **P2, P3 y A2** de `AUDITORIA_FINAL_PG.md`. Los pasos 1, 2, 4-7 y 9-10
> quedan como estaban.
> **Estado del script:** `scripts/pasaje_con_mantenimiento.py` **ya está en el repo**, con sus
> pruebas (`backend/tests/test_pasaje_con_mantenimiento.py`): corren contra la app de verdad
> (uvicorn local, el mismo middleware de mantenimiento, el login y el disparador del respaldo
> reales), en SQLite y en Postgres. ⚠️ **Lo que no se pudo probar:** contra la app de
> producción, y bajar el archivo con los clics de Cloudflare R2. Por eso el paso B.
> **La dirección de la app no está escrita en el código:** se pasa con `--url` (paso A0).

**Quién hace qué.** En cada paso dice **🧑 Nico** (lo hacés vos, con clics) o **🤖 central** (la
sesión central, desde una terminal). Nunca hay un paso que no tenga dueño.

**Qué nunca pasa por el chat:** la llave del mantenimiento, la contraseña de tu cuenta, la
dirección de Supabase. Viven en archivos de tu Mac (permiso sólo para tu usuario, fuera del
repo) o se escriben en una pantalla que no muestra lo que tipeás. Si alguna vez pegás una en el
chat por error, **avisá en el momento**: la llave se cambia en Railway (Variables → editar) y se
vuelve a guardar con el paso A de abajo.

### Antes del día (no el mismo día)

- [ ] Medir los dos tramos [A MEDIR] de arriba.
- [ ] Confirmar en Railway que `SECRET_KEY` está puesta (si no, el reinicio desloguea a todos).
- [ ] **La dirección de la app confirmada** (paso A0, abajo) y **la llave del mantenimiento guardada en tu Mac** (paso A).
- [ ] **Leer el aviso ⚠ del volumen `trading-volume`** (Railway → `trading` → pestaña Volumes /
      el volumen). Si el disco está casi lleno, el respaldo del paso 3 falla justo en el peor
      momento (`HANDOFF` §12, punto 5: sigue sin leerse). Si dice que está por llenarse: avisá
      a la central antes de fijar la fecha.
- [ ] **Ensayo del respaldo y de la bajada, con el de la noche** (paso B, abajo): lo que no se
      probó es justo cómo bajar el archivo. Mejor enterarse un martes que el domingo del pasaje.
- [ ] **Elegir la fecha y la hora** (paso 0, abajo).
- [ ] Las decisiones de Nico pendientes del traspaso §11.

#### Paso A0 — 🧑 Nico: confirmar la dirección de la app (2 minutos, días antes)

El script habla con la app por su dirección de Railway (no por `rendi.finance`: el respaldo
tarda minutos y la pasarela de Vercel que está delante corta los pedidos largos). **No es
secreta**, y no está escrita en el código a propósito: la confirmás vos.

1. Railway → proyecto `resplendent-stillness` → servicio `trading` → **Settings** → **Domains**.

   | si ves | qué hacer |
   |---|---|
   | una dirección que termina en `.up.railway.app` | copiala y pasásela a la central en el chat (no es secreta). La central la usa como `--url` |
   | varias | la que termina en `.up.railway.app` |
   | ninguna | pará y avisá a la central |

2. La central comprueba que contesta (`<dirección>/api/health` tiene que dar `ok: true` y
   `motor: sqlite`). Si no contesta, la dirección está mal: repetí el 1.

#### Paso A — 🧑 Nico: guardar la llave del mantenimiento en tu Mac (5 minutos, días antes)

**Qué es la llave:** la variable `RENDI_MANTENIMIENTO_TOKEN` de Railway. Con la app cerrada, la
app le contesta «503, estamos mudando la base» a todo el mundo, **menos a quien manda esa llave
en una cabecera** (un dato extra que viaja con el pedido, que el navegador común no manda).
Es como el cordón de seguridad de una obra: todos ven la valla; el capataz pasa con su credencial.
Sin llave guardada no hay forma de mirar nada con la app cerrada.

1. Railway → proyecto `resplendent-stillness` → servicio `trading` → pestaña **Variables**.
   Buscá `RENDI_MANTENIMIENTO_TOKEN` (podés usar el buscador de la pestaña).

   | si ves | seguí en |
   |---|---|
   | la variable existe | **A1** |
   | no existe | **A2** |

2. **A1 — ya existe.** Abrí la Terminal (la pestaña Terminal de esta app, o la app Terminal de la
   Mac), andá a la carpeta del proyecto y corré:

   ```bash
   cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py llave
   ```

   Te va a pedir «Pegá la llave que está en Railway». Pasá a Railway, hacé clic en el **ícono del
   ojo** de esa variable (muestra el valor), seleccioná todo el valor y copialo (Cmd+C); volvé a la
   Terminal, pegá (Cmd+V) y apretá Enter. **Al pegar no aparece nada: es normal**, igual que
   cuando escribís una contraseña. Después tapá el ojo de nuevo.

   | si la Terminal dice | qué hacer |
   |---|---|
   | `✅ Guardada en /Users/…/.rendi-mantenimiento-llave` | listo, seguí al paso B |
   | `✋ Vacía. No se guardó nada.` | no pegaste nada: repetí el comando |
   | cualquier otra cosa | pará y avisá a la central (sin pegar el valor de la llave) |

3. **A2 — no existe.** Corré:

   ```bash
   cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py llave --nueva
   ```

   Inventa una llave larga al azar, la guarda en tu Mac y **la deja copiada** (sin mostrarla).
   Después: Railway → `trading` → **Variables** → botón **New Variable** → en *Name* escribí
   `RENDI_MANTENIMIENTO_TOKEN`, en *Value* pegá (Cmd+V) → **Add**. Railway deja el cambio «en
   espera» y muestra un botón **Deploy**: apretalo. **Es normal que la app se reinicie** (un
   corte de unos segundos). No tiene ningún efecto sobre los usuarios mientras la app está abierta.

   | si la Terminal dice | qué hacer |
   |---|---|
   | `✅ Llave nueva inventada, guardada y COPIADA` | pegala en Railway como dice arriba |
   | un error de `pbcopy` | pará y avisá a la central |

**Cómo se sabe que la llave sirve:** recién se prueba en el paso 2b del día (con la app cerrada,
no hay otra forma). Si ahí da `503`, el motivo casi seguro es que la llave del archivo no es la
de Railway: se repite el paso A1.

#### Paso B — 🧑 Nico + 🤖 central: ensayo de bajar un respaldo (15 minutos, días antes)

Es el mismo recorrido del paso 3 del día, pero con el respaldo que la app ya hace **todas las
noches** (así no hace falta cerrar nada). Sirve para probar los clics de Cloudflare y que el
archivo baje entero.

1. 🧑 Entrá a dash.cloudflare.com → menú de la izquierda → **R2 Object Storage** → el depósito
   **`rendi-backups`** → pestaña **Objects** → carpeta **`rendi/`**.
2. 🧑 Vas a ver archivos con nombre `trading-AAAA-MM-DD.db.gz`, uno por noche (al bajarlo, Cloudflare
   le agrega la carpeta adelante: queda `rendi_trading-AAAA-MM-DD.db.gz`; ensayado el 04/11/2026,
   237 MB, entero). Hacé clic en el
   más nuevo: se abre un panel con sus datos. Buscá el botón **Download** y apretalo.

   | si ves | qué hacer |
   |---|---|
   | el archivo se baja a `Descargas` (≈ 200 MB; al 31/10 pesaba 198,7 MB) | seguí al 3 |
   | no hay botón **Download**, o el navegador lo corta a la mitad | **pará y avisá a la central**: hace falta otro camino para bajarlo (no se pudo probar) |
   | la carpeta `rendi/` está vacía o el último archivo tiene más de 2 días | pará y avisá: el respaldo de afuera no está andando |

3. 🤖 La central comprueba el archivo bajado (no hace falta que hagas nada):

   ```bash
   ls -l ~/Downloads/trading-*.db.gz && gzip -t ~/Downloads/trading-AAAA-MM-DD.db.gz && echo "ARCHIVO ENTERO" && md5 ~/Downloads/trading-AAAA-MM-DD.db.gz
   ```

   (`gzip -t` prueba que el archivo comprimido no esté cortado; sólo imprime «ARCHIVO ENTERO» si
   está bien.) Si no imprime eso, el paso del día no se puede hacer así: avisar.

---

**El día** (un **domingo** temprano: mercados cerrados, sin brief del asesor):

### 0. Elegir la ventana — **antes** de fijar la fecha (hallazgo A2)

Los trabajos internos de la app **no los frena el modo mantenimiento** (sólo cierra la puerta
web). Si la ventana cae en alguno, salen mails o fotos desde una base que todavía se está
verificando; y si después se vuelve atrás, salen otra vez desde la vieja.

| qué corre solo | hora de Argentina | hora UTC | ¿molesta? |
|---|---|---|---|
| foto diaria de las carteras | 23:59 | 02:59 | **sí** (escribe fotos de todos) |
| bajas de plan y mails de ciclo de vida | 00:30 | 03:30 | **sí** (manda mails) |
| respaldo nocturno | 00:45 | 03:45 | **sí** (compite con el tuyo) |
| avisos de la tarde (mails) | 12:00 | 15:00 | **sí** (manda mails) |
| actualización de precios de fondos comunes | ≈ 09:10 | 12:10 | **no**: sólo guarda precios, no manda nada y no toca datos de personas (se mira el 03/11 en `main.py`, `_start_scheduler`) |
| renovar el acceso de la cuenta de laboratorio de IOL | cada hora, minuto 07 | cada hora, minuto 07 | no (0 a 3 cuentas; ver «Lo que no se midió» de la auditoría) |

**Regla:** todo el pasaje, de la primera tilde a «abierto» (o a «volví atrás»), tiene que caer
**fuera de 23:45–01:00 y de 11:55–12:10 (hora de Argentina)**. La auditoría sugiere un
**domingo entre las 8 y las 10**: arrancando a las 8:00, hay casi cuatro horas hasta el aviso de
las 12:00. **Si a las 11:30 todavía no abriste, no apures el paso 9: volvé atrás** (es gratis
antes del 9, ver «Cómo se vuelve atrás») y elegí otro domingo.

### 1. Apagar los crons externos

**Apagar los crons externos** — los TRES tokens (`MIGRACION_POSTGRES.md` §4). Primero,
porque los mails a asesores y de cobros no se pueden desmandar.

### 2. Mantenimiento ON sobre SQLite

`RENDI_MANTENIMIENTO=1` y reiniciar. Desde acá nadie escribe. *(No poner nunca
`RENDI_MANTENIMIENTO=0`: ver la memoria.)*

### 2b. 🧑 Nico + 🤖 central: la «foto de antes» de las pantallas

**Por qué acá, y no después:** es lo único que permite comparar pantallas *de verdad*. Se
guarda lo que muestra la app **hoy, sobre SQLite, con nadie escribiendo**; en el paso 8 se pide
lo mismo sobre Postgres y se comparan. Tiene que ir **antes del respaldo** (paso 3): la
pantalla «Mensual» crea las filas de los meses que falten, y así esas filas quedan dentro de
lo que se copia.

1. 🤖 La central abre la pestaña Terminal y corre (una vez por cuenta; recomendado 2 o 3 cuentas
   con mucha historia: la tuya y alguna de prueba):

   ```bash
   cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py pantallas antes --url https://LA-DIRECCION-DEL-PASO-A0
   ```

2. 🧑 Nico: en esa pestaña te pide **«Mail de la cuenta»** (tipealo) y **«Contraseña»** (tipeala:
   **no se ve nada mientras escribís, es normal**; no la pegues en ningún chat). Te puede
   llegar un mail de «nuevo ingreso» de Rendi: es el que genera este mismo login, es normal.

   | si la Terminal dice | qué hacer |
   |---|---|
   | tres líneas `estado 200` y `✅ Guardado en …/rendi-pasaje/pantallas-antes-….json` | listo; repetí con la próxima cuenta, o seguí al 3 |
   | `✋ 503: la app no te dejó pasar…` | la llave del archivo no es la de Railway (o falta la variable): **pará**, repetí el paso A1 y volvé a intentar. Si sigue, avisá |
   | `✋ La app contestó 401 al entrar` | mail o contraseña mal escritos: repetí (ojo: son 10 intentos por minuto) |
   | un estado que no es 200 en alguna pantalla | pará y avisá a la central |

### 3. Respaldo propio, con la app cerrada (hallazgo P2)

**Lo que pasaba:** con el mantenimiento prendido, el único botón que hace el respaldo
(`POST /api/admin/backup-trigger`, el «Backup ahora» del panel admin) da `503` desde el
navegador. Y **además** exige estar entrado con una cuenta de administrador. O sea que hacen
falta **dos** cosas: la llave (cabecera) y la contraseña de admin. Por eso se hace con el
script (`scripts/pasaje_con_mantenimiento.py`, ver el Anexo A), que trae las dos sin mostrarlas.

**Qué hace el respaldo:** copia la base entera (con la copia «en caliente» de SQLite, que
sale sin el archivo auxiliar `-wal` que frena al copiador), la comprime, la deja en el disco de
Railway **y la sube a Cloudflare R2**, depósito `rendi-backups`, como
**`rendi/trading-AAAA-MM-DD.db.gz`** (fecha en UTC; el domingo a las 8-10 es la misma fecha que
en Argentina). Si ya había uno de esa fecha —el de la noche— **lo pisa**: es lo esperado, y es
justo lo que querés (el nuevo es más reciente).

**3a. 🤖 central dispara el respaldo, 🧑 Nico tipea la contraseña de admin.**

```bash
cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py respaldo --url https://LA-DIRECCION-DEL-PASO-A0
```

Nico: en la Terminal, **«Mail de la cuenta»** = el de tu cuenta de **administrador** (la que
entra al panel admin) y **«Contraseña»** (no se ve). Tarda de 1 a 3 minutos; **no cierres la
pestaña**. Al final imprime un cuadro. Anotá **el tamaño en bytes, los usuarios y las
operaciones** (la central los guarda también).

| si el cuadro termina en | qué significa | qué hacer |
|---|---|---|
| `✅ Respaldo hecho y subido a Cloudflare R2` con `motor: sqlite` y `errores: ninguno` | está bien | seguí al 3b |
| `✋ Esa cuenta no es de administrador` | entraste con otra cuenta | repetí con la de admin |
| `✋ 503: la app no te dejó pasar` | la llave no es la de Railway | **pará**; paso A1 |
| `🛑 El respaldo dice que es de Postgres` | la app ya tiene `DATABASE_URL`: se adelantó un paso | **pará y avisá**: no sigas |
| `🛑 El respaldo NO está bien` (con `errores:` o `subido afuera: NO`) | no hay respaldo confiable | **pará, no sigas al paso 4.** Pegá a la central lo que dice el cuadro. Causas probables: disco del volumen lleno (ver «Antes del día»), o las llaves de R2 vencidas |
| se corta sin cuadro / `❌ No pude hablar con…` | no llegó a Railway | esperá 1 minuto y repetí **una** vez; si sigue, avisá |

**3b. 🧑 Nico baja el archivo desde Cloudflare R2 (fuera del volumen de Railway).**

1. dash.cloudflare.com → **R2 Object Storage** → **`rendi-backups`** → pestaña **Objects** →
   carpeta **`rendi/`**.
2. Buscá `trading-AAAA-MM-DD.db.gz` con **la fecha de hoy** (UTC). Hacé clic en ese archivo: en
   el panel que se abre mirá **Last modified**.

   | si ves | qué hacer |
   |---|---|
   | fecha de hoy **y una hora posterior a cuando disparaste el respaldo** (pasá de hora UTC a Argentina: se le restan 3 horas) | es el nuevo: seguí |
   | fecha de hoy pero la hora es **de la noche** (anterior al respaldo) | es el de la noche, **no** el nuevo: **no lo bajes**; esperá 1 minuto, recargá la página; si sigue igual, avisá |
   | no hay archivo de hoy | **pará y avisá**: el respaldo no subió |

3. Apretá **Download**. El archivo queda en `Descargas`. **No lo muevas ni lo abras.**

   | si ves | qué hacer |
   |---|---|
   | termina de bajar | seguí al 3c |
   | no hay botón **Download** o se corta | **pará y avisá**: hace falta otro camino (es lo que el paso B del «antes del día» debía detectar) |

**3c. 🤖 central comprueba el archivo y 🧑 Nico anota los números.** La central corre:

```bash
stat -f%z ~/Downloads/trading-AAAA-MM-DD.db.gz && gzip -t ~/Downloads/trading-AAAA-MM-DD.db.gz && echo "ARCHIVO ENTERO" && md5 ~/Downloads/trading-AAAA-MM-DD.db.gz
```

Y le muestra a Nico tres cosas, que él anota (en papel o en un mensaje a sí mismo; **no hace
falta pegarlas en un chat**):

| número | de dónde sale | **«bien» es** |
|---|---|---|
| **tamaño en bytes** | `stat` de arriba | **idéntico** al «tamaño (bytes)» que imprimió el cuadro del 3a. Si difiere, el archivo bajado no es el que subió la app: **pará** |
| **`ARCHIVO ENTERO`** | `gzip -t` | tiene que aparecer. Si no: archivo cortado, bajalo de nuevo (una vez) |
| **`md5`** (una huella de 32 letras y números del archivo: si cambia un solo byte, cambia toda) | `md5` | cualquiera, pero **anotado**: es la huella con la que la central vuelve a comprobar, en el paso 4, que el archivo del que se va a copiar sigue siendo exactamente este |

> Nota honesta: el `md5` **no se puede comparar con lo que muestra R2** (R2 sube los archivos
> grandes en partes y su «ETag» no es el md5 del archivo entero). Lo que prueba el tamaño y
> `gzip -t` es que llegó entero; lo que prueba el `md5` es que nadie lo tocó después.

Anotá además los **usuarios y operaciones** del cuadro del 3a: sirven en el paso 8c.

- ⚠️ **No usar un respaldo nocturno viejo:** el del 16/08 (hecho con el `backup_db.py`
  de entonces) se ensayó y **el guardián lo frena** («modo WAL y NO está su `-wal`»).
  Es el bloqueante de `MIGRACION_POSTGRES.md`, reproducido tal cual. El de hoy pasa.
- Si en vez del respaldo se baja el archivo vivo: SIEMPRE con su `-wal`, y con la app ya
  frenada correr antes `PRAGMA wal_checkpoint(TRUNCATE)`.

### 4. `copiar_a_postgres.py aplicar-esquema` → `preflight`

🤖 Antes de empezar: recalcular el `md5` del archivo y compararlo con el anotado en 3c.
**Si el preflight no está limpio, no se sigue.**

### 5. `copiar_a_postgres.py copiar`

Copia, adelanta las secuencias y verifica sola, en una conexión nueva, los cuatro niveles.
**Tiene que terminar en «✅ los cuatro niveles en CERO hallazgos». Un hallazgo = no se sigue**
(y se reintenta con `preparar-destino`). *(Esta es la comparación 1 del paso 8.)*

### 6. Cerrar la puerta de Supabase

Lo hace Nico, `MIGRACION_POSTGRES.md` 9-bis: Data API apagada, RLS en todas las tablas, Spend
Cap ON, Security Advisor en 0.

### 7. En Railway: poner `DATABASE_URL`, sacar `RENDI_MANTENIMIENTO`

Con `DATABASE_URL` puesta y sin `RENDI_PASAJE_COMPLETO`, la app arranca CERRADA sola; reiniciar.
- Es normal que el primer arranque diga «se aplican 797 sentencias (la base no tiene
  huella)»: el copiador no deja la huella (§4.3). Los siguientes dicen «al día».

### 8. Comparar, con la app cerrada (hallazgo P3)

**Por qué NO se repite lo del ensayo.** En el ensayo se compararon dos copias de la app **sin
internet**: las dos veían los mismos precios (ninguno), así que cualquier diferencia era de la
base. El día real, la app de Postgres **es producción**, con precios en vivo (acciones, cripto,
dólar). La pantalla **Cartera** vale «cantidad × precio de ahora»: va a dar distinto a la de
«antes» **aunque la copia sea perfecta**. Es como comparar el stock de dos depósitos mientras
un camión baja mercadería en uno: lo guardado coincide; lo que vale hoy en góndola, no. Mirar
Cartera acá no sirve, y es peor que no servir: si alguien ve diferencias «normales», se
acostumbra a ignorarlas el día que no lo sean. **Por eso la Cartera NO se compara.**

Tampoco se levanta una segunda copia de la app contra Supabase «sólo para comparar»: al arrancar
correría sus programadores internos (fotos, mails) contra la base nueva.

Se comparan **tres cosas**, en este orden. Para cada una: qué se mira, qué es «bien», y qué hacer.

#### 8a. Base contra base (ya la hizo el paso 5)

- **Qué se mira:** la última línea del `copiar`: «✅ los cuatro niveles en CERO hallazgos»
  (nivel 0: vaciar el andamio no tocó nada más; 1: fila por fila, exacto; 2: la plata de cada
  usuario sumada; 3: las secuencias). Sin precios, sin internet: compara el archivo bajado con
  Postgres.
- **«Bien» es:** esa línea, con **cero** en los cuatro niveles. **Sin tolerancia**, a propósito.
- **Si no da:** no se sigue, y no se abre. Un hallazgo = `preparar-destino` y repetir el `copiar`
  (paso 5). Si vuelve a dar, volver atrás (gratis antes del 9).

#### 8b. Pantallas, sólo lo que **no** depende del precio

Son las tres pantallas que muestran lo **guardado**: **Movimientos** (`/api/operations`),
**Resumen mensual** (`/api/monthly`) y **fotos guardadas** (`/api/snapshots`). Se compara la foto
de antes (paso 2b, SQLite) contra la misma pedida ahora (Postgres), **para las mismas cuentas**.

1. 🤖 La central corre, por cada cuenta que se guardó en el 2b, el mismo comando pero con
   `despues` (🧑 Nico tipea mail y contraseña, ocultos, como en el 2b). **Va con la app todavía
   cerrada y entrando con la llave**: el script ya la manda.

   ```bash
   cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py pantallas despues --url https://LA-DIRECCION-DEL-PASO-A0
   ```

2. 🤖 Y compara:

   ```bash
   cd ~/Documents/trading && python3 scripts/pasaje_con_mantenimiento.py comparar
   ```

- **Qué se mira:** por cuenta, tres renglones.
  - Movimientos: mismas filas, **en cualquier orden** (los empates de fecha salen en otro orden
    en Postgres: §4.2, conocido y sin efecto en los números).
  - Mensual: mismas filas por broker y mes; **no cuenta el `id`** (la pantalla crea filas
    nuevas al completar meses, ver 2b).
  - Fotos: mismas fechas y mismos valores.
- **«Bien» es:** `✅` en las tres de cada cuenta y la línea final **`✅ SIN DIFERENCIAS: seguí.`**
- **Si no da:**

  | si ves | qué significa | qué hacer |
  |---|---|---|
  | `✅ SIN DIFERENCIAS` | la copia dice lo mismo que lo que había | seguí al 8c |
  | `❌` con «filas que sólo están de un lado» o «N filas distintas» | falta o sobra algo en Postgres | **no abras.** Pasale la salida a la central: **no tiene montos**, se puede pegar |
  | `❌` con «campos distintos: {nombre: n}» en Mensual | hay un campo que cambió | **no abras.** La central decide si es un campo que depende del precio del día (esos son «normales» el día real) o un error: no lo decidas vos mirando |
  | `❌ estados 200 vs 503` o parecido | la llave no entró en el «despues» | repetí el «despues»; si sigue, avisá |

  *(Por qué el domingo ayuda: con los mercados cerrados casi nada se mueve, salvo cripto y
  algunos tipos de cambio. Cuantas menos diferencias «normales», más fácil es ver una anormal.)*

#### 8c. Quién tiene la llave, y los totales (sin pasar nada por el chat)

- **Quién tiene la llave:** **vos (Nico)**. Está en dos lugares: Railway (variable
  `RENDI_MANTENIMIENTO_TOKEN`) y el archivo `~/.rendi-mantenimiento-llave` de tu Mac, que se
  llenó en el paso A. La central **usa** el archivo (el script lo lee) pero **no ve el contenido**:
  en el chat no aparece nunca. Contraseñas de cuenta: las tipeás vos, ocultas, cada vez.
- **Los totales del respaldo contra Postgres.** 🤖 La central cuenta usuarios y operaciones en
  Postgres (con la conexión guardada en `~/.rendi-supabase-url`, que tampoco pasa por el chat) y
  los compara con los **usuarios y operaciones** del cuadro del 3a.

  | si da | qué hacer |
  |---|---|
  | **iguales** | seguí |
  | difieren en 1 o 2 (un alta o una operación que justo estaba en vuelo al prender el mantenimiento) | **no abras todavía**: la central mira cuáles son y decide |
  | difieren en más | **pará**: la copia no es la del respaldo. Volver atrás |

#### Lo que sigue valiendo de la lista de chequeos con la app cerrada

- el motor es Postgres (primero de todo): 🧑 abrí `<dirección del paso A0>/api/health` en el
  navegador (no toca la base y contesta aunque la app esté cerrada). Tiene que decir
  **`"motor":"postgres"`**. Si dice `"sqlite"`, la app todavía no tomó `DATABASE_URL`: **pará**.
  (Hallazgo A1 de la auditoría, ya en el código; en el paso 2 el mismo enlace tiene que decir
  `"sqlite"`.);
- los logs del arranque: las reparaciones tienen que decir **0** en todo (en el ensayo,
  las cuatro líneas — cajas USDT, cajas vacías, tokens de reseteo, tokens de asesor —
  dieron 0, igual que un segundo arranque en SQLite);
- **sin la cabecera, cualquier pantalla tiene que dar 503**: 🧑 entrá a `https://rendi.finance`
  desde el navegador común; tiene que decir «Estamos mudando la base de datos. Volvemos en
  unos minutos» (si se abre la app normal, **pará: el mantenimiento no está cerrado**);
- lo de `MIGRACION_POSTGRES.md` §3 (cuenta de prueba, un import de punta a punta,
  conexiones abiertas).

### 🛑 ANTES del paso 9 — leé esto

> **⚠️ DESPUÉS DE ABRIR (paso 9) NO HAY VUELTA ATRÁS SIN PERDER LO QUE LA GENTE CARGUE.**
> Desde que abrís, cada depósito, operación o alta de un usuario se guarda **sólo en Postgres**.
> Volver a SQLite es volver al estado de la mañana del pasaje: **todo lo cargado después se
> pierde**. Es lo único irreversible del día. Antes del 9, volver es gratis.

**Tilde por tilde, antes de apretar el 9** (cada uno lo marca la central y se lo lee a Nico):

- [ ] 5: «✅ los cuatro niveles en CERO hallazgos».
- [ ] 8b: «✅ SIN DIFERENCIAS: seguí.» en **todas** las cuentas guardadas.
- [ ] 8c: usuarios y operaciones de Postgres = los del respaldo.
- [ ] 8: sin la cabecera, `rendi.finance` muestra «Estamos mudando la base de datos».
- [ ] 8: los logs del arranque dicen 0 en las cuatro reparaciones.
- [ ] La hora de Argentina está **antes de las 11:30** (paso 0).
- [ ] 🧑 **Nico dice «sí, abrí»** en el chat. Sin ese sí explícito, no se aprieta.

Si falta cualquiera: **no se abre**. Se vuelve atrás (abajo) y se elige otro domingo.

### 9. Abrir

`RENDI_PASAJE_COMPLETO=1` y reiniciar.

### 10. Prender los crons externos

De a uno, mirando los logs.

🤖 Y al terminar el día: **borrar la carpeta `~/rendi-pasaje/`** (tiene las pantallas de las
cuentas de prueba, con montos reales): `rm -r ~/rendi-pasaje`. El archivo de la llave
(`~/.rendi-mantenimiento-llave`) se queda para el próximo mantenimiento.

### Cómo se vuelve atrás

- **Antes del paso 9 (app cerrada): gratis.** Sacar `DATABASE_URL` (y
  `RENDI_PASAJE_COMPLETO` si estuviera), poner `RENDI_MANTENIMIENTO=1`, reiniciar: la app
  vuelve a la SQLite, que el copiador sólo LEYÓ. Cuando esté verificada, sacar
  `RENDI_MANTENIMIENTO` para abrir sobre SQLite.
- **Después del paso 9: no se vuelve atrás.** Cada escritura de un usuario queda sólo en
  Postgres; volver es perderlas. Se arregla para adelante.


## 3 · Lo que mostró la comparación por la app (20 cuentas, 264 pantallas) — **del ensayo, no del día**

> Esto se hizo con dos copias de la app **sin internet**. El día real eso no se puede repetir
> (hay precios en vivo): lo que se compara el día es lo del paso 8 de §2. Esta sección queda
> como el patrón de qué diferencias son conocidas (el orden del mismo día, los `id` que crea
> la pantalla mensual).

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

## Anexo A · El script del día

`scripts/pasaje_con_mantenimiento.py` (ya está en el repo). Mismo patrón que
`scripts/conectar_supabase.py`: lo secreto vive en un archivo de la Mac con permiso `600` y
las contraseñas se piden sin mostrarlas. Sólo usa la biblioteca estándar de Python.

| comando | qué hace |
|---|---|
| `llave` | guarda la llave que ya está en Railway (la pide oculta) en `~/.rendi-mantenimiento-llave` |
| `llave --nueva` | inventa una llave, la guarda y la copia al portapapeles sin mostrarla |
| `respaldo --url …` | entra con tu cuenta de administrador y dispara el respaldo; imprime motor, tablas, usuarios, operaciones, tamaño y si subió a R2 |
| `pantallas antes --url …` / `pantallas despues --url …` | guarda Movimientos, Mensual y fotos de una cuenta en `~/rendi-pasaje/` |
| `comparar` | compara «antes» con «despues», cuenta por cuenta, sin imprimir montos |

**Lo que garantiza** (cada punto tiene su prueba en `backend/tests/test_pasaje_con_mantenimiento.py`):

- la llave, la contraseña y el token de sesión **no se imprimen nunca**, ni se pasan como
  argumento (no quedan en el historial de la Terminal);
- el archivo de la llave se rechaza si otra gente de la Mac lo puede leer;
- la dirección **no está en el código**: `--url` o la variable `RENDI_URL`; sin ella no hace nada;
  y tiene que ser `https` (la llave viaja en cada pedido), salvo `localhost` para las pruebas;
- el respaldo **no dice «hecho»** si el motor no es `sqlite`, si hubo errores o si no subió a R2.

**Cómo se probó:** contra la app de verdad levantada en un puerto local, con SQLite y con el
Postgres local de pruebas (el teclado y la subida a R2 son lo único reemplazado). Plantando a
propósito tres defectos (imprimir la contraseña, aceptar `http` remoto, no mirar el motor) las
pruebas fallan: muerden. **No probado:** contra producción.

**Para ensayar el paso 3a un día cualquiera:** `respaldo` contra la app abierta **funciona y es
inofensivo** (hace lo mismo que el botón «Backup ahora» del panel admin; sube el de hoy a R2). La
llave simplemente no se usa si no hay mantenimiento.
