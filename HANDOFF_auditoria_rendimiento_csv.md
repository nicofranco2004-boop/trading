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
- [x] Archivos inventados (Balanz, IEB, genérico) × 6 escenarios de discrepancia: `correr_escenarios.py`
      (historia y verdad en `historia.py`, formatos en `generadores.py`). Falta: Cocos, IOL, PPI, Inviu, BMB.
- [x] Tabla parser × tipo de movimiento (`tabla_parsers.py`, por la vista previa HTTP).
- [x] Consistencia entre lectores (`lectores.py`).
- [x] Informe **`AUDIT_rendimiento_desde_csv_2026-10-27.md`** en la raíz de esta rama — es el entregable.
- [ ] **Pendiente para tu Mac:** correr `medir_prod.py` contra la copia de prod (ver §7 del informe) y
      completar los conteos "por medir". Y las pruebas de punta a punta de Cocos/IOL/PPI/Inviu/BMB (§6).

## Hallazgos (el detalle y los números finales están en el informe)

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

6. **H4 · El Estimado tira la contabilidad posterior a CUALQUIER foto apta.** `twr.py` ~2483
   `_primer_apto` toma la primera foto apta, incluida una RECONSTRUIDA; el comentario dice "la
   contabilidad se apaga en la primera MEDICIÓN REAL". Con un primer mes 100 % valuado (antes de
   comprar bonos), 30 fotos contables posteriores se descartan: Estimado 135 % (2,75 años) → 25 %
   (3 meses). Hoy no se ve porque H1 lo tapa.
7. **H5 · La costura reconstrucción→cron fabrica ganancia con export parcial.** Con el export desde
   2025 (escenario S1), una VENTA sin su compra mete efectivo en `positions` pero no en
   `capital_final`; la foto reconstruida vale contabilidad+no realizado (2.777) y el cron vale
   posiciones (22.030). La guarda `twr.costura_no_cierra` mide `v1/(v0+flujo)` = 1,21 < 1,25: el
   aporte de la siembra de la foto la diluye. Resultado: Certero +70,6 % vs verdad +25,5 % (Balanz).
8. **H6 · `base='costo'` mezcla dos reglas.** `twr.base_de`: RECONSTRUIDO con cobertura < 0,90 →
   'costo', pero su `total_value` (backfill_user: `new_cf = cost + total_unreal`) incluye el no
   realizado de lo que tuvo precio. El Estimado encadena por base → un leg contable→casi-mercado
   asienta años de no realizado de golpe (IEB S0: +36 % en un trimestre). El Estimado NO es
   "sin no realizado": da 123–135 % con verdad contable 21,7 % y TWR real 141,3 %.
9. **H7 · `rendimiento_publicable(modo='certero')` devuelve un número contable** cuando el motor no
   mide (S0 antes del cron: 32,06 % base 'contable'). Los lectores que lo usan (Wrapped, IA,
   reportes) muestran un contable en modo Certero.
10. **IEB: dividendos en dólares como pesos.** Divisa 'OTHER' en la columna "Importe ARS" →
   DIVIDEND ARS 0,27 (era US$0,27). Real: 22 filas, US$26,93. Después la foto lo "arregla" con un
   DEPÓSITO de caja (aporte, no renta).

### Matriz de escenarios (Certero / Estimado, verdad TWR 141,3 % y contable 21,7 % en S0)

| escenario | Balanz | IEB |
|---|---|---|
| S0 completo | 25,2✔(sólo cron) / 135,5 | 25,2✔ / 123,5 |
| S1 export desde 2025 | **70,6 vs 25,5** / 82,4 | sin número / 25,2 |
| S2 falta una venta | 25,2✔ / **166,6** | 25,2✔ / 147,6 |
| S3 títulos de otro broker | 24,7✔ / 134,5 (v 137,6) | 24,7✔ / 122,5 |
| S4 faltan cupones | 25,2✔ / 125,3 | 25,2✔ / 125,4 |
| S5 movimientos post-foto | 18,9 (v 19,5) / 131,3 | 18,9 / 119,5 |

## Dónde está cada cosa en la rama

- `HANDOFF_auditoria_rendimiento_csv.md` — este archivo.
- `audit/rendimiento_csv/` — arnés, generadores de archivos y salidas (se agrega a medida que avanza).
