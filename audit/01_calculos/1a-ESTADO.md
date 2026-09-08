# Tanda 1A — estado

**Objetivo:** veredicto sobre las 166 implementaciones divergentes de `audit/_listas/divergencias.md`.
**Commit auditado:** `b74f450f2badf1a2b84e657551115a0595110e45` (copia limpia en `/tmp/rendi-main`, 1.126 archivos, `backend/main.py` = 38.029 líneas).
**Deriva:** `origin/main` = `82fad6a0` (+1 commit, FCI Ualá). Sólo toca `backend/pricing/fci.py`, `frontend/src/components/AddPositionFlow.jsx`, `backend/tests/test_fci_uala.py`.

## Agrupación

Las 166 divergencias se repartieron en los **16 conceptos de negocio** que ya traía el mapeo.
Los archivos de input por grupo están en `audit/01_calculos/_grupos/<slug>.md` (extraídos literalmente de la lista original, sin reinterpretar).

| # | concepto | slug | divergencias | IDs | tanda |
|---|---|---|---:|---|---|
| 1 | Valuación de cartera / valor de mercado | `valuacion` | 15 | DIV-145–159 | **1A** |
| 2 | Tenencia / posición / holding | `tenencia` | 13 | DIV-121–133 | **1A** |
| 3 | Costo de adquisición, costo promedio y lotes FIFO | `costo-fifo` | 13 | DIV-050–062 | **1A** |
| 4 | Capital aportado, flujos, depósitos y retiros | `capital-aportado` | 13 | DIV-029–041 | **1A** |
| 5 | Tipo de cambio (blue, MEP, CCL, cripto) | `fx` | 11 | DIV-134–144 | **1A** |
| 6 | P&L realizado | `pnl-realizado` | 11 | DIV-081–091 | **1A** |
| 7 | P&L no realizado / ganancia latente | `pnl-no-realizado` | 9 | DIV-072–080 | **1A** |
| 8 | Rendimiento / retorno (simple, TWR, anualizado, CAGR) | `rendimiento` | 9 | DIV-092–100 | **1A** |
| 9 | Bonos: escala per-100, paridad, vencimiento y flujos | `bonos` | 13 | DIV-001–013 | 1B |
| 10 | Snapshot / foto histórica de la cartera | `snapshot` | 11 | DIV-101–111 | 1B |
| 11 | TIR / IRR / XIRR / retorno ponderado por dinero | `tir` | 9 | DIV-112–120 | 1B |
| 12 | Dividendos, cupones, rentas y amortizaciones | `dividendos` | 9 | DIV-063–071 | 1B |
| 13 | Comisiones, impuestos y costos de transacción | `comisiones` | 8 | DIV-042–049 | 1B |
| 14 | CEDEAR: ratio, split, valuación y pata en dólares | `cedear` | 8 | DIV-014–021 | 1B |
| 15 | Variación diaria / periódica y evolución | `variacion` | 7 | DIV-160–166 | 1B |
| 16 | Caja / cash / saldo disponible | `caja` | 7 | DIV-022–028 | 1B |

**1A: 8 grupos, 94 divergencias. 1B pendiente: 8 grupos, 72 divergencias.**

## Criterio de priorización

La tanda 1A cubre **la cadena completa del número que el usuario ve en la pantalla principal**, en orden de dependencia:

```
tenencia (cantidad) → costo/FIFO → valuación → P&L no realizado
                                             → P&L realizado
                    capital aportado (denominador) → rendimiento
                    FX (multiplica todo lo anterior)
```

Si un eslabón de esa cadena está roto, todo lo que viene después muestra mal aunque su propio cálculo sea correcto. Por eso van juntos: los veredictos se cruzan entre sí.

Los 8 grupos de 1B son o bien **clases de activo específicas** (bonos, CEDEAR), o bien **vistas derivadas** que se apoyan en la cadena de 1A (snapshot, variación, TIR) — auditarlos antes de saber cuál es la fórmula correcta de la cadena habría producido veredictos que después hay que rehacer.

## Salidas esperadas de 1A

- `audit/01_calculos/1a-valuacion.md`
- `audit/01_calculos/1a-tenencia.md`
- `audit/01_calculos/1a-costo-fifo.md`
- `audit/01_calculos/1a-capital-aportado.md`
- `audit/01_calculos/1a-fx.md`
- `audit/01_calculos/1a-pnl-realizado.md`
- `audit/01_calculos/1a-pnl-no-realizado.md`
- `audit/01_calculos/1a-rendimiento.md`
- `audit/01_calculos/1a-resumen.md` (ensamblado por el orquestador con `cat`, no con un agente)

## Reglas vigentes en esta tanda

- **No se modifica código.** Única carpeta escribible: `audit/`.
- Cada agente **escribe su archivo a disco antes de responder**.
- Cada agente **verifica sus propias citas** contra el código real: el mapa es hipótesis, gana el código.
- Verificación integrada, **sin fase separada** de re-lectura.
- Los parches (fix del síntoma en un solo lugar) se marcan explícitamente, con causa real y dónde más sigue rompiendo.
