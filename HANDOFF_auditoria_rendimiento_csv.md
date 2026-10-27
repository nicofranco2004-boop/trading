# Handoff — Auditoría "rendimiento CERTERO y ESTIMADO desde el CSV" (2026-10-27)

> Si esta sesión de la nube se cortó, seguí desde acá en tu Mac. Todo lo hecho está en la
> rama **`claude/modest-mccarthy-4nsncl`** (no en `main`). Este archivo se actualiza en cada
> avance; la última versión es la de la punta de esa rama.

## Cómo retomarlo en tu Mac

```bash
cd ~/Documents/trading
git fetch origin claude/modest-mccarthy-4nsncl
git worktree add .claude/worktrees/audit-csv origin/claude/modest-mccarthy-4nsncl
cd .claude/worktrees/audit-csv
```

Y en un chat nuevo de Claude Code pegá: *"Seguí la auditoría de `HANDOFF_auditoria_rendimiento_csv.md`.
El prompt original es el de la auditoría del rendimiento desde el CSV. La copia de prod está en
`~/Downloads/<la más nueva>.db` — abrila con `?immutable=1`."*

**Archivos reales que subiste** (NO están en el repo: son datos personales). Están en tu
computadora; ponelos en `.claude/worktrees/audit-csv/_datos/` (carpeta ignorada) con estos nombres:

| archivo original | nombre en `_datos/` |
|---|---|
| `movimientos_balanz.xlsx` | `balanzA/movimientos_balanz.xlsx` |
| `Movimientos_Facu_Balanz.xlsx` | `balanzB/movimientos_balanzB.xlsx` |
| `IEB-2026-08-03-Portafolio-356811-ARS.xlsx` | `ieb/portafolio.xlsx` |
| `IEB-2026-08-03-toda-la-actividad-356811.xlsx` | `ieb/actividad.xlsx` |

## Estado (se va actualizando)

- [x] Entorno: la nube NO tiene la copia de prod ni acceso de red a Yahoo / data912 /
      argentinadatos (el proxy los bloquea, 403). Por eso el arnés usa un **mercado sintético**
      (precios y dólar conocidos) → se sabe el rendimiento VERDADERO y se mide el error exacto.
- [ ] Arnés que corre el camino de producción (HTTP `/api/imports/preview` → `/confirm` →
      post-proceso → reconstrucción a mercado → `estampar_base` → `curva_indexada` en los dos modos).
- [ ] Archivos reales (Balanz A, Balanz B, IEB) por el arnés.
- [ ] Archivos inventados por broker: movimientos + foto de tenencia, con y sin discrepancias.
- [ ] Tabla parser × tipo de movimiento.
- [ ] Consistencia entre lectores.
- [ ] Informe `AUDIT_rendimiento_desde_csv_2026-10-27.md`.

## Hallazgos preliminares (sin cuantificar todavía)

1. **El Certero de producción no usa `ledger_replay`.** `ledger_replay.tenencia_en/cash_en/valor_en`
   no tiene ningún llamador fuera de `tests/` (`grep -rn "import ledger_replay" backend --include=*.py`
   → sólo un comentario en `importing/proyeccion.py:12`). La reconstrucción a mercado usa su propia
   copia: `scripts/backfill_historical_mtm.py:307` `_holdings_asof` (BUY−SELL de
   `import_normalized_tx`, costo PROMEDIO de todas las compras). Dos implementaciones de "qué tenía
   en tal fecha" → regla de propagación. Falta medir si dan distinto.
2. **`diagnostico.py`, `censo_flujos.py`, `censo_capital.py` no existen en `main`** — viven en la
   rama `feat/reconstructor-f1`, que nunca se mergeó. Lo que el HANDOFF_reconstructor da por
   construido no está en producción.

## Dónde está cada cosa en la rama

- `HANDOFF_auditoria_rendimiento_csv.md` — este archivo.
- `audit/rendimiento_csv/` — arnés, generadores de archivos y salidas (se agrega a medida que avanza).
