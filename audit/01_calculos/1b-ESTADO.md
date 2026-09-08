# Tanda 1B — estado

**Objetivo:** auditoría transversal de cálculo, 6 temas.
**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` · copia limpia `/tmp/rendi-main` (1.126 archivos, `main.py` = 38.029 líneas).

## Chequeos previos al lanzamiento

| chequeo | resultado |
|---|---|
| Copia limpia íntegra | ⚠️ **estaba contaminada** — la recreé. Ver abajo |
| `origin/main` | `82fad6a0` (+1, FCI Ualá) — sin cambios desde 1A |
| Rama `fix/snapshots-valuacion` | **existe y está checkouteada, pero sin ningún commit ni cambio sin commitear sobre `backend/snapshots_job.py`**. Hoy no hay nada nuevo contra qué comparar |
| Working tree | los mismos 4 archivos modificados de siempre; ningún código tocado por la auditoría |

### La copia limpia estaba contaminada — por mí

Al ejecutar el repro de A-1/A-2/A-3 en la sesión anterior, `import snapshots_job` arrastró `import main`, que **crea `trading.db` en el árbol**. La copia quedó con 1.129 archivos en vez de 1.126: `trading.db`, `trading.db-wal`, `trading.db-shm`.

No afectó ningún hallazgo (son archivos nuevos, no modificaciones del código auditado) ni tocó el repo. Pero rompía la premisa de "copia de solo lectura", así que la recreé desde cero y verifiqué 1.126 / 38.029.

**Consecuencia operativa, ya incorporada al prompt de los 6 agentes:** quien necesite ejecutar Python que importe `main` debe copiar lo que precise a un directorio propio. Nadie escribe dentro de `/tmp/rendi-main`.

## Los 6 temas

| # | tema | archivo | preguntas pre-filtradas | nota |
|---|---|---|---|---|
| 1 | Decimales y precisión | `1b-decimales.md` | 16 | — |
| 2 | Monedas y cotizaciones | `1b-monedas.md` | 57 | mayor solape con 1A (`1a-fx.md`) |
| 3 | Fechas, períodos y zonas horarias | `1b-fechas.md` | 113 | filtro ancho, con ruido |
| 4 | Inflación, UVA y CER | `1b-inflacion.md` | 11 | **concepto sin mapear**: hay que mapearlo y auditarlo a la vez |
| 5 | Benchmarks y objetivos | `1b-benchmarks.md` | 29 | **conceptos sin mapear**, ídem |
| 6 | Casos borde | `1b-borde.md` | 49 | el más apto para MEDIR |

Las preguntas están partidas en `audit/01_calculos/_preguntas/<tema>.md` por palabra clave. **Es un filtro automático, no curado**: trae ruido y puede faltar alguna. Cada agente elige sólo las bloqueantes.

## Reglas vigentes

- **No se modifica código.** Única carpeta escribible: `audit/`.
- Cada agente escribe su archivo **antes** de responder.
- **Etiqueta de evidencia obligatoria** en toda magnitud: MEDIDO (con traza pegada) / DEDUCIDO (con supuestos) / ESTRUCTURAL. Prohibido decir "medido" sin haber ejecutado.
- Cada informe abre con un bloque `## Método`.
- Verificación de citas integrada, **sin fase separada**. Gana el código.
- Parches marcados con causa real y dónde más rompe — **distinguiendo parche de decisión de diseño documentada**.
- Nadie lee `00-mapa-sistema.md` entero.

## Antecedente de 1A que condiciona 1B

En 1A, de 8 agentes **sólo 1 ejecutó código**; los otros 7 usaron "medido" para aritmética a mano, y yo lo repetí sin verificar. De ahí sale la etiqueta de evidencia obligatoria de esta tanda. El agente que ejecutó (costo/FIFO) fue el que más valor produjo, y por eso a los temas 3 y 6 se les pidió explícitamente que midan.
