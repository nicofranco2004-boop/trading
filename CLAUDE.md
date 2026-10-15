# Cómo se trabaja en este repo

> Alcance: todo el repo. El frontend además tiene su propio contrato visual en
> [`frontend/CLAUDE.md`](frontend/CLAUDE.md) — este documento no lo reemplaza.
>
> ⚠️ **Las reglas de abajo están también en `~/.claude/CLAUDE.md`**, el archivo global que
> lee toda sesión. Están duplicadas a propósito: este archivo sólo lo ven las copias del proyecto
> que lo tienen —al 2026-09-08, **6 de 33 worktrees**, porque las demás salieron de ramas
> anteriores a que se commiteara—, y las reglas tienen que llegar a todas. La copia de acá es la
> que queda versionada en git y la que lleva la evidencia de este repo.
> **Si cambiás una versión, cambiá la otra.**

---

## REGLA PERMANENTE — arreglar el proceso, no el síntoma

Cuando encuentres un error, **no lo parches donde aparece**. El lugar donde el número se ve mal
casi nunca es el lugar donde se rompió.

Antes de escribir el fix:

1. **Seguí el dato hacia atrás** hasta el punto donde se generó mal: de la pantalla al endpoint,
   del endpoint al motor de cálculo, del motor al importador o al persister. Decime en qué
   eslabón está la causa real y por qué los eslabones anteriores estaban bien.
2. **Preguntá qué más pasa por ese eslabón.** Si el dato roto lo escribe un motor que corre para
   todas las cuentas, el fix es en el motor, no en la fila que miraste.
3. **Verificá que tu fix sobreviva el pipeline completo.** Un fix aplicado en un paso al que
   después lo pisa un recálculo, un rebuild o un backfill **no está aplicado**: buscá los
   escritores POSTERIORES antes de darlo por bueno.
4. **El test tiene que atravesar el mismo camino que producción.** Un test que llama al persister
   directo, saltándose el recálculo, certifica en verde exactamente lo contrario de lo que pasa
   en prod.

Un fix que hace desaparecer el síntoma sin explicar el mecanismo no es un fix: es el mismo bug
esperando a salir por otra pantalla.

---

## REGLA PERMANENTE — propagación de fixes

La causa raíz más frecuente de este proyecto (28+ hallazgos auditados) es: un fix correcto
que se aplicó en un solo lugar y no se propagó al resto de los call sites.

Por eso, cada vez que arregles algo:

1. Antes de dar el fix por terminado, buscá con grep TODOS los lugares donde vive el mismo
   cálculo, la misma llamada o el mismo patrón. Listámelos.
2. Decime explícitamente cuáles arreglaste y cuáles no, y por qué.
3. Si el mismo cálculo existe en más de un lugar, la respuesta por defecto no es arreglar
   los dos: es unificarlos en uno solo.
4. Un fix que arregla 1 de N call sites no está terminado. Está a medias, y a medias es
   como se generó toda la deuda que estamos limpiando.

---

## REGLA PERMANENTE — tu copia del código se borra cuando publicás

Cada sesión trabaja en su propia copia del repo (un *worktree*) para no pisarse con las otras.
Eso está bien. Lo que no está bien es dejarla: el 2026-10-09 había **74 copias** en cuatro
lugares distintos, 71 sin nadie adentro, y la carpeta principal llevaba **un mes atrasada** sin
que nadie lo notara — toda sesión que se abría ahí leía el código de septiembre.

1. **Sacá tu copia adentro de `.claude/worktrees/`** (la app ya lo hace sola; a mano:
   `git worktree add -b <rama> .claude/worktrees/<nombre> origin/main`). No en `~/rendi-worktrees`
   ni en la raíz del repo: así se juntaron 62 de las 74.
2. **Cuando lo tuyo está en origin/main, borrá tu copia** (`git worktree remove <ruta>`). Si
   quedó algo sin guardar, guardalo o decí que es descartable antes de borrar.
3. **La carpeta principal (`~/Documents/trading`) vive en `main` y al día con origin/main.**
   No se le acumulan cambios sin guardar encima.
4. **Si encontrás copias abandonadas:** `scripts/limpiar-copias.sh` muestra cuáles se pueden
   borrar y con `--borrar` lo hace. Nunca toca una copia en uso o con trabajo sin publicar, y lo
   local que valga la pena (bases de prueba, capturas) lo mueve a `~/Documents/rendi-archivo/`.
