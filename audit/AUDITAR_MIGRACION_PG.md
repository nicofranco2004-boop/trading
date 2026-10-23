# Auditar: los arreglos de migración a Postgres (23/10/2026)

**Rama:** `claude/migracion-pg-oct` · **Copia:** `.claude/worktrees/verif-pg`
**NO PUBLICAR.** Nada de push a `origin/main` — la decisión es de Nico.

---

## Qué hay que auditar, y con qué actitud

10 commits. Los 5 primeros son conversiones mecánicas (SQLite-ismos → Postgres)
y son de bajo riesgo. **Los que importan son los últimos tres**, porque tocan
caminos que mueven plata y porque los arreglos son de concurrencia, que es donde
un razonamiento correcto puede dar un resultado falso.

La consigna NO es confirmar que están bien: es **intentar romperlos**.

### A · El día de la cuota sale de Python, no del SQL (`c4f552d2`)

Seis `UPDATE` de cobros escribían `quota_window_from = date('now','localtime')`.
El shim rechaza ese modificador y, como el `tier = ?` viaja en la MISMA
sentencia, al rechazarla **el usuario no cambiaba de plan**.

Verificar:
- Que los 6 sitios pasen el día como dato y que el orden de los parámetros
  quedó bien en cada uno (una consulta que pide N y recibe N−1 revienta; una
  que recibe N en otro orden escribe valores cruzados **sin error**).
- Que `quota.dia_de_la_cuota()` devuelva LO MISMO que devolvía antes
  (día UTC). **No tiene que ser el día argentino**: mover el bloque de cuota es
  una decisión de producto pendiente (los ~19 sitios van juntos).
- Que `note_tier_change` siga haciendo lo mismo.

### B · Los topes que SQLite hacía cumplir gratis (`76816f3c`)

Tres topes se hacen cumplir contando y escribiendo en una sola sentencia. Eso
funciona en SQLite **porque el motor deja escribir a uno por vez**, no por la
sentencia. Medido contra Postgres real:

| tope | aguanta | medido |
|---|---|---|
| cuota de IA | SÍ | se salva por chocar en la fila del usuario |
| pruebas gratis del mes | NO | entraban 10 con tope 5 |
| datos que la IA recuerda | NO | 57 con tope 50 |

Arreglo: `pgsesion.turno_exclusivo` (`pg_advisory_xact_lock`).

Verificar:
- **¿La cuota de IA realmente aguanta?** Lo medí con DOS pedidos. Probar con
  más, y con pedidos de USUARIOS DISTINTOS a la vez.
- ¿El turno se pide SIEMPRE antes de contar, en todos los caminos que llegan al
  tope? (buscar otros llamadores).
- ¿Puede el turno causar una espera larga o un bloqueo mutuo bajo carga?
- ¿Hay OTROS topes con el mismo patrón que no encontré? Buscar
  `WHERE (SELECT COUNT` y `ON CONFLICT … WHERE`.

### C · La fila del mes y la caja de efectivo (`d4742484`)

1. `_update_monthly_flow`: leía «¿existe la fila?» y después insertaba. Dos
   depósitos simultáneos la creaban los dos → 500 al usuario. Ahora el INSERT
   lleva `ON CONFLICT DO UPDATE` que SUMA.
   **Verificar que suma EXACTAMENTE lo mismo que la rama de «ya existe»**, que
   `capital_inicio` no se pise y que los `pnl_*` tampoco.

2. `efectivo.tomar_saldo`: tomaba el candado con un UPDATE que no cambia nada.
   En SQLite un UPDATE de 0 filas igual toma la base; **en Postgres no hay fila
   que trabar y no toma nada** → dos primeros depósitos creaban DOS cajas, y
   como todo lee «la más vieja», la plata de la segunda quedaba invisible.
   Ahora, si el UPDATE no tocó ninguna fila, se pide turno por usuario.
   **Verificar que no quedó ningún otro camino que cree la caja sin pasar por
   `tomar_saldo`.**

---

## Cómo correr las dos bases

```bash
cd .claude/worktrees/verif-pg/backend
python3 -m pytest tests -q -p no:randomly              # SQLite
```

Postgres: el paquete `pgserver` (ya instalado) levanta uno real, sin docker.

```python
import pgserver, pathlib
srv = pgserver.get_server("<carpeta>/pgdata")     # dejar el proceso VIVO
print(srv.get_uri())    # ojo: el host viene como parámetro, no en la URL
```

Después, con `DATABASE_URL=<uri con dbname propio>`:
`python3 -m pytest tests -q -p no:randomly --timeout=90`

⚠️ **Una medición sólo vale si los errores son VARIADOS.** Si las N fallas
dicen todas lo mismo, lo más probable es que el instrumento esté mal (me pasó:
283 "fallas" eran una dirección de conexión mal armada).

---

## Lo que NO hay que arreglar acá

- **El horario de la cuota** (día UTC vs día argentino): decisión de producto
  pendiente, ~19 sitios que se mueven juntos o ninguno.
- **La columna de orden en `import_batches`**: la tabla no sabe cuál se creó
  primero. Tres tests dependían de eso. Es un cambio de esquema.
- **`VenderDolaresMientrasSeCompran`**: dos conversiones a la vez dan
  `deadlock detected`. Diagnosticado, SIN arreglar.
- El patrón «borrar e ignorar el error» está en **118 archivos de test**; sólo
  se arreglaron los 5 que fallaban.

## Estado medido al cerrar

SQLite **6.993 / 0 fallas, 0 bloqueos** · Postgres **17 fallas** (desde 656).
