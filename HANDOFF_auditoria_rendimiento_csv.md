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
- [x] Arnés que corre el camino de producción: `audit/rendimiento_csv/arnes.py` (HTTP
      `/api/imports/preview` → `/confirm` → post-proceso → reconstrucción a mercado en su hilo →
      cron real `take_snapshot_for_user` → `curva_indexada`/`rendimiento_publicable` en los dos modos).
      Mercado inventado en `mercado.py`. Correr: `python3 correr_reales.py <carpeta _datos> <salida>`.
- [x] Archivos reales (Balanz A, Balanz B, IEB) por el arnés (salidas fuera del repo).
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

3. **H1 · Los cobros bloquean la cobertura del Certero.** Dividendos/cupones/amortizaciones viven en
   `operations` (op_type 'Dividendo'/'Amortización'/'Interés') SIN `entry_date` ni `entry_price`.
   `backfill_historical_mtm._tenencia_no_vista` (loop de `operations`) los toma como "posición abierta
   no vista de valor desconocido" → `afirmable=False` → `mtm_coverage=None` → foto `costo`, `apto=0`
   para TODO mes anterior al cobro, cuando el cobro cae en otro broker (el sibling "· USD") o en un
   activo que todavía no se tenía. Medido con los archivos reales: Balanz A 40 de 51 meses perdidos
   (Certero sólo desde 2025-10), Balanz B 36 de 38, IEB 8 de 9. Contrafáctico en
   `arnes.contrafactico_sin_cobros`.
4. **H2 · El Certero es todo-o-nada ante un hueco.** `twr.curva_indexada`: `publicable =
   len(con_legs)==1 and not partida` (twr.py ~3252). Un solo mes con cobertura < 0,90 en cualquier
   punto de la historia → Certero sin número (`serie_partida`), aunque haya un tramo reciente
   continuo. El Estimado sí publica la ventana más reciente. ⚠️ Interacción: arreglar H1 SOLO le
   BORRA el número a Balanz A (sus meses 2024 tienen bonos/FCI al costo → hueco → `serie_partida`).
   H1 y H2 van juntos.
5. **H3 · Precio histórico que existe y no se usa.** `price_history.py` (tabla
   `asset_price_history`) no tiene ningún llamador de producción; `velas_diarias` (3 años de velas de
   lo que la gente tiene) tampoco lo lee la reconstrucción. Bonos/ONs/letras van SIEMPRE al costo en
   la reconstrucción (`_fetch_monthly_close` los saltea por "data912 es live-only"), y son los que
   bajan la cobertura bajo 0,90.

## Dónde está cada cosa en la rama

- `HANDOFF_auditoria_rendimiento_csv.md` — este archivo.
- `audit/rendimiento_csv/` — arnés, generadores de archivos y salidas (se agrega a medida que avanza).
