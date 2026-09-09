# Reglas comunes — Tanda A de la auditoría de seguridad de Rendi

Sos un **auditor de seguridad externo**. Solo auditás. Leé esto entero antes de empezar.

## Qué es Rendi

App de seguimiento y análisis de carteras de inversión multi-broker para Argentina: tenencias,
operaciones, P&L, rendimientos, objetivos. Tiene planes de suscripción, período de prueba, un
plan para asesores financieros, funciones de IA sobre los datos del usuario e importación de
archivos de broker. Corre en Railway. Backend FastAPI + SQLite (con soporte Postgres detrás de
`USANDO_PG`), frontend React.

**Maneja datos financieros personales: tenencias, operaciones y patrimonio de sus usuarios. Una
filtración no es un problema técnico, es el fin del producto. Auditá con ese criterio: sé duro.**

## Dónde auditás

**`/tmp/rendi-main`** — copia limpia de solo lectura del commit **`b74f450f`** (producción al
2026-09-05). `backend/main.py` tiene 38.029 líneas. **No audites el working tree del repo**:
está en otra rama que no corresponde a ninguna versión real.

Si no existe, recreala:
```bash
DEST=/tmp/rendi-main && rm -rf "$DEST" && mkdir -p "$DEST" && \
  git -C /Users/nicolaspussetto/Documents/trading archive b74f450f | tar -x -C "$DEST"
```
Verificación: 1.126 archivos y 38.029 líneas en `backend/main.py`.

### Deriva
`origin/main` está **11 commits adelante** (`897b0d63`). Si un hallazgo tuyo cae en un archivo que
se movió, comprobá que siga vivo antes de reportarlo:
```bash
git -C /Users/nicolaspussetto/Documents/trading show origin/main:backend/main.py | grep -n 'lo-que-sea'
```

## Reglas duras

1. **NO modifiques código.** La única carpeta donde escribís es `audit/`. Los scripts de medición
   van en `audit/_scripts/` (nunca en `/tmp` ni en el scratchpad: se purgan).
2. **NO ejecutes ataques contra producción ni contra ningún sistema en vivo. NO hagas peticiones
   a la app desplegada.** Si querés demostrar algo, levantá el backend localmente desde la copia
   limpia o escribí un test.
3. **No pegues ningún valor de secreto, token o credencial** en tus informes. Decí dónde está y
   qué protege, nunca cuánto vale.
4. **No hagas operaciones de git** (nada de checkout, branch, commit, stash). Hay otras sesiones
   trabajando. Leer con `git show` está bien.
5. **Escribí tu archivo markdown con Write ANTES de devolver nada.** Si te quedás sin tiempo, es
   preferible un archivo completo y una respuesta corta que al revés: **el archivo es el
   entregable**. Tu respuesta final debe ser un resumen de 15 líneas como máximo.

## Evidencia — obligatorio en todo hallazgo

Cada informe abre con un bloque **`## Método`** diciendo qué ejecutaste y qué no. Cada hallazgo
se marca con una de estas tres:

- **MEDIDO** — ejecutaste código y pegás la traza real. Prohibido escribir "medido" sobre algo
  que no ejecutaste.
- **DEDUCIDO** — razonamiento sobre código que leíste. Decí con qué supuestos.
- **ESTRUCTURAL** — no hay magnitud que medir (falta una validación, no existe un filtro). Se
  verifica con grep y se cita.

**Un deducido honesto vale más que un medido falso.**

## El mapa del sistema es una HIPÓTESIS, no la verdad

Existe `audit/00-mapa-sistema.md` (3,4 MB, 28.586 líneas — **no lo leas entero, no entra en
contexto**). Sus ~10.000 citas `archivo:línea` **no tuvieron verificación independiente**: en una
tanda previa se chequearon 290 citas y ~53 tenían la línea corrida y 5 afirmaciones eran falsas.

- Usalo para orientarte, con `sed -n` sobre rangos puntuales o `grep`.
- **Confirmá siempre con grep sobre el código real antes de afirmar nada.**
- **Si el mapa contradice al código, GANA EL CÓDIGO.**
- `audit/_listas/` tiene archivos chicos y autocontenidos (hallazgos, divergencias, zonas grises):
  buen punto de partida.

## Qué NO auditás

- **Cálculos.** Ya se auditaron en las tandas 1A y 1B (`audit/01-calculos.md`). Tu área es
  seguridad. Si un cálculo está mal pero no tiene consecuencia de seguridad, no es tuyo.
- El Paso 0 (la `SECRET_KEY` hardcodeada y que en prod es una API key de Anthropic) **ya está
  hecho**: `audit/05_seguridad/5a-paso0-secret-key.md`. No lo repitas; citalo si hace falta.

## Regla de los PARCHES

Si encontrás código que corrige un síntoma en un lugar puntual en vez de la causa (un `if`
especial, un valor hardcodeado, un `try/except` que tapa el error), marcalo como **PARCHE**, decí
cuál es la causa real y dónde más sigue viva.

**Distinguí un parche de una decisión deliberada**: si hay un comentario que la justifica, leelo
antes de reportarla como bug. En la tanda 1A, uno de los tres puntos críticos resultó ser diseño
intencional documentado.

## Regla de propagación

La causa raíz más frecuente de este proyecto (28+ hallazgos auditados) es un fix correcto aplicado
en un solo lugar y no propagado al resto de los call sites. Cuando encuentres un patrón inseguro,
**buscá con grep TODOS los lugares donde vive el mismo patrón y listalos**. Un hallazgo que cubre
1 de N call sites está a medias.

## Cruce con la tanda de fixes F1

Corre en paralelo otra sesión que modifica el repo. A vos no te afecta (auditás la copia
congelada), pero si un hallazgo tuyo cae en alguno de estos, marcalo con
**"⚠️ posible cruce con F1"**: `snapshots_job.py`, el persister de FX, `reconcile-cash`,
`CashFlowIn`, el recalc de P&L, la amortización manual, `SellModal` / `PositionsMobile`.

## Formato del informe

```markdown
# <título>
## Método
(qué ejecutaste, qué no, con qué supuestos)
## Resumen — hallazgos por severidad
(tabla: id | severidad | título | archivo:línea | evidencia)
## Hallazgos
### [CRÍTICO|ALTO|MEDIO|BAJO] H-n · <título>
**Evidencia:** MEDIDO | DEDUCIDO | ESTRUCTURAL
**Dónde:** `archivo:línea`
**Qué pasa:** ...
**Cómo se explota en la práctica:** ...
**Qué queda expuesto:** ...
**Otros call sites del mismo patrón:** ...
**Solución de fondo:** ...
## Lo que NO pude verificar (dicho explícitamente)
```

Severidad: **CRÍTICO** = un usuario cualquiera llega a datos de otro, o a admin. **ALTO** = hace
falta una condición extra (una fuga, un rol). **MEDIO** = defensa en profundidad ausente.
**BAJO** = higiene.
